# README media

These files present the N3 Goata project. They are presentation media, not inputs
to the app or evidence of new validation.

| File | Source and purpose |
|---|---|
| `n3-goata-banner.gif` | Actual Quest replay excerpt from `demo.mp4`, 01:07.5 to 01:10.0. A 2.5-second loop with 30 frames at 960 × 628, including the title strip. |
| `n3-goata-banner.svg` | Static first frame of the same banner, with its image embedded. |
| `demo-poster.jpg` | Unmodified [project-film poster](https://n3-goata.vercel.app/demo-poster.jpg?v=requested-edits), retrieved October 12, 2026. |
| `demo.mp4` | Smaller copy of the [public project film](https://n3-goata.vercel.app/HtH-Demo-N3.mp4?v=requested-edits), included at the project owner's request. |
| `benchmark.json` | Unmodified [website benchmark summary](https://n3-goata.vercel.app/benchmark.json), retrieved October 12, 2026. The half-second-chunk runner and raw event files are not included in this repo. |

The README uses a [GitHub video attachment](https://github.com/user-attachments/assets/6b5f804e-f4cf-48c7-8f9c-bac253dac2b9)
so the full film plays inline on GitHub. The attachment contains the same bytes
as `demo.mp4`. The MP4 remains in the repository for local playback and download.

Keep the attachment URL on its own paragraph in the README. GitHub turns that
URL into a native video player. A Markdown image link or a raw HTML video tag
does not produce the same player. The banner links to the README's demo section.

The only video exception in `.gitignore` is `/docs/media/demo.mp4`. Original
participant recordings remain excluded. The banner reuses only the already-public
film. It introduces no new recordings. These files do not grant a project-wide
license to third-party assets.

The website benchmark is separate from the checked-in
[two-second-chunk experiment](../../experiments/streaming_inference/rtx3070-640-15.json).
That experiment records 3.56 seconds after input stops to a decode-verified video.
The website summary reports a 2.27-second median from a different run. Neither
measurement includes the complete Quest capture-to-display path.

## Rebuild the banner

From the repository root, run:

```sh
node docs/media/render_banner.mjs
```

The generator uses the included `demo.mp4`, Node.js, `rsvg-convert` from librsvg,
FFmpeg, and Helvetica or Arial. It checks the film's SHA-256 before selecting the
documented interval. It needs no npm packages or network connection.

The generator resizes the full 16:9 picture to 960 × 540 and samples it at 12 fps.
It adds an 88-pixel title strip above the footage.
It does not crop the room view, replace the body, interpolate new motion, or
change the excerpt's playback duration. The animation loops at the end of the
excerpt, with a visible transition back to its first frame.

Temporary frames are removed after rendering. The script writes the GIF and
self-contained static SVG beside itself. The GIF is 7,253,970 bytes, below its
eight-megabyte size limit. The README offers the static SVG for readers who prefer
a still image. The film excerpt shows the recorded app appearance. It does not
establish clinical accuracy or new end-to-end validation.

## Re-encode the public film

Download the linked public film to a local file. The repo copy keeps the full
136.77-second film and its audio, encoded as 1280 × 720 H.264 at 24 fps with AAC
audio. It is 11,801,525 bytes, compared with the source's 73,226,966 bytes.
The website link retains access to the original 1920 × 1080 version.

Replace the input path below with the downloaded film. This command overwrites
the generated repo copy:

```sh
ffmpeg -hide_banner -loglevel error -y -i /path/to/public-project-film.mp4 \
	-map 0:v:0 -map '0:a:0?' -vf 'scale=1280:-2,fps=24' \
	-c:v libx264 -preset medium -crf 29 -maxrate 900k -bufsize 1800k \
	-pix_fmt yuv420p -c:a aac -b:a 96k -map_metadata -1 \
	-movflags +faststart docs/media/demo.mp4
```

The encoding removes embedded metadata and puts the MP4 index before the media
data for playback while downloading. It does not trim or rearrange the film.

SHA-256 of the source retrieved on October 12, 2026:

```text
753bb0ad995001aed78e78fabeea9ee03673474d316dc0094c76f41dfbf93fab
```

SHA-256 of the included repo copy:

```text
0c4be5014357f74aae8a369884177aee83b97a616f2bc33b24f97d8593b3f73e
```

FFmpeg 9.0.2 decoded the complete video and audio without errors. Chrome loaded
the local MP4 at 1280 × 720, reported 136.766667 seconds, and began playback.
The banner generator ran with Node.js 26.0.0 and librsvg 2.62.1. Re-encoding on
different tool versions can produce different bytes.
