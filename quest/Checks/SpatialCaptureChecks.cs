using System;
using Physio.Viewer;
static class SpatialCaptureChecks
{
    static int Main()
    {
        Check(SpatialCapturePresentation.FootSide("not_applicable") == "left", "torso draft cannot leak invalid foot selection");
        Check(SpatialCapturePresentation.FootSide("right") == "right", "saved right foot is preserved");
        Check(SpatialCapturePresentation.ViewName("rear") == "back", "rear shown in familiar language");
        Check(SpatialCapturePresentation.Step("right") == 1 && SpatialCapturePresentation.Step("left") == 4, "patient view order");
        Check(SpatialCapturePresentation.RecordAction(true, false, false, false, false) == "Stop recording", "stop always wins while recording");
        Check(SpatialCapturePresentation.RecordAction(false, true, false, false, false) == "Opening camera…", "no duplicate begin during preparation");
        Check(SpatialCapturePresentation.RecordAction(false, false, true, false, false) == "Saving recording…", "save cannot trigger another take");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, true, false) == "Retry saving", "failed save keeps retry action");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, false, false) == "Confirm consent", "consent precedes capture");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, false, true) == "Record", "idle explicit record");
        Check(SpatialCapturePresentation.Time(14, 10) == "10.0 / 10s", "late UI update clamps to target");
        Check(!SpatialCapturePresentation.RevealHand(true, true, false, .6f, .8f, .8f), "focus loss hides shortcut");
        Check(!SpatialCapturePresentation.RevealHand(true, false, true, .6f, .8f, .8f), "confidence loss hides shortcut");
        Check(!SpatialCapturePresentation.RevealHand(true, true, true, .6f, .8f, -.8f), "back of hand cannot reveal");
        Check(SpatialCapturePresentation.RevealHand(true, true, true, .6f, .8f, .8f), "deliberate tracked palm reveals");
        var selected = Guid.NewGuid(); var unselected = Guid.NewGuid(); var completed = DateTimeOffset.UtcNow;
        Check(SpatialCapturePresentation.LatestCaptureIsSelected(selected, false, 42, completed, new[] { selected }, completed), "selected final take permits monotonic time");
        Check(!SpatialCapturePresentation.LatestCaptureIsSelected(selected, true, 42, completed, new[] { selected }, completed), "interrupted retake never supplies latency");
        Check(!SpatialCapturePresentation.LatestCaptureIsSelected(unselected, false, 42, completed, new[] { selected }, completed), "unselected retake never supplies latency");
        Check(!SpatialCapturePresentation.LatestCaptureIsSelected(selected, false, 42, completed, new[] { selected }, completed.AddSeconds(1)), "earlier selected take is not capture completion");
        Check(!SpatialCapturePresentation.LatestCaptureIsSelected(selected, false, 0, completed, new[] { selected }, completed), "missing monotonic origin uses wall estimate");
        var walking = SpatialCapturePresentation.SetupInstruction("walking");
        Check(walking.Contains("straight") && walking.Contains("right, front, back and left"), "walking is four independent straight passes");
        Check(walking.Contains("clear path") && walking.Contains("feet") && walking.Contains("still") && walking.Contains("backwards"), "walking safety framing and stationary practitioner explicit");
        Check(!SpatialCapturePresentation.ViewInstruction("walking", "left", 10).Contains("Seated"), "walking never seated");
        Check(SpatialCapturePresentation.ViewInstruction("walking", "left", 10).Contains("10 seconds"), "walking duration retained");
        Check(SpatialCapturePresentation.SetupInstruction("elk").Contains("seated"), "ELK remains seated");
        Check(SpatialCapturePresentation.SetupInstruction("barefoot").Contains("foot"), "historical barefoot guidance preserved");
        Console.WriteLine("26 spatial capture presentation checks passed"); return 0;
    }
    static void Check(bool value, string label) { if (!value) throw new Exception(label); }
}
