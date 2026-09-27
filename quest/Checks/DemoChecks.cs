using System;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using Physio.Replay;

// Run from the repository root. These authored values establish interaction mechanics only.
var directory = Path.GetFullPath("quest/Assets/Resources/Physio/Demo");
if (args.Length == 1 && args[0] == "--generate") DemoGenerator.Write(directory);
else if (args.Length != 0) throw new ArgumentException("Use --generate to rebuild the authored demo, or no arguments to check it.");
var manifest = File.ReadAllBytes(Path.Combine(directory, "replay_manifest.json"));
var data = ReplayImporter.Parse(manifest,
    File.ReadAllBytes(Path.Combine(directory, "mesh_triangles.bytes")),
    File.ReadAllBytes(Path.Combine(directory, "mesh_vertices.bytes")),
    File.ReadAllBytes(Path.Combine(directory, "skeleton_joints.bytes")));
using var json = JsonDocument.Parse(manifest);
var root = json.RootElement;
var checks = 0;
void Check(bool condition, string label)
{
    if (!condition) throw new Exception(label);
    checks++;
}
bool Near(Vector3 actual, Vector3 expected, float tolerance = 1e-5f) => Vector3.Distance(actual, expected) <= tolerance;
Check(data.Synthetic && data.ScaleStatus == "estimated", "demo must remain synthetic with estimated scale");
Check(data.ScaleProvenance.Contains("authored", StringComparison.OrdinalIgnoreCase)
    && data.ScaleProvenance.Contains("not participant", StringComparison.OrdinalIgnoreCase), "unmistakable authored provenance");
Check(root.GetProperty("model").GetProperty("name").GetString()!.Contains("SYNTHETIC"), "model cannot imply reconstruction");
Check(!root.TryGetProperty("findings", out _) && !root.TryGetProperty("confidence", out _), "no clinical findings or confidence");
Check(data.FrameCount == 121 && data.Timeline.StartTime == 0 && data.Timeline.EndTime == 6, "six-second replay timing");
Check(data.JointCount == 21 && data.VertexCount >= 1000 && data.VertexCount < 4000, "readable low-poly humanoid dimensions");
Check(data.TriangleCount > data.VertexCount && data.TriangleCount < 8000, "bounded surface topology");
Check(root.GetProperty("gaps").GetArrayLength() == 0, "interaction demo must stay visible");
Check(root.GetProperty("frame_valid").EnumerateArray().All(x => x.GetBoolean()), "all demo frames explicitly valid");
Check(root.GetProperty("joint_valid").EnumerateArray().All(row => row.EnumerateArray().All(x => x.GetBoolean())), "all authored joints explicitly valid");
Check(data.JointNameAt(0) == "pelvis" && data.JointNameAt(4) == "head" && data.JointNameAt(20) == "toe_right", "human joint labels");
Check(data.JointParentAt(0) == -1 && data.JointParentAt(4) == 3, "aligned skeleton hierarchy");
Check(Near(data.JointAt(0, 0), new Vector3(0, .56f, 0)) && data.JointAt(0, 4).Y > 1.15f, "seated pelvis and head height");
Check(data.JointAt(0, 14).Z > .35f && data.JointAt(0, 15).Y < .1f, "bent seated legs and feet near floor");
Check(data.JointAt(0, 5).X < -.15f && data.JointAt(0, 9).X > .15f, "left and right shoulders preserved");

var times = root.GetProperty("frame_times_s").EnumerateArray().Select(x => x.GetDouble()).ToArray();
Check(times[1] == .049 && times[2] == .1, "authored irregular timestamps retained");
var stepped = new ReplayClock(data.Timeline).Step(1);
Check(stepped.Sample.SourceFrameId == 5002 && stepped.CursorTime == .049 && stepped.Sample.IsObserved, "stable nonconsecutive source IDs");
for (var frame = 0; frame < data.FrameCount; frame++)
{
    Check(Near(data.JointAt(frame, 0), data.JointAt(0, 0)), "pelvis stays seated");
    foreach (var joint in new[] { 13, 14, 15, 16, 17, 18, 19, 20 })
        Check(Near(data.JointAt(frame, joint), data.JointAt(0, joint)), "legs stay planted");
    for (var joint = 0; joint < data.JointCount; joint++) Check(data.IsJointValid(frame, joint), "authored joint remains available");
    Check(new ReplayClock(data.Timeline).Seek(times[frame]).Sample.IsObserved, "no disappearing interaction frame");
}
Check(Math.Abs(data.JointAt(30, 5).Z - data.JointAt(90, 5).Z) > .1f, "visible left/right torso rotation");
Check(Near(data.JointAt(0, 4), data.JointAt(120, 4)), "motion returns to neutral");
Check(Near(data.VertexAt(0, 0), data.VertexAt(120, 0)), "surface returns with skeleton");

// Each closed ellipsoid has two poles and seven rings of twelve vertices.
const int verticesPerPart = 86;
const int trianglesPerPart = 168;
var centers = new (int A, int B)[]
{
    (0, 0), (0, 3), (4, 4), (3, 4), (5, 9),
    (5, 6), (6, 7), (7, 8), (9, 10), (10, 11), (11, 12),
    (13, 14), (14, 15), (14, 14), (15, 16),
    (17, 18), (18, 19), (18, 18), (19, 20)
};
Check(data.VertexCount == centers.Length * verticesPerPart && data.TriangleCount == centers.Length * trianglesPerPart, "fixed authored surface parts");
foreach (var frame in new[] { 0, 30, 60, 90, 120 })
{
    for (var part = 0; part < centers.Length; part++)
    {
        var sum = Vector3.Zero;
        for (var vertex = 0; vertex < verticesPerPart; vertex++) sum += data.VertexAt(frame, part * verticesPerPart + vertex);
        var expected = (data.JointAt(frame, centers[part].A) + data.JointAt(frame, centers[part].B)) * .5f;
        Check(Near(sum / verticesPerPart, expected), "surface centers follow matching joint poses");
        for (var triangle = 0; triangle < trianglesPerPart; triangle++)
        {
            var index = (part * trianglesPerPart + triangle) * 3;
            var a = data.VertexAt(frame, data.TriangleIndexAt(index));
            var b = data.VertexAt(frame, data.TriangleIndexAt(index + 1));
            var c = data.VertexAt(frame, data.TriangleIndexAt(index + 2));
            Check(Vector3.Dot(Vector3.Cross(b - a, c - a), (a + b + c) / 3 - expected) > 1e-9f,
                "nondegenerate outward triangle winding");
        }
    }
}
Console.WriteLine($"PASS: {checks} synthetic mannequin checks; {data.FrameCount} frames, {data.VertexCount} vertices, {data.TriangleCount} triangles, {data.JointCount} joints.");
