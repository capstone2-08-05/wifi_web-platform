"""U-Net 확률맵 → threshold 별 **흑백 마스크** 비교.

`inspect_wall_extraction.py` 가 도면 위 빨강/파랑 오버레이라면, 이 스크립트는
U-Net 출력 그 자체를 보고 싶을 때 쓴다 — 흰색=벽(prob > t), 검정=배경.
threshold 를 바꿔가며 벽이 어디서 뭉치고/끊기는지 순수 마스크로 비교한다.

별도 백엔드·AI 실행 불필요. prob map(.npy) 만 읽는다.

사용 (backend 디렉토리에서):
  # 가장 최근 prob map 자동 탐색 (최신에 돌렸던 거)
  python scripts/inspect_threshold_masks.py --auto-prob

  # 종횡비 맞는 최신 prob 우선 (도면 이미지 같이 주면)
  python scripts/inspect_threshold_masks.py --auto-prob --image data/uploads/xxx.jpg

  # prob map 직접 지정
  python scripts/inspect_threshold_masks.py --prob path/to/xxx_wall_prob.npy

  # threshold 직접 지정 (쉼표 구분) / 촘촘하게 스윕
  python scripts/inspect_threshold_masks.py --auto-prob --thresholds 0.2,0.3,0.4,0.5
  python scripts/inspect_threshold_masks.py --auto-prob --fine          # 0.10~0.90 step 0.05

옵션:
  --clean   : 파이프라인 전처리(_preprocess: open+H/V close) 적용한 마스크도 같이 저장
              → 실제 skeleton 에 들어가는 모양 확인용.

결과는 기본 data/threshold_masks/ 에 저장 (data/ 는 gitignore):
  mask_t030.png ...  : threshold 별 순수 흑백 마스크
  _grid.png          : 라벨(threshold + 커버리지%) 붙은 비교 그리드 한 장
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

# AI 서버가 prob map 을 저장하는 위치 (repo 루트 기준). inspect_wall_extraction 과 동일.
_UNET_OUT = _BACKEND_ROOT.parents[1] / "rf-service" / "apps" / "ai_api" / "data" / "output" / "unet"


def _find_latest_prob(img_aspect: float | None = None, tol: float = 0.06) -> Path | None:
    """최근 prob map. img_aspect(=w/h) 주면 종횡비 맞는 것 우선."""
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


def _parse_thresholds(args) -> list[float]:
    if args.thresholds:
        return [float(x) for x in args.thresholds.split(",") if x.strip()]
    if args.fine:
        return [round(0.10 + 0.05 * i, 2) for i in range(17)]  # 0.10 ~ 0.90
    from app.services.floorplan.wall_extraction_helpers.threshold_scoring import (
        DEFAULT_THRESHOLDS,
    )
    return list(DEFAULT_THRESHOLDS)


def _label(mask_gray: np.ndarray, text: str) -> np.ndarray:
    """흑백 마스크 위에 상단 라벨 바를 얹은 BGR 이미지 반환 (그리드용)."""
    bgr = cv2.cvtColor(mask_gray, cv2.COLOR_GRAY2BGR)
    h, w = bgr.shape[:2]
    bar_h = max(22, int(h * 0.07))
    cv2.rectangle(bgr, (0, 0), (w, bar_h), (40, 40, 40), -1)
    fs = max(0.4, w / 900)
    cv2.putText(bgr, text, (6, int(bar_h * 0.72)),
                cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 235, 0), 1, cv2.LINE_AA)
    cv2.rectangle(bgr, (0, 0), (w - 1, h - 1), (70, 70, 70), 1)
    return bgr


def _build_grid(tiles: list[np.ndarray], cols: int, cell_w: int = 380) -> np.ndarray:
    """동일 종횡비 타일들을 cols 열 그리드로 합침."""
    if not tiles:
        return np.zeros((10, 10, 3), np.uint8)
    ar = tiles[0].shape[0] / tiles[0].shape[1]
    cw, ch = cell_w, int(cell_w * ar)
    resized = [cv2.resize(t, (cw, ch)) for t in tiles]
    rows = (len(resized) + cols - 1) // cols
    pad = 6
    grid = np.full((rows * ch + (rows + 1) * pad,
                    cols * cw + (cols + 1) * pad, 3), 25, np.uint8)
    for i, t in enumerate(resized):
        r, c = divmod(i, cols)
        y = pad + r * (ch + pad)
        x = pad + c * (cw + pad)
        grid[y:y + ch, x:x + cw] = t
    return grid


def main() -> None:
    ap = argparse.ArgumentParser(description="U-Net prob map threshold 별 흑백 마스크 비교")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prob", type=Path, help="U-Net prob map (.npy)")
    g.add_argument("--auto-prob", action="store_true", help="가장 최근 prob map 자동 탐색")
    ap.add_argument("--image", type=Path, default=None,
                    help="원본 도면(선택). 주면 prob 를 이미지 크기로 resize + 종횡비 매칭")
    ap.add_argument("--thresholds", type=str, default=None,
                    help="쉼표 구분 threshold 목록 (예: 0.2,0.3,0.4). 미지정 시 DEFAULT_THRESHOLDS")
    ap.add_argument("--fine", action="store_true", help="0.10~0.90 step 0.05 스윕")
    ap.add_argument("--clean", action="store_true",
                    help="파이프라인 전처리(open+H/V close) 적용 마스크도 저장")
    ap.add_argument("--out", type=Path, default=Path("data/threshold_masks"),
                    help="저장 폴더 (gitignore: data/)")
    ap.add_argument("--cols", type=int, default=4, help="그리드 열 수")
    args = ap.parse_args()

    # ── prob map 로드 ────────────────────────────────────────────────
    img_aspect = None
    bgr = None
    if args.image is not None:
        if not args.image.exists():
            sys.exit(f"이미지 없음: {args.image}")
        bgr = cv2.imread(str(args.image))
        if bgr is None:
            sys.exit("이미지 디코드 실패")
        h_img, w_img = bgr.shape[:2]
        img_aspect = w_img / h_img

    prob_path = args.prob if args.prob else _find_latest_prob(img_aspect=img_aspect)
    if prob_path is None or not prob_path.exists():
        sys.exit(f"prob map 없음: {prob_path} (--prob 로 직접 지정하세요)")

    prob = np.load(str(prob_path)).astype(np.float32)
    if prob.ndim != 2:
        prob = np.squeeze(prob)
    print(f"prob map : {prob_path}")
    print(f"prob shape={prob.shape}, min={prob.min():.3f} max={prob.max():.3f} mean={prob.mean():.3f}")

    # 실제 파이프라인처럼 prob 를 이미지 좌표계로 resize (이미지 줬을 때만)
    if bgr is not None and prob.shape[:2] != (h_img, w_img):
        pa = prob.shape[1] / prob.shape[0]
        if abs(pa - img_aspect) / img_aspect > 0.06:
            print("  ⚠️ prob 종횡비 ≠ 이미지 — 다른 도면의 prob 일 수 있음. --prob 로 맞는 것 지정 권장.")
        prob = cv2.resize(prob, (w_img, h_img), interpolation=cv2.INTER_LINEAR)
        print(f"  → prob 를 이미지 크기 ({w_img}x{h_img}) 로 resize")

    thresholds = _parse_thresholds(args)
    args.out.mkdir(parents=True, exist_ok=True)

    # ── threshold 별 마스크 ──────────────────────────────────────────
    print(f"\nthreshold 별 흑백 마스크 ({len(thresholds)}개) → {args.out}/")
    print("-" * 46)
    print(f"  {'thr':>5}  {'커버리지%':>8}  {'벽픽셀수':>10}")
    print("-" * 46)
    tiles: list[np.ndarray] = []
    extractor = None
    if args.clean:
        from app.services.floorplan.wall_extraction import wall_extractor as extractor

    for t in thresholds:
        mask = (prob > t).astype(np.uint8) * 255
        cov = float((mask > 0).mean()) * 100
        px = int((mask > 0).sum())
        tag = f"{t:.2f}".replace(".", "")
        cv2.imwrite(str(args.out / f"mask_t{tag}.png"), mask)
        print(f"  {t:>5.2f}  {cov:>8.2f}  {px:>10,}")

        if extractor is not None:
            cleaned = extractor._preprocess(mask)  # open + H/V close
            cv2.imwrite(str(args.out / f"mask_t{tag}_clean.png"), cleaned)

        tiles.append(_label(mask, f"thr={t:.2f}  cov={cov:.2f}%"))

    # ── 비교 그리드 ─────────────────────────────────────────────────
    grid = _build_grid(tiles, cols=args.cols)
    grid_path = args.out / "_grid.png"
    cv2.imwrite(str(grid_path), grid)
    print("-" * 46)
    print(f"\n  → 개별 마스크 : {args.out}/mask_t*.png")
    if args.clean:
        print(f"  → 전처리 마스크: {args.out}/mask_t*_clean.png")
    print(f"  → 비교 그리드 : {grid_path}")
    print("\n  낮은 threshold → 글자·노이즈까지 흰색(벽), 높을수록 벽이 끊긴다.")
    print("  외벽이 어디서 끊기는지 _grid.png 에서 한눈에 비교하세요.")


if __name__ == "__main__":
    main()
