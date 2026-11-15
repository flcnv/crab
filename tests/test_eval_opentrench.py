from pathlib import Path

import numpy as np
import pytest

from app.domain.models import UtilityType
from eval.opentrench import (
    AREA_TYPES,
    INACTIVE,
    MAIN,
    OTHER,
    TRENCH,
    PointCloud,
    RemoteFile,
    View,
    area_of,
    case_id_of,
    read_ply,
    render,
    select_files,
    split_of,
    view_truth,
)


def write_ply(path: Path, rows: list[tuple[float, float, float, int, int, int, int]]) -> Path:
    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(rows)}",
        *(f"property float {p}" for p in "xyz"),
        *(f"property uchar {p}" for p in ("red", "green", "blue", "class")),
        "end_header",
    ]
    body = [" ".join(str(v) for v in row) for row in rows]
    path.write_text("\n".join(header + body) + "\n", encoding="ascii")
    return path


def trench(main_on_top: bool = True) -> PointCloud:
    xs, ys = np.meshgrid(np.linspace(0, 4, 200), np.linspace(0, 1, 50))
    floor = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)])
    px = np.linspace(0, 4, 400)
    pipe = np.column_stack(
        [px, np.full_like(px, 0.5), np.full_like(px, 0.1 if main_on_top else -0.1)]
    )
    xyz = np.vstack([floor, pipe])
    cls = np.concatenate([np.full(len(floor), TRENCH), np.full(len(pipe), MAIN)]).astype(np.uint8)
    rgb = np.where(cls[:, None] == MAIN, [30, 30, 30], [140, 110, 80]).astype(np.uint8)
    return PointCloud(xyz=xyz, rgb=rgb, cls=cls)


def test_read_ply(tmp_path: Path) -> None:
    path = write_ply(tmp_path / "a.ply", [(0, 0, 0, 255, 0, 0, 2), (1.5, 2, -0.5, 0, 0, 255, 0)])
    cloud = read_ply(path)
    assert cloud.xyz.shape == (2, 3)
    assert cloud.rgb[1].tolist() == [0, 0, 255]
    assert cloud.cls.tolist() == [2, 0]


def test_read_ply_rejects_other_layouts(tmp_path: Path) -> None:
    path = tmp_path / "b.ply"
    path.write_text("ply\nformat binary_little_endian 1.0\nelement vertex 0\nend_header\n")
    with pytest.raises(ValueError, match="unsupported PLY"):
        read_ply(path)


def test_render_shows_the_pipe_from_above_and_hides_a_buried_one() -> None:
    top = View("top", 90)
    image, classes = render(trench(main_on_top=True), top, width=200)
    assert image.shape[1] == 200
    assert image.ndim == 3
    assert view_truth("x.jpg", top, classes).main_visible

    _, hidden = render(trench(main_on_top=False), top, width=200)
    truth = view_truth("y.jpg", top, hidden)
    assert not truth.main_visible
    assert truth.fractions[TRENCH] > 0.5


def test_view_truth_thresholds() -> None:
    classes = np.full((100, 100), TRENCH, np.int16)
    classes[0, :30] = OTHER
    classes[1, :10] = INACTIVE
    truth = view_truth("f.jpg", View("top", 90), classes)
    assert (truth.main_visible, truth.other_visible, truth.inactive_visible) == (False, True, False)


def test_area_split_and_case_ids() -> None:
    source = "OpenTrench3D/OpenTrench3D/Heating_Area_1_Finetuning_All/Area_1_Site_6_part_2.ply"
    assert area_of(source) == "Heating_Area_1"
    assert AREA_TYPES[area_of(source)] is UtilityType.DISTRICT_HEATING
    assert case_id_of(source) == "ot_h1_a1_s6_part_2"
    assert split_of("Water_Area_2") == "dev"
    assert split_of("Water_Area_3") == "test"
    with pytest.raises(ValueError, match="not an OpenTrench3D area path"):
        area_of("OpenTrench3D/OpenTrench3D/Heating_Area_1_Finetuning_5/Area_1_Site_1.ply")


def test_select_files_is_seeded_per_area_and_skips_duplicates_and_big_files() -> None:
    root = "OpenTrench3D/OpenTrench3D"
    files = [RemoteFile(f"{root}/Water_Area_1/Area_1_Site_{i:02d}.ply", 10) for i in range(10)]
    files += [RemoteFile(f"{root}/Heating_Area_2/Area_2_Site_{i}.ply", 10) for i in range(5)]
    files += [RemoteFile(f"{root}/Heating_Area_1_Finetuning_10/Area_1_Site_1.ply", 10)]
    files += [RemoteFile(f"{root}/Water_Area_1/Area_1_Site_99.ply", 10_000)]

    chosen = select_files(files, per_area=3, max_bytes=100)

    assert chosen == select_files(list(reversed(files)), per_area=3, max_bytes=100)
    assert sorted(area_of(f.name) for f in chosen) == ["Heating_Area_2"] * 3 + ["Water_Area_1"] * 3
    assert all("Finetuning_10" not in f.name and "Site_99" not in f.name for f in chosen)
