using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading.Tasks;
using Meta.XR;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Android;
using UnityEngine.Rendering;

namespace Physio.Capture
{
    /// <summary>One original take at a time. All retakes get new folders and identifiers.</summary>
    public sealed class QuestTakeRecorder : MonoBehaviour
    {
        const string CameraPermission="horizonos.permission.HEADSET_CAMERA";
        public bool IsRecording { get; private set; }
        public bool IsFinalizing { get; private set; }
        public bool IsPreparing => waitingForCamera || countingDown || waitingForEncoder;
        public string Status { get; private set; }="Ready to record a consenting participant.";
        public string Error { get; private set; }="";
        public CompletedCapture LastCapture { get; private set; }
        public Texture PreviewTexture => cameraAccess!=null && cameraAccess.IsPlaying ? cameraAccess.GetTexture() : null;
        public double DurationSeconds => frames.Count<2?0:(frames[frames.Count-1].SourceNanoseconds-frames[0].SourceNanoseconds)/1e9;
        public int FrameCount => frames.Count;

        PassthroughCameraAccess cameraAccess;
        AndroidJavaObject encoder;
        PermissionCallbacks permissionCallbacks;
        Task<CompletedCapture> saving;
        readonly List<CapturedFrame> frames=new List<CapturedFrame>();
        readonly List<long> missedTimes=new List<long>();
        string patient,session,test,view,side,take,directory;
        StreamWriter journal;
        bool waitingForCamera,requestingPermission,countingDown,waitingForEncoder,pendingReadback,stopping,interrupted,encoderFinishing,isMicroscopeHold;
        double deadline;
        long originNs=-1,lastObserved=-1,captureCompletedTicks;
        int observedFrames,width,height,generation;
        double[] intrinsics;

        void OnEnable() { OVRManager.InputFocusLost+=LostFocus; }
        void OnDisable() { OVRManager.InputFocusLost-=LostFocus; LostFocus(); }
        bool HasCaptureFocus => Application.isFocused && OVRManager.hasInputFocus;

        public void BeginTake(string patientId,string sessionId,string testType,string captureView="front",string captureSide="not_applicable",bool microscopeHold=false)
        {
            if(IsRecording || IsPreparing || IsFinalizing) { Error="Finish the current take first."; return; }
            try { CaptureBundle.ValidateIdentity(patientId,sessionId,testType,captureView,captureSide); }
            catch(ArgumentException failure) { Error=failure.Message; return; }
            patient=patientId;session=sessionId;test=testType;view=captureView;side=captureSide;
            isMicroscopeHold=microscopeHold;
            LastCapture=null;Error="";interrupted=false;stopping=false;encoderFinishing=false;
            frames.Clear();missedTimes.Clear();originNs=-1;lastObserved=-1;observedFrames=0;generation++;
#if UNITY_ANDROID && !UNITY_EDITOR
            if(!SystemInfo.supportsAsyncGPUReadback) { Fail("This graphics configuration cannot read camera images."); return; }
            if(!PassthroughCameraAccess.IsSupported) { Fail("Camera capture requires supported Quest 3 camera access."); return; }
            if(!Permission.HasUserAuthorizedPermission(CameraPermission)) {
                Status="Allow headset camera access to record this test.";
                waitingForCamera=requestingPermission=true;deadline=Time.realtimeSinceStartupAsDouble+60;
                int permissionGeneration=generation;
                permissionCallbacks=new PermissionCallbacks();
                permissionCallbacks.PermissionGranted+=_=> { if(permissionGeneration==generation && waitingForCamera) EnableCamera(); };
                permissionCallbacks.PermissionDenied+=_=> { if(permissionGeneration==generation && waitingForCamera) Fail("Camera permission denied. Allow headset camera access in Settings, then retry."); };
                Permission.RequestUserPermission(CameraPermission,permissionCallbacks);
                return;
            }
            EnableCamera();
#else
            Fail("Real recording is available on the Quest headset.");
#endif
        }

        void EnableCamera()
        {
            if(!Permission.HasUserAuthorizedPermission(CameraPermission)) return;
            requestingPermission=false;
            if(cameraAccess==null) {
                // The scene has one recorder and one left-camera owner.
                cameraAccess=gameObject.AddComponent<PassthroughCameraAccess>();
                cameraAccess.enabled=false;
                cameraAccess.CameraPosition=PassthroughCameraAccess.CameraPositionType.Left;
                cameraAccess.RequestedResolution=new Vector2Int(1280,960);
                cameraAccess.MaxFramerate=30;
            }
            cameraAccess.enabled=true;waitingForCamera=true;
            deadline=Time.realtimeSinceStartupAsDouble+12;
            Status=isMicroscopeHold?"Opening camera. Frame the region and hold the headset steady for a separate motion-microscope recording.":"Opening camera. Keep the participant and required region visible.";
        }

        void Update()
        {
            if(saving!=null) { CheckSaved(); return; }
            if(IsFinalizing) { CheckFinalized(); return; }
            if(waitingForCamera) {
                if(cameraAccess!=null && cameraAccess.IsPlaying && HasCaptureFocus) {
                    waitingForCamera=false;countingDown=true;deadline=Time.realtimeSinceStartupAsDouble+3;
                } else if(Time.realtimeSinceStartupAsDouble>deadline) Fail("Camera did not start. Check permission and retry.");
                return;
            }
            if(countingDown) {
                if(!HasCaptureFocus) { LostFocus();return; }
                double left=deadline-Time.realtimeSinceStartupAsDouble;
                Status="Recording starts in "+Math.Max(0,(int)Math.Ceiling(left))+". Keep the headset steady.";
                if(left<=0) { countingDown=false;StartEncoder(); }
                return;
            }
            if(waitingForEncoder) {
                if(!HasCaptureFocus) { LostFocus();return; }
                if(encoder.Call<bool>("isDone")) { Fail(encoder.Call<string>("getError")); return; }
                if(encoder.Call<bool>("isReady")) { waitingForEncoder=false;IsRecording=true;Status=isMicroscopeHold?"Recording separate steady-hold evidence. Keep the headset and framing steady.":"Recording. Keep the full required region visible.";deadline=Time.realtimeSinceStartupAsDouble+22; }
                else if(Time.realtimeSinceStartupAsDouble>deadline) Fail("Recording encoder did not start.");
                return;
            }
            if(!IsRecording) return;
            if(!HasCaptureFocus) { LostFocus();return; }
            if(!Permission.HasUserAuthorizedPermission(CameraPermission) || !cameraAccess.enabled) { Interrupt("Camera access was lost. Retake required."); return; }
            if(encoder.Call<bool>("isDone")) { Interrupt(encoder.Call<string>("getError")); return; }
            if(Time.realtimeSinceStartupAsDouble>deadline) { Interrupt("Camera stopped delivering frames. Retake required."); return; }
            if(!cameraAccess.IsUpdatedThisFrame) return;
            CaptureCurrentImage();
        }

        void StartEncoder()
        {
            try {
                take=Guid.NewGuid().ToString();
                directory=Path.Combine(Application.persistentDataPath,"recordings",patient,session,take);
                Directory.CreateDirectory(directory);
                var size=cameraAccess.CurrentResolution;width=size.x;height=size.y;
                var k=cameraAccess.Intrinsics;
                intrinsics=CaptureBundle.ScaleIntrinsics(k.SensorResolution.x,k.SensorResolution.y,width,height,
                    k.FocalLength.x,k.FocalLength.y,k.PrincipalPoint.x,k.PrincipalPoint.y);
                journal=new StreamWriter(new FileStream(Path.Combine(directory,"source-frames.csv"),FileMode.CreateNew));
                journal.WriteLine("frame_id,source_pts_ns,state");journal.Flush();
                // GPU readback preserves graphics API row order. Android Vulkan starts at the top; OpenGL starts at the bottom.
                encoder=new AndroidJavaObject("com.hth.capture.PhysioMp4Recorder",Path.Combine(directory,take+".mp4"),width,height,!SystemInfo.graphicsUVStartsAtTop);
                waitingForEncoder=true;deadline=Time.realtimeSinceStartupAsDouble+8;Status="Preparing video encoder.";
            } catch(Exception failure) { Debug.LogException(failure);Fail("Recording could not start. Check available device storage."); }
        }

        void CaptureCurrentImage()
        {
            long ns=checked((cameraAccess.Timestamp.Ticks-DateTime.UnixEpoch.Ticks)*100L);
            if(ns==lastObserved) return;
            if(ns<lastObserved) { Interrupt("Camera timestamps moved backwards. Retake required."); return; }
            if(lastObserved>=0 && ns-lastObserved>100_000_000) interrupted=true;
            lastObserved=ns;int id=observedFrames++;
            if(originNs>=0 && (ns-originNs>CaptureBundle.MaximumDurationNs || frames.Count>=CaptureBundle.MaximumFrames)) { StopTake(); return; }
            if(pendingReadback) { RecordMiss(id,ns,"readback_busy"); return; }
            if(originNs<0) originNs=ns;
            int requestGeneration=generation;
            pendingReadback=true;
            AsyncGPUReadback.Request(cameraAccess.GetTexture(),0,TextureFormat.RGBA32,request=> {
                if(requestGeneration!=generation) return;
                pendingReadback=false;
                try {
                    if(encoderFinishing) return;
                    if(request.hasError) { RecordMiss(id,ns,"readback_failed");Interrupt("Camera image transfer failed. Retake required.");return; }
                    byte[] rgba=request.GetData<byte>().ToArray();
                    bool accepted=encoder.Call<bool>("submit",rgba,(ns-originNs)/1000);
                    if(accepted) { frames.Add(new CapturedFrame(id,ns));WriteJournal(id,ns,"encoded_input"); }
                    else RecordMiss(id,ns,"encoder_busy");
                } catch(Exception failure) { Debug.LogException(failure);Interrupt("Camera recording failed. Original files have been kept."); }
                finally { if(stopping && !encoderFinishing) FinishEncoder(); }
            });
        }

        void RecordMiss(int id,long ns,string reason)
        {
            missedTimes.Add(ns);WriteJournal(id,ns,reason);
            Status="A camera frame was missed. Complete this take, then retake if quality is insufficient.";
        }

        void WriteJournal(int id,long ns,string state)
        { journal.WriteLine(id.ToString(CultureInfo.InvariantCulture)+","+ns.ToString(CultureInfo.InvariantCulture)+","+state);journal.Flush(); }

        public void StopTake()
        {
            if(IsPreparing) { waitingForCamera=countingDown=waitingForEncoder=false;Fail("Recording cancelled before capture.");return; }
            if(!IsRecording) return;
            captureCompletedTicks=System.Diagnostics.Stopwatch.GetTimestamp();
            IsRecording=false;stopping=true;IsFinalizing=true;Status="Saving original recording and verifying video timestamps.";
            if(!pendingReadback) FinishEncoder();
        }

        void FinishEncoder()
        {
            encoderFinishing=true;encoder?.Call("finish");journal?.Dispose();journal=null;
            deadline=Time.realtimeSinceStartupAsDouble+20;
        }

        void CheckFinalized()
        {
            if(!encoderFinishing) return;
            if(!encoder.Call<bool>("isDone")) {
                if(Time.realtimeSinceStartupAsDouble>deadline) Fail("Video finalization timed out. Original files have been kept; retake required.");
                return;
            }
            string encoderError=encoder.Call<string>("getError");
            if(!string.IsNullOrEmpty(encoderError)) { Fail(encoderError);return; }
            try {
                long[] times=encoder.Call<long[]>("getPresentationTimes");
                var metadata=CaptureBundle.Sidecar(take,width,height,frames,times,view,isMicroscopeHold?"steady_hold":test=="barefoot"?"standing":"seated",side,
                    interrupted,intrinsics[0],intrinsics[1],intrinsics[2],intrinsics[3],missedTimes);
                bool gaps=((JArray)metadata["capture"]["gaps"]).Count>0 || missedTimes.Count>0;
                if(gaps) { metadata["capture"]["interrupted"]=true;Error="Some camera frames were missed. Retake before processing."; }
                encoder.Dispose();encoder=null;
                // Hashing/zipping never blocks headset rendering. The completed bundle is published only on success.
                saving=Task.Run(()=>CaptureBundle.Save(directory,patient,session,test,metadata,captureCompletedTicks,isMicroscopeHold));
            } catch(Exception failure) { Debug.LogException(failure);Fail("Recording metadata could not be verified. Original files have been kept; retake required."); }
        }

        void CheckSaved()
        {
            if(!saving.IsCompleted) return;
            if(saving.IsFaulted) { Debug.LogException(saving.Exception);saving=null;Fail("Recording could not be saved. Check storage; original files have been kept.");return; }
            LastCapture=saving.Result;saving=null;IsFinalizing=false;
            if(cameraAccess!=null) cameraAccess.enabled=false;
            Status=LastCapture.Interrupted?"Interrupted capture saved. Retake required.":isMicroscopeHold?"Steady-hold recording saved. Combine with the original test before processing.":"Capture saved. Ready for processing.";
        }

        void Interrupt(string reason)
        { interrupted=true;Error=reason;StopTake(); }

        void Fail(string message)
        {
            Error=string.IsNullOrEmpty(message)?"Capture failed. Retake required.":message;Status=Error;
            waitingForCamera=requestingPermission=countingDown=waitingForEncoder=IsRecording=IsFinalizing=false;
            encoder?.Call("finish");encoder?.Dispose();encoder=null;journal?.Dispose();journal=null;generation++;pendingReadback=false;
            if(cameraAccess!=null) cameraAccess.enabled=false;
        }

        void OnApplicationPause(bool paused)
        {
            if(paused && IsRecording) { Interrupt("Headset capture was interrupted. Retake required.");if(!encoderFinishing) FinishEncoder(); }
            else if(paused && IsPreparing) Fail("Capture was interrupted before recording. Try again.");
        }
        void OnApplicationFocus(bool focused) { if(!focused) LostFocus(); }
        void LostFocus()
        {
            if(IsRecording) { Interrupt("Headset focus was lost. Retake required.");if(!encoderFinishing) FinishEncoder(); }
            else if(countingDown || waitingForEncoder || (waitingForCamera && !requestingPermission)) Fail("Capture was interrupted before recording. Try again.");
        }
        void OnDestroy() { generation++;encoder?.Call("finish");encoder?.Dispose();journal?.Dispose(); }
    }
}
