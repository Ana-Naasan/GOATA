import com.hth.capture.PhysioYuv420;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.Random;
final class CaptureYuvChecks {
  private static final class Layout {
    final ByteBuffer[] backing, planes; final int[] row,pixel,positions,limits;
    Layout(int w,int h,boolean direct,int layout,int yp,int pad,int offset) {
      row=new int[]{w*yp+pad,(w/2)*(layout==0?1:2)+pad,(w/2)*(layout==0?1:2)+pad};
      pixel=new int[]{yp,layout==0?1:2,layout==0?1:2};
      ByteBuffer y=buffer(offset+row[0]*h+8,direct);
      ByteBuffer u=buffer(offset+row[1]*(h/2)+8,direct);
      ByteBuffer v=layout>=2?u:buffer(offset+row[2]*(h/2)+8,direct);
      backing=layout>=2?new ByteBuffer[]{y,u}:new ByteBuffer[]{y,u,v};
      int ub=offset+(layout==3?1:0),vb=offset+(layout==2?1:0);
      planes=new ByteBuffer[]{view(y,offset,offset+(h-1)*row[0]+(w-1)*yp+1),view(u,ub,ub+(h/2-1)*row[1]+(w/2-1)*pixel[1]+1),view(v,vb,vb+(h/2-1)*row[2]+(w/2-1)*pixel[2]+1)};
      positions=Arrays.stream(planes).mapToInt(ByteBuffer::position).toArray();
      limits=Arrays.stream(planes).mapToInt(ByteBuffer::limit).toArray();
    }
    static ByteBuffer buffer(int n,boolean direct) {ByteBuffer b=direct?ByteBuffer.allocateDirect(n):ByteBuffer.allocate(n);for(int i=0;i<n;i++)b.put(i,(byte)0xA7);return b;}
    static ByteBuffer view(ByteBuffer b,int p,int l) {ByteBuffer v=b.duplicate();v.limit(l);v.position(p);return v;}
    void unchanged(){for(int i=0;i<3;i++)if(planes[i].position()!=positions[i]||planes[i].limit()!=limits[i])throw new AssertionError("plane cursor changed");}
  }
  static byte[] bytes(ByteBuffer b){ByteBuffer c=b.duplicate();c.clear();byte[] a=new byte[c.remaining()];c.get(a);return a;}
  public static void main(String[] args){Random random=new Random(0x485448);int checks=0;
    for(boolean direct:new boolean[]{false,true})for(boolean flip:new boolean[]{false,true})for(int layout=0;layout<4;layout++)for(int yp=1;yp<=2;yp++)for(int repeat=0;repeat<50;repeat++){
      int w=2+2*random.nextInt(24),h=2+2*random.nextInt(20),pad=2*random.nextInt(5),offset=1+random.nextInt(6);
      byte[] rgba=new byte[w*h*4];random.nextBytes(rgba);
      Layout scalar=new Layout(w,h,direct,layout,yp,pad,offset),bulk=new Layout(w,h,direct,layout,yp,pad,offset);
      fillScalarReference(rgba,w,h,flip,scalar.planes,scalar.row,scalar.pixel);
      PhysioYuv420.fill(rgba,w,h,flip,bulk.planes,bulk.row,bulk.pixel,new byte[w*2]);
      scalar.unchanged();bulk.unchanged();for(int i=0;i<scalar.backing.length;i++)if(!Arrays.equals(bytes(scalar.backing[i]),bytes(bulk.backing[i])))throw new AssertionError("mismatch layout="+layout+" yp="+yp+" direct="+direct+" flip="+flip);checks++;
    }
    // A previously warmed scratch array must not contribute pixels to the next real frame.
    byte[] reusedScratch=new byte[16];
    Layout warmed=new Layout(8,8,true,2,1,0,0);
    for(int i=0;i<6;i++)PhysioYuv420.fill(new byte[8*8*4],8,8,false,warmed.planes,warmed.row,warmed.pixel,reusedScratch);
    byte[] nextRgba=new byte[8*8*4];random.nextBytes(nextRgba);
    Layout reference=new Layout(8,8,true,2,1,0,0),next=new Layout(8,8,true,2,1,0,0);
    fillScalarReference(nextRgba,8,8,false,reference.planes,reference.row,reference.pixel);
    PhysioYuv420.fill(nextRgba,8,8,false,next.planes,next.row,next.pixel,reusedScratch);
    for(int i=0;i<reference.backing.length;i++)if(!Arrays.equals(bytes(reference.backing[i]),bytes(next.backing[i])))throw new AssertionError("warmup scratch leaked into next frame");
    System.out.println("PASS warmed scratch does not leak synthetic pixels into next frame");
    Layout shortScratch=new Layout(4,4,true,2,1,2,3);
    byte[][] untouched=Arrays.stream(shortScratch.backing).map(CaptureYuvChecks::bytes).toArray(byte[][]::new);
    boolean scratchThrew=false;
    try {PhysioYuv420.fill(new byte[4*4*4],4,4,false,shortScratch.planes,shortScratch.row,shortScratch.pixel,new byte[7]);}
    catch(IllegalArgumentException expected){scratchThrew=true;}
    if(!scratchThrew)throw new AssertionError("short scratch accepted");
    shortScratch.unchanged();
    for(int i=0;i<untouched.length;i++)if(!Arrays.equals(untouched[i],bytes(shortScratch.backing[i])))throw new AssertionError("short scratch wrote output");
    System.out.println("PASS short scratch rejected before any buffer/cursor changes");
    Layout shortY=new Layout(4,4,true,2,1,2,3);
    shortY.planes[0].limit(shortY.positions[0]+shortY.row[0]+2);
    boolean threw=false;
    try {PhysioYuv420.fill(new byte[4*4*4],4,4,false,shortY.planes,shortY.row,shortY.pixel,new byte[8]);}
    catch(java.nio.BufferOverflowException expected){threw=true;}
    if(!threw||shortY.planes[0].position()!=shortY.positions[0])throw new AssertionError("short Y limit must throw and restore position");
    System.out.println("PASS short Y limit throws and restores original position");
    System.out.println("PASS randomized exact scalar/bulk parity "+checks+" layouts; shared UV/VU, heap/direct, flip, pixel/row strides, positions, limits and untouched bytes");
  }

    // Frozen scalar implementation: compare complete backing bytes, including untouched padding.
    private static void fillScalarReference(byte[] rgba,int width,int height,boolean flip,ByteBuffer[] planes,int[] row,int[] pixel) {
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
