#nullable enable
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using Newtonsoft.Json.Linq;

namespace Physio.Replay
{
    /// <summary>Descriptive patterns from validated original model joints; never a clinical assessment.</summary>
    public static class MotionPatternClassifier
    {
        public const string MethodId = "local-motion-patterns-v1";
        private const string Quality = "Joint visibility and anatomical accuracy are unvalidated; finite fitted joints are not visibility scores.";
        private static readonly string[] Torso = { "left_hip", "right_hip", "left_shoulder", "right_shoulder" };

        public static JObject Method() => new JObject
        {
            ["method_id"] = MethodId, ["method_version"] = "1.0.0",
            ["name"] = "Local motion patterns", ["version"] = "1.0.0",
            ["validation_status"] = "research_demo_unvalidated",
            ["description"] = "Local descriptive motion patterns from original fitted joints. No clinical classification or evaluated exercise assessment.",
            ["input"] = "Original exported model joints; no display transform, smoothing or magnification.",
            ["peak_policy"] = "Greatest absolute eligible sample; ties keep the first source frame. At least two observed source frames required.",
            ["quality"] = Quality
        };

        public static JObject[] Classify(ReplayData replay, string testType, string condition)
        {
            if (replay == null) throw new ArgumentNullException(nameof(replay));
            if ((condition != "exercise" && condition != "seated") ||
                (testType == "walking" && condition != "exercise")) return Array.Empty<JObject>();
            if (testType == "elk" || testType == "rtk")
            {
                var operation = testType == "elk" ? "lateral" : "rotation";
                var samples = Samples(replay, Torso, operation);
                return samples.Length < 2 ? Array.Empty<JObject>() : new[] {
                    Card(replay, samples, testType == "elk" ? "elk.lateral_torso_lean" : "rtk.shoulder_pelvis_rotation",
                        "not_applicable", Torso, condition, Label(operation, Peak(samples).Value), Definition(operation)) };
            }
            if (testType != "walking") return Array.Empty<JObject>();
            var leftNames = KneeNames("left");
            var rightNames = KneeNames("right");
            var left = Samples(replay, leftNames, "knee");
            var right = Samples(replay, rightNames, "knee");
            var rightFrames = new HashSet<int>(right.Select(s => s.Source.Index));
            var commonLeft = left.Where(s => rightFrames.Contains(s.Source.Index)).ToArray();
            var sharedFrames = new HashSet<int>(commonLeft.Select(s => s.Source.Index));
            var commonRight = right.Where(s => sharedFrames.Contains(s.Source.Index)).ToArray();
            var comparable = commonLeft.Length >= 2;
            var cards = new List<JObject>();
            AddKnee(cards, replay, comparable ? commonLeft : left, comparable ? commonRight : null, "left", leftNames, condition);
            AddKnee(cards, replay, comparable ? commonRight : right, comparable ? commonLeft : null, "right", rightNames, condition);
            var trunk = Samples(replay, Torso, "inclination");
            if (trunk.Length >= 2) cards.Add(Card(replay, trunk, "walking.trunk_lean", "not_applicable", Torso,
                condition, Label("inclination", Peak(trunk).Value), Definition("inclination")));
            return cards.ToArray();
        }

        private static void AddKnee(List<JObject> cards, ReplayData replay, Measurement[] samples,
            Measurement[]? otherSamples, string side, string[] names, string condition)
        {
            if (samples.Length < 2) return;
            var label = "Estimated " + side + " knee bending";
            var explanation = Definition("knee");
            if (otherSamples == null)
                explanation += " Bilateral comparison unavailable: fewer than two source frames have valid, nondegenerate joints for both legs.";
            else
            {
                var own = Peak(samples);
                var other = Peak(otherSamples);
                var otherSide = side == "left" ? "right" : "left";
                var difference = DisplayValue(own.Value) - DisplayValue(other.Value);
                label = (side == "left" ? "Left" : "Right") + " knee: " +
                    (difference == 0 ? "equal displayed peaks" : difference > 0 ? "higher bending peak" : "lower bending peak");
                explanation += " Both peaks use only the same eligible source frames. The " + side + " peak is " +
                    Display(own.Value) + " degrees at source " + SourceTime(own) + " s; the " + otherSide + " peak is " +
                    Display(other.Value) + " degrees at source " + SourceTime(other) +
                    " s. Peaks may occur at different moments; this does not establish gait asymmetry or limp.";
            }
            cards.Add(Card(replay, samples, "walking.knee_flexion", side, names, condition, label, explanation));
        }

        private static string Label(string operation, double value)
        {
            var displayed = DisplayValue(value);
            if (operation == "rotation") return displayed == 0 ? "Offset rounds to 0.0°" : "Relative torso rotation observed";
            if (operation == "inclination") return displayed == 0 ? "Inclination rounds to 0.0°" : "Torso inclination observed";
            return displayed == 0 ? "Lateral offset rounds to 0.0°" : "Peak " + (displayed > 0 ? "left" : "right") + " torso lean";
        }

        private static string Definition(string operation)
        {
            switch (operation)
            {
                case "lateral": return "Signed torso lean at greatest absolute lateral lean, positive toward anatomical left. The hip-to-shoulder midpoint direction is projected onto estimated upright and the horizontal hip axis. This describes fitted torso orientation, not lumbar or vertebral motion.";
                case "rotation": return "Largest absolute shortest angle (0 to 180 degrees) between horizontal shoulder and hip axes. This is fitted relative orientation at one frame, not accumulated rotation, anatomical rotation direction or lumbar motion.";
                case "inclination": return "Largest unsigned angle between the hip-to-shoulder midpoint direction and estimated upright. This does not establish walking direction or lumbar motion.";
                default: return "Largest geometric 3D hip-knee-ankle bending angle: 180 degrees minus the included angle, with a straight leg at zero. This is a model-joint estimate, not a clinical anatomical knee measurement.";
            }
        }

        private static Measurement[] Samples(ReplayData replay, string[] required, string operation)
        {
            var names = Enumerable.Range(0, replay.JointCount).Select(replay.JointNameAt).ToArray();
            var indices = required.Select(name => Array.IndexOf(names, name)).ToArray();
            if (indices.Any(index => index < 0)) return Array.Empty<Measurement>();
            var samples = new List<Measurement>();
            var clock = new ReplayClock(replay.Timeline);
            for (var i = 0; i < replay.FrameCount; i++, clock = clock.Step(1))
            {
                var source = clock.Sample;
                // The existing evidence UI accepts Int64 IDs. Never truncate a larger original ID.
                if (!source.IsObserved || source.SourceFrameId > long.MaxValue ||
                    indices.Any(index => !replay.IsJointValid(source.Index, index))) continue;
                var points = indices.Select(index => new V(replay.JointAt(source.Index, index))).ToArray();
                if (points.Any(point => !point.Finite)) continue;
                var value = Measure(operation, points);
                if (value.HasValue && !double.IsNaN(value.Value) && !double.IsInfinity(value.Value))
                    samples.Add(new Measurement(source, value.Value));
            }
            return samples.ToArray();
        }

        private static double? Measure(string operation, V[] p)
        {
            if (operation == "knee")
            {
                var a = Unit(p[0] - p[1]); var b = Unit(p[2] - p[1]);
                return a.HasValue && b.HasValue ? 180 - Degrees(Math.Atan2(Cross(a.Value, b.Value).Length, Dot(a.Value, b.Value))) : (double?)null;
            }
            var torso = Unit((p[2] + p[3]) / 2 - (p[0] + p[1]) / 2);
            if (!torso.HasValue) return null;
            var t = torso.Value;
            if (operation == "inclination") return Degrees(Math.Atan2(Math.Sqrt(t.X * t.X + t.Z * t.Z), t.Y));
            var hip = Horizontal(p[0] - p[1]);
            if (!hip.HasValue) return null;
            if (operation == "lateral")
            {
                var lateral = Dot(t, hip.Value);
                return Math.Sqrt(lateral * lateral + t.Y * t.Y) >= 1e-6 ? Degrees(Math.Atan2(lateral, t.Y)) : (double?)null;
            }
            var shoulder = Horizontal(p[2] - p[3]);
            return shoulder.HasValue ? Degrees(Math.Atan2(Math.Abs(hip.Value.X * shoulder.Value.Z - hip.Value.Z * shoulder.Value.X),
                Dot(hip.Value, shoulder.Value))) : (double?)null;
        }

        private static JObject Card(ReplayData replay, Measurement[] samples, string quantity, string side,
            string[] names, string condition, string label, string explanation)
        {
            var peak = Peak(samples);
            var min = samples.Min(sample => sample.Value);
            var max = samples.Max(sample => sample.Value);
            var limitations = new JArray(Quality,
                "Gravity, camera motion and body fitting are model estimates; no clinical reference comparison was performed.",
                "Only eligible reconstructed source frames are described. Missing frames are excluded and never interpolated.",
                "Labels compare estimates at displayed precision (0.1 degree); they do not classify exercise correctness or normal movement.");
            if (replay.Synthetic) limitations.Add("Synthetic mechanics fixture; this is not a participant measurement.");
            return new JObject
            {
                ["observation_id"] = Guid.NewGuid().ToString(), ["method_id"] = MethodId, ["quantity_code"] = quantity,
                ["label"] = (replay.Synthetic ? "Synthetic fixture: " : "") + label,
                ["explanation"] = explanation + " Based on " + samples.Length.ToString(CultureInfo.InvariantCulture) + " eligible observed source frames.",
                ["region"] = quantity == "walking.knee_flexion" ? "knee" : "torso", ["side"] = side,
                ["evidence"] = new JObject { ["take_id"] = replay.Timeline.SourceTakeId.ToString(),
                    ["start_s"] = peak.Source.SourceTime, ["end_s"] = peak.Source.SourceTime,
                    ["first_frame_id"] = (long)peak.Source.SourceFrameId, ["last_frame_id"] = (long)peak.Source.SourceFrameId,
                    ["condition"] = condition, ["quality"] = "limited", ["quality_reason"] = Quality },
                ["limitations"] = limitations, ["highlight_joint_names"] = new JArray(names),
                ["metrics"] = new JArray(Metric("peak angle", peak.Value), Metric("minimum angle", min),
                    Metric("maximum angle", max), Metric("angle range", max - min))
            };
        }

        private static JObject Metric(string name, double value) => new JObject
        { ["name"] = name, ["value"] = value, ["unit"] = "deg", ["basis"] = "pose_estimate", ["scale_status"] = "not_required" };
        private static Measurement Peak(Measurement[] samples) => samples.Aggregate((best, next) => Math.Abs(next.Value) > Math.Abs(best.Value) ? next : best);
        private static string[] KneeNames(string side) => new[] { side + "_hip", side + "_knee", side + "_ankle" };
        private static string Display(double value) => value.ToString("0.0", CultureInfo.InvariantCulture);
        private static double DisplayValue(double value) => double.Parse(Display(value), CultureInfo.InvariantCulture);
        private static string SourceTime(Measurement sample) => sample.Source.SourceTime.ToString("0.#########", CultureInfo.InvariantCulture);
        private static double Degrees(double radians) => radians * 180 / Math.PI;
        private static double Dot(V a, V b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
        private static V Cross(V a, V b) => new V(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);
        private static V? Unit(V value) => value.Length > 0 && value.Finite ? value / value.Length : (V?)null;
        private static V? Horizontal(V value)
        {
            var unit = Unit(value);
            if (!unit.HasValue) return null;
            var flat = new V(unit.Value.X, 0, unit.Value.Z);
            return flat.Length < 1e-6 ? null : Unit(flat);
        }

        private readonly struct Measurement
        {
            public readonly ReplaySample Source;
            public readonly double Value;
            public Measurement(ReplaySample source, double value) { Source = source; Value = value; }
        }

        // Double arithmetic avoids float squared-length overflow and preserves uniformly scaled angles.
        private readonly struct V
        {
            public readonly double X, Y, Z;
            public V(double x, double y, double z) { X = x; Y = y; Z = z; }
            public V(Vector3 v) : this(v.X, v.Y, v.Z) { }
            public bool Finite => !double.IsNaN(X + Y + Z) && !double.IsInfinity(X + Y + Z);
            public double Length => Math.Sqrt(X * X + Y * Y + Z * Z);
            public static V operator +(V a, V b) => new V(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
            public static V operator -(V a, V b) => new V(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
            public static V operator /(V v, double n) => new V(v.X / n, v.Y / n, v.Z / n);
        }
    }
}
