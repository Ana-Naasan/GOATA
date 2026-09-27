#nullable enable
using System;
using TMPro;
using UnityEngine;

namespace Physio.Viewer
{
    public sealed partial class FixtureViewer
    {
        private string regionLabel = "";
        private LineRenderer? regionHalo;
        private LineRenderer? regionLeader;
        private TMP_Text? regionCaption;
        private GameObject? regionCaptionRoot;
        private readonly Vector3[] regionHaloPoints = new Vector3[33];

        private void ClearRegionMarker()
        {
            regionLabel = "";
            HideRegionMarker();
            replayPanel?.ClearEvidence();
        }

        private void HideRegionMarker()
        {
            if (regionHalo != null) regionHalo.gameObject.SetActive(false);
            if (regionLeader != null) regionLeader.gameObject.SetActive(false);
            if (regionCaptionRoot != null) regionCaptionRoot.SetActive(false);
        }

        private void UpdateRegionMarker()
        {
            var visible = findingHighlightVisible && clock?.Sample.IsObserved == true && replay != null && regionLabel.Length > 0;
            var found = false; var bounds = new Bounds();
            if (visible)
                for (var index = 0; index < replay!.JointCount; index++)
                {
                    if (Array.IndexOf(findingJointNames, replay.JointNameAt(index)) < 0 || !replay.IsJointValid(clock!.Sample.Index, index)) continue;
                    var point = ToUnity(replay.JointAt(clock!.Sample.Index, index));
                    if (!found) bounds = new Bounds(point, Vector3.zero); else bounds.Encapsulate(point);
                    found = true;
                }
            if (!found)
            {
                HideRegionMarker();
                return;
            }
            EnsureRegionMarker();
            var radiusX = Mathf.Max(bounds.extents.x + .075f, .085f);
            var radiusY = Mathf.Max(bounds.extents.y + .075f, .10f);
            var z = bounds.center.z - .04f;
            for (var index = 0; index < regionHaloPoints.Length; index++)
            {
                var angle = index * (Mathf.PI * 2f / (regionHaloPoints.Length - 1));
                regionHaloPoints[index] = new Vector3(bounds.center.x + Mathf.Cos(angle) * radiusX,
                    bounds.center.y + Mathf.Sin(angle) * radiusY, z);
            }
            regionHalo!.SetPositions(regionHaloPoints); regionHalo.gameObject.SetActive(true);
            var labelPosition = new Vector3(bounds.center.x + radiusX + .16f, bounds.center.y + radiusY + .10f, z);
            regionLeader!.SetPosition(0, new Vector3(bounds.center.x + radiusX, bounds.center.y, z));
            regionLeader.SetPosition(1, labelPosition);
            regionLeader.gameObject.SetActive(true);
            regionCaption!.text = regionLabel + " · estimated";
            regionCaptionRoot!.transform.localPosition = labelPosition;
            regionCaptionRoot.SetActive(true);
        }

        private void EnsureRegionMarker()
        {
            if (regionHalo != null) return;
            var halo = new GameObject("Selected anatomy halo");
            halo.transform.SetParent(replayDisplayRoot, false);
            regionHalo = halo.AddComponent<LineRenderer>();
            regionHalo.useWorldSpace = false; regionHalo.positionCount = regionHaloPoints.Length; regionHalo.widthMultiplier = .012f;
            regionHalo.sharedMaterial = boneMaterial;
            var properties = new MaterialPropertyBlock(); properties.SetColor("_Color", new Color(1f, .78f, .25f));
            regionHalo.SetPropertyBlock(properties);
            var leader = new GameObject("Selected anatomy callout");
            leader.transform.SetParent(replayDisplayRoot, false);
            regionLeader = leader.AddComponent<LineRenderer>();
            regionLeader.useWorldSpace = false; regionLeader.positionCount = 2; regionLeader.widthMultiplier = .006f;
            regionLeader.sharedMaterial = boneMaterial; regionLeader.SetPropertyBlock(properties);
            regionCaptionRoot = new GameObject("Selected evidence region label", typeof(Canvas));
            regionCaptionRoot.transform.SetParent(replayDisplayRoot, false);
            regionCaptionRoot.GetComponent<Canvas>().renderMode = RenderMode.WorldSpace;
            regionCaptionRoot.transform.localScale = Vector3.one * .0025f;
            var label = new GameObject("Region label", typeof(RectTransform), typeof(TextMeshProUGUI));
            label.transform.SetParent(regionCaptionRoot.transform, false);
            regionCaption = label.GetComponent<TextMeshProUGUI>();
            regionCaption.rectTransform.sizeDelta = new Vector2(420, 60);
            regionCaption.font = TMP_Settings.defaultFontAsset; regionCaption.fontSize = 22;
            regionCaption.alignment = TextAlignmentOptions.Center; regionCaption.color = new Color(1f, .86f, .5f);
            regionCaption.richText = false; regionCaption.raycastTarget = false;
        }

        private void LateUpdate()
        {
            MaintainGroundedReplay();
            if (regionCaptionRoot == null || !regionCaptionRoot.activeSelf) return;
            var eye = GetEyeTransform();
            if (eye == null) return;
            var direction = regionCaptionRoot.transform.position - eye.position;
            if (direction.sqrMagnitude > .0001f) regionCaptionRoot.transform.rotation = Quaternion.LookRotation(direction, Vector3.up);
        }

        private void MaintainGroundedReplay()
        {
            if (replayDisplayRoot == null || replay == null) return;
            var rig = FindFirstObjectByType<OVRCameraRig>();
            if (rig == null || rig.trackingSpace == null) return;
            var point = replayDisplayRoot.position;
            point.y = rig.trackingSpace.position.y - firstSurfaceBottom * replayDisplayRoot.lossyScale.y;
            replayDisplayRoot.position = point;
        }
    }
}
