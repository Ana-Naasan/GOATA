#nullable enable
using System;
using System.Linq;
using Newtonsoft.Json.Linq;
using Physio.Replay;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Physio.Viewer
{
    public sealed partial class WorkflowPanel
    {
        private bool showObservations = true;
        private JObject? selectedObservation;
        private JObject? reviewCapture;

        private string? EvidenceView(JObject item) => (string?)reviewCapture?["takes"]?
            .FirstOrDefault(take => (string?)take["take_id"] == (string?)item["evidence"]?["take_id"])?["view"];

        private JToken? Feature(string name) => manifest?["features"]?.FirstOrDefault(feature => (string?)feature["name"] == name);

        private void RenderReview()
        {
            heading.text = result?.ResultId == session?.ResultId ? "Movement review · latest" : "Movement review · saved version";
            if (manifest == null) { body.text = "No validated result is loaded."; return; }
            var observations = (manifest["observations"] as JArray)?.OfType<JObject>().ToArray() ?? Array.Empty<JObject>();
            var assessment = Feature(session?.TestType == "barefoot" ? "foot" : "movement");
            var assessmentStatus = InsightPresentation.AssessmentStatus(session?.TestType ?? "elk", (string?)assessment?["status"], ((JArray)manifest["findings"]!).Count);
            var observationStatus = InsightPresentation.ObservationStatus((string?)manifest["schema_version"], (string?)Feature("observations")?["status"], observations.Length);
            var pages = Math.Max(1, (observations.Length + 2) / 3);
            page = InsightPresentation.ClampObservationPage(page, observations.Length, showObservations);
            SetAction(observationsTab, "Observations" + (showObservations && pages > 1 ? $" {page + 1}/{pages} · next" : ""), () =>
            { page = showObservations ? (page + 1) % pages : 0; showObservations = true; Show(Screen.Review, false); });
            SetAction(assessmentTab, "Assessment", () => { showObservations = false; Show(Screen.Review); });
            var elapsed = result?.ResultId == session?.ResultId && session?.CaptureToLoadedSeconds is double seconds
                ? $" · {seconds:0.0}s capture → display" + (session.CaptureTimingBasis == "monotonic" ? "" : " (wall-clock estimate)") : "";
            status.text = "RESEARCH · UNVALIDATED" + elapsed + "\n" + (showObservations ? assessmentStatus.Replace("\n", " · ") : observationStatus);
            if (showObservations && observations.Length > 0) RenderObservations(observations);
            else RenderAssessmentOrUnavailable(assessmentStatus, observationStatus, assessment);
        }

        private void RenderObservations(JObject[] observations)
        {
            var visible = observations.Skip(page * 3).Take(3).ToArray();
            if (selectedObservation == null || !visible.Contains(selectedObservation)) selectedObservation = visible[0];
            body.fontSize = 20; SetBodyHeight(132);
            body.text = InsightPresentation.Summary(selectedObservation, EvidenceView(selectedObservation));
            for (var index = 0; index < visible.Length; index++)
            {
                var item = visible[index];
                SetRow(index, (item == selectedObservation ? "Selected · " : "") + InsightPresentation.Card(item, EvidenceView(item)), () =>
                { selectedObservation = item; Show(Screen.Review, false); });
                var layout = rows[index].GetComponent<LayoutElement>(); layout.minHeight = layout.preferredHeight = 90;
                var label = rows[index].GetComponentsInChildren<TMP_Text>(true).First(text => text.name == "Label");
                label.fontSize = 20; label.color = item == selectedObservation ? new Color(1f, .84f, .42f) : Color.white;
            }
            SetRow(3, "Details · method and all limitations", () =>
            { finding = selectedObservation; detailPage = 0; Show(Screen.Finding); });
            var detailLayout = rows[3].GetComponent<LayoutElement>(); detailLayout.minHeight = detailLayout.preferredHeight = 44;
            FocusObservation(selectedObservation, false);
            SetAction(primary, "View moment", () => FocusObservation(selectedObservation!, true));
            SetAction(secondary, "Inspect original", () => OpenEvidence(selectedObservation!));
        }

        private void FocusObservation(JObject item, bool openSeparate)
        {
            viewer.PauseReplay();
            var interval = item["evidence"]!;
            var take = Guid.Parse((string)interval["take_id"]!);
            if (ReviewEvidence.CanSeek(result?.ReplayTakeId, take, (double)interval["start_s"]!, (double)interval["end_s"]!))
                viewer.SelectFinding(new FindingInterval(take, (double)interval["start_s"]!, (double)interval["end_s"]!),
                    item["highlight_joint_names"]?.Values<string>().Where(name => name != null).Select(name => name!).ToArray() ?? Array.Empty<string>(),
                    (string?)item["region"] ?? "Selected region");
            else
            {
                viewer.Highlight(Array.Empty<string>());
                if (openSeparate) OpenEvidence(item);
            }
        }

        private void RenderAssessmentOrUnavailable(string assessmentStatus, string observationStatus, JToken? assessment)
        {
            SetBodyHeight(180); body.fontSize = 22;
            body.text = showObservations
                ? observationStatus + "\n" + InsightPresentation.Compact((string?)Feature("observations")?["detail"] ?? "This saved result contains no estimated observations.", 260)
                : assessmentStatus + "\n" + InsightPresentation.Compact((string?)assessment?["detail"] ?? "No evaluated assessment is available.", 260);
            var findings = showObservations ? Enumerable.Empty<JObject>() : ((JArray)manifest!["findings"]!).OfType<JObject>();
            var choices = findings.Select(item => ((string)item["label"]!, (Action)(() =>
            { finding = item; detailPage = 0; Show(Screen.Finding); }))).ToList();
            choices.AddRange(manifest!["features"]!.Select(feature => ($"{feature["name"]} · {feature["status"]}", (Action)(() =>
            { featureDetail = InsightPresentation.FeatureDetail((string)feature["name"]!, (string?)feature["detail"]); detailPage = 0; Show(Screen.Feature); }))));
            List(choices.ToArray(), 3);
            SetAction(primary, session?.TestType == "barefoot" ? "Foot assessment" : "Motion microscope", () => Show(session?.TestType == "barefoot" ? Screen.Foot : Screen.Microscope));
            SetAction(secondary, showObservations ? "Assessment" : "Observations", () => { showObservations = !showObservations; Show(Screen.Review); });
        }
    }
}
