"""Validated detector runtime options shared by API and process lifecycle code."""

DEFAULT_FRAME_STRIDE = 3
MIN_FRAME_STRIDE = 1
MAX_USER_FRAME_STRIDE = 30
# Keep the existing high-stride EOF/diagnostic seam available to trusted
# deployment configuration. Public Mission/Pipeline requests use the lower
# user bound above so an interactive mistake cannot silently become a smoke run.
MAX_FRAME_STRIDE = 300


def resolve_frame_stride(
    value: int | None,
    *,
    fallback: int = DEFAULT_FRAME_STRIDE,
) -> int:
    """Return a bounded stride; one means every source frame is processed."""
    resolved = fallback if value is None else value
    if isinstance(resolved, bool) or not isinstance(resolved, int):
        raise ValueError("frame_stride must be an integer")
    if not MIN_FRAME_STRIDE <= resolved <= MAX_FRAME_STRIDE:
        raise ValueError(
            f"frame_stride must be between {MIN_FRAME_STRIDE} and {MAX_FRAME_STRIDE}"
        )
    return resolved
