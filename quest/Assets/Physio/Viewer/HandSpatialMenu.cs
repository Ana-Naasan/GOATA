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
        [SerializeField] private Button closeButton = null!;
        [SerializeField] private Button tomatoButton = null!;
        [SerializeField] private ReplayPlayInteractions play = null!;
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
            closeButton.onClick.AddListener(Close);
            tomatoButton.onClick.AddListener(SpawnTomato);
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
            if (!viewer.HasInputFocus) Close();
            handRoot.SetActive(show);
            captureButton.interactable = opened && workflow.CanOpenCapture;
            replayButton.interactable = opened && workflow.CanOpenReplay;
            optionsButton.interactable = opened && workflow.CanOpenOptions;
            tomatoButton.gameObject.SetActive(play.IsPlayMode);
            tomatoButton.interactable = opened && play.IsPlayMode;
        }

        private void Toggle()
        {
            if (!viewer.HasInputFocus) return;
            if (opened) { Close(); return; }
            var yaw = Quaternion.Euler(0, head.eulerAngles.y, 0);
            shelf.transform.SetPositionAndRotation(head.position + yaw * new Vector3(-.48f, -.55f, 1.25f), yaw);
            opened = true;
            shelf.SetActive(true);
        }
        private void Capture() { workflow.OpenCaptureShortcut(); Close(); }
        private void Replay() { workflow.OpenInsightsShortcut(); Close(); }
        private void Options() { viewer.BringPanelToView(); workflow.OpenOptions(); Close(); }
        private void SpawnTomato() { play.SpawnTomato(); Close(); }
        private void Close() { opened = false; shelf.SetActive(false); }
        private void OnDestroy()
        {
            if (launcherButton != null) launcherButton.onClick.RemoveListener(Toggle);
            if (captureButton != null) captureButton.onClick.RemoveListener(Capture);
            if (replayButton != null) replayButton.onClick.RemoveListener(Replay);
            if (optionsButton != null) optionsButton.onClick.RemoveListener(Options);
            if (closeButton != null) closeButton.onClick.RemoveListener(Close);
            if (tomatoButton != null) tomatoButton.onClick.RemoveListener(SpawnTomato);
        }
    }
}
