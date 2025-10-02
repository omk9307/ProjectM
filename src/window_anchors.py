"""Mapleland 창 좌표 저장/복원 및 ROI 변환 유틸리티."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import pygetwindow as gw

try:  # pragma: no cover - 플랫폼에 따라 미지원일 수 있음
    import win32con
    import win32gui
except ImportError:  # pragma: no cover - 테스트 환경 등에서 win32 미설치 가능
    win32con = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]

try:  # pragma: no cover - 멀티 모니터 정보 확보용 (Windows 전용)
    from ctypes import POINTER, Structure, byref, sizeof, windll
    from ctypes import wintypes
except ImportError:  # pragma: no cover - 비 Windows 환경 대비
    POINTER = None  # type: ignore[assignment]
    Structure = None  # type: ignore[assignment]
    byref = None  # type: ignore[assignment]
    sizeof = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]
    windll = None  # type: ignore[assignment]


MAPLE_WINDOW_TITLE = "Mapleland"


@dataclass
class WindowGeometry:
    """Mapleland 창의 위치 및 크기 정보."""

    left: int
    top: int
    width: int
    height: int
    screen_left: Optional[int] = None
    screen_top: Optional[int] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    screen_device: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_absolute_roi(self, rel_roi: Dict[str, int]) -> Dict[str, int]:
        """창 상대 ROI를 절대 좌표로 변환한다."""

        return {
            "left": self.left + int(rel_roi.get("left", 0)),
            "top": self.top + int(rel_roi.get("top", 0)),
            "width": int(rel_roi.get("width", 0)),
            "height": int(rel_roi.get("height", 0)),
        }

    def to_relative_roi(self, abs_roi: Dict[str, int]) -> Dict[str, int]:
        """절대 ROI를 창 상대 좌표로 변환한다."""

        return {
            "left": int(abs_roi.get("left", 0)) - self.left,
            "top": int(abs_roi.get("top", 0)) - self.top,
            "width": int(abs_roi.get("width", 0)),
            "height": int(abs_roi.get("height", 0)),
        }


def _workspace_config_dir() -> Path:
    base = Path(__file__).resolve().parent.parent / "workspace" / "config"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _anchor_file_path() -> Path:
    return _workspace_config_dir() / "maple_window_anchors.json"


def _load_anchor_payload() -> Dict[str, object]:
    path = _anchor_file_path()
    if not path.exists():
        return {"anchors": {}, "last_used": None}

    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (json.JSONDecodeError, OSError):
        return {"anchors": {}, "last_used": None}

    anchors = data.get("anchors") if isinstance(data, dict) else {}
    if not isinstance(anchors, dict):
        anchors = {}
    last_used = data.get("last_used") if isinstance(data, dict) else None
    return {"anchors": anchors, "last_used": last_used}


def _write_anchor_payload(payload: Dict[str, object]) -> None:
    path = _anchor_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)


def list_saved_anchors() -> Dict[str, Dict[str, object]]:
    payload = _load_anchor_payload()
    anchors = payload.get("anchors", {})
    return anchors if isinstance(anchors, dict) else {}


def save_window_anchor(name: str, geometry: WindowGeometry) -> None:
    payload = _load_anchor_payload()
    anchors: Dict[str, object] = payload.setdefault("anchors", {})  # type: ignore[assignment]
    anchors[name] = asdict(geometry)
    payload["last_used"] = name
    _write_anchor_payload(payload)


def delete_window_anchor(name: str) -> None:
    payload = _load_anchor_payload()
    anchors: Dict[str, object] = payload.get("anchors", {})  # type: ignore[assignment]
    if name in anchors:
        anchors.pop(name, None)
        if payload.get("last_used") == name:
            payload["last_used"] = None
        _write_anchor_payload(payload)


def get_anchor(name: str) -> Optional[WindowGeometry]:
    anchors = list_saved_anchors()
    data = anchors.get(name)
    if not isinstance(data, dict):
        return None
    try:
        return WindowGeometry(**{k: data.get(k) for k in WindowGeometry.__annotations__.keys()})
    except TypeError:
        return None


def _resolve_monitor_info(left: int, top: int, width: int, height: int) -> Dict[str, Optional[int]]:
    if windll is None or Structure is None or wintypes is None or byref is None or sizeof is None:  # pragma: no cover - 비 Windows 환경
        return {
            "screen_left": None,
            "screen_top": None,
            "screen_width": None,
            "screen_height": None,
            "screen_device": None,
        }

    class RECT(Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFOEXW(Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    user32 = windll.user32  # type: ignore[attr-defined]
    monitor_from_point = getattr(user32, "MonitorFromPoint", None)
    get_monitor_info = getattr(user32, "GetMonitorInfoW", None)

    if monitor_from_point is None or get_monitor_info is None:
        return {
            "screen_left": None,
            "screen_top": None,
            "screen_width": None,
            "screen_height": None,
            "screen_device": None,
        }

    point = wintypes.POINT(left + width // 2, top + height // 2)
    monitor_handle = monitor_from_point(point, 2)  # MONITOR_DEFAULTTONEAREST
    if not monitor_handle:
        return {
            "screen_left": None,
            "screen_top": None,
            "screen_width": None,
            "screen_height": None,
            "screen_device": None,
        }

    info = MONITORINFOEXW()
    info.cbSize = wintypes.DWORD(sizeof(MONITORINFOEXW))
    if not get_monitor_info(monitor_handle, byref(info)):
        return {
            "screen_left": None,
            "screen_top": None,
            "screen_width": None,
            "screen_height": None,
            "screen_device": None,
        }

    monitor_width = int(info.rcMonitor.right - info.rcMonitor.left)
    monitor_height = int(info.rcMonitor.bottom - info.rcMonitor.top)

    return {
        "screen_left": int(info.rcMonitor.left),
        "screen_top": int(info.rcMonitor.top),
        "screen_width": monitor_width,
        "screen_height": monitor_height,
        "screen_device": info.szDevice.rstrip("\x00"),
    }


def get_maple_window_geometry(title_keyword: str = MAPLE_WINDOW_TITLE) -> Optional[WindowGeometry]:
    windows = []
    try:
        windows = gw.getWindowsWithTitle(title_keyword)
    except Exception:
        return None

    target = None
    for win in windows:
        if not win:
            continue
        title = (getattr(win, "title", "") or "").strip()
        if title_keyword.lower() in title.lower():
            target = win
            break

    if target is None:
        return None

    left, top = int(target.left), int(target.top)
    width, height = int(target.width), int(target.height)
    if width <= 0 or height <= 0:
        return None

    info = _resolve_monitor_info(left, top, width, height)
    return WindowGeometry(
        left=left,
        top=top,
        width=width,
        height=height,
        screen_left=info.get("screen_left"),
        screen_top=info.get("screen_top"),
        screen_width=info.get("screen_width"),
        screen_height=info.get("screen_height"),
        screen_device=info.get("screen_device"),
        timestamp=time.time(),
    )


def restore_maple_window(anchor: WindowGeometry, *, allow_resize: bool = True) -> Tuple[bool, str]:
    geometry = get_maple_window_geometry()
    if geometry is None:
        return False, "Mapleland 창을 찾을 수 없습니다."

    try:
        pg_window = next(
            win
            for win in gw.getWindowsWithTitle(MAPLE_WINDOW_TITLE)
            if win and getattr(win, "title", "").lower().find(MAPLE_WINDOW_TITLE.lower()) != -1
        )
    except StopIteration:
        return False, "Mapleland 창 핸들을 찾을 수 없습니다."
    except Exception as exc:
        return False, f"창 목록을 읽는 중 오류가 발생했습니다: {exc}"

    hw = getattr(pg_window, "_hWnd", None)

    target_left, target_top = int(anchor.left), int(anchor.top)
    target_width, target_height = int(anchor.width), int(anchor.height)

    if win32gui and hw:
        flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        if not allow_resize:
            flags |= win32con.SWP_NOSIZE
        try:
            win32gui.SetWindowPos(hw, None, target_left, target_top, target_width, target_height, flags)
        except Exception as exc:  # pragma: no cover - SetWindowPos 실패 시
            return False, f"창 위치 복원 실패: {exc}"
    else:  # pragma: no cover - win32gui 미사용 시 pygetwindow로 폴백
        try:
            pg_window.moveTo(target_left, target_top)
            if allow_resize:
                pg_window.resizeTo(target_width, target_height)
        except Exception as exc:
            return False, f"창 이동/사이즈 조정 실패: {exc}"

    return True, "창 좌표를 복원했습니다."


def convert_multiple_rois_to_relative(
    rois: Iterable[Dict[str, int]],
    geometry: WindowGeometry,
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]]]:
    """여러 ROI를 상대좌표로 변환한다.

    반환값은 (relative_map, absolute_map)이며, key는 호출 측에서 지정해야 한다.
    해당 함수는 Convenience 용으로 남겨두며, 직접 key를 지정할 때 활용한다.
    """

    relative: Dict[str, Dict[str, int]] = {}
    absolute: Dict[str, Dict[str, int]] = {}
    for idx, roi in enumerate(rois):
        key = f"roi_{idx}"
        relative[key] = geometry.to_relative_roi(roi)
        absolute[key] = geometry.to_absolute_roi(relative[key])
    return relative, absolute


def anchor_exists(name: str) -> bool:
    anchors = list_saved_anchors()
    return name in anchors


def set_last_used_anchor(name: Optional[str]) -> None:
    payload = _load_anchor_payload()
    anchors = payload.get("anchors", {})
    if not isinstance(anchors, dict):
        anchors = {}
    if name is None or name not in anchors:
        payload["last_used"] = None
    else:
        payload["last_used"] = name
    _write_anchor_payload(payload)


def last_used_anchor_name() -> Optional[str]:
    payload = _load_anchor_payload()
    raw_name = payload.get("last_used")
    return raw_name if isinstance(raw_name, str) else None


RELATIVE_ROI_MODE = "relative_to_window"


def make_relative_roi(
    absolute_roi: Dict[str, int],
    window: WindowGeometry,
    *,
    anchor_name: Optional[str] = None,
) -> Dict[str, object]:
    """절대 ROI를 Maple 창 상대 좌표로 직렬화한다."""

    relative_rect = window.to_relative_roi(absolute_roi)
    payload: Dict[str, object] = {
        "mode": RELATIVE_ROI_MODE,
        "rect": relative_rect,
        "window": asdict(window),
        "updated_at": time.time(),
    }
    if anchor_name:
        payload["anchor_name"] = anchor_name
    return payload


def is_relative_roi(roi_payload: Optional[Dict[str, object]]) -> bool:
    return bool(isinstance(roi_payload, dict) and roi_payload.get("mode") == RELATIVE_ROI_MODE)


def _window_from_payload(payload: Dict[str, object]) -> Optional[WindowGeometry]:
    window_data = payload.get("window")
    if not isinstance(window_data, dict):
        return None
    try:
        kwargs = {}
        for key in WindowGeometry.__annotations__.keys():
            value = window_data.get(key)
            if value is None and key in {"left", "top", "width", "height"}:
                return None
            kwargs[key] = value
        return WindowGeometry(**kwargs)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def resolve_roi_to_absolute(
    roi_payload: Optional[Dict[str, object]],
    *,
    window: Optional[WindowGeometry] = None,
) -> Optional[Dict[str, int]]:
    """ROI 데이터를 절대 좌표로 변환한다. 상대 데이터면 주어진 창 좌표를 활용한다."""

    if roi_payload is None:
        return None

    if is_relative_roi(roi_payload):
        rect = roi_payload.get("rect")
        if not isinstance(rect, dict):
            return None
        reference_window = window or _window_from_payload(roi_payload)
        if reference_window is None:
            return None
        return reference_window.to_absolute_roi(rect)

    # 구버전 절대 좌표 지원
    if all(key in roi_payload for key in ("left", "top", "width", "height")):
        try:
            return {
                "left": int(roi_payload["left"]),
                "top": int(roi_payload["top"]),
                "width": int(roi_payload["width"]),
                "height": int(roi_payload["height"]),
            }
        except (TypeError, ValueError):
            return None
    return None


def ensure_relative_roi(
    roi_payload: Optional[Dict[str, object]],
    window: Optional[WindowGeometry],
    *,
    anchor_name: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    """ROI가 상대 좌표가 아니라면 가능한 경우 상대 좌표로 변환한다."""

    if roi_payload is None:
        return None
    if is_relative_roi(roi_payload):
        return roi_payload
    if window is None:
        return roi_payload
    absolute = resolve_roi_to_absolute(roi_payload)
    if absolute is None:
        return roi_payload
    return make_relative_roi(absolute, window, anchor_name=anchor_name)


__all__ = [
    "WindowGeometry",
    "MAPLE_WINDOW_TITLE",
    "get_maple_window_geometry",
    "restore_maple_window",
    "save_window_anchor",
    "list_saved_anchors",
    "get_anchor",
    "anchor_exists",
    "delete_window_anchor",
    "last_used_anchor_name",
    "set_last_used_anchor",
    "make_relative_roi",
    "resolve_roi_to_absolute",
    "ensure_relative_roi",
    "is_relative_roi",
    "RELATIVE_ROI_MODE",
]
