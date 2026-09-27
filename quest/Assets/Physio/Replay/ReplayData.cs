#nullable enable
using System;
using System.Numerics;

namespace Physio.Replay
{
    /// <summary>Validated package values. No caller-owned arrays or JSON objects are retained.</summary>
    public sealed class ReplayData
    {
        private readonly Vector3[] vertices;
        private readonly Vector3[] joints;
        private readonly int[] triangles;
        private readonly int[] parents;
        private readonly string[] names;
        private readonly bool[] frameValid;
        private readonly bool[] jointValid;
        public Guid ResultId { get; }
        public ReplayTimeline Timeline { get; }
        public int FrameCount => Timeline.FrameCount;
        public int VertexCount { get; }
        public int TriangleCount => triangles.Length / 3;
        public int JointCount => parents.Length;
        public bool Synthetic { get; }
        public string ScaleStatus { get; }
        public string ScaleProvenance { get; }

        internal ReplayData(Guid resultId, ReplayTimeline timeline, int vertexCount, bool synthetic,
            string scaleStatus, string scaleProvenance, Vector3[] vertices, Vector3[] joints,
            int[] triangles, int[] parents, string[] names, bool[] frameValid, bool[] jointValid)
        {
            ResultId = resultId;
            Timeline = timeline;
            VertexCount = vertexCount;
            Synthetic = synthetic;
            ScaleStatus = scaleStatus;
            ScaleProvenance = scaleProvenance;
            this.vertices = vertices;
            this.joints = joints;
            this.triangles = triangles;
            this.parents = parents;
            this.names = names;
            this.frameValid = frameValid;
            this.jointValid = jointValid;
        }

        public Vector3 VertexAt(int frame, int vertex)
        {
            Bounds(frame, FrameCount);
            Bounds(vertex, VertexCount);
            if (!frameValid[frame]) throw new InvalidOperationException("This frame has no observed surface.");
            return vertices[frame * VertexCount + vertex];
        }

        public Vector3 JointAt(int frame, int joint)
        {
            if (!IsJointValid(frame, joint)) throw new InvalidOperationException("This joint is not observed.");
            return joints[frame * JointCount + joint];
        }

        public bool IsJointValid(int frame, int joint)
        {
            Bounds(frame, FrameCount);
            Bounds(joint, JointCount);
            return jointValid[frame * JointCount + joint];
        }

        public int JointParentAt(int joint) { Bounds(joint, JointCount); return parents[joint]; }
        public string JointNameAt(int joint) { Bounds(joint, JointCount); return names[joint]; }
        public int TriangleIndexAt(int index) { Bounds(index, triangles.Length); return triangles[index]; }

        private static void Bounds(int index, int count)
        {
            if (index < 0 || index >= count) throw new ArgumentOutOfRangeException(nameof(index));
        }
    }
}
