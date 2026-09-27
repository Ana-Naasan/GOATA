using System;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using Physio.Replay;

// Synthetic poses prove numerical and evidence behavior, not anatomical accuracy.
internal static class PatternChecks
{
    private static int checks;
    private static readonly Guid Take = Guid.Parse("8f4e59a5-30d1-43d4-ae31-c8a036680f34");
    private static readonly string[] Names = { "left_hip", "right_hip", "left_shoulder", "right_shoulder",
        "left_knee", "left_ankle", "right_knee", "right_ankle" };

    private static void Check(bool value, string reason)
    { if (!value) throw new Exception(reason); checks++; }
    private static void Near(double value, double expected, string reason) =>
        Check(Math.Abs(value - expected) < .0001, reason + $": {value} != {expected}");
    private static JObject One(ReplayData replay, string type = "elk") =>
        MotionPatternClassifier.Classify(replay, type, "exercise").Single();
    private static double Peak(JObject item) => (double)item["metrics"]![0]!["value"]!;
    private static string Label(JObject item) => (string)item["label"]!;
    private static double Time(JObject item) => (double)item["evidence"]!["start_s"]!;
    private static JArray Stable(JObject[] items) => new JArray(items.Select(item =>
        new JObject(item.Properties().Where(p => p.Name != "observation_id").Select(p => new JProperty(p.Name, p.Value.DeepClone())))));

    private static Vector3[] Pose(double lean = 0, double rotation = 0, double leftKnee = 0, double rightKnee = 0)
    {
        var l = lean * Math.PI / 180;
        var r = rotation * Math.PI / 180;
        var torso = new Vector3((float)Math.Sin(l), (float)Math.Cos(l), 0);
        var shoulder = new Vector3((float)(.5 * Math.Cos(r)), 0, (float)(.5 * Math.Sin(r)));
        Vector3 Ankle(float x, double angle) => new Vector3(x, -(float)Math.Cos(angle * Math.PI / 180), (float)Math.Sin(angle * Math.PI / 180));
        return new[] { new Vector3(.5f, 1, 0), new Vector3(-.5f, 1, 0),
            Vector3.UnitY + torso + shoulder, Vector3.UnitY + torso - shoulder,
            new Vector3(.5f, 0, 0), Ankle(.5f, leftKnee), new Vector3(-.5f, 0, 0), Ankle(-.5f, rightKnee) };
    }

    private static ReplayData Data(Vector3[][] rows, bool[]? valid = null, bool[]? joints = null,
        string[]? names = null, ReplayGap[]? gaps = null, bool synthetic = false, BigInteger? firstId = null)
    {
        var flags = valid ?? Enumerable.Repeat(true, rows.Length).ToArray();
        var timeline = new ReplayTimeline(Take, Enumerable.Range(0, rows.Length).Select(i => 5.5 + i * .37).ToArray(),
            Enumerable.Range(0, rows.Length).Select(i => (firstId ?? BigInteger.Pow(10, 12)) + 13 * i).ToArray(), flags,
            gaps ?? Array.Empty<ReplayGap>());
        return new ReplayData(Guid.Empty, timeline, 0, synthetic, "model_estimate", "test fixture",
            Array.Empty<Vector3>(), rows.SelectMany(r => r).ToArray(), Array.Empty<int>(),
            Enumerable.Repeat(-1, 8).ToArray(), names ?? Names, flags,
            joints ?? Enumerable.Repeat(true, rows.Length * 8).ToArray());
    }

    public static void Main()
    {
        var baseline = Data(new[] { Pose(), Pose(30), Pose(-20) });
        var left = One(baseline);
        Near(Peak(left), 30, "ELK signed lean from anatomical hip axis");
        Check(Label(left).Contains("left", StringComparison.OrdinalIgnoreCase), "ELK names peak left lean");
        var right = One(Data(new[] { Pose(10), Pose(-40) }));
        Near(Peak(right), -40, "ELK negative peak retained");
        Check(((string)right["explanation"]!).StartsWith("Your upper body leaned to both the left and the right."), "ELK plain conclusion follows observed sides");
        var sameSide = One(Data(new[] { Pose(10), Pose(20) }));
        Check(((string)sameSide["explanation"]!).StartsWith("Your upper body leaned toward your left in the sampled frames."), "same-side lean does not imply crossing zero");
        Check(Label(right).Contains("right", StringComparison.OrdinalIgnoreCase), "ELK names peak right lean");
        Check(Label(One(Data(new[] { Pose(.04), Pose(-.02) }))).Contains("rounds to 0.0°"), "ELK rounded zero explicit");
        var rotated = One(Data(new[] { Pose(rotation: 0), Pose(rotation: -70) }), "rtk");
        Near(Peak(rotated), 70, "RTK unsigned shortest rotation");
        Check(((string)rotated["explanation"]!).StartsWith("Your shoulders were turned relative to your hips."), "RTK plain conclusion avoids anatomical direction");
        Check(Label(rotated) == "Relative torso rotation observed", "RTK has no anatomical direction");
        Near(Peak(One(Data(new[] { Pose(), Pose(rotation: 270) }), "rtk")), 90, "RTK wraps shortest angle");
        Near(Peak(One(Data(new[] { Pose(), Pose(rotation: 180) }), "rtk")), 180, "RTK upper boundary");
        Check(Label(One(Data(new[] { Pose(), Pose(rotation: .04) }), "rtk")) ==
            "Offset rounds to 0.0°", "RTK rounded zero explicit");

        var walking = MotionPatternClassifier.Classify(Data(new[] { Pose(leftKnee: 60, rightKnee: 5),
            Pose(lean: 25, leftKnee: 10, rightKnee: 40), Pose(leftKnee: 25, rightKnee: 20) }), "walking", "exercise");
        Check(walking.Length == 3, "walking retains knee and trunk quantities");
        Near(Peak(walking[0]), 60, "left knee 180 minus included angle");
        Near(Peak(walking[1]), 40, "right knee estimate");
        Near(Peak(walking[2]), 25, "torso inclination uses estimated upright");
        Check(((string)walking[0]["explanation"]!).StartsWith("Your left knee reached a deeper bend than your right.\nLeft knee peaked at 60.0° at 5.5 s; right at 40.0° at 5.87 s."), "walking plain conclusion retains separate peak moments below");
        Check(((string)walking[2]["explanation"]!).StartsWith("Your upper body tilted away from upright in the sampled frames."), "walking plain torso conclusion avoids unsupported direction");
        Near(Time(walking[0]), 5.5, "left keeps own peak moment");
        Near(Time(walking[1]), 5.87, "right keeps own peak moment");
        Check(Label(walking[0]).Contains("left", StringComparison.OrdinalIgnoreCase), "higher peak left label");
        Check(Label(walking[0]) == "Left knee: higher bending peak" && Label(walking[1]) == "Right knee: lower bending peak", "each knee label describes its own side");
        Check(((string)walking[0]["explanation"]!).Contains("40.0") &&
            ((string)walking[0]["explanation"]!).Contains("5.87"), "comparison explains other actual peak value and time");
        var equal = MotionPatternClassifier.Classify(Data(new[] { Pose(leftKnee: 30.01, rightKnee: 30.04), Pose() }), "walking", "exercise");
        Check(Label(equal[0]).Contains("equal", StringComparison.OrdinalIgnoreCase), "rounded peaks treated equally");
        var largerRight = MotionPatternClassifier.Classify(Data(new[] { Pose(leftKnee: 10, rightKnee: 70), Pose() }), "walking", "exercise");
        Check(Label(largerRight[1]).Contains("right", StringComparison.OrdinalIgnoreCase), "higher peak right label");
        var zero = MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose() }), "walking", "exercise");
        Check(Label(zero[2]).Contains("rounds to 0.0°"), "zero torso inclination explicit");

        var jointValidity = Enumerable.Repeat(true, 24).ToArray();
        jointValidity[6] = false;
        var common = MotionPatternClassifier.Classify(Data(new[] { Pose(leftKnee: 90),
            Pose(leftKnee: 10, rightKnee: 20), Pose(leftKnee: 5, rightKnee: 30) }, joints: jointValidity), "walking", "exercise");
        Near(Peak(common[0]), 10, "comparison left peak restricted to common frames");
        Near(Peak(common[1]), 30, "comparison right peak restricted to common frames");
        Near(Time(common[0]), 5.87, "common eligible peak binds original frame");
        var missing = Names.Select(n => n == "right_ankle" ? "unknown_😀" : n).ToArray();
        var unilateral = MotionPatternClassifier.Classify(Data(new[] { Pose(leftKnee: 10), Pose(leftKnee: 20) }, names: missing), "walking", "exercise");
        Check(unilateral.Length == 2 && (string?)unilateral[0]["side"] == "left", "missing right joint omits right quantity");
        Check(((string)unilateral[0]["explanation"]!).Contains("comparison unavailable", StringComparison.OrdinalIgnoreCase), "missing leg cannot imply comparison");
        var disjointFlags = Enumerable.Repeat(true, 32).ToArray();
        disjointFlags[6] = disjointFlags[14] = disjointFlags[20] = disjointFlags[28] = false;
        var disjoint = MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose(leftKnee: 60), Pose(), Pose(rightKnee: 45) }, joints: disjointFlags), "walking", "exercise");
        Check(disjoint.Take(2).All(o => ((string)o["explanation"]!).Contains("comparison unavailable", StringComparison.OrdinalIgnoreCase)), "disjoint leg samples never compared");

        var rejected = One(Data(new[] { Pose(10), Pose(80), Pose(20) }, valid: new[] { true, false, true },
            gaps: new[] { new ReplayGap(5.8, 5.9) }));
        Near(Peak(rejected), 20, "invalid frames and closed gap excluded");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose(10), Pose(80) }, valid: new[] { true, false }), "elk", "exercise").Length == 0,
            "one eligible frame cannot describe motion");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose() }), "elk", "exercise").Length == 0, "singleton absent");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose() }, joints: new bool[16]), "elk", "exercise").Length == 0, "missing validity absent");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose() }, names: missing.Select(n => n == "left_shoulder" ? "" : n).ToArray()), "elk", "exercise").Length == 0, "missing torso joint absent");
        var collapsed = Pose(); collapsed[2] = collapsed[0]; collapsed[3] = collapsed[1];
        Check(MotionPatternClassifier.Classify(Data(new[] { collapsed, collapsed }), "elk", "exercise").Length == 0, "degenerate torso absent");
        var nonfinite = Pose(); nonfinite[2] = new Vector3(float.NaN, 0, 0);
        Check(MotionPatternClassifier.Classify(Data(new[] { nonfinite, nonfinite }), "elk", "exercise").Length == 0, "nonfinite joints absent");
        var infinite = Pose(); infinite[2] = new Vector3(float.PositiveInfinity, 0, 0);
        Check(MotionPatternClassifier.Classify(Data(new[] { infinite, infinite }), "elk", "exercise").Length == 0, "infinite joints absent");
        var verticalHips = Pose(); verticalHips[0] = new Vector3(0, 1, 0); verticalHips[1] = new Vector3(0, 2, 0);
        Check(MotionPatternClassifier.Classify(Data(new[] { verticalHips, verticalHips }), "elk", "exercise").Length == 0, "vertical hip axis excluded");
        var coincidentHips = Pose(); coincidentHips[0] = coincidentHips[1];
        Check(MotionPatternClassifier.Classify(Data(new[] { coincidentHips, coincidentHips }), "rtk", "exercise").Length == 0, "coincident hip axis excluded");
        var verticalShoulders = Pose(); verticalShoulders[2] = new Vector3(0, 2, 0); verticalShoulders[3] = new Vector3(0, 3, 0);
        Check(MotionPatternClassifier.Classify(Data(new[] { verticalShoulders, verticalShoulders }), "rtk", "exercise").Length == 0, "vertical shoulder axis excluded");
        var unprojectable = Pose(); unprojectable[2] = new Vector3(.5f, 1, 1); unprojectable[3] = new Vector3(-.5f, 1, 1);
        Check(MotionPatternClassifier.Classify(Data(new[] { unprojectable, unprojectable }), "elk", "exercise").Length == 0, "vanishing lateral projection excluded");
        var collapsedLeg = Pose(); collapsedLeg[4] = collapsedLeg[0];
        Check(MotionPatternClassifier.Classify(Data(new[] { collapsedLeg, collapsedLeg }), "walking", "exercise").Length == 2, "zero thigh omitted independently");
        var collapsedShin = Pose(); collapsedShin[5] = collapsedShin[4];
        Check(MotionPatternClassifier.Classify(Data(new[] { collapsedShin, collapsedShin }), "walking", "exercise").Length == 2, "zero shin omitted independently");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose() }), null!, "exercise").Length == 0, "null test unsupported");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose() }), "elk", null!).Length == 0, "null condition unsupported");
        foreach (var condition in new[] { "", "standing", "seated", "exercise" })
            Check(MotionPatternClassifier.Classify(baseline, "walking", condition).Length == (condition == "exercise" ? 3 : 0), "walking condition gated");
        foreach (var type in new[] { "", "barefoot", "elk\u200b" })
            Check(MotionPatternClassifier.Classify(baseline, type, "exercise").Length == 0, "unsupported test absent");
        Check(MotionPatternClassifier.Classify(baseline, "elk", "seated").Length == 1, "seated ELK supported");
        try { MotionPatternClassifier.Classify(null!, "elk", "exercise"); throw new Exception("null replay accepted"); }
        catch (ArgumentNullException) { checks++; }

        Check((string?)left["evidence"]!["take_id"] == Take.ToString(), "source take bound");
        Near(Time(left), 5.87, "source time keeps original origin");
        Check(BigInteger.Parse(left["evidence"]!["first_frame_id"]!.ToString(), CultureInfo.InvariantCulture) == BigInteger.Pow(10, 12) + 13, "large source frame preserved");
        var idBoundary = One(Data(new[] { Pose(), Pose(30) }, firstId: new BigInteger(long.MaxValue) - 13));
        Check((long)idBoundary["evidence"]!["first_frame_id"]! == long.MaxValue, "Int64 maximum retained exactly");
        Check(MotionPatternClassifier.Classify(Data(new[] { Pose(), Pose() }, firstId: BigInteger.Pow(10, 30)), "elk", "exercise").Length == 0,
            "source IDs outside evidence Int64 range excluded without truncation");
        var ties = One(Data(new[] { Pose(30), Pose(-30) }));
        Near(Time(ties), 5.5, "equal absolute peaks retain first source frame");
        Near((double)ties["metrics"]![1]!["value"]!, -30, "minimum angle retained");
        Near((double)ties["metrics"]![3]!["value"]!, 60, "range uses original signed angles");
        Check(JToken.DeepEquals(left["evidence"]!["first_frame_id"], left["evidence"]!["last_frame_id"]) &&
            JToken.DeepEquals(left["evidence"]!["start_s"], left["evidence"]!["end_s"]), "point evidence precise");
        var before = baseline.JointAt(1, 2);
        var stable = Stable(MotionPatternClassifier.Classify(baseline, "elk", "exercise"));
        left["metrics"]![0]!["value"] = 999;
        Check(JToken.DeepEquals(stable, Stable(MotionPatternClassifier.Classify(baseline, "elk", "exercise"))), "fresh cards repeat exactly without cached mutations");
        Check(baseline.JointAt(1, 2) == before, "source joints unchanged");
        Parallel.For(0, 12, _ => { if (!JToken.DeepEquals(stable, Stable(MotionPatternClassifier.Classify(baseline, "elk", "exercise")))) throw new Exception("concurrent result drift"); });
        checks++;
        foreach (var scale in new[] { .00001f, 7f, 1e20f })
        {
            var scaled = Data(new[] { Pose(), Pose(30), Pose(-20) }.Select(row => row.Select(v => v * scale).ToArray()).ToArray());
            Near(Peak(One(scaled)), 30, "scale invariant source angle");
        }
        var translated = Data(new[] { Pose(), Pose(30) }.Select(row => row.Select(v => Vector3.Transform(v,
            Matrix4x4.CreateRotationY(.73f)) + new Vector3(2, 3, 4)).ToArray()).ToArray());
        Near(Peak(One(translated)), 30, "yaw and translation invariant anatomical lateral angle");
        var synthetic = One(Data(new[] { Pose(), Pose(10) }, synthetic: true));
        Check(Label(synthetic).Contains("Synthetic") && synthetic["limitations"]!.ToString().Contains("not a participant"), "synthetic provenance visible");
        Check((string?)synthetic["evidence"]!["quality"] == "limited" && synthetic["limitations"]!.ToString().Contains("unvalidated"), "unvalidated quality retained");
        Check(((string)synthetic["explanation"]!).Contains("2 eligible observed source frames"), "sample count is explicit");
        Check(synthetic["metrics"]!.Count() <= 4 && synthetic["metrics"]!.All(m => (string?)m["basis"] == "pose_estimate"), "metrics bounded estimates");
        var method = MotionPatternClassifier.Method(); method["method_id"] = "changed";
        Check((string?)MotionPatternClassifier.Method()["method_id"] == MotionPatternClassifier.MethodId, "method metadata fresh");
        Check((string?)MotionPatternClassifier.Method()["name"] == "Local motion patterns" &&
            (string?)MotionPatternClassifier.Method()["version"] == "1.0.0", "method display metadata available");
        Check(MotionPatternClassifier.Classify(Data(Enumerable.Range(0, 10001).Select(i => Pose(i % 25)).ToArray()), "elk", "exercise").Length == 1, "large replay bounded iteration");
        Console.WriteLine($"PASS: {checks} motion pattern checks using synthetic poses; no clinical validation claimed.");
    }
}
