#nullable enable
using System;

namespace Physio.Replay
{
    public sealed class FindingInterval
    {
        public Guid TakeId { get; }
        public double StartTime { get; }
        public double EndTime { get; }

        public FindingInterval(Guid takeId, double startTime, double endTime)
        {
            if (takeId == Guid.Empty) throw new ArgumentException("An evidence take is required.", nameof(takeId));
            ReplayTimeline.RequireTime(startTime, nameof(startTime));
            ReplayTimeline.RequireTime(endTime, nameof(endTime));
            if (endTime < startTime) throw new ArgumentException("Finding interval is inverted.");
            TakeId = takeId;
            StartTime = startTime;
            EndTime = endTime;
        }
    }

    /// <summary>Use Sample.Index for both mesh and joints; apply joint validity before rendering.</summary>
    public sealed class ReplayClock
    {
        public ReplayTimeline Timeline { get; }
        public double CursorTime { get; }
        public bool IsPlaying { get; }
        public double Speed { get; }
        public int Direction { get; }
        public FindingInterval? SelectedFinding { get; }
        public ReplaySample Sample => Timeline.SampleAt(CursorTime);
        public bool IsFindingHighlighted => SelectedFinding != null &&
            SelectedFinding.TakeId == Timeline.SourceTakeId &&
            SelectedFinding.StartTime <= CursorTime && CursorTime <= SelectedFinding.EndTime;

        public ReplayClock(ReplayTimeline timeline)
            : this(timeline, timeline?.StartTime ?? throw new ArgumentNullException(nameof(timeline)), false, 1, 1, null) { }

        private ReplayClock(ReplayTimeline timeline, double cursorTime, bool playing, double speed,
            int direction, FindingInterval? finding)
        {
            Timeline = timeline;
            CursorTime = cursorTime;
            IsPlaying = playing && (direction > 0 ? cursorTime < timeline.EndTime : cursorTime > timeline.StartTime);
            Speed = speed;
            Direction = direction;
            SelectedFinding = finding;
        }

        public ReplayClock Play() => new ReplayClock(Timeline, CursorTime, true, Speed, Direction, SelectedFinding);
        public ReplayClock Pause() => new ReplayClock(Timeline, CursorTime, false, Speed, Direction, SelectedFinding);
        public ReplayClock Reverse() => new ReplayClock(Timeline, CursorTime, IsPlaying, Speed, -Direction, SelectedFinding);
        public ReplayClock Restart() => new ReplayClock(Timeline, Timeline.StartTime, false, Speed, 1, SelectedFinding);

        public ReplayClock SetSpeed(double speed)
        {
            if (speed != .25 && speed != .5 && speed != 1 && speed != 1.5 && speed != 2)
                throw new ArgumentOutOfRangeException(nameof(speed), "Supported speeds are 0.25, 0.5, 1, 1.5 and 2.");
            return new ReplayClock(Timeline, CursorTime, IsPlaying, speed, Direction, SelectedFinding);
        }

        public ReplayClock Seek(double sourceTime)
        {
            if (double.IsNaN(sourceTime) || double.IsInfinity(sourceTime))
                throw new ArgumentOutOfRangeException(nameof(sourceTime), "Seek time must be finite.");
            return new ReplayClock(Timeline, Timeline.Clamp(sourceTime), false, Speed, Direction, SelectedFinding);
        }

        public ReplayClock Step(int direction)
        {
            if (direction != -1 && direction != 1)
                throw new ArgumentOutOfRangeException(nameof(direction), "Frame step must be -1 or +1.");
            return Seek(Timeline.StepTime(CursorTime, direction));
        }

        public ReplayClock Advance(double elapsedSeconds)
        {
            ReplayTimeline.RequireTime(elapsedSeconds, nameof(elapsedSeconds));
            if (!IsPlaying) return this;
            var endpoint = Direction > 0 ? Timeline.EndTime : Timeline.StartTime;
            // Compare before multiplying so even finite, very large deltas cannot overflow.
            if (elapsedSeconds >= Math.Abs(endpoint - CursorTime) / Speed)
                return new ReplayClock(Timeline, endpoint, false, Speed, Direction, SelectedFinding);
            return new ReplayClock(Timeline, CursorTime + elapsedSeconds * Speed * Direction,
                true, Speed, Direction, SelectedFinding);
        }

        public ReplayClock SelectFinding(FindingInterval finding)
        {
            if (finding == null) throw new ArgumentNullException(nameof(finding));
            var cursor = finding.TakeId == Timeline.SourceTakeId ? Timeline.Clamp(finding.StartTime) : CursorTime;
            return new ReplayClock(Timeline, cursor, false, Speed, Direction, finding);
        }
    }
}
