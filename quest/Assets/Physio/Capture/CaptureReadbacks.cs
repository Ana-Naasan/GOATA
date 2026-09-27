using System;
using System.Collections.Generic;

namespace Physio.Capture
{
    /// <summary>Three camera reads may overlap; encoding always follows source order. Main thread only.</summary>
    internal sealed class CaptureReadbacks
    {
        internal sealed class Frame
        {
            public readonly int FrameId;
            public readonly long SourceNanoseconds;
            public readonly sbyte[] Pixels;
            internal bool Ready;
            public bool Failed { get; internal set; }
            internal Frame(int frameId,long sourceNanoseconds,sbyte[] pixels)
            { FrameId=frameId;SourceNanoseconds=sourceNanoseconds;Pixels=pixels; }
        }

        const int Capacity=3;
        readonly Queue<Frame> pending=new Queue<Frame>(Capacity);
        readonly Queue<sbyte[]> available=new Queue<sbyte[]>(Capacity);
        bool accepting=true;
        int lastFrameId=-1;
        long lastSourceNs=-1;
        public int Count => pending.Count;
        public bool IsCancelled { get; private set; }

        public CaptureReadbacks(int bytesPerFrame)
        {
            if(bytesPerFrame<1 || bytesPerFrame>2_073_600*4) throw new ArgumentException("Invalid frame buffer size.");
            for(int i=0;i<Capacity;i++) available.Enqueue(new sbyte[bytesPerFrame]);
        }

        public bool TryReserve(int frameId,long sourceNs,out Frame frame)
        {
            frame=null;
            if(!accepting || available.Count==0) return false;
            if(frameId<=lastFrameId || sourceNs<=lastSourceNs) throw new ArgumentException("Readbacks require ordered source frames.");
            frame=new Frame(frameId,sourceNs,available.Dequeue());pending.Enqueue(frame);
            lastFrameId=frameId;lastSourceNs=sourceNs;
            return true;
        }

        public bool IsPending(Frame frame) => !IsCancelled && frame!=null && !frame.Ready && pending.Contains(frame);

        public bool Complete(Frame frame,bool failed)
        {
            if(!IsPending(frame)) return false;
            frame.Failed=failed;frame.Ready=true;return true;
        }

        public bool TryPeekReady(out Frame frame)
        {
            frame=pending.Count>0?pending.Peek():null;
            return frame!=null && frame.Ready;
        }

        public void Release(Frame frame)
        {
            if(!TryPeekReady(out var head) || !ReferenceEquals(frame,head))
                throw new InvalidOperationException("Only the completed oldest readback can be released.");
            pending.Dequeue();available.Enqueue(frame.Pixels);
        }

        public void StopAccepting() { accepting=false; }

        public Frame[] Cancel()
        {
            StopAccepting();IsCancelled=true;
            var abandoned=pending.ToArray();pending.Clear();available.Clear();
            return abandoned;
        }
    }
}
