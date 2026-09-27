using Oculus.Interaction;
using UnityEngine;

namespace Physio.Viewer
{
    /// <summary>Only clamp a panel while it is being dragged; leaning toward it never moves it.</summary>
    public sealed class PanelGrabBoundary : MonoBehaviour
    {
        [SerializeField] private Transform target;
        [SerializeField] private Transform head;
        [SerializeField] private Grabbable grab;
        [SerializeField] private float panelHeightMeters;

        public void Initialize(Transform panel, Transform eye, Grabbable grabbable, float heightMeters)
        {
            target = panel;
            head = eye;
            grab = grabbable;
            panelHeightMeters = heightMeters;
        }

        private void LateUpdate()
        {
            if (target == null || head == null || grab == null || grab.GrabPoints.Count == 0) return;
            var delta = target.position - head.position;
            var distance = delta.magnitude;
            if (distance < .001f) delta = head.forward;
            var minimum = Mathf.Max(.85f, panelHeightMeters * target.lossyScale.y / (2f * Mathf.Tan(20f * Mathf.Deg2Rad)));
            target.position = head.position + delta.normalized * Mathf.Clamp(distance, minimum, 2.25f);
        }
    }
}
