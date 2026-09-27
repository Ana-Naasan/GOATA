#nullable enable
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Events;

namespace Physio.Viewer
{
    public sealed class HandReplayPanel : MonoBehaviour
    {
        [SerializeField] private Transform? timelineRoot;
        [SerializeField] private Transform? head;

        [Header("Controls")]
        [SerializeField] private Button? playPauseButton;
        [SerializeField] private Button? reverseButton;
        [SerializeField] private Button? previousFrameButton;
        [SerializeField] private Button? nextFrameButton;
        [SerializeField] private Button? restartButton;
        [SerializeField] private Button? speedButton;
        [SerializeField] private GameObject? speedChoicesRoot;
        [SerializeField] private Button[] speedChoices = System.Array.Empty<Button>();
        [SerializeField] private Button? resetReplayButton;
        [SerializeField] private Button? bringPanelButton;
        [SerializeField] private Button? scaleDownButton;
        [SerializeField] private Button? scaleUpButton;
        [SerializeField] private Button? skeletonToggleButton;
        [SerializeField] private Button? controlsButton;
        [SerializeField] private Button? insightsButton;
        [SerializeField] private Button? environmentButton;
        [SerializeField] private TMP_Text? environmentLabel;
        [SerializeField] private Button? playModeButton;
        [SerializeField] private TMP_Text? playModeLabel;
        [SerializeField] private Slider? seekSlider;

        [SerializeField] private bool externalLayout;

        [Header("Layout")]
        [SerializeField] private GameObject? secondaryControlsRoot;
        [SerializeField] private RectTransform? canvasRect;
        [SerializeField] private RectTransform? backplateRect;
        [SerializeField] private Transform? panelGrabHandle;
        [SerializeField] private float collapsedPanelHeight = 344f;
        [SerializeField] private float expandedPanelHeight = 560f;

        [Header("Labels")]
        [SerializeField] private TMP_Text? titleLabel;
        [SerializeField] private TMP_Text? statusLabel;
        [SerializeField] private TMP_Text? timeLabel;
        [SerializeField] private TMP_Text? evidenceLabel;
        [SerializeField] private RectTransform? evidenceRange;
        [SerializeField] private TMP_Text? playPauseLabel;
        [SerializeField] private TMP_Text? reverseLabel;
        [SerializeField] private TMP_Text? speedLabel;
        [SerializeField] private TMP_Text? skeletonLabel;
        [SerializeField] private TMP_Text? controlsLabel;

        private FixtureViewer? viewer;
        private bool suppressSeekEvent;
        private bool controlsExpanded;
        private bool timelinePlaced;
        private bool timelineVisible;
        private bool speedChoicesOpen;
        private UnityAction[] speedChoiceActions = System.Array.Empty<UnityAction>();
        private string replayContext = "";

        public void SetContext(string value) => replayContext = value;
        public void ResetPlacement() => timelinePlaced = false;
        public void BringTimelineToView() { timelinePlaced = false; ShowTimeline(timelineVisible); }

        public static State Empty => new()
        {
            Title = "Replay demo",
            Status = "Replay loading",
            Time = "--",
            PlayPause = "Play",
            Reverse = "Forward",
            Speed = "1x",
            Skeleton = "Skeleton On",
            SeekTime = 0f,
            CanInteract = false
        };

        public void Bind(FixtureViewer owner)
        {
            RemoveListeners();
            viewer = owner;
            if (playPauseButton != null) playPauseButton.onClick.AddListener(viewer.TogglePlay);
            if (reverseButton != null) reverseButton.onClick.AddListener(viewer.Reverse);
            if (previousFrameButton != null) previousFrameButton.onClick.AddListener(viewer.StepBack);
            if (nextFrameButton != null) nextFrameButton.onClick.AddListener(viewer.StepForward);
            if (restartButton != null) restartButton.onClick.AddListener(viewer.Restart);
            if (speedButton != null) speedButton.onClick.AddListener(ToggleSpeedChoices);
            speedChoiceActions = new UnityAction[speedChoices.Length];
            for (var index = 0; index < speedChoices.Length; index++)
            {
                var choice = index;
                speedChoiceActions[index] = () => ChooseSpeed(choice);
                speedChoices[index].onClick.AddListener(speedChoiceActions[index]);
            }
            speedChoicesOpen = false;
            if (speedChoicesRoot != null) speedChoicesRoot.SetActive(false);
            ResizePanel(544f);
            if (resetReplayButton != null) resetReplayButton.onClick.AddListener(viewer.ResetReplayPlacement);
            if (bringPanelButton != null) bringPanelButton.onClick.AddListener(viewer.BringPanelToView);
            if (scaleDownButton != null) scaleDownButton.onClick.AddListener(viewer.ScaleReplayDown);
            if (scaleUpButton != null) scaleUpButton.onClick.AddListener(viewer.ScaleReplayUp);
            if (skeletonToggleButton != null) skeletonToggleButton.onClick.AddListener(viewer.ToggleSkeletonVisibility);
            if (controlsButton != null) controlsButton.onClick.AddListener(ToggleControls);
            if (insightsButton != null) insightsButton.onClick.AddListener(ToggleInsights);
            if (environmentButton != null) environmentButton.onClick.AddListener(viewer.ToggleQuietRoom);
            if (playModeButton != null) playModeButton.onClick.AddListener(TogglePlayMode);
            if (seekSlider != null) seekSlider.onValueChanged.AddListener(HandleSeekChanged);
            SetControlsExpanded(false);
        }

        public void ShowTimeline(bool visible)
        {
            if (timelineRoot == null) return;
            timelineVisible = visible;
            if (visible && !timelinePlaced && head != null)
            {
                var yaw = Quaternion.Euler(0, head.eulerAngles.y, 0);
                timelineRoot.SetPositionAndRotation(head.position + yaw * new Vector3(1.2f, -.42f, 1.45f), yaw);
                timelinePlaced = true;
            }
            RefreshTimelineVisibility();
        }

        private void LateUpdate() => RefreshTimelineVisibility();

        private void RefreshTimelineVisibility()
        {
            if (timelineRoot == null) return;
            timelineRoot.gameObject.SetActive(timelineVisible);
        }

        private void ToggleInsights() => GetComponent<WorkflowPanel>()?.ToggleInsights();
        private void TogglePlayMode() => viewer?.GetComponent<ReplayPlayInteractions>()?.TogglePlayMode();

        public void ConfigureTimeline(float startTime, float endTime)
        {
            if (seekSlider == null) return;
            seekSlider.minValue = startTime;
            seekSlider.maxValue = endTime;
            seekSlider.wholeNumbers = false;
            seekSlider.SetValueWithoutNotify(startTime);
        }

        public void SelectEvidence(double start, double end, string region)
        {
            if (evidenceLabel != null) evidenceLabel.text = $"{region} · source {start:0.00}" + (end == start ? "s · selected frame" : $"–{end:0.00}s");
            if (evidenceRange == null || seekSlider == null) return;
            var span = seekSlider.maxValue - seekSlider.minValue;
            if (span <= 0) return;
            var left = Mathf.Clamp01(((float)start - seekSlider.minValue) / span);
            var right = Mathf.Clamp01(((float)end - seekSlider.minValue) / span);
            evidenceRange.anchorMin = new Vector2(left, 0);
            evidenceRange.anchorMax = new Vector2(right, 1);
            evidenceRange.offsetMin = new Vector2(-2, 0); evidenceRange.offsetMax = new Vector2(2, 0);
            evidenceRange.gameObject.SetActive(true);
        }

        public void ClearEvidence()
        {
            if (evidenceLabel != null) evidenceLabel.text = "";
            if (evidenceRange != null) evidenceRange.gameObject.SetActive(false);
        }

        public void ApplyState(State state)
        {
            if (titleLabel != null) titleLabel.gameObject.SetActive(replayContext.Length > 0);
            SetText(titleLabel, replayContext.Length > 0 ? replayContext : state.Title);
            var inMoonRoom = viewer != null && viewer.GetComponent<ReplayEnvironment>()?.IsQuietRoom == true;
            var playMode = viewer?.GetComponent<ReplayPlayInteractions>();
            SetText(statusLabel, state.Status);
            SetText(timeLabel, state.Time + (inMoonRoom ? " · STATIONARY VR" : ""));
            SetText(playPauseLabel, state.PlayPause);
            SetText(reverseLabel, state.Reverse);
            SetText(speedLabel, "Speed " + state.Speed + (speedChoicesOpen ? " ▴" : " ▾"));
            SetText(skeletonLabel, state.Skeleton);
            SetText(controlsLabel, controlsExpanded ? "Hide" : "Controls");
            SetText(environmentLabel, inMoonRoom ? "Passthrough" : "Moon room");
            SetText(playModeLabel, playMode?.IsPlayMode == true ? "Exit play" : "Play mode");

            if (seekSlider != null)
            {
                suppressSeekEvent = true;
                seekSlider.SetValueWithoutNotify(state.SeekTime);
                suppressSeekEvent = false;
                seekSlider.interactable = state.CanInteract;
            }

            SetInteractable(playPauseButton, state.CanInteract);
            SetInteractable(reverseButton, state.CanInteract);
            SetInteractable(previousFrameButton, state.CanInteract);
            SetInteractable(nextFrameButton, state.CanInteract);
            SetInteractable(restartButton, state.CanInteract);
            SetInteractable(speedButton, state.CanInteract);
            SetInteractable(resetReplayButton, state.CanInteract);
            SetInteractable(bringPanelButton, state.CanInteract);
            SetInteractable(scaleDownButton, state.CanInteract);
            SetInteractable(scaleUpButton, state.CanInteract);
            SetInteractable(skeletonToggleButton, state.CanInteract);
            SetInteractable(controlsButton, state.CanInteract);
            SetInteractable(environmentButton, state.CanInteract);
            SetInteractable(playModeButton, state.CanInteract && (playMode?.IsPlayMode == true || viewer?.CanEnterPlayMode == true));
        }

        private void OnDestroy()
        {
            RemoveListeners();
        }

        private void RemoveListeners()
        {
            if (viewer != null)
            {
                if (playPauseButton != null) playPauseButton.onClick.RemoveListener(viewer.TogglePlay);
                if (reverseButton != null) reverseButton.onClick.RemoveListener(viewer.Reverse);
                if (previousFrameButton != null) previousFrameButton.onClick.RemoveListener(viewer.StepBack);
                if (nextFrameButton != null) nextFrameButton.onClick.RemoveListener(viewer.StepForward);
                if (restartButton != null) restartButton.onClick.RemoveListener(viewer.Restart);
                if (speedButton != null) speedButton.onClick.RemoveListener(ToggleSpeedChoices);
                if (resetReplayButton != null) resetReplayButton.onClick.RemoveListener(viewer.ResetReplayPlacement);
                if (bringPanelButton != null) bringPanelButton.onClick.RemoveListener(viewer.BringPanelToView);
                if (scaleDownButton != null) scaleDownButton.onClick.RemoveListener(viewer.ScaleReplayDown);
                if (scaleUpButton != null) scaleUpButton.onClick.RemoveListener(viewer.ScaleReplayUp);
                if (skeletonToggleButton != null) skeletonToggleButton.onClick.RemoveListener(viewer.ToggleSkeletonVisibility);
                if (environmentButton != null) environmentButton.onClick.RemoveListener(viewer.ToggleQuietRoom);
                if (playModeButton != null) playModeButton.onClick.RemoveListener(TogglePlayMode);
            }
            if (controlsButton != null) controlsButton.onClick.RemoveListener(ToggleControls);
            for (var index = 0; index < speedChoices.Length && index < speedChoiceActions.Length; index++)
                speedChoices[index].onClick.RemoveListener(speedChoiceActions[index]);
            if (insightsButton != null) insightsButton.onClick.RemoveListener(ToggleInsights);
            if (seekSlider != null) seekSlider.onValueChanged.RemoveListener(HandleSeekChanged);
        }


        private void ToggleControls()
        {
            SetControlsExpanded(!controlsExpanded);
        }

        private void ToggleSpeedChoices()
        {
            speedChoicesOpen = !speedChoicesOpen;
            if (speedChoicesRoot != null) speedChoicesRoot.SetActive(speedChoicesOpen);
            ResizePanel(speedChoicesOpen ? 624f : 544f);
        }

        private void ChooseSpeed(int index)
        {
            viewer?.SetPlaybackSpeed(index);
            if (speedChoicesOpen) ToggleSpeedChoices();
        }

        private void SetControlsExpanded(bool expanded)
        {
            controlsExpanded = expanded;
            if (secondaryControlsRoot != null) secondaryControlsRoot.SetActive(controlsExpanded);
            SetText(controlsLabel, controlsExpanded ? "Hide" : "Controls");
            if (!externalLayout) ResizePanel(controlsExpanded ? expandedPanelHeight : collapsedPanelHeight);
        }

        private void ResizePanel(float height)
        {
            if (canvasRect != null) canvasRect.SetSizeWithCurrentAnchors(RectTransform.Axis.Vertical, height);
            if (backplateRect != null) backplateRect.SetSizeWithCurrentAnchors(RectTransform.Axis.Vertical, height);
            if (panelGrabHandle == null) return;

            var local = panelGrabHandle.localPosition;
            local.y = -(height * 0.001f * 0.5f) - 0.028f;
            panelGrabHandle.localPosition = local;
        }

        private void HandleSeekChanged(float value)
        {
            if (suppressSeekEvent || viewer == null) return;
            viewer.SeekFromPanel(value);
        }

        private static void SetText(TMP_Text? target, string value)
        {
            if (target != null) target.text = value;
        }

        private static void SetInteractable(Selectable? selectable, bool value)
        {
            if (selectable != null) selectable.interactable = value;
        }

        public struct State
        {
            public string Title;
            public string Status;
            public string Time;
            public string PlayPause;
            public string Reverse;
            public string Speed;
            public string Skeleton;
            public float SeekTime;
            public bool CanInteract;
        }
    }
}
