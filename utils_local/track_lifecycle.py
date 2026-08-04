"""Canonical read-only views over the image-trajectory lifecycle."""

from elements.FrameElement import FrameElement


def active_tracks_of(frame_element: FrameElement) -> dict:
    """Return tracks whose association lifecycle has not terminated."""
    explicit = getattr(frame_element, "active_tracks", None)
    if explicit is not None:
        return explicit
    return getattr(frame_element, "buffer_tracks", None) or {}


def mature_tracks_of(frame_element: FrameElement) -> dict:
    """Return the monotonic mature business-track view.

    Frames produced before the explicit lifecycle contract are filtered by the
    per-track eligibility flag. Objects without that historical flag are kept
    for compatibility with legacy/unit-created frames.
    """
    explicit = getattr(frame_element, "mature_tracks", None)
    if explicit is not None:
        return explicit
    return {
        track_id: track
        for track_id, track in active_tracks_of(frame_element).items()
        if bool(getattr(track, "trajectory_output_eligible", True))
    }


def mature_track_for_association(
    frame_element: FrameElement, association_id: int
):
    """Resolve a detector association ID into the mature lifecycle view."""
    track_map = (
        getattr(frame_element, "track_id_by_association", None)
        or getattr(frame_element, "formal_track_id_by_association", None)
        or {}
    )
    track_id = int(track_map.get(int(association_id), int(association_id)))
    return mature_tracks_of(frame_element).get(track_id)


def active_track_for_association(
    frame_element: FrameElement, association_id: int
):
    """Resolve a detector association ID without granting business maturity."""
    track_map = (
        getattr(frame_element, "track_id_by_association", None)
        or getattr(frame_element, "formal_track_id_by_association", None)
        or {}
    )
    track_id = int(track_map.get(int(association_id), int(association_id)))
    return active_tracks_of(frame_element).get(track_id)
