using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    /// <summary>A small authored pose diagram for capture instruction, never patient evidence.</summary>
    public sealed class MovementExample : MonoBehaviour
    {
        [SerializeField] private RectTransform diagram;
        [SerializeField] private TMP_Text caption;
        private readonly RectTransform[] strokes = new RectTransform[12];
        private string test = "";
        private float nextFrame;

        public void Configure(RectTransform target, TMP_Text label) { diagram = target; caption = label; }

        public void SetTest(string value)
        {
            if (test == value) return;
            test = value;
            caption.text = value switch
            {
                "elk" => "Seated: arm overhead, lean away, return. Repeat the other side.",
                "rtk" => "Seated: arms in a T, turn the torso left and right.",
                "walking" => "Walk straight past the camera; keep the full body in view.",
                _ => "Movement example unavailable."
            };
        }

        private void EnsureStrokes()
        {
            if (strokes[0] != null || diagram == null) return;
            for (var i = 0; i < strokes.Length; i++)
            {
                var line = new GameObject("Pose stroke " + i, typeof(RectTransform), typeof(Image));
                line.transform.SetParent(diagram, false);
                var image = line.GetComponent<Image>();
                image.color = i == 10 || i == 11 ? new Color(.36f, .46f, .55f) :
                    i == 0 ? new Color(.95f, .78f, .39f) : new Color(.50f, .87f, 1f);
                image.raycastTarget = false;
                strokes[i] = line.GetComponent<RectTransform>();
            }
        }

        private void Update()
        {
            EnsureStrokes();
            if (strokes[0] == null) return;
            if (Time.unscaledTime < nextFrame) return;
            nextFrame = Time.unscaledTime + .05f;
            var phase = Time.unscaledTime * 1.5f;
            if (test == "walking") DrawWalking(phase);
            else DrawSeated(phase, test == "elk");
        }

        private void DrawSeated(float phase, bool flank)
        {
            var hip = new Vector2(0, -20);
            var shift = flank ? -24f * Mathf.Sin(phase) : 0f;
            var shoulder = new Vector2(shift, 35);
            var left = shoulder + new Vector2(-22, -4);
            var right = shoulder + new Vector2(22, -4);
            var twist = flank ? 1f : Mathf.Cos(phase);
            var leftHand = flank ? left + new Vector2(-28, -38) :
                left + new Vector2(-50f * twist, 12f * Mathf.Sin(phase));
            var rightHand = flank ? right + new Vector2(23, 55) :
                right + new Vector2(50f * twist, -12f * Mathf.Sin(phase));
            Draw(0, hip, shoulder);
            Draw(1, shoulder + new Vector2(0, 8), shoulder + new Vector2(0, 23), 15f);
            Draw(2, left, leftHand);
            Draw(3, right, rightHand);
            Draw(4, left, right, 4f);
            Draw(5, hip, new Vector2(-25, -32));
            Draw(6, new Vector2(-25, -32), new Vector2(-25, -61));
            Draw(7, hip, new Vector2(25, -32));
            Draw(8, new Vector2(25, -32), new Vector2(25, -61));
            Draw(9, new Vector2(-20, -64), new Vector2(20, -64));
            Draw(10, new Vector2(-46, -33), new Vector2(46, -33), 4f);
            Draw(11, new Vector2(-39, -33), new Vector2(-39, -62), 4f);
        }

        private void DrawWalking(float phase)
        {
            var swing = Mathf.Sin(phase * 2f);
            var hip = new Vector2(0, -8);
            var shoulder = new Vector2(0, 43);
            Draw(0, hip, shoulder);
            Draw(1, shoulder, shoulder + new Vector2(0, 19), 15f);
            Draw(2, shoulder + new Vector2(-18, -3), new Vector2(-18 - swing * 24f, 0));
            Draw(3, shoulder + new Vector2(18, -3), new Vector2(18 + swing * 24f, 0));
            Draw(4, shoulder + new Vector2(-18, -3), shoulder + new Vector2(18, -3), 4f);
            Draw(5, hip, new Vector2(-15 + swing * 19f, -38));
            Draw(6, new Vector2(-15 + swing * 19f, -38), new Vector2(-17 + swing * 30f, -64));
            Draw(7, hip, new Vector2(15 - swing * 19f, -38));
            Draw(8, new Vector2(15 - swing * 19f, -38), new Vector2(17 - swing * 30f, -64));
            Draw(9, new Vector2(-100, -67), new Vector2(100, -67), 3f);
            Draw(10, new Vector2(-100, -67), new Vector2(-100, -67), 0f);
            Draw(11, new Vector2(100, -67), new Vector2(100, -67), 0f);
        }

        private void Draw(int index, Vector2 from, Vector2 to, float thickness = 6f)
        {
            var bar = strokes[index];
            var delta = to - from;
            bar.anchoredPosition = (from + to) * .5f;
            bar.sizeDelta = new Vector2(delta.magnitude, thickness);
            bar.localRotation = Quaternion.Euler(0, 0, Mathf.Atan2(delta.y, delta.x) * Mathf.Rad2Deg);
        }
    }
}
