"""dimension_matching OCR/파싱 진단 스크립트.

"dimension_matching 에 넘어가는 OCR 값이 얼마나 좋은지" 를 한눈에 보기 위한 도구.
OCR raw 값 → parse_dimension_to_meters 해석 → scale 추정 → (선택) span 까지 표로 출력.

OCR 소스 3가지 (백엔드 env 에 easyocr 없어도 ②③ 으로 검사 가능):

  # ① 실제 도면 이미지로 라이브 OCR (easyocr 설치 필요)
  python scripts/inspect_dimension_ocr.py --image path/to/floorplan.png

  # ② 실행 결과 summary_json (summary_json.wall_postprocess.dimension_matches)
  python scripts/inspect_dimension_ocr.py --summary-json path/to/summary.json

  # ③ OCR entries JSON ([{"text","bbox":[x1,y1,x2,y2],"confidence"}, ...])
  python scripts/inspect_dimension_ocr.py --entries-json path/to/entries.json

  # ④ OCR 없이 파서만 빠르게 점검 (내장 샘플 + 직접 텍스트)
  python scripts/inspect_dimension_ocr.py --demo
  python scripts/inspect_dimension_ocr.py --text "3,500" --text "3.5m" --text "350cm"

선택: --walls-json [[x1,y1,x2,y2], ...] 을 주면 span/평행 길이 매칭까지 출력.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 콘솔(cp949)에서 한글 깨짐 방지 — UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# backend 루트를 import 경로에 추가 (이 파일은 backend/scripts/ 에 있음).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.floorplan.wall_extraction_helpers import dimension_matching as dm  # noqa: E402
from app.services.floorplan.wall_extraction_helpers.ocr import OCREntry  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# OCR entry 로딩 (소스별)
# ─────────────────────────────────────────────────────────────────────────
def _entries_from_image(image_path: Path) -> list[OCREntry]:
    """easyocr 로 라이브 OCR. 미설치 시 친절한 에러."""
    try:
        from app.services.floorplan.wall_extraction_helpers import ocr
    except Exception as exc:  # pragma: no cover
        sys.exit(f"OCR 모듈 import 실패: {exc}")
    try:
        import easyocr  # noqa: F401
    except ImportError:
        sys.exit(
            "easyocr 가 설치돼 있지 않습니다. 이미지 라이브 OCR 대신\n"
            "  --summary-json / --entries-json 으로 운영에서 넘어온 값을 검사하거나\n"
            "  pip install easyocr 후 다시 시도하세요."
        )
    if not image_path.exists():
        sys.exit(f"이미지 없음: {image_path}")
    return ocr.detect_text_entries(image_path)


def _coerce_entry(d: dict) -> OCREntry | None:
    bbox = d.get("bbox") or []
    if len(bbox) != 4:
        return None
    try:
        return OCREntry(
            bbox=tuple(int(round(float(v))) for v in bbox),  # type: ignore[arg-type]
            text=str(d.get("text", "")),
            confidence=float(d.get("confidence", d.get("ocr_confidence", 0.0)) or 0.0),
        )
    except (TypeError, ValueError):
        return None


def _entries_from_entries_json(path: Path) -> list[OCREntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit("entries-json 은 [{text,bbox,confidence}, ...] 형태여야 합니다.")
    out = [_coerce_entry(d) for d in data if isinstance(d, dict)]
    return [e for e in out if e is not None]


def _entries_from_summary_json(path: Path) -> list[OCREntry]:
    """summary_json.wall_postprocess 의 dimension_matches/ocr_entries 에서 복원."""
    data = json.loads(path.read_text(encoding="utf-8"))
    wp = (data.get("wall_postprocess") or data.get("summary_json", {}).get("wall_postprocess")
          if isinstance(data, dict) else None) or {}
    raw = wp.get("dimension_matches") or wp.get("ocr_entries") or []
    out = [_coerce_entry(d) for d in raw if isinstance(d, dict)]
    return [e for e in out if e is not None]


def _entries_from_texts(texts: list[str]) -> list[OCREntry]:
    """텍스트만 줄 때 — bbox 는 더미(가로 라벨로 가정). 파서 점검용."""
    entries = []
    for i, t in enumerate(texts):
        # 가로 라벨 가정한 더미 bbox (x 간격만 벌려 둠).
        x = 100 + i * 200
        entries.append(OCREntry(bbox=(x, 50, x + 60, 70), text=t, confidence=0.99))
    return entries


_DEMO_TEXTS = [
    "3,500", "3.5m", "350cm", "3500", "17,500", "17500",
    "방", "Kitchen", "1/80", "9,700", "2.3", "abc", "12",
]


# ─────────────────────────────────────────────────────────────────────────
# 리포트
# ─────────────────────────────────────────────────────────────────────────
def _print_ocr_table(entries: list[OCREntry]) -> None:
    print("\n[1] OCR raw entries  (dimension_matching 에 넘어가는 값)")
    print("-" * 88)
    print(f"{'#':>3}  {'text':<16} {'ocr_conf':>8}  {'orient':<10} {'bbox (x1,y1,x2,y2)':<26}")
    print("-" * 88)
    for i, e in enumerate(entries):
        orient = dm._bbox_orientation(e.bbox)
        bbox_s = f"({e.bbox[0]},{e.bbox[1]},{e.bbox[2]},{e.bbox[3]})"
        print(f"{i:>3}  {e.text!r:<16} {e.confidence:>8.3f}  {orient:<10} {bbox_s:<26}")
    print(f"\n총 {len(entries)} 개 OCR 항목")


def _print_parse_table(entries: list[OCREntry]) -> None:
    print("\n[2] 치수 파싱  (parse_dimension_to_meters)")
    print("-" * 88)
    print(f"{'#':>3}  {'text':<16} {'parsed_m':>10} {'parse_conf':>10}  {'unit_hint':<12} note")
    print("-" * 88)
    parsed_n = 0
    conf_buckets = {1.0: 0, 0.5: 0, 0.3: 0}
    for i, e in enumerate(entries):
        p = dm.parse_dimension_to_meters(e.text)
        if p is None:
            print(f"{i:>3}  {e.text!r:<16} {'-':>10} {'-':>10}  {'-':<12} 치수 아님")
            continue
        parsed_n += 1
        conf_buckets[p.confidence] = conf_buckets.get(p.confidence, 0) + 1
        print(f"{i:>3}  {e.text!r:<16} {p.meters:>10.4f} {p.confidence:>10.2f}  {p.unit_hint:<12}")
    print(
        f"\n파싱 성공 {parsed_n}/{len(entries)}  "
        f"(신뢰도 1.0(단위명시)={conf_buckets.get(1.0,0)}, "
        f"0.5(comma/decimal)={conf_buckets.get(0.5,0)}, "
        f"0.3(맨숫자추정)={conf_buckets.get(0.3,0)})"
    )


def _print_scale(entries: list[OCREntry], walls: list | None = None) -> None:
    print("\n[3] scale 추정  (tick-interval vs 교차검증)")
    print("-" * 88)
    pairs = dm.find_dimension_interval_pairs(entries)
    if not pairs:
        print("인접 치수 페어 없음 — 같은 치수선 위 텍스트가 2개 미만이거나 파싱 실패.")
        return
    for p in pairs:
        print(
            f"  {p.text_a!r:>10} ↔ {p.text_b!r:<10} "
            f"{p.orientation:<10} dx={p.center_distance_px:>7.1f}px "
            f"→ {p.implied_scale_m_per_px:.6f} m/px"
        )
    est = dm.estimate_scale_from_intervals(pairs)
    if est is None:
        print("\n→ tick-interval scale 추정 실패 (유효 페어 부족 / 분산 큼).")
    else:
        print(
            f"\n→ tick-interval scale = {est.scale_m_per_px:.6f} m/px  "
            f"(페어 {est.pair_count}개, median={est.median:.6f}, "
            f"mad={est.mad:.6f}, outlier {est.outliers_dropped}개 제외)"
        )

    # 교차검증(anchored) — 긴 기준선 cluster 합의 (walls 있으면 외곽 anchor 도 포함)
    cv = dm.estimate_scale_crossvalidated(entries, walls)
    if cv is not None:
        print(
            f"→ 교차검증 scale  = {cv.scale_m_per_px:.6f} m/px  "
            f"(동의 {cv.pair_count}개, mad={cv.mad:.6f}, "
            f"이상치 {cv.outliers_dropped}개 배제) ★ 더 안정적"
        )
        for c in cv.used_pairs:
            print(f"     ✓ {c['source']:<8} baseline={c['baseline_px']:>7.0f}px → {c['scale_m_per_px']:.6f}")


def _print_spans(entries: list[OCREntry], walls: list[list[float]], scale: float) -> None:
    print("\n[4] span / 평행 길이 매칭  (walls + scale 제공 시)")
    print("-" * 88)
    spans = dm.build_dimension_spans(entries, scale, walls)
    if not spans:
        print("span 생성 안 됨 (치수/스케일/벽 부족).")
        return
    for s in spans:
        print(
            f"  {s.text!r:>10} {s.orientation:<10} "
            f"axis {s.axis_lo:>7.1f}~{s.axis_hi:<7.1f} "
            f"경계벽 lo={s.boundary_lo_wall} hi={s.boundary_hi_wall}  {s.meters:.3f}m"
        )
    wlen = dm.attach_wall_lengths_parallel(spans, walls)
    print("\n  벽 평행 길이:")
    for idx, v in sorted(wlen.items()):
        print(f"    wall[{idx}] = {v['meters']:.3f} m  ({v['text']})")


# ─────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="dimension_matching OCR/파싱 진단")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", type=Path, help="도면 이미지 (easyocr 라이브 OCR)")
    src.add_argument("--summary-json", type=Path, help="실행 결과 summary_json")
    src.add_argument("--entries-json", type=Path, help="OCR entries JSON")
    src.add_argument("--demo", action="store_true", help="내장 샘플 텍스트로 파서 점검")
    src.add_argument("--text", action="append", default=[], help="직접 텍스트 (반복 가능)")
    ap.add_argument("--walls-json", type=Path, help="[[x1,y1,x2,y2],...] (span 매칭용)")
    ap.add_argument("--scale", type=float, help="m/px (없으면 OCR tick-interval 추정값 사용)")
    args = ap.parse_args()

    if args.image:
        entries = _entries_from_image(args.image)
    elif args.summary_json:
        entries = _entries_from_summary_json(args.summary_json)
    elif args.entries_json:
        entries = _entries_from_entries_json(args.entries_json)
    elif args.demo:
        entries = _entries_from_texts(_DEMO_TEXTS)
    else:
        entries = _entries_from_texts(args.text)

    if not entries:
        sys.exit("OCR entry 가 0개입니다. 소스를 확인하세요.")

    walls = json.loads(args.walls_json.read_text(encoding="utf-8")) if args.walls_json else None

    _print_ocr_table(entries)
    _print_parse_table(entries)
    _print_scale(entries, walls)

    if walls is not None:
        scale = args.scale
        if scale is None:
            est = dm.estimate_scale_from_intervals(dm.find_dimension_interval_pairs(entries))
            scale = est.scale_m_per_px if est else None
        if not scale or scale <= 0:
            print("\n[4] span 생략 — scale 없음 (--scale 로 직접 지정 가능).")
        else:
            _print_spans(entries, walls, float(scale))


if __name__ == "__main__":
    main()
