using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using Physio.Replay;
using Physio.Viewer;

// A real fixture exercises contract mechanics only; no model or device claim.
using var json = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "replay_manifest.json")));
var manifest = json.RootElement;
var take = manifest.GetProperty("source_take_id").GetGuid();
var times = manifest.GetProperty("frame_times_s").EnumerateArray().Select(x => x.GetDouble()).ToArray();
var ids = manifest.GetProperty("source_frame_ids").EnumerateArray()
    .Select(x => BigInteger.Parse(x.GetRawText(), CultureInfo.InvariantCulture)).ToArray();
var validity = manifest.GetProperty("frame_valid").EnumerateArray().Select(x => x.GetBoolean()).ToArray();
var gaps = manifest.GetProperty("gaps").EnumerateArray()
    .Select(x => new ReplayGap(x.GetProperty("start_s").GetDouble(), x.GetProperty("end_s").GetDouble())).ToArray();
var timeline = new ReplayTimeline(take, times, ids, validity, gaps);
var initial = new ReplayClock(timeline);
var checks = 0;

void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
    checks++;
}

void Near(double actual, double expected, string message) => Check(Math.Abs(actual - expected) < 1e-12, message);

void Reject(Action action, string message)
{
    try { action(); }
    catch (ArgumentException) { checks++; return; }
    throw new Exception("Expected invalid input rejection: " + message);
}

Check(timeline.FrameCount == 4 && timeline.SourceTakeId == take, "fixture identity/count");
Check(!initial.IsPlaying && initial.Speed == 1 && initial.Direction == 1, "initial clock state");
Check(initial.Sample.SourceFrameId == 100 && initial.Sample.IsObserved, "initial original frame");
Near(initial.CursorTime, 0, "initial actual source time");
var playing = initial.Play();
Check(playing.IsPlaying && !initial.IsPlaying, "immutable play");
var advanced = playing.Advance(.05);
Near(advanced.CursorTime, .05, "real elapsed time advances source time");
Check(advanced.Sample.Index == 1 && advanced.Sample.SourceFrameId == 101, "previous source sample at irregular time");
Near(advanced.Sample.SourceTime, .04, "sample remains an original observation, no interpolation");
Check(advanced.Sample.IsObserved, "observed source sample may be held before gap");
Near(advanced.Pause().Advance(.5).CursorTime, .05, "pause freezes cursor");
Near(playing.CursorTime, 0, "old playing state unchanged");
Check(!advanced.Seek(.04).IsPlaying, "seek pauses");
Near(initial.Seek(-1).CursorTime, 0, "seek clamps at start");
Near(initial.Seek(10).CursorTime, .2, "seek clamps at end");
Check(!playing.Advance(1).IsPlaying && playing.Advance(1).CursorTime == .2, "end stops/clamps");
Check(!playing.Advance(.2).IsPlaying, "exact end stops");
Check(!initial.Seek(.2).Play().IsPlaying, "forward play at end stays stopped");
Check(!initial.Reverse().Play().IsPlaying, "reverse play at start stays stopped");

var reverse = initial.Seek(.2).Reverse().SetSpeed(.5).Play().Advance(.1);
Near(reverse.CursorTime, .15, "reverse multiplies speed independently");
Check(reverse.Direction == -1 && reverse.Speed == .5, "direction/speed independent");
Check(reverse.Reverse().IsPlaying && reverse.Reverse().Speed == .5, "reverse preserves play and speed");
Check(!reverse.Advance(10).IsPlaying && reverse.Advance(10).CursorTime == 0, "reverse endpoint stop");
foreach (var speed in new[] { .25, .5, 1, 1.5, 2 })
    Near(initial.SetSpeed(speed).Play().Advance(.02).CursorTime, .02 * speed, "allowed speed");
var restarted = reverse.Restart();
Check(!restarted.IsPlaying && restarted.Direction == 1 && restarted.Speed == .5, "restart pauses forward, preserves speed");
Near(restarted.CursorTime, 0, "restart first retained source sample");

var step = initial.Play().Step(1);
Check(!step.IsPlaying && step.Sample.SourceFrameId == 101, "frame step pauses at next original source sample");
step = step.Step(1);
Check(step.Sample.SourceFrameId == 103 && !step.Sample.IsObserved, "frame step exposes invalid original frame");
Near(step.CursorTime, .11, "invalid sample retains source time");
Check(step.Step(1).Sample.SourceFrameId == 107, "step beyond invalid frame");
Check(step.Step(1).Step(1).Sample.SourceFrameId == 107, "step clamps end");
Check(initial.Step(-1).Sample.SourceFrameId == 100, "step clamps start");
Check(initial.Seek(.06).Step(-1).Sample.SourceFrameId == 101, "previous frame from between samples");
Check(initial.Seek(.06).Step(1).Sample.SourceFrameId == 103, "next frame from between samples");
Check(initial.Seek(.11).Step(-1).Sample.SourceFrameId == 101, "previous frame from exact sample");
Check(initial.Reverse().Seek(.11).Step(1).Sample.SourceFrameId == 107, "step direction independent of playback direction");
foreach (var time in new[] { .08, .10, .11, .15, .19 })
    Check(!initial.Seek(time).Sample.IsObserved, "closed gaps and invalid observations must stay unavailable");
Check(initial.Seek(.2).Sample.IsObserved, "observation resumes at valid sample");

var finding = new FindingInterval(take, .04, .11);
var selected = playing.SelectFinding(finding);
Check(!selected.IsPlaying && selected.IsFindingHighlighted, "matching finding pauses and highlights");
Near(selected.CursorTime, .04, "matching finding seeks");
Check(selected.Seek(.11).IsFindingHighlighted, "finding interval includes endpoint");
Check(!selected.Seek(.12).IsFindingHighlighted && !selected.Seek(.03).IsFindingHighlighted, "highlight follows one cursor");
var otherTake = new FindingInterval(Guid.NewGuid(), .15, .2);
var otherSelected = selected.Play().SelectFinding(otherTake);
Check(!otherSelected.IsPlaying && !otherSelected.IsFindingHighlighted, "other take pauses and disables temporal highlight");
Check(ReferenceEquals(otherSelected.SelectedFinding, otherTake), "other take evidence identity remains available");
Near(otherSelected.CursorTime, .04, "other take cannot seek hologram");
Check(!otherSelected.Seek(.15).IsFindingHighlighted, "equal other-take time never highlights");
var distantEvidence = new FindingInterval(Guid.NewGuid(), 5, 6);
var distantSelected = selected.Play().SelectFinding(distantEvidence);
Check(!distantSelected.IsPlaying && !distantSelected.IsFindingHighlighted, "longer other-take evidence pauses without highlight");
Check(ReferenceEquals(distantSelected.SelectedFinding, distantEvidence), "longer other-take evidence retains identity");
Near(distantSelected.CursorTime, .04, "other-take intervals outside this replay cannot seek it");

// Constructor defensively copies all caller-owned collections.
times[0] = 99;
ids[0] = 999;
validity[0] = false;
gaps[0] = new ReplayGap(0, .2);
Check(initial.Sample.IsObserved && initial.Sample.SourceFrameId == 100 && initial.CursorTime == 0, "timeline immutable inputs");
Check(initial.Seek(.05).Sample.IsObserved, "gap input copied");

ReplayTimeline Make(double[] ts, BigInteger[]? fs = null, bool[]? vs = null, ReplayGap[]? gs = null) =>
    new ReplayTimeline(take, ts, fs ?? Enumerable.Range(0, ts.Length).Select(x => new BigInteger(x)).ToArray(),
        vs ?? Enumerable.Repeat(true, ts.Length).ToArray(), gs ?? Array.Empty<ReplayGap>());
foreach (var bad in new[] { double.NaN, double.NegativeInfinity, double.PositiveInfinity })
{
    Reject(() => initial.Seek(bad), "finite seek");
    Reject(() => playing.Advance(bad), "finite elapsed time");
    Reject(() => initial.SetSpeed(bad), "finite speed");
    Reject(() => Make(new[] { 0, bad }), "finite source time");
    Reject(() => new ReplayGap(bad, .2), "finite gap start");
    Reject(() => new ReplayGap(0, bad), "finite gap end");
    Reject(() => new FindingInterval(take, bad, .2), "finite finding start");
    Reject(() => new FindingInterval(take, 0, bad), "finite finding end");
}
Reject(() => initial.Advance(-.01), "negative elapsed even while paused");
foreach (var speed in new[] { -1, 0, .1, 3 }) Reject(() => initial.SetSpeed(speed), "unsupported speed");
foreach (var direction in new[] { -2, 0, 2 }) Reject(() => initial.Step(direction), "invalid step");
Reject(() => new ReplayClock(null!), "null timeline");
Reject(() => initial.SelectFinding(null!), "null finding");
Reject(() => new ReplayTimeline(Guid.Empty, new[] { 0.0 }, new BigInteger[] { 0 }, new[] { true }, Array.Empty<ReplayGap>()), "empty take");
Reject(() => new ReplayTimeline(take, null!, Array.Empty<BigInteger>(), Array.Empty<bool>(), Array.Empty<ReplayGap>()), "null times");
Reject(() => new ReplayTimeline(take, new[] { 0.0 }, null!, new[] { true }, Array.Empty<ReplayGap>()), "null IDs");
Reject(() => new ReplayTimeline(take, new[] { 0.0 }, new BigInteger[] { 0 }, null!, Array.Empty<ReplayGap>()), "null validity");
Reject(() => new ReplayTimeline(take, new[] { 0.0 }, new BigInteger[] { 0 }, new[] { true }, null!), "null gaps");
Reject(() => Make(Array.Empty<double>()), "empty timeline");
Reject(() => Make(new[] { -.1, 0 }), "negative times");
Reject(() => Make(new[] { 0.0, 0.0 }), "duplicate times");
Reject(() => Make(new[] { .2, .1 }), "decreasing times");
Reject(() => Make(new[] { 0.0 }, Array.Empty<BigInteger>()), "ID count mismatch");
Reject(() => Make(new[] { 0.0 }, vs: Array.Empty<bool>()), "validity count mismatch");
Reject(() => Make(new[] { 0.0, .2 }, new BigInteger[] { 7, 7 }), "duplicate IDs");
Reject(() => Make(new[] { 0.0 }, new BigInteger[] { -1 }), "negative original ID");
Reject(() => new ReplayGap(-.1, .2), "negative gap");
Reject(() => new ReplayGap(.2, .2), "empty gap");
Reject(() => new ReplayGap(.2, .1), "inverted gap");
Reject(() => Make(new[] { 0.0, .2 }, gs: new[] { new ReplayGap(.1, .3) }), "gap outside timeline");
Reject(() => Make(new[] { 0.0, .2 }, gs: new[] { new ReplayGap(.1, .18), new ReplayGap(.08, .09) }), "unordered gaps");
Reject(() => Make(new[] { 0.0, .2 }, gs: new[] { new ReplayGap(.04, .1), new ReplayGap(.08, .15) }), "overlapping gaps");
Reject(() => Make(new[] { 0.0, .2 }, gs: new[] { default(ReplayGap) }), "default gap cannot bypass validation");
Reject(() => Make(new[] { 0.0, .08, .2 }, gs: new[] { new ReplayGap(.08, .15) }), "valid frame at gap start");
Reject(() => Make(new[] { 0.0, .15, .2 }, gs: new[] { new ReplayGap(.08, .15) }), "valid frame at gap end");
Reject(() => new FindingInterval(Guid.Empty, 0, .2), "empty finding take");
Reject(() => new FindingInterval(take, -.1, .2), "negative finding start");
Reject(() => new FindingInterval(take, .2, .1), "inverted finding");
Check(new FindingInterval(take, .1, .1).StartTime == .1, "point finding permitted");

var sparse = new ReplayClock(Make(new[] { 0.0, .2 }, gs: new[] { new ReplayGap(.08, .15) }));
Check(!sparse.Seek(.16).Sample.IsObserved, "cannot hold earlier sample across gap");
var touchingGaps = new ReplayClock(Make(new[] { 0.0, .2 }, gs: new[] { new ReplayGap(.08, .1), new ReplayGap(.1, .15) }));
Check(!touchingGaps.Seek(.1).Sample.IsObserved && !touchingGaps.Seek(.16).Sample.IsObserved,
    "touching closed gaps preserve unavailable intervals");
Check(touchingGaps.Seek(.2).Sample.IsObserved, "valid sample after multiple gaps resumes");
var late = new ReplayClock(Make(new[] { .5, .7 }, new[] { BigInteger.Pow(10, 30), BigInteger.One }));
Near(late.CursorTime, .5, "rejected leading samples do not reset source origin");
Check(late.Sample.SourceFrameId == BigInteger.Pow(10, 30), "large original ID retained exactly");
Check(late.Step(1).Sample.SourceFrameId == 1, "nonmonotonic original IDs supported");
var leadingGap = new ReplayClock(Make(new[] { .5, .7 }, gs: new[] { new ReplayGap(0, .49) }));
Check(leadingGap.Sample.IsObserved, "gap before first retained source sample is permitted");
Near(leadingGap.CursorTime, .5, "leading gap does not reset source origin");
var singleton = new ReplayClock(Make(new[] { .5 }));
Check(!singleton.Play().IsPlaying && singleton.Reverse().Step(1).CursorTime == .5, "single-frame replay");
Near(initial.SetSpeed(2).Play().Advance(double.MaxValue).CursorTime, .2, "finite elapsed overflow safely clamps");
var large = new ReplayClock(Make(Enumerable.Range(0, 10001).Select(x => x * .01).ToArray()));
Check(large.Seek(55.555).Step(1).Sample.Index == 5556, "large irregular cursor lookup");
Near(playing.Advance(0).CursorTime, 0, "zero elapsed");

var handMenuArmed = false;
Check(!HandMenuPressEdge.Update(false, false, ref handMenuArmed) && !handMenuArmed, "failed hand menu read cannot arm");
Check(!HandMenuPressEdge.Update(true, true, ref handMenuArmed) && !handMenuArmed, "held hand menu after focus recovery is suppressed");
Check(!HandMenuPressEdge.Update(true, false, ref handMenuArmed) && handMenuArmed, "observed hand menu release arms edge detector");
Check(HandMenuPressEdge.Update(true, true, ref handMenuArmed) && !handMenuArmed, "armed hand menu press fires once");
Check(!HandMenuPressEdge.Update(true, true, ref handMenuArmed) && !handMenuArmed, "held hand menu does not repeat");
handMenuArmed = true;
handMenuArmed = false;
Check(!HandMenuPressEdge.Update(true, true, ref handMenuArmed), "focus loss disarms held hand menu");
Console.WriteLine($"PASS: {checks} replay checks using the synthetic contract fixture.");
