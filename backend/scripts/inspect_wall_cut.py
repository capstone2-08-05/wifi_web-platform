"""문/창 자리 벽 절단(cut_walls_at_openings) 시각 진단.

전체 파이프라인의 '마지막 단계'(방 추출 후 벽만 자르기)를 눈으로 확인:
  벽 추출(U-Net prob) + YOLO 문/창 탐지 → wall_ref 매칭/투영 → 절단.

저장 (data/wall_cut_debug/):
  - wall_cut.png : 절단 전 벽(연회색) + 절단 후 조각(초록, 끝점 점) + 문/창(빨강 박스)
                    문/창 자리에 gap 이 생겼는지 확인.

사용 (※ ultralytics 필요 → AI venv 로 실행):
  rf-service/apps/ai_api/.venv/Scripts/python.exe \
      web-platform/backend/scripts/inspect_wall_cut.py \
      --image web-platform/backend/data/uploads/xxx.png --auto-prob
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
_REPO_ROOT = _BACKEND_ROOT.parents[1]
_RF_ROOT = _REPO_ROOT / "rf-service"
for p in (_BACKEND_ROOT, _RF_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# app.geometry.__init__ → conversion.py 가 geoalchemy2(DB 전용)를 import 하는데
# AI venv 엔 없음. 이 스크립트는 conversion 을 안 쓰므로 stub 으로 막는다.
import types  # noqa: E402
_g = types.ModuleType("geoalchemy2"); _gs = types.ModuleType("geoalchemy2.shape")
_gs.from_shape = _gs.to_shape = lambda *a, **k: None  # type: ignore[attr-defined]
_g.shape = _gs  # type: ignore[attr-defined]
sys.modules.setdefault("geoalchemy2", _g)
sys.modules.setdefault("geoalchemy2.shape", _gs)

from app.schemas.scene import Opening, Wall  # noqa: E402
from app.services.floorplan.wall_extraction import wall_extractor  # noqa: E402
# conversion.py 가 geoalchemy2(DB 전용)를 끌어와 AI venv 에서 막히므로 submodule 직접 import.
from app.geometry.matching import assign_wall_refs  # noqa: E402
from app.geometry.reconciliation import (  # noqa: E402
    cut_walls_at_openings,
    project_openings_onto_walls,
)

_UNET_OUT = _RF_ROOT / "apps" / "ai_api" / "data" / "output" / "unet"
_YOLO_WEIGHTS = _RF_ROOT / "apps" / "trainer" / "src" / "models" / "yolo" / "best.pt"


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


def _detect_openings(bgr: np.ndarray, conf: float) -> list[Opening]:
    from packages.ai_runtime.yolo_runtime import run_yolo_inference_result

    model, result, _ = run_yolo_inference_result(
        bgr, weights_path=str(_YOLO_WEIGHTS), conf_threshold=conf,
        preferred_device="", default_device="cpu",
    )
    names = model.names if isinstance(model.names, dict) else {}
    ops: list[Opening] = []
    if result.boxes is not None:
        for box in result.boxes:
            cls = names.get(int(box.cls.item()), str(int(box.cls.item())))
            if cls not in {"door", "window"}:
                continue
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            ops.append(Opening(id=f"opening_{len(ops)}", type=cls,
                               x1=x1, y1=y1, x2=x2, y2=y2))
    return ops


def main() -> None:
    ap = argparse.ArgumentParser(description="문/창 자리 벽 절단 진단")
    ap.add_argument("--image", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path)
    g.add_argument("--auto-prob", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/wall_cut_debug"))
    ap.add_argument("--conf", type=float, default=0.25)
    args = ap.parse_args()

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        sys.exit(f"이미지 디코드 실패: {args.image}")
    h, w = bgr.shape[:2]
    prob_path = args.prob if args.prob else _find_prob(w / h)
    if prob_path is None:
        sys.exit("prob map 없음")
    print(f"이미지: {args.image} ({w}x{h})\nprob  : {prob_path}")

    walls_xy = wall_extractor.execute_from_prob_map(prob_path, image_path=args.image).walls
    walls = [Wall(id=str(i), x1=a, y1=b, x2=c, y2=d, thickness=0.15)
             for i, (a, b, c, d) in enumerate(walls_xy)]
    print(f"벽 {len(walls)}개")

    openings = _detect_openings(bgr, args.conf)
    print(f"문/창 {len(openings)}개: {[o.type for o in openings]}")

    matched = assign_wall_refs(openings, walls)
    projected = project_openings_onto_walls(openings, walls)
    print(f"매칭 {matched}/{len(openings)}, 투영 {projected}")

    cut = cut_walls_at_openings(walls, openings)
    print(f"절단: 벽 {len(walls)} → {len(cut)}개 (+{len(cut) - len(walls)} 조각)")

    # ── 오버레이 ──
    args.out.mkdir(parents=True, exist_ok=True)
    ov = bgr.copy()
    # 절단 전 (연회색, 두껍게 깔기)
    for wl in walls:
        cv2.line(ov, (int(wl.x1), int(wl.y1)), (int(wl.x2), int(wl.y2)), (190, 190, 190), 4)
    # 절단 후 조각 (초록 + 끝점)
    for wl in cut:
        p1 = (int(wl.x1), int(wl.y1)); p2 = (int(wl.x2), int(wl.y2))
        cv2.line(ov, p1, p2, (0, 170, 0), 2)
        cv2.circle(ov, p1, 4, (0, 100, 0), -1)
        cv2.circle(ov, p2, 4, (0, 100, 0), -1)
    # 문/창 (빨강 박스)
    for o in openings:
        cv2.rectangle(ov, (int(o.x1), int(o.y1)), (int(o.x2), int(o.y2)), (0, 0, 230), 2)
        cv2.putText(ov, o.type[0].upper(), (int(o.x1), int(o.y1) - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 230), 1)
    out_path = args.out / "wall_cut.png"
    cv2.imwrite(str(out_path), ov)
    print(f"\n→ {out_path}  (연회색=절단 전, 초록=절단 후 조각, 빨강=문/창 → gap 확인)")


if __name__ == "__main__":
    main()
