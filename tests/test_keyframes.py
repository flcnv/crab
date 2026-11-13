from app.domain.services import FrameCandidate, hamming, select_keyframes


def c(index: int, sharpness: float, phash: int) -> FrameCandidate:
    return FrameCandidate(index=index, sharpness=sharpness, phash=phash)


def pick(cands: list[FrameCandidate], max_frames: int = 10) -> list[int]:
    return [
        k.index
        for k in select_keyframes(
            cands, max_frames=max_frames, min_sharpness=50, min_hash_distance=4
        )
    ]


def test_hamming() -> None:
    assert hamming(0b1011, 0b0001) == 2


def test_drops_blurry_and_keeps_time_order() -> None:
    assert pick([c(0, 80, 0x00), c(1, 10, 0xFF), c(2, 90, 0xF0F0)]) == [0, 2]


def test_all_blurry_keeps_the_sharpest() -> None:
    assert pick([c(0, 5, 0x0), c(1, 20, 0xFF), c(2, 9, 0xF00)]) == [1]


def test_duplicates_keep_the_sharper_copy() -> None:
    # 0 and 1 differ by 1 bit (duplicate); 1 is sharper
    assert pick([c(0, 60, 0b0000), c(1, 95, 0b0001), c(2, 70, 0xFFFF)]) == [1, 2]


def test_caps_at_max_frames_preferring_sharp() -> None:
    cands = [c(i, 50 + i, 0xF << (4 * i)) for i in range(6)]  # pairwise 8 bits apart
    assert pick(cands, max_frames=3) == [3, 4, 5]


def test_empty_input() -> None:
    assert pick([]) == []
