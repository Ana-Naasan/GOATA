using System;
using Physio.Viewer;
using Newtonsoft.Json.Linq;

static class UIEvidenceChecks
{
    static void Main()
    {
        var a = Guid.NewGuid(); var b = Guid.NewGuid();
        Check(ReviewEvidence.CanSeek(a, a, 1, 2), "same take seeks");
        Check(!ReviewEvidence.CanSeek(a, b, 1, 2), "other take never seeks");
        Check(!ReviewEvidence.CanSeek(null, a, 1, 2), "no replay never seeks");
        Check(!ReviewEvidence.CanSeek(a, a, double.NaN, 2), "nan rejected");
        Check(!ReviewEvidence.CanSeek(a, a, 2, 1), "reversed interval rejected");
        Check(!ReviewEvidence.CanSeek(a, a, -1, 1), "negative time rejected");
        Check(ReviewEvidence.CanSeek(a, a, 0, 0), "single instant allowed");
        var pages = ReviewEvidence.Pages(new string('x', 1200), 420);
        Check(pages.Length == 3 && string.Concat(pages).Length == 1200, "all detail text retained");
        Check(ReviewEvidence.Pages("", 420).Length == 1, "empty detail stable");
        Check(ReviewEvidence.TestName("elk").Contains("ELK"), "ELK named");
        Check(ReviewEvidence.TestName("rtk").Contains("RTK"), "RTK named");
        Check(ReviewEvidence.TestName("barefoot") == "Barefoot assessment", "foot named");
        Check(ReviewEvidence.TestName("walking") == "Walking review", "walking named");
        Check(string.Join(",", ReviewEvidence.NewTests()) == "elk,rtk,walking", "new test menu replaces foot and preserves history name");
        Check(InsightPresentation.AssessmentStatus("elk", "available", 0).Contains("No supported findings detected"), "supported completed assessment distinct from unavailable");
        Check(InsightPresentation.AssessmentStatus("elk", "unavailable", 0).Contains("not evaluated"), "unavailable never called no detections");
        Check(InsightPresentation.AssessmentStatus("walking", "available", 2).Contains("2 findings"), "finding count retained");
        Check(InsightPresentation.ObservationStatus("1.0", null, 0).Contains("saved result"), "historical observations absent explicitly");
        Check(InsightPresentation.ObservationStatus("1.1", "unavailable", 0).Contains("unavailable"), "observation status independent");
        Check(InsightPresentation.ObservationStatus("1.1", "available", 3).Contains("3 estimates"), "observations never called findings");
        Check(InsightPresentation.SourceLabel("rear", 1.25, 1.25) == "Back take · 1.25s", "single original frame named");
        Check(InsightPresentation.SourceLabel("front", 1, 2) == "Front take · 1.00–2.00s", "interval retained");
        Check(InsightPresentation.SourceLabel(null, 1, 2).StartsWith("Source take"), "unknown view not fabricated");
        var observation = JObject.Parse("{\"label\":\"Torso lean\",\"method_id\":\"geometry\",\"explanation\":\"Fitted torso orientation.\",\"region\":\"torso\",\"side\":\"not_applicable\",\"evidence\":{\"start_s\":1.0,\"end_s\":2.0,\"quality\":\"limited\",\"quality_reason\":\"Occlusion possible.\"},\"limitations\":[\"Fitted joints may be hidden.\",\"Not a lumbar measurement.\"],\"metrics\":[{\"name\":\"peak\",\"value\":12.25,\"unit\":\"deg\"}]}");
        var card = InsightPresentation.Card(observation, "front");
        Check(card.Contains("Estimated") && card.Contains("12.3°") && card.Contains("Front take") && card.Contains("Limited evidence"), "card estimate value source limitation labels");
        Check(InsightPresentation.Summary(observation, "front").Contains("Fitted joints may be hidden."), "specific limitation visible outside details");
        var method = JObject.Parse("{\"name\":\"Joint geometry\",\"version\":\"v2\"}");
        var detail = InsightPresentation.Details(observation, "front", method);
        Check(detail.Contains("Joint geometry · v2") && detail.Contains("Not a lumbar measurement.") && detail.Contains("Occlusion possible."), "details preserve all limitations method and quality reason");
        Check(InsightPresentation.FeatureDetail("observations", "failed because pose support is absent").Contains("failed because pose support is absent"), "failure and insufficient evidence explanations retained");
        Check(InsightPresentation.Compact(new string('x', 200), 40).Length == 40, "compact labels bounded with ellipsis");
        Check(string.Join("", ReviewEvidence.Pages(detail)).Contains("Not a lumbar measurement."), "full details remain pageable");
        Check(InsightPresentation.EstimatedLabel("Estimated knee angle") == "Estimated knee angle", "estimated prefix not duplicated");
        Check(InsightPresentation.ClampObservationPage(2, 3, false) == 2, "assessment pages are independent of observations");
        Check(InsightPresentation.ClampObservationPage(2, 0, true) == 2, "historical empty observations do not clamp feature pages");
        Check(InsightPresentation.ClampObservationPage(4, 5, true) == 1, "observation cards clamp to own final page");
        Console.WriteLine("PASS: 33 evidence routing, observation presentation and history checks");
    }
    static void Check(bool value, string label) { if (!value) throw new Exception(label); }
}
