#nullable enable
using System;
using System.Collections.Generic;

namespace Physio.Viewer
{
    /// <summary>Source identity, never equal elapsed time, decides whether evidence may seek the body.</summary>
    public static class ReviewEvidence
    {
        public static bool CanSeek(Guid? replayTake, Guid evidenceTake, double start, double end) =>
            replayTake.HasValue && replayTake.Value == evidenceTake &&
            !double.IsNaN(start) && !double.IsInfinity(start) &&
            !double.IsNaN(end) && !double.IsInfinity(end) && start >= 0 && end >= start;

        public static string TestName(string test) => test switch
        {
            "elk" => "KERAAL ELK · seated flank stretch",
            "rtk" => "KERAAL RTK · seated torso rotation",
            "barefoot" => "Barefoot assessment",
            _ => throw new ArgumentException("Unknown test.", nameof(test))
        };

        public static string[] Pages(string text, int maxCharacters = 420)
        {
            if (maxCharacters < 1) throw new ArgumentOutOfRangeException(nameof(maxCharacters));
            if (text.Length == 0) return new[] { "" };
            var pages = new List<string>();
            for (var offset = 0; offset < text.Length;)
            {
                var length = Math.Min(maxCharacters, text.Length - offset);
                if (offset + length < text.Length)
                {
                    var space = text.LastIndexOf(' ', offset + length - 1, length);
                    if (space > offset + length / 2) length = space - offset + 1;
                }
                pages.Add(text.Substring(offset, length));
                offset += length;
            }
            return pages.ToArray();
        }
    }
}
