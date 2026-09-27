using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Physio.Replay;

// Authored mannequin only: no recording, fitted anatomy, model output or clinical result.
internal static class DemoGenerator
{
    private const int Frames = 121;
    private const int Sides = 12;
    private const int Rings = 7;
    private const int VerticesPerPart = 2 + Sides * Rings;
    private static readonly string[] Names =
    {
        "pelvis", "spine_lower", "chest", "neck", "head",
        "shoulder_left", "elbow_left", "wrist_left", "hand_left",
        "shoulder_right", "elbow_right", "wrist_right", "hand_right",
        "hip_left", "knee_left", "ankle_left", "toe_left",
        "hip_right", "knee_right", "ankle_right", "toe_right"
    };
    private static readonly int[] Parents = { -1, 0, 1, 2, 3, 2, 5, 6, 7, 2, 9, 10, 11, 0, 13, 14, 15, 0, 17, 18, 19 };
    private static readonly Vector3[] Neutral =
    {
        new(0, .56f, 0), new(0, .72f, 0), new(0, .91f, 0), new(0, 1.07f, 0), new(0, 1.22f, 0),
        new(-.19f, .96f, 0), new(-.30f, .76f, .055f), new(-.23f, .58f, .18f), new(-.205f, .54f, .235f),
        new(.19f, .96f, 0), new(.30f, .76f, .055f), new(.23f, .58f, .18f), new(.205f, .54f, .235f),
        new(-.105f, .53f, .015f), new(-.115f, .49f, .40f), new(-.115f, .075f, .42f), new(-.115f, .035f, .59f),
        new(.105f, .53f, .015f), new(.115f, .49f, .40f), new(.115f, .075f, .42f), new(.115f, .035f, .59f)
    };
    // A/B identify the skeleton anchors. Length is half-height for a sphere, or a segment-length multiplier.
    private static readonly (int A, int B, float Width, float Depth, float Length)[] Parts =
    {
        (0, 0, .17f, .13f, .11f), (0, 3, .175f, .11f, .59f), (4, 4, .095f, .105f, .135f),
        (3, 4, .047f, .047f, .62f), (5, 9, .06f, .09f, .54f),
        (5, 6, .047f, .048f, .65f), (6, 7, .04f, .042f, .62f), (7, 8, .038f, .022f, .88f),
        (9, 10, .047f, .048f, .65f), (10, 11, .04f, .042f, .62f), (11, 12, .038f, .022f, .88f),
        (13, 14, .081f, .09f, .63f), (14, 15, .055f, .055f, .60f), (14, 14, .078f, .078f, .078f), (15, 16, .06f, .042f, .74f),
        (17, 18, .081f, .09f, .63f), (18, 19, .055f, .055f, .60f), (18, 18, .078f, .078f, .078f), (19, 20, .06f, .042f, .74f)
    };

    internal static void Write(string directory)
    {
        var offsets = Enumerable.Range(0, Frames).Select(i => i * 50_000_000L - (i % 2) * 1_000_000L).ToArray();
        var times = offsets.Select(ns => ns / 1e9).ToArray();
        var mesh = Encode(writer =>
        {
            foreach (var time in times)
                foreach (var vertex in Surface(Pose(time), Rotation(time))) WriteVector(writer, vertex);
        });
        var joints = Encode(writer =>
        {
            foreach (var time in times)
                foreach (var joint in Pose(time)) WriteVector(writer, joint);
        });
        var indices = Topology();
        var triangles = Encode(writer => { foreach (var index in indices) writer.Write((uint)index); });
        var manifest = Manifest(times, offsets, triangles, mesh, joints, indices.Length / 3);
        ReplayImporter.Parse(manifest, triangles, mesh, joints);
        Directory.CreateDirectory(directory);
        foreach (var entry in new[] { ("mesh_triangles.bytes", triangles), ("mesh_vertices.bytes", mesh),
            ("skeleton_joints.bytes", joints), ("replay_manifest.json", manifest) })
        {
            File.WriteAllBytes(Path.Combine(directory, entry.Item1), entry.Item2);
            File.WriteAllText(Path.Combine(directory, entry.Item1 + ".meta"),
                "fileFormatVersion: 2\nguid: " + Id("asset/" + entry.Item1).ToString("N") +
                "\nTextScriptImporter:\n  externalObjects: {}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n");
        }
    }

    private static Quaternion Rotation(double time, float weight = 1)
    {
        var phase = (float)Math.Sin(2 * Math.PI * time / 6);
        return Quaternion.CreateFromYawPitchRoll(phase * 25 * MathF.PI / 180 * weight, 0, phase * 6 * MathF.PI / 180 * weight);
    }

    private static Vector3[] Pose(double time) => Neutral.Select((joint, index) => index is >= 1 and <= 12
        ? Neutral[0] + Vector3.Transform(joint - Neutral[0], Rotation(time, index == 1 ? .35f : index == 2 ? .8f : 1))
        : joint).ToArray();

    private static IEnumerable<Vector3> Surface(Vector3[] joints, Quaternion upperRotation)
    {
        foreach (var part in Parts)
        {
            var rotation = part.A is >= 1 and <= 12 || part.B is >= 1 and <= 12 ? upperRotation : Quaternion.Identity;
            var center = (joints[part.A] + joints[part.B]) * .5f;
            var axis = part.A == part.B ? Vector3.Transform(Vector3.UnitY, rotation) : Vector3.Normalize(joints[part.B] - joints[part.A]);
            var reference = Vector3.Transform(Vector3.UnitZ, rotation);
            if (Math.Abs(Vector3.Dot(axis, reference)) > .9f) reference = Vector3.Transform(Vector3.UnitY, rotation);
            var right = Vector3.Normalize(Vector3.Cross(axis, reference));
            var forward = Vector3.Cross(right, axis);
            var halfLength = part.A == part.B ? part.Length : Vector3.Distance(joints[part.A], joints[part.B]) * part.Length;
            yield return center + axis * halfLength;
            for (var ring = 1; ring <= Rings; ring++)
            {
                var theta = MathF.PI * ring / (Rings + 1);
                for (var side = 0; side < Sides; side++)
                {
                    var phi = 2 * MathF.PI * side / Sides;
                    yield return center + axis * (MathF.Cos(theta) * halfLength)
                        + right * (MathF.Sin(theta) * MathF.Cos(phi) * part.Width)
                        + forward * (MathF.Sin(theta) * MathF.Sin(phi) * part.Depth);
                }
            }
            yield return center - axis * halfLength;
        }
    }

    private static int[] Topology()
    {
        var indices = new List<int>();
        for (var part = 0; part < Parts.Length; part++)
        {
            var start = part * VerticesPerPart;
            for (var side = 0; side < Sides; side++)
            {
                var next = (side + 1) % Sides;
                indices.AddRange(new[] { start, start + 1 + next, start + 1 + side });
                for (var ring = 0; ring < Rings - 1; ring++)
                {
                    var upper = start + 1 + ring * Sides;
                    var lower = upper + Sides;
                    indices.AddRange(new[] { upper + side, upper + next, lower + side, upper + next, lower + next, lower + side });
                }
                var lastRing = start + 1 + (Rings - 1) * Sides;
                indices.AddRange(new[] { start + VerticesPerPart - 1, lastRing + side, lastRing + next });
            }
        }
        return indices.ToArray();
    }

    private static byte[] Manifest(double[] times, long[] offsets, byte[] triangles, byte[] mesh, byte[] joints, int triangleCount)
    {
        var value = new
        {
            schema_version = "1.0", result_id = Id("result"), source_take_id = Id("source-take"), synthetic = true,
            model = new { name = "AUTHORED_SYNTHETIC_SEATED_MANNEQUIN", revision = "demo-1.0", topology_revision = "19-ellipsoids-1634v-3192t-v1" },
            frame_count = Frames, vertex_count = Parts.Length * VerticesPerPart, triangle_count = triangleCount, joint_count = Names.Length,
            joint_names = Names, joint_parents = Parents,
            joint_regions = new Dictionary<string, string[]>
            {
                ["demo_torso"] = Names.Take(5).ToArray(), ["demo_left_arm"] = Names.Skip(5).Take(4).ToArray(),
                ["demo_right_arm"] = Names.Skip(9).Take(4).ToArray(), ["demo_legs"] = Names.Skip(13).ToArray()
            },
            frame_times_s = times, source_frame_ids = Enumerable.Range(0, Frames).Select(i => 5000 + i * 2).ToArray(),
            source_pts_ns = offsets.Select(ns => (1_000_000_000L + ns).ToString(System.Globalization.CultureInfo.InvariantCulture)).ToArray(),
            source_clock = new { id = "authored_demo_clock_not_device_capture", unit = "nanoseconds", origin_pts_ns = "1000000000" },
            frame_valid = Enumerable.Repeat(true, Frames).ToArray(), joint_valid = Enumerable.Range(0, Frames).Select(_ => Enumerable.Repeat(true, Names.Length).ToArray()).ToArray(),
            gaps = Array.Empty<object>(), coordinate_system = "unity_left_handed_y_up_z_forward", units = "metres", scale_status = "estimated",
            scale_provenance = "Synthetic interaction demo: authored geometry and motion, not participant capture, model inference or clinical measurements. Dimensions are estimated display units.",
            source_coordinate_system = "authored_unity_coordinates",
            source_to_replay = new[] { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 }, resampling_map = Array.Empty<object>(),
            artifacts = new
            {
                mesh_triangles = Artifact("mesh_triangles.u32", "uint32_le", triangles),
                mesh_vertices = Artifact("mesh_vertices.f32", "float32_le_frame_major_xyz", mesh),
                skeleton_joints = Artifact("skeleton_joints.f32", "float32_le_frame_major_xyz", joints)
            }
        };
        return JsonSerializer.SerializeToUtf8Bytes(value, new JsonSerializerOptions { WriteIndented = true });
    }

    private static object Artifact(string filename, string encoding, byte[] bytes) => new
    {
        artifact_id = Id(filename), filename, byte_size = bytes.Length,
        sha256 = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(), encoding
    };

    private static Guid Id(string label) => new(SHA256.HashData(Encoding.UTF8.GetBytes("physio-authored-demo-v1/" + label)).AsSpan(0, 16));
    private static void WriteVector(BinaryWriter writer, Vector3 value) { writer.Write(value.X); writer.Write(value.Y); writer.Write(value.Z); }
    private static byte[] Encode(Action<BinaryWriter> write)
    {
        using var stream = new MemoryStream();
        using (var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true)) write(writer);
        return stream.ToArray();
    }
}
