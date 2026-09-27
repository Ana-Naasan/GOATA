#nullable enable
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;

namespace Physio.Replay
{
    public sealed class GoataScoreEvidence
    {
        public Guid TakeId { get; }
        public long FrameId { get; }
        public double SourceTime { get; }
        public double Degrees { get; }
        internal GoataScoreEvidence(Guid take, ReplaySample sample, double degrees)
        { TakeId = take; FrameId = (long)sample.SourceFrameId; SourceTime = sample.SourceTime; Degrees = degrees; }
    }

    public sealed class GoataScoreCategory
    {
        public string Label { get; }
        public double Weight { get; }
        public double? Severity { get; }
        public double? Degrees { get; }
        public double FullSeverityDegrees { get; }
        public double? Deduction => Severity * Weight;
        public IReadOnlyList<GoataScoreEvidence> Evidence { get; }
        public GoataScoreCategory(string label, double weight, double? severity, double? degrees = null,
            double fullSeverityDegrees = 30, IEnumerable<GoataScoreEvidence>? evidence = null)
        {
            if (string.IsNullOrWhiteSpace(label)) throw new ArgumentException("Category label required.");
            if (!GoataScore.Finite(weight) || weight < 0) throw new ArgumentOutOfRangeException(nameof(weight));
            if (severity.HasValue && (!GoataScore.Finite(severity.Value) || severity < 0 || severity > 1))
                throw new ArgumentOutOfRangeException(nameof(severity));
            if (!GoataScore.Finite(fullSeverityDegrees) || fullSeverityDegrees <= 0) throw new ArgumentOutOfRangeException(nameof(fullSeverityDegrees));
            if (degrees.HasValue && (!GoataScore.Finite(degrees.Value) || degrees < 0)) throw new ArgumentOutOfRangeException(nameof(degrees));
            Label = label; Weight = weight; Severity = severity; Degrees = degrees; FullSeverityDegrees = fullSeverityDegrees;
            Evidence = Array.AsReadOnly((evidence ?? Array.Empty<GoataScoreEvidence>()).ToArray());
        }
    }

    public sealed class GoataScoreSettings
    {
        public double FirstWeight { get; }
        public double SecondWeight { get; }
        public double KneeDifferenceScale { get; }
        public double TorsoScale { get; }
        public GoataScoreSettings(double firstWeight = 50, double secondWeight = 50, double kneeDifferenceScale = 20, double torsoScale = 30)
        {
            if (!GoataScore.Finite(firstWeight) || !GoataScore.Finite(secondWeight) || firstWeight < 0 || secondWeight < 0 || Math.Abs(firstWeight + secondWeight - 100) > 1e-8)
                throw new ArgumentException("Demo weights must be finite, nonnegative and total 100.");
            if (!GoataScore.Finite(kneeDifferenceScale) || !GoataScore.Finite(torsoScale) || kneeDifferenceScale <= 0 || torsoScale <= 0)
                throw new ArgumentException("Demo angle scales must be positive and finite.");
            FirstWeight = firstWeight; SecondWeight = secondWeight; KneeDifferenceScale = kneeDifferenceScale; TorsoScale = torsoScale;
        }
    }

    public sealed class GoataScoreResult
    {
        public double? Score { get; }
        public int? DisplayScore => Score.HasValue ? GoataScore.RoundScore(Score.Value) : (int?)null;
        public string Band => !DisplayScore.HasValue ? "unavailable" : DisplayScore <= 50 ? "red" : DisplayScore <= 90 ? "yellow" : "green";
        public IReadOnlyList<GoataScoreCategory> Categories { get; }
        public string Summary => Score.HasValue
            ? string.Join(" · ", Categories.Select(c => c.Label + " −" + c.Deduction!.Value.ToString("0.0", CultureInfo.InvariantCulture))) + "\nDemo rules · pose estimates"
            : "No supported movement categories.\nDemo rules · pose estimates";
        public string Details => "GoataScore demo rules v1: 100 minus weighted severity; no clinical validation.\n" +
            string.Join("\n", Categories.Select(c => c.Label + ": weight " + c.Weight.ToString("0.0", CultureInfo.InvariantCulture) +
                ", full severity at " + c.FullSeverityDegrees.ToString("0.0", CultureInfo.InvariantCulture) + "°; " +
                (c.Severity.HasValue ? "severity " + c.Severity.Value.ToString("0.000", CultureInfo.InvariantCulture) + ", deduction " + c.Deduction!.Value.ToString("0.0", CultureInfo.InvariantCulture) : "unavailable") +
                string.Join("", c.Evidence.Select(e => "; source " + e.SourceTime.ToString("0.#########", CultureInfo.InvariantCulture) + " s, frame " + e.FrameId)))) +
            "\nSeverity increases linearly from zero at 0° to one at the stated demo scale. Available categories are reweighted to total 100; only contributing categories are listed. Display uses nearest integer, halves away from zero. Red 0–50; yellow 51–90; green 91–100.";
        internal GoataScoreResult(double? score, GoataScoreCategory[] categories)
        { Score = score; Categories = Array.AsReadOnly((GoataScoreCategory[])categories.Clone()); }
    }

    /// <summary>App-defined demo deductions from original pose samples, never clinical infractions.</summary>
    public static class GoataScore
    {
        public const string MethodVersion = "goata-demo-v1";
        private static readonly string[] Torso = { "left_hip", "right_hip", "left_shoulder", "right_shoulder" };
        private static readonly string[] Legs = { "left_hip", "left_knee", "left_ankle", "right_hip", "right_knee", "right_ankle" };
        internal static bool Finite(double x) => !double.IsNaN(x) && !double.IsInfinity(x);
        public static int RoundScore(double score)
        {
            if (!Finite(score) || score < 0 || score > 100) throw new ArgumentOutOfRangeException(nameof(score));
            return (int)Math.Round(score, MidpointRounding.AwayFromZero);
        }
        public static GoataScoreResult Calculate(IEnumerable<GoataScoreCategory> categories)
        {
            if (categories == null) throw new ArgumentNullException(nameof(categories));
            var rows = categories.ToArray();
            if (rows.Length == 0 || rows.Any(c => c == null) || Math.Abs(rows.Sum(c => c.Weight) - 100) > 1e-8)
                throw new ArgumentException("Category weights must total 100.");
            var available = rows.Where(c => c.Severity.HasValue && c.Weight > 0).ToArray();
            if (available.Length == 0) return new GoataScoreResult(null, Array.Empty<GoataScoreCategory>());
            var weight = available.Sum(c => c.Weight);
            var normalized = available.Select(c => new GoataScoreCategory(c.Label, c.Weight / weight * 100,
                c.Severity, c.Degrees, c.FullSeverityDegrees, c.Evidence)).ToArray();
            var score = Math.Max(0, Math.Min(100, 100 - normalized.Sum(c => c.Deduction!.Value)));
            return new GoataScoreResult(score, normalized);
        }
        public static GoataScoreResult Evaluate(ReplayData replay, string testType, string condition, GoataScoreSettings? settings = null)
        {
            if (replay == null) throw new ArgumentNullException(nameof(replay));
            var config = settings ?? new GoataScoreSettings();
            var allowed = condition == "exercise" || condition == "seated" && testType != "walking";
            var validTest = testType == "walking" || testType == "elk" || testType == "rtk";
            if (!allowed || !validTest) return Calculate(new[] { Missing("Movement category 1", config.FirstWeight, config.TorsoScale), Missing("Movement category 2", config.SecondWeight, config.TorsoScale) });
            if (testType == "walking")
            {
                // Both peaks use exactly the same frames with both legs valid and nondegenerate.
                var paired = Samples(replay, Legs, "knees");
                GoataScoreCategory knee;
                if (paired.Length < 2) knee = Missing("Knee peak difference", config.FirstWeight, config.KneeDifferenceScale);
                else
                {
                    var left = paired.Aggregate((a, b) => b.Value > a.Value ? b : a);
                    var right = paired.Aggregate((a, b) => b.Second > a.Second ? b : a);
                    var difference = Math.Abs(left.Value - right.Second);
                    knee = Category("Knee peak difference", config.FirstWeight, difference, config.KneeDifferenceScale,
                        new GoataScoreEvidence(replay.Timeline.SourceTakeId, left.Source, left.Value), new GoataScoreEvidence(replay.Timeline.SourceTakeId, right.Source, right.Second));
                }
                return Calculate(new[] { knee, PeakCategory(replay, "Upper-body tilt", "inclination", config.SecondWeight, config.TorsoScale) });
            }
            return Calculate(new[] {
                PeakCategory(replay, testType == "elk" ? "Shoulder–hip twist" : "Sideways tilt", testType == "elk" ? "rotation" : "lateral", config.FirstWeight, config.TorsoScale),
                PeakCategory(replay, "Fore/aft tilt", "foreaft", config.SecondWeight, config.TorsoScale) });
        }
        private static GoataScoreCategory Missing(string name, double weight, double scale) => new GoataScoreCategory(name, weight, null, null, scale);
        private static GoataScoreCategory Category(string name, double weight, double value, double scale, params GoataScoreEvidence[] evidence) =>
            new GoataScoreCategory(name, weight, Math.Min(1, value / scale), value, scale, evidence);
        private static GoataScoreCategory PeakCategory(ReplayData replay, string name, string operation, double weight, double scale)
        {
            var samples = Samples(replay, Torso, operation);
            if (samples.Length < 2) return Missing(name, weight, scale);
            var peak = samples.Aggregate((a, b) => Math.Abs(b.Value) > Math.Abs(a.Value) ? b : a);
            return Category(name, weight, Math.Abs(peak.Value), scale, new GoataScoreEvidence(replay.Timeline.SourceTakeId, peak.Source, peak.Value));
        }
        private static Sample[] Samples(ReplayData replay, string[] names, string operation)
        {
            var all = Enumerable.Range(0, replay.JointCount).Select(replay.JointNameAt).ToArray();
            var indices = names.Select(n => Array.IndexOf(all, n)).ToArray();
            if (indices.Any(i => i < 0)) return Array.Empty<Sample>();
            var result = new List<Sample>();
            var clock = new ReplayClock(replay.Timeline);
            for (var i = 0; i < replay.FrameCount; i++, clock = clock.Step(1))
            {
                var sample = clock.Sample;
                if (!sample.IsObserved || sample.SourceFrameId > long.MaxValue || indices.Any(j => !replay.IsJointValid(sample.Index, j))) continue;
                var p = indices.Select(j => new V(replay.JointAt(sample.Index, j))).ToArray();
                if (p.Any(v => !v.Valid)) continue;
                var value = Measure(p, operation);
                if (value.HasValue && Finite(value.Value.Item1) && Finite(value.Value.Item2)) result.Add(new Sample(sample, value.Value.Item1, value.Value.Item2));
            }
            return result.ToArray();
        }
        private static (double, double)? Measure(V[] p, string operation)
        {
            if (operation == "knees")
            {
                var a = Knee(p[0], p[1], p[2]); var b = Knee(p[3], p[4], p[5]);
                return a.HasValue && b.HasValue ? (a.Value, b.Value) : ((double, double)?)null;
            }
            var t = Unit((p[2] + p[3] - p[0] - p[1]) / 2);
            if (!t.HasValue) return null;
            if (operation == "inclination") return (Degrees(Math.Atan2(Math.Sqrt(t.Value.X * t.Value.X + t.Value.Z * t.Value.Z), t.Value.Y)), 0);
            var hip = Horizontal(p[0] - p[1]);
            if (!hip.HasValue) return null;
            if (operation == "rotation")
            {
                var shoulder = Horizontal(p[2] - p[3]);
                return shoulder.HasValue ? (Degrees(Math.Atan2(Math.Abs(hip.Value.X * shoulder.Value.Z - hip.Value.Z * shoulder.Value.X), Dot(hip.Value, shoulder.Value))), 0) : ((double, double)?)null;
            }
            var axis = operation == "lateral" ? hip.Value : new V(-hip.Value.Z, 0, hip.Value.X);
            var projection = Dot(t.Value, axis);
            return Math.Sqrt(projection * projection + t.Value.Y * t.Value.Y) < 1e-6 ? ((double, double)?)null : (Degrees(Math.Atan2(projection, t.Value.Y)), 0);
        }
        private static double? Knee(V hip, V knee, V ankle)
        {
            var a = Unit(hip - knee); var b = Unit(ankle - knee);
            return a.HasValue && b.HasValue ? Math.Max(0, 180 - Degrees(Math.Atan2(Cross(a.Value, b.Value).Length, Dot(a.Value, b.Value)))) : (double?)null;
        }
        private static V? Horizontal(V v)
        { var n = Unit(v); if (!n.HasValue) return null; var h = new V(n.Value.X, 0, n.Value.Z); return h.Length < 1e-6 ? (V?)null : Unit(h); }
        private static V? Unit(V v) => v.Valid && v.Length > 0 ? v / v.Length : (V?)null;
        private static double Dot(V a, V b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
        private static V Cross(V a, V b) => new V(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);
        private static double Degrees(double radians) => radians * 180 / Math.PI;
        private readonly struct Sample
        { public readonly ReplaySample Source; public readonly double Value, Second; public Sample(ReplaySample source, double value, double second) { Source = source; Value = value; Second = second; } }
        private readonly struct V
        {
            public readonly double X, Y, Z;
            public V(double x, double y, double z) { X = x; Y = y; Z = z; }
            public V(Vector3 v) : this(v.X, v.Y, v.Z) { }
            public bool Valid => Finite(X) && Finite(Y) && Finite(Z);
            public double Length => Math.Sqrt(X * X + Y * Y + Z * Z);
            public static V operator +(V a, V b) => new V(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
            public static V operator -(V a, V b) => new V(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
            public static V operator /(V v, double x) => new V(v.X / x, v.Y / x, v.Z / x);
        }
    }
}
