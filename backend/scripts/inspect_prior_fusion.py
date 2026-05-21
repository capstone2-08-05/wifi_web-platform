"""prior-guided line fusion 시각 진단.

AI 원본 Hough line prior 가 U-Net prob corridor 검증을 거쳐 최종 벽에 합쳐지는 과정을
눈으로 확인. prob map(.npy) + 원본 이미지로 동작 (백엔드/AI 실행 불필요).

저장물 (기본 ./prior_fusion_debug/):
  - priors_decision.png : 각 prior 선 색상 — 초록=채택 / 빨강=저prob / 주황=저coverage
  - fusion_compare.png  : skeleton-only 벽(파랑) vs fusion 후 벽(초록) 비교
콘솔: prior 후보/채택/탈락 수 + threshold.

사용 (backend 디렉토리에서):
  python scripts/inspect_prior_fusion.py --image data/uploads/xxx.jpg --auto-prob
  python scripts/inspect_prior_fusion.py --image data/uploads/xxx.jpg --prob path/to/wall_prob.npy

참고: prior 는 백엔드 line_detection(Hough)로 재현 — 운영의 AI linePriors 와 거의 동일
(전부 wall_candidate 로 둠; dimension_line 분류는 OCR 필요라 여기선 생략).
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

from app.services.floorplan.wall_extraction import wall_extractor  # noqa: E402
from app.services.floorplan.wall_extraction_helpers import line_detection  # noqa: E402

_UNET_OUT = _BACKEND_ROOT.parents[1] / "rf-service" / "apps" / "ai_api" / "data" / "output" / "unet"


def _find_latest_prob(img_aspect: float | None = None, tol: float = 0.06) -> Path | None:
    """가장 최근 prob map. img_aspect(=w/h) 주면 종횡비 맞는 것 우선 — 다른 도면의
    prob 를 잘못 집어 resize 하는 mismatch 방지 (shape 만 싸게 읽어 비교)."""
    if not _UNET_OUT.exists():
        return None
    npys = list(_UNET_OUT.rglob("*_wall_prob.npy"))
    if not npys:
        return None
    if img_aspect:
        matched = []
        for p in npys:
            try:
                shp = np.load(str(p), mmap_mode="r").shape
                if abs((shp[1] / shp[0]) - img_aspect) / img_aspect <= tol:
                    matched.append(p)
            except Exception:
                pass
        if matched:
            return max(matched, key=lambda p: p.stat().st_mtime)
    return max(npys, key=lambda p: p.stat().st_mtime)


def main() -> None:
    ap = argparse.ArgumentParser(description="prior-guided line fusion 시각 진단")
    ap.add_argument("--image", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path)
    g.add_argument("--auto-prob", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/prior_fusion_debug"))
    args = ap.parse_args()

    if not args.image.exists():
        sys.exit(f"이미지 없음: {args.image}")
    bgr = cv2.imread(str(args.image))
    if bgr is None:
        sys.exit("이미지 디코드 실패")
    h, w = bgr.shape[:2]
    prob_path = args.prob if args.prob else _find_latest_prob(img_aspect=w / h)
    if prob_path is None or not prob_path.exists():
        sys.exit(f"prob map 없음: {prob_path}")
    print(f"이미지   : {args.image} ({w}x{h})\nprob map : {prob_path}")

    prob = np.load(str(prob_path)).astype(np.float32)
    if prob.shape[:2] != (h, w):
        pa = prob.shape[1] / prob.shape[0]
        if abs(pa - w / h) / (w / h) > 0.06:
            print(f"  ⚠️ prob 종횡비({prob.shape[1]}x{prob.shape[0]}) ≠ 이미지 — "
                  f"다른 도면의 prob 일 수 있음! --prob 로 맞는 것 지정 권장.")
        prob = cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)
    args.out.mkdir(parents=True, exist_ok=True)

    # AI linePriors 재현 — Hough wall 후보 (전부 wall_candidate)
    segs = line_detection.detect_line_segments(args.image)
    priors = [
        {"kind": "wall_candidate", "x1": float(x1), "y1": float(y1),
         "x2": float(x2), "y2": float(y2)}
        for (x1, y1, x2, y2) in segs
    ]
    print(f"\nHough prior 후보: {len(priors)} 개 (wall_candidate)")

    # ── fusion 적용 실행 → threshold + prior 진단 ──────────────────────
    res_fused = wall_extractor.execute_from_prob_map(
        prob_path, image_path=args.image, line_priors=priors,
    )
    m = res_fused.postprocess
    thr = float(m.selected_threshold or 0.4)
    print(f"\n선택 threshold = {thr:.2f}")
    print(f"prior 후보 {m.prior_line_candidates_count} → "
          f"채택 {m.prior_line_accepted_count}, "
          f"저prob 탈락 {m.prior_line_rejected_low_prob_count}, "
          f"저coverage 탈락 {m.prior_line_rejected_coverage_count} "
          f"(fusion_applied={m.prior_line_fusion_applied})")

    # ── skeleton-only (같은 threshold, prior 없이) ─────────────────────
    res_skel = wall_extractor.execute_from_prob_map(
        prob_path, image_path=args.image, threshold=thr, line_priors=[],
    )
    print(f"\n벽 수:  skeleton-only {len(res_skel.walls)}  →  fusion {len(res_fused.walls)}")

    # ── [overlay 1] segment 추출 결과 (회색=전체 prior, 초록=prob 위 추출 구간) ─
    prior_segs = wall_extractor._filter_line_priors_by_probability(priors, prob, thr, band_px=4)
    ov1 = bgr.copy()
    for p in priors:  # 전체 Hough prior = 회색 배경
        cv2.line(ov1, (int(p["x1"]), int(p["y1"])), (int(p["x2"]), int(p["y2"])),
                 (180, 180, 180), 1)
    for x1, y1, x2, y2 in prior_segs:  # prob 위 추출 구간 = 초록 굵게
        cv2.line(ov1, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 0), 3)
    cv2.imwrite(str(args.out / "priors_decision.png"), ov1)
    print(f"\n[overlay1] priors_decision.png — 회색=전체 prior, 초록=prob 위 추출 구간 "
          f"({len(prior_segs)}개)")

    # ── [overlay 2] skeleton vs fusion 벽 비교 ────────────────────────
    ov2 = bgr.copy()
    for x1, y1, x2, y2 in res_skel.walls:  # skeleton-only = 파랑
        cv2.line(ov2, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 4)
    for x1, y1, x2, y2 in res_fused.walls:  # fusion 후 = 초록(위에 덧그림)
        cv2.line(ov2, (int(x1), int(y1)), (int(x2), int(y2)), (0, 180, 0), 2)
    cv2.imwrite(str(args.out / "fusion_compare.png"), ov2)
    print("[overlay2] fusion_compare.png — 파랑=skeleton-only, 초록=fusion 후")
    print("\n  초록만 있고 파랑 없는 구간 = prior fusion 으로 새로 살아난 벽")


if __name__ == "__main__":
    main()
