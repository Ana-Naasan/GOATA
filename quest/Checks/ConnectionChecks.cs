using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Physio.Workflow;

static class ConnectionChecks
{
    static int checks;
    static readonly string fixtureToken = Guid.NewGuid().ToString("N");
    static void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
    static void Reject(Action action, string name)
    { try { action(); } catch (InvalidDataException) { checks++; return; } throw new Exception(name); }
    static async Task RejectAsync(Func<Task> action, string name)
    { try { await action(); } catch (InvalidDataException) { checks++; return; } catch (ProcessingException) { checks++; return; } throw new Exception(name); }
    static async Task Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "physio-connection-" + Guid.NewGuid());
        Directory.CreateDirectory(root);
        try
        {
            var path = Path.Combine(root, ProcessingConnection.FileName);
            Check(ProcessingConnection.LoadOnce(root) == null, "Absent provisioning leaves manual setup available.");
            var json = "{\"endpoint\":\"https://127.0.0.1:8443\",\"bearer_token\":\"" + fixtureToken + "\",\"tls_leaf_sha256\":\"" + new string('A', 64) + "\"}";
            File.WriteAllText(path, json);
            var loaded = ProcessingConnection.LoadOnce(root)!;
            Check(loaded.Endpoint.Host == "127.0.0.1" && loaded.BearerToken == fixtureToken && loaded.LeafSha256 == new string('a', 64), "Bounded provisioning validates and normalizes.");
            Check(!File.Exists(path) && ProcessingConnection.LoadOnce(root) == null, "Credentials consumed once and deleted.");
            foreach (var invalid in new[] { "{}", json.Replace("https:", "http:"), json.Replace(fixtureToken, ""), json.Replace(fixtureToken, "bad\\ntoken"), json.Replace(new string('A', 64), "bad-pin"), json.Replace("\"endpoint\":", "\"unknown\":"), json.Replace("{", "{\"endpoint\":\"https://evil.test\","), json + "trailing", new string('x', ProcessingConnection.MaxBytes + 1) })
            {
                File.WriteAllText(path, invalid);
                Reject(() => ProcessingConnection.LoadOnce(root), "Malformed provisioning rejected.");
                Check(!File.Exists(path), "Rejected secret file is also removed.");
            }
            File.WriteAllText(path, "{\"endpoint\":\"https://example.test\",\"bearer_token\":\"" + fixtureToken + "\"}");
            Check(ProcessingConnection.LoadOnce(root)!.LeafSha256 == "", "Pin is optional.");
            using (var defaultHandler = ProcessingConnection.CreateHandler(""))
                Check(defaultHandler.ServerCertificateCustomValidationCallback == null && !defaultHandler.AllowAutoRedirect, "Default CA and host validation preserved; redirects disabled.");
            Reject(() => ProcessingConnection.CreateHandler("no"), "Malformed manual pin rejected before networking.");
            using var rsa = RSA.Create(2048);
            var request = new CertificateRequest("CN=127.0.0.1", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
            var san = new SubjectAlternativeNameBuilder(); san.AddIpAddress(IPAddress.Loopback); request.CertificateExtensions.Add(san.Build());
            request.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, true));
            request.CertificateExtensions.Add(new X509KeyUsageExtension(X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, true));
            request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(new OidCollection { new Oid("1.3.6.1.5.5.7.3.1") }, true));
            using var cert = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-1), DateTimeOffset.UtcNow.AddDays(1));
            var pin = Convert.ToHexString(SHA256.HashData(cert.RawData));
            using var chain = new X509Chain(); chain.Build(cert);
            using var handler = ProcessingConnection.CreateHandler(pin);
            using var message = new HttpRequestMessage(HttpMethod.Get, "https://127.0.0.1:8443/");
            var validate = handler.ServerCertificateCustomValidationCallback!;
            Check(validate(message, cert, chain, SslPolicyErrors.RemoteCertificateChainErrors), "Matching untrusted leaf accepted by explicit pin.");
            Check(validate(message, cert, chain, SslPolicyErrors.None), "Matching otherwise trusted leaf accepted.");
            Check(!validate(message, cert, chain, SslPolicyErrors.RemoteCertificateNameMismatch), "Hostname mismatch rejected despite matching pin.");
            Check(!validate(message, null, chain, SslPolicyErrors.RemoteCertificateNotAvailable), "Missing leaf rejected.");
            Check(!validate(message, cert, null, SslPolicyErrors.RemoteCertificateChainErrors), "Missing chain rejected.");
            using var wrongHandler = ProcessingConnection.CreateHandler(new string('0', 64));
            Check(!wrongHandler.ServerCertificateCustomValidationCallback!(message, cert, chain, SslPolicyErrors.None), "Wrong pin rejected even for valid CA certificate.");
            using var expired = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-2), DateTimeOffset.UtcNow.AddDays(-1));
            using var expiredHandler = ProcessingConnection.CreateHandler(Convert.ToHexString(SHA256.HashData(expired.RawData)));
            Check(!expiredHandler.ServerCertificateCustomValidationCallback!(message, expired, chain, SslPolicyErrors.None), "Expired pinned certificate rejected.");
            using var future = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(1), DateTimeOffset.UtcNow.AddDays(2));
            using var futureHandler = ProcessingConnection.CreateHandler(Convert.ToHexString(SHA256.HashData(future.RawData)));
            Check(!futureHandler.ServerCertificateCustomValidationCallback!(message, future, chain, SslPolicyErrors.None), "Not-yet-valid pinned certificate rejected.");
            Check(await TlsRoundTrip(cert, pin, "127.0.0.1"), "Real TLS handshake accepts only explicitly pinned private certificate.");
            Check(!await TlsRoundTrip(cert, "", "127.0.0.1"), "Real default TLS rejects untrusted private certificate.");
            Check(!await TlsRoundTrip(cert, new string('0', 64), "127.0.0.1"), "Real TLS rejects wrong leaf pin.");
            Check(!await TlsRoundTrip(cert, pin, "localhost"), "Real TLS rejects wrong hostname despite matching pin.");
            Check(!await TlsRoundTrip(expired, Convert.ToHexString(SHA256.HashData(expired.RawData)), "127.0.0.1"), "Real TLS rejects expired pinned certificate.");
            var store = new LocalPatientStore(Path.Combine(root, "patients"));
            using (var client = new ProcessingClient(store, new Uri("https://example.test"), fixtureToken, new ProbeTransport(HttpStatusCode.NotFound, "NOT_FOUND")))
                await client.CheckConnectionAsync();
            Check(true, "Read-only probe verifies auth and contract without a capture.");
            foreach (var response in new[] { (HttpStatusCode.Unauthorized, "UNAUTHORIZED"), (HttpStatusCode.NotFound, "OTHER"), (HttpStatusCode.OK, "NOT_FOUND") })
            {
                using var client = new ProcessingClient(store, new Uri("https://example.test"), fixtureToken, new ProbeTransport(response.Item1, response.Item2));
                await RejectAsync(() => client.CheckConnectionAsync(), "Auth failures and unexpected probe responses rejected.");
            }
            Console.WriteLine($"Connection checks: {checks} passed.");
        }
        finally { Directory.Delete(root, true); }
    }
    static async Task<bool> TlsRoundTrip(X509Certificate2 certificate, string pin, string host)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serve = Task.Run(async () =>
        {
            try
            {
                using var socket = await listener.AcceptTcpClientAsync(deadline.Token);
                using var tls = new SslStream(socket.GetStream());
                await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions { ServerCertificate = certificate }, deadline.Token);
                using var reader = new StreamReader(tls, Encoding.ASCII, false, 1024, true);
                while (!string.IsNullOrEmpty(await reader.ReadLineAsync(deadline.Token))) { }
                await tls.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"), deadline.Token);
            }
            catch (Exception exception) when (exception is IOException || exception is AuthenticationException || exception is OperationCanceledException) { }
        });
        try
        {
            using var client = new HttpClient(ProcessingConnection.CreateHandler(pin));
            using var response = await client.GetAsync($"https://{host}:{((IPEndPoint)listener.LocalEndpoint).Port}/", deadline.Token);
            return response.StatusCode == HttpStatusCode.NotFound;
        }
        catch (HttpRequestException) { return false; }
        finally { deadline.Cancel(); listener.Stop(); await serve; }
    }
    sealed class ProbeTransport(HttpStatusCode status, string code) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellation)
        {
            Check(request.Method == HttpMethod.Get && request.Content == null && request.RequestUri!.AbsolutePath.StartsWith("/v1/jobs/") && Guid.TryParse(request.RequestUri.Segments[^1], out _), "Probe cannot upload or create a job.");
            Check(request.Headers.Authorization?.ToString() == "Bearer " + fixtureToken, "Probe requires configured auth.");
            return Task.FromResult(new HttpResponseMessage(status) { Content = new StringContent("{\"error\":{\"code\":\"" + code + "\",\"message\":\"Probe response\",\"retryable\":false},\"request_id\":\"" + Guid.NewGuid() + "\"}", Encoding.UTF8, "application/json") });
        }
    }
}
