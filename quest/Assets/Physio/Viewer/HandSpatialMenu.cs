#nullable enable
using Oculus.Interaction.Input;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    /// <summary>The native hand joint is only a shortcut anchor. Floating controls remain available.</summary>
    public sealed class HandSpatialMenu : MonoBehaviour
    {
        [SerializeField] private FixtureViewer viewer = null!;
        [SerializeField] private WorkflowPanel workflow = null!;
        [SerializeField] private GameObject handRoot = null!;
        [SerializeField] private Button launcherButton = null!;
        [SerializeField] private GameObject shelf = null!;
        [SerializeField] private Button captureButton = null!;
        [SerializeField] private Button replayButton = null!;
        [SerializeField] private Button optionsButton = null!;
        [SerializeField] private DominantHandRef hand = null!;
        [SerializeField] private Transform head = null!;
        private bool opened;
        private float revealAt = -1;

        private void Start()
        {
            launcherButton.onClick.AddListener(Toggle);
            captureButton.onClick.AddListener(Capture);
            replayButton.onClick.AddListener(Replay);
            optionsButton.onClick.AddListener(Options);
            shelf.SetActive(false); handRoot.SetActive(false);
        }

        private void LateUpdate()
        {
            if (head == null || hand == null) return;
            var delta = handRoot.transform.position - head.position;
            var direction = delta.normalized;
            var eligible = SpatialCapturePresentation.RevealHand(hand.IsTrackedDataValid, hand.IsHighConfidence,
                viewer.HasInputFocus, delta.magnitude, Vector3.Dot(head.forward, direction), Vector3.Dot(handRoot.transform.forward, direction));
            if (!eligible) revealAt = -1;
            else if (revealAt < 0) revealAt = Time.unscaledTime + .15f;
            var show = eligible && Time.unscaledTime >= revealAt;
            if (!show) { opened = false; shelf.SetActive(false); }
            handRoot.SetActive(show);
            captureButton.interactable = show && workflow.CanOpenCapture;
            replayButton.interactable = show && workflow.CanOpenReplay;
            optionsButton.interactable = show && workflow.CanOpenOptions;
        }

        private void Toggle() { if (!viewer.HasInputFocus) return; opened = !opened; shelf.SetActive(opened); }
        private void Capture() { workflow.OpenCaptureShortcut(); Close(); }
        private void Replay() { workflow.OpenInsightsShortcut(); Close(); }
        private void Options() { workflow.OpenOptions(); Close(); }
        private void Close() { opened = false; shelf.SetActive(false); }
        private void OnDestroy()
        {
            if (launcherButton != null) launcherButton.onClick.RemoveListener(Toggle);
            if (captureButton != null) captureButton.onClick.RemoveListener(Capture);
            if (replayButton != null) replayButton.onClick.RemoveListener(Replay);
            if (optionsButton != null) optionsButton.onClick.RemoveListener(Options);
        }
    }
}
