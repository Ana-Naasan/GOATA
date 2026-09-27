#nullable enable
using System;
using System.Collections.Generic;
using Physio.Replay;
using UnityEngine;

namespace Physio.Viewer
{
    public sealed partial class FixtureViewer
    {
        private bool lowOpacity;
        private string[] findingJointNames = Array.Empty<string>();
        private bool findingHighlightVisible;
        public bool HasInputFocus => hasInputFocus;
        public Guid? ReplayTakeId => replay?.Timeline.SourceTakeId;

        public void LoadDemo()
        {
            LoadReplay();
            LoadReplay(replay!);
        }

        public void LoadReplay(ReplayData data)
        {
            if (data == null) throw new ArgumentNullException(nameof(data));
            ClearReplay();
            replay = data;
            clock = new ReplayClock(data.Timeline);
            speedIndex = 2;
            lastRenderedFrame = -1;
            BuildMesh(); BuildSkeleton(); BindPanel();
            RenderCurrentFrame(true);
            SetReplayVisible(true);
        }

        public void ClearReplay()
        {
            PauseReplay();
            if (meshObject != null) { meshObject.SetActive(false); Destroy(meshObject); }
            if (mesh != null) Destroy(mesh);
            foreach (var joint in jointObjects) { joint.SetActive(false); Destroy(joint); }
            foreach (var bone in boneLines) { bone.gameObject.SetActive(false); Destroy(bone.gameObject); }
            jointObjects.Clear(); boneLines.Clear();
            replay = null; clock = null; mesh = null; meshObject = null; meshVertices = null;
            findingJointNames = Array.Empty<string>(); findingHighlightVisible = false;
            SetReplayVisible(false);
            replayPanel?.ApplyState(HandReplayPanel.Empty);
        }

        public void PauseReplay() { if (clock != null) clock = clock.Pause(); }

        public void SetReplayVisible(bool visible)
        {
            if (!visible) PauseReplay();
            if (replayDisplayRoot != null) replayDisplayRoot.gameObject.SetActive(visible);
        }

        public void SelectFinding(FindingInterval interval, string[] jointNames)
        {
            if (clock == null) return;
            clock = clock.SelectFinding(interval);
            findingJointNames = (string[])jointNames.Clone();
            UpdateFindingHighlight(true);
            RenderCurrentFrame(true);
        }

        public void Highlight(string[] jointNames)
        {
            findingJointNames = (string[])jointNames.Clone();
            findingHighlightVisible = false;
            ApplyJointHighlight(jointNames);
        }

        private void UpdateFindingHighlight(bool force = false)
        {
            var visible = findingJointNames.Length > 0 && clock?.IsFindingHighlighted == true;
            if (!force && visible == findingHighlightVisible) return;
            findingHighlightVisible = visible;
            ApplyJointHighlight(visible ? findingJointNames : Array.Empty<string>());
        }

        private void ApplyJointHighlight(string[] jointNames)
        {
            if (replay == null) return;
            var names = new HashSet<string>(jointNames, StringComparer.Ordinal);
            for (var i = 0; i < jointObjects.Count; i++)
            {
                var selected = names.Contains(replay.JointNameAt(i));
                jointObjects[i].transform.localScale = Vector3.one * (selected ? .032f : .018f);
                var properties = new MaterialPropertyBlock();
                properties.SetColor("_Color", selected ? new Color(1f, .78f, .25f) : jointMaterial!.color);
                jointObjects[i].GetComponent<Renderer>().SetPropertyBlock(properties);
            }
        }

        public void ToggleBodyOpacity()
        {
            if (meshObject == null || bodyMaterial == null) return;
            lowOpacity = !lowOpacity;
            var color = bodyMaterial.color;
            color.a = lowOpacity ? .16f : .4f;
            var properties = new MaterialPropertyBlock();
            properties.SetColor("_Color", color);
            meshObject.GetComponent<Renderer>().SetPropertyBlock(properties);
        }
    }
}
