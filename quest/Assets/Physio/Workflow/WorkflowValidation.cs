#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using Newtonsoft.Json.Linq;
using Physio.Replay;
using static Physio.Replay.ReplayJson;
using static Physio.Workflow.WorkflowJson;

namespace Physio.Workflow
{
    internal static class WorkflowValidation
    {
        internal static void Capture(JObject value, SessionRecord session)
        {
            Fields(value, "schema_version session_id patient_id test_type protocol_id protocol_version capture_completed_at takes", "replay_take_id");
            Identity(value, session); Require(String(value["schema_version"]) == "1.0" && String(value["protocol_version"]) == "1.0" && String(value["protocol_id"]) == session.TestType, "Unsupported capture protocol.");
            Date(value["capture_completed_at"]);
            var takes = Array(value["takes"]); Require(takes.Count > 0 && takes.Count <= 8, "Capture requires 1–8 takes.");
            var ids = new HashSet<Guid>(); var members = new HashSet<string>(StringComparer.Ordinal);
            foreach (var token in takes)
            {
                var take = Fields(token, "take_id kind view condition side duration_s video frame_metadata");
                Require(ids.Add(Id(take["take_id"])), "Duplicate take ID.");
                var kind = Choice(take["kind"], "full_body", "foot_closeup", "microscope");
                Choice(take["view"], "front", "left", "right", "rear", "medial", "other");
                Choice(take["condition"], "standing", "seated", "exercise", "steady_hold");
                Choice(take["side"], "left", "right", "bilateral", "not_applicable"); Require(Number(take["duration_s"]) > 0, "Capture duration must be positive.");
                if (kind == "foot_closeup") { Choice(take["side"], "left", "right"); Choice(take["condition"], "standing", "seated"); }
                foreach (var field in new[] { "video", "frame_metadata" })
                {
                    var file = Fields(take[field], "member sha256 byte_size"); var member = String(file["member"]);
                    var extension = field == "video" ? ".mp4" : ".json";
                    Require(member.EndsWith(extension, StringComparison.Ordinal) && member.Length == 36 + extension.Length, "Unsafe capture filename.");
                    Id(new JValue(member.Substring(0, 36))); Require(members.Add(member), "Duplicate file reference."); Hash(file["sha256"]);
                    Size(file["byte_size"], field == "frame_metadata" ? JsonLimit : 1024L * 1024 * 1024);
                }
            }
            if (session.TestType != "barefoot" || value["replay_take_id"] != null)
            {
                var replayId = Id(value["replay_take_id"]);
                Require(takes.Any(t => Id(t["take_id"]) == replayId && (string?)t["kind"] == "full_body"), "Replay must use an included full-body take.");
            }
            if (session.TestType == "barefoot") Require(takes.Any(t => (string?)t["kind"] == "foot_closeup"), "Barefoot requires a foot closeup.");
        }
        internal static void Sidecar(JObject value, JObject take)
        {
            Fields(value, "schema_version take_id adapter image camera clock frames capture", "media");
            Require(String(value["schema_version"]) == "1.0" && Id(value["take_id"]) == Id(take["take_id"]), "Sidecar identity mismatch.");
            var clock = Fields(value["clock"], "id unit origin_pts_ns"); String(clock["id"]); Require(String(clock["unit"]) == "nanoseconds", "Unknown source clock unit.");
            var origin = Timestamp(clock["origin_pts_ns"]);
            var capture = Fields(value["capture"], "view condition side interrupted gaps");
            foreach (var field in new[] { "view", "condition", "side" }) Require(JToken.DeepEquals(capture[field], take[field]), "Capture context mismatch.");
            Require(!Boolean(capture["interrupted"]), "An interrupted take cannot be submitted as complete.");
            var frames = Array(value["frames"]); Require(frames.Count > 0, "Capture has no frames.");
            BigInteger priorId = -1, priorPts = -1;
            foreach (var token in frames)
            {
                var frame = Fields(token, "frame_id pts_ns image_valid", "camera_pose"); var id = Integer(frame["frame_id"]); var pts = Timestamp(frame["pts_ns"]); Boolean(frame["image_valid"]);
                Require(id > priorId && pts > priorPts && pts >= origin, "Original frame IDs/PTS must be ordered."); priorId = id; priorPts = pts;
            }
            if (value["media"] != null)
            {
                var media = Fields(value["media"], "binding presentation_time_us");
                Require(String(media["binding"]) == "indexed_presentation_time_us", "Unknown source/video binding.");
                var mediaTimes = Array(media["presentation_time_us"], frames.Count); BigInteger previous = -1;
                foreach (var timestamp in mediaTimes) { var pts = Timestamp(timestamp); Require(pts > previous, "Video presentation times must increase."); previous = pts; }
            }
            Require(Timestamp(frames[0]!["pts_ns"]) == origin && (double)(priorPts - origin) / 1e9 <= Number(take["duration_s"]) + 1e-6, "Source duration/origin mismatch.");
            foreach (var token in Array(capture["gaps"]))
            {
                var gap = Fields(token, "start_pts_ns end_pts_ns reason"); String(gap["reason"], 500);
                Require(Timestamp(gap["start_pts_ns"]) >= origin && Timestamp(gap["end_pts_ns"]) >= Timestamp(gap["start_pts_ns"]) && Timestamp(gap["end_pts_ns"]) <= priorPts, "Invalid capture gap.");
            }
        }
        internal static void Job(JObject value, SessionRecord session)
        {
            Fields(value, "job_id session_id patient_id test_type status stage created_at updated_at", "progress result_id error"); Identity(value, session);
            var jobId = Id(value["job_id"]); Require(!session.JobId.HasValue || session.JobId == jobId, "Job ID changed across retries.");
            var status = Choice(value["status"], "pending", "running", "succeeded", "failed");
            var stage = Choice(value["stage"], "queued", "preparing_recording", "estimating_movement", "analysing_test", "preparing_replay", "complete");
            Require(Date(value["updated_at"]) >= Date(value["created_at"]), "Job time moved backwards.");
            if (status == "succeeded") { Id(value["result_id"]); Require(stage == "complete", "Succeeded job is incomplete."); }
            else Require(value["result_id"] == null, "Unfinished job must not expose a result.");
            if (status == "failed") Error(Fields(value["error"], "code message retryable")); else Require(value["error"] == null, "Unexpected job error.");
            if (value["progress"] != null)
            {
                var progress = Fields(value["progress"], "completed total unit"); var total = Size(progress["total"], long.MaxValue);
                Require(Integer(progress["completed"]) <= total, "Invalid processing progress."); Choice(progress["unit"], "frames", "takes", "artifacts");
            }
        }
        internal static void Error(JObject value)
        {
            Fields(value, "code message retryable");
            Choice(value["code"], "VALIDATION_ERROR", "UPLOAD_TOO_LARGE", "UNAUTHORIZED", "NOT_FOUND", "NOT_READY", "IDEMPOTENCY_CONFLICT", "CAPACITY_EXCEEDED", "PROCESSING_FAILED", "WORKER_INTERRUPTED", "INTERNAL_ERROR");
            String(value["message"], 500); Boolean(value["retryable"]);
        }
        internal static void Result(JObject value, SessionRecord session, JObject capture, LocalPatientStore store, Guid? expectedResult)
        {
            Fields(value, "schema_version result_id job_id session_id patient_id test_type created_at pipeline_version protocol_id protocol_version input_digest validation_status methods features findings microscopes artifacts", "replay");
            Identity(value, session); var id = Id(value["result_id"]); if (expectedResult.HasValue) Require(id == expectedResult.Value && Id(value["job_id"]) == session.JobId, "Result differs from completed job."); else Id(value["job_id"]);
            Require(String(value["schema_version"]) == "1.0" && String(value["validation_status"]) == "research_demo_unvalidated", "Unsupported result schema or validation status.");
            Require(JToken.DeepEquals(value["protocol_id"], capture["protocol_id"]) && JToken.DeepEquals(value["protocol_version"], capture["protocol_version"]), "Result protocol mismatch.");
            Date(value["created_at"]); String(value["pipeline_version"], 100); Hash(value["input_digest"]);
            var artifacts = new Dictionary<Guid, JObject>(); long total = 0;
            foreach (var token in Array(value["artifacts"]))
            {
                var artifact = Fields(token, "artifact_id role media_type byte_size sha256"); var artifactId = Id(artifact["artifact_id"]);
                Require(!artifacts.ContainsKey(artifactId), "Duplicate artifact ID."); artifacts.Add(artifactId, artifact);
                var role = Choice(artifact["role"], "replay_manifest", "replay_binary", "evidence_video", "microscope_original", "microscope_amplified", "processing_settings", "quality_report");
                var media = Choice(artifact["media_type"], "application/json", "application/octet-stream", "video/mp4");
                Require(media == (role == "replay_binary" ? "application/octet-stream" : role.EndsWith("video", StringComparison.Ordinal) || role.StartsWith("microscope_", StringComparison.Ordinal) ? "video/mp4" : "application/json"), "Artifact type/role mismatch.");
                total += Size(artifact["byte_size"], media == "application/json" ? JsonLimit : 1024L * 1024 * 1024); Hash(artifact["sha256"]);
                Require(total <= 1024L * 1024 * 1024 && artifacts.Count <= 128, "Result artifacts exceed bounds.");
            }
            var methods = new HashSet<string>(StringComparer.Ordinal);
            foreach (var token in Array(value["methods"]))
            {
                var method = Fields(token, "method_id name version settings_artifact_id", "checkpoint_sha256");
                Require(methods.Add(String(method["method_id"], 80)), "Duplicate method ID."); String(method["name"], 100); String(method["version"], 100);
                Reference(method["settings_artifact_id"], artifacts, "processing_settings"); if (method["checkpoint_sha256"] != null) Hash(method["checkpoint_sha256"]);
            }
            Require(methods.Count > 0, "Missing processing methods.");
            var features = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var token in Array(value["features"]))
            {
                var feature = Fields(token, "name status detail"); var name = Choice(feature["name"], "replay", "movement", "foot", "microscope");
                Require(!features.ContainsKey(name), "Duplicate feature."); features.Add(name, Choice(feature["status"], "available", "unavailable")); String(feature["detail"], 500);
            }
            Require(features.ContainsKey("microscope") && (session.TestType == "barefoot" ? features.ContainsKey("foot") : features.ContainsKey("movement") && features.ContainsKey("replay")), "Missing feature availability.");
            if (value["replay"] != null)
            {
                var replay = Fields(value["replay"], "source_take_id manifest_artifact_id");
                Require(features.TryGetValue("replay", out var state) && state == "available" && JToken.DeepEquals(replay["source_take_id"], capture["replay_take_id"]), "Replay source does not match capture.");
                Reference(replay["manifest_artifact_id"], artifacts, "replay_manifest");
            }
            else Require(!features.TryGetValue("replay", out var state) || state == "unavailable", "Replay marked available without artifacts.");
            var microscopes = new Dictionary<Guid, JObject>();
            foreach (var token in Array(value["microscopes"]))
            {
                var item = Fields(token, "microscope_id method_id evidence region side status detail", "original_artifact_id amplified_artifact_id settings_artifact_id");
                var microscopeId = Id(item["microscope_id"]); Require(!microscopes.ContainsKey(microscopeId), "Duplicate microscope ID."); microscopes.Add(microscopeId, item);
                MethodAndEvidence(item, methods, capture, session, store); String(item["detail"], 500);
                if (Choice(item["status"], "available", "unavailable") == "available")
                { Reference(item["original_artifact_id"], artifacts, "microscope_original"); Reference(item["amplified_artifact_id"], artifacts, "microscope_amplified"); Reference(item["settings_artifact_id"], artifacts, "processing_settings"); }
            }
            Require(features["microscope"] != "available" || microscopes.Values.Any(m => (string?)m["status"] == "available"), "Microscope marked available without a video pair.");
            var findingIds = new HashSet<Guid>();
            foreach (var token in Array(value["findings"]))
            {
                var finding = Fields(token, "finding_id method_id label_code label explanation region side evidence limitations metrics", "highlight_joint_names microscope_id");
                Require(findingIds.Add(Id(finding["finding_id"])), "Duplicate finding ID."); MethodAndEvidence(finding, methods, capture, session, store);
                String(finding["label_code"], 100); String(finding["label"], 160); String(finding["explanation"], 1000);
                Require((string?)finding["evidence"]!["quality"] != "insufficient", "Finding has insufficient evidence.");
                foreach (var limitation in Array(finding["limitations"])) String(limitation, 500);
                foreach (var tokenMetric in Array(finding["metrics"]))
                {
                    var metric = Fields(tokenMetric, "name value unit basis scale_status", "scale_provenance"); String(metric["name"], 100); Number(metric["value"]); String(metric["unit"], 40);
                    Choice(metric["basis"], "image_measurement", "pose_estimate", "model_score"); var scale = Choice(metric["scale_status"], "calibrated", "estimated", "not_required");
                    if (scale != "not_required" || metric["scale_provenance"] != null) String(metric["scale_provenance"], 500);
                }
                if (finding["highlight_joint_names"] != null)
                { var names = Array(finding["highlight_joint_names"]).Select(t => String(t, 80)).ToArray(); Require(names.Distinct(StringComparer.Ordinal).Count() == names.Length, "Duplicate highlight joint."); }
                if (finding["microscope_id"] != null)
                {
                    Require(microscopes.TryGetValue(Id(finding["microscope_id"]), out var microscope), "Missing microscope reference.");
                    Require(JToken.DeepEquals(finding["evidence"], microscope!["evidence"]), "Microscope evidence differs from finding.");
                }
            }
        }
        private static void MethodAndEvidence(JObject item, HashSet<string> methods, JObject capture, SessionRecord session, LocalPatientStore store)
        {
            Require(methods.Contains(String(item["method_id"], 80)), "Unknown method reference."); String(item["region"], 80); Choice(item["side"], "left", "right", "bilateral", "not_applicable");
            var evidence = Fields(item["evidence"], "take_id start_s end_s first_frame_id last_frame_id condition quality", "quality_reason");
            var id = Id(evidence["take_id"]); var take = ((JArray)capture["takes"]!).OfType<JObject>().SingleOrDefault(t => Id(t["take_id"]) == id);
            Require(take != null, "Evidence refers to another capture.");
            Require(JToken.DeepEquals(evidence["condition"], take!["condition"]), "Evidence condition differs from source.");
            var start = Number(evidence["start_s"]); var end = Number(evidence["end_s"]);
            Require(start >= 0 && end >= start && end <= Number(take["duration_s"]), "Evidence interval exceeds source.");
            var quality = Choice(evidence["quality"], "usable", "limited", "insufficient"); if (quality != "usable" || evidence["quality_reason"] != null) String(evidence["quality_reason"], 500);
            var sidecar = store.Sidecar(session, take); var frames = ((JArray)sidecar["frames"]!).OfType<JObject>().ToDictionary(f => Integer(f["frame_id"]));
            var first = Integer(evidence["first_frame_id"]); var last = Integer(evidence["last_frame_id"]);
            Require(first <= last && frames.ContainsKey(first) && frames.ContainsKey(last), "Evidence references missing original frames.");
            var origin = Timestamp(sidecar["clock"]!["origin_pts_ns"]);
            var firstTime = (double)(Timestamp(frames[first]["pts_ns"]) - origin) / 1e9;
            var lastTime = (double)(Timestamp(frames[last]["pts_ns"]) - origin) / 1e9;
            Require(firstTime >= start - 1e-9 && lastTime <= end + 1e-9, "Evidence frames are outside the source interval.");
            if (quality != "insufficient") Require(Boolean(frames[first]["image_valid"]) && Boolean(frames[last]["image_valid"]), "Evidence endpoints are invalid images.");
        }
        private static void Reference(JToken? token, Dictionary<Guid, JObject> artifacts, string role)
        { Require(artifacts.TryGetValue(Id(token), out var value) && (string?)value["role"] == role, "Artifact reference has wrong role or is missing."); }
        private static void Identity(JObject value, SessionRecord session)
        { Require(Id(value["session_id"]) == session.Id && Id(value["patient_id"]) == session.PatientId && String(value["test_type"]) == session.TestType, "Response belongs to another patient or test."); }
        internal static void Replay(JObject result, string directory, SessionRecord session, LocalPatientStore store)
        {
            if (result["replay"] == null) return;
            var cache = new CachedResult(result, directory); var data = cache.LoadReplay()!;
            var metadata = WorkflowJson.Read(File.ReadAllBytes(cache.ArtifactPath(Id(result["replay"]!["manifest_artifact_id"]))));
            var capture = store.Capture(session); var take = ((JArray)capture["takes"]!).OfType<JObject>().Single(t => Id(t["take_id"]) == data.Timeline.SourceTakeId);
            var sidecar = store.Sidecar(session, take);
            Require(JToken.DeepEquals(metadata["source_clock"], sidecar["clock"]), "Replay source clock differs from capture.");
            var original = ((JArray)sidecar["frames"]!).ToDictionary(f => Integer(f["frame_id"]));
            var ids = Array(metadata["source_frame_ids"]); var pts = Array(metadata["source_pts_ns"]);
            for (var i = 0; i < ids.Count; i++)
            {
                Require(original.TryGetValue(Integer(ids[i]), out var frame) && JToken.DeepEquals(frame["pts_ns"], pts[i]), "Replay source frame mapping differs from capture.");
                if (!Boolean(frame!["image_valid"]))
                    Require(!Boolean(metadata["frame_valid"]![i]) && Array(metadata["joint_valid"]![i]).All(j => !Boolean(j)), "Replay marks an unobserved source frame as valid.");
            }
            var origin = Timestamp(sidecar["clock"]!["origin_pts_ns"]);
            var firstTime = Number(metadata["frame_times_s"]![0]); var lastTime = Number(metadata["frame_times_s"]![ids.Count - 1]);
            foreach (var sourceGap in Array(sidecar["capture"]!["gaps"]))
            {
                var start = Math.Max(firstTime, (double)(Timestamp(sourceGap["start_pts_ns"]) - origin) / 1e9);
                var end = Math.Min(lastTime, (double)(Timestamp(sourceGap["end_pts_ns"]) - origin) / 1e9);
                if (end >= start) Require(Array(metadata["gaps"]).Any(g => Number(g["start_s"]) <= start && Number(g["end_s"]) >= end), "Replay omitted an original capture gap.");
            }
            var names = new HashSet<string>(Enumerable.Range(0, data.JointCount).Select(data.JointNameAt), StringComparer.Ordinal);
            foreach (var finding in (JArray)result["findings"]!)
                if (finding["highlight_joint_names"] is JArray highlights)
                    foreach (var name in highlights) Require(names.Contains(String(name, 80)), "Finding highlights an unknown replay joint.");
        }
    }
}
