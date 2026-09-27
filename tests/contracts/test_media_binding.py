"""Bind encoded frames without rounding away the original camera clock."""

from copy import deepcopy
from fractions import Fraction

import pytest

from processing.contracts import generate_fixture, read_json_file, validate_sidecar
from processing.reconstruction.runtime import bind_pts, plan_input


def capture(tmp_path):
    generate_fixture(tmp_path)
    doc = read_json_file(tmp_path / "capture_sidecar.json")
    doc["capture"]["gaps"] = []
    doc["camera"].update(calibration_status="estimated", distortion_model="none",
                         distortion_coefficients=[],
                         intrinsics={"fx": 500, "fy": 500, "cx": 320, "cy": 240})
    doc["media"] = {"binding": "indexed_presentation_time_us",
                    "presentation_time_us": ["0", "40000", "110000", "200000"]}
    for frame in doc["frames"]:
        frame["image_valid"] = True
        frame["pts_ns"] = str(int(frame["pts_ns"]) + 17)
    doc["clock"]["origin_pts_ns"] = doc["frames"][0]["pts_ns"]
    return doc


def test_explicit_mapping_preserves_original_sub_microsecond_pts(tmp_path):
    doc = capture(tmp_path)
    original = deepcopy(doc)
    validate_sidecar(doc)
    plan = plan_input(doc)
    decoded = [(i, Fraction(int(value), 1_000_000))
               for i, value in enumerate(doc["media"]["presentation_time_us"])]
    assert bind_pts(doc["frames"], decoded, 0, media=doc["media"]) == [0, 1, 2, 3]
    assert plan["media"] == doc["media"]
    assert plan["frame_mapping"][0]["source_pts_ns"].endswith("017")
    assert doc == original


@pytest.mark.parametrize("values", [[], ["0"], ["0", "40000", "40000", "200000"],
                                  ["0", "110000", "40000", "200000"],
                                  ["0", "40000", "110000", "-1"],
                                  ["0", "40000", "110000", 200000],
                                  ["0", "40000", "110000", "1" * 31]])
def test_malformed_media_mapping_rejected_by_contract_and_runtime(tmp_path, values):
    doc = capture(tmp_path)
    doc["media"]["presentation_time_us"] = values
    with pytest.raises(ValueError):
        validate_sidecar(doc)
    with pytest.raises(ValueError):
        plan_input(doc)


def test_same_count_wrong_media_pts_and_reordered_frames_fail(tmp_path):
    doc = capture(tmp_path)
    decoded = [(i, Fraction(int(value), 1_000_000))
               for i, value in enumerate(doc["media"]["presentation_time_us"])]
    for rows in (decoded[:-1], decoded + [(4, Fraction(1))], decoded[::-1],
                 [(i, time + Fraction(1, 1000)) for i, time in decoded]):
        with pytest.raises(ValueError):
            bind_pts(doc["frames"], rows, 0, media=doc["media"])


def test_explicit_binding_rejects_offset_and_unknown_binding(tmp_path):
    doc = capture(tmp_path)
    with pytest.raises(ValueError):
        bind_pts(doc["frames"], [], 1, media=doc["media"])
    doc["media"]["binding"] = "count-only"
    with pytest.raises(ValueError):
        validate_sidecar(doc)
    with pytest.raises(ValueError):
        plan_input(doc)


@pytest.mark.parametrize("origin", ["0", "01000000017", "-1", "1" * 31])
def test_standalone_runtime_rejects_mismatched_or_noncanonical_source_origin(tmp_path, origin):
    doc = capture(tmp_path)
    doc["clock"]["origin_pts_ns"] = origin
    with pytest.raises(ValueError):
        plan_input(doc)


@pytest.mark.parametrize("timescale", [1_000_000, 90_000])
def test_real_codec_roundtrip_with_separate_original_clock(tmp_path, timescale):
    av = pytest.importorskip("av")
    from processing.reconstruction.runtime import prepare_video

    doc = capture(tmp_path)
    doc["image"].update(width_px=64, height_px=48)
    video = tmp_path / "source.mp4"
    with av.open(str(video), "w", options={"video_track_timescale": str(timescale)}) as output:
        stream = output.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        stream.time_base = stream.codec_context.time_base = Fraction(1, 1_000_000)
        stream.options = {"bf": "0", "crf": "0"}
        for i, pts in enumerate(doc["media"]["presentation_time_us"]):
            frame = av.VideoFrame(64, 48, "rgb24")
            for plane in frame.planes:
                plane.update(bytes([i * 50]) * plane.buffer_size)
            frame.pts, frame.time_base = int(pts) + i * 17, Fraction(1, 1_000_000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    with av.open(str(video)) as encoded:
        mux_pts = [Fraction(frame.pts) * frame.time_base for frame in encoded.decode(video=0)]
    # Mirror Android MediaExtractor's integer division, not rounded microseconds.
    doc["media"]["presentation_time_us"] = [str(int(pts * 1_000_000)) for pts in mux_pts]
    if timescale == 90_000:
        assert any(round(pts * 1_000_000) != int(pts * 1_000_000) for pts in mux_pts)
    plan = plan_input(doc)
    prepare_video(video, tmp_path / "prepared.mp4", plan, 0)
    assert plan["decoder_binding"]["binding"] == "indexed_presentation_time_us"
    assert plan["source_frames"] == doc["frames"]
    assert plan["frame_mapping"][0]["source_pts_ns"] == "1000000017"
    with av.open(str(tmp_path / "prepared.mp4")) as output:
        assert len(list(output.decode(video=0))) == len(plan["selected_indices"])
