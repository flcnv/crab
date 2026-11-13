from collections.abc import Sequence

from app.domain.models import MediaMetadata


def merge_image_metadata(items: Sequence[MediaMetadata]) -> MediaMetadata:
    """One job, many photos: first known location, earliest capture time, first resolution."""
    if not items:
        raise ValueError("no metadata to merge")
    times = [m.captured_at for m in items if m.captured_at is not None]
    return MediaMetadata(
        kind="image",
        width=items[0].width,
        height=items[0].height,
        location=next((m.location for m in items if m.location is not None), None),
        # .timestamp() also orders a mix of naive (EXIF without offset) and aware datetimes
        captured_at=min(times, key=lambda t: t.timestamp()) if times else None,
    )
