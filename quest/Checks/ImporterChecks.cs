using System;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Physio.Replay;

var folder = Path.Combine(AppContext.BaseDirectory, "fixtures");
var manifest = File.ReadAllBytes(Path.Combine(folder, "replay_manifest.json"));
var triangles = File.ReadAllBytes(Path.Combine(folder, "mesh_triangles.u32"));
var vertices = File.ReadAllBytes(Path.Combine(folder, "mesh_vertices.f32"));
var joints = File.ReadAllBytes(Path.Combine(folder, "skeleton_joints.f32"));
var count = 0;

void Check(bool condition, string label)
{
    if (!condition) throw new Exception(label);
    count++;
}

byte[] Edit(Action<JsonNode> edit)
{
    var document = JsonNode.Parse(manifest)!;
    edit(document);
    return Encoding.UTF8.GetBytes(document.ToJsonString());
}

ReplayData Parse(byte[]? json = null, byte[]? ts = null, byte[]? vs = null, byte[]? js = null) =>
    ReplayImporter.Parse(json ?? manifest, ts ?? triangles, vs ?? vertices, js ?? joints);

void Reject(Action action, string label)
{
    try { action(); }
    catch (InvalidDataException) { count++; return; }
    throw new Exception("Expected InvalidDataException: " + label);
}

void Bad(Action<JsonNode> edit, string label) => Reject(() => Parse(Edit(edit)), label);

void BadText(string text, string label) => Reject(() => Parse(Encoding.UTF8.GetBytes(text)), label);

void GeometryReject(Action action, string label)
{
    try { action(); }
    catch (InvalidOperationException) { count++; return; }
    throw new Exception("Expected invalid observation rejection: " + label);
}

void BoundsReject(Action action, string label)
{
    try { action(); }
    catch (ArgumentOutOfRangeException) { count++; return; }
    throw new Exception("Expected index bounds rejection: " + label);
}

var data = Parse();
Check(data.FrameCount == 4 && data.VertexCount == 4 && data.TriangleCount == 4 && data.JointCount == 3, "fixture dimensions");
Check(data.Synthetic && data.ScaleStatus == "estimated" && data.ScaleProvenance.Contains("synthetic"), "fixture provenance");
Check(data.VertexAt(0, 0) == new Vector3(-.25f, 0, 0), "left tip axis");
Check(data.VertexAt(0, 1) == new Vector3(.5f, 0, 0), "asymmetric right tip axis");
Check(data.VertexAt(0, 3) == new Vector3(0, .1f, .4f), "positive forward apex");
Check(data.TriangleIndexAt(0) == 0 && data.TriangleIndexAt(1) == 2 && data.TriangleIndexAt(2) == 1, "triangle winding preserved");
Check(data.JointAt(3, 0) == new Vector3(.3f, 0, .15f), "root motion retained");
Check(data.JointParentAt(0) == -1 && data.JointParentAt(2) == 0 && data.JointNameAt(1) == "high_tip", "skeleton metadata");
Check(!data.IsJointValid(1, 2) && !data.IsJointValid(2, 0) && data.IsJointValid(3, 2), "joint validity retained");
GeometryReject(() => data.JointAt(1, 2), "invalid joint cannot become zero observation");
GeometryReject(() => data.JointAt(2, 0), "invalid frame joint cannot be observed");
GeometryReject(() => data.VertexAt(2, 0), "invalid frame vertex cannot be observed");
var clock = new ReplayClock(data.Timeline).Step(1).Step(1);
Check(clock.Sample.SourceFrameId == 103 && clock.CursorTime == .11 && !clock.Sample.IsObserved, "importer reuses source timeline");
Check(!clock.Seek(.08).Sample.IsObserved && clock.Seek(.2).Sample.SourceFrameId == 107, "imported closed gap and source IDs");
var transformed = Parse(Edit(x => x["source_to_replay"]![3] = 100));
Check(transformed.VertexAt(0, 0) == data.VertexAt(0, 0), "converted coordinates must not be transformed twice");
var unicode = Parse(Edit(x => { x["joint_names"]![1] = "tip 🦶"; x["joint_regions"]!["synthetic_upper"]![0] = "tip 🦶"; }));
Check(unicode.JointNameAt(1) == "tip 🦶", "Unicode metadata survives");
var calibrated = Parse(Edit(x => { x["synthetic"] = false; x["scale_status"] = "calibrated"; }));
Check(!calibrated.Synthetic && calibrated.ScaleStatus == "calibrated", "provenance remains input metadata");

foreach (var invalid in new[] { -1, 4 }) BoundsReject(() => data.VertexAt(invalid, 0), "frame bounds");
foreach (var invalid in new[] { -1, 4 }) BoundsReject(() => data.VertexAt(0, invalid), "vertex bounds");
foreach (var invalid in new[] { -1, 3 })
{
    BoundsReject(() => data.JointAt(0, invalid), "joint bounds");
    BoundsReject(() => data.IsJointValid(0, invalid), "validity bounds");
    BoundsReject(() => data.JointParentAt(invalid), "parent bounds");
    BoundsReject(() => data.JointNameAt(invalid), "name bounds");
}
BoundsReject(() => data.IsJointValid(4, 0), "joint validity frame bounds");
foreach (var invalid in new[] { -1, 12 }) BoundsReject(() => data.TriangleIndexAt(invalid), "triangle bounds");

var manifestText = Encoding.UTF8.GetString(manifest);
BadText(manifestText.Replace("\"schema_version\": \"1.0\"", "\"schema_version\": \"1.0\", \"schema_version\": \"1.0\""), "duplicate root key");
BadText(manifestText.Replace("\"revision\": \"1.0\"", "\"revision\": \"1.0\", \"revision\": \"1.0\""), "duplicate nested key");
BadText(manifestText + " {}", "trailing JSON document");
BadText(manifestText.Insert(1, "// comment\n"), "comments");
BadText(manifestText.Replace("\"schema_version\"", "'schema_version'"), "single quote property");
BadText(manifestText.Replace("\"schema_version\"", "schema_version"), "unquoted property");
BadText(manifestText.TrimEnd().Insert(manifestText.TrimEnd().Length - 1, ","), "trailing object comma");
BadText(manifestText.Replace("0.04,", "0.04,,"), "missing array element");
BadText(manifestText.Replace("0.04,", "+0.04,"), "leading plus number");
BadText(manifestText.Replace("0.04,", "00.04,"), "leading zero number");
BadText(manifestText.Replace("0.04,", ".04,"), "missing integer part");
BadText(manifestText.Replace("0.04,", "4.,"), "missing fractional digits");
BadText(manifestText.Replace("0.04,", "NaN,"), "NaN token");
BadText(manifestText.Replace("0.04,", "1e999,"), "overflowing number");
BadText(manifestText.Replace("synthetic_pts", "bad\nstring"), "raw control in string");
BadText(manifestText.Replace("synthetic_pts", "\\uD800"), "unpaired Unicode surrogate");
BadText("[" + new string('[', 100) + new string(']', 100) + "]", "excessive depth");
foreach (var invalid in new[] { "", "null", "[]", "true", "{", "{\"x\":undefined}", "{\"x\":new Date(1)}" })
    BadText(invalid, "invalid top-level syntax");
Reject(() => Parse(new byte[] { 0xff, 0xfe }), "invalid UTF8");
Reject(() => Parse(new byte[16 * 1024 * 1024 + 1]), "JSON byte ceiling before parse");
Reject(() => ReplayImporter.Parse(null!, triangles, vertices, joints), "null manifest");
Reject(() => ReplayImporter.Parse(manifest, null!, vertices, joints), "null triangles");
Reject(() => ReplayImporter.Parse(manifest, triangles, null!, joints), "null vertices");
Reject(() => ReplayImporter.Parse(manifest, triangles, vertices, null!), "null joints");

foreach (var key in JsonNode.Parse(manifest)!.AsObject().Select(x => x.Key).ToArray())
    Bad(x => x.AsObject().Remove(key), "missing root field " + key);
Bad(x => x["unknown"] = 1, "unknown root field");
foreach (var key in new[] { "model", "source_clock", "artifacts", "artifacts.mesh_vertices" })
    Bad(x => { var value = key.Split('.').Aggregate(x, (item, part) => item[part]!); value["unknown"] = 1; }, "unknown nested field");
Bad(x => x["schema_version"] = "2.0", "schema version");
Bad(x => x["result_id"] = "invalid", "result UUID");
Bad(x => x["source_take_id"] = "invalid", "take UUID");
Bad(x => x["synthetic"] = 1, "boolean type");
Bad(x => x["scale_status"] = "measured", "scale enum");
Bad(x => x["coordinate_system"] = "right_handed", "coordinate convention");
Bad(x => x["units"] = "centimetres", "unit convention");
Bad(x => x["model"]!["name"] = "", "empty bounded string");
Bad(x => x["scale_provenance"] = new string('x', 1001), "oversized bounded string");
Bad(x => x["model"] = new JsonArray(), "object type");
Bad(x => x["frame_valid"] = "true", "array type");
foreach (var field in new[] { "frame_count", "vertex_count", "triangle_count", "joint_count" })
{
    Bad(x => x[field] = 0, "zero count");
    Bad(x => x[field] = int.MaxValue, "count exceeds lengths/budget");
    Bad(x => x[field] = "4", "string count");
}
BadText(manifestText.Replace("\"frame_count\": 4", "\"frame_count\": 4.0"), "integer-valued float count");
BadText(manifestText.Replace("\"frame_count\": 4", "\"frame_count\": 999999999999999999999999999999"), "huge count");
BadText(manifestText.Replace("\"frame_count\": 4", "\"frame_count\": " + new string('9', 10000)), "oversized integer rejected before BigInteger parsing");
Bad(x => { x["frame_count"] = 10000; x["vertex_count"] = 10000; }, "decoded budget before allocations");
Bad(x => x["frame_times_s"]![1] = 0, "duplicate source time");
Bad(x => x["frame_times_s"]![1] = -.01, "negative source time");
Bad(x => x["frame_times_s"]![1] = .05, "time/PTS mismatch");
Bad(x => x["source_frame_ids"]![1] = 100, "duplicate source ID");
Bad(x => x["source_frame_ids"]![1] = -1, "negative source ID");
Bad(x => x["source_pts_ns"]![1] = "1000000000", "duplicate PTS");
Bad(x => x["source_pts_ns"]![1] = "01040000000", "noncanonical PTS");
Bad(x => x["source_pts_ns"]![1] = new string('1', 31), "oversized PTS");
Bad(x => x["source_clock"]!["unit"] = "seconds", "clock unit");
Bad(x => x["joint_valid"]![2]![0] = true, "valid joint in invalid frame");
Bad(x => x["joint_valid"]![0]!.AsArray().RemoveAt(0), "joint validity width");
Bad(x => x["frame_valid"]![0] = 1, "strict boolean mask");
Bad(x => x["gaps"]![0]!["start_s"] = .04, "valid frame at closed gap start");
Bad(x => x["gaps"]![0]!["end_s"] = .2, "valid frame at closed gap end");
Bad(x => x["gaps"]![0]!["end_s"] = .3, "gap outside timeline");
Bad(x => x["gaps"]![0]!["reason"] = "", "gap reason");
Bad(x => x["resampling_map"]![1]!["inference_frame_id"] = 0, "inference ID ordering");
Bad(x => x["resampling_map"]![0]!["source_frame_id"] = 999, "unknown resampling source");
Bad(x => x["resampling_map"]![0]!["source_pts_ns"] = "999", "resampling PTS mismatch");
Bad(x => { x["resampling_map"]![0]!["source_frame_id"] = 107; x["resampling_map"]![0]!["source_pts_ns"] = "1200000000"; }, "resampling source time reversal");
Bad(x => x["joint_names"]![1] = "root", "duplicate names");
Bad(x => x["joint_parents"]![1] = -1, "multiple roots");
Bad(x => x["joint_parents"]![1] = 3, "parent out of range");
Bad(x => { x["joint_parents"]![1] = 2; x["joint_parents"]![2] = 1; }, "parent cycle");
Bad(x => x["joint_regions"]!["synthetic_upper"]![0] = "unknown", "unknown region joint");
Bad(x => x["joint_regions"]!["synthetic_upper"]!.AsArray().Add("high_tip"), "duplicate region joint");
Bad(x => x["joint_regions"] = new JsonObject(), "empty regions");
Bad(x => x["source_to_replay"]![15] = 0, "nonaffine transform");
Bad(x => x["source_to_replay"]![0] = 0, "singular transform");
foreach (var role in new[] { "mesh_triangles", "mesh_vertices", "skeleton_joints" })
{
    Bad(x => x["artifacts"]![role]!["filename"] = "../escape", "fixed filename");
    Bad(x => x["artifacts"]![role]!["byte_size"] = 1, "declared artifact size");
    Bad(x => x["artifacts"]![role]!["encoding"] = "unknown", "encoding");
    Bad(x => x["artifacts"]![role]!["sha256"] = new string('0', 64), "hash mismatch");
    Bad(x => x["artifacts"]![role]!["sha256"] = "invalid", "hash format");
}
Bad(x => x["artifacts"]!["mesh_vertices"]!["artifact_id"] = x["artifacts"]!["mesh_triangles"]!["artifact_id"]!.DeepClone(), "duplicate artifact UUID");
Reject(() => Parse(ts: triangles[..^1]), "truncated triangles");
Reject(() => Parse(vs: vertices.Concat(new byte[4]).ToArray()), "oversized vertices");
Reject(() => Parse(js: joints[..^4]), "truncated joints");
foreach (var (role, badBytes) in new[] { ("mesh_triangles", (byte[])triangles.Clone()), ("mesh_vertices", (byte[])vertices.Clone()), ("skeleton_joints", (byte[])joints.Clone()) })
{
    var badValue = role == "mesh_triangles" ? BitConverter.GetBytes(uint.MaxValue) : BitConverter.GetBytes(float.NaN);
    badValue.CopyTo(badBytes, 0);
    var modified = Edit(x => x["artifacts"]![role]!["sha256"] = Convert.ToHexString(SHA256.HashData(badBytes)).ToLowerInvariant());
    Reject(() => Parse(modified, role == "mesh_triangles" ? badBytes : null,
        role == "mesh_vertices" ? badBytes : null, role == "skeleton_joints" ? badBytes : null), "malformed binary with correct hash");
}
var originalVertex = data.VertexAt(0, 0);
Array.Clear(manifest); Array.Clear(triangles); Array.Clear(vertices); Array.Clear(joints);
Check(data.VertexAt(0, 0) == originalVertex && data.JointNameAt(0) == "root", "imported data owns values after caller mutation");
Console.WriteLine($"PASS: {count} replay importer checks using the synthetic contract fixture.");
