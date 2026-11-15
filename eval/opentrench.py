import argparse
import json
import os
import random
import re
import shutil
import sys
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from app.domain.models import UtilityType

HANDLE = "hestogpony/opentrench3d"
LIST_API = "https://api.kaggle.com/v1/datasets.DatasetApiService/ListDatasetFiles"
DATA_ROOT = Path(os.environ.get("OPENTRENCH3D_DIR", Path.home() / "datasets" / "opentrench3d"))
FILES_PATH = DATA_ROOT / "files.json"
RENDER_DIR = Path("eval/data/opentrench3d")
CASES_PATH = Path("eval/opentrench_cases.jsonl")
LICENCE = "CC BY-NC 4.0 (OpenTrench3D, Hansen et al. 2024)"

MAIN, OTHER, TRENCH, INACTIVE, MISC = 0, 1, 2, 3, 4
VISIBLE_MIN_FRACTION = 0.002
RENDER_WIDTH_PX = 1400
SELECTION_SEED = 0

AREA_TYPES: frozendict[str, UtilityType] = frozendict(
    {
        "Water_Area_1": UtilityType.WATER,
        "Water_Area_2": UtilityType.WATER,
        "Water_Area_3": UtilityType.WATER,
        "Water_Area_4": UtilityType.WATER,
        "Water_Area_5": UtilityType.WATER,
        "Heating_Area_1": UtilityType.DISTRICT_HEATING,
        "Heating_Area_2": UtilityType.DISTRICT_HEATING,
    }
)
_AREA_DIR = re.compile(r"/(Water_Area_\d|Heating_Area_2|Heating_Area_1_Finetuning_All)/")


@dataclass(frozen=True, slots=True)
class PointCloud:
    xyz: NDArray[np.float64]
    rgb: NDArray[np.uint8]
    cls: NDArray[np.uint8]


_EXPECTED_PROPERTIES = ["x", "y", "z", "red", "green", "blue", "class"]


def read_ply(path: Path) -> PointCloud:
    with path.open("rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError(f"{path} is not a PLY file")
        count, properties, fmt = 0, [], ""
        while (line := f.readline().decode("ascii").strip()) != "end_header":
            parts = line.split()
            if parts[:1] == ["format"]:
                fmt = parts[1]
            elif parts[:2] == ["element", "vertex"]:
                count = int(parts[2])
            elif parts[:1] == ["property"]:
                properties.append(parts[-1])
        if fmt != "ascii" or properties != _EXPECTED_PROPERTIES:
            raise ValueError(f"{path}: unsupported PLY ({fmt}, {properties})")
        data = np.loadtxt(f, dtype=np.float64, max_rows=count, ndmin=2)
    return PointCloud(
        xyz=data[:, :3],
        rgb=data[:, 3:6].astype(np.uint8),
        cls=data[:, 6].astype(np.uint8),
    )


@dataclass(frozen=True, slots=True)
class View:
    name: str
    elevation_deg: float
    from_other_side: bool = False


VIEWS: tuple[View, ...] = (View("top", 90), View("left", 50), View("right", 50, True))


def _project(
    cloud: PointCloud, view: View, width: int
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.float64], int]:
    c = cloud.xyz - cloud.xyz.mean(axis=0)
    horizontal = c[:, :2]
    _, _, vt = np.linalg.svd(horizontal - horizontal.mean(axis=0), full_matrices=False)
    along = vt[0]
    across = np.array([-along[1], along[0]]) * (-1 if view.from_other_side else 1)
    u, v, z = horizontal @ along, horizontal @ across, c[:, 2]
    e = np.radians(view.elevation_deg)
    screen_x = u * (-1 if view.from_other_side else 1)
    screen_y = v * np.sin(e) - z * np.cos(e)
    depth = -v * np.cos(e) - z * np.sin(e)
    scale = (width - 1) / max(float(np.ptp(screen_x)), 1e-9)
    height = int(float(np.ptp(screen_y)) * scale) + 1
    px = ((screen_x - screen_x.min()) * scale).astype(np.int64)
    py = ((screen_y - screen_y.min()) * scale).astype(np.int64)
    return px, py, depth, height


def render(
    cloud: PointCloud, view: View, width: int = RENDER_WIDTH_PX
) -> tuple[NDArray[np.uint8], NDArray[np.int16]]:
    px, py, depth, height = _project(cloud, view, width)
    order = np.argsort(-depth, kind="stable")
    image = np.zeros((height, width, 3), np.uint8)
    classes = np.full((height, width), -1, np.int16)
    image[py[order], px[order]] = cloud.rgb[order][:, ::-1]
    classes[py[order], px[order]] = cloud.cls[order]
    painted = (classes >= 0).astype(np.uint8) * 255
    gaps = np.asarray(cv2.dilate(painted, np.ones((3, 3), np.uint8)), np.uint8) & ~painted
    filled = np.asarray(cv2.inpaint(image, gaps, 2, cv2.INPAINT_TELEA), np.uint8)
    return filled, classes


def visible_fractions(classes: NDArray[np.int16]) -> dict[int, float]:
    counts = np.bincount(classes[classes >= 0].ravel(), minlength=5)
    return {c: round(float(counts[c]) / classes.size, 5) for c in range(5)}


class ViewTruth(BaseModel):
    file: str
    view: str
    main_visible: bool
    other_visible: bool
    inactive_visible: bool
    fractions: dict[int, float]


class OpenTrenchCase(BaseModel):
    case_id: str
    source: str
    area: str
    main_type: UtilityType
    split: str
    views: list[ViewTruth]

    @property
    def other_visible(self) -> bool:
        return any(v.other_visible for v in self.views)


def area_of(source: str) -> str:
    match = _AREA_DIR.search(f"/{source}")
    if match is None:
        raise ValueError(f"not an OpenTrench3D area path: {source}")
    return match[1].removesuffix("_Finetuning_All")


DEV_AREAS = frozenset({"Water_Area_2", "Heating_Area_2"})


def split_of(area: str) -> str:
    return "dev" if area in DEV_AREAS else "test"


def case_id_of(source: str) -> str:
    area = area_of(source)
    short = ("w" if area.startswith("Water") else "h") + area.rsplit("_", 1)[1]
    stem = Path(source).stem.lower().replace("area_", "a").replace("site_", "s")
    return f"ot_{short}_{re.sub(r'[^a-z0-9]+', '_', stem)}"


def view_truth(file: str, view: View, classes: NDArray[np.int16]) -> ViewTruth:
    fractions = visible_fractions(classes)
    return ViewTruth(
        file=file,
        view=view.name,
        main_visible=fractions[MAIN] >= VISIBLE_MIN_FRACTION,
        other_visible=fractions[OTHER] >= VISIBLE_MIN_FRACTION,
        inactive_visible=fractions[INACTIVE] >= VISIBLE_MIN_FRACTION,
        fractions=fractions,
    )


@dataclass(frozen=True, slots=True)
class RemoteFile:
    name: str
    size: int


def list_remote_files() -> list[RemoteFile]:
    files: list[RemoteFile] = []
    token: str | None = None
    while True:
        body = {"ownerSlug": "hestogpony", "datasetSlug": "opentrench3d", "pageSize": 200}
        if token:
            body["pageToken"] = token
        request = urllib.request.Request(
            LIST_API,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "crab-eval/0.1"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            data = json.load(response)
        files += [RemoteFile(f["name"], int(f.get("totalBytes", 0))) for f in data["datasetFiles"]]
        token = data.get("nextPageToken")
        if not token:
            return files


def select_files(
    files: Iterable[RemoteFile], *, per_area: int, max_bytes: int, seed: int = SELECTION_SEED
) -> list[RemoteFile]:
    by_area: dict[str, list[RemoteFile]] = defaultdict(list)
    for f in files:
        if f.name.endswith(".ply") and _AREA_DIR.search(f"/{f.name}") and f.size <= max_bytes:
            by_area[area_of(f.name)].append(f)
    rng = random.Random(seed)  # noqa: S311 (sampling, not security)
    chosen: list[RemoteFile] = []
    for area in sorted(by_area):
        pool = sorted(by_area[area], key=lambda f: f.name)
        chosen += rng.sample(pool, min(per_area, len(pool)))
    return chosen


def local_path(source: str) -> Path:
    return DATA_ROOT / area_of(source) / Path(source).name


def cmd_list(_: argparse.Namespace) -> int:
    files = list_remote_files()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    FILES_PATH.write_text(
        json.dumps([{"name": f.name, "size": f.size} for f in files], indent=1), encoding="utf-8"
    )
    print(f"{len(files)} files ({sum(f.size for f in files) / 1e9:.1f} GB) -> {FILES_PATH}")
    return 0


def _selection(args: argparse.Namespace) -> list[RemoteFile]:
    if not FILES_PATH.exists():
        cmd_list(args)
    files = [RemoteFile(**f) for f in json.loads(FILES_PATH.read_text(encoding="utf-8"))]
    return select_files(files, per_area=args.per_area, max_bytes=args.max_mb * 1_000_000)


def cmd_download(args: argparse.Namespace) -> int:
    import kagglehub  # type: ignore[import-untyped]  # dev dependency, used only here

    chosen = _selection(args)
    todo = [f for f in chosen if not local_path(f.name).exists()]
    print(
        f"{len(chosen)} point clouds selected, {len(todo)} to download "
        f"({sum(f.size for f in todo) / 1e9:.2f} GB uncompressed) -> {DATA_ROOT}"
    )
    if args.dry_run:
        return 0
    for f in todo:
        cached = Path(kagglehub.dataset_download(HANDLE, path=f.name))
        target = local_path(f.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(cached, target)
        print(f"  {target}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    chosen = _selection(args)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    cases: list[OpenTrenchCase] = []
    for f in chosen:
        path = local_path(f.name)
        if not path.exists():
            print(f"  missing {path} (run download first)", file=sys.stderr)
            continue
        cloud = read_ply(path)
        case_id = case_id_of(f.name)
        views = []
        for view in VIEWS:
            image, classes = render(cloud, view)
            name = f"{case_id}_{view.name}.jpg"
            cv2.imwrite(str(RENDER_DIR / name), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            views.append(view_truth(name, view, classes))
        area = area_of(f.name)
        cases.append(
            OpenTrenchCase(
                case_id=case_id,
                source=f.name,
                area=area,
                main_type=AREA_TYPES[area],
                split=split_of(area),
                views=views,
            )
        )
        print(f"  {case_id}: {[v.view for v in views if v.main_visible]} show the main utility")
    write_cases(cases)
    print(f"{len(cases)} cases -> {CASES_PATH}, images -> {RENDER_DIR}")
    return 0


def write_cases(cases: Sequence[OpenTrenchCase], path: Path = CASES_PATH) -> None:
    path.write_text("".join(c.model_dump_json() + "\n" for c in cases), encoding="utf-8")


def read_cases(path: Path = CASES_PATH) -> list[OpenTrenchCase]:
    return [
        OpenTrenchCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenTrench3D eval set")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    for name in ("download", "render"):
        p = sub.add_parser(name)
        p.add_argument("--per-area", type=int, default=3)
        p.add_argument("--max-mb", type=int, default=120, help="skip larger point clouds")
        if name == "download":
            p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return {"list": cmd_list, "download": cmd_download, "render": cmd_render}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
