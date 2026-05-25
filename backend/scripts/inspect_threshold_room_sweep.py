"""threshold 를 강제로 바꿔가며 방 폐합 결과(벽 수·방 수·방 면적)를 비교.

가설 검증용: scorer 는 후보(0.25~0.60) 중 0.25 를 best 로 고르지만, 그보다 더 낮은
threshold 를 쓰면 내부 칸막이 벽이 살아나 방이 더 닫히는가?

각 threshold 마다 fusion 의 방 폐합 단계를 동일하게 돌린다:
  execute_from_prob_map(threshold=t) → bridge+snap → 문/창 합성 → polygonize
  → 라벨 flood-fill 병합.
문/창(YOLO)·OCR·scale 은 threshold 와 무관하므로 한 번만 계산해 재사용.

사용 (전체 단계 = AI venv 권장):
  rf-service/apps/ai_api/.venv/Scripts/python.exe \
      web-platform/backend/scripts/inspect_threshold_room_sweep.py \
      --image web-platform/backend/data/uploads/xxx.jpg --auto-prob

  # threshold 목록 직접 지정
  ... --thresholds 0.10,0.15,0.20,0.25,0.30,0.35

결과 (data/threshold_room_sweep/):
  rooms_t010.png ...  : threshold 별 (벽=회색 + 방=채움) 오버레이
  _grid.png           : 비교 그리드 한 장 (라벨: thr / walls / rooms / area)
"""
from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_ROOT.parents[1]
_RF_ROOT = _REPO_ROOT / "rf-service"
for p in (_BACKEND_ROOT, _RF_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_g = types.ModuleType("geoalchemy2"); _gs = types.ModuleType("geoalchemy2.shape")
_gs.from_shape = _gs.to_shape = lambda *a, **k: None  # type: ignore[attr-defined]
_g.shape = _gs  # type: ignore[attr-defined]
sys.modules.setdefault("geoalchemy2", _g)
sys.modules.setdefault("geoalchemy2.shape", _gs)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.schemas.scene import Opening, Wall  # noqa: E402
from app.services.floorplan.wall_extraction import wall_extractor  # noqa: E402
from app.services.floorplan.wall_extraction_helpers import ocr  # noqa: E402
from app.services.floorplan.wall_extraction_helpers import dimension_matching as dm  # noqa: E402
from app.services.floorplan.geometry_service import (  # noqa: E402
    GeometryService,
    classify_room_label,
)
from app.geometry.matching import assign_wall_refs  # noqa: E402
from app.geometry.reconciliation import (  # noqa: E402
    bridge_collinear_walls,
    project_openings_onto_walls,
    snap_wall_endpoints,
    synthesize_opening_wall_segments,
)
from shapely.geometry import Polygon as _Poly  # noqa: E402

_UNET_OUT = _RF_ROOT / "apps" / "ai_api" / "data" / "output" / "unet"
_YOLO_WEIGHTS = _RF_ROOT / "apps" / "trainer" / "src" / "models" / "yolo" / "best.pt"


class _Det:
    def __init__(self, class_name, bbox_xyxy, score=1.0):
        self.class_name = class_name
        self.bbox_xyxy = bbox_xyxy
        self.score = score
        self.id = ""


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


def _detect_openings(bgr, conf):
    try:
        from packages.ai_runtime.yolo_runtime import run_yolo_inference_result
    except Exception as exc:
        print(f"  ⚠️ YOLO 미사용 ({type(exc).__name__}) → 문/창 0개 (AI venv 로 실행 시 전체).")
        return []
    if not _YOLO_WEIGHTS.exists():
        print(f"  ⚠️ YOLO weights 없음 → 문/창 0개")
        return []
    model, result, _ = run_yolo_inference_result(
        bgr, weights_path=str(_YOLO_WEIGHTS), conf_threshold=conf,
        preferred_device="", default_device="cpu",
    )
    names = model.names if isinstance(model.names, dict) else {}
    dets = []
    if result.boxes is not None:
        for box in result.boxes:
            cls = names.get(int(box.cls.item()), str(int(box.cls.item())))
            if cls not in {"door", "window"}:
                continue
            xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
            dets.append(_Det(cls, xyxy, float(box.conf.item())))
    return dets


def _draw_rooms(base, rooms):
    out = base.copy()
    rng = np.random.default_rng(0)
    for i, r in enumerate(rooms):
        try:
            pts = np.array(r.points, dtype=np.int32)
        except Exception:
            continue
        col = tuple(int(c) for c in rng.integers(60, 220, size=3))
        layer = out.copy()
        cv2.fillPoly(layer, [pts], col)
        out = cv2.addWeighted(layer, 0.40, out, 0.60, 0)
        cv2.polylines(out, [pts], True, col, 2, cv2.LINE_AA)
    return out


def _label_tile(img, lines):
    t = img.copy()
    h, w = t.shape[:2]
    bar = max(46, int(h * 0.11))
    cv2.rectangle(t, (0, 0), (w, bar), (35, 35, 35), -1)
    fs = max(0.5, w / 1000)
    for k, ln in enumerate(lines):
        cv2.putText(t, ln, (8, int(bar * (0.42 + 0.46 * k))),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 235, 0), 1, cv2.LINE_AA)
    return t


def _grid(tiles, cols, cell_w=520):
    ar = tiles[0].shape[0] / tiles[0].shape[1]
    cw, ch = cell_w, int(cell_w * ar)
    res = [cv2.resize(t, (cw, ch)) for t in tiles]
    rows = (len(res) + cols - 1) // cols
    pad = 8
    g = np.full((rows * ch + (rows + 1) * pad, cols * cw + (cols + 1) * pad, 3), 22, np.uint8)
    for i, t in enumerate(res):
        r, c = divmod(i, cols)
        g[pad + r * (ch + pad):pad + r * (ch + pad) + ch,
          pad + c * (cw + pad):pad + c * (cw + pad) + cw] = t
    return g


def _close_rooms(walls_xy, dets, geo, seeds):
    """fusion 의 방 폐합 단계 재현 → (rooms, n_walls_after_bridge)."""
    walls = [Wall(id=str(i), x1=a, y1=b, x2=c, y2=d, thickness=0.2)
             for i, (a, b, c, d) in enumerate(walls_xy)]
    try:
        walls = geo.calibrate_walls(walls, dets)
    except Exception:
        pass
    walls = bridge_collinear_walls(walls)
    walls = snap_wall_endpoints(walls)
    n_after = len(walls)

    bboxes = [d.bbox_xyxy for d in dets if d.class_name in {"door", "window"}]
    synth = synthesize_opening_wall_segments(bboxes, walls)
    walls_for_rooms = list(walls) + [
        Wall(id=f"synth_{i}", x1=a, y1=b, x2=c, y2=d, thickness=0.0)
        for i, (a, b, c, d) in enumerate(synth)
    ]
    poly_rooms = geo.extract_rooms(walls_for_rooms)

    openings = [Opening(id=f"op_{i}", type=d.class_name,
                        x1=d.bbox_xyxy[0], y1=d.bbox_xyxy[1],
                        x2=d.bbox_xyxy[2], y2=d.bbox_xyxy[3])
                for i, d in enumerate(dets) if d.class_name in {"door", "window"}]
    assign_wall_refs(openings, walls)
    project_openings_onto_walls(openings, walls)
    label_rooms = geo.extract_rooms_from_labels(walls, openings, seeds) if seeds else []

    lbl_polys = []
    for r in label_rooms:
        try:
            lbl_polys.append(_Poly(r.points))
        except Exception:
            pass
    kept = []
    for r in poly_rooms:
        try:
            c = _Poly(r.points).centroid
            if any(lp.contains(c) for lp in lbl_polys):
                continue
        except Exception:
            pass
        kept.append(r)
    return label_rooms + kept, n_after


def main():
    ap = argparse.ArgumentParser(description="threshold 별 방 폐합 결과 비교")
    ap.add_argument("--image", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path)
    g.add_argument("--auto-prob", action="store_true")
    ap.add_argument("--thresholds", type=str, default="0.10,0.15,0.20,0.25,0.30,0.35")
    ap.add_argument("--out", type=Path, default=Path("data/threshold_room_sweep"))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--scale", type=float, default=None)
    args = ap.parse_args()

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        sys.exit(f"이미지 디코드 실패: {args.image}")
    h, w = bgr.shape[:2]
    prob_path = args.prob if args.prob else _find_prob(w / h)
    if prob_path is None or not Path(prob_path).exists():
        sys.exit(f"prob map 없음: {prob_path}")
    thresholds = [float(x) for x in args.thresholds.split(",") if x.strip()]
    print(f"이미지: {args.image} ({w}x{h})")
    print(f"prob  : {prob_path}")
    print(f"threshold 스윕: {thresholds}\n")

    # threshold 와 무관한 것들 1회 계산: 문/창, OCR(seed+scale)
    dets = _detect_openings(bgr, args.conf)
    print(f"문/창 (YOLO): {len(dets)}개")
    entries = ocr.detect_text_entries(args.image)
    scale = args.scale
    if scale is None:
        # prob dims == image dims 이므로 image_path=None 으로 내부 재읽기 우회 (좌표 동일).
        base_walls = wall_extractor.execute_from_prob_map(prob_path, image_path=None).walls
        est = dm.estimate_scale_crossvalidated(entries, base_walls or None)
        scale = est.scale_m_per_px if est else 0.02
    print(f"scale = {scale:.5f} m/px")
    geo = GeometryService(w, h, scale_ratio=scale)
    seeds = []
    for e in entries:
        cls = classify_room_label(e.text)
        if cls is None:
            continue
        cx = (e.bbox[0] + e.bbox[2]) / 2.0
        cy = (e.bbox[1] + e.bbox[3]) / 2.0
        seeds.append((cx, cy, cls[0], cls[1]))
    print(f"라벨 seed: {len(seeds)}개 {[s[2] for s in seeds]}\n")

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"{'thr':>5} {'cov%':>6} {'walls':>6} {'rooms':>6} {'area_m2':>8}")
    print("-" * 40)
    tiles = []
    for t in thresholds:
        # threshold 강제 → prob>t 마스크로 벽 추출 (auto-pick 우회).
        # prob dims == image dims 이라 image_path=None 로 내부 OCR 스킵(빠름).
        walls_xy = wall_extractor.execute_from_prob_map(
            prob_path, threshold=t, image_path=None,
        ).walls
        rooms, n_walls = _close_rooms(walls_xy, dets, geo, seeds)
        cov = float((np.load(str(prob_path)) > t).mean()) * 100
        area = sum(getattr(r, "area", 0) or 0 for r in rooms)
        print(f"{t:>5.2f} {cov:>6.2f} {n_walls:>6} {len(rooms):>6} {area:>8.1f}")

        ov = _draw_rooms(bgr, rooms)
        for wl in (Wall(id="", x1=a, y1=b, x2=c, y2=d) for a, b, c, d in walls_xy):
            cv2.line(ov, (int(wl.x1), int(wl.y1)), (int(wl.x2), int(wl.y2)),
                     (150, 150, 150), 1, cv2.LINE_AA)
        tag = f"{t:.2f}".replace(".", "")
        star = "  <- scorer best" if abs(t - 0.25) < 1e-6 else ""
        cv2.imwrite(str(args.out / f"rooms_t{tag}.png"), ov)
        tiles.append(_label_tile(
            ov, [f"thr={t:.2f}{star}", f"walls={n_walls}  rooms={len(rooms)}  {area:.0f}m2"]))

    grid = _grid(tiles, cols=3)
    cv2.imwrite(str(args.out / "_grid.png"), grid)
    print("-" * 40)
    print(f"\n→ threshold 별: {args.out}/rooms_t*.png")
    print(f"→ 비교 그리드 : {args.out / '_grid.png'}")
    print("\n  rooms 가 더 낮은 thr 에서 늘면 → 0.25 하한이 병목 (후보 확장 검토).")
    print("  안 늘면 → threshold 문제 아님. prob map/내부벽 복원이 병목.")


if __name__ == "__main__":
    main()
