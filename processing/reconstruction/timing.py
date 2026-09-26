"""Source-time provenance for explicitly selected inference frames."""

import re


def map_selected_frames(frames, selected_indices):
    """Map nondecreasing source positions, allowing skips and repetitions."""
    if not isinstance(frames, (list, tuple)) or not frames:
        raise ValueError("frames must be a nonempty list or tuple")
    if not isinstance(selected_indices, (list, tuple)) or not selected_indices:
        raise ValueError("selected_indices must be a nonempty list or tuple")

    seen_ids = set()
    offsets = []
    origin = previous_timestamp = None
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("each source frame must be a dictionary")
        frame_id = frame.get("frame_id")
        pts = frame.get("pts_ns")
        if type(frame_id) is not int or frame_id < 0 or frame_id in seen_ids:
            raise ValueError("frame_id must be a unique nonnegative integer")
        if not isinstance(pts, str) or re.fullmatch(r"-?[0-9]+", pts) is None:
            raise ValueError("pts_ns must be an ASCII decimal integer string")
        if type(frame.get("image_valid")) is not bool:
            raise ValueError("image_valid must be boolean")
        timestamp = int(pts)
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("source PTS must be strictly increasing")
        if origin is None:
            origin = timestamp
        try:
            offsets.append((timestamp - origin) / 1_000_000_000)
        except OverflowError as error:
            raise ValueError("source time offset exceeds float range") from error
        seen_ids.add(frame_id)
        previous_timestamp = timestamp

    result = []
    previous = -1
    for index, source in enumerate(selected_indices):
        if type(source) is not int or not 0 <= source < len(frames):
            raise ValueError("selection must be an in-range integer position")
        if source < previous:
            raise ValueError("selections must be nondecreasing")
        previous = source
        frame = frames[source]
        result.append({
            "inference_index": index,
            "source_frame_id": frame["frame_id"],
            "source_pts_ns": frame["pts_ns"],
            "source_time_s": offsets[source],
            "image_valid": frame["image_valid"],
        })
    return result
