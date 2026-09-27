#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using Newtonsoft.Json.Linq;
using static Physio.Replay.ReplayJson;

namespace Physio.Workflow
{
    /// <summary>App-private patient records. IDs, never names, select histories and paths.</summary>
    public sealed partial class LocalPatientStore
    {
        private readonly string root;
        private readonly object gate = new object();
        public const long StorageLimit = 4L * 1024 * 1024 * 1024;
        public IReadOnlyList<string> RecoveryWarnings => warnings.ToArray();
        private readonly List<string> warnings = new List<string>();
        public LocalPatientStore(string directory)
        {
            root = Path.GetFullPath(directory ?? throw new ArgumentNullException(nameof(directory)));
            Directory.CreateDirectory(Path.Combine(root, "patients"));
            Directory.CreateDirectory(Path.Combine(root, "sessions"));
        }
        public PatientRecord CreatePatient(string displayName)
        {
            var name = (displayName ?? "").Trim();
            Require(name.Length > 0 && name.Length <= 100 && !name.Any(char.IsControl), "Enter a patient name of 1–100 characters.");
            var data = new JObject { ["id"] = Guid.NewGuid().ToString("D"), ["display_name"] = name, ["created_at"] = Now() };
            var patient = new PatientRecord(data);
            lock (gate) { EnsureSpace(4096); AtomicJson(PatientPath(patient.Id), data); }
            return patient;
        }
        public IReadOnlyList<PatientRecord> Patients()
        {
            lock (gate)
            {
                return Directory.EnumerateFiles(Path.Combine(root, "patients"), "*.json")
                    .Select(path => new PatientRecord(ReadRecovered(path))).OrderBy(p => p.DisplayName, StringComparer.Ordinal)
                    .ThenBy(p => p.CreatedAt).ToArray();
            }
        }
        public SessionRecord CreateSession(Guid patientId, string testType)
        {
            WorkflowJson.Choice(new JValue(testType), "elk", "rtk", "barefoot");
            lock (gate)
            {
                ReadPatient(patientId);
                var id = Guid.NewGuid();
                var data = new JObject { ["id"] = id.ToString("D"), ["patient_id"] = patientId.ToString("D"),
                    ["test_type"] = testType, ["created_at"] = Now(), ["status"] = "awaiting_capture",
                    ["idempotency_key"] = Guid.NewGuid().ToString("D") };
                EnsureSpace(4096); Directory.CreateDirectory(SessionDirectory(id)); AtomicJson(SessionPath(id), data);
                return new SessionRecord(data);
            }
        }
        public IReadOnlyList<SessionRecord> History(Guid patientId)
        {
            lock (gate)
            {
                ReadPatient(patientId);
                return Directory.EnumerateDirectories(Path.Combine(root, "sessions"))
                    .Where(path => File.Exists(Path.Combine(path, "session.json")))
                    .Select(path => new SessionRecord(ReadRecovered(Path.Combine(path, "session.json"))))
                    .Where(s => s.PatientId == patientId).Select(s => Session(patientId, s.Id)).OrderByDescending(s => s.CreatedAt).ToArray();
            }
        }
        public SessionRecord Session(Guid patientId, Guid sessionId)
        {
            lock (gate)
            {
                ReadPatient(patientId);
                Require(File.Exists(SessionPath(sessionId)) || File.Exists(SessionPath(sessionId) + ".bak"), "Saved test does not exist.");
                var result = new SessionRecord(ReadRecovered(SessionPath(sessionId)));
                Require(result.Id == sessionId && result.PatientId == patientId, "Saved test belongs to another patient.");
                WorkflowJson.Choice(new JValue(result.TestType), "elk", "rtk", "barefoot");
                var capturePath = Path.Combine(SessionDirectory(sessionId), "capture", "manifest.json");
                if (result.Status == "awaiting_capture" && File.Exists(capturePath))
                {
                    var capture = ReadRecovered(capturePath); WorkflowValidation.Capture(capture, result);
                    var recovered = (JObject)result.Data.DeepClone(); recovered["status"] = "captured";
                    recovered["capture_completed_at"] = capture["capture_completed_at"]!.DeepClone();
                    AtomicJson(SessionPath(sessionId), recovered); result = new SessionRecord(recovered);
                    warnings.Add("Recovered a completed capture after an interrupted session update.");
                }
                return result;
            }
        }
        public void SaveCapture(Guid patientId, Guid sessionId, string manifestJson, string zipPath)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId);
                Require(session.Status == "awaiting_capture", "This test already has a capture. Create a new test to change its evidence.");
                var manifestBytes = System.Text.Encoding.UTF8.GetBytes(manifestJson);
                Require(manifestBytes.Length <= 1024 * 1024, "Capture manifest exceeds 1 MiB.");
                var manifest = WorkflowJson.Read(manifestBytes);
                WorkflowValidation.Capture(manifest, session);
                var size = new FileInfo(zipPath).Length;
                Require(size > 0 && size <= 512L * 1024 * 1024, "Capture ZIP exceeds 512 MiB.");
                EnsureSpace(size + 128L * 1024 * 1024);
                var target = Path.Combine(SessionDirectory(sessionId), "capture");
                var staging = target + ".pending";
                if (Directory.Exists(staging)) Directory.Delete(staging, true);
                Directory.CreateDirectory(staging);
                try
                {
                    File.Copy(zipPath, Path.Combine(staging, "media.zip"));
                    Require(new FileInfo(Path.Combine(staging, "media.zip")).Length == size, "Capture ZIP changed while being saved.");
                    ValidateZip(manifest, Path.Combine(staging, "media.zip"), staging);
                    AtomicJson(Path.Combine(staging, "manifest.json"), manifest);
                    // A complete capture directory is recoverable if shutdown precedes the session update.
                    Require(!Directory.Exists(target), "A saved capture already exists and cannot be replaced.");
                    Directory.Move(staging, target);
                    Change(session, data => { data["status"] = "captured"; data["capture_completed_at"] = manifest["capture_completed_at"]!.DeepClone(); });
                }
                finally { if (Directory.Exists(staging)) Directory.Delete(staging, true); }
            }
        }
        /// <summary>Creates one immutable assessment bundle from a saved primary and a separate steady hold.</summary>
        public void SaveMicroscopeCapture(Guid patientId, Guid newSessionId, Guid sourceSessionId, string supplementalManifestJson, string zipPath)
        {
            lock (gate)
            {
                Require(newSessionId != sourceSessionId, "A supplemental take requires a new session.");
                var target = Session(patientId, newSessionId); var source = Session(patientId, sourceSessionId);
                Require(target.Status == "awaiting_capture" && target.TestType == source.TestType, "Supplemental capture must use a new session of the same patient and test.");
                var primary = Capture(source);
                var bytes = System.Text.Encoding.UTF8.GetBytes(supplementalManifestJson);
                Require(bytes.Length <= 1024 * 1024, "Capture manifest exceeds 1 MiB.");
                var supplement = WorkflowJson.Read(bytes);
                WorkflowJson.Fields(supplement, "schema_version session_id patient_id test_type protocol_id protocol_version capture_completed_at takes", "replay_take_id");
                Require(WorkflowJson.Id(supplement["patient_id"]) == patientId && WorkflowJson.Id(supplement["session_id"]) == newSessionId
                    && (string?)supplement["test_type"] == target.TestType && (string?)supplement["protocol_id"] == target.TestType
                    && (string?)supplement["schema_version"] == "1.0" && (string?)supplement["protocol_version"] == "1.0", "Supplemental capture identity/protocol mismatch.");
                var takes = Array(supplement["takes"], 1);
                Require((string?)takes[0]!["kind"] == "microscope" && (string?)takes[0]!["condition"] == "steady_hold", "Expected one separate microscope steady hold.");
                Require(WorkflowJson.Date(supplement["capture_completed_at"]) >= WorkflowJson.Date(primary["capture_completed_at"]), "Supplemental capture predates its primary take.");
                var combined = (JObject)primary.DeepClone(); combined["session_id"] = newSessionId.ToString("D");
                combined["capture_completed_at"] = supplement["capture_completed_at"]!.DeepClone();
                combined["takes"] = new JArray(((JArray)primary["takes"]!).Concat(takes).Select(t => t.DeepClone()));
                WorkflowValidation.Capture(combined, target);
                var combinedSize = CombinedCaptureSize(combined);
                EnsureSpace(combinedSize * 2 + 128L * 1024 * 1024);
                var temporary = Path.Combine(SessionDirectory(newSessionId), "combined.pending.zip");
                try
                {
                    CombineCaptureArchives(new[] { UploadPath(source), zipPath }, temporary, combined);
                    SaveCapture(patientId, newSessionId, combined.ToString(Newtonsoft.Json.Formatting.None), temporary);
                }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
            }
        }
        private static long CombinedCaptureSize(JObject manifest)
        {
            // Output is uncompressed. Reserve both the temporary ZIP and immutable copy, including bounded ZIP headers.
            var files = ((JArray)manifest["takes"]!).SelectMany(t => new[] { t["video"]!, t["frame_metadata"]! }).ToArray();
            var bytes = files.Sum(file => WorkflowJson.Size(file["byte_size"])) + files.Length * 512L + 1024;
            Require(bytes <= 512L * 1024 * 1024, "Expanded recordings exceed the combined 512 MiB upload limit.");
            return bytes;
        }
        private static void CombineCaptureArchives(IEnumerable<string> paths, string target, JObject manifest)
        {
            using var output = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None);
            using var archive = new ZipArchive(output, ZipArchiveMode.Create);
            var names = new HashSet<string>(StringComparer.Ordinal);
            var expected = ((JArray)manifest["takes"]!).SelectMany(t => new[] { t["video"]!, t["frame_metadata"]! })
                .ToDictionary(file => (string)file["member"]!, file => WorkflowJson.Size(file["byte_size"]), StringComparer.Ordinal);
            foreach (var path in paths)
            {
                using var input = ZipFile.OpenRead(path); Require(input.Entries.Count <= 16, "Too many capture members.");
                foreach (var entry in input.Entries)
                {
                    Require(names.Add(entry.FullName) && entry.Length > 0 && entry.Length <= 512L * 1024 * 1024 && ((entry.ExternalAttributes >> 16) & 0xf000) != 0xa000, "Invalid, linked or duplicate capture member.");
                    Require(expected.TryGetValue(entry.FullName, out var expectedSize) && entry.Length == expectedSize, "Combined ZIP member differs from declared recording.");
                    using var source = entry.Open(); using var destination = archive.CreateEntry(entry.FullName, CompressionLevel.NoCompression).Open();
                    var buffer = new byte[65536]; long copied = 0; int count;
                    while ((count = source.Read(buffer, 0, buffer.Length)) > 0)
                    { copied += count; Require(copied <= expectedSize, "Combined capture member exceeded its reserved size."); destination.Write(buffer, 0, count); }
                    Require(copied == expectedSize, "Combined capture member is truncated.");
                }
            }
            Require(names.Count == expected.Count, "Combined capture is missing expected recordings.");
        }
        public string OriginalVideoPath(Guid patientId, Guid sessionId, Guid takeId)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId); var capture = Capture(session);
                var take = ((JArray)capture["takes"]!).OfType<JObject>().SingleOrDefault(t => WorkflowJson.Id(t["take_id"]) == takeId);
                Require(take != null, "Original video belongs to another capture.");
                var video = (JObject)take!["video"]!; var member = (string)video["member"]!;
                var target = Path.Combine(SessionDirectory(session.Id), "capture", member);
                if (File.Exists(target)) { VerifyFile(target, video); return target; }
                EnsureSpace(WorkflowJson.Size(video["byte_size"]));
                using var zip = ZipFile.OpenRead(UploadPath(session));
                var entry = zip.GetEntry(member); Require(entry != null, "Original video is missing from saved capture.");
                var temporary = target + ".tmp";
                try
                {
                    using (var source = entry!.Open()) using (var output = File.Create(temporary))
                    {
                        var buffer = new byte[65536]; long size = 0; int count;
                        while ((count = source.Read(buffer, 0, buffer.Length)) > 0)
                        { size += count; Require(size <= WorkflowJson.Size(video["byte_size"]), "Original video exceeded its declared size."); output.Write(buffer, 0, count); }
                        output.Flush(true);
                    }
                    VerifyFile(temporary, video); File.Move(temporary, target); return target;
                }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
            }
        }
        public double OriginalVideoFrameSeconds(Guid patientId, Guid sessionId, Guid takeId, long originalFrameId)
        {
            Require(originalFrameId >= 0, "Invalid original frame ID.");
            var session = Session(patientId, sessionId); var capture = Capture(session);
            var take = ((JArray)capture["takes"]!).OfType<JObject>().SingleOrDefault(t => WorkflowJson.Id(t["take_id"]) == takeId);
            Require(take != null, "Original video belongs to another capture.");
            var sidecar = Sidecar(session, take!); var frames = (JArray)sidecar["frames"]!;
            var origin = Timestamp(sidecar["clock"]!["origin_pts_ns"]);
            for (var i = 0; i < frames.Count; i++)
                if (Integer(frames[i]!["frame_id"]) == originalFrameId)
                    return sidecar["media"] is JObject media ? (double)Timestamp(media["presentation_time_us"]![i]) / 1e6 : (double)(Timestamp(frames[i]!["pts_ns"]) - origin) / 1e9;
            throw new InvalidDataException("Evidence frame is not present in the original recording.");
        }
        internal JObject Capture(SessionRecord session)
        {
            var manifest = ReadRecovered(Path.Combine(SessionDirectory(session.Id), "capture", "manifest.json"));
            WorkflowValidation.Capture(manifest, session); return manifest;
        }
        internal string UploadPath(SessionRecord session) => Path.Combine(SessionDirectory(session.Id), "capture", "media.zip");
        internal JObject Sidecar(SessionRecord session, JObject take) => ReadRecovered(Path.Combine(SessionDirectory(session.Id), "capture", (string)take["frame_metadata"]!["member"]!));
        public IReadOnlyList<Guid> SavedResults(Guid patientId, Guid sessionId)
        {
            var session = Session(patientId, sessionId);
            var path = Path.Combine(SessionDirectory(session.Id), "results");
            if (!Directory.Exists(path)) return System.Array.Empty<Guid>();
            return Directory.EnumerateDirectories(path).Select(Path.GetFileName).Where(name => Guid.TryParseExact(name, "D", out _))
                .Select(name => Guid.Parse(name!)).ToArray();
        }
        public CachedResult OpenResult(Guid patientId, Guid sessionId, Guid? resultId = null)
        {
            var session = Session(patientId, sessionId);
            var id = resultId ?? session.ResultId ?? throw new InvalidDataException("This test has no saved result.");
            var directory = ResultDirectory(session, id);
            var manifest = ReadRecovered(Path.Combine(directory, "result.json"));
            WorkflowValidation.Result(manifest, session, Capture(session), this, null);
            Require(WorkflowJson.Id(manifest["result_id"]) == id, "Saved result ID mismatch.");
            foreach (var artifact in (JArray)manifest["artifacts"]!) VerifyFile(Path.Combine(directory, WorkflowJson.Id(artifact["artifact_id"]).ToString("D")), (JObject)artifact);
            WorkflowValidation.Replay(manifest, directory, session, this);
            return new CachedResult(manifest, directory);
        }
        internal SessionRecord SetState(SessionRecord session, string status, string stage, string error = "") =>
            Change(session, data => { data["status"] = status; data["stage"] = stage; data["error"] = error; });
        internal SessionRecord SaveJob(SessionRecord session, JObject job) => Change(session, data =>
        {
            data["job_id"] = job["job_id"]!.DeepClone(); data["status"] = job["status"]!.DeepClone(); data["stage"] = job["stage"]!.DeepClone();
            data["error"] = (string?)job["error"]?["message"] ?? "";
        });
        internal SessionRecord Reprocess(SessionRecord session)
        {
            Require(session.Status == "failed" || session.Status == "loaded" || session.Status == "ready", "Reprocessing requires a terminal attempt.");
            return Change(session, data => { data["idempotency_key"] = Guid.NewGuid().ToString("D"); data.Remove("job_id"); data.Remove("result_id"); data.Remove("capture_to_loaded_seconds"); data["status"] = "captured"; data["error"] = ""; });
        }
        internal SessionRecord Cached(SessionRecord session, Guid resultId) => Change(session, data =>
        { data["result_id"] = resultId.ToString("D"); data["status"] = "ready"; data["stage"] = "complete"; data["error"] = ""; });
        /// <summary>Call after the first displayed result/replay frame. First completion timing is immutable.</summary>
        public SessionRecord MarkReplayLoaded(Guid patientId, Guid sessionId, Guid resultId, double? monotonicElapsedSeconds = null)
        {
            var session = Session(patientId, sessionId);
            Require(session.ResultId == resultId && (session.Status == "ready" || session.Status == "loaded"), "Displayed result does not match saved result.");
            if (session.CaptureToLoadedSeconds.HasValue) return session;
            if (monotonicElapsedSeconds.HasValue)
                Require(!double.IsNaN(monotonicElapsedSeconds.Value) && !double.IsInfinity(monotonicElapsedSeconds.Value) && monotonicElapsedSeconds.Value >= 0, "Invalid elapsed measurement.");
            var captureTime = WorkflowJson.Date(Capture(session)["capture_completed_at"]);
            var seconds = monotonicElapsedSeconds ?? (DateTimeOffset.UtcNow - captureTime).TotalSeconds;
            Require(seconds >= 0, "Capture clock is ahead of display time; timing is unavailable.");
            return Change(session, data =>
            {
                data["status"] = "loaded";
                data["capture_to_loaded_seconds"] = seconds;
                data["capture_timing_basis"] = monotonicElapsedSeconds.HasValue ? "monotonic" : "wall_clock_estimate";
            });
        }
        internal string ResultDirectory(SessionRecord session, Guid resultId) => Path.Combine(SessionDirectory(session.Id), "results", resultId.ToString("D"));
        internal void Reserve(long bytes) { lock (gate) EnsureSpace(bytes); }
        internal static void AtomicJson(string path, JObject data)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var temporary = path + ".tmp";
            using (var stream = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
            { var bytes = WorkflowJson.Bytes(data); stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            if (File.Exists(path)) File.Replace(temporary, path, path + ".bak"); else File.Move(temporary, path);
        }
        private SessionRecord Change(SessionRecord session, Action<JObject> update)
        {
            lock (gate)
            {
                var data = (JObject)Session(session.PatientId, session.Id).Data.DeepClone(); update(data);
                AtomicJson(SessionPath(session.Id), data); return new SessionRecord(data);
            }
        }
        private PatientRecord ReadPatient(Guid id)
        {
            Require(id != Guid.Empty && (File.Exists(PatientPath(id)) || File.Exists(PatientPath(id) + ".bak")), "Patient does not exist.");
            var value = new PatientRecord(ReadRecovered(PatientPath(id))); Require(value.Id == id, "Patient ID mismatch."); return value;
        }
        private JObject ReadRecovered(string path)
        {
            try { return ReadFile(path); }
            catch (Exception exception) when (exception is IOException || exception is InvalidDataException || exception is ArgumentException)
            {
                if (!File.Exists(path + ".bak")) throw new InvalidDataException("A saved record is damaged; its source files were preserved.", exception);
                var backup = ReadFile(path + ".bak"); warnings.Add("Recovered a previous saved record after an interrupted or damaged write."); return backup;
            }
        }
        private static JObject ReadFile(string path)
        { Require(new FileInfo(path).Length <= WorkflowJson.JsonLimit, "Saved JSON exceeds its size limit."); return WorkflowJson.Read(File.ReadAllBytes(path)); }
        private void EnsureSpace(long extra)
        {
            var used = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Sum(file => new FileInfo(file).Length);
            Require(extra >= 0 && extra <= StorageLimit - used, "Local storage budget reached. Export or remove old test data before recording again.");
        }
        private static void ValidateZip(JObject manifest, string zipPath, string output, bool writeSidecars = true)
        {
            var files = ((JArray)manifest["takes"]!).SelectMany(t => new[] { (JObject)t["video"]!, (JObject)t["frame_metadata"]! })
                .ToDictionary(f => (string)f["member"]!, StringComparer.Ordinal);
            using var zip = ZipFile.OpenRead(zipPath);
            Require(zip.Entries.Count == files.Count, "Capture ZIP has missing or unexpected members.");
            var names = new HashSet<string>(StringComparer.Ordinal); long total = 0;
            foreach (var entry in zip.Entries)
            {
                Require(names.Add(entry.FullName) && files.TryGetValue(entry.FullName, out _), "Duplicate or unexpected ZIP member.");
                var expected = files[entry.FullName]; var size = WorkflowJson.Size(expected["byte_size"]);
                Require(entry.Length == size && ((entry.ExternalAttributes >> 16) & 0xf000) != 0xa000, "ZIP member is a link or its size differs.");
                total += size; Require(total <= 1024L * 1024 * 1024, "Capture extraction exceeds 1 GiB.");
                using var input = entry.Open(); using var sha = SHA256.Create();
                using var sidecar = entry.FullName.EndsWith(".json", StringComparison.Ordinal) ? new MemoryStream() : null;
                var buffer = new byte[65536]; var signature = new byte[12]; long read = 0; int count;
                while ((count = input.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (read < signature.Length) System.Array.Copy(buffer, 0, signature, (int)read, Math.Min(count, signature.Length - (int)read));
                    read += count; Require(read <= size, "ZIP member exceeded declared size."); sha.TransformBlock(buffer, 0, count, null, 0); sidecar?.Write(buffer, 0, count);
                }
                if (sidecar == null) Require(read >= 12 && System.Text.Encoding.ASCII.GetString(signature, 4, 4) == "ftyp", "Invalid original MP4 signature.");
                sha.TransformFinalBlock(System.Array.Empty<byte>(), 0, 0);
                Require(read == size && Hex(sha.Hash!) == WorkflowJson.Hash(expected["sha256"]), "Capture member hash mismatch.");
                if (sidecar != null)
                {
                    var data = WorkflowJson.Read(sidecar.ToArray());
                    var take = (JObject)((JArray)manifest["takes"]!).Single(t => (string?)t["frame_metadata"]?["member"] == entry.FullName);
                    WorkflowValidation.Sidecar(data, take); if (writeSidecars) AtomicJson(Path.Combine(output, entry.FullName), data);
                }
            }
        }
        internal static void VerifyFile(string path, JObject artifact)
        {
            Require(File.Exists(path) && new FileInfo(path).Length == WorkflowJson.Size(artifact["byte_size"]), "Saved artifact size mismatch.");
            using var stream = File.OpenRead(path); using var sha = SHA256.Create();
            Require(Hex(sha.ComputeHash(stream)) == WorkflowJson.Hash(artifact["sha256"]), "Saved artifact hash mismatch.");
        }
        internal static string Hex(byte[] bytes) => BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        private string PatientPath(Guid id) => Path.Combine(root, "patients", id.ToString("D") + ".json");
        private string SessionDirectory(Guid id) => Path.Combine(root, "sessions", id.ToString("D"));
        private string SessionPath(Guid id) => Path.Combine(SessionDirectory(id), "session.json");
        private static string Now() => DateTimeOffset.UtcNow.ToString("O");
    }
}
