#nullable enable
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using static Physio.Replay.ReplayJson;

namespace Physio.Workflow
{
    public sealed partial class LocalPatientStore
    {
        private static readonly string[] GuidedViews = { "right", "front", "rear", "left" };
        private const int MaximumGuidedTakes = 32;

        public GuidedCaptureState BeginGuidedCapture(Guid patientId, Guid sessionId, string footSide = "left", double targetDurationSeconds = 10)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId);
                Require(session.Status == "awaiting_capture", "This assessment already has immutable capture evidence.");
                Require(new[] { 5.0, 10.0, 15.0 }.Contains(targetDurationSeconds), "Choose a 5, 10 or 15 second recording.");
                var side = session.TestType == "barefoot" ? WorkflowJson.Choice(new JValue(footSide), "left", "right") : "not_applicable";
                var plan = ReadGuidedPlan(session);
                if (plan != null) plan = RecoverGuidedSelection(session, plan);
                if (plan == null)
                {
                    plan = new JObject { ["schema_version"] = "1", ["patient_id"] = patientId.ToString("D"), ["session_id"] = sessionId.ToString("D"),
                        ["test_type"] = session.TestType, ["foot_side"] = side, ["duration_s"] = targetDurationSeconds, ["selected"] = new JObject() };
                    EnsureSpace(4096); AtomicJson(GuidedPlanPath(sessionId), plan);
                }
                else if ((string?)plan["foot_side"] != side || Number(plan["duration_s"]) != targetDurationSeconds)
                {
                    Require(GuidedTakeDirectories(sessionId).Count == 0, "Recording duration and foot side cannot change after a take is saved.");
                    plan = (JObject)plan.DeepClone(); plan["foot_side"] = side; plan["duration_s"] = targetDurationSeconds;
                    AtomicJson(GuidedPlanPath(sessionId), plan);
                }
                return GuidedCapture(patientId, sessionId)!;
            }
        }

        public GuidedCaptureState? GuidedCapture(Guid patientId, Guid sessionId)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId); var plan = ReadGuidedPlan(session);
                if (plan == null) return null;
                plan = RecoverGuidedSelection(session, plan);
                var takes = ReadGuidedTakes(session, plan);
                var selected = (JObject)plan["selected"]!; var recovered = (JObject)selected.DeepClone();
                var views = new List<GuidedCaptureView>();
                foreach (var view in GuidedViews)
                {
                    var available = takes.Where(t => (string?)t.Value["takes"]![0]!["view"] == view)
                        .OrderBy(t => WorkflowJson.Date(t.Value["capture_completed_at"])).ThenBy(t => t.Key).Select(t => t.Key).ToArray();
                    Guid? chosen = selected[view] == null ? null : WorkflowJson.Id(selected[view]);
                    if (chosen.HasValue) Require(available.Contains(chosen.Value), "A selected guided recording is missing or has changed view.");
                    else if (available.Length > 0) { chosen = available.Last(); recovered[view] = chosen.Value.ToString("D"); }
                    views.Add(new GuidedCaptureView(view, chosen, available));
                }
                if (!JToken.DeepEquals(selected, recovered))
                {
                    var repaired = (JObject)plan.DeepClone(); repaired["selected"] = recovered; AtomicJson(GuidedPlanPath(sessionId), repaired);
                    warnings.Add("Recovered a saved recording after capture progress was interrupted.");
                }
                return new GuidedCaptureState(views, (string)plan["foot_side"]!, Number(plan["duration_s"]), session.Status != "awaiting_capture", session.TestType == "barefoot");
            }
        }

        public GuidedCaptureState SaveGuidedTake(Guid patientId, Guid sessionId, string manifestJson, string zipPath)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId);
                Require(session.Status == "awaiting_capture", "Completed assessment recordings cannot be replaced.");
                var plan = ReadGuidedPlan(session); Require(plan != null, "Choose guided capture settings before recording.");
                plan = RecoverGuidedSelection(session, plan!);
                var bytes = System.Text.Encoding.UTF8.GetBytes(manifestJson); Require(bytes.Length <= 1024 * 1024, "Capture manifest exceeds 1 MiB.");
                var manifest = WorkflowJson.Read(bytes); ValidateGuidedManifest(manifest, session, plan!);
                var take = manifest["takes"]![0]!; var id = WorkflowJson.Id(take["take_id"]); var view = (string)take["view"]!;
                var target = GuidedTakePath(sessionId, id); var pending = target + ".pending";
                if (Directory.Exists(target))
                {
                    Require(JToken.DeepEquals(ReadRecovered(Path.Combine(target, "manifest.json")), manifest), "This take ID already belongs to different evidence.");
                    ValidateZip(manifest, Path.Combine(target, "media.zip"), target, writeSidecars: false);
                    // A delayed save retry must not undo a newer retake or the practitioner's selection.
                    return GuidedCapture(patientId, sessionId)!;
                }
                else
                {
                    Require(GuidedTakeDirectories(sessionId).Count < MaximumGuidedTakes, "This assessment has 32 saved takes. Start a new assessment for more recordings.");
                    var size = new FileInfo(zipPath).Length; Require(size > 0 && size <= 512L * 1024 * 1024, "Capture ZIP exceeds 512 MiB.");
                    EnsureSpace(size + 128L * 1024 * 1024);
                    if (Directory.Exists(pending)) Directory.Delete(pending, true);
                    Directory.CreateDirectory(pending);
                    var selectionIntentSaved = false;
                    try
                    {
                        using (var input = File.OpenRead(zipPath)) using (var output = File.Create(Path.Combine(pending, "media.zip")))
                        {
                            var buffer = new byte[65536]; long copied = 0; int count;
                            while ((count = input.Read(buffer, 0, buffer.Length)) > 0)
                            { copied += count; Require(copied <= size, "Capture ZIP grew while saving."); output.Write(buffer, 0, count); }
                            output.Flush(true); Require(output.Length == size, "Capture ZIP changed while saving.");
                        }
                        ValidateZip(manifest, Path.Combine(pending, "media.zip"), pending);
                        ValidateGuidedSidecar(ReadFile(Path.Combine(pending, (string)take["frame_metadata"]!["member"]!)), take, plan!);
                        AtomicJson(Path.Combine(pending, "manifest.json"), manifest);
                        var intent = (JObject)plan!.DeepClone();
                        intent["pending_selection"] = new JObject { ["view"] = view, ["take_id"] = id.ToString("D"),
                            ["previous_take_id"] = plan["selected"]![view]?.DeepClone() ?? JValue.CreateNull() };
                        AtomicJson(GuidedPlanPath(sessionId), intent); selectionIntentSaved = true;
                        Directory.Move(pending, target);
                    }
                    finally { if (!selectionIntentSaved && Directory.Exists(pending)) Directory.Delete(pending, true); }
                }
                return GuidedCapture(patientId, sessionId)!;
            }
        }

        public GuidedCaptureState SelectGuidedTake(Guid patientId, Guid sessionId, string view, Guid takeId)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId); Require(session.Status == "awaiting_capture", "Completed assessment recordings cannot change.");
                Require(GuidedViews.Contains(view), "Unsupported guided viewpoint.");
                var state = GuidedCapture(patientId, sessionId); Require(state != null && state.Views.Single(v => v.View == view).TakeIds.Contains(takeId), "Recording does not belong to this patient, assessment and viewpoint.");
                var plan = (JObject)ReadGuidedPlan(session)!.DeepClone(); plan["selected"]![view] = takeId.ToString("D");
                AtomicJson(GuidedPlanPath(sessionId), plan); return GuidedCapture(patientId, sessionId)!;
            }
        }

        public SessionRecord CompleteGuidedCapture(Guid patientId, Guid sessionId, Guid? replayTakeId)
        {
            lock (gate)
            {
                var session = Session(patientId, sessionId); var state = GuidedCapture(patientId, sessionId);
                Require(state != null && state.Complete, "Finish a complete recording from each required viewpoint first.");
                var selected = state!.Views.Select(v => v.SelectedTakeId!.Value).ToArray();
                Require(session.TestType == "barefoot" ? replayTakeId == null : replayTakeId.HasValue && selected.Contains(replayTakeId.Value), "Choose one selected full-body recording for replay.");
                if (state.Sealed)
                {
                    var existing = Capture(session); var existingPrimary = existing["replay_take_id"] == null ? (Guid?)null : WorkflowJson.Id(existing["replay_take_id"]);
                    Require(existingPrimary == replayTakeId, "The saved replay source cannot be replaced."); return session;
                }
                var plan = ReadGuidedPlan(session)!; var takes = ReadGuidedTakes(session, plan);
                var chosen = selected.Select(id => takes[id]).ToArray(); var combined = (JObject)chosen[0].DeepClone();
                combined["takes"] = new JArray(chosen.Select(t => t["takes"]![0]!.DeepClone()));
                combined["capture_completed_at"] = chosen.OrderBy(t => WorkflowJson.Date(t["capture_completed_at"])).Last()["capture_completed_at"]!.DeepClone();
                if (replayTakeId.HasValue) combined["replay_take_id"] = replayTakeId.Value.ToString("D"); else combined.Remove("replay_take_id");
                var paths = selected.Select(id => Path.Combine(GuidedTakePath(sessionId, id), "media.zip")).ToArray();
                var size = CombinedCaptureSize(combined); EnsureSpace(size * 2 + 128L * 1024 * 1024);
                var temporary = Path.Combine(GuidedDirectory(sessionId), "combined.pending.zip");
                try
                {
                    CombineCaptureArchives(paths, temporary, combined);
                    SaveCapture(patientId, sessionId, combined.ToString(Newtonsoft.Json.Formatting.None), temporary);
                    return Session(patientId, sessionId);
                }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
            }
        }

        private JObject? ReadGuidedPlan(SessionRecord session)
        {
            var path = GuidedPlanPath(session.Id); if (!File.Exists(path) && !File.Exists(path + ".bak")) return null;
            var plan = WorkflowJson.Fields(ReadRecovered(path), "schema_version patient_id session_id test_type foot_side duration_s selected", "pending_selection");
            Require((string?)plan["schema_version"] == "1" && WorkflowJson.Id(plan["patient_id"]) == session.PatientId && WorkflowJson.Id(plan["session_id"]) == session.Id && (string?)plan["test_type"] == session.TestType, "Guided capture identity mismatch.");
            Require(new[] { 5.0, 10.0, 15.0 }.Contains(Number(plan["duration_s"])), "Unsupported guided duration.");
            WorkflowJson.Choice(plan["foot_side"], session.TestType == "barefoot" ? new[] { "left", "right" } : new[] { "not_applicable" });
            var selected = WorkflowJson.Fields(plan["selected"], "", "right front rear left");
            foreach (var property in selected.Properties()) WorkflowJson.Id(property.Value);
            return plan;
        }
        private JObject RecoverGuidedSelection(SessionRecord session, JObject plan)
        {
            if (plan["pending_selection"] == null) return plan;
            var intent = WorkflowJson.Fields(plan["pending_selection"], "view take_id previous_take_id");
            var view = WorkflowJson.Choice(intent["view"], GuidedViews); var id = WorkflowJson.Id(intent["take_id"]);
            Guid? previous = intent["previous_take_id"]!.Type == JTokenType.Null ? null : WorkflowJson.Id(intent["previous_take_id"]);
            var target = GuidedTakePath(session.Id, id); var pending = target + ".pending";
            var source = Directory.Exists(target) ? target : pending;
            Require(Directory.Exists(source), "A saved recording could not be recovered. Original camera files remain on this device.");
            var manifest = ReadRecovered(Path.Combine(source, "manifest.json")); ValidateGuidedManifest(manifest, session, plan);
            var take = manifest["takes"]![0]!;
            Require(WorkflowJson.Id(take["take_id"]) == id && (string?)take["view"] == view, "Pending selection differs from saved recording.");
            ValidateZip(manifest, Path.Combine(source, "media.zip"), source, writeSidecars: false);
            ValidateGuidedSidecar(ReadFile(Path.Combine(source, (string)take["frame_metadata"]!["member"]!)), take, plan);
            if (source == pending) Directory.Move(pending, target);
            var recovered = (JObject)plan.DeepClone();
            Guid? current = recovered["selected"]![view] == null ? null : WorkflowJson.Id(recovered["selected"]![view]);
            if (current == previous) recovered["selected"]![view] = id.ToString("D");
            recovered.Remove("pending_selection"); AtomicJson(GuidedPlanPath(session.Id), recovered);
            return recovered;
        }
        private Dictionary<Guid, JObject> ReadGuidedTakes(SessionRecord session, JObject plan)
        {
            var result = new Dictionary<Guid, JObject>();
            foreach (var directory in GuidedTakeDirectories(session.Id))
            {
                var id = Guid.Parse(Path.GetFileName(directory)); var manifest = ReadRecovered(Path.Combine(directory, "manifest.json"));
                ValidateGuidedManifest(manifest, session, plan); var take = manifest["takes"]![0]!;
                Require(WorkflowJson.Id(take["take_id"]) == id, "Saved guided take ID mismatch.");
                ValidateGuidedSidecar(ReadRecovered(Path.Combine(directory, (string)take["frame_metadata"]!["member"]!)), take, plan);
                Require(File.Exists(Path.Combine(directory, "media.zip")), "Saved guided recording is missing."); result.Add(id, manifest);
            }
            return result;
        }
        private static void ValidateGuidedManifest(JObject manifest, SessionRecord session, JObject plan)
        {
            WorkflowValidation.Capture(manifest, session);
            var takes = (JArray)manifest["takes"]!; Require(takes.Count == 1, "Save one independent viewpoint recording at a time.");
            var take = takes[0]!; var foot = session.TestType == "barefoot";
            Require(GuidedViews.Contains((string)take["view"]!) && (string?)take["kind"] == (foot ? "foot_closeup" : "full_body") &&
                (string?)take["side"] == (string?)plan["foot_side"] && (string?)take["condition"] == (foot ? "standing" : session.TestType == "walking" ? "exercise" : "seated"), "Recording differs from the guided capture settings.");
            var duration = Number(take["duration_s"]); Require(duration >= Number(plan["duration_s"]) - 1.0 / 30 - 1e-6 && duration <= Number(plan["duration_s"]) + 1.0 / 30 + 1e-6, "Record the complete selected duration before continuing.");
        }
        private static void ValidateGuidedSidecar(JObject sidecar, JToken take, JObject plan)
        {
            WorkflowValidation.Sidecar(sidecar, (JObject)take);
            var frames = (JArray)sidecar["frames"]!; Require(frames.Count >= 2 && frames.Count <= 600 && ((JArray)sidecar["capture"]!["gaps"]!).Count == 0, "Recording has gaps or an invalid frame count; retake this view.");
            var duration = (double)(Timestamp(frames.Last!["pts_ns"]) - Timestamp(frames.First!["pts_ns"])) / 1e9;
            Require(duration >= Number(plan["duration_s"]) - 1.0 / 30 - 1e-6 && Math.Abs(duration - Number(take["duration_s"])) <= 1e-6, "Recording timing does not cover the selected duration.");
            for (var i = 0; i < frames.Count; i++)
            {
                Require(Boolean(frames[i]!["image_valid"]), "Recording contains invalid images; retake this view.");
                if (i > 0) Require(Timestamp(frames[i]!["pts_ns"]) - Timestamp(frames[i - 1]!["pts_ns"]) <= 100000000, "Recording has an unreported source-time gap; retake this view.");
            }
        }
        private IReadOnlyList<string> GuidedTakeDirectories(Guid sessionId)
        {
            var path = Path.Combine(GuidedDirectory(sessionId), "takes"); if (!Directory.Exists(path)) return System.Array.Empty<string>();
            var entries = Directory.EnumerateDirectories(path).Where(p => Guid.TryParseExact(Path.GetFileName(p), "D", out _)).Take(MaximumGuidedTakes + 1).ToArray();
            Require(entries.Length <= MaximumGuidedTakes, "Guided capture has too many saved recordings."); return entries;
        }
        private string GuidedDirectory(Guid id) => Path.Combine(SessionDirectory(id), "capture-draft");
        private string GuidedPlanPath(Guid id) => Path.Combine(GuidedDirectory(id), "plan.json");
        private string GuidedTakePath(Guid sessionId, Guid takeId) => Path.Combine(GuidedDirectory(sessionId), "takes", takeId.ToString("D"));
    }
}
