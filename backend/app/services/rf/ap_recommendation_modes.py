"""Mode-aware AP recommendation plan builder.

Four modes:
  add              — keep existing APs, recommend N new positions
  replace          — remove target AP(s), search replacement position(s)
  relocate_all     — discard all existing positions, redesign from scratch
  relocate_selected — fix some APs, relocate the chosen ones
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.schemas.rf.ap_recommendation import ApRecommendationRequest
    from app.services.rf.ap_recommendation_service import AccessPoint


@dataclass
class RecommendationPlan:
    """Resolved placement plan for a recommendation request.

    baseline_aps:  All existing APs — used for before/after RSSI comparison.
    fixed_aps:     APs always included in eval (never moved).
                   Greedy search adds candidate APs on top of these.
    movable_count: How many new AP positions to search for.
    movable_ap_ids:    IDs of APs being moved/replaced (for relocation_moves).
    movable_ap_coords: Original (x, y) of each movable AP.
    mode_explanation:  Human-readable description of this plan.
    """

    mode: str
    baseline_aps: list  # list[AccessPoint]
    fixed_aps: list     # list[AccessPoint]
    movable_count: int
    movable_ap_ids: list[str] = field(default_factory=list)
    movable_ap_coords: list[tuple[float, float]] = field(default_factory=list)
    mode_explanation: str = ""


def build_recommendation_plan(
    request: "ApRecommendationRequest",
    existing_aps: list,  # list[AccessPoint]
) -> "RecommendationPlan":
    """Resolve request fields into a RecommendationPlan."""
    mode = request.recommendation_mode
    n_aps = max(1, request.n_aps)

    # ── add ───────────────────────────────────────────────────────────────────
    if mode == "add":
        additional = getattr(request, "additional_ap_count", 0) or 0
        movable_count = max(1, additional if additional > 0 else n_aps)
        return RecommendationPlan(
            mode="add",
            baseline_aps=existing_aps,
            fixed_aps=existing_aps,
            movable_count=movable_count,
            mode_explanation=(
                f"기존 AP {len(existing_aps)}개 유지, {movable_count}개 신규 AP 위치 추천."
            ),
        )

    # ── replace ───────────────────────────────────────────────────────────────
    if mode == "replace":
        targets: list[str] = list(getattr(request, "replace_target_ap_ids", None) or [])
        if request.replace_target_ap_id and request.replace_target_ap_id not in targets:
            targets.append(request.replace_target_ap_id)

        if not targets:
            return RecommendationPlan(
                mode="replace",
                baseline_aps=existing_aps,
                fixed_aps=existing_aps,
                movable_count=1,
                mode_explanation="교체 대상 미지정 — 신규 AP 1개 위치 추천.",
            )

        target_set = set(targets)
        fixed = [ap for ap in existing_aps if ap.name not in target_set]
        moved = [ap for ap in existing_aps if ap.name in target_set]
        return RecommendationPlan(
            mode="replace",
            baseline_aps=existing_aps,
            fixed_aps=fixed,
            movable_count=max(1, len(targets)),
            movable_ap_ids=[ap.name for ap in moved],
            movable_ap_coords=[(ap.x, ap.y) for ap in moved],
            mode_explanation=(
                f"AP [{', '.join(targets)}] 교체. "
                f"나머지 {len(fixed)}개 유지 후 {len(targets)}개 새 위치 추천."
            ),
        )

    # ── relocate_all ──────────────────────────────────────────────────────────
    if mode == "relocate_all":
        total = getattr(request, "target_total_aps", None) or len(existing_aps) or n_aps
        return RecommendationPlan(
            mode="relocate_all",
            baseline_aps=existing_aps,
            fixed_aps=[],  # start from scratch
            movable_count=max(1, total),
            movable_ap_ids=[ap.name for ap in existing_aps],
            movable_ap_coords=[(ap.x, ap.y) for ap in existing_aps],
            mode_explanation=(
                f"전체 재배치 — 기존 {len(existing_aps)}개 기준, "
                f"{total}개 새 위치로 재설계."
            ),
        )

    # ── relocate_selected ─────────────────────────────────────────────────────
    if mode == "relocate_selected":
        relocate_ids: set[str] = set(getattr(request, "relocate_target_ap_ids", None) or [])
        fixed_ids: set[str] = set(getattr(request, "fixed_ap_ids", None) or [])
        if fixed_ids:
            relocate_ids -= fixed_ids

        fixed = [ap for ap in existing_aps if ap.name not in relocate_ids]
        moved = [ap for ap in existing_aps if ap.name in relocate_ids]

        if not moved:
            return RecommendationPlan(
                mode="relocate_selected",
                baseline_aps=existing_aps,
                fixed_aps=existing_aps,
                movable_count=n_aps,
                mode_explanation=f"이동 대상 미지정 — 신규 AP {n_aps}개 위치 추천.",
            )

        return RecommendationPlan(
            mode="relocate_selected",
            baseline_aps=existing_aps,
            fixed_aps=fixed,
            movable_count=len(moved),
            movable_ap_ids=[ap.name for ap in moved],
            movable_ap_coords=[(ap.x, ap.y) for ap in moved],
            mode_explanation=(
                f"선택 AP [{', '.join(ap.name for ap in moved)}] 재배치. "
                f"나머지 {len(fixed)}개 고정."
            ),
        )

    # ── unknown mode fallback → add ───────────────────────────────────────────
    return RecommendationPlan(
        mode=mode,
        baseline_aps=existing_aps,
        fixed_aps=existing_aps,
        movable_count=n_aps,
        mode_explanation="",
    )


def compute_relocation_moves(
    plan: "RecommendationPlan",
    top_ap_positions: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """Build relocation_moves for replace / relocate modes.

    Matches each movable AP to the corresponding recommended position
    by insertion order (1st moved AP → 1st new position, etc.).
    """
    if plan.mode not in ("replace", "relocate_all", "relocate_selected"):
        return []

    moves: list[dict[str, Any]] = []
    for i, (old_x, old_y) in enumerate(plan.movable_ap_coords):
        if i >= len(top_ap_positions):
            break
        new_x, new_y = top_ap_positions[i]
        ap_id = plan.movable_ap_ids[i] if i < len(plan.movable_ap_ids) else f"ap_{i + 1}"
        moves.append(
            {
                "ap_id": ap_id,
                "from_x": round(old_x, 3),
                "from_y": round(old_y, 3),
                "to_x": round(new_x, 3),
                "to_y": round(new_y, 3),
            }
        )
    return moves


def compute_final_aps(
    plan: "RecommendationPlan",
    top_ap_positions: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """Build final_aps — the complete AP layout for the top recommendation.

    fixed=True  : AP that stays in place.
    fixed=False : newly placed / relocated AP.
    """
    final: list[dict[str, Any]] = []

    for ap in plan.fixed_aps:
        final.append(
            {"id": ap.name, "x": round(ap.x, 3), "y": round(ap.y, 3), "fixed": True}
        )

    for i, (x, y) in enumerate(top_ap_positions):
        ap_id = (
            plan.movable_ap_ids[i]
            if i < len(plan.movable_ap_ids)
            else f"new_ap_{i + 1}"
        )
        final.append({"id": ap_id, "x": round(x, 3), "y": round(y, 3), "fixed": False})

    return final
