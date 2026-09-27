using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using Physio.Workflow;

static class WorkflowChecks
{
    static int checks;
    static void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
    static void Reject(Action action, string name)
    { try { action(); } catch (ArgumentException) { checks++; return; } catch (InvalidDataException) { checks++; return; } throw new Exception(name); }
    static async Task RejectAsync(Func<Task> action, string name)
    { try { await action(); } catch (ProcessingException) { checks++; return; } catch (InvalidDataException) { checks++; return; } throw new Exception(name); }
    static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    static JObject FileEntry(string member, byte[] bytes) => new JObject { ["member"] = member, ["sha256"] = Hash(bytes), ["byte_size"] = bytes.Length };
    static async Task Main()
    {
        var root = Path.Combine(Path.GetTempPath(), "physio-workflow-" + Guid.NewGuid());
        try
        {
            var store = new LocalPatientStore(root);
            var first = store.CreatePatient("Sam"); var second = store.CreatePatient("Sam");
            Check(first.Id != second.Id, "Same-name profiles must be isolated.");
            var session = store.CreateSession(first.Id, "elk");
            Check(store.History(first.Id).Count == 1 && store.History(second.Id).Count == 0, "History isolation.");
            Reject(() => store.Session(second.Id, session.Id), "Cross-patient lookup rejected.");
            Reject(() => store.CreatePatient(" "), "Blank name.");
            Reject(() => store.CreatePatient("Sam\nSmith"), "Control character name.");
            Reject(() => store.CreateSession(Guid.NewGuid(), "elk"), "Unknown patient.");
            Reject(() => store.Session(first.Id, Guid.NewGuid()), "Unknown session.");
            Reject(() => store.OpenResult(first.Id, session.Id), "No result before processing.");
            Check(store.SavedResults(first.Id, session.Id).Count == 0, "No versions before processing.");
            Check(session.Stage == "" && session.Error == "" && !session.ResultId.HasValue, "New session empty state.");
            Reject(() => store.CreateSession(first.Id, "gait"), "Only three tests.");
            var reopened = new LocalPatientStore(root);
            Check(reopened.Patients().Count == 2 && reopened.Session(first.Id, session.Id).Id == session.Id, "Restart preserves IDs/history.");
            Reject(() => ProcessingClient.ValidateEndpoint(new Uri("http://192.168.1.2:8000"), false), "Remote HTTP rejected.");
            Reject(() => ProcessingClient.ValidateEndpoint(new Uri("http://localhost:8000"), false), "Loopback must be explicit.");
            ProcessingClient.ValidateEndpoint(new Uri("http://127.0.0.1:8000"), true); checks++;
            Reject(() => ProcessingClient.ValidateEndpoint(new Uri("https://token@example.com"), false), "URL credentials rejected.");
            Reject(() => ProcessingClient.ValidateEndpoint(new Uri("https://example.com/v1"), false), "API path rejected.");
            var capture = MakeCapture(root, session);
            var manifest = capture.Manifest;
            var wrong = (JObject)manifest.DeepClone(); wrong["patient_id"] = second.Id.ToString();
            Reject(() => store.SaveCapture(first.Id, session.Id, wrong.ToString(), capture.Zip), "Wrong-patient upload blocked.");
            wrong = (JObject)manifest.DeepClone(); wrong["takes"]![0]!["video"]!["member"] = "../private.mp4";
            Reject(() => store.SaveCapture(first.Id, session.Id, wrong.ToString(), capture.Zip), "Capture traversal blocked.");
            wrong = (JObject)manifest.DeepClone(); wrong["takes"]![0]!["video"]!["sha256"] = new string('0', 64);
            Reject(() => store.SaveCapture(first.Id, session.Id, wrong.ToString(), capture.Zip), "Capture hash verified.");
            store.SaveCapture(first.Id, session.Id, manifest.ToString(), capture.Zip);
            Check(store.Session(first.Id, session.Id).Status == "captured", "Capture published.");
            Reject(() => store.SaveCapture(first.Id, session.Id, manifest.ToString(), capture.Zip), "Capture immutable.");
            var takeId = Guid.Parse((string)manifest["takes"]![0]!["take_id"]!);
            Check(File.ReadAllBytes(store.OriginalVideoPath(first.Id, session.Id, takeId)).SequenceEqual(capture.Video), "Original video is exact accepted take.");
            Reject(() => store.OriginalVideoPath(first.Id, session.Id, Guid.NewGuid()), "Other-take original blocked.");
            Check(File.Exists(store.OriginalVideoPath(first.Id, session.Id, takeId)), "Original cache reopens.");
            Check(store.OriginalVideoFrameSeconds(first.Id, session.Id, takeId, 9) == 0.083, "Exact original frame maps to media time independently of source time.");
            Reject(() => store.OriginalVideoFrameSeconds(first.Id, session.Id, takeId, 999), "Missing media frame rejected.");
            Reject(() => store.OriginalVideoFrameSeconds(first.Id, session.Id, takeId, -1), "Negative media frame rejected.");
            var beforeCaptureState = Path.Combine(root, "sessions", session.Id.ToString(), "session.json");
            File.Copy(beforeCaptureState + ".bak", beforeCaptureState, true);
            Check(new LocalPatientStore(root).History(first.Id).Single(s => s.Id == session.Id).Status == "captured", "History recovers published capture after session update crash.");
            Reject(() => store.SaveCapture(first.Id, session.Id, manifest.ToString(), capture.Zip), "Recovered original cannot be overwritten.");
            var scenario = new Scenario(session);
            using (var cancelled = new CancellationTokenSource())
            using (var client = Client(store, scenario, cancelled))
            {
                try { await client.ProcessAsync(first.Id, session.Id, cancellation: cancelled.Token); throw new Exception("Expected cancellation."); }
                catch (OperationCanceledException) { checks++; }
            }
            Check(store.Session(first.Id, session.Id).JobId == null, "Unknown accepted job can resume by stable key.");
            store = new LocalPatientStore(root);
            var updates = new List<string>();
            using (var client = Client(store, scenario))
            {
                var cached = await client.ProcessAsync(first.Id, session.Id, update => updates.Add(update.Stage));
                Check(cached.ResultId == scenario.ResultId, "Correct result saved.");
                Check(cached.LoadReplay() == null, "Unavailable replay remains unavailable.");
                Reject(() => cached.ArtifactPath(Guid.NewGuid()), "Other-result artifact path blocked.");
            }
            Check(scenario.Keys.Count == 2 && scenario.Keys.Distinct().Count() == 1, "Upload retry reuses same idempotency key after restart.");
            Check(updates.Contains("uploading") && updates.Contains("downloading") && updates.Last() == "complete", "Actual stages reported.");
            Check(!store.Session(first.Id, session.Id).CaptureToLoadedSeconds.HasValue, "Cache completion does not claim first rendered frame timing.");
            var timed = store.MarkReplayLoaded(first.Id, session.Id, scenario.ResultId, 12.5);
            Check(timed.CaptureToLoadedSeconds == 12.5 && timed.CaptureTimingBasis == "monotonic", "Actual first-frame timing retained.");
            Check(store.MarkReplayLoaded(first.Id, session.Id, scenario.ResultId, 99).CaptureToLoadedSeconds == 12.5, "Saved timing immutable on history reopen.");
            Reject(() => store.MarkReplayLoaded(first.Id, session.Id, Guid.NewGuid()), "Timing cannot identify other result.");
            Check(store.History(second.Id).Count == 0 && store.OpenResult(first.Id, session.Id).ResultId == scenario.ResultId, "Reopening stays isolated.");
            Check(store.SavedResults(first.Id, session.Id).Single() == scenario.ResultId, "Immutable version listed.");
            var before = scenario.Calls;
            using (var client = Client(store, scenario)) await client.ProcessAsync(first.Id, session.Id);
            Check(before == scenario.Calls, "Cached result reopens without network.");
            var artifact = store.OpenResult(first.Id, session.Id).ArtifactPath(scenario.ArtifactId); File.WriteAllText(artifact, "BAD");
            Reject(() => store.OpenResult(first.Id, session.Id), "Corrupt saved artifact rejected.");
            File.WriteAllBytes(artifact, scenario.Artifact);
            var sessionFile = Path.Combine(root, "sessions", session.Id.ToString(), "session.json");
            File.WriteAllText(sessionFile, "{");
            Check(new LocalPatientStore(root).Session(first.Id, session.Id).Id == session.Id, "Damaged atomic state falls back to last backup.");
            await MalformedResponses(root, store, first.Id);
            await ReplayAndEvidence(root, store, first.Id);
            await RetryAndPolling(root, store, first.Id);
            MicroscopeBundle(root, store, first.Id);
            GuidedCaptureBundle(root, store, first.Id, second.Id);
            Check(!Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Where(f => f.EndsWith(".json")).Any(f => File.ReadAllText(f).Contains("private-token")), "No auth token persisted.");
            Console.WriteLine($"Workflow checks: {checks} passed.");
        }
        finally { Directory.Delete(root, true); }
    }
    static void GuidedCaptureBundle(string root, LocalPatientStore store, Guid patient, Guid otherPatient)
    {
        var session = store.CreateSession(patient, "elk");
        Check(store.GuidedCapture(patient, session.Id) == null, "Legacy/new sessions have no implicit guided draft.");
        var draft = store.BeginGuidedCapture(patient, session.Id);
        Check(draft.Views.Select(v => v.View).SequenceEqual(new[] { "right", "front", "rear", "left" }) && draft.NextView == "right", "Patient-relative guided order.");
        Check(draft.TargetDurationSeconds == 10 && !draft.Complete && !draft.Sealed && draft.FootSide == "not_applicable", "Guided draft starts incomplete with ten-second duration.");
        Reject(() => store.GuidedCapture(otherPatient, session.Id), "Guided draft remains patient isolated.");
        Reject(() => store.CompleteGuidedCapture(patient, session.Id, null), "Incomplete sequence cannot seal.");
        var selected = new Dictionary<string, Guid>();
        foreach (var view in new[] { "right", "front", "rear", "left" })
        {
            var input = MakeGuidedCapture(root, session, view);
            draft = store.SaveGuidedTake(patient, session.Id, input.Manifest.ToString(), input.Zip);
            selected[view] = Guid.Parse((string)input.Manifest["takes"]![0]!["take_id"]!);
            Check(draft.Views.Single(v => v.View == view).SelectedTakeId == selected[view], "Saved take selects its exact original.");
            store = new LocalPatientStore(root);
            Check(store.BeginGuidedCapture(patient, session.Id).Views.Single(v => v.View == view).TakeIds.Single() == selected[view], "Restart keeps each completed view.");
            Check(store.SaveGuidedTake(patient, session.Id, input.Manifest.ToString(), input.Zip).Views.Single(v => v.View == view).TakeIds.Count == 1, "Same take save retry is idempotent.");
        }
        Check(draft.Complete && draft.NextView == null && draft.SuggestedReplayTakeId == selected["right"], "Four views completed without fusing their times.");
        var retake = MakeGuidedCapture(root, session, "right");
        draft = store.SaveGuidedTake(patient, session.Id, retake.Manifest.ToString(), retake.Zip);
        Check(draft.Views[0].TakeIds.Count == 2 && draft.Views[0].SelectedTakeId != selected["right"], "Retake preserves original and selects replacement.");
        draft = store.SelectGuidedTake(patient, session.Id, "right", selected["right"]);
        Check(draft.Views[0].SelectedTakeId == selected["right"], "Practitioner can retain earlier original.");
        Check(store.SaveGuidedTake(patient, session.Id, retake.Manifest.ToString(), retake.Zip).Views[0].SelectedTakeId == selected["right"], "Delayed save retry does not override explicit selection.");
        Reject(() => store.SelectGuidedTake(patient, session.Id, "right", selected["left"]), "Cross-view selection rejected.");
        Reject(() => store.CompleteGuidedCapture(patient, session.Id, Guid.NewGuid()), "Unknown primary rejected.");
        Reject(() => store.CompleteGuidedCapture(patient, session.Id, null), "Movement requires explicit primary.");
        var complete = store.CompleteGuidedCapture(patient, session.Id, selected["front"]);
        var manifest = JObject.Parse(File.ReadAllText(Path.Combine(root, "sessions", session.Id.ToString(), "capture", "manifest.json")));
        Check(complete.Status == "captured" && ((JArray)manifest["takes"]!).Count == 4 && (string?)manifest["replay_take_id"] == selected["front"].ToString(), "Final bundle has four takes and chosen primary only.");
        Check(store.GuidedCapture(patient, session.Id)!.Sealed && store.CompleteGuidedCapture(patient, session.Id, selected["front"]).Status == "captured", "Sealing retry is idempotent.");
        Reject(() => store.CompleteGuidedCapture(patient, session.Id, selected["right"]), "Sealed primary immutable.");
        Reject(() => store.SaveGuidedTake(patient, session.Id, retake.Manifest.ToString(), retake.Zip), "Sealed originals cannot change.");
        foreach (var id in selected.Values) Check(File.Exists(store.OriginalVideoPath(patient, session.Id, id)), "Each chosen original available independently.");
        var invalidSession = store.CreateSession(patient, "rtk"); store.BeginGuidedCapture(patient, invalidSession.Id);
        foreach (var bad in new[] { "short", "interrupted", "gap", "invalid_frame", "wrong_side", "wrong_view", "wrong_condition", "wrong_kind", "duration_lie", "undeclared_gap", "too_long", "hash" })
        {
            var input = MakeGuidedCapture(root, invalidSession, "right", bad);
            Reject(() => store.SaveGuidedTake(patient, invalidSession.Id, input.Manifest.ToString(), input.Zip), "Malformed guided input rejected: " + bad);
            Check(store.GuidedCapture(patient, invalidSession.Id)!.Views.All(v => v.SelectedTakeId == null), "Rejected input never advances progress.");
        }
        var good = MakeGuidedCapture(root, invalidSession, "right"); store.SaveGuidedTake(patient, invalidSession.Id, good.Manifest.ToString(), good.Zip);
        var planPath = Path.Combine(root, "sessions", invalidSession.Id.ToString(), "capture-draft", "plan.json");
        File.Copy(planPath + ".bak", planPath, true);
        Check(new LocalPatientStore(root).GuidedCapture(patient, invalidSession.Id)!.Views[0].SelectedTakeId.HasValue, "Published take recovered after crash before progress update.");
        foreach (var beforePublication in new[] { false, true })
        {
            var recovery = store.CreateSession(patient, "elk"); store.BeginGuidedCapture(patient, recovery.Id);
            var oldTake = MakeGuidedCapture(root, recovery, "right"); store.SaveGuidedTake(patient, recovery.Id, oldTake.Manifest.ToString(), oldTake.Zip);
            var newTake = MakeGuidedCapture(root, recovery, "right"); store.SaveGuidedTake(patient, recovery.Id, newTake.Manifest.ToString(), newTake.Zip);
            var newId = Guid.Parse((string)newTake.Manifest["takes"]![0]!["take_id"]!);
            var recoveryPlan = Path.Combine(root, "sessions", recovery.Id.ToString(), "capture-draft", "plan.json");
            File.Copy(recoveryPlan + ".bak", recoveryPlan, true);
            var published = Path.Combine(root, "sessions", recovery.Id.ToString(), "capture-draft", "takes", newId.ToString());
            if (beforePublication) Directory.Move(published, published + ".pending");
            var restored = new LocalPatientStore(root);
            Check(restored.GuidedCapture(patient, recovery.Id)!.Views[0].SelectedTakeId == newId, "Retake selection intent recovers across publication boundary.");
            Check(restored.SaveGuidedTake(patient, recovery.Id, oldTake.Manifest.ToString(), oldTake.Zip).Views[0].SelectedTakeId == newId, "Older delayed save cannot undo recovered retake.");
        }
        foreach (var duration in new[] { 5, 15 })
        {
            var timed = store.CreateSession(patient, "rtk"); store.BeginGuidedCapture(patient, timed.Id);
            Check(store.BeginGuidedCapture(patient, timed.Id, targetDurationSeconds: duration).TargetDurationSeconds == duration, "Duration adjustable before first saved view.");
            var input = MakeGuidedCapture(root, timed, "right", durationSeconds: duration);
            store.SaveGuidedTake(patient, timed.Id, input.Manifest.ToString(), input.Zip);
            Check(new LocalPatientStore(root).GuidedCapture(patient, timed.Id)!.TargetDurationSeconds == duration, "Duration persists on restart.");
            Reject(() => store.BeginGuidedCapture(patient, timed.Id), "Duration fixed after first recording.");
        }
        var noPlan = store.CreateSession(patient, "elk"); var noPlanInput = MakeGuidedCapture(root, noPlan, "right");
        Reject(() => store.SaveGuidedTake(patient, noPlan.Id, noPlanInput.Manifest.ToString(), noPlanInput.Zip), "Recording requires explicit guided plan.");
        Reject(() => store.BeginGuidedCapture(patient, noPlan.Id, targetDurationSeconds: 0), "Zero recording duration rejected.");
        Reject(() => store.BeginGuidedCapture(patient, noPlan.Id, targetDurationSeconds: double.NaN), "Non-finite duration rejected.");
        var wrongPatient = (JObject)good.Manifest.DeepClone(); wrongPatient["patient_id"] = otherPatient.ToString();
        Reject(() => store.SaveGuidedTake(patient, invalidSession.Id, wrongPatient.ToString(), good.Zip), "Cross-patient guided manifest rejected.");
        var colliding = (JObject)good.Manifest.DeepClone(); colliding["capture_completed_at"] = "2026-01-01T00:00:00Z";
        Reject(() => store.SaveGuidedTake(patient, invalidSession.Id, colliding.ToString(), good.Zip), "Existing take ID cannot acquire different metadata.");
        Reject(() => store.SelectGuidedTake(patient, invalidSession.Id, "other", Guid.NewGuid()), "Unsupported selected viewpoint rejected.");
        var budgetCheck = typeof(LocalPatientStore).GetMethod("CombinedCaptureSize", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!;
        JObject DeclaredFiles(long videoBytes) => new JObject { ["takes"] = new JArray(Enumerable.Range(0, 4).Select(_ => new JObject {
            ["video"] = new JObject { ["byte_size"] = videoBytes }, ["frame_metadata"] = new JObject { ["byte_size"] = 4096 } })) };
        Check((long)budgetCheck.Invoke(null, new object[] { DeclaredFiles(100_000_000) })! > 400_000_000, "Storage reserve uses expanded member sizes plus ZIP headers.");
        try { budgetCheck.Invoke(null, new object[] { DeclaredFiles(150_000_000) }); throw new Exception("Expected expanded-size rejection."); }
        catch (System.Reflection.TargetInvocationException error) when (error.InnerException is InvalidDataException) { checks++; }
        var feet = store.CreateSession(patient, "barefoot"); store.BeginGuidedCapture(patient, feet.Id, "right");
        foreach (var view in new[] { "right", "front", "rear", "left" })
        { var input = MakeGuidedCapture(root, feet, view, footSide: "right"); store.SaveGuidedTake(patient, feet.Id, input.Manifest.ToString(), input.Zip); }
        Reject(() => store.BeginGuidedCapture(patient, feet.Id, "left"), "Foot laterality cannot change within draft.");
        Check(store.GuidedCapture(patient, feet.Id)!.SuggestedReplayTakeId == null, "Foot views do not become fabricated full-body replay.");
        Reject(() => store.CompleteGuidedCapture(patient, feet.Id, selected["front"]), "Foot cannot nominate unrelated body.");
        Check(store.CompleteGuidedCapture(patient, feet.Id, null).Status == "captured", "Four foot views retain selected side and standing condition.");
    }
    static (JObject Manifest, string Zip) MakeGuidedCapture(string root, SessionRecord session, string view, string? failure = null, string footSide = "left", int durationSeconds = 10)
    {
        var input = MakeCapture(root, session); var manifest = input.Manifest; var take = manifest["takes"]![0]!;
        var videoName = (string)take["video"]!["member"]!; var metadataName = (string)take["frame_metadata"]!["member"]!;
        JObject metadata;
        using (var zip = ZipFile.OpenRead(input.Zip)) using (var reader = new StreamReader(zip.GetEntry(metadataName)!.Open())) metadata = JObject.Parse(reader.ReadToEnd());
        var count = failure == "short" || failure == "duration_lie" ? 150 : failure == "too_long" ? 450 : durationSeconds * 30;
        var times = Enumerable.Range(0, count).Select(i => 1000000000L + i * 1000000000L / 30).ToArray();
        metadata["frames"] = new JArray(times.Select((ns, i) => new JObject { ["frame_id"] = i, ["pts_ns"] = ns.ToString(), ["image_valid"] = failure != "invalid_frame" }));
        metadata["media"]!["presentation_time_us"] = new JArray(times.Select(ns => ((ns - times[0]) / 1000).ToString()));
        foreach (var item in new[] { take, metadata["capture"]! })
        { item["view"] = failure == "wrong_view" ? "medial" : view; item["side"] = failure == "wrong_side" ? "bilateral" : session.TestType == "barefoot" ? footSide : "not_applicable"; item["condition"] = failure == "wrong_condition" ? "steady_hold" : session.TestType == "barefoot" ? "standing" : "seated"; }
        if (failure == "undeclared_gap")
        { metadata["frames"] = new JArray(metadata["frames"]!.First!.DeepClone(), metadata["frames"]!.Last!.DeepClone()); metadata["media"]!["presentation_time_us"] = new JArray("0", "9966666"); }
        metadata["capture"]!["interrupted"] = failure == "interrupted";
        if (failure == "gap") metadata["capture"]!["gaps"] = new JArray(new JObject { ["start_pts_ns"] = "1000000001", ["end_pts_ns"] = "1033333332", ["reason"] = "unit test gap" });
        take["kind"] = failure == "wrong_kind" ? "microscope" : session.TestType == "barefoot" ? "foot_closeup" : "full_body";
        take["duration_s"] = failure == "duration_lie" ? 10 : (times.Last() - times[0]) / 1e9;
        if (session.TestType == "barefoot") manifest.Remove("replay_take_id");
        var bytes = Encoding.UTF8.GetBytes(metadata.ToString()); take["frame_metadata"] = FileEntry(metadataName, bytes);
        if (failure == "hash") take["video"]!["sha256"] = new string('0', 64);
        var path = Path.Combine(root, Guid.NewGuid() + ".zip");
        using (var zip = ZipFile.Open(path, ZipArchiveMode.Create))
        { using (var output = zip.CreateEntry(videoName).Open()) output.Write(input.Video); using (var output = zip.CreateEntry(metadataName).Open()) output.Write(bytes); }
        return (manifest, path);
    }
    static void MicroscopeBundle(string root, LocalPatientStore store, Guid patient)
    {
        var original = store.CreateSession(patient, "elk"); var primary = MakeCapture(root, original);
        store.SaveCapture(patient, original.Id, primary.Manifest.ToString(), primary.Zip);
        var next = store.CreateSession(patient, "elk"); var supplement = MakeCapture(root, next, microscopeHold: true);
        store.SaveMicroscopeCapture(patient, next.Id, original.Id, supplement.Manifest.ToString(), supplement.Zip);
        Check(store.Session(patient, next.Id).Status == "captured" && store.Session(patient, original.Id).Status == "captured", "Supplemental session preserves primary.");
        var manifest = JObject.Parse(File.ReadAllText(Path.Combine(root, "sessions", next.Id.ToString(), "capture", "manifest.json")));
        Check(((JArray)manifest["takes"]!).Count == 2 && JToken.DeepEquals(manifest["replay_take_id"], primary.Manifest["replay_take_id"]), "Combined replay remains original primary take.");
        Check(JToken.DeepEquals(manifest["takes"]![0], primary.Manifest["takes"]![0]) && JToken.DeepEquals(manifest["takes"]![1], supplement.Manifest["takes"]![0]), "Source hashes/IDs/durations untouched.");
        Check(File.ReadAllBytes(store.OriginalVideoPath(patient, next.Id, Guid.Parse((string)manifest["takes"]![1]!["take_id"]!))).SequenceEqual(supplement.Video), "Supplement original preserved.");
        Reject(() => store.SaveMicroscopeCapture(patient, original.Id, original.Id, supplement.Manifest.ToString(), supplement.Zip), "Original session cannot be replaced.");
        var wrong = store.CreateSession(patient, "rtk");
        Reject(() => store.SaveMicroscopeCapture(patient, wrong.Id, original.Id, supplement.Manifest.ToString(), supplement.Zip), "Cross-test supplement rejected.");
        var badNext = store.CreateSession(patient, "elk"); var malformed = MakeCapture(root, badNext, microscopeHold: true);
        using (var zip = ZipFile.Open(malformed.Zip, ZipArchiveMode.Update))
        {
            var member = (string)malformed.Manifest["takes"]![0]!["video"]!["member"]!;
            zip.GetEntry(member)!.Delete(); using var output = zip.CreateEntry(member, CompressionLevel.Optimal).Open(); output.Write(new byte[65536]);
        }
        try { store.SaveMicroscopeCapture(patient, badNext.Id, original.Id, malformed.Manifest.ToString(), malformed.Zip); throw new Exception("Expected ZIP preflight rejection."); }
        catch (InvalidDataException error) { Check(error.Message == "Combined ZIP member differs from declared recording.", "Supplemental expansion rejected before copying bytes beyond reserved member size."); }

    }
    static async Task RetryAndPolling(string root, LocalPatientStore store, Guid patient)
    {
        foreach (var behavior in new[] { "poll", "transient", "network", "unauthorized" })
        {
            var session = store.CreateSession(patient, "elk"); var input = MakeCapture(root, session);
            store.SaveCapture(patient, session.Id, input.Manifest.ToString(), input.Zip);
            var scenario = new Scenario(session) { PendingOnCreate = behavior == "poll", TransientResponses = behavior == "transient" ? 2 : 0,
                ThrowOnce = behavior == "network", Unauthorized = behavior == "unauthorized" };
            using var client = Client(store, scenario);
            if (behavior == "unauthorized")
            {
                try { await client.ProcessAsync(patient, session.Id); throw new Exception("Expected unauthorized failure."); }
                catch (ProcessingException e) { Check(e.Code == "UNAUTHORIZED" && !e.Retryable, "Unauthorized error surfaced accurately."); }
                Check(store.Session(patient, session.Id).Status == "retry_required", "Unauthorized recording retained for explicit retry.");
            }
            else
            {
                var progress = new List<ProcessingUpdate>(); await client.ProcessAsync(patient, session.Id, p => progress.Add(p));
                Check(scenario.Keys.Distinct().Count() == 1, "Transient retries preserve idempotency.");
                if (behavior == "poll") Check(progress.Any(p => p.Completed == 1 && p.Total == 2 && p.Unit == "frames" && p.Elapsed >= TimeSpan.Zero && p.Detail == "running"), "Measured server progress preserved during polling.");
                else Check(scenario.Keys.Count >= 2, "Retry actually occurred.");
            }
        }
    }
    static async Task ReplayAndEvidence(string root, LocalPatientStore store, Guid patient)
    {
        var session = store.CreateSession(patient, "elk"); var capture = MakeCapture(root, session, true);
        store.SaveCapture(patient, session.Id, capture.Manifest.ToString(), capture.Zip);
        var scenario = new Scenario(session); scenario.AddReplay();
        scenario.Result["findings"]![0]!["evidence"]!["end_s"] = 0.05;
        scenario.Result["microscopes"]![0]!["evidence"]!["end_s"] = 0.05;
        using (var client = Client(store, scenario))
        {
            var cached = await client.ProcessAsync(patient, session.Id);
            Check(cached.LoadReplay()!.FrameCount == 4, "Full replay downloaded and mapped to source frames.");
            Check((double)cached.Manifest["findings"]![0]!["evidence"]!["end_s"]! == 0.05, "Evidence interval may enclose endpoint frames without exact time equality.");
            Check(cached.LoadReplay()!.Synthetic, "Synthetic provenance retained.");
            Check(cached.ReplayTakeId.HasValue && Directory.Exists(cached.DirectoryPath) && cached.Manifest["findings"] != null, "Cached result interface available.");
            Check(store.OriginalVideoFrameSeconds(patient, session.Id, cached.ReplayTakeId!.Value, 101) == 0.04, "Legacy sidecar media fallback.");
        }
        Check(store.MarkReplayLoaded(patient, session.Id, scenario.ResultId).CaptureTimingBasis == "wall_clock_estimate", "Restart timing identified as wall-clock estimate.");
        Check(store.OpenResult(patient, session.Id).LoadReplay()!.Timeline.SourceTakeId == Guid.Parse((string)capture.Manifest["replay_take_id"]!), "Cached source take verified.");
        var changes = new Action<JObject>[] {
            r => r["findings"]![0]!["method_id"] = "unknown",
            r => r["findings"]![0]!["evidence"]!["take_id"] = Guid.NewGuid().ToString(),
            r => r["findings"]![0]!["evidence"]!["first_frame_id"] = 99,
            r => r["findings"]![0]!["evidence"]!["start_s"] = 0.01,
            r => r["findings"]![0]!["evidence"]!["quality"] = "insufficient",
            r => r["findings"]![0]!["evidence"]!["condition"] = "standing",
            r => r["findings"]![0]!["evidence"]!["end_s"] = 10,
            r => ((JObject)r["findings"]![0]!["evidence"]!).Remove("quality_reason"),
            r => r["findings"]![0]!["highlight_joint_names"] = new JArray("unknown_joint"),
            r => r["findings"]![0]!["highlight_joint_names"] = new JArray("high_tip", "high_tip"),
            r => r["findings"]![0]!["microscope_id"] = Guid.NewGuid().ToString(),
            r => ((JObject)r["findings"]![0]!["metrics"]![0]!).Remove("scale_provenance"),
            r => r["microscopes"]![0]!["original_artifact_id"] = Guid.NewGuid().ToString(),
            r => r["replay"]!["source_take_id"] = Guid.NewGuid().ToString(),
            r => r["created_at"] = "2026-09-26T01:00:00",
            r => r["result_id"] = Guid.Empty.ToString(),
            r => r["artifacts"]![0]!["sha256"] = new string('G',64),
            r => r["features"] = new JArray(),
            r => ((JArray)r["features"]!).Add(r["features"]![0]!.DeepClone()),
            r => ((JArray)r["methods"]!).Add(r["methods"]![0]!.DeepClone()),
            r => ((JArray)r["findings"]!).Add(r["findings"]![0]!.DeepClone()),
            r => ((JArray)r["microscopes"]!).Add(r["microscopes"]![0]!.DeepClone()),
        };
        foreach (var change in changes)
        {
            var malformedSession = store.CreateSession(patient, "elk"); var input = MakeCapture(root, malformedSession, true);
            store.SaveCapture(patient, malformedSession.Id, input.Manifest.ToString(), input.Zip);
            var malformed = new Scenario(malformedSession); malformed.AddReplay(); change(malformed.Result);
            using var client = Client(store, malformed);
            await RejectAsync(() => client.ProcessAsync(patient, malformedSession.Id), "Malformed replay/evidence accepted.");
        }
        foreach (var mismatch in new[] { "byte_size", "sha256", "artifact_id", "missing", "gaps", "invalid_source" })
        {
            var alteredSession = store.CreateSession(patient, "elk"); var input = MakeCapture(root, alteredSession, true);
            store.SaveCapture(patient, alteredSession.Id, input.Manifest.ToString(), input.Zip);
            var altered = new Scenario(alteredSession); altered.AddReplay();
            var descriptor = ((JArray)altered.Result["artifacts"]!).Single(a => (string?)a["role"] == "replay_manifest");
            var id = Guid.Parse((string)descriptor["artifact_id"]!);
            var replay = JObject.Parse(Encoding.UTF8.GetString(altered.Files[id]));
            var binary = (JObject)replay["artifacts"]!["mesh_vertices"]!;
            if (mismatch == "byte_size") binary["byte_size"] = 1;
            else if (mismatch == "sha256") binary["sha256"] = new string('0',64);
            else if (mismatch == "artifact_id") binary["artifact_id"] = altered.ArtifactId.ToString();
            else if (mismatch == "gaps") replay["gaps"] = new JArray();
            else if (mismatch == "invalid_source") { replay["gaps"] = new JArray(); replay["frame_valid"]![2] = true; }
            else replay.Remove("artifacts");
            var bytes = Encoding.UTF8.GetBytes(replay.ToString()); altered.Files[id] = bytes;
            descriptor["byte_size"] = bytes.Length; descriptor["sha256"] = Hash(bytes);
            using var client = Client(store, altered);
            await RejectAsync(() => client.ProcessAsync(patient, alteredSession.Id), "Inner replay descriptor rejected before binary allocation.");
        }
    }
    static ProcessingClient Client(LocalPatientStore store, Scenario scenario, CancellationTokenSource? cancel = null) =>
        new ProcessingClient(store, new Uri("https://processing.example"), "private-token", new FakeTransport(scenario, cancel));

    static async Task MalformedResponses(string root, LocalPatientStore store, Guid patient)
    {
        var changes = new Action<JObject>[] {
            r => r["patient_id"] = Guid.NewGuid().ToString(),
            r => r["result_id"] = Guid.NewGuid().ToString(),
            r => r["job_id"] = Guid.NewGuid().ToString(),
            r => r["protocol_id"] = "rtk",
            r => r["artifacts"]![0]!["artifact_id"] = "../private",
            r => r["artifacts"]![0]!["byte_size"] = 1073741825L,
            r => r["artifacts"]![0]!["sha256"] = new string('0', 64),
            r => ((JArray)r["artifacts"]!).Add(r["artifacts"]![0]!.DeepClone()),
            r => r["methods"]![0]!["settings_artifact_id"] = Guid.NewGuid().ToString(),
            r => r["features"]![0]!["status"] = "available",
            r => r["features"]![2]!["status"] = "available",
            r => r["unexpected"] = true,
        };
        foreach (var change in changes)
        {
            var session = store.CreateSession(patient, "elk"); var input = MakeCapture(root, session);
            store.SaveCapture(patient, session.Id, input.Manifest.ToString(), input.Zip);
            var scenario = new Scenario(session); change(scenario.Result);
            using var client = Client(store, scenario);
            await RejectAsync(() => client.ProcessAsync(patient, session.Id), "Malformed response accepted.");
            Check(store.SavedResults(patient, session.Id).Count == 0, "Rejected result not published.");
        }
        var terminal = store.CreateSession(patient, "elk"); var cap = MakeCapture(root, terminal);
        store.SaveCapture(patient, terminal.Id, cap.Manifest.ToString(), cap.Zip);
        var failed = new Scenario(terminal) { FailJob = true };
        using (var client = Client(store, failed)) await RejectAsync(() => client.ProcessAsync(patient, terminal.Id), "Failed job surfaced.");
        var firstKey = failed.Keys.Single(); failed.FailJob = false; failed.JobId = Guid.NewGuid(); failed.Result["job_id"] = failed.JobId.ToString();
        using (var client = Client(store, failed)) await client.ProcessAsync(patient, terminal.Id, reprocess: true);
        Check(failed.Keys.Last() != firstKey, "Explicit failed-job reprocess uses a new key.");
    }
    static (JObject Manifest, string Zip, byte[] Video) MakeCapture(string root, SessionRecord session, bool useReplay = false, bool microscopeHold = false)
    {
        var take = Guid.NewGuid(); var videoName = Guid.NewGuid() + ".mp4"; var metadataName = Guid.NewGuid() + ".json";
        var video = new byte[] { 0, 0, 0, 16, 102, 116, 121, 112, 105, 115, 111, 109, 0, 0, 0, 0 };
        var sidecar = new JObject { ["schema_version"] = "1.0", ["take_id"] = take.ToString(),
            ["adapter"] = new JObject { ["name"] = "unit-test", ["version"] = "1" },
            ["image"] = new JObject { ["width_px"] = 10, ["height_px"] = 10, ["rotation_degrees"] = 0, ["mirrored"] = false },
            ["camera"] = new JObject { ["id"] = "test", ["calibration_status"] = "unavailable" },
            ["clock"] = new JObject { ["id"] = "source", ["unit"] = "nanoseconds", ["origin_pts_ns"] = "1000000000" },
            ["frames"] = new JArray(new JObject { ["frame_id"] = 4, ["pts_ns"] = "1000000000", ["image_valid"] = true }, new JObject { ["frame_id"] = 9, ["pts_ns"] = "1040000000", ["image_valid"] = true }),
            ["media"] = new JObject { ["binding"] = "indexed_presentation_time_us", ["presentation_time_us"] = new JArray("0", "83000") },
            ["capture"] = new JObject { ["view"] = "front", ["condition"] = "seated", ["side"] = "not_applicable", ["interrupted"] = false, ["gaps"] = new JArray() } };
        if (useReplay)
        {
            sidecar = JObject.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "fixtures", "capture_sidecar.json")));
            take = Guid.Parse((string)sidecar["take_id"]!);
        }
        if (microscopeHold) sidecar["capture"]!["condition"] = "steady_hold";
        var metadata = Encoding.UTF8.GetBytes(sidecar.ToString());
        var manifest = new JObject { ["schema_version"] = "1.0", ["patient_id"] = session.PatientId.ToString(), ["session_id"] = session.Id.ToString(), ["test_type"] = session.TestType,
            ["protocol_id"] = session.TestType, ["protocol_version"] = "1.0", ["capture_completed_at"] = DateTimeOffset.UtcNow.ToString("O"), ["replay_take_id"] = take.ToString(),
            ["takes"] = new JArray(new JObject { ["take_id"] = take.ToString(), ["kind"] = "full_body", ["view"] = "front", ["condition"] = "seated", ["side"] = "not_applicable", ["duration_s"] = useReplay ? 0.2 : 0.04,
                ["video"] = FileEntry(videoName, video), ["frame_metadata"] = FileEntry(metadataName, metadata) }) };
        if (microscopeHold) { manifest.Remove("replay_take_id"); manifest["takes"]![0]!["kind"] = "microscope"; manifest["takes"]![0]!["condition"] = "steady_hold"; }
        var path = Path.Combine(root, Guid.NewGuid() + ".zip");
        using (var zip = ZipFile.Open(path, ZipArchiveMode.Create))
        { using (var output = zip.CreateEntry(videoName).Open()) output.Write(video); using (var output = zip.CreateEntry(metadataName).Open()) output.Write(metadata); }
        return (manifest, path, video);
    }
    sealed class Scenario
    {
        public readonly SessionRecord Session;
        public Guid JobId = Guid.NewGuid(); public readonly Guid ResultId = Guid.NewGuid(); public readonly Guid ArtifactId = Guid.NewGuid();
        public readonly byte[] Artifact = Encoding.UTF8.GetBytes("{}"); public readonly JObject Result;
        public readonly List<string> Keys = new(); public int Calls; public bool FailJob;
        public bool PendingOnCreate; public int TransientResponses; public bool ThrowOnce; public bool Unauthorized;
        public readonly Dictionary<Guid, byte[]> Files = new();
        public Scenario(SessionRecord session)
        {
            Session = session; Files.Add(ArtifactId, Artifact);
            Result = new JObject { ["schema_version"] = "1.0", ["result_id"] = ResultId.ToString(), ["job_id"] = JobId.ToString(), ["session_id"] = session.Id.ToString(), ["patient_id"] = session.PatientId.ToString(), ["test_type"] = session.TestType,
                ["created_at"] = DateTimeOffset.UtcNow.ToString("O"), ["pipeline_version"] = "test", ["protocol_id"] = session.TestType, ["protocol_version"] = "1.0", ["input_digest"] = new string('1', 64), ["validation_status"] = "research_demo_unvalidated",
                ["methods"] = new JArray(new JObject { ["method_id"] = "test", ["name"] = "Transport test", ["version"] = "1", ["settings_artifact_id"] = ArtifactId.ToString() }),
                ["features"] = new JArray(new[] { "replay", "movement", "microscope" }.Select(name => new JObject { ["name"] = name, ["status"] = "unavailable", ["detail"] = "No inference in transport test" })),
                ["findings"] = new JArray(), ["microscopes"] = new JArray(),
                ["artifacts"] = new JArray(new JObject { ["artifact_id"] = ArtifactId.ToString(), ["role"] = "processing_settings", ["media_type"] = "application/json", ["byte_size"] = Artifact.Length, ["sha256"] = Hash(Artifact) }) };
        }
        public void AddReplay()
        {
            var replay = JObject.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "fixtures", "replay_manifest.json")));
            replay["result_id"] = ResultId.ToString();
            Guid Add(string role, string media, byte[] bytes, Guid? chosen = null)
            {
                var id = chosen ?? Guid.NewGuid(); Files.Add(id, bytes);
                ((JArray)Result["artifacts"]!).Add(new JObject { ["artifact_id"] = id.ToString(), ["role"] = role, ["media_type"] = media, ["byte_size"] = bytes.Length, ["sha256"] = Hash(bytes) }); return id;
            }
            foreach (var token in ((JObject)replay["artifacts"]!).Properties())
                Add("replay_binary", "application/octet-stream", File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "fixtures", (string)token.Value["filename"]!)), Guid.Parse((string)token.Value["artifact_id"]!));
            var replayId = Add("replay_manifest", "application/json", Encoding.UTF8.GetBytes(replay.ToString()));
            Result["replay"] = new JObject { ["source_take_id"] = replay["source_take_id"]!.DeepClone(), ["manifest_artifact_id"] = replayId.ToString() };
            Result["features"]![0]!["status"] = "available"; Result["features"]![1]!["status"] = "available"; Result["features"]![2]!["status"] = "available";
            var evidence = new JObject { ["take_id"] = replay["source_take_id"]!.DeepClone(), ["start_s"] = 0, ["end_s"] = 0.04, ["first_frame_id"] = 100, ["last_frame_id"] = 101, ["condition"] = "seated", ["quality"] = "limited", ["quality_reason"] = "Synthetic test" };
            var microscope = Guid.NewGuid(); var video = new byte[] { 0, 0, 0, 16, 102, 116, 121, 112, 105, 115, 111, 109, 0, 0, 0, 0 };
            Result["microscopes"] = new JArray(new JObject { ["microscope_id"] = microscope.ToString(), ["method_id"] = "test", ["evidence"] = evidence.DeepClone(), ["region"] = "synthetic_upper", ["side"] = "not_applicable", ["status"] = "available", ["detail"] = "Synthetic test videos",
                ["original_artifact_id"] = Add("microscope_original", "video/mp4", video).ToString(), ["amplified_artifact_id"] = Add("microscope_amplified", "video/mp4", video).ToString(), ["settings_artifact_id"] = ArtifactId.ToString() });
            Result["findings"] = new JArray(new JObject { ["finding_id"] = Guid.NewGuid().ToString(), ["method_id"] = "test", ["label_code"] = "synthetic", ["label"] = "Synthetic test finding", ["explanation"] = "Transport validation example, not an assessment", ["region"] = "synthetic_upper", ["side"] = "not_applicable", ["evidence"] = evidence.DeepClone(), ["limitations"] = new JArray("Synthetic data"),
                ["metrics"] = new JArray(new JObject { ["name"] = "example", ["value"] = 12.5, ["unit"] = "degrees", ["basis"] = "pose_estimate", ["scale_status"] = "estimated", ["scale_provenance"] = "Synthetic test" }), ["highlight_joint_names"] = new JArray("high_tip"), ["microscope_id"] = microscope.ToString() });
        }
        public JObject Job()
        {
            var value = new JObject { ["job_id"] = JobId.ToString(), ["patient_id"] = Session.PatientId.ToString(), ["session_id"] = Session.Id.ToString(), ["test_type"] = Session.TestType,
                ["status"] = FailJob ? "failed" : "succeeded", ["stage"] = FailJob ? "analysing_test" : "complete", ["created_at"] = "2026-09-26T00:00:00Z", ["updated_at"] = "2026-09-26T00:00:01Z" };
            if (FailJob) value["error"] = new JObject { ["code"] = "PROCESSING_FAILED", ["message"] = "Pipeline failed", ["retryable"] = true }; else value["result_id"] = ResultId.ToString(); return value;
        }
    }
    sealed class FakeTransport : HttpMessageHandler
    {
        readonly Scenario scenario; readonly CancellationTokenSource? cancel;
        public FakeTransport(Scenario scenario, CancellationTokenSource? cancel) { this.scenario = scenario; this.cancel = cancel; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            scenario.Calls++; Check(request.Headers.Authorization?.ToString() == "Bearer private-token", "Auth sent to selected origin.");
            if (request.Method == HttpMethod.Post)
            {
                scenario.Keys.Add(request.Headers.GetValues("Idempotency-Key").Single());
                if (cancel != null) { cancel.Cancel(); throw new OperationCanceledException(cancel.Token); }
                if (scenario.ThrowOnce) { scenario.ThrowOnce = false; throw new HttpRequestException("Simulated disconnect"); }
                if (scenario.TransientResponses > 0)
                {
                    scenario.TransientResponses--;
                    var retry = new HttpResponseMessage(scenario.TransientResponses == 1 ? HttpStatusCode.TooManyRequests : HttpStatusCode.ServiceUnavailable);
                    retry.Headers.RetryAfter = new System.Net.Http.Headers.RetryConditionHeaderValue(TimeSpan.FromSeconds(1)); return Task.FromResult(retry);
                }
                if (scenario.Unauthorized) return Task.FromResult(Json(new JObject { ["request_id"] = Guid.NewGuid().ToString(), ["error"] = new JObject { ["code"] = "UNAUTHORIZED", ["message"] = "Check deployment token", ["retryable"] = false } }, HttpStatusCode.Unauthorized));
                var job = scenario.Job();
                if (scenario.PendingOnCreate) { job["status"] = "running"; job["stage"] = "estimating_movement"; job.Remove("result_id"); job["progress"] = new JObject { ["completed"] = 1, ["total"] = 2, ["unit"] = "frames" }; }
                return Task.FromResult(Json(job, HttpStatusCode.Accepted));
            }
            var path = request.RequestUri!.AbsolutePath;
            if (path.EndsWith("/result")) return Task.FromResult(Json(scenario.Result));
            if (path.Contains("/artifacts/"))
            {
                var id = Guid.Parse(path.Split('/').Last()); var bytes = scenario.Files[id];
                var artifact = ((JArray)scenario.Result["artifacts"]!).Single(a => (string?)a["artifact_id"] == id.ToString());
                var response = new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue((string)artifact["media_type"]!); return Task.FromResult(response);
            }
            return Task.FromResult(Json(scenario.Job()));
        }
        static HttpResponseMessage Json(JObject value, HttpStatusCode status = HttpStatusCode.OK) => new HttpResponseMessage(status) { Content = new StringContent(value.ToString(), Encoding.UTF8, "application/json") };
    }
}
