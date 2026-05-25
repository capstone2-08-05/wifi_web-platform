"""방 폐합 파이프라인 단계별 시각 진단 (slide 1-7 "끊긴 벽 잇고 방 닫기").

fusion_service._run_wi_twin_pipeline 의 방 폐합 순서를 그대로 재현해 단계별로 본다:

  1. raw walls            : wall_extractor (U-Net prob → 벽 선분)
  2. bridge + snap        : bridge_collinear_walls + snap_wall_endpoints
                            (같은 축 끊김 잇기 + 가까운 끝점 코너 스냅)
  3. + 문/창 합성 조각     : synthesize_opening_wall_segments
                            (문/창 bbox 를 '벽 지나감' 증거로 중심선 조각 끼움)
  4. polygonize 방        : geo.extract_rooms (닫힌 루프 → 방 다각형)
  5. + 라벨 flood-fill 방  : OCR 방이름 seed → extract_rooms_from_labels 병합
  6. cut_walls_at_openings: 방 닫은 뒤 문/창 자리 벽 절단 (gap)

문/창(YOLO)은 best-effort:
  - ultralytics 가 있으면(AI venv) YOLO 로 문/창 탐지 → 합성/절단까지 전체 단계.
  - 없으면(백엔드 venv) openings=0 → 3·6 단계는 생략되고 1·2·4·5 만 표시.

사용:
  # 전체 단계 (AI venv 권장 — YOLO 문/창 포함)
  rf-service/apps/ai_api/.venv/Scripts/python.exe \
      web-platform/backend/scripts/inspect_room_closing.py \
      --image web-platform/backend/data/uploads/xxx.jpg --auto-prob

  # 백엔드 venv (문/창 없이 bridge/snap/polygonize/flood-fill 만)
  python scripts/inspect_room_closing.py --image data/uploads/xxx.jpg --auto-prob

결과 (data/room_closing_debug/):
  stage1_walls.png ... stage6_cut.png  : 단계별 오버레이
  _grid.png                            : 6단계 비교 그리드 한 장
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

# app.geometry.__init__ → conversion.py 가 geoalchemy2(DB 전용)를 import 하는데
# AI venv 엔 없음. 이 스크립트는 conversion 을 안 쓰므로 stub 으로 막는다.
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
    cut_walls_at_openings,
    project_openings_onto_walls,
    snap_wall_endpoints,
    synthesize_opening_wall_segments,
)

_UNET_OUT = _RF_ROOT / "apps" / "ai_api" / "data" / "output" / "unet"
_YOLO_WEIGHTS = _RF_ROOT / "apps" / "trainer" / "src" / "models" / "yolo" / "best.pt"


class _Det:
    """ml_output.detections 호환 최소 객체 (class_name + bbox_xyxy)."""
    def __init__(self, class_name: str, bbox_xyxy, score: float = 1.0):
        self.class_name = class_name
        self.bbox_xyxy = bbox_xyxy
        self.score = score
        self.id = ""


def _find_prob(img_aspect: float, tol: float = 0.06) -> Path | None:
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


def _detect_openings(bgr: np.ndarray, conf: float) -> list[_Det]:
    """YOLO 로 문/창 탐지 (best-effort). ultralytics 없으면 빈 리스트 + 안내."""
    try:
        from packages.ai_runtime.yolo_runtime import run_yolo_inference_result
    except Exception as exc:
        print(f"  ⚠️ YOLO 미사용 ({type(exc).__name__}) → 문/창 0개. "
              "전체 단계는 AI venv 로 실행하세요.")
        return []
    if not _YOLO_WEIGHTS.exists():
        print(f"  ⚠️ YOLO weights 없음: {_YOLO_WEIGHTS} → 문/창 0개")
        return []
    model, result, _ = run_yolo_inference_result(
        bgr, weights_path=str(_YOLO_WEIGHTS), conf_threshold=conf,
        preferred_device="", default_device="cpu",
    )
    names = model.names if isinstance(model.names, dict) else {}
    dets: list[_Det] = []
    if result.boxes is not None:
        for box in result.boxes:
            cls = names.get(int(box.cls.item()), str(int(box.cls.item())))
            if cls not in {"door", "window"}:
                continue
            xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
            dets.append(_Det(cls, xyxy, float(box.conf.item())))
    return dets


# ── 시각화 헬퍼 ──────────────────────────────────────────────────────
def _draw_walls(ov, walls, color, thick=2, dots=False):
    for wl in walls:
        p1 = (int(wl.x1), int(wl.y1)); p2 = (int(wl.x2), int(wl.y2))
        cv2.line(ov, p1, p2, color, thick, cv2.LINE_AA)
        if dots:
            cv2.circle(ov, p1, 4, (255, 255, 255), -1)
            cv2.circle(ov, p2, 4, (255, 255, 255), -1)


def _draw_openings(ov, dets):
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d.bbox_xyxy)
        cv2.rectangle(ov, (x1, y1), (x2, y2), (0, 0, 230), 2)
        cv2.putText(ov, d.class_name[0].upper(), (x1, y1 - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 230), 1, cv2.LINE_AA)


def _draw_rooms(ov, rooms, base=None):
    out = (base if base is not None else ov).copy()
    rng = np.random.default_rng(0)
    for i, r in enumerate(rooms):
        try:
            pts = np.array(r.points, dtype=np.int32)
        except Exception:
            continue
        col = tuple(int(c) for c in rng.integers(60, 220, size=3))
        layer = out.copy()
        cv2.fillPoly(layer, [pts], col)
        out = cv2.addWeighted(layer, 0.38, out, 0.62, 0)
        cv2.polylines(out, [pts], True, col, 2, cv2.LINE_AA)
        cx = int(np.mean(pts[:, 0])); cy = int(np.mean(pts[:, 1]))
        rtype = getattr(r, "type", None) or ""
        tag = f"R{i}:{rtype}" if rtype else f"R{i}"
        cv2.putText(out, tag, (cx - 18, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 2, cv2.LINE_AA)
    return out


def _label_tile(img, text):
    t = img.copy()
    h, w = t.shape[:2]
    bar = max(24, int(h * 0.06))
    cv2.rectangle(t, (0, 0), (w, bar), (35, 35, 35), -1)
    fs = max(0.45, w / 1100)
    cv2.putText(t, text, (8, int(bar * 0.72)), cv2.FONT_HERSHEY_SIMPLEX,
                fs, (0, 235, 0), 1, cv2.LINE_AA)
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


def main() -> None:
    ap = argparse.ArgumentParser(description="방 폐합 파이프라인 단계별 진단")
    ap.add_argument("--image", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path)
    g.add_argument("--auto-prob", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/room_closing_debug"))
    ap.add_argument("--conf", type=float, default=0.25, help="YOLO 문/창 conf")
    ap.add_argument("--scale", type=float, default=None, help="m/px (미지정 시 OCR 추정)")
    args = ap.parse_args()

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        sys.exit(f"이미지 디코드 실패: {args.image}")
    h, w = bgr.shape[:2]
    prob_path = args.prob if args.prob else _find_prob(w / h)
    if prob_path is None or not Path(prob_path).exists():
        sys.exit(f"prob map 없음: {prob_path}")
    print(f"이미지: {args.image} ({w}x{h})")
    print(f"prob  : {prob_path}\n")

    # ── 0. OCR (라벨 seed + scale) ──────────────────────────────────
    entries = ocr.detect_text_entries(args.image)
    scale = args.scale
    if scale is None:
        wall_xy_for_scale = wall_extractor.execute_from_prob_map(
            prob_path, image_path=args.image).walls
        est = dm.estimate_scale_crossvalidated(entries, wall_xy_for_scale or None)
        scale = est.scale_m_per_px if est else 0.02
    print(f"scale = {scale:.5f} m/px  (area 필터용)")
    geo = GeometryService(w, h, scale_ratio=scale)

    # ── 1. raw walls ────────────────────────────────────────────────
    walls_xy = wall_extractor.execute_from_prob_map(prob_path, image_path=args.image).walls
    raw_walls = [Wall(id=str(i), x1=a, y1=b, x2=c, y2=d, thickness=0.2)
                 for i, (a, b, c, d) in enumerate(walls_xy)]
    print(f"[1] raw walls           : {len(raw_walls)}개")

    # ── 문/창 (best-effort) ─────────────────────────────────────────
    dets = _detect_openings(bgr, args.conf)
    print(f"    문/창 (YOLO)        : {len(dets)}개  {[d.class_name for d in dets]}")

    # ── 2. calibrate → bridge → snap ───────────────────────────────
    try:
        calibrated = geo.calibrate_walls(raw_walls, dets)
    except Exception as exc:
        print(f"    (calibrate_walls 생략: {exc})")
        calibrated = raw_walls
    n0 = len(calibrated)
    calibrated = bridge_collinear_walls(calibrated)
    calibrated = snap_wall_endpoints(calibrated)
    print(f"[2] bridge + snap       : {n0} → {len(calibrated)}개")

    # ── 3. 문/창 합성 조각 ──────────────────────────────────────────
    opening_bboxes = [d.bbox_xyxy for d in dets if d.class_name in {"door", "window"}]
    synth = synthesize_opening_wall_segments(opening_bboxes, calibrated)
    walls_for_rooms = list(calibrated) + [
        Wall(id=f"synth_{i}", x1=a, y1=b, x2=c, y2=d, thickness=0.0)
        for i, (a, b, c, d) in enumerate(synth)
    ]
    print(f"[3] 문/창 합성 조각     : +{len(synth)}개 (방 추출 입력 전용)")

    # ── 4. polygonize 방 ────────────────────────────────────────────
    poly_rooms = geo.extract_rooms(walls_for_rooms)
    print(f"[4] polygonize 방       : {len(poly_rooms)}개")

    # ── 5. 라벨 flood-fill 방 병합 ──────────────────────────────────
    openings = [Opening(id=f"opening_{i}", type=d.class_name,
                        x1=d.bbox_xyxy[0], y1=d.bbox_xyxy[1],
                        x2=d.bbox_xyxy[2], y2=d.bbox_xyxy[3])
                for i, d in enumerate(dets) if d.class_name in {"door", "window"}]
    assign_wall_refs(openings, calibrated)
    project_openings_onto_walls(openings, calibrated)

    seeds = []
    for e in entries:
        cls = classify_room_label(e.text)
        if cls is None:
            continue
        cx = (e.bbox[0] + e.bbox[2]) / 2.0
        cy = (e.bbox[1] + e.bbox[3]) / 2.0
        seeds.append((cx, cy, cls[0], cls[1]))
    label_rooms = geo.extract_rooms_from_labels(calibrated, openings, seeds) if seeds else []
    print(f"[5] 라벨 seed           : {len(seeds)}개 {[s[2] for s in seeds]}")
    print(f"    라벨 flood-fill 방   : {len(label_rooms)}개")

    # polygonize 방 중 라벨 방과 겹치는 것 제거 후 병합 (fusion 과 동일)
    from shapely.geometry import Polygon as _Poly
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
    final_rooms = label_rooms + kept
    print(f"    최종 방 (병합)       : {len(final_rooms)}개")
    for r in final_rooms:
        nm = getattr(r, "name", None) or getattr(r, "id", "?")
        print(f"        - {nm}  area={getattr(r, 'area', '?')}m2")

    # ── 6. cut_walls_at_openings ────────────────────────────────────
    final_walls = cut_walls_at_openings(calibrated, openings)
    print(f"[6] 문/창 자리 절단      : 벽 {len(calibrated)} → {len(final_walls)}개 "
          f"(+{len(final_walls) - len(calibrated)} 조각)")

    # ── 오버레이 6장 + 그리드 ───────────────────────────────────────
    args.out.mkdir(parents=True, exist_ok=True)
    tiles = []

    s1 = bgr.copy(); _draw_walls(s1, raw_walls, (160, 160, 160), 2)
    cv2.imwrite(str(args.out / "stage1_walls.png"), s1)
    tiles.append(_label_tile(s1, f"[1] raw walls ({len(raw_walls)})"))

    s2 = bgr.copy(); _draw_walls(s2, calibrated, (255, 120, 0), 2, dots=True)
    cv2.imwrite(str(args.out / "stage2_bridge_snap.png"), s2)
    tiles.append(_label_tile(s2, f"[2] bridge+snap ({len(calibrated)})"))

    s3 = bgr.copy(); _draw_walls(s3, calibrated, (255, 120, 0), 2)
    for (a, b, c, d) in synth:
        cv2.line(s3, (int(a), int(b)), (int(c), int(d)), (255, 0, 200), 3, cv2.LINE_AA)
    _draw_openings(s3, dets)
    cv2.imwrite(str(args.out / "stage3_synth.png"), s3)
    tiles.append(_label_tile(s3, f"[3] +opening synth segs (+{len(synth)})"))

    s4 = _draw_rooms(None, poly_rooms, base=bgr); _draw_walls(s4, calibrated, (160, 160, 160), 1)
    cv2.imwrite(str(args.out / "stage4_polygonize.png"), s4)
    tiles.append(_label_tile(s4, f"[4] polygonize rooms ({len(poly_rooms)})"))

    s5 = _draw_rooms(None, final_rooms, base=bgr); _draw_walls(s5, calibrated, (160, 160, 160), 1)
    cv2.imwrite(str(args.out / "stage5_label_merge.png"), s5)
    tiles.append(_label_tile(s5, f"[5] +label flood-fill ({len(final_rooms)})"))

    s6 = bgr.copy()
    _draw_walls(s6, calibrated, (200, 200, 200), 4)
    _draw_walls(s6, final_walls, (0, 170, 0), 2, dots=True)
    _draw_openings(s6, dets)
    cv2.imwrite(str(args.out / "stage6_cut.png"), s6)
    tiles.append(_label_tile(s6, f"[6] cut at openings ({len(final_walls)})"))

    grid = _grid(tiles, cols=3)
    cv2.imwrite(str(args.out / "_grid.png"), grid)
    print(f"\n→ 단계별: {args.out}/stage*.png")
    print(f"→ 그리드: {args.out / '_grid.png'}")
    if not dets:
        print("\n  ⚠️ 문/창 0개 → [3] 합성·[6] 절단은 비어 있음. "
              "전체 단계를 보려면 AI venv(ultralytics) 로 실행하세요.")


if __name__ == "__main__":
    main()
