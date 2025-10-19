"""공통 화면 캡처 관리를 담당하는 헬퍼."""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

import mss
import numpy as np


MonitorRegion = Dict[str, int]


class _MSSBackend:
    """mss 기반 단순 캡처 백엔드."""

    def __init__(self) -> None:
        self._sct: Optional[mss.mss] = None
        self._lock = threading.Lock()

    def ensure_open(self) -> None:
        with self._lock:
            if self._sct is None:
                self._sct = mss.mss()

    def grab(self, region: MonitorRegion) -> np.ndarray:
        self.ensure_open()
        assert self._sct is not None
        shot = self._sct.grab(region)
        # BGRA → BGR. frombuffer로 불필요한 복사를 줄이고 최종적으로 copy()로 안전하게 분리.
        frame = np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return frame[:, :, :3].copy()

    def close(self) -> None:
        with self._lock:
            if self._sct is not None:
                self._sct.close()
                self._sct = None


class CaptureManager:
    """여러 소비자가 공통 프레임을 공유할 수 있도록 캡처를 통합한다."""

    _instance: Optional["CaptureManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self, *, target_fps: float = 30.0) -> None:
        self._default_target_fps = max(1.0, float(target_fps))
        self._target_fps = self._default_target_fps
        self._backend = _MSSBackend()
        self._consumers: Dict[str, Dict[str, object]] = {}
        self._consumers_lock = threading.Lock()
        self._wake_event = threading.Event()
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="CaptureManagerThread",
            daemon=True,
        )
        self._running = threading.Event()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_seq: int = 0
        self._base_region: Optional[MonitorRegion] = None

    # ------------------------------------------------------------------
    # 싱글턴 접근자
    # ------------------------------------------------------------------
    @classmethod
    def instance(cls) -> "CaptureManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = CaptureManager()
                cls._instance.start()
        return cls._instance

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        if not self._capture_thread.is_alive():
            self._capture_thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._wake_event.set()
        self._backend.close()

    # 동적으로 캡처 FPS를 조절하기 위한 간단한 API
    def set_target_fps(self, fps: Optional[float]) -> None:
        """
        캡처 루프의 목표 FPS를 설정합니다.
        - fps가 None 또는 0 이하이면 기본값으로 복원합니다.
        - 유효 범위는 [1.0, 60.0]로 클램프합니다.
        """
        new_fps: float
        if fps is None or float(fps) <= 0.0:
            new_fps = self._default_target_fps
        else:
            new_fps = max(1.0, min(60.0, float(fps)))
        # 경합 최소화를 위해 잠금 하에서 변경
        with self._consumers_lock:
            self._target_fps = new_fps
        # 즉시 반영되도록 웨이크 업
        self._wake_event.set()

    def restore_target_fps(self) -> None:
        self.set_target_fps(None)

    def get_target_fps(self) -> float:
        return float(self._target_fps)

    def register_region(self, name: str, region: MonitorRegion) -> None:
        norm_region = self._normalize_region(region)
        with self._consumers_lock:
            self._consumers[name] = {
                "region": norm_region,
                "event": threading.Event(),
                "seq": -1,
                "consumed_seq": -1,
            }
            if name.startswith("minimap:"):
                area = int(norm_region["width"]) * int(norm_region["height"])  # type: ignore[index]
                if area > 512 * 512:
                    print(
                        f"[CaptureManager] 경고: {name} 소비자가 등록한 ROI 크기 {norm_region['width']}x{norm_region['height']}가 큽니다."
                    )
            self._recompute_base_region_locked()
        self._wake_event.set()

    def update_region(self, name: str, region: MonitorRegion) -> None:
        norm_region = self._normalize_region(region)
        with self._consumers_lock:
            consumer = self._consumers.get(name)
            if consumer is None:
                raise KeyError(f"등록되지 않은 캡처 소비자: {name}")
            consumer["region"] = norm_region
            self._recompute_base_region_locked()
        self._wake_event.set()

    def unregister_region(self, name: str) -> None:
        with self._consumers_lock:
            self._consumers.pop(name, None)
            self._recompute_base_region_locked()
        self._wake_event.set()

    def get_frame(self, name: str, *, timeout: Optional[float] = None) -> Optional[np.ndarray]:
        start_ts = time.perf_counter()
        consumer: Optional[Dict[str, object]]
        while True:
            with self._consumers_lock:
                consumer = self._consumers.get(name)
                if consumer is None:
                    raise KeyError(f"등록되지 않은 캡처 소비자: {name}")
                seq = consumer.get("seq", -1)
                consumed_seq = consumer.get("consumed_seq", -1)
                event = consumer["event"]  # type: ignore[index]
            if seq != consumed_seq:
                break
            remaining: Optional[float]
            if timeout is None:
                remaining = None
            else:
                elapsed = time.perf_counter() - start_ts
                remaining = max(0.0, timeout - elapsed)
                if remaining == 0.0 and timeout is not None:
                    return None
            if not event.wait(timeout=remaining):
                return None
        event.clear()

        with self._consumers_lock:
            base_region = self._base_region
            frame = self._latest_frame
            consumer = self._consumers.get(name)
            if consumer is None:
                return None
            consumer["consumed_seq"] = consumer.get("seq", -1)

        if frame is None or base_region is None:
            return None

        region = consumer["region"]  # type: ignore[index]
        y1 = int(region["top"] - base_region["top"])
        y2 = y1 + int(region["height"])
        x1 = int(region["left"] - base_region["left"])
        x2 = x1 + int(region["width"])

        if y1 < 0 or x1 < 0:
            return None
        if y2 > frame.shape[0] or x2 > frame.shape[1]:
            return None

        return frame[y1:y2, x1:x2].copy()

    # ------------------------------------------------------------------
    # 내부 로직
    # ------------------------------------------------------------------
    def _capture_loop(self) -> None:
        capture_interval = 1.0 / self._target_fps
        while self._running.is_set():
            start = time.perf_counter()

            with self._consumers_lock:
                has_consumers = bool(self._consumers)
                base_region = self._base_region

            if not has_consumers or base_region is None:
                # 소비자가 없으면 대기.
                self._wake_event.wait(timeout=0.25)
                self._wake_event.clear()
                continue

            try:
                frame = self._backend.grab(base_region)
            except mss.exception.ScreenShotError as exc:  # type: ignore[attr-defined]
                try:
                    print(f"[CaptureManager] ScreenShotError 발생: {exc}")
                except Exception:
                    pass
                self._backend.close()
                time.sleep(0.05)
                self._wake_event.wait(timeout=0.1)
                self._wake_event.clear()
                continue

            with self._consumers_lock:
                self._latest_frame = frame
                self._latest_seq += 1
                seq = self._latest_seq
                for consumer in self._consumers.values():
                    consumer["seq"] = seq
                    consumer["event"].set()  # type: ignore[index]

            elapsed = time.perf_counter() - start
            sleep_time = capture_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _recompute_base_region_locked(self) -> None:
        if not self._consumers:
            self._base_region = None
            return
        lefts = []
        tops = []
        rights = []
        bottoms = []
        for consumer in self._consumers.values():
            region = consumer["region"]  # type: ignore[index]
            lefts.append(int(region["left"]))
            tops.append(int(region["top"]))
            rights.append(int(region["left"]) + int(region["width"]))
            bottoms.append(int(region["top"]) + int(region["height"]))
        base_left = min(lefts)
        base_top = min(tops)
        base_right = max(rights)
        base_bottom = max(bottoms)
        self._base_region = {
            "left": base_left,
            "top": base_top,
            "width": max(1, base_right - base_left),
            "height": max(1, base_bottom - base_top),
        }

    @staticmethod
    def _normalize_region(region: MonitorRegion) -> MonitorRegion:
        left = int(region.get("left", 0))
        top = int(region.get("top", 0))
        width = max(1, int(region.get("width", 0)))
        height = max(1, int(region.get("height", 0)))
        return {"left": left, "top": top, "width": width, "height": height}


def get_capture_manager() -> CaptureManager:
    return CaptureManager.instance()
