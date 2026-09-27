#nullable enable
using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using static Physio.Replay.ReplayJson;

namespace Physio.Workflow
{
    public sealed class ProcessingException : Exception
    {
        public string Code { get; }
        public bool Retryable { get; }
        public ProcessingException(string code, string message, bool retryable) : base(message) { Code = code; Retryable = retryable; }
    }

    /// <summary>One explicit processing operation at a time. Authentication is kept only in memory.</summary>
    public sealed class ProcessingClient : IDisposable
    {
        private readonly LocalPatientStore store;
        private readonly HttpClient http;
        private readonly string token;
        private int active;
        public ProcessingClient(LocalPatientStore store, Uri endpoint, string bearerToken, bool allowLoopbackHttp = false)
            : this(store, endpoint, bearerToken, new HttpClientHandler { AllowAutoRedirect = false }, allowLoopbackHttp) { }
        // Injectable HTTP transport permits deterministic upload/poll/restart checks without a live service.
        public ProcessingClient(LocalPatientStore store, Uri endpoint, string bearerToken, HttpMessageHandler transport, bool allowLoopbackHttp = false)
        {
            ValidateEndpoint(endpoint, allowLoopbackHttp);
            Require(!string.IsNullOrWhiteSpace(bearerToken) && bearerToken.Length <= 4096 && !bearerToken.Any(char.IsControl), "Enter a valid deployment token.");
            this.store = store; token = bearerToken;
            http = new HttpClient(transport) { BaseAddress = new Uri(endpoint.AbsoluteUri.TrimEnd('/') + "/"), Timeout = Timeout.InfiniteTimeSpan };
        }
        public static void ValidateEndpoint(Uri endpoint, bool allowLoopbackHttp = false)
        {
            Require(endpoint != null && endpoint.IsAbsoluteUri && string.IsNullOrEmpty(endpoint.UserInfo) && string.IsNullOrEmpty(endpoint.Query) && string.IsNullOrEmpty(endpoint.Fragment), "Server URL must be absolute and contain no credentials, query or fragment.");
            if (endpoint == null) throw new ArgumentNullException(nameof(endpoint));
            var loopback = endpoint.IsLoopback && (endpoint.Host == "localhost" || IPAddress.TryParse(endpoint.Host.Trim('[', ']'), out var address) && IPAddress.IsLoopback(address));
            Require(endpoint.Scheme == "https" || allowLoopbackHttp && endpoint.Scheme == "http" && loopback, "Use HTTPS. HTTP is allowed only for explicitly enabled local development.");
            Require(endpoint.AbsolutePath == "/", "Server URL must identify the service origin, without an API path.");
        }
        public async Task<CachedResult> ProcessAsync(Guid patientId, Guid sessionId, Action<ProcessingUpdate>? progress = null,
            CancellationToken cancellation = default, bool reprocess = false)
        {
            if (Interlocked.CompareExchange(ref active, 1, 0) != 0) throw new InvalidOperationException("A processing request is already active.");
            SessionRecord? session = null;
            try
            {
                session = store.Session(patientId, sessionId);
                if (reprocess) session = store.Reprocess(session);
                else if (session.ResultId.HasValue) return store.OpenResult(patientId, sessionId);
                var capture = store.Capture(session); var completed = WorkflowJson.Date(capture["capture_completed_at"]);
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation); deadline.CancelAfter(TimeSpan.FromMinutes(15));
                var ct = deadline.Token;
                JObject job;
                if (session.JobId.HasValue) job = await JsonRequest(() => Request(HttpMethod.Get, "v1/jobs/" + session.JobId), ct);
                else
                {
                    session = store.SetState(session, "uploading", "uploading"); progress?.Invoke(new ProcessingUpdate("uploading", "Uploading saved recording", completed));
                    job = await JsonRequest(() => Upload(session, capture), ct, 120);
                }
                while (true)
                {
                    WorkflowValidation.Job(job, session); session = store.SaveJob(session, job);
                    progress?.Invoke(new ProcessingUpdate(session.Stage, session.Status, completed, job["progress"] as JObject));
                    if (session.Status == "failed")
                        throw new ProcessingException((string)job["error"]!["code"]!, (string)job["error"]!["message"]!, (bool)job["error"]!["retryable"]!);
                    if (session.Status == "succeeded") break;
                    await Task.Delay(TimeSpan.FromSeconds(lastRetryAfter), ct);
                    job = await JsonRequest(() => Request(HttpMethod.Get, "v1/jobs/" + session.JobId), ct);
                }
                var resultId = WorkflowJson.Id(job["result_id"]);
                session = store.SetState(session, "downloading", "downloading"); progress?.Invoke(new ProcessingUpdate("downloading", "Downloading and checking result", completed));
                var manifest = await JsonRequest(() => Request(HttpMethod.Get, "v1/jobs/" + session.JobId + "/result"), ct);
                WorkflowValidation.Result(manifest, session, capture, store, resultId);
                await CacheResult(session, manifest, ct);
                progress?.Invoke(new ProcessingUpdate("loading", "Loading verified replay", completed));
                var result = store.OpenResult(patientId, sessionId, resultId);
                store.Cached(session, resultId);
                progress?.Invoke(new ProcessingUpdate("complete", "Result saved", completed)); return result;
            }
            catch (OperationCanceledException)
            {
                if (session != null) store.SetState(session, "paused", session.Stage, "Processing wait stopped. Retry resumes the same saved job and recording.");
                throw;
            }
            catch (ProcessingException exception)
            {
                var saved = store.Session(patientId, sessionId);
                store.SetState(saved, saved.Status == "failed" ? "failed" : "retry_required", saved.Stage, exception.Message); throw;
            }
            catch (Exception exception) when (exception is HttpRequestException || exception is IOException || exception is InvalidDataException || exception is Newtonsoft.Json.JsonException)
            {
                var saved = store.Session(patientId, sessionId);
                store.SetState(saved, "retry_required", saved.Stage, "Connection or result validation failed. Saved recordings were retained.");
                throw new ProcessingException("CLIENT_VALIDATION_OR_TRANSFER", "Connection or result validation failed. Saved recordings were retained; check the service and retry.", true);
            }
            finally { Interlocked.Exchange(ref active, 0); }
        }
        private int lastRetryAfter = 2;
        private HttpRequestMessage Request(HttpMethod method, string path)
        {
            var request = new HttpRequestMessage(method, path);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token); return request;
        }
        private HttpRequestMessage Upload(SessionRecord session, JObject capture)
        {
            var request = Request(HttpMethod.Post, "v1/jobs");
            request.Headers.Add("Idempotency-Key", session.IdempotencyKey.ToString("D"));
            var multipart = new MultipartFormDataContent();
            multipart.Add(new StringContent(capture.ToString(Newtonsoft.Json.Formatting.None), Encoding.UTF8, "text/plain"), "manifest");
            var media = new StreamContent(File.OpenRead(store.UploadPath(session))); media.Headers.ContentType = new MediaTypeHeaderValue("application/zip");
            multipart.Add(media, "media", "capture.zip"); request.Content = multipart; return request;
        }
        private async Task<JObject> JsonRequest(Func<HttpRequestMessage> createRequest, CancellationToken cancellation, int timeoutSeconds = 30)
        {
            using var response = await Send(createRequest, cancellation, timeoutSeconds);
            var bytes = await ReadBounded(response.Content, WorkflowJson.JsonLimit, cancellation);
            var value = WorkflowJson.Read(bytes);
            if (!response.IsSuccessStatusCode)
            {
                WorkflowJson.Fields(value, "error request_id"); WorkflowJson.Id(value["request_id"]); WorkflowValidation.Error((JObject)value["error"]!);
                throw new ProcessingException((string)value["error"]!["code"]!, (string)value["error"]!["message"]!, (bool)value["error"]!["retryable"]!);
            }
            return value;
        }
        private async Task<HttpResponseMessage> Send(Func<HttpRequestMessage> createRequest, CancellationToken cancellation, int timeoutSeconds)
        {
            for (var attempt = 0; ; attempt++)
            {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation); timeout.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
                try
                {
                    using var request = createRequest();
                    var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
                    var suggested = response.Headers.RetryAfter?.Delta?.TotalSeconds ?? 2;
                    lastRetryAfter = (int)Math.Max(1, Math.Min(30, suggested));
                    var transient = response.StatusCode == (HttpStatusCode)429 || (int)response.StatusCode >= 500;
                    if (!transient || attempt == 2) return response;
                    response.Dispose();
                }
                catch (HttpRequestException) when (attempt < 2) { }
                catch (OperationCanceledException) when (!cancellation.IsCancellationRequested && attempt < 2) { }
                await Task.Delay(TimeSpan.FromSeconds(Math.Max(lastRetryAfter, Math.Pow(2, attempt))), cancellation);
            }
        }
        private async Task CacheResult(SessionRecord session, JObject manifest, CancellationToken cancellation)
        {
            var resultId = WorkflowJson.Id(manifest["result_id"]); var target = store.ResultDirectory(session, resultId);
            if (Directory.Exists(target)) { store.OpenResult(session.PatientId, session.Id, resultId); return; }
            var artifacts = (JArray)manifest["artifacts"]!;
            var staging = target + ".pending"; if (Directory.Exists(staging)) Directory.Delete(staging, true);
            store.Reserve(artifacts.Sum(a => WorkflowJson.Size(a["byte_size"])) + WorkflowJson.Bytes(manifest).Length * 2L);
            Directory.CreateDirectory(staging);
            try
            {
                foreach (var tokenArtifact in artifacts)
                {
                    var artifact = (JObject)tokenArtifact; var id = WorkflowJson.Id(artifact["artifact_id"]);
                    using var response = await Send(() => Request(HttpMethod.Get, "v1/jobs/" + session.JobId + "/artifacts/" + id), cancellation, 120);
                    if (!response.IsSuccessStatusCode) throw new ProcessingException("ARTIFACT_DOWNLOAD_FAILED", "An artifact could not be downloaded. Retry keeps the same result.", true);
                    var size = WorkflowJson.Size(artifact["byte_size"]);
                    Require(!response.Content.Headers.ContentLength.HasValue || response.Content.Headers.ContentLength == size, "Download size differs from result.");
                    Require(response.Content.Headers.ContentType?.MediaType == (string?)artifact["media_type"], "Download content type differs from result.");
                    if (response.Headers.TryGetValues("X-Content-SHA256", out var hashes)) Require(hashes.SingleOrDefault() == (string?)artifact["sha256"], "Download hash header differs from result.");
                    var file = Path.Combine(staging, id.ToString("D"));
                    using (var output = new FileStream(file, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    using (var input = await response.Content.ReadAsStreamAsync())
                    {
                        var buffer = new byte[65536]; long received = 0; int count;
                        while ((count = await input.ReadAsync(buffer, 0, buffer.Length, cancellation)) > 0)
                        { received += count; Require(received <= size, "Download exceeded declared size."); await output.WriteAsync(buffer, 0, count, cancellation); }
                        Require(received == size, "Download was incomplete."); output.Flush(true);
                    }
                    LocalPatientStore.VerifyFile(file, artifact);
                    if ((string?)artifact["media_type"] == "application/json") WorkflowJson.Read(File.ReadAllBytes(file));
                    if ((string?)artifact["media_type"] == "video/mp4")
                    { using var input = File.OpenRead(file); var signature = new byte[12]; Require(input.Read(signature, 0, 12) == 12 && Encoding.ASCII.GetString(signature, 4, 4) == "ftyp", "Invalid MP4 artifact signature."); }
                }
                WorkflowValidation.Replay(manifest, staging, session, store);
                LocalPatientStore.AtomicJson(Path.Combine(staging, "result.json"), manifest);
                Directory.Move(staging, target);
            }
            finally { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
        }
        private static async Task<byte[]> ReadBounded(HttpContent content, int limit, CancellationToken cancellation)
        {
            Require(!content.Headers.ContentLength.HasValue || content.Headers.ContentLength <= limit, "Response exceeds JSON limit.");
            using var input = await content.ReadAsStreamAsync(); using var output = new MemoryStream(); var buffer = new byte[65536]; int count;
            while ((count = await input.ReadAsync(buffer, 0, buffer.Length, cancellation)) > 0)
            { Require(output.Length + count <= limit, "Response exceeds JSON limit."); output.Write(buffer, 0, count); }
            return output.ToArray();
        }
        public void Dispose() => http.Dispose();
    }
}
