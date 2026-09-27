package com.hth.capture;

import java.nio.ByteBuffer;

/** RGBA to limited-range BT.601 with 2x2 chroma averaging and explicit row order. */
public final class PhysioYuv420 {
    private PhysioYuv420() { }
    public static void fill(byte[] rgba,int width,int height,boolean flip,ByteBuffer[] planes,int[] row,int[] pixel,byte[] lumaRows) {
        if(lumaRows.length<width*2) throw new IllegalArgumentException("Luma scratch too small");
        int[] base={planes[0].position(),planes[1].position(),planes[2].position()};
        try {
        // Only Y is bulk-written: U/V may share interleaved backing storage.
        for(int y=0;y<height;y+=2) {
          for(int x=0;x<width;x+=2) {
            int rr=0,gg=0,bb=0;
            for(int dy=0;dy<2;dy++) for(int dx=0;dx<2;dx++) {
                int offset=((flip?height-1-y-dy:y+dy)*width+x+dx)*4;
                int r=rgba[offset]&255,g=rgba[offset+1]&255,b=rgba[offset+2]&255;
                rr+=r;gg+=g;bb+=b;
                byte luma=(byte)(((66*r+129*g+25*b+128)>>8)+16);
                if(pixel[0]==1) lumaRows[dy*width+x+dx]=luma;
                else planes[0].put(base[0]+(y+dy)*row[0]+(x+dx)*pixel[0],luma);
            }
            rr/=4;gg/=4;bb/=4;
            planes[1].put(base[1]+y/2*row[1]+x/2*pixel[1],(byte)(((-38*rr-74*gg+112*bb+128)>>8)+128));
            planes[2].put(base[2]+y/2*row[2]+x/2*pixel[2],(byte)(((112*rr-94*gg-18*bb+128)>>8)+128));
          }
          if(pixel[0]==1) {
              planes[0].position(base[0]+y*row[0]);planes[0].put(lumaRows,0,width);
              planes[0].position(base[0]+(y+1)*row[0]);planes[0].put(lumaRows,width,width);
          }
        }
        } finally { planes[0].position(base[0]); }
    }
}
