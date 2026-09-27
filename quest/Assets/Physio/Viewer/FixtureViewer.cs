#nullable enable
using System;
using System.Collections;
using System.Collections.Generic;
using NumericsVector3 = System.Numerics.Vector3;
using Oculus.Interaction;
using Oculus.Interaction.HandGrab;
using Physio.Replay;
using UnityEngine;

namespace Physio.Viewer
{
    public sealed partial class FixtureViewer : MonoBehaviour
    {
        private static readonly double[] SupportedSpeeds = { .25, .5, 1, 1.5, 2 };

        [Header("Replay resources")]
        [SerializeField] private string resourcePrefix = "Physio/Demo";
        [SerializeField] private bool runFourFrameFixtureCheck;

        [Header("Scene wiring")]
        [SerializeField] private Transform? replayDisplayRoot;
        [SerializeField] private HandReplayPanel? replayPanel;
        [SerializeField] private GameObject? interactionRigRoot;

        [Header("Materials")]
        [SerializeField] private Material? bodyMaterial;
        [SerializeField] private Material? boneMaterial;
        [SerializeField] private Material? jointMaterial;

        [Header("Placement")]
        [SerializeField] private Vector3 viewerOffset = new(0.25f, -0.6f, 0.75f);
        [SerializeField] private Vector3 panelOffset = new(-0.35f, -0.12f, 0.8f);
        [SerializeField] private float initialDisplayScale = 0.4f;

        private ReplayData? replay;
        private ReplayClock? clock;
        private Mesh? mesh;
        private Vector3[]? meshVertices;
        private int lastRenderedFrame = -1;
        private bool lastRenderedObserved;
        private GameObject? meshObject;
        private BoxCollider? interactionCollider;
        private Rigidbody? interactionBody;
        private readonly List<GameObject> jointObjects = new();
        private readonly List<LineRenderer> boneLines = new();
        private bool ownsReplayDisplayRoot;
        private bool appHasFocus = true;
        private bool appIsPaused;
        private bool ovrHasInputFocus = true;
        private bool hasInputFocus = true;
        private bool loggedFixtureSummary;
        private Pose initialRootPose;
        private Vector3 initialRootScale;
        private int speedIndex = 2;
        private bool skeletonVisible = true;
        private bool leftHandMenuArmed;
        private bool rightHandMenuArmed;
        private OVRPlugin.HandState leftHandState;
        private OVRPlugin.HandState rightHandState;
        private bool isDestroying;
        private OVRCameraRig? deferredPlacementRig;
        private Action<OVRCameraRig>? deferredPlacementAnchorHandler;

        private void Awake()
        {
            PrepareNativePhysicsShell();
            InjectNativeInteractablesIfPresent(requireAll: false);
        }

        private void OnEnable()
        {
            OVRManager.InputFocusLost += HandleInputFocusLost;
            OVRManager.InputFocusAcquired += HandleInputFocusAcquired;
        }

        private void Start()
        {
            InitializeFocusState();
            RequireRenderMaterials();
            EnsureReplayRoot();
            EnsureNativeManipulation();
            replayPanel?.Bind(this);
            if (replayPanel?.GetComponent<WorkflowPanel>() == null || runFourFrameFixtureCheck)
            {
                LoadDemo();
                RunDirectionalEndpointPlaybackCheck();
                if (runFourFrameFixtureCheck) RunFourFrameFixtureRenderCheck();
            }
            else SetReplayVisible(false);
            StartCoroutine(DeferredInitialPlacement());
        }

        private void Update()
        {
            HandleMenuShortcut();
            if (clock == null || replay == null) return;

            if (hasInputFocus && clock.IsPlaying)
            {
                clock = clock.Advance(Time.deltaTime);
                RenderCurrentFrame(force: false);
            }

            replayPanel?.ApplyState(BuildPanelState());
        }

        private void OnApplicationPause(bool paused)
        {
            appIsPaused = paused;
            if (!paused) ovrHasInputFocus = CurrentOvrInputFocus();
            UpdateEffectiveInputFocus();
        }

        private void OnApplicationFocus(bool focus)
        {
            appHasFocus = focus;
            if (focus) ovrHasInputFocus = CurrentOvrInputFocus();
            UpdateEffectiveInputFocus();
        }

        private void OnDisable()
        {
            OVRManager.InputFocusLost -= HandleInputFocusLost;
            OVRManager.InputFocusAcquired -= HandleInputFocusAcquired;
        }

        private void OnDestroy()
        {
            isDestroying = true;
            ClearDeferredPlacementSubscription();
            if (mesh != null) Destroy(mesh);
            if (ownsReplayDisplayRoot && replayDisplayRoot != null) Destroy(replayDisplayRoot.gameObject);
        }

        public void TogglePlay()
        {
            if (!hasInputFocus || clock == null) return;
            if (clock.IsPlaying)
            {
                clock = clock.Pause();
                LogAction("pause");
                return;
            }

            clock = PrepareClockForPlay(clock);
            RenderCurrentFrame(force: true);
            clock = clock.Play();
            LogAction("play");
        }

        public void Restart()
        {
            if (!hasInputFocus || clock == null) return;
            clock = clock.Restart();
            RenderCurrentFrame(force: true);
            LogAction("restart");
        }

        public void StepBack() => Step(-1);
        public void StepForward() => Step(1);

        public void Reverse()
        {
            if (!hasInputFocus || clock == null) return;
            clock = clock.Reverse();
            LogAction("reverse_direction");
        }

        public void CycleSpeed()
        {
            if (!hasInputFocus || clock == null) return;
            speedIndex = (speedIndex + 1) % SupportedSpeeds.Length;
            clock = clock.SetSpeed(SupportedSpeeds[speedIndex]);
            LogAction($"speed_{clock.Speed:0.##}x");
        }

        public void ScaleReplayDown() => ScaleReplay(0.9f);
        public void ScaleReplayUp() => ScaleReplay(1.1f);

        public void ToggleSkeletonVisibility()
        {
            if (!hasInputFocus) return;
            skeletonVisible = !skeletonVisible;
            RenderCurrentFrame(force: true);
            LogAction(skeletonVisible ? "show_skeleton" : "hide_skeleton");
        }

        public void SeekFromPanel(float sourceTime)
        {
            if (!hasInputFocus || clock == null) return;
            clock = clock.Seek(sourceTime);
            RenderCurrentFrame(force: true);
            LogAction("seek");
        }

        public void ResetReplayPlacement()
        {
            if (!hasInputFocus || replayDisplayRoot == null) return;
            replayDisplayRoot.SetPositionAndRotation(initialRootPose.position, initialRootPose.rotation);
            replayDisplayRoot.localScale = initialRootScale;
            LogAction("reset_replay_placement");
        }

        public void BringPanelToView()
        {
            PositionPanel();
            if (replayPanel != null && !replayPanel.gameObject.activeSelf) replayPanel.gameObject.SetActive(true);
            LogAction("bring_panel");
        }

        private void LoadReplay()
        {
            var manifest = LoadTextAsset("replay_manifest");
            var triangles = LoadTextAsset("mesh_triangles");
            var vertices = LoadTextAsset("mesh_vertices");
            var joints = LoadTextAsset("skeleton_joints");
            replay = ReplayImporter.Parse(manifest.bytes, triangles.bytes, vertices.bytes, joints.bytes);
            clock = new ReplayClock(replay.Timeline);
            speedIndex = Array.IndexOf(SupportedSpeeds, clock.Speed);
            if (speedIndex < 0) speedIndex = 2;
            if (!replay.Synthetic)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_REPLAY_REFUSED: default demo must be explicitly labelled synthetic.");
            }

            if (!loggedFixtureSummary)
            {
                Debug.Log($"PHYSIO_VIEWER_LOAD: resource={resourcePrefix} synthetic={replay.Synthetic} frames={replay.FrameCount} vertices={replay.VertexCount} triangles={replay.TriangleCount} joints={replay.JointCount} duration={replay.Timeline.EndTime:0.###} scale={replay.ScaleStatus} provenance=\"{replay.ScaleProvenance}\"");
                loggedFixtureSummary = true;
            }
        }

        private TextAsset LoadTextAsset(string name)
        {
            var asset = Resources.Load<TextAsset>($"{resourcePrefix}/{name}");
            if (asset == null) throw new InvalidOperationException($"Missing Resources replay asset: {resourcePrefix}/{name}");
            return asset;
        }

        private void RequireRenderMaterials()
        {
            if (bodyMaterial != null && boneMaterial != null && jointMaterial != null) return;
            var missing = new List<string>();
            if (bodyMaterial == null) missing.Add(nameof(bodyMaterial));
            if (boneMaterial == null) missing.Add(nameof(boneMaterial));
            if (jointMaterial == null) missing.Add(nameof(jointMaterial));
            throw new InvalidOperationException("PHYSIO_VIEWER_MATERIALS_MISSING: assign serialized viewer materials before build: " + string.Join(", ", missing));
        }

        private void EnsureReplayRoot()
        {
            if (replayDisplayRoot == null)
            {
                replayDisplayRoot = new GameObject("Physio Replay Display").transform;
                ownsReplayDisplayRoot = true;
            }

            PrepareNativePhysicsShell();
            replayDisplayRoot.localScale = Vector3.one * initialDisplayScale;
        }

        private void CaptureInitialPlacement()
        {
            if (replayDisplayRoot == null) return;
            initialRootPose = new Pose(replayDisplayRoot.position, replayDisplayRoot.rotation);
            initialRootScale = replayDisplayRoot.localScale;
        }

        private void PlaceReplayRootFromRig()
        {
            if (replayDisplayRoot == null) return;
            var rig = FindFirstObjectByType<OVRCameraRig>(FindObjectsInactive.Include);
            if (rig != null && rig.centerEyeAnchor != null)
            {
                var yaw = Quaternion.Euler(0f, rig.centerEyeAnchor.eulerAngles.y, 0f);
                replayDisplayRoot.position = rig.centerEyeAnchor.position + yaw * viewerOffset;
                replayDisplayRoot.rotation = yaw;
                return;
            }

            replayDisplayRoot.position = new Vector3(0f, 1.1f, 0.75f);
            replayDisplayRoot.rotation = Quaternion.identity;
        }

        private void BuildMesh()
        {
            if (replay == null || replayDisplayRoot == null) return;

            meshVertices = new Vector3[replay.VertexCount];
            var triangles = new int[replay.TriangleCount * 3];
            for (var i = 0; i < triangles.Length; i++)
            {
                triangles[i] = replay.TriangleIndexAt(i);
            }

            mesh = new Mesh { name = "Physio replay mesh", indexFormat = replay.VertexCount > 65535 ? UnityEngine.Rendering.IndexFormat.UInt32 : UnityEngine.Rendering.IndexFormat.UInt16 };
            mesh.MarkDynamic();
            mesh.vertices = meshVertices;
            mesh.triangles = triangles;
            mesh.RecalculateBounds();
            mesh.RecalculateNormals();

            meshObject = new GameObject(replay.Synthetic ? "Authored synthetic body" : "Patient fitted estimated body");
            meshObject.transform.SetParent(replayDisplayRoot, false);
            meshObject.AddComponent<MeshFilter>().sharedMesh = mesh;
            var meshRenderer = meshObject.AddComponent<MeshRenderer>();
            meshRenderer.sharedMaterial = bodyMaterial;
        }

        private void BuildSkeleton()
        {
            if (replay == null || replayDisplayRoot == null) return;

            for (var i = 0; i < replay.JointCount; i++)
            {
                var joint = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                joint.name = $"Joint {i} {replay.JointNameAt(i)}";
                joint.transform.SetParent(replayDisplayRoot, false);
                joint.transform.localScale = Vector3.one * 0.018f;
                joint.GetComponent<Renderer>().sharedMaterial = jointMaterial;
                jointObjects.Add(joint);

                if (replay.JointParentAt(i) < 0) continue;
                var bone = new GameObject($"Bone {replay.JointParentAt(i)} to {i}").AddComponent<LineRenderer>();
                bone.transform.SetParent(replayDisplayRoot, false);
                bone.useWorldSpace = false;
                bone.positionCount = 2;
                bone.startWidth = 0.008f;
                bone.endWidth = 0.008f;
                bone.sharedMaterial = boneMaterial;
                boneLines.Add(bone);
            }
        }

        private void EnsureNativeManipulation()
        {
            if (replayDisplayRoot == null) return;
            PrepareNativePhysicsShell();
            if (interactionBody == null)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_NATIVE_MANIPULATION_MISSING: replay display Rigidbody was not created.");
            }

            var transformer = replayDisplayRoot.GetComponentInChildren<GrabFreeTransformer>(true);
            var grabbable = replayDisplayRoot.GetComponentInChildren<Grabbable>(true);
            if (transformer == null || grabbable == null)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_NATIVE_MANIPULATION_MISSING: builder must provide Grabbable and configured GrabFreeTransformer for two-hand scale.");
            }

            InjectNativeInteractablesIfPresent(requireAll: true);

            Debug.Log("PHYSIO_VIEWER_NATIVE_MANIPULATION: Grabbable GrabFreeTransformer GrabInteractable HandGrabInteractable configured");
        }

        private void InjectNativeInteractablesIfPresent(bool requireAll)
        {
            if (replayDisplayRoot == null || interactionBody == null) return;
            var controllerGrab = replayDisplayRoot.GetComponentInChildren<GrabInteractable>(true);
            if (controllerGrab != null)
            {
                controllerGrab.InjectRigidbody(interactionBody);
                controllerGrab.UseClosestPointAsGrabSource = true;
            }
            else if (requireAll)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_NATIVE_MANIPULATION_MISSING: builder must provide GrabInteractable for controller manipulation.");
            }

            var handGrab = replayDisplayRoot.GetComponentInChildren<HandGrabInteractable>(true);
            if (handGrab != null)
            {
                handGrab.InjectRigidbody(interactionBody);
            }
            else if (requireAll)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_NATIVE_MANIPULATION_MISSING: builder must provide HandGrabInteractable for hand manipulation.");
            }
        }

        private void PrepareNativePhysicsShell()
        {
            if (replayDisplayRoot == null) return;
            interactionBody = replayDisplayRoot.GetComponent<Rigidbody>() ?? replayDisplayRoot.gameObject.AddComponent<Rigidbody>();
            interactionBody.useGravity = false;
            interactionBody.isKinematic = true;
            interactionCollider = replayDisplayRoot.GetComponent<BoxCollider>();
            if (interactionCollider == null)
            {
                interactionCollider = replayDisplayRoot.gameObject.AddComponent<BoxCollider>();
                interactionCollider.isTrigger = false;
                interactionCollider.size = Vector3.one;
            }
        }

        private void BindPanel()
        {
            if (replayPanel == null || clock == null)
            {
                Debug.LogWarning("PHYSIO_VIEWER_PANEL_MISSING: runtime panel is not assigned.");
                return;
            }

            replayPanel.Bind(this);
            replayPanel.ConfigureTimeline((float)clock.Timeline.StartTime, (float)clock.Timeline.EndTime);
            replayPanel.ApplyState(BuildPanelState());
        }

        private HandReplayPanel.State BuildPanelState()
        {
            if (clock == null || replay == null)
            {
                return HandReplayPanel.Empty;
            }

            var sample = clock.Sample;
            var atEnd = Math.Abs(clock.CursorTime - clock.Timeline.EndTime) < 0.0001;
            return new HandReplayPanel.State
            {
                Title = replay.Synthetic ? "SYNTHETIC REPLAY LAB" : "SOURCE REPLAY",
                Status = !sample.IsObserved ? "Missing observation · body hidden" : replay.Synthetic ? "Authored synthetic demo" : $"Estimated anatomy · scale {replay.ScaleStatus}",
                Time = $"{sample.SourceTime:0.00}s / {clock.Timeline.EndTime:0.00}s",
                PlayPause = clock.IsPlaying ? "Pause" : atEnd ? "Replay" : "Play",
                Reverse = clock.Direction > 0 ? "Direction: forward" : "Direction: reverse",
                Speed = $"{clock.Speed:0.##}x",
                Skeleton = skeletonVisible ? "Skeleton On" : "Skeleton Off",
                SeekTime = (float)clock.CursorTime,
                CanInteract = hasInputFocus
            };
        }

        private void RenderCurrentFrame(bool force)
        {
            if (replay == null || clock == null || mesh == null || meshVertices == null) return;

            var sample = clock.Sample;
            var observed = sample.IsObserved;
            if (!force && sample.Index == lastRenderedFrame && observed == lastRenderedObserved) return;
            lastRenderedFrame = sample.Index;
            lastRenderedObserved = observed;

            var localBounds = new Bounds(Vector3.zero, new Vector3(0.35f, 0.5f, 0.35f));
            if (meshObject != null) meshObject.SetActive(observed);
            if (observed)
            {
                for (var i = 0; i < meshVertices.Length; i++)
                {
                    meshVertices[i] = ToUnity(replay.VertexAt(sample.Index, i));
                    if (i == 0) localBounds = new Bounds(meshVertices[i], Vector3.zero);
                    else localBounds.Encapsulate(meshVertices[i]);
                }
                mesh.vertices = meshVertices;
                mesh.RecalculateBounds();
                mesh.RecalculateNormals();
            }

            for (var i = 0; i < jointObjects.Count; i++)
            {
                var valid = skeletonVisible && observed && replay.IsJointValid(sample.Index, i);
                jointObjects[i].SetActive(valid);
                if (!valid) continue;
                var jointPosition = ToUnity(replay.JointAt(sample.Index, i));
                jointObjects[i].transform.localPosition = jointPosition;
                localBounds.Encapsulate(jointPosition);
            }

            var boneIndex = 0;
            for (var i = 0; i < replay.JointCount; i++)
            {
                var parent = replay.JointParentAt(i);
                if (parent < 0) continue;
                var valid = skeletonVisible && observed && replay.IsJointValid(sample.Index, parent) && replay.IsJointValid(sample.Index, i);
                var bone = boneLines[boneIndex++];
                bone.gameObject.SetActive(valid);
                if (!valid) continue;
                bone.SetPosition(0, ToUnity(replay.JointAt(sample.Index, parent)));
                bone.SetPosition(1, ToUnity(replay.JointAt(sample.Index, i)));
            }

            UpdateInteractionBounds(localBounds);
            Debug.Log($"PHYSIO_VIEWER_FRAME: frame_index={sample.Index} source_frame_id={sample.SourceFrameId} source_time={sample.SourceTime:0.###} observed={observed} playing={clock.IsPlaying} speed={clock.Speed:0.##} direction={clock.Direction}");
        }

        private void UpdateInteractionBounds(Bounds localBounds)
        {
            if (interactionCollider == null) return;
            var padded = localBounds.size + new Vector3(0.12f, 0.12f, 0.12f);
            padded.x = Mathf.Max(padded.x, 0.25f);
            padded.y = Mathf.Max(padded.y, 0.35f);
            padded.z = Mathf.Max(padded.z, 0.25f);
            interactionCollider.center = localBounds.center;
            interactionCollider.size = padded;
        }

        private void Step(int direction)
        {
            if (!hasInputFocus || clock == null) return;
            clock = clock.Step(direction);
            RenderCurrentFrame(force: true);
            LogAction(direction > 0 ? "step_forward" : "step_back");
        }

        private void ScaleReplay(float multiplier)
        {
            if (!hasInputFocus || replayDisplayRoot == null) return;
            var current = replayDisplayRoot.localScale.x;
            var target = Mathf.Clamp(current * multiplier, 0.2f, 1.2f);
            replayDisplayRoot.localScale = Vector3.one * target;
            LogAction($"scale_replay_{target:0.###}");
        }

        private void PositionPanel()
        {
            if (replayPanel == null || replayDisplayRoot == null) return;
            var eye = GetEyeTransform();
            if (eye != null)
            {
                var yaw = Quaternion.Euler(0f, eye.eulerAngles.y, 0f);
                replayPanel.transform.position = eye.position + yaw * panelOffset;
            }
            else
            {
                replayPanel.transform.position = panelOffset;
            }
            if (eye == null) return;
            var awayFromEye = replayPanel.transform.position - eye.position;
            if (awayFromEye.sqrMagnitude > 0.0001f)
                replayPanel.transform.rotation = Quaternion.LookRotation(awayFromEye.normalized, Vector3.up);
        }

        private IEnumerator DeferredInitialPlacement()
        {
            yield return null;

            var waitedFrames = 0;
            while (!isDestroying && !HasEffectiveInputFocusNow())
            {
                waitedFrames++;
                yield return null;
            }

            var rig = FindFirstObjectByType<OVRCameraRig>(FindObjectsInactive.Include);
            var anchorUpdated = false;
            deferredPlacementRig = rig;
            deferredPlacementAnchorHandler = _ => anchorUpdated = HasEffectiveInputFocusNow();
            if (deferredPlacementRig != null) deferredPlacementRig.UpdatedAnchors += deferredPlacementAnchorHandler;

            try
            {
                while (!isDestroying && (!HasEffectiveInputFocusNow() || !HasUsableHeadPose() || !anchorUpdated))
                {
                    if (!HasEffectiveInputFocusNow()) anchorUpdated = false;
                    waitedFrames++;
                    yield return null;
#if UNITY_EDITOR
                    if (waitedFrames > 2) break;
#else
                    if (waitedFrames % 120 == 0)
                    {
                        Debug.Log($"PHYSIO_VIEWER_DEFERRED_PLACEMENT_WAIT: input_focus={hasInputFocus} tracked_head_pose={HasUsableHeadPose()} anchor_updated={anchorUpdated} waited_frames={waitedFrames}");
                    }
#endif
                }

                if (isDestroying) yield break;

                PlaceReplayRootFromRig();
                if (replayDisplayRoot != null)
                {
                    replayDisplayRoot.localScale = Vector3.one * initialDisplayScale;
                    CaptureInitialPlacement();
                }
                PositionPanel();
                RenderCurrentFrame(force: true);
                Debug.Log($"PHYSIO_VIEWER_DEFERRED_PLACEMENT: input_focus=true tracked_head_pose={HasUsableHeadPose()} waited_frames={waitedFrames}");
                Debug.Log($"PHYSIO_VIEWER_READY: resource={resourcePrefix} start_paused=true source_frame={clock?.Sample.SourceFrameId}");
            }
            finally
            {
                ClearDeferredPlacementSubscription();
            }
        }

        private void RunFourFrameFixtureRenderCheck()
        {
            if (clock == null || replay == null) throw new InvalidOperationException("PHYSIO_VIEWER_FIXTURE_CHECK_FAIL: replay missing.");
            if (replay.FrameCount != 4 || clock.Timeline.EndTime > 0.21)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_FIXTURE_CHECK_FAIL: four-frame diagnostic fixture expected.");
            }

            clock = clock.Seek(0.04);
            RenderCurrentFrame(force: false);
            AssertRenderState("time_0.04", meshVisible: true, visibleJoints: 2);
            clock = clock.Seek(0.08);
            RenderCurrentFrame(force: false);
            AssertRenderState("time_0.08_gap_same_index", meshVisible: false, visibleJoints: 0);
            clock = clock.Seek(0.04);
            RenderCurrentFrame(force: false);
            AssertRenderState("time_0.04_restore", meshVisible: true, visibleJoints: 2);
            clock = clock.Seek(0.11);
            RenderCurrentFrame(force: false);
            AssertRenderState("time_0.11_invalid_frame", meshVisible: false, visibleJoints: 0);
            clock = clock.Seek(0.2);
            RenderCurrentFrame(force: false);
            AssertRenderState("time_0.20_final", meshVisible: true, visibleJoints: 3);
            clock = clock.Restart();
            RenderCurrentFrame(force: true);
            Debug.Log("PHYSIO_VIEWER_FOUR_FRAME_FIXTURE_CHECK: PASS");
        }

        private void RunDirectionalEndpointPlaybackCheck()
        {
            if (replay == null) throw new InvalidOperationException("PHYSIO_VIEWER_ENDPOINT_CHECK_FAIL: replay missing.");
            var timeline = replay.Timeline;
            var forwardAtEnd = new ReplayClock(timeline).Seek(timeline.EndTime);
            var preparedForward = PrepareClockForPlay(forwardAtEnd);
            if (!IsAtStart(preparedForward) || preparedForward.Direction != 1)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_ENDPOINT_CHECK_FAIL: forward replay at end must restart at the beginning.");
            }

            var reverseAtEnd = new ReplayClock(timeline).Seek(timeline.EndTime).Reverse();
            var preparedReverseAtEnd = PrepareClockForPlay(reverseAtEnd);
            if (!IsAtEnd(preparedReverseAtEnd) || preparedReverseAtEnd.Direction != -1)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_ENDPOINT_CHECK_FAIL: reverse play at end must stay at the end and move backward.");
            }

            var reverseAtStart = new ReplayClock(timeline).Reverse();
            var preparedReverseAtStart = PrepareClockForPlay(reverseAtStart);
            if (!IsAtEnd(preparedReverseAtStart) || preparedReverseAtStart.Direction != -1)
            {
                throw new InvalidOperationException("PHYSIO_VIEWER_ENDPOINT_CHECK_FAIL: reverse replay at start must begin from the end.");
            }

            Debug.Log("PHYSIO_VIEWER_ENDPOINT_CHECK: PASS directional replay endpoints");
        }

        private void AssertRenderState(string label, bool meshVisible, int visibleJoints)
        {
            var actualMesh = meshObject != null && meshObject.activeSelf;
            var actualJoints = 0;
            foreach (var joint in jointObjects)
            {
                if (joint != null && joint.activeSelf) actualJoints++;
            }

            if (actualMesh != meshVisible || actualJoints != visibleJoints)
            {
                throw new InvalidOperationException($"PHYSIO_VIEWER_FIXTURE_CHECK_FAIL: {label} mesh={actualMesh} expected={meshVisible} joints={actualJoints} expected={visibleJoints}");
            }
        }

        private void HandleInputFocusLost()
        {
            ovrHasInputFocus = false;
            UpdateEffectiveInputFocus();
        }

        private void HandleInputFocusAcquired()
        {
            ovrHasInputFocus = CurrentOvrInputFocus();
            UpdateEffectiveInputFocus();
        }

        private void InitializeFocusState()
        {
            appHasFocus = Application.isFocused;
            appIsPaused = false;
            ovrHasInputFocus = CurrentOvrInputFocus();
            UpdateEffectiveInputFocus();
        }

        private static bool CurrentOvrInputFocus()
        {
#if UNITY_EDITOR
            return true;
#else
            return OVRManager.hasInputFocus;
#endif
        }

        private void UpdateEffectiveInputFocus()
        {
            var next = HasEffectiveInputFocusNow();
            if (hasInputFocus == next) return;
            hasInputFocus = next;
            if (!hasInputFocus)
            {
                if (clock != null) clock = clock.Pause();
                leftHandMenuArmed = false;
                rightHandMenuArmed = false;
                SetInteractionEnabled(false);
                Debug.Log("PHYSIO_VIEWER_FOCUS_LOST: playback_paused=true interaction_rig_enabled=false");
                return;
            }

            SetInteractionEnabled(true);
            Debug.Log("PHYSIO_VIEWER_FOCUS_ACQUIRED: interaction_rig_enabled=true");
        }

        private bool HasEffectiveInputFocusNow() => appHasFocus && !appIsPaused && ovrHasInputFocus && CurrentOvrInputFocus();

        private void SetInteractionEnabled(bool enabled)
        {
            if (interactionRigRoot != null) interactionRigRoot.SetActive(enabled);
            replayPanel?.ApplyState(BuildPanelState());
        }

        private void HandleMenuShortcut()
        {
            if (!hasInputFocus) return;
            var handMenuPressed = IsHandMenuPressedEdge();
            if (OVRInput.GetDown(OVRInput.Button.Start) || handMenuPressed)
            {
                BringPanelToView();
                replayPanel?.GetComponent<WorkflowPanel>()?.OpenOptions();
            }
        }

        private bool IsHandMenuPressedEdge() =>
            UpdateHandMenuEdge(OVRPlugin.Hand.HandLeft, ref leftHandState, ref leftHandMenuArmed)
            | UpdateHandMenuEdge(OVRPlugin.Hand.HandRight, ref rightHandState, ref rightHandMenuArmed);

        private static bool UpdateHandMenuEdge(OVRPlugin.Hand hand, ref OVRPlugin.HandState state, ref bool armed)
        {
#if UNITY_EDITOR
            return false;
#else
            var read = OVRPlugin.GetHandState(OVRPlugin.Step.Render, hand, ref state);
            var pressed = read && (state.Status & OVRPlugin.HandStatus.MenuPressed) != 0;
            return HandMenuPressEdge.Update(read, pressed, ref armed);
#endif
        }

        private Transform? GetEyeTransform()
        {
            var rig = FindFirstObjectByType<OVRCameraRig>(FindObjectsInactive.Include);
            if (rig != null && rig.centerEyeAnchor != null) return rig.centerEyeAnchor;
            return Camera.main != null ? Camera.main.transform : null;
        }

        private void ClearDeferredPlacementSubscription()
        {
            if (deferredPlacementRig != null && deferredPlacementAnchorHandler != null)
            {
                deferredPlacementRig.UpdatedAnchors -= deferredPlacementAnchorHandler;
            }

            deferredPlacementRig = null;
            deferredPlacementAnchorHandler = null;
        }

        private static bool HasUsableHeadPose()
        {
#if UNITY_EDITOR
            return true;
#else
            const OVRPlugin.Node head = OVRPlugin.Node.Head;
            return OVRPlugin.GetNodeOrientationTracked(head)
                && OVRPlugin.GetNodeOrientationValid(head)
                && OVRPlugin.GetNodePositionTracked(head)
                && OVRPlugin.GetNodePositionValid(head);
#endif
        }

        private static bool IsAtStart(ReplayClock value) =>
            Math.Abs(value.CursorTime - value.Timeline.StartTime) < 0.0001;

        private static bool IsAtEnd(ReplayClock value) =>
            Math.Abs(value.CursorTime - value.Timeline.EndTime) < 0.0001;

        private static ReplayClock PrepareClockForPlay(ReplayClock value)
        {
            if (IsAtEnd(value) && value.Direction > 0)
            {
                return value.Restart();
            }

            if (IsAtStart(value) && value.Direction < 0)
            {
                return value.Seek(value.Timeline.EndTime);
            }

            return value;
        }

        private void LogAction(string action)
        {
            if (clock == null) return;
            var sample = clock.Sample;
            Debug.Log($"PHYSIO_VIEWER_ACTION: action={action} source_frame_id={sample.SourceFrameId} frame_index={sample.Index} observed={sample.IsObserved} cursor={clock.CursorTime:0.###}");
        }

        private static Vector3 ToUnity(NumericsVector3 value) => new(value.X, value.Y, value.Z);
    }
}
