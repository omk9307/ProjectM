"""HP/MP/EXP 상태 감지를 담당하는 보조 모듈."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

import copy

import cv2
import numpy as np
from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QThread, pyqtSignal

from capture_manager import get_capture_manager
from window_anchors import get_maple_window_geometry, resolve_roi_to_absolute

try:
    import pytesseract  # type: ignore

    PYTESSERACT_AVAILABLE = True
except ImportError:  # pragma: no cover - 실행 환경에 따라 미설치일 수 있음
    PYTESSERACT_AVAILABLE = False


GRAY_FULL_COLOR = np.array([109, 109, 109], dtype=np.int16)  # #6d6d6d
GRAY_BOUNDARY_CANDIDATES = [
    np.array([95, 95, 95], dtype=np.int16),  # #5f5f5f
    np.array([82, 82, 82], dtype=np.int16),  # #525252
]
COLOR_TOLERANCE = 3


@dataclass
class Roi:
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def to_monitor_dict(self) -> Dict[str, int]:
        return {
            "left": int(self.left),
            "top": int(self.top),
            "width": int(self.width),
            "height": int(self.height),
        }

    @staticmethod
    def from_dict(data: Optional[Dict[str, int]]) -> "Roi":
        if not isinstance(data, dict):
            return Roi()
        try:
            return Roi(
                left=int(data.get("left", 0)),
                top=int(data.get("top", 0)),
                width=int(data.get("width", 0)),
                height=int(data.get("height", 0)),
            )
        except (TypeError, ValueError):
            return Roi()


@dataclass
class ResourceConfig:
    roi: Roi = field(default_factory=Roi)
    interval_sec: float = 1.0
    recovery_threshold: Optional[int] = None
    command_profile: Optional[str] = None
    enabled: bool = True
    maximum_value: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "roi": {
                "left": self.roi.left,
                "top": self.roi.top,
                "width": self.roi.width,
                "height": self.roi.height,
            },
            "interval_sec": float(max(0.1, self.interval_sec)),
            "enabled": bool(self.enabled),
        }
        if self.maximum_value is not None:
            data["max_value"] = int(self.maximum_value)
        if self.recovery_threshold is not None:
            data["recovery_threshold"] = int(self.recovery_threshold)
        if self.command_profile is not None:
            data["command_profile"] = self.command_profile
        return data

    @staticmethod
    def from_dict(source: Optional[Dict[str, object]], *, allow_threshold: bool = True) -> "ResourceConfig":
        if not isinstance(source, dict):
            return ResourceConfig()
        roi = Roi.from_dict(source.get("roi"))
        try:
            interval = float(source.get("interval_sec", 1.0))
        except (TypeError, ValueError):
            interval = 1.0
        interval = max(0.1, float(interval))
        threshold_val: Optional[int] = None
        command: Optional[str] = None
        if allow_threshold:
            threshold = source.get("recovery_threshold")
            try:
                if threshold is not None:
                    threshold_val = int(threshold)
            except (TypeError, ValueError):
                threshold_val = None
            command_raw = source.get("command_profile")
            if isinstance(command_raw, str):
                command = command_raw
        enabled = bool(source.get("enabled", True))
        max_value: Optional[int] = None
        max_raw = source.get("max_value")
        if max_raw not in (None, ""):
            try:
                parsed = int(max_raw)
            except (TypeError, ValueError):
                parsed = None
            else:
                if parsed > 0:
                    max_value = parsed
        return ResourceConfig(
            roi=roi,
            interval_sec=interval,
            recovery_threshold=threshold_val,
            command_profile=command,
            enabled=enabled,
            maximum_value=max_value,
        )


@dataclass
class StatusMonitorConfig:
    hp: ResourceConfig = field(default_factory=lambda: ResourceConfig(interval_sec=1.0))
    mp: ResourceConfig = field(default_factory=lambda: ResourceConfig(interval_sec=1.0))
    exp: ResourceConfig = field(default_factory=lambda: ResourceConfig(interval_sec=60.0))

    @staticmethod
    def default() -> "StatusMonitorConfig":
        cfg = StatusMonitorConfig()
        cfg.hp.recovery_threshold = 70
        cfg.mp.recovery_threshold = 50
        cfg.hp.command_profile = ""
        cfg.mp.command_profile = ""
        cfg.exp.interval_sec = 60.0
        cfg.hp.enabled = True
        cfg.mp.enabled = True
        cfg.exp.enabled = True
        return cfg

    def to_dict(self) -> Dict[str, Dict[str, object]]:
        exp_data: Dict[str, object] = {
            "roi": {
                "left": self.exp.roi.left,
                "top": self.exp.roi.top,
                "width": self.exp.roi.width,
                "height": self.exp.roi.height,
            },
            "interval_sec": float(max(1.0, self.exp.interval_sec)),
            "enabled": bool(self.exp.enabled),
        }
        if self.exp.maximum_value is not None:
            exp_data["max_value"] = int(self.exp.maximum_value)

        return {
            "hp": self.hp.to_dict(),
            "mp": self.mp.to_dict(),
            "exp": exp_data,
        }

    @staticmethod
    def from_dict(data: Optional[Dict[str, object]]) -> "StatusMonitorConfig":
        default_cfg = StatusMonitorConfig.default()
        if not isinstance(data, dict):
            return default_cfg
        hp_cfg = ResourceConfig.from_dict(data.get("hp"), allow_threshold=True)
        mp_cfg = ResourceConfig.from_dict(data.get("mp"), allow_threshold=True)
        exp_cfg = ResourceConfig.from_dict(data.get("exp"), allow_threshold=False)
        if exp_cfg.interval_sec < 1.0:
            exp_cfg.interval_sec = 60.0
        cfg = StatusMonitorConfig(hp=hp_cfg, mp=mp_cfg, exp=exp_cfg)
        return cfg


class StatusMonitorThread(QThread):
    """HP/MP/EXP 상태를 주기적으로 읽어오는 백그라운드 스레드."""

    status_captured = pyqtSignal(dict)
    ocr_unavailable = pyqtSignal()
    exp_status_logged = pyqtSignal(str, str)

    def __init__(
        self,
        config: StatusMonitorConfig,
        *,
        roi_payloads: Optional[Dict[str, dict]] = None,
        roi_provider: Optional[Callable[[], Dict[str, dict]]] = None,
    ):
        super().__init__()
        self._config = config
        self._roi_payloads: Dict[str, dict] = copy.deepcopy(roi_payloads) if roi_payloads else {}
        self._roi_provider = roi_provider
        self._active_hunt = False
        self._active_map = False
        self._running = True
        self._lock = QMutex()
        self._last_capture: Dict[str, float] = {"hp": 0.0, "mp": 0.0, "exp": 0.0}
        self._latest_status: Dict[str, dict] = {}
        self._warned_ocr_missing = not PYTESSERACT_AVAILABLE
        self._last_exp_log_text = ""
        self._last_exp_snapshot: Optional[Tuple[int, float]] = None
        self._exp_roi_warned = False
        self._exp_capture_warned = False
        self._exp_failure_cache: Optional[str] = None
        self._exp_last_log_signature: Optional[Tuple[str, str]] = None
        self._manager = get_capture_manager()
        self._consumer_prefix = f"status:{id(self)}"
        self._resource_consumers: Dict[str, str] = {}
        self._resource_regions: Dict[str, Dict[str, int]] = {}

    # -------------------- public API --------------------
    def update_config(self, config: StatusMonitorConfig) -> None:
        with QMutexLocker(self._lock):
            self._config = config
            if self._roi_provider:
                try:
                    payloads = self._roi_provider()
                except Exception:
                    payloads = None
                if isinstance(payloads, dict):
                    self._roi_payloads = copy.deepcopy(payloads)
            self._last_exp_log_text = ""
            self._last_capture["exp"] = 0.0
            self._last_exp_snapshot = None
            self._exp_roi_warned = False
            self._exp_capture_warned = False
            self._exp_failure_cache = None
            self._exp_last_log_signature = None

    def set_roi_payloads(self, payloads: Dict[str, dict]) -> None:
        with QMutexLocker(self._lock):
            self._roi_payloads = copy.deepcopy(payloads)

    def set_tab_active(self, *, hunt: Optional[bool] = None, map_tab: Optional[bool] = None) -> None:
        with QMutexLocker(self._lock):
            if hunt is not None:
                previous = self._active_hunt
                self._active_hunt = bool(hunt)
                if self._active_hunt and not previous:
                    self._last_capture["exp"] = 0.0
                    self._last_exp_snapshot = None
                    self._exp_roi_warned = False
                    self._exp_capture_warned = False
                    self._exp_failure_cache = None
                    self._exp_last_log_signature = None
                    self._emit_exp_log("info", "[EXP] 감시를 시작합니다.", dedupe=False)
                if not self._active_hunt and previous:
                    self._emit_exp_log("info", "[EXP] 감시를 종료합니다.", dedupe=False)
                    self._last_capture["exp"] = 0.0
            if map_tab is not None:
                self._active_map = bool(map_tab)

    def latest_status(self) -> Dict[str, dict]:
        with QMutexLocker(self._lock):
            return dict(self._latest_status)

    def stop(self) -> None:
        self._running = False

    # -------------------- QThread API --------------------
    def run(self) -> None:  # noqa: D401
        try:
            while self._running:
                snapshot = self._evaluate_once()
                if snapshot:
                    self.status_captured.emit(snapshot)
                time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - 안전 로그용
            print(f"[StatusMonitorThread] 스레드 오류: {exc}")
        finally:
            self._unregister_all_resources()

    # -------------------- 내부 로직 --------------------
    def _evaluate_once(self) -> Dict[str, object]:
        now = time.time()
        tasks: Tuple[str, ...] = ("hp", "mp", "exp")
        snapshot: Dict[str, object] = {}

        with QMutexLocker(self._lock):
            config = self._config
            active_hunt = self._active_hunt
            active_map = self._active_map
            roi_payloads = copy.deepcopy(self._roi_payloads)

        window_geometry = get_maple_window_geometry()

        for resource in tasks:
            cfg = getattr(config, resource)
            if not getattr(cfg, 'enabled', True):
                self._unregister_resource(resource)
                continue
            if resource in {"hp", "mp"} and not (active_hunt or active_map):
                self._unregister_resource(resource)
                continue
            if resource == "exp" and not active_hunt:
                self._unregister_resource(resource)
                continue

            interval = getattr(config, resource).interval_sec
            last_ts = self._last_capture.get(resource, 0.0)
            interval_elapsed = interval <= 0.0 or (now - last_ts) >= interval
            if resource == "exp" and last_ts <= 0.0:
                interval_elapsed = True
            if not interval_elapsed:
                continue

            roi = getattr(config, resource).roi
            payload = roi_payloads.get(resource) if isinstance(roi_payloads, dict) else None
            if isinstance(payload, dict):
                absolute_roi = resolve_roi_to_absolute(payload, window=window_geometry)
                if absolute_roi is None:
                    absolute_roi = resolve_roi_to_absolute(payload)
                if absolute_roi:
                    roi = Roi.from_dict(absolute_roi)
            if not roi.is_valid():
                if resource == "exp" and not self._exp_roi_warned:
                    self._emit_exp_log("warn", "[EXP] ROI가 설정되지 않아 감지를 건너뜁니다.")
                    self._exp_roi_warned = True
                self._last_capture[resource] = now
                self._unregister_resource(resource)
                continue
            elif resource == "exp" and self._exp_roi_warned:
                self._exp_roi_warned = False
                self._exp_last_log_signature = None

            monitor_dict = roi.to_monitor_dict()
            consumer_name = self._ensure_resource_consumer(resource, monitor_dict)
            if consumer_name is None:
                self._last_capture[resource] = now
                continue

            frame_bgr = self._manager.get_frame(consumer_name, timeout=0.5)
            if frame_bgr is None or frame_bgr.size == 0:
                if resource == "exp" and not self._exp_capture_warned:
                    self._emit_exp_log("warn", "[EXP] 캡처에 실패했습니다.")
                    self._exp_capture_warned = True
                self._last_capture[resource] = now
                continue

            bgr = frame_bgr
            if resource in {"hp", "mp"}:
                percentage = self._analyze_bar(bgr)
                if percentage is not None:
                    snapshot[resource] = {
                        "percentage": percentage,
                        "timestamp": now,
                    }
            else:  # exp
                exp_data = self._analyze_exp(bgr)
                if exp_data:
                    exp_data["timestamp"] = now
                    snapshot[resource] = exp_data
                    self._exp_capture_warned = False

            self._last_capture[resource] = now

        if snapshot:
            snapshot["timestamp"] = now
            with QMutexLocker(self._lock):
                self._latest_status.update({k: v for k, v in snapshot.items() if k in tasks})
        return snapshot

    def _ensure_resource_consumer(self, resource: str, region: Dict[str, int]) -> Optional[str]:
        if not region:
            self._unregister_resource(resource)
            return None
        name = self._resource_consumers.get(resource)
        region_norm = {
            "left": int(region.get("left", 0)),
            "top": int(region.get("top", 0)),
            "width": max(1, int(region.get("width", 0))),
            "height": max(1, int(region.get("height", 0))),
        }
        if name is None:
            name = f"{self._consumer_prefix}:{resource}"
            self._resource_consumers[resource] = name
            self._manager.register_region(name, region_norm)
        else:
            prev = self._resource_regions.get(resource)
            if prev != region_norm:
                try:
                    self._manager.update_region(name, region_norm)
                except KeyError:
                    self._manager.register_region(name, region_norm)
        self._resource_regions[resource] = region_norm
        return name

    def _unregister_resource(self, resource: str) -> None:
        name = self._resource_consumers.pop(resource, None)
        self._resource_regions.pop(resource, None)
        if name is not None:
            try:
                self._manager.unregister_region(name)
            except KeyError:
                pass

    def _unregister_all_resources(self) -> None:
        for resource in list(self._resource_consumers.keys()):
            self._unregister_resource(resource)

    def _emit_exp_log(self, level: str, message: str, *, dedupe: bool = True) -> None:
        if not message:
            return
        signature = (level, message)
        if dedupe and self._exp_last_log_signature == signature:
            return
        if dedupe:
            self._exp_last_log_signature = signature
        else:
            self._exp_last_log_signature = None
        self.exp_status_logged.emit(level, message)

    @staticmethod
    def _analyze_bar(image_bgr: np.ndarray) -> Optional[float]:
        if image_bgr is None or image_bgr.size == 0:
            return None
        height, width = image_bgr.shape[:2]
        if width <= 1:
            return None
        arr = image_bgr.astype(np.int16)
        full_mask = np.all(np.abs(arr - GRAY_FULL_COLOR) <= COLOR_TOLERANCE, axis=2)
        boundary_mask = np.zeros((height, width), dtype=bool)
        for color in GRAY_BOUNDARY_CANDIDATES:
            boundary_mask |= np.all(np.abs(arr - color) <= COLOR_TOLERANCE, axis=2)

        column_hits = boundary_mask.any(axis=0)
        first_idx: Optional[int] = None
        for idx, hit in enumerate(column_hits):
            if hit:
                first_idx = idx
                break

        if first_idx is None:
            return 100.0

        percent = max(0.0, min(100.0, (first_idx / float(width)) * 100.0))
        if full_mask.any() and percent > 99.0:
            return 100.0
        return percent

    def _analyze_exp(self, image_bgr: np.ndarray) -> Optional[Dict[str, object]]:
        if image_bgr is None or image_bgr.size == 0:
            return None

        if not PYTESSERACT_AVAILABLE:
            if not self._warned_ocr_missing:
                self._warned_ocr_missing = True
                self.ocr_unavailable.emit()
            return None

        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (0, 0), fx=1.2, fy=1.2, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        config = "--psm 7 -c tessedit_char_whitelist=0123456789.%[]"
        text = pytesseract.image_to_string(thresh, config=config)
        if not text:
            self._emit_exp_log("warn", "[EXP] OCR 결과가 비어 있습니다.")
            return None
        cleaned = text.strip().replace("\n", " ")
        amount = self._extract_exp_amount(cleaned)
        percent = self._extract_exp_percent(cleaned)
        if amount is None or percent is None:
            if cleaned and cleaned != self._exp_failure_cache:
                self._emit_exp_log("warn", f"[EXP] OCR 실패: '{cleaned}'")
                self._exp_failure_cache = cleaned
            return None
        snapshot_key = (amount, round(percent, 3))
        if self._last_exp_snapshot != snapshot_key:
            self._emit_exp_log("info", f"[EXP] OCR 성공: {amount} / {percent:.2f}%")
            self._last_exp_snapshot = snapshot_key
        self._exp_failure_cache = None
        self._last_exp_log_text = cleaned
        return {"amount": amount, "percent": percent}

    @staticmethod
    def _extract_exp_amount(text: str) -> Optional[str]:
        digits = []
        for char in text:
            if char.isdigit():
                digits.append(char)
            elif digits and char in " [":
                break
        if not digits:
            return None
        return "".join(digits)

    @staticmethod
    def _extract_exp_percent(text: str) -> Optional[float]:
        start = text.find("[")
        if start == -1:
            return None
        segment = text[start + 1 :]
        candidate = []
        for ch in segment:
            if ch.isdigit() or ch == ".":
                candidate.append(ch)
            elif candidate:
                break
        if not candidate:
            return None
        try:
            value = float("".join(candidate))
        except ValueError:
            return None
        if value < 0.0:
            return None
        return value


class StatusConfigNotifier(QObject):
    """DataManager에서 상태 모니터 구성 변경을 전달하기 위한 헬퍼."""

    status_config_changed = pyqtSignal(StatusMonitorConfig)

    def emit_config(self, config: StatusMonitorConfig) -> None:
        self.status_config_changed.emit(config)
