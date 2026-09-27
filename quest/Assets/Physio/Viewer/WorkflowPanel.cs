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
        [SerializeField] private RectTransform workspaceCanvas = null!;
        [SerializeField] private RectTransform workspaceBackplate = null!;
        [SerializeField] private Transform workspaceHandle = null!;
        [SerializeField] private SpatialCaptureOverlay captureOverlay = null!;
        [SerializeField] private TMP_Text heading = null!;
        [SerializeField] private TMP_Text context = null!;
        [SerializeField] private TMP_Text body = null!;
        [SerializeField] private ScrollRect? bodyScroll;
        [SerializeField] private TMP_Text status = null!;
        [SerializeField] private GoataScoreGauge? goataScoreGauge;
        [SerializeField] private Button back = null!;
        [SerializeField] private Button options = null!;
        [SerializeField] private Button primary = null!;
        [SerializeField] private Button secondary = null!;
        [SerializeField] private Button[] rows = Array.Empty<Button>();
        [SerializeField] private GameObject listPager = null!;
        [SerializeField] private Button previousPage = null!;
        [SerializeField] private Button nextPage = null!;
        [SerializeField] private GameObject replayControls = null!;
        [SerializeField] private RawImage preview = null!;
        [SerializeField] private RawImage amplifiedPreview = null!;
        [SerializeField] private GameObject previewRoot = null!;
        [SerializeField] private TMP_Text previewCaption = null!;
        [SerializeField] private GameObject reviewTabs = null!;
        [SerializeField] private Button observationsTab = null!;
        [SerializeField] private Button assessmentTab = null!;
        [SerializeField] private Button previousObservations = null!;
        [SerializeField] private Button nextObservations = null!;

        private enum Screen { Patients, History, Tests, CaptureSetup, Capture, CaptureSummary, Processing, Review, Finding, Feature, Foot, Microscope, Options, Versions, Demo }
        private Screen screen;
        private Screen returnScreen;
        private Screen detailReturnScreen;
        public bool IsReplayScreen => screen == Screen.Review || screen == Screen.Finding || screen == Screen.Demo;
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
        private bool originalEvidenceOpen;
        private CancellationTokenSource? processingCancellation;
        private TaskCompletionSource<bool>? frameCompletion;
        private readonly ConcurrentQueue<ProcessingUpdate> updates = new();
        private string processingStage = "";
        private double processingElapsedAtUpdate;
        private float processingUpdateTime;
        private int displayedProcessingSecond = -1;
        private TouchScreenKeyboard? keyboard;
        private Action<string>? keyboardDone;
        private string error = "";
        private bool hadFocus = true;
        private bool insightsVisible = true;
        public bool IsInsightsVisible => screen == Screen.Review && insightsVisible;

        public void ToggleInsights()
        {
            if (screen != Screen.Review || !viewer.HasInputFocus) return;
            insightsVisible = !insightsVisible;
            if (insightsVisible) viewer.BringPanelToView();
            workspaceVisuals.SetActive(insightsVisible);
        }

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
            var provisioned = LoadConnection();
            try { Show(Screen.Patients); }
            catch (Exception)
            { heading.text = "Patient history unavailable"; body.text = "Local records could not be read. Existing files are retained."; status.text = "Check local storage and retry."; SetAction(primary, "Retry local history", () => Show(Screen.Patients)); return; }
            if (provisioned) CheckConnection();
        }

        private void Update()
        {
            var focus = viewer.HasInputFocus;
            var workspaceNeeded = screen != Screen.Capture && (screen != Screen.Review || insightsVisible);
            workspaceVisuals.SetActive(workspaceNeeded);
            if (hadFocus && !focus) evidence.Pause();
            hadFocus = focus;
            captureOverlay.SetVisible(screen == Screen.Capture && focus);
            if (originalEvidenceOpen) { primary.interactable = focus && evidence.IsReady; secondary.interactable = focus && evidence.IsReady; }
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
                processingStage = update.Stage + count;
                processingElapsedAtUpdate = update.Elapsed.TotalSeconds;
                processingUpdateTime = Time.unscaledTime;
                displayedProcessingSecond = -1;
                body.text = update.Detail;
            }
            if (screen == Screen.Processing && busy && processingStage.Length > 0)
            {
                var seconds = Mathf.Max(0, (float)processingElapsedAtUpdate + Time.unscaledTime - processingUpdateTime);
                var wholeSeconds = Mathf.FloorToInt(seconds);
                if (wholeSeconds != displayedProcessingSecond)
                {
                    displayedProcessingSecond = wholeSeconds;
                    status.text = $"{processingStage} · {wholeSeconds}s since final capture";
                }
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
            if (busy || CaptureBusy || NeedsCaptureSave) return;
            if (screen == Screen.Options) { Show(returnScreen); return; }
            returnScreen = screen;
            viewer.PauseReplay();
            Show(Screen.Options);
        }

        private void Show(Screen next, bool resetPage = true)
        {
            if ((CaptureBusy || NeedsCaptureSave) && next != Screen.Capture) { status.text = "Finish saving this recording before leaving capture."; return; }
            if (session == null || result == null) ClearPatternReview();
            var previousScreen = screen;
            if (next != Screen.Review && next != Screen.Demo)
                viewer.GetComponent<ReplayPlayInteractions>()?.SetPlayMode(false);
            if ((next == Screen.Finding || next == Screen.Feature) &&
                (previousScreen == Screen.Review || previousScreen == Screen.Foot || previousScreen == Screen.Microscope))
                detailReturnScreen = previousScreen;
            if (previousScreen == Screen.Capture && next != Screen.Capture && recorder.IsPreviewing) recorder.StopTake();
            screen = next;
            originalEvidenceOpen = false;
            if (previousScreen == Screen.Capture && next != Screen.Capture) viewer.BringPanelToView();
            workspaceVisuals.SetActive(next != Screen.Capture && (next != Screen.Review || insightsVisible));
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
            reviewTabs.SetActive(next == Screen.Review);
            workspaceBackplate.GetComponent<VerticalLayoutGroup>().spacing = next == Screen.Review ? 6f : 12f;
            var bodyContainer = bodyScroll != null ? bodyScroll.transform.parent : body.transform.parent;
            bodyContainer.GetComponent<VerticalLayoutGroup>().spacing = next == Screen.Review ? 6f : 12f;
            if (goataScoreGauge != null)
            {
                goataScoreGauge.SetScore(null, "Not enough data");
                goataScoreGauge.gameObject.SetActive(false);
            }
            listPager.SetActive(false);
            var panelHeight = next == Screen.CaptureSetup || next == Screen.Review || next == Screen.Finding || next == Screen.Feature ||
                next == Screen.Foot || next == Screen.Microscope ? 940f : 800f;
            workspaceCanvas.SetSizeWithCurrentAnchors(RectTransform.Axis.Vertical, panelHeight);
            workspaceBackplate.SetSizeWithCurrentAnchors(RectTransform.Axis.Vertical, panelHeight);
            workspaceHandle.localPosition = new Vector3(0f, -panelHeight * .0005f - .022f, -.018f);
            foreach (var row in rows)
            {
                row.gameObject.SetActive(false);
                var layout = row.GetComponent<LayoutElement>(); layout.minHeight = layout.preferredHeight = 68;
                var label = row.GetComponentsInChildren<TMP_Text>(true).First(t => t.name == "Label"); label.fontSize = 24; label.color = Color.white;
            }
            body.fontSize = 24;
            body.enableAutoSizing = false;
            body.overflowMode = TextOverflowModes.Overflow;
            SetAction(primary, "", null); SetAction(secondary, "", null);
            body.text = "";
            SetBodyHeight(next == Screen.Review ? 56 : next == Screen.Finding || next == Screen.Feature ? 300 :
                next == Screen.CaptureSetup ? 240 : 96);
            status.text = error.Length == 0 && (next == Screen.Patients || next == Screen.History || next == Screen.CaptureSetup)
                ? connectionStatus : error;
            error = "";
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
            ResetBodyScroll();
        }

        private void RenderPatients()
        {
            heading.text = "Your patients";
            var list = store.Patients();
            body.text = list.Count == 0 ? "Create a local patient profile to begin a dated assessment." : "Choose a patient to view saved tests or start a new capture.";
            List(list.Select(p => (p.DisplayName + " · added " + p.CreatedAt.ToLocalTime().ToString("MMM d, HH:mm"), (Action)(() =>
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
            List(list.Select(s => ($"{ReviewEvidence.TestName(s.TestType)} · {s.CreatedAt.ToLocalTime():MMM d, HH:mm}\n{ReviewEvidence.SessionStatus(s.Status)}",
                (Action)(() => OpenSession(s)))).ToArray());
            SetAction(primary, "New assessment", () => { session = null; result = null; manifest = null; Show(Screen.Tests); });
        }

        private async void OpenSession(SessionRecord selected, Guid? version = null)
        {
            session = selected; result = null; manifest = null;
            ClearPatternReview();
            primarySessionId = null; microscopeHold = false;
            savedTake = attemptedTake = captureSaveError = "";
            var chosenVersion = version ?? selected.ResultId;
            if (chosenVersion.HasValue)
            {
                busy = true;
                Show(Screen.Processing);
                var generation = patternGeneration;
                heading.text = "Opening saved assessment";
                try
                {
                    var loaded = await Task.Run(() => store.OpenResult(selected.PatientId, selected.Id, chosenVersion));
                    if (!PatternIdentityMatches(generation, selected.PatientId, selected.Id)) return;
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
                var lastCapture = recorder.LastCapture;
                if (lastCapture != null && restored != null &&
                    Guid.TryParse(lastCapture.SessionId, out var lastSessionId) && lastSessionId == selected.Id &&
                    Guid.TryParse(lastCapture.TakeId, out var lastTakeId))
                {
                    var savedView = restored.Views.FirstOrDefault(view => view.TakeIds.Contains(lastTakeId));
                    if (savedView != null)
                    {
                        savedTake = attemptedTake = lastCapture.TakeId.ToString();
                        lastSavedView = savedView.View;
                    }
                }
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
            body.text = "Choose one protocol. Each uses four separate recordings: right, front, back and left. You can return to a saved draft.";
            var tests = ReviewEvidence.NewTests();
            for (var i = 0; i < tests.Length; i++)
            {
                var type = tests[i];
                SetRow(i, ReviewEvidence.TestName(type), () =>
                {
                    pendingTestType = type; session = null; consentConfirmed = false;
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
            pendingTestType = session.TestType;
            session = null;
            microscopeHold = true; guidedCapture = null; targetDurationSeconds = 10; lastSavedView = "";
            consentConfirmed = false;
            savedTake = attemptedTake = captureSaveError = "";
            Show(Screen.CaptureSetup);
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
            while (updates.TryDequeue(out _)) { }
            processingStage = "";
            displayedProcessingSecond = -1;
            status.text = "Preparing recording for upload…";
            processingCancellation = new CancellationTokenSource();
            var patientId = patient.Id; var sessionId = session.Id; var retry = forceNewVersion || session.Status == "failed";
            try
            {
                using var client = new ProcessingClient(store, new Uri(endpoint), token, leafSha256: leafSha256);
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
            var selectedSession = session;
            if (selectedSession == null || patient?.Id != selectedSession.PatientId) return;
            var loadedManifest = loaded.Manifest;
            if ((string?)loadedManifest["patient_id"] != selectedSession.PatientId.ToString() ||
                (string?)loadedManifest["session_id"] != selectedSession.Id.ToString() ||
                (string?)loadedManifest["test_type"] != selectedSession.TestType)
                throw new InvalidDataException("The saved result belongs to another patient or test.");
            ClearPatternReview();
            var generation = patternGeneration;
            var opened = await Task.Run(() =>
            {
                var replay = loaded.LoadReplay();
                var capture = store.Capture(selectedSession);
                return (Replay: replay, Capture: capture, Patterns: LoadPatterns(replay, capture, selectedSession));
            });
            var data = opened.Replay;
            if (!PatternIdentityMatches(generation, selectedSession.PatientId, selectedSession.Id)) return;
            result = loaded; manifest = loadedManifest; finding = null;
            reviewCapture = opened.Capture; selectedObservation = null; showObservations = true;
            patternReview = opened.Patterns;
            if (patternReview.Completed)
                Debug.Log("PHYSIO_PATTERNS_READY method=" + MotionPatternClassifier.MethodId + " count=" + patternReview.Items.Length);
            insightsVisible = data == null;
            GetComponent<HandReplayPanel>().SetContext(patient == null || session == null ? "Replay" :
                patient.DisplayName + " · " + ReviewEvidence.TestName(session.TestType) + " · " +
                session.CreatedAt.ToLocalTime().ToString("MMM d, HH:mm"));
            if (data != null) viewer.LoadReplay(data); else viewer.ClearReplay();
            Show(Screen.Review);
            if (markFirstDisplay && patient != null && session != null)
            {
                frameCompletion = new TaskCompletionSource<bool>();
                StartCoroutine(AfterRenderedFrame(frameCompletion));
                await frameCompletion.Task;
                frameCompletion = null;
                if (!PatternIdentityMatches(generation, selectedSession.PatientId, selectedSession.Id, loaded.ResultId)) return;
                var patientId = patient.Id; var sessionId = session.Id;
                var capture = recorder.LastCapture;
                var displayedTicks = System.Diagnostics.Stopwatch.GetTimestamp();
                var displayedSession = await Task.Run(() =>
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
                if (!PatternIdentityMatches(generation, patientId, sessionId, loaded.ResultId)) return;
                session = displayedSession;
            }
            busy = false;
            if (screen == Screen.Review) RenderReview();
        }

        private static IEnumerator AfterRenderedFrame(TaskCompletionSource<bool> completion)
        { yield return new WaitForEndOfFrame(); completion.TrySetResult(true); }

        private void RenderFinding()
        {
            if (finding == null || result == null) { Show(Screen.Review); return; }
            heading.text = finding["observation_id"] != null ? InsightPresentation.EstimatedLabel((string)finding["label"]!) : (string)finding["label"]!;
            var interval = finding["evidence"]!;
            var methodId = (string?)finding["method_id"];
            var method = methodId == MotionPatternClassifier.MethodId ? MotionPatternClassifier.Method()
                : manifest?["methods"]?.FirstOrDefault(m => (string?)m["method_id"] == methodId);
            var text = finding["observation_id"] != null
                ? InsightPresentation.Details(finding, EvidenceView(finding), method)
                : $"{finding["explanation"]}\n\n{InsightPresentation.Source(finding, EvidenceView(finding))} · {interval["condition"]}\n" +
                  $"Evidence: {interval["quality"]} · {interval["quality_reason"]}\n" +
                  $"{InsightPresentation.Metrics(finding)}\nLimitations\n" +
                  string.Join("\n", finding["limitations"]!.Select(v => (string)v!)) +
                  (method == null ? "" : $"\nMethod: {method["name"]} · {method["version"]}");
            var takeId = Guid.Parse((string)interval["take_id"]!);
            if (result.ReplayTakeId == takeId)
                viewer.SelectFinding(new FindingInterval(takeId, (double)interval["start_s"]!, (double)interval["end_s"]!),
                    finding["highlight_joint_names"]?.Values<string>().Where(name => name != null).Select(name => name!).ToArray() ?? Array.Empty<string>(), (string?)finding["region"] ?? "Selected region");
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
                originalEvidenceOpen = true;
                var interval = (JObject)selected["evidence"]!;
                var take = Guid.Parse((string)interval["take_id"]!);
                var same = ReviewEvidence.CanSeek(result!.ReplayTakeId, take, (double)interval["start_s"]!, (double)interval["end_s"]!);
                if (same)
                {
                    viewer.SetReplayVisible(true);
                    viewer.SelectFinding(new FindingInterval(take, (double)interval["start_s"]!, (double)interval["end_s"]!),
                        selected["highlight_joint_names"]?.Values<string>().Where(name => name != null).Select(name => name!).ToArray() ?? Array.Empty<string>(), (string?)selected["region"] ?? "Selected region");
                }
                else { viewer.Highlight(Array.Empty<string>()); viewer.SetReplayVisible(false); }
                GetComponent<HandReplayPanel>().ShowTimeline(same);
                reviewTabs.SetActive(false);
                if (goataScoreGauge != null) goataScoreGauge.gameObject.SetActive(false);
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
                status.text = same ? "Matching source · paused at the evidence frame" : "Separate take · body paused; times are not aligned";
                SetAction(primary, sourceEnd > sourceStart ? "Play / pause footage" : "Play / pause full recording", sourceEnd > sourceStart ? (Action)evidence.TogglePlay : evidence.ToggleFullRecording);
                SetAction(secondary, sourceEnd > sourceStart ? "Restart footage" : "Return to peak frame", sourceEnd > sourceStart ? (Action)evidence.Restart : evidence.ReturnToEvidence);
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
            heading.text = "Options";
            var items = new List<(string, Action)>();
            if (returnScreen == Screen.Processing || returnScreen == Screen.CaptureSummary || returnScreen == Screen.Patients)
            {
                AddConnectionOptions(items);
            }
            else if (returnScreen == Screen.Review || returnScreen == Screen.Finding || returnScreen == Screen.Microscope)
            {
                body.text = "Replay display settings. Display changes do not alter measurements.";
                items.Add(("Show / hide skeleton", viewer.ToggleSkeletonVisibility));
                items.Add(("Change body opacity", viewer.ToggleBodyOpacity));
                items.Add(("Place replay on floor again", viewer.ResetReplayPlacement));
                if (session?.ResultId != null) items.Add(("Saved result versions", () => Show(Screen.Versions)));
            }
            else body.text = "Move this panel with the bar below it. Use two hands to resize.";
            if (returnScreen == Screen.Processing && session != null && patient != null &&
                (session.Status == "loaded" || session.Status == "ready" || session.Status == "failed"))
                items.Add(("Reprocess saved capture", () =>
                { session = store.Session(patient.Id, session.Id); ProcessSavedCapture(true); }));
            List(items.ToArray());
            SetAction(primary, returnScreen == Screen.Capture ? "Bring capture controls here" : "Resume", () =>
            {
                Show(returnScreen);
            });
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
            if (pages.Length <= 1) return;
            listPager.SetActive(true);
            SetAction(previousPage, $"Previous · {detailPage + 1}/{pages.Length}", detailPage > 0 ? () =>
            { detailPage--; if (screen == Screen.Finding) RenderFinding(); else Detail(text); } : null);
            SetAction(nextPage, $"Next · {detailPage + 1}/{pages.Length}", detailPage < pages.Length - 1 ? () =>
            { detailPage++; if (screen == Screen.Finding) RenderFinding(); else Detail(text); } : null);
        }

        private void List((string Label, Action Action)[] items, int size = 4)
        {
            size = Math.Min(size, rows.Length);
            var paginated = items.Length > size;
            var contentSize = paginated ? Math.Min(3, size) : size;
            var count = Math.Max(1, (items.Length + contentSize - 1) / contentSize);
            page = Math.Min(page, count - 1);
            for (var i = 0; i < contentSize && page * contentSize + i < items.Length; i++)
            { var item = items[page * contentSize + i]; SetRow(i, item.Label, item.Action); }
            if (!paginated) return;
            listPager.SetActive(true);
            SetAction(previousPage, $"Previous · {page + 1}/{count}", page > 0 ? () => { page--; Show(screen, false); } : null);
            SetAction(nextPage, $"Next · {page + 1}/{count}", page < count - 1 ? () => { page++; Show(screen, false); } : null);
        }

        private void Back()
        {
            if (busy || CaptureBusy || NeedsCaptureSave) { status.text = "Finish saving this recording before leaving."; return; }
            error = "";
            if (originalEvidenceOpen) { Show(screen == Screen.Finding ? Screen.Finding : Screen.Review, false); return; }
            switch (screen)
            {
                case Screen.Options: Show(returnScreen); break;
                case Screen.Finding: case Screen.Feature: Show(detailReturnScreen); break;
                case Screen.Versions: case Screen.Foot: case Screen.Microscope: Show(Screen.Review); break;
                case Screen.CaptureSetup when microscopeHold: ReturnToPrimaryReview(); break;
                case Screen.CaptureSetup when session == null: Show(Screen.Tests); break;
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
        {
            var layout = bodyScroll != null ? bodyScroll.GetComponent<LayoutElement>() : body.GetComponent<LayoutElement>();
            layout.minHeight = layout.preferredHeight = height;
        }

        private void ResetBodyScroll()
        {
            if (bodyScroll == null) return;
            LayoutRebuilder.ForceRebuildLayoutImmediate(workspaceBackplate);
            bodyScroll.StopMovement();
            bodyScroll.verticalNormalizedPosition = 1f;
        }

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
        private void OnDestroy() { connectionCancellation?.Cancel(); processingCancellation?.Cancel(); frameCompletion?.TrySetCanceled(); evidence?.Stop(); token = leafSha256 = ""; }
    }
}
