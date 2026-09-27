using System;
using System.IO;
using UnityEngine;

namespace Physio.Capture
{
    public sealed partial class QuestTakeRecorder
    {
        Texture2D syntheticTexture;
        double syntheticStartedAt=-1;
        const int SyntheticFrameCount=90;

        void Start()
        {
#if DEVELOPMENT_BUILD && UNITY_ANDROID && !UNITY_EDITOR
            using(var player=new AndroidJavaClass("com.unity3d.player.UnityPlayer"))
            using(var activity=player.GetStatic<AndroidJavaObject>("currentActivity"))
            using(var intent=activity.Call<AndroidJavaObject>("getIntent"))
                if(intent.Call<bool>("getBooleanExtra","physio_capture_benchmark",false))
                    Invoke(nameof(StartSyntheticBenchmark),5f);
#endif
        }

        // Explicit development-build intent only. No camera, patient profile, or clinical evidence is created.
        void StartSyntheticBenchmark()
        {
            // Allow the XR rig and UI to finish their cold startup before measuring sustained capture.
            if(IsPreparing || IsRecording || IsFinalizing || frames.Count>0 || LastCapture!=null)
            { Debug.LogWarning("PHYSIO_CAPTURE_BENCHMARK: skipped because this launch has capture activity");return; }
            if(!SystemInfo.supportsAsyncGPUReadback) { Debug.LogError("PHYSIO_CAPTURE_BENCHMARK: GPU readback unavailable");return; }
            try {
                syntheticBenchmark=true;width=1280;height=960;targetDurationNs=3_000_000_000;TargetDurationSeconds=3;
                take=Guid.NewGuid().ToString();directory=Path.Combine(Application.temporaryCachePath,"synthetic-capture-benchmark",take);
                Directory.CreateDirectory(directory);
                syntheticTexture=new Texture2D(width,height,TextureFormat.RGBA32,false);
                var pixels=new Color32[width*height];
                for(int y=0;y<height;y++) for(int x=0;x<width;x++)
                    pixels[y*width+x]=x<16?new Color32(0,255,0,255):y<height/2?new Color32(255,0,0,255):new Color32(0,0,255,255);
                syntheticTexture.SetPixels32(pixels);syntheticTexture.Apply(false,true);
                OpenEncoder();deadline=Time.realtimeSinceStartupAsDouble+10;
                Debug.Log("PHYSIO_CAPTURE_BENCHMARK: synthetic GPU texture, 1280x960, 30fps, 90 frames; camera never opened");
            } catch(Exception failure) {
                Debug.LogException(failure);
                Fail("Synthetic recording check could not start. Normal capture remains available.");
            }
        }

        void UpdateSyntheticBenchmark()
        {
            if(encoder==null || encoderFinishing) return;
            if(encoder.Call<bool>("isDone")) { Fail(encoder.Call<string>("getError"));return; }
            if(!encoder.Call<bool>("isReady")) {
                if(Time.realtimeSinceStartupAsDouble>deadline) Fail("Synthetic encoder did not start.");
                return;
            }
            if(syntheticStartedAt<0) { syntheticStartedAt=Time.realtimeSinceStartupAsDouble;originNs=0;IsRecording=true; }
            int available=(int)Math.Floor((Time.realtimeSinceStartupAsDouble-syntheticStartedAt)*30);
            if(available>=SyntheticFrameCount) { StopTake();return; }
            if(available<observedFrames) return;
            while(observedFrames<available) { int skipped=observedFrames++;RecordMiss(skipped,skipped*1_000_000_000L/30,"diagnostic_render_missed"); }
            int id=observedFrames++;long ns=id*1_000_000_000L/30;
            RequestImage(syntheticTexture,id,ns);
        }

        void FinishSyntheticBenchmark(long[] times)
        {
            Debug.Log(FormattableString.Invariant($"PHYSIO_CAPTURE_BENCHMARK: mux_verified=true expected_frames={SyntheticFrameCount} encoded_frames={times.Length} missed_frames={missedTimes.Count} complete_without_drops={times.Length==SyntheticFrameCount && missedTimes.Count==0}"));
            encoder.Dispose();encoder=null;readbacks=null;IsFinalizing=false;IsRecording=false;
            syntheticBenchmark=false;
            if(syntheticTexture!=null) Destroy(syntheticTexture);
        }
    }
}
