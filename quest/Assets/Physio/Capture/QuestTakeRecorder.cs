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
    public sealed partial class QuestTakeRecorder : MonoBehaviour
    {
        const string CameraPermission="horizonos.permission.HEADSET_CAMERA";
        public bool IsRecording { get; private set; }
        public bool IsFinalizing { get; private set; }
        public bool IsPreparing => waitingForCamera || countingDown || waitingForEncoder || (syntheticBenchmark && !IsRecording && encoder!=null);
        public bool IsPreviewing => previewReady;
        public string Status { get; private set; }="Ready to record a consenting participant.";
        public string Error { get; private set; }="";
        public CompletedCapture LastCapture { get; private set; }
        public Texture PreviewTexture => cameraAccess!=null && cameraAccess.IsPlaying ? cameraAccess.GetTexture() : null;
        public double DurationSeconds => frames.Count<2?0:(frames[frames.Count-1].SourceNanoseconds-frames[0].SourceNanoseconds)/1e9;
        public int FrameCount => frames.Count;
        public double TargetDurationSeconds { get; private set; }=10;
        public double RemainingSeconds => Math.Max(0,TargetDurationSeconds-DurationSeconds);
        public int CountdownSeconds => countingDown ? Math.Max(0, (int)Math.Ceiling(deadline-Time.realtimeSinceStartupAsDouble)) : 0;
        public bool IsCountingDown => countingDown;

        PassthroughCameraAccess cameraAccess;
        AndroidJavaObject encoder;
        IntPtr submitMethod;
        CaptureReadbacks readbacks;
        PermissionCallbacks permissionCallbacks;
        Task<CompletedCapture> saving;
        readonly List<CapturedFrame> frames=new List<CapturedFrame>();
        readonly List<long> missedTimes=new List<long>();
        readonly Dictionary<string,int> missedReasons=new Dictionary<string,int>(StringComparer.Ordinal);
        string patient,session,test,view,side,take,directory;
        StreamWriter journal;
        bool waitingForCamera,requestingPermission,previewReady,countingDown,waitingForEncoder,stopping,interrupted,encoderFinishing,isMicroscopeHold;
        double deadline;
        long originNs=-1,lastObserved=-1,captureCompletedTicks,targetDurationNs=10_000_000_000;
        int observedFrames,width,height,generation;
        double[] intrinsics;
        double captureStartedAt,readbackTotalMs,copyTotalMs,submitTotalMs,maxSubmitMs;
        int readbackCount,submitAttempts,maxPendingReadbacks;
        bool metricsLogged,syntheticBenchmark;

        void OnEnable() { OVRManager.InputFocusLost+=LostFocus; }
        void OnDisable() { OVRManager.InputFocusLost-=LostFocus; LostFocus(); }
        bool HasCaptureFocus => Application.isFocused && OVRManager.hasInputFocus;

        public void BeginTake(string patientId,string sessionId,string testType,string captureView="front",string captureSide="not_applicable",bool microscopeHold=false,double targetDurationSeconds=10)
        {
            if(syntheticBenchmark || IsRecording || IsPreparing || IsPreviewing || IsFinalizing) { Error="Finish the current take first."; return; }
            try {
                CaptureBundle.ValidateIdentity(patientId,sessionId,testType,captureView,captureSide);
                targetDurationNs=CaptureBundle.TargetDurationNanoseconds(targetDurationSeconds);
            }
            catch(ArgumentException failure) { Error=failure.Message; return; }
            TargetDurationSeconds=targetDurationSeconds;
            patient=patientId;session=sessionId;test=testType;view=captureView;side=captureSide;
            isMicroscopeHold=microscopeHold;
            LastCapture=null;Error="";interrupted=false;stopping=false;encoderFinishing=false;previewReady=false;
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
            if(syntheticBenchmark) { UpdateSyntheticBenchmark();return; }
            if(waitingForCamera) {
                if(cameraAccess!=null && cameraAccess.IsPlaying && HasCaptureFocus) {
                    waitingForCamera=false;previewReady=true;
                    Status="Camera ready. Check the full required region, then press Record this view.";
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
                OpenEncoder();
                waitingForEncoder=true;deadline=Time.realtimeSinceStartupAsDouble+8;Status="Preparing video encoder.";
            } catch(Exception failure) { Debug.LogException(failure);Fail("Recording could not start. Check available device storage."); }
        }

        void OpenEncoder()
        {
            // Three reads cover the measured ~40ms callback latency at 30fps. Java receives its own JNI array.
            readbacks=new CaptureReadbacks(checked(width*height*4));
            readbackTotalMs=copyTotalMs=submitTotalMs=maxSubmitMs=0;readbackCount=submitAttempts=maxPendingReadbacks=0;missedReasons.Clear();metricsLogged=false;
            captureStartedAt=Time.realtimeSinceStartupAsDouble;
            // Preserve graphics API row order; never blit a previous camera texture onto the next timestamp.
            encoder=new AndroidJavaObject("com.hth.capture.PhysioMp4Recorder",Path.Combine(directory,take+".mp4"),width,height,!SystemInfo.graphicsUVStartsAtTop);
            submitMethod=AndroidJNIHelper.GetMethodID(encoder.GetRawClass(),"submit","([BJ)Z");
        }

        void CaptureCurrentImage()
        {
            long ns=checked((cameraAccess.Timestamp.Ticks-DateTime.UnixEpoch.Ticks)*100L);
            if(ns==lastObserved) return;
            if(ns<lastObserved) { Interrupt("Camera timestamps moved backwards. Retake required."); return; }
            if(lastObserved>=0 && ns-lastObserved>100_000_000) interrupted=true;
            lastObserved=ns;int id=observedFrames++;
            if(originNs>=0 && (ns-originNs>CaptureBundle.MaximumDurationNs || frames.Count>=CaptureBundle.MaximumFrames)) { StopTake(); return; }
            if(originNs<0) originNs=ns;
            RequestImage(cameraAccess.GetTexture(),id,ns);
        }

        void RequestImage(Texture image,int id,long ns)
        {
            try {
                var owner=readbacks;
                if(owner==null || !owner.TryReserve(id,ns,out var frame)) { RecordMiss(id,ns,"readback_busy");return; }
                maxPendingReadbacks=Math.Max(maxPendingReadbacks,owner.Count);
                int requestGeneration=generation;
                double requestedAt=Time.realtimeSinceStartupAsDouble;
                AsyncGPUReadback.Request(image,0,TextureFormat.RGBA32,request=> {
                    // Each take owns a distinct queue. Never write into a buffer after cancellation or reuse.
                    if(requestGeneration!=generation || !ReferenceEquals(owner,readbacks) || !owner.IsPending(frame)) return;
                    try {
                        if(!request.hasError) {
                            readbackTotalMs+=(Time.realtimeSinceStartupAsDouble-requestedAt)*1000;readbackCount++;
                            long copying=System.Diagnostics.Stopwatch.GetTimestamp();
                            request.GetData<sbyte>().CopyTo(frame.Pixels);
                            copyTotalMs+=(System.Diagnostics.Stopwatch.GetTimestamp()-copying)*1000.0/System.Diagnostics.Stopwatch.Frequency;
                        }
                        owner.Complete(frame,request.hasError);
                        if(request.hasError) Interrupt("Camera image transfer failed. Retake required.");
                        DrainReadbacks(owner);
                    } catch(Exception failure) { AbortReadbacks(failure); }
                });
            } catch(Exception failure) { AbortReadbacks(failure); }
            finally {
                // The source-time deadline also applies when all readback slots are occupied.
                if(IsRecording && CaptureBundle.DurationComplete(originNs,ns,targetDurationNs)) StopTake();
            }
        }

        void DrainReadbacks(CaptureReadbacks owner)
        {
            while(owner.TryPeekReady(out var frame)) {
                try {
                    if(frame.Failed) RecordMiss(frame.FrameId,frame.SourceNanoseconds,"readback_failed");
                    else {
                        long submitting=System.Diagnostics.Stopwatch.GetTimestamp();
                        submitAttempts++;
                        bool accepted=encoder.Call<bool>(submitMethod,frame.Pixels,(frame.SourceNanoseconds-originNs)/1000);
                        double submitMs=(System.Diagnostics.Stopwatch.GetTimestamp()-submitting)*1000.0/System.Diagnostics.Stopwatch.Frequency;
                        submitTotalMs+=submitMs;maxSubmitMs=Math.Max(maxSubmitMs,submitMs);
                        if(accepted) { frames.Add(new CapturedFrame(frame.FrameId,frame.SourceNanoseconds));WriteJournal(frame.FrameId,frame.SourceNanoseconds,"encoded_input"); }
                        else RecordMiss(frame.FrameId,frame.SourceNanoseconds,"encoder_busy");
                    }
                } finally { owner.Release(frame); }
            }
            if(stopping && !encoderFinishing && owner.Count==0) FinishEncoder();
        }

        void AbortReadbacks(Exception failure)
        {
            Debug.LogException(failure);Interrupt("Camera recording failed. Original files have been kept.");
            DiscardReadbacks("capture_failed");
            if(stopping && !encoderFinishing) FinishEncoder();
        }

        void DiscardReadbacks(string reason)
        {
            if(readbacks==null) return;
            foreach(var frame in readbacks.Cancel()) {
                try { RecordMiss(frame.FrameId,frame.SourceNanoseconds,reason); }
                catch(Exception failure) { Debug.LogException(failure); } // Keep cleanup possible when storage fails.
            }
        }

        void RecordMiss(int id,long ns,string reason)
        {
            missedReasons.TryGetValue(reason,out var count);missedReasons[reason]=count+1;
            missedTimes.Add(ns);WriteJournal(id,ns,reason);
            Status="A camera frame was missed. Complete this take, then retake if quality is insufficient.";
        }

        void WriteJournal(int id,long ns,string state)
        { if(journal==null) return;journal.WriteLine(id.ToString(CultureInfo.InvariantCulture)+","+ns.ToString(CultureInfo.InvariantCulture)+","+state);journal.Flush(); }

        public void StopTake()
        {
            if(IsPreviewing) { ClosePreview("Camera preview closed. Open it again to frame the next take."); return; }
            if(IsPreparing) { waitingForCamera=countingDown=waitingForEncoder=false;Fail("Recording cancelled before capture.");return; }
            if(!IsRecording) return;
            captureCompletedTicks=System.Diagnostics.Stopwatch.GetTimestamp();
            IsRecording=false;stopping=true;IsFinalizing=true;Status="Saving original recording and verifying video timestamps.";
            readbacks?.StopAccepting();deadline=Time.realtimeSinceStartupAsDouble+5;
            if(readbacks==null || readbacks.Count==0) FinishEncoder();
        }

        public void StartCountdown()
        {
            if(!IsPreviewing || !HasCaptureFocus) { Error="Open the camera and check framing before recording."; return; }
            Error="";previewReady=false;countingDown=true;deadline=Time.realtimeSinceStartupAsDouble+3;
            Status="Recording starts in 3. Keep the headset steady.";
        }

        private void ClosePreview(string message)
        {
            generation++;previewReady=false;
            if(cameraAccess!=null) cameraAccess.enabled=false;
            Error="";Status=message;
        }

        void FinishEncoder()
        {
            encoderFinishing=true;encoder?.Call("finish");journal?.Dispose();journal=null;
            deadline=Time.realtimeSinceStartupAsDouble+20;
        }

        void CheckFinalized()
        {
            if(!encoderFinishing) {
                if(Time.realtimeSinceStartupAsDouble>deadline) {
                    interrupted=true;Error="Camera image transfer timed out. Original files have been kept; retake required.";
                    DiscardReadbacks("readback_timeout");FinishEncoder();
                }
                return;
            }
            if(!encoder.Call<bool>("isDone")) {
                if(Time.realtimeSinceStartupAsDouble>deadline) Fail("Video finalization timed out. Original files have been kept; retake required.");
                return;
            }
            string encoderError=encoder.Call<string>("getError");
            LogCaptureMetrics();
            if(!string.IsNullOrEmpty(encoderError)) { Fail(encoderError);return; }
            try {
                long[] times=encoder.Call<long[]>("getPresentationTimes");
                if(syntheticBenchmark) { FinishSyntheticBenchmark(times);return; }
                bool incomplete=frames.Count<2 || !CaptureBundle.DurationComplete(frames[0].SourceNanoseconds,frames[frames.Count-1].SourceNanoseconds,targetDurationNs);
                if(incomplete) { interrupted=true;Error="Recording stopped early. Record the full "+TargetDurationSeconds.ToString("0.#",CultureInfo.InvariantCulture)+" seconds to complete this view."; }
                var metadata=CaptureBundle.Sidecar(take,width,height,frames,times,view,isMicroscopeHold?"steady_hold":test=="barefoot"?"standing":test=="walking"?"exercise":"seated",side,
                    interrupted,intrinsics[0],intrinsics[1],intrinsics[2],intrinsics[3],missedTimes);
                bool gaps=((JArray)metadata["capture"]["gaps"]).Count>0 || missedTimes.Count>0;
                if(gaps) { metadata["capture"]["interrupted"]=true;Error="Some camera frames were missed. Retake before processing."; }
                encoder.Dispose();encoder=null;readbacks=null;
                // Hashing/zipping never blocks headset rendering. The completed bundle is published only on success.
                saving=Task.Run(()=>CaptureBundle.Save(directory,patient,session,test,metadata,captureCompletedTicks,isMicroscopeHold));
            } catch(Exception failure) { Debug.LogException(failure);Fail("Recording metadata could not be verified. Original files have been kept; retake required."); }
        }

        void LogCaptureMetrics()
        {
            if(metricsLogged) return;metricsLogged=true;
            double count=Math.Max(1,readbackCount);
            Debug.Log(FormattableString.Invariant($"PHYSIO_CAPTURE_METRICS: synthetic={syntheticBenchmark} width={width} height={height} observed={observedFrames} accepted={frames.Count} missed={missedTimes.Count} readback_count={readbackCount} submit_attempts={submitAttempts} max_pending={maxPendingReadbacks} miss_reasons={Newtonsoft.Json.JsonConvert.SerializeObject(missedReasons)} source_seconds={DurationSeconds:F3} effective_fps={(DurationSeconds>0?(frames.Count-1)/DurationSeconds:0):F2} wall_seconds={Time.realtimeSinceStartupAsDouble-captureStartedAt:F3} readback_callback_ms={readbackTotalMs/count:F3} copy_ms={copyTotalMs/count:F3} submit_ms={submitTotalMs/Math.Max(1,submitAttempts):F3} max_submit_ms={maxSubmitMs:F3}"));
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
            generation++;DiscardReadbacks("capture_failed");
            if(encoder!=null) LogCaptureMetrics();
            waitingForCamera=requestingPermission=previewReady=countingDown=waitingForEncoder=IsRecording=IsFinalizing=false;
            encoder?.Call("finish");encoder?.Dispose();encoder=null;readbacks=null;journal?.Dispose();journal=null;
            syntheticBenchmark=false;if(syntheticTexture!=null) Destroy(syntheticTexture);
            if(cameraAccess!=null) cameraAccess.enabled=false;
        }

        void OnApplicationPause(bool paused)
        {
            if(paused && (IsRecording || (IsFinalizing && !encoderFinishing))) {
                Interrupt("Headset capture was interrupted. Retake required.");DiscardReadbacks("application_paused");
                if(!encoderFinishing) FinishEncoder();
            }
            else if(paused && IsPreviewing) ClosePreview("Camera preview closed when the app paused. Open it again to frame the take.");
            else if(paused && IsPreparing) Fail("Capture was interrupted before recording. Try again.");
        }
        void OnApplicationFocus(bool focused) { if(!focused) LostFocus(); }
        void LostFocus()
        {
            if(IsRecording || (IsFinalizing && !encoderFinishing)) {
                Interrupt("Headset focus was lost. Retake required.");DiscardReadbacks("focus_lost");
                if(!encoderFinishing) FinishEncoder();
            }
            else if(IsPreviewing) ClosePreview("Camera preview closed when headset focus was lost. Open it again to frame the take.");
            else if(countingDown || waitingForEncoder || (waitingForCamera && !requestingPermission)) Fail("Capture was interrupted before recording. Try again.");
        }
        void OnDestroy() { generation++;DiscardReadbacks("recorder_destroyed");encoder?.Call("finish");encoder?.Dispose();journal?.Dispose(); }
    }
}
