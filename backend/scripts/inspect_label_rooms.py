"""OCR 방 라벨 seed → flood-fill 방 추출 시각 진단.

OCR 로 방 라벨(욕실/화장실/201호/승강기 등)을 잡고, 그 위치에서 벽 장벽 안으로
flood-fill 해 방 영역을 만들어 라벨링하는 결과를 눈으로 확인.

저장 (data/label_rooms_debug/):
  - label_rooms.png : 추출된 방 영역(반투명 색) + 라벨 텍스트

사용:
  python scripts/inspect_label_rooms.py --image data/uploads/xxx.png --auto-prob

참고: openings(문/창) 는 standalone 에선 비어 있어 문 gap 으로 flood 가 샐 수 있음.
운영 fusion 은 openings 로 gap 을 막아 더 깔끔함.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.schemas.scene import Wall  # noqa: E402
from app.services.floorplan.wall_extraction import wall_extractor  # noqa: E402
from app.services.floorplan.wall_extraction_helpers import ocr, dimension_matching as dm  # noqa: E402
from app.services.floorplan.geometry_service import GeometryService, classify_room_label  # noqa: E402

_UNET_OUT = _BACKEND_ROOT.parents[1] / "rf-service" / "apps" / "ai_api" / "data" / "output" / "unet"


def _find_prob(img_aspect, tol=0.06):
    if not _UNET_OUT.exists():
        return None
    npys = list(_UNET_OUT.rglob("*_wall_prob.npy"))
    if not npys:
        return None
    matched = []
    for p in npys:
        try:
            shp = np.load(str(p), mmap_mode="r").shape
            if abs((shp[1] / shp[0]) - img_aspect) / img_aspect <= tol:
                matched.append(p)
        except Exception:
            pass
    pool = matched or npys
    return max(pool, key=lambda p: p.stat().st_mtime)


def main() -> None:
    ap = argparse.ArgumentParser(description="라벨 seed flood-fill 방 추출 진단")
    ap.add_argument("--image", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path)
    g.add_argument("--auto-prob", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/label_rooms_debug"))
    ap.add_argument("--scale", type=float, default=None)
    args = ap.parse_args()

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        sys.exit(f"이미지 디코드 실패: {args.image}")
    h, w = bgr.shape[:2]
    prob_path = args.prob if args.prob else _find_prob(w / h)
    if prob_path is None:
        sys.exit("prob map 없음")
    print(f"이미지: {args.image} ({w}x{h})\nprob  : {prob_path}")

    # 벽
    walls_xy = wall_extractor.execute_from_prob_map(prob_path, image_path=args.image).walls
    walls = [Wall(id=str(i), x1=a, y1=b, x2=c, y2=d, thickness=0.15)
             for i, (a, b, c, d) in enumerate(walls_xy)]
    print(f"벽 {len(walls)}개")

    # OCR → 방 라벨 seed
    entries = ocr.detect_text_entries(args.image)
    seeds = []
    for e in entries:
        cls = classify_room_label(e.text)
        if cls is None:
            continue
        cx = (e.bbox[0] + e.bbox[2]) / 2.0
        cy = (e.bbox[1] + e.bbox[3]) / 2.0
        seeds.append((cx, cy, cls[0], cls[1]))
    print(f"방 라벨 seed {len(seeds)}개: {[s[2] for s in seeds]}")

    # scale (area 필터용) — 지정 없으면 OCR 교차검증, 실패 시 0.02
    scale = args.scale
    if scale is None:
        wall_coords = [[wl.x1, wl.y1, wl.x2, wl.y2] for wl in walls]
        est = dm.estimate_scale_crossvalidated(entries, wall_coords)
        scale = est.scale_m_per_px if est else 0.02
    print(f"scale = {scale:.5f} m/px")

    geo = GeometryService(w, h, scale_ratio=scale)
    rooms = geo.extract_rooms_from_labels(walls, [], seeds)
    print(f"\n추출된 방 {len(rooms)}개:")
    for r in rooms:
        print(f"  {r.name}({r.type})  area={r.area}m2")

    # 오버레이
    args.out.mkdir(parents=True, exist_ok=True)
    ov = bgr.copy()
    rng = np.random.default_rng(0)
    for r in rooms:
        pts = np.array(r.points, dtype=np.int32)
        col = tuple(int(c) for c in rng.integers(60, 220, size=3))
        layer = ov.copy()
        cv2.fillPoly(layer, [pts], col)
        ov = cv2.addWeighted(layer, 0.35, ov, 0.65, 0)
        cv2.polylines(ov, [pts], True, col, 2)
        cx = int(np.mean(pts[:, 0])); cy = int(np.mean(pts[:, 1]))
        cv2.putText(ov, r.name, (cx - 20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.imwrite(str(args.out / "label_rooms.png"), ov)
    print(f"\n→ {args.out / 'label_rooms.png'}")


if __name__ == "__main__":
    main()
