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
