using System;
using System.IO;
using System.Linq;
using System.Numerics;
using Physio.Replay;
static class GoataScoreChecks
{
 static int checks;
 static void Check(bool value,string text) { if(!value)throw new Exception(text);checks++; }
 static GoataScoreResult Number(double score)=>GoataScore.Calculate(new[]{new GoataScoreCategory("a",50,(100-score)/100),new GoataScoreCategory("b",50,(100-score)/100)});
 static void Reject(Action act){try{act();}catch(ArgumentException){checks++;return;}throw new Exception("Expected validation rejection");}
 static Vector3[] Pose(double lean=0,double twist=0){double a=lean*Math.PI/180,r=twist*Math.PI/180;var mid=new Vector3((float)Math.Sin(a),1+(float)Math.Cos(a),0);var shoulder=new Vector3((float)(.5*Math.Cos(r)),0,(float)(.5*Math.Sin(r)));return new[]{new Vector3(.5f,1,0),new Vector3(-.5f,1,0),mid+shoulder,mid-shoulder,new Vector3(.5f,0,0),new Vector3(.5f,-1,0),new Vector3(-.5f,0,0),new Vector3(-.5f,-1,0)};}
 static ReplayData Data(Vector3[][] poses){var names=new[]{"left_hip","right_hip","left_shoulder","right_shoulder","left_knee","left_ankle","right_knee","right_ankle"};var flags=Enumerable.Repeat(true,poses.Length).ToArray();var timeline=new ReplayTimeline(Guid.NewGuid(),Enumerable.Range(0,poses.Length).Select(i=>5.0+i).ToArray(),Enumerable.Range(0,poses.Length).Select(i=>new BigInteger(100+i)).ToArray(),flags,Array.Empty<ReplayGap>());return new ReplayData(Guid.Empty,timeline,0,true,"model_estimate","synthetic",Array.Empty<Vector3>(),poses.SelectMany(x=>x).ToArray(),Array.Empty<int>(),Enumerable.Repeat(-1,8).ToArray(),names,flags,Enumerable.Repeat(true,poses.Length*8).ToArray());}
 static void Main(){
  foreach(var score in new[]{0,50,51,90,91,100}){var r=Number(score);Check(r.DisplayScore==score,"boundary value");Check(r.Band==(score<=50?"red":score<=90?"yellow":"green"),"boundary color");}
  Check(Number(50.5).DisplayScore==51&&Number(50.5).Band=="yellow","50.5 rounds into yellow");Check(Number(90.5).DisplayScore==91&&Number(90.5).Band=="green","90.5 rounds into green");
  var partial=GoataScore.Calculate(new[]{new GoataScoreCategory("a",50,null),new GoataScoreCategory("b",50,.2)});
  Check(partial.Score==80&&partial.Categories.Count==1&&partial.Categories[0].Weight==100,"missing omitted and available weight normalized to100");
  Check(GoataScore.Calculate(new[]{new GoataScoreCategory("a",50,null),new GoataScoreCategory("b",50,null)}).Score==null,"all missing never fabricates100");
  Reject(()=>new GoataScoreCategory("x",-1,0));Reject(()=>new GoataScoreCategory("x",50,double.NaN));Reject(()=>new GoataScoreCategory("x",50,1.1));Reject(()=>new GoataScoreCategory("x",50,-.1));Reject(()=>GoataScore.Calculate(new[]{new GoataScoreCategory("x",99,0)}));Reject(()=>new GoataScoreSettings(50,49));Reject(()=>new GoataScoreSettings(torsoScale:0));
  var straight=Data(new[]{Pose(),Pose()});Check(GoataScore.Evaluate(straight,"walking","exercise").DisplayScore==100,"zero demo deductions");
  Check(GoataScore.Evaluate(Data(new[]{Pose(),Pose(30)}),"elk","seated").DisplayScore==100,"intended ELK lateral bend not deducted");
  Check(GoataScore.Evaluate(Data(new[]{Pose(),Pose(twist:70)}),"rtk","seated").DisplayScore==100,"intended RTK twist not deducted");
  Check(GoataScore.Evaluate(Data(new[]{Pose()}),"walking","exercise").Score==null,"single frame incomplete");
  Check(GoataScore.Evaluate(straight,"barefoot","exercise").Score==null,"historical unsupported unavailable");
  Check(GoataScore.Evaluate(straight,"walking","seated").Score==null,"wrong condition unavailable");
  var dir=Environment.GetEnvironmentVariable("HTH_GOATA_PROOF_DIR"); if (!string.IsNullOrEmpty(dir)) {byte[] Read(string n)=>File.ReadAllBytes(Path.Combine(dir,n));
  var saved=ReplayImporter.Parse(Read("replay_manifest.json"),Read("mesh_triangles.u32"),Read("mesh_vertices.f32"),Read("skeleton_joints.f32"));var first=GoataScore.Evaluate(saved,"walking","exercise");var second=GoataScore.Evaluate(saved,"walking","exercise");
  Check(first.Score.HasValue&&first.Score==second.Score&&first.Details==second.Details,"saved scoring deterministic");Check(first.Categories[0].Evidence.Count==2,"both knee peak moments retained");Check(first.Categories.SelectMany(c=>c.Evidence).All(e=>e.TakeId==saved.Timeline.SourceTakeId),"source take bound");
  foreach(var evidence in first.Categories.SelectMany(c=>c.Evidence)){var clock=new ReplayClock(saved.Timeline).Seek(evidence.SourceTime);Check((long)clock.Sample.SourceFrameId==evidence.FrameId&&clock.Sample.SourceTime==evidence.SourceTime,"exact source frame/time binding");}
  Console.WriteLine("Saved Walking demo score: "+first.Score+"; displayed "+first.DisplayScore+"; "+first.Band);Console.WriteLine(first.Summary);Console.WriteLine(first.Details); }
  Console.WriteLine("PASS: "+checks+" GoataScore focused checks.");
 }
}
