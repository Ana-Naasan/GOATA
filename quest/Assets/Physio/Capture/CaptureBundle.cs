using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Physio.Capture
{
    public sealed class CapturedFrame
    {
        public readonly int FrameId;
        public readonly long SourceNanoseconds;
        public CapturedFrame(int frameId, long sourceNanoseconds)
        { FrameId = frameId; SourceNanoseconds = sourceNanoseconds; }
    }

    public sealed class CompletedCapture
    {
        public string PatientId { get; internal set; }
        public string SessionId { get; internal set; }
        public string TestType { get; internal set; }
        public string TakeId { get; internal set; }
        public string ManifestJson { get; internal set; }
        public string ZipPath { get; internal set; }
        public bool Interrupted { get; internal set; }
        public double DurationSeconds { get; internal set; }
        public long CaptureCompletedStopwatchTicks { get; internal set; }
    }

    /// <summary>Preserves source camera timestamps; media PTS is a separate verified mapping.</summary>
    public static class CaptureBundle
    {
        public const int MaximumFrames = 600;
        public const long MaximumDurationNs = 19_966_666_666;
        static string Decimal(long value) => value.ToString(CultureInfo.InvariantCulture);

        public static long TargetDurationNanoseconds(double seconds)
        {
            if(double.IsNaN(seconds) || double.IsInfinity(seconds) || seconds<1 || seconds>15)
                throw new ArgumentException("Recording duration must be between 1 and 15 seconds.");
            return checked((long)Math.Round(seconds*1e9));
        }

        // A 30fps take spans first-to-last sample, one frame less than its playback duration.
        public static bool DurationComplete(long firstNs,long lastNs,long targetNs) =>
            firstNs>=0 && lastNs>=firstNs && lastNs-firstNs>=targetNs-33_333_334;

        public static void ValidateIdentity(string patient, string session, string test, string view, string side)
        {
            if (!Guid.TryParseExact(patient,"D",out _) || !Guid.TryParseExact(session,"D",out _))
                throw new ArgumentException("Patient and session require UUIDs.");
            if (!new[]{"elk","rtk","walking","barefoot"}.Contains(test)) throw new ArgumentException("Unsupported test.");
            if (!new[]{"front","left","right","rear","medial","other"}.Contains(view)) throw new ArgumentException("Unsupported view.");
            if (!new[]{"left","right","bilateral","not_applicable"}.Contains(side)) throw new ArgumentException("Unsupported side.");
            if (test=="walking" && side!="not_applicable") throw new ArgumentException("Walking captures the full body.");
            if (test=="barefoot" && side!="left" && side!="right") throw new ArgumentException("Choose left or right foot.");
        }

        // Same centered sensor crop as SDK85 PassthroughCameraAccess.CalcSensorCropRegion.
        public static double[] ScaleIntrinsics(int sensorWidth,int sensorHeight,int width,int height,
                                               double fx,double fy,double cx,double cy)
        {
            if (Math.Min(Math.Min(sensorWidth,sensorHeight),Math.Min(width,height))<=0) throw new ArgumentException("Invalid resolution.");
            double scale=Math.Max((double)width/sensorWidth,(double)height/sensorHeight);
            return new[]{fx*scale,fy*scale,(cx-sensorWidth/2.0)*scale+width/2.0,(cy-sensorHeight/2.0)*scale+height/2.0};
        }

        public static JObject Sidecar(string take,int width,int height,IReadOnlyList<CapturedFrame> frames,
            IReadOnlyList<long> mediaTimes,string view,string condition,string side,bool interrupted,
            double fx,double fy,double cx,double cy,IReadOnlyList<long> missedSourceTimes)
        {
            if(!new[]{"standing","seated","exercise","steady_hold"}.Contains(condition))
                throw new ArgumentException("Unsupported capture condition.");
            if (!Guid.TryParseExact(take,"D",out _) || width<32 || height<32 || width%2!=0 || height%2!=0 || (long)width*height>2073600)
                throw new ArgumentException("Invalid take or image dimensions.");
            if (frames.Count<2 || frames.Count>MaximumFrames || frames.Count!=mediaTimes.Count) throw new ArgumentException("Invalid frame count.");
            if (new[]{fx,fy,cx,cy}.Any(v=>double.IsNaN(v)||double.IsInfinity(v)) || fx<=0 || fy<=0)
                throw new ArgumentException("Invalid sensor intrinsics.");
            for(int i=0;i<frames.Count;i++)
                if(frames[i].FrameId<0 || frames[i].SourceNanoseconds<0 || mediaTimes[i]<0 ||
                   (i>0 && (frames[i].FrameId<=frames[i-1].FrameId || frames[i].SourceNanoseconds<=frames[i-1].SourceNanoseconds || mediaTimes[i]<=mediaTimes[i-1])))
                    throw new ArgumentException("Frames and presentation times must be strictly ordered.");
            long origin=frames[0].SourceNanoseconds, last=frames[frames.Count-1].SourceNanoseconds;
            if(last-origin>MaximumDurationNs) throw new ArgumentException("Take exceeds 20 seconds.");
            var gaps = new JArray();
            for(int i=1;i<frames.Count;i++)
            {
                long previous=frames[i-1].SourceNanoseconds,current=frames[i].SourceNanoseconds;
                bool missed=missedSourceTimes.Any(t=>t>previous && t<current);
                if(missed || current-previous>100_000_000)
                    gaps.Add(new JObject { ["start_pts_ns"]=Decimal(previous+1), ["end_pts_ns"]=Decimal(current-1),
                        ["reason"]=missed ? "Camera image was observed but could not be encoded; retake required." : "Camera delivery interval exceeded 100ms; missing observations were not filled." });
            }
            return new JObject {
                ["schema_version"]="1.0",["take_id"]=take,
                ["adapter"]=new JObject{["name"]="Meta.MRUK.PassthroughCameraAccess/HTH.AndroidMediaCodec",["version"]="85.0.0/1"},
                ["image"]=new JObject{["width_px"]=width,["height_px"]=height,["rotation_degrees"]=0,["mirrored"]=false},
                ["camera"]=new JObject{["id"]="quest3-left",["calibration_status"]="calibrated",
                    ["intrinsics"]=new JObject{["fx"]=fx,["fy"]=fy,["cx"]=cx,["cy"]=cy},
                    ["distortion_model"]="unknown",["distortion_coefficients"]=new JArray(),
                    ["calibration_note"]="SDK85 sensor intrinsics transformed with SDK centered crop to stored resolution. Distortion is unknown: this API exposes no distortion model or coefficients, and the empty array does not establish rectification. No physical body-scale calibration. Camera pose omitted because per-image tracking validity is unavailable."},
                ["clock"]=new JObject{["id"]="meta-pca-image-timestamp-unix-us",["unit"]="nanoseconds",["origin_pts_ns"]=Decimal(origin)},
                ["frames"]=new JArray(frames.Select(f=>new JObject{["frame_id"]=f.FrameId,["pts_ns"]=Decimal(f.SourceNanoseconds),["image_valid"]=true})),
                ["media"]=new JObject{["binding"]="indexed_presentation_time_us",["presentation_time_us"]=new JArray(mediaTimes.Select(Decimal))},
                ["capture"]=new JObject{["view"]=view,["condition"]=condition,["side"]=side,["interrupted"]=interrupted,["gaps"]=gaps}
            };
        }

        // A microscope-only bundle is supplemental: Workflow must merge it with the original primary take before submission.
        public static CompletedCapture Save(string directory,string patient,string session,string test,JObject sidecar,long captureCompletedStopwatchTicks=0,bool microscopeHold=false)
        {
            ValidateIdentity(patient,session,test,(string)sidecar["capture"]["view"],(string)sidecar["capture"]["side"]);
            if(microscopeHold!=((string)sidecar["capture"]["condition"]=="steady_hold"))
                throw new ArgumentException("Steady-hold evidence must be saved as a supplemental microscope take.");
            if(test=="walking" && !microscopeHold && (string)sidecar["capture"]["condition"]!="exercise")
                throw new ArgumentException("Walking requires an exercise take.");
            string take=(string)sidecar["take_id"];
            if(!Guid.TryParseExact(take,"D",out _)) throw new ArgumentException("Invalid take ID.");
            string sidecarPath=Path.Combine(directory,take+".json"),video=Path.Combine(directory,take+".mp4");
            string zip=Path.Combine(directory,"capture.zip"),manifestPath=Path.Combine(directory,"manifest.json");
            if(File.Exists(sidecarPath)||File.Exists(zip)||File.Exists(manifestPath)) throw new ArgumentException("Original capture already exists; create a new take for retakes.");
            if(!File.Exists(video) || new FileInfo(video).Length==0 || new FileInfo(video).Length>512L*1024*1024)
                throw new ArgumentException("Recording file is missing or exceeds the capture limit.");
            var frames=(JArray)sidecar["frames"];
            double duration=(long.Parse((string)frames[frames.Count-1]["pts_ns"],CultureInfo.InvariantCulture)-
                             long.Parse((string)frames[0]["pts_ns"],CultureInfo.InvariantCulture))/1e9;
            File.WriteAllText(sidecarPath,sidecar.ToString(Formatting.Indented));
            var manifest=new JObject{["schema_version"]="1.0",["session_id"]=session,["patient_id"]=patient,["test_type"]=test,
                ["protocol_id"]=test,["protocol_version"]="1.0",
                ["capture_completed_at"]=DateTime.UnixEpoch.AddTicks(long.Parse((string)frames[frames.Count-1]["pts_ns"],CultureInfo.InvariantCulture)/100).ToString("o",CultureInfo.InvariantCulture),
                ["takes"]=new JArray(new JObject{["take_id"]=take,["kind"]=microscopeHold?"microscope":test=="barefoot"?"foot_closeup":"full_body",
                    ["view"]=sidecar["capture"]["view"].DeepClone(),["condition"]=sidecar["capture"]["condition"].DeepClone(),
                    ["side"]=sidecar["capture"]["side"].DeepClone(),["duration_s"]=duration,["video"]=FileReference(video),["frame_metadata"]=FileReference(sidecarPath)})};
            if(test!="barefoot" && !microscopeHold) manifest["replay_take_id"]=take;
            string json=manifest.ToString(Formatting.Indented);
            File.WriteAllText(manifestPath,json);
            using(var output=new FileStream(zip,FileMode.CreateNew))
            using(var archive=new ZipArchive(output,ZipArchiveMode.Create))
                foreach(string path in new[]{video,sidecarPath}) archive.CreateEntryFromFile(path,Path.GetFileName(path),CompressionLevel.NoCompression);
            return new CompletedCapture{PatientId=patient,SessionId=session,TestType=test,TakeId=take,ManifestJson=json,
                ZipPath=zip,Interrupted=(bool)sidecar["capture"]["interrupted"],DurationSeconds=duration,CaptureCompletedStopwatchTicks=captureCompletedStopwatchTicks};
        }

        static JObject FileReference(string path)
        {
            using(var hash=SHA256.Create()) using(var stream=File.OpenRead(path))
                return new JObject{["member"]=Path.GetFileName(path),["byte_size"]=stream.Length,
                    ["sha256"]=BitConverter.ToString(hash.ComputeHash(stream)).Replace("-","").ToLowerInvariant()};
        }
    }
}
