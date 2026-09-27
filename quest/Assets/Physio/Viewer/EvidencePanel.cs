#nullable enable
using System;
using System.IO;
using Newtonsoft.Json.Linq;
using Physio.Workflow;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Video;

namespace Physio.Viewer
{
    /// <summary>Only local, validated result artifacts or the selected session's exact original take.</summary>
    public sealed class EvidencePanel : MonoBehaviour
    {
        private RawImage original = null!;
        private RawImage amplified = null!;
        private TMP_Text caption = null!;
        private VideoPlayer? first;
        private VideoPlayer? second;
        private RenderTexture? firstTexture;
        private RenderTexture? secondTexture;
        private double start;
        private double end;
        private bool pair;
        private bool wantsPlay;
        private bool initialized;
        private string label = "";

        public void Configure(RawImage originalImage, RawImage amplifiedImage, TMP_Text captionLabel)
        { original = originalImage; amplified = amplifiedImage; caption = captionLabel; }

        public void OpenOriginal(string path, Guid take, double startSeconds, double endSeconds, bool matchingTake, double mediaStart, double mediaEnd)
        {
            Stop();
            start = mediaStart; end = mediaEnd;
            label = (matchingTake ? "MATCHING RECORDING" : "SEPARATE RECORDING") +
                $" · ORIGINAL · {startSeconds:0.00}–{endSeconds:0.00}s\nTake {take.ToString("N").Substring(0, 8)} · hologram paused";
            caption.text = label + " · loading";
            amplified.transform.parent.gameObject.SetActive(false);
            first = CreatePlayer(path, original, out firstTexture);
        }

        public void OpenMicroscope(CachedResult result, JObject microscope)
        {
            Stop();
            pair = true;
            start = 0;
            end = (double)microscope["evidence"]!["end_s"]! - (double)microscope["evidence"]!["start_s"]!;
            label = $"ORIGINAL                                  AMPLIFIED\nSource {microscope["evidence"]!["start_s"]}–{microscope["evidence"]!["end_s"]}s · same recording and crop";
            caption.text = label + " · loading";
            amplified.transform.parent.gameObject.SetActive(true);
            first = CreatePlayer(result.ArtifactPath(Guid.Parse((string)microscope["original_artifact_id"]!)), original, out firstTexture);
            second = CreatePlayer(result.ArtifactPath(Guid.Parse((string)microscope["amplified_artifact_id"]!)), amplified, out secondTexture);
        }

        public void TogglePlay()
        {
            if (first == null || end <= start) return;
            wantsPlay = !wantsPlay;
            if (!wantsPlay) Pause();
        }
        public void Pause()
        {
            wantsPlay = false;
            first?.Pause(); second?.Pause();
        }
        public void Restart()
        {
            Pause();
            if (first != null && first.isPrepared) first.time = start;
            if (second != null && second.isPrepared) second.time = start;
        }

        private void Update()
        {
            if (first == null || !first.isPrepared || (pair && (second == null || !second.isPrepared))) return;
            if (!initialized)
            {
                first.time = start;
                if (second != null) second.time = start;
                caption.text = label + " · ready";
                initialized = true;
            }
            if (!wantsPlay) return;
            if (first.time >= end && end > start) { Restart(); return; }
            if (!first.isPlaying) first.Play();
            if (second == null) return;
            if (Math.Abs(second.time - first.time) > .12) second.time = first.time;
            if (!second.isPlaying) second.Play();
        }

        private VideoPlayer CreatePlayer(string path, RawImage target, out RenderTexture texture)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Original evidence file is unavailable.");
            texture = new RenderTexture(1024, 576, 0) { name = "Evidence display" };
            texture.Create();
            target.texture = texture;
            target.GetComponent<AspectRatioFitter>().aspectRatio = 16f / 9f;
            target.enabled = true;
            var player = gameObject.AddComponent<VideoPlayer>();
            player.playOnAwake = false;
            player.source = VideoSource.Url;
            player.url = new Uri(Path.GetFullPath(path)).AbsoluteUri;
            player.renderMode = VideoRenderMode.RenderTexture;
            player.targetTexture = texture;
            player.aspectRatio = VideoAspectRatio.FitInside;
            player.audioOutputMode = VideoAudioOutputMode.None;
            player.waitForFirstFrame = true;
            player.isLooping = false;
            player.errorReceived += OnVideoError;
            player.Prepare();
            return player;
        }

        private void OnVideoError(VideoPlayer source, string message)
        {
            Pause();
            caption.text = "Evidence could not be decoded. The original recording is retained.";
            Debug.LogWarning("PHYSIO_EVIDENCE_DECODE_FAILED");
        }

        public void Stop()
        {
            Pause();
            foreach (var player in new[] { first, second })
            {
                if (player == null) continue;
                player.errorReceived -= OnVideoError;
                player.Stop();
                Destroy(player);
            }
            first = second = null;
            if (firstTexture != null) { firstTexture.Release(); Destroy(firstTexture); }
            if (secondTexture != null) { secondTexture.Release(); Destroy(secondTexture); }
            firstTexture = secondTexture = null;
            pair = false; initialized = false;
            if (original != null) original.texture = null;
            if (amplified != null) amplified.texture = null;
        }
        private void OnDestroy() => Stop();
    }
}
