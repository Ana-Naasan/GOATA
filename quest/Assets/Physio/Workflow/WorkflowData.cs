#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Physio.Replay;

namespace Physio.Workflow
{
    public sealed class PatientRecord
    {
        public Guid Id { get; }
        public string DisplayName { get; }
        public DateTimeOffset CreatedAt { get; }
        internal PatientRecord(JObject data)
        { Id = WorkflowJson.Id(data["id"]); DisplayName = ReplayJson.String(data["display_name"], 100); CreatedAt = WorkflowJson.Date(data["created_at"]); }
    }

    public sealed class SessionRecord
    {
        internal JObject Data { get; }
        public Guid Id => WorkflowJson.Id(Data["id"]);
        public Guid PatientId => WorkflowJson.Id(Data["patient_id"]);
        public string TestType => ReplayJson.String(Data["test_type"]);
        public DateTimeOffset CreatedAt => WorkflowJson.Date(Data["created_at"]);
        public string Status => ReplayJson.String(Data["status"]);
        public string Stage => (string?)Data["stage"] ?? "";
        public string Error => (string?)Data["error"] ?? "";
        public Guid IdempotencyKey => WorkflowJson.Id(Data["idempotency_key"]);
        public Guid? JobId => Data["job_id"] == null ? null : WorkflowJson.Id(Data["job_id"]);
        public Guid? ResultId => Data["result_id"] == null ? null : WorkflowJson.Id(Data["result_id"]);
        public string? CaptureTimingBasis => (string?)Data["capture_timing_basis"];
        public double? CaptureToLoadedSeconds => (double?)Data["capture_to_loaded_seconds"];
        internal SessionRecord(JObject data) { Data = (JObject)data.DeepClone(); }
    }

    public sealed class GuidedCaptureView
    {
        public string View { get; }
        public Guid? SelectedTakeId { get; }
        public IReadOnlyList<Guid> TakeIds { get; }
        internal GuidedCaptureView(string view, Guid? selected, IEnumerable<Guid> takes)
        { View = view; SelectedTakeId = selected; TakeIds = System.Array.AsReadOnly(takes.ToArray()); }
    }

    public sealed class GuidedCaptureState
    {
        public IReadOnlyList<GuidedCaptureView> Views { get; }
        public string? NextView => Views.FirstOrDefault(v => !v.SelectedTakeId.HasValue)?.View;
        public string FootSide { get; }
        public double TargetDurationSeconds { get; }
        public bool Complete => Views.All(v => v.SelectedTakeId.HasValue);
        public bool Sealed { get; }
        public Guid? SuggestedReplayTakeId { get; }
        internal GuidedCaptureState(IEnumerable<GuidedCaptureView> views, string side, double duration, bool sealedCapture, bool foot)
        {
            Views = System.Array.AsReadOnly(views.ToArray()); FootSide = side; TargetDurationSeconds = duration;
            Sealed = sealedCapture; SuggestedReplayTakeId = foot ? null : Views.First().SelectedTakeId;
        }
    }

    public sealed class ProcessingUpdate
    {
        public string Stage { get; }
        public string Detail { get; }
        public TimeSpan Elapsed { get; }
        public long? Completed { get; }
        public long? Total { get; }
        public string? Unit { get; }
        internal ProcessingUpdate(string stage, string detail, DateTimeOffset captureTime, JObject? progress = null)
        {
            Stage = stage; Detail = detail; Elapsed = DateTimeOffset.UtcNow - captureTime;
            Completed = (long?)progress?["completed"]; Total = (long?)progress?["total"]; Unit = (string?)progress?["unit"];
        }
    }

    public sealed class CachedResult
    {
        private readonly JObject manifest;
        private readonly string directory;
        public JObject Manifest => (JObject)manifest.DeepClone();
        public Guid ResultId => WorkflowJson.Id(manifest["result_id"]);
        public Guid? ReplayTakeId => manifest["replay"] == null ? null : WorkflowJson.Id(manifest["replay"]!["source_take_id"]);
        public string DirectoryPath => directory;
        internal CachedResult(JObject manifest, string directory) { this.manifest = (JObject)manifest.DeepClone(); this.directory = directory; }
        public string ArtifactPath(Guid artifactId)
        {
            ReplayJson.Require(((JArray)manifest["artifacts"]!).Any(a => WorkflowJson.Id(a["artifact_id"]) == artifactId), "Artifact is outside this result.");
            return Path.Combine(directory, artifactId.ToString("D"));
        }
        public ReplayData? LoadReplay()
        {
            if (manifest["replay"] == null) return null;
            var path = ArtifactPath(WorkflowJson.Id(manifest["replay"]!["manifest_artifact_id"]));
            var bytes = File.ReadAllBytes(path);
            var replay = WorkflowJson.Read(bytes);
            var artifacts = WorkflowJson.Fields(replay["artifacts"], "mesh_triangles mesh_vertices skeleton_joints");
            var paths = new Dictionary<string, string>(StringComparer.Ordinal);
            long size = bytes.Length;
            foreach (var role in new[] { "mesh_triangles", "mesh_vertices", "skeleton_joints" })
            {
                var inner = WorkflowJson.Fields(artifacts[role], "artifact_id filename byte_size sha256 encoding");
                var id = WorkflowJson.Id(inner["artifact_id"]);
                var outer = ((JArray)manifest["artifacts"]!).OfType<JObject>().SingleOrDefault(a => WorkflowJson.Id(a["artifact_id"]) == id);
                var length = WorkflowJson.Size(inner["byte_size"], ReplayImporter.MaxDecodedBytes);
                ReplayJson.Require(outer != null && (string?)outer["role"] == "replay_binary" && (string?)outer["media_type"] == "application/octet-stream"
                    && WorkflowJson.Size(outer["byte_size"]) == length && WorkflowJson.Hash(outer["sha256"]) == WorkflowJson.Hash(inner["sha256"]),
                    "Replay binary descriptor differs from result artifact.");
                var artifactPath = ArtifactPath(id);
                ReplayJson.Require(new FileInfo(artifactPath).Length == length, "Replay binary file size differs from metadata.");
                size += length; ReplayJson.Require(size <= ReplayImporter.MaxDecodedBytes, "Replay inputs exceed 256 MiB.");
                paths.Add(role, artifactPath);
            }
            byte[] Load(string role) => File.ReadAllBytes(paths[role]);
            var data = ReplayImporter.Parse(bytes, Load("mesh_triangles"), Load("mesh_vertices"), Load("skeleton_joints"));
            ReplayJson.Require(data.ResultId == ResultId && data.Timeline.SourceTakeId == ReplayTakeId,
                "Replay identity does not match the selected result.");
            return data;
        }
    }

    internal static class WorkflowJson
    {
        internal const int JsonLimit = 16 * 1024 * 1024;
        internal static JObject Read(byte[] bytes)
        {
            ReplayJson.Require(bytes.Length > 0 && bytes.Length <= JsonLimit, "JSON size exceeds the supported bound.");
            try { return ReplayJson.Read(bytes); }
            catch (Newtonsoft.Json.JsonException) { throw new InvalidDataException("Malformed JSON."); }
        }
        internal static JObject Fields(JToken? token, string required, string optional = "")
        {
            ReplayJson.Require(token is JObject, "Expected an object.");
            var data = (JObject)token!;
            var requiredFields = required.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
            var allowed = new HashSet<string>(requiredFields.Concat(optional.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries)), StringComparer.Ordinal);
            ReplayJson.Require(requiredFields.All(f => data[f] != null) && data.Properties().All(p => allowed.Contains(p.Name)), "Missing or unknown field.");
            return data;
        }
        internal static Guid Id(JToken? token)
        {
            var id = ReplayJson.Uuid(token);
            ReplayJson.Require(id != Guid.Empty && (string?)token == id.ToString("D"), "Expected canonical nonzero UUID.");
            return id;
        }
        internal static DateTimeOffset Date(JToken? token)
        {
            var raw = ReplayJson.String(token);
            ReplayJson.Require(raw.EndsWith("Z", StringComparison.Ordinal) || (raw.Length >= 6 && (raw[raw.Length - 6] == '+' || raw[raw.Length - 6] == '-')), "Timestamp requires a timezone.");
            ReplayJson.Require(DateTimeOffset.TryParse(raw, System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.None, out var result), "Invalid date.");
            return result;
        }
        internal static string Choice(JToken? token, params string[] allowed)
        {
            var value = ReplayJson.String(token);
            ReplayJson.Require(allowed.Contains(value, StringComparer.Ordinal), "Unsupported field value.");
            return value;
        }
        internal static string Hash(JToken? token)
        {
            var value = ReplayJson.String(token, 64);
            ReplayJson.Require(value.Length == 64 && value.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f'), "Invalid SHA-256.");
            return value;
        }
        internal static long Size(JToken? token, long limit = 1024L * 1024 * 1024)
        {
            var size = ReplayJson.Integer(token, 1);
            ReplayJson.Require(size <= limit, "Size exceeds supported bound."); return (long)size;
        }
        internal static byte[] Bytes(JObject data) => System.Text.Encoding.UTF8.GetBytes(data.ToString(Newtonsoft.Json.Formatting.None));
    }
}
