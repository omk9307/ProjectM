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
        self.is_running = True

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
            while self.is_running:
                frame_np = np.array(sct.grab(self.capture_region))
                frame = cv2.cvtColor(frame_np, cv2.COLOR_BGRA2BGR)

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

                results = model(
                    frame,
                    conf=low_conf,
                    classes=self.target_class_indices,
                    verbose=False,
                )

                result = results[0]

                if len(result.boxes) > 0 and use_char_class:
                    char_indices_with_conf: List[tuple[int, float]] = []
                    other_indices: List[int] = []

                    for i, box in enumerate(result.boxes):
                        cls_id = int(box.cls)
                        conf = float(box.conf.item())

                        if cls_id == self.char_class_index:
                            if conf >= self.conf_char:
                                char_indices_with_conf.append((i, conf))
                        elif conf >= self.conf_monster:
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

                if len(result.boxes) > 0:
                    boxes_for_payload: List[Dict[str, float]] = []
                    for box in result.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        item = {
                            "x": float(x1),
                            "y": float(y1),
                            "width": float(x2 - x1),
                            "height": float(y2 - y1),
                            "score": float(box.conf.item()),
                            "class_id": int(box.cls),
                            "class_name": model.names[int(box.cls)],
                        }
                        boxes_for_payload.append(item)

                    for item in boxes_for_payload:
                        if item["class_id"] == self.char_class_index:
                            payload["characters"].append(item)
                        else:
                            payload["monsters"].append(item)

                self.detections_ready.emit(payload)

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

                annotated_frame = result.plot()
                if not annotated_frame.flags.writeable:
                    annotated_frame = annotated_frame.copy()
                if nickname_info and nickname_info.get('nickname_box'):
                    nick_box = nickname_info['nickname_box']
                    x1 = int(nick_box.get('x', 0))
                    y1 = int(nick_box.get('y', 0))
                    x2 = int(x1 + nick_box.get('width', 0))
                    y2 = int(y1 + nick_box.get('height', 0))
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                rgb_image = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(
                    rgb_image.data,
                    w,
                    h,
                    bytes_per_line,
                    QImage.Format.Format_RGB888,
                )
                self.frame_ready.emit(qt_image.copy())
                self.msleep(15)
        except Exception as exc:  # pragma: no cover - GUI 스레드 예외 로깅
            print(f"탐지 스레드 오류: {exc}")

    def stop(self) -> None:
        self.is_running = False
