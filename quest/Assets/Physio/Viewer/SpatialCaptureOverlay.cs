#nullable enable
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    /// <summary>Native movable surfaces keep recording controls out of the participant's view.</summary>
    public sealed class SpatialCaptureOverlay : MonoBehaviour
    {
        [SerializeField] private WorkflowPanel workflow = null!;
        [SerializeField] private Transform head = null!;
        [SerializeField] private GameObject guidanceRoot = null!;
        [SerializeField] private TMP_Text guidanceTitle = null!;
        [SerializeField] private TMP_Text guidanceContext = null!;
        [SerializeField] private TMP_Text guidanceSteps = null!;
        [SerializeField] private TMP_Text guidanceStatus = null!;
        [SerializeField] private GameObject recordDock = null!;
        [SerializeField] private Button recordButton = null!;
        [SerializeField] private TMP_Text recordLabel = null!;
        [SerializeField] private TMP_Text recordTime = null!;
        [SerializeField] private Button retakeButton = null!;
        [SerializeField] private Button workspaceButton = null!;
        private bool visible;
        private bool canRecenter;
        private float openedAt;

        private void Start()
        {
            recordButton.onClick.AddListener(workflow.ActivateCaptureControl);
            retakeButton.onClick.AddListener(workflow.RetakeLastView);
            workspaceButton.onClick.AddListener(workflow.OpenOptions);
            recordLabel.richText = true;
            SetVisible(false);
        }

        public void SetVisible(bool value)
        {
            if (value && !visible) { PlaceSurfaces(); openedAt = Time.unscaledTime; }
            visible = value;
            guidanceRoot.SetActive(value);
            recordDock.SetActive(value);
        }

        public void Render(string title, string context, string steps, string status, string action, string time, bool canAct, bool canRetake, bool canLeave)
        {
            SetText(guidanceTitle, title); SetText(guidanceContext, context); SetText(guidanceSteps, steps);
            SetText(guidanceStatus, status);
            var glyph = action == "Stop recording" ? "<color=#FF5048>■</color> " : action == "Record" ? "<color=#FF5048>●</color> " : "";
            SetText(recordLabel, glyph + action); SetText(recordTime, time);
            canRecenter = canLeave;
            recordButton.interactable = canAct;
            retakeButton.gameObject.SetActive(canRetake);
            retakeButton.interactable = canRetake;
            workspaceButton.interactable = canLeave;
        }

        private void LateUpdate()
        {
            if (!visible || !canRecenter || head == null || Time.unscaledTime - openedAt < .5f) return;
            // Between viewpoints only, retrieve controls that are behind the wearer. Visible targets stay fixed.
            var direction = (recordDock.transform.position - head.position).normalized;
            if (Vector3.Dot(head.forward, direction) < .2f) PlaceSurfaces();
        }

        public void PlaceSurfaces()
        {
            if (head == null) return;
            Place(guidanceRoot.transform, new Vector3(-.52f, .08f, 1.15f));
            Place(recordDock.transform, new Vector3(0f, -.38f, .85f));
        }

        private void Place(Transform target, Vector3 offset)
        {
            var yaw = Quaternion.Euler(0, head.eulerAngles.y, 0);
            target.SetPositionAndRotation(head.position + yaw * offset, yaw);
        }
        private static void SetText(TMP_Text text, string value) { if (text.text != value) text.text = value; }
        private void OnDestroy()
        {
            if (recordButton != null) recordButton.onClick.RemoveListener(workflow.ActivateCaptureControl);
            if (retakeButton != null) retakeButton.onClick.RemoveListener(workflow.RetakeLastView);
            if (workspaceButton != null) workspaceButton.onClick.RemoveListener(workflow.OpenOptions);
        }
    }
}
