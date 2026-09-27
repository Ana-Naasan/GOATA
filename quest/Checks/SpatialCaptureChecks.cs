using System;
using Physio.Viewer;
static class SpatialCaptureChecks
{
    static int checks;
    static int Main()
    {
        Check(SpatialCapturePresentation.FootSide("not_applicable") == "left", "torso draft cannot leak invalid foot selection");
        Check(SpatialCapturePresentation.FootSide("right") == "right", "saved right foot is preserved");
        Check(SpatialCapturePresentation.ViewName("rear") == "back", "rear shown in familiar language");
        Check(SpatialCapturePresentation.Step("right") == 1 && SpatialCapturePresentation.Step("left") == 4, "patient view order");
        Check(SpatialCapturePresentation.RecordAction(true, false, false, false, false, false) == "Stop recording", "stop always wins while recording");
        Check(SpatialCapturePresentation.RecordAction(false, true, false, false, false, false) == "Cancel recording", "camera preparation can be cancelled");
        Check(SpatialCapturePresentation.RecordAction(false, false, true, false, false, true) == "Record this view", "framing waits for an explicit record action");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, true, false, false) == "Saving recording…", "save cannot trigger another take");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, false, true, false) == "Retry saving", "failed save keeps retry action");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, false, false, false) == "Confirm consent", "consent precedes capture");
        Check(SpatialCapturePresentation.RecordAction(false, false, false, false, false, true) == "Open camera", "camera is opened before the separate recording action");
        Check(SpatialCapturePresentation.Time(14, 10) == "10.0 / 10s", "late UI update clamps to target");
        Check(SpatialCapturePresentation.CaptureClock(false, false, 0, true, false, false, 0, 10) == "FRAMING · READY TO RECORD", "preview has no false elapsed timer");
        Check(SpatialCapturePresentation.CaptureClock(false, true, 2, false, true, false, 0, 10) == "STARTING IN 2", "countdown begins after explicit record action");
        Check(SpatialCapturePresentation.CaptureClock(true, false, 0, false, false, false, 2.5, 10) == "RECORDING 2.5 / 10s", "recording clock follows source take");
        Check(SpatialCapturePresentation.CaptureClock(false, false, 0, false, false, true, 10, 10) == "SAVING ORIGINAL TAKE", "save does not imply a new countdown");
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
        Check(SpatialCapturePresentation.ViewInstruction("elk", "right", 10).Contains("ELK · seated flank stretch"), "ELK capture card identifies the exercise");
        Check(SpatialCapturePresentation.ViewInstruction("rtk", "right", 10).Contains("RTK · seated torso rotation"), "RTK capture card identifies the exercise");
        Check(SpatialCapturePresentation.SetupInstruction("barefoot").Contains("foot"), "historical barefoot guidance preserved");
        Console.WriteLine($"{checks} spatial capture presentation checks passed"); return 0;
    }
    static void Check(bool value, string label) { if (!value) throw new Exception(label); checks++; }
}
