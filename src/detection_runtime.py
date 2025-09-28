"""공용 실시간 탐지 지원 도구 모음.

Learning 탭과 Hunt 탭에서 공유할 화면 영역 지정, 탐지 팝업,
백그라운드 탐지 스레드를 한 곳에 모아둔다.
"""

from __future__ import annotations

import time
from typing import Dict, Iterable, List, Optional

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


MIN_MONSTER_BOX_SIZE = 30  # 탐지된 몬스터로 인정할 최소 크기(px)


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
        self.nickname_detector = nickname_detector
        self.direction_detector = direction_detector
        self.show_nickname_overlay = bool(show_nickname_overlay)
        self.show_direction_overlay = bool(show_direction_overlay)
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

        # FPS 계산 변수
        self.fps = 0.0
        self.frame_count = 0
        self.start_time = time.time()
        
        # [추가] 성능 분석을 위한 통계 변수
        self.perf_stats = {
            "nickname_ms": 0.0,
            "direction_ms": 0.0,
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

    def run(self) -> None:  # noqa: D401
        try:
            model = YOLO(self.model_path)
            sct = mss.mss()
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

                capture_start = time.perf_counter()
                grabbed = sct.grab(self.capture_region)
                capture_end = time.perf_counter()

                frame_np = np.array(grabbed)
                frame = cv2.cvtColor(frame_np, cv2.COLOR_BGRA2BGR)
                if self._region_mask is not None:
                    if (
                        self._region_mask.shape[0] == frame.shape[0]
                        and self._region_mask.shape[1] == frame.shape[1]
                    ):
                        frame = frame.copy()
                        frame[~self._region_mask] = 0
                preprocess_end = time.perf_counter()

                self.perf_stats["capture_ms"] = (capture_end - capture_start) * 1000
                self.perf_stats["preprocess_ms"] = (preprocess_end - capture_end) * 1000

                nick_start = time.perf_counter()
                nickname_info = None
                if self.nickname_detector is not None:
                    try:
                        nickname_info = self.nickname_detector.detect(frame)
                    except Exception as exc:
                        if self.is_debug_mode:
                            print(f"[DetectionThread] 닉네임 탐지 오류: {exc}")
                        nickname_info = None
                        try:
                            self.nickname_detector.notify_missed()
                        except Exception:
                            pass
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
                payload["direction"] = direction_info

                annotated_frame = frame
                if not annotated_frame.flags.writeable:
                    annotated_frame = annotated_frame.copy()

                if len(result.boxes) > 0:
                    boxes_for_payload: List[Dict[str, float]] = []
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
                        }
                        boxes_for_payload.append(item)

                        # 몬스터별 색상 및 텍스트 그리기
                        if class_id not in class_color_map:
                            class_color_map[class_id] = np.random.randint(0, 256, size=3).tolist()
                        color = class_color_map[class_id]
                        
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                        
                        # [핵심 수정] 표시할 텍스트에서 한글 클래스 이름을 제외
                        label = f"{item['score']:.2f}"
                        
                        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                        text_bg_y2 = y1 - 5
                        text_bg_y1 = text_bg_y2 - h - 5
                        if text_bg_y1 < 0:
                            text_bg_y1 = y1 + 5
                            text_bg_y2 = text_bg_y1 + h + 5

                        cv2.rectangle(annotated_frame, (x1, text_bg_y1), (x1 + w, text_bg_y2), color, -1)
                        
                        text_y = y1 - 10 if text_bg_y1 < y1 else y1 + h + 5
                        cv2.putText(annotated_frame, label, (x1 + 2, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

                    for item in boxes_for_payload:
                        if item["class_id"] == self.char_class_index:
                            payload["characters"].append(item)
                        else:
                            payload["monsters"].append(item)

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
                
                nick_box_data = nickname_info.get('nickname_box') if isinstance(nickname_info, dict) else None

                if self.show_nickname_overlay and nick_box_data:
                    x1, y1 = int(nick_box_data.get('x', 0)), int(nick_box_data.get('y', 0))
                    x2 = int(x1 + nick_box_data.get('width', 0))
                    y2 = int(y1 + nick_box_data.get('height', 0))
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 255), 2)

                if self.show_direction_overlay and direction_info and isinstance(direction_info, dict):
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

                if nick_box_data and self.current_facing in ("left", "right"):
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
                    "capture_ms": float(self.perf_stats["capture_ms"]),
                    "preprocess_ms": float(self.perf_stats["preprocess_ms"]),
                    "post_ms": float(self.perf_stats["post_ms"]),
                    "render_ms": float(self.perf_stats["render_ms"]),
                    "emit_ms": float(self.perf_stats["emit_ms"]),
                }

                emit_start = time.perf_counter()
                self.detections_ready.emit(payload)

                self.frame_ready.emit(qt_image.copy())
                emit_end = time.perf_counter()
                self.perf_stats["emit_ms"] = (emit_end - emit_start) * 1000
                self.msleep(15)
        except Exception as exc:
            print(f"탐지 스레드 오류: {exc}")

    def stop(self) -> None:
        self.is_running = False
