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
        [SerializeField] private Button movementButton = null!;
        [SerializeField] private TMP_Text movementButtonLabel = null!;
        [SerializeField] private GameObject movementExampleRoot = null!;
        [SerializeField] private MovementExample movementExample = null!;
        [SerializeField] private RawImage cameraPreview = null!;
        [SerializeField] private GameObject cameraPreviewFrame = null!;
        [SerializeField] private TMP_Text cameraPreviewCaption = null!;
        [SerializeField] private RectTransform guidanceCanvas = null!;
        [SerializeField] private RectTransform guidanceBackplate = null!;
        [SerializeField] private Transform guidanceHandle = null!;
        [SerializeField] private Button recordButton = null!;
        [SerializeField] private TMP_Text recordLabel = null!;
        [SerializeField] private TMP_Text recordTime = null!;
        [SerializeField] private Button retakeButton = null!;
        [SerializeField] private TMP_Text retakeLabel = null!;
        [SerializeField] private Button returnButton = null!;
        private bool placed;
        private bool exampleOpen;

        private void Start()
        {
            recordButton.onClick.AddListener(workflow.ActivateCaptureControl);
            retakeButton.onClick.AddListener(workflow.RetakeOrClosePreview);
            returnButton.onClick.AddListener(workflow.LeaveCapture);
            movementButton.onClick.AddListener(ToggleExample);
            recordLabel.richText = true;
            SetVisible(false);
        }

        public void SetVisible(bool value)
        {
            if (value && !placed) PlaceSurfaces();
            if (!value) exampleOpen = false;
            guidanceRoot.SetActive(value);
        }

        public void Render(string test, string title, string context, string steps, string status, string action, string time,
            Texture? cameraFrame, bool recording, bool previewing, bool preparing, bool canAct, bool canRetake, bool canLeave)
        {
            var exampleLocked = string.IsNullOrEmpty(test) || test == "barefoot" || previewing || preparing || recording;
            if (exampleLocked) exampleOpen = false;
            SetText(guidanceTitle, title); SetText(guidanceContext, context); SetText(guidanceSteps, steps);
            SetText(guidanceStatus, status);
            movementExample.SetTest(test);
            movementButton.gameObject.SetActive(!exampleLocked);
            movementExampleRoot.SetActive(exampleOpen && !exampleLocked);
            SetText(movementButtonLabel, exampleOpen ? "Hide movement example ▴" : "How the movement looks ▾");
            guidanceContext.gameObject.SetActive(!recording);
            guidanceSteps.gameObject.SetActive(!recording);
            returnButton.transform.parent.gameObject.SetActive(!recording);
            var glyph = action == "Stop recording" ? "<color=#FF5048>■</color> " : action == "Record" ? "<color=#FF5048>●</color> " : "";
            SetText(recordLabel, glyph + action); SetText(recordTime, time);
            cameraPreview.texture = cameraFrame;
            if (cameraFrame != null && cameraFrame.height > 0)
                cameraPreview.GetComponent<AspectRatioFitter>().aspectRatio = (float)cameraFrame.width / cameraFrame.height;
            var showFrame = cameraFrame != null && !exampleOpen;
            cameraPreviewFrame.SetActive(showFrame);
            cameraPreviewCaption.gameObject.SetActive(showFrame && !recording);
            var previewLayout = cameraPreviewFrame.GetComponent<LayoutElement>();
            previewLayout.minHeight = previewLayout.preferredHeight = recording ? 140f : 260f;
            SetText(cameraPreviewCaption, "Recorded camera view · include the full required region");
            var height = recording ? 500f : exampleOpen ? 820f : showFrame ? 888f : 588f;
            if (Mathf.Abs(guidanceCanvas.rect.height - height) > .5f)
            {
                guidanceCanvas.SetSizeWithCurrentAnchors(RectTransform.Axis.Vertical, height);
                guidanceBackplate.SetSizeWithCurrentAnchors(RectTransform.Axis.Vertical, height);
                guidanceHandle.localPosition = new Vector3(0f, -height * .0005f - .022f, -.018f);
            }
            recordButton.interactable = canAct;
            SetText(retakeLabel, previewing ? "Close camera" : "Retake last view");
            retakeButton.gameObject.SetActive(previewing || canRetake);
            retakeButton.interactable = previewing || canRetake;
            returnButton.interactable = canLeave;
        }

        private void ToggleExample() => exampleOpen = !exampleOpen;

        public void PlaceSurfaces()
        {
            if (head == null) return;
            Place(guidanceRoot.transform, new Vector3(-.73f, -.12f, 1.45f));
            placed = true;
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
            if (retakeButton != null) retakeButton.onClick.RemoveListener(workflow.RetakeOrClosePreview);
            if (returnButton != null) returnButton.onClick.RemoveListener(workflow.LeaveCapture);
            if (movementButton != null) movementButton.onClick.RemoveListener(ToggleExample);
        }
    }
}
