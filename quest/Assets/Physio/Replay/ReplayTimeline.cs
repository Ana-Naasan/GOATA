#nullable enable
using System;
using System.Collections.Generic;
using System.Numerics;

namespace Physio.Replay
{
    public readonly struct ReplayGap
    {
        public double StartTime { get; }
        public double EndTime { get; }

        public ReplayGap(double startTime, double endTime)
        {
            ReplayTimeline.RequireTime(startTime, nameof(startTime));
            ReplayTimeline.RequireTime(endTime, nameof(endTime));
            if (endTime <= startTime) throw new ArgumentException("A gap must have positive duration.");
            StartTime = startTime;
            EndTime = endTime;
        }
    }

    public readonly struct ReplaySample
    {
        public int Index { get; }
        public BigInteger SourceFrameId { get; }
        public double SourceTime { get; }
        public bool IsObserved { get; }

        internal ReplaySample(int index, BigInteger sourceFrameId, double sourceTime, bool isObserved)
        {
            Index = index;
            SourceFrameId = sourceFrameId;
            SourceTime = sourceTime;
            IsObserved = isObserved;
        }
    }

    /// <summary>Original source samples only. Geometry and per-joint validity remain with the importer.</summary>
    public sealed class ReplayTimeline
    {
        private readonly double[] times;
        private readonly BigInteger[] frameIds;
        private readonly bool[] validity;
        private readonly ReplayGap[] gaps;
        public Guid SourceTakeId { get; }
        public int FrameCount => times.Length;
        public double StartTime => times[0];
        public double EndTime => times[times.Length - 1];

        public ReplayTimeline(Guid sourceTakeId, IReadOnlyList<double> sourceTimes,
            IReadOnlyList<BigInteger> sourceFrameIds, IReadOnlyList<bool> frameValid,
            IReadOnlyList<ReplayGap> sourceGaps)
        {
            if (sourceTakeId == Guid.Empty) throw new ArgumentException("A source take is required.", nameof(sourceTakeId));
            if (sourceTimes == null) throw new ArgumentNullException(nameof(sourceTimes));
            if (sourceFrameIds == null) throw new ArgumentNullException(nameof(sourceFrameIds));
            if (frameValid == null) throw new ArgumentNullException(nameof(frameValid));
            if (sourceGaps == null) throw new ArgumentNullException(nameof(sourceGaps));
            if (sourceTimes.Count == 0 || sourceFrameIds.Count != sourceTimes.Count || frameValid.Count != sourceTimes.Count)
                throw new ArgumentException("Source samples must be nonempty and have matching counts.");

            SourceTakeId = sourceTakeId;
            times = new double[sourceTimes.Count];
            frameIds = new BigInteger[sourceTimes.Count];
            validity = new bool[sourceTimes.Count];
            var seen = new HashSet<BigInteger>();
            for (var i = 0; i < times.Length; i++)
            {
                var time = sourceTimes[i];
                var id = sourceFrameIds[i];
                RequireTime(time, nameof(sourceTimes));
                if (i > 0 && time <= times[i - 1]) throw new ArgumentException("Source times must strictly increase.");
                if (id.Sign < 0 || !seen.Add(id)) throw new ArgumentException("Original frame IDs must be unique and nonnegative.");
                times[i] = time;
                frameIds[i] = id;
                validity[i] = frameValid[i];
            }
            gaps = CopyGaps(sourceGaps);
            var gapIndex = 0;
            for (var i = 0; i < times.Length; i++)
            {
                while (gapIndex < gaps.Length && times[i] > gaps[gapIndex].EndTime) gapIndex++;
                if (validity[i] && gapIndex < gaps.Length && times[i] >= gaps[gapIndex].StartTime)
                    throw new ArgumentException("An observation cannot be inside a closed gap.");
            }
        }

        private ReplayGap[] CopyGaps(IReadOnlyList<ReplayGap> sourceGaps)
        {
            var copy = new ReplayGap[sourceGaps.Count];
            for (var i = 0; i < copy.Length; i++)
            {
                var gap = sourceGaps[i];
                // Revalidate because a default struct bypasses its constructor.
                copy[i] = new ReplayGap(gap.StartTime, gap.EndTime);
                if (gap.EndTime > EndTime || (i > 0 && gap.StartTime < copy[i - 1].EndTime))
                    throw new ArgumentException("Gaps must be ordered, disjoint and inside the source interval.");
            }
            return copy;
        }

        internal static void RequireTime(double time, string name)
        {
            if (double.IsNaN(time) || double.IsInfinity(time) || time < 0)
                throw new ArgumentOutOfRangeException(name, "Time must be finite and nonnegative.");
        }

        internal double Clamp(double time) => Math.Max(StartTime, Math.Min(EndTime, time));

        private int IndexAt(double cursor)
        {
            var index = Array.BinarySearch(times, cursor);
            return index >= 0 ? index : Math.Max(0, ~index - 1);
        }

        internal double StepTime(double cursor, int direction)
        {
            var index = IndexAt(cursor);
            if (direction > 0) index++;
            else if (times[index] == cursor) index--;
            return times[Math.Max(0, Math.Min(times.Length - 1, index))];
        }

        internal ReplaySample SampleAt(double cursor)
        {
            var index = IndexAt(cursor);
            // Hold one original sample; never invent observed motion between source samples.
            return new ReplaySample(index, frameIds[index], times[index],
                validity[index] && !CrossesGap(times[index], cursor));
        }

        private bool CrossesGap(double from, double to)
        {
            var low = 0;
            var high = gaps.Length;
            while (low < high)
            {
                var middle = low + (high - low) / 2;
                if (gaps[middle].StartTime <= to) low = middle + 1;
                else high = middle;
            }
            return low > 0 && gaps[low - 1].EndTime >= from;
        }
    }
}
