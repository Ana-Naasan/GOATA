#nullable enable

namespace Physio.Viewer
{
    internal static class HandMenuPressEdge
    {
        public static bool Update(bool readSucceeded, bool menuPressed, ref bool armed)
        {
            if (!readSucceeded) return false;
            if (!menuPressed) { armed = true; return false; }
            if (!armed) return false;
            armed = false;
            return true;
        }
    }
}
