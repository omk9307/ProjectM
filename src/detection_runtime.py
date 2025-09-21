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
    """화면 전체에 반투명 오버레이를 씌우고 사용자가 영역을 선택하게 하는 도구."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screens = QApplication.screens()
        if not screens:
            raise RuntimeError("사용 가능한 모니터를 찾을 수 없습니다.")

        virtual_rect = screens[0].geometry()
        for screen in screens[1:]:
            virtual_rect = virtual_rect.united(screen.geometry())

        self.virtual_geometry = virtual_rect
        self.virtual_origin = virtual_rect.topLeft()
        self.setGeometry(virtual_rect)

        self.screenshot = QPixmap(virtual_rect.size())
        self.screenshot.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.screenshot)
        for screen in screens:
            geo = screen.geometry()
            offset = geo.topLeft() - self.virtual_origin
            painter.drawPixmap(offset, screen.grabWindow(0))
        painter.end()

        self.begin = QPoint()
        self.end = QPoint()
        self.is_selecting = False

    def paintEvent(self, event):  # noqa: N802 (Qt 시그니처 유지)
        painter = QPainter(self)
        painter.drawPixmap(QPoint(0, 0), self.screenshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.is_selecting:
            selected_rect = QRect(self.begin, self.end).normalized()
            painter.drawPixmap(selected_rect, self.screenshot, selected_rect)
            painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine))
            painter.drawRect(selected_rect)

    def mousePressEvent(self, event):  # noqa: N802
        self.begin = event.position().toPoint()
        self.end = event.position().toPoint()
        self.is_selecting = True
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        self.end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self.is_selecting = False
        if QRect(self.begin, self.end).normalized().width() > 5:
            self.accept()
        else:
            self.reject()

    def get_roi(self) -> QRect:
        return QRect(self.begin, self.end).normalized().translated(self.virtual_origin)


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
        
        # FPS 계산 변수
        self.fps = 0.0
        self.frame_count = 0
        self.start_time = time.time()
        
        # [추가] 성능 분석을 위한 통계 변수
        self.perf_stats = {
            "nickname_ms": 0.0,
            "direction_ms": 0.0,
            "yolo_ms": 0.0,
            "total_ms": 0.0,
        }

    def run(self) -> None:  # noqa: D401
        try:
            model = YOLO(self.model_path)
            sct = mss.mss()
            use_char_class = self.char_class_index >= 0
            low_conf = (
                min(self.conf_char, self.conf_monster)
                if use_char_class
                else self.conf_monster
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

                frame_np = np.array(sct.grab(self.capture_region))
                frame = cv2.cvtColor(frame_np, cv2.COLOR_BGRA2BGR)

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
                    verbose=False,
                )
                yolo_end = time.perf_counter()
                self.perf_stats["yolo_ms"] = (yolo_end - yolo_start) * 1000

                result = results[0]

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
                        elif conf >= self.conf_monster:
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
                
                if self.show_nickname_overlay and nickname_info and nickname_info.get('nickname_box'):
                    nick_box = nickname_info['nickname_box']
                    x1, y1 = int(nick_box.get('x', 0)), int(nick_box.get('y', 0))
                    x2 = int(x1 + nick_box.get('width', 0))
                    y2 = int(y1 + nick_box.get('height', 0))
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
                
                loop_end_time = time.perf_counter()
                self.perf_stats["total_ms"] = (loop_end_time - loop_start_time) * 1000
                payload["perf"] = {
                    "fps": float(self.fps),
                    "total_ms": float(self.perf_stats["total_ms"]),
                    "yolo_ms": float(self.perf_stats["yolo_ms"]),
                    "nickname_ms": float(self.perf_stats["nickname_ms"]),
                    "direction_ms": float(self.perf_stats["direction_ms"]),
                }

                y_pos = 30
                cv2.rectangle(annotated_frame, (5, 5), (250, 140), (0,0,0), -1)
                fps_text = f"FPS : {self.fps:.1f}"
                total_text = f"TOTAL: {self.perf_stats['total_ms']:.1f} ms"
                nick_text = f" NICK: {self.perf_stats['nickname_ms']:.1f} ms"
                yolo_text = f" YOLO: {self.perf_stats['yolo_ms']:.1f} ms"
                dir_text = f" DIR: {self.perf_stats['direction_ms']:.1f} ms"
                cv2.putText(annotated_frame, fps_text, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2); y_pos += 25
                cv2.putText(annotated_frame, total_text, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2); y_pos += 25
                cv2.putText(annotated_frame, nick_text, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2); y_pos += 25
                cv2.putText(annotated_frame, yolo_text, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2); y_pos += 25
                cv2.putText(annotated_frame, dir_text, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                self.detections_ready.emit(payload)

                rgb_image = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.frame_ready.emit(qt_image.copy())
                self.msleep(15)
        except Exception as exc:
            print(f"탐지 스레드 오류: {exc}")

    def stop(self) -> None:
        self.is_running = False
