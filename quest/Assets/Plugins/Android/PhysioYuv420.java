package com.hth.capture;

import java.nio.ByteBuffer;

/** RGBA to limited-range BT.601 with 2x2 chroma averaging and explicit row order. */
public final class PhysioYuv420 {
    private PhysioYuv420() { }
    public static void fill(byte[] rgba,int width,int height,boolean flip,ByteBuffer[] planes,int[] row,int[] pixel,byte[] lumaRows) {
        if(lumaRows.length<width*2) throw new IllegalArgumentException("Luma scratch too small");
        if(pixel[0]!=1) { fillStrided(rgba,width,height,flip,planes,row,pixel);return; }
        ByteBuffer yp=planes[0],up=planes[1],vp=planes[2];
        int yBase=yp.position(),uBase=up.position(),vBase=vp.position();
        try {
            // Expand each 2x2 block once: avoid per-pixel flip/stride branches and row arithmetic.
            // U/V stay independent absolute writes because their native buffers can alias as UV or VU.
            for(int y=0;y<height;y+=2) {
                int top=(flip?height-1-y:y)*width*4;
                int bottom=(flip?height-2-y:y+1)*width*4;
                int ui=uBase+y/2*row[1],vi=vBase+y/2*row[2];
                for(int x=0;x<width;x+=2,top+=8,bottom+=8,ui+=pixel[1],vi+=pixel[2]) {
                    int r0=rgba[top]&255,g0=rgba[top+1]&255,b0=rgba[top+2]&255;
                    int r1=rgba[top+4]&255,g1=rgba[top+5]&255,b1=rgba[top+6]&255;
                    int r2=rgba[bottom]&255,g2=rgba[bottom+1]&255,b2=rgba[bottom+2]&255;
                    int r3=rgba[bottom+4]&255,g3=rgba[bottom+5]&255,b3=rgba[bottom+6]&255;
                    lumaRows[x]=(byte)(((66*r0+129*g0+25*b0+128)>>8)+16);
                    lumaRows[x+1]=(byte)(((66*r1+129*g1+25*b1+128)>>8)+16);
                    lumaRows[width+x]=(byte)(((66*r2+129*g2+25*b2+128)>>8)+16);
                    lumaRows[width+x+1]=(byte)(((66*r3+129*g3+25*b3+128)>>8)+16);
                    int rr=(r0+r1+r2+r3)/4,gg=(g0+g1+g2+g3)/4,bb=(b0+b1+b2+b3)/4;
                    up.put(ui,(byte)(((-38*rr-74*gg+112*bb+128)>>8)+128));
                    vp.put(vi,(byte)(((112*rr-94*gg-18*bb+128)>>8)+128));
                }
                yp.position(yBase+y*row[0]);yp.put(lumaRows,0,width);
                yp.position(yBase+(y+1)*row[0]);yp.put(lumaRows,width,width);
            }
        } finally { yp.position(yBase); }
    }

    private static void fillStrided(byte[] rgba,int width,int height,boolean flip,ByteBuffer[] planes,int[] row,int[] pixel) {
        int[] base={planes[0].position(),planes[1].position(),planes[2].position()};
        for(int y=0;y<height;y+=2) for(int x=0;x<width;x+=2) {
            int rr=0,gg=0,bb=0;
            for(int dy=0;dy<2;dy++) for(int dx=0;dx<2;dx++) {
                int offset=((flip?height-1-y-dy:y+dy)*width+x+dx)*4;
                int r=rgba[offset]&255,g=rgba[offset+1]&255,b=rgba[offset+2]&255;
                rr+=r;gg+=g;bb+=b;
                planes[0].put(base[0]+(y+dy)*row[0]+(x+dx)*pixel[0],(byte)(((66*r+129*g+25*b+128)>>8)+16));
            }
            rr/=4;gg/=4;bb/=4;
            planes[1].put(base[1]+y/2*row[1]+x/2*pixel[1],(byte)(((-38*rr-74*gg+112*bb+128)>>8)+128));
            planes[2].put(base[2]+y/2*row[2]+x/2*pixel[2],(byte)(((112*rr-94*gg-18*bb+128)>>8)+128));
        }
    }
}
