#nullable enable
using System;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    /// <summary>Compact, display-only weighted score dial. Scoring remains in the replay domain.</summary>
    public sealed class GoataScoreGauge : MaskableGraphic
    {
        [SerializeField] private TMP_Text? scoreLabel;
        [SerializeField] private TMP_Text? deductionsLabel;
        private int? displayedScore;

        public void Configure(TMP_FontAsset font, Material fontMaterial)
        {
            raycastTarget = false;
            scoreLabel = AddLabel("GoataScore value", font, fontMaterial, 25f, new Vector2(198f, -4f), new Vector2(-8f, -36f));
            deductionsLabel = AddLabel("GoataScore deductions", font, fontMaterial, 19f, new Vector2(198f, -40f), new Vector2(-8f, -86f));
            var legend = AddLabel("GoataScore bands", font, fontMaterial, 16f, new Vector2(198f, -88f), new Vector2(-8f, -110f));
            legend.text = "Red 0-50  |  Yellow 51-90  |  Green 91-100";
            var minimum = AddLabel("Dial minimum", font, fontMaterial, 18f, new Vector2(15f, -88f), new Vector2(49f, -110f), false);
            minimum.text = "0";
            var maximum = AddLabel("Dial maximum", font, fontMaterial, 18f, new Vector2(143f, -88f), new Vector2(188f, -110f), false);
            maximum.text = "100";
            SetScore(null, "Not enough data");
        }

        public void SetScore(double? score, string deductionSummary)
        {
            displayedScore = score.HasValue && !double.IsNaN(score.Value) && !double.IsInfinity(score.Value)
                && score.Value >= 0 && score.Value <= 100
                ? (int)Math.Round(score.Value, MidpointRounding.AwayFromZero) : null;
            if (scoreLabel != null) scoreLabel.text = displayedScore.HasValue
                ? $"GoataScore (demo)  {displayedScore.Value} / 100" : "GoataScore (demo)  -- / 100";
            if (deductionsLabel != null) deductionsLabel.text = displayedScore.HasValue
                ? deductionSummary : "Not enough data";
            SetVerticesDirty();
        }

        protected override void OnPopulateMesh(VertexHelper mesh)
        {
            mesh.Clear();
            var rect = rectTransform.rect;
            var origin = new Vector2(rect.xMin + 96f, rect.yMax - 86f);
            const float radius = 74f;
            const int segments = 60;
            for (var index = 0; index < segments; index++)
            {
                var from = index * 100f / segments;
                var to = (index + 1) * 100f / segments;
                var band = !displayedScore.HasValue ? new Color(.3f, .36f, .42f, 1f)
                    : to <= 50f ? new Color(.96f, .34f, .31f, 1f)
                    : to <= 90f ? new Color(1f, .77f, .22f, 1f) : new Color(.32f, .83f, .49f, 1f);
                Quad(mesh, origin + Point(from, radius), origin + Point(to, radius),
                    origin + Point(to, radius - 12f), origin + Point(from, radius - 12f), band);
            }
            if (!displayedScore.HasValue) return;
            var direction = Point(displayedScore.Value, 1f);
            var across = new Vector2(-direction.y, direction.x) * 2.5f;
            Quad(mesh, origin - across, origin + across,
                origin + direction * (radius - 17f) + across,
                origin + direction * (radius - 17f) - across, Color.white);
        }

        private static Vector2 Point(float score, float radius)
        {
            var angle = Mathf.PI * (1f - score / 100f);
            return new Vector2(Mathf.Cos(angle), Mathf.Sin(angle)) * radius;
        }

        private static void Quad(VertexHelper mesh, Vector2 a, Vector2 b, Vector2 c, Vector2 d, Color tint)
        {
            var start = mesh.currentVertCount;
            mesh.AddVert(a, tint, Vector2.zero); mesh.AddVert(b, tint, Vector2.zero);
            mesh.AddVert(c, tint, Vector2.zero); mesh.AddVert(d, tint, Vector2.zero);
            mesh.AddTriangle(start, start + 1, start + 2);
            mesh.AddTriangle(start, start + 2, start + 3);
        }

        private TMP_Text AddLabel(string labelName, TMP_FontAsset font, Material fontMaterial,
            float size, Vector2 topLeft, Vector2 bottomRight, bool stretchWidth = true)
        {
            var root = new GameObject(labelName, typeof(RectTransform), typeof(TextMeshProUGUI));
            root.transform.SetParent(transform, false);
            var label = root.GetComponent<TextMeshProUGUI>();
            label.font = font; label.fontSharedMaterial = fontMaterial; label.fontSize = size;
            label.color = Color.white; label.richText = false; label.raycastTarget = false;
            label.overflowMode = TextOverflowModes.Ellipsis;
            label.alignment = TextAlignmentOptions.TopLeft;
            var bounds = label.rectTransform;
            bounds.anchorMin = new Vector2(0f, 1f);
            bounds.anchorMax = new Vector2(stretchWidth ? 1f : 0f, 1f);
            bounds.offsetMin = new Vector2(topLeft.x, bottomRight.y);
            bounds.offsetMax = new Vector2(bottomRight.x, topLeft.y);
            return label;
        }
    }
}
