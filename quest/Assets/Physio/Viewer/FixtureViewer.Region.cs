#nullable enable
using System;
using TMPro;
using UnityEngine;

namespace Physio.Viewer
{
    public sealed partial class FixtureViewer
    {
        private string regionLabel = "";
        private LineRenderer? regionBracket;
        private TMP_Text? regionCaption;
        private GameObject? regionCaptionRoot;
        private readonly Vector3[] regionCorners = new Vector3[5];

        private void ClearRegionMarker()
        {
            regionLabel = "";
            HideRegionMarker();
            replayPanel?.ClearEvidence();
        }

        private void HideRegionMarker()
        {
            if (regionBracket != null) regionBracket.gameObject.SetActive(false);
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
            bounds.Expand(.12f);
            var low = bounds.min; var high = bounds.max; var z = bounds.center.z;
            regionCorners[0] = new Vector3(low.x, low.y, z); regionCorners[1] = new Vector3(low.x, high.y, z);
            regionCorners[2] = new Vector3(high.x, high.y, z); regionCorners[3] = new Vector3(high.x, low.y, z); regionCorners[4] = regionCorners[0];
            regionBracket!.SetPositions(regionCorners); regionBracket.gameObject.SetActive(true);
            regionCaption!.text = regionLabel + " · estimated region";
            regionCaptionRoot!.transform.localPosition = new Vector3(bounds.center.x, high.y + .1f, z);
            regionCaptionRoot.SetActive(true);
        }

        private void EnsureRegionMarker()
        {
            if (regionBracket != null) return;
            var bracket = new GameObject("Selected evidence region bracket");
            bracket.transform.SetParent(replayDisplayRoot, false);
            regionBracket = bracket.AddComponent<LineRenderer>();
            regionBracket.useWorldSpace = false; regionBracket.positionCount = 5; regionBracket.widthMultiplier = .009f;
            regionBracket.sharedMaterial = boneMaterial;
            var properties = new MaterialPropertyBlock(); properties.SetColor("_Color", new Color(1f, .78f, .25f));
            regionBracket.SetPropertyBlock(properties);
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
            if (regionCaptionRoot == null || !regionCaptionRoot.activeSelf) return;
            var eye = GetEyeTransform();
            if (eye == null) return;
            var direction = regionCaptionRoot.transform.position - eye.position;
            if (direction.sqrMagnitude > .0001f) regionCaptionRoot.transform.rotation = Quaternion.LookRotation(direction, Vector3.up);
        }
    }
}
