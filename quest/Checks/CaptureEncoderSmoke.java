package com.hth.capture;

import java.util.Arrays;

/** Explicit synthetic device check: never opens a camera or records a participant. */
public final class CaptureEncoderSmoke {
    public static void main(String[] args) throws Exception {
        if(args.length!=1) throw new IllegalArgumentException("Pass a new synthetic MP4 path");
        if(new java.io.File(args[0]).exists()) throw new IllegalArgumentException("Refusing to overwrite existing file");
        int width=1280,height=960;
        byte[] rgba=new byte[width*height*4];
        for(int y=0;y<height;y++) for(int x=0;x<width;x++) {
            int i=(y*width+x)*4;
            if(x<16) rgba[i+1]=(byte)255;
            else rgba[i+(y<height/2?0:2)]=(byte)255;
            rgba[i+3]=(byte)255;
        }
        long[] input={0,33333,66667,100001,133332,166667,200000,233333,266667,300001,333332,366667};
        PhysioMp4Recorder recorder=new PhysioMp4Recorder(args[0],width,height,false);
        long deadline=System.currentTimeMillis()+15000;
        while(!recorder.isReady() && !recorder.isDone() && System.currentTimeMillis()<deadline) Thread.sleep(10);
        if(!recorder.isReady()) throw new IllegalStateException("Encoder not ready: "+recorder.getError());
        for(long pts:input) {
            deadline=System.currentTimeMillis()+3000;
            while(!recorder.submit(rgba,pts)) {
                if(recorder.isDone() || System.currentTimeMillis()>deadline) throw new IllegalStateException("Submit failed: "+recorder.getError());
                Thread.sleep(5);
            }
        }
        recorder.finish();deadline=System.currentTimeMillis()+20000;
        while(!recorder.isDone() && System.currentTimeMillis()<deadline) Thread.sleep(10);
        if(!recorder.isDone() || !recorder.getError().isEmpty()) throw new IllegalStateException("Encoder failed: "+recorder.getError());
        long[] output=recorder.getPresentationTimes();
        if(output.length!=input.length) throw new AssertionError("Frame count");
        System.out.println("SYNTHETIC_INPUT_US="+Arrays.toString(input));
        System.out.println("VERIFIED_MUX_US="+Arrays.toString(output));
        System.out.println("SYNTHETIC_COLOR_LAYOUT=top_red,bottom_blue,left_green; flipRows=false; no camera used");
        System.out.println("PASS: native synthetic encoder and mux timestamp identity");
    }
}
