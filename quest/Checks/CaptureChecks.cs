using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Physio.Capture;

static class CaptureChecks
{
    static int count;
    static void Check(bool ok) { count++; if (!ok) throw new Exception("Capture check " + count); }
    static void Reject(Action action) { try { action(); } catch (ArgumentException) { count++; return; } throw new Exception("Expected rejection"); }
    static void Main(string[] args)
    {
        var root = Path.Combine(Path.GetTempPath(), "capture-check-" + Guid.NewGuid());
        Directory.CreateDirectory(root);
        try
        {
            var patient = Guid.NewGuid().ToString(); var session = Guid.NewGuid().ToString();
            var take = Guid.NewGuid().ToString();
            var frames = new[] { new CapturedFrame(0, 1790472000123456000), new CapturedFrame(2, 1790472000156789000) };
            var metadata = CaptureBundle.Sidecar(take, 640, 480, frames, new long[] {0,33333}, "front", "seated", "not_applicable", false, 500, 510, 320, 240, new long[] {1790472000140000000});
            Check((string)metadata["frames"][1]["pts_ns"] == "1790472000156789000");
            Check((int)metadata["frames"][1]["frame_id"] == 2);
            Check(metadata["capture"]["gaps"].Count() == 1);
            Check((string)metadata["media"]["presentation_time_us"][1] == "33333");
            Check((string)metadata["camera"]["distortion_model"] == "unknown");
            Check(metadata["camera"]["distortion_coefficients"] is JArray distortion && distortion.Count == 0);
            Check((double)metadata["camera"]["intrinsics"]["fy"] == 510);
            Check(metadata["frames"][0]["camera_pose"] == null);
            Reject(() => CaptureBundle.Sidecar(take,640,480,frames,new long[] {0,0},"front","seated","not_applicable",false,500,500,320,240,Array.Empty<long>()));
            Reject(() => CaptureBundle.Sidecar(take,640,480,frames,new long[] {0},"front","seated","not_applicable",false,500,500,320,240,Array.Empty<long>()));
            Reject(() => CaptureBundle.ValidateIdentity("../escape",session,"elk","front","not_applicable"));
            Reject(() => CaptureBundle.ValidateIdentity(patient,session,"walking","front","not_applicable"));
            Reject(() => CaptureBundle.ValidateIdentity(patient,session,"barefoot","front","not_applicable"));
            Reject(() => CaptureBundle.Sidecar(take,640,480,frames,new long[] {0,33333},"front","seated","not_applicable",false,double.NaN,500,320,240,Array.Empty<long>()));
            Reject(() => CaptureBundle.ValidateIdentity(patient,"bad","elk","front","left"));
            Reject(() => CaptureBundle.ValidateIdentity(patient,session,"elk","bad","left"));
            Reject(() => CaptureBundle.ValidateIdentity(patient,session,"elk","front","bad"));
            CaptureBundle.ValidateIdentity(patient,session,"barefoot","medial","left");
            CaptureBundle.ValidateIdentity(patient,session,"barefoot","medial","right");
            Reject(() => CaptureBundle.ScaleIntrinsics(0,960,640,480,1,1,1,1));
            JObject Make(CapturedFrame[] f,long[] pts,int w=640,int h=480,double fx=500,double fy=500) =>
                CaptureBundle.Sidecar(take,w,h,f,pts,"front","seated","not_applicable",false,fx,fy,320,240,Array.Empty<long>());
            Reject(() => Make(Array.Empty<CapturedFrame>(),Array.Empty<long>()));
            Reject(() => Make(frames,new long[]{0,33333},31));
            Reject(() => Make(frames,new long[]{0,33333},640,31));
            Reject(() => Make(frames,new long[]{0,33333},641));
            Reject(() => Make(frames,new long[]{0,33333},640,481));
            Reject(() => Make(frames,new long[]{0,33333},4000,4000));
            Reject(() => Make(frames,new long[]{0,33333},fx:0));
            Reject(() => Make(frames,new long[]{0,33333},fy:0));
            Reject(() => Make(frames,new long[]{0,33333},fx:double.PositiveInfinity));
            Reject(() => Make(new[]{new CapturedFrame(-1,0),new CapturedFrame(1,33333000)},new long[]{0,33333}));
            Reject(() => Make(new[]{new CapturedFrame(0,-1),new CapturedFrame(1,33333000)},new long[]{0,33333}));
            Reject(() => Make(new[]{new CapturedFrame(0,0),new CapturedFrame(0,33333000)},new long[]{0,33333}));
            Reject(() => Make(new[]{new CapturedFrame(0,0),new CapturedFrame(1,0)},new long[]{0,33333}));
            Reject(() => Make(frames,new long[]{-1,33333}));
            Reject(() => Make(new[]{new CapturedFrame(0,0),new CapturedFrame(1,20_000_000_000)},new long[]{0,20_000_000}));
            var longGap=Make(new[]{new CapturedFrame(0,0),new CapturedFrame(1,200_000_000)},new long[]{0,200_000});
            Check(longGap["capture"]["gaps"].Count()==1);
            Check(Make(frames,new long[]{0,33333})["capture"]["gaps"].Count()==0);
            Reject(() => CaptureBundle.Save(root,patient,session,"elk",metadata));
            File.WriteAllBytes(Path.Combine(root,take+".mp4"),new byte[]{0,0,0,8,102,116,121,112});
            var bundle = CaptureBundle.Save(root,patient,session,"elk",metadata);
            Check(File.Exists(bundle.ZipPath)); Check(bundle.TakeId == take); Check(!bundle.Interrupted);
            var manifest=JObject.Parse(bundle.ManifestJson);
            Check((string)manifest["replay_take_id"] == take);
            Check((string)manifest["patient_id"] == patient);
            Check(manifest["capture_completed_at"].Value<DateTime>()==DateTime.UnixEpoch.AddTicks(frames[1].SourceNanoseconds/100));
            Check((double)manifest["takes"][0]["duration_s"] > 0.033);
            Reject(() => CaptureBundle.Save(root,patient,session,"elk",metadata));
            var crop = CaptureBundle.ScaleIntrinsics(1280,960,640,480,1000,1020,640,480);
            Check(crop.SequenceEqual(new double[]{500,510,320,240}));
            var square=CaptureBundle.ScaleIntrinsics(1280,960,640,640,1000,1020,640,480);
            Check(Math.Abs(square[2]-320)<1e-9 && Math.Abs(square[3]-320)<1e-9);
            var footTake=Guid.NewGuid().ToString();
            File.WriteAllBytes(Path.Combine(root,footTake+".mp4"),new byte[]{0,0,0,8,102,116,121,112});
            var footMetadata=CaptureBundle.Sidecar(footTake,640,480,frames,new long[]{0,33333},"medial","standing","left",true,500,500,320,240,Array.Empty<long>());
            var footDir=Path.Combine(root,"foot");Directory.CreateDirectory(footDir);
            File.Move(Path.Combine(root,footTake+".mp4"),Path.Combine(footDir,footTake+".mp4"));
            var foot=CaptureBundle.Save(footDir,patient,session,"barefoot",footMetadata);
            Check(JObject.Parse(foot.ManifestJson)["replay_take_id"]==null && foot.Interrupted);
            var microscopeTake=Guid.NewGuid().ToString();
            var microscopeDir=Path.Combine(root,"microscope");Directory.CreateDirectory(microscopeDir);
            File.WriteAllBytes(Path.Combine(microscopeDir,microscopeTake+".mp4"),new byte[]{0,0,0,8,102,116,121,112});
            var microscopeMetadata=CaptureBundle.Sidecar(microscopeTake,640,480,frames,new long[]{0,33333},"front","steady_hold","not_applicable",false,500,500,320,240,Array.Empty<long>());
            Reject(() => CaptureBundle.Save(microscopeDir,patient,session,"elk",microscopeMetadata));
            Reject(() => CaptureBundle.Save(microscopeDir,patient,session,"elk",metadata,microscopeHold:true));
            var microscope=CaptureBundle.Save(microscopeDir,patient,session,"elk",microscopeMetadata,12345,microscopeHold:true);
            var microscopeManifest=JObject.Parse(microscope.ManifestJson);
            Check(microscopeManifest["replay_take_id"]==null);
            Check((string)microscopeManifest["takes"][0]["kind"]=="microscope");
            Check((string)microscopeManifest["takes"][0]["condition"]=="steady_hold");
            Check((string)microscopeManifest["test_type"]=="elk" && microscope.CaptureCompletedStopwatchTicks==12345);
            Reject(() => CaptureBundle.Sidecar(microscopeTake,640,480,frames,new long[]{0,33333},"front","unknown","not_applicable",false,500,500,320,240,Array.Empty<long>()));
            if(args.Length==1) File.WriteAllText(args[0],metadata.ToString());
            Console.WriteLine($"Capture checks passed: {count}");
        }
        finally { Directory.Delete(root,true); }
    }
}
