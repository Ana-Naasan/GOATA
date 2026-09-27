#nullable enable
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    public sealed class HandReplayPanel : MonoBehaviour
    {
        [Header("Controls")]
        [SerializeField] private Button? playPauseButton;
        [SerializeField] private Button? reverseButton;
        [SerializeField] private Button? previousFrameButton;
        [SerializeField] private Button? nextFrameButton;
        [SerializeField] private Button? restartButton;
        [SerializeField] private Button? speedButton;
        [SerializeField] private Button? resetReplayButton;
        [SerializeField] private Button? bringPanelButton;
        [SerializeField] private Button? scaleDownButton;
        [SerializeField] private Button? scaleUpButton;
        [SerializeField] private Button? skeletonToggleButton;
        [SerializeField] private Button? controlsButton;
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
        [SerializeField] private TMP_Text? playPauseLabel;
        [SerializeField] private TMP_Text? reverseLabel;
        [SerializeField] private TMP_Text? speedLabel;
        [SerializeField] private TMP_Text? skeletonLabel;
        [SerializeField] private TMP_Text? controlsLabel;

        private FixtureViewer? viewer;
        private bool suppressSeekEvent;
        private bool controlsExpanded;

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
            if (speedButton != null) speedButton.onClick.AddListener(viewer.CycleSpeed);
            if (resetReplayButton != null) resetReplayButton.onClick.AddListener(viewer.ResetReplayPlacement);
            if (bringPanelButton != null) bringPanelButton.onClick.AddListener(viewer.BringPanelToView);
            if (scaleDownButton != null) scaleDownButton.onClick.AddListener(viewer.ScaleReplayDown);
            if (scaleUpButton != null) scaleUpButton.onClick.AddListener(viewer.ScaleReplayUp);
            if (skeletonToggleButton != null) skeletonToggleButton.onClick.AddListener(viewer.ToggleSkeletonVisibility);
            if (controlsButton != null) controlsButton.onClick.AddListener(ToggleControls);
            if (seekSlider != null) seekSlider.onValueChanged.AddListener(HandleSeekChanged);
            SetControlsExpanded(false);
        }

        public void ConfigureTimeline(float startTime, float endTime)
        {
            if (seekSlider == null) return;
            seekSlider.minValue = startTime;
            seekSlider.maxValue = endTime;
            seekSlider.wholeNumbers = false;
            seekSlider.SetValueWithoutNotify(startTime);
        }

        public void ApplyState(State state)
        {
            SetText(titleLabel, state.Title);
            SetText(statusLabel, state.Status);
            SetText(timeLabel, state.Time);
            SetText(playPauseLabel, state.PlayPause);
            SetText(reverseLabel, state.Reverse);
            SetText(speedLabel, state.Speed);
            SetText(skeletonLabel, state.Skeleton);
            SetText(controlsLabel, controlsExpanded ? "Hide" : "Controls");

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
                if (speedButton != null) speedButton.onClick.RemoveListener(viewer.CycleSpeed);
                if (resetReplayButton != null) resetReplayButton.onClick.RemoveListener(viewer.ResetReplayPlacement);
                if (bringPanelButton != null) bringPanelButton.onClick.RemoveListener(viewer.BringPanelToView);
                if (scaleDownButton != null) scaleDownButton.onClick.RemoveListener(viewer.ScaleReplayDown);
                if (scaleUpButton != null) scaleUpButton.onClick.RemoveListener(viewer.ScaleReplayUp);
                if (skeletonToggleButton != null) skeletonToggleButton.onClick.RemoveListener(viewer.ToggleSkeletonVisibility);
            }
            if (controlsButton != null) controlsButton.onClick.RemoveListener(ToggleControls);
            if (seekSlider != null) seekSlider.onValueChanged.RemoveListener(HandleSeekChanged);
        }


        private void ToggleControls()
        {
            SetControlsExpanded(!controlsExpanded);
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
