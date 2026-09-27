"""Explicit mux timestamps preserve the independent original camera clock."""

from itertools import pairwise


def validate_media_mapping(media, frame_count):
    """Return verified per-frame encoded microseconds, or no explicit mapping."""
    if media is None:
        return None
    if (type(media) is not dict or set(media) != {"binding", "presentation_time_us"}
            or media["binding"] != "indexed_presentation_time_us"):
        raise ValueError("Unsupported media timestamp binding")
    values = media["presentation_time_us"]
    if type(values) is not list or len(values) != frame_count or not values:
        raise ValueError("Media timestamp mapping must match every source frame")
    if any(type(value) is not str or not 1 <= len(value) <= 30
           or not value.isascii() or not value.isdigit()
           or (len(value) > 1 and value.startswith("0")) for value in values):
        raise ValueError("Media timestamps must be canonical nonnegative integer strings")
    times = [int(value) for value in values]
    if any(a >= b for a, b in pairwise(times)):
        raise ValueError("Media timestamps must strictly increase")
    return times
