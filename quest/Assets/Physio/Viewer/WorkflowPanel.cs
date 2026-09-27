#nullable enable
using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using Physio.Capture;
using Physio.Replay;
using Physio.Workflow;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    [DefaultExecutionOrder(20)]
    public sealed partial class WorkflowPanel : MonoBehaviour
    {
        [SerializeField] private FixtureViewer viewer = null!;
        [SerializeField] private GameObject workspaceVisuals = null!;
        [SerializeField] private SpatialCaptureOverlay captureOverlay = null!;
        [SerializeField] private TMP_Text heading = null!;
        [SerializeField] private TMP_Text context = null!;
        [SerializeField] private TMP_Text body = null!;
        [SerializeField] private TMP_Text status = null!;
        [SerializeField] private Button back = null!;
        [SerializeField] private Button options = null!;
        [SerializeField] private Button primary = null!;
        [SerializeField] private Button secondary = null!;
        [SerializeField] private Button[] rows = Array.Empty<Button>();
        [SerializeField] private GameObject replayControls = null!;
        [SerializeField] private RawImage preview = null!;
        [SerializeField] private RawImage amplifiedPreview = null!;
        [SerializeField] private GameObject previewRoot = null!;
        [SerializeField] private TMP_Text previewCaption = null!;

        private enum Screen { Patients, History, Tests, CaptureSetup, Capture, CaptureSummary, Processing, Review, Finding, Feature, Foot, Microscope, Options, Versions, Demo }
        private Screen screen;
        private Screen returnScreen;
        private LocalPatientStore store = null!;
        private QuestTakeRecorder recorder = null!;
        private EvidencePanel evidence = null!;
        private PatientRecord? patient;
        private SessionRecord? session;
        private CachedResult? result;
        private JObject? manifest;
        private JObject? finding;
        private string featureDetail = "";
        private int page;
        private int detailPage;
        private string endpoint = "";
        private string token = "";
        private string captureView = "right";
        private string captureSide = "left";
        private Guid? primarySessionId;
        private bool microscopeHold;
        private string savedTake = "";
        private string attemptedTake = "";
        private string captureSaveError = "";
        private bool consentConfirmed;
        private bool captureWasBusy;
        private bool savingCapture;
        private bool busy;
        private CancellationTokenSource? processingCancellation;
        private TaskCompletionSource<bool>? frameCompletion;
        private readonly ConcurrentQueue<ProcessingUpdate> updates = new();
        private TouchScreenKeyboard? keyboard;
        private Action<string>? keyboardDone;
        private string error = "";
        private bool hadFocus = true;

        private void Start()
        {
            store = new LocalPatientStore(Path.Combine(Application.persistentDataPath, "patients"));
            recorder = viewer.GetComponent<QuestTakeRecorder>() ?? viewer.gameObject.AddComponent<QuestTakeRecorder>();
            evidence = gameObject.AddComponent<EvidencePanel>();
            evidence.Configure(preview, amplifiedPreview, previewCaption);
            back.onClick.AddListener(Back);
            options.onClick.AddListener(OpenOptions);
            endpoint = PlayerPrefs.GetString("physio.processing.url", "");
            if (!string.IsNullOrEmpty(endpoint))
            { try { ProcessingClient.ValidateEndpoint(new Uri(endpoint)); } catch (Exception) { endpoint = ""; PlayerPrefs.DeleteKey("physio.processing.url"); } }
            try { Show(Screen.Patients); }
            catch (Exception)
            { heading.text = "Patient history unavailable"; body.text = "Local records could not be read. Existing files are retained."; status.text = "Check local storage and retry."; SetAction(primary, "Retry local history", () => Show(Screen.Patients)); }
        }

        private void Update()
        {
            var focus = viewer.HasInputFocus;
            if (hadFocus && !focus) evidence.Pause();
            hadFocus = focus;
            captureOverlay.SetVisible(screen == Screen.Capture && focus);
            back.interactable = focus && !busy && !CaptureBusy;
            options.interactable = focus && !busy && !CaptureBusy;
            if (keyboard != null && keyboard.status != TouchScreenKeyboard.Status.Visible)
            {
                var completed = keyboard.status == TouchScreenKeyboard.Status.Done;
                var text = keyboard.text;
                keyboard = null;
                var callback = keyboardDone; keyboardDone = null;
                if (completed && callback != null)
                { try { callback(text); } catch (Exception exception) { status.text = SafeError(exception); } }
            }
            while (updates.TryDequeue(out var update))
            {
                if (screen != Screen.Processing) continue;
                var count = update.Completed.HasValue && update.Total.HasValue
                    ? $" · {update.Completed}/{update.Total} {update.Unit}" : "";
                status.text = $"{update.Stage}{count} · {update.Elapsed.TotalSeconds:0}s since capture";
                body.text = update.Detail;
            }
            if (screen != Screen.Capture) return;
            status.text = !string.IsNullOrEmpty(captureSaveError) ? captureSaveError : string.IsNullOrEmpty(recorder.Error) ? recorder.Status : recorder.Error;
            UpdateCaptureOverlay();
            if (captureWasBusy && !CaptureBusy) RenderCapture();
            captureWasBusy = CaptureBusy;
            var captured = recorder.LastCapture;
            if (captured == null || attemptedTake == captured.TakeId.ToString()) return;
            if (patient == null || session == null) return;
            if (captured.PatientId.ToString() != patient.Id.ToString() || captured.SessionId.ToString() != session.Id.ToString()) return;
            attemptedTake = captured.TakeId.ToString();
            PersistCapture(captured);
        }

        private bool CaptureBusy => savingCapture || recorder != null && (recorder.IsPreparing || recorder.IsRecording || recorder.IsFinalizing);

        public void OpenOptions()
        {
            if (busy || CaptureBusy) return;
            if (screen == Screen.Options) { Show(returnScreen); return; }
            returnScreen = screen;
            viewer.PauseReplay();
            Show(Screen.Options);
        }

        private void Show(Screen next, bool resetPage = true)
        {
            if (CaptureBusy && next != Screen.Capture) { status.text = "Stop and save the active recording first."; return; }
            screen = next;
            workspaceVisuals.SetActive(next != Screen.Capture);
            captureOverlay.SetVisible(next == Screen.Capture && viewer.HasInputFocus);
            if (resetPage) page = 0;
            evidence.Stop();
            viewer.PauseReplay();
            viewer.Highlight(Array.Empty<string>());
            var matchingFinding = next == Screen.Finding && finding != null && result?.ReplayTakeId?.ToString() == (string?)finding["evidence"]?["take_id"];
            GetComponent<HandReplayPanel>().ShowTimeline((next == Screen.Review && result?.ReplayTakeId != null) || matchingFinding || next == Screen.Demo);
            viewer.SetReplayVisible((next == Screen.Review && result?.ReplayTakeId != null) || matchingFinding || next == Screen.Demo ||
                (next == Screen.Options && ((returnScreen == Screen.Review && result?.ReplayTakeId != null) || returnScreen == Screen.Demo)));
            previewRoot.SetActive(false);
            amplifiedPreview.transform.parent.gameObject.SetActive(false);
            foreach (var row in rows) row.gameObject.SetActive(false);
            SetAction(primary, "", null); SetAction(secondary, "", null);
            body.text = "";
            SetBodyHeight(next == Screen.Review ? 56 : next == Screen.Finding || next == Screen.Feature ? 300 : next == Screen.Capture || next == Screen.Microscope || next == Screen.Foot ? 96 : 150);
            status.text = error; error = "";
            context.text = patient == null ? "LOCAL PATIENTS · QUEST 3" : patient.DisplayName +
                (session == null ? " · Patient history" : $"\n{ReviewEvidence.TestName(session.TestType)} · {session.CreatedAt.ToLocalTime():MMM d, HH:mm}");
            back.gameObject.SetActive(next != Screen.Patients);
            switch (next)
            {
                case Screen.Patients: RenderPatients(); break;
                case Screen.History: RenderHistory(); break;
                case Screen.Tests: RenderTests(); break;
                case Screen.CaptureSetup: RenderCaptureSetup(); break;
                case Screen.Capture: RenderCapture(); break;
                case Screen.CaptureSummary: RenderCaptureSummary(); break;
                case Screen.Processing: RenderProcessing(); break;
                case Screen.Review: RenderReview(); break;
                case Screen.Finding: RenderFinding(); break;
                case Screen.Feature: heading.text = "Feature availability"; Detail(featureDetail); break;
                case Screen.Foot: RenderFoot(); break;
                case Screen.Microscope: RenderMicroscope(); break;
                case Screen.Options: RenderOptions(); break;
                case Screen.Versions: RenderVersions(); break;
                case Screen.Demo:
                    heading.text = "Replay interaction lab";
                    body.text = "AUTHORED SYNTHETIC DEMO\nUse the handles to move and resize. This body is not a participant or assessment.";
                    break;
            }
        }

        private void RenderPatients()
        {
            heading.text = "Your patients";
            var list = store.Patients();
            body.text = list.Count == 0 ? "Create a local patient profile to begin a dated assessment." : "Choose a patient to view saved tests or start a new capture.";
            List(list.Select(p => (p.DisplayName + " · " + p.Id.ToString("N").Substring(0, 6), (Action)(() =>
            { patient = p; session = null; result = null; manifest = null; Show(Screen.History); }))).ToArray());
            SetAction(primary, "New patient", () => Keyboard("Patient display name", false, name =>
            { patient = store.CreatePatient(name); session = null; result = null; Show(Screen.History); }));
        }

        private void RenderHistory()
        {
            if (patient == null) { Show(Screen.Patients); return; }
            heading.text = "Saved assessments";
            var list = store.History(patient.Id);
            body.text = list.Count == 0 ? "No tests yet. Each new assessment keeps its own recording and result." : "Select a dated test. Saved results reopen exactly as processed.";
            List(list.Select(s => ($"{s.CreatedAt.ToLocalTime():MMM d · HH:mm}   {s.TestType.ToUpperInvariant()}   {s.Status}",
                (Action)(() => OpenSession(s)))).ToArray());
            SetAction(primary, "New assessment", () => { session = null; result = null; manifest = null; Show(Screen.Tests); });
        }

        private async void OpenSession(SessionRecord selected, Guid? version = null)
        {
            session = selected; result = null; manifest = null;
            primarySessionId = null; microscopeHold = false;
            savedTake = attemptedTake = captureSaveError = "";
            var chosenVersion = version ?? selected.ResultId;
            if (chosenVersion.HasValue)
            {
                busy = true;
                Show(Screen.Processing);
                heading.text = "Opening saved assessment";
                try
                {
                    var loaded = await Task.Run(() => store.OpenResult(selected.PatientId, selected.Id, chosenVersion));
                    await BindResult(loaded, markFirstDisplay: chosenVersion == selected.ResultId && !selected.CaptureToLoadedSeconds.HasValue);
                }
                catch (Exception exception)
                { busy = false; if (this == null) return; error = SafeError(exception); Show(Screen.History); }
                return;
            }
            busy = true;
            status.text = "Opening saved capture progress…";
            try
            {
                var restored = await Task.Run(() => store.GuidedCapture(selected.PatientId, selected.Id));
                if (this == null || patient?.Id != selected.PatientId || session?.Id != selected.Id) return;
                guidedCapture = restored;
                if (guidedCapture != null) { captureSide = SpatialCapturePresentation.FootSide(guidedCapture.FootSide); targetDurationSeconds = guidedCapture.TargetDurationSeconds; }
                consentConfirmed = false;
                busy = false;
                Show(selected.Status == "awaiting_capture" ? guidedCapture?.Complete == true ? Screen.CaptureSummary : Screen.CaptureSetup : Screen.Processing);
            }
            catch (Exception exception)
            { busy = false; if (this == null || patient?.Id != selected.PatientId || session?.Id != selected.Id) return; error = "Saved capture progress could not be opened. Original files are retained. " + SafeError(exception); Show(Screen.History); }
            finally { busy = false; }
        }

        private void RenderTests()
        {
            heading.text = "Choose an assessment";
            body.text = "Three supported tests. Findings remain specific to the selected test and original recording.";
            var tests = new[] { "elk", "rtk", "barefoot" };
            for (var i = 0; i < tests.Length; i++)
            {
                var type = tests[i];
                SetRow(i, ReviewEvidence.TestName(type), () =>
                {
                    session = store.CreateSession(patient!.Id, type); consentConfirmed = false;
                    primarySessionId = null; microscopeHold = false;
                    guidedCapture = null; targetDurationSeconds = 10; captureView = "right"; captureSide = "left"; replayView = "right";
                    savedTake = attemptedTake = captureSaveError = lastSavedView = ""; Show(Screen.CaptureSetup);
                });
            }
        }

        private void BeginMicroscopeCapture()
        {
            if (patient == null || session == null || CaptureBusy || busy) return;
            primarySessionId = session.Id;
            session = store.CreateSession(patient.Id, session.TestType);
            microscopeHold = true; guidedCapture = null; targetDurationSeconds = 10; lastSavedView = "";
            consentConfirmed = false;
            savedTake = attemptedTake = captureSaveError = "";
            Show(Screen.Capture);
        }

        private void RenderProcessing()
        {
            heading.text = busy ? "Processing your capture" : "Ready to process";
            body.text = "Original recordings stay on this device. The configured service receives this assessment only. Real stages and elapsed time appear here.";
            if (session != null && !string.IsNullOrEmpty(session.Error)) body.text = session.Error;
            SetAction(primary, string.IsNullOrWhiteSpace(endpoint) || string.IsNullOrWhiteSpace(token) ? "Connect service" : "Process / retry",
                busy ? null : string.IsNullOrWhiteSpace(endpoint) || string.IsNullOrWhiteSpace(token) ? (Action)OpenOptions : StartProcessing);
            SetAction(secondary, "Patient history", busy ? null : (Action)(() => Show(Screen.History)));
        }

        private void StartProcessing() => ProcessSavedCapture(false);

        private async void ProcessSavedCapture(bool forceNewVersion)
        {
            if (busy || session == null || patient == null) return;
            if (string.IsNullOrWhiteSpace(endpoint) || string.IsNullOrWhiteSpace(token))
            { if (screen == Screen.Options) status.text = "Set the service URL and access token first."; else OpenOptions(); return; }
            busy = true;
            Show(Screen.Processing);
            processingCancellation = new CancellationTokenSource();
            var patientId = patient.Id; var sessionId = session.Id; var retry = forceNewVersion || session.Status == "failed";
            try
            {
                using var client = new ProcessingClient(store, new Uri(endpoint), token);
                var loaded = await Task.Run(() => client.ProcessAsync(patientId, sessionId, update => updates.Enqueue(update), processingCancellation.Token, reprocess: retry));
                if (this == null) return;
                session = store.Session(patientId, sessionId);
                await BindResult(loaded, markFirstDisplay: true);
            }
            catch (OperationCanceledException) { busy = false; }
            catch (Exception exception)
            {
                busy = false;
                if (this == null) return;
                try { session = store.Session(patientId, sessionId); }
                catch (Exception) { Debug.LogWarning("PHYSIO_SESSION_RELOAD_FAILED"); }
                error = "Processing could not finish. " + SafeError(exception);
                Show(Screen.Processing);
            }
            finally { processingCancellation?.Dispose(); processingCancellation = null; }
        }

        private async Task BindResult(CachedResult loaded, bool markFirstDisplay = false)
        {
            var data = await Task.Run(loaded.LoadReplay);
            if (this == null) return;
            result = loaded; manifest = loaded.Manifest; finding = null;
            if (data != null) viewer.LoadReplay(data); else viewer.ClearReplay();
            Show(Screen.Review);
            if (markFirstDisplay && patient != null && session != null)
            {
                frameCompletion = new TaskCompletionSource<bool>();
                StartCoroutine(AfterRenderedFrame(frameCompletion));
                await frameCompletion.Task;
                frameCompletion = null;
                if (this == null) return;
                var patientId = patient.Id; var sessionId = session.Id;
                var capture = recorder.LastCapture;
                var displayedTicks = System.Diagnostics.Stopwatch.GetTimestamp();
                session = await Task.Run(() =>
                {
                    double? elapsed = null;
                    var current = store.Session(patientId, sessionId);
                    if (capture != null && !capture.Interrupted && capture.PatientId == patientId.ToString() && capture.SessionId == sessionId.ToString())
                    {
                        var accepted = store.Capture(current);
                        var candidate = JObject.Parse(capture.ManifestJson);
                        var selectedTakes = accepted["takes"]!.Select(t => Guid.Parse((string)t["take_id"]!)).ToArray();
                        var candidateEnd = DateTimeOffset.Parse((string)candidate["capture_completed_at"]!, System.Globalization.CultureInfo.InvariantCulture);
                        var acceptedEnd = DateTimeOffset.Parse((string)accepted["capture_completed_at"]!, System.Globalization.CultureInfo.InvariantCulture);
                        if (SpatialCapturePresentation.LatestCaptureIsSelected(Guid.Parse(capture.TakeId), capture.Interrupted,
                            capture.CaptureCompletedStopwatchTicks, candidateEnd, selectedTakes, acceptedEnd))
                            elapsed = (displayedTicks - capture.CaptureCompletedStopwatchTicks) / (double)System.Diagnostics.Stopwatch.Frequency;
                    }
                    return store.MarkReplayLoaded(patientId, sessionId, loaded.ResultId, elapsed);
                });
                if (this == null) return;
                RenderReview();
            }
            busy = false;
        }

        private static IEnumerator AfterRenderedFrame(TaskCompletionSource<bool> completion)
        { yield return new WaitForEndOfFrame(); completion.TrySetResult(true); }

        private void RenderReview()
        {
            heading.text = result?.ResultId == session?.ResultId ? "Review recording" : "Review saved version";
            if (manifest == null) { body.text = "No validated result is loaded."; return; }
            body.text = $"RESEARCH DEMO · UNVALIDATED\n{(result?.ResultId == session?.ResultId ? "Latest result" : "Previous saved result")} · {result?.ResultId.ToString("N").Substring(0, 8)}";
            var findings = (JArray)manifest["findings"]!;
            var choices = findings.Cast<JObject>().Select(f => ((string)f["label"]!, (Action)(() =>
            { finding = f; detailPage = 0; Show(Screen.Finding); }))).ToList();
            choices.AddRange(((JArray)manifest["features"]!).Select(f => ($"{f["name"]} · {f["status"]}", (Action)(() =>
            { featureDetail = $"{f["name"]} · {f["status"]}\n{f["detail"]}"; detailPage = 0; Show(Screen.Feature); }))));
            List(choices.ToArray(), 2);
            if (findings.Count == 0) status.text = session?.TestType == "barefoot"
                ? "Foot analysis unavailable. Automatic foot landmarks and calibrated measurements are not available for this recording."
                : "Movement findings unavailable. This recording has not been assessed for exercise errors.";
            SetAction(primary, session?.TestType == "barefoot" ? "Foot assessment" : "Motion microscope", () => Show(session?.TestType == "barefoot" ? Screen.Foot : Screen.Microscope));
            SetAction(secondary, "History", () => { session = null; Show(Screen.History); });
            if (result?.ResultId == session?.ResultId && session?.CaptureToLoadedSeconds is double elapsed) status.text = (status.text + $"\n{elapsed:0.0}s capture to first display" + (session.CaptureTimingBasis == "monotonic" ? "" : " · wall-clock estimate")).Trim();
        }

        private void RenderFinding()
        {
            if (finding == null || result == null) { Show(Screen.Review); return; }
            heading.text = (string)finding["label"]!;
            var interval = finding["evidence"]!;
            var metrics = finding["metrics"] is JArray values ? string.Join("\n", values.Select(m =>
                $"{m["name"]}: {m["value"]} {m["unit"]} · {m["basis"]} · scale {m["scale_status"]} {m["scale_provenance"]}")) : "";
            var text = $"{finding["label"]}\n{finding["explanation"]}\n\n{finding["region"]} · {finding["side"]} · {interval["condition"]}\n" +
                $"Source {interval["take_id"]}\n{interval["start_s"]}–{interval["end_s"]}s · quality {interval["quality"]}\n" +
                $"{interval["quality_reason"]}\n{metrics}\n" + string.Join("\n", finding["limitations"]!.Select(v => (string)v!));
            var methodId = (string?)finding["method_id"];
            var method = manifest?["methods"]?.FirstOrDefault(m => (string?)m["method_id"] == methodId);
            if (method != null) text += $"\nMethod: {method["name"]} · {method["version"]}";
            var takeId = Guid.Parse((string)interval["take_id"]!);
            if (result.ReplayTakeId == takeId)
                viewer.SelectFinding(new FindingInterval(takeId, (double)interval["start_s"]!, (double)interval["end_s"]!),
                    finding["highlight_joint_names"]?.Values<string>().Where(name => name != null).Select(name => name!).ToArray() ?? Array.Empty<string>());
            Detail(text);
            SetAction(primary, "Open original evidence", () => OpenEvidence(finding));
            SetAction(secondary, "Motion microscope", () => Show(Screen.Microscope));
        }

        private async void OpenEvidence(JObject selected)
        {
            busy = true;
            try
            {
                viewer.PauseReplay();
                var interval = (JObject)selected["evidence"]!;
                var take = Guid.Parse((string)interval["take_id"]!);
                var same = ReviewEvidence.CanSeek(result!.ReplayTakeId, take, (double)interval["start_s"]!, (double)interval["end_s"]!);
                if (same)
                {
                    viewer.SetReplayVisible(true);
                    viewer.SelectFinding(new FindingInterval(take, (double)interval["start_s"]!, (double)interval["end_s"]!),
                        selected["highlight_joint_names"]?.Values<string>().Where(name => name != null).Select(name => name!).ToArray() ?? Array.Empty<string>());
                }
                else viewer.SetReplayVisible(false);
                previewRoot.SetActive(true);
                foreach (var row in rows) row.gameObject.SetActive(false);
                SetBodyHeight(56);
                body.text = "Original source evidence · numerical measurements remain unamplified.";
                status.text = same ? "Matching recording · replay paused at evidence start" : "Separate recording · hologram paused";
                status.text = "Opening original recording…";
                var patientId = patient!.Id; var sessionId = session!.Id;
                var sourceStart = (double)interval["start_s"]!; var sourceEnd = (double)interval["end_s"]!;
                var firstFrame = (long)interval["first_frame_id"]!; var lastFrame = (long)interval["last_frame_id"]!;
                var media = await Task.Run(() => (
                    Path: store.OriginalVideoPath(patientId, sessionId, take),
                    Start: store.OriginalVideoFrameSeconds(patientId, sessionId, take, firstFrame),
                    End: store.OriginalVideoFrameSeconds(patientId, sessionId, take, lastFrame)));
                if (this == null) return;
                evidence.OpenOriginal(media.Path, take, sourceStart, sourceEnd, same, media.Start, media.End);
                SetAction(primary, "Play / pause footage", evidence.TogglePlay);
                SetAction(secondary, "Restart footage", evidence.Restart);
            }
            catch (Exception exception) { status.text = SafeError(exception); }
            finally { busy = false; }
        }

        private void RenderFoot()
        {
            heading.text = "Barefoot assessment";
            body.text = "Select a foot finding to inspect side, view, condition, scale and method.";
            var list = manifest?["findings"] as JArray;
            var choices = list == null ? new List<(string, Action)>() : list.Cast<JObject>().Select(f => ($"{f["side"]} · {f["label"]}", (Action)(() =>
            { finding = f; detailPage = 0; Show(Screen.Finding); }))).ToList();
            var foot = manifest?["features"]?.FirstOrDefault(f => (string?)f["name"] == "foot");
            if (foot != null) choices.Add(($"Foot analysis · {foot["status"]}", () =>
            { featureDetail = $"Foot analysis · {foot["status"]}\n{foot["detail"]}"; detailPage = 0; Show(Screen.Feature); }));
            List(choices.ToArray(), 3);
            SetAction(primary, "Motion microscope", () => Show(Screen.Microscope));
            status.text = "Standing evidence does not establish gait. See each metric's scale and method.";
        }

        private void RenderMicroscope()
        {
            heading.text = "Motion microscope";
            var items = manifest?["microscopes"] as JArray;
            body.text = "Compare original and amplified pixels from one source interval. Measurements always use original evidence.";
            if (items == null || items.Count == 0)
            {
                var feature = manifest?["features"]?.FirstOrDefault(f => (string?)f["name"] == "microscope");
                SetBodyHeight(300);
                Detail("Unavailable · " + ((string?)feature?["detail"] ?? "No microscope output for this result."));
                SetRow(1, "Capture steady hold for microscope", BeginMicroscopeCapture); return;
            }
            List(items.Cast<JObject>().Select(m => ($"{m["region"]} · {m["side"]} · {m["status"]}", (Action)(() =>
            {
                body.text = "Original and amplified view of the selected interval.";
                if ((string?)m["status"] != "available")
                { foreach (var row in rows) row.gameObject.SetActive(false); SetBodyHeight(300); Detail((string)m["detail"]!); status.text = "Unavailable for this interval."; return; }
                viewer.PauseReplay(); viewer.SetReplayVisible(false);
                previewRoot.SetActive(true);
                foreach (var row in rows) row.gameObject.SetActive(false);
                evidence.OpenMicroscope(result!, m);
                SetRow(0, "Method and processing detail", () => { featureDetail = (string)m["detail"]!; detailPage = 0; Show(Screen.Feature); });
                SetAction(primary, "Play / pause footage", evidence.TogglePlay);
                SetAction(secondary, "Restart footage", evidence.Restart);
                status.text = "Original + amplified · same source interval · hologram paused";
            }))).ToArray(), 3);
            SetRow(3, "Capture steady hold for microscope", BeginMicroscopeCapture);
            SetAction(primary, "Play / pause footage", null);
            SetAction(secondary, "Restart footage", null);
        }

        private void RenderOptions()
        {
            heading.text = "Workspace options";
            body.text = $"Processing service: {(string.IsNullOrEmpty(endpoint) ? "not connected" : endpoint)}\n" +
                $"Access token: {(string.IsNullOrEmpty(token) ? "not entered" : "set for this app session")}\nDisplay changes never alter stored measurements.";
            var actions = new (string, Action)[]
            {
                ("Set HTTPS service URL", () => Keyboard("https://your-service", false, value =>
                { var uri = new Uri(value.Trim()); ProcessingClient.ValidateEndpoint(uri); endpoint = uri.AbsoluteUri.TrimEnd('/'); PlayerPrefs.SetString("physio.processing.url", endpoint); PlayerPrefs.Save(); Show(Screen.Options); })),
                ("Enter access token", () => Keyboard("Service access token", true, value => { token = value.Trim(); Show(Screen.Options); })),
                ("Bring controls here", () => { viewer.BringPanelToView(); captureOverlay.PlaceSurfaces(); }),
                ("Reset replay placement", viewer.ResetReplayPlacement),
                ("Toggle skeleton", viewer.ToggleSkeletonVisibility),
                ("Toggle body opacity", viewer.ToggleBodyOpacity),
                ("Replay smaller", viewer.ScaleReplayDown),
                ("Replay larger", viewer.ScaleReplayUp),
                ("Open synthetic interaction lab", () => { patient = null; session = null; result = null; manifest = null; viewer.LoadDemo(); Show(Screen.Demo); })
            };
            var items = actions.ToList();
            if (session != null && patient != null)
            {
                items.Insert(0, ("Saved result versions", () => Show(Screen.Versions)));
                if (session.Status == "loaded" || session.Status == "ready" || session.Status == "failed")
                    items.Insert(0, ("Reprocess saved capture · new version", () =>
                    { session = store.Session(patient.Id, session.Id); ProcessSavedCapture(true); }));
            }
            List(items.ToArray());
            SetAction(primary, "Resume", () => Show(returnScreen));
        }

        private void RenderVersions()
        {
            heading.text = "Saved result versions";
            if (patient == null || session == null) { body.text = "Choose a dated assessment first."; return; }
            session = store.Session(patient.Id, session.Id);
            var versions = store.SavedResults(patient.Id, session.Id).OrderByDescending(id => id == session.ResultId).ToArray();
            body.text = versions.Length == 0 ? "No saved result yet." : "Each result retains its own evidence and methods. Latest is marked explicitly.";
            List(versions.Select(id => ($"{(id == session.ResultId ? "Latest" : "Previous")} · {id.ToString("N").Substring(0, 12)}",
                (Action)(() => OpenSession(store.Session(patient.Id, session.Id), id)))).ToArray());
        }

        private void Detail(string text)
        {
            var pages = ReviewEvidence.Pages(text);
            detailPage = Math.Min(detailPage, pages.Length - 1);
            body.text = pages[detailPage];
            if (pages.Length > 1) SetRow(0, $"More detail · {detailPage + 1}/{pages.Length}", () => { detailPage = (detailPage + 1) % pages.Length; if (screen == Screen.Finding) RenderFinding(); else Detail(text); });
        }

        private void List((string Label, Action Action)[] items, int size = 4)
        {
            size = Math.Min(size, rows.Length);
            var paginated = items.Length > size;
            var contentSize = paginated ? Math.Max(1, size - 1) : size;
            var count = Math.Max(1, (items.Length + contentSize - 1) / contentSize);
            page = Math.Min(page, count - 1);
            for (var i = 0; i < contentSize && page * contentSize + i < items.Length; i++)
            { var item = items[page * contentSize + i]; SetRow(i, item.Label, item.Action); }
            if (paginated) SetRow(size - 1, $"Next page · {page + 1}/{count}", () => { page = (page + 1) % count; Show(screen, false); });
        }

        private void Back()
        {
            if (busy || CaptureBusy) { status.text = "Finish the active capture or processing before leaving."; return; }
            error = "";
            switch (screen)
            {
                case Screen.Options: Show(returnScreen); break;
                case Screen.Versions: case Screen.Finding: case Screen.Feature: case Screen.Foot: case Screen.Microscope: Show(Screen.Review); break;
                case Screen.Review: case Screen.CaptureSetup: case Screen.Capture: case Screen.CaptureSummary: case Screen.Processing: case Screen.Tests:
                    session = null; result = null; manifest = null; Show(Screen.History); break;
                default: patient = null; session = null; result = null; manifest = null; Show(Screen.Patients); break;
            }
        }

        private void Keyboard(string placeholder, bool secure, Action<string> callback)
        {
            if (!TouchScreenKeyboard.isSupported) { status.text = "System keyboard unavailable. Enable the Quest system keyboard in project settings."; return; }
            viewer.PauseReplay();
            keyboardDone = callback;
            keyboard = TouchScreenKeyboard.Open("", TouchScreenKeyboardType.Default, false, false, secure, false, placeholder, secure ? 512 : 160);
        }

        private void SetBodyHeight(float height)
        { var layout = body.GetComponent<LayoutElement>(); layout.minHeight = layout.preferredHeight = height; }

        private void SetRow(int index, string label, Action action) => SetAction(rows[index], label, action);
        private readonly Dictionary<Button, (TMP_Text Label, Action? Action)> buttonActions = new();
        private void SetAction(Button button, string label, Action? action)
        {
            button.gameObject.SetActive(label.Length > 0);
            if (!buttonActions.TryGetValue(button, out var binding))
            {
                binding = (button.GetComponentsInChildren<TMP_Text>(true).First(t => t.name == "Label"), null);
                button.onClick.AddListener(() => { var current = buttonActions[button].Action; if (current != null) Safe(current); });
            }
            buttonActions[button] = (binding.Label, action);
            if (binding.Label.text != label) binding.Label.text = label;
            button.interactable = action != null;
        }
        private void Safe(Action action)
        {
            if (busy || (!viewer.HasInputFocus && keyboard == null)) return;
            try { action(); }
            catch (Exception exception) { status.text = SafeError(exception); }
        }
        private static string SafeError(Exception exception) => exception is ArgumentException || exception is InvalidDataException
            ? exception.Message : "The operation failed. The saved recording is retained; try again or check the service.";
        private void OnDestroy() { processingCancellation?.Cancel(); frameCompletion?.TrySetCanceled(); evidence?.Stop(); token = ""; }
    }
}
