package com.hth.capture;

import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

/** Bounded CPU capture encoder. Camera/source timestamps remain owned by the C# sidecar. */
public final class PhysioMp4Recorder {
    private static final class Frame {
        final byte[] pixels; final long pts;
        Frame(byte[] pixels, long pts) { this.pixels = pixels; this.pts = pts; }
    }
    private final ArrayBlockingQueue<Frame> queue = new ArrayBlockingQueue<>(2);
    private final ArrayList<Long> submitted = new ArrayList<>();
    private final ArrayList<Long> encoded = new ArrayList<>();
    private final int width, height;
    private final byte[] lumaRows;
    private final boolean flipRows;
    private final String path;
    private volatile boolean stopping, done, ready;
    private volatile String error = "";
    private volatile long[] presentationTimes = new long[0];
    private long lastSubmitted = -1;
    private int accepted;
    // Encoder-thread-owned counters, emitted once on completion without capture identifiers.
    private long inputWaitNanos, conversionNanos, maxConversionNanos, drainNanos, warmupNanos;
    private int inputWaitCalls, conversionCalls, drainCalls, warmupCalls;
    private MediaCodec codec;
    private MediaMuxer muxer;
    private int track = -1;

    public PhysioMp4Recorder(String path, int width, int height, boolean flipRows) {
        if (width < 32 || height < 32 || width % 2 != 0 || height % 2 != 0 || (long)width * height > 2073600)
            throw new IllegalArgumentException("Invalid recording dimensions");
        this.lumaRows=new byte[width*2];
        this.path=path; this.width=width; this.height=height; this.flipRows=flipRows;
        new Thread(this::encode, "Physio-camera-encoder").start();
    }

    public synchronized boolean submit(byte[] rgba, long presentationUs) {
        if (!ready || stopping || done || rgba == null || rgba.length != width*height*4 || presentationUs <= lastSubmitted ||
            presentationUs < 0 || presentationUs > 19966666 || accepted >= 600) return false;
        if (!queue.offer(new Frame(rgba, presentationUs))) return false;
        lastSubmitted=presentationUs; accepted++; return true;
    }
    public void finish() { stopping=true; }
    public boolean isDone() { return done; }
    public boolean isReady() { return ready; }
    public String getError() { return error; }
    public long[] getPresentationTimes() { return presentationTimes.clone(); }

    private void encode() {
        long started=System.nanoTime();
        try {
            MediaFormat format=MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC,width,height);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            format.setInteger(MediaFormat.KEY_BIT_RATE,6000000);
            format.setInteger(MediaFormat.KEY_FRAME_RATE,30);
            format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL,1);
            format.setInteger(MediaFormat.KEY_PROFILE,MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
            format.setInteger(MediaFormat.KEY_MAX_B_FRAMES,0);
            format.setInteger(MediaFormat.KEY_COLOR_STANDARD,MediaFormat.COLOR_STANDARD_BT601_NTSC);
            format.setInteger(MediaFormat.KEY_COLOR_RANGE,MediaFormat.COLOR_RANGE_LIMITED);
            format.setInteger(MediaFormat.KEY_COLOR_TRANSFER,MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
            codec=MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC);
            codec.configure(format,null,null,MediaCodec.CONFIGURE_FLAG_ENCODE);
            muxer=new MediaMuxer(path,MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            codec.start();
            if(!warmUpConversion()) return;
            ready=true;
            while (!stopping || !queue.isEmpty()) {
                Frame frame=queue.poll(20,TimeUnit.MILLISECONDS);
                if(frame!=null) writeFrame(frame);
                drain(false);
            }
            int index=inputBuffer();
            codec.queueInputBuffer(index,0,0,lastSubmitted+33333,MediaCodec.BUFFER_FLAG_END_OF_STREAM);
            drain(true);
            if(encoded.size()<2 || encoded.size()!=submitted.size()) throw new IllegalStateException("Encoder omitted source frames");
            muxer.stop(); muxer.release(); muxer=null;
            verifyMuxed();
        } catch (Exception failure) {
            // Detailed errors stay in logcat; user-facing callers receive a bounded, non-sensitive message.
            android.util.Log.e("PhysioCapture","Recording encoder failed",failure);
            error="Recording could not be encoded and verified. Retake after checking device storage and camera access.";
        } finally {
            if(codec!=null) {
                try { codec.stop(); } catch(RuntimeException failure) { android.util.Log.w("PhysioCapture","Encoder stop failed during cleanup",failure); }
                try { codec.release(); } catch(RuntimeException failure) { android.util.Log.w("PhysioCapture","Encoder release failed during cleanup",failure); }
            }
            if(muxer!=null) { try { muxer.release(); } catch(RuntimeException failure) { android.util.Log.w("PhysioCapture","Muxer release failed during cleanup",failure); } }
            queue.clear();
            try {
                android.util.Log.i("PhysioCapture",String.format(java.util.Locale.ROOT,
                    "PHYSIO_NATIVE_TIMING warmup_calls=%d warmup_ms=%.3f submitted_frames=%d encoded_frames=%d conversion_calls=%d conversion_ms_total=%.3f conversion_ms_max=%.3f input_wait_calls=%d input_wait_ms_total=%.3f drain_calls=%d drain_ms_total=%.3f lifetime_ms=%.3f",
                    warmupCalls,warmupNanos/1e6,submitted.size(),encoded.size(),conversionCalls,conversionNanos/1e6,maxConversionNanos/1e6,
                    inputWaitCalls,inputWaitNanos/1e6,drainCalls,drainNanos/1e6,(System.nanoTime()-started)/1e6));
            } finally { done=true; }
        }
    }

    private boolean warmUpConversion() {
        long started=System.nanoTime();
        try {
            // Local synthetic buffers only: never queued to the codec or assigned source timestamps.
            // Existing constructor limits cap these buffers at 5.5 * 2,073,600 bytes.
            byte[] synthetic=new byte[width*height*4];
            ByteBuffer y=ByteBuffer.allocateDirect(width*height);
            ByteBuffer uv=ByteBuffer.allocateDirect(width*height/2);
            ByteBuffer v=uv.duplicate(); v.position(1);
            ByteBuffer[] planes={y,uv,v};
            int[] row={width,width,width},pixel={1,2,2};
            for(int i=0;i<6;i++) {
                if(stopping) return false;
                PhysioYuv420.fill(synthetic,width,height,flipRows,planes,row,pixel,lumaRows);
                warmupCalls++;
            }
            return !stopping;
        } finally { warmupNanos=System.nanoTime()-started; }
    }

    private int inputBuffer() {
        long deadline=System.nanoTime()+5_000_000_000L;
        while(System.nanoTime()<deadline) {
            long waitStarted=System.nanoTime();
            int index;
            try { index=codec.dequeueInputBuffer(10000); }
            finally { inputWaitNanos+=System.nanoTime()-waitStarted; inputWaitCalls++; }
            if(index>=0) return index;
            drain(false);
        }
        throw new IllegalStateException("Encoder input timed out");
    }

    private void writeFrame(Frame frame) {
        int index=inputBuffer();
        Image image=codec.getInputImage(index);
        if(image==null) throw new IllegalStateException("Encoder has no flexible YUV input image");
        Image.Plane[] planes=image.getPlanes();
        if(planes.length!=3) throw new IllegalStateException("Encoder YUV plane mismatch");
        ByteBuffer[] buffers={planes[0].getBuffer(),planes[1].getBuffer(),planes[2].getBuffer()};
        int[] row={planes[0].getRowStride(),planes[1].getRowStride(),planes[2].getRowStride()};
        int[] pixel={planes[0].getPixelStride(),planes[1].getPixelStride(),planes[2].getPixelStride()};
        long conversionStarted=System.nanoTime();
        try { PhysioYuv420.fill(frame.pixels,width,height,flipRows,buffers,row,pixel,lumaRows); }
        finally {
            long elapsed=System.nanoTime()-conversionStarted;
            conversionNanos+=elapsed; maxConversionNanos=Math.max(maxConversionNanos,elapsed); conversionCalls++;
        }
        // Flexible input buffers may have padded row/slice strides. Queue their actual capacity.
        ByteBuffer buffer=codec.getInputBuffer(index);
        if(buffer==null) throw new IllegalStateException("Encoder has no input buffer");
        submitted.add(frame.pts);
        codec.queueInputBuffer(index,0,buffer.capacity(),frame.pts,0);
    }

    private void drain(boolean untilEnd) {
        long started=System.nanoTime();
        try { drainOutput(untilEnd); }
        finally { drainNanos+=System.nanoTime()-started; drainCalls++; }
    }

    private void drainOutput(boolean untilEnd) {
        MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
        long deadline=System.nanoTime()+5_000_000_000L;
        while(true) {
            int index=codec.dequeueOutputBuffer(info,untilEnd?10000:0);
            if(index==MediaCodec.INFO_TRY_AGAIN_LATER) {
                if(!untilEnd) return;
                if(System.nanoTime()>deadline) throw new IllegalStateException("Encoder output timed out");
                continue;
            }
            if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                if(track>=0) throw new IllegalStateException("Encoder changed format during capture");
                track=muxer.addTrack(codec.getOutputFormat()); muxer.start(); continue;
            }
            if(index<0) continue;
            if(info.size>0 && (info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)==0) {
                if(track<0 || encoded.size()>=submitted.size() || info.presentationTimeUs!=submitted.get(encoded.size()))
                    throw new IllegalStateException("Encoded frame timestamp differs from its source image");
                ByteBuffer bytes=codec.getOutputBuffer(index);
                if(bytes==null) throw new IllegalStateException("Encoder output missing");
                bytes.position(info.offset);bytes.limit(info.offset+info.size);
                muxer.writeSampleData(track,bytes,info);encoded.add(info.presentationTimeUs);
            }
            boolean end=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
            codec.releaseOutputBuffer(index,false);
            if(end) return;
        }
    }

    private void verifyMuxed() throws java.io.IOException {
        MediaExtractor extractor=new MediaExtractor();
        try {
            extractor.setDataSource(path);
            if(extractor.getTrackCount()!=1) throw new IllegalStateException("Unexpected recording tracks");
            extractor.selectTrack(0);
            long[] times=new long[encoded.size()];int index=0;
            while(extractor.getSampleTime()>=0) {
                long time=extractor.getSampleTime();
                // Mux timescale can quantize input PTS. Retain the final actual PTS, not a guessed constant offset.
                if(index>=times.length || Math.abs(time-encoded.get(index))>100 || (index>0 && time<=times[index-1]))
                    throw new IllegalStateException("Muxed frame timestamp cannot be mapped to source image");
                times[index++]=time;extractor.advance();
            }
            if(index!=times.length) throw new IllegalStateException("Muxed file omitted encoded images");
            presentationTimes=times;
        } finally { extractor.release(); }
    }
}
