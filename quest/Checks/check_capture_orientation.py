"""Check an MP4 from the on-Quest physio_capture_benchmark intent.

Usage: python3 quest/Checks/check_capture_orientation.py synthetic.mp4
Requires the existing ffmpeg executable. This does not open a camera.
"""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Pass the synthetic Unity capture benchmark MP4 path")
    video = Path(sys.argv[1]).resolve(strict=True)
    # Bound decoding to one 1280x960 frame; ignore metadata rotation so it cannot
    # conceal wrong row order in the actual encoded pixels.
    pixels = subprocess.check_output(
        [
            "ffmpeg", "-v", "error", "-noautorotate", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=1280:960", "-pix_fmt", "rgb24",
            "-f", "rawvideo", "pipe:1",
        ],
        timeout=15,
    )
    assert len(pixels) == 1280 * 960 * 3, "Missing or incomplete decoded frame"
    # Independent oracle: SetPixels32 starts at bottom-left. The benchmark's
    # y<height/2 red region must appear BELOW blue; its x<16 stripe stays LEFT.
    # https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Texture2D.SetPixels32.html
    failed = []
    for label, x, y, channel in (
        ("top blue", 640, 120, 2),
        ("bottom red", 640, 840, 0),
        ("left top green", 8, 120, 1),
        ("left bottom green", 8, 840, 1),
    ):
        offset = (y * 1280 + x) * 3
        rgb = pixels[offset:offset + 3]
        valid = rgb[channel] > 200 and max(rgb[i] for i in range(3) if i != channel) < 60
        print(f"{label}: {tuple(rgb)} {'PASS' if valid else 'FAIL'}")
        if not valid:
            failed.append(label)
    assert not failed, "Capture orientation mismatch: " + ", ".join(failed)
    print("PASS: Unity GPU readback to MP4 orientation")


if __name__ == "__main__":
    main()
