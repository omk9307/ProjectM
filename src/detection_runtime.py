"""공용 실시간 탐지 지원 도구 모음.

Learning 탭과 Hunt 탭에서 공유할 화면 영역 지정, 탐지 팝업,
백그라운드 탐지 스레드를 한 곳에 모아둔다.
"""

from __future__ import annotations

import os
import math
import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import mss
import numpy as np
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPen, QColor, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QSlider,
    QVBoxLayout,
)
from ultralytics import YOLO

from nickname_detection import NicknameDetector
from direction_detection import DirectionDetector
from capture_manager import get_capture_manager


MIN_MONSTER_BOX_SIZE = 30  # 탐지된 몬스터로 인정할 최소 크기(px)
NAMEPLATE_TRACK_MATCH_RADIUS = 120.0  # 이름표 트래킹과 YOLO 박스를 연결할 최대 거리(px)
NAMEPLATE_NICKNAME_OVERLAP_THRESHOLD = 0.5  # 닉네임 영역과 겹치는 비율이 이 이상이면 이름표 후보 제외
NAMEPLATE_NICKNAME_MARGIN = 6.0  # 닉네임 박스에 적용할 여유 마진(px)


__all__ = ["ScreenSnipper", "DetectionPopup", "DetectionThread"]


class ScreenSnipper(QDialog):
    """전체 화면을 캡처한 정지 화면 위에서 영역을 지정하도록 돕는 도구."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self.virtual_origin = QPoint(0, 0)
        self.screenshot = self._capture_virtual_desktop()
        if self.screenshot.isNull():
            raise RuntimeError("화면 캡처에 실패했습니다.")

        geometry = QRect(self.virtual_origin, self.screenshot.size())
        self.setGeometry(geometry)

        self.begin = QPoint()
        self.end = QPoint()
        self.is_selecting = False

    def _capture_virtual_desktop(self) -> QPixmap:
        pixmap: Optional[QPixmap] = None
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                shot = sct.grab(monitor)
            img = QImage(shot.rgb, shot.width, shot.height, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(img.copy())
            self.virtual_origin = QPoint(monitor.get('left', 0), monitor.get('top', 0))
        except Exception:
            pixmap = None

        if pixmap is not None and not pixmap.isNull():
            return pixmap

        screens = QApplication.screens()
        if not screens:
            return QPixmap()

        virtual_rect = screens[0].geometry()
        for screen in screens[1:]:
            virtual_rect = virtual_rect.united(screen.geometry())

        self.virtual_origin = virtual_rect.topLeft()
        snapshot = QPixmap(virtual_rect.size())
        snapshot.fill(Qt.GlobalColor.transparent)
        painter = QPainter(snapshot)
        for screen in screens:
            geo = screen.geometry()
            offset = geo.topLeft() - self.virtual_origin
            painter.drawPixmap(offset, screen.grabWindow(0))
        painter.end()
        return snapshot

    def paintEvent(self, event):  # noqa: N802 (Qt 시그니처 유지)
        painter = QPainter(self)
        painter.drawPixmap(QPoint(0, 0), self.screenshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if self.is_selecting:
            selected_rect = QRect(self.begin, self.end).normalized()
            painter.drawPixmap(selected_rect, self.screenshot, selected_rect)
            painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine))
            painter.drawRect(selected_rect)

    def mousePressEvent(self, event):  # noqa: N802
        point = event.position().toPoint()
        self.begin = point
        self.end = point
        self.is_selecting = True
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self.is_selecting:
            return
        self.end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if not self.is_selecting:
            return
        self.is_selecting = False
        self.end = event.position().toPoint()
        rect = QRect(self.begin, self.end).normalized()
        if rect.width() > 5 and rect.height() > 5:
            self.accept()
        else:
            self.reject()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()

    def get_roi(self) -> QRect:
        rect = QRect(self.begin, self.end).normalized()
        return rect.translated(self.virtual_origin)


class DetectionPopup(QDialog):
    """실시간 탐지 화면을 표시하고 크기 조절이 가능한 팝업 창."""

    closed = pyqtSignal()
    scale_changed = pyqtSignal(int)

    def __init__(self, initial_scale: int = 50, parent=None):
        super().__init__(parent)
        self.setWindowTitle("탐지 팝업")
        self.setMinimumSize(320, 240)
        self.original_frame_size: Optional[QSize] = None

        layout = QVBoxLayout(self)

        self.view_label = QLabel("탐지 시작 대기 중...")
        self.view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_label.setStyleSheet("background-color: black; color: white;")
        layout.addWidget(self.view_label, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(20, 80)
        self.slider.setValue(initial_scale)
        self.slider.valueChanged.connect(self.on_scale_changed)
        layout.addWidget(self.slider)

    def on_scale_changed(self, value: int) -> None:
        self.scale_changed.emit(value)
        if self.original_frame_size:
            new_width = int(self.original_frame_size.width() * (value / 100))
            new_height = int(self.original_frame_size.height() * (value / 100))
            self.resize(
                max(new_width, self.minimumWidth()),
                max(new_height, self.minimumHeight()),
            )

    def update_frame(self, q_image: QImage) -> None:
        if self.original_frame_size is None:
            self.original_frame_size = q_image.size()
            self.on_scale_changed(self.slider.value())

        scaled_pixmap = QPixmap.fromImage(q_image).scaled(
            self.view_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.view_label.setPixmap(scaled_pixmap)

    def set_waiting_message(self) -> None:
        self.view_label.setText("탐지 시작 대기 중...")
        self.view_label.setPixmap(QPixmap())

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)


class DetectionThread(QThread):
    frame_ready = pyqtSignal(QImage)
    detection_logged = pyqtSignal(list)
    detections_ready = pyqtSignal(dict)

    def __init__(
        self,
        model_path: str,
        capture_region: dict,
        target_class_indices: Iterable[int],
        conf_char: float,
        conf_monster: float,
        char_class_index: int,
        is_debug_mode: bool = False,
        nickname_detector: Optional[NicknameDetector] = None,
        direction_detector: Optional[DirectionDetector] = None,
        show_nickname_overlay: bool = True,
        show_direction_overlay: bool = True,
        show_nickname_range_overlay: bool = False,
        nameplate_config: Optional[dict] = None,
        nameplate_templates: Optional[Dict[int, List[dict]]] = None,
        nameplate_thresholds: Optional[Dict[int, float]] = None,
        show_nameplate_overlay: bool = True,
        show_monster_confidence: bool = True,
        screen_output_enabled: bool = True,
        nms_iou: float = 0.45,
        max_det: int = 100,
        allowed_subregions: Optional[Iterable[dict]] = None,
        monster_confidence_overrides: Optional[Dict[int, float]] = None,
    ) -> None:
        super().__init__()
        self.model_path = model_path
        self.capture_region = capture_region
        self.target_class_indices = list(target_class_indices)
        self.conf_char = conf_char
        self.conf_monster = conf_monster
        self.char_class_index = (
            int(char_class_index)
            if char_class_index is not None and int(char_class_index) >= 0
            else -1
        )
        self.is_debug_mode = is_debug_mode
        self.screen_output_enabled = bool(screen_output_enabled)
        self.nickname_detector = nickname_detector
        self.direction_detector = direction_detector
        self.show_nickname_overlay = bool(show_nickname_overlay)
        self.show_direction_overlay = bool(show_direction_overlay)
        self.show_nickname_range_overlay = bool(show_nickname_range_overlay)
        self.show_nameplate_overlay = bool(show_nameplate_overlay)
        self.show_monster_confidence = bool(show_monster_confidence)
        self.is_running = True
        self.min_monster_box_size = MIN_MONSTER_BOX_SIZE
        self.current_authority: str = "map"
        self.current_facing: Optional[str] = None
        self.nms_iou = max(0.05, min(0.95, float(nms_iou)))
        try:
            self.max_det = max(1, int(max_det))
        except (TypeError, ValueError):
            self.max_det = 100

        self.monster_confidence_overrides: Dict[int, float] = {}
        if monster_confidence_overrides:
            for key, value in monster_confidence_overrides.items():
                try:
                    index = int(key)
                    threshold = float(value)
                except (TypeError, ValueError):
                    continue
                if index < 0:
                    continue
                self.monster_confidence_overrides[index] = max(0.05, min(0.95, threshold))

        self.allowed_subregions: List[dict] = []
        if allowed_subregions:
            for region in allowed_subregions:
                if not isinstance(region, dict):
                    continue
                try:
                    rel_top = int(region['top'])
                    rel_left = int(region['left'])
                    rel_width = int(region['width'])
                    rel_height = int(region['height'])
                except (KeyError, TypeError, ValueError):
                    continue
                if rel_width <= 0 or rel_height <= 0:
                    continue
                self.allowed_subregions.append(
                    {
                        'top': rel_top,
                        'left': rel_left,
                        'width': rel_width,
                        'height': rel_height,
                    }
                )

        self._region_mask: Optional[np.ndarray] = None
        if self.allowed_subregions:
            try:
                mask_height = int(self.capture_region['height'])
                mask_width = int(self.capture_region['width'])
            except (KeyError, TypeError, ValueError):
                mask_height = 0
                mask_width = 0
            if mask_height > 0 and mask_width > 0:
                mask = np.zeros((mask_height, mask_width), dtype=bool)
                for sub in self.allowed_subregions:
                    top = max(0, min(mask_height, sub['top']))
                    left = max(0, min(mask_width, sub['left']))
                    bottom = max(top, min(mask_height, sub['top'] + sub['height']))
                    right = max(left, min(mask_width, sub['left'] + sub['width']))
                    if top >= bottom or left >= right:
                        continue
                    mask[top:bottom, left:right] = True
                if mask.any():
                    self._region_mask = mask

        self.nameplate_config = nameplate_config if isinstance(nameplate_config, dict) else {}
        roi_cfg = self.nameplate_config.get('roi', {}) if isinstance(self.nameplate_config.get('roi'), dict) else {}
        self.nameplate_roi_width = max(4, int(roi_cfg.get('width', 135) or 135))
        self.nameplate_roi_height = max(4, int(roi_cfg.get('height', 65) or 65))
        self.nameplate_roi_offset_x = int(roi_cfg.get('offset_x', 0) or 0)
        self.nameplate_roi_offset_y = int(roi_cfg.get('offset_y', 0) or 0)
        try:
            self.nameplate_match_threshold = float(self.nameplate_config.get('match_threshold', 0.60) or 0.60)
        except (TypeError, ValueError):
            self.nameplate_match_threshold = 0.60
        try:
            track_grace_raw = float(self.nameplate_config.get('track_missing_grace_sec', 0.12))
        except (TypeError, ValueError):
            track_grace_raw = 0.12
        self.nameplate_track_missing_grace = max(0.0, min(2.0, track_grace_raw))
        try:
            track_hold_raw = float(self.nameplate_config.get('track_max_hold_sec', 2.0))
        except (TypeError, ValueError):
            track_hold_raw = 2.0
        self.nameplate_track_max_hold = max(0.0, min(5.0, track_hold_raw))
        self.nameplate_thresholds: Dict[int, float] = {}
        if nameplate_thresholds:
            for key, value in nameplate_thresholds.items():
                try:
                    idx = int(key)
                    thr = float(value)
                except (TypeError, ValueError):
                    continue
                self.nameplate_thresholds[idx] = max(0.10, min(0.99, thr))
        self._nameplate_template_images: Dict[int, List[dict]] = {}
        if nameplate_templates:
            prepared_templates = self._prepare_nameplate_templates(nameplate_templates)
            if prepared_templates:
                self._nameplate_template_images = prepared_templates
        self.nameplate_enabled = bool(
            self.nameplate_config.get('enabled', False)
            and self._nameplate_template_images
        )
        self._nameplate_tracks: Dict[int, dict] = {}
        self._next_nameplate_track_id = 1
        self._box_uid_counter = 1

        # FPS 계산 변수
        self.fps = 0.0
        self.frame_count = 0
        self.start_time = time.time()
        
        # [추가] 성능 분석을 위한 통계 변수
        self.perf_stats = {
            "nickname_ms": 0.0,
            "direction_ms": 0.0,
            "nameplate_ms": 0.0,
            "yolo_ms": 0.0,
            "yolo_speed_preprocess_ms": 0.0,
            "yolo_speed_inference_ms": 0.0,
            "yolo_speed_postprocess_ms": 0.0,
            "total_ms": 0.0,
            "capture_ms": 0.0,
            "preprocess_ms": 0.0,
            "post_ms": 0.0,
            "render_ms": 0.0,
            "emit_ms": 0.0,
        }

        # 캡처-추론 병렬화를 위한 공유 상태
        self._frame_lock = threading.Lock()
        self._frame_condition = threading.Condition(self._frame_lock)
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_capture_ms: float = 0.0
        self._frame_version: int = 0
        self._capture_thread_obj: Optional[threading.Thread] = None
        self._capture_stop_event = threading.Event()

    def _monster_threshold_for_class(self, class_id: int) -> float:
        return self.monster_confidence_overrides.get(class_id, self.conf_monster)

    def _minimum_monster_confidence(self) -> float:
        if not self.monster_confidence_overrides:
            return self.conf_monster
        min_override = min(self.monster_confidence_overrides.values(), default=self.conf_monster)
        return min(self.conf_monster, min_override)

    def set_authority(self, owner: Optional[str]) -> None:
        if isinstance(owner, str):
            self.current_authority = owner

    def set_facing(self, side: Optional[str]) -> None:
        if side in ("left", "right"):
            self.current_facing = side
        else:
            self.current_facing = None

    def set_screen_output_enabled(self, enabled: bool) -> None:
        self.screen_output_enabled = bool(enabled)

    def run(self) -> None:  # noqa: D401
        consumer_name = f"detection:{id(self)}"
        manager = get_capture_manager()
        manager.register_region(consumer_name, self.capture_region)
        try:
            self._start_capture_worker(manager, consumer_name)
            last_processed_version = -1
            model = YOLO(self.model_path)
            use_char_class = self.char_class_index >= 0
            monster_base_conf = self._minimum_monster_confidence()
            low_conf = (
                min(self.conf_char, monster_base_conf)
                if use_char_class
                else monster_base_conf
            )
            # 클래스 ID별 색상을 저장할 딕셔너리
            class_color_map = {}

            while self.is_running:
                loop_start_time = time.perf_counter()

                self.frame_count += 1
                current_time = time.time()
                elapsed_time = current_time - self.start_time
                if elapsed_time >= 1.0:
                    self.fps = self.frame_count / elapsed_time
                    self.frame_count = 0
                    self.start_time = current_time

                frame: Optional[np.ndarray] = None
                capture_ms = 0.0
                with self._frame_condition:
                    has_frame = self._frame_condition.wait_for(
                        lambda: self._frame_version != last_processed_version or not self.is_running,
                        timeout=1.0,
                    )
                    if has_frame and self._frame_version != last_processed_version and self._latest_frame is not None:
                        frame = self._latest_frame
                        capture_ms = self._latest_capture_ms
                        last_processed_version = self._frame_version

                if frame is None:
                    fallback_start = time.perf_counter()
                    frame = manager.get_frame(consumer_name, timeout=1.0)
                    fallback_end = time.perf_counter()
                    if frame is None:
                        continue
                    capture_ms = (fallback_end - fallback_start) * 1000

                preprocess_start = time.perf_counter()
                if self._region_mask is not None:
                    if (
                        self._region_mask.shape[0] == frame.shape[0]
                        and self._region_mask.shape[1] == frame.shape[1]
                    ):
                        frame = frame.copy()
                        frame[~self._region_mask] = 0
                preprocess_end = time.perf_counter()

                now = time.perf_counter()
                effective_capture_ms = (now - loop_start_time) * 1000 - (preprocess_end - preprocess_start) * 1000
                if effective_capture_ms < 0:
                    effective_capture_ms = capture_ms

                self.perf_stats["capture_ms"] = float(effective_capture_ms)
                self.perf_stats["preprocess_ms"] = (preprocess_end - preprocess_start) * 1000

                nick_start = time.perf_counter()
                nickname_info = None
                nickname_search_region = None
                if self.nickname_detector is not None:
                    try:
                        nickname_info = self.nickname_detector.detect(frame)
                        if self.show_nickname_range_overlay:
                            nickname_search_region = self.nickname_detector.get_last_search_region()
                    except Exception as exc:
                        if self.is_debug_mode:
                            print(f"[DetectionThread] 닉네임 탐지 오류: {exc}")
                        nickname_info = None
                        try:
                            self.nickname_detector.notify_missed()
                        except Exception:
                            pass
                        if self.show_nickname_range_overlay:
                            try:
                                nickname_search_region = self.nickname_detector.get_last_search_region()
                            except Exception:
                                nickname_search_region = None
                nick_end = time.perf_counter()
                self.perf_stats["nickname_ms"] = (nick_end - nick_start) * 1000

                direction_start = time.perf_counter()
                direction_info = None
                if self.direction_detector is not None:
                    try:
                        if nickname_info is not None:
                            direction_info = self.direction_detector.detect(frame, nickname_info)
                        else:
                            self.direction_detector.notify_missed()
                    except Exception as exc:
                        if self.is_debug_mode:
                            print(f"[DetectionThread] 방향 탐지 오류: {exc}")
                        direction_info = None
                direction_end = time.perf_counter()
                self.perf_stats["direction_ms"] = (direction_end - direction_start) * 1000

                yolo_start = time.perf_counter()
                results = model(
                    frame,
                    conf=low_conf,
                    classes=self.target_class_indices,
                    iou=self.nms_iou,
                    max_det=self.max_det,
                    verbose=False,
                )
                yolo_end = time.perf_counter()
                self.perf_stats["yolo_ms"] = (yolo_end - yolo_start) * 1000

                result = results[0]
                speed_info = getattr(result, "speed", None)
                if isinstance(speed_info, dict):
                    try:
                        self.perf_stats["yolo_speed_preprocess_ms"] = float(
                            speed_info.get("preprocess", 0.0)
                        )
                    except (TypeError, ValueError):
                        self.perf_stats["yolo_speed_preprocess_ms"] = 0.0
                    try:
                        self.perf_stats["yolo_speed_inference_ms"] = float(
                            speed_info.get("inference", 0.0)
                        )
                    except (TypeError, ValueError):
                        self.perf_stats["yolo_speed_inference_ms"] = 0.0
                    try:
                        self.perf_stats["yolo_speed_postprocess_ms"] = float(
                            speed_info.get("postprocess", 0.0)
                        )
                    except (TypeError, ValueError):
                        self.perf_stats["yolo_speed_postprocess_ms"] = 0.0
                else:
                    self.perf_stats["yolo_speed_preprocess_ms"] = 0.0
                    self.perf_stats["yolo_speed_inference_ms"] = 0.0
                    self.perf_stats["yolo_speed_postprocess_ms"] = 0.0

                post_start = time.perf_counter()

                if len(result.boxes) > 0 and use_char_class:
                    char_indices_with_conf: List[tuple[int, float]] = []
                    other_indices: List[int] = []
                    for i, box in enumerate(result.boxes):
                        cls_id = int(box.cls)
                        conf = float(box.conf.item())
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        width = float(x2 - x1)
                        height = float(y2 - y1)
                        if cls_id == self.char_class_index:
                            if conf >= self.conf_char:
                                char_indices_with_conf.append((i, conf))
                        elif conf >= self._monster_threshold_for_class(cls_id):
                            if (
                                width >= self.min_monster_box_size
                                and height >= self.min_monster_box_size
                            ):
                                other_indices.append(i)
                    final_indices: List[int] = []
                    if char_indices_with_conf and nickname_info is None:
                        best_char_index = max(
                            char_indices_with_conf, key=lambda item: item[1]
                        )[0]
                        final_indices.append(best_char_index)
                    final_indices.extend(other_indices)
                    if final_indices:
                        result = result[final_indices]
                    else:
                        result = result[:0]

                payload: Dict[str, object] = {
                    "timestamp": time.time(),
                    "characters": [],
                    "monsters": [],
                }
                payload["nickname"] = nickname_info
                if self.show_nickname_range_overlay and nickname_search_region:
                    payload["nickname_search"] = nickname_search_region
                payload["direction"] = direction_info

                annotated_frame: Optional[np.ndarray] = None
                if self.screen_output_enabled:
                    annotated_frame = frame
                    if not annotated_frame.flags.writeable:
                        annotated_frame = annotated_frame.copy()
                draw_enabled = annotated_frame is not None

                frame_now = float(payload["timestamp"])
                track_events: List[dict] = []
                if not self.nameplate_enabled and self._nameplate_tracks:
                    self._nameplate_tracks.clear()
                for track in self._nameplate_tracks.values():
                    track['matched_this_frame'] = False
                    track['nameplate_confirmed_this_frame'] = False
                    track['probe_requested'] = False

                boxes_for_payload: List[Dict[str, float]] = []
                if len(result.boxes) > 0:
                    for box in result.boxes:
                        x1, y1, x2, y2 = [int(coord) for coord in box.xyxy[0].tolist()]
                        class_id = int(box.cls)
                        width_px = float(x2 - x1)
                        height_px = float(y2 - y1)
                        if (
                            class_id != self.char_class_index
                            and (
                                width_px < self.min_monster_box_size
                                or height_px < self.min_monster_box_size
                            )
                        ):
                            continue
                        item = {
                            "x": float(x1),
                            "y": float(y1),
                            "width": width_px,
                            "height": height_px,
                            "score": float(box.conf.item()),
                            "class_id": class_id,
                            "class_name": model.names[class_id],
                            "source": "yolo",
                            "box_uid": self._allocate_box_uid(),
                            "track_id": None,
                        }

                        if class_id not in class_color_map:
                            class_color_map[class_id] = np.random.randint(0, 256, size=3).tolist()
                        color = class_color_map[class_id]

                        if annotated_frame is not None:
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)

                            should_draw_confidence = True
                            if class_id != self.char_class_index and not self.show_monster_confidence:
                                should_draw_confidence = False

                            if should_draw_confidence:
                                label = f"{item['score']:.2f}"

                                (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                                text_bg_y2 = y1 - 5
                                text_bg_y1 = text_bg_y2 - h - 5
                                if text_bg_y1 < 0:
                                    text_bg_y1 = y1 + 5
                                    text_bg_y2 = text_bg_y1 + h + 5

                                cv2.rectangle(annotated_frame, (x1, text_bg_y1), (x1 + w, text_bg_y2), color, -1)

                                text_y = y1 - 10 if text_bg_y1 < y1 else y1 + h + 5
                                cv2.putText(
                                    annotated_frame,
                                    label,
                                    (x1 + 2, text_y),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5,
                                    (255, 255, 255),
                                    2,
                                )

                        if class_id != self.char_class_index and self._nameplate_tracks:
                            center_x, center_y = self._box_center(item)
                            matched_track = self._find_nameplate_track(class_id, center_x, center_y)
                            if matched_track is not None:
                                item['track_id'] = matched_track['id']
                                matched_track['matched_this_frame'] = True
                                matched_track['active'] = True
                                matched_track['last_yolo_ts'] = frame_now
                                matched_track['box'] = {
                                    'x': item['x'],
                                    'y': item['y'],
                                    'width': item['width'],
                                    'height': item['height'],
                                }
                                self._update_track_center(matched_track, item)

                        boxes_for_payload.append(item)

                track_probe_items: List[Dict[str, float]] = []
                for track in self._nameplate_tracks.values():
                    if not track.get('active', True):
                        continue
                    if track.get('matched_this_frame'):
                        continue
                    track['probe_requested'] = True
                    track_probe_items.append(self._prepare_track_probe_item(track))

                nick_box_data = nickname_info.get('nickname_box') if isinstance(nickname_info, dict) else None

                nameplate_input_items: List[Dict[str, float]] = []
                nameplate_input_items.extend(boxes_for_payload)
                nameplate_input_items.extend(track_probe_items)

                if nameplate_input_items:
                    nameplate_start = time.perf_counter()
                    nameplate_matches = self._detect_nameplates(
                        frame,
                        nameplate_input_items,
                        nickname_box=nick_box_data,
                    )
                    nameplate_end = time.perf_counter()
                    self.perf_stats["nameplate_ms"] = (nameplate_end - nameplate_start) * 1000
                else:
                    nameplate_matches = []
                    self.perf_stats["nameplate_ms"] = 0.0

                synthetic_monsters = self._process_nameplate_tracking(
                    frame_now,
                    boxes_for_payload,
                    track_probe_items,
                    track_events,
                )

                for item in boxes_for_payload:
                    if item["class_id"] == self.char_class_index:
                        payload["characters"].append(item)
                    else:
                        payload["monsters"].append(item)

                if synthetic_monsters:
                    payload.setdefault("monsters", []).extend(synthetic_monsters)

                if track_events:
                    payload["nameplate_track_events"] = track_events

                payload["nameplates"] = nameplate_matches

                if self.is_debug_mode:
                    log_messages: List[str] = []
                    boxes = result.boxes
                    timestamp = time.strftime("%H:%M:%S")
                    if boxes is not None and len(boxes) > 0:
                        log_messages.append(
                            f"[{timestamp}] 탐지된 객체: {len(boxes)}개"
                        )
                        for box in boxes:
                            log_messages.append(
                                f"  - {model.names[int(box.cls)]} (신뢰도: {box.conf.item():.2f})"
                            )
                    else:
                        log_messages.append(f"[{timestamp}] 탐색 완료. 객체 없음.")
                    self.detection_logged.emit(log_messages)
                if draw_enabled and self.show_nickname_overlay and nick_box_data:
                    x1, y1 = int(nick_box_data.get('x', 0)), int(nick_box_data.get('y', 0))
                    x2 = int(x1 + nick_box_data.get('width', 0))
                    y2 = int(y1 + nick_box_data.get('height', 0))
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 255), 2)

                if draw_enabled and self.show_nickname_range_overlay and nickname_search_region:
                    try:
                        rx = int(nickname_search_region.get('x', 0))
                        ry = int(nickname_search_region.get('y', 0))
                        rw = int(nickname_search_region.get('width', 0))
                        rh = int(nickname_search_region.get('height', 0))
                    except (AttributeError, ValueError, TypeError):
                        rx = ry = rw = rh = 0
                    if rw > 0 and rh > 0:
                        cv2.rectangle(annotated_frame, (rx, ry), (rx + rw, ry + rh), (80, 200, 255), 1)

                if draw_enabled and self.show_direction_overlay and direction_info and isinstance(direction_info, dict):
                    roi_rect = direction_info.get('roi_rect')
                    if roi_rect:
                        dx1 = int(roi_rect.get('x', 0))
                        dy1 = int(roi_rect.get('y', 0))
                        dx2 = int(dx1 + roi_rect.get('width', 0))
                        dy2 = int(dy1 + roi_rect.get('height', 0))
                        cv2.rectangle(annotated_frame, (dx1, dy1), (dx2, dy2), (128, 64, 255), 1)
                    if direction_info.get('matched') and direction_info.get('match_rect'):
                        match_rect = direction_info['match_rect']
                        mx1 = int(match_rect.get('x', 0))
                        my1 = int(match_rect.get('y', 0))
                        mx2 = int(mx1 + match_rect.get('width', 0))
                        my2 = int(my1 + match_rect.get('height', 0))
                        color = (0, 200, 255) if direction_info.get('side') == 'left' else (255, 200, 0)
                        cv2.rectangle(annotated_frame, (mx1, my1), (mx2, my2), color, 2)

                if draw_enabled and nick_box_data and self.current_facing in ("left", "right"):
                    frame_height, frame_width = annotated_frame.shape[:2]
                    x1 = int(nick_box_data.get('x', 0))
                    y1 = int(nick_box_data.get('y', 0))
                    width = int(nick_box_data.get('width', 0))
                    height = int(nick_box_data.get('height', 0))
                    mid_x = x1 + width // 2
                    arrow_length = max(20, int(width * 0.6))
                    arrow_y = y1 + height + 15
                    if arrow_y >= frame_height - 5:
                        arrow_y = max(10, y1 - 10)
                    arrow_y = int(np.clip(arrow_y, 5, frame_height - 5))
                    half_len = arrow_length // 2
                    if self.current_facing == "left":
                        start_point = (min(frame_width - 5, mid_x + half_len), arrow_y)
                        end_point = (max(5, mid_x - half_len), arrow_y)
                    else:
                        start_point = (max(5, mid_x - half_len), arrow_y)
                        end_point = (min(frame_width - 5, mid_x + half_len), arrow_y)
                    cv2.arrowedLine(
                        annotated_frame,
                        start_point,
                        end_point,
                        (0, 255, 0),
                        3,
                        tipLength=0.35,
                    )
                
                post_end = time.perf_counter()
                self.perf_stats["post_ms"] = (post_end - post_start) * 1000
                self.perf_stats["total_ms"] = (post_end - loop_start_time) * 1000

                if draw_enabled:
                    cv2.rectangle(annotated_frame, (5, 5), (180, 80), (0, 0, 0), -1)
                    fps_text = f"FPS {self.fps:.1f}"
                    cv2.putText(
                        annotated_frame,
                        fps_text,
                        (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                    )

                    authority_key = (self.current_authority or "").lower()
                    if authority_key == "hunt":
                        authority_display = "Hunt"
                        authority_color = (0, 0, 255)
                    elif authority_key == "map":
                        authority_display = "Map"
                        authority_color = (255, 0, 0)
                    elif authority_key:
                        authority_display = authority_key.title()
                        authority_color = (200, 200, 200)
                    else:
                        authority_display = "-"
                        authority_color = (200, 200, 200)

                    cv2.putText(
                        annotated_frame,
                        authority_display,
                        (12, 60),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        authority_color,
                        2,
                    )

                    render_start = time.perf_counter()
                    rgb_image = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    render_end = time.perf_counter()
                    self.perf_stats["render_ms"] = (render_end - render_start) * 1000
                else:
                    qt_image = None
                    self.perf_stats["render_ms"] = 0.0

                payload["perf"] = {
                    "fps": float(self.fps),
                    "total_ms": float(self.perf_stats["total_ms"]),
                    "yolo_ms": float(self.perf_stats["yolo_ms"]),
                    "yolo_speed_preprocess_ms": float(
                        self.perf_stats["yolo_speed_preprocess_ms"]
                    ),
                    "yolo_speed_inference_ms": float(
                        self.perf_stats["yolo_speed_inference_ms"]
                    ),
                    "yolo_speed_postprocess_ms": float(
                        self.perf_stats["yolo_speed_postprocess_ms"]
                    ),
                    "nickname_ms": float(self.perf_stats["nickname_ms"]),
                    "direction_ms": float(self.perf_stats["direction_ms"]),
                    "nameplate_ms": float(self.perf_stats["nameplate_ms"]),
                    "capture_ms": float(self.perf_stats["capture_ms"]),
                    "preprocess_ms": float(self.perf_stats["preprocess_ms"]),
                    "post_ms": float(self.perf_stats["post_ms"]),
                    "render_ms": float(self.perf_stats["render_ms"]),
                    "emit_ms": float(self.perf_stats["emit_ms"]),
                }

                emit_start = time.perf_counter()
                self.detections_ready.emit(payload)

                if qt_image is not None:
                    self.frame_ready.emit(qt_image.copy())
                emit_end = time.perf_counter()
                self.perf_stats["emit_ms"] = (emit_end - emit_start) * 1000
                self.msleep(15)
        except Exception as exc:
            print(f"탐지 스레드 오류: {exc}")
        finally:
            self._stop_capture_worker()
            manager.unregister_region(consumer_name)

    def stop(self) -> None:
        self.is_running = False
        self._capture_stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()

    def _start_capture_worker(self, manager, consumer_name: str) -> None:
        if self._capture_thread_obj and self._capture_thread_obj.is_alive():
            return
        self._capture_stop_event.clear()

        def _worker() -> None:
            while self.is_running and not self._capture_stop_event.is_set():
                start = time.perf_counter()
                frame = manager.get_frame(consumer_name, timeout=1.0)
                end = time.perf_counter()
                if frame is None:
                    continue
                with self._frame_condition:
                    self._latest_frame = frame
                    self._latest_capture_ms = (end - start) * 1000
                    self._frame_version += 1
                    self._frame_condition.notify_all()
            with self._frame_condition:
                self._frame_condition.notify_all()

        thread = threading.Thread(
            target=_worker,
            name=f"DetectionCaptureWorker-{id(self)}",
            daemon=True,
        )
        self._capture_thread_obj = thread
        thread.start()

    def _stop_capture_worker(self) -> None:
        self._capture_stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()
        if self._capture_thread_obj and self._capture_thread_obj.is_alive():
            self._capture_thread_obj.join(timeout=1.0)
        self._capture_thread_obj = None

    def _prepare_nameplate_templates(self, templates: Dict[int, List[dict]]) -> Dict[int, List[dict]]:
        prepared: Dict[int, List[dict]] = {}
        for raw_key, entries in templates.items():
            try:
                class_id = int(raw_key)
            except (TypeError, ValueError):
                continue
            if not entries:
                continue
            loaded_entries: List[dict] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                path = entry.get('path')
                if not path or not os.path.exists(path):
                    continue
                template_image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                if template_image is None:
                    continue
                if template_image.ndim == 3:
                    channels = template_image.shape[2]
                    if channels == 1:
                        template_image = template_image[:, :, 0]
                    elif channels == 3:
                        template_image = cv2.cvtColor(template_image, cv2.COLOR_BGR2GRAY)
                    elif channels == 4:
                        template_image = cv2.cvtColor(template_image, cv2.COLOR_BGRA2GRAY)
                    else:
                        continue
                elif template_image.ndim != 2:
                    continue
                loaded_entries.append({'id': entry.get('id'), 'image': template_image})
            if loaded_entries:
                prepared[class_id] = loaded_entries
        return prepared

    def _allocate_box_uid(self) -> int:
        uid = self._box_uid_counter
        self._box_uid_counter += 1
        return uid

    @staticmethod
    def _box_center(item: Dict[str, float]) -> Tuple[float, float]:
        x = float(item.get('x', 0.0))
        y = float(item.get('y', 0.0))
        width = float(item.get('width', 0.0))
        height = float(item.get('height', 0.0))
        return (x + width / 2.0, y + height / 2.0)

    def _find_nameplate_track(
        self,
        class_id: int,
        center_x: float,
        center_y: float,
    ) -> Optional[dict]:
        best_track: Optional[dict] = None
        best_distance = float('inf')
        for track in self._nameplate_tracks.values():
            if not track.get('active', True):
                continue
            if track.get('class_id') != class_id:
                continue
            track_center = track.get('center')
            if not track_center:
                continue
            distance = math.hypot(track_center[0] - center_x, track_center[1] - center_y)
            if distance < best_distance:
                best_distance = distance
                best_track = track
        if best_track and best_distance <= NAMEPLATE_TRACK_MATCH_RADIUS:
            return best_track
        return None

    @staticmethod
    def _update_track_center(track: dict, box: Dict[str, float]) -> None:
        center = DetectionThread._box_center(box)
        track['center'] = center

    def _create_nameplate_track(self, item: Dict[str, float], now: float) -> dict:
        track_id = self._next_nameplate_track_id
        self._next_nameplate_track_id += 1
        source = item.get('source')
        track = {
            'id': track_id,
            'class_id': int(item.get('class_id', -1)),
            'class_name': item.get('class_name'),
            'box': {
                'x': float(item.get('x', 0.0)),
                'y': float(item.get('y', 0.0)),
                'width': float(item.get('width', 0.0)),
                'height': float(item.get('height', 0.0)),
            },
            'center': self._box_center(item),
            'last_yolo_ts': now,
            'last_nameplate_ts': now,
            'missing_since': None,
            'active': True,
            'matched_this_frame': source != 'track',
            'nameplate_confirmed_this_frame': True,
            'created_ts': now,
        }
        self._nameplate_tracks[track_id] = track
        return track

    def _prepare_track_probe_item(self, track: dict) -> Dict[str, float]:
        box = dict(track.get('box', {}))
        box['class_id'] = track.get('class_id')
        box['class_name'] = track.get('class_name')
        box['track_id'] = track.get('id')
        box['source'] = 'track'
        box['box_uid'] = self._allocate_box_uid()
        return box

    def _build_track_event(self, track: dict, event_type: str, frame_now: float) -> dict:
        box = track.get('box', {}) or {}
        center = track.get('center')
        if not center:
            center = self._box_center(box) if box else (0.0, 0.0)
        return {
            'event': event_type,
            'track_id': track.get('id'),
            'class_id': track.get('class_id'),
            'class_name': track.get('class_name'),
            'center': {'x': float(center[0]), 'y': float(center[1])},
            'box': {
                'x': float(box.get('x', 0.0)),
                'y': float(box.get('y', 0.0)),
                'width': float(box.get('width', 0.0)),
                'height': float(box.get('height', 0.0)),
            },
            'timestamp': float(frame_now),
        }

    def _process_nameplate_tracking(
        self,
        frame_now: float,
        yolo_items: List[Dict[str, float]],
        track_probe_items: List[Dict[str, float]],
        track_events: List[dict],
    ) -> List[Dict[str, float]]:
        synthetic_entries: List[Dict[str, float]] = []
        items_to_handle: List[Dict[str, float]] = []
        items_to_handle.extend(yolo_items)
        items_to_handle.extend(track_probe_items)

        for item in items_to_handle:
            try:
                class_id = int(item.get('class_id', -1))
            except (TypeError, ValueError):
                continue
            if class_id == self.char_class_index:
                continue
            track_id = item.get('track_id')
            track = self._nameplate_tracks.get(track_id) if track_id else None
            if track is not None:
                current_box = track.get('box') or {}
                # 업데이트된 박스 좌표를 반영
                track['box'] = {
                    'x': float(item.get('x', current_box.get('x', 0.0))),
                    'y': float(item.get('y', current_box.get('y', 0.0))),
                    'width': float(item.get('width', current_box.get('width', 0.0))),
                    'height': float(item.get('height', current_box.get('height', 0.0))),
                }
                self._update_track_center(track, item)
            if item.get('nameplate_confirmed'):
                if track is None:
                    track = self._create_nameplate_track(item, frame_now)
                    item['track_id'] = track['id']
                    track_events.append(self._build_track_event(track, 'started', frame_now))
                track['last_nameplate_ts'] = frame_now
                track['missing_since'] = None
                track['nameplate_confirmed_this_frame'] = True
                track['active'] = True
                track['last_score'] = float(item.get('nameplate_score', item.get('score', 0.0)))
            else:
                if track is not None and track.get('missing_since') is None and track.get('last_nameplate_ts') is not None:
                    track['missing_since'] = frame_now

        grace_limit = self.nameplate_track_missing_grace
        hold_limit = self.nameplate_track_max_hold
        for track_id, track in list(self._nameplate_tracks.items()):
            if not track.get('active', True):
                continue
            if track.get('matched_this_frame'):
                continue
            if hold_limit > 0.0:
                reference_ts = track.get('last_yolo_ts')
                if reference_ts is None:
                    reference_ts = track.get('created_ts', track.get('last_nameplate_ts', frame_now))
                if reference_ts is None:
                    reference_ts = frame_now
                if frame_now - reference_ts > hold_limit:
                    track['active'] = False
                    track_events.append(self._build_track_event(track, 'ended', frame_now))
                    del self._nameplate_tracks[track_id]
                    continue
            last_nameplate_ts = track.get('last_nameplate_ts')
            missing_since = track.get('missing_since')
            should_emit = False
            grace_active = False
            if track.get('nameplate_confirmed_this_frame'):
                should_emit = True
            elif missing_since is not None:
                elapsed = frame_now - missing_since
                if elapsed <= grace_limit:
                    should_emit = True
                    grace_active = True
            elif last_nameplate_ts is not None:
                elapsed = frame_now - last_nameplate_ts
                if elapsed <= grace_limit:
                    should_emit = True
            if should_emit:
                box = track.get('box', {}) or {}
                synthetic_entry = {
                    'x': float(box.get('x', 0.0)),
                    'y': float(box.get('y', 0.0)),
                    'width': float(box.get('width', 0.0)),
                    'height': float(box.get('height', 0.0)),
                    'score': float(track.get('last_score', 0.99)),
                    'class_id': track.get('class_id'),
                    'class_name': track.get('class_name'),
                    'track_id': track_id,
                    'source': 'nameplate_track',
                    'nameplate_confirmed': bool(track.get('nameplate_confirmed_this_frame', False)),
                    'grace_active': grace_active,
                    'nameplate_detected': bool(track.get('nameplate_confirmed_this_frame', False)),
                    'yolo_missing': True,
                }
                synthetic_entries.append(synthetic_entry)
            else:
                if missing_since is not None:
                    elapsed = frame_now - missing_since
                    if elapsed > grace_limit:
                        track['active'] = False
                        track_events.append(self._build_track_event(track, 'ended', frame_now))
                        del self._nameplate_tracks[track_id]

        for track in self._nameplate_tracks.values():
            track['probe_requested'] = False

        return synthetic_entries

    @staticmethod
    def _normalize_box_rect(
        box: Optional[dict],
        frame_width: int,
        frame_height: int,
        margin: float = 0.0,
    ) -> Optional[Tuple[float, float, float, float]]:
        if not isinstance(box, dict):
            return None
        try:
            x = float(box.get('x', 0.0))
            y = float(box.get('y', 0.0))
            width = float(box.get('width', 0.0))
            height = float(box.get('height', 0.0))
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        left = x - margin
        top = y - margin
        right = x + width + margin
        bottom = y + height + margin
        left = max(0.0, left)
        top = max(0.0, top)
        right = min(float(frame_width), right)
        bottom = min(float(frame_height), bottom)
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    @staticmethod
    def _rect_overlap_ratios(
        rect_a: Tuple[float, float, float, float],
        rect_b: Tuple[float, float, float, float],
    ) -> Tuple[float, float]:
        left = max(rect_a[0], rect_b[0])
        top = max(rect_a[1], rect_b[1])
        right = min(rect_a[2], rect_b[2])
        bottom = min(rect_a[3], rect_b[3])
        if right <= left or bottom <= top:
            return 0.0, 0.0
        intersection_area = (right - left) * (bottom - top)
        area_a = max((rect_a[2] - rect_a[0]) * (rect_a[3] - rect_a[1]), 0.0)
        area_b = max((rect_b[2] - rect_b[0]) * (rect_b[3] - rect_b[1]), 0.0)
        if area_a <= 0.0 or area_b <= 0.0:
            return 0.0, 0.0
        return intersection_area / area_a, intersection_area / area_b

    def _box_intersects_allowed_regions(self, item: Dict[str, float]) -> bool:
        if not self.allowed_subregions:
            return True
        try:
            left = float(item.get('x', 0.0))
            top = float(item.get('y', 0.0))
            width = float(item.get('width', 0.0))
            height = float(item.get('height', 0.0))
        except (TypeError, ValueError):
            return False
        if width <= 0 or height <= 0:
            return False
        right = left + width
        bottom = top + height
        for sub in self.allowed_subregions:
            sub_left = float(sub.get('left', 0))
            sub_top = float(sub.get('top', 0))
            sub_right = sub_left + float(sub.get('width', 0))
            sub_bottom = sub_top + float(sub.get('height', 0))
            if right <= sub_left or sub_right <= left or bottom <= sub_top or sub_bottom <= top:
                continue
            return True
        return False

    def _compute_nameplate_roi(self, item: Dict[str, float], frame_width: int, frame_height: int):
        try:
            x = float(item.get('x', 0.0))
            y = float(item.get('y', 0.0))
            width = float(item.get('width', 0.0))
            height = float(item.get('height', 0.0))
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        center_x = x + width / 2.0 + float(self.nameplate_roi_offset_x)
        base_y = y + height + float(self.nameplate_roi_offset_y)
        left = int(round(center_x - self.nameplate_roi_width / 2.0))
        top = int(round(base_y))
        right = left + self.nameplate_roi_width
        bottom = top + self.nameplate_roi_height
        left = max(0, left)
        top = max(0, top)
        right = min(frame_width, right)
        bottom = min(frame_height, bottom)
        if right - left < 4 or bottom - top < 4:
            return None
        return left, top, right, bottom

    def _detect_nameplates(
        self,
        frame: np.ndarray,
        boxes: List[Dict[str, float]],
        nickname_box: Optional[dict] = None,
    ) -> List[dict]:
        if not self.nameplate_enabled or not boxes or not self._nameplate_template_images:
            return []
        frame_height, frame_width = frame.shape[:2]
        frame_gray = None
        matches: List[dict] = []
        nickname_rect = self._normalize_box_rect(
            nickname_box,
            frame_width,
            frame_height,
            margin=NAMEPLATE_NICKNAME_MARGIN,
        )
        for item in boxes:
            try:
                class_id = int(item.get('class_id', -1))
            except (TypeError, ValueError):
                continue
            templates = self._nameplate_template_images.get(class_id)
            if not templates:
                continue
            if not self._box_intersects_allowed_regions(item):
                continue
            try:
                box_x = float(item.get('x', 0.0))
                box_y = float(item.get('y', 0.0))
                box_w = float(item.get('width', 0.0))
                box_h = float(item.get('height', 0.0))
            except (TypeError, ValueError):
                continue
            roi_coords = self._compute_nameplate_roi(item, frame_width, frame_height)
            if roi_coords is None:
                continue
            left, top, right, bottom = roi_coords
            if nickname_rect is not None:
                roi_rect = (float(left), float(top), float(right), float(bottom))
                roi_ratio, nickname_ratio = self._rect_overlap_ratios(roi_rect, nickname_rect)
                if (
                    roi_ratio >= NAMEPLATE_NICKNAME_OVERLAP_THRESHOLD
                    or nickname_ratio >= NAMEPLATE_NICKNAME_OVERLAP_THRESHOLD
                ):
                    continue
            if frame_gray is None:
                frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            roi_gray = frame_gray[top:bottom, left:right]
            if roi_gray.size == 0:
                continue
            roi_bin = self._preprocess_nameplate_roi(roi_gray)
            if roi_bin is None or roi_bin.size == 0:
                continue
            best_score = -1.0
            best_template_id = None
            best_loc: Optional[Tuple[int, int]] = None
            best_shape: Optional[Tuple[int, int]] = None
            for template in templates:
                tpl_img = template.get('image')
                if tpl_img is None:
                    continue
                th, tw = tpl_img.shape[:2]
                if roi_bin.shape[0] < th or roi_bin.shape[1] < tw:
                    continue
                result = cv2.matchTemplate(roi_bin, tpl_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val > best_score:
                    best_score = float(max_val)
                    best_template_id = template.get('id')
                    best_loc = (int(max_loc[0]), int(max_loc[1]))
                    best_shape = (int(tw), int(th))
            threshold = self.nameplate_thresholds.get(class_id, self.nameplate_match_threshold)
            matched = best_score >= threshold if best_score >= 0 else False
            match_rect: Optional[Dict[str, float]] = None
            if matched and best_loc is not None and best_shape is not None:
                match_x = left + best_loc[0]
                match_y = top + best_loc[1]
                match_w, match_h = best_shape
                match_rect = {
                    'x': float(match_x),
                    'y': float(match_y),
                    'width': float(match_w),
                    'height': float(match_h),
                }
            roi_dict = {
                'x': float(left),
                'y': float(top),
                'width': float(right - left),
                'height': float(bottom - top),
            }
            box_dict = {
                'x': float(box_x),
                'y': float(box_y),
                'width': float(box_w),
                'height': float(box_h),
            }
            include_overlay_details = bool(self.show_nameplate_overlay)
            match_entry = {
                'class_id': class_id,
                'class_name': item.get('class_name'),
                'score': float(max(best_score, 0.0)),
                'threshold': float(threshold),
                'matched': bool(matched),
                'roi': roi_dict,
                'source_box': box_dict,
                'track_id': item.get('track_id'),
                'source': item.get('source', 'yolo'),
            }
            if include_overlay_details:
                match_entry['template_id'] = best_template_id
                match_entry['box_uid'] = item.get('box_uid')
                if match_rect is not None:
                    match_entry['match_rect'] = match_rect
            if matched:
                item['nameplate_confirmed'] = True
                item['nameplate_score'] = float(best_score)
                item['nameplate_roi'] = roi_dict
                if match_rect is not None:
                    item['nameplate_match_rect'] = match_rect
            if matched or self.show_nameplate_overlay:
                matches.append(match_entry)
        return matches

    @staticmethod
    def _preprocess_nameplate_roi(roi_gray: np.ndarray) -> Optional[np.ndarray]:
        if roi_gray is None or roi_gray.size == 0:
            return None
        roi = cv2.normalize(roi_gray, None, 0, 255, cv2.NORM_MINMAX)
        roi = cv2.GaussianBlur(roi, (3, 3), 0)
        roi = cv2.adaptiveThreshold(
            roi,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )
        fg_mean = np.mean(roi[roi == 255]) if np.any(roi == 255) else 255
        bg_mean = np.mean(roi[roi == 0]) if np.any(roi == 0) else 0
        if fg_mean < bg_mean:
            roi = cv2.bitwise_not(roi)
        roi = cv2.dilate(roi, np.ones((2, 2), np.uint8), iterations=1)
        return roi
