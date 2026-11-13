"""Keyframe selection: which sampled video frames are worth sending to the vision model.

Adapters measure each frame (sharpness, perceptual hash); the choice itself is pure logic.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FrameCandidate:
    index: int  # position in the sampled sequence (time order)
    sharpness: float  # variance of Laplacian; higher = sharper
    phash: int  # 64-bit perceptual hash


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def select_keyframes(
    candidates: Sequence[FrameCandidate],
    *,
    max_frames: int,
    min_sharpness: float,
    min_hash_distance: int,
) -> list[FrameCandidate]:
    """Sharpest-first greedy pick of visually distinct frames, returned in time order.

    - Frames below `min_sharpness` are dropped; if all are blurry, the sharpest one is kept.
    - A frame closer than `min_hash_distance` bits to an already kept frame is a duplicate;
      because we go sharpest-first, the sharper copy of a duplicate pair wins.
    """
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
