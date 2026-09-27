#nullable enable
using System;
using System.Globalization;
using System.Collections.Generic;
using System.Linq;

namespace Physio.Viewer
{
    public static class SpatialCapturePresentation
    {
        public static bool LatestCaptureIsSelected(Guid take, bool interrupted, long monotonicTicks, DateTimeOffset takeCompleted,
            IReadOnlyCollection<Guid> selectedTakes, DateTimeOffset finalCaptureCompleted) =>
            !interrupted && monotonicTicks > 0 && takeCompleted == finalCaptureCompleted && selectedTakes.Contains(take);
        public static string SetupInstruction(string test) => test == "walking"
            ? "Record four independent straight walking passes from the patient's right, front, back and left. Choose a clear path; keep the full body and feet visible. Stay still during each pass. Reposition between recordings; never walk backwards to follow the participant."
            : test == "barefoot" ? "Four viewpoints of the selected bare foot while standing. Keep that foot visible and steady. Automated foot assessment is unvalidated."
            : "Repeat the seated movement from the patient's right, front, back and left. Move between takes, then hold steady. Keep the participant and chair centered: the camera records less than your passthrough view.";
        public static string ViewInstruction(string test, string side, double duration) => test == "walking"
            ? $"Straight walking pass · {duration:0} seconds\nClear path · Full body and feet visible · Stay still"
            : test == "barefoot" ? $"{side.ToUpperInvariant()} FOOT · Standing close-up · {duration:0} seconds"
            : $"Seated movement · {duration:0} seconds\nKeep the participant and chair in view.";
        public static string FootSide(string? savedSide) => savedSide == "right" ? "right" : "left";
        public static string ViewName(string view) => view == "rear" ? "back" : view;
        public static int Step(string view) => view switch { "right" => 1, "front" => 2, "rear" => 3, "left" => 4, _ => throw new ArgumentException("Unknown capture viewpoint.") };
        public static string RecordAction(bool recording, bool preparing, bool saving, bool retrySave, bool consent) =>
            recording ? "Stop recording" : preparing ? "Opening camera…" : saving ? "Saving recording…" : retrySave ? "Retry saving" : consent ? "Record" : "Confirm consent";
        public static string Time(double elapsed, double target) =>
            Math.Max(0, Math.Min(elapsed, target)).ToString("0.0", CultureInfo.InvariantCulture) + " / " + target.ToString("0", CultureInfo.InvariantCulture) + "s";
        public static bool RevealHand(bool tracked, bool confident, bool focused, float distance, float facingHead, float palmFacing) =>
            tracked && confident && focused && distance >= .2f && distance <= .85f && facingHead >= .55f && palmFacing >= .45f;
    }
}
