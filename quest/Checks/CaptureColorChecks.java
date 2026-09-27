import java.nio.ByteBuffer;
import com.hth.capture.PhysioYuv420;

final class CaptureColorChecks {
    public static void main(String[] args) {
        byte[] red={(byte)255,0,0,(byte)255,(byte)255,0,0,(byte)255,(byte)255,0,0,(byte)255,(byte)255,0,0,(byte)255};
        ByteBuffer[] planes={ByteBuffer.allocate(8),ByteBuffer.allocate(2),ByteBuffer.allocate(2)};
        PhysioYuv420.fill(red,2,2,false,planes,new int[]{4,2,2},new int[]{1,2,2});
        check((planes[0].get(0)&255)==82 && (planes[0].get(4)&255)==82,"red luma and padded rows");
        check((planes[1].get(0)&255)==90 && (planes[2].get(0)&255)==240,"red chroma");
        byte[] rows={0,0,0,0,0,0,0,0,(byte)255,(byte)255,(byte)255,0,(byte)255,(byte)255,(byte)255,0};
        PhysioYuv420.fill(rows,2,2,true,planes,new int[]{4,2,2},new int[]{1,2,2});
        check((planes[0].get(0)&255)==235 && (planes[0].get(4)&255)==16,"vertical flip");
        check((planes[1].get(0)&255)==128 && (planes[2].get(0)&255)==128,"neutral chroma");
        System.out.println("Capture color checks passed: 4");
    }
    private static void check(boolean value,String label) { if(!value) throw new AssertionError(label); }
}
