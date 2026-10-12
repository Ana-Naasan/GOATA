#!/usr/bin/env node
/**
 * Rebuild the README banner from the public project film.
 * Run: node docs/media/render_banner.mjs
 * Requires Node.js, FFmpeg, rsvg-convert, and Helvetica or Arial.
 * No network, npm packages, models, or new participant recordings are used.
 */
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const destination = dirname(fileURLToPath(import.meta.url));
const source = join(destination, 'demo.mp4');
const expectedSource = '0c4be5014357f74aae8a369884177aee83b97a616f2bc33b24f97d8593b3f73e';
if (createHash('sha256').update(readFileSync(source)).digest('hex') !== expectedSource) {
  throw new Error('demo.mp4 differs from the documented film. Review the excerpt before rebuilding.');
}
const start = 67.5;
const duration = 2.5;
const fps = 12;
const width = 960;
const height = 628;
const temporary = mkdtempSync(join(tmpdir(), 'n3-goata-film-banner-'));
const ffmpeg = args => execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args]);
try {
  const overlay = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="628" viewBox="0 0 960 628">
    <rect width="960" height="88" fill="#f3f2e9"/>
    <g font-family="Helvetica,Arial,sans-serif" fill="#14231b">
      <text x="28" y="29" font-size="14" font-weight="700" letter-spacing="1.6">N3 GOATA</text>
      <text x="28" y="65" font-size="29" font-weight="700">See your stride. <tspan fill="#164bff">Differently.</tspan></text>
    </g>
    <g font-family="Menlo,Consolas,monospace" fill="#52645b" text-anchor="end">
      <text x="932" y="29" font-size="12">META QUEST 3</text>
      <text x="932" y="62" font-size="11">FROM THE DEMO FILM</text>
    </g>
  </svg>`;
  const overlaySvg = join(temporary, 'overlay.svg');
  const overlayPng = join(temporary, 'overlay.png');
  writeFileSync(overlaySvg, overlay);
  execFileSync('rsvg-convert', ['--output', overlayPng, overlaySvg]);

  const frames = join(temporary, 'frame-%03d.png');
  ffmpeg([
    '-ss', String(start), '-t', String(duration), '-i', source,
    '-loop', '1', '-i', overlayPng,
    '-filter_complex',
    `[0:v]fps=${fps},scale=960:540:flags=lanczos,pad=960:628:0:88:color=0xf3f2e9[clip];[clip][1:v]overlay=shortest=1:format=auto,format=rgb24[out]`,
    '-map', '[out]', '-frames:v', String(duration * fps), frames,
  ]);
  const gif = join(temporary, 'banner.gif');
  ffmpeg([
    '-framerate', String(fps), '-i', frames,
    '-filter_complex',
    '[0:v]split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle',
    '-loop', '0', gif,
  ]);
  const contents = readFileSync(gif);
  if (contents.length > 8_000_000) throw new Error(`Banner exceeds 8 MB: ${contents.length} bytes`);
  const still = readFileSync(join(temporary, 'frame-001.png')).toString('base64');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description">
    <title id="title">N3 Goata. See your stride. Differently.</title>
    <desc id="description">Still from the public project film at 01:07.5. A translucent blue reconstructed body and skeleton appear in the recorded Quest room view.</desc>
    <image width="${width}" height="${height}" href="data:image/png;base64,${still}"/>
  </svg>\n`;
  writeFileSync(join(destination, 'n3-goata-banner.svg'), svg);
  writeFileSync(join(destination, 'n3-goata-banner.gif'), contents);
  console.log(`Film excerpt ${start}s to ${start + duration}s; ${width}x${height}; ${duration * fps} frames; ${duration}s; ${contents.length} GIF bytes.`);
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
