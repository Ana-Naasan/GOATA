using System;
using Physio.Viewer;

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
        Console.WriteLine("PASS: 12 evidence routing and detail paging checks");
    }
    static void Check(bool value, string label) { if (!value) throw new Exception(label); }
}
