#nullable enable
using System;
using System.Collections.Generic;
using System.Numerics;
using Newtonsoft.Json.Linq;
using static Physio.Replay.ReplayJson;

namespace Physio.Replay
{
    public static partial class ReplayImporter
    {
        private static (int[] Parents, string[] Names) ReadSkeleton(JObject root, int count)
        {
            var nameTokens = Array(root["joint_names"], count);
            var parentTokens = Array(root["joint_parents"], count);
            var names = new string[count];
            var parents = new int[count];
            var known = new HashSet<string>(StringComparer.Ordinal);
            var roots = 0;
            for (var i = 0; i < count; i++)
            {
                names[i] = String(nameTokens[i], 80);
                Require(known.Add(names[i]), "Duplicate joint name.");
                var parent = Integer(parentTokens[i], -1);
                Require(parent < count, "Joint parent out of bounds.");
                parents[i] = (int)parent;
                if (parents[i] == -1) roots++;
            }
            Require(roots == 1, "Skeleton must have exactly one root.");
            var states = new byte[count];
            for (var i = 0; i < count; i++)
            {
                var cursor = i;
                while (cursor != -1 && states[cursor] == 0) { states[cursor] = 1; cursor = parents[cursor]; }
                Require(cursor == -1 || states[cursor] == 2, "Joint parent cycle.");
                cursor = i;
                while (cursor != -1 && states[cursor] == 1) { states[cursor] = 2; cursor = parents[cursor]; }
            }
            Require(root["joint_regions"] is JObject regions && regions.Count > 0, "Finding regions must be a nonempty object.");
            foreach (var region in ((JObject)root["joint_regions"]!).Properties())
            {
                StringLength(region.Name, 80);
                var members = Array(region.Value);
                Require(members.Count > 0, "Finding region must name at least one joint.");
                var seen = new HashSet<string>(StringComparer.Ordinal);
                foreach (var member in members)
                {
                    var name = String(member, 80);
                    Require(known.Contains(name) && seen.Add(name), "Unknown or duplicate joint in finding region.");
                }
            }
            return (parents, names);
        }

        private static (ReplayTimeline Timeline, bool[] Frames, bool[] Joints) ReadTiming(JObject root, int frameCount, int jointCount)
        {
            var timeTokens = Array(root["frame_times_s"], frameCount);
            var idTokens = Array(root["source_frame_ids"], frameCount);
            var ptsTokens = Array(root["source_pts_ns"], frameCount);
            var validTokens = Array(root["frame_valid"], frameCount);
            var jointTokens = Array(root["joint_valid"], frameCount);
            var clock = Object(root["source_clock"], "id", "unit", "origin_pts_ns");
            String(clock["id"]);
            Require(String(clock["unit"]) == "nanoseconds", "Unsupported source clock unit.");
            var origin = Timestamp(clock["origin_pts_ns"]);
            var times = new double[frameCount];
            var ids = new BigInteger[frameCount];
            var valid = new bool[frameCount];
            var jointValid = new bool[frameCount * jointCount];
            var source = new Dictionary<BigInteger, BigInteger>();
            var previousPts = BigInteger.MinusOne;
            for (var i = 0; i < frameCount; i++)
            {
                times[i] = Number(timeTokens[i]);
                ids[i] = Integer(idTokens[i]);
                var pts = Timestamp(ptsTokens[i]);
                Require(pts > previousPts && Math.Abs(times[i] - (double)(pts - origin) / 1e9) <= 1e-9,
                    "Replay time does not preserve original source PTS.");
                Require(!source.ContainsKey(ids[i]), "Duplicate original frame ID.");
                source.Add(ids[i], pts);
                previousPts = pts;
                valid[i] = Boolean(validTokens[i]);
                var row = Array(jointTokens[i], jointCount);
                for (var j = 0; j < jointCount; j++)
                {
                    var observed = Boolean(row[j]);
                    Require(valid[i] || !observed, "Invalid frame cannot contain an observed joint.");
                    jointValid[i * jointCount + j] = observed;
                }
            }
            ValidateResampling(Array(root["resampling_map"]), source);
            var gapTokens = Array(root["gaps"]);
            var gaps = new ReplayGap[gapTokens.Count];
            for (var i = 0; i < gaps.Length; i++)
            {
                var gap = Object(gapTokens[i], "start_s", "end_s", "reason");
                String(gap["reason"], 500);
                gaps[i] = new ReplayGap(Number(gap["start_s"]), Number(gap["end_s"]));
            }
            return (new ReplayTimeline(Uuid(root["source_take_id"]), times, ids, valid, gaps), valid, jointValid);
        }

        private static void ValidateResampling(JArray mapping, Dictionary<BigInteger, BigInteger> source)
        {
            var previousId = BigInteger.MinusOne;
            var previousPts = BigInteger.MinusOne;
            foreach (var token in mapping)
            {
                var item = Object(token, "inference_frame_id", "source_frame_id", "source_pts_ns");
                var id = Integer(item["inference_frame_id"]);
                var sourceId = Integer(item["source_frame_id"]);
                var pts = Timestamp(item["source_pts_ns"]);
                Require(id > previousId && pts >= previousPts, "Resampling order is invalid.");
                Require(source.TryGetValue(sourceId, out var original) && original == pts, "Resampling references an unknown source sample.");
                previousId = id;
                previousPts = pts;
            }
        }
    }
}
