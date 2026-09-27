#nullable enable
using System;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using Physio.Replay;
using Physio.Workflow;
using UnityEngine;

namespace Physio.Viewer
{
    public sealed partial class WorkflowPanel
    {
        private sealed class LocalPatternReview
        {
            public ReplayData? Replay { get; }
            public string Condition { get; }
            public JObject[] Items { get; }
            public string Detail { get; }
            public bool Completed { get; }
            public GoataScoreResult? Score { get; }

            public LocalPatternReview(ReplayData? replay, string condition, JObject[] items, string detail, bool completed, GoataScoreResult? score = null)
            { Replay = replay; Condition = condition; Items = items; Detail = detail; Completed = completed; Score = score; }
        }

        private LocalPatternReview patternReview = UnavailablePatterns("No validated replay is loaded.");
        private int patternGeneration;
        private bool classifyingPatterns;
        private bool patternRerunCompleted;

        private static LocalPatternReview UnavailablePatterns(string reason) =>
            new(null, "", Array.Empty<JObject>(), reason, false);

        private void ClearPatternReview()
        {
            patternGeneration++;
            patternReview = UnavailablePatterns("No validated replay is loaded.");
            classifyingPatterns = patternRerunCompleted = false;
            selectedObservation = null;
            reviewCapture = null;
        }

        private bool PatternIdentityMatches(int generation, Guid patientId, Guid sessionId, Guid? resultId = null) =>
            this != null && patternGeneration == generation && patient?.Id == patientId && session?.Id == sessionId &&
            (!resultId.HasValue || result?.ResultId == resultId);

        // Uses the validated original replay, before any viewer placement or presentation effects.
        private LocalPatternReview LoadPatterns(ReplayData? replay, JObject capture, SessionRecord selected)
        {
            if (selected.TestType != "elk" && selected.TestType != "rtk" && selected.TestType != "walking")
                return UnavailablePatterns("Local motion patterns are unavailable for historical barefoot assessments.");
            if (replay == null)
                return UnavailablePatterns("This saved result has no reconstructed replay to classify.");
            var take = capture["takes"]?.OfType<JObject>().SingleOrDefault(item =>
                (string?)item["take_id"] == replay.Timeline.SourceTakeId.ToString());
            if (take == null || (string?)take["kind"] != "full_body")
                return UnavailablePatterns("The replay must match a full-body take in this saved capture.");
            var condition = (string?)take["condition"] ?? "";
            if (selected.TestType == "walking" ? condition != "exercise" : condition != "seated" && condition != "exercise")
                return UnavailablePatterns("The saved capture condition is not supported for this test.");
            try
            {
                var sidecar = store.Sidecar(selected, take);
                if ((bool?)sidecar["capture"]?["interrupted"] != false)
                    return UnavailablePatterns("The source take was interrupted or has no confirmed capture status.");
                WorkflowValidation.Sidecar(sidecar, take);
            }
            catch (Exception exception)
            {
                Debug.LogWarning("PHYSIO_PATTERNS_CAPTURE_FAILED type=" + exception.GetType().Name);
                return UnavailablePatterns("Source capture metadata could not be validated. Original evidence is retained.");
            }
            return ClassifyPatterns(replay, selected.TestType, condition);
        }

        private static LocalPatternReview ClassifyPatterns(ReplayData replay, string testType, string condition)
        {
            try
            {
                var items = MotionPatternClassifier.Classify(replay, testType, condition);
                var detail = items.Length == 0
                    ? "No supported patterns could be derived from the valid pose samples in this replay. Inspect original evidence and pose visibility."
                    : "Descriptive patterns estimated from the saved reconstructed pose. Clinical assessment remains unavailable.";
                return new LocalPatternReview(replay, condition, items, detail, true, GoataScore.Evaluate(replay, testType, condition));
            }
            catch (Exception exception)
            {
                Debug.LogWarning("PHYSIO_PATTERNS_CLASSIFY_FAILED type=" + exception.GetType().Name);
                return new LocalPatternReview(replay, condition, Array.Empty<JObject>(),
                    "Local classification could not finish. Rerun classifications to retry; the saved replay and original evidence are retained.", false);
            }
        }

        private string PatternStatus()
        {
            if (classifyingPatterns) return "Classifying saved motion…";
            if (!patternReview.Completed) return "Patterns unavailable";
            var count = patternReview.Items.Length;
            return count + (count == 1 ? " descriptive pattern" : " descriptive patterns") +
                (patternRerunCompleted ? " · rerun complete" : " · local classification complete");
        }

        private void SetPatternRerunAction() => SetAction(secondary,
            classifyingPatterns ? "Classifying…" : "Rerun classifications",
            !busy && !classifyingPatterns && patternReview.Replay != null ? RerunPatterns : null);

        private async void RerunPatterns()
        {
            if (busy || classifyingPatterns || patternReview.Replay == null || patient == null || session == null || result == null) return;
            var replay = patternReview.Replay;
            var condition = patternReview.Condition;
            var testType = session.TestType;
            var patientId = patient.Id; var sessionId = session.Id; var resultId = result.ResultId;
            var generation = ++patternGeneration;
            classifyingPatterns = true; patternRerunCompleted = false;
            showObservations = true;
            viewer.PauseReplay();
            Show(Screen.Review);
            try
            {
                var classified = await Task.Run(() => ClassifyPatterns(replay, testType, condition));
                if (!PatternIdentityMatches(generation, patientId, sessionId, resultId)) return;
                patternReview = classified;
                selectedObservation = null;
                patternRerunCompleted = classified.Completed;
                if (classified.Completed)
                    Debug.Log("PHYSIO_PATTERNS_RERUN method=" + MotionPatternClassifier.MethodId + " count=" + classified.Items.Length);
            }
            finally
            {
                if (PatternIdentityMatches(generation, patientId, sessionId, resultId))
                {
                    classifyingPatterns = false;
                    if (screen == Screen.Review && !originalEvidenceOpen) Show(Screen.Review, false);
                }
            }
        }
    }
}
