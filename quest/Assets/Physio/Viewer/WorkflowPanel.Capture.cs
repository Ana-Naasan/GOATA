#nullable enable
using System;
using System.Linq;
using System.Threading.Tasks;
using Physio.Capture;
using Physio.Workflow;

namespace Physio.Viewer
{
    public sealed partial class WorkflowPanel
    {
        private GuidedCaptureState? guidedCapture;
        private string pendingTestType = "";
        private double targetDurationSeconds = 10;
        private string lastSavedView = "";
        private string replayView = "right";
        private float nextOverlayUpdate;
        private bool NeedsCaptureSave => screen == Screen.Capture && recorder.LastCapture != null && !recorder.LastCapture.Interrupted &&
            recorder.LastCapture.SessionId.ToString() == session?.Id.ToString() && recorder.LastCapture.TakeId.ToString() != savedTake;
        public bool CanOpenOptions => !busy && !CaptureBusy && !NeedsCaptureSave;
        public bool CanOpenCapture => screen == Screen.Capture ? !busy : !busy && !CaptureBusy && !NeedsCaptureSave;
        public bool CanOpenReplay => !busy && !CaptureBusy && !microscopeHold && result != null;
        public bool IsCaptureScreen => screen == Screen.Capture;

        public void BringCaptureControlsToView()
        {
            if (viewer.HasInputFocus && screen == Screen.Capture) captureOverlay.PlaceSurfaces();
        }

        public void OpenCaptureShortcut()
        {
            if (!CanOpenCapture || !viewer.HasInputFocus) return;
            if (screen == Screen.Capture) { BringCaptureControlsToView(); return; }
            if (session?.Status == "awaiting_capture")
                Show(guidedCapture?.Complete == true ? Screen.CaptureSummary : consentConfirmed ? Screen.Capture : Screen.CaptureSetup);
            else { session = null; result = null; manifest = null; finding = null; Show(patient == null ? Screen.Patients : Screen.Tests); }
        }

        public void OpenReplayShortcut()
        {
            if (!CanOpenReplay || !viewer.HasInputFocus) return;
            Show(Screen.Review);
        }

        public void OpenInsightsShortcut()
        {
            if (!CanOpenReplay || !viewer.HasInputFocus) return;
            showObservations = true; insightsVisible = true; Show(Screen.Review);
            viewer.BringPanelToView();
        }

        private void RenderCaptureSetup()
        {
            if (patient == null || session == null && pendingTestType.Length == 0) { Show(Screen.Tests); return; }
            var testType = session?.TestType ?? pendingTestType;
            if (microscopeHold)
            {
                heading.text = "Prepare a steady-hold capture";
                body.text = "This is a separate recording for the motion microscope. Choose a region, keep the headset still, and check the live camera framing before recording. The original assessment remains saved.";
                SetRow(0, consentConfirmed ? "Participant consent confirmed" : "Confirm participant consent", () => { consentConfirmed = !consentConfirmed; RenderCaptureSetup(); });
                SetAction(primary, "Continue to room capture", consentConfirmed ? (Action)PrepareMicroscopeCapture : null);
                SetAction(secondary, "Back to review", ReturnToPrimaryReview);
                status.text = "No recording starts until you frame the camera and press Record this view.";
                return;
            }
            heading.text = "Prepare your capture";
            var hasSavedTake = guidedCapture?.Views.Any(view => view.TakeIds.Count > 0) == true;
            body.text = ReviewEvidence.TestName(testType) + "\n" + SpatialCapturePresentation.SetupInstruction(testType);
            SetRow(0, consentConfirmed ? "Participant consent confirmed" : "Confirm participant consent", () => { consentConfirmed = !consentConfirmed; RenderCaptureSetup(); });
            if (!hasSavedTake)
                SetRow(1, $"Each recording: {targetDurationSeconds:0} seconds · change", () => { targetDurationSeconds = targetDurationSeconds == 5 ? 10 : targetDurationSeconds == 10 ? 15 : 5; RenderCaptureSetup(); });
            else SetAction(rows[1], $"Each recording: {targetDurationSeconds:0} seconds · fixed for this assessment", null);
            if (testType == "barefoot")
                SetAction(rows[2], $"Selected foot: {captureSide}" + (hasSavedTake ? " · fixed" : " · change"), hasSavedTake ? null : (Action)(() => { captureSide = captureSide == "left" ? "right" : "left"; RenderCaptureSetup(); }));
            SetAction(primary, "Continue to room capture", consentConfirmed ? (Action)PrepareGuidedCapture : null);
            SetAction(secondary, "Patient history", () => Show(Screen.History));
            status.text = hasSavedTake ? "Saved viewpoints are preserved. Finish the remaining recordings." : "Open the camera, check framing, then record each view.";
        }

        private void PrepareMicroscopeCapture()
        {
            if (!consentConfirmed || !microscopeHold || patient == null || primarySessionId == null) return;
            try
            {
                session = store.CreateSession(patient.Id, pendingTestType);
                captureOverlay.PlaceSurfaces();
                Show(Screen.Capture);
            }
            catch (Exception exception) { status.text = SafeError(exception); }
        }

        private void ReturnToPrimaryReview()
        {
            if (patient == null || primarySessionId == null) { Show(Screen.History); return; }
            try
            {
                session = store.Session(patient.Id, primarySessionId.Value);
                microscopeHold = false; primarySessionId = null;
                Show(Screen.Microscope);
            }
            catch (Exception exception) { status.text = SafeError(exception); }
        }

        private async void PrepareGuidedCapture()
        {
            if (busy || CaptureBusy || !consentConfirmed || patient == null || session == null && pendingTestType.Length == 0) return;
            var patientId = patient.Id; var side = captureSide; var duration = targetDurationSeconds;
            busy = true; status.text = "Preparing saved capture progress…";
            try
            {
                session ??= store.CreateSession(patientId, pendingTestType);
                var sessionId = session.Id;
                var prepared = await Task.Run(() => store.BeginGuidedCapture(patientId, sessionId, side, duration));
                if (this == null || patient?.Id != patientId || session?.Id != sessionId) return;
                guidedCapture = prepared; captureView = prepared.NextView ?? "right";
                busy = false;
                if (!prepared.Complete) captureOverlay.PlaceSurfaces();
                Show(prepared.Complete ? Screen.CaptureSummary : Screen.Capture);
            }
            catch (Exception exception)
            { if (this != null && patient?.Id == patientId) status.text = SafeError(exception); }
            finally { busy = false; }
        }

        private void RenderCapture()
        {
            if (session == null) { Show(Screen.Tests); return; }
            previewRoot.SetActive(false);
            UpdateCaptureOverlay(true);
        }

        private void UpdateCaptureOverlay(bool force = false)
        {
            if (session == null || !force && UnityEngine.Time.unscaledTime < nextOverlayUpdate) return;
            nextOverlayUpdate = UnityEngine.Time.unscaledTime + .1f;
            var view = SpatialCapturePresentation.ViewName(captureView);
            var title = microscopeHold ? "Steady hold for motion microscope" : $"{SpatialCapturePresentation.Step(captureView)} OF 4 · PATIENT'S {view.ToUpperInvariant()}";
            var instruction = microscopeHold
                ? "Frame the chosen region. Keep the participant and camera steady."
                : SpatialCapturePresentation.ViewInstruction(session.TestType, captureSide, targetDurationSeconds);
            var steps = microscopeHold ? "Separate evidence recording" : string.Join("    ", new[] { "right", "front", "rear", "left" }.Select(v =>
                (guidedCapture?.Views.FirstOrDefault(item => item.View == v)?.SelectedTakeId != null ? "✓ " : v == captureView ? "● " : "○ ") + SpatialCapturePresentation.ViewName(v)));
            var message = !string.IsNullOrEmpty(captureSaveError) ? captureSaveError : !string.IsNullOrEmpty(recorder.Error) ? recorder.Error :
                CaptureBusy || recorder.IsPreviewing ? recorder.Status : !consentConfirmed ? "Confirm participant consent before opening the camera." : !string.IsNullOrEmpty(lastSavedView)
                    ? $"{SpatialCapturePresentation.ViewName(lastSavedView)} saved. Move to the patient's {view}, then open the camera." : $"Start at the patient's {view}. Open the camera to check framing.";
            var action = SpatialCapturePresentation.RecordAction(recorder.IsRecording, recorder.IsPreparing, recorder.IsPreviewing,
                savingCapture || recorder.IsFinalizing, NeedsCaptureSave, consentConfirmed);
            var canAct = viewer.HasInputFocus && !busy && (recorder.IsRecording || recorder.IsPreparing || !CaptureBusy);
            var environment = viewer.GetComponent<ReplayEnvironment>();
            if (environment != null && !environment.PassthroughReady)
            {
                message = environment.PassthroughTimedOut
                    ? "Passthrough did not return. Retry before recording a participant."
                    : "Returning to passthrough before capture…";
                action = environment.PassthroughTimedOut ? "Retry passthrough" : "Waiting for passthrough…";
                canAct = viewer.HasInputFocus && environment.PassthroughTimedOut;
            }
            captureOverlay.Render(microscopeHold ? string.Empty : session.TestType, title, instruction, steps, message, action,
                SpatialCapturePresentation.CaptureClock(recorder.IsRecording, recorder.IsCountingDown,
                    recorder.CountdownSeconds, recorder.IsPreviewing, recorder.IsPreparing,
                    savingCapture || recorder.IsFinalizing, recorder.DurationSeconds, targetDurationSeconds),
                recorder.PreviewTexture, recorder.IsRecording, recorder.IsPreviewing, recorder.IsPreparing,
                canAct, viewer.HasInputFocus && !CaptureBusy && !NeedsCaptureSave && !string.IsNullOrEmpty(lastSavedView),
                viewer.HasInputFocus && !CaptureBusy && !NeedsCaptureSave);
        }

        public void ActivateCaptureControl()
        {
            if (!viewer.HasInputFocus || busy || screen != Screen.Capture) return;
            var environment = viewer.GetComponent<ReplayEnvironment>();
            if (environment != null && !environment.PassthroughReady)
            {
                if (environment.PassthroughTimedOut) environment.RetryPassthrough();
                UpdateCaptureOverlay(true);
                return;
            }
            try
            {
                if (recorder.IsRecording) { recorder.StopTake(); return; }
                if (recorder.IsPreparing) { recorder.StopTake(); return; }
                if (recorder.IsPreviewing) { recorder.StartCountdown(); return; }
                if (CaptureBusy) return;
                if (NeedsCaptureSave) { attemptedTake = ""; captureSaveError = ""; return; }
                if (!consentConfirmed) { consentConfirmed = true; RenderCapture(); return; }
                BeginCapture();
            }
            catch (Exception exception) { captureSaveError = SafeError(exception); RenderCapture(); }
        }

        private void BeginCapture()
        {
            if (!consentConfirmed || patient == null || session == null || CaptureBusy) return;
            captureSaveError = "";
            recorder.BeginTake(patient.Id.ToString(), session.Id.ToString(), session.TestType, captureView,
                session.TestType == "barefoot" ? captureSide : "not_applicable", microscopeHold: microscopeHold, targetDurationSeconds: targetDurationSeconds);
        }

        public void RetakeLastView()
        {
            if (!viewer.HasInputFocus || CaptureBusy || busy || NeedsCaptureSave || string.IsNullOrEmpty(lastSavedView)) return;
            if (recorder.IsPreviewing) recorder.StopTake();
            captureView = lastSavedView;
            lastSavedView = "";
            RenderCapture();
        }

        public void RetakeOrClosePreview()
        {
            if (recorder.IsPreviewing) { recorder.StopTake(); RenderCapture(); return; }
            RetakeLastView();
        }

        public void LeaveCapture()
        {
            if (!viewer.HasInputFocus || busy || CaptureBusy || NeedsCaptureSave || screen != Screen.Capture) return;
            session = null; result = null; manifest = null;
            Show(Screen.History);
        }

        private async void PersistCapture(CompletedCapture captured)
        {
            var patientId = patient!.Id; var sessionId = session!.Id;
            var primarySource = primarySessionId; var savedView = captureView;
            savingCapture = true;
            try
            {
                if (captured.Interrupted)
                { captureSaveError = "Recording ended before the complete take. Original files are kept. Press Record to try this view again."; return; }
                var saved = await Task.Run(() =>
                {
                    GuidedCaptureState? updated = null;
                    if (primarySource.HasValue) store.SaveMicroscopeCapture(patientId, sessionId, primarySource.Value, captured.ManifestJson, captured.ZipPath);
                    else if (guidedCapture != null) updated = store.SaveGuidedTake(patientId, sessionId, captured.ManifestJson, captured.ZipPath);
                    else store.SaveCapture(patientId, sessionId, captured.ManifestJson, captured.ZipPath);
                    return (Session: store.Session(patientId, sessionId), Guided: updated);
                });
                if (this == null) return;
                session = saved.Session; guidedCapture = saved.Guided;
                savedTake = captured.TakeId.ToString(); captureSaveError = ""; lastSavedView = savedView;
                if (guidedCapture?.NextView != null) captureView = guidedCapture.NextView;
            }
            catch (Exception)
            { captureSaveError = "Recording remains on this device. Saving to history failed; press Retry saving before continuing."; }
            finally
            {
                savingCapture = false;
                if (this != null)
                {
                    if (guidedCapture?.Complete == true && string.IsNullOrEmpty(captureSaveError)) Show(Screen.CaptureSummary);
                    else if (session?.Status == "captured" && string.IsNullOrEmpty(captureSaveError)) Show(Screen.Processing);
                    else RenderCapture();
                }
            }
        }

        private void RenderCaptureSummary()
        {
            if (guidedCapture?.Complete != true || session == null) { Show(Screen.Capture); return; }
            heading.text = "All four views saved";
            body.text = session.TestType == "barefoot"
                ? "Four standing close-ups of the selected foot are saved. Select a viewpoint to retake, or process the evidence. No body replay is created for a foot assessment."
                : "Choose the recording for the 3D replay. Other viewpoints remain separate evidence; they are different performances.";
            for (var i = 0; i < guidedCapture.Views.Count; i++)
            {
                var view = guidedCapture.Views[i].View;
                SetRow(i, (view == replayView ? "✓ " : "") + SpatialCapturePresentation.ViewName(view) + (session.TestType == "barefoot" ? " viewpoint" : " replay"),
                    () => { replayView = view; RenderCaptureSummary(); });
            }
            SetAction(primary, "Process four saved views", SealGuidedCapture);
            SetAction(secondary, "Retake " + SpatialCapturePresentation.ViewName(replayView), () =>
            { captureView = replayView; lastSavedView = ""; Show(Screen.Capture); });
            status.text = $"{targetDurationSeconds:0} seconds per viewpoint · originals preserved";
        }

        private async void SealGuidedCapture()
        {
            if (busy || CaptureBusy || patient == null || session == null || guidedCapture?.Complete != true) return;
            var patientId = patient.Id; var sessionId = session.Id;
            var source = session.TestType == "barefoot" ? (Guid?)null : guidedCapture.Views.Single(v => v.View == replayView).SelectedTakeId;
            busy = true;
            var startProcessing = false;
            try
            {
                var sealedCapture = await Task.Run(() => (
                    Session: store.CompleteGuidedCapture(patientId, sessionId, source),
                    Guided: store.GuidedCapture(patientId, sessionId)));
                if (this == null || patient?.Id != patientId || session?.Id != sessionId) return;
                session = sealedCapture.Session; guidedCapture = sealedCapture.Guided;
                startProcessing = true;
            }
            catch (Exception exception)
            { busy = false; if (this != null && patient?.Id == patientId && session?.Id == sessionId) { error = SafeError(exception); Show(Screen.CaptureSummary); } }
            finally { busy = false; }
            // Sealing releases only its own busy state. Processing acquires the next operation's lock afterward.
            if (startProcessing && this != null && patient?.Id == patientId && session?.Id == sessionId)
            { Show(Screen.Processing); StartProcessing(); }
        }
    }
}
