"""맵탭 전역 X → 사냥탭 프레임 X 선형 보정(calibration) 저장/조회 유틸리티.

구성 파일: workspace/config/map_hunt_calibration.json

스키마 예시:
{
  "enabled": true,
  "entries": {
    "<profile_name>": {
      "<roi_sig>": {
        "a": 1.234,
        "b": 56.7,
        "points": {"left": {"map_x": 0.0, "hunt_x": 123.0}, "right": {"map_x": 1000.0, "hunt_x": 923.0}}
      }
    }
  }
}
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


_CACHE: dict[str, Any] = {
    "loaded_ts": 0.0,
    "payload": None,
}


def _workspace_config_dir() -> Path:
    base = Path(__file__).resolve().parent.parent / "workspace" / "config"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _config_path() -> Path:
    return _workspace_config_dir() / "map_hunt_calibration.json"


def _load_payload() -> dict:
    path = _config_path()
    if not path.exists():
        return {"enabled": False, "entries": {}}
    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "entries": {}}
    if not isinstance(data, dict):
        return {"enabled": False, "entries": {}}
    if not isinstance(data.get("entries"), dict):
        data["entries"] = {}
    if "enabled" not in data:
        data["enabled"] = False
    return data


def _save_payload(payload: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    _CACHE["loaded_ts"] = time.time()
    _CACHE["payload"] = payload


def _get_cached_payload() -> dict:
    now = time.time()
    payload = _CACHE.get("payload")
    if payload is not None and (now - float(_CACHE.get("loaded_ts", 0.0))) < 1.0:
        return payload
    payload = _load_payload()
    _CACHE["loaded_ts"] = now
    _CACHE["payload"] = payload
    return payload


def is_enabled() -> bool:
    try:
        return bool(_get_cached_payload().get("enabled", False))
    except Exception:
        return False


def set_enabled(enabled: bool) -> None:
    payload = _get_cached_payload()
    payload["enabled"] = bool(enabled)
    _save_payload(payload)


def roi_signature(roi: dict | None) -> Optional[str]:
    """ROI(절대좌표)의 간단 서명 문자열 생성.
    입력 예: {left, top, width, height}
    """
    if not isinstance(roi, dict):
        return None
    try:
        l = int(roi.get("left", 0))
        t = int(roi.get("top", 0))
        w = int(roi.get("width", 0))
        h = int(roi.get("height", 0))
        if w <= 0 or h <= 0:
            return None
        return f"L{l}_T{t}_W{w}_H{h}"
    except Exception:
        return None


def save_calibration(
    profile: str,
    roi: dict,
    left_pair: Tuple[float, float],
    right_pair: Tuple[float, float],
) -> Tuple[bool, str]:
    """두 점(left/right)으로 선형 보정 y = a*x + b 를 계산/저장.
    - x: map_x(전역), y: hunt_center_x(프레임)
    """
    if not isinstance(profile, str) or not profile.strip():
        return False, "프로필명이 유효하지 않습니다."
    sig = roi_signature(roi)
    if sig is None:
        return False, "ROI 정보가 유효하지 않습니다."
    try:
        x1, y1 = float(left_pair[0]), float(left_pair[1])
        x2, y2 = float(right_pair[0]), float(right_pair[1])
    except Exception:
        return False, "좌우 샘플 좌표가 유효하지 않습니다."
    if abs(x2 - x1) < 1e-6:
        return False, "맵 X 좌표 차이가 너무 작습니다. 다른 지점에서 다시 시도하세요."
    a = (y2 - y1) / (x2 - x1)
    b = y1 - a * x1
    payload = _get_cached_payload()
    entries = payload.setdefault("entries", {})  # type: ignore[assignment]
    prof = entries.setdefault(profile.strip(), {})  # type: ignore[assignment]
    prof[sig] = {
        "a": float(a),
        "b": float(b),
        "points": {
            "left": {"map_x": float(x1), "hunt_x": float(y1)},
            "right": {"map_x": float(x2), "hunt_x": float(y2)},
        },
    }
    _save_payload(payload)
    return True, "캘리브레이션이 저장되었습니다."


def find_calibration(profile: str, roi: dict | None) -> Optional[Tuple[float, float]]:
    """해당 프로필+ROI 서명에 매칭되는 (a,b)을 반환. 없으면 None."""
    if not isinstance(profile, str) or not profile.strip():
        return None
    sig = roi_signature(roi)
    if sig is None:
        return None
    payload = _get_cached_payload()
    try:
        entry = payload.get("entries", {}).get(profile.strip(), {}).get(sig)
        if not isinstance(entry, dict):
            return None
        a = float(entry.get("a"))
        b = float(entry.get("b"))
        return (a, b)
    except Exception:
        return None


def clear_calibration(profile: str, roi: dict | None) -> Tuple[bool, str]:
    sig = roi_signature(roi)
    if not isinstance(profile, str) or not profile.strip() or sig is None:
        return False, "프로필 또는 ROI가 유효하지 않습니다."
    payload = _get_cached_payload()
    try:
        prof = payload.get("entries", {}).get(profile.strip())
        if isinstance(prof, dict) and sig in prof:
            prof.pop(sig, None)
            _save_payload(payload)
            return True, "해당 ROI의 캘리브레이션을 삭제했습니다."
        return False, "삭제할 항목이 없습니다."
    except Exception as exc:
        return False, f"삭제 실패: {exc}"

