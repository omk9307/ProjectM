# Learning.py
# 2025년 08月 12日 16:10 (KST)
# 기능: 데이터 관리, YOLOv8 훈련, 실시간 객체 탐지 기능을 통합한 GUI 위젯
# 설명:
# - v1.4: [기능개선] 마지막으로 사용한 모델을 기억하고 프로그램 재시작 시 자동으로 선택하는 기능 추가.
# - v1.3: [기능추가] '방해 요소' 지정 및 관리 기능 추가.
#         - 편집기에서 특정 영역을 지정하여 '방해 요소' 네거티브 샘플로 저장하는 기능.
#         - 잘라낸 방해 요소 이미지를 별도로 관리하고, 학습 시 오탐 감소에 활용.
#         - UI에 '학습 방해 요소 (네거티브)' 카테고리를 추가하여 관리 편의성 증대.
# - v1.2: src/workspace 분리 구조에 맞게 모든 경로 설정을 수정.
# - v1.1: LearningTab 위젯에 레이아웃이 중복으로 설정되던 버그 수정.
# - main.py에서 이 파일을 모듈로 불러와 탭으로 사용합니다.

import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

import sys
import os
import shutil
import json
import yaml
import cv2
import numpy as np
import mss
import pygetwindow as gw
import time
import uuid
import requests
from pathlib import Path
from collections import OrderedDict
from typing import Optional, ClassVar

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover - 실행 환경에 따라 미설치일 수 있음
    pytesseract = None  # type: ignore

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QLabel, QDialog, QMessageBox, QFileDialog,
    QListWidgetItem, QInputDialog, QTextEdit, QDialogButtonBox, QCheckBox,
    QComboBox, QDoubleSpinBox, QGroupBox, QScrollArea, QSpinBox,
    QProgressBar, QStatusBar, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QLineEdit, QFormLayout, QGridLayout, QSizePolicy
)
from PyQt6.QtGui import (
    QPixmap, QImage, QIcon, QPainter, QPen, QColor, QBrush, QCursor, QPolygon,
    QDropEvent, QGuiApplication, QIntValidator, QDoubleValidator, QFont
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QPoint, QObject, QMimeData

from capture_manager import get_capture_manager

# AI 어시스트 기능(SAM)과 훈련(YOLO)에 필요한 라이브러리를 import 합니다.
# 만약 라이브러리가 설치되지 않았더라도 프로그램이 실행은 되도록 try-except 구문을 사용합니다.
try:
    import torch
    from segment_anything import sam_model_registry, SamPredictor
    SAM_AVAILABLE = True
except ImportError:
    SAM_AVAILABLE = False

from ultralytics import YOLO

from status_monitor import (
    PYTESSERACT_AVAILABLE,
    ResourceConfig as StatusResourceConfig,
    Roi as StatusRoi,
    StatusConfigNotifier,
    StatusMonitorConfig,
    StatusMonitorThread,
)

# --- 0. 전역 설정 (v1.3 방해 요소 이름 추가) ---
# 소스 코드가 위치한 src/ 폴더
SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
# 작업 데이터가 저장될 workspace/ 폴더
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..', 'workspace'))

# AI 어시스트 모델(SAM)의 로컬 경로와 다운로드 URL을 정의합니다.
SAM_MODEL_DIR = os.path.join(WORKSPACE_ROOT, "config", "ai_assist")
os.makedirs(SAM_MODEL_DIR, exist_ok=True)
SAM_CHECKPOINT_PATH = os.path.join(SAM_MODEL_DIR, "sam_vit_b_01ec64.pth")
SAM_MODEL_URL = "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"

# '캐릭터' 클래스는 특별 취급(신뢰도 분리 등)을 위해 상수로 이름을 정의합니다.
CHARACTER_CLASS_NAME = "캐릭터"
# v1.3: 네거티브 샘플(방해 요소)을 관리하기 위한 특수 클래스 이름을 정의합니다.
NEGATIVE_SAMPLES_NAME = "학습 방해 요소 (네거티브)"
# 클래스 관리의 최상위 카테고리 목록을 정의합니다. '캐릭터'는 항상 최상단에 위치합니다.
CATEGORIES = [CHARACTER_CLASS_NAME, "몬스터", "오브젝트", "기타"]


# 편집기에서 클래스별로 다른 색상의 다각형을 그리기 위한 색상 목록입니다.
CLASS_COLORS = [
    QColor(0, 255, 0, 80), QColor(255, 0, 0, 80), QColor(0, 0, 255, 80),
    QColor(255, 255, 0, 80), QColor(0, 255, 255, 80), QColor(255, 0, 255, 80),
    QColor(128, 0, 0, 80), QColor(0, 128, 0, 80), QColor(0, 0, 128, 80),
    QColor(128, 128, 0, 80), QColor(0, 128, 128, 80), QColor(128, 0, 128, 80)
]
# 최소 몬스터 라벨 크기(px)
MIN_MONSTER_LABEL_SIZE = 30
# 편집기에서 마우스 커서를 올린 다각형을 강조하기 위한 색상입니다.
HIGHLIGHT_BRUSH_COLOR = QColor(255, 255, 0, 100) # 채우기 색상
HIGHLIGHT_PEN_COLOR = QColor(255, 255, 255)   # 외곽선 색상 (흰색)

DEFAULT_DETECTION_RUNTIME_SETTINGS = {
    'yolo_nms_iou': 0.40,
    'yolo_max_det': 60,
}

DEFAULT_MONSTER_CONFIDENCE = 0.50

# --- 0.5 SAM 관리자 클래스 ---
class SAMManager(QObject):
    """
    AI 어시스트 모델(SAM)의 다운로드, 로딩, 예측을 관리하는 클래스입니다.
    GUI의 응답 없음을 방지하기 위해 별도의 스레드에서 동작합니다.
    """
    model_ready = pyqtSignal(object)      # 모델 로딩이 완료되었을 때 시그널
    status_updated = pyqtSignal(str)      # 상태바 메시지 업데이트 시그널
    progress_updated = pyqtSignal(int)    # 다운로드 진행률 업데이트 시그널

    def __init__(self):
        super().__init__()
        self.predictor = None

    def download_checkpoint(self):
        """SAM 모델 파일을 인터넷에서 다운로드합니다."""
        self.status_updated.emit("SAM 모델 파일 다운로드 중...")
        try:
            with requests.get(SAM_MODEL_URL, stream=True) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                with open(SAM_CHECKPOINT_PATH, 'wb') as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = int((downloaded / total_size) * 100) if total_size > 0 else 0
                        self.progress_updated.emit(progress)
            self.progress_updated.emit(100)
            return True
        except Exception as e:
            self.status_updated.emit(f"SAM 모델 다운로드 실패: {e}")
            if os.path.exists(SAM_CHECKPOINT_PATH): os.remove(SAM_CHECKPOINT_PATH)
            return False

    def load_model(self):
        """로컬에 저장된 SAM 모델 파일을 메모리로 로드합니다."""
        if not SAM_AVAILABLE: self.status_updated.emit("SAM 필수 라이브러리가 설치되지 않았습니다."); return
        if not os.path.exists(SAM_CHECKPOINT_PATH):
            if not self.download_checkpoint(): return
        self.status_updated.emit("SAM 모델 로드 중... (GPU 우선 사용)")
        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            sam = sam_model_registry["vit_b"](checkpoint=SAM_CHECKPOINT_PATH)
            sam.to(device=device)
            self.predictor = SamPredictor(sam)
            self.model_ready.emit(self.predictor)
            self.status_updated.emit("SAM 모델 로드 완료. AI 어시스트를 사용할 수 있습니다.")
        except Exception as e: self.status_updated.emit(f"SAM 모델 로드 실패: {e}")

# --- 1. 위젯: 화면 캡처 영역 지정 도구 ---
class ScreenSnipper(QDialog):
    """화면 전체에 반투명 오버레이를 씌우고 사용자가 드래그하여 특정 영역을 선택하게 하는 위젯."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screen = QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        self.screenshot = screen.grabWindow(0)
        self.begin, self.end, self.is_selecting = QPoint(), QPoint(), False
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screenshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.is_selecting:
            selected_rect = QRect(self.begin, self.end).normalized()
            painter.drawPixmap(selected_rect, self.screenshot, selected_rect)
            painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine))
            painter.drawRect(selected_rect)
    def mousePressEvent(self, event): self.begin = event.pos(); self.end = event.pos(); self.is_selecting = True; self.update()
    def mouseMoveEvent(self, event): self.end = event.pos(); self.update()
    def mouseReleaseEvent(self, event):
        self.is_selecting = False
        if QRect(self.begin, self.end).normalized().width() > 5: self.accept()
        else: self.reject()
    def get_roi(self): return QRect(self.begin, self.end).normalized()


class StatusRegionSelector(QDialog):
    """전체 화면 위에서 정밀하게 ROI를 지정하기 위한 오버레이."""

    def __init__(self, parent=None, zoom_factor: int = 15, preview_size: QSize = QSize(180, 180)):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.zoom_factor = max(1, int(zoom_factor))
        self.preview_size = preview_size

        screens = QApplication.screens()
        if not screens:
            raise RuntimeError("사용 가능한 모니터를 찾을 수 없습니다.")

        virtual_rect = screens[0].geometry()
        for screen in screens[1:]:
            virtual_rect = virtual_rect.united(screen.geometry())

        self.virtual_origin = virtual_rect.topLeft()
        self.setGeometry(virtual_rect)

        self.begin = QPoint()
        self.end = QPoint()
        self.is_selecting = False
        self.selection_active = False

        self._zoom_label = QLabel(self)
        self._zoom_label.setFixedSize(self.preview_size)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 200);"
            "border: 1px solid #ffffff;"
        )
        self._zoom_label.hide()

        self._size_label = QLabel(self)
        self._size_label.setStyleSheet(
            "color: #ffffff;"
            "background-color: rgba(0, 0, 0, 180);"
            "padding: 2px 6px;"
            "border: 1px solid #888888;"
        )
        self._size_label.hide()

        pattern_pixmap = QPixmap(2, 2)
        pattern_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pattern_pixmap)
        painter.fillRect(0, 0, 1, 1, QColor(255, 0, 0, 90))
        painter.fillRect(1, 1, 1, 1, QColor(255, 0, 0, 40))
        painter.end()
        self._selection_brush = QBrush(pattern_pixmap)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        local_point = QCursor.pos() - self.virtual_origin
        if not self.rect().contains(local_point):
            local_point = self.rect().center()
        self._update_overlays(local_point)

    def mousePressEvent(self, event):  # noqa: N802
        point = self._clamp_to_virtual(event.position().toPoint())
        self.begin = point
        self.end = point
        self.is_selecting = True
        self.selection_active = True
        self.setFocus()
        self._update_overlays(point)
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        point = self._clamp_to_virtual(event.position().toPoint())
        if self.is_selecting:
            self.end = point
        self._update_overlays(point)
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        point = self._clamp_to_virtual(event.position().toPoint())
        if self.is_selecting:
            self.end = point
            self.is_selecting = False
            self.selection_active = True
            left = min(self.begin.x(), self.end.x())
            right = max(self.begin.x(), self.end.x())
            top = min(self.begin.y(), self.end.y())
            bottom = max(self.begin.y(), self.end.y())
            self.begin = QPoint(left, top)
            self.end = QPoint(right, bottom)
            rect = self._current_rect()
            if rect.width() <= 0 or rect.height() <= 0:
                self.selection_active = False
                self.reject()
                return
        self._update_overlays(point)
        self.update()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.selection_active and self._current_rect().width() > 0 and self._current_rect().height() > 0:
                self.accept()
            return

        if key == Qt.Key.Key_Escape:
            self.selection_active = False
            self.reject()
            return

        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            if not self.selection_active:
                return
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx = dy = 0
            if key == Qt.Key.Key_Left:
                dx = -step
            elif key == Qt.Key.Key_Right:
                dx = step
            elif key == Qt.Key.Key_Up:
                dy = -step
            elif key == Qt.Key.Key_Down:
                dy = step
            self._adjust_end(dx, dy)
            self._update_overlays(self.end)
            self.update()
            return

        super().keyPressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        rect = self._current_rect()
        if rect.width() > 0 and rect.height() > 0:
            painter.save()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.restore()
            painter.save()
            painter.setOpacity(0.35)
            painter.fillRect(rect, self._selection_brush)
            painter.restore()
            painter.setPen(QPen(QColor(255, 0, 0, 200), 1))
            painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
            painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
            painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
            painter.drawLine(rect.right(), rect.top(), rect.right(), rect.bottom())
        painter.end()

    def _update_overlays(self, local_point: QPoint) -> None:
        local_point = self._clamp_to_virtual(local_point)
        global_point = self.virtual_origin + local_point
        self._update_zoom_preview(global_point, local_point)
        self._update_size_label(local_point)

    def _update_zoom_preview(self, global_point: QPoint, local_point: QPoint) -> None:
        screen = QGuiApplication.screenAt(global_point)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            self._zoom_label.hide()
            return

        crop_w = max(1, self.preview_size.width() // self.zoom_factor)
        crop_h = max(1, self.preview_size.height() // self.zoom_factor)
        screen_geo = screen.geometry()
        grab_x = int(global_point.x() - screen_geo.left() - crop_w // 2)
        grab_y = int(global_point.y() - screen_geo.top() - crop_h // 2)
        grab_x = max(0, min(screen_geo.width() - crop_w, grab_x))
        grab_y = max(0, min(screen_geo.height() - crop_h, grab_y))
        pixmap = screen.grabWindow(0, grab_x, grab_y, crop_w, crop_h)
        if pixmap.isNull():
            self._zoom_label.hide()
            return
        zoomed = pixmap.scaled(
            self.preview_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        painter = QPainter(zoomed)
        scale_x = self.preview_size.width() / crop_w
        scale_y = self.preview_size.height() / crop_h

        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        for col in range(crop_w + 1):
            x_pos = int(round(col * scale_x))
            painter.drawLine(x_pos, 0, x_pos, zoomed.height())
        for row in range(crop_h + 1):
            y_pos = int(round(row * scale_y))
            painter.drawLine(0, y_pos, zoomed.width(), y_pos)

        painter.setPen(QPen(QColor(255, 0, 0, 200), 1))
        center_x = zoomed.width() // 2
        center_y = zoomed.height() // 2
        painter.drawLine(center_x, 0, center_x, zoomed.height())
        painter.drawLine(0, center_y, zoomed.width(), center_y)

        rect = self._current_rect()
        if rect.width() > 0 and rect.height() > 0:
            selection_global = rect.translated(self.virtual_origin)
            capture_rect_global = QRect(
                screen_geo.left() + grab_x,
                screen_geo.top() + grab_y,
                crop_w,
                crop_h,
            )
            intersect = selection_global.intersected(capture_rect_global)
            if not intersect.isNull():
                sel_left = int(round((intersect.left() - capture_rect_global.left()) * scale_x))
                sel_top = int(round((intersect.top() - capture_rect_global.top()) * scale_y))
                sel_width = max(1, int(round(intersect.width() * scale_x)))
                sel_height = max(1, int(round(intersect.height() * scale_y)))
                pixel_w = max(1, intersect.width())
                pixel_h = max(1, intersect.height())
                for row in range(pixel_h):
                    y1 = sel_top + int(round(row * scale_y))
                    y2 = sel_top + int(round((row + 1) * scale_y))
                    h = max(1, y2 - y1)
                    for col in range(pixel_w):
                        x1 = sel_left + int(round(col * scale_x))
                        x2 = sel_left + int(round((col + 1) * scale_x))
                        w = max(1, x2 - x1)
                        alpha = 90 if (row + col) % 2 == 0 else 40
                        painter.fillRect(x1, y1, w, h, QColor(255, 0, 0, alpha))
                painter.setPen(QPen(QColor(255, 0, 0, 200), 1))
                painter.drawRect(sel_left, sel_top, sel_width, sel_height)
        painter.end()

        label_x = local_point.x() - self.preview_size.width() // 2
        label_y = local_point.y() - self.preview_size.height() - 24
        label_x = max(0, min(self.width() - self.preview_size.width(), label_x))
        label_y = max(0, min(self.height() - self.preview_size.height(), label_y))
        self._zoom_label.move(label_x, label_y)
        self._zoom_label.setPixmap(zoomed)
        self._zoom_label.show()

    def _update_size_label(self, local_point: QPoint) -> None:
        rect = self._current_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            self._size_label.hide()
            return
        self._size_label.setText(f"{rect.width()}px × {rect.height()}px")
        label_x = local_point.x() + 16
        label_y = local_point.y() + 16
        label_x = max(0, min(self.width() - self._size_label.sizeHint().width(), label_x))
        label_y = max(0, min(self.height() - self._size_label.sizeHint().height(), label_y))
        self._size_label.move(label_x, label_y)
        self._size_label.show()

    def get_roi(self) -> QRect:
        rect = self._current_rect()
        return rect.translated(self.virtual_origin)

    def _current_rect(self) -> QRect:
        if not (self.selection_active or self.is_selecting):
            return QRect()
        left = min(self.begin.x(), self.end.x())
        right = max(self.begin.x(), self.end.x())
        top = min(self.begin.y(), self.end.y())
        bottom = max(self.begin.y(), self.end.y())
        width = max(1, right - left + 1)
        height = max(1, bottom - top + 1)
        return QRect(left, top, width, height)

    def _clamp_to_virtual(self, point: QPoint) -> QPoint:
        return QPoint(
            max(0, min(self.width() - 1, point.x())),
            max(0, min(self.height() - 1, point.y()))
        )

    def _adjust_end(self, dx: int, dy: int) -> None:
        new_x = max(0, min(self.width() - 1, self.end.x() + dx))
        new_y = max(0, min(self.height() - 1, self.end.y() + dy))
        self.end = QPoint(new_x, new_y)


class ExpRecognitionPreviewDialog(QDialog):
    """EXP 탐지 ROI 캡처와 OCR 결과를 시각적으로 확인하기 위한 대화상자."""

    def __init__(
        self,
        parent: Optional[QWidget],
        roi_description: str,
        original_bgr: Optional[np.ndarray],
        processed_gray: Optional[np.ndarray],
        summary_lines: list[str],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle('EXP 인식 확인')
        self.setModal(True)
        self.setMinimumWidth(520)

        self._buffers: list[np.ndarray] = []
        layout = QVBoxLayout()

        roi_label = QLabel(roi_description or '탐지 범위 정보가 없습니다.')
        roi_label.setWordWrap(True)
        layout.addWidget(roi_label)

        image_layout = QHBoxLayout()

        original_column = QVBoxLayout()
        original_title = QLabel('원본 캡처')
        original_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        original_column.addWidget(original_title)
        original_view = QLabel()
        original_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        original_pixmap = self._create_color_pixmap(original_bgr)
        original_view.setPixmap(self._scaled_pixmap(original_pixmap))
        original_column.addWidget(original_view)
        image_layout.addLayout(original_column)

        processed_column = QVBoxLayout()
        processed_title = QLabel('전처리(Threshold)')
        processed_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        processed_column.addWidget(processed_title)
        processed_view = QLabel()
        processed_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        processed_pixmap = self._create_gray_pixmap(processed_gray)
        processed_view.setPixmap(self._scaled_pixmap(processed_pixmap))
        processed_column.addWidget(processed_view)
        image_layout.addLayout(processed_column)

        layout.addLayout(image_layout)

        info_box = QTextEdit()
        info_box.setReadOnly(True)
        info_box.setMinimumHeight(140)
        info_text = '\n'.join(summary_lines) if summary_lines else '표시할 정보가 없습니다.'
        info_box.setPlainText(info_text)
        layout.addWidget(info_box)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _create_color_pixmap(self, image_bgr: Optional[np.ndarray]) -> QPixmap:
        if image_bgr is None or image_bgr.size == 0:
            return QPixmap()
        buffer = np.ascontiguousarray(image_bgr)
        self._buffers.append(buffer)
        height, width, channels = buffer.shape
        bytes_per_line = channels * width
        qimage = QImage(buffer.data, width, height, bytes_per_line, QImage.Format.Format_BGR888)
        return QPixmap.fromImage(qimage)

    def _create_gray_pixmap(self, image_gray: Optional[np.ndarray]) -> QPixmap:
        if image_gray is None:
            return QPixmap()
        buffer = np.ascontiguousarray(image_gray)
        self._buffers.append(buffer)
        height, width = buffer.shape[:2]
        bytes_per_line = width
        qimage = QImage(buffer.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(qimage)

    @staticmethod
    def _scaled_pixmap(pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        return pixmap.scaled(
            320,
            200,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

# --- 1.5. 위젯: 드래그앤드롭 커스텀 QTreeWidget ---
class ClassTreeWidget(QTreeWidget):
    """
    드롭 이벤트 발생 후 커스텀 시그널을 발생시키고,
    카테고리-클래스 계층 구조 규칙을 강제하는 커스텀 QTreeWidget.
    """
    drop_completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def dropEvent(self, event: 'QDropEvent'):
        # 드롭 위치와 대상 아이템 분석
        target_item = self.itemAt(event.position().toPoint())
        # currentItem()은 드래그 시작 시의 아이템을 정확히 가져오지 못할 수 있으므로,
        # MIME 데이터를 통해 가져오는 것이 더 안정적입니다.
        source_item = self.selectedItems()[0] if self.selectedItems() else None
        if not source_item:
            event.ignore()
            return

        drop_indicator = self.dropIndicatorPosition()

        # --- 규칙 검증 ---
        # v1.3: 방해 요소 항목은 드래그 불가
        if source_item.text(0) == NEGATIVE_SAMPLES_NAME:
            event.ignore()
            return

        is_source_item_category = source_item.parent() is None

        # 1. 클래스를 최상위(카테고리 레벨)로 이동 시도 방지
        if not is_source_item_category:  # 드래그한 것이 클래스일 때
            # 대상이 없거나(빈 공간), 대상이 카테고리인데 위/아래로 드롭하는 경우
            if target_item is None or (target_item.parent() is None and drop_indicator != QAbstractItemView.DropIndicatorPosition.OnItem):
                event.ignore()
                return

        # 2. 카테고리를 클래스 안으로 이동 시도 방지
        if is_source_item_category:  # 드래그한 것이 카테고리일 때
            # 대상이 클래스이거나(부모가 있음), 대상이 카테고리인데 '안으로(OnItem)' 드롭하는 경우
            if (target_item and target_item.parent() is not None) or \
               (target_item and target_item.parent() is None and drop_indicator == QAbstractItemView.DropIndicatorPosition.OnItem):
                event.ignore()
                return

        # 3. 클래스를 다른 클래스 '안으로' 중첩 시도 방지
        if not is_source_item_category and target_item and target_item.parent() is not None:  # 클래스를 클래스 위로 드롭
            if drop_indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
                event.ignore()
                return

        # 모든 규칙을 통과하면 기본 드롭 이벤트 실행
        super().dropEvent(event)
        self.drop_completed.emit()


    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current_item = self.currentItem()
            if current_item is not None:
                self.itemDoubleClicked.emit(current_item, 0)
                event.accept()
                return
        super().keyPressEvent(event)


class MonsterSettingsDialog(QDialog):
    """특정 몬스터 클래스에 대한 추후 확장 가능한 설정 다이얼로그."""

    _DEFAULT_BROWSE_DIR: ClassVar[str] = str(Path.home())
    _LAST_TEMPLATE_DIRS: ClassVar[dict[str, str]] = {}
    _LAST_TEST_DIRS: ClassVar[dict[str, str]] = {}

    @classmethod
    def _resolve_start_directory(cls, cache: dict[str, str], class_name: str) -> str:
        stored = cache.get(class_name)
        if stored and os.path.isdir(stored):
            return stored
        if cls._DEFAULT_BROWSE_DIR and os.path.isdir(cls._DEFAULT_BROWSE_DIR):
            return cls._DEFAULT_BROWSE_DIR
        return str(Path.home())

    @classmethod
    def _remember_directory(cls, cache: dict[str, str], class_name: str, selected_files: list[str]) -> None:
        if not selected_files:
            return
        first_dir = os.path.dirname(selected_files[0])
        if first_dir and os.path.isdir(first_dir):
            cache[class_name] = first_dir
            cls._DEFAULT_BROWSE_DIR = first_dir

    def __init__(
        self,
        parent: Optional[QWidget],
        class_name: str,
        *,
        current_value: Optional[float],
        default_value: float,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"몬스터 설정 - {class_name}")
        self.resize(420, 520)

        self.learning_tab = parent
        self.data_manager = getattr(parent, 'data_manager', None)
        self._default_value = float(default_value)
        self.override_enabled: bool = current_value is not None
        self.override_value: float = float(current_value) if current_value is not None else self._default_value
        self.class_name = class_name

        nameplate_entry = {'threshold': None, 'templates': []}
        if self.data_manager and hasattr(self.data_manager, 'get_monster_nameplate_entry'):
            try:
                entry = self.data_manager.get_monster_nameplate_entry(class_name)
                if isinstance(entry, dict):
                    nameplate_entry.update(entry)
            except Exception:
                pass
        self.nameplate_threshold_enabled = nameplate_entry.get('threshold') is not None
        default_nameplate_threshold = 0.60
        if getattr(parent, 'nameplate_config', None):
            try:
                default_nameplate_threshold = float(parent.nameplate_config.get('match_threshold', 0.60))
            except (TypeError, ValueError):
                default_nameplate_threshold = 0.60
        self.nameplate_threshold_value = float(nameplate_entry.get('threshold') or default_nameplate_threshold)
        self._initial_nameplate_threshold_enabled = self.nameplate_threshold_enabled
        self._initial_nameplate_threshold_value = self.nameplate_threshold_value
        self.test_samples: list[dict] = []
        self._test_item_map: dict[str, QListWidgetItem] = {}

        layout = QVBoxLayout(self)

        intro_label = QLabel(
            "클래스별 탐지 옵션을 설정합니다. 필요 시 다른 설정도 추가될 예정입니다."
        )
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        settings_group = QGroupBox("탐지 설정")
        settings_layout = QVBoxLayout(settings_group)

        override_row = QHBoxLayout()
        self.use_override_checkbox = QCheckBox("개별 신뢰도 사용")
        self.use_override_checkbox.setChecked(self.override_enabled)
        self.use_override_checkbox.toggled.connect(self._on_override_toggled)
        override_row.addWidget(self.use_override_checkbox)

        self.conf_spinbox = QDoubleSpinBox()
        self.conf_spinbox.setRange(0.05, 0.95)
        self.conf_spinbox.setSingleStep(0.05)
        self.conf_spinbox.setDecimals(2)
        self.conf_spinbox.setValue(self.override_value)
        self.conf_spinbox.setEnabled(self.override_enabled)
        self.conf_spinbox.setToolTip("사냥 탭에서 해당 몬스터를 탐지할 최소 신뢰도입니다.")
        override_row.addWidget(self.conf_spinbox)
        override_row.addStretch(1)

        settings_layout.addLayout(override_row)

        hint_label = QLabel("미사용 시 전역 몬스터 신뢰도 값을 따릅니다.")
        hint_label.setWordWrap(True)
        settings_layout.addWidget(hint_label)

        layout.addWidget(settings_group)

        nameplate_group = QGroupBox("몬스터 이름표 설정")
        nameplate_layout = QVBoxLayout(nameplate_group)

        threshold_row = QHBoxLayout()
        self.use_nameplate_threshold_checkbox = QCheckBox("이름표 임계값 사용")
        self.use_nameplate_threshold_checkbox.setChecked(self.nameplate_threshold_enabled)
        self.use_nameplate_threshold_checkbox.toggled.connect(self._on_nameplate_threshold_toggled)
        threshold_row.addWidget(self.use_nameplate_threshold_checkbox)

        self.nameplate_threshold_spin = QDoubleSpinBox()
        self.nameplate_threshold_spin.setRange(0.10, 0.99)
        self.nameplate_threshold_spin.setSingleStep(0.01)
        self.nameplate_threshold_spin.setDecimals(2)
        self.nameplate_threshold_spin.setValue(self.nameplate_threshold_value)
        self.nameplate_threshold_spin.setEnabled(self.nameplate_threshold_enabled)
        threshold_row.addWidget(self.nameplate_threshold_spin)
        threshold_row.addStretch(1)
        nameplate_layout.addLayout(threshold_row)

        templates_label = QLabel("이름표 템플릿 (검은 박스 + 흰 글씨 이미지)")
        templates_label.setWordWrap(True)
        nameplate_layout.addWidget(templates_label)

        self.nameplate_template_list = QListWidget()
        self.nameplate_template_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.nameplate_template_list.setIconSize(QSize(160, 64))
        self.nameplate_template_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.nameplate_template_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.nameplate_template_list.setMinimumHeight(140)
        nameplate_layout.addWidget(self.nameplate_template_list)

        template_buttons = QHBoxLayout()
        self.add_nameplate_template_btn = QPushButton("파일 추가")
        self.add_nameplate_template_btn.clicked.connect(self._import_nameplate_templates)
        template_buttons.addWidget(self.add_nameplate_template_btn)
        self.delete_nameplate_template_btn = QPushButton("선택 삭제")
        self.delete_nameplate_template_btn.clicked.connect(self._delete_selected_nameplate_templates)
        template_buttons.addWidget(self.delete_nameplate_template_btn)
        template_buttons.addStretch(1)
        nameplate_layout.addLayout(template_buttons)

        test_group = QGroupBox("이름표 인식 테스트")
        test_layout = QVBoxLayout(test_group)
        test_layout.addWidget(QLabel("예제 이미지와 현재 템플릿으로 인식 가능 여부를 확인합니다."))

        self.test_sample_list = QListWidget()
        self.test_sample_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.test_sample_list.setIconSize(QSize(160, 64))
        self.test_sample_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.test_sample_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.test_sample_list.setMinimumHeight(140)
        test_layout.addWidget(self.test_sample_list)

        test_button_row = QHBoxLayout()
        self.add_test_sample_btn = QPushButton("테스트 이미지 추가")
        self.add_test_sample_btn.clicked.connect(self._add_test_samples)
        test_button_row.addWidget(self.add_test_sample_btn)
        self.remove_test_sample_btn = QPushButton("선택 삭제")
        self.remove_test_sample_btn.clicked.connect(self._remove_selected_test_samples)
        test_button_row.addWidget(self.remove_test_sample_btn)
        self.run_test_btn = QPushButton("테스트 실행")
        self.run_test_btn.clicked.connect(self._run_nameplate_test)
        test_button_row.addWidget(self.run_test_btn)
        test_button_row.addStretch(1)
        test_layout.addLayout(test_button_row)

        self.test_result_label = QLabel("테스트 준비됨")
        self.test_result_label.setWordWrap(True)
        self.test_result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        test_layout.addWidget(self.test_result_label)

        nameplate_layout.addWidget(test_group)

        layout.addWidget(nameplate_group)

        button_layout = QHBoxLayout()
        self.reset_button = QPushButton("초기화")
        self.reset_button.clicked.connect(self._reset_to_default)
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch(1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_layout.addWidget(button_box)
        layout.addLayout(button_layout)

        self._populate_nameplate_templates()

    def _on_override_toggled(self, checked: bool) -> None:
        self.conf_spinbox.setEnabled(checked)

    def _reset_to_default(self) -> None:
        self.use_override_checkbox.setChecked(False)
        self.conf_spinbox.setValue(self._default_value)

    def _on_nameplate_threshold_toggled(self, checked: bool) -> None:
        self.nameplate_threshold_spin.setEnabled(checked)

    def _populate_nameplate_templates(self) -> None:
        if self.nameplate_template_list is None:
            return
        self.nameplate_template_list.clear()
        templates = []
        if self.data_manager and hasattr(self.data_manager, 'list_monster_nameplate_templates'):
            try:
                templates = self.data_manager.list_monster_nameplate_templates(self.class_name)
            except Exception:
                templates = []
        if not templates:
            placeholder = QListWidgetItem(QIcon(), "등록된 템플릿이 없습니다")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.nameplate_template_list.addItem(placeholder)
            self.delete_nameplate_template_btn.setEnabled(False)
            self._update_test_buttons()
            return
        self.delete_nameplate_template_btn.setEnabled(True)
        for entry in templates:
            path = entry.get('path')
            pixmap = QPixmap(path) if path else QPixmap()
            if pixmap.isNull():
                pixmap = QPixmap(self.nameplate_template_list.iconSize())
                pixmap.fill(Qt.GlobalColor.darkGray)
            icon = QIcon(pixmap)
            display = entry.get('original_name') or entry.get('id', '템플릿')
            item = QListWidgetItem(icon, display)
            item.setData(Qt.ItemDataRole.UserRole, entry.get('id'))
            tooltip_lines = [f"ID: {entry.get('id')}"]
            size_text = f"크기: {entry.get('width', '?')}x{entry.get('height', '?')}"
            tooltip_lines.append(size_text)
            created = entry.get('created_at')
            if created:
                tooltip_lines.append(time.strftime('등록 시각: %Y-%m-%d %H:%M:%S', time.localtime(created)))
            item.setToolTip('\n'.join(tooltip_lines))
            self.nameplate_template_list.addItem(item)
        self._update_test_buttons()

    def _import_nameplate_templates(self) -> None:
        if not self.data_manager:
            QMessageBox.warning(self, "오류", "데이터 매니저를 찾을 수 없습니다.")
            return
        start_dir = self._resolve_start_directory(self.__class__._LAST_TEMPLATE_DIRS, self.class_name)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "이름표 이미지 선택",
            start_dir,
            "이미지 파일 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not files:
            return
        added = 0
        for file_path in files:
            try:
                entry = self.data_manager.import_monster_nameplate_template(self.class_name, file_path)
            except Exception as exc:
                QMessageBox.warning(self, "오류", f"이름표 이미지를 추가하지 못했습니다: {exc}")
                continue
            if entry:
                added += 1
        if added:
            QMessageBox.information(self, "완료", f"이름표 템플릿 {added}개를 추가했습니다.")
            self._remember_directory(self.__class__._LAST_TEMPLATE_DIRS, self.class_name, files)
        self._populate_nameplate_templates()

    def _delete_selected_nameplate_templates(self) -> None:
        if not self.data_manager:
            QMessageBox.warning(self, "오류", "데이터 매니저를 찾을 수 없습니다.")
            return
        selected = [item for item in self.nameplate_template_list.selectedItems() if item.flags() != Qt.ItemFlag.NoItemFlags]
        if not selected:
            QMessageBox.information(self, "안내", "삭제할 템플릿을 선택해주세요.")
            return
        template_ids = [item.data(Qt.ItemDataRole.UserRole) for item in selected]
        removed = self.data_manager.delete_monster_nameplate_templates(self.class_name, template_ids)
        QMessageBox.information(self, "완료", f"이름표 템플릿 {removed}개를 삭제했습니다.")
        self._populate_nameplate_templates()
        self._update_test_buttons()

    def accept(self) -> None:  # noqa: D401
        self.override_enabled = self.use_override_checkbox.isChecked()
        self.override_value = float(self.conf_spinbox.value())
        self.nameplate_threshold_enabled = self.use_nameplate_threshold_checkbox.isChecked()
        self.nameplate_threshold_value = float(self.nameplate_threshold_spin.value())
        super().accept()

    def _update_test_buttons(self) -> None:
        has_samples = bool(self.test_samples)
        has_templates = bool(self.nameplate_template_list.count()) and not (
            self.nameplate_template_list.count() == 1 and self.nameplate_template_list.item(0).flags() == Qt.ItemFlag.NoItemFlags
        )
        self.remove_test_sample_btn.setEnabled(has_samples)
        self.run_test_btn.setEnabled(has_samples and has_templates)

    def _add_test_samples(self) -> None:
        start_dir = self._resolve_start_directory(self.__class__._LAST_TEST_DIRS, self.class_name)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "테스트용 이름표 이미지 선택",
            start_dir,
            "이미지 파일 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not files:
            return
        added = 0
        for path in files:
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None:
                QMessageBox.warning(self, "오류", f"이미지를 불러오지 못했습니다: {path}")
                continue
            sample_id = f"sample_{uuid.uuid4().hex[:8]}"
            icon = self._build_icon_from_image(image)
            label = os.path.basename(path)
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, sample_id)
            self.test_sample_list.addItem(item)
            self.test_samples.append({'id': sample_id, 'path': path, 'image': image})
            self._test_item_map[sample_id] = item
            added += 1
        if added:
            self.test_result_label.setText(f"테스트 이미지 {added}개를 추가했습니다.")
            self._remember_directory(self.__class__._LAST_TEST_DIRS, self.class_name, files)
        self._update_test_buttons()

    def _remove_selected_test_samples(self) -> None:
        selected = [item for item in self.test_sample_list.selectedItems() if item.flags() != Qt.ItemFlag.NoItemFlags]
        if not selected:
            return
        ids_to_remove = {item.data(Qt.ItemDataRole.UserRole) for item in selected}
        self.test_samples = [sample for sample in self.test_samples if sample['id'] not in ids_to_remove]
        for item in selected:
            row = self.test_sample_list.row(item)
            self.test_sample_list.takeItem(row)
        for sample_id in ids_to_remove:
            self._test_item_map.pop(sample_id, None)
        self.test_result_label.setText("선택한 테스트 이미지를 삭제했습니다.")
        self._update_test_buttons()

    def _run_nameplate_test(self) -> None:
        if not self.data_manager:
            QMessageBox.warning(self, "오류", "데이터 매니저를 찾을 수 없습니다.")
            return
        templates = self.data_manager.list_monster_nameplate_templates(self.class_name)
        if not templates:
            QMessageBox.information(self, "안내", "등록된 이름표 템플릿이 없습니다.")
            return
        template_images: list[tuple[str, np.ndarray]] = []
        for entry in templates:
            path = entry.get('path')
            if not path:
                continue
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None:
                continue
            if image.ndim == 3 and image.shape[2] == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            elif image.ndim == 3 and image.shape[2] == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
            display_name = entry.get('original_name') or os.path.basename(path) or entry.get('id', '템플릿')
            template_images.append((display_name, image))
        if not template_images:
            QMessageBox.warning(self, "오류", "템플릿 이미지를 불러오지 못했습니다.")
            return

        if self.use_nameplate_threshold_checkbox.isChecked():
            threshold = float(self.nameplate_threshold_spin.value())
        else:
            fallback = getattr(self.learning_tab, 'nameplate_config', {}) or {}
            threshold = float(fallback.get('match_threshold', 0.60))

        summary_lines: list[str] = []
        success_count = 0
        for sample in self.test_samples:
            sample_id = sample['id']
            item = self._test_item_map.get(sample_id)
            base_label = os.path.basename(sample['path'])
            best_score = -1.0
            best_template_name = None
            template_details: list[str] = []
            sample_success = False
            roi = self._preprocess_test_roi(sample['image'])
            if roi is None or roi.size == 0:
                if item:
                    item.setBackground(QBrush())
                    item.setText(f"{base_label} - 오류 (이미지를 처리하지 못했습니다)")
                    item.setBackground(QColor(200, 40, 40, 80))
                summary_lines.append(f"{base_label} → 전처리 실패")
                continue
            for tpl_name, tpl_img in template_images:
                if roi.shape[0] < tpl_img.shape[0] or roi.shape[1] < tpl_img.shape[1]:
                    template_details.append(f"{tpl_name}: 비교 불가(크기)")
                    continue
                result = cv2.matchTemplate(roi, tpl_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                score = float(max_val)
                is_match = score >= threshold
                template_details.append(f"{tpl_name}: {score:.2f} ({'성공' if is_match else '실패'})")
                if score > best_score:
                    best_score = score
                    best_template_name = tpl_name
                if is_match:
                    sample_success = True
            if item:
                item.setBackground(QBrush())
                status = "성공" if sample_success else "실패"
                if best_score >= 0 and best_template_name:
                    item.setText(f"{base_label} - {status} (최고 {best_template_name} {best_score:.2f})")
                else:
                    item.setText(f"{base_label} - {status} (유효한 템플릿 없음)")
                if sample_success:
                    item.setBackground(QColor(20, 120, 60, 80))
                else:
                    item.setBackground(QColor(200, 40, 40, 80))
            detail_text = ', '.join(template_details) if template_details else '유효한 템플릿 결과 없음'
            summary_lines.append(f"{base_label} → {detail_text}")
            if sample_success:
                success_count += 1
        if summary_lines:
            header = f"임계값 {threshold:.2f} | 총 {len(summary_lines)}개 테스트 중 {success_count}개 성공"
            self.test_result_label.setText(header + "\n" + "\n".join(summary_lines))
        else:
            self.test_result_label.setText("테스트할 이미지가 없습니다.")
        self._update_test_buttons()

    @staticmethod
    def _build_icon_from_image(image: np.ndarray) -> QIcon:
        display = image
        if display.ndim == 2:
            display = cv2.cvtColor(display, cv2.COLOR_GRAY2BGR)
        elif display.ndim == 3 and display.shape[2] == 4:
            display = cv2.cvtColor(display, cv2.COLOR_BGRA2BGR)
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(160, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return QIcon(pixmap)

    @staticmethod
    def _preprocess_test_roi(image: np.ndarray) -> Optional[np.ndarray]:
        if image is None or not hasattr(image, 'ndim'):
            return None
        if image.ndim == 3 and image.shape[2] == 4:
            gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        elif image.ndim == 3 and image.shape[2] == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif image.ndim == 2:
            gray = image
        else:
            return None
        roi = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
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

# --- 2. 위젯: 다각형 편집기의 캔버스 (공통 로직 추가) ---
class BaseCanvasLabel(QLabel):
    """
    수동 및 AI 편집기 캔버스의 공통 기능을 정의하는 부모 클래스입니다.
    (줌, 패닝, 다각형 그리기, 하이라이트, 지정 삭제)
    """
    def __init__(self, pixmap, parent_dialog):
        super().__init__()
        self.pixmap = pixmap
        self.parent_dialog = parent_dialog
        self.zoom_factor = 1.0
        self.polygons = []
        self.hovered_polygon_idx = -1
        self.panning, self.pan_start_pos = False, QPoint()
        self.setMouseTracking(True)
        self.set_zoom(1.0)

    def set_zoom(self, factor):
        self.zoom_factor = factor
        self.setFixedSize(self.pixmap.size() * self.zoom_factor)
        self.update()

    def enterEvent(self, event):
        """마우스가 캔버스에 들어오면 부모 다이얼로그에 포커스를 줍니다."""
        self.parent_dialog.activateWindow()
        self.parent_dialog.setFocus()
        super().enterEvent(event)

    def paint_polygons(self, painter):
        """저장된 모든 다각형을 그립니다. 마우스 오버 시 하이라이트됩니다."""
        for i, poly_data in enumerate(self.polygons):
            scaled_points = [p * self.zoom_factor for p in poly_data['points']]

            # 동적 색상 할당 맵에서 색상을 가져옴
            color = self.parent_dialog.get_color_for_class_id(poly_data['class_id'])

            if i == self.hovered_polygon_idx:
                # 하이라이트: 밝은 흰색 외곽선 + 반투명 노란색 채우기
                painter.setPen(QPen(HIGHLIGHT_PEN_COLOR, 2, Qt.PenStyle.SolidLine))
                painter.setBrush(QBrush(HIGHLIGHT_BRUSH_COLOR))
            else:
                painter.setPen(QPen(color.darker(150), 2))
                painter.setBrush(QBrush(color))

            painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in scaled_points]))

    def mouseMoveEvent(self, event):
        """마우스 이동 이벤트를 처리합니다. (패닝 또는 하이라이트)"""
        if self.panning:
            delta = event.pos() - self.pan_start_pos
            scroll_area = self.parent().parent()
            scroll_area.horizontalScrollBar().setValue(scroll_area.horizontalScrollBar().value() - delta.x())
            scroll_area.verticalScrollBar().setValue(scroll_area.verticalScrollBar().value() - delta.y())
            self.pan_start_pos = event.pos()
        else:
            original_pos_f = event.pos() / self.zoom_factor
            original_pos = QPoint(int(original_pos_f.x()), int(original_pos_f.y()))
            self.hovered_polygon_idx = -1
            for i, poly_data in reversed(list(enumerate(self.polygons))):
                q_poly = QPolygon([QPoint(int(p.x()), int(p.y())) for p in poly_data['points']])
                if q_poly.containsPoint(original_pos, Qt.FillRule.WindingFill):
                    self.hovered_polygon_idx = i
                    break

            # 상태바에 호버된 클래스 이름 표시
            if self.hovered_polygon_idx != -1:
                class_id = self.polygons[self.hovered_polygon_idx]['class_id']
                self.parent_dialog.update_hover_status(class_id)
            else:
                self.parent_dialog.update_hover_status(None)

            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = False
            self.setCursor(Qt.CursorShape.CrossCursor)

    def change_hovered_polygon_class(self):
        """마우스가 올라가 있는 다각형의 클래스를 현재 선택된 클래스로 변경합니다."""
        if self.hovered_polygon_idx != -1:
            new_class_id = self.parent_dialog.get_current_class_id()
            if new_class_id is not None:
                self.polygons[self.hovered_polygon_idx]['class_id'] = new_class_id
                self.update()
                return True
        return False

    def delete_hovered_polygon(self):
        """마우스 커서가 올라가 있는 다각형을 삭제합니다."""
        if self.hovered_polygon_idx != -1:
            del self.polygons[self.hovered_polygon_idx]
            self.hovered_polygon_idx = -1
            self.update()

class CanvasLabel(BaseCanvasLabel):
    """수동 다각형 편집기 전용 캔버스. 현재 그리는 다각형을 추가로 처리합니다."""
    def __init__(self, pixmap, initial_polygons=None, parent_dialog=None):
        super().__init__(pixmap, parent_dialog)
        self.polygons = initial_polygons if initial_polygons else []
        self.current_points = []
        self.current_pos = QPoint()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_polygons(painter)
        if self.current_points:
            class_id = self.parent_dialog.get_current_class_id()
            if class_id is not None:
                color = self.parent_dialog.get_color_for_class_id(class_id)
                scaled_current_points = [p * self.zoom_factor for p in self.current_points]
                painter.setPen(QPen(color.darker(150), 2)); painter.setBrush(QBrush(color))
                painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in scaled_current_points]))
                if self.rect().contains(self.current_pos): painter.drawLine(scaled_current_points[-1], self.current_pos)
                for point in scaled_current_points: painter.drawEllipse(point, 4, 4)

    def mousePressEvent(self, event):
        if self.parent_dialog.is_change_mode and event.button() == Qt.MouseButton.LeftButton:
            if self.change_hovered_polygon_class():
                return

        if event.button() == Qt.MouseButton.LeftButton:
            self.current_points.append(event.pos() / self.zoom_factor); self.update()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True; self.pan_start_pos = event.pos(); self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.panning:
            self.current_pos = event.pos(); self.update()

# --- 3. 위젯: 다각형 편집기 다이얼로그 (공통 로직 추가) ---
class PolygonAnnotationEditor(QDialog):
    """수동 다각형 편집기 메인 창."""
    # v1.3: 방해 요소 저장을 위한 커스텀 결과 코드 정의
    DistractorSaved = 100

    def __init__(self, pixmap, initial_polygons=None, parent=None, initial_class_name=None):
        super().__init__(parent)
        self.setWindowTitle('수동 편집기 (변경:C, 지정삭제:D, 완성취소:Z, 초기화:R)')
        self.learning_tab = parent # LearningTab 인스턴스 저장
        self.is_change_mode = False
        self.canvas = CanvasLabel(pixmap, initial_polygons, self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.setWidgetResizable(True)
        main_layout = QVBoxLayout()
        top_controls_layout = QHBoxLayout()

        # 확대/축소 및 클래스 변경 버튼
        left_controls_layout = QHBoxLayout()
        self.zoom_1x_btn, self.zoom_1_5x_btn, self.zoom_2x_btn = QPushButton("1x"), QPushButton("1.5x"), QPushButton("2x")
        self.zoom_1x_btn.clicked.connect(lambda: self.canvas.set_zoom(1.0))
        self.zoom_1_5x_btn.clicked.connect(lambda: self.canvas.set_zoom(1.5))
        self.zoom_2x_btn.clicked.connect(lambda: self.canvas.set_zoom(2.0))
        left_controls_layout.addWidget(QLabel("확대:"))
        left_controls_layout.addWidget(self.zoom_1x_btn)
        left_controls_layout.addWidget(self.zoom_1_5x_btn)
        left_controls_layout.addWidget(self.zoom_2x_btn)
        left_controls_layout.addSpacing(20)
        self.change_class_btn = QPushButton("클래스 변경 (C)")
        self.change_class_btn.setCheckable(True)
        self.change_class_btn.toggled.connect(self.toggle_change_mode)
        left_controls_layout.addWidget(self.change_class_btn)

        # 클래스 선택 UI
        class_selection_layout = QHBoxLayout()
        class_selection_layout.addWidget(QLabel("카테고리:"))
        self.category_selector = QComboBox()
        self.category_selector.addItems(CATEGORIES)
        self.category_selector.currentIndexChanged.connect(self.update_class_selector)
        class_selection_layout.addWidget(self.category_selector)

        class_selection_layout.addWidget(QLabel("클래스:"))
        self.class_selector = QComboBox()
        self.class_selector.activated.connect(self.handle_class_selection)
        class_selection_layout.addWidget(self.class_selector)

        top_controls_layout.addLayout(left_controls_layout); top_controls_layout.addStretch(1); top_controls_layout.addLayout(class_selection_layout)

        # 상태바 추가
        self.status_bar = QStatusBar()
        self.status_label = QLabel("준비")
        self.status_bar.addWidget(self.status_label)

        # v1.3: 버튼 박스 수정
        self.button_box = QDialogButtonBox()
        self.save_button = self.button_box.addButton("저장", QDialogButtonBox.ButtonRole.AcceptRole)
        self.distractor_button = self.button_box.addButton("방해 요소로 저장", QDialogButtonBox.ButtonRole.ActionRole)
        self.cancel_button = self.button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.on_save)
        self.distractor_button.clicked.connect(self.on_save_distractor)
        self.button_box.rejected.connect(self.reject)
        
        main_layout.addLayout(top_controls_layout)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.status_bar)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        new_width = min(pixmap.width() + 50, int(screen_geometry.width() * 0.9))
        new_height = min(pixmap.height() + 150, int(screen_geometry.height() * 0.9))
        self.resize(new_width, new_height)

        self.full_class_list = self.learning_tab.data_manager.get_class_list()
        self.create_local_color_map()
        self.set_initial_selection(initial_class_name)
        self.setFocus()

    # v1.3: 방해 요소 저장 슬롯
    def on_save_distractor(self):
        """'방해 요소로 저장' 버튼 클릭 시 호출됩니다."""
        if len(self.canvas.current_points) >= 3:
            # 방해 요소는 클래스 ID가 필요 없으므로, 현재 그리던 다각형만 저장
            self.canvas.polygons.append({'class_id': None, 'points': list(self.canvas.current_points)})
            self.canvas.current_points.clear()
        
        if not self.canvas.polygons:
            QMessageBox.warning(self, "오류", "방해 요소로 지정할 다각형이 없습니다.")
            return

        self.done(self.DistractorSaved)

    def create_local_color_map(self):
        """현재 이미지에 있는 클래스 ID에 대해서만 동적으로 색상을 할당합니다."""
        self.local_color_map = {}
        unique_class_ids = sorted(list({poly['class_id'] for poly in self.canvas.polygons if poly['class_id'] is not None}))
        for i, class_id in enumerate(unique_class_ids):
            self.local_color_map[class_id] = CLASS_COLORS[i % len(CLASS_COLORS)]

    def get_color_for_class_id(self, class_id):
        """주어진 클래스 ID에 대한 색상을 반환합니다."""
        if class_id is None: # 방해 요소는 회색으로 표시
             return QColor(128, 128, 128, 80)
        if class_id not in self.local_color_map:
            # 맵에 없는 새로운 클래스 ID인 경우, 동적으로 추가
            new_color_index = len(self.local_color_map)
            self.local_color_map[class_id] = CLASS_COLORS[new_color_index % len(CLASS_COLORS)]
        return self.local_color_map[class_id]

    def update_hover_status(self, class_id):
        """상태바에 호버된 클래스 정보를 업데이트합니다."""
        if class_id is not None and class_id < len(self.full_class_list):
            class_name = self.full_class_list[class_id]
            self.status_label.setText(f"마우스 오버: {class_name}")
        elif class_id is None and self.canvas.hovered_polygon_idx != -1:
            self.status_label.setText(f"마우스 오버: 방해 요소 후보")
        else:
            self.status_label.setText("준비")

    def toggle_change_mode(self, checked):
        """'클래스 변경' 모드를 켜고 끕니다."""
        self.is_change_mode = checked
        if checked:
            self.canvas.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setWindowTitle("클래스 변경 모드 (변경할 다각형 클릭)")
        else:
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.setWindowTitle('수동 편집기 (변경:C, 지정삭제:D, 완성취소:Z, 초기화:R)')

    def update_class_selector(self, new_class_to_select=None):
        """선택된 카테고리에 맞는 클래스 목록으로 QComboBox를 채웁니다."""
        self.class_selector.blockSignals(True)
        self.class_selector.clear()

        category = self.category_selector.currentText()
        manifest = self.learning_tab.data_manager.get_manifest()
        classes_in_category = list(manifest.get(category, {}).keys())

        self.class_selector.addItems(classes_in_category)
        # '캐릭터' 카테고리는 새 클래스 추가 불가
        if category != CHARACTER_CLASS_NAME:
            self.class_selector.addItem("[새 클래스 추가...]")

        if new_class_to_select and new_class_to_select in classes_in_category:
            self.class_selector.setCurrentText(new_class_to_select)

        self.class_selector.blockSignals(False)

    def set_initial_selection(self, class_name):
        """편집기 시작 시 전달받은 클래스 이름으로 선택자를 설정합니다."""
        if class_name:
            category = self.learning_tab.data_manager.get_class_category(class_name)
            if category:
                self.category_selector.setCurrentText(category)
                self.update_class_selector(new_class_to_select=class_name)
        else:
            self.update_class_selector()

    def handle_class_selection(self, index):
        """'[새 클래스 추가...]'가 선택되면 새 클래스 추가 로직을 실행합니다."""
        if self.class_selector.itemText(index) == "[새 클래스 추가...]":
            category = self.category_selector.currentText()
            new_name, ok = QInputDialog.getText(self, "새 클래스 추가", f"'{category}' 카테고리에 추가할 클래스 이름:")
            if ok and new_name:
                success, message = self.learning_tab.data_manager.add_class(new_name, category)
                if success:
                    self.learning_tab.populate_class_list() # 메인 창 목록 갱신
                    self.full_class_list = self.learning_tab.data_manager.get_class_list() # 전체 목록 갱신
                    self.update_class_selector(new_class_to_select=new_name)
                else:
                    QMessageBox.warning(self, "오류", message)
                    self.class_selector.setCurrentIndex(0)
            else:
                self.class_selector.setCurrentIndex(0)

    def get_current_class_id(self):
        """현재 선택된 클래스의 전체 목록 기준 인덱스를 반환합니다."""
        class_name = self.class_selector.currentText()
        if class_name and class_name != "[새 클래스 추가...]":
            try:
                return self.full_class_list.index(class_name)
            except ValueError:
                return None
        return None

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            if len(self.canvas.current_points) >= 3:
                class_id = self.get_current_class_id()
                if class_id is not None:
                    self.canvas.polygons.append({'class_id': class_id, 'points': list(self.canvas.current_points)})
                    self.canvas.current_points.clear(); self.canvas.update()
        elif event.key() == Qt.Key.Key_Backspace:
            if self.canvas.current_points: self.canvas.current_points.pop(); self.canvas.update()
        elif event.key() == Qt.Key.Key_R:
            if self.canvas.polygons or self.canvas.current_points:
                if QMessageBox.question(self, "초기화", "모든 다각형을 지우시겠습니까?") == QMessageBox.StandardButton.Yes:
                    self.canvas.polygons.clear(); self.canvas.current_points.clear(); self.canvas.update()
        elif event.key() == Qt.Key.Key_Z:
            if self.canvas.polygons: self.canvas.polygons.pop(); self.canvas.update()
        elif event.key() == Qt.Key.Key_D: self.canvas.delete_hovered_polygon()
        elif event.key() == Qt.Key.Key_C:
            self.change_class_btn.setChecked(not self.change_class_btn.isChecked())
        else: super().keyPressEvent(event)

    def on_save(self):
        if len(self.canvas.current_points) >= 3:
            class_id = self.get_current_class_id()
            if class_id is not None:
                self.canvas.polygons.append({'class_id': class_id, 'points': list(self.canvas.current_points)})
                self.canvas.current_points.clear()
        self.accept()

    def get_all_polygons(self): return self.canvas.polygons

# --- 3.5. 위젯: SAM(AI) 편집기 ---
class SAMCanvasLabel(BaseCanvasLabel):
    """AI 어시스트 편집기 전용 캔버스. AI가 예측한 마스크(mask)와 사용자 클릭 포인트를 추가로 그립니다."""
    def __init__(self, pixmap, parent_dialog):
        super().__init__(pixmap, parent_dialog)
        self.current_mask, self.input_points, self.input_labels = None, [], []
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_polygons(painter)

        if self.current_mask is not None:
            class_id = self.parent_dialog.get_current_class_id()
            # if class_id is not None: # v1.3: 클래스 없이도 마스크 미리보기 가능하도록 수정
            # 마스크 영역 채우기
            color = self.parent_dialog.get_color_for_class_id(class_id) # class_id가 None이면 회색 반환
            h, w = self.current_mask.shape
            mask_image = QImage(w, h, QImage.Format.Format_ARGB32)
            mask_image.fill(Qt.GlobalColor.transparent)
            for y in range(h):
                for x in range(w):
                    if self.current_mask[y, x]: mask_image.setPixelColor(x, y, color)
            
            scaled_mask_image = mask_image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
            painter.drawImage(self.rect(), scaled_mask_image)

            # 마스크 외곽선 그리기
            contours, _ = cv2.findContours(self.current_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            painter.setPen(QPen(HIGHLIGHT_PEN_COLOR, 2, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for contour in contours:
                poly_points = [QPoint(p[0][0], p[0][1]) * self.zoom_factor for p in contour]
                painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in poly_points]))

    def mousePressEvent(self, event):
        if self.parent_dialog.is_change_mode and event.button() == Qt.MouseButton.LeftButton:
            if self.change_hovered_polygon_class():
                return

        if event.button() in [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton]:
            self.parent_dialog.predict_mask(event.pos(), 1 if event.button() == Qt.MouseButton.LeftButton else 0)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True; self.pan_start_pos = event.pos(); self.setCursor(Qt.CursorShape.ClosedHandCursor)

class SAMAnnotationEditor(QDialog):
    """AI 어시스트 편집기 메인 창."""
    # v1.3: 방해 요소 저장을 위한 커스텀 결과 코드 정의
    DistractorSaved = 100
    
    def __init__(self, pixmap, predictor, initial_polygons=None, parent=None, initial_class_name=None):
        super().__init__(parent)
        self.setWindowTitle('AI 어시스트 (변경:C, 지정삭제:D, 완성취소:Z, 초기화:R)')
        self.learning_tab = parent
        self.is_change_mode = False
        self.predictor, self.pixmap = predictor, pixmap
        q_image = self.pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        w, h = q_image.width(), q_image.height()
        ptr = q_image.bits(); ptr.setsize(q_image.sizeInBytes())
        arr = np.array(ptr).reshape(h, q_image.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
        self.image_np = arr
        self.predictor.set_image(self.image_np)
        self.canvas = SAMCanvasLabel(pixmap, self)
        self.canvas.polygons = initial_polygons if initial_polygons else []
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.canvas); self.scroll_area.setWidgetResizable(True)
        main_layout = QVBoxLayout()
        top_controls_layout = QHBoxLayout()

        left_controls_layout = QHBoxLayout()
        self.zoom_1x_btn = QPushButton("1x")
        self.zoom_1_5x_btn = QPushButton("1.5x")
        self.zoom_2x_btn = QPushButton("2x")
        self.zoom_1x_btn.clicked.connect(lambda: self.canvas.set_zoom(1.0))
        self.zoom_1_5x_btn.clicked.connect(lambda: self.canvas.set_zoom(1.5))
        self.zoom_2x_btn.clicked.connect(lambda: self.canvas.set_zoom(2.0))
        left_controls_layout.addWidget(QLabel("확대:"))
        left_controls_layout.addWidget(self.zoom_1x_btn)
        left_controls_layout.addWidget(self.zoom_1_5x_btn)
        left_controls_layout.addWidget(self.zoom_2x_btn)
        left_controls_layout.addSpacing(20)

        self.change_class_btn = QPushButton("클래스 변경 (C)")
        self.change_class_btn.setCheckable(True)
        self.change_class_btn.toggled.connect(self.toggle_change_mode)
        left_controls_layout.addWidget(self.change_class_btn)

        class_selection_layout = QHBoxLayout()
        class_selection_layout.addWidget(QLabel("카테고리:"))
        self.category_selector = QComboBox()
        self.category_selector.addItems(CATEGORIES)
        self.category_selector.currentIndexChanged.connect(self.update_class_selector)
        class_selection_layout.addWidget(self.category_selector)

        class_selection_layout.addWidget(QLabel("클래스:"))
        self.class_selector = QComboBox()
        self.class_selector.activated.connect(self.handle_class_selection)
        class_selection_layout.addWidget(self.class_selector)

        top_controls_layout.addLayout(left_controls_layout); top_controls_layout.addStretch(1); top_controls_layout.addLayout(class_selection_layout)

        self.status_bar = QStatusBar()
        self.status_label = QLabel("준비")
        self.status_bar.addWidget(self.status_label)

        # v1.3: 버튼 박스 수정
        self.button_box = QDialogButtonBox()
        self.save_button = self.button_box.addButton("저장", QDialogButtonBox.ButtonRole.AcceptRole)
        self.distractor_button = self.button_box.addButton("방해 요소로 저장", QDialogButtonBox.ButtonRole.ActionRole)
        self.cancel_button = self.button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.distractor_button.clicked.connect(self.on_save_distractor)
        self.button_box.rejected.connect(self.reject)

        main_layout.addLayout(top_controls_layout)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.status_bar)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        new_width = min(pixmap.width() + 50, int(screen_geometry.width() * 0.9))
        new_height = min(pixmap.height() + 150, int(screen_geometry.height() * 0.9))
        self.resize(new_width, new_height)

        self.full_class_list = self.learning_tab.data_manager.get_class_list()
        self.create_local_color_map()
        self.set_initial_selection(initial_class_name)
        self.setFocus()

    # v1.3: 방해 요소 저장 슬롯
    def on_save_distractor(self):
        """'방해 요소로 저장' 버튼 클릭 시 호출됩니다."""
        if self.canvas.current_mask is not None:
            contours, _ = cv2.findContours(self.canvas.current_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                largest_contour = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest_contour) > 10:
                    poly_points = [QPoint(p[0][0], p[0][1]) for p in largest_contour]
                    # 방해 요소는 클래스 ID가 None
                    self.canvas.polygons.append({'class_id': None, 'points': poly_points})
                    self.reset_current_mask()
        
        if not self.canvas.polygons:
            QMessageBox.warning(self, "오류", "방해 요소로 지정할 다각형이 없습니다.")
            return

        self.done(self.DistractorSaved)

    def create_local_color_map(self):
        """현재 이미지에 있는 클래스 ID에 대해서만 동적으로 색상을 할당합니다."""
        self.local_color_map = {}
        unique_class_ids = sorted(list({poly['class_id'] for poly in self.canvas.polygons if poly['class_id'] is not None}))
        for i, class_id in enumerate(unique_class_ids):
            self.local_color_map[class_id] = CLASS_COLORS[i % len(CLASS_COLORS)]

    def get_color_for_class_id(self, class_id):
        """주어진 클래스 ID에 대한 색상을 반환합니다."""
        if class_id is None: # 방해 요소는 회색으로 표시
             return QColor(128, 128, 128, 80)
        if class_id not in self.local_color_map:
            # 맵에 없는 새로운 클래스 ID인 경우, 동적으로 추가
            new_color_index = len(self.local_color_map)
            self.local_color_map[class_id] = CLASS_COLORS[new_color_index % len(CLASS_COLORS)]
        return self.local_color_map[class_id]

    def update_hover_status(self, class_id):
        """상태바에 호버된 클래스 정보를 업데이트합니다."""
        if class_id is not None and class_id < len(self.full_class_list):
            class_name = self.full_class_list[class_id]
            self.status_label.setText(f"마우스 오버: {class_name}")
        elif class_id is None and self.canvas.hovered_polygon_idx != -1:
            self.status_label.setText(f"마우스 오버: 방해 요소 후보")
        else:
            self.status_label.setText("준비")

    def toggle_change_mode(self, checked):
        """'클래스 변경' 모드를 켜고 끕니다."""
        self.is_change_mode = checked
        if checked:
            self.canvas.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setWindowTitle("클래스 변경 모드 (변경할 다각형 클릭)")
        else:
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.setWindowTitle('AI 어시스트 (변경:C, 지정삭제:D, 완성취소:Z, 초기화:R)')

    def update_class_selector(self, new_class_to_select=None):
        """선택된 카테고리에 맞는 클래스 목록으로 QComboBox를 채웁니다."""
        self.class_selector.blockSignals(True)
        self.class_selector.clear()

        category = self.category_selector.currentText()
        manifest = self.learning_tab.data_manager.get_manifest()
        classes_in_category = list(manifest.get(category, {}).keys())

        self.class_selector.addItems(classes_in_category)
        if category != CHARACTER_CLASS_NAME:
            self.class_selector.addItem("[새 클래스 추가...]")

        if new_class_to_select and new_class_to_select in classes_in_category:
            self.class_selector.setCurrentText(new_class_to_select)

        self.class_selector.blockSignals(False)

    def set_initial_selection(self, class_name):
        """편집기 시작 시 전달받은 클래스 이름으로 선택자를 설정합니다."""
        if class_name:
            category = self.learning_tab.data_manager.get_class_category(class_name)
            if category:
                self.category_selector.setCurrentText(category)
                self.update_class_selector(new_class_to_select=class_name)
        else:
            self.update_class_selector()

    def handle_class_selection(self, index):
        """'[새 클래스 추가...]'가 선택되면 새 클래스 추가 로직을 실행합니다."""
        if self.class_selector.itemText(index) == "[새 클래스 추가...]":
            category = self.category_selector.currentText()
            new_name, ok = QInputDialog.getText(self, "새 클래스 추가", f"'{category}' 카테고리에 추가할 클래스 이름:")
            if ok and new_name:
                success, message = self.learning_tab.data_manager.add_class(new_name, category)
                if success:
                    self.learning_tab.populate_class_list()
                    self.full_class_list = self.learning_tab.data_manager.get_class_list()
                    self.update_class_selector(new_class_to_select=new_name)
                else:
                    QMessageBox.warning(self, "오류", message)
                    self.class_selector.setCurrentIndex(0)
            else:
                self.class_selector.setCurrentIndex(0)

    def get_current_class_id(self):
        """현재 선택된 클래스의 전체 목록 기준 인덱스를 반환합니다."""
        class_name = self.class_selector.currentText()
        if class_name and class_name != "[새 클래스 추가...]":
            try:
                return self.full_class_list.index(class_name)
            except ValueError:
                return None
        return None

    def predict_mask(self, pos, label):
        zoom_factor = self.canvas.zoom_factor if self.canvas.zoom_factor > 0 else 1.0
        self.canvas.input_points.append(pos / zoom_factor)
        self.canvas.input_labels.append(label)
        input_points_np = np.array([[p.x(), p.y()] for p in self.canvas.input_points])
        input_labels_np = np.array(self.canvas.input_labels)
        masks, _, _ = self.predictor.predict(point_coords=input_points_np, point_labels=input_labels_np, multimask_output=False)
        self.canvas.current_mask = masks[0]
        self.canvas.update()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            if self.canvas.current_mask is not None:
                class_id = self.get_current_class_id()
                if class_id is not None:
                    contours, _ = cv2.findContours(self.canvas.current_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if contours:
                        largest_contour = max(contours, key=cv2.contourArea)
                        if cv2.contourArea(largest_contour) > 10:
                            poly_points = [QPoint(p[0][0], p[0][1]) for p in largest_contour]
                            self.canvas.polygons.append({'class_id': class_id, 'points': poly_points})
                            self.reset_current_mask()
        elif event.key() == Qt.Key.Key_R: self.reset_current_mask()
        elif event.key() == Qt.Key.Key_Z:
            if self.canvas.polygons: self.canvas.polygons.pop(); self.canvas.update()
        elif event.key() == Qt.Key.Key_D: self.canvas.delete_hovered_polygon()
        elif event.key() == Qt.Key.Key_C:
            self.change_class_btn.setChecked(not self.change_class_btn.isChecked())
        else: super().keyPressEvent(event)

    def reset_current_mask(self):
        self.canvas.current_mask = None; self.canvas.input_points.clear(); self.canvas.input_labels.clear(); self.canvas.update()

    def get_all_polygons(self): return self.canvas.polygons

# --- 4. 위젯: 편집 모드 및 다중 캡처 선택 ---
class EditModeDialog(QDialog):
    AI_ASSIST, MANUAL, CANCEL = 1, 2, 0
    def __init__(self, pixmap, sam_ready, parent=None):
        super().__init__(parent)
        self.setWindowTitle("편집 모드 선택")
        self.image_label = QLabel()
        self.image_label.setPixmap(pixmap.scaled(640, 480, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.ai_button = QPushButton("AI 어시스트 편집")
        self.ai_button.clicked.connect(self.on_ai_assist)
        if not sam_ready:
            self.ai_button.setEnabled(False)
            self.ai_button.setToolTip("SAM 모델이 로드 중이거나 설치되지 않았습니다.")
        self.manual_button = QPushButton("수동 다각형 편집")
        self.manual_button.clicked.connect(self.on_manual)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.ai_button)
        button_layout.addWidget(self.manual_button)
        button_layout.addWidget(self.cancel_button)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.image_label)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
    def on_ai_assist(self): self.done(self.AI_ASSIST)
    def on_manual(self): self.done(self.MANUAL)
    def on_cancel(self): self.done(self.CANCEL)

class MultiCaptureDialog(QDialog):
    def __init__(self, pixmaps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("편집할 이미지 선택")
        self.pixmaps = pixmaps
        self.image_list_widget = QListWidget()
        self.image_list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_list_widget.setIconSize(QSize(160, 120))
        self.image_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for i, pixmap in enumerate(pixmaps):
            item = QListWidgetItem(QIcon(pixmap), f"캡처 {i+1}")
            self.image_list_widget.addItem(item)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.image_list_widget)
        main_layout.addWidget(buttons)
        self.setLayout(main_layout)
        self.resize(800, 600)

    def get_selected_pixmaps(self):
        selected_pixmaps = []
        for item in self.image_list_widget.selectedItems():
            row = self.image_list_widget.row(item)
            selected_pixmaps.append(self.pixmaps[row])
        return selected_pixmaps

# --- 5. 핵심 로직 클래스 (백엔드) ---
class DataManager:
    def __init__(self, workspace_root):
        # (v1.2) 모든 경로는 workspace_root를 기준으로 설정됩니다.
        self.workspace_root = workspace_root
        self.dataset_path = os.path.join(self.workspace_root, 'datasets', 'maple_dataset')
        self.images_path = os.path.join(self.dataset_path, 'images')
        self.labels_path = os.path.join(self.dataset_path, 'labels')
        self.manifest_path = os.path.join(self.dataset_path, 'manifest.json')
        self.yaml_path = os.path.join(self.dataset_path, 'data.yaml')
        self.models_path = os.path.join(self.workspace_root, 'models')
        self.config_path = os.path.join(self.workspace_root, 'config')
        self.presets_path = os.path.join(self.config_path, 'presets.json')
        self.settings_path = os.path.join(self.config_path, 'settings.json') # 설정 파일 경로 추가
        self.nickname_dir = os.path.join(self.config_path, 'nickname')
        self.nickname_templates_dir = os.path.join(self.nickname_dir, 'templates')
        self.nickname_config_path = os.path.join(self.nickname_dir, 'config.json')
        self.direction_dir = os.path.join(self.config_path, 'direction')
        self.direction_templates_dir = os.path.join(self.direction_dir, 'templates')
        self.direction_left_dir = os.path.join(self.direction_templates_dir, 'left')
        self.direction_right_dir = os.path.join(self.direction_templates_dir, 'right')
        self.direction_config_path = os.path.join(self.direction_dir, 'config.json')
        self.nameplate_dir = os.path.join(self.config_path, 'monster_nameplate')
        self.nameplate_templates_dir = os.path.join(self.nameplate_dir, 'templates')
        self.nameplate_config_path = os.path.join(self.nameplate_dir, 'config.json')
        self.status_config_path = os.path.join(self.config_path, 'status_monitor.json')
        self._overlay_listeners: list = []
        self._model_listeners: list[callable] = []
        self._last_used_model: Optional[str] = None
        self.status_config_notifier = StatusConfigNotifier()
        self.key_mappings_path = self._resolve_key_mappings_path()
        self.ensure_dirs_and_files()
        self.migrate_manifest_if_needed()
        settings = self.load_settings()
        if isinstance(settings, dict):
            model = settings.get('last_used_model') or settings.get('model')
            if isinstance(model, str) and model.strip():
                self._last_used_model = model.strip()
        self._prune_monster_confidence_overrides()

    def ensure_dirs_and_files(self):
        os.makedirs(self.images_path, exist_ok=True)
        os.makedirs(self.labels_path, exist_ok=True)
        os.makedirs(self.models_path, exist_ok=True)
        os.makedirs(self.config_path, exist_ok=True)
        os.makedirs(self.nickname_dir, exist_ok=True)
        os.makedirs(self.nickname_templates_dir, exist_ok=True)
        os.makedirs(self.direction_dir, exist_ok=True)
        os.makedirs(self.direction_templates_dir, exist_ok=True)
        os.makedirs(self.direction_left_dir, exist_ok=True)
        os.makedirs(self.direction_right_dir, exist_ok=True)
        os.makedirs(self.nameplate_dir, exist_ok=True)
        os.makedirs(self.nameplate_templates_dir, exist_ok=True)
        # v1.3: manifest 생성/확인 시 네거티브 샘플 항목 추가
        if not os.path.exists(self.manifest_path):
            initial_manifest = {category: {} for category in CATEGORIES}
            initial_manifest[NEGATIVE_SAMPLES_NAME] = []
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(initial_manifest, f, indent=4, ensure_ascii=False)
        else:
            try:
                with open(self.manifest_path, 'r+', encoding='utf-8') as f:
                    manifest = json.load(f)
                    if NEGATIVE_SAMPLES_NAME not in manifest:
                        manifest[NEGATIVE_SAMPLES_NAME] = []
                        f.seek(0)
                        json.dump(manifest, f, indent=4, ensure_ascii=False)
                        f.truncate()
            except (json.JSONDecodeError, FileNotFoundError):
                 # 파일이 비어있거나 손상된 경우 새로 생성
                initial_manifest = {category: {} for category in CATEGORIES}
                initial_manifest[NEGATIVE_SAMPLES_NAME] = []
                with open(self.manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(initial_manifest, f, indent=4, ensure_ascii=False)
        if not os.path.exists(self.presets_path):
            with open(self.presets_path, 'w', encoding='utf-8') as f: json.dump({}, f)
        if not os.path.exists(self.settings_path):
            with open(self.settings_path, 'w', encoding='utf-8') as f: json.dump({}, f)
        # 닉네임 템플릿 설정 초기화
        default_nickname_config = self._default_nickname_config()
        if not os.path.exists(self.nickname_config_path):
            self._write_nickname_config(default_nickname_config)
        else:
            try:
                with open(self.nickname_config_path, 'r', encoding='utf-8') as f:
                    nickname_config = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._write_nickname_config(default_nickname_config)
            else:
                changed = False
                for key, value in default_nickname_config.items():
                    if key not in nickname_config:
                        nickname_config[key] = value if key != 'templates' else list(value)
                        changed = True
                if changed:
                    self._write_nickname_config(nickname_config)
        default_direction_config = self._default_direction_config()
        if not os.path.exists(self.direction_config_path):
            direction_config = default_direction_config
            self._write_direction_config(direction_config)
        else:
            try:
                with open(self.direction_config_path, 'r', encoding='utf-8') as f:
                    loaded_direction_config = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                direction_config = default_direction_config
                self._write_direction_config(direction_config)
            else:
                direction_config, changed = self._merge_direction_config(loaded_direction_config)
                if changed:
                    self._write_direction_config(direction_config)
        default_nameplate_config = self._default_nameplate_config()
        if not os.path.exists(self.nameplate_config_path):
            self._write_nameplate_config(default_nameplate_config)
        else:
            try:
                with open(self.nameplate_config_path, 'r', encoding='utf-8') as f:
                    loaded_nameplate_config = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._write_nameplate_config(default_nameplate_config)
            else:
                merged_nameplate, changed = self._merge_nameplate_config(loaded_nameplate_config)
                if changed:
                    self._write_nameplate_config(merged_nameplate)
        status_default = StatusMonitorConfig.default()
        if not os.path.exists(self.status_config_path):
            self._write_status_config(status_default)
        else:
            try:
                with open(self.status_config_path, 'r', encoding='utf-8') as f:
                    json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._write_status_config(status_default)

    def _default_nickname_config(self):
        return {
            "target_text": "버프몬",
            "match_threshold": 0.72,
            "char_offset_x": 0,
            "char_offset_y": 46,
            "search_margin_x": 210,
            "search_margin_top": 100,
            "search_margin_bottom": 100,
            "full_scan_delay_sec": 1.0,
            "show_overlay": True,
            "templates": [],
        }

    def _write_nickname_config(self, config_data):
        with open(self.nickname_config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

    def _default_direction_config(self):
        return {
            'match_threshold': 0.72,
            'search_offset_y': 60.0,
            'search_height': 20.0,
            'search_half_width': 30.0,
            'show_overlay': True,
            'templates_left': [],
            'templates_right': [],
        }

    def _write_direction_config(self, config_data):
        with open(self.direction_config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

    def _merge_direction_config(self, loaded_config):
        default_config = self._default_direction_config()
        if not isinstance(loaded_config, dict):
            return default_config, True
        merged = dict(loaded_config)
        changed = False
        for key, value in default_config.items():
            if key not in merged:
                merged[key] = value if key not in {'templates_left', 'templates_right'} else list(value)
                changed = True
        for side_key in ('templates_left', 'templates_right'):
            if not isinstance(merged.get(side_key), list):
                merged[side_key] = []
                changed = True
        return merged, changed

    def _default_nameplate_config(self):
        return {
            'enabled': False,
            'show_overlay': True,
            'match_threshold': 0.60,
            'roi': {
                'width': 135,
                'height': 65,
                'offset_x': 0,
                'offset_y': 0,
            },
            'dead_zone_sec': 0.20,
            'track_missing_grace_sec': 0.12,
            'per_class': {},
        }

    def _write_nameplate_config(self, config_data):
        with open(self.nameplate_config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

    def _merge_nameplate_config(self, loaded_config):
        default_config = self._default_nameplate_config()
        if not isinstance(loaded_config, dict):
            return default_config, True
        merged = dict(loaded_config)
        changed = False
        if 'enabled' not in merged:
            merged['enabled'] = default_config['enabled']
            changed = True
        if 'show_overlay' not in merged:
            merged['show_overlay'] = default_config['show_overlay']
            changed = True
        if 'match_threshold' not in merged:
            merged['match_threshold'] = default_config['match_threshold']
            changed = True
        if 'dead_zone_sec' not in merged:
            merged['dead_zone_sec'] = default_config['dead_zone_sec']
            changed = True
        if 'track_missing_grace_sec' not in merged:
            merged['track_missing_grace_sec'] = default_config['track_missing_grace_sec']
            changed = True
        roi = merged.get('roi') if isinstance(merged.get('roi'), dict) else None
        if roi is None:
            merged['roi'] = dict(default_config['roi'])
            changed = True
        else:
            roi_changed = False
            for key, value in default_config['roi'].items():
                if key not in roi:
                    roi[key] = value
                    roi_changed = True
            if roi_changed:
                merged['roi'] = roi
                changed = True
        if not isinstance(merged.get('per_class'), dict):
            merged['per_class'] = {}
            changed = True
        else:
            per_class = merged['per_class']
            for class_name, entry in list(per_class.items()):
                if not isinstance(entry, dict):
                    per_class[class_name] = {'templates': []}
                    changed = True
                    continue
                if 'templates' not in entry or not isinstance(entry['templates'], list):
                    entry['templates'] = []
                    changed = True
                if 'threshold' in entry and entry['threshold'] is not None:
                    try:
                        entry['threshold'] = float(entry['threshold'])
                    except (TypeError, ValueError):
                        entry['threshold'] = None
                        changed = True
        return merged, changed

    def _ensure_nameplate_class_entry(self, config: dict, class_name: str):
        if not isinstance(config, dict):
            config = self._default_nameplate_config()
        per_class = config.setdefault('per_class', {})
        entry = per_class.get(class_name)
        changed = False
        if not isinstance(entry, dict):
            entry = {}
            changed = True
        templates = entry.get('templates') if isinstance(entry.get('templates'), list) else None
        if templates is None:
            entry['templates'] = []
            changed = True
        if 'threshold' in entry and entry['threshold'] is not None:
            try:
                entry['threshold'] = float(entry['threshold'])
            except (TypeError, ValueError):
                entry['threshold'] = None
                changed = True
        per_class[class_name] = entry
        return entry, changed

    def _resolve_nameplate_templates(self, config: dict, class_name: str):
        entry, changed = self._ensure_nameplate_class_entry(config, class_name)
        templates = entry.get('templates', [])
        resolved_templates = []
        retained_templates = []
        for template in templates:
            if not isinstance(template, dict):
                changed = True
                continue
            template_id = template.get('id')
            filename = template.get('filename')
            if not template_id or not filename:
                changed = True
                continue
            path = os.path.join(self.nameplate_templates_dir, filename)
            if not os.path.exists(path):
                changed = True
                continue
            resolved_entry = dict(template)
            resolved_entry['path'] = path
            resolved_templates.append(resolved_entry)
            retained_templates.append(template)
        if len(retained_templates) != len(templates):
            entry['templates'] = retained_templates
            changed = True
        return resolved_templates, changed

    def get_monster_nameplate_config(self):
        try:
            with open(self.nameplate_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            config = self._default_nameplate_config()
            self._write_nameplate_config(config)
            return config
        config, changed = self._merge_nameplate_config(config)
        if changed:
            self._write_nameplate_config(config)
        return config

    def update_monster_nameplate_config(self, updates: dict):
        if not isinstance(updates, dict):
            return self.get_monster_nameplate_config()
        config = self.get_monster_nameplate_config()
        changed = False

        if 'enabled' in updates:
            new_state = bool(updates['enabled'])
            if config.get('enabled') != new_state:
                config['enabled'] = new_state
                changed = True

        if 'show_overlay' in updates:
            new_overlay = bool(updates['show_overlay'])
            if config.get('show_overlay') != new_overlay:
                config['show_overlay'] = new_overlay
                changed = True

        if 'match_threshold' in updates:
            try:
                threshold = float(updates['match_threshold'])
                threshold = max(0.10, min(0.99, threshold))
            except (TypeError, ValueError):
                threshold = config.get('match_threshold', self._default_nameplate_config()['match_threshold'])
            if abs(config.get('match_threshold', 0.0) - threshold) > 1e-6:
                config['match_threshold'] = threshold
                changed = True

        if 'dead_zone_sec' in updates:
            try:
                dz_value = float(updates['dead_zone_sec'])
            except (TypeError, ValueError):
                dz_value = config.get('dead_zone_sec', self._default_nameplate_config()['dead_zone_sec'])
            dz_value = max(0.0, min(2.0, dz_value))
            if abs(config.get('dead_zone_sec', 0.0) - dz_value) > 1e-6:
                config['dead_zone_sec'] = dz_value
                changed = True

        if 'track_missing_grace_sec' in updates:
            try:
                grace_value = float(updates['track_missing_grace_sec'])
            except (TypeError, ValueError):
                grace_value = config.get(
                    'track_missing_grace_sec', self._default_nameplate_config()['track_missing_grace_sec']
                )
            grace_value = max(0.0, min(2.0, grace_value))
            if abs(config.get('track_missing_grace_sec', 0.0) - grace_value) > 1e-6:
                config['track_missing_grace_sec'] = grace_value
                changed = True

        if 'roi' in updates and isinstance(updates['roi'], dict):
            roi = dict(config.get('roi', {}))
            roi_updates = updates['roi']
            roi_changed = False
            for key in ('width', 'height', 'offset_x', 'offset_y'):
                if key not in roi_updates:
                    continue
                try:
                    value = int(roi_updates[key])
                except (TypeError, ValueError):
                    continue
                if key in {'width', 'height'}:
                    value = max(1, value)
                if roi.get(key) != value:
                    roi[key] = value
                    roi_changed = True
            if roi_changed:
                config['roi'] = roi
                changed = True

        if changed:
            self._write_nameplate_config(config)
        self._notify_overlay_listeners({
            'target': 'monster_nameplate',
            'show_overlay': bool(config.get('show_overlay', True)),
            'enabled': bool(config.get('enabled', False)),
            'roi': dict(config.get('roi', {})),
            'match_threshold': float(config.get('match_threshold', 0.60)),
            'dead_zone_sec': float(config.get('dead_zone_sec', 0.20)),
            'track_missing_grace_sec': float(config.get('track_missing_grace_sec', 0.12)),
        })
        return config

    def get_monster_nameplate_entry(self, class_name: str):
        config = self.get_monster_nameplate_config()
        entry, entry_changed = self._ensure_nameplate_class_entry(config, class_name)
        resolved, templates_changed = self._resolve_nameplate_templates(config, class_name)
        if entry_changed or templates_changed:
            self._write_nameplate_config(config)
        result = {
            'threshold': entry.get('threshold'),
            'templates': resolved,
        }
        return result

    def list_monster_nameplate_templates(self, class_name: str):
        config = self.get_monster_nameplate_config()
        resolved, changed = self._resolve_nameplate_templates(config, class_name)
        if changed:
            self._write_nameplate_config(config)
        return resolved

    def _preprocess_nameplate_image(self, image: np.ndarray) -> np.ndarray:
        if image is None or not hasattr(image, 'ndim'):
            raise ValueError('유효한 이미지가 필요합니다.')

        alpha = None
        if image.ndim == 3 and image.shape[2] == 4:
            alpha = image[:, :, 3]
            bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim == 3 and image.shape[2] == 3:
            bgr = image
        elif image.ndim == 2:
            bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            raise ValueError('지원하지 않는 이름표 이미지 형식입니다.')

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        mask = None
        if alpha is not None:
            mask = alpha > 0
            if np.count_nonzero(mask) == 0:
                mask = None
        if mask is not None:
            gray = gray.copy()
            gray[~mask] = 255
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if mask is not None:
            thresh[~mask] = 0

        # ensure text pixels are white (255)
        fg_mean = np.mean(thresh[thresh > 0]) if np.any(thresh > 0) else 255
        bg_mean = np.mean(thresh[thresh == 0]) if np.any(thresh == 0) else 0
        if fg_mean < bg_mean:
            thresh = cv2.bitwise_not(thresh)
        if mask is not None:
            thresh[~mask] = 0

        # slight dilation to stabilize thin fonts
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.dilate(thresh, kernel, iterations=1)
        return thresh

    def add_monster_nameplate_template(self, class_name: str, image_bgr, *, source='import', original_name=None):
        if image_bgr is None or not hasattr(image_bgr, 'shape'):
            raise ValueError('유효한 이미지 배열이 필요합니다.')

        processed = self._preprocess_nameplate_image(image_bgr)

        template_id = f"np_{int(time.time()*1000)%1_000_000:06d}_{uuid.uuid4().hex[:6]}"
        filename = f"{template_id}.png"
        save_path = os.path.join(self.nameplate_templates_dir, filename)
        if not cv2.imwrite(save_path, processed):
            raise IOError('몬스터 이름표 템플릿을 저장하지 못했습니다.')

        config = self.get_monster_nameplate_config()
        entry, entry_changed = self._ensure_nameplate_class_entry(config, class_name)
        template_entry = {
            'id': template_id,
            'filename': filename,
            'source': source,
            'original_name': original_name,
            'created_at': time.time(),
            'width': int(processed.shape[1]),
            'height': int(processed.shape[0]),
        }
        entry['templates'].append(template_entry)
        config['per_class'][class_name] = entry
        self._write_nameplate_config(config)
        template_entry_with_path = dict(template_entry)
        template_entry_with_path['path'] = save_path
        return template_entry_with_path

    def import_monster_nameplate_template(self, class_name: str, file_path: str):
        if not file_path:
            raise ValueError('파일 경로가 필요합니다.')
        image = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise IOError(f"이미지를 불러올 수 없습니다: {file_path}")
        return self.add_monster_nameplate_template(
            class_name,
            image,
            source='import',
            original_name=os.path.basename(file_path),
        )

    def delete_monster_nameplate_templates(self, class_name: str, template_ids):
        if not template_ids:
            return 0
        if isinstance(template_ids, str):
            template_ids = [template_ids]
        template_ids = set(template_ids)

        config = self.get_monster_nameplate_config()
        entry, entry_changed = self._ensure_nameplate_class_entry(config, class_name)
        templates = entry.get('templates', [])
        remaining = []
        removed_count = 0
        for template in templates:
            template_id = template.get('id')
            if template_id in template_ids:
                filename = template.get('filename')
                if filename:
                    path = os.path.join(self.nameplate_templates_dir, filename)
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                removed_count += 1
            else:
                remaining.append(template)
        if removed_count or entry_changed:
            entry['templates'] = remaining
            config['per_class'][class_name] = entry
            self._write_nameplate_config(config)
        return removed_count

    def set_monster_nameplate_threshold(self, class_name: str, threshold: Optional[float]):
        config = self.get_monster_nameplate_config()
        entry, entry_changed = self._ensure_nameplate_class_entry(config, class_name)
        new_value: Optional[float]
        if threshold is None:
            new_value = None
        else:
            try:
                new_value = float(threshold)
            except (TypeError, ValueError):
                new_value = None
            else:
                new_value = max(0.10, min(0.99, new_value))
        if entry.get('threshold') != new_value or entry_changed:
            if new_value is None and 'threshold' in entry:
                entry.pop('threshold', None)
            elif new_value is not None:
                entry['threshold'] = new_value
            config['per_class'][class_name] = entry
            self._write_nameplate_config(config)
        return new_value

    def get_monster_nameplate_threshold(self, class_name: str) -> Optional[float]:
        config = self.get_monster_nameplate_config()
        entry, entry_changed = self._ensure_nameplate_class_entry(config, class_name)
        if entry_changed:
            self._write_nameplate_config(config)
        return entry.get('threshold')

    def clear_monster_nameplate_templates(self, class_name: str):
        config = self.get_monster_nameplate_config()
        entry, _ = self._ensure_nameplate_class_entry(config, class_name)
        for template in entry.get('templates', []):
            filename = template.get('filename')
            if not filename:
                continue
            path = os.path.join(self.nameplate_templates_dir, filename)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        entry['templates'] = []
        config['per_class'][class_name] = entry
        self._write_nameplate_config(config)

    def get_monster_nameplate_resources(self):
        config = self.get_monster_nameplate_config()
        per_class = config.get('per_class', {})
        resolved = {}
        changed = False
        for class_name in list(per_class.keys()):
            templates, entry_changed = self._resolve_nameplate_templates(config, class_name)
            resolved[class_name] = templates
            if entry_changed:
                changed = True
        if changed:
            self._write_nameplate_config(config)
        return config, resolved

    def register_overlay_listener(self, callback):
        if callable(callback) and callback not in self._overlay_listeners:
            self._overlay_listeners.append(callback)

    def unregister_overlay_listener(self, callback):
        if callback in self._overlay_listeners:
            self._overlay_listeners.remove(callback)

    def register_model_listener(self, callback):
        if callable(callback) and callback not in self._model_listeners:
            self._model_listeners.append(callback)

    def unregister_model_listener(self, callback):
        if callback in self._model_listeners:
            self._model_listeners.remove(callback)

    def _notify_model_listeners(self, model_name: Optional[str]) -> None:
        for callback in list(self._model_listeners):
            try:
                callback(model_name)
            except Exception:
                continue

    def _notify_overlay_listeners(self, payload: dict) -> None:
        for callback in list(self._overlay_listeners):
            try:
                callback(payload)
            except Exception:
                continue

    def migrate_manifest_if_needed(self):
        """이전 버전의 manifest.json(플랫 구조)을 새 계층 구조로 자동 변환합니다."""
        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return # 파일이 비어있거나 없으면 마이그레이션 불필요

        # manifest의 첫 번째 값 유형을 확인하여 이전 버전인지 판단
        # 이전 버전: {"클래스이름": ["이미지1.png", ...]} -> 값이 list
        # 새 버전:   {"카테고리": {"클래스이름": ["이미지1.png", ...], ...}} -> 값이 dict
        first_value = next(iter(manifest.values()), None)
        if first_value is None or isinstance(first_value, list):
            print("이전 버전 manifest.json 감지. 새 구조로 마이그레이션을 시작합니다.")
            new_manifest = {category: {} for category in CATEGORIES}
            for class_name, image_list in manifest.items():
                # '캐릭터'는 '캐릭터' 카테고리로, 나머지는 '기타' 카테고리로 이동
                target_category = CHARACTER_CLASS_NAME if class_name == CHARACTER_CLASS_NAME else "기타"
                new_manifest[target_category][class_name] = image_list
            # v1.3: 마이그레이션 시 네거티브 샘플 키 추가
            new_manifest[NEGATIVE_SAMPLES_NAME] = []
            self.save_manifest(new_manifest)
            print("마이그레이션 완료.")

    def get_manifest(self):
        with open(self.manifest_path, 'r', encoding='utf-8') as f: return json.load(f)

    def save_manifest(self, manifest):
        with open(self.manifest_path, 'w', encoding='utf-8') as f: json.dump(manifest, f, indent=4, ensure_ascii=False)

    def get_presets(self):
        with open(self.presets_path, 'r', encoding='utf-8') as f: return json.load(f)

    def save_presets(self, presets):
        with open(self.presets_path, 'w', encoding='utf-8') as f: json.dump(presets, f, indent=4, ensure_ascii=False)

    def get_class_list(self):
        """사용자가 UI에서 정한 순서 그대로 모든 클래스를 리스트로 반환합니다."""
        manifest = self.get_manifest()
        all_classes = []
        for category in CATEGORIES:
            # manifest.json에 저장된 순서(dict key 순서)를 그대로 사용
            class_names_in_category = list(manifest.get(category, {}).keys())
            all_classes.extend(class_names_in_category)
        return all_classes

    def get_class_category(self, class_name):
        """주어진 클래스 이름이 속한 카테고리를 찾습니다."""
        manifest = self.get_manifest()
        for category, classes in manifest.items():
            if category in CATEGORIES and class_name in classes:
                return category
        return None

    def rename_class(self, old_name, new_name):
        manifest = self.get_manifest()

        # 새 이름이 이미 다른 클래스에 의해 사용되고 있는지 확인
        if any(new_name in classes for classes in manifest.values() if isinstance(classes, dict)):
             return False, "이름 변경 불가: 새 이름이 이미 존재합니다."

        category = self.get_class_category(old_name)
        if not category:
            return False, "이름 변경 불가: 이전 이름을 찾을 수 없습니다."

        old_class_list = self.get_class_list()

        # manifest에서 이름 변경 (순서 유지를 위해 새 dict 생성)
        new_ordered_classes = {}
        for name, data in manifest[category].items():
            if name == old_name:
                new_ordered_classes[new_name] = data
            else:
                new_ordered_classes[name] = data
        manifest[category] = new_ordered_classes

        self.save_manifest(manifest)

        new_class_list = self.get_class_list()

        # 프리셋 업데이트
        presets = self.get_presets()
        for preset_name, class_list in presets.items():
            if old_name in class_list:
                presets[preset_name] = [new_name if name == old_name else name for name in class_list]
        self.save_presets(presets)

        overrides = self.get_monster_confidence_overrides()
        if old_name in overrides:
            overrides[new_name] = overrides.pop(old_name)
            self.save_settings({'monster_confidence_overrides': overrides})

        nameplate_config = self.get_monster_nameplate_config()
        per_class = nameplate_config.get('per_class', {})
        if old_name in per_class:
            per_class[new_name] = per_class.pop(old_name)
            self._write_nameplate_config(nameplate_config)

        # 라벨 파일의 클래스 인덱스 업데이트
        try:
            old_idx = old_class_list.index(old_name)
        except ValueError:
            # 이름이 바뀌기 전 리스트에 old_name이 없는 경우는 거의 없지만, 안전장치
            return True, "이름 변경 완료. (라벨 파일 업데이트 불필요)"

        try:
            new_idx = new_class_list.index(new_name)
        except ValueError:
             return False, "클래스 리스트에서 새 인덱스를 찾지 못했습니다."

        if old_idx != new_idx:
            # 모든 클래스의 인덱스가 변경될 수 있으므로 전체 맵을 생성
            old_map = {name: i for i, name in enumerate(old_class_list)}
            new_map = {name: i for i, name in enumerate(new_class_list)}

            # 이전 인덱스를 새 인덱스로 매핑
            idx_remap = {old_map[name]: new_map.get(name) for name in old_map if new_map.get(name) is not None}

            for label_file in os.listdir(self.labels_path):
                if label_file.endswith('.txt'):
                    filepath = os.path.join(self.labels_path, label_file)
                    new_lines = []
                    try:
                        with open(filepath, 'r') as f:
                            lines = f.readlines()
                        for line in lines:
                            parts = line.strip().split()
                            if not parts: continue
                            class_idx = int(parts[0])
                            if class_idx in idx_remap:
                                parts[0] = str(idx_remap[class_idx])
                                new_lines.append(" ".join(parts) + "\n")
                            else:
                                new_lines.append(line) # 매핑에 없는 경우 원본 유지
                        with open(filepath, 'w') as f:
                            f.writelines(new_lines)
                    except Exception as e:
                        print(f"라벨 파일 업데이트 중 오류 ({filepath}): {e}")
                        continue

        return True, "이름 변경 및 모든 관련 파일 업데이트 완료."


    def add_class(self, class_name, category_name):
        manifest = self.get_manifest()
        if category_name not in manifest:
            return False, f"'{category_name}' 카테고리를 찾을 수 없습니다."
        # 모든 카테고리에서 중복 이름 확인
        if any(class_name in classes for classes in manifest.values() if isinstance(classes, dict)):
            return False, "이미 존재하는 클래스 이름입니다."

        manifest[category_name][class_name] = []
        self.save_manifest(manifest)
        return True, f"'{category_name}' 카테고리에 '{class_name}' 클래스를 추가했습니다."

    def delete_class(self, class_name):
        manifest = self.get_manifest()
        category = self.get_class_category(class_name)
        if not category:
            return False, "삭제할 클래스를 찾을 수 없습니다."

        image_files_to_check = manifest[category].pop(class_name)
        self.save_manifest(manifest)

        # 다른 클래스에서 사용되지 않는 이미지와 라벨 파일 삭제
        all_remaining_images = {
            img_file for cat_classes in manifest.values() if isinstance(cat_classes, dict)
            for img_list in cat_classes.values()
            for img_file in img_list
        }
        # v1.3: 네거티브 샘플도 잔존 이미지 목록에 포함
        all_remaining_images.update(manifest.get(NEGATIVE_SAMPLES_NAME, []))


        for filename in image_files_to_check:
            if filename not in all_remaining_images:
                for path in [os.path.join(self.images_path, filename), os.path.join(self.labels_path, f"{os.path.splitext(filename)[0]}.txt")]:
                    if os.path.exists(path): os.remove(path)

        self.delete_monster_confidence_override(class_name)

        nameplate_config = self.get_monster_nameplate_config()
        per_class = nameplate_config.get('per_class', {})
        entry = per_class.pop(class_name, None) if isinstance(per_class, dict) else None
        if entry:
            templates = entry.get('templates', []) if isinstance(entry, dict) else []
            for template in templates:
                filename = template.get('filename') if isinstance(template, dict) else None
                if not filename:
                    continue
                path = os.path.join(self.nameplate_templates_dir, filename)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            self._write_nameplate_config(nameplate_config)

        return True, f"'{class_name}' 클래스 및 관련 파일 삭제 완료."

    def get_images_for_class(self, class_name):
        category = self.get_class_category(class_name)
        if category:
            return self.get_manifest()[category].get(class_name, [])
        return []

    def add_image_and_label_multi_class(self, image_data, label_content, involved_classes):
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        base_filename = f"multi_{timestamp}_{int(time.time() * 1000) % 1000:03d}"
        image_path = os.path.join(self.images_path, f"{base_filename}.png")
        label_path = os.path.join(self.labels_path, f"{base_filename}.txt")
        cv2.imwrite(image_path, image_data)
        with open(label_path, 'w') as f: f.write(label_content)

        manifest = self.get_manifest()
        for class_name in involved_classes:
            category = self.get_class_category(class_name)
            if category and class_name in manifest[category]:
                manifest[category][class_name].append(f"{base_filename}.png")
        self.save_manifest(manifest)
        return f"{base_filename}.png"

    def update_label(self, image_path, label_content, involved_classes):
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        label_path = os.path.join(self.labels_path, f"{base_name}.txt")
        with open(label_path, 'w') as f: f.write(label_content)

        manifest = self.get_manifest()
        filename = f"{base_name}.png"

        # 모든 클래스에서 해당 이미지 파일 제거
        for category in manifest:
            if category == NEGATIVE_SAMPLES_NAME: continue
            for class_name in manifest[category]:
                if filename in manifest[category][class_name]:
                    manifest[category][class_name].remove(filename)

        # 관련된 클래스에 다시 추가
        for class_name in involved_classes:
            category = self.get_class_category(class_name)
            if category and class_name in manifest[category]:
                 if filename not in manifest[category][class_name]:
                    manifest[category][class_name].append(filename)
        self.save_manifest(manifest)

    def delete_image(self, image_path):
        filename = os.path.basename(image_path)
        for path in [image_path, os.path.join(self.labels_path, f"{os.path.splitext(filename)[0]}.txt")]:
            if os.path.exists(path): os.remove(path)

        manifest = self.get_manifest()
        # 모든 카테고리 및 클래스에서 제거
        for category in manifest:
            if isinstance(manifest[category], dict):
                for class_name in manifest[category]:
                    if filename in manifest[category][class_name]:
                        manifest[category][class_name].remove(filename)
            # v1.3: 네거티브 샘플 목록에서도 제거
            elif isinstance(manifest[category], list) and category == NEGATIVE_SAMPLES_NAME:
                if filename in manifest[category]:
                    manifest[category].remove(filename)

        self.save_manifest(manifest)

    def load_settings(self):
        """
        settings.json 파일에서 설정을 불러옵니다.
        """
        try:
            with open(self.settings_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {} # 파일이 없거나 비어있으면 빈 딕셔너리 반환

    def save_settings(self, settings_data):
        """
        주어진 딕셔너리를 settings.json 파일에 저장합니다.
        """
        # 안전한 저장을 위해 기존 설정을 불러와 업데이트
        current_settings = self.load_settings()
        current_settings.update(settings_data)
        with open(self.settings_path, 'w', encoding='utf-8') as f:
            json.dump(current_settings, f, indent=4, ensure_ascii=False)
        if 'last_used_model' in settings_data:
            value = settings_data.get('last_used_model')
            if isinstance(value, str) and value.strip():
                self._last_used_model = value.strip()
            else:
                self._last_used_model = None
            self._notify_model_listeners(self._last_used_model)

    def get_detection_runtime_settings(self) -> dict:
        settings = self.load_settings()
        detection = settings.get('detection', {}) if isinstance(settings, dict) else {}
        nms = detection.get('yolo_nms_iou', DEFAULT_DETECTION_RUNTIME_SETTINGS['yolo_nms_iou'])
        max_det = detection.get('yolo_max_det', DEFAULT_DETECTION_RUNTIME_SETTINGS['yolo_max_det'])
        try:
            nms_val = max(0.05, min(0.95, float(nms)))
        except (TypeError, ValueError):
            nms_val = DEFAULT_DETECTION_RUNTIME_SETTINGS['yolo_nms_iou']
        try:
            max_det_val = max(1, int(max_det))
        except (TypeError, ValueError):
            max_det_val = DEFAULT_DETECTION_RUNTIME_SETTINGS['yolo_max_det']
        return {
            'yolo_nms_iou': nms_val,
            'yolo_max_det': max_det_val,
        }

    def update_detection_runtime_settings(
        self,
        *,
        yolo_nms_iou: float,
        yolo_max_det: int,
    ) -> None:
        current = self.load_settings()
        detection = dict(current.get('detection', {})) if isinstance(current, dict) else {}
        detection['yolo_nms_iou'] = max(0.05, min(0.95, float(yolo_nms_iou)))
        detection['yolo_max_det'] = max(1, int(yolo_max_det))
        self.save_settings({'detection': detection})

    def get_last_used_model(self) -> Optional[str]:
        return self._last_used_model

    def set_last_used_model(self, model_name: Optional[str]) -> None:
        model = model_name.strip() if isinstance(model_name, str) else None
        payload = {'last_used_model': model} if model else {'last_used_model': None}
        self.save_settings(payload)

    # --- 몬스터 신뢰도 보조 메서드 ---
    def get_monster_confidence_overrides(self) -> dict[str, float]:
        settings = self.load_settings()
        raw = settings.get('monster_confidence_overrides', {}) if isinstance(settings, dict) else {}
        overrides: dict[str, float] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if not isinstance(key, str):
                    continue
                try:
                    overrides[key] = float(value)
                except (TypeError, ValueError):
                    continue
        return overrides

    def set_monster_confidence_override(self, class_name: str, value: float) -> None:
        class_name = class_name.strip()
        if not class_name:
            return
        overrides = self.get_monster_confidence_overrides()
        overrides[class_name] = max(0.05, min(0.95, float(value)))
        self.save_settings({'monster_confidence_overrides': overrides})

    def delete_monster_confidence_override(self, class_name: str) -> None:
        overrides = self.get_monster_confidence_overrides()
        if class_name in overrides:
            overrides.pop(class_name, None)
            self.save_settings({'monster_confidence_overrides': overrides})

    def _prune_monster_confidence_overrides(self) -> None:
        overrides = self.get_monster_confidence_overrides()
        if not overrides:
            return
        valid_names = set(self.get_class_list())
        removed = False
        for name in list(overrides.keys()):
            if name not in valid_names:
                overrides.pop(name)
                removed = True
        if removed:
            self.save_settings({'monster_confidence_overrides': overrides})

    def load_status_monitor_config(self) -> StatusMonitorConfig:
        try:
            with open(self.status_config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            config = StatusMonitorConfig.default()
            self._write_status_config(config)
            return config
        return StatusMonitorConfig.from_dict(data)

    def update_status_monitor_config(self, updates: dict) -> StatusMonitorConfig:
        if not isinstance(updates, dict):
            return self.load_status_monitor_config()

        config = self.load_status_monitor_config()

        def apply_resource(target: StatusResourceConfig, payload: Optional[dict], *, allow_threshold: bool) -> None:
            if not isinstance(payload, dict):
                return
            if 'roi' in payload:
                roi_payload = payload.get('roi')
                if isinstance(roi_payload, dict):
                    target.roi = StatusRoi.from_dict(roi_payload)
            if 'interval_sec' in payload:
                try:
                    val = float(payload.get('interval_sec'))
                except (TypeError, ValueError):
                    val = None
                if val is not None and val > 0:
                    target.interval_sec = max(0.1, val)
            if allow_threshold and 'recovery_threshold' in payload:
                threshold = payload.get('recovery_threshold')
                if threshold is None:
                    target.recovery_threshold = None
                else:
                    try:
                        t_val = int(threshold)
                    except (TypeError, ValueError):
                        pass
                    else:
                        if 1 <= t_val <= 99:
                            target.recovery_threshold = t_val
            if allow_threshold and 'command_profile' in payload:
                command = payload.get('command_profile')
                if command is None or (isinstance(command, str) and not command.strip()):
                    target.command_profile = None
                elif isinstance(command, str):
                    target.command_profile = command
            if 'enabled' in payload:
                target.enabled = bool(payload.get('enabled'))
            if 'max_value' in payload:
                raw_value = payload.get('max_value')
                if raw_value in (None, ''):
                    target.maximum_value = None
                else:
                    try:
                        max_val = int(raw_value)
                    except (TypeError, ValueError):
                        pass
                    else:
                        if max_val > 0:
                            target.maximum_value = max_val

        apply_resource(config.hp, updates.get('hp'), allow_threshold=True)
        apply_resource(config.mp, updates.get('mp'), allow_threshold=True)
        apply_resource(config.exp, updates.get('exp'), allow_threshold=False)

        self._write_status_config(config)
        return config

    def register_status_config_listener(self, slot) -> None:
        if slot is None:
            return
        try:
            self.status_config_notifier.status_config_changed.connect(slot)
        except Exception:
            pass

    def _write_status_config(self, config: StatusMonitorConfig) -> None:
        with open(self.status_config_path, 'w', encoding='utf-8') as f:
            json.dump(config.to_dict(), f, indent=4, ensure_ascii=False)
        try:
            self.status_config_notifier.emit_config(config)
        except Exception:
            pass

    def _resolve_key_mappings_path(self) -> Path:
        legacy_relative = Path(os.path.join('Project_Maple', 'workspace', 'config', 'key_mappings.json'))
        module_workspace = Path(__file__).resolve().parents[1] / 'workspace' / 'config' / 'key_mappings.json'
        workspace_relative = Path('workspace') / 'config' / 'key_mappings.json'

        candidates = [
            legacy_relative,
            Path.cwd() / legacy_relative,
            module_workspace,
            workspace_relative,
            Path.cwd() / workspace_relative,
        ]

        for candidate in candidates:
            try:
                candidate_path = candidate if candidate.is_absolute() else (Path.cwd() / candidate)
                if candidate_path.is_file():
                    return candidate_path.resolve()
            except OSError:
                continue

        fallback = candidates[1] if len(candidates) > 1 else module_workspace
        fallback_path = fallback if fallback.is_absolute() else (Path.cwd() / fallback)
        return fallback_path.resolve()

    def list_command_profiles(self, categories: tuple[str, ...]) -> dict[str, list[str]]:
        results = {category: [] for category in categories}
        target_path = self.key_mappings_path
        if not target_path or not target_path.is_file():
            return results

        raw_data = None
        for encoding in ('utf-8', 'utf-8-sig', 'cp949', 'euc-kr'):
            try:
                with target_path.open('r', encoding=encoding) as f:
                    raw_data = json.load(f)
                break
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raw_data = None

        if not isinstance(raw_data, dict):
            return results

        category_map = raw_data.get('_categories')
        if not isinstance(category_map, dict):
            category_map = {}

        profiles_section = raw_data.get('profiles')
        if isinstance(profiles_section, dict):
            profile_names = list(profiles_section.keys())
        else:
            profile_names = [key for key in raw_data.keys() if not str(key).startswith('_')]

        for name in profile_names:
            mapped_category = category_map.get(name)
            if mapped_category in results:
                results[mapped_category].append(name)

        for key in results:
            results[key] = sorted(set(results[key]))

        return results

    # --- 닉네임 템플릿 관리 ---
    def get_nickname_config(self):
        try:
            with open(self.nickname_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            config = self._default_nickname_config()
            self._write_nickname_config(config)
        else:
            default_cfg = self._default_nickname_config()
            changed = False
            for key, default_value in default_cfg.items():
                if key not in config:
                    config[key] = default_value if key != 'templates' else list(default_value)
                    changed = True
            if 'templates' not in config or not isinstance(config['templates'], list):
                config['templates'] = []
                changed = True
            for legacy in ('search_scale_x', 'search_scale_top', 'search_scale_bottom', 'search_scale_y'):
                if legacy in config:
                    config.pop(legacy, None)
                    changed = True
            if changed:
                self._write_nickname_config(config)
        return config

    def update_nickname_config(self, updates: dict):
        if not isinstance(updates, dict):
            return self.get_nickname_config()
        config = self.get_nickname_config()
        forbidden_keys = {'templates'}
        for key, value in updates.items():
            if key in forbidden_keys:
                continue
            config[key] = value
        for legacy in ('search_scale_x', 'search_scale_top', 'search_scale_bottom', 'search_scale_y'):
            config.pop(legacy, None)
        if 'full_scan_delay_sec' in config:
            try:
                config['full_scan_delay_sec'] = max(0.0, float(config['full_scan_delay_sec']))
            except (TypeError, ValueError):
                config['full_scan_delay_sec'] = self._default_nickname_config()['full_scan_delay_sec']
        self._write_nickname_config(config)
        self._notify_overlay_listeners({
            'target': 'nickname',
            'show_overlay': bool(config.get('show_overlay', True)),
        })
        return config

    def list_nickname_templates(self):
        config = self.get_nickname_config()
        templates = config.get('templates', [])
        resolved_templates = []
        for entry in templates:
            filename = entry.get('filename')
            if not filename:
                continue
            path = os.path.join(self.nickname_templates_dir, filename)
            if not os.path.exists(path):
                continue
            resolved_entry = dict(entry)
            resolved_entry['path'] = path
            resolved_templates.append(resolved_entry)
        return resolved_templates

    def add_nickname_template(self, image_bgr, *, source='capture', original_name=None):
        if image_bgr is None or not hasattr(image_bgr, 'shape'):
            raise ValueError('유효한 이미지 배열이 필요합니다.')

        if image_bgr.ndim == 3 and image_bgr.shape[2] == 4:
            image_bgr = cv2.cvtColor(image_bgr, cv2.COLOR_BGRA2BGR)
        elif image_bgr.ndim == 2:
            image_bgr = cv2.cvtColor(image_bgr, cv2.COLOR_GRAY2BGR)

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        template_id = f"tpl_{int(time.time()*1000)%1_000_000:06d}_{uuid.uuid4().hex[:6]}"
        filename = f"{template_id}.png"
        save_path = os.path.join(self.nickname_templates_dir, filename)
        if not cv2.imwrite(save_path, image_bgr):
            raise IOError('닉네임 템플릿을 저장하지 못했습니다.')

        config = self.get_nickname_config()
        template_entry = {
            'id': template_id,
            'filename': filename,
            'source': source,
            'original_name': original_name,
            'created_at': time.time(),
            'width': int(image_bgr.shape[1]),
            'height': int(image_bgr.shape[0]),
        }
        templates = config.get('templates', [])
        templates.append(template_entry)
        config['templates'] = templates
        self._write_nickname_config(config)
        return template_entry

    def import_nickname_template(self, file_path: str):
        if not file_path:
            raise ValueError('파일 경로가 필요합니다.')
        image = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise IOError(f"이미지를 불러올 수 없습니다: {file_path}")
        return self.add_nickname_template(image, source='import', original_name=os.path.basename(file_path))

    def delete_nickname_templates(self, template_ids):
        if not template_ids:
            return 0
        if isinstance(template_ids, str):
            template_ids = [template_ids]
        template_ids = set(template_ids)

        config = self.get_nickname_config()
        templates = config.get('templates', [])
        remaining = []
        removed_count = 0
        for entry in templates:
            if entry.get('id') in template_ids:
                filename = entry.get('filename')
                if filename:
                    path = os.path.join(self.nickname_templates_dir, filename)
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                removed_count += 1
            else:
                remaining.append(entry)

        config['templates'] = remaining
        self._write_nickname_config(config)
        return removed_count

    # --- 방향 템플릿 관리 ---
    def get_direction_config(self):
        try:
            with open(self.direction_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            config = self._default_direction_config()
            self._write_direction_config(config)
            return config

        default_cfg = self._default_direction_config()
        changed = False
        for key, value in default_cfg.items():
            if key not in config:
                config[key] = value if key not in {'templates_left', 'templates_right'} else list(value)
                changed = True
        for side_key in ('templates_left', 'templates_right'):
            if not isinstance(config.get(side_key), list):
                config[side_key] = []
                changed = True
        if changed:
            self._write_direction_config(config)
        return config

    def update_direction_config(self, updates: dict):
        if not isinstance(updates, dict):
            return self.get_direction_config()
        config = self.get_direction_config()
        allowed = {'match_threshold', 'search_offset_y', 'search_height', 'search_half_width', 'show_overlay'}
        changed = False
        for key, value in updates.items():
            if key in allowed:
                config[key] = value
                changed = True
        if changed:
            self._write_direction_config(config)
        self._notify_overlay_listeners({
            'target': 'direction',
            'show_overlay': bool(config.get('show_overlay', True)),
        })
        return config

    def list_direction_templates(self, side: str):
        side = side.lower()
        if side not in {'left', 'right'}:
            return []
        config = self.get_direction_config()
        key = 'templates_left' if side == 'left' else 'templates_right'
        entries = config.get(key, [])
        results = []
        base_dir = self.direction_left_dir if side == 'left' else self.direction_right_dir
        changed = False
        valid_entries = []
        for entry in entries:
            filename = entry.get('filename')
            template_id = entry.get('id')
            if not filename or not template_id:
                changed = True
                continue
            path = os.path.join(base_dir, filename)
            if not os.path.exists(path):
                changed = True
                continue
            resolved = dict(entry)
            resolved['path'] = path
            resolved['side'] = side
            results.append(resolved)
            valid_entries.append(entry)
        if changed:
            config[key] = valid_entries
            self._write_direction_config(config)
        return results

    def import_direction_template(self, side: str, file_path: str):
        side = side.lower()
        if side not in {'left', 'right'}:
            raise ValueError('side must be "left" or "right"')
        if not file_path:
            raise ValueError('파일 경로가 필요합니다.')
        image = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise IOError(f'이미지를 불러올 수 없습니다: {file_path}')
        if image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        template_id = f"dir_{int(time.time()*1000)%1_000_000:06d}_{uuid.uuid4().hex[:6]}"
        filename = f"{template_id}.png"
        save_dir = self.direction_left_dir if side == 'left' else self.direction_right_dir
        save_path = os.path.join(save_dir, filename)
        if not cv2.imwrite(save_path, image):
            raise IOError('방향 템플릿을 저장하지 못했습니다.')

        config = self.get_direction_config()
        entry = {
            'id': template_id,
            'filename': filename,
            'side': side,
            'source': 'import',
            'original_name': os.path.basename(file_path),
            'created_at': time.time(),
            'width': int(image.shape[1]),
            'height': int(image.shape[0]),
        }
        key = 'templates_left' if side == 'left' else 'templates_right'
        templates = config.get(key, [])
        templates.append(entry)
        config[key] = templates
        self._write_direction_config(config)
        entry['path'] = save_path
        return entry

    def delete_direction_templates(self, side: str, template_ids):
        side = side.lower()
        if side not in {'left', 'right'}:
            return 0
        if not template_ids:
            return 0
        if isinstance(template_ids, str):
            template_ids = [template_ids]
        template_ids = set(template_ids)
        config = self.get_direction_config()
        key = 'templates_left' if side == 'left' else 'templates_right'
        templates = config.get(key, [])
        remaining = []
        removed = 0
        for entry in templates:
            template_id = entry.get('id')
            if template_id in template_ids:
                filename = entry.get('filename')
                if filename:
                    path = os.path.join(self.direction_left_dir if side == 'left' else self.direction_right_dir, filename)
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                removed += 1
            else:
                remaining.append(entry)
        config[key] = remaining
        self._write_direction_config(config)
        return removed

    # v1.3: 방해 요소 추가 메서드 신설
    def add_distractor(self, cropped_image_data):
        """
        잘라낸 이미지를 방해 요소(네거티브 샘플)로 저장합니다.
        - 이미지를 images/ 폴더에 저장
        - 비어있는 라벨 파일을 labels/ 폴더에 생성
        - manifest.json의 네거티브 목록에 파일명 추가
        """
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        base_filename = f"distractor_{timestamp}_{int(time.time() * 1000) % 1000:03d}"
        image_filename = f"{base_filename}.png"
        label_filename = f"{base_filename}.txt"

        image_path = os.path.join(self.images_path, image_filename)
        label_path = os.path.join(self.labels_path, label_filename)

        cv2.imwrite(image_path, cropped_image_data)
        with open(label_path, 'w') as f:
            pass # 빈 파일 생성

        manifest = self.get_manifest()
        if image_filename not in manifest[NEGATIVE_SAMPLES_NAME]:
            manifest[NEGATIVE_SAMPLES_NAME].append(image_filename)
        self.save_manifest(manifest)

        return image_filename

    def create_yaml_file(self):
        # get_class_list()가 이미 정렬된 전체 클래스 목록을 반환하므로 그대로 사용
        class_list = self.get_class_list()
        data = {
            'path': self.dataset_path, # (v1.2) 경로 수정
            'train': 'images',
            'val': 'images',
            'names': {i: name for i, name in enumerate(class_list)}
        }
        with open(self.yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        return self.yaml_path

    def get_saved_models(self):
        if not os.path.exists(self.models_path): return []
        return sorted([d for d in os.listdir(self.models_path) if os.path.isdir(os.path.join(self.models_path, d))])

    def save_model_version(self, source_run_dir, model_name):
        dest_dir = os.path.join(self.models_path, model_name)
        if os.path.exists(dest_dir): shutil.rmtree(dest_dir)
        source_weights_dir = os.path.join(source_run_dir, 'weights')
        if os.path.exists(source_weights_dir):
            shutil.copytree(source_weights_dir, os.path.join(dest_dir, 'weights'))
            return True
        return False

    def delete_model_version(self, model_name):
        model_dir = os.path.join(self.models_path, model_name)
        if os.path.exists(model_dir) and os.path.isdir(model_dir):
            try:
                shutil.rmtree(model_dir)
                return True, f"'{model_name}' 모델이 삭제되었습니다."
            except Exception as e:
                return False, f"모델 삭제 중 오류 발생: {e}"
        return False, "삭제할 모델을 찾을 수 없습니다."

    def rebuild_manifest_from_labels(self):
        """
        모든 라벨(.txt) 파일을 스캔하여 manifest.json의 이미지 목록을 재구성합니다.
        라벨 파일에 기록된 class_id를 기반으로 어떤 이미지에 어떤 클래스가 포함되어 있는지
        역추적하여 manifest를 복원합니다.
        """
        try:
            # 1. 현재 클래스 목록과 이름->인덱스 맵 생성
            all_classes = self.get_class_list()
            if not all_classes:
                return False, "복구를 위해 manifest에 클래스가 하나 이상 정의되어 있어야 합니다."

            # 2. 현재 manifest 구조를 가져와 이미지 목록만 비웁니다.
            manifest = self.get_manifest()
            for category in manifest:
                if isinstance(manifest[category], dict):
                    for class_name in manifest[category]:
                        manifest[category][class_name] = [] # 이미지 목록 초기화
                elif isinstance(manifest[category], list):
                    manifest[category] = [] # 네거티브 샘플 목록도 초기화
            
            # 3. 모든 이미지 파일을 기준으로 라벨 파일을 찾습니다.
            image_files = [f for f in os.listdir(self.images_path) if f.endswith('.png')]
            if not image_files:
                 return True, "스캔할 이미지 파일이 없습니다. 복구가 필요하지 않습니다."

            for image_filename in image_files:
                label_filename = os.path.splitext(image_filename)[0] + ".txt"
                filepath = os.path.join(self.labels_path, label_filename)
                
                if not os.path.exists(filepath):
                    continue

                involved_class_ids = set()
                with open(filepath, 'r') as f:
                    lines = f.readlines()
                    if not lines: # 라벨 파일이 비어있으면 네거티브 샘플
                        manifest[NEGATIVE_SAMPLES_NAME].append(image_filename)
                        continue

                    for line in lines:
                        parts = line.strip().split()
                        if parts:
                            try:
                                class_id = int(parts[0])
                                involved_class_ids.add(class_id)
                            except (ValueError, IndexError):
                                continue # 잘못된 형식의 라인 건너뛰기

                # 4. 이 이미지에 포함된 클래스들을 manifest에 기록합니다.
                for class_id in involved_class_ids:
                    if class_id < len(all_classes):
                        class_name = all_classes[class_id]
                        category = self.get_class_category(class_name)
                        if category:
                            # 중복 추가 방지
                            if image_filename not in manifest[category][class_name]:
                                manifest[category][class_name].append(image_filename)

            # 5. 재구성된 manifest를 저장합니다.
            self.save_manifest(manifest)
            return True, f"데이터 복구 완료. 총 {len(image_files)}개의 이미지를 스캔했습니다."
        except Exception as e:
            return False, f"데이터 복구 중 오류 발생: {e}"

# --- 6. 스레드 클래스 (백그라운드 작업) ---
class TrainingThread(QThread):
    progress = pyqtSignal(str)
    results_path_ready = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    def __init__(self, yaml_path, epochs, base_model_name, training_runs_path):
        super().__init__()
        self.yaml_path = yaml_path
        self.epochs = epochs
        self.base_model_name = base_model_name
        self.training_runs_path = training_runs_path # (v1.2) 훈련 결과 저장 경로 추가

    def run(self):
        try:
            self.progress.emit(f"모델 훈련을 시작합니다... (기본 모델: {self.base_model_name}, Epochs: {self.epochs})")
            model = YOLO(f"{self.base_model_name}-seg.pt")
            # (v1.2) project 경로를 workspace/training_runs로 지정
            results = model.train(data=self.yaml_path, epochs=self.epochs, imgsz=640, device=0, project=self.training_runs_path)
            self.results_path_ready.emit(str(results.save_dir))
            self.finished.emit(True, "훈련 성공! '최신 훈련 저장'으로 모델을 저장하세요.")
        except Exception as e: self.finished.emit(False, f"훈련 오류: {e}")

class ExportThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    def __init__(self, model_path): super().__init__(); self.model_path = model_path
    def run(self):
        try:
            self.progress.emit(f"'{os.path.basename(self.model_path)}' 모델을 TensorRT로 변환 중...")
            model = YOLO(self.model_path)
            model.export(format='engine', half=False, device=0)
            self.finished.emit(True, "모델 최적화 성공!")
        except Exception as e: self.finished.emit(False, f"모델 최적화 오류: {e}")

# --- 7. GUI 클래스 (프론트엔드) ---
class LearningTab(QWidget):
    def __init__(self):
        super().__init__()
        # (v1.2) DataManager를 새로운 workspace 경로 기준으로 초기화
        self.data_manager = DataManager(workspace_root=WORKSPACE_ROOT)
        self.training_thread = None
        self.export_thread = None
        self.latest_run_dir = None
        self.sam_predictor = None
        self.current_image_sort_mode = 'date'
        # v1.4: 마지막 사용 모델 로드
        settings = self.data_manager.load_settings()
        self.last_used_model = self.data_manager.get_last_used_model()
        self._checked_class_names: set[str] = set(settings.get('hunt_checked_classes', []))
        self.nickname_config = self.data_manager.get_nickname_config()
        self._nickname_ui_updating = False
        self.direction_config = self.data_manager.get_direction_config()
        self._direction_ui_updating = False
        self.nameplate_config = self.data_manager.get_monster_nameplate_config()
        self._nameplate_ui_updating = False
        self._status_config = self.data_manager.load_status_monitor_config()
        self._status_ui_updating = False
        self._status_command_options: list[tuple[str, str]] = []
        self._thumbnail_cache = OrderedDict()
        self._thumbnail_cache_limit = 256
        self._runtime_ui_updating = False
        self._monster_settings_dialog_open = False
        self.initUI()
        self.init_sam()
        self.data_manager.register_status_config_listener(self._handle_status_config_changed)

    def get_data_manager(self):
        """Hunt 등 다른 탭에서 데이터 매니저를 참조할 때 사용."""
        return self.data_manager

    def initUI(self):
        # [BUG FIX] 레이아웃을 위젯에 할당하지 않고 생성한 뒤, 마지막에 한 번만 설정합니다.
        main_layout = QHBoxLayout()
        
        # 왼쪽: 클래스 목록 및 프리셋
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel('클래스 목록 (체크하여 탐지 대상 설정)'))

        self.class_tree_widget = ClassTreeWidget()
        self.class_tree_widget.setHeaderLabel('클래스')
        self.class_tree_widget.itemSelectionChanged.connect(self.populate_image_list)
        self.class_tree_widget.itemChanged.connect(self.handle_item_check)
        self.class_tree_widget.drop_completed.connect(self.save_tree_state_to_manifest)
        self.class_tree_widget.itemDoubleClicked.connect(self._handle_class_item_double_clicked)
        self.class_tree_widget.setExpandsOnDoubleClick(False)

        left_layout.addWidget(self.class_tree_widget)

        class_buttons_layout = QHBoxLayout()
        self.add_class_btn = QPushButton('클래스 추가')
        self.rename_class_btn = QPushButton('이름 변경')
        self.delete_class_btn = QPushButton('선택 항목 삭제')
        self.recover_data_btn = QPushButton('데이터 복구')
        self.recover_data_btn.setToolTip("라벨(.txt) 파일을 기반으로 이미지 목록을 재구성합니다.")

        self.add_class_btn.clicked.connect(self.add_class)
        self.rename_class_btn.clicked.connect(self.rename_class)
        self.delete_class_btn.clicked.connect(self.delete_class)
        self.recover_data_btn.clicked.connect(self.recover_data)

        class_buttons_layout.addWidget(self.add_class_btn)
        class_buttons_layout.addWidget(self.rename_class_btn)
        class_buttons_layout.addWidget(self.delete_class_btn)
        class_buttons_layout.addWidget(self.recover_data_btn)
        left_layout.addLayout(class_buttons_layout)

        preset_group = QGroupBox("탐지 프리셋")
        preset_layout = QVBoxLayout()
        self.preset_selector = QComboBox()
        self.preset_selector.currentIndexChanged.connect(self.load_preset)
        preset_buttons_layout = QHBoxLayout()
        self.add_preset_btn = QPushButton("추가")
        self.update_preset_btn = QPushButton("수정")
        self.delete_preset_btn = QPushButton("삭제")
        self.add_preset_btn.clicked.connect(self.add_preset)
        self.update_preset_btn.clicked.connect(self.update_preset)
        self.delete_preset_btn.clicked.connect(self.delete_preset)
        preset_buttons_layout.addWidget(self.add_preset_btn)
        preset_buttons_layout.addWidget(self.update_preset_btn)
        preset_buttons_layout.addWidget(self.delete_preset_btn)
        preset_layout.addWidget(self.preset_selector)
        preset_layout.addLayout(preset_buttons_layout)
        preset_group.setLayout(preset_layout)
        left_layout.addWidget(preset_group)

        # 중앙: 이미지 목록
        center_layout = QVBoxLayout()

        image_list_header_layout = QHBoxLayout()
        image_list_header_layout.addWidget(QLabel('이미지 목록'))
        image_list_header_layout.addStretch(1)
        image_list_header_layout.addWidget(QLabel("정렬:"))
        self.sort_by_name_btn = QPushButton("이름순")
        self.sort_by_date_btn = QPushButton("추가순")
        self.sort_by_name_btn.setCheckable(True)
        self.sort_by_date_btn.setCheckable(True)
        self.sort_by_date_btn.setChecked(True)
        self.sort_by_name_btn.clicked.connect(lambda: self.set_image_sort_mode('name'))
        self.sort_by_date_btn.clicked.connect(lambda: self.set_image_sort_mode('date'))
        image_list_header_layout.addWidget(self.sort_by_name_btn)
        image_list_header_layout.addWidget(self.sort_by_date_btn)

        self.image_list_widget = QListWidget()
        self.image_list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_list_widget.setIconSize(QSize(128, 128))
        self.image_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.image_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.image_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.image_list_widget.itemDoubleClicked.connect(self.edit_selected_image)
        self.image_list_widget.setFixedHeight(370)

        capture_options_layout = QHBoxLayout()
        capture_options_layout.addWidget(QLabel("대기시간(초):"))
        self.capture_delay_spinbox = QDoubleSpinBox()
        self.capture_delay_spinbox.setRange(0.0, 10.0)
        self.capture_delay_spinbox.setValue(0.0)
        self.capture_delay_spinbox.setSingleStep(0.1)
        capture_options_layout.addWidget(self.capture_delay_spinbox)
        capture_options_layout.addWidget(QLabel("횟수:"))
        self.capture_count_spinbox = QSpinBox()
        self.capture_count_spinbox.setRange(1, 50)
        self.capture_count_spinbox.setValue(1)
        capture_options_layout.addWidget(self.capture_count_spinbox)
        capture_options_layout.addWidget(QLabel("간격(초):"))
        self.capture_interval_spinbox = QDoubleSpinBox()
        self.capture_interval_spinbox.setRange(0.2, 5.0)
        self.capture_interval_spinbox.setValue(1.0)
        self.capture_interval_spinbox.setSingleStep(0.1)
        capture_options_layout.addWidget(self.capture_interval_spinbox)
        self.capture_btn = QPushButton('메이플 창 캡처')
        self.capture_btn.clicked.connect(self.capture_screen)
        capture_options_layout.addWidget(self.capture_btn)

        center_buttons_layout = QHBoxLayout()
        self.add_image_btn = QPushButton('이미지 파일 추가')
        self.add_image_btn.clicked.connect(self.add_images_from_files)
        self.edit_image_btn = QPushButton('선택 이미지 편집')
        self.edit_image_btn.clicked.connect(self.edit_selected_image)
        self.delete_image_btn = QPushButton('선택 이미지 삭제')
        self.delete_image_btn.clicked.connect(self.delete_image)
        center_buttons_layout.addWidget(self.add_image_btn)
        center_buttons_layout.addWidget(self.edit_image_btn)
        center_buttons_layout.addWidget(self.delete_image_btn)

        nameplate_group = QGroupBox("몬스터 이름표")
        nameplate_group.setCheckable(True)
        nameplate_group.setChecked(False)
        self.nameplate_group = nameplate_group
        nameplate_layout = QVBoxLayout()
        nameplate_layout.setContentsMargins(0, 0, 0, 0)
        nameplate_layout.setSpacing(12)

        nameplate_grid = QGridLayout()
        nameplate_grid.setContentsMargins(0, 0, 0, 0)
        nameplate_grid.setHorizontalSpacing(16)
        nameplate_grid.setVerticalSpacing(10)

        size_label = QLabel("이름표 크기")
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        self.nameplate_width_spin = QSpinBox()
        self.nameplate_width_spin.setRange(10, 600)
        self.nameplate_width_spin.setSingleStep(5)
        self.nameplate_width_spin.setMaximumWidth(80)
        size_row.addWidget(QLabel("가로"))
        size_row.addWidget(self.nameplate_width_spin)
        self.nameplate_height_spin = QSpinBox()
        self.nameplate_height_spin.setRange(10, 400)
        self.nameplate_height_spin.setSingleStep(5)
        self.nameplate_height_spin.setMaximumWidth(80)
        size_row.addWidget(QLabel("세로"))
        size_row.addWidget(self.nameplate_height_spin)
        size_row.addStretch(1)
        size_widget = QWidget()
        size_widget.setLayout(size_row)
        nameplate_grid.addWidget(size_label, 0, 0)
        nameplate_grid.addWidget(size_widget, 0, 1)

        offset_label = QLabel("오프셋")
        offset_row = QHBoxLayout()
        offset_row.setContentsMargins(0, 0, 0, 0)
        offset_row.setSpacing(8)
        self.nameplate_offset_x_spin = QSpinBox()
        self.nameplate_offset_x_spin.setRange(-300, 300)
        self.nameplate_offset_x_spin.setSingleStep(5)
        self.nameplate_offset_x_spin.setMaximumWidth(80)
        offset_row.addWidget(QLabel("X"))
        offset_row.addWidget(self.nameplate_offset_x_spin)
        self.nameplate_offset_y_spin = QSpinBox()
        self.nameplate_offset_y_spin.setRange(-300, 300)
        self.nameplate_offset_y_spin.setSingleStep(5)
        self.nameplate_offset_y_spin.setMaximumWidth(80)
        offset_row.addWidget(QLabel("Y"))
        offset_row.addWidget(self.nameplate_offset_y_spin)
        self.nameplate_overlay_checkbox = QCheckBox("범위 표시")
        offset_row.addSpacing(12)
        offset_row.addWidget(self.nameplate_overlay_checkbox)
        offset_row.addStretch(1)
        offset_widget = QWidget()
        offset_widget.setLayout(offset_row)
        nameplate_grid.addWidget(offset_label, 1, 0)
        nameplate_grid.addWidget(offset_widget, 1, 1)

        detection_label = QLabel("감지 설정")
        detection_row = QHBoxLayout()
        detection_row.setContentsMargins(0, 0, 0, 0)
        detection_row.setSpacing(8)
        self.nameplate_threshold_spin = QDoubleSpinBox()
        self.nameplate_threshold_spin.setRange(0.10, 0.99)
        self.nameplate_threshold_spin.setSingleStep(0.01)
        self.nameplate_threshold_spin.setDecimals(2)
        self.nameplate_threshold_spin.setMaximumWidth(90)
        detection_row.addWidget(QLabel("임계값"))
        detection_row.addWidget(self.nameplate_threshold_spin)
        self.nameplate_dead_zone_spin = QDoubleSpinBox()
        self.nameplate_dead_zone_spin.setRange(0.0, 2.0)
        self.nameplate_dead_zone_spin.setSingleStep(0.01)
        self.nameplate_dead_zone_spin.setDecimals(2)
        self.nameplate_dead_zone_spin.setMaximumWidth(90)
        detection_row.addSpacing(12)
        detection_row.addWidget(QLabel("사망 무시"))
        detection_row.addWidget(self.nameplate_dead_zone_spin)
        self.nameplate_grace_spin = QDoubleSpinBox()
        self.nameplate_grace_spin.setRange(0.0, 2.0)
        self.nameplate_grace_spin.setSingleStep(0.01)
        self.nameplate_grace_spin.setDecimals(2)
        self.nameplate_grace_spin.setMaximumWidth(90)
        detection_row.addSpacing(12)
        detection_row.addWidget(QLabel("유예"))
        detection_row.addWidget(self.nameplate_grace_spin)
        detection_row.addStretch(1)
        detection_widget = QWidget()
        detection_widget.setLayout(detection_row)
        nameplate_grid.addWidget(detection_label, 2, 0)
        nameplate_grid.addWidget(detection_widget, 2, 1)

        nameplate_grid.setColumnStretch(1, 1)

        nameplate_layout.addLayout(nameplate_grid)
        nameplate_layout.addStretch(1)

        nameplate_group.setLayout(nameplate_layout)
        nameplate_group.toggled.connect(self._handle_nameplate_enabled_toggled)
        self.nameplate_width_spin.valueChanged.connect(self._handle_nameplate_roi_changed)
        self.nameplate_height_spin.valueChanged.connect(self._handle_nameplate_roi_changed)
        self.nameplate_offset_x_spin.valueChanged.connect(self._handle_nameplate_roi_changed)
        self.nameplate_offset_y_spin.valueChanged.connect(self._handle_nameplate_roi_changed)
        self.nameplate_overlay_checkbox.toggled.connect(self._handle_nameplate_overlay_toggled)
        self.nameplate_threshold_spin.valueChanged.connect(self._handle_nameplate_threshold_changed)
        self.nameplate_dead_zone_spin.valueChanged.connect(self._handle_nameplate_dead_zone_changed)
        self.nameplate_grace_spin.valueChanged.connect(self._handle_nameplate_grace_changed)

        center_layout.addLayout(image_list_header_layout)
        center_layout.addWidget(self.image_list_widget)
        center_layout.addLayout(capture_options_layout)
        center_layout.addLayout(center_buttons_layout)
        center_layout.addWidget(nameplate_group)

        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(center_layout, 2)

        # 오른쪽: 훈련 및 탐지
        right_layout = QVBoxLayout()

        train_group = QGroupBox("모델 훈련")
        train_layout = QVBoxLayout()
        train_options_layout = QHBoxLayout()
        train_options_layout.addWidget(QLabel("기본 모델:"))
        self.base_model_selector = QComboBox()
        self.base_model_selector.addItems(['yolov8n', 'yolov8s', 'yolov8m'])
        train_options_layout.addWidget(self.base_model_selector)
        train_options_layout.addWidget(QLabel("Epochs:"))
        self.epoch_spinbox = QSpinBox()
        self.epoch_spinbox.setRange(10, 500)
        self.epoch_spinbox.setValue(100)
        self.epoch_spinbox.setSingleStep(10)
        train_options_layout.addWidget(self.epoch_spinbox)
        train_options_layout.addStretch(1)
        self.train_btn = QPushButton('훈련 시작'); self.train_btn.clicked.connect(self.start_training)
        train_options_layout.addWidget(self.train_btn)
        train_layout.addLayout(train_options_layout)
        train_group.setLayout(train_layout)

        runtime_group = QGroupBox("YOLO 실시간 설정")
        runtime_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred))
        runtime_form = QFormLayout()
        runtime_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.yolo_nms_spin = QDoubleSpinBox()
        self.yolo_nms_spin.setRange(0.10, 0.90)
        self.yolo_nms_spin.setSingleStep(0.05)
        self.yolo_nms_spin.setDecimals(2)
        self.yolo_nms_spin.setToolTip("NMS IoU 임계값. 낮을수록 겹치는 박스를 더 많이 제거합니다.")
        runtime_form.addRow("NMS IoU", self.yolo_nms_spin)

        self.yolo_max_det_spin = QSpinBox()
        self.yolo_max_det_spin.setRange(10, 300)
        self.yolo_max_det_spin.setSingleStep(5)
        self.yolo_max_det_spin.setToolTip("한 프레임에서 유지할 최대 박스 수를 제한합니다.")
        runtime_form.addRow("최대 박스 수", self.yolo_max_det_spin)

        runtime_group.setLayout(runtime_form)

        train_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred))
        train_runtime_layout = QHBoxLayout()
        train_runtime_layout.addWidget(train_group, 1)
        train_runtime_layout.addWidget(runtime_group, 1)
        right_layout.addLayout(train_runtime_layout)

        model_manage_group = QGroupBox("저장된 모델 관리")
        model_manage_layout = QVBoxLayout()
        self.save_model_btn = QPushButton('최신 훈련 결과 저장'); self.save_model_btn.clicked.connect(self.save_latest_training_result); self.save_model_btn.setEnabled(False)
        model_selection_layout = QHBoxLayout()
        model_selection_layout.addWidget(QLabel('사용 모델:'))
        self.model_selector = QComboBox()
        model_selection_layout.addWidget(self.model_selector)
        model_buttons_layout = QHBoxLayout()
        self.export_btn = QPushButton('선택 모델 최적화'); self.export_btn.clicked.connect(self.start_exporting)
        self.delete_saved_model_btn = QPushButton('선택 모델 삭제'); self.delete_saved_model_btn.clicked.connect(self.delete_saved_model)
        model_buttons_layout.addWidget(self.export_btn)
        model_buttons_layout.addWidget(self.delete_saved_model_btn)
        model_manage_layout.addWidget(self.save_model_btn)
        model_manage_layout.addLayout(model_selection_layout)
        model_manage_layout.addLayout(model_buttons_layout)
        model_manage_group.setLayout(model_manage_layout)
        right_layout.addWidget(model_manage_group)

        runtime_settings = self.data_manager.get_detection_runtime_settings()
        self._runtime_ui_updating = True
        self.yolo_nms_spin.setValue(runtime_settings['yolo_nms_iou'])
        self.yolo_max_det_spin.setValue(runtime_settings['yolo_max_det'])
        self._runtime_ui_updating = False
        self.yolo_nms_spin.valueChanged.connect(self._handle_runtime_settings_changed)
        self.yolo_max_det_spin.valueChanged.connect(self._handle_runtime_settings_changed)

        nickname_group = QGroupBox("닉네임 탐지 설정")
        nickname_layout = QVBoxLayout()

        nickname_text_layout = QHBoxLayout()
        nickname_text_layout.addWidget(QLabel("대상 닉네임:"))
        self.nickname_text_input = QLineEdit()
        self.nickname_text_input.setPlaceholderText("예: 버프몬")
        self.nickname_text_input.setMaximumWidth(200)
        nickname_text_layout.addWidget(self.nickname_text_input)
        self.nickname_overlay_checkbox = QCheckBox("실시간 표기")
        nickname_text_layout.addSpacing(8)
        nickname_text_layout.addWidget(self.nickname_overlay_checkbox)
        nickname_text_layout.addSpacing(8)
        nickname_text_layout.addWidget(QLabel("전체 탐색 딜레이(초):"))
        self.nickname_full_scan_delay_spin = QDoubleSpinBox()
        self.nickname_full_scan_delay_spin.setRange(0.0, 5.0)
        self.nickname_full_scan_delay_spin.setSingleStep(0.1)
        self.nickname_full_scan_delay_spin.setDecimals(2)
        self.nickname_full_scan_delay_spin.setToolTip("전체 화면 재탐색 간 최소 지연 시간(초). 0이면 프레임마다 탐색합니다.")
        nickname_text_layout.addWidget(self.nickname_full_scan_delay_spin)
        nickname_layout.addLayout(nickname_text_layout)

        nickname_threshold_layout = QHBoxLayout()
        nickname_threshold_layout.addWidget(QLabel("템플릿 임계값:"))
        self.nickname_threshold_spin = QDoubleSpinBox()
        self.nickname_threshold_spin.setRange(0.1, 0.99)
        self.nickname_threshold_spin.setSingleStep(0.01)
        nickname_threshold_layout.addWidget(self.nickname_threshold_spin)
        nickname_threshold_layout.addSpacing(8)
        nickname_threshold_layout.addWidget(QLabel("X 오프셋:"))
        self.nickname_offset_x_spin = QSpinBox()
        self.nickname_offset_x_spin.setRange(-400, 400)
        nickname_threshold_layout.addWidget(self.nickname_offset_x_spin)
        nickname_threshold_layout.addSpacing(8)
        nickname_threshold_layout.addWidget(QLabel("Y 오프셋:"))
        self.nickname_offset_y_spin = QSpinBox()
        self.nickname_offset_y_spin.setRange(-400, 400)
        nickname_threshold_layout.addWidget(self.nickname_offset_y_spin)
        nickname_threshold_layout.addSpacing(8)
        nickname_threshold_layout.addWidget(QLabel("좌우 여백(px):"))
        self.nickname_margin_x_spin = QSpinBox()
        self.nickname_margin_x_spin.setRange(0, 600)
        self.nickname_margin_x_spin.setSingleStep(10)
        nickname_threshold_layout.addWidget(self.nickname_margin_x_spin)
        nickname_threshold_layout.addSpacing(8)
        nickname_threshold_layout.addWidget(QLabel("위 여백(px):"))
        self.nickname_margin_top_spin = QSpinBox()
        self.nickname_margin_top_spin.setRange(0, 400)
        self.nickname_margin_top_spin.setSingleStep(5)
        nickname_threshold_layout.addWidget(self.nickname_margin_top_spin)
        nickname_threshold_layout.addSpacing(8)
        nickname_threshold_layout.addWidget(QLabel("아래 여백(px):"))
        self.nickname_margin_bottom_spin = QSpinBox()
        self.nickname_margin_bottom_spin.setRange(0, 400)
        self.nickname_margin_bottom_spin.setSingleStep(5)
        nickname_threshold_layout.addWidget(self.nickname_margin_bottom_spin)
        nickname_layout.addLayout(nickname_threshold_layout)

        self.nickname_template_list = QListWidget()
        self.nickname_template_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.nickname_template_list.setIconSize(QSize(160, 64))
        self.nickname_template_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.nickname_template_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.nickname_template_list.setFixedHeight(100)
        nickname_layout.addWidget(self.nickname_template_list, 1)

        nickname_buttons_layout = QHBoxLayout()
        self.capture_nickname_btn = QPushButton("영역 캡처")
        self.capture_nickname_btn.clicked.connect(self.capture_nickname_template)
        self.import_nickname_btn = QPushButton("파일 추가")
        self.import_nickname_btn.clicked.connect(self.import_nickname_templates)
        self.delete_nickname_btn = QPushButton("선택 삭제")
        self.delete_nickname_btn.clicked.connect(self.delete_selected_nickname_templates)
        nickname_buttons_layout.addWidget(self.capture_nickname_btn)
        nickname_buttons_layout.addWidget(self.import_nickname_btn)
        nickname_buttons_layout.addWidget(self.delete_nickname_btn)
        nickname_layout.addLayout(nickname_buttons_layout)

        nickname_group.setLayout(nickname_layout)
        right_layout.addWidget(nickname_group)

        direction_group = QGroupBox("방향 탐지 설정")
        direction_layout = QVBoxLayout()

        direction_threshold_layout = QHBoxLayout()
        direction_threshold_layout.addWidget(QLabel("템플릿 임계값:"))
        self.direction_threshold_spin = QDoubleSpinBox()
        self.direction_threshold_spin.setRange(0.1, 0.99)
        self.direction_threshold_spin.setSingleStep(0.01)
        direction_threshold_layout.addWidget(self.direction_threshold_spin)
        direction_threshold_layout.addSpacing(8)

        direction_threshold_layout.addWidget(QLabel("위쪽 오프셋(px):"))
        self.direction_offset_spin = QSpinBox()
        self.direction_offset_spin.setRange(0, 400)
        self.direction_offset_spin.setSingleStep(1)
        direction_threshold_layout.addWidget(self.direction_offset_spin)
        direction_threshold_layout.addSpacing(8)

        direction_threshold_layout.addWidget(QLabel("높이(px):"))
        self.direction_height_spin = QSpinBox()
        self.direction_height_spin.setRange(4, 200)
        self.direction_height_spin.setSingleStep(1)
        direction_threshold_layout.addWidget(self.direction_height_spin)
        direction_threshold_layout.addSpacing(8)

        direction_threshold_layout.addWidget(QLabel("좌우 폭(±px):"))
        self.direction_half_width_spin = QSpinBox()
        self.direction_half_width_spin.setRange(4, 400)
        self.direction_half_width_spin.setSingleStep(1)
        direction_threshold_layout.addWidget(self.direction_half_width_spin)
        direction_threshold_layout.addSpacing(8)
        self.direction_overlay_checkbox = QCheckBox("실시간 표기")
        direction_threshold_layout.addWidget(self.direction_overlay_checkbox)
        direction_layout.addLayout(direction_threshold_layout)

        list_icon_size = QSize(96, 32)

        direction_layout.addWidget(QLabel("좌측 템플릿"))
        self.direction_left_list = QListWidget()
        self.direction_left_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.direction_left_list.setIconSize(list_icon_size)
        self.direction_left_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.direction_left_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.direction_left_list.setFixedHeight(40)
        direction_layout.addWidget(self.direction_left_list)

        left_buttons_layout = QHBoxLayout()
        self.import_direction_left_btn = QPushButton("파일 추가")
        self.import_direction_left_btn.clicked.connect(lambda: self.import_direction_templates('left'))
        self.delete_direction_left_btn = QPushButton("선택 삭제")
        self.delete_direction_left_btn.clicked.connect(lambda: self.delete_direction_templates('left'))
        left_buttons_layout.addWidget(self.import_direction_left_btn)
        left_buttons_layout.addWidget(self.delete_direction_left_btn)
        direction_layout.addLayout(left_buttons_layout)

        direction_layout.addWidget(QLabel("우측 템플릿"))
        self.direction_right_list = QListWidget()
        self.direction_right_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.direction_right_list.setIconSize(list_icon_size)
        self.direction_right_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.direction_right_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.direction_right_list.setFixedHeight(40)
        direction_layout.addWidget(self.direction_right_list)

        right_buttons_layout = QHBoxLayout()
        self.import_direction_right_btn = QPushButton("파일 추가")
        self.import_direction_right_btn.clicked.connect(lambda: self.import_direction_templates('right'))
        self.delete_direction_right_btn = QPushButton("선택 삭제")
        self.delete_direction_right_btn.clicked.connect(lambda: self.delete_direction_templates('right'))
        right_buttons_layout.addWidget(self.import_direction_right_btn)
        right_buttons_layout.addWidget(self.delete_direction_right_btn)
        direction_layout.addLayout(right_buttons_layout)

        direction_group.setLayout(direction_layout)
        right_layout.addWidget(direction_group)

        status_group = self._create_status_monitor_group()
        right_layout.addWidget(status_group)

        self.log_viewer = QTextEdit()
        self.log_viewer.setReadOnly(True)
        log_metrics = self.log_viewer.fontMetrics()
        self.log_viewer.setFixedHeight(max(log_metrics.lineSpacing() * 3, 48))

        right_layout.addWidget(QLabel('로그'))
        right_layout.addWidget(self.log_viewer)
        right_layout.addStretch(1)
        
        main_layout.addLayout(right_layout, 2)

        # 상태바 대신 사용할 라벨과 프로그레스바
        status_layout = QHBoxLayout()
        self.status_label = QLabel("준비")
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.progress_bar)
        
        # 전체 레이아웃 구성
        overall_layout = QVBoxLayout()
        overall_layout.addLayout(main_layout)
        overall_layout.addLayout(status_layout)
        
        # 최종적으로 위젯에 레이아웃 설정
        self.setLayout(overall_layout)


        self._apply_nameplate_config_to_ui()
        self._apply_nickname_config_to_ui()
        self._apply_direction_config_to_ui()
        self.nickname_text_input.editingFinished.connect(self.on_nickname_text_changed)
        for spin in (
            self.nickname_threshold_spin,
            self.nickname_offset_x_spin,
            self.nickname_offset_y_spin,
            self.nickname_margin_x_spin,
            self.nickname_margin_top_spin,
            self.nickname_margin_bottom_spin,
            self.nickname_full_scan_delay_spin,
        ):
            spin.setKeyboardTracking(False)

        self.nickname_threshold_spin.editingFinished.connect(self.on_nickname_threshold_committed)
        self.nickname_offset_x_spin.editingFinished.connect(self.on_nickname_offset_committed)
        self.nickname_offset_y_spin.editingFinished.connect(self.on_nickname_offset_committed)
        self.nickname_margin_x_spin.editingFinished.connect(self.on_nickname_margin_committed)
        self.nickname_margin_top_spin.editingFinished.connect(self.on_nickname_margin_committed)
        self.nickname_margin_bottom_spin.editingFinished.connect(self.on_nickname_margin_committed)
        self.nickname_full_scan_delay_spin.editingFinished.connect(self.on_nickname_full_scan_delay_committed)
        self.nickname_overlay_checkbox.toggled.connect(self.on_nickname_overlay_toggled)
        self.direction_threshold_spin.valueChanged.connect(self.on_direction_threshold_changed)
        self.direction_offset_spin.valueChanged.connect(self.on_direction_offset_changed)
        self.direction_height_spin.valueChanged.connect(self.on_direction_range_changed)
        self.direction_half_width_spin.valueChanged.connect(self.on_direction_range_changed)
        self.direction_overlay_checkbox.toggled.connect(self.on_direction_overlay_toggled)

        self.populate_class_list()
        self.populate_model_list()
        self.model_selector.currentTextChanged.connect(self._handle_model_selection_changed)
        self.populate_preset_list()
        self.populate_nickname_template_list()
        self._load_status_command_options()
        self._apply_status_config_to_ui()

    def update_status_message(self, message):
        """상태바 메시지 업데이트를 위한 슬롯."""
        self.status_label.setText(message)

    def init_sam(self):
        if not SAM_AVAILABLE:
            self.update_status_message("SAM 사용 불가: 'segment_anything' 또는 'torch' 라이브러리를 설치하세요.")
            return

        self.sam_manager = SAMManager()
        self.sam_thread = QThread()
        self.sam_manager.moveToThread(self.sam_thread)

        self.sam_manager.model_ready.connect(self.on_sam_model_ready)
        self.sam_manager.status_updated.connect(self.update_status_message)
        self.sam_manager.progress_updated.connect(self.update_progress_bar)

        self.sam_thread.started.connect(self.sam_manager.load_model)
        self.sam_thread.start()

    def on_sam_model_ready(self, predictor):
        self.sam_predictor = predictor
        self.progress_bar.hide()

    def update_progress_bar(self, value):
        if value > 0 and value < 100:
            self.progress_bar.show()
            self.progress_bar.setValue(value)
        else:
            self.progress_bar.hide()

    def populate_model_list(self):
        self.model_selector.blockSignals(True)
        try:
            self.model_selector.clear()
            saved_models = self.data_manager.get_saved_models()
            self.model_selector.addItems(saved_models)

            active_model = self.data_manager.get_last_used_model() or self.last_used_model
            if active_model and active_model in saved_models:
                self.model_selector.setCurrentText(active_model)
            elif saved_models:
                self.model_selector.setCurrentIndex(0)
                active_model = self.model_selector.currentText()
            else:
                active_model = None
        finally:
            self.model_selector.blockSignals(False)

        if active_model:
            self.last_used_model = active_model
            self.data_manager.set_last_used_model(active_model)

    def _handle_model_selection_changed(self, model_name: str) -> None:
        normalized = model_name.strip()
        self.last_used_model = normalized if normalized else None
        self.data_manager.set_last_used_model(self.last_used_model or None)

    def _refresh_nickname_config_cache(self):
        self.nickname_config = self.data_manager.get_nickname_config()

    def _apply_nickname_config_to_ui(self):
        self._nickname_ui_updating = True
        config = self.data_manager.get_nickname_config()
        self.nickname_config = config
        self.nickname_text_input.setText(config.get('target_text', ''))
        threshold = float(config.get('match_threshold', 0.72))
        self.nickname_threshold_spin.setValue(max(self.nickname_threshold_spin.minimum(), min(self.nickname_threshold_spin.maximum(), threshold)))
        self.nickname_offset_x_spin.setValue(int(config.get('char_offset_x', 0)))
        self.nickname_offset_y_spin.setValue(int(config.get('char_offset_y', 0)))
        margin_x = int(config.get('search_margin_x', config.get('search_margin', 210)))
        margin_top = int(config.get('search_margin_top', config.get('search_margin_vertical', 100)))
        margin_bottom = int(config.get('search_margin_bottom', config.get('search_margin_vertical', 100)))
        self.nickname_margin_x_spin.setValue(
            max(self.nickname_margin_x_spin.minimum(), min(self.nickname_margin_x_spin.maximum(), margin_x))
        )
        self.nickname_margin_top_spin.setValue(
            max(self.nickname_margin_top_spin.minimum(), min(self.nickname_margin_top_spin.maximum(), margin_top))
        )
        self.nickname_margin_bottom_spin.setValue(
            max(self.nickname_margin_bottom_spin.minimum(), min(self.nickname_margin_bottom_spin.maximum(), margin_bottom))
        )
        try:
            delay_value = float(config.get('full_scan_delay_sec', 0.0))
        except (TypeError, ValueError):
            delay_value = self._default_nickname_config()['full_scan_delay_sec']
        self.nickname_full_scan_delay_spin.setValue(
            max(self.nickname_full_scan_delay_spin.minimum(), min(self.nickname_full_scan_delay_spin.maximum(), delay_value))
        )
        self.nickname_overlay_checkbox.setChecked(bool(config.get('show_overlay', True)))
        self._nickname_ui_updating = False

    def populate_nickname_template_list(self):
        self.nickname_template_list.clear()
        templates = self.data_manager.list_nickname_templates()
        if not templates:
            empty_item = QListWidgetItem(QIcon(), "등록된 템플릿이 없습니다")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.nickname_template_list.addItem(empty_item)
            self.delete_nickname_btn.setEnabled(False)
            return

        self.delete_nickname_btn.setEnabled(True)
        for entry in templates:
            pixmap = QPixmap(entry['path'])
            if pixmap.isNull():
                pixmap = QPixmap(self.nickname_template_list.iconSize())
                pixmap.fill(Qt.GlobalColor.darkGray)
            icon = QIcon(pixmap)
            label = entry.get('original_name') or entry.get('id', '템플릿')
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, entry.get('id'))
            tooltip_lines = [f"ID: {entry.get('id')}"]
            if entry.get('original_name'):
                tooltip_lines.append(f"원본: {entry.get('original_name')}")
            size_text = f"크기: {entry.get('width', '?')}x{entry.get('height', '?')}"
            tooltip_lines.append(size_text)
            score = entry.get('created_at')
            if score:
                tooltip_lines.append(time.strftime('등록 시각: %Y-%m-%d %H:%M:%S', time.localtime(score)))
            item.setToolTip('\n'.join(tooltip_lines))
            self.nickname_template_list.addItem(item)

    def _refresh_direction_config_cache(self):
        self.direction_config = self.data_manager.get_direction_config()

    def _apply_direction_config_to_ui(self):
        self._direction_ui_updating = True
        config = self.data_manager.get_direction_config()
        self.direction_config = config
        threshold = float(config.get('match_threshold', 0.72))
        self.direction_threshold_spin.setValue(max(self.direction_threshold_spin.minimum(), min(self.direction_threshold_spin.maximum(), threshold)))
        self.direction_offset_spin.setValue(int(round(config.get('search_offset_y', 60.0))))
        self.direction_height_spin.setValue(int(round(config.get('search_height', 20.0))))
        self.direction_half_width_spin.setValue(int(round(config.get('search_half_width', 30.0))))
        self.direction_overlay_checkbox.setChecked(bool(config.get('show_overlay', True)))
        self._direction_ui_updating = False
        self.populate_direction_template_lists()

    def populate_direction_template_lists(self):
        self._populate_direction_template_list('left')
        self._populate_direction_template_list('right')

    def _populate_direction_template_list(self, side: str):
        widget = self.direction_left_list if side == 'left' else self.direction_right_list
        widget.clear()
        templates = self.data_manager.list_direction_templates(side)
        button = self.delete_direction_left_btn if side == 'left' else self.delete_direction_right_btn
        if not templates:
            empty = QListWidgetItem(QIcon(), "등록된 템플릿이 없습니다")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            widget.addItem(empty)
            button.setEnabled(False)
            return
        button.setEnabled(True)
        for entry in templates:
            pixmap = QPixmap(entry['path'])
            if pixmap.isNull():
                pixmap = QPixmap(widget.iconSize())
                pixmap.fill(Qt.GlobalColor.darkGray)
            icon = QIcon(pixmap)
            label = entry.get('original_name') or entry.get('id', '템플릿')
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, entry.get('id'))
            tooltip_lines = [f"ID: {entry.get('id')}"]
            size_text = f"크기: {entry.get('width', '?')}x{entry.get('height', '?')}"
            tooltip_lines.append(size_text)
            created = entry.get('created_at')
            if created:
                tooltip_lines.append(time.strftime('등록 시각: %Y-%m-%d %H:%M:%S', time.localtime(created)))
            item.setToolTip('\n'.join(tooltip_lines))
            widget.addItem(item)

    def _apply_nameplate_config_to_ui(self):
        config = self.data_manager.get_monster_nameplate_config()
        self.nameplate_config = config
        roi = config.get('roi', {}) if isinstance(config.get('roi'), dict) else {}
        self._nameplate_ui_updating = True
        try:
            enabled = bool(config.get('enabled', False))
            self.nameplate_group.blockSignals(True)
            self.nameplate_group.setChecked(enabled)
            self.nameplate_group.blockSignals(False)
            self.nameplate_dead_zone_spin.setEnabled(enabled)
            self.nameplate_grace_spin.setEnabled(enabled)

            width_val = int(roi.get('width', 135) or 135)
            height_val = int(roi.get('height', 65) or 65)
            offset_x_val = int(roi.get('offset_x', 0) or 0)
            offset_y_val = int(roi.get('offset_y', 0) or 0)

            for spinbox, value in (
                (self.nameplate_width_spin, width_val),
                (self.nameplate_height_spin, height_val),
                (self.nameplate_offset_x_spin, offset_x_val),
                (self.nameplate_offset_y_spin, offset_y_val),
            ):
                spinbox.blockSignals(True)
                spinbox.setValue(value)
                spinbox.blockSignals(False)

            overlay_enabled = bool(config.get('show_overlay', True))
            self.nameplate_overlay_checkbox.blockSignals(True)
            self.nameplate_overlay_checkbox.setChecked(overlay_enabled)
            self.nameplate_overlay_checkbox.blockSignals(False)

            threshold_value = float(config.get('match_threshold', 0.60) or 0.60)
            self.nameplate_threshold_spin.blockSignals(True)
            self.nameplate_threshold_spin.setValue(threshold_value)
            self.nameplate_threshold_spin.blockSignals(False)

            dead_zone_value = float(config.get('dead_zone_sec', 0.20) or 0.0)
            self.nameplate_dead_zone_spin.blockSignals(True)
            self.nameplate_dead_zone_spin.setValue(dead_zone_value)
            self.nameplate_dead_zone_spin.blockSignals(False)

            grace_value = float(config.get('track_missing_grace_sec', 0.12) or 0.0)
            self.nameplate_grace_spin.blockSignals(True)
            self.nameplate_grace_spin.setValue(grace_value)
            self.nameplate_grace_spin.blockSignals(False)
        finally:
            self._nameplate_ui_updating = False

    def _handle_nameplate_enabled_toggled(self, checked: bool) -> None:
        if self._nameplate_ui_updating:
            return
        updated = self.data_manager.update_monster_nameplate_config({'enabled': bool(checked)})
        self.nameplate_config = updated
        if hasattr(self, 'log_viewer'):
            state_text = '활성화' if checked else '비활성화'
            self.log_viewer.append(f"몬스터 이름표 탐지를 {state_text}했습니다.")
        self._apply_nameplate_config_to_ui()

    def _handle_nameplate_overlay_toggled(self, checked: bool) -> None:
        if self._nameplate_ui_updating:
            return
        updated = self.data_manager.update_monster_nameplate_config({'show_overlay': bool(checked)})
        self.nameplate_config = updated
        self._apply_nameplate_config_to_ui()

    def _handle_nameplate_roi_changed(self, _value=None) -> None:
        if self._nameplate_ui_updating:
            return
        roi_updates = {
            'width': self.nameplate_width_spin.value(),
            'height': self.nameplate_height_spin.value(),
            'offset_x': self.nameplate_offset_x_spin.value(),
            'offset_y': self.nameplate_offset_y_spin.value(),
        }
        updated = self.data_manager.update_monster_nameplate_config({'roi': roi_updates})
        self.nameplate_config = updated
        self._apply_nameplate_config_to_ui()

    def _handle_nameplate_threshold_changed(self, value: float) -> None:
        if self._nameplate_ui_updating:
            return
        updated = self.data_manager.update_monster_nameplate_config({'match_threshold': float(value)})
        self.nameplate_config = updated
        self._apply_nameplate_config_to_ui()

    def _handle_nameplate_dead_zone_changed(self, value: float) -> None:
        if self._nameplate_ui_updating:
            return
        value = float(value)
        updated = self.data_manager.update_monster_nameplate_config({'dead_zone_sec': value})
        self.nameplate_config = updated
        self._apply_nameplate_config_to_ui()

    def _handle_nameplate_grace_changed(self, value: float) -> None:
        if self._nameplate_ui_updating:
            return
        value = float(value)
        updated = self.data_manager.update_monster_nameplate_config({'track_missing_grace_sec': value})
        self.nameplate_config = updated
        self._apply_nameplate_config_to_ui()

    # --- 상태 모니터링 UI 구성 ---
    def _create_status_monitor_group(self) -> QGroupBox:
        group = QGroupBox("HP / MP / EXP 설정")
        layout = QVBoxLayout()
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.hp_card = self._build_status_card('hp')
        self.mp_card = self._build_status_card('mp')
        self.exp_card = self._build_exp_status_card()

        cards_layout.addWidget(self.hp_card)
        cards_layout.addWidget(self.mp_card)
        cards_layout.addWidget(self.exp_card)

        layout.addLayout(cards_layout)
        group.setLayout(layout)
        return group

    def _build_status_card(self, resource: str) -> QGroupBox:
        title = 'HP' if resource == 'hp' else 'MP'
        box = QGroupBox()
        vbox = QVBoxLayout()

        header_layout = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet('font-weight: bold;')
        header_layout.addWidget(title_label)
        enabled_checkbox = QCheckBox('사용')
        header_layout.addWidget(enabled_checkbox)
        header_layout.addStretch(1)
        vbox.addLayout(header_layout)

        button = QPushButton('탐지 범위 설정')
        button.clicked.connect(lambda _, key=resource: self._select_status_roi(key))
        vbox.addWidget(button)

        roi_label = QLabel('범위가 설정되지 않았습니다.')
        roi_label.setWordWrap(True)
        vbox.addWidget(roi_label)

        max_layout = QHBoxLayout()
        max_label = QLabel(f'최대 {title}:')
        max_layout.addWidget(max_label)
        max_input = QLineEdit()
        max_input.setPlaceholderText('예: 120')
        max_input.setValidator(QIntValidator(1, 999999, max_input))
        max_layout.addWidget(max_input)
        vbox.addLayout(max_layout)

        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel('회복 % 설정:'))
        input_field = QLineEdit()
        input_field.setPlaceholderText('예: 70')
        input_field.setValidator(QIntValidator(1, 99, input_field))
        threshold_layout.addWidget(input_field)
        vbox.addLayout(threshold_layout)

        command_layout = QHBoxLayout()
        command_layout.addWidget(QLabel('명령 프로필:'))
        combo = QComboBox()
        command_layout.addWidget(combo)
        vbox.addLayout(command_layout)

        interval_layout = QHBoxLayout()
        interval_label = QLabel('탐지주기(초):')
        interval_layout.addWidget(interval_label)
        interval_input = QLineEdit()
        interval_input.setPlaceholderText('예: 1.0')
        validator = QDoubleValidator(0.1, 3600.0, 2, interval_input)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        interval_input.setValidator(validator)
        interval_layout.addWidget(interval_input)
        vbox.addLayout(interval_layout)

        vbox.addStretch(1)
        box.setLayout(vbox)

        if resource == 'hp':
            self.hp_enabled_checkbox = enabled_checkbox
            self.hp_roi_button = button
            self.hp_roi_label = roi_label
            self.hp_max_input = max_input
            self.hp_threshold_input = input_field
            self.hp_command_combo = combo
            self.hp_interval_input = interval_input
            self.hp_enabled_checkbox.toggled.connect(lambda checked: self._on_status_enabled_changed('hp', checked))
            self.hp_max_input.editingFinished.connect(lambda: self._on_status_max_changed('hp'))
            self.hp_threshold_input.editingFinished.connect(lambda: self._on_status_threshold_changed('hp'))
            self.hp_command_combo.currentIndexChanged.connect(lambda _: self._on_status_command_changed('hp'))
            self.hp_interval_input.editingFinished.connect(lambda: self._on_status_interval_changed('hp'))
        else:
            self.mp_enabled_checkbox = enabled_checkbox
            self.mp_roi_button = button
            self.mp_roi_label = roi_label
            self.mp_max_input = max_input
            self.mp_threshold_input = input_field
            self.mp_command_combo = combo
            self.mp_interval_input = interval_input
            self.mp_enabled_checkbox.toggled.connect(lambda checked: self._on_status_enabled_changed('mp', checked))
            self.mp_max_input.editingFinished.connect(lambda: self._on_status_max_changed('mp'))
            self.mp_threshold_input.editingFinished.connect(lambda: self._on_status_threshold_changed('mp'))
            self.mp_command_combo.currentIndexChanged.connect(lambda _: self._on_status_command_changed('mp'))
            self.mp_interval_input.editingFinished.connect(lambda: self._on_status_interval_changed('mp'))

        return box

    def _build_exp_status_card(self) -> QGroupBox:
        box = QGroupBox()
        vbox = QVBoxLayout()
        header_layout = QHBoxLayout()
        title_label = QLabel('EXP')
        title_label.setStyleSheet('font-weight: bold;')
        header_layout.addWidget(title_label)
        self.exp_enabled_checkbox = QCheckBox('사용')
        header_layout.addWidget(self.exp_enabled_checkbox)
        header_layout.addStretch(1)
        vbox.addLayout(header_layout)
        self.exp_roi_button = QPushButton('탐지 범위 설정')
        self.exp_roi_button.clicked.connect(lambda: self._select_status_roi('exp'))
        vbox.addWidget(self.exp_roi_button)

        self.exp_roi_label = QLabel('범위가 설정되지 않았습니다.')
        self.exp_roi_label.setWordWrap(True)
        vbox.addWidget(self.exp_roi_label)

        info_label = QLabel('탐지 주기: 60초 (고정)')
        self.exp_interval_label = info_label
        vbox.addWidget(info_label)

        self.exp_preview_button = QPushButton('인식 확인')
        self.exp_preview_button.setToolTip('현재 EXP 탐지 범위에서 캡처한 화면과 OCR 결과를 확인합니다.')
        self.exp_preview_button.clicked.connect(self._handle_exp_preview)
        vbox.addWidget(self.exp_preview_button)

        vbox.addStretch(1)
        box.setLayout(vbox)
        self.exp_enabled_checkbox.toggled.connect(lambda checked: self._on_status_enabled_changed('exp', checked))
        return box

    def _load_status_command_options(self) -> None:
        profiles = self.data_manager.list_command_profiles(('스킬', '기타'))
        options: list[tuple[str, str]] = []
        for category in ('스킬', '기타'):
            names = profiles.get(category, []) if isinstance(profiles, dict) else []
            for name in names:
                options.append((category, name))
        self._status_command_options = options

    def _apply_status_config_to_ui(self) -> None:
        if not hasattr(self, 'hp_roi_label'):
            return
        self._status_ui_updating = True
        try:
            hp_roi_text = self._format_status_roi(self._status_config.hp.roi)
            mp_roi_text = self._format_status_roi(self._status_config.mp.roi)
            exp_roi_text = self._format_status_roi(self._status_config.exp.roi)
            self.hp_roi_label.setText(hp_roi_text)
            self.mp_roi_label.setText(mp_roi_text)
            self.exp_roi_label.setText(exp_roi_text)

            self._populate_status_combo(self.hp_command_combo, self._status_config.hp.command_profile)
            self._populate_status_combo(self.mp_command_combo, self._status_config.mp.command_profile)

            self._set_line_edit_value(getattr(self, 'hp_max_input', None), self._status_config.hp.maximum_value)
            self._set_line_edit_value(getattr(self, 'mp_max_input', None), self._status_config.mp.maximum_value)
            self._set_line_edit_value(self.hp_threshold_input, self._status_config.hp.recovery_threshold)
            self._set_line_edit_value(self.mp_threshold_input, self._status_config.mp.recovery_threshold)

            self._set_interval_value(self.hp_interval_input, self._status_config.hp.interval_sec)
            self._set_interval_value(self.mp_interval_input, self._status_config.mp.interval_sec)

            self._set_checkbox_state(self.hp_enabled_checkbox, self._status_config.hp.enabled)
            self._set_checkbox_state(self.mp_enabled_checkbox, self._status_config.mp.enabled)
            self._set_checkbox_state(self.exp_enabled_checkbox, self._status_config.exp.enabled)

            self._set_status_controls_enabled('hp', self._status_config.hp.enabled)
            self._set_status_controls_enabled('mp', self._status_config.mp.enabled)
            self._set_status_controls_enabled('exp', self._status_config.exp.enabled)
        finally:
            self._status_ui_updating = False

    def _set_line_edit_value(self, widget: QLineEdit, value: Optional[int]) -> None:
        if widget is None:
            return
        widget.blockSignals(True)
        widget.setText('' if value is None else str(int(value)))
        widget.blockSignals(False)

    def _set_checkbox_state(self, checkbox: QCheckBox, checked: bool) -> None:
        if checkbox is None:
            return
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(checked))
        checkbox.blockSignals(False)

    def _set_interval_value(self, widget: QLineEdit, value: float) -> None:
        if widget is None:
            return
        widget.blockSignals(True)
        text = f"{float(value):.2f}" if abs(value - round(value)) > 1e-6 else str(int(round(value)))
        widget.setText(text)
        widget.blockSignals(False)

    def _set_status_controls_enabled(self, resource: str, enabled: bool) -> None:
        enabled = bool(enabled)
        if resource == 'hp':
            controls = [
                getattr(self, 'hp_roi_button', None),
                getattr(self, 'hp_max_input', None),
                getattr(self, 'hp_threshold_input', None),
                getattr(self, 'hp_command_combo', None),
                getattr(self, 'hp_interval_input', None),
            ]
        elif resource == 'mp':
            controls = [
                getattr(self, 'mp_roi_button', None),
                getattr(self, 'mp_max_input', None),
                getattr(self, 'mp_threshold_input', None),
                getattr(self, 'mp_command_combo', None),
                getattr(self, 'mp_interval_input', None),
            ]
        else:
            controls = [
                getattr(self, 'exp_roi_button', None),
                getattr(self, 'exp_preview_button', None),
            ]
            if getattr(self, 'exp_interval_label', None):
                if enabled:
                    self.exp_interval_label.setText('탐지 주기: 60초 (고정)')
                else:
                    self.exp_interval_label.setText('탐지 주기: 60초 (비활성)')

        for control in controls:
            if control is not None:
                control.setEnabled(enabled)

    def _handle_exp_preview(self) -> None:
        if not hasattr(self, '_status_config') or self._status_config is None:
            QMessageBox.warning(self, 'EXP 인식 확인', '상태 모니터 구성이 아직 초기화되지 않았습니다.')
            return

        roi = getattr(self._status_config.exp, 'roi', StatusRoi())
        if not roi.is_valid():
            QMessageBox.information(self, 'EXP 인식 확인', '탐지 범위가 설정되지 않아 확인할 수 없습니다. 먼저 ROI를 지정해주세요.')
            return

        monitor_dict = roi.to_monitor_dict()
        manager = get_capture_manager()
        consumer_name = f"learning:exp_preview:{id(self)}:{int(time.time()*1000)}"
        frame_bgr: Optional[np.ndarray] = None
        try:
            manager.register_region(consumer_name, monitor_dict)
            frame_bgr = manager.get_frame(consumer_name, timeout=1.0)
        except Exception:
            frame_bgr = None
        finally:
            try:
                manager.unregister_region(consumer_name)
            except KeyError:
                pass

        if frame_bgr is None or frame_bgr.size == 0:
            try:
                with mss.mss() as sct:
                    raw = np.array(sct.grab(monitor_dict))
            except Exception as exc:  # pragma: no cover - 시스템 환경에 따라 다름
                QMessageBox.warning(self, 'EXP 인식 확인', f'화면 캡처에 실패했습니다.\n{exc}')
                return

            if raw.size == 0:
                QMessageBox.warning(self, 'EXP 인식 확인', '캡처 결과가 비어 있습니다. ROI 범위를 다시 확인해주세요.')
                return

            try:
                frame_bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
            except cv2.error as exc:  # pragma: no cover - OpenCV 내부 오류 대비
                QMessageBox.warning(self, 'EXP 인식 확인', f'이미지 변환 중 오류가 발생했습니다.\n{exc}')
                return

        preview = self._prepare_exp_preview(frame_bgr)
        roi_text = self._format_status_roi(roi)
        dialog = ExpRecognitionPreviewDialog(
            self,
            f'탐지 범위: {roi_text}',
            frame_bgr,
            preview.get('processed'),
            preview.get('summary_lines', []),
        )
        dialog.exec()

    def _prepare_exp_preview(self, image_bgr: np.ndarray) -> dict:
        result: dict = {
            'processed': None,
            'summary_lines': [],
        }

        if image_bgr is None or image_bgr.size == 0:
            result['summary_lines'] = ['상태: 캡처 이미지가 비어 있습니다.']
            return result

        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(
            gray,
            (0, 0),
            fx=1.2,
            fy=1.2,
            interpolation=cv2.INTER_CUBIC,
        )
        _, thresh = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        result['processed'] = thresh

        lines: list[str] = []

        if not PYTESSERACT_AVAILABLE or pytesseract is None:
            lines.append('상태: pytesseract가 설치되어 있지 않아 OCR을 수행할 수 없습니다.')
            return {**result, 'summary_lines': lines}

        config = '--psm 7 -c tessedit_char_whitelist=0123456789.%[]'
        try:
            text = pytesseract.image_to_string(thresh, config=config)
        except Exception as exc:  # pragma: no cover - pytesseract 내부 오류 대비
            lines.append(f'상태: pytesseract 실행 중 오류가 발생했습니다. ({exc})')
            return {**result, 'summary_lines': lines}

        cleaned = text.strip().replace('\n', ' ') if text else ''

        amount = StatusMonitorThread._extract_exp_amount(cleaned) if cleaned else None
        percent = StatusMonitorThread._extract_exp_percent(cleaned) if cleaned else None

        if not cleaned:
            lines.append('상태: OCR 결과가 비어 있습니다.')
        elif amount is None or percent is None:
            lines.append('상태: OCR 결과를 해석하지 못했습니다.')
        else:
            lines.append('상태: OCR 성공')

        lines.append(f'OCR 원문: {text.strip() if text else "(비어 있음)"}')
        lines.append(f'정제된 문자열: {cleaned if cleaned else "(비어 있음)"}')

        if amount is not None:
            lines.append(f'추출된 경험치 값: {amount}')
        else:
            lines.append('추출된 경험치 값: 해석 실패')

        if percent is not None:
            lines.append(f'추출된 EXP 퍼센트: {percent:.2f}%')
        else:
            lines.append('추출된 EXP 퍼센트: 해석 실패')

        return {**result, 'summary_lines': lines}


    def _populate_status_combo(self, combo: QComboBox, selected: Optional[str]) -> None:
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem('(선택 없음)', '')
        for category, name in self._status_command_options:
            combo.addItem(f"[{category}] {name}", name)
        if selected:
            index = combo.findData(selected)
            if index == -1:
                combo.addItem(f"[기타] {selected}", selected)
                index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _format_status_roi(self, roi: StatusRoi) -> str:
        if not isinstance(roi, StatusRoi) or not roi.is_valid():
            return '범위가 설정되지 않았습니다.'
        return f"위치: ({roi.left}, {roi.top}) / 크기: {roi.width}×{roi.height}"

    def _select_status_roi(self, resource: str) -> None:
        try:
            selector = StatusRegionSelector(self)
        except RuntimeError as exc:
            QMessageBox.warning(self, '오류', str(exc))
            return
        if selector.exec():
            rect = selector.get_roi()
            updates = {
                resource: {
                    'roi': {
                        'left': rect.left(),
                        'top': rect.top(),
                        'width': rect.width(),
                        'height': rect.height(),
                    }
                }
            }
            self._status_config = self.data_manager.update_status_monitor_config(updates)
            self._apply_status_config_to_ui()

    def _on_status_threshold_changed(self, resource: str) -> None:
        if self._status_ui_updating:
            return
        widget = self.hp_threshold_input if resource == 'hp' else self.mp_threshold_input
        text = widget.text().strip() if widget else ''
        value = None
        if text:
            try:
                val = int(text)
                if 1 <= val <= 99:
                    value = val
            except ValueError:
                pass
        updates = {resource: {'recovery_threshold': value}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _on_status_max_changed(self, resource: str) -> None:
        if self._status_ui_updating:
            return
        widget = self.hp_max_input if resource == 'hp' else self.mp_max_input
        if widget is None:
            return
        text = widget.text().strip()
        if not text:
            updates = {resource: {'max_value': None}}
        else:
            try:
                value = int(text)
            except ValueError:
                self._apply_status_config_to_ui()
                return
            if value <= 0:
                self._apply_status_config_to_ui()
                return
            updates = {resource: {'max_value': value}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _on_status_interval_changed(self, resource: str) -> None:
        if self._status_ui_updating:
            return
        widget = self.hp_interval_input if resource == 'hp' else self.mp_interval_input
        text = widget.text().strip() if widget else ''
        if not text:
            self._apply_status_config_to_ui()
            return
        try:
            val = float(text)
            if val <= 0:
                raise ValueError
        except ValueError:
            self._apply_status_config_to_ui()
            return
        updates = {resource: {'interval_sec': val}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _on_status_command_changed(self, resource: str) -> None:
        if self._status_ui_updating:
            return
        combo = self.hp_command_combo if resource == 'hp' else self.mp_command_combo
        data = combo.currentData() if combo else ''
        command = data if isinstance(data, str) and data else None
        updates = {resource: {'command_profile': command}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _on_status_enabled_changed(self, resource: str, checked: bool) -> None:
        if self._status_ui_updating:
            return
        updates = {resource: {'enabled': bool(checked)}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _handle_status_config_changed(self, config: StatusMonitorConfig) -> None:
        self._status_config = config
        self._load_status_command_options()
        self._apply_status_config_to_ui()

    def on_nickname_text_changed(self):
        if self._nickname_ui_updating:
            return
        text = self.nickname_text_input.text().strip()
        if not text:
            text = '버프몬'
            self.nickname_text_input.setText(text)
        self.nickname_config = self.data_manager.update_nickname_config({'target_text': text})
        self.log_viewer.append(f"닉네임 기준 문자열을 '{text}'(으)로 설정했습니다.")

    def on_nickname_overlay_toggled(self, checked: bool):
        if self._nickname_ui_updating:
            return
        self.nickname_config = self.data_manager.update_nickname_config({'show_overlay': bool(checked)})
        state_text = '표시' if checked else '비표시'
        self.log_viewer.append(f"닉네임 실시간 표기를 {state_text}로 전환했습니다.")

    def on_nickname_threshold_committed(self):
        if self._nickname_ui_updating:
            return
        value = float(self.nickname_threshold_spin.value())
        self.nickname_config = self.data_manager.update_nickname_config({'match_threshold': value})

    def on_nickname_offset_committed(self):
        if self._nickname_ui_updating:
            return
        updates = {
            'char_offset_x': int(self.nickname_offset_x_spin.value()),
            'char_offset_y': int(self.nickname_offset_y_spin.value()),
        }
        self.nickname_config = self.data_manager.update_nickname_config(updates)

    def on_nickname_margin_committed(self):
        if self._nickname_ui_updating:
            return
        updates = {
            'search_margin_x': int(self.nickname_margin_x_spin.value()),
            'search_margin_top': int(self.nickname_margin_top_spin.value()),
            'search_margin_bottom': int(self.nickname_margin_bottom_spin.value()),
        }
        self.nickname_config = self.data_manager.update_nickname_config(updates)

    def on_nickname_full_scan_delay_committed(self):
        if self._nickname_ui_updating:
            return
        value = float(self.nickname_full_scan_delay_spin.value())
        self.nickname_config = self.data_manager.update_nickname_config({'full_scan_delay_sec': value})
        self.log_viewer.append(f"전체화면 탐색 딜레이를 {value:.2f}초로 설정했습니다.")

    def on_direction_threshold_changed(self, value: float):
        if self._direction_ui_updating:
            return
        self.direction_config = self.data_manager.update_direction_config({'match_threshold': float(value)})
        self.log_viewer.append(f"방향 템플릿 임계값을 {float(value):.2f}로 설정했습니다.")

    def on_direction_offset_changed(self):
        if self._direction_ui_updating:
            return
        offset_value = float(self.direction_offset_spin.value())
        self.direction_config = self.data_manager.update_direction_config({'search_offset_y': offset_value})
        self.log_viewer.append(f"방향 탐색 시작 오프셋을 {offset_value:.0f}px로 설정했습니다.")

    def on_direction_range_changed(self):
        if self._direction_ui_updating:
            return
        updates = {
            'search_height': float(self.direction_height_spin.value()),
            'search_half_width': float(self.direction_half_width_spin.value()),
        }
        self.direction_config = self.data_manager.update_direction_config(updates)
        self.log_viewer.append(
            f"방향 탐색 크기를 높이 {updates['search_height']:.0f}px / 좌우 ±{updates['search_half_width']:.0f}px로 설정했습니다."
        )

    def on_direction_overlay_toggled(self, checked: bool):
        if self._direction_ui_updating:
            return
        self.direction_config = self.data_manager.update_direction_config({'show_overlay': bool(checked)})
        state_text = '표시' if checked else '비표시'
        self.log_viewer.append(f"방향 실시간 표기를 {state_text}로 전환했습니다.")

    def capture_nickname_template(self):
        try:
            snipper = ScreenSnipper(self)
            if snipper.exec():
                roi = snipper.get_roi()
                if roi.width() < 5 or roi.height() < 5:
                    QMessageBox.warning(self, '캡처 오류', '선택한 영역이 너무 작습니다. 닉네임 영역을 다시 선택해주세요.')
                    return
                region = {
                    'top': roi.top(),
                    'left': roi.left(),
                    'width': roi.width(),
                    'height': roi.height(),
                }
                with mss.mss() as sct:
                    sct_img = sct.grab(region)
                frame = np.array(sct_img)
                template_entry = self.data_manager.add_nickname_template(cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), source='capture')
                self._refresh_nickname_config_cache()
                self.populate_nickname_template_list()
                self.log_viewer.append(f"닉네임 템플릿 '{template_entry['id']}'을(를) 추가했습니다.")
        except Exception as exc:
            QMessageBox.critical(self, '닉네임 템플릿 추가 오류', str(exc))

    def import_nickname_templates(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, '닉네임 템플릿 불러오기', '', '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not file_paths:
            return
        added = 0
        errors = []
        for path in file_paths:
            try:
                entry = self.data_manager.import_nickname_template(path)
                added += 1
                self.log_viewer.append(f"닉네임 템플릿 '{entry['id']}' 추가 (파일: {os.path.basename(path)})")
            except Exception as exc:
                errors.append((path, str(exc)))
        if added:
            self._refresh_nickname_config_cache()
            self.populate_nickname_template_list()
        if errors:
            error_text = '\n'.join(f"- {os.path.basename(p)}: {msg}" for p, msg in errors)
            QMessageBox.warning(self, '일부 템플릿 추가 실패', error_text)

    def import_direction_templates(self, side: str):
        caption = '좌측 방향 템플릿 불러오기' if side == 'left' else '우측 방향 템플릿 불러오기'
        file_paths, _ = QFileDialog.getOpenFileNames(self, caption, '', '이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not file_paths:
            return
        added = 0
        errors = []
        for path in file_paths:
            try:
                entry = self.data_manager.import_direction_template(side, path)
                added += 1
                self.log_viewer.append(
                    f"방향 템플릿 '{entry['id']}' 추가 (측: {side}, 파일: {os.path.basename(path)})"
                )
            except Exception as exc:
                errors.append((path, str(exc)))
        if added:
            self._refresh_direction_config_cache()
            self.populate_direction_template_lists()
        if errors:
            error_text = '\n'.join(f"- {os.path.basename(p)}: {msg}" for p, msg in errors)
            QMessageBox.warning(self, '일부 방향 템플릿 추가 실패', error_text)

    def delete_selected_nickname_templates(self):
        selected_items = [item for item in self.nickname_template_list.selectedItems() if item.flags() != Qt.ItemFlag.NoItemFlags]
        if not selected_items:
            QMessageBox.information(self, '삭제', '삭제할 닉네임 템플릿을 선택하세요.')
            return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole)]
        if not ids:
            return
        if QMessageBox.question(
            self,
            '삭제 확인',
            f"선택한 템플릿 {len(ids)}개를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        removed = self.data_manager.delete_nickname_templates(ids)
        if removed:
            self._refresh_nickname_config_cache()
            self.populate_nickname_template_list()
            self.log_viewer.append(f"닉네임 템플릿 {removed}개를 삭제했습니다.")

    def delete_direction_templates(self, side: str):
        widget = self.direction_left_list if side == 'left' else self.direction_right_list
        selected_items = [item for item in widget.selectedItems() if item.flags() != Qt.ItemFlag.NoItemFlags]
        if not selected_items:
            QMessageBox.information(self, '삭제', '삭제할 방향 템플릿을 선택하세요.')
            return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole)]
        if not ids:
            return
        if QMessageBox.question(
            self,
            '삭제 확인',
            f"선택한 방향 템플릿 {len(ids)}개를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        removed = self.data_manager.delete_direction_templates(side, ids)
        if removed:
            self._refresh_direction_config_cache()
            self.populate_direction_template_lists()
            self.log_viewer.append(f"방향 템플릿 {removed}개를 삭제했습니다. (측: {side})")

    def populate_class_list(self):
        """manifest.json 데이터를 기반으로 QTreeWidget을 채웁니다."""
        self.class_tree_widget.blockSignals(True)
        self.class_tree_widget.clear()
        manifest = self.data_manager.get_manifest()
        overrides = self.data_manager.get_monster_confidence_overrides() if self.data_manager else {}

        temp_manifest = manifest
        all_categories_in_manifest = list(temp_manifest.keys())

        base_categories = [category for category in CATEGORIES if category != CHARACTER_CLASS_NAME]
        extra_categories = [
            cat for cat in all_categories_in_manifest
            if cat not in base_categories and cat not in (NEGATIVE_SAMPLES_NAME, CHARACTER_CLASS_NAME)
        ]
        ordered_categories = base_categories + extra_categories

        def add_category_item(category_name: str) -> None:
            if category_name not in temp_manifest:
                return
            category_item = QTreeWidgetItem(self.class_tree_widget, [category_name])
            category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)

            classes_in_category = manifest.get(category_name, {})
            for class_name in classes_in_category:
                class_item = QTreeWidgetItem(category_item, [class_name])
                class_item.setFlags(class_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                class_item.setCheckState(0, Qt.CheckState.Checked)
                self._apply_monster_confidence_indicator(class_item, class_name, overrides)

            category_item.setExpanded(True)

        for category_name in ordered_categories:
            add_category_item(category_name)

        # v1.3: 네거티브 샘플 항목을 트리의 마지막에 추가
        negative_item = QTreeWidgetItem(self.class_tree_widget, [NEGATIVE_SAMPLES_NAME])
        flags = negative_item.flags()
        flags &= ~Qt.ItemFlag.ItemIsUserCheckable
        flags &= ~Qt.ItemFlag.ItemIsDragEnabled
        flags &= ~Qt.ItemFlag.ItemIsDropEnabled
        negative_item.setFlags(flags)
        # 아이콘 설정 (선택사항, 경로를 실제 아이콘 파일로 변경해야 함)
        # try:
        #     icon_path = os.path.join(SRC_ROOT, 'icons', 'warning.png')
        #     if os.path.exists(icon_path):
        #         negative_item.setIcon(0, QIcon(icon_path))
        # except Exception:
        #     pass

        # '캐릭터' 카테고리를 네거티브 항목 아래에 배치
        add_category_item(CHARACTER_CLASS_NAME)

        if self._checked_class_names:
            self._apply_checked_classes_to_tree()
        self.class_tree_widget.blockSignals(False)
        self._persist_checked_classes()

    def _apply_checked_classes_to_tree(self):
        """저장된 체크 정보에 맞게 QTreeWidget의 체크 상태를 맞춘다."""
        if not hasattr(self, "class_tree_widget"):
            return
        was_blocked = self.class_tree_widget.signalsBlocked()
        self.class_tree_widget.blockSignals(True)
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            if category_item.text(0) == NEGATIVE_SAMPLES_NAME:
                continue
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                name = class_item.text(0)
                is_checked = name in self._checked_class_names if self._checked_class_names else True
                class_item.setCheckState(0, Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
        self.class_tree_widget.blockSignals(was_blocked)

    def _collect_checked_class_names(self) -> list[str]:
        names: list[str] = []
        if not hasattr(self, "class_tree_widget"):
            return names
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            if category_item.text(0) == NEGATIVE_SAMPLES_NAME:
                continue
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                if class_item.checkState(0) == Qt.CheckState.Checked:
                    names.append(class_item.text(0))
        return names

    def _persist_checked_classes(self) -> None:
        if not hasattr(self, "data_manager") or not self.data_manager:
            return
        checked_names = self._collect_checked_class_names()
        self._checked_class_names = set(checked_names)
        try:
            self.data_manager.save_settings({'hunt_checked_classes': checked_names})
        except Exception:
            pass

    def _default_monster_confidence(self) -> float:
        return DEFAULT_MONSTER_CONFIDENCE

    def _apply_monster_confidence_indicator(
        self,
        item: Optional[QTreeWidgetItem],
        class_name: str,
        overrides: Optional[dict[str, float]] = None,
    ) -> None:
        if item is None:
            return
        if overrides is None:
            overrides = (
                self.data_manager.get_monster_confidence_overrides()
                if getattr(self, 'data_manager', None)
                else {}
            )
        value = overrides.get(class_name)
        font = item.font(0)
        if value is not None:
            font.setItalic(True)
            item.setFont(0, font)
            item.setToolTip(0, f"개별 신뢰도: {value:.2f}")
            item.setForeground(0, QBrush(QColor(47, 133, 90)))
        else:
            font.setItalic(False)
            item.setFont(0, font)
            item.setToolTip(0, "")
            item.setForeground(0, QBrush())

    def _handle_class_item_double_clicked(self, item: Optional[QTreeWidgetItem], column: int) -> None:
        if not item or not item.parent():
            return
        parent_name = item.parent().text(0)
        if parent_name == NEGATIVE_SAMPLES_NAME:
            return
        class_name = item.text(0)
        if class_name == CHARACTER_CLASS_NAME:
            return
        if not getattr(self, 'data_manager', None):
            return
        if getattr(self, '_monster_settings_dialog_open', False):
            return

        overrides = self.data_manager.get_monster_confidence_overrides()
        current_value = overrides.get(class_name)
        dialog = MonsterSettingsDialog(
            self,
            class_name,
            current_value=current_value,
            default_value=self._default_monster_confidence(),
        )
        self._monster_settings_dialog_open = True
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            if dialog.override_enabled:
                self.data_manager.set_monster_confidence_override(class_name, dialog.override_value)
                if hasattr(self, 'log_viewer'):
                    self.log_viewer.append(
                        f"'{class_name}' 개별 신뢰도를 {dialog.override_value:.2f}로 설정했습니다."
                    )
            else:
                self.data_manager.delete_monster_confidence_override(class_name)
                if hasattr(self, 'log_viewer'):
                    self.log_viewer.append(
                        f"'{class_name}' 개별 신뢰도를 전역 값으로 되돌렸습니다."
                    )

            if hasattr(dialog, 'nameplate_threshold_enabled') and hasattr(dialog, 'nameplate_threshold_value'):
                previous_threshold = self.data_manager.get_monster_nameplate_threshold(class_name)
                threshold_to_apply = dialog.nameplate_threshold_value if dialog.nameplate_threshold_enabled else None
                new_threshold = self.data_manager.set_monster_nameplate_threshold(class_name, threshold_to_apply)
                self.nameplate_config = self.data_manager.get_monster_nameplate_config()
                if hasattr(self, 'log_viewer') and new_threshold != previous_threshold:
                    if new_threshold is None:
                        self.log_viewer.append(
                            f"'{class_name}' 이름표 임계값을 전역 값으로 되돌렸습니다."
                        )
                    else:
                        self.log_viewer.append(
                            f"'{class_name}' 이름표 임계값을 {new_threshold:.2f}로 설정했습니다."
                        )

            self._apply_monster_confidence_indicator(item, class_name)
        finally:
            self._monster_settings_dialog_open = False

    def set_image_sort_mode(self, mode):
        self.current_image_sort_mode = mode
        self.sort_by_name_btn.setChecked(mode == 'name')
        self.sort_by_date_btn.setChecked(mode == 'date')
        self.populate_image_list()

    def _get_selected_class_name(self):
        """클래스 트리에서 현재 선택된 클래스 이름을 반환합니다."""
        selected_item = self.class_tree_widget.currentItem() if hasattr(self, 'class_tree_widget') else None
        if not selected_item or selected_item.text(0) == NEGATIVE_SAMPLES_NAME:
            return None
        if selected_item.parent():
            return selected_item.text(0)
        return None

    def _handle_runtime_settings_changed(self, _value=None) -> None:
        if self._runtime_ui_updating:
            return
        try:
            nms_val = float(self.yolo_nms_spin.value())
        except (TypeError, ValueError):
            nms_val = DEFAULT_DETECTION_RUNTIME_SETTINGS['yolo_nms_iou']
        try:
            max_det_val = int(self.yolo_max_det_spin.value())
        except (TypeError, ValueError):
            max_det_val = DEFAULT_DETECTION_RUNTIME_SETTINGS['yolo_max_det']
        self.data_manager.update_detection_runtime_settings(
            yolo_nms_iou=nms_val,
            yolo_max_det=max_det_val,
        )

    def populate_image_list(self):
        self.image_list_widget.clear()
        selected_items = self.class_tree_widget.selectedItems()
        if not selected_items:
            # v1.3: 아무것도 선택되지 않았을 때 버튼 상태 제어
            self.edit_image_btn.setEnabled(False)
            self.delete_image_btn.setEnabled(False)
            self.add_image_btn.setEnabled(False)
            return

        selected_item = selected_items[0]
        item_text = selected_item.text(0)
        image_filenames = []

        if item_text == NEGATIVE_SAMPLES_NAME:
            # v1.3: 네거티브 샘플 항목을 선택한 경우
            manifest = self.data_manager.get_manifest()
            image_filenames = manifest.get(NEGATIVE_SAMPLES_NAME, [])
            self.edit_image_btn.setEnabled(True)
            self.delete_image_btn.setEnabled(True)
            self.add_image_btn.setEnabled(False) # 네거티브 샘플은 파일 추가로 넣지 않음
        elif selected_item.parent():
            # 일반 클래스를 선택한 경우
            class_name = item_text
            image_filenames = self.data_manager.get_images_for_class(class_name)
            self.edit_image_btn.setEnabled(True)
            self.delete_image_btn.setEnabled(True)
            self.add_image_btn.setEnabled(True)
        else:
            # 카테고리를 선택한 경우
            self.edit_image_btn.setEnabled(False)
            self.delete_image_btn.setEnabled(False)
            self.add_image_btn.setEnabled(False)
            return

        image_paths = [os.path.join(self.data_manager.images_path, fname) for fname in image_filenames]

        if self.current_image_sort_mode == 'name':
            image_paths.sort(key=lambda p: os.path.basename(p))
        else: # 'date'
            valid_paths = [p for p in image_paths if os.path.exists(p)]
            valid_paths.sort(key=os.path.getctime, reverse=True)
            image_paths = valid_paths

        for path in image_paths:
            icon = self._get_thumbnail_icon(path)
            item = QListWidgetItem(icon, os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.image_list_widget.addItem(item)

    def _get_thumbnail_icon(self, image_path):
        """이미지 경로에 대한 썸네일 QIcon을 캐시에서 반환하거나 새로 생성합니다."""
        icon_size = self.image_list_widget.iconSize()
        size_tuple = (icon_size.width(), icon_size.height())

        if size_tuple[0] <= 0 or size_tuple[1] <= 0:
            size_tuple = (128, 128)
            icon_size = QSize(*size_tuple)

        cache_entry = self._thumbnail_cache.get(image_path)
        file_mtime = None
        try:
            file_mtime = os.path.getmtime(image_path)
        except OSError:
            file_mtime = None

        if cache_entry and file_mtime is None:
            self._thumbnail_cache.pop(image_path, None)
            cache_entry = None

        if cache_entry and file_mtime is not None:
            cached_mtime, cached_size, cached_icon = cache_entry
            if cached_mtime == file_mtime and cached_size == size_tuple:
                self._thumbnail_cache.move_to_end(image_path)
                return cached_icon
            self._thumbnail_cache.pop(image_path, None)

        placeholder = None
        pixmap = QPixmap()
        if file_mtime is not None and pixmap.load(image_path):
            pixmap = pixmap.scaled(icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            placeholder = QPixmap(icon_size)
            placeholder.fill(Qt.GlobalColor.darkGray)
            pixmap = placeholder

        icon = QIcon(pixmap)

        if file_mtime is not None:
            self._thumbnail_cache[image_path] = (file_mtime, size_tuple, icon)
            self._thumbnail_cache.move_to_end(image_path)
            while len(self._thumbnail_cache) > self._thumbnail_cache_limit:
                self._thumbnail_cache.popitem(last=False)

        return icon

    def _invalidate_thumbnail_cache(self, image_path):
        """지정한 이미지 경로에 대한 캐시를 제거합니다."""
        self._thumbnail_cache.pop(image_path, None)

    def add_class(self):
        selected_item = self.class_tree_widget.currentItem()
        target_category = "기타"
        if selected_item:
            if selected_item.text(0) == NEGATIVE_SAMPLES_NAME: # 방해 요소에는 클래스 추가 불가
                QMessageBox.warning(self, "오류", f"'{NEGATIVE_SAMPLES_NAME}'에는 클래스를 추가할 수 없습니다.")
                return
            target_category = selected_item.text(0) if not selected_item.parent() else selected_item.parent().text(0)

        text, ok = QInputDialog.getText(self, '클래스 추가', f"'{target_category}' 카테고리에 추가할 클래스 이름:")
        if ok and text:
            success, message = self.data_manager.add_class(text, target_category)
            if success:
                self.populate_class_list()
                self.log_viewer.append(message)
                for i in range(self.class_tree_widget.topLevelItemCount()):
                    cat_item = self.class_tree_widget.topLevelItem(i)
                    if cat_item.text(0) == target_category:
                        for j in range(cat_item.childCount()):
                            child_item = cat_item.child(j)
                            if child_item.text(0) == text:
                                self.class_tree_widget.setCurrentItem(child_item)
                                break
                        break
            else:
                QMessageBox.warning(self, "오류", message)

    def rename_class(self):
        selected = self.class_tree_widget.currentItem()
        if not selected or not selected.parent():
            QMessageBox.warning(self, "오류", "이름을 변경할 클래스를 선택하세요.")
            return

        old_name = selected.text(0)
        new_name, ok = QInputDialog.getText(self, "클래스 이름 변경", f"'{old_name}'의 새 이름 입력:", text=old_name)

        if ok and new_name and new_name != old_name:
            checked_states = self.get_checked_states()

            success, message = self.data_manager.rename_class(old_name, new_name)
            if success:
                self.log_viewer.append(message)
                self.populate_class_list()
                self.populate_preset_list()
                self.set_checked_states(checked_states)
            else:
                QMessageBox.critical(self, "이름 변경 오류", message)

    def delete_class(self):
        selected = self.class_tree_widget.currentItem()
        if not selected or not selected.parent():
            QMessageBox.warning(self, "오류", "삭제할 클래스를 선택하세요.")
            return

        class_name = selected.text(0)
        reply = QMessageBox.question(self, '삭제 확인', f"'{class_name}' 클래스를 삭제하시겠습니까?\n이 클래스가 포함된 모든 이미지와 라벨이 삭제될 수 있습니다.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success, message = self.data_manager.delete_class(class_name)
            if success:
                self._thumbnail_cache.clear()
                self.populate_class_list()
                self.image_list_widget.clear()
                self.log_viewer.append(message)
            else:
                QMessageBox.critical(self, "삭제 오류", message)

    def recover_data(self):
        reply = QMessageBox.question(self, '데이터 복구 확인',
                                     "모든 라벨 파일을 스캔하여 이미지 목록을 재구성합니다.\n"
                                     "manifest.json 파일이 덮어씌워집니다. 계속하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.update_status_message("데이터 복구 중...")
            QApplication.processEvents()

            success, message = self.data_manager.rebuild_manifest_from_labels()

            if success:
                self._thumbnail_cache.clear()
                self.update_status_message(message)
                self.log_viewer.append(message)
                self.populate_class_list()
                self.populate_image_list()
            else:
                QMessageBox.critical(self, "복구 오류", message)
                self.update_status_message("복구 실패.")

    def add_images_from_files(self):
        # 1. 현재 선택된 클래스가 있는지 확인
        selected_items = self.class_tree_widget.selectedItems()
        if not selected_items or not selected_items[0].parent():
            QMessageBox.warning(self, "오류", "이미지를 추가할 클래스를 먼저 선택해주세요.")
            return

        selected_class_name = selected_items[0].text(0)

        # 2. 파일 대화 상자 열기
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "데이터셋에 추가할 이미지 선택",
            "", # 기본 경로
            "Image Files (*.png *.jpg *.jpeg *.bmp)"
        )

        if not file_paths:
            return # 사용자가 취소한 경우

        # 3. 선택된 각 파일을 처리
        added_count = 0
        manifest = self.data_manager.get_manifest()
        for file_path in file_paths:
            try:
                # 3-1. 새 파일명 생성 (타임스탬프 기반)
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                # 원본 파일의 확장자를 유지하도록 수정
                original_base, original_ext = os.path.splitext(os.path.basename(file_path))
                new_filename = f"file_{timestamp}_{added_count}_{original_base}{original_ext}"
                
                # 3-2. 이미지/라벨 경로 설정
                new_image_path = os.path.join(self.data_manager.images_path, new_filename)
                new_label_path = os.path.join(self.data_manager.labels_path, f"{os.path.splitext(new_filename)[0]}.txt")

                # 3-3. 파일 복사 및 빈 라벨 생성
                shutil.copy(file_path, new_image_path)
                with open(new_label_path, 'w') as f:
                    pass # 빈 파일 생성

                # 3-4. manifest.json 업데이트
                category = self.data_manager.get_class_category(selected_class_name)
                if category and selected_class_name in manifest[category]:
                    if new_filename not in manifest[category][selected_class_name]:
                        manifest[category][selected_class_name].append(new_filename)
                
                added_count += 1
            except Exception as e:
                self.log_viewer.append(f"'{file_path}' 파일 추가 중 오류 발생: {e}")
                continue
        
        # 4. 최종 저장 및 UI 갱신
        if added_count > 0:
            self.data_manager.save_manifest(manifest)
            self.log_viewer.append(f"'{selected_class_name}' 클래스에 {added_count}개의 이미지를 추가했습니다.")
            self.populate_image_list()

    def delete_image(self):
        selected_items = self.image_list_widget.selectedItems()
        if not selected_items: return
        if QMessageBox.question(self, '삭제', f"이미지 {len(selected_items)}개를 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                image_path = item.data(Qt.ItemDataRole.UserRole)
                if image_path:
                    self._invalidate_thumbnail_cache(image_path)
                    self.data_manager.delete_image(image_path)
            self.populate_image_list()

    def capture_screen(self):
        count = self.capture_count_spinbox.value()
        interval = self.capture_interval_spinbox.value()
        delay_seconds = self.capture_delay_spinbox.value()
        initial_class_name = self._get_selected_class_name()

        # 캡처 시에는 메인 윈도우를 숨길 필요가 없으므로 hide/show 로직 제거
        try:
            QApplication.processEvents() # UI 업데이트
            QThread.msleep(250)

            target_windows = gw.getWindowsWithTitle('Maple') or gw.getWindowsWithTitle('메이플')
            if not target_windows:
                QMessageBox.warning(self, '오류', '메이플스토리 게임 창을 찾을 수 없습니다.')
                return

            target_window = target_windows[0]
            if target_window.isMinimized: target_window.restore(); QThread.msleep(500)

            capture_region = {'top': target_window.top, 'left': target_window.left, 'width': target_window.width, 'height': target_window.height}

            if capture_region['width'] <= 0 or capture_region['height'] <= 0:
                QMessageBox.warning(self, '오류', '게임 창의 크기가 유효하지 않습니다.')
                return

            delay_ms = max(0, int(delay_seconds * 1000))
            if delay_ms:
                self.update_status_message(f"캡처 시작 전 {delay_seconds:.1f}초 대기 중...")
                QThread.msleep(delay_ms)

            captured_pixmaps = []
            with mss.mss() as sct:
                for i in range(count):
                    self.update_status_message(f"{i+1}/{count}번째 캡처 중...")
                    sct_img = sct.grab(capture_region)
                    frame_rgb = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2RGB)
                    h, w, ch = frame_rgb.shape
                    bytes_per_line = ch * w
                    q_image = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    captured_pixmaps.append(QPixmap.fromImage(q_image))
                    if count > 1: QThread.msleep(int(interval * 1000))

            self.update_status_message("캡처 완료")

            if count == 1:
                self.open_editor_mode_dialog(captured_pixmaps[0], initial_class_name=initial_class_name)
            else:
                multi_dialog = MultiCaptureDialog(captured_pixmaps, self)
                if multi_dialog.exec():
                    selected_pixmaps = multi_dialog.get_selected_pixmaps()
                    for pixmap in selected_pixmaps:
                        self.open_editor_mode_dialog(pixmap, initial_class_name=initial_class_name)
        except Exception as e:
            QMessageBox.critical(self, "캡처 오류", str(e))
        finally:
            self.update_status_message("준비")

    def open_editor_mode_dialog(self, pixmap, image_path=None, initial_polygons=None, initial_class_name=None):
        dialog = EditModeDialog(pixmap, self.sam_predictor is not None, self)
        mode_result = dialog.exec()
        editor = None
        if mode_result == EditModeDialog.AI_ASSIST:
            editor = SAMAnnotationEditor(pixmap, self.sam_predictor, initial_polygons, self, initial_class_name)
        elif mode_result == EditModeDialog.MANUAL:
            editor = PolygonAnnotationEditor(pixmap, initial_polygons, self, initial_class_name)
        else:
            return

        editor_result = editor.exec()

        # v1.3: 편집기에서 반환된 결과에 따라 분기 처리
        # 시나리오 1: 일반 저장
        if editor_result == QDialog.DialogCode.Accepted:
            previously_selected_class = initial_class_name

            self.populate_class_list() # 새 클래스가 추가되었을 수 있으므로 목록 갱신

            if previously_selected_class:
                self.select_class_item_by_name(previously_selected_class)

            polygons_data = editor.get_all_polygons()
            final_class_list = self.data_manager.get_class_list()
            
            label_lines, involved_class_ids = [], set()
            # 클래스가 할당된 다각형만 라벨로 변환
            labeled_polygons = [p for p in polygons_data if p.get('class_id') is not None]

            filtered_small_polygons = 0
            if labeled_polygons:
                q_img = pixmap.toImage()
                w, h = q_img.width(), q_img.height()
                for poly_data in labeled_polygons:
                    class_id, points = poly_data['class_id'], poly_data['points']
                    if w > 0 and h > 0:
                        is_monster_class = False
                        if 0 <= class_id < len(final_class_list):
                            class_name = final_class_list[class_id]
                            category = self.data_manager.get_class_category(class_name)
                            is_monster_class = category == "몬스터"
                        if is_monster_class and points:
                            xs = [p.x() for p in points]
                            ys = [p.y() for p in points]
                            width_px = max(xs) - min(xs)
                            height_px = max(ys) - min(ys)
                            if (
                                width_px < MIN_MONSTER_LABEL_SIZE
                                or height_px < MIN_MONSTER_LABEL_SIZE
                            ):
                                filtered_small_polygons += 1
                                continue
                        normalized_points = [f"{p.x()/w:.6f} {p.y()/h:.6f}" for p in points]
                        label_lines.append(f"{class_id} {' '.join(normalized_points)}")
                        involved_class_ids.add(class_id)

            involved_classes = [final_class_list[i] for i in involved_class_ids if i < len(final_class_list)]
            label_content = "\n".join(label_lines)

            if filtered_small_polygons and hasattr(self, 'log_viewer'):
                self.log_viewer.append(
                    f"{MIN_MONSTER_LABEL_SIZE}px 미만 몬스터 라벨 {filtered_small_polygons}개를 제외했습니다."
                )

            filename_to_update = os.path.basename(image_path) if image_path else None

            if image_path: # 기존 이미지 편집
                self.data_manager.update_label(image_path, label_content, involved_classes)
                # 만약 이 이미지가 이전에 네거티브 샘플이었다면, 목록에서 제거 (승격)
                if label_content:
                    manifest = self.data_manager.get_manifest()
                    if filename_to_update in manifest.get(NEGATIVE_SAMPLES_NAME, []):
                        manifest[NEGATIVE_SAMPLES_NAME].remove(filename_to_update)
                        self.data_manager.save_manifest(manifest)
                        self.log_viewer.append(f"'{filename_to_update}'가 네거티브 샘플에서 일반 클래스로 승격되었습니다.")
                self.log_viewer.append(f"'{filename_to_update}' 라벨 업데이트 완료.")
            elif label_content: # 새 이미지 추가
                q_img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
                w, h = q_img.width(), q_img.height()
                ptr = q_img.bits(); ptr.setsize(q_img.sizeInBytes())
                arr = np.array(ptr).reshape(h, q_img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
                cropped_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                filename = self.data_manager.add_image_and_label_multi_class(cropped_bgr, label_content, involved_classes)
                self.log_viewer.append(f"새로운 다중 클래스 이미지 '{filename}' 추가 완료.")
            else: # 새 이미지인데 라벨이 없는 경우 -> 네거티브 샘플로 저장
                q_img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
                w, h = q_img.width(), q_img.height()
                ptr = q_img.bits(); ptr.setsize(q_img.sizeInBytes())
                arr = np.array(ptr).reshape(h, q_img.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
                full_image_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                # 전체 이미지를 방해 요소로 추가
                filename = self.data_manager.add_distractor(full_image_bgr)
                self.log_viewer.append(f"라벨 없는 전체 이미지를 방해 요소 '{filename}'(으)로 추가했습니다.")

        # 시나리오 2: 방해 요소로 저장
        elif editor_result == PolygonAnnotationEditor.DistractorSaved:
            polygons_data = editor.get_all_polygons()
            if not polygons_data: return

            # 마지막 다각형을 방해 요소로 간주
            distractor_polygon_data = polygons_data[-1]

            polygon_points = distractor_polygon_data['points']
            bounding_rect = QPolygon([QPoint(int(p.x()), int(p.y())) for p in polygon_points]).boundingRect()

            original_image = pixmap.toImage()
            cropped_qimage = original_image.copy(bounding_rect)

            # QImage를 OpenCV Numpy 배열로 변환
            cropped_qimage = cropped_qimage.convertToFormat(QImage.Format.Format_RGB888)
            w, h = cropped_qimage.width(), cropped_qimage.height()
            ptr = cropped_qimage.bits()
            ptr.setsize(cropped_qimage.sizeInBytes())
            arr = np.array(ptr).reshape(h, cropped_qimage.bytesPerLine())[:, :w * 3].reshape(h, w, 3)
            cropped_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

            filename = self.data_manager.add_distractor(cropped_bgr)
            origin_name = f"(원본: {os.path.basename(image_path)})" if image_path else "(원본: 새 캡처)"
            self.log_viewer.append(f"새로운 방해 요소 '{filename}'를 추가했습니다. {origin_name}")

        self.populate_image_list()

    def select_class_item_by_name(self, class_name):
        """이름으로 클래스 트리 아이템을 찾아 선택합니다."""
        if not class_name: return
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                if class_item.text(0) == class_name:
                    self.class_tree_widget.setCurrentItem(class_item)
                    return

    def edit_selected_image(self):
        image_paths_to_edit = [item.data(Qt.ItemDataRole.UserRole) for item in self.image_list_widget.selectedItems()]

        if not image_paths_to_edit:
            QMessageBox.warning(self, '오류', '편집할 이미지를 선택하세요.'); return

        selected_class_item = self.class_tree_widget.currentItem()
        if not selected_class_item: return

        # v1.3: 네거티브 샘플인지 확인
        is_editing_negative_sample = (selected_class_item.text(0) == NEGATIVE_SAMPLES_NAME)
        
        # 네거티브 샘플을 편집할 때는 초기 클래스 이름이 없음
        if is_editing_negative_sample:
            initial_class_name = None
        elif selected_class_item.parent():
             initial_class_name = selected_class_item.text(0)
        else: # 카테고리가 선택된 경우는 없음(버튼 비활성화)
            return

        for image_path in image_paths_to_edit:
            img_bgr = cv2.imread(image_path)
            if img_bgr is None:
                self.log_viewer.append(f"오류: '{os.path.basename(image_path)}' 파일을 열 수 없습니다.")
                continue

            h, w, _ = img_bgr.shape
            label_path = os.path.join(self.data_manager.labels_path, f"{os.path.splitext(os.path.basename(image_path))[0]}.txt")
            initial_polygons = []
            if os.path.exists(label_path):
                with open(label_path, 'r') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) > 1:
                            class_id = int(parts[0])
                            coords = [float(c) for c in parts[1:]]
                            poly_points = [QPoint(int(coords[i] * w), int(coords[i+1] * h)) for i in range(0, len(coords), 2)]
                            initial_polygons.append({'class_id': class_id, 'points': poly_points})

            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = img_rgb.shape
            bytes_per_line = ch * w
            q_image = QImage(img_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.open_editor_mode_dialog(QPixmap.fromImage(q_image), image_path=image_path, initial_polygons=initial_polygons, initial_class_name=initial_class_name)

    def start_training(self):
        if len(self.data_manager.get_class_list()) == 0:
            QMessageBox.warning(self, "오류", "훈련할 클래스가 하나 이상 있어야 합니다.")
            return

        self.log_viewer.clear()
        yaml_path = self.data_manager.create_yaml_file()
        self.log_viewer.append(f"데이터셋 설정 파일 생성 완료: '{yaml_path}'")
        epochs = self.epoch_spinbox.value()
        base_model = self.base_model_selector.currentText()
        self.train_btn.setEnabled(False)
        
        # (v1.2) TrainingThread에 training_runs 경로 전달
        training_runs_path = os.path.join(self.data_manager.workspace_root, 'training_runs')
        self.training_thread = TrainingThread(yaml_path, epochs, base_model, training_runs_path)
        
        self.training_thread.progress.connect(self.log_viewer.append)
        self.training_thread.results_path_ready.connect(self.log_training_path)
        self.training_thread.finished.connect(self.training_finished)
        self.training_thread.start()

    def log_training_path(self, path):
        self.latest_run_dir = path
        self.log_viewer.append(f"훈련 결과 저장 경로: {os.path.abspath(path)}")
        self.save_model_btn.setEnabled(True)

    def training_finished(self, success, message):
        QMessageBox.information(self, '훈련 완료' if success else '훈련 오류', message)
        self.train_btn.setEnabled(True)

    def save_latest_training_result(self):
        if not self.latest_run_dir: QMessageBox.warning(self, '오류', '저장할 최신 훈련 결과가 없습니다.'); return
        text, ok = QInputDialog.getText(self, '모델 버전 저장', '모델 버전 이름을 입력하세요 (예: v1-slime):')
        if ok and text:
            if self.data_manager.save_model_version(self.latest_run_dir, text):
                self.log_viewer.append(f"모델 '{text}' 버전 저장 완료.")
                self.populate_model_list()
                self.model_selector.setCurrentText(text)
            else: QMessageBox.critical(self, '오류', '모델 저장 실패.')

    def start_exporting(self):
        selected_model = self.model_selector.currentText()
        if not selected_model: return
        model_path = os.path.join(self.data_manager.models_path, selected_model, 'weights', 'best.pt')
        if not os.path.exists(model_path): QMessageBox.warning(self, '오류', f"best.pt 파일을 찾을 수 없습니다."); return
        self.export_btn.setEnabled(False)
        self.export_thread = ExportThread(model_path)
        self.export_thread.progress.connect(self.log_viewer.append)
        self.export_thread.finished.connect(self.exporting_finished)
        self.export_thread.start()

    def exporting_finished(self, success, message):
        QMessageBox.information(self, '최적화 완료' if success else '최적화 오류', message)
        self.export_btn.setEnabled(True)

    def delete_saved_model(self):
        model_name = self.model_selector.currentText()
        if not model_name: QMessageBox.warning(self, "오류", "삭제할 모델을 선택하세요."); return
        reply = QMessageBox.question(self, "삭제 확인", f"'{model_name}' 모델을 정말로 삭제하시겠습니까?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            success, message = self.data_manager.delete_model_version(model_name)
            if success:
                self.log_viewer.append(message); self.populate_model_list()
            else: QMessageBox.critical(self, "삭제 오류", message)

    def get_checked_class_indices(self):
        """QTreeWidget에서 체크된 클래스들의 인덱스를 가져옵니다."""
        all_classes = self.data_manager.get_class_list()
        checked_indices = []
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                if class_item.checkState(0) == Qt.CheckState.Checked:
                    class_name = class_item.text(0)
                    if class_name in all_classes:
                        checked_indices.append(all_classes.index(class_name))
        return checked_indices

    def populate_preset_list(self):
        self.preset_selector.blockSignals(True)
        self.preset_selector.clear()
        presets = self.data_manager.get_presets()
        self.preset_selector.addItems(presets.keys())
        self.preset_selector.blockSignals(False)

    def add_preset(self):
        preset_name, ok = QInputDialog.getText(self, "프리셋 추가", "새 프리셋 이름:")
        if ok and preset_name:
            presets = self.data_manager.get_presets()
            if preset_name in presets: QMessageBox.warning(self, "오류", "이미 존재하는 프리셋 이름입니다."); return

            checked_classes = [self.data_manager.get_class_list()[i] for i in self.get_checked_class_indices()]
            presets[preset_name] = checked_classes
            self.data_manager.save_presets(presets)
            self.populate_preset_list()
            self.preset_selector.setCurrentText(preset_name)

    def update_preset(self):
        preset_name = self.preset_selector.currentText()
        if not preset_name: QMessageBox.warning(self, "오류", "수정할 프리셋을 선택하세요."); return
        presets = self.data_manager.get_presets()
        checked_classes = [self.data_manager.get_class_list()[i] for i in self.get_checked_class_indices()]
        presets[preset_name] = checked_classes
        self.data_manager.save_presets(presets)
        QMessageBox.information(self, "성공", f"'{preset_name}' 프리셋이 업데이트되었습니다.")

    def delete_preset(self):
        preset_name = self.preset_selector.currentText()
        if not preset_name: QMessageBox.warning(self, "오류", "삭제할 프리셋을 선택하세요."); return
        if QMessageBox.question(self, "삭제 확인", f"'{preset_name}' 프리셋을 정말 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            presets = self.data_manager.get_presets()
            if preset_name in presets:
                del presets[preset_name]
                self.data_manager.save_presets(presets)
                self.populate_preset_list()

    def load_preset(self):
        preset_name = self.preset_selector.currentText()
        if not preset_name: return
        presets = self.data_manager.get_presets()
        checked_classes = presets.get(preset_name, [])

        self.class_tree_widget.blockSignals(True)
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                if class_item.text(0) in checked_classes:
                    class_item.setCheckState(0, Qt.CheckState.Checked)
                else:
                    class_item.setCheckState(0, Qt.CheckState.Unchecked)
        self.class_tree_widget.blockSignals(False)
        self._persist_checked_classes()

    def save_tree_state_to_manifest(self):
        old_manifest = self.data_manager.get_manifest()
        all_class_data = {}
        for category in old_manifest:
            if category == NEGATIVE_SAMPLES_NAME: continue
            for class_name, img_list in old_manifest[category].items():
                all_class_data[class_name] = img_list

        new_manifest = {category: {} for category in CATEGORIES}
        # v1.3: 네거티브 샘플 목록은 그대로 유지
        new_manifest[NEGATIVE_SAMPLES_NAME] = old_manifest.get(NEGATIVE_SAMPLES_NAME, [])
        
        current_categories_order = [self.class_tree_widget.topLevelItem(i).text(0) for i in range(self.class_tree_widget.topLevelItemCount()) if self.class_tree_widget.topLevelItem(i).parent() is None and self.class_tree_widget.topLevelItem(i).text(0) != NEGATIVE_SAMPLES_NAME]

        for category_name in current_categories_order:
            if category_name not in new_manifest:
                 new_manifest[category_name] = {}

        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            category_name = category_item.text(0)
            
            if category_name == NEGATIVE_SAMPLES_NAME: continue

            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                class_name = class_item.text(0)

                if class_name in all_class_data:
                    new_manifest[category_name][class_name] = all_class_data.get(class_name, [])

        self.data_manager.save_manifest(new_manifest)

        checked_states = self.get_checked_states()
        self.populate_class_list()
        self.set_checked_states(checked_states)
        self.populate_preset_list()
        self.log_viewer.append("클래스 순서 또는 카테고리가 변경되었습니다.")

    def get_checked_states(self):
        """현재 트리의 모든 클래스 아이템의 체크 상태를 dict로 저장합니다."""
        states = {}
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                states[class_item.text(0)] = class_item.checkState(0)
        return states

    def set_checked_states(self, states):
        """ 저장된 체크 상태를 트리에 복원합니다. """
        was_blocked = self.class_tree_widget.signalsBlocked()
        self.class_tree_widget.blockSignals(True)
        for i in range(self.class_tree_widget.topLevelItemCount()):
            category_item = self.class_tree_widget.topLevelItem(i)
            for j in range(category_item.childCount()):
                class_item = category_item.child(j)
                if class_item.text(0) in states:
                    class_item.setCheckState(0, states[class_item.text(0)])
        self.class_tree_widget.blockSignals(was_blocked)
        self._persist_checked_classes()

    def handle_item_check(self, item, column):
        """체크박스 상태 변경 시, 프리셋을 '사용자 설정'으로 변경"""
        if self.preset_selector.count() > 0:
            self.preset_selector.blockSignals(True)
            self.preset_selector.setCurrentIndex(-1)
            self.preset_selector.blockSignals(False)
        self._persist_checked_classes()

    def cleanup_on_close(self):
        """
        애플리케이션 종료 시 호출될 정리 메서드.
        실행 중인 모든 스레드를 안전하게 종료합니다.
        """
        if hasattr(self, 'sam_thread') and self.sam_thread.isRunning():
            self.sam_thread.quit()
            self.sam_thread.wait()
