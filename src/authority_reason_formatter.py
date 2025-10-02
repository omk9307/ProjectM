from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional

NumberLike = Optional[float]


def format_authority_reason(reason: Optional[str], meta: Optional[Dict[str, Any]] = None) -> str:
    """사냥/맵 권한 사유 코드를 사람이 읽기 쉬운 문장으로 변환한다."""

    if not isinstance(reason, str):
        return ""

    normalized = reason.strip()
    if not normalized:
        return normalized

    meta_dict = meta if isinstance(meta, dict) else {}
    handler = _HANDLERS.get(normalized.upper())
    if handler:
        formatted = handler(meta_dict)
        if formatted:
            return formatted

    # 매칭되는 핸들러가 없으면 기존 문자열을 그대로 반환한다.
    return normalized


def _format_monster_ready(meta: Dict[str, Any]) -> str:
    total = _extract_number(meta, ("latest_monster_count", "monster_count"))
    total_threshold = _extract_number(meta, ("hunt_monster_threshold", "monster_threshold"))
    primary = _extract_number(meta, ("latest_primary_monster_count", "primary_monster_count"))
    primary_threshold = _extract_number(meta, ("primary_monster_threshold",))

    details: list[str] = []
    if total is not None:
        if total_threshold and total_threshold > 0:
            details.append(
                f"사냥범위 {_format_count(total)}마리 ≥ 기준 {_format_count(total_threshold)}마리"
            )
        else:
            details.append(f"사냥범위 {_format_count(total)}마리")

    if primary is not None:
        if primary_threshold and primary_threshold > 0:
            details.append(
                f"주 스킬 {_format_count(primary)}마리 ≥ 기준 {_format_count(primary_threshold)}마리"
            )
        else:
            details.append(f"주 스킬 {_format_count(primary)}마리")

    if not details:
        return "몬스터 조건 충족"

    return "몬스터 조건 충족: " + ", ".join(details)


def _format_monster_shortage(meta: Dict[str, Any]) -> str:
    total = _extract_number(meta, ("latest_monster_count", "monster_count"))
    total_threshold = _extract_number(meta, ("hunt_monster_threshold", "monster_threshold"))
    primary = _extract_number(meta, ("latest_primary_monster_count", "primary_monster_count"))
    primary_threshold = _extract_number(meta, ("primary_monster_threshold",))
    idle_elapsed = _extract_number(meta, ("idle_elapsed",))
    idle_limit = _extract_number(meta, ("idle_limit",))

    details: list[str] = []
    if (
        total is not None
        and total_threshold is not None
        and total_threshold > 0
        and total < total_threshold
    ):
        details.append(
            f"사냥범위 {_format_count(total)}마리 < 기준 {_format_count(total_threshold)}마리"
        )

    if (
        primary is not None
        and primary_threshold is not None
        and primary_threshold > 0
        and primary < primary_threshold
    ):
        details.append(
            f"주 스킬 {_format_count(primary)}마리 < 기준 {_format_count(primary_threshold)}마리"
        )

    if idle_elapsed is not None and idle_limit is not None and idle_limit > 0:
        details.append(
            f"최근 미탐지 {_format_duration(idle_elapsed)} / 기준 {_format_duration(idle_limit)}"
        )

    if not details:
        return "몬스터 부족"

    return "몬스터 부족: " + ", ".join(details)


def _format_max_hold_exceeded(meta: Dict[str, Any]) -> str:
    elapsed = _extract_number(meta, ("hold_elapsed",))
    limit = _extract_number(meta, ("hold_limit", "timeout"))

    if elapsed is not None and limit is not None and limit > 0:
        return (
            "사냥 권한 최대 유지 시간 초과: "
            f"경과 {_format_duration(elapsed)} ≥ 제한 {_format_duration(limit)}"
        )
    if elapsed is not None:
        return f"사냥 권한 최대 유지 시간 초과: 경과 {_format_duration(elapsed)}"
    return "사냥 권한 최대 유지 시간 초과"


def _format_max_total_hold_exceeded(meta: Dict[str, Any]) -> str:
    elapsed = _extract_number(meta, ("hold_elapsed",))
    limit = _extract_number(meta, ("total_limit",))

    if elapsed is not None and limit is not None and limit > 0:
        return (
            "총 권한 보유 시간 초과: "
            f"경과 {_format_duration(elapsed)} ≥ 제한 {_format_duration(limit)}"
        )
    if elapsed is not None:
        return f"총 권한 보유 시간 초과: 경과 {_format_duration(elapsed)}"
    return "총 권한 보유 시간 초과"


def _format_floor_hold_exceeded(meta: Dict[str, Any]) -> str:
    elapsed = _extract_number(meta, ("floor_elapsed",))
    limit = _extract_number(meta, ("floor_limit",))
    floor = meta.get("floor") if isinstance(meta.get("floor"), (int, float, str)) else None

    details: list[str] = []
    if floor is not None:
        details.append(f"층 {floor}")
    if elapsed is not None and limit is not None and limit > 0:
        details.append(
            f"경과 {_format_duration(elapsed)} ≥ 제한 {_format_duration(limit)}"
        )
    elif elapsed is not None:
        details.append(f"경과 {_format_duration(elapsed)}")

    prefix = "층별 권한 유지 시간 초과"
    if not details:
        return prefix
    return prefix + ": " + ", ".join(details)


def _extract_number(meta: Dict[str, Any], keys: Iterable[str]) -> NumberLike:
    for key in keys:
        if key not in meta:
            continue
        value = meta.get(key)
        number = _coerce_number(value)
        if number is not None:
            return number
    return None


def _coerce_number(value: Any) -> NumberLike:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _format_count(value: float) -> str:
    if math.isfinite(value) and abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return _format_float(value)


def _format_duration(value: float) -> str:
    return _format_float(value) + "초"


def _format_float(value: float) -> str:
    if not math.isfinite(value):
        return "?"
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}".rstrip("0").rstrip(".")


_HANDLERS = {
    "MONSTER_READY": _format_monster_ready,
    "MONSTER_SHORTAGE": _format_monster_shortage,
    "MAX_HOLD_EXCEEDED": _format_max_hold_exceeded,
    "MAX_TOTAL_HOLD_EXCEEDED": _format_max_total_hold_exceeded,
    "FLOOR_HOLD_EXCEEDED": _format_floor_hold_exceeded,
}

