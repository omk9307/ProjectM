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
from typing import Dict, Optional, Tuple

import cv2
import mss
import numpy as np

from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QRect, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent
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
    QVBoxLayout,
    QWidget,
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
                cfg.chat.whisper.hex_color = normalize_hex_color(whisper.get("hex_color", DEFAULT_WHISPER_COLOR) or DEFAULT_WHISPER_COLOR)
            else:
                cfg.chat.whisper.hex_color = DEFAULT_WHISPER_COLOR
            friend = chat_src.get("friend")
            if isinstance(friend, dict):
                cfg.chat.friend.enabled = bool(friend.get("enabled", False))
                cfg.chat.friend.hex_color = normalize_hex_color(friend.get("hex_color", DEFAULT_FRIEND_COLOR) or DEFAULT_FRIEND_COLOR)
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
        self._active_colors: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
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
                rgb = _hex_to_bgr(hex_color)
                if rgb is None:
                    continue
                lower, upper = _build_color_threshold(
                    rgb,
                    delta_h=CHAT_COLOR_DELTA_H,
                    delta_s=CHAT_COLOR_DELTA_S,
                    delta_v=CHAT_COLOR_DELTA_V,
                )
                self._active_colors[key] = (lower, upper)
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

                if not is_maple_window_foreground():
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
                frame_hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
                frame_height, frame_width = frame_hsv.shape[:2]
                min_pixels = max(
                    CHAT_MIN_PIXEL_COUNT,
                    int(frame_height * frame_width * CHAT_MIN_PIXEL_RATIO),
                )

                current_states: Dict[str, bool] = {}
                for key, (lower, upper) in active_colors.items():
                    mask = cv2.inRange(frame_hsv, lower, upper)
                    pixel_count = int(cv2.countNonZero(mask))
                    detected = pixel_count >= min_pixels
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


# ---------------------------------------------------------------------------
# 메인 위젯
# ---------------------------------------------------------------------------


class MonitorDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Project Maple - 모니터 대시보드")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

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

        self._chat_detection_states: Dict[str, bool] = {"whisper": False, "friend": False}

        self._build_ui()
        self._apply_config_to_ui()
        self._apply_config_to_workers()
        self._connect_signals()

        if self.config.window_pos:
            self.move(*self.config.window_pos)
        else:
            self.move(80, 20)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        self.anchor_summary_label = QLabel()
        self.anchor_save_btn = QPushButton("저장")
        self.anchor_load_btn = QPushButton("불러오기")
        self.anchor_save_btn.clicked.connect(self._handle_anchor_save)
        self.anchor_load_btn.clicked.connect(self._handle_anchor_load)

        anchor_box = QGroupBox("창 위치 관리")
        anchor_layout = QHBoxLayout()
        anchor_layout.addWidget(self.anchor_summary_label, 1)
        anchor_layout.addWidget(self.anchor_save_btn)
        anchor_layout.addWidget(self.anchor_load_btn)
        anchor_box.setLayout(anchor_layout)
        root_layout.addWidget(anchor_box)

        # 다른 유저 감지
        other_group = QGroupBox("다른 유저 감지")
        other_layout = QGridLayout()
        other_layout.setHorizontalSpacing(8)
        other_layout.setVerticalSpacing(6)

        self.other_toggle_button = QPushButton("시작")
        self.other_toggle_button.clicked.connect(self._handle_other_toggle)

        other_top_row = QHBoxLayout()
        other_top_row.setContentsMargins(0, 0, 0, 0)
        other_top_row.setSpacing(6)
        other_top_row.addWidget(self.other_toggle_button)

        self.other_roi_button = QPushButton("미니맵 범위 설정")
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

        count_row = QHBoxLayout()
        count_row.setContentsMargins(0, 0, 0, 0)
        count_row.setSpacing(6)
        count_label = QLabel("최소 인원")
        count_label.setFixedWidth(80)
        self.other_min_count_spin = QSpinBox()
        self.other_min_count_spin.setRange(1, 50)
        self.other_min_count_spin.setFixedWidth(60)
        count_row.addWidget(count_label)
        count_row.addWidget(self.other_min_count_spin)
        count_row.addStretch(1)
        count_container = QWidget()
        count_container.setLayout(count_row)
        other_layout.addWidget(count_container, 1, 0, 1, 3)

        interval_row = QHBoxLayout()
        interval_row.setContentsMargins(0, 0, 0, 0)
        interval_row.setSpacing(6)
        interval_label = QLabel("탐지 주기(초)")
        interval_label.setFixedWidth(80)
        self.other_interval_spin = QDoubleSpinBox()
        self.other_interval_spin.setRange(0.01, 10.0)
        self.other_interval_spin.setSingleStep(0.01)
        self.other_interval_spin.setDecimals(2)
        self.other_interval_spin.setFixedWidth(60)
        interval_row.addWidget(interval_label)
        interval_row.addWidget(self.other_interval_spin)
        interval_row.addStretch(1)
        interval_container = QWidget()
        interval_container.setLayout(interval_row)
        other_layout.addWidget(interval_container, 2, 0, 1, 3)

        self.other_status_label = QLabel("감지 대기 중")
        other_layout.addWidget(self.other_status_label, 3, 0, 1, 3)

        other_group.setLayout(other_layout)
        root_layout.addWidget(other_group)

        # 채팅 감지
        chat_group = QGroupBox("채팅창 감지")
        chat_layout = QGridLayout()
        chat_layout.setHorizontalSpacing(8)
        chat_layout.setVerticalSpacing(6)

        self.chat_roi_button = QPushButton("범위 설정")
        self.chat_roi_button.clicked.connect(self._handle_chat_roi_select)

        chat_interval_row = QHBoxLayout()
        chat_interval_row.setContentsMargins(0, 0, 0, 0)
        chat_interval_row.setSpacing(6)
        chat_interval_row.addWidget(self.chat_roi_button)
        chat_interval_label = QLabel("탐지 주기(초)")
        chat_interval_label.setFixedWidth(80)
        self.chat_interval_spin = QDoubleSpinBox()
        self.chat_interval_spin.setRange(CHAT_INTERVAL_MIN, CHAT_INTERVAL_MAX)
        self.chat_interval_spin.setSingleStep(0.1)
        self.chat_interval_spin.setDecimals(1)
        self.chat_interval_spin.setFixedWidth(60)
        chat_interval_row.addWidget(chat_interval_label)
        chat_interval_row.addWidget(self.chat_interval_spin)
        chat_interval_row.addStretch(1)
        chat_interval_container = QWidget()
        chat_interval_container.setLayout(chat_interval_row)
        chat_layout.addWidget(chat_interval_container, 0, 0, 1, 3)

        self.whisper_toggle_button = QPushButton("시작")
        self.whisper_toggle_button.clicked.connect(self._handle_whisper_toggle)
        self.whisper_color_edit = QLineEdit()
        self.whisper_color_edit.setMaxLength(6)
        self.whisper_color_edit.setFixedWidth(70)
        self.whisper_status_label = QLabel("미감지")
        whisper_row = QHBoxLayout()
        whisper_row.setContentsMargins(0, 0, 0, 0)
        whisper_row.setSpacing(6)
        whisper_row.addWidget(self.whisper_toggle_button)
        whisper_label = QLabel("귓속말 감지")
        whisper_label.setFixedWidth(80)
        whisper_row.addWidget(whisper_label)
        whisper_row.addWidget(self.whisper_color_edit)
        whisper_row.addWidget(self.whisper_status_label)
        whisper_container = QWidget()
        whisper_container.setLayout(whisper_row)
        chat_layout.addWidget(whisper_container, 1, 0, 1, 3)

        self.friend_toggle_button = QPushButton("시작")
        self.friend_toggle_button.clicked.connect(self._handle_friend_toggle)
        self.friend_color_edit = QLineEdit()
        self.friend_color_edit.setMaxLength(6)
        self.friend_color_edit.setFixedWidth(70)
        self.friend_status_label = QLabel("미감지")
        friend_row = QHBoxLayout()
        friend_row.setContentsMargins(0, 0, 0, 0)
        friend_row.setSpacing(6)
        friend_row.addWidget(self.friend_toggle_button)
        friend_label = QLabel("친구채팅 감지")
        friend_label.setFixedWidth(80)
        friend_row.addWidget(friend_label)
        friend_row.addWidget(self.friend_color_edit)
        friend_row.addWidget(self.friend_status_label)
        friend_container = QWidget()
        friend_container.setLayout(friend_row)
        chat_layout.addWidget(friend_container, 2, 0, 1, 3)

        chat_group.setLayout(chat_layout)
        root_layout.addWidget(chat_group)

        # 경험치 측정
        exp_group = QGroupBox("경험치 측정")
        exp_layout = QGridLayout()

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

        self.exp_roi_button = QPushButton("범위 설정")
        self.exp_roi_button.clicked.connect(self._handle_exp_roi_select)
        exp_layout.addWidget(self.exp_roi_button, 1, 0)

        self.exp_test_button = QPushButton("인식 테스트")
        self.exp_test_button.clicked.connect(self._handle_exp_test)
        exp_layout.addWidget(self.exp_test_button, 1, 1)

        self.exp_roi_label = QLabel("범위가 지정되지 않았습니다.")
        exp_layout.addWidget(self.exp_roi_label, 2, 0, 1, 4)

        self.exp_card = QFrame()
        self.exp_card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(self.exp_card)
        self.exp_summary_label = QLabel("측정을 시작하세요.")
        self.exp_gain_label = QLabel("분당 데이터 없음")
        self.exp_prediction_label = QLabel("예측 데이터 없음")
        self.exp_prediction_label.setWordWrap(True)
        card_layout.addWidget(self.exp_summary_label)
        card_layout.addWidget(self.exp_gain_label)
        card_layout.addWidget(self.exp_prediction_label)
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
            self.chat_roi_button,
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

    def _normalize_chat_color_field(self, line_edit: QLineEdit, default: str) -> str:
        code = normalize_hex_color(line_edit.text()) or default
        if len(code) != 6:
            code = default
        line_edit.setText(code)
        return code

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
        color = self._normalize_chat_color_field(self.whisper_color_edit, DEFAULT_WHISPER_COLOR)
        self.config.chat.whisper.hex_color = color
        self.config.chat.whisper.enabled = not self.config.chat.whisper.enabled
        self.whisper_toggle_button.setText("중지" if self.config.chat.whisper.enabled else "시작")
        self._update_chat_status_label("whisper", False)
        self._apply_config_to_workers()
        self._save_config()

    def _handle_friend_toggle(self) -> None:
        color = self._normalize_chat_color_field(self.friend_color_edit, DEFAULT_FRIEND_COLOR)
        self.config.chat.friend.hex_color = color
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
        elif channel == "friend":
            label = self.friend_status_label
        else:
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
        if len(self.exp_history) < EXP_REGRESSION_MIN_SAMPLES:
            return 0.0
        base_time = self.exp_history[0].timestamp
        xs = [snap.timestamp - base_time for snap in self.exp_history]
        ys = [getattr(snap, attr) for snap in self.exp_history]
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)
        if denominator <= 0:
            return 0.0
        slope = numerator / denominator
        if slope < 0:
            return 0.0
        return slope

    def _snapshot_seconds_ago(self, seconds: int) -> Optional[ExpSnapshot]:
        if not self.exp_history or seconds <= 0:
            return None
        target_time = self.exp_history[-1].timestamp - seconds
        if target_time <= self.exp_history[0].timestamp:
            return self.exp_history[0]
        closest = min(self.exp_history, key=lambda snap: abs(snap.timestamp - target_time))
        return closest

    def _update_exp_labels(self) -> None:
        if not self.exp_history:
            return
        first = self.exp_history[0]
        latest = self.exp_history[-1]
        measurement_elapsed = max(latest.timestamp - first.timestamp, 0.0)
        gained_amount = int(latest.total_amount)
        gained_percent = latest.total_percent

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

        rate_per_sec_amount = self._compute_regression_rate("total_amount")
        rate_per_sec_percent = self._compute_regression_rate("total_percent")

        if rate_per_sec_amount <= 0 and elapsed_for_rate > 0:
            rate_per_sec_amount = gained_amount / elapsed_for_rate
        if rate_per_sec_percent <= 0 and elapsed_for_rate > 0:
            rate_per_sec_percent = gained_percent / elapsed_for_rate

        predictions = []
        for minutes in (1, 5, 10, 60):
            amount_projection = rate_per_sec_amount * (minutes * 60)
            percent_projection = rate_per_sec_percent * (minutes * 60)
            predictions.append(
                f"{minutes}분 예상: +{int(amount_projection)} | +{percent_projection:.2f}%"
            )

        if rate_per_sec_percent > 0:
            remaining_percent = max(0.0, 100.0 - latest.percent)
            eta_seconds = remaining_percent / rate_per_sec_percent
            eta_minutes = eta_seconds / 60.0
            eta_text = f"100%까지 예상 {eta_minutes:.1f}분"
        else:
            eta_text = "100% 예측 불가"

        predictions.append(eta_text)
        self.exp_prediction_label.setText("\n".join(predictions))

    def _capture_region(self, region: Dict[str, int]) -> Optional[np.ndarray]:
        try:
            with mss.mss() as sct:
                frame = sct.grab(region)
        except Exception:
            return None
        return np.array(frame)[:, :, :3]

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
        self.config.chat.whisper.hex_color = self._normalize_chat_color_field(self.whisper_color_edit, DEFAULT_WHISPER_COLOR)
        self.config.chat.friend.hex_color = self._normalize_chat_color_field(self.friend_color_edit, DEFAULT_FRIEND_COLOR)
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


if __name__ == "__main__":
    main()
