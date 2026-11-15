from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameCandidate:
    index: int
    sharpness: float
    phash: int


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def select_keyframes(
    candidates: Sequence[FrameCandidate],
    *,
    max_frames: int,
    min_sharpness: float,
    min_hash_distance: int,
) -> list[FrameCandidate]:
    if not candidates or max_frames <= 0:
        return []

    sharp = [c for c in candidates if c.sharpness >= min_sharpness]
    if not sharp:
        sharp = [max(candidates, key=lambda c: c.sharpness)]

    kept: list[FrameCandidate] = []
    for c in sorted(sharp, key=lambda c: c.sharpness, reverse=True):
        if all(hamming(c.phash, k.phash) >= min_hash_distance for k in kept):
            kept.append(c)
            if len(kept) == max_frames:
                break
    return sorted(kept, key=lambda c: c.index)
