using Oculus.Interaction.Input;
using System.Collections.Generic;
using UnityEngine;

namespace Physio.Viewer
{
    /// <summary>Optional replay-only interactions. Recorded motion and findings are never modified.</summary>
    public sealed class ReplayPlayInteractions : MonoBehaviour
    {
        [SerializeField] private FixtureViewer viewer;
        [SerializeField] private Hand leftHand;
        [SerializeField] private Hand rightHand;
        [SerializeField] private Transform rightController;
        [SerializeField] private GameObject tomatoModel;
        [SerializeField] private Texture2D splatTexture;
        private GameObject heldTomato;
        private Rigidbody heldBody;
        private Vector3 lastPalm;
        private Vector3 palmVelocity;
        private float spawnedAt;
        private float lastSlapAt = -10f;
        private bool gripSeen;
        private Vector3 previousLeft;
        private Vector3 previousRight;
        private bool leftReady;
        private bool rightReady;
        private readonly List<GameObject> splats = new();
        public bool IsPlayMode { get; private set; }

        public void TogglePlayMode() => SetPlayMode(!IsPlayMode);

        public void SetPlayMode(bool value)
        {
            if (value && (viewer == null || !viewer.HasInputFocus || !viewer.CanEnterPlayMode)) return;
            if (IsPlayMode == value) return;
            IsPlayMode = value;
            if (value) return;
            if (heldTomato != null) Destroy(heldTomato);
            heldTomato = null; heldBody = null;
            foreach (var projectile in FindObjectsByType<TomatoProjectile>(FindObjectsSortMode.None))
                Destroy(projectile.gameObject);
            foreach (var splat in splats) if (splat != null) Destroy(splat);
            splats.Clear();
            viewer?.ClearPlayNudge();
        }

        public void RegisterSplat(GameObject splat) => splats.Add(splat);

        public void Configure(FixtureViewer owner, Hand left, Hand right, Transform controller,
            GameObject model, Texture2D splat)
        {
            viewer = owner; leftHand = left; rightHand = right; rightController = controller;
            tomatoModel = model; splatTexture = splat;
        }

        public void SpawnTomato()
        {
            if (!IsPlayMode || viewer == null || !viewer.HasInputFocus || !viewer.CanEnterPlayMode || tomatoModel == null) return;
            if (heldTomato != null) Destroy(heldTomato);
            heldTomato = new GameObject("Tomato · pinch, swing, and release");
            heldTomato.transform.position = RightPalm();
            heldBody = heldTomato.AddComponent<Rigidbody>();
            heldBody.isKinematic = true;
            heldBody.useGravity = false;
            heldBody.mass = .09f;
            heldBody.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
            var collider = heldTomato.AddComponent<SphereCollider>();
            collider.radius = .048f;
            var visual = Instantiate(tomatoModel, heldTomato.transform);
            visual.name = "CC0 tomato model";
            visual.transform.localPosition = Vector3.zero;
            visual.transform.localRotation = Quaternion.identity;
            visual.transform.localScale = Vector3.one * .045f;
            foreach (var nested in visual.GetComponentsInChildren<Collider>()) Destroy(nested);
            heldTomato.AddComponent<TomatoProjectile>().Configure(viewer, splatTexture);
            spawnedAt = Time.unscaledTime;
            gripSeen = false;
            lastPalm = heldTomato.transform.position;
            palmVelocity = Vector3.zero;
        }

        private void Update()
        {
            if (viewer == null || !viewer.HasInputFocus || !viewer.CanEnterPlayMode)
            {
                SetPlayMode(false);
                leftReady = rightReady = false;
                return;
            }
            if (!IsPlayMode) return;
            CheckSlap(leftHand, ref previousLeft, ref leftReady);
            CheckSlap(rightHand, ref previousRight, ref rightReady);
            if (heldTomato == null) return;
            var palm = RightPalm();
            palmVelocity = Vector3.Lerp(palmVelocity, (palm - lastPalm) / Mathf.Max(.001f, Time.unscaledDeltaTime), .35f);
            lastPalm = palm;
            heldTomato.transform.position = palm;
            var gripping = rightHand != null && rightHand.IsTrackedDataValid && rightHand.GetIndexFingerIsPinching()
                || OVRInput.Get(OVRInput.Button.SecondaryIndexTrigger);
            if (Time.unscaledTime - spawnedAt > .2f && gripping) gripSeen = true;
            if (gripSeen && !gripping) ThrowTomato();
        }

        private Vector3 RightPalm()
        {
            if (rightHand != null && rightHand.IsTrackedDataValid && rightHand.IsHighConfidence &&
                rightHand.GetJointPose(HandJointId.HandWristRoot, out var wrist) &&
                rightHand.GetJointPose(HandJointId.HandMiddle1, out var fingers))
                return Vector3.Lerp(wrist.position, fingers.position, .6f);
            return rightController != null ? rightController.position + rightController.forward * .08f : transform.position;
        }

        private void ThrowTomato()
        {
            heldBody.isKinematic = false;
            heldBody.useGravity = true;
            var forward = rightController != null ? rightController.forward :
                Camera.main != null ? Camera.main.transform.forward : Vector3.forward;
            heldBody.linearVelocity = palmVelocity.magnitude > .6f ? Vector3.ClampMagnitude(palmVelocity, 8f) : forward * 2f;
            heldBody.angularVelocity = new Vector3(5f, 7f, 3f);
            Destroy(heldTomato, 5f);
            heldTomato = null;
            heldBody = null;
        }

        private void CheckSlap(Hand hand, ref Vector3 previous, ref bool ready)
        {
            if (hand == null || !hand.IsTrackedDataValid || !hand.IsHighConfidence ||
                !hand.GetJointPose(HandJointId.HandWristRoot, out var wrist) ||
                !hand.GetJointPose(HandJointId.HandMiddle1, out var fingers))
            { ready = false; return; }
            var palm = Vector3.Lerp(wrist.position, fingers.position, .6f);
            var velocity = ready ? (palm - previous) / Mathf.Max(.001f, Time.unscaledDeltaTime) : Vector3.zero;
            previous = palm; ready = true;
            if (Time.unscaledTime - lastSlapAt < 1.1f || !viewer.TryHeadWorld(out var head)) return;
            var back = head - viewer.ReplayForward * .09f;
            if (Vector3.Distance(palm, back) > .15f || velocity.magnitude < .7f ||
                Vector3.Dot(velocity.normalized, (head - palm).normalized) < .45f) return;
            lastSlapAt = Time.unscaledTime;
            viewer.TriggerPlayNudge(velocity);
        }

        private void OnDestroy()
        {
            if (heldTomato != null) Destroy(heldTomato);
        }
    }
}
