#nullable enable
using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.IO;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using static Physio.Replay.ReplayJson;

namespace Physio.Replay
{
    public static partial class ReplayImporter
    {
        public const int MaxJsonBytes = 16 * 1024 * 1024;
        public const int MaxDecodedBytes = 256 * 1024 * 1024;

        public static ReplayData Parse(byte[] manifestUtf8, byte[] triangles, byte[] vertices, byte[] joints)
        {
            if (manifestUtf8 == null || triangles == null || vertices == null || joints == null)
                throw new InvalidDataException("All replay artifacts are required.");
            Require(manifestUtf8.Length <= MaxJsonBytes, "Replay JSON exceeds 16 MiB.");
            Require((long)manifestUtf8.Length + triangles.Length + vertices.Length + joints.Length <= MaxDecodedBytes,
                "Replay inputs exceed 256 MiB.");
            try { return ParseValidated(manifestUtf8, triangles, vertices, joints); }
            catch (JsonException) { throw new InvalidDataException("Invalid replay JSON."); }
            catch (ArgumentException) { throw new InvalidDataException("Invalid replay metadata."); }
            catch (OverflowException) { throw new InvalidDataException("Replay number or allocation exceeds its bound."); }
            catch (FormatException) { throw new InvalidDataException("Invalid replay number."); }
        }

        private static ReplayData ParseValidated(byte[] bytes, byte[] triangles, byte[] vertices, byte[] joints)
        {
            var root = Object(Read(bytes), "schema_version", "result_id", "source_take_id", "synthetic", "model",
                "frame_count", "vertex_count", "triangle_count", "joint_count", "joint_names", "joint_parents",
                "joint_regions", "frame_times_s", "source_frame_ids", "source_pts_ns", "source_clock", "frame_valid",
                "joint_valid", "gaps", "coordinate_system", "units", "scale_status", "scale_provenance",
                "source_coordinate_system", "source_to_replay", "resampling_map", "artifacts");
            var frames = Count(root["frame_count"]);
            var vertexCount = Count(root["vertex_count"]);
            var triangleCount = Count(root["triangle_count"]);
            var jointCount = Count(root["joint_count"]);
            var mapCount = Array(root["resampling_map"]).Count;
            var vertexBytes = checked((long)frames * vertexCount * 12);
            var jointBytes = checked((long)frames * jointCount * 12);
            var triangleBytes = checked((long)triangleCount * 12);
            var decoded = checked(vertexBytes + jointBytes + triangleBytes + frames * (25L + jointCount)
                + jointCount * 4L + 64 + mapCount * 24L + bytes.Length);
            Require(decoded <= MaxDecodedBytes, "Decoded replay exceeds 256 MiB.");
            ValidateMetadata(root);
            var artifacts = Object(root["artifacts"], "mesh_triangles", "mesh_vertices", "skeleton_joints");
            var artifactIds = new HashSet<Guid>();
            ValidateArtifact(artifacts["mesh_triangles"], triangles, triangleBytes, "mesh_triangles.u32", "uint32_le", vertexCount, artifactIds);
            ValidateArtifact(artifacts["mesh_vertices"], vertices, vertexBytes, "mesh_vertices.f32", "float32_le_frame_major_xyz", null, artifactIds);
            ValidateArtifact(artifacts["skeleton_joints"], joints, jointBytes, "skeleton_joints.f32", "float32_le_frame_major_xyz", null, artifactIds);
            var skeleton = ReadSkeleton(root, jointCount);
            var timing = ReadTiming(root, frames, jointCount);
            var indices = new int[triangles.Length / 4];
            for (var i = 0; i < indices.Length; i++) indices[i] = (int)BinaryPrimitives.ReadUInt32LittleEndian(triangles.AsSpan(i * 4, 4));
            return new ReplayData(Uuid(root["result_id"]), timing.Timeline, vertexCount, Boolean(root["synthetic"]),
                String(root["scale_status"]), String(root["scale_provenance"], 1000), DecodeVectors(vertices), DecodeVectors(joints),
                indices, skeleton.Parents, skeleton.Names, timing.Frames, timing.Joints);
        }

        private static void ValidateMetadata(JObject root)
        {
            Require(String(root["schema_version"]) == "1.0", "Unsupported replay schema version.");
            Uuid(root["result_id"]);
            Boolean(root["synthetic"]);
            var model = Object(root["model"], "name", "revision", "topology_revision");
            String(model["name"]); String(model["revision"]); String(model["topology_revision"]);
            Require(String(root["coordinate_system"]) == "unity_left_handed_y_up_z_forward" && String(root["units"]) == "metres",
                "Unsupported replay coordinates or units.");
            var scale = String(root["scale_status"]);
            Require(scale == "estimated" || scale == "calibrated", "Unsupported scale status.");
            String(root["scale_provenance"], 1000);
            String(root["source_coordinate_system"]);
            var transform = Array(root["source_to_replay"], 16);
            var m = new double[16];
            for (var i = 0; i < m.Length; i++) m[i] = Number(transform[i]);
            Require(m[12] == 0 && m[13] == 0 && m[14] == 0 && m[15] == 1, "Source transform must be row-major affine.");
            var determinant = m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8])
                + m[2] * (m[4] * m[9] - m[5] * m[8]);
            Require(!double.IsNaN(determinant) && !double.IsInfinity(determinant) && Math.Abs(determinant) > 1e-12,
                "Source transform is singular or nonfinite.");
        }

        private static void ValidateArtifact(JToken? token, byte[] bytes, long expected, string filename,
            string encoding, int? vertexCount, HashSet<Guid> ids)
        {
            var metadata = Object(token, "artifact_id", "filename", "byte_size", "sha256", "encoding");
            Require(ids.Add(Uuid(metadata["artifact_id"])), "Duplicate replay artifact ID.");
            Require(String(metadata["filename"]) == filename && String(metadata["encoding"]) == encoding,
                "Replay artifact filename or encoding is unsupported.");
            Require(Integer(metadata["byte_size"], 1) == expected && bytes.Length == expected, "Replay artifact byte count mismatch.");
            var digest = String(metadata["sha256"], 64);
            Require(digest.Length == 64, "SHA-256 must contain 64 lowercase hex digits.");
            foreach (var c in digest) Require((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'), "Invalid SHA-256 encoding.");
            using var sha = SHA256.Create();
            var actual = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
            Require(actual == digest, "Replay artifact hash mismatch.");
            for (var offset = 0; offset < bytes.Length; offset += 4)
            {
                if (vertexCount.HasValue)
                    Require(BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(offset, 4)) < vertexCount.Value, "Triangle index out of bounds.");
                else
                {
                    var value = ReadFloat(bytes, offset);
                    Require(!float.IsNaN(value) && !float.IsInfinity(value), "Replay coordinate must be finite.");
                }
            }
        }

        private static float ReadFloat(byte[] bytes, int offset) =>
            BitConverter.Int32BitsToSingle(BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(offset, 4)));

        private static Vector3[] DecodeVectors(byte[] bytes)
        {
            var values = new Vector3[bytes.Length / 12];
            for (var i = 0; i < values.Length; i++)
                values[i] = new Vector3(ReadFloat(bytes, i * 12), ReadFloat(bytes, i * 12 + 4), ReadFloat(bytes, i * 12 + 8));
            return values;
        }
    }
}
