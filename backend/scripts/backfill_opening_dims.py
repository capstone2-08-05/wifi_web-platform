"""기존 opening row 의 width_m / height_m / sill_height_m 단위 보정 backfill.

배경:
  - 과거 fusion/save_scene_draft 버그로 width_m/height_m 에 픽셀 bbox 크기가
    그대로 저장됨 (예: width_m="38.000" 인데 실제 문 폭은 0.23m).
  - 수정 후 새 분석은 정상이지만, 이미 저장된 draft_openings / openings row 는
    잘못된 값이 남아있음.

보정 로직 (row 별):
  - width_m       = line_geom 의 실제 길이(미터). line_geom 은 이미 미터 좌표라 신뢰 가능.
                    line_geom 이 NULL 이면 width_m 은 건드리지 않음 (복원 불가).
  - height_m      = opening_type 별 표준값 (door 2.1 / window 1.2). 항상 보정.
  - sill_height_m = opening_type 별 표준값 (door 0.0 / window 0.9). 항상 보정.

대상 테이블:
  - draft_openings  (SceneDraft 의 opening)
  - openings        (SceneVersion 의 opening - promote 시 draft 값 복사됨)

사용법:
  # dry-run (변경 없이 미리보기)
  python -m scripts.backfill_opening_dims --dry-run

  # 실제 적용
  python -m scripts.backfill_opening_dims

  # 특정 테이블만
  python -m scripts.backfill_opening_dims --table draft_openings
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.geometry import line_geom_length_m, opening_type_dims
from app.models.draft_opening import DraftOpening
from app.models.opening import Opening

# 보정 정책: line_geom 이 있으면 기존 width_m 값(픽셀이든 미터든) 무관하게
# line 길이로 전체 보정. 기존 데이터 신뢰도가 낮아 "의심 값만 선별 보정" 하지 않음.


def _round3(value: float) -> Decimal:
    return Decimal(str(round(value, 3)))


def _backfill_table(db: Session, model, label: str, *, dry_run: bool) -> dict[str, int]:
    rows = db.execute(select(model)).scalars().all()
    stats = {
        "total": len(rows),
        "width_fixed": 0,
        "width_skipped_no_geom": 0,
        "height_fixed": 0,
        "sill_fixed": 0,
    }

    for row in rows:
        # --- width_m: line_geom 길이로 보정 ---
        length_m = line_geom_length_m(row.line_geom)
        if length_m is not None:
            new_width = _round3(length_m)
            if row.width_m != new_width:
                old = row.width_m
                if not dry_run:
                    row.width_m = new_width
                stats["width_fixed"] += 1
                print(
                    f"  [{label}] {row.id} width_m {old} -> {new_width} "
                    f"(type={row.opening_type})"
                )
        else:
            # line_geom 이 없으면 width 는 복원 불가 - 건드리지 않음.
            stats["width_skipped_no_geom"] += 1

        # --- height_m / sill_height_m: type 표준값으로 항상 보정 ---
        height_m, sill_m = opening_type_dims(row.opening_type)
        new_height = _round3(height_m)
        new_sill = _round3(sill_m)

        if row.height_m != new_height:
            old = row.height_m
            if not dry_run:
                row.height_m = new_height
            stats["height_fixed"] += 1
            print(f"  [{label}] {row.id} height_m {old} -> {new_height}")

        if row.sill_height_m != new_sill:
            old = row.sill_height_m
            if not dry_run:
                row.sill_height_m = new_sill
            stats["sill_fixed"] += 1
            print(f"  [{label}] {row.id} sill_height_m {old} -> {new_sill}")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="opening width/height/sill 단위 보정 backfill")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="변경 없이 무엇이 바뀔지만 출력",
    )
    parser.add_argument(
        "--table",
        choices=["draft_openings", "openings", "all"],
        default="all",
        help="보정할 테이블 (기본: all)",
    )
    args = parser.parse_args()

    targets: list[tuple[type, str]] = []
    if args.table in ("draft_openings", "all"):
        targets.append((DraftOpening, "draft_openings"))
    if args.table in ("openings", "all"):
        targets.append((Opening, "openings"))

    mode = "DRY-RUN (변경 없음)" if args.dry_run else "APPLY (DB 수정)"
    print(f"=== opening dims backfill - {mode} ===\n")

    db: Session = SessionLocal()
    total_stats: dict[str, int] = {}
    try:
        for model, label in targets:
            print(f"[{label}] 처리 중...")
            stats = _backfill_table(db, model, label, dry_run=args.dry_run)
            print(
                f"[{label}] total={stats['total']} "
                f"width_fixed={stats['width_fixed']} "
                f"width_skipped_no_geom={stats['width_skipped_no_geom']} "
                f"height_fixed={stats['height_fixed']} "
                f"sill_fixed={stats['sill_fixed']}\n"
            )
            for k, v in stats.items():
                total_stats[k] = total_stats.get(k, 0) + v

        if args.dry_run:
            db.rollback()
            print("DRY-RUN 완료 - DB 변경 없음. 실제 적용하려면 --dry-run 빼고 재실행.")
        else:
            db.commit()
            print("커밋 완료.")

        print(
            f"\n합계: width_fixed={total_stats.get('width_fixed', 0)} "
            f"height_fixed={total_stats.get('height_fixed', 0)} "
            f"sill_fixed={total_stats.get('sill_fixed', 0)} "
            f"(width 복원 불가 = {total_stats.get('width_skipped_no_geom', 0)})"
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"오류 발생, 롤백함: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
