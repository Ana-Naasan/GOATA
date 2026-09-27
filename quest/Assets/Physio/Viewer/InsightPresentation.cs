#nullable enable
using System;
using System.Globalization;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace Physio.Viewer
{
    /// <summary>Labels for validated evidence. Display formatting never changes source measurements.</summary>
    public static class InsightPresentation
    {
        public static int ClampObservationPage(int page, int count, bool showingObservations) =>
            showingObservations && count > 0 ? Math.Min(page, (count - 1) / 3) : page;

        public static string AssessmentStatus(string test, string? state, int count)
        {
            var title = test == "barefoot" ? "Foot assessment" : test == "walking" ? "Walking assessment" : "Exercise assessment";
            return state == "available"
                ? title + " · completed\n" + (count == 0 ? "No supported findings detected." : count + " findings")
                : title + " · unavailable / not evaluated";
        }

        public static string ObservationStatus(string? version, string? state, int count) =>
            version != "1.1" ? "Estimated observations · unavailable in this saved result"
            : state == "available" && count > 0 ? "Estimated observations · " + count + " estimates"
            : "Estimated observations · unavailable";

        public static string FeatureDetail(string name, string? detail) => name + "\n" +
            (string.IsNullOrWhiteSpace(detail) ? "No assessment result is available for this recording." : detail);

        public static string SourceLabel(string? view, double start, double end)
        {
            var name = view switch { "front" => "Front", "rear" => "Back", "right" => "Right", "left" => "Left", _ => "Source" };
            var time = start.ToString("0.00", CultureInfo.InvariantCulture);
            if (end != start) time += "–" + end.ToString("0.00", CultureInfo.InvariantCulture);
            return name + " take · " + time + "s";
        }

        public static string Source(JObject item, string? view) => SourceLabel(view,
            (double)item["evidence"]!["start_s"]!, (double)item["evidence"]!["end_s"]!);

        public static string Metrics(JObject item) => string.Join(" · ", item["metrics"]?.Select(metric =>
            ((string?)metric["name"] ?? "Value").Replace('_', ' ') + " " +
            ((double)metric["value"]!).ToString("0.0", CultureInfo.InvariantCulture) +
            ((string?)metric["unit"] == "deg" ? "°" : " " + (string?)metric["unit"])) ?? Array.Empty<string>());

        public static string EstimatedLabel(string label) => label.StartsWith("Estimated", StringComparison.OrdinalIgnoreCase) ? label : "Estimated · " + label;

        public static string Card(JObject item, string? view) =>
            Compact(EstimatedLabel((string)item["label"]!), 58) + "\n" + Compact(Metrics(item), 68) +
            "\n" + Source(item, view) + " · Limited evidence";

        public static string Summary(JObject item, string? view) =>
            "Selected: " + (string)item["region"]! + " · " + Source(item, view) +
            "\nEstimated from reconstructed pose\nLimitation: " + Compact((string?)item["limitations"]?.FirstOrDefault() ?? "See evidence limitations.", 150);

        public static string Details(JObject item, string? view, JToken? method) =>
            EstimatedLabel((string)item["label"]!) + "\n" + Metrics(item) + "\n" + Source(item, view) +
            "\n" + item["explanation"] + "\n" + item["region"] + " · " + item["side"] +
            "\nEvidence: " + item["evidence"]!["quality"] + " · " + item["evidence"]!["quality_reason"] +
            "\nLimitations\n" + string.Join("\n", item["limitations"]!.Select(value => (string)value!)) +
            (method == null ? "" : "\nMethod: " + method["name"] + " · " + method["version"]);

        public static string Compact(string text, int limit) => text.Length <= limit ? text : text.Substring(0, limit - 1).TrimEnd() + "…";
    }
}
