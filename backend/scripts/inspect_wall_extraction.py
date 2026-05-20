"""벽 추출 디버그 — U-Net prob map + 여러 threshold + 선탐지(Hough) 비교.

"외벽이 어느 threshold에서 끊기는지 / 선탐지는 어떤지" 를 눈+숫자로 확인하는 도구.
prob map(.npy)을 직접 불러와 분석 (백엔드/AI 실행·로그 불필요):

  - 확률 분포 + threshold 별 커버리지(%)
  - threshold 후보별 점수표 (line_alignment/connectivity/orthogonal/ocr_penalty/...)
  - threshold 별 **마스크 오버레이 PNG** 저장 → 외벽이 어디서 끊기는지 눈으로
  - **선탐지(Hough) 오버레이 PNG** → U-Net 없이 선만으로의 결과
  - 실제 추출기 1회 실행 → 선택된 threshold + 최종 벽 오버레이

사용 (backend 디렉토리에서):
  # prob map 자동 탐색(가장 최근) + 이미지 지정
  python scripts/inspect_wall_extraction.py --image data/uploads/xxx.jpg --auto-prob

  # prob map 직접 지정
  python scripts/inspect_wall_extraction.py --image data/uploads/xxx.jpg --prob path/to/wall_prob.npy

오버레이는 기본 ./wall_debug/ 에 저장됩니다 (--out 으로 변경).
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

from app.services.wall_extraction import wall_extractor  # noqa: E402
from app.services.wall_extraction_helpers import (  # noqa: E402
    line_detection,
    ocr,
    threshold_scoring,
)
from app.services.wall_extraction_helpers import dimension_matching as dm  # noqa: E402

# AI 서버가 prob map 을 저장하는 위치 (repo 루트 기준).
_UNET_OUT = _BACKEND_ROOT.parents[1] / "rf-service" / "apps" / "ai_api" / "data" / "output" / "unet"


def _find_latest_prob() -> Path | None:
    if not _UNET_OUT.exists():
        return None
    npys = list(_UNET_OUT.rglob("*_wall_prob.npy"))
    if not npys:
        return None
    return max(npys, key=lambda p: p.stat().st_mtime)


def _overlay_mask(bgr: np.ndarray, mask: np.ndarray, color=(0, 0, 255), alpha=0.5) -> np.ndarray:
    """mask>0 영역을 color 로 덧칠한 오버레이."""
    out = bgr.copy()
    layer = out.copy()
    layer[mask > 0] = color
    return cv2.addWeighted(layer, alpha, out, 1 - alpha, 0)


def main() -> None:
    ap = argparse.ArgumentParser(description="벽 추출 threshold/선탐지 디버그")
    ap.add_argument("--image", type=Path, required=True, help="원본 도면 이미지")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path, help="U-Net prob map (.npy)")
    g.add_argument("--auto-prob", action="store_true", help="가장 최근 prob map 자동 탐색")
    ap.add_argument("--out", type=Path, default=Path("wall_debug"), help="오버레이 저장 폴더")
    ap.add_argument("--no-ocr", action="store_true", help="OCR text_mask 생략(빠름)")
    args = ap.parse_args()

    if not args.image.exists():
        sys.exit(f"이미지 없음: {args.image}")
    prob_path = args.prob if args.prob else _find_latest_prob()
    if prob_path is None or not prob_path.exists():
        sys.exit(f"prob map 없음: {prob_path} (--prob 로 직접 지정하세요)")
    print(f"이미지   : {args.image}")
    print(f"prob map : {prob_path}")

    bgr = cv2.imread(str(args.image))
    if bgr is None:
        sys.exit("이미지 디코드 실패")
    h_img, w_img = bgr.shape[:2]

    prob = np.load(str(prob_path)).astype(np.float32)
    print(f"prob shape={prob.shape}, image shape=({h_img},{w_img})")
    # 실제 파이프라인처럼 prob 를 이미지 좌표계로 resize
    if prob.shape[:2] != (h_img, w_img):
        prob = cv2.resize(prob, (w_img, h_img), interpolation=cv2.INTER_LINEAR)
        print("  → prob 를 이미지 크기로 resize 함")

    args.out.mkdir(parents=True, exist_ok=True)

    # ── [1] 확률 분포 + threshold 별 커버리지 ───────────────────────────
    print("\n[1] 확률 분포")
    print(f"  min={prob.min():.3f} max={prob.max():.3f} mean={prob.mean():.3f}")
    print("  threshold 별 wall 픽셀 비율:")
    for t in threshold_scoring.DEFAULT_THRESHOLDS:
        cov = float((prob > t).mean()) * 100
        print(f"    >{t:.2f} : {cov:5.2f}%")

    # ── [2] 선탐지(Hough) ────────────────────────────────────────────
    print("\n[2] 선탐지 (Hough wall 후보)")
    segs = line_detection.detect_line_segments(args.image)
    print(f"  검출된 H/V 선분: {len(segs)} 개")
    line_mask = (
        line_detection.build_line_mask(segs, (h_img, w_img), thickness=3)
        if len(segs) > 0 else None
    )
    line_ov = bgr.copy()
    for x1, y1, x2, y2 in segs:
        cv2.line(line_ov, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 0), 2)
    cv2.imwrite(str(args.out / "lines_hough.png"), line_ov)
    print(f"  → 저장: {args.out / 'lines_hough.png'}")

    # ── [3] OCR text_mask (선택) ─────────────────────────────────────
    text_mask = None
    dim_entries: list = []
    if not args.no_ocr:
        try:
            entries = ocr.detect_text_entries(args.image)
            confident = [e.bbox for e in entries if e.confidence >= 0.5]
            text_mask = (
                ocr.build_text_mask(confident, (h_img, w_img), pad=3) if confident else None
            )
            dim_entries = [e for e in entries if dm.parse_dimension_to_meters(e.text)]
            print(f"\n[3] OCR: 전체 {len(entries)}개, text_mask(conf>=0.5) {len(confident)}개")
        except Exception as exc:
            print(f"\n[3] OCR 생략(실패): {exc}")

    # ── [4] threshold 후보별 점수 ────────────────────────────────────
    print("\n[4] threshold 후보 점수 (높을수록 좋음; ocr_p/np 는 감점)")
    print("-" * 92)
    print(f"{'thr':>5} {'total':>8} {'line':>7} {'conn':>7} {'orth':>7} {'dim':>7} {'ocr_p':>7} {'noise':>7}")
    print("-" * 92)
    best_thr, scores = threshold_scoring.pick_best_threshold(
        prob, line_mask=line_mask, text_mask=text_mask, dim_entries=dim_entries,
    )
    for s in scores:
        mark = " ★best" if abs(s.threshold - best_thr) < 1e-6 else ""
        print(
            f"{s.threshold:>5.2f} {s.total:>8.3f} {s.line_alignment:>7.3f} "
            f"{s.connectivity:>7.3f} {s.orthogonal:>7.3f} {s.dimension_alignment:>7.3f} "
            f"{s.ocr_penalty:>7.3f} {s.noise_penalty:>7.3f}{mark}"
        )
    print(f"\n  → 선택된 threshold = {best_thr:.2f}")

    # ── [5] threshold 별 "실제 추출 벽" 비교 ─────────────────────────
    # raw 마스크(prob>t, 빨강) + 그 threshold 로 벡터화한 최종 벽(파랑) 을 한 장에.
    # 외벽이 어느 threshold 에서 한 줄로 이어지고/끊기는지 눈으로 비교.
    print("\n[5] threshold 별 추출 결과 (raw 마스크=빨강, 벡터화 벽=파랑)")
    for t in threshold_scoring.DEFAULT_THRESHOLDS:
        r = wall_extractor.execute_from_prob_map(
            prob_path, threshold=float(t), image_path=args.image,
        )
        mask = (prob > t).astype(np.uint8) * 255
        ov = _overlay_mask(bgr, mask, color=(0, 0, 255), alpha=0.30)
        for x1, y1, x2, y2 in r.walls:
            cv2.line(ov, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 3)
        tag = f"{t:.2f}".replace(".", "")
        star = "_BEST" if abs(t - best_thr) < 1e-6 else ""
        cv2.imwrite(str(args.out / f"thr_{tag}{star}.png"), ov)
        cov = float((prob > t).mean()) * 100
        print(f"    thr={t:.2f}: 벽 {len(r.walls):>3}개  (커버리지 {cov:5.2f}%)"
              + ("  ★ scorer 선택" if abs(t - best_thr) < 1e-6 else ""))
    print(f"  → {args.out}/thr_*.png  (파일명에 BEST = scorer 가 고른 값)")
    print("\n  외벽이 끊기면: 더 낮은 threshold 의 thr_*.png 에서 이어지는지 보세요.")
    print("  거기서 이어지는데 BEST 가 높게 잡혔다면 → ocr_penalty 가 threshold 를 올린 것.")


if __name__ == "__main__":
    main()
