"""다중 기능 모니터링 전용 경량 대시보드.

맵 탭/학습 탭에서 사용 중인 핵심 로직을 재활용하여
 - 다른 유저 감지
 - 채팅창 색상 감지
 - 경험치 측정(파들 OCR 기반)
기능을 하나의 창에서 제공한다.

주요 특징
 - 창 위치 저장/불러오기(학습 탭의 앵커 시스템 재사용)
 - Mapleland 창 상대 좌표 기반 ROI 관리
 - 톱레벨 고정(항상 위)
 - 설정 자동 저장/복원
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import cv2
import mss
import numpy as np

from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QRect, Qt, QThread, QTimer, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QCloseEvent, QPixmap, QPainter, QPen, QColor, QImage, QFont, QFontDatabase, QFontInfo
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)


# ---------------------------------------------------------------------------
# src/ 경로를 sys.path에 추가하여 기존 모듈을 그대로 재사용한다.
# ---------------------------------------------------------------------------

CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from detection_runtime import ScreenSnipper  # type: ignore[import-not-found]  # noqa: E402
from map import (  # type: ignore[import-not-found]  # noqa: E402
    OTHER_PLAYER_ICON_LOWER1,
    OTHER_PLAYER_ICON_LOWER2,
    OTHER_PLAYER_ICON_UPPER1,
    OTHER_PLAYER_ICON_UPPER2,
    PLAYER_ICON_STD_HEIGHT,
    PLAYER_ICON_STD_WIDTH,
    WORKSPACE_ROOT,
)
from window_anchors import (  # type: ignore[import-not-found]  # noqa: E402
    get_anchor,
    get_maple_window_geometry,
    is_maple_window_foreground,
    last_used_anchor_name,
    list_saved_anchors,
    make_relative_roi,
    restore_maple_window,
    resolve_roi_to_absolute,
    save_window_anchor,
    set_last_used_anchor,
)
from status_monitor import StatusMonitorThread  # type: ignore[import-not-found]  # noqa: E402

try:
    from Learning import (  # type: ignore[import-not-found]  # noqa: E402
        StatusRecognitionPreviewDialog,
        WindowAnchorLoadDialog,
        WindowAnchorSaveDialog,
    )
except Exception:  # pragma: no cover - 학습 탭이 없을 때 대비
    WindowAnchorLoadDialog = None  # type: ignore[assignment]
    WindowAnchorSaveDialog = None  # type: ignore[assignment]
    StatusRecognitionPreviewDialog = None  # type: ignore[assignment]

try:  # pytesseract가 설치되지 않은 환경 대비
    import pytesseract  # type: ignore

    PYTESSERACT_AVAILABLE = True
except Exception:  # pragma: no cover - 선택적 의존성
    pytesseract = None  # type: ignore
    PYTESSERACT_AVAILABLE = False


CONFIG_PATH = Path(WORKSPACE_ROOT) / "config"
CONFIG_PATH.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_PATH / "monitor_dashboard.json"

SOUNDS_DIR = Path(WORKSPACE_ROOT) / "sounds"
DEFAULT_WHISPER_COLOR = "00F100"
DEFAULT_FRIEND_COLOR = "FFA500"
CHAT_INTERVAL_MIN = 0.1
CHAT_INTERVAL_MAX = 10.0
CHAT_COLOR_DELTA_H = 5
CHAT_COLOR_DELTA_S = 30
CHAT_COLOR_DELTA_V = 30
CHAT_MIN_PIXEL_RATIO = 0.002  # 최소 면적 비율(0.2%)
CHAT_MIN_PIXEL_COUNT = 12     # 매우 작은 ROI 대비 절댓값 하한
EXP_LEVEL_UP_DROP_THRESHOLD = 35.0
EXP_LEVEL_UP_POST_PERCENT = 30.0
EXP_REGRESSION_MIN_SAMPLES = 3
EXP_REGRESSION_WINDOW_SEC = 600  # 최근 10분만 사용
EXP_REGRESSION_HALF_LIFE_SEC = 360  # 회귀 가중 반감기 6분
EXP_EWMA_1MIN_WINDOW_SEC = 60  # 최근 60초 구간
EXP_EWMA_1MIN_HALF_LIFE_SEC = 30  # 1분 예상용 EWMA 반감기
EXP_IDLE_WINDOW_SEC = 20
EXP_IDLE_MIN_PERCENT = 0.1

_ACTIVE_QT_SOUND_PLAYERS: list = []


# ---------------------------------------------------------------------------
# 유효성 헬퍼
# ---------------------------------------------------------------------------


def clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def normalize_hex_color(text: str) -> str:
    value = (text or "").strip().lstrip("#")
    if not value:
        return ""
    return value.upper()[:6]

def normalize_hex_color_list(text: str, *, default: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return default
    parts = [p.strip() for p in raw.replace("#", "").split(",") if p.strip()]
    codes: List[str] = []
    for p in parts:
        code = p.upper()[:6]
        if len(code) == 6 and all(ch in "0123456789ABCDEF" for ch in code):
            if code not in codes:
                codes.append(code)
    if not codes:
        return default
    return ",".join(codes)


def _format_duration_hms(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def resolve_sound_path(name: str) -> Optional[str]:
    if not name:
        return None

    direct_candidate = Path(name)
    if direct_candidate.exists():
        try:
            return str(direct_candidate.resolve())
        except Exception:
            return str(direct_candidate)

    candidates: list[Path] = []
    try:
        workspace_root_path = Path(WORKSPACE_ROOT)
        candidates.append(workspace_root_path / "sounds" / name)
    except Exception:
        pass

    raw_workspace = str(WORKSPACE_ROOT)
    if ":" in raw_workspace:
        drive, remainder = raw_workspace.split(":", 1)
        remainder = remainder.replace("\\", "/").lstrip("/\\")
        wsl_base = Path("/mnt") / drive.lower()
        if remainder:
            wsl_base = wsl_base / Path(remainder)
        candidates.append(wsl_base / "sounds" / name)

    candidates.append(Path.cwd() / "workspace" / "sounds" / name)

    fallback: Optional[str] = None
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if fallback is None:
            fallback = str(resolved)
        if resolved.exists():
            return str(resolved)
    return fallback


def play_sound_async(name: str, *, volume: float = 0.4) -> None:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer  # 지연 import
    from PyQt6.QtCore import QUrl

    sound_path = resolve_sound_path(name)
    if not sound_path:
        QApplication.beep()
        return

    def _play_qt_sound() -> bool:
        try:
            player = QMediaPlayer()
            audio_output = QAudioOutput(player)
            audio_output.setVolume(max(0.0, min(volume, 1.0)))
            player.setAudioOutput(audio_output)
            player.setSource(QUrl.fromLocalFile(sound_path))

            def _cleanup():
                try:
                    player.stop()
                except Exception:
                    pass
                try:
                    _ACTIVE_QT_SOUND_PLAYERS.remove(player)
                except ValueError:
                    pass
                except Exception:
                    pass
                try:
                    player.deleteLater()
                except Exception:
                    pass

            def _handle_status(status) -> None:
                if status == QMediaPlayer.MediaStatus.EndOfMedia:
                    _cleanup()

            def _handle_error(*_: object) -> None:
                _cleanup()

            try:
                player.mediaStatusChanged.connect(_handle_status)
            except Exception:
                pass
            try:
                player.errorOccurred.connect(_handle_error)
            except Exception:
                pass
            try:
                QTimer.singleShot(20000, _cleanup)
            except Exception:
                pass

            player.play()
            _ACTIVE_QT_SOUND_PLAYERS.append(player)
        except Exception:
            return False
        return True

    if _play_qt_sound():
        return

    def _fallback() -> None:
        try:
            import playsound  # type: ignore

            playsound.playsound(sound_path, block=False)
            return
        except Exception:
            try:
                import winsound  # type: ignore

                winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception:
                pass
        QApplication.beep()

    threading.Thread(target=_fallback, daemon=True).start()


# ---------------------------------------------------------------------------
# 기본 다른 유저 색상 계산
# ---------------------------------------------------------------------------


def _midpoint_hsv_to_hex(lower: np.ndarray, upper: np.ndarray) -> str:
    try:
        h = int(round((float(lower[0]) + float(upper[0])) / 2))
        s = int(round((float(lower[1]) + float(upper[1])) / 2))
        v = int(round((float(lower[2]) + float(upper[2])) / 2))
        hsv = np.uint8([[[h, s, v]]])
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0][0]
        return f"{int(bgr[2]):02X}{int(bgr[1]):02X}{int(bgr[0]):02X}"
    except Exception:
        return "FF3FD7"


def _default_other_player_colors() -> list[str]:
    try:
        colors = [
            _midpoint_hsv_to_hex(OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1),
            _midpoint_hsv_to_hex(OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2),
        ]
    except Exception:
        colors = ["FF3FD7", "FFA040"]
    return [normalize_hex_color(code) for code in colors if len(normalize_hex_color(code)) == 6]


DEFAULT_OTHER_PLAYER_COLORS = _default_other_player_colors()


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------


@dataclass
class OtherPlayerSettings:
    enabled: bool = False
    interval_sec: float = 0.5
    min_count: int = 1
    roi: Optional[Dict[str, object]] = None
    color_codes: list[str] = field(default_factory=lambda: list(DEFAULT_OTHER_PLAYER_COLORS))


@dataclass
class ChatChannelSetting:
    enabled: bool = False
    hex_color: str = ""


@dataclass
class ChatDetectionSettings:
    interval_sec: float = 5.0
    roi: Optional[Dict[str, object]] = None
    whisper: ChatChannelSetting = field(default_factory=lambda: ChatChannelSetting(enabled=True, hex_color=DEFAULT_WHISPER_COLOR))
    friend: ChatChannelSetting = field(default_factory=lambda: ChatChannelSetting(enabled=False, hex_color=DEFAULT_FRIEND_COLOR))


@dataclass
class ExpMeasurementSettings:
    roi: Optional[Dict[str, object]] = None
    update_interval_sec: float = 10.0
    last_minutes_limit: Optional[int] = None


@dataclass
class MonitorConfig:
    other_players: OtherPlayerSettings = field(default_factory=OtherPlayerSettings)
    chat: ChatDetectionSettings = field(default_factory=ChatDetectionSettings)
    exp: ExpMeasurementSettings = field(default_factory=ExpMeasurementSettings)
    window_pos: Optional[Tuple[int, int]] = None
    anchor_name: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "other_players": {
                "enabled": self.other_players.enabled,
                "interval_sec": float(self.other_players.interval_sec),
                "min_count": int(self.other_players.min_count),
                "roi": self.other_players.roi or {},
                "colors": list(self.other_players.color_codes),
            },
            "chat": {
                "interval_sec": float(self.chat.interval_sec),
                "roi": self.chat.roi or {},
                "whisper": {
                    "enabled": self.chat.whisper.enabled,
                    "hex_color": self.chat.whisper.hex_color,
                },
                "friend": {
                    "enabled": self.chat.friend.enabled,
                    "hex_color": self.chat.friend.hex_color,
                },
            },
            "exp": {
                "roi": self.exp.roi or {},
                "update_interval_sec": float(self.exp.update_interval_sec),
                "last_minutes_limit": self.exp.last_minutes_limit,
            },
            "window_pos": list(self.window_pos) if self.window_pos else None,
            "anchor_name": self.anchor_name,
        }

    @staticmethod
    def from_dict(data: Optional[Dict[str, object]]) -> "MonitorConfig":
        cfg = MonitorConfig()
        if not isinstance(data, dict):
            return cfg

        other_src = data.get("other_players")
        if isinstance(other_src, dict):
            cfg.other_players.enabled = bool(other_src.get("enabled", False))
            cfg.other_players.interval_sec = clamp_float(float(other_src.get("interval_sec", 0.5)), 0.01, 10.0)
            cfg.other_players.min_count = clamp_int(int(other_src.get("min_count", 1)), 1, 50)
            roi = other_src.get("roi")
            cfg.other_players.roi = roi if isinstance(roi, dict) and roi else None
            raw_colors = other_src.get("colors")
            colors: list[str] = []
            if isinstance(raw_colors, str):
                raw_colors = [raw_colors]
            if isinstance(raw_colors, (list, tuple)):
                for item in raw_colors:
                    code = normalize_hex_color(str(item))
                    if len(code) == 6:
                        colors.append(code)
            if not colors:
                colors = list(DEFAULT_OTHER_PLAYER_COLORS)
            cfg.other_players.color_codes = colors

        chat_src = data.get("chat")
        if isinstance(chat_src, dict):
            cfg.chat.interval_sec = clamp_float(
                float(chat_src.get("interval_sec", 5.0)), CHAT_INTERVAL_MIN, CHAT_INTERVAL_MAX
            )
            roi = chat_src.get("roi")
            cfg.chat.roi = roi if isinstance(roi, dict) and roi else None
            whisper = chat_src.get("whisper")
            if isinstance(whisper, dict):
                cfg.chat.whisper.enabled = bool(whisper.get("enabled", True))
                cfg.chat.whisper.hex_color = normalize_hex_color_list(
                    str(whisper.get("hex_color", DEFAULT_WHISPER_COLOR) or DEFAULT_WHISPER_COLOR),
                    default=DEFAULT_WHISPER_COLOR,
                )
            else:
                cfg.chat.whisper.hex_color = DEFAULT_WHISPER_COLOR
            friend = chat_src.get("friend")
            if isinstance(friend, dict):
                cfg.chat.friend.enabled = bool(friend.get("enabled", False))
                cfg.chat.friend.hex_color = normalize_hex_color_list(
                    str(friend.get("hex_color", DEFAULT_FRIEND_COLOR) or DEFAULT_FRIEND_COLOR),
                    default=DEFAULT_FRIEND_COLOR,
                )
            else:
                cfg.chat.friend.hex_color = DEFAULT_FRIEND_COLOR

        exp_src = data.get("exp")
        if isinstance(exp_src, dict):
            roi = exp_src.get("roi")
            cfg.exp.roi = roi if isinstance(roi, dict) and roi else None
            cfg.exp.update_interval_sec = clamp_float(float(exp_src.get("update_interval_sec", 10.0)), 5.0, 30.0)
            minutes = exp_src.get("last_minutes_limit")
            cfg.exp.last_minutes_limit = int(minutes) if isinstance(minutes, int) else None

        window_pos = data.get("window_pos")
        if isinstance(window_pos, (list, tuple)) and len(window_pos) == 2:
            cfg.window_pos = (int(window_pos[0]), int(window_pos[1]))

        anchor_name = data.get("anchor_name")
        if isinstance(anchor_name, str) and anchor_name.strip():
            cfg.anchor_name = anchor_name.strip()

        return cfg


# ---------------------------------------------------------------------------
# 캡처/탐지 워커
# ---------------------------------------------------------------------------


def _extract_other_player_rects(frame_bgr: np.ndarray, thresholds: list[tuple[np.ndarray, np.ndarray]]) -> list[QRect]:
    if frame_bgr is None or frame_bgr.size == 0 or not thresholds:
        return []
    frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

    mask = np.zeros(frame_hsv.shape[:2], dtype=np.uint8)
    for lower, upper in thresholds:
        try:
            mask = cv2.bitwise_or(mask, cv2.inRange(frame_hsv, lower, upper))
        except Exception:
            continue

    output = cv2.connectedComponentsWithStats(mask, 8, cv2.CV_32S)
    num_labels, stats = output[0], output[2]
    rects: list[QRect] = []
    for i in range(1, num_labels):
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if w <= 0 or h <= 0:
            continue
        center_x = x + w / 2
        center_y = y + h / 2
        rects.append(QRect(int(center_x - PLAYER_ICON_STD_WIDTH / 2), int(center_y - PLAYER_ICON_STD_HEIGHT / 2), PLAYER_ICON_STD_WIDTH, PLAYER_ICON_STD_HEIGHT))
    return rects


class OtherPlayerWatcher(QThread):
    detected = pyqtSignal(int)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._enabled = False
        self._interval = 0.5
        self._min_count = 1
        self._roi_payload: Optional[Dict[str, object]] = None
        self._thresholds: list[tuple[np.ndarray, np.ndarray]] = []
        self._running = True

    def update_settings(
        self,
        *,
        enabled: bool,
        interval: float,
        min_count: int,
        roi: Optional[Dict[str, object]],
        thresholds: Optional[list[tuple[np.ndarray, np.ndarray]]],
    ) -> None:
        with QMutexLocker(self._mutex):
            self._enabled = bool(enabled)
            self._interval = clamp_float(interval, 0.01, 10.0)
            self._min_count = clamp_int(min_count, 1, 50)
            self._roi_payload = roi if isinstance(roi, dict) else None
            self._thresholds = list(thresholds or [])

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:  # noqa: D401
        with mss.mss() as sct:
            last_count = 0
            while self._running:
                with QMutexLocker(self._mutex):
                    enabled = self._enabled
                    interval = self._interval
                    min_count = self._min_count
                    roi_payload = self._roi_payload
                    thresholds = list(self._thresholds)

                if not enabled or roi_payload is None or not thresholds:
                    last_count = 0
                    time.sleep(0.3)
                    continue

                if not is_maple_window_foreground():
                    last_count = 0
                    time.sleep(interval)
                    continue

                window_geometry = get_maple_window_geometry()
                region = resolve_roi_to_absolute(roi_payload, window=window_geometry)
                if not region:
                    time.sleep(interval)
                    continue

                try:
                    frame = sct.grab(region)
                except Exception:
                    time.sleep(interval)
                    continue

                frame_bgr = np.array(frame)[:, :, :3]
                rects = _extract_other_player_rects(frame_bgr, thresholds)
                count = len(rects)

                if count >= min_count:
                    self.detected.emit(count)
                    last_count = count
                else:
                    if last_count != 0:
                        self.detected.emit(0)
                    last_count = 0

                time.sleep(interval)


class ChatWatcher(QThread):
    detected = pyqtSignal(str, bool)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._interval = 5.0
        self._roi_payload: Optional[Dict[str, object]] = None
        self._active_colors: Dict[str, List[Tuple[np.ndarray, np.ndarray]]] = {}
        self._last_states: Dict[str, bool] = {}
        self._running = True

    def update_settings(
        self,
        *,
        interval: float,
        roi: Optional[Dict[str, object]],
        color_map: Dict[str, Tuple[str, bool]],
    ) -> None:
        with QMutexLocker(self._mutex):
            self._interval = clamp_float(interval, CHAT_INTERVAL_MIN, CHAT_INTERVAL_MAX)
            self._roi_payload = roi if isinstance(roi, dict) else None
            self._active_colors = {}
            for key, (hex_color, enabled) in color_map.items():
                if not enabled:
                    continue
                thresholds: List[Tuple[np.ndarray, np.ndarray]] = []
                for code in (hex_color or "").split(","):
                    code = normalize_hex_color(code)
                    if len(code) != 6:
                        continue
                    rgb = _hex_to_bgr(code)
                    if rgb is None:
                        continue
                    lower, upper = _build_color_threshold(
                        rgb,
                        delta_h=CHAT_COLOR_DELTA_H,
                        delta_s=CHAT_COLOR_DELTA_S,
                        delta_v=CHAT_COLOR_DELTA_V,
                    )
                    thresholds.append((lower, upper))
                if thresholds:
                    self._active_colors[key] = thresholds
            for key in list(self._last_states.keys()):
                if key not in self._active_colors:
                    if self._last_states[key]:
                        self.detected.emit(key, False)
                    self._last_states.pop(key, None)

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:  # noqa: D401
        with mss.mss() as sct:
            while self._running:
                with QMutexLocker(self._mutex):
                    interval = self._interval
                    roi_payload = self._roi_payload
                    active_colors = dict(self._active_colors)

                if not roi_payload or not active_colors:
                    if self._last_states:
                        for key, state in list(self._last_states.items()):
                            if state:
                                self.detected.emit(key, False)
                            self._last_states[key] = False
                    time.sleep(0.5)
                    continue

                # 채팅 감지는 Mapleland 포그라운드 여부와 무관하게 동작

                window_geometry = get_maple_window_geometry()
                region = resolve_roi_to_absolute(roi_payload, window=window_geometry)
                if not region:
                    time.sleep(interval)
                    continue

                try:
                    frame = sct.grab(region)
                except Exception:
                    time.sleep(interval)
                    continue

                frame_bgr = np.array(frame)[:, :, :3]
                frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
                frame_height, frame_width = frame_hsv.shape[:2]
                min_pixels = max(
                    CHAT_MIN_PIXEL_COUNT,
                    int(frame_height * frame_width * CHAT_MIN_PIXEL_RATIO),
                )

                current_states: Dict[str, bool] = {}
                for key, th_list in active_colors.items():
                    detected = False
                    for (lower, upper) in th_list:
                        mask = cv2.inRange(frame_hsv, lower, upper)
                        pixel_count = int(cv2.countNonZero(mask))
                        if pixel_count >= min_pixels:
                            detected = True
                            break
                    current_states[key] = detected
                    if self._last_states.get(key) != detected:
                        self.detected.emit(key, detected)
                self._last_states = current_states
                time.sleep(interval)


def _hex_to_bgr(hex_color: str) -> Optional[Tuple[int, int, int]]:
    value = normalize_hex_color(hex_color)
    if len(value) != 6:
        return None
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError:
        return None
    return b, g, r


def _build_color_threshold(
    bgr: Tuple[int, int, int],
    *,
    delta_h: int = 8,
    delta_s: int = 60,
    delta_v: int = 60,
) -> Tuple[np.ndarray, np.ndarray]:
    b, g, r = bgr
    hsv = cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0][0]
    h, s, v = hsv
    lower = np.array([max(0, h - delta_h), max(0, s - delta_s), max(0, v - delta_v)])
    upper = np.array([min(179, h + delta_h), min(255, s + delta_s), min(255, v + delta_v)])
    return lower, upper


# ---------------------------------------------------------------------------
# 경험치 측정 헬퍼
# ---------------------------------------------------------------------------


class ExpSnapshot:
    def __init__(
        self,
        *,
        amount: int,
        percent: float,
        timestamp: float,
        total_amount: float = 0.0,
        total_percent: float = 0.0,
        level_ups: int = 0,
    ):
        self.amount = amount
        self.percent = percent
        self.timestamp = timestamp
        self.total_amount = total_amount
        self.total_percent = total_percent
        self.level_ups = level_ups


class ExpPredictionRecord:
    def __init__(
        self,
        *,
        minutes: int,
        predicted_percent: float,
        target_ts: float,
        snapshot_ts: float,
    ):
        self.minutes = minutes
        self.predicted_percent = predicted_percent
        self.target_ts = target_ts
        self.snapshot_ts = snapshot_ts
        self.evaluated = False


# ---------------------------------------------------------------------------
# 메인 위젯
# ---------------------------------------------------------------------------


class MonitorDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Maple - 모니터 대시보드")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setObjectName("monitorDashboard")

        self.config = MonitorConfig.from_dict(self._load_config())
        if not self.config.anchor_name:
            self.config.anchor_name = last_used_anchor_name()
        self.config.other_players.enabled = False
        self.config.chat.whisper.enabled = False
        self.config.chat.friend.enabled = False

        self.other_watcher = OtherPlayerWatcher(self)
        self.other_watcher.detected.connect(self._handle_other_player_signal)
        self.other_watcher.start()

        self.chat_watcher = ChatWatcher(self)
        self.chat_watcher.detected.connect(self._handle_chat_signal)
        self.chat_watcher.start()

        self.exp_timer = QTimer(self)
        self.exp_timer.timeout.connect(self._handle_exp_tick)
        self.exp_elapsed_timer = QTimer(self)
        self.exp_elapsed_timer.setInterval(1000)
        self.exp_elapsed_timer.timeout.connect(self._handle_exp_elapsed_tick)

        self.exp_history: list[ExpSnapshot] = []
        self.exp_minutes_limit: Optional[int] = None
        self.exp_start_ts: Optional[float] = None
        self.exp_active = False
        self.exp_prediction_records: list[ExpPredictionRecord] = []
        self.exp_prediction_accuracy: dict[int, float] = {}
        self._last_prediction_snapshot_ts = 0.0

        self._chat_detection_states: Dict[str, bool] = {"whisper": False, "friend": False}

        self._build_ui()
        self._apply_modern_style()
        self._apply_config_to_ui()
        self._apply_config_to_workers()
        self._connect_signals()

        if self.config.window_pos:
            self.move(*self.config.window_pos)
        else:
            self.move(80, 20)

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------
    def _apply_modern_style(self) -> None:
        target_font_name = "NanumGothic"
        font_size = 10
        base_font = QFont(target_font_name, font_size)
        if QFontInfo(base_font).family().lower() != target_font_name.lower():
            font_candidates = [
                "C:/Windows/Fonts/NanumGothic.ttf",
                "C:/Windows/Fonts/NanumGothic-Regular.ttf",
            ]
            for font_path in font_candidates:
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        base_font = QFont(families[0], font_size)
                        break
        self.setFont(base_font)

        glass_stylesheet = """
            QWidget#monitorDashboard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f9fbff, stop:1 #e9f0ff);
            }
            QGroupBox {
                font-weight: 600;
                color: #2a3550;
                border: 1px solid rgba(80, 120, 200, 0.25);
                border-radius: 14px;
                margin-top: 26px;
                padding: 5px;
                background-color: rgba(255, 255, 255, 0.82);
            }
            QGroupBox::title {
                top: 0px;
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 5px;
                background-color: rgba(249, 251, 255, 0.96);
                border-radius: 8px;
                color: #1f2b44;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel {
                color: #1f2b44;
            }
            QPushButton {
                background-color: #4a8df5;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #6aa4ff;
            }
            QPushButton:pressed {
                background-color: #2b6fd4;
            }
            QPushButton:disabled {
                background-color: #c5d4f0;
                color: #f4f6fb;
            }
            QToolButton {
                background-color: rgba(74, 141, 245, 0.15);
                border: 1px solid rgba(74, 141, 245, 0.4);
                border-radius: 10px;
                padding: 2px;
            }
            QToolButton:hover {
                background-color: rgba(74, 141, 245, 0.3);
            }
            QToolButton:pressed {
                background-color: rgba(43, 111, 212, 0.45);
            }
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.9);
                border: 1px solid rgba(70, 100, 160, 0.35);
                border-radius: 8px;
                padding: 4px 6px;
                color: #1f2b44;
                selection-background-color: #4a8df5;
                selection-color: white;
            }
            QLineEdit:focus {
                border: 1px solid #4a8df5;
                box-shadow: 0 0 8px rgba(74, 141, 245, 0.35);
            }
            QLabel#statusLabel {
                font-weight: 600;
            }
            QToolButton#chatTestButton {
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                padding: 0;
                border-radius: 11px;
                background-color: transparent;
                border: none;
            }
        """
        self.setStyleSheet(glass_stylesheet)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 14, 10, 10)
        root_layout.setSpacing(12)

        self.anchor_summary_label = QLabel()
        self.anchor_save_btn = QPushButton("저장")
        self.anchor_load_btn = QPushButton("불러오기")
        self.anchor_save_btn.clicked.connect(self._handle_anchor_save)
        self.anchor_load_btn.clicked.connect(self._handle_anchor_load)

        anchor_box = QGroupBox("창 위치 관리")
        anchor_layout = QHBoxLayout()
        anchor_layout.setContentsMargins(2, 2, 2, 2)
        anchor_layout.setSpacing(6)
        anchor_layout.addWidget(self.anchor_summary_label, 1)
        anchor_layout.addWidget(self.anchor_save_btn)
        anchor_layout.addWidget(self.anchor_load_btn)
        anchor_box.setLayout(anchor_layout)
        root_layout.addWidget(anchor_box)

        # 다른 유저 감지
        other_group = QGroupBox("다른 유저 감지")
        other_layout = QGridLayout()
        other_layout.setContentsMargins(2, 2, 2, 2)
        other_layout.setHorizontalSpacing(8)
        other_layout.setVerticalSpacing(6)

        self.other_toggle_button = QPushButton("시작")
        self.other_toggle_button.clicked.connect(self._handle_other_toggle)

        other_top_row = QHBoxLayout()
        other_top_row.setContentsMargins(0, 0, 0, 0)
        other_top_row.setSpacing(6)
        other_top_row.addWidget(self.other_toggle_button)

        self.other_roi_button = QPushButton("범위설정")
        self.other_roi_button.clicked.connect(self._handle_other_roi_select)
        other_top_row.addWidget(self.other_roi_button)

        self.other_color_edit = QLineEdit()
        self.other_color_edit.setPlaceholderText("HEX 코드(,로 구분)")
        self.other_color_edit.setMaxLength(120)
        self.other_color_edit.setFixedWidth(70)
        self.other_color_edit.setToolTip("다른 유저 아이콘 HEX 색상 (예: FF3FD7,FFA040)")
        other_top_row.addWidget(self.other_color_edit)
        other_top_row.addStretch(1)
        other_top_container = QWidget()
        other_top_container.setLayout(other_top_row)
        other_layout.addWidget(other_top_container, 0, 0, 1, 3)

        count_interval_row = QHBoxLayout()
        count_interval_row.setContentsMargins(0, 0, 0, 0)
        count_interval_row.setSpacing(6)

        self.other_min_count_spin = QSpinBox()
        self.other_min_count_spin.setRange(1, 50)
        self.other_min_count_spin.setFixedWidth(40)
        count_interval_row.addWidget(QLabel("최소 인원"))
        count_interval_row.addWidget(self.other_min_count_spin)

        self.other_interval_spin = QDoubleSpinBox()
        self.other_interval_spin.setRange(0.01, 10.0)
        self.other_interval_spin.setSingleStep(0.01)
        self.other_interval_spin.setDecimals(2)
        self.other_interval_spin.setFixedWidth(55)
        count_interval_row.addSpacing(12)
        count_interval_row.addWidget(QLabel("탐지 주기"))
        count_interval_row.addWidget(self.other_interval_spin)

        count_interval_row.addStretch(1)
        count_interval_container = QWidget()
        count_interval_container.setLayout(count_interval_row)
        other_layout.addWidget(count_interval_container, 1, 0, 1, 3)

        self.other_status_label = QLabel("감지 대기 중")
        self.other_status_label.setObjectName("statusLabel")
        other_layout.addWidget(self.other_status_label, 3, 0, 1, 3)

        other_group.setLayout(other_layout)
        root_layout.addWidget(other_group)

        # 채팅 감지
        chat_group = QGroupBox("채팅창 감지")
        chat_layout = QGridLayout()
        chat_layout.setContentsMargins(2, 2, 2, 2)
        chat_layout.setHorizontalSpacing(8)
        chat_layout.setVerticalSpacing(6)

        self.chat_roi_button = QPushButton("범위설정")
        self.chat_roi_button.clicked.connect(self._handle_chat_roi_select)
        chat_interval_label = QLabel("탐지 주기")
        chat_interval_label.setFixedWidth(80)
        self.chat_interval_spin = QDoubleSpinBox()
        self.chat_interval_spin.setRange(CHAT_INTERVAL_MIN, CHAT_INTERVAL_MAX)
        self.chat_interval_spin.setSingleStep(0.1)
        self.chat_interval_spin.setDecimals(1)
        self.chat_interval_spin.setFixedWidth(60)
        self.chat_test_button = QToolButton()
        self.chat_test_button.setObjectName("chatTestButton")
        self.chat_test_button.setAutoRaise(True)
        self.chat_test_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.chat_test_button.setToolTip("채팅 감지 테스트")
        self.chat_test_button.setIconSize(QSize(14, 14))
        self.chat_test_button.setFixedSize(20, 20)
        self.chat_test_button.clicked.connect(self._handle_chat_test)
        chat_layout.addWidget(self.chat_roi_button, 0, 0)
        chat_layout.addWidget(chat_interval_label, 0, 1)
        chat_layout.addWidget(self.chat_interval_spin, 0, 2)
        chat_layout.addWidget(self.chat_test_button, 0, 3)

        self.whisper_toggle_button = QPushButton("시작")
        self.whisper_toggle_button.clicked.connect(self._handle_whisper_toggle)
        self.whisper_color_edit = QLineEdit()
        self.whisper_color_edit.setMaxLength(64)
        self.whisper_color_edit.setFixedWidth(80)
        self.whisper_pick_button = QToolButton()
        self.whisper_pick_button.setAutoRaise(True)
        self.whisper_pick_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.whisper_pick_button.setToolTip("화면에서 색상 픽셀 선택")
        self.whisper_pick_button.setIconSize(QSize(14, 14))
        self.whisper_pick_button.setFixedSize(20, 20)
        self.whisper_pick_button.clicked.connect(self._handle_whisper_pick)
        self.whisper_status_label = QLabel("미감지")
        self.whisper_status_label.setObjectName("statusLabel")
        whisper_label = QLabel("귓속말 감지")
        whisper_label.setFixedWidth(80)
        chat_layout.addWidget(self.whisper_toggle_button, 1, 0)
        chat_layout.addWidget(whisper_label, 1, 1)
        chat_layout.addWidget(self.whisper_color_edit, 1, 2)
        chat_layout.addWidget(self.whisper_pick_button, 1, 3)
        chat_layout.addWidget(self.whisper_status_label, 1, 4)

        self.friend_toggle_button = QPushButton("시작")
        self.friend_toggle_button.clicked.connect(self._handle_friend_toggle)
        self.friend_color_edit = QLineEdit()
        self.friend_color_edit.setMaxLength(64)
        self.friend_color_edit.setFixedWidth(80)
        self.friend_pick_button = QToolButton()
        self.friend_pick_button.setAutoRaise(True)
        self.friend_pick_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.friend_pick_button.setToolTip("화면에서 색상 픽셀 선택")
        self.friend_pick_button.setIconSize(QSize(14, 14))
        self.friend_pick_button.setFixedSize(20, 20)
        self.friend_pick_button.clicked.connect(self._handle_friend_pick)
        self.friend_status_label = QLabel("미감지")
        self.friend_status_label.setObjectName("statusLabel")
        friend_label = QLabel("친구채팅 감지")
        friend_label.setFixedWidth(80)
        chat_layout.addWidget(self.friend_toggle_button, 2, 0)
        chat_layout.addWidget(friend_label, 2, 1)
        chat_layout.addWidget(self.friend_color_edit, 2, 2)
        chat_layout.addWidget(self.friend_pick_button, 2, 3)
        chat_layout.addWidget(self.friend_status_label, 2, 4)

        chat_layout.setColumnStretch(4, 1)

        chat_group.setLayout(chat_layout)
        root_layout.addWidget(chat_group)

        # 경험치 측정
        exp_group = QGroupBox("경험치 측정")
        exp_layout = QGridLayout()
        exp_layout.setContentsMargins(2, 2, 2, 2)

        self.exp_start_button = QPushButton("시작")
        self.exp_start_button.clicked.connect(self._handle_exp_toggle)
        exp_layout.addWidget(self.exp_start_button, 0, 0)

        self.exp_reset_button = QPushButton("초기화")
        self.exp_reset_button.clicked.connect(self._handle_exp_reset)
        exp_layout.addWidget(self.exp_reset_button, 0, 1)

        self.exp_minutes_edit = QLineEdit()
        self.exp_minutes_edit.setPlaceholderText("1~120 분")
        self.exp_minutes_edit.setMaxLength(3)
        self.exp_minutes_edit.setFixedWidth(70)
        exp_layout.addWidget(self.exp_minutes_edit, 0, 2)

        self.exp_roi_button = QPushButton("범위설정")
        self.exp_roi_button.clicked.connect(self._handle_exp_roi_select)
        exp_layout.addWidget(self.exp_roi_button, 1, 0)

        self.exp_test_button = QPushButton("테스트")
        self.exp_test_button.clicked.connect(self._handle_exp_test)
        exp_layout.addWidget(self.exp_test_button, 1, 1)

        self.exp_roi_label = QLabel("범위가 지정되지 않았습니다.")
        exp_layout.addWidget(self.exp_roi_label, 2, 0, 1, 4)

        self.exp_card = QFrame()
        self.exp_card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(self.exp_card)
        self.exp_summary_label = QLabel("측정을 시작하세요.")
        self.exp_gain_label = QLabel("분당 데이터 없음")
        prediction_container = QWidget()
        prediction_layout = QVBoxLayout(prediction_container)
        prediction_layout.setContentsMargins(0, 0, 0, 0)
        prediction_layout.setSpacing(4)

        self.exp_prediction_title = QLabel("예측")
        self.exp_prediction_label = QLabel("예측 데이터 없음")
        self.exp_prediction_label.setWordWrap(True)
        self.exp_accuracy_label = QLabel("정확도 데이터 없음")
        self.exp_accuracy_label.setWordWrap(True)

        prediction_layout.addWidget(self.exp_prediction_title)
        prediction_layout.addWidget(self.exp_prediction_label)
        prediction_layout.addWidget(self.exp_accuracy_label)

        card_layout.addWidget(self.exp_summary_label)
        card_layout.addWidget(self.exp_gain_label)
        card_layout.addWidget(prediction_container)
        exp_layout.addWidget(self.exp_card, 3, 0, 1, 4)

        exp_group.setLayout(exp_layout)
        root_layout.addWidget(exp_group)

        root_layout.addStretch(1)

        self._normalize_button_widths()
        self._refresh_anchor_summary()

    # ------------------------------------------------------------------
    # 설정 반영
    # ------------------------------------------------------------------
    def _apply_config_to_ui(self) -> None:
        self.other_toggle_button.setText("중지" if self.config.other_players.enabled else "시작")
        self.other_interval_spin.setValue(self.config.other_players.interval_sec)
        self.other_min_count_spin.setValue(self.config.other_players.min_count)
        self.other_color_edit.setText(",".join(self.config.other_players.color_codes))

        self.chat_interval_spin.setValue(self.config.chat.interval_sec)
        if not self.config.chat.whisper.hex_color:
            self.config.chat.whisper.hex_color = DEFAULT_WHISPER_COLOR
        if not self.config.chat.friend.hex_color:
            self.config.chat.friend.hex_color = DEFAULT_FRIEND_COLOR
        self.whisper_color_edit.setText(self.config.chat.whisper.hex_color)
        self.whisper_toggle_button.setText("중지" if self.config.chat.whisper.enabled else "시작")
        self.friend_color_edit.setText(self.config.chat.friend.hex_color)
        self.friend_toggle_button.setText("중지" if self.config.chat.friend.enabled else "시작")
        self._update_chat_status_label("whisper", False)
        self._update_chat_status_label("friend", False)

        self.exp_roi_label.setText(self._format_roi_text(self.config.exp.roi))
        if self.config.exp.last_minutes_limit:
            self.exp_minutes_edit.setText(str(self.config.exp.last_minutes_limit))

    def _normalize_button_widths(self) -> None:
        try:
            base_width = self.exp_start_button.sizeHint().width()
        except Exception:
            base_width = 80
        if base_width <= 0:
            base_width = 80

        try:
            long_base = max(
                self.exp_roi_button.sizeHint().width(),
                self.exp_test_button.sizeHint().width(),
            )
        except Exception:
            long_base = base_width
        if long_base <= 0:
            long_base = base_width

        small_buttons = [
            self.anchor_save_btn,
            self.anchor_load_btn,
            self.other_toggle_button,
            self.chat_roi_button,
            self.whisper_toggle_button,
            self.friend_toggle_button,
            self.exp_start_button,
            self.exp_reset_button,
        ]
        for button in small_buttons:
            if button is None:
                continue
            try:
                hint = button.sizeHint().width()
            except Exception:
                hint = base_width
            target = max(base_width, hint)
            button.setFixedWidth(target)

        long_buttons = [
            self.other_roi_button,
            self.exp_roi_button,
            self.exp_test_button,
        ]
        for button in long_buttons:
            if button is None:
                continue
            try:
                hint = button.sizeHint().width()
            except Exception:
                hint = long_base
            target = max(long_base, hint)
            button.setFixedWidth(target)

    def _apply_config_to_workers(self) -> None:
        self.other_watcher.update_settings(
            enabled=self.config.other_players.enabled,
            interval=self.other_interval_spin.value(),
            min_count=self.other_min_count_spin.value(),
            roi=self.config.other_players.roi,
            thresholds=self._compute_other_color_thresholds(self.config.other_players.color_codes),
        )

        color_map = {
            "whisper": (self.config.chat.whisper.hex_color, self.config.chat.whisper.enabled),
            "friend": (self.config.chat.friend.hex_color, self.config.chat.friend.enabled),
        }
        self.chat_watcher.update_settings(
            interval=self.chat_interval_spin.value(),
            roi=self.config.chat.roi,
            color_map=color_map,
        )

    def _normalize_chat_color_list_field(self, line_edit: QLineEdit, default: str) -> str:
        value = normalize_hex_color_list(line_edit.text(), default=default)
        if line_edit.text() != value:
            line_edit.setText(value)
        return value

    def _parse_other_colors_from_ui(self) -> list[str]:
        raw = self.other_color_edit.text()
        codes: list[str] = []
        if raw:
            for part in raw.split(","):
                code = normalize_hex_color(part)
                if len(code) == 6 and code not in codes:
                    codes.append(code)
        normalized_text = ",".join(codes)
        if self.other_color_edit.text() != normalized_text:
            self.other_color_edit.setText(normalized_text)
        return codes

    def _compute_other_color_thresholds(
        self, color_codes: list[str]
    ) -> list[tuple[np.ndarray, np.ndarray]]:
        thresholds: list[tuple[np.ndarray, np.ndarray]] = []
        for code in color_codes:
            bgr = _hex_to_bgr(code)
            if bgr is None:
                continue
            lower, upper = _build_color_threshold(bgr, delta_h=6, delta_s=45, delta_v=45)
            thresholds.append((lower, upper))
        return thresholds

    # ------------------------------------------------------------------
    # ROI 선택 처리
    # ------------------------------------------------------------------
    def _handle_other_roi_select(self) -> None:
        roi = self._prompt_roi_selection()
        if not roi:
            return
        self.config.other_players.roi = roi
        self._apply_config_to_workers()
        self._save_config()

    def _handle_other_toggle(self) -> None:
        colors = self._parse_other_colors_from_ui()
        self.config.other_players.color_codes = colors
        if not self.config.other_players.enabled and not self.config.other_players.color_codes:
            QMessageBox.warning(self, "다른 유저 감지", "감지할 HEX 색상 코드를 입력해주세요.")
            return
        self.config.other_players.enabled = not self.config.other_players.enabled
        self.other_toggle_button.setText("중지" if self.config.other_players.enabled else "시작")
        if not self.config.other_players.enabled:
            self.other_status_label.setText("감지 대기 중")
        self._apply_config_to_workers()
        self._save_config()

    def _handle_whisper_toggle(self) -> None:
        color_list = self._normalize_chat_color_list_field(self.whisper_color_edit, DEFAULT_WHISPER_COLOR)
        self.config.chat.whisper.hex_color = color_list
        self.config.chat.whisper.enabled = not self.config.chat.whisper.enabled
        self.whisper_toggle_button.setText("중지" if self.config.chat.whisper.enabled else "시작")
        self._update_chat_status_label("whisper", False)
        self._apply_config_to_workers()
        self._save_config()

    def _handle_friend_toggle(self) -> None:
        color_list = self._normalize_chat_color_list_field(self.friend_color_edit, DEFAULT_FRIEND_COLOR)
        self.config.chat.friend.hex_color = color_list
        self.config.chat.friend.enabled = not self.config.chat.friend.enabled
        self.friend_toggle_button.setText("중지" if self.config.chat.friend.enabled else "시작")
        self._update_chat_status_label("friend", False)
        self._apply_config_to_workers()
        self._save_config()

    def _handle_chat_roi_select(self) -> None:
        roi = self._prompt_roi_selection()
        if not roi:
            return
        self.config.chat.roi = roi
        self._apply_config_to_workers()
        self._save_config()

    def _handle_exp_roi_select(self) -> None:
        roi = self._prompt_roi_selection()
        if not roi:
            return
        self.config.exp.roi = roi
        self.exp_roi_label.setText(self._format_roi_text(roi))
        self._save_config()

    def _handle_exp_test(self) -> None:
        if StatusRecognitionPreviewDialog is None:
            QMessageBox.warning(self, "기능 사용 불가", "인식 테스트를 위해 Learning 모듈이 필요합니다.")
            return
        if not self.config.exp.roi:
            QMessageBox.warning(self, "경험치 측정", "먼저 경험치 OCR 범위를 설정해주세요.")
            return
        window_geometry = get_maple_window_geometry()
        region = resolve_roi_to_absolute(self.config.exp.roi, window=window_geometry)
        if not region:
            QMessageBox.warning(self, "경험치 측정", "경험치 범위를 절대 좌표로 변환할 수 없습니다. Mapleland 창 위치를 확인해주세요.")
            return
        frame = self._capture_region(region)
        if frame is None or frame.size == 0:
            QMessageBox.warning(self, "경험치 측정", "화면을 캡처하지 못했습니다. Mapleland 창이 가려져 있는지 확인해주세요.")
            return

        preview = self._prepare_exp_preview(frame)
        roi_text = self._format_roi_text(self.config.exp.roi)
        dialog = StatusRecognitionPreviewDialog(
            self,
            "EXP 인식 확인",
            f"탐지 범위: {roi_text}",
            frame,
            preview.get("processed"),
            preview.get("summary_lines", []),
            processed_title="전처리(Threshold)",
        )
        dialog.exec()

    def _prompt_roi_selection(self) -> Optional[Dict[str, object]]:
        try:
            snipper = ScreenSnipper(self)
        except Exception as exc:
            QMessageBox.warning(self, "오류", f"화면 영역 지정 도구를 열 수 없습니다: {exc}")
            return None
        if snipper.exec() != QDialog.DialogCode.Accepted:
            return None
        rect: QRect = snipper.get_roi()
        if rect.width() <= 0 or rect.height() <= 0:
            QMessageBox.warning(self, "잘못된 영역", "유효한 영역을 지정해주세요.")
            return None

        geometry = get_maple_window_geometry()
        if not geometry:
            QMessageBox.warning(self, "Mapleland 창", "Mapleland 창을 찾을 수 없습니다. 창을 전면에 두고 다시 시도해주세요.")
            return None

        anchor_name = self.config.anchor_name or last_used_anchor_name()
        relative = make_relative_roi(
            {
                "left": rect.left(),
                "top": rect.top(),
                "width": rect.width(),
                "height": rect.height(),
            },
            geometry,
            anchor_name=anchor_name,
        )
        return relative

    # ------------------------------------------------------------------
    # 상태 업데이트 및 이벤트 핸들러
    # ------------------------------------------------------------------
    def _handle_other_player_signal(self, count: int) -> None:
        if count <= 0:
            self.other_status_label.setText("감지 해제")
            play_sound_async("other_user_out.mp3")
            return

        previous_text = self.other_status_label.text()
        self.other_status_label.setText(f"감지됨: {count}명")
        if "감지됨" not in previous_text or self._parse_last_count(previous_text) < count:
            play_sound_async("other_user_in.mp3")
        elif self._parse_last_count(previous_text) > count:
            play_sound_async("other_user_out.mp3")

    def _handle_chat_signal(self, channel_key: str, detected: bool) -> None:
        previous = self._chat_detection_states.get(channel_key, False)
        self._update_chat_status_label(channel_key, detected)
        if detected and not previous:
            if channel_key == "whisper" and self.config.chat.whisper.enabled:
                play_sound_async("tap.mp3")
            elif channel_key == "friend" and self.config.chat.friend.enabled:
                play_sound_async("tap.mp3")

    def _parse_last_count(self, text: str) -> int:
        try:
            digits = ''.join(ch for ch in text if ch.isdigit())
            return int(digits) if digits else 0
        except ValueError:
            return 0

    def _update_chat_status_label(self, channel: str, detected: bool) -> None:
        if channel == "whisper":
            label = self.whisper_status_label
            enabled = self.config.chat.whisper.enabled
        elif channel == "friend":
            label = self.friend_status_label
            enabled = self.config.chat.friend.enabled
        else:
            return
        if not enabled:
            label.setText("")
            label.setStyleSheet("")
            self._chat_detection_states[channel] = False
            return
        text = "감지" if detected else "미감지"
        color = "#2ecc71" if detected else "#7f8c8d"
        label.setText(text)
        label.setStyleSheet(f"color: {color};")
        self._chat_detection_states[channel] = detected

    # ------------------------------------------------------------------
    # 경험치 측정 로직
    # ------------------------------------------------------------------
    def _handle_exp_toggle(self) -> None:
        if self.exp_active:
            self._stop_exp_measurement()
        else:
            self._start_exp_measurement()

    def _start_exp_measurement(self) -> None:
        if not self.config.exp.roi:
            QMessageBox.warning(self, "경험치 측정", "먼저 경험치 OCR 범위를 설정해주세요.")
            return
        if not PYTESSERACT_AVAILABLE:
            QMessageBox.warning(self, "OCR", "pytesseract를 사용할 수 없습니다. 설치 상태를 확인해주세요.")
            return

        minutes_text = self.exp_minutes_edit.text().strip()
        minutes_limit: Optional[int] = None
        if minutes_text:
            try:
                value = int(minutes_text)
            except ValueError:
                QMessageBox.warning(self, "입력 오류", "측정 분은 1~120 사이의 정수여야 합니다.")
                return
            if not (1 <= value <= 120):
                QMessageBox.warning(self, "입력 오류", "측정 분은 1~120 사이의 정수여야 합니다.")
                return
            minutes_limit = value

        window_geometry = get_maple_window_geometry()
        region = resolve_roi_to_absolute(self.config.exp.roi, window=window_geometry)
        if not region:
            QMessageBox.warning(self, "경험치 측정", "경험치 범위를 절대 좌표로 변환할 수 없습니다. 창 위치가 맞는지 확인하세요.")
            return

        frame = self._capture_region(region)
        snapshot = self._run_exp_ocr(frame) if frame is not None else None
        if snapshot is None:
            QMessageBox.warning(self, "경험치 측정", "초기 OCR에 실패했습니다. 범위 또는 밝기를 조정해주세요.")
            return

        amount, percent = snapshot
        now = time.time()
        self.exp_history = []
        self.exp_prediction_records.clear()
        self.exp_prediction_accuracy.clear()
        self._last_prediction_snapshot_ts = 0.0
        self.exp_start_ts = now
        self.exp_minutes_limit = minutes_limit
        self.exp_active = True
        self.exp_timer.start(int(self.config.exp.update_interval_sec * 1000))
        self.exp_elapsed_timer.start()
        self.exp_start_button.setText("정지")
        self.config.exp.last_minutes_limit = minutes_limit
        self._save_config()
        self._ingest_exp_snapshot(amount, percent, now, force_reset=True)
        self._update_exp_labels()

    def _stop_exp_measurement(self, *, finished: bool = False) -> None:
        self.exp_timer.stop()
        self.exp_elapsed_timer.stop()
        self.exp_active = False
        self.exp_start_ts = None
        self.exp_minutes_limit = None if finished else self.exp_minutes_limit
        self.exp_start_button.setText("시작")
        if finished:
            play_sound_async("tap.mp3")

    def _handle_exp_reset(self) -> None:
        if self.exp_active:
            self._stop_exp_measurement()
        self.exp_history.clear()
        self.exp_summary_label.setText("측정을 시작하세요.")
        self.exp_gain_label.setText("분당 데이터 없음")
        self.exp_prediction_label.setText("예측 데이터 없음")
        self.exp_accuracy_label.setText("정확도 데이터 없음")
        self.exp_prediction_records.clear()
        self.exp_prediction_accuracy.clear()
        self._last_prediction_snapshot_ts = 0.0

    def _handle_exp_elapsed_tick(self) -> None:
        if not self.exp_active:
            return
        self._update_exp_labels()

    def _handle_exp_tick(self) -> None:
        if not self.exp_active:
            return
        if not is_maple_window_foreground():
            return

        window_geometry = get_maple_window_geometry()
        region = resolve_roi_to_absolute(self.config.exp.roi, window=window_geometry)
        if not region:
            return

        frame = self._capture_region(region)
        snapshot = self._run_exp_ocr(frame) if frame is not None else None
        if snapshot is None:
            return

        amount, percent = snapshot
        now = time.time()
        if not self._ingest_exp_snapshot(amount, percent, now):
            return

        self._update_exp_labels()

        if self.exp_start_ts and self.exp_minutes_limit:
            elapsed_minutes = (now - self.exp_start_ts) / 60.0
            if elapsed_minutes >= self.exp_minutes_limit:
                self._stop_exp_measurement(finished=True)

    def _ingest_exp_snapshot(self, amount: int, percent: float, timestamp: float, *, force_reset: bool = False) -> bool:
        if force_reset or not self.exp_history:
            snapshot = ExpSnapshot(
                amount=amount,
                percent=percent,
                timestamp=timestamp,
                total_amount=0.0,
                total_percent=0.0,
                level_ups=0,
            )
            self.exp_history = [snapshot]
            return True

        last_snapshot = self.exp_history[-1]
        if amount == last_snapshot.amount and math.isclose(percent, last_snapshot.percent, abs_tol=0.01):
            return False

        level_up = self._detect_level_up(last_snapshot, amount, percent)
        if level_up:
            delta_percent = (100.0 - last_snapshot.percent) + percent
            level_ups = last_snapshot.level_ups + 1
        else:
            delta_percent = max(percent - last_snapshot.percent, 0.0)
            level_ups = last_snapshot.level_ups

        delta_percent = max(delta_percent, 0.0)
        delta_amount = max(amount - last_snapshot.amount, 0)
        total_amount = last_snapshot.total_amount + delta_amount
        total_percent = last_snapshot.total_percent + delta_percent
        snapshot = ExpSnapshot(
            amount=amount,
            percent=percent,
            timestamp=timestamp,
            total_amount=total_amount,
            total_percent=total_percent,
            level_ups=level_ups,
        )
        self.exp_history.append(snapshot)
        return True

    def _detect_level_up(self, previous: ExpSnapshot, amount: int, percent: float) -> bool:
        percent_drop = previous.percent - percent
        if percent <= EXP_LEVEL_UP_POST_PERCENT and percent_drop >= EXP_LEVEL_UP_DROP_THRESHOLD:
            return True
        if percent <= EXP_LEVEL_UP_POST_PERCENT and amount < previous.amount:
            return True
        return False

    def _compute_regression_rate(self, attr: str) -> float:
        # 기존 전 구간 회귀 → 최근 창 + 가중치 회귀로 대체
        history = self._recent_history(EXP_REGRESSION_WINDOW_SEC)
        return self._compute_weighted_regression_rate(history, attr, half_life_sec=EXP_REGRESSION_HALF_LIFE_SEC)

    def _snapshot_seconds_ago(self, seconds: int) -> Optional[ExpSnapshot]:
        if not self.exp_history or seconds <= 0:
            return None
        target_time = self.exp_history[-1].timestamp - seconds
        if target_time <= self.exp_history[0].timestamp:
            return self.exp_history[0]
        closest = min(self.exp_history, key=lambda snap: abs(snap.timestamp - target_time))
        return closest

    def _snapshot_at_timestamp(self, target_ts: float) -> Optional[ExpSnapshot]:
        if not self.exp_history:
            return None
        closest = min(self.exp_history, key=lambda snap: abs(snap.timestamp - target_ts))
        tolerance = max(self.config.exp.update_interval_sec * 1.5, 15.0)
        if abs(closest.timestamp - target_ts) > tolerance:
            return None
        return closest

    def _recent_history(self, window_sec: int) -> list[ExpSnapshot]:
        if not self.exp_history:
            return []
        latest_ts = self.exp_history[-1].timestamp
        cutoff = latest_ts - max(int(window_sec), 1)
        recent = [snap for snap in self.exp_history if snap.timestamp >= cutoff]
        if len(recent) < 2 and len(self.exp_history) >= 2:
            # 최소 2개 확보를 위해 가장 최근 2개라도 반환
            return self.exp_history[-2:]
        return recent

    def _compute_weighted_regression_rate(
        self,
        history: list[ExpSnapshot],
        attr: str,
        *,
        half_life_sec: float,
    ) -> float:
        if len(history) < EXP_REGRESSION_MIN_SAMPLES:
            return 0.0
        latest_ts = history[-1].timestamp
        # 지수가중치: w = 0.5 ** (age / half_life)
        xs: list[float] = []
        ys: list[float] = []
        ws: list[float] = []
        for snap in history:
            x = snap.timestamp - history[0].timestamp
            y = getattr(snap, attr)
            age = latest_ts - snap.timestamp
            w = 0.5 ** (age / max(half_life_sec, 1e-6))
            xs.append(x)
            ys.append(float(y))
            ws.append(w)
        # 가중 평균
        sum_w = sum(ws)
        if sum_w <= 0:
            return 0.0
        mean_x = sum(w * x for w, x in zip(ws, xs)) / sum_w
        mean_y = sum(w * y for w, y in zip(ws, ys)) / sum_w
        cov = sum(w * (x - mean_x) * (y - mean_y) for w, x, y in zip(ws, xs, ys))
        var = sum(w * (x - mean_x) ** 2 for w, x in zip(ws, xs))
        if var <= 0:
            return 0.0
        slope = cov / var
        return max(slope, 0.0)

    def _compute_ewma_rate(
        self,
        history: list[ExpSnapshot],
        attr: str,
        *,
        window_sec: int,
        half_life_sec: float,
    ) -> float:
        # 연속 구간의 순간 속도(dy/dt)를 dt 가중 EWMA로 결합
        recent = self._recent_history(window_sec)
        if len(recent) < 2:
            return 0.0
        # 연속 시간 지수감쇠 계수
        tau = max(half_life_sec / math.log(2), 1e-6)
        latest_ts = recent[-1].timestamp
        r_ewma = None
        total_w = 0.0
        for prev, curr in zip(recent[:-1], recent[1:]):
            dt = curr.timestamp - prev.timestamp
            if dt <= 0:
                continue
            dy = float(getattr(curr, attr)) - float(getattr(prev, attr))
            r = max(dy / dt, 0.0)
            # 쌍이 끝나는 시점의 연령을 기준으로 가중
            age = latest_ts - curr.timestamp
            w = (1.0 - math.exp(-dt / tau)) * (0.5 ** (age / max(half_life_sec, 1e-6)))
            if r_ewma is None:
                r_ewma = r * w
                total_w = w
            else:
                r_ewma = r_ewma + w * (r - (r_ewma / max(total_w, 1e-12)))
                total_w += w
        if r_ewma is None or total_w <= 0:
            return 0.0
        return max(r_ewma / total_w, 0.0)

    def _store_exp_prediction(self, *, minutes: int, predicted_percent: float, snapshot_ts: float) -> None:
        target_ts = snapshot_ts + (minutes * 60)
        record = ExpPredictionRecord(
            minutes=minutes,
            predicted_percent=min(max(predicted_percent, 0.0), 100.0),
            target_ts=target_ts,
            snapshot_ts=snapshot_ts,
        )
        self.exp_prediction_records.append(record)
        if len(self.exp_prediction_records) > 200:
            self.exp_prediction_records = self.exp_prediction_records[-200:]

    def _evaluate_prediction_records(self) -> None:
        if not self.exp_prediction_records or not self.exp_history:
            return
        latest_ts = self.exp_history[-1].timestamp
        remaining_records: list[ExpPredictionRecord] = []
        for record in self.exp_prediction_records:
            if record.evaluated:
                continue
            if latest_ts < record.target_ts:
                remaining_records.append(record)
                continue
            actual_snapshot = self._snapshot_at_timestamp(record.target_ts)
            if actual_snapshot is None:
                remaining_records.append(record)
                continue
            actual_percent = actual_snapshot.percent
            error = abs(actual_percent - record.predicted_percent)
            accuracy = max(0.0, 100.0 - error)
            self.exp_prediction_accuracy[record.minutes] = accuracy
            record.evaluated = True
        stale_threshold = latest_ts - 3600  # 1시간 이전 예측은 정리
        self.exp_prediction_records = [
            record
            for record in remaining_records
            if record.target_ts >= stale_threshold
        ]

    def _format_accuracy_text(self, minutes: int) -> str:
        accuracy = self.exp_prediction_accuracy.get(minutes)
        if accuracy is None:
            return "정확도 데이터 없음"
        return f"정확도 {accuracy:.1f}%"

    def _update_exp_labels(self) -> None:
        if not self.exp_history:
            return
        first = self.exp_history[0]
        latest = self.exp_history[-1]
        measurement_elapsed = max(latest.timestamp - first.timestamp, 0.0)
        gained_amount = int(latest.total_amount)
        gained_percent = latest.total_percent
        self._evaluate_prediction_records()

        current_time = time.time() if self.exp_active else None
        if self.exp_active and self.exp_start_ts is not None and current_time is not None:
            elapsed_seconds = max(int(current_time - self.exp_start_ts), 0)
        else:
            elapsed_seconds = max(int(measurement_elapsed), 0)

        elapsed_text = _format_duration_hms(elapsed_seconds)
        level_up_text = f" | 레벨업 {latest.level_ups}회" if latest.level_ups else ""
        self.exp_summary_label.setText(
            f"누적: +{gained_amount} ( +{gained_percent:.2f}% ){level_up_text} | 경과 {elapsed_text}"
        )

        recent_snapshot = self._snapshot_seconds_ago(60)
        if recent_snapshot and latest.timestamp - recent_snapshot.timestamp >= 45:
            delta_amount = int(latest.total_amount - recent_snapshot.total_amount)
            delta_percent = latest.total_percent - recent_snapshot.total_percent
            self.exp_gain_label.setText(f"최근 1분: +{delta_amount} | +{delta_percent:.2f}%")
        else:
            self.exp_gain_label.setText("최근 1분: 데이터 부족")

        elapsed_for_rate = measurement_elapsed
        if self.exp_active and self.exp_start_ts is not None and current_time is not None:
            elapsed_for_rate = max(current_time - self.exp_start_ts, measurement_elapsed)

        # 휴식/정체 판단: 최근 20초 누적 증가가 너무 작으면 예측 0 처리
        idle_snapshot = self._snapshot_seconds_ago(EXP_IDLE_WINDOW_SEC)
        idle = False
        if idle_snapshot:
            idle_delta_percent = latest.total_percent - idle_snapshot.total_percent
            idle = idle_delta_percent < EXP_IDLE_MIN_PERCENT

        # 1분 예상은 최근 60초 EWMA 속도, 그 외는 최근 10분 가중 회귀 속도 사용
        ewma_rate_amount = self._compute_ewma_rate(
            self.exp_history, "total_amount", window_sec=EXP_EWMA_1MIN_WINDOW_SEC, half_life_sec=EXP_EWMA_1MIN_HALF_LIFE_SEC
        )
        ewma_rate_percent = self._compute_ewma_rate(
            self.exp_history, "total_percent", window_sec=EXP_EWMA_1MIN_WINDOW_SEC, half_life_sec=EXP_EWMA_1MIN_HALF_LIFE_SEC
        )
        reg_rate_amount = self._compute_regression_rate("total_amount")
        reg_rate_percent = self._compute_regression_rate("total_percent")

        # 폴백: 데이터 부족 시 평균 속도 사용
        if ewma_rate_amount <= 0 and elapsed_for_rate > 0:
            ewma_rate_amount = gained_amount / elapsed_for_rate
        if ewma_rate_percent <= 0 and elapsed_for_rate > 0:
            ewma_rate_percent = gained_percent / elapsed_for_rate
        if reg_rate_amount <= 0 and elapsed_for_rate > 0:
            reg_rate_amount = gained_amount / elapsed_for_rate
        if reg_rate_percent <= 0 and elapsed_for_rate > 0:
            reg_rate_percent = gained_percent / elapsed_for_rate

        should_store_prediction = self.exp_active and latest.timestamp > self._last_prediction_snapshot_ts
        prediction_lines = []
        accuracy_summary: list[str] = []
        horizons = (5, 15, 30, 60)
        for minutes in horizons:
            if idle:
                amount_projection = 0.0
                percent_projection = 0.0
            else:
                rate_amt = ewma_rate_amount if minutes == 5 else reg_rate_amount
                rate_pct = ewma_rate_percent if minutes == 5 else reg_rate_percent
                amount_projection = rate_amt * (minutes * 60)
                percent_projection = rate_pct * (minutes * 60)
            future_percent = min(100.0, max(0.0, latest.percent + percent_projection))
            accuracy_text = self._format_accuracy_text(minutes)
            prediction_lines.append(
                f"{minutes}분 예상: +{int(amount_projection)} | 현재 {latest.percent:.2f}% → {future_percent:.2f}% (+{percent_projection:.2f}%) | {accuracy_text}"
            )
            accuracy_summary.append(f"{minutes}분 {accuracy_text}")
            if should_store_prediction:
                self._store_exp_prediction(minutes=minutes, predicted_percent=future_percent, snapshot_ts=latest.timestamp)

        if should_store_prediction:
            self._last_prediction_snapshot_ts = latest.timestamp

        # 100%까지 ETA는 장기 추세(회귀 퍼센트 속도)를 사용
        if reg_rate_percent > 0:
            remaining_percent = max(0.0, 100.0 - latest.percent)
            eta_seconds = remaining_percent / reg_rate_percent
            eta_minutes = eta_seconds / 60.0
            eta_text = f"100%까지 예상 {eta_minutes:.1f}분"
        else:
            eta_text = "100% 예측 불가"

        prediction_lines.append(eta_text)
        self.exp_prediction_title.setText("예측 (5/15/30/60분)")
        self.exp_prediction_label.setText("\n".join(prediction_lines))

        if accuracy_summary:
            self.exp_accuracy_label.setText("정확도(최근 실측 비교): " + " | ".join(accuracy_summary))
        else:
            self.exp_accuracy_label.setText("정확도 데이터 없음")

    def _capture_region(self, region: Dict[str, int]) -> Optional[np.ndarray]:
        try:
            with mss.mss() as sct:
                frame = sct.grab(region)
        except Exception:
            return None
        return np.array(frame)[:, :, :3]

    def _to_qimage(self, image_bgr: np.ndarray) -> Optional[QImage]:
        if image_bgr is None or image_bgr.size == 0:
            return None
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        h, w = image_rgb.shape[:2]
        bytes_per_line = 3 * w
        return QImage(image_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()

    # ------------------------------
    # 채팅 인식 테스트 & 스포이드
    # ------------------------------
    def _handle_chat_test(self) -> None:
        if not self.config.chat.roi:
            QMessageBox.warning(self, "채팅 인식 테스트", "먼저 채팅창 범위를 설정해주세요.")
            return
        window_geometry = get_maple_window_geometry()
        region = resolve_roi_to_absolute(self.config.chat.roi, window=window_geometry)
        if not region:
            QMessageBox.warning(self, "채팅 인식 테스트", "채팅 범위를 절대 좌표로 변환할 수 없습니다.")
            return
        frame_bgr = self._capture_region(region)
        if frame_bgr is None or frame_bgr.size == 0:
            QMessageBox.warning(self, "채팅 인식 테스트", "화면 캡처에 실패했습니다.")
            return

        # 활성 색상 파싱 → 임계치 생성
        color_defs = {
            "whisper": (self.whisper_color_edit.text().strip(), self.config.chat.whisper.enabled),
            "friend": (self.friend_color_edit.text().strip(), self.config.chat.friend.enabled),
        }
        active_thresholds: Dict[str, List[Tuple[np.ndarray, np.ndarray]]] = {}
        for key, (hex_text, enabled) in color_defs.items():
            if not enabled:
                continue
            thresholds: List[Tuple[np.ndarray, np.ndarray]] = []
            for part in (hex_text or "").split(","):
                code = normalize_hex_color(part)
                if len(code) != 6:
                    continue
                bgr = _hex_to_bgr(code)
                if bgr is None:
                    continue
                lo, hi = _build_color_threshold(
                    bgr,
                    delta_h=CHAT_COLOR_DELTA_H,
                    delta_s=CHAT_COLOR_DELTA_S,
                    delta_v=CHAT_COLOR_DELTA_V,
                )
                thresholds.append((lo, hi))
            if thresholds:
                active_thresholds[key] = thresholds

        frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        h, w = frame_hsv.shape[:2]
        min_pixels = max(CHAT_MIN_PIXEL_COUNT, int(h * w * CHAT_MIN_PIXEL_RATIO))

        overlay = frame_bgr.copy()
        summary_lines: List[str] = []
        channel_labels = {"whisper": "귓속말", "friend": "친구채팅"}
        combined_all = np.zeros((h, w), dtype=np.uint8)
        for key, ths in active_thresholds.items():
            combined_mask = np.zeros((h, w), dtype=np.uint8)
            for (lo, hi) in ths:
                mask = cv2.inRange(frame_hsv, lo, hi)
                combined_mask = cv2.bitwise_or(combined_mask, mask)
            pixels = int(cv2.countNonZero(combined_mask))
            detected = pixels >= min_pixels
            label = channel_labels.get(key, key)
            summary_lines.append(f"{label}: {pixels}px → {'감지' if detected else '미감지'}")
            combined_all = cv2.bitwise_or(combined_all, combined_mask)
        if int(cv2.countNonZero(combined_all)) > 0:
            red_layer = np.zeros_like(frame_bgr)
            red_layer[:, :] = (0, 0, 255)
            overlay = np.where(combined_all[:, :, None] > 0, (0.5 * red_layer + 0.5 * overlay).astype(np.uint8), overlay)

        # 다이얼로그 구성(원본 크기 표시)
        dialog = QDialog(self)
        dialog.setWindowTitle("채팅 인식 확인")
        vbox = QVBoxLayout(dialog)
        info = QLabel("\n".join(summary_lines) if summary_lines else "활성화된 채널이 없습니다.")
        vbox.addWidget(info)
        img_label = QLabel()
        q_ov = self._to_qimage(overlay)
        if q_ov:
            pix = QPixmap.fromImage(q_ov)
            img_label.setPixmap(pix)
            img_label.resize(pix.size())
            dialog.resize(pix.size())
        vbox.addWidget(img_label)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.accept)
        vbox.addWidget(close_btn)
        dialog.exec()

    def _handle_whisper_pick(self) -> None:
        self._handle_color_pick(self.whisper_color_edit)

    def _handle_friend_pick(self) -> None:
        self._handle_color_pick(self.friend_color_edit)

    def _handle_color_pick(self, target_edit: QLineEdit) -> None:
        picker = _ColorPickerDialog(self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        hex_code = picker.get_hex()
        if not hex_code:
            return
        existing = [c for c in (target_edit.text() or "").split(",") if c]
        if hex_code not in existing:
            existing.append(hex_code)
        target_edit.setText(",".join([c for c in existing if len(c) == 6]))
        self._on_chat_settings_changed()

    def _prepare_exp_preview(self, image_bgr: np.ndarray) -> dict:
        result: dict = {
            "processed": None,
            "summary_lines": [],
            "amount": None,
            "percent": None,
        }
        if image_bgr is None or image_bgr.size == 0:
            result["summary_lines"] = ["상태: 캡처 이미지가 비어 있습니다."]
            return result

        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (0, 0), fx=1.2, fy=1.2, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        result["processed"] = thresh

        lines: list[str] = []

        if not PYTESSERACT_AVAILABLE or pytesseract is None:
            lines.append("상태: pytesseract가 설치되어 있지 않아 OCR을 수행할 수 없습니다.")
            result["summary_lines"] = lines
            return result

        config = "--psm 7 -c tessedit_char_whitelist=0123456789.%[]"
        try:
            text = pytesseract.image_to_string(thresh, config=config)
        except Exception as exc:  # pragma: no cover - pytesseract 내부 오류 대비
            lines.append(f"상태: pytesseract 실행 중 오류가 발생했습니다. ({exc})")
            result["summary_lines"] = lines
            return result

        cleaned = text.strip().replace("\n", " ") if text else ""

        amount_raw = StatusMonitorThread._extract_exp_amount(cleaned) if cleaned else None
        percent_value = StatusMonitorThread._extract_exp_percent(cleaned) if cleaned else None

        amount_value: Optional[int] = None
        if amount_raw is not None:
            try:
                amount_value = int(amount_raw)
            except (TypeError, ValueError):
                amount_value = None

        if not cleaned:
            lines.append("상태: OCR 결과가 비어 있습니다.")
        else:
            lines.append(f"원문: {cleaned}")

        if amount_value is not None:
            lines.append(f"추출된 경험치 값: {amount_value}")
        else:
            lines.append("추출된 경험치 값: 해석 실패")

        if percent_value is not None:
            lines.append(f"추출된 경험치 %: {percent_value:.2f}%")
        else:
            lines.append("추출된 경험치 %: 해석 실패")

        result["summary_lines"] = lines
        result["amount"] = amount_value
        result["percent"] = percent_value
        return result

    def _run_exp_ocr(self, image_bgr: np.ndarray) -> Optional[Tuple[int, float]]:
        preview = self._prepare_exp_preview(image_bgr)
        amount = preview.get("amount")
        percent = preview.get("percent")
        if amount is None or percent is None:
            return None
        return int(amount), float(percent)

    # ------------------------------------------------------------------
    # 앵커 관리
    # ------------------------------------------------------------------
    def _refresh_anchor_summary(self) -> None:
        anchors = list_saved_anchors()
        anchor_name = self.config.anchor_name or last_used_anchor_name()
        if anchor_name and anchor_name in anchors:
            summary = anchor_name
        else:
            summary = ""
        self.anchor_summary_label.setText(summary)
        self.anchor_load_btn.setEnabled(bool(anchors))

    def _handle_anchor_save(self) -> None:
        if WindowAnchorSaveDialog is None:
            QMessageBox.warning(self, "지원 불가", "Learning 모듈이 없어 창 좌표 저장 기능을 사용할 수 없습니다.")
            return
        geometry = get_maple_window_geometry()
        if not geometry:
            QMessageBox.warning(self, "창 위치", "Mapleland 창을 찾을 수 없습니다.")
            return
        suggested = self.config.anchor_name or "위치 1"
        dialog = WindowAnchorSaveDialog(geometry, suggested, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.anchor_name()
        if not name:
            QMessageBox.warning(self, "입력 필요", "이름을 입력해주세요.")
            return
        save_window_anchor(name, geometry)
        set_last_used_anchor(name)
        self.config.anchor_name = name
        self._refresh_anchor_summary()
        self._save_config()

    def _handle_anchor_load(self) -> None:
        if WindowAnchorLoadDialog is None:
            QMessageBox.warning(self, "지원 불가", "Learning 모듈이 없어 창 좌표 불러오기를 사용할 수 없습니다.")
            return
        anchors = list_saved_anchors()
        if not anchors:
            QMessageBox.information(self, "안내", "저장된 창 좌표가 없습니다.")
            return
        last_used = self.config.anchor_name or last_used_anchor_name()
        dialog = WindowAnchorLoadDialog(anchors, last_used, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_anchor_name()
        if not selected:
            return
        anchor_payload = get_anchor(selected)
        if anchor_payload is None:
            QMessageBox.warning(self, "불러오기 실패", "선택한 좌표 정보를 읽을 수 없습니다.")
            self._refresh_anchor_summary()
            return

        succeeded, message = restore_maple_window(anchor_payload)
        if succeeded:
            set_last_used_anchor(selected)
            self.config.anchor_name = selected
            QMessageBox.information(self, "복원 완료", message)
        else:
            QMessageBox.warning(self, "복원 실패", message)
        self._refresh_anchor_summary()
        self._save_config()

    # ------------------------------------------------------------------
    # 설정 저장/로드
    # ------------------------------------------------------------------
    def _save_config(self) -> None:
        data = self.config.to_dict()
        data["other_players"]["enabled"] = self.config.other_players.enabled
        data["other_players"]["interval_sec"] = self.other_interval_spin.value()
        data["other_players"]["min_count"] = self.other_min_count_spin.value()
        data["other_players"]["roi"] = self.config.other_players.roi or {}
        data["other_players"]["colors"] = list(self.config.other_players.color_codes)

        data["chat"]["interval_sec"] = self.chat_interval_spin.value()
        data["chat"]["roi"] = self.config.chat.roi or {}
        data["chat"]["whisper"] = {
            "enabled": self.config.chat.whisper.enabled,
            "hex_color": self.config.chat.whisper.hex_color,
        }
        data["chat"]["friend"] = {
            "enabled": self.config.chat.friend.enabled,
            "hex_color": self.config.chat.friend.hex_color,
        }

        data["exp"]["roi"] = self.config.exp.roi or {}
        data["exp"]["last_minutes_limit"] = self.config.exp.last_minutes_limit

        data["anchor_name"] = self.config.anchor_name
        pos = self.pos()
        data["window_pos"] = [int(pos.x()), int(pos.y())]

        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_config(self) -> Dict[str, object]:
        if not CONFIG_FILE.exists():
            return {}
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _format_roi_text(self, roi_payload: Optional[Dict[str, object]]) -> str:
        if not roi_payload:
            return "범위가 지정되지 않았습니다."
        return ""

    # ------------------------------------------------------------------
    # 위젯 이벤트
    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_config()
        self.other_watcher.stop()
        self.chat_watcher.stop()
        self.other_watcher.wait(1000)
        self.chat_watcher.wait(1000)
        super().closeEvent(event)

    def _connect_signals(self) -> None:
        self.other_interval_spin.valueChanged.connect(self._on_other_settings_changed)
        self.other_min_count_spin.valueChanged.connect(self._on_other_settings_changed)
        self.other_color_edit.editingFinished.connect(self._on_other_settings_changed)
        self.whisper_color_edit.editingFinished.connect(self._on_chat_settings_changed)
        self.friend_color_edit.editingFinished.connect(self._on_chat_settings_changed)
        self.chat_interval_spin.valueChanged.connect(self._on_chat_settings_changed)
        # chat_test_button, pick buttons는 생성 시점에 연결됨

    def _on_other_settings_changed(self) -> None:
        colors = self._parse_other_colors_from_ui()
        self.config.other_players.color_codes = colors
        # 버튼을 통한 토글에서만 enabled 상태를 바꾸므로 여기서는 주기/인원만 반영
        self.config.other_players.interval_sec = self.other_interval_spin.value()
        self.config.other_players.min_count = self.other_min_count_spin.value()
        self._apply_config_to_workers()
        self._save_config()

    def _on_chat_settings_changed(self) -> None:
        self.config.chat.interval_sec = self.chat_interval_spin.value()
        self.config.chat.whisper.hex_color = self._normalize_chat_color_list_field(self.whisper_color_edit, DEFAULT_WHISPER_COLOR)
        self.config.chat.friend.hex_color = self._normalize_chat_color_list_field(self.friend_color_edit, DEFAULT_FRIEND_COLOR)
        self._apply_config_to_workers()
        self._save_config()


def main() -> None:
    app = QApplication.instance()
    owns_app = False
    if app is None:
        owns_app = True
        app = QApplication(sys.argv)

    widget = MonitorDashboard()
    widget.show()

    if owns_app:
        sys.exit(app.exec())


class _ColorPickerDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._screenshot, self._origin = self._capture_virtual_desktop()
        if self._screenshot.isNull():
            raise RuntimeError("화면 캡처에 실패했습니다.")
        self.setGeometry(QRect(self._origin, self._screenshot.size()))
        self._hover = QPoint(self._screenshot.width() // 2, self._screenshot.height() // 2)
        self._picked_hex: Optional[str] = None

    def _capture_virtual_desktop(self) -> Tuple[QImage, QPoint]:
        origin = QPoint(0, 0)
        try:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                shot = sct.grab(mon)
            img = QImage(shot.rgb, shot.width, shot.height, QImage.Format.Format_RGB888)
            origin = QPoint(mon.get("left", 0), mon.get("top", 0))
            return img.copy(), origin
        except Exception:
            pass
        screens = QApplication.screens()
        if not screens:
            return QImage(), origin
        virtual_rect = screens[0].geometry()
        for screen in screens[1:]:
            virtual_rect = virtual_rect.united(screen.geometry())
        origin = virtual_rect.topLeft()
        snapshot = QPixmap(virtual_rect.size())
        snapshot.fill(Qt.GlobalColor.transparent)
        painter = QPainter(snapshot)
        for screen in screens:
            geo = screen.geometry()
            offset = geo.topLeft() - origin
            painter.drawPixmap(offset, screen.grabWindow(0))
        painter.end()
        return snapshot.toImage(), origin

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.drawImage(QPoint(0, 0), self._screenshot)
        painter.setPen(QPen(QColor(255, 0, 0), 1))
        x, y = self._hover.x(), self._hover.y()
        painter.drawLine(x - 15, y, x + 15, y)
        painter.drawLine(x, y - 15, x, y + 15)
        zoom_size = 15
        scale = 10
        x0 = max(0, x - zoom_size // 2)
        y0 = max(0, y - zoom_size // 2)
        rect = QRect(
            x0,
            y0,
            min(zoom_size, self._screenshot.width() - x0),
            min(zoom_size, self._screenshot.height() - y0),
        )
        sub = self._screenshot.copy(rect)
        zoom = QPixmap.fromImage(sub).scaled(
            rect.width() * scale,
            rect.height() * scale,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        zx = min(self.width() - zoom.width() - 10, x + 20)
        zy = min(self.height() - zoom.height() - 10, y + 20)
        painter.drawPixmap(zx, zy, zoom)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawRect(zx - 1, zy - 1, zoom.width() + 2, zoom.height() + 2)
        painter.setPen(QPen(QColor(255, 0, 0), 1))
        zx_center = zx + (self._hover.x() - x0) * scale + scale // 2
        zy_center = zy + (self._hover.y() - y0) * scale + scale // 2
        painter.drawLine(zx_center - 10, zy_center, zx_center + 10, zy_center)
        painter.drawLine(zx_center, zy_center - 10, zx_center, zy_center + 10)

    def mouseMoveEvent(self, event):  # noqa: N802
        pt = event.position().toPoint()
        x = max(0, min(self._screenshot.width() - 1, pt.x()))
        y = max(0, min(self._screenshot.height() - 1, pt.y()))
        self._hover = QPoint(x, y)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            c = self._screenshot.pixelColor(self._hover)
            self._picked_hex = f"{c.red():02X}{c.green():02X}{c.blue():02X}"
            self.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.reject()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()

    def get_hex(self) -> Optional[str]:
        return self._picked_hex


if __name__ == "__main__":
    main()
