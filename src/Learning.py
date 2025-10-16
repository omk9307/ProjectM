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
import glob
import shutil
import json
import yaml
import cv2
import numpy as np
import mss
import pygetwindow as gw
import time
import uuid
import hashlib
import random
import requests
import copy
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
    QListWidgetItem, QTextEdit, QDialogButtonBox, QCheckBox,
    QComboBox, QDoubleSpinBox, QGroupBox, QScrollArea, QSpinBox,
    QProgressBar, QStatusBar, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QLineEdit, QFormLayout, QGridLayout, QSizePolicy, QInputDialog,
    QStackedLayout
)
from PyQt6.QtGui import (
    QPixmap, QImage, QIcon, QPainter, QPen, QColor, QBrush, QCursor, QPolygon,
    QDropEvent, QGuiApplication, QIntValidator, QDoubleValidator, QFont
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QPoint, QPointF, QObject, QMimeData, QTimer

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
from ocr_watch import (
    ocr_korean_words,
    draw_word_boxes,
    get_ocr_engine_label,
    get_ocr_last_error,
    is_paddle_available,
    set_paddle_use_gpu,
)

from window_anchors import (
    anchor_exists,
    get_anchor,
    get_maple_window_geometry,
    last_used_anchor_name,
    list_saved_anchors,
    restore_maple_window,
    save_window_anchor,
    set_last_used_anchor,
    ensure_relative_roi,
    resolve_roi_to_absolute,
    WindowGeometry,
    is_maple_window_foreground,
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
# 편집기에서는 추후 확장을 위해 남겨둔 '캐릭터' 카테고리를 노출하지 않습니다.
SELECTABLE_CATEGORIES = [category for category in CATEGORIES if category != CHARACTER_CLASS_NAME]

STATUS_RESOURCE_LABELS = {
    'hp': 'HP',
    'mp': 'MP',
    'exp': 'EXP',
}


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
    """전체 화면 위에서 정밀하게 ROI를 지정하기 위한 오버레이.

    변경 사항:
    - 확대 미리보기/격자/십자선 제거(요청사항)
    - 선택 영역만 투명/하이라이트로 표기
    """

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
        # 확대/격자 미사용
        self.zoom_factor = 1
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

        # 확대 미리보기 라벨 제거
        self._zoom_label = QLabel(self)
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
        # 확대/격자 미리보기 제거
        self._update_size_label(local_point)

    def _update_zoom_preview(self, global_point: QPoint, local_point: QPoint) -> None:
        # 더 이상 사용하지 않음
        self._zoom_label.hide()

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


class StatusRecognitionPreviewDialog(QDialog):
    """탐지 ROI 캡처와 분석 결과를 시각적으로 확인하기 위한 대화상자."""

    def __init__(
        self,
        parent: Optional[QWidget],
        window_title: str,
        roi_description: str,
        original_image: Optional[np.ndarray],
        processed_image: Optional[np.ndarray],
        summary_lines: list[str],
        *,
        processed_title: Optional[str] = None,
        scale_images: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        # 비모달로 동작: 뒤 창 조작 가능
        self.setModal(False)
        # 기본 크기 600x850
        self.resize(600, 850)

        self._buffers: list[np.ndarray] = []
        layout = QVBoxLayout()

        roi_label = QLabel(roi_description or '탐지 범위 정보가 없습니다.')
        roi_label.setWordWrap(True)
        layout.addWidget(roi_label)

        image_layout = QHBoxLayout()

        original_pixmap = self._create_pixmap(original_image)
        # 학습탭 OCR 테스트에서는 원본을 숨기기 위해 original_image=None을 넘깁니다.
        # 이 다이얼로그는 original_pixmap이 비어있으면 원본 칼럼을 생성하지 않습니다.
        if not original_pixmap.isNull():
            original_column = QVBoxLayout()
            original_title = QLabel('원본 캡처')
            original_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            original_column.addWidget(original_title)
            original_view = QLabel()
            original_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            original_view.setPixmap(self._scaled_pixmap(original_pixmap))
            # 클릭 시 원본 크기로 별도 창 열기
            original_view.setCursor(Qt.CursorShape.PointingHandCursor)
            original_view.mousePressEvent = lambda e, pm=original_pixmap: self._open_image_viewer(pm)
            original_column.addWidget(original_view)
            image_layout.addLayout(original_column)

        processed_pixmap = self._create_pixmap(processed_image)
        if not processed_pixmap.isNull():
            processed_column = QVBoxLayout()
            title_text = processed_title or '분석 이미지'
            processed_title_label = QLabel(title_text)
            processed_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            processed_column.addWidget(processed_title_label)
            processed_view = QLabel()
            processed_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if scale_images:
                processed_view.setPixmap(self._scaled_pixmap(processed_pixmap))
            else:
                processed_view.setPixmap(processed_pixmap)
                try:
                    processed_view.setFixedSize(processed_pixmap.size())
                except Exception:
                    pass
            processed_view.setCursor(Qt.CursorShape.PointingHandCursor)
            processed_view.mousePressEvent = lambda e, pm=processed_pixmap: self._open_image_viewer(pm)
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

        # 원본 크기 표시 시 다이얼로그를 이미지 크기에 맞춰 조정
        if not processed_pixmap.isNull() and not scale_images:
            try:
                self.adjustSize()
                scr = QGuiApplication.primaryScreen()
                if scr:
                    avail = scr.availableGeometry()
                    w = min(self.width(), avail.width() - 80)
                    h = min(self.height(), avail.height() - 120)
                    self.resize(max(320, w), max(240, h))
            except Exception:
                pass

    def _create_pixmap(self, image: Optional[np.ndarray]) -> QPixmap:
        if image is None:
            return QPixmap()
        if not hasattr(image, 'size') or image.size == 0:
            return QPixmap()
        buffer = np.ascontiguousarray(image)
        self._buffers.append(buffer)
        if buffer.ndim == 2:
            height, width = buffer.shape
            bytes_per_line = width
            fmt = QImage.Format.Format_Grayscale8
        else:
            height, width, channels = buffer.shape
            if channels == 1:
                bytes_per_line = width
                fmt = QImage.Format.Format_Grayscale8
            elif channels == 3:
                bytes_per_line = channels * width
                fmt = QImage.Format.Format_BGR888
            elif channels == 4:
                bytes_per_line = channels * width
                fmt = QImage.Format.Format_RGBA8888
            else:
                return QPixmap()
        qimage = QImage(buffer.data, width, height, bytes_per_line, fmt)
        return QPixmap.fromImage(qimage)

    @staticmethod
    def _scaled_pixmap(pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        return pixmap.scaled(
            320,
            250,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _open_image_viewer(self, pixmap: QPixmap) -> None:
        """이미지 클릭 시 원본 크기로 보여주는 비모달 뷰어를 띄운다."""
        if pixmap.isNull():
            return
        viewer = QDialog(self)
        viewer.setWindowTitle("이미지 보기")
        viewer.setModal(False)
        v_layout = QVBoxLayout(viewer)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setPixmap(pixmap)
        v_layout.addWidget(lbl)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(viewer.reject)
        v_layout.addWidget(btn)
        # 화면 크기에 맞춰 창 크기 자동 조정
        scr = QGuiApplication.primaryScreen()
        sw = scr.availableGeometry().width() if scr else 1920
        sh = scr.availableGeometry().height() if scr else 1080
        w = min(pixmap.width() + 40, sw - 80)
        h = min(pixmap.height() + 100, sh - 120)
        viewer.resize(max(320, w), max(240, h))
        viewer.show()


class OcrLiveReportDialog(QDialog):
    """OCR 워커 결과를 주기적으로 갱신 표시하는 간단 리포트 창."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('OCR 탐지 보고')
        self.setModal(False)
        self.resize(600, 850)

        self._buffers: list[np.ndarray] = []
        layout = QVBoxLayout(self)
        self.summary_label = QLabel('최근 결과 요약')
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.image_title = QLabel('OCR 결과')
        self.image_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_title)

        # 원본 크기 표시(스크롤 없음), 창 크기를 이미지에 맞춰 조정
        self.image_view = QLabel()
        self.image_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_view)

        self.text_box = QTextEdit()
        self.text_box.setReadOnly(True)
        self.text_box.setMinimumHeight(160)
        layout.addWidget(self.text_box)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _to_pixmap(self, image: Optional[np.ndarray]) -> QPixmap:
        if image is None or not hasattr(image, 'size') or image.size == 0:
            return QPixmap()
        buf = np.ascontiguousarray(image)
        self._buffers.append(buf)
        if buf.ndim == 2:
            h, w = buf.shape
            qimg = QImage(buf.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            h, w, c = buf.shape
            if c == 3:
                qimg = QImage(buf.data, w, h, c * w, QImage.Format.Format_BGR888)
            elif c == 4:
                qimg = QImage(buf.data, w, h, c * w, QImage.Format.Format_RGBA8888)
            else:
                return QPixmap()
        return QPixmap.fromImage(qimg)

    def update_content(self, *, annotated_bgr: Optional[np.ndarray], words: list[dict], ts: float, keywords: Optional[list[str]] = None, show_keywords: bool = False) -> None:
        pix = self._to_pixmap(annotated_bgr)
        self.image_view.setPixmap(pix)
        try:
            if not pix.isNull():
                self.image_view.setFixedSize(pix.size())
                self.adjustSize()
                scr = QGuiApplication.primaryScreen()
                if scr:
                    avail = scr.availableGeometry()
                    w = min(self.width(), avail.width() - 80)
                    h = min(self.height(), avail.height() - 120)
                    self.resize(max(320, w), max(240, h))
        except Exception:
            pass
        # summary
        import time as _t
        tstr = _t.strftime('%H:%M:%S', _t.localtime(ts))
        self.summary_label.setText(f'최근 업데이트: {tstr}  |  항목: {len(words)}')
        # text list
        lines: list[str] = []
        total = len(words)
        lines.append(f'감지 단어 수: {total}개')
        kw_list = keywords if isinstance(keywords, list) else []
        kw_count = 0
        for i, w in enumerate(words[:50]):
            try:
                text = str(w.get('text', ''))
                conf = int(round(float(w.get('conf', 0))))
                h = int(w.get('height', 0))
                wid = int(w.get('width', 0))
                lines.append(f'[{i+1}] : {text} (신뢰도: {conf}% , W: {wid} px, H: {h} px)')
                if show_keywords and kw_list:
                    if any((isinstance(kw, str) and kw.strip() and kw.strip() in text) for kw in kw_list):
                        kw_count += 1
            except Exception:
                continue
        if show_keywords and kw_list:
            lines.append(f'키워드 검출 수: {kw_count}개')
        self.text_box.setPlainText('\n'.join(lines) if lines else '표시할 항목이 없습니다.')

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
        # [NEW] 공격 금지 체크박스 (개별 신뢰도 스핀박스 우측)
        self.attack_forbidden_checkbox = QCheckBox("공격 금지")
        try:
            if self.data_manager and hasattr(self.data_manager, 'is_monster_attack_forbidden'):
                self.attack_forbidden_checkbox.setChecked(
                    bool(self.data_manager.is_monster_attack_forbidden(self.class_name))
                )
        except Exception:
            self.attack_forbidden_checkbox.setChecked(False)
        override_row.addWidget(self.attack_forbidden_checkbox)
        override_row.addStretch(1)

        settings_layout.addLayout(override_row)

        hint_label = QLabel("미사용 시 전역 몬스터 신뢰도 값을 따릅니다.")
        hint_label.setWordWrap(True)
        settings_layout.addWidget(hint_label)

        layout.addWidget(settings_group)

        nameplate_group = QGroupBox("몬스터 이름표 설정")
        # 그룹 높이가 내용만큼만 차지하도록 설정
        nameplate_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum))
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
        # 초기 확대 배율 적용이 무시되지 않도록 0에서 시작한다.
        self.zoom_factor = 0.0
        self._min_zoom = 0.25
        self._max_zoom = 4.0
        # 확대된 배경 픽스맵 캐시(페인트 최적화)
        self._scaled_pixmap = None
        self.polygons = []
        self.hovered_polygon_idx = -1
        self.panning, self.pan_start_pos = False, QPoint()
        # 글로벌 기준 패닝 기준점(스크롤 중 떨림 방지)
        self._pan_start_global = QPoint()
        self.setMouseTracking(True)
        self.set_zoom(1.0)

    def _scaled_pixmap_size(self) -> QSize:
        """현재 확대 배율을 반영한 픽스맵 크기를 반환합니다."""
        if self.pixmap.isNull():
            return QSize()
        factor = self.zoom_factor if self.zoom_factor > 0 else 1.0
        width = max(1, int(round(self.pixmap.width() * factor)))
        height = max(1, int(round(self.pixmap.height() * factor)))
        return QSize(width, height)

    def sizeHint(self) -> QSize:
        scaled = self._scaled_pixmap_size()
        return scaled if scaled.isValid() else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        scaled = self._scaled_pixmap_size()
        return scaled if scaled.isValid() else super().minimumSizeHint()

    def set_zoom(self, factor, focal_point: QPoint | QPointF | None = None):
        previous_factor = self.zoom_factor
        factor = max(self._min_zoom, min(self._max_zoom, factor))
        if abs(factor - previous_factor) < 1e-6:
            return

        self.zoom_factor = factor
        # 배율 변경 시 원본 픽스맵을 미리 스케일해 캐싱(페인트에서 스케일 제거)
        try:
            size = self._scaled_pixmap_size()
            if not self.pixmap.isNull() and size.isValid():
                self._scaled_pixmap = self.pixmap.scaled(
                    size,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            else:
                self._scaled_pixmap = None
            self.setFixedSize(size)
        except Exception:
            self._scaled_pixmap = None
            self.setFixedSize(self._scaled_pixmap_size())
        self.updateGeometry()
        self.update()

        if focal_point is None:
            return

        scroll_area = self._scroll_area()
        if not scroll_area:
            return

        viewport_pos = QPointF(focal_point)
        hbar = scroll_area.horizontalScrollBar()
        vbar = scroll_area.verticalScrollBar()

        if previous_factor == 0:
            previous_factor = 1.0

        anchor_x = (hbar.value() + viewport_pos.x()) / previous_factor
        anchor_y = (vbar.value() + viewport_pos.y()) / previous_factor

        hbar.setValue(int(anchor_x * self.zoom_factor - viewport_pos.x()))
        vbar.setValue(int(anchor_y * self.zoom_factor - viewport_pos.y()))

    def _scroll_area(self):
        # self.parent() 는 QScrollArea의 뷰포트(QWidget)이므로 그 부모를 사용
        parent = self.parent()
        if parent is None:
            return None
        return parent.parent()

    def enterEvent(self, event):
        """마우스가 캔버스에 들어오면 부모 다이얼로그에 포커스를 줍니다."""
        self.parent_dialog.activateWindow()
        self.parent_dialog.setFocus()
        super().enterEvent(event)

    def wheelEvent(self, event):
        angle_delta = event.angleDelta().y()
        if angle_delta == 0:
            event.ignore()
            return

        step = 1.1 if angle_delta > 0 else 0.9
        new_factor = self.zoom_factor * step
        scroll_area = self._scroll_area()
        focal = event.position() if hasattr(event, "position") else QPointF(event.pos())
        if scroll_area:
            self.set_zoom(new_factor, focal)
        else:
            self.set_zoom(new_factor)
        event.accept()

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
            # 위젯 좌표 대신 글로벌 좌표 차이를 사용해 떨림 방지
            try:
                gp = event.globalPosition() if hasattr(event, 'globalPosition') else None
                current_global = gp.toPoint() if gp is not None else (event.globalPos() if hasattr(event, 'globalPos') else QPoint())
            except Exception:
                current_global = QPoint()
            delta = current_global - self._pan_start_global
            scroll_area = self._scroll_area()
            hbar = scroll_area.horizontalScrollBar()
            vbar = scroll_area.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
            self._pan_start_global = current_global
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
    """수동 다각형 편집기 전용 캔버스.

    변경점:
    - 좌클릭 다각형(합집합 후보)과 우클릭 다각형(차집합 후보)을 분리해 동시 표시/편집.
    - AI 편집에서 전달된 임시 마스크(pending_mask) 오버레이 표시.
    """
    def __init__(self, pixmap, initial_polygons=None, parent_dialog=None):
        super().__init__(pixmap, parent_dialog)
        self.polygons = initial_polygons if initial_polygons else []
        self.current_add_points = []  # 좌클릭으로 그리는 다각형
        self.current_sub_points = []  # 우클릭으로 그리는 다각형(빼기)
        self.current_pos = QPoint()
        self._last_pressed_button = None  # 최근 포인트 추가 버튼 추적
        self.pending_mask = None  # AI 편집에서 넘어온 임시 마스크

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        # 캐시된 스케일 픽스맵 사용으로 페인트 경량화
        if getattr(self, '_scaled_pixmap', None) is not None:
            painter.drawPixmap(QPoint(0, 0), self._scaled_pixmap)
        else:
            painter.drawPixmap(self.rect(), self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_polygons(painter)

        # [NEW] AI에서 넘어온 임시 마스크 시각화(캐시 사용)
        if self.pending_mask is not None and hasattr(self.pending_mask, 'shape'):
            class_id = self.parent_dialog.get_current_class_id()
            # 캐시가 없거나 클래스 변경 시 재구성
            if getattr(self, '_pending_qimage', None) is None or getattr(self, '_pending_overlay_class_id', None) != class_id:
                self._rebuild_pending_overlay(class_id)
            # 스케일 캐시 갱신 및 그리기
            if getattr(self, '_pending_qimage', None) is not None:
                if getattr(self, '_pending_scaled', None) is None or getattr(self, '_pending_scaled', None).size() != self.size() or getattr(self, '_pending_scaled_dirty', True):
                    self._pending_scaled = self._pending_qimage.scaled(
                        self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
                    )
                    self._pending_scaled_dirty = False
                painter.drawImage(self.rect(), self._pending_scaled)

        # 현재 그리고 있는 좌/우클릭 다각형 오버레이
        class_id = self.parent_dialog.get_current_class_id()
        if class_id is not None:
            color_add = self.parent_dialog.get_color_for_class_id(class_id)
            color_sub_edge = HIGHLIGHT_PEN_COLOR
            # 좌클릭 다각형(추가)
            if self.current_add_points:
                scaled_pts = [p * self.zoom_factor for p in self.current_add_points]
                painter.setPen(QPen(color_add.darker(150), 2))
                painter.setBrush(QBrush(color_add))
                painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in scaled_pts]))
                if self.rect().contains(self.current_pos):
                    painter.drawLine(scaled_pts[-1], self.current_pos)
                for point in scaled_pts:
                    painter.drawEllipse(point, 4, 4)
            # 우클릭 다각형(빼기)
            if self.current_sub_points:
                scaled_pts = [p * self.zoom_factor for p in self.current_sub_points]
                painter.setPen(QPen(color_sub_edge, 2, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(QColor(255, 0, 0, 60)))
                painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in scaled_pts]))
                if self.rect().contains(self.current_pos):
                    painter.drawLine(scaled_pts[-1], self.current_pos)
                for point in scaled_pts:
                    painter.drawEllipse(point, 4, 4)

    def mousePressEvent(self, event):
        if self.parent_dialog.is_change_mode and event.button() == Qt.MouseButton.LeftButton:
            if self.change_hovered_polygon_class():
                return

        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pressed_button = Qt.MouseButton.LeftButton
            self.current_add_points.append(event.pos() / self.zoom_factor)
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._last_pressed_button = Qt.MouseButton.RightButton
            self.current_sub_points.append(event.pos() / self.zoom_factor)
            self.update()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True
            self.pan_start_pos = event.pos()
            try:
                gp = event.globalPosition() if hasattr(event, 'globalPosition') else None
                self._pan_start_global = gp.toPoint() if gp is not None else (event.globalPos() if hasattr(event, 'globalPos') else QPoint())
            except Exception:
                self._pan_start_global = QPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.panning:
            self.current_pos = event.pos(); self.update()

    # [NEW] 유틸: 마지막 포인트 제거(Backspace)
    def remove_last_point(self):
        if self._last_pressed_button == Qt.MouseButton.RightButton:
            if self.current_sub_points:
                self.current_sub_points.pop()
                if not self.current_sub_points:
                    self._last_pressed_button = Qt.MouseButton.LeftButton if self.current_add_points else None
                self.update()
                return True
        # 기본: 좌클릭 포인트 제거
        if self.current_add_points:
            self.current_add_points.pop()
            if not self.current_add_points:
                self._last_pressed_button = Qt.MouseButton.RightButton if self.current_sub_points else None
            self.update()
            return True
        return False

    # [NEW] BaseCanvasLabel.set_zoom 오버라이드하여 pending 스케일 캐시 무효화
    def set_zoom(self, factor, focal_point: QPoint | QPointF | None = None):
        super().set_zoom(factor, focal_point)
        if hasattr(self, '_pending_scaled'):
            self._pending_scaled_dirty = True

    # [NEW] pending 마스크 오버레이(QImage) 재구성
    def _rebuild_pending_overlay(self, class_id):
        try:
            self._pending_overlay_class_id = class_id
            mask = self.pending_mask
            if mask is None or not hasattr(mask, 'shape'):
                self._pending_rgba = None
                self._pending_qimage = None
                self._pending_scaled = None
                self._pending_scaled_dirty = True
                return
            h, w = mask.shape
            color = self.parent_dialog.get_color_for_class_id(class_id)
            r, g, b, a = color.red(), color.green(), color.blue(), color.alpha()
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            m = mask.astype(bool)
            rgba[m, 0] = r
            rgba[m, 1] = g
            rgba[m, 2] = b
            rgba[m, 3] = a
            self._pending_rgba = rgba
            bytes_per_line = w * 4
            self._pending_qimage = QImage(rgba.data, w, h, bytes_per_line, QImage.Format.Format_RGBA8888)
            self._pending_scaled = None
            self._pending_scaled_dirty = True
        except Exception:
            self._pending_rgba = None
            self._pending_qimage = None
            self._pending_scaled = None
            self._pending_scaled_dirty = True

# --- 3. 위젯: 다각형 편집기 다이얼로그 (공통 로직 추가) ---
class PolygonAnnotationEditor(QDialog):
    """수동 다각형 편집기 메인 창."""
    # v1.3: 방해 요소 저장을 위한 커스텀 결과 코드 정의
    DistractorSaved = 100
    SwitchToAI = 101

    mode_switch_requested = pyqtSignal(int)
    saved = pyqtSignal()
    canceled = pyqtSignal()
    distractor_saved = pyqtSignal()

    def __init__(self, pixmap, initial_polygons=None, parent=None, initial_class_name=None, *, embedded: bool = False, sam_ready: bool | None = None):
        super().__init__(parent)
        self._embedded = embedded
        self.setWindowTitle('수동 편집기 (변경:C, 지정삭제:D, 완성취소:Z, 초기화:R)')
        self.learning_tab = parent # LearningTab 인스턴스 저장
        self.is_change_mode = False
        self.canvas = CanvasLabel(pixmap, initial_polygons, self)
        self.pending_ai_mask = None  # [NEW] AI 편집에서 전달된 임시 마스크
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        if sam_ready is None:
            sam_ready = getattr(self.learning_tab, "sam_predictor", None) is not None

        self.mode_ai_btn = QPushButton("AI 편집")
        self.mode_ai_btn.setEnabled(sam_ready)
        if not sam_ready:
            self.mode_ai_btn.setToolTip("SAM 모델이 준비되지 않아 전환할 수 없습니다.")
        else:
            self.mode_ai_btn.setToolTip("AI 편집으로 전환")
        self.mode_ai_btn.clicked.connect(self.on_switch_to_ai)
        left_controls_layout.addWidget(self.mode_ai_btn)

        self.mode_manual_btn = QPushButton("수동 편집")
        self.mode_manual_btn.setEnabled(False)
        self.mode_manual_btn.setToolTip("현재 수동 편집 모드입니다.")
        left_controls_layout.addWidget(self.mode_manual_btn)

        # 클래스 선택 UI
        class_selection_layout = QHBoxLayout()
        class_selection_layout.addWidget(QLabel("카테고리:"))
        self.category_selector = QComboBox()
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
        if self._embedded:
            self.button_box.rejected.connect(self.on_cancel)
        else:
            self.button_box.rejected.connect(self.reject)
        
        main_layout.addLayout(top_controls_layout)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.status_bar)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)
        self._preferred_size = self._compute_preferred_size(pixmap)
        if not self._embedded:
            self.resize(self._preferred_size)
        else:
            self.setWindowFlags(Qt.WindowType.Widget)

        self.full_class_list = self.learning_tab.data_manager.get_class_list()
        self.create_local_color_map()
        # [NEW] 카테고리/클래스를 체크된 항목으로 필터링하여 표시
        self.populate_category_selector()
        self.set_initial_selection(initial_class_name)
        self.setFocus()

    # [NEW] 외부에서 AI 임시 마스크 설정(수동 전환 시 전달)
    def set_pending_ai_mask(self, mask: Optional[np.ndarray]):
        self.pending_ai_mask = None if mask is None else (mask.copy().astype(bool))
        self.canvas.pending_mask = None if mask is None else (mask.copy().astype(bool))
        try:
            # 캐시 재구성 및 업데이트
            class_id = self.get_current_class_id()
            if hasattr(self.canvas, '_rebuild_pending_overlay'):
                self.canvas._rebuild_pending_overlay(class_id)
        except Exception:
            pass
        self.canvas.update()

    def _compute_preferred_size(self, pixmap: QPixmap) -> QSize:
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        extra_width, extra_height = 80, 200
        raw_width = pixmap.width() + extra_width
        raw_height = pixmap.height() + extra_height
        max_width = int(screen_geometry.width() * 0.9)
        max_height = int(screen_geometry.height() * 0.9)
        scale = min(max_width / raw_width if raw_width else 1.0, max_height / raw_height if raw_height else 1.0, 1.0)
        preferred_width = max(int(raw_width * scale), 800)
        preferred_height = max(int(raw_height * scale), 600)
        return QSize(preferred_width, preferred_height)

    def sizeHint(self) -> QSize:
        if self._embedded:
            return self._preferred_size
        return super().sizeHint()

    # v1.3: 방해 요소 저장 슬롯
    def on_save_distractor(self):
        """'방해 요소로 저장' 버튼 클릭 시 호출됩니다."""
        if len(self.canvas.current_add_points) >= 3:
            # 방해 요소는 클래스 ID가 필요 없으므로, 현재 그리던 다각형만 저장
            self.canvas.polygons.append({'class_id': None, 'points': list(self.canvas.current_add_points)})
            self.canvas.current_add_points.clear()
        
        if not self.canvas.polygons:
            QMessageBox.warning(self, "오류", "방해 요소로 지정할 다각형이 없습니다.")
            return

        if self._embedded:
            self.distractor_saved.emit()
        else:
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
        """선택된 카테고리에 맞는 '체크된 클래스'만 QComboBox에 채웁니다."""
        self.class_selector.blockSignals(True)
        self.class_selector.clear()

        category = self.category_selector.currentText()
        manifest = self.learning_tab.data_manager.get_manifest()
        all_classes_in_category = list(manifest.get(category, {}).keys()) if isinstance(manifest.get(category), dict) else []
        checked = getattr(self.learning_tab, '_checked_class_names', set())
        filtered = [name for name in all_classes_in_category if name in checked]

        self.class_selector.addItems(filtered)
        if category != CHARACTER_CLASS_NAME:
            self.class_selector.addItem("[새 클래스 추가...]")

        if new_class_to_select and new_class_to_select in filtered:
            self.class_selector.setCurrentText(new_class_to_select)

        self.class_selector.blockSignals(False)

    # [NEW] 체크된 클래스가 존재하는 카테고리만 노출
    def populate_category_selector(self):
        self.category_selector.blockSignals(True)
        self.category_selector.clear()
        manifest = self.learning_tab.data_manager.get_manifest()
        checked = getattr(self.learning_tab, '_checked_class_names', set())
        categories = []
        for cat in SELECTABLE_CATEGORIES:
            entry = manifest.get(cat)
            if isinstance(entry, dict):
                class_names = list(entry.keys())
                if any((name in checked) for name in class_names):
                    categories.append(cat)
        self.category_selector.addItems(categories)
        self.category_selector.blockSignals(False)

    def set_initial_selection(self, class_name):
        """편집기 시작 시 전달받은 클래스 이름으로 선택자를 설정합니다."""
        checked = getattr(self.learning_tab, '_checked_class_names', set())
        if class_name and class_name in checked:
            category = self.learning_tab.data_manager.get_class_category(class_name)
            if category and category != CHARACTER_CLASS_NAME:
                # 카테고리가 목록에 없으면 첫 번째 사용 가능 카테고리로 대체
                if self.category_selector.findText(category) != -1:
                    self.category_selector.setCurrentText(category)
                    self.update_class_selector(new_class_to_select=class_name)
                    return
        # 기본 선택: 첫 가용 카테고리/클래스
        if self.category_selector.count() > 0:
            self.category_selector.setCurrentIndex(0)
        self.update_class_selector()

    def handle_class_selection(self, index):
        """'[새 클래스 추가...]'가 선택되면 새 클래스 추가 로직을 실행합니다."""
        if self.class_selector.itemText(index) == "[새 클래스 추가...]":
            category = self.category_selector.currentText()
            new_name, ok = QInputDialog.getText(self, "새 클래스 추가", f"'{category}' 카테고리에 추가할 클래스 이름:")
            if ok and new_name:
                success, message = self.learning_tab.data_manager.add_class(new_name, category)
                if success:
                    # 메인 창 목록 갱신 및 새 클래스 자동 체크 반영
                    self.learning_tab.populate_class_list()
                    if hasattr(self.learning_tab, '_checked_class_names'):
                        self.learning_tab._checked_class_names.add(new_name)
                        self.learning_tab._apply_checked_classes_to_tree()
                        self.learning_tab._persist_checked_classes()
                    self.full_class_list = self.learning_tab.data_manager.get_class_list()
                    self.populate_category_selector()
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
            self.commit_current_polygon()
        elif event.key() == Qt.Key.Key_Escape:
            # [NEW] 진행 중(좌/우 포인트 또는 pending 마스크)일 때만 취소, 없으면 무시
            if self.canvas.current_add_points or self.canvas.current_sub_points or self.pending_ai_mask is not None:
                self.canvas.current_add_points.clear()
                self.canvas.current_sub_points.clear()
                self.pending_ai_mask = None
                self.canvas.pending_mask = None
                self.canvas.update()
            return
        elif event.key() == Qt.Key.Key_Backspace:
            # 좌/우클릭 포인트에서 최근 것을 제거
            self.canvas.remove_last_point()
        elif event.key() == Qt.Key.Key_R:
            if self.canvas.polygons or self.canvas.current_add_points or self.canvas.current_sub_points or self.pending_ai_mask is not None:
                if QMessageBox.question(self, "초기화", "모든 다각형을 지우시겠습니까?") == QMessageBox.StandardButton.Yes:
                    self.canvas.polygons.clear();
                    self.canvas.current_add_points.clear();
                    self.canvas.current_sub_points.clear();
                    self.pending_ai_mask = None; self.canvas.pending_mask = None;
                    self.canvas.update()
        elif event.key() == Qt.Key.Key_Z:
            if self.canvas.polygons: self.canvas.polygons.pop(); self.canvas.update()
        elif event.key() == Qt.Key.Key_D: self.canvas.delete_hovered_polygon()
        elif event.key() == Qt.Key.Key_T:
            self.on_switch_to_ai()
        elif event.key() == Qt.Key.Key_C:
            self.change_class_btn.setChecked(not self.change_class_btn.isChecked())
        else: super().keyPressEvent(event)

    def on_save(self):
        self.commit_current_polygon()
        if self._embedded:
            self.saved.emit()
        else:
            self.accept()

    def get_all_polygons(self): return self.canvas.polygons

    def commit_current_polygon(self):
        """현재 그리고 있는 다각형을 확정하거나, 우클릭 차집합을 적용합니다.

        요구사항 반영:
        - AI→수동 전환 시 자동 완료하지 않고 pending_ai_mask로 보관 후, 엔터 시 수동 다각형과 합집합 완료.
        - 우클릭 다각형은 엔터 시 겹치는 영역을 빼기. 이미 완성된 경우 즉시 반영, 미완성(좌클릭 진행 중)이면 1회 적용 후 다시 엔터로 최종 완료.
        """
        class_id = self.get_current_class_id()
        if class_id is None:
            return False

        h = self.canvas.pixmap.height()
        w = self.canvas.pixmap.width()

        def _mask_from_points(points):
            if len(points) < 3:
                return None
            mask = np.zeros((h, w), dtype=np.uint8)
            pts = np.array([[int(p.x()), int(p.y())] for p in points], dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)
            return mask

        def _mask_from_class_polygons():
            mask = np.zeros((h, w), dtype=np.uint8)
            found = False
            for poly in self.canvas.polygons:
                if poly.get('class_id') == class_id and poly.get('points'):
                    pts = np.array([[int(p.x()), int(p.y())] for p in poly['points']], dtype=np.int32)
                    cv2.fillPoly(mask, [pts], 255)
                    found = True
            return mask if found else None

        add_mask = _mask_from_points(self.canvas.current_add_points)
        sub_mask = _mask_from_points(self.canvas.current_sub_points)

        # subtract-only: 기존 확정 폴리곤에서 겹치는 부분만 빼기(다른 객체는 유지)
        if self.pending_ai_mask is None and add_mask is None and sub_mask is not None:
            updated = False
            new_list = []
            inv_sub = cv2.bitwise_not(sub_mask)
            for poly in self.canvas.polygons:
                if poly.get('class_id') != class_id or not poly.get('points'):
                    new_list.append(poly)
                    continue
                # 이 폴리곤만 마스크로 만들고 차집합
                single_mask = np.zeros((h, w), dtype=np.uint8)
                pts = np.array([[int(p.x()), int(p.y())] for p in poly['points']], dtype=np.int32)
                cv2.fillPoly(single_mask, [pts], 255)
                result_mask = cv2.bitwise_and(single_mask, inv_sub)
                contours, _ = cv2.findContours(result_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                found_any = False
                for c in contours:
                    if cv2.contourArea(c) <= 10:
                        continue
                    pts2 = [QPoint(p[0][0], p[0][1]) for p in c]
                    new_list.append({'class_id': class_id, 'points': pts2})
                    found_any = True
                if found_any:
                    updated = True
                else:
                    # 완전히 지워졌으면 추가하지 않음
                    pass

            if updated:
                self.canvas.polygons = new_list
                self.canvas.current_sub_points.clear()
                self.canvas.update()
                return True
            return False

        # base 생성: AI pending 또는 좌클릭 추가
        base_mask = None
        if self.pending_ai_mask is not None:
            base_mask = (self.pending_ai_mask.astype(np.uint8)) * 255
        if add_mask is not None:
            base_mask = add_mask if base_mask is None else cv2.bitwise_or(base_mask, add_mask)
        if base_mask is None:
            return False

        # in-progress에서 차집합만 먼저 적용하고 확정 보류
        if self.pending_ai_mask is None and add_mask is not None and sub_mask is not None:
            inv = cv2.bitwise_not(sub_mask)
            preview_mask = cv2.bitwise_and(base_mask, inv)
            contours, _ = cv2.findContours(preview_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                largest = max(contours, key=cv2.contourArea)
                if cv2.contourArea(largest) > 10:
                    new_points = [QPoint(p[0][0], p[0][1]) for p in largest]
                    self.canvas.current_add_points = new_points
                    self.canvas.current_sub_points.clear()
                    self.canvas.update()
                    return False
            self.canvas.current_sub_points.clear()
            self.canvas.update()
            return False

        # 최종 확정: base(합집합)에 sub가 있으면 빼고, 같은 클래스의 겹치는 기존 폴리곤과 합집합하여 교체
        if sub_mask is not None:
            inv = cv2.bitwise_not(sub_mask)
            base_mask = cv2.bitwise_and(base_mask, inv)

        # 커밋 대상 마스크
        commit_mask = base_mask.copy()

        # 같은 클래스의 겹치는 기존 폴리곤과 합집합, 겹치지 않으면 유지 목록에 남김
        merged_mask = commit_mask.copy()
        new_list = []
        for poly in self.canvas.polygons:
            if poly.get('class_id') != class_id or not poly.get('points'):
                new_list.append(poly)
                continue
            single_mask = np.zeros((h, w), dtype=np.uint8)
            pts = np.array([[int(p.x()), int(p.y())] for p in poly['points']], dtype=np.int32)
            cv2.fillPoly(single_mask, [pts], 255)
            if cv2.countNonZero(cv2.bitwise_and(single_mask, merged_mask)) > 0:
                merged_mask = cv2.bitwise_or(merged_mask, single_mask)
            else:
                new_list.append(poly)

        # 합집합 결과를 컨투어로 폴리곤화하여 추가
        contours, _ = cv2.findContours(merged_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) <= 10:
                continue
            pts = [QPoint(p[0][0], p[0][1]) for p in c]
            new_list.append({'class_id': class_id, 'points': pts})

        self.canvas.polygons = new_list

        # 상태 정리
        self.canvas.current_add_points.clear()
        self.canvas.current_sub_points.clear()
        self.pending_ai_mask = None
        self.canvas.pending_mask = None
        self.canvas.update()
        return True

    def on_switch_to_ai(self):
        """AI 편집기로 전환합니다."""
        self.commit_current_polygon()
        if self._embedded:
            self.mode_switch_requested.emit(EditModeDialog.AI_ASSIST)
        else:
            self.done(self.SwitchToAI)

    def get_current_class_name(self):
        class_name = self.class_selector.currentText()
        if class_name and class_name != "[새 클래스 추가...]":
            return class_name
        return None

    def on_cancel(self):
        if self._embedded:
            self.canceled.emit()
        else:
            self.reject()

    def update_mode_buttons(self, is_active: bool, sam_ready: bool):
        if not hasattr(self, "mode_manual_btn"):
            return
        if is_active:
            self.mode_manual_btn.setEnabled(False)
            self.mode_manual_btn.setToolTip("현재 수동 편집 모드입니다.")
            self.mode_ai_btn.setEnabled(sam_ready)
            if sam_ready:
                self.mode_ai_btn.setToolTip("AI 편집으로 전환")
            else:
                self.mode_ai_btn.setToolTip("SAM 모델이 준비되지 않아 전환할 수 없습니다.")
        else:
            self.mode_manual_btn.setEnabled(True)
            self.mode_manual_btn.setToolTip("수동 편집으로 전환")
            self.mode_ai_btn.setEnabled(False)
            self.mode_ai_btn.setToolTip("현재 AI 편집 모드입니다.")

    def set_polygons(self, polygons):
        self.canvas.polygons = polygons if polygons else []
        self.create_local_color_map()
        self.canvas.current_add_points.clear()
        self.canvas.current_sub_points.clear()
        self.canvas.update()

# --- 3.5. 위젯: SAM(AI) 편집기 ---
class SAMCanvasLabel(BaseCanvasLabel):
    """AI 어시스트 편집기 전용 캔버스. AI가 예측한 마스크(mask)와 사용자 클릭 포인트를 추가로 그립니다."""
    def __init__(self, pixmap, parent_dialog):
        super().__init__(pixmap, parent_dialog)
        self.current_mask, self.input_points, self.input_labels = None, [], []
        # 마스크/오버레이 캐시
        self._mask_qimage = None
        self._mask_scaled = None
        self._mask_scaled_dirty = True
        self._mask_overlay_class_id = None
        self._mask_contours = []
        # 우클릭 수동 차집합 폴리곤 상태
        self.current_sub_points = []
        self.current_pos = QPoint()
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        # 캐시된 스케일 픽스맵 사용
        if getattr(self, '_scaled_pixmap', None) is not None:
            painter.drawPixmap(QPoint(0, 0), self._scaled_pixmap)
        else:
            painter.drawPixmap(self.rect(), self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_polygons(painter)

        if self.current_mask is not None:
            class_id = self.parent_dialog.get_current_class_id()
            # 캐시가 없거나 클래스/스냅샷이 바뀌면 재구성
            if class_id != getattr(self, '_mask_overlay_class_id', None) or self._mask_qimage is None or not self._mask_contours:
                self._rebuild_mask_cache(class_id)
            if self._mask_qimage is not None:
                if self._mask_scaled is None or self._mask_scaled.size() != self.size() or self._mask_scaled_dirty:
                    self._mask_scaled = self._mask_qimage.scaled(
                        self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
                    )
                    self._mask_scaled_dirty = False
                painter.drawImage(self.rect(), self._mask_scaled)

            # 마스크 외곽선(캐시) 그리기
            painter.setPen(QPen(HIGHLIGHT_PEN_COLOR, 2, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for contour in self._mask_contours:
                poly_points = [QPoint(p[0][0], p[0][1]) * self.zoom_factor for p in contour]
                painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in poly_points]))

        # 우클릭 수동 차집합 폴리곤 미리보기
        if self.current_sub_points:
            scaled_pts = [p * self.zoom_factor for p in self.current_sub_points]
            painter.setPen(QPen(HIGHLIGHT_PEN_COLOR, 2, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(255, 0, 0, 60)))
            painter.drawPolygon(QPolygon([QPoint(int(p.x()), int(p.y())) for p in scaled_pts]))
            if self.rect().contains(self.current_pos):
                painter.drawLine(scaled_pts[-1], self.current_pos)
            for point in scaled_pts:
                painter.drawEllipse(point, 4, 4)

    def mousePressEvent(self, event):
        if self.parent_dialog.is_change_mode and event.button() == Qt.MouseButton.LeftButton:
            if self.change_hovered_polygon_class():
                return

        if event.button() == Qt.MouseButton.RightButton:
            # 마스크 생성 중이 아니면 우클릭 폴리곤 점 추가(수동 차집합 모드)
            if getattr(self.parent_dialog.canvas, 'current_mask', None) is None:
                self.current_sub_points.append(event.pos() / self.zoom_factor)
                self.update()
                return
            # 마스크 진행 중이면 기존 SAM 네거티브 클릭 동작 유지
            self.parent_dialog.predict_mask(event.pos(), 0)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.parent_dialog.predict_mask(event.pos(), 1)
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True
            self.pan_start_pos = event.pos()
            try:
                gp = event.globalPosition() if hasattr(event, 'globalPosition') else None
                self._pan_start_global = gp.toPoint() if gp is not None else (event.globalPos() if hasattr(event, 'globalPos') else QPoint())
            except Exception:
                self._pan_start_global = QPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if not self.panning:
            self.current_pos = event.pos()
            self.update()

    # 줌 변경 시 마스크 스케일 캐시 무효화
    def set_zoom(self, factor, focal_point: QPoint | QPointF | None = None):
        super().set_zoom(factor, focal_point)
        if hasattr(self, '_mask_scaled'):
            self._mask_scaled_dirty = True

    def _rebuild_mask_cache(self, class_id):
        try:
            self._mask_overlay_class_id = class_id
            mask = self.current_mask
            if mask is None:
                self._mask_qimage = None
                self._mask_scaled = None
                self._mask_scaled_dirty = True
                self._mask_contours = []
                return
            h, w = mask.shape
            color = self.parent_dialog.get_color_for_class_id(class_id)
            r, g, b, a = color.red(), color.green(), color.blue(), color.alpha()
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            m = mask.astype(bool)
            rgba[m, 0] = r
            rgba[m, 1] = g
            rgba[m, 2] = b
            rgba[m, 3] = a
            bytes_per_line = w * 4
            self._mask_qimage = QImage(rgba.data, w, h, bytes_per_line, QImage.Format.Format_RGBA8888)
            self._mask_scaled = None
            self._mask_scaled_dirty = True
            # 외곽선 캐시도 구성
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            self._mask_contours = contours or []
        except Exception:
            self._mask_qimage = None
            self._mask_scaled = None
            self._mask_scaled_dirty = True
            self._mask_contours = []

class SAMAnnotationEditor(QDialog):
    """AI 어시스트 편집기 메인 창."""
    # v1.3: 방해 요소 저장을 위한 커스텀 결과 코드 정의
    DistractorSaved = 100
    SwitchToManual = 102

    mode_switch_requested = pyqtSignal(int)
    saved = pyqtSignal()
    canceled = pyqtSignal()
    distractor_saved = pyqtSignal()

    def __init__(self, pixmap, predictor, initial_polygons=None, parent=None, initial_class_name=None, *, embedded: bool = False):
        super().__init__(parent)
        self._embedded = embedded
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
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        self.mode_ai_btn = QPushButton("AI 편집")
        self.mode_ai_btn.setEnabled(False)
        self.mode_ai_btn.setToolTip("현재 AI 편집 모드입니다.")
        left_controls_layout.addWidget(self.mode_ai_btn)

        self.mode_manual_btn = QPushButton("수동 편집")
        self.mode_manual_btn.clicked.connect(self.on_switch_to_manual)
        left_controls_layout.addWidget(self.mode_manual_btn)

        class_selection_layout = QHBoxLayout()
        class_selection_layout.addWidget(QLabel("카테고리:"))
        self.category_selector = QComboBox()
        self.category_selector.addItems(SELECTABLE_CATEGORIES)
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
        self.button_box.accepted.connect(self.on_save)
        self.distractor_button.clicked.connect(self.on_save_distractor)
        if self._embedded:
            self.button_box.rejected.connect(self.on_cancel)
        else:
            self.button_box.rejected.connect(self.reject)

        main_layout.addLayout(top_controls_layout)
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(self.status_bar)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)
        self._preferred_size = self._compute_preferred_size(pixmap)
        if not self._embedded:
            self.resize(self._preferred_size)
        else:
            self.setWindowFlags(Qt.WindowType.Widget)

        self.full_class_list = self.learning_tab.data_manager.get_class_list()
        self.create_local_color_map()
        self.set_initial_selection(initial_class_name)
        self.setFocus()

    def _compute_preferred_size(self, pixmap: QPixmap) -> QSize:
        screen_geometry = QApplication.primaryScreen().availableGeometry()
        extra_width, extra_height = 80, 220
        raw_width = pixmap.width() + extra_width
        raw_height = pixmap.height() + extra_height
        max_width = int(screen_geometry.width() * 0.9)
        max_height = int(screen_geometry.height() * 0.9)
        scale = min(max_width / raw_width if raw_width else 1.0, max_height / raw_height if raw_height else 1.0, 1.0)
        preferred_width = max(int(raw_width * scale), 800)
        preferred_height = max(int(raw_height * scale), 600)
        return QSize(preferred_width, preferred_height)

    def sizeHint(self) -> QSize:
        if self._embedded:
            return self._preferred_size
        return super().sizeHint()

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

        if self._embedded:
            self.distractor_saved.emit()
        else:
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
        """선택된 카테고리의 '체크된 클래스'만 표시합니다."""
        self.class_selector.blockSignals(True)
        self.class_selector.clear()

        category = self.category_selector.currentText()
        manifest = self.learning_tab.data_manager.get_manifest()
        all_classes_in_category = list(manifest.get(category, {}).keys()) if isinstance(manifest.get(category), dict) else []
        checked = getattr(self.learning_tab, '_checked_class_names', set())
        filtered = [name for name in all_classes_in_category if name in checked]

        self.class_selector.addItems(filtered)
        if category != CHARACTER_CLASS_NAME:
            self.class_selector.addItem("[새 클래스 추가...]")

        if new_class_to_select and new_class_to_select in filtered:
            self.class_selector.setCurrentText(new_class_to_select)

        self.class_selector.blockSignals(False)

    def populate_category_selector(self):
        """체크된 클래스가 존재하는 카테고리만 표시합니다."""
        self.category_selector.blockSignals(True)
        self.category_selector.clear()
        manifest = self.learning_tab.data_manager.get_manifest()
        checked = getattr(self.learning_tab, '_checked_class_names', set())
        categories = []
        for cat in SELECTABLE_CATEGORIES:
            entry = manifest.get(cat)
            if isinstance(entry, dict):
                class_names = list(entry.keys())
                if any((name in checked) for name in class_names):
                    categories.append(cat)
        self.category_selector.addItems(categories)
        self.category_selector.blockSignals(False)

    def set_initial_selection(self, class_name):
        """체크된 클래스만 초기 선택으로 허용합니다."""
        checked = getattr(self.learning_tab, '_checked_class_names', set())
        if class_name and class_name in checked:
            category = self.learning_tab.data_manager.get_class_category(class_name)
            if category and category != CHARACTER_CLASS_NAME and self.category_selector.findText(category) != -1:
                self.category_selector.setCurrentText(category)
                self.update_class_selector(new_class_to_select=class_name)
                return
        if self.category_selector.count() > 0:
            self.category_selector.setCurrentIndex(0)
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
                    # [NEW] 새 클래스 자동 체크 반영
                    if hasattr(self.learning_tab, '_checked_class_names'):
                        self.learning_tab._checked_class_names.add(new_name)
                        self.learning_tab._apply_checked_classes_to_tree()
                        self.learning_tab._persist_checked_classes()
                    self.full_class_list = self.learning_tab.data_manager.get_class_list()
                    self.populate_category_selector()
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
        # 마스크 캐시 즉시 재구성(페인트 시 반복 계산 방지)
        try:
            class_id = self.get_current_class_id()
            if hasattr(self.canvas, '_rebuild_mask_cache'):
                self.canvas._rebuild_mask_cache(class_id)
        except Exception:
            pass
        self.canvas.update()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            # 우클릭 수동 차집합 폴리곤이 활성 상태이면 우선 적용
            if getattr(self.canvas, 'current_sub_points', None) and len(self.canvas.current_sub_points) >= 3 and self.canvas.current_mask is None:
                if self._commit_subtract_polygon():
                    return
            self.commit_current_mask()
        elif event.key() == Qt.Key.Key_Escape:
            # 작업 중일 때만 취소, 아니면 무시
            if getattr(self.canvas, 'current_sub_points', None):
                self.canvas.current_sub_points.clear(); self.canvas.update(); return
            if self.canvas.current_mask is not None or self.canvas.input_points:
                self.reset_current_mask(); return
            return
        elif event.key() == Qt.Key.Key_T:
            self.on_switch_to_manual()
        elif event.key() == Qt.Key.Key_R:
            self.reset_current_mask()
            if getattr(self.canvas, 'current_sub_points', None):
                self.canvas.current_sub_points.clear(); self.canvas.update()
        elif event.key() == Qt.Key.Key_Z:
            if self.canvas.polygons: self.canvas.polygons.pop(); self.canvas.update()
        elif event.key() == Qt.Key.Key_D: self.canvas.delete_hovered_polygon()
        elif event.key() == Qt.Key.Key_C:
            self.change_class_btn.setChecked(not self.change_class_btn.isChecked())
        else: super().keyPressEvent(event)

    def reset_current_mask(self):
        self.canvas.current_mask = None; self.canvas.input_points.clear(); self.canvas.input_labels.clear(); self.canvas.update()

    def get_all_polygons(self): return self.canvas.polygons

    def commit_current_mask(self):
        """현재 마스크를 다각형으로 변환해 저장합니다."""
        if self.canvas.current_mask is None:
            return False

        class_id = self.get_current_class_id()
        if class_id is None:
            return False

        contours, _ = cv2.findContours(self.canvas.current_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False

        largest_contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest_contour) <= 10:
            return False

        poly_points = [QPoint(p[0][0], p[0][1]) for p in largest_contour]
        self.canvas.polygons.append({'class_id': class_id, 'points': poly_points})
        self.reset_current_mask()
        return True

    # [NEW] AI 모드에서 완료 후 우클릭 폴리곤 차집합 적용
    def _commit_subtract_polygon(self) -> bool:
        sub_pts = getattr(self.canvas, 'current_sub_points', None)
        if not sub_pts or len(sub_pts) < 3:
            return False
        class_id = self.get_current_class_id()
        if class_id is None:
            return False
        qimg = self.pixmap.toImage()
        w, h = qimg.width(), qimg.height()
        if w <= 0 or h <= 0:
            return False
        sub_mask = np.zeros((h, w), dtype=np.uint8)
        pts = np.array([[int(p.x()), int(p.y())] for p in sub_pts], dtype=np.int32)
        cv2.fillPoly(sub_mask, [pts], 255)
        inv_sub = cv2.bitwise_not(sub_mask)
        updated = False
        new_list = []
        for poly in self.canvas.polygons:
            if poly.get('class_id') != class_id or not poly.get('points'):
                new_list.append(poly)
                continue
            single_mask = np.zeros((h, w), dtype=np.uint8)
            pts2 = np.array([[int(p.x()), int(p.y())] for p in poly['points']], dtype=np.int32)
            cv2.fillPoly(single_mask, [pts2], 255)
            result_mask = cv2.bitwise_and(single_mask, inv_sub)
            contours, _ = cv2.findContours(result_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            found_any = False
            for c in contours:
                if cv2.contourArea(c) <= 10:
                    continue
                pts3 = [QPoint(p[0][0], p[0][1]) for p in c]
                new_list.append({'class_id': class_id, 'points': pts3})
                found_any = True
            if found_any:
                updated = True
        if updated:
            self.canvas.polygons = new_list
            self.canvas.current_sub_points.clear()
            self.canvas.update()
            return True
        return False

    def on_save(self):
        self.commit_current_mask()
        if self._embedded:
            self.saved.emit()
        else:
            self.accept()

    def on_switch_to_manual(self):
        """수동 편집기로 전환합니다."""
        # [CHANGED] 자동 확정하지 않고, 진행 중인 마스크는 컨테이너가 수동 편집기로 전달
        if self._embedded:
            self.mode_switch_requested.emit(EditModeDialog.MANUAL)
        else:
            self.done(self.SwitchToManual)

    def get_current_class_name(self):
        class_name = self.class_selector.currentText()
        if class_name and class_name != "[새 클래스 추가...]":
            return class_name
        return None

    def on_cancel(self):
        if self._embedded:
            self.canceled.emit()
        else:
            self.reject()

    def update_mode_buttons(self, is_active: bool):
        if not hasattr(self, "mode_manual_btn"):
            return
        if is_active:
            self.mode_ai_btn.setEnabled(False)
            self.mode_ai_btn.setToolTip("현재 AI 편집 모드입니다.")
            self.mode_manual_btn.setEnabled(True)
            self.mode_manual_btn.setToolTip("수동 편집으로 전환")
        else:
            self.mode_ai_btn.setEnabled(True)
            self.mode_ai_btn.setToolTip("AI 편집으로 전환")
            self.mode_manual_btn.setEnabled(False)
            self.mode_manual_btn.setToolTip("현재 수동 편집 모드입니다.")

    def set_polygons(self, polygons):
        self.canvas.polygons = polygons if polygons else []
        self.create_local_color_map()
        self.reset_current_mask()
        self.canvas.update()

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

class AnnotationEditorDialog(QDialog):
    """AI/수동 편집기를 하나의 창에서 전환하기 위한 컨테이너."""

    def __init__(
        self,
        pixmap,
        learning_tab,
        sam_predictor,
        initial_polygons=None,
        initial_class_name=None,
        initial_mode=EditModeDialog.MANUAL,
        *,
        seq_index: int | None = None,
        seq_total: int | None = None,
    ):
        super().__init__(learning_tab)
        self.pixmap = pixmap
        self.learning_tab = learning_tab
        self.sam_predictor = sam_predictor
        self._result_polygons = []
        self._result_class_name = None
        self._current_mode = None
        # 다중 편집 순번 표시용
        self._seq_index = int(seq_index) if isinstance(seq_index, int) and seq_index > 0 else None
        self._seq_total = int(seq_total) if isinstance(seq_total, int) and seq_total > 0 else None

        polygons_copy = self._clone_polygons(initial_polygons)

        sam_ready = sam_predictor is not None
        self.manual_editor = PolygonAnnotationEditor(
            pixmap,
            polygons_copy,
            learning_tab,
            initial_class_name,
            embedded=True,
            sam_ready=sam_ready,
        )
        self.manual_editor.setParent(self)
        self.manual_editor.saved.connect(lambda: self._finalize(QDialog.DialogCode.Accepted, self.manual_editor))
        self.manual_editor.distractor_saved.connect(lambda: self._finalize(PolygonAnnotationEditor.DistractorSaved, self.manual_editor))
        self.manual_editor.canceled.connect(self.reject)
        self.manual_editor.mode_switch_requested.connect(self._handle_mode_switch)

        if sam_predictor is not None:
            self.ai_editor = SAMAnnotationEditor(
                pixmap,
                sam_predictor,
                polygons_copy,
                learning_tab,
                initial_class_name,
                embedded=True,
            )
            self.ai_editor.setParent(self)
            self.ai_editor.saved.connect(lambda: self._finalize(QDialog.DialogCode.Accepted, self.ai_editor))
            self.ai_editor.distractor_saved.connect(lambda: self._finalize(SAMAnnotationEditor.DistractorSaved, self.ai_editor))
            self.ai_editor.canceled.connect(self.reject)
            self.ai_editor.mode_switch_requested.connect(self._handle_mode_switch)
        else:
            self.ai_editor = None

        self.stack = QStackedLayout()
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.manual_editor)
        if self.ai_editor is not None:
            self.stack.addWidget(self.ai_editor)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addLayout(self.stack)

        self.setSizeGripEnabled(True)
        self.setMinimumSize(QSize(640, 480))

        if initial_mode == EditModeDialog.AI_ASSIST and self.ai_editor is not None:
            self._switch_mode(EditModeDialog.AI_ASSIST, initialize=True)
        else:
            self._switch_mode(EditModeDialog.MANUAL, initialize=True)

    def _clone_polygons(self, polygons):
        if not polygons:
            return []
        cloned = []
        for poly in polygons:
            points = [QPoint(p) for p in poly.get('points', [])]
            cloned.append({'class_id': poly.get('class_id'), 'points': points})
        return cloned

    def _handle_mode_switch(self, mode):
        self._switch_mode(mode)

    def _switch_mode(self, mode, *, initialize=False):
        sam_ready = self.sam_predictor is not None

        # 현재 뷰 상태(줌/스크롤) 스냅샷 후, 전환 대상에도 동일 적용
        prev_state = self._capture_view_state()

        if mode == EditModeDialog.AI_ASSIST:
            if self.ai_editor is None:
                if not initialize:
                    QMessageBox.warning(self, "오류", "SAM 모델이 준비되지 않아 AI 편집기로 전환할 수 없습니다.")
                return
            self.manual_editor.commit_current_polygon()
            polygons = self._clone_polygons(self.manual_editor.get_all_polygons())
            self.ai_editor.set_polygons(polygons)
            current_class = self.manual_editor.get_current_class_name()
            if current_class:
                self.ai_editor.set_initial_selection(current_class)
            self.ai_editor.reset_current_mask()
            self.stack.setCurrentWidget(self.ai_editor)
            self._current_mode = EditModeDialog.AI_ASSIST
            self.manual_editor.update_mode_buttons(False, sam_ready)
            self.ai_editor.update_mode_buttons(True)
            self._set_title_from_child(self.ai_editor)
            # 이전 뷰 상태 적용
            if prev_state is not None:
                self._apply_view_state(self.ai_editor, prev_state)
        else:
            if self.ai_editor is not None:
                # [CHANGED] AI → 수동 전환 시 더 이상 자동 확정하지 않음.
                # 진행 중이던 마스크를 수동 편집기의 pending_ai_mask로 전달하여, 수동에서 엔터 시 합집합 처리.
                ai_pending_mask = getattr(self.ai_editor.canvas, 'current_mask', None)
                polygons = self._clone_polygons(self.ai_editor.get_all_polygons())
                self.manual_editor.set_polygons(polygons)
                if ai_pending_mask is not None:
                    self.manual_editor.set_pending_ai_mask(ai_pending_mask)
            else:
                polygons = self._clone_polygons(self.manual_editor.get_all_polygons())
                self.manual_editor.set_polygons(polygons)
            if self.ai_editor is not None:
                current_class = self.ai_editor.get_current_class_name()
                if current_class:
                    self.manual_editor.set_initial_selection(current_class)
                self.ai_editor.update_mode_buttons(False)
            self.stack.setCurrentWidget(self.manual_editor)
            self._current_mode = EditModeDialog.MANUAL
            self.manual_editor.update_mode_buttons(True, sam_ready)
            self._set_title_from_child(self.manual_editor)
            # 이전 뷰 상태 적용
            if prev_state is not None:
                self._apply_view_state(self.manual_editor, prev_state)

        if initialize and self.ai_editor is None:
            self.manual_editor.update_mode_buttons(True, sam_ready)

        current_widget = self.stack.currentWidget()
        if current_widget is not None:
            desired_size = current_widget.sizeHint()
            new_width = max(self.width(), desired_size.width())
            new_height = max(self.height(), desired_size.height())
            self.resize(new_width, new_height)
            self.setMinimumSize(QSize(640, 480))
            current_widget.setFocus()

    # 줌/스크롤 상태를 캡처/적용하는 헬퍼
    def _capture_view_state(self) -> dict | None:
        try:
            current = self.stack.currentWidget()
            if current is None:
                return None
            canvas = getattr(current, 'canvas', None)
            scroll = getattr(current, 'scroll_area', None)
            if canvas is None or scroll is None:
                return None
            hbar = scroll.horizontalScrollBar()
            vbar = scroll.verticalScrollBar()
            return {
                'zoom': float(getattr(canvas, 'zoom_factor', 1.0) or 1.0),
                'h': int(hbar.value()),
                'v': int(vbar.value()),
            }
        except Exception:
            return None

    def _apply_view_state(self, editor_widget, state: dict) -> None:
        try:
            if not state:
                return
            canvas = getattr(editor_widget, 'canvas', None)
            scroll = getattr(editor_widget, 'scroll_area', None)
            if canvas is None or scroll is None:
                return
            # 1) 줌 적용 (포컬 지정 없음으로 위치 변화 최소화)
            zoom = float(state.get('zoom', 1.0) or 1.0)
            canvas.set_zoom(zoom)
            # 2) 스크롤바 적용 (범위 클램프)
            hbar = scroll.horizontalScrollBar()
            vbar = scroll.verticalScrollBar()
            hv = int(state.get('h', 0))
            vv = int(state.get('v', 0))
            hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), hv)))
            vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), vv)))
        except Exception:
            pass

    def _finalize(self, result_code, editor):
        self._result_polygons = self._clone_polygons(editor.get_all_polygons())
        self._result_class_name = editor.get_current_class_name()
        self.done(result_code)

    def result_polygons(self):
        return self._clone_polygons(self._result_polygons)

    def result_class_name(self):
        return self._result_class_name

    def current_mode(self):
        return self._current_mode

    def _compose_seq_title(self, base: str) -> str:
        try:
            if self._seq_total and self._seq_total > 1 and self._seq_index:
                return f"{base} ({self._seq_index}/{self._seq_total})"
        except Exception:
            pass
        return base

    def _set_title_from_child(self, child_widget: QWidget) -> None:
        try:
            base = child_widget.windowTitle()
        except Exception:
            base = "편집기"
        self.setWindowTitle(self._compose_seq_title(base))

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


class WindowAnchorSaveDialog(QDialog):
    """Mapleland 창 좌표 저장 시 이름을 입력받는 다이얼로그."""

    def __init__(self, geometry: WindowGeometry, suggested_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("창 좌표 저장")
        layout = QVBoxLayout(self)

        info_lines = [
            f"현재 창 위치: ({geometry.left}, {geometry.top})",
            f"창 크기: {geometry.width} x {geometry.height}",
        ]
        if geometry.screen_device:
            info_lines.append(f"모니터: {geometry.screen_device}")

        info_label = QLabel("\n".join(info_lines))
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.name_edit = QLineEdit(suggested_name)
        self.name_edit.selectAll()
        layout.addWidget(self.name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def anchor_name(self) -> str:
        return self.name_edit.text().strip()


class WindowAnchorLoadDialog(QDialog):
    """저장된 Mapleland 창 좌표 목록에서 선택하는 다이얼로그."""

    def __init__(self, anchors: dict[str, dict], last_used: Optional[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("창 좌표 불러오기")
        self._anchors = anchors

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("불러올 창 좌표를 선택하세요."))

        self.anchor_combo = QComboBox()
        for name, payload in anchors.items():
            left = int(payload.get("left", 0))
            top = int(payload.get("top", 0))
            width = int(payload.get("width", 0))
            height = int(payload.get("height", 0))
            display = f"{name} — ({left}, {top}) / {width}x{height}"
            self.anchor_combo.addItem(display, userData=name)

        if last_used:
            idx = self.anchor_combo.findData(last_used)
            if idx >= 0:
                self.anchor_combo.setCurrentIndex(idx)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.anchor_combo)
        layout.addWidget(self.detail_label)

        self.anchor_combo.currentIndexChanged.connect(self._update_details)
        self._update_details(self.anchor_combo.currentIndex())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_anchor_name(self) -> Optional[str]:
        return self.anchor_combo.currentData()

    def _update_details(self, index: int) -> None:
        if index < 0:
            self.detail_label.setText("")
            return
        name = self.anchor_combo.itemData(index)
        data = self._anchors.get(name, {})

        lines: list[str] = []
        device = data.get("screen_device")
        if device:
            lines.append(f"모니터: {device}")

        screen_components = (
            data.get("screen_left"),
            data.get("screen_top"),
            data.get("screen_width"),
            data.get("screen_height"),
        )
        if all(component is not None for component in screen_components):
            left, top, width, height = screen_components
            lines.append(
                f"모니터 위치: ({int(left)} , {int(top)}) / {int(width)}x{int(height)}"
            )

        timestamp = data.get("timestamp")
        if timestamp:
            try:
                ts = float(timestamp)
                lines.append(time.strftime("저장 시각: %Y-%m-%d %H:%M:%S", time.localtime(ts)))
            except (TypeError, ValueError):
                pass

        self.detail_label.setText("\n".join(lines))

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
        self._status_roi_payloads: dict[str, dict] = {}
        self.ensure_dirs_and_files()
        self.migrate_manifest_if_needed()
        settings = self.load_settings()
        if isinstance(settings, dict):
            model = settings.get('last_used_model') or settings.get('model')
            if isinstance(model, str) and model.strip():
                self._last_used_model = model.strip()
        self._prune_monster_confidence_overrides()
        # [NEW] 공격 금지 설정 정리(존재하지 않는 클래스 제거)
        try:
            self._prune_monster_attack_forbidden()
        except Exception:
            pass

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

    # --- [NEW] 펫 먹이 설정 관리 ---
    def _default_pet_feed_config(self) -> dict:
        return {
            'enabled': False,
            'when_exp_standalone': True,
            'when_map_or_hunt': True,
            'min_minutes': 30,
            'max_minutes': 30,
            'command_profile': None,
        }

    def get_pet_feed_config(self) -> dict:
        settings = self.load_settings()
        default_cfg = self._default_pet_feed_config()
        raw = settings.get('pet_feed') if isinstance(settings, dict) else None
        cfg = dict(raw) if isinstance(raw, dict) else {}
        changed = False

        # 병합 및 정규화
        for k, v in default_cfg.items():
            if k not in cfg:
                cfg[k] = v
                changed = True
        # 타입 보정
        cfg['enabled'] = bool(cfg.get('enabled'))
        cfg['when_exp_standalone'] = bool(cfg.get('when_exp_standalone'))
        cfg['when_map_or_hunt'] = bool(cfg.get('when_map_or_hunt'))
        try:
            min_m = int(cfg.get('min_minutes', 30) or 30)
        except (TypeError, ValueError):
            min_m = 30
        try:
            max_m = int(cfg.get('max_minutes', 30) or 30)
        except (TypeError, ValueError):
            max_m = 30
        if min_m < 1:
            min_m = 1
        if max_m < 1:
            max_m = 1
        if min_m > 720:
            min_m = 720
        if max_m > 720:
            max_m = 720
        if min_m > max_m:
            min_m, max_m = max_m, min_m
        if cfg.get('min_minutes') != min_m:
            cfg['min_minutes'] = min_m
            changed = True
        if cfg.get('max_minutes') != max_m:
            cfg['max_minutes'] = max_m
            changed = True

        cmd = cfg.get('command_profile')
        if not isinstance(cmd, str) or not cmd.strip():
            if cmd is not None:
                cfg['command_profile'] = None
                changed = True
        else:
            cfg['command_profile'] = cmd.strip()

        if changed:
            try:
                self.save_settings({'pet_feed': cfg})
            except Exception:
                pass
        return cfg

    def update_pet_feed_config(self, updates: dict) -> dict:
        if not isinstance(updates, dict):
            return self.get_pet_feed_config()
        cfg = self.get_pet_feed_config()
        merged = dict(cfg)
        for k, v in updates.items():
            merged[k] = v
        # 재정규화
        self.save_settings({'pet_feed': merged})
        return self.get_pet_feed_config()

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
            'apply_facing': False,
            'match_threshold': 0.60,
            'roi': {
                'width': 135,
                'height': 65,
                'offset_x': 0,
                'offset_y': 0,
            },
            'dead_zone_sec': 0.20,
            'track_missing_grace_sec': 0.12,
            'track_max_hold_sec': 2.0,
            # [NEW] 이름표 하위 OCR 설정(절대 좌표 ROI + 주기)
            'ocr': {
                'roi': {
                    'left': 0,
                    'top': 0,
                    'width': 0,
                    'height': 0,
                },
                'interval_sec': 5.0,
                'enabled': True,
                'use_gpu': False,
                # 필터/알림
                'conf_threshold': 0,         # 0~100 (%). 0이면 미적용
                'min_height_px': 0,          # 0~1000 px. 0이면 미적용
                'max_height_px': 0,          # 0이면 미적용
                'min_width_px': 0,           # 0이면 미적용
                'max_width_px': 0,           # 0이면 미적용
                'keywords': [],              # 콤마 구분 저장
                'telegram_enabled': False,   # 키워드 포함 시 전송
                'save_screenshots': False,   # 탐지 주기마다 스크린샷 저장 여부
            },
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
        if 'apply_facing' not in merged:
            merged['apply_facing'] = bool(default_config['apply_facing'])
            changed = True
        else:
            try:
                merged['apply_facing'] = bool(merged['apply_facing'])
            except Exception:
                merged['apply_facing'] = bool(default_config['apply_facing'])
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
        if 'track_max_hold_sec' not in merged:
            merged['track_max_hold_sec'] = default_config['track_max_hold_sec']
            changed = True
        else:
            try:
                hold_value = float(merged['track_max_hold_sec'])
            except (TypeError, ValueError):
                merged['track_max_hold_sec'] = default_config['track_max_hold_sec']
                changed = True
            else:
                clamped = max(0.0, min(5.0, hold_value))
                if abs(clamped - hold_value) > 1e-6:
                    merged['track_max_hold_sec'] = clamped
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
        # [NEW] ocr 하위 설정 병합(없으면 기본 추가)
        ocr_cfg = merged.get('ocr') if isinstance(merged.get('ocr'), dict) else None
        if ocr_cfg is None:
            merged['ocr'] = copy.deepcopy(default_config['ocr'])
            changed = True
        else:
            # roi 병합
            roi = ocr_cfg.get('roi') if isinstance(ocr_cfg.get('roi'), dict) else None
            if roi is None:
                ocr_cfg['roi'] = copy.deepcopy(default_config['ocr']['roi'])
                changed = True
            else:
                for k, v in default_config['ocr']['roi'].items():
                    if k not in roi:
                        roi[k] = v
                        changed = True
            # interval_sec 정규화
            try:
                iv = float(ocr_cfg.get('interval_sec', default_config['ocr']['interval_sec']))
            except (TypeError, ValueError):
                iv = default_config['ocr']['interval_sec']
            iv = max(0.2, min(600.0, iv))
            if abs(iv - float(ocr_cfg.get('interval_sec', 0.0))) > 1e-6:
                ocr_cfg['interval_sec'] = iv
                changed = True
            if 'enabled' not in ocr_cfg:
                ocr_cfg['enabled'] = bool(default_config['ocr']['enabled'])
                changed = True
            if 'use_gpu' not in ocr_cfg:
                ocr_cfg['use_gpu'] = bool(default_config['ocr']['use_gpu'])
                changed = True
            # 추가 필드 병합/정규화
            if 'conf_threshold' not in ocr_cfg:
                ocr_cfg['conf_threshold'] = int(default_config['ocr']['conf_threshold'])
                changed = True
            else:
                try:
                    ct = ocr_cfg['conf_threshold']
                    if isinstance(ct, float) and ct <= 1.0001:
                        ct = int(round(ct * 100))
                    ocr_cfg['conf_threshold'] = max(0, min(100, int(ct)))
                except Exception:
                    ocr_cfg['conf_threshold'] = 0
                changed = True
            if 'min_height_px' not in ocr_cfg:
                ocr_cfg['min_height_px'] = int(default_config['ocr']['min_height_px'])
                changed = True
            else:
                try:
                    mh = max(0, min(1000, int(ocr_cfg['min_height_px'])))
                except Exception:
                    mh = 0
                if ocr_cfg.get('min_height_px') != mh:
                    ocr_cfg['min_height_px'] = mh
                    changed = True
            if 'max_height_px' not in ocr_cfg:
                ocr_cfg['max_height_px'] = int(default_config['ocr']['max_height_px'])
                changed = True
            else:
                try:
                    xh = max(0, min(5000, int(ocr_cfg['max_height_px'])))
                except Exception:
                    xh = 0
                if ocr_cfg.get('max_height_px') != xh:
                    ocr_cfg['max_height_px'] = xh
                    changed = True
            if 'min_width_px' not in ocr_cfg:
                ocr_cfg['min_width_px'] = int(default_config['ocr']['min_width_px'])
                changed = True
            else:
                try:
                    mw = max(0, min(5000, int(ocr_cfg['min_width_px'])))
                except Exception:
                    mw = 0
                if ocr_cfg.get('min_width_px') != mw:
                    ocr_cfg['min_width_px'] = mw
                    changed = True
            if 'max_width_px' not in ocr_cfg:
                ocr_cfg['max_width_px'] = int(default_config['ocr']['max_width_px'])
                changed = True
            else:
                try:
                    xw = max(0, min(5000, int(ocr_cfg['max_width_px'])))
                except Exception:
                    xw = 0
                if ocr_cfg.get('max_width_px') != xw:
                    ocr_cfg['max_width_px'] = xw
                    changed = True
            if 'keywords' not in ocr_cfg or not isinstance(ocr_cfg.get('keywords'), list):
                ocr_cfg['keywords'] = []
                changed = True
            if 'telegram_enabled' not in ocr_cfg:
                ocr_cfg['telegram_enabled'] = bool(default_config['ocr']['telegram_enabled'])
                changed = True
            if 'save_screenshots' not in ocr_cfg:
                ocr_cfg['save_screenshots'] = bool(default_config['ocr']['save_screenshots'])
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

        if 'apply_facing' in updates:
            new_apply = bool(updates['apply_facing'])
            if bool(config.get('apply_facing', False)) != new_apply:
                config['apply_facing'] = new_apply
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

        if 'track_max_hold_sec' in updates:
            try:
                hold_value = float(updates['track_max_hold_sec'])
            except (TypeError, ValueError):
                hold_value = config.get(
                    'track_max_hold_sec', self._default_nameplate_config()['track_max_hold_sec']
                )
            hold_value = max(0.0, min(5.0, hold_value))
            if abs(config.get('track_max_hold_sec', 0.0) - hold_value) > 1e-6:
                config['track_max_hold_sec'] = hold_value
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

        # [NEW] ocr 하위 설정 갱신(roi/interval_sec/enabled)
        if 'ocr' in updates and isinstance(updates['ocr'], dict):
            ocr_cfg = dict(config.get('ocr', {})) if isinstance(config.get('ocr'), dict) else {}
            ocr_updates = updates['ocr']
            ocr_changed = False
            if 'roi' in ocr_updates and isinstance(ocr_updates['roi'], dict):
                ocr_roi = dict(ocr_cfg.get('roi', {})) if isinstance(ocr_cfg.get('roi'), dict) else {}
                for key in ('left', 'top', 'width', 'height'):
                    if key not in ocr_updates['roi']:
                        continue
                    try:
                        value = int(ocr_updates['roi'][key])
                    except (TypeError, ValueError):
                        continue
                    if key in {'width', 'height'}:
                        value = max(1, value)
                    if ocr_roi.get(key) != value:
                        ocr_roi[key] = value
                        ocr_changed = True
                ocr_cfg['roi'] = ocr_roi
            if 'interval_sec' in ocr_updates:
                try:
                    iv = float(ocr_updates['interval_sec'])
                except (TypeError, ValueError):
                    iv = ocr_cfg.get('interval_sec', 5.0)
                iv = max(0.2, min(600.0, iv))
                if abs(float(ocr_cfg.get('interval_sec', 0.0)) - iv) > 1e-6:
                    ocr_cfg['interval_sec'] = iv
                    ocr_changed = True
            if 'enabled' in ocr_updates:
                en = bool(ocr_updates['enabled'])
                if bool(ocr_cfg.get('enabled', True)) != en:
                    ocr_cfg['enabled'] = en
                    ocr_changed = True
            if 'use_gpu' in ocr_updates:
                ug = bool(ocr_updates['use_gpu'])
                if bool(ocr_cfg.get('use_gpu', False)) != ug:
                    ocr_cfg['use_gpu'] = ug
                    ocr_changed = True
            if 'conf_threshold' in ocr_updates:
                try:
                    ct = ocr_updates['conf_threshold']
                    if isinstance(ct, float) and ct <= 1.0001:
                        ct = int(round(ct * 100))
                    ct = max(0, min(100, int(ct)))
                except Exception:
                    ct = int(ocr_cfg.get('conf_threshold', 0) or 0)
                if int(ocr_cfg.get('conf_threshold', 0) or 0) != ct:
                    ocr_cfg['conf_threshold'] = ct
                    ocr_changed = True
            if 'min_height_px' in ocr_updates:
                try:
                    mh = max(0, min(1000, int(ocr_updates['min_height_px'])))
                except Exception:
                    mh = int(ocr_cfg.get('min_height_px', 0) or 0)
                if int(ocr_cfg.get('min_height_px', 0) or 0) != mh:
                    ocr_cfg['min_height_px'] = mh
                    ocr_changed = True
            if 'max_height_px' in ocr_updates:
                try:
                    xh = max(0, min(5000, int(ocr_updates['max_height_px'])))
                except Exception:
                    xh = int(ocr_cfg.get('max_height_px', 0) or 0)
                if int(ocr_cfg.get('max_height_px', 0) or 0) != xh:
                    ocr_cfg['max_height_px'] = xh
                    ocr_changed = True
            if 'min_width_px' in ocr_updates:
                try:
                    mw = max(0, min(5000, int(ocr_updates['min_width_px'])))
                except Exception:
                    mw = int(ocr_cfg.get('min_width_px', 0) or 0)
                if int(ocr_cfg.get('min_width_px', 0) or 0) != mw:
                    ocr_cfg['min_width_px'] = mw
                    ocr_changed = True
            if 'max_width_px' in ocr_updates:
                try:
                    xw = max(0, min(5000, int(ocr_updates['max_width_px'])))
                except Exception:
                    xw = int(ocr_cfg.get('max_width_px', 0) or 0)
                if int(ocr_cfg.get('max_width_px', 0) or 0) != xw:
                    ocr_cfg['max_width_px'] = xw
                    ocr_changed = True
            if 'keywords' in ocr_updates:
                kws = ocr_updates.get('keywords')
                if not isinstance(kws, list):
                    kws = []
                kws = [str(s).strip() for s in kws if isinstance(s, (str, int, float)) and str(s).strip()]
                if ocr_cfg.get('keywords') != kws:
                    ocr_cfg['keywords'] = kws
                    ocr_changed = True
            if 'telegram_enabled' in ocr_updates:
                te = bool(ocr_updates['telegram_enabled'])
                if bool(ocr_cfg.get('telegram_enabled', False)) != te:
                    ocr_cfg['telegram_enabled'] = te
                    ocr_changed = True
            if 'save_screenshots' in ocr_updates:
                ss = bool(ocr_updates['save_screenshots'])
                if bool(ocr_cfg.get('save_screenshots', False)) != ss:
                    ocr_cfg['save_screenshots'] = ss
                    ocr_changed = True
            if ocr_changed:
                config['ocr'] = ocr_cfg
                changed = True

        if changed:
            self._write_nameplate_config(config)
        self._notify_overlay_listeners({
            'target': 'monster_nameplate',
            'show_overlay': bool(config.get('show_overlay', True)),
            'enabled': bool(config.get('enabled', False)),
            'apply_facing': bool(config.get('apply_facing', False)),
            'roi': dict(config.get('roi', {})),
            'match_threshold': float(config.get('match_threshold', 0.60)),
            'dead_zone_sec': float(config.get('dead_zone_sec', 0.20)),
            'track_missing_grace_sec': float(config.get('track_missing_grace_sec', 0.12)),
            'track_max_hold_sec': float(config.get('track_max_hold_sec', 2.0)),
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

        # [NEW] 공격 금지 설정 키 이관
        try:
            forbidden_map = self.get_monster_attack_forbidden_map()
            if old_name in forbidden_map:
                forbidden_map[new_name] = bool(forbidden_map.pop(old_name))
                self.save_settings({'monster_attack_forbidden': forbidden_map})
        except Exception:
            pass

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
        # [NEW] 공격 금지 설정 제거
        try:
            self.delete_monster_attack_forbidden(class_name)
        except Exception:
            pass

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

    # --- [NEW] 몬스터 공격 금지 설정 ---
    def get_monster_attack_forbidden_map(self) -> dict[str, bool]:
        settings = self.load_settings()
        raw = settings.get('monster_attack_forbidden', {}) if isinstance(settings, dict) else {}
        result: dict[str, bool] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str):
                    result[key] = bool(value)
        return result

    def is_monster_attack_forbidden(self, class_name: str) -> bool:
        try:
            return bool(self.get_monster_attack_forbidden_map().get(class_name, False))
        except Exception:
            return False

    def set_monster_attack_forbidden(self, class_name: str, enabled: bool) -> None:
        class_name = (class_name or '').strip()
        if not class_name:
            return
        settings = self.load_settings()
        current = dict(settings.get('monster_attack_forbidden', {})) if isinstance(settings, dict) else {}
        if enabled:
            current[class_name] = True
        else:
            current.pop(class_name, None)
        self.save_settings({'monster_attack_forbidden': current})

    def delete_monster_attack_forbidden(self, class_name: str) -> None:
        class_name = (class_name or '').strip()
        if not class_name:
            return
        settings = self.load_settings()
        current = dict(settings.get('monster_attack_forbidden', {})) if isinstance(settings, dict) else {}
        if class_name in current:
            current.pop(class_name, None)
            self.save_settings({'monster_attack_forbidden': current})

    def _prune_monster_attack_forbidden(self) -> None:
        settings = self.load_settings()
        current = dict(settings.get('monster_attack_forbidden', {})) if isinstance(settings, dict) else {}
        if not current:
            return
        valid = set(self.get_class_list())
        removed = False
        for key in list(current.keys()):
            if key not in valid:
                current.pop(key, None)
                removed = True
        if removed:
            self.save_settings({'monster_attack_forbidden': current})

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
        if not isinstance(data, dict):
            data = {}

        window_geometry = get_maple_window_geometry()
        self._status_roi_payloads = {}
        dirty = False

        for resource_key in ('hp', 'mp', 'exp'):
            resource_data = data.get(resource_key)
            if not isinstance(resource_data, dict):
                resource_data = {}
                data[resource_key] = resource_data

            roi_payload = resource_data.get('roi_payload')
            if not isinstance(roi_payload, dict):
                roi_payload = resource_data.get('roi') if isinstance(resource_data.get('roi'), dict) else None

            if isinstance(roi_payload, dict):
                converted_payload = ensure_relative_roi(roi_payload, window_geometry, anchor_name=last_used_anchor_name())
                if converted_payload is None:
                    converted_payload = roi_payload
                if converted_payload is not roi_payload:
                    dirty = True
                self._status_roi_payloads[resource_key] = copy.deepcopy(converted_payload)
                absolute_roi = resolve_roi_to_absolute(converted_payload, window=window_geometry)
                if absolute_roi is not None:
                    resource_data['roi'] = absolute_roi
                if resource_data.get('roi_payload') != converted_payload:
                    resource_data['roi_payload'] = converted_payload
                    dirty = True
            else:
                # ROI 정보가 전혀 없는 경우 안전한 기본값 유지
                resource_data.setdefault('roi', {'left': 0, 'top': 0, 'width': 0, 'height': 0})

        config = StatusMonitorConfig.from_dict(data)
        if dirty:
            self._write_status_config(config)
        return config

    def get_status_roi_payloads(self) -> dict[str, dict]:
        return copy.deepcopy(self._status_roi_payloads)

    def update_status_monitor_config(self, updates: dict) -> StatusMonitorConfig:
        if not isinstance(updates, dict):
            return self.load_status_monitor_config()

        config = self.load_status_monitor_config()

        def apply_resource(resource_key: str, target: StatusResourceConfig, payload: Optional[dict], *, allow_threshold: bool) -> None:
            if not isinstance(payload, dict):
                return
            if 'roi' in payload or 'roi_payload' in payload:
                raw_roi = payload.get('roi_payload') if isinstance(payload.get('roi_payload'), dict) else payload.get('roi')
                if isinstance(raw_roi, dict):
                    window_geometry = get_maple_window_geometry()
                    relative_payload = ensure_relative_roi(
                        raw_roi,
                        window_geometry,
                        anchor_name=last_used_anchor_name(),
                    )
                    if relative_payload is None:
                        relative_payload = raw_roi
                    self._status_roi_payloads[resource_key] = copy.deepcopy(relative_payload)
                    absolute_roi = resolve_roi_to_absolute(relative_payload, window=window_geometry)
                    if absolute_roi is None:
                        absolute_roi = resolve_roi_to_absolute(relative_payload)
                    if absolute_roi is None:
                        absolute_roi = raw_roi
                    target.roi = StatusRoi.from_dict(absolute_roi)
            if 'interval_sec' in payload:
                try:
                    val = float(payload.get('interval_sec'))
                except (TypeError, ValueError):
                    val = None
                if val is not None and val > 0:
                    target.interval_sec = max(0.1, val)
            # [NEW] 단독사용 토글 (mp 전용 의미, 공통 키로 수용)
            if 'standalone' in payload:
                try:
                    target.standalone = bool(payload.get('standalone'))
                except Exception:
                    pass
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
                        # [변경] 1 이상이면 저장(100 초과는 절대 HP로 해석)
                        if 1 <= t_val:
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
            # 긴급모드 설정 적용 (hp 중심, 다른 리소스도 키가 있으면 수용)
            if 'emergency_enabled' in payload:
                try:
                    target.emergency_enabled = bool(payload.get('emergency_enabled'))
                except Exception:
                    pass
            if 'emergency_trigger_failures' in payload:
                try:
                    val = int(payload.get('emergency_trigger_failures'))
                except (TypeError, ValueError):
                    val = None
                if val is not None and val >= 1:
                    target.emergency_trigger_failures = val
            if 'emergency_max_duration_sec' in payload:
                try:
                    val = float(payload.get('emergency_max_duration_sec'))
                except (TypeError, ValueError):
                    val = None
                if val is not None and val >= 1.0:
                    target.emergency_max_duration_sec = val
            if 'emergency_timeout_telegram' in payload:
                try:
                    target.emergency_timeout_telegram = bool(payload.get('emergency_timeout_telegram'))
                except Exception:
                    pass
            # [NEW] 긴급모드 발동용 HP 임계값(%)
            if 'emergency_trigger_hp_percent' in payload:
                raw = payload.get('emergency_trigger_hp_percent')
                if raw in (None, ''):
                    target.emergency_trigger_hp_percent = None
                else:
                    try:
                        ival = int(raw)
                    except (TypeError, ValueError):
                        pass
                    else:
                        if 1 <= ival <= 99:
                            target.emergency_trigger_hp_percent = ival
            # [NEW] HP 초긴급모드 임계값/명령프로필
            if 'urgent_threshold' in payload:
                raw = payload.get('urgent_threshold')
                if raw in (None, ''):
                    target.urgent_threshold = None
                else:
                    try:
                        ival = int(raw)
                    except (TypeError, ValueError):
                        pass
                    else:
                        if 1 <= ival <= 99:
                            target.urgent_threshold = ival
            if 'urgent_command_profile' in payload:
                raw = payload.get('urgent_command_profile')
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    target.urgent_command_profile = None
                elif isinstance(raw, str):
                    target.urgent_command_profile = raw.strip()
            # [NEW] HP 저체력(3% 미만) 텔레그램 알림 여부
            if 'low_hp_telegram_alert' in payload:
                try:
                    target.low_hp_telegram_alert = bool(payload.get('low_hp_telegram_alert'))
                except Exception:
                    pass

        apply_resource('hp', config.hp, updates.get('hp'), allow_threshold=True)
        apply_resource('mp', config.mp, updates.get('mp'), allow_threshold=True)
        apply_resource('exp', config.exp, updates.get('exp'), allow_threshold=False)

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
        payload = config.to_dict()
        for key in ('hp', 'mp', 'exp'):
            resource_payload = payload.get(key)
            if not isinstance(resource_payload, dict):
                continue
            roi_payload = self._status_roi_payloads.get(key)
            if roi_payload:
                resource_payload['roi_payload'] = roi_payload
        with open(self.status_config_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
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

    def __init__(self, yaml_path, epochs, base_model_name, training_runs_path, selected_class_indices=None, patience: Optional[int] = None):
        super().__init__()
        self.yaml_path = yaml_path
        self.epochs = epochs
        self.base_model_name = base_model_name
        self.training_runs_path = training_runs_path  # (v1.2) 훈련 결과 저장 경로 추가
        # v1.5: 선택된 클래스만 학습하도록 인덱스 전달(없으면 전체 학습)
        self.selected_class_indices = selected_class_indices if selected_class_indices else None
        # (v1.6) 조기종료 허용 에폭 수
        self.patience = patience

    def run(self):
        try:
            cls_info = (
                f"선택 클래스: {len(self.selected_class_indices)}개" if self.selected_class_indices else "전체 클래스"
            )
            self.progress.emit(
                f"모델 훈련을 시작합니다... (기본 모델: {self.base_model_name}, Epochs: {self.epochs}, {cls_info})"
            )
            model = YOLO(f"{self.base_model_name}-seg.pt")
            # (v1.2) project 경로를 workspace/training_runs로 지정
            # Ultralytics YOLOv8-seg 학습 호출. 조기종료(patience) 지원.
            kwargs = dict(
                data=self.yaml_path,
                epochs=self.epochs,
                imgsz=640,
                device=0,
                project=self.training_runs_path,
                # v1.5: 선택된 클래스만 학습
                classes=self.selected_class_indices,
            )
            if self.patience is not None:
                kwargs["patience"] = int(self.patience)

            results = model.train(**kwargs)
            self.results_path_ready.emit(str(results.save_dir))
            self.finished.emit(True, "훈련 성공! '최신 훈련 저장'으로 모델을 저장하세요.")
        except Exception as e:
            self.finished.emit(False, f"훈련 오류: {e}")

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
    # 자동 제어 탭으로 명령 전달 시그널
    control_command_issued = pyqtSignal(str, object)
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
        # [NEW] MP 단독사용 런타임 상태
        self._mp_standalone_last_ts: float = 0.0
        self._hunt_active: bool = False
        self._map_active: bool = False
        self._status_ui_updating = False
        self._status_command_options: list[tuple[str, str]] = []
        self._thumbnail_cache = OrderedDict()
        self._thumbnail_cache_limit = 256
        self._thumbnail_cache_dir = os.path.join(WORKSPACE_ROOT, "cache", "thumbnails")
        os.makedirs(self._thumbnail_cache_dir, exist_ok=True)
        self._thumbnail_disk_limit = 512
        self._runtime_ui_updating = False
        self._monster_settings_dialog_open = False
        # [NEW] 편집 초기 클래스 유지(배치/최근)
        self._batch_initial_class_name: Optional[str] = None
        self._last_used_editor_class: Optional[str] = None
        self.initUI()
        self.init_sam()
        self.data_manager.register_status_config_listener(self._handle_status_config_changed)
        # [NEW] 단독실행 체크박스 색상 토글 타이머
        try:
            self._standalone_ui_timer = QTimer(self)
            self._standalone_ui_timer.setSingleShot(False)
            self._standalone_ui_timer.setInterval(500)
            self._standalone_ui_timer.timeout.connect(self._tick_standalone_ui)
            self._standalone_ui_timer.start()
        except Exception:
            pass
        # [NEW] 펫 먹이 스케줄러 상태
        self._pet_feed_cfg = self.data_manager.get_pet_feed_config()
        self._pet_feed_next_due_ts: float = 0.0
        try:
            self._pet_feed_timer = QTimer(self)
            self._pet_feed_timer.setSingleShot(False)
            self._pet_feed_timer.setInterval(1000)
            self._pet_feed_timer.timeout.connect(self._tick_pet_feed)
            self._pet_feed_timer.start()
        except Exception:
            pass

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

        # 이미지 목록 그룹 (헤더 정렬 + 리스트 + 캡처 옵션 + 하단 버튼까지 포함)
        image_group = QGroupBox("이미지 목록")
        # 그룹이 필요 이상 세로 확장되지 않도록 제한
        image_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum))
        image_group_layout = QVBoxLayout()
        image_group_layout.setContentsMargins(8, 8, 8, 8)
        image_group_layout.setSpacing(6)

        image_list_header_layout = QHBoxLayout()
        image_list_header_layout.setContentsMargins(0, 0, 0, 0)
        image_list_header_layout.setSpacing(6)
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
        # 가로는 확장, 세로는 고정 정책으로 내부 여백 발생 방지
        self.image_list_widget.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        # 고정 높이: 세로 350px로 제한
        self.image_list_widget.setFixedHeight(350)

        capture_options_layout = QHBoxLayout()
        capture_options_layout.setContentsMargins(0, 0, 0, 0)
        capture_options_layout.setSpacing(6)
        delay_label = QLabel("대기시간(초):")
        delay_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        capture_options_layout.addWidget(delay_label)
        self.capture_delay_spinbox = QDoubleSpinBox()
        self.capture_delay_spinbox.setRange(0.0, 10.0)
        self.capture_delay_spinbox.setValue(0.0)
        self.capture_delay_spinbox.setSingleStep(0.1)
        self.capture_delay_spinbox.setMaximumWidth(100)
        capture_options_layout.addWidget(self.capture_delay_spinbox)
        count_label = QLabel("횟수:")
        count_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        capture_options_layout.addWidget(count_label)
        self.capture_count_spinbox = QSpinBox()
        self.capture_count_spinbox.setRange(1, 50)
        self.capture_count_spinbox.setValue(1)
        self.capture_count_spinbox.setMaximumWidth(90)
        capture_options_layout.addWidget(self.capture_count_spinbox)
        interval_label = QLabel("간격(초):")
        interval_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        capture_options_layout.addWidget(interval_label)
        self.capture_interval_spinbox = QDoubleSpinBox()
        self.capture_interval_spinbox.setRange(0.2, 5.0)
        self.capture_interval_spinbox.setValue(1.0)
        self.capture_interval_spinbox.setSingleStep(0.1)
        self.capture_interval_spinbox.setMaximumWidth(100)
        capture_options_layout.addWidget(self.capture_interval_spinbox)
        self.capture_btn = QPushButton('메이플 창 캡처')
        self.capture_btn.clicked.connect(self.capture_screen)
        capture_options_layout.addWidget(self.capture_btn)
        capture_options_layout.addStretch(1)

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

        # 구성 요소들을 이미지 그룹 레이아웃에 모아 추가
        image_group_layout.addLayout(image_list_header_layout)
        image_group_layout.addWidget(self.image_list_widget)
        image_group_layout.addLayout(capture_options_layout)
        image_group_layout.addLayout(center_buttons_layout)
        image_group.setLayout(image_group_layout)

        nameplate_group = QGroupBox("몬스터 이름표")
        nameplate_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum))
        nameplate_group.setCheckable(True)
        nameplate_group.setChecked(False)
        self.nameplate_group = nameplate_group
        nameplate_layout = QVBoxLayout()
        nameplate_layout.setContentsMargins(8, 8, 8, 8)
        nameplate_layout.setSpacing(8)

        # OCR 그룹과 유사한 Form 스타일로 정리
        nameplate_form = QFormLayout()
        nameplate_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        nameplate_form.setHorizontalSpacing(12)
        nameplate_form.setVerticalSpacing(8)
        nameplate_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        # 크기
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(6)
        self.nameplate_width_spin = QSpinBox()
        self.nameplate_width_spin.setRange(10, 600)
        self.nameplate_width_spin.setSingleStep(5)
        self.nameplate_width_spin.setMaximumWidth(80)
        size_label_w = QLabel("가로")
        size_label_w.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        size_row.addWidget(size_label_w)
        size_row.addWidget(self.nameplate_width_spin)
        self.nameplate_height_spin = QSpinBox()
        self.nameplate_height_spin.setRange(10, 400)
        self.nameplate_height_spin.setSingleStep(5)
        self.nameplate_height_spin.setMaximumWidth(80)
        size_label_h = QLabel("세로")
        size_label_h.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        size_row.addWidget(size_label_h)
        size_row.addWidget(self.nameplate_height_spin)
        size_row.addStretch(1)
        size_widget = QWidget()
        size_widget.setLayout(size_row)
        nameplate_form.addRow("이름표 크기", size_widget)

        # 오프셋 + 범위표시
        offset_row = QHBoxLayout()
        offset_row.setContentsMargins(0, 0, 0, 0)
        offset_row.setSpacing(6)
        self.nameplate_offset_x_spin = QSpinBox()
        self.nameplate_offset_x_spin.setRange(-300, 300)
        self.nameplate_offset_x_spin.setSingleStep(5)
        self.nameplate_offset_x_spin.setMaximumWidth(80)
        offset_label_x = QLabel("X")
        offset_label_x.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        offset_row.addWidget(offset_label_x)
        offset_row.addWidget(self.nameplate_offset_x_spin)
        self.nameplate_offset_y_spin = QSpinBox()
        self.nameplate_offset_y_spin.setRange(-300, 300)
        self.nameplate_offset_y_spin.setSingleStep(5)
        self.nameplate_offset_y_spin.setMaximumWidth(80)
        offset_label_y = QLabel("Y")
        offset_label_y.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        offset_row.addWidget(offset_label_y)
        offset_row.addWidget(self.nameplate_offset_y_spin)
        self.nameplate_overlay_checkbox = QCheckBox("범위 표시")
        offset_row.addWidget(self.nameplate_overlay_checkbox)
        offset_row.addStretch(1)
        offset_widget = QWidget()
        offset_widget.setLayout(offset_row)
        nameplate_form.addRow("오프셋", offset_widget)

        # 감지 설정(임계값/사망 무시/유예/최대 유지)
        detection_row = QHBoxLayout()
        detection_row.setContentsMargins(0, 0, 0, 0)
        detection_row.setSpacing(6)
        self.nameplate_threshold_spin = QDoubleSpinBox()
        self.nameplate_threshold_spin.setRange(0.10, 0.99)
        self.nameplate_threshold_spin.setSingleStep(0.01)
        self.nameplate_threshold_spin.setDecimals(2)
        self.nameplate_threshold_spin.setMaximumWidth(90)
        th_label = QLabel("임계값")
        th_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        detection_row.addWidget(th_label)
        detection_row.addWidget(self.nameplate_threshold_spin)
        self.nameplate_dead_zone_spin = QDoubleSpinBox()
        self.nameplate_dead_zone_spin.setRange(0.0, 2.0)
        self.nameplate_dead_zone_spin.setSingleStep(0.01)
        self.nameplate_dead_zone_spin.setDecimals(2)
        self.nameplate_dead_zone_spin.setMaximumWidth(90)
        dz_label = QLabel("사망 무시")
        dz_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        detection_row.addWidget(dz_label)
        detection_row.addWidget(self.nameplate_dead_zone_spin)
        self.nameplate_grace_spin = QDoubleSpinBox()
        self.nameplate_grace_spin.setRange(0.0, 2.0)
        self.nameplate_grace_spin.setSingleStep(0.01)
        self.nameplate_grace_spin.setDecimals(2)
        self.nameplate_grace_spin.setMaximumWidth(90)
        gr_label = QLabel("유예")
        gr_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        detection_row.addWidget(gr_label)
        detection_row.addWidget(self.nameplate_grace_spin)
        self.nameplate_hold_spin = QDoubleSpinBox()
        self.nameplate_hold_spin.setRange(0.0, 5.0)
        self.nameplate_hold_spin.setSingleStep(0.1)
        self.nameplate_hold_spin.setDecimals(2)
        self.nameplate_hold_spin.setMaximumWidth(90)
        hold_label = QLabel("최대 유지")
        hold_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred))
        detection_row.addWidget(hold_label)
        detection_row.addWidget(self.nameplate_hold_spin)
        detection_row.addStretch(1)
        detection_widget = QWidget()
        detection_widget.setLayout(detection_row)
        nameplate_form.addRow("감지 설정", detection_widget)

        # 필터: 캐릭터 방향 적용
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        self.nameplate_apply_facing_checkbox = QCheckBox("캐릭터 방향 적용")
        filter_row.addWidget(self.nameplate_apply_facing_checkbox)
        filter_row.addStretch(1)
        filter_widget = QWidget()
        filter_widget.setLayout(filter_row)
        nameplate_form.addRow("필터", filter_widget)

        nameplate_layout.addLayout(nameplate_form)

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
        self.nameplate_hold_spin.valueChanged.connect(self._handle_nameplate_hold_changed)
        self.nameplate_apply_facing_checkbox.toggled.connect(self._handle_nameplate_apply_facing_toggled)

        # 중앙 레이아웃에는 그룹만 추가
        center_layout.addWidget(image_group)
        center_layout.addWidget(nameplate_group)

        # [NEW] 몬스터 이름표 하위 OCR 그룹
        ocr_group = QGroupBox("OCR")
        # 그룹 높이가 내용만큼만 차지하도록 설정
        ocr_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum))
        self.nameplate_ocr_group = ocr_group
        ocr_form = QFormLayout()
        ocr_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        ocr_form.setHorizontalSpacing(12)
        ocr_form.setVerticalSpacing(8)

        # 엔진 상태 (라벨 + 현재 엔진 + GPU 토글)
        engine_field = QWidget()
        engine_field_row = QHBoxLayout(engine_field)
        engine_field_row.setContentsMargins(0, 0, 0, 0)
        engine_field_row.setSpacing(8)
        self.ocr_engine_label = QLabel(get_ocr_engine_label())
        engine_field_row.addWidget(self.ocr_engine_label)
        self.ocr_gpu_checkbox = QCheckBox('GPU 사용')
        self.ocr_gpu_checkbox.setToolTip('PaddleOCR을 GPU로 실행합니다. (Paddle GPU 빌드 필요)')
        self.ocr_gpu_checkbox.toggled.connect(self._handle_ocr_gpu_toggled)
        engine_field_row.addWidget(self.ocr_gpu_checkbox)
        # 단독 실행 체크박스
        self.ocr_standalone_checkbox = QCheckBox('단독 실행')
        self.ocr_standalone_checkbox.setToolTip('맵/사냥탭이 실행되지 않아도 OCR을 단독 실행합니다.')
        self.ocr_standalone_checkbox.toggled.connect(self._handle_ocr_standalone_toggled)
        engine_field_row.addWidget(self.ocr_standalone_checkbox)
        engine_field_row.addStretch(1)
        ocr_form.addRow('엔진', engine_field)

        # ROI: 버튼 2개 + 요약
        roi_field = QWidget()
        roi_field_row = QHBoxLayout(roi_field)
        roi_field_row.setContentsMargins(0, 0, 0, 0)
        roi_field_row.setSpacing(8)
        self.ocr_roi_button = QPushButton('탐지 범위 설정')
        self.ocr_roi_button.setToolTip('이름표 OCR 탐지 범위를 화면에서 지정합니다.')
        self.ocr_roi_button.clicked.connect(self._handle_ocr_roi_select)
        roi_field_row.addWidget(self.ocr_roi_button)
        self.ocr_test_button = QPushButton('인식 테스트')
        self.ocr_test_button.setToolTip('지정한 범위를 즉시 캡처하여 텍스트를 OCR로 인식합니다.')
        self.ocr_test_button.clicked.connect(self._handle_ocr_test)
        roi_field_row.addWidget(self.ocr_test_button)
        # 탐지 보고 버튼
        self.ocr_report_button = QPushButton('탐지 보고')
        self.ocr_report_button.setToolTip('탐지 주기마다 최신 인식 결과를 보여주는 창을 엽니다.')
        self.ocr_report_button.clicked.connect(self._open_ocr_live_report)
        roi_field_row.addWidget(self.ocr_report_button)
        self.ocr_roi_summary_label = QLabel('위치/크기 미설정')
        self.ocr_roi_summary_label.setStyleSheet('color: #666666;')
        roi_field_row.addSpacing(8)
        roi_field_row.addWidget(self.ocr_roi_summary_label)
        roi_field_row.addStretch(1)
        ocr_form.addRow('탐지 범위', roi_field)

        # 탐지주기(초) + 스크린샷 저장 체크
        interval_field = QWidget()
        interval_row = QHBoxLayout(interval_field)
        interval_row.setContentsMargins(0, 0, 0, 0)
        interval_row.setSpacing(8)
        self.ocr_interval_spin = QDoubleSpinBox()
        self.ocr_interval_spin.setRange(0.2, 600.0)
        self.ocr_interval_spin.setSingleStep(0.2)
        self.ocr_interval_spin.setDecimals(2)
        self.ocr_interval_spin.setMaximumWidth(100)
        self.ocr_interval_spin.valueChanged.connect(self._handle_ocr_interval_changed)
        interval_row.addWidget(self.ocr_interval_spin)
        self.ocr_screenshot_checkbox = QCheckBox('스크린샷 저장')
        self.ocr_screenshot_checkbox.setToolTip('탐지 주기마다 ROI 원본과 OCR 결과 이미지를 저장합니다.')
        self.ocr_screenshot_checkbox.toggled.connect(self._handle_ocr_save_screenshot_toggled)
        interval_row.addWidget(self.ocr_screenshot_checkbox)
        interval_row.addStretch(1)
        ocr_form.addRow('탐지 주기(초)', interval_field)

        # 필터(신뢰도% + 최소/최대 높이 px + 최소/최대 넓이 px)
        filter_field = QWidget()
        filter_row = QHBoxLayout(filter_field)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)
        self.ocr_conf_spin = QSpinBox()
        self.ocr_conf_spin.setRange(0, 100)
        self.ocr_conf_spin.setSingleStep(1)
        self.ocr_conf_spin.setMaximumWidth(80)
        self.ocr_conf_spin.valueChanged.connect(self._handle_ocr_conf_changed)
        filter_row.addWidget(QLabel('신뢰도(%)'))
        filter_row.addWidget(self.ocr_conf_spin)
        self.ocr_min_height_spin = QSpinBox()
        self.ocr_min_height_spin.setRange(0, 1000)
        self.ocr_min_height_spin.setSingleStep(1)
        self.ocr_min_height_spin.setMaximumWidth(90)
        self.ocr_min_height_spin.valueChanged.connect(self._handle_ocr_min_height_changed)
        filter_row.addSpacing(8)
        filter_row.addWidget(QLabel('최소 높이(px)'))
        filter_row.addWidget(self.ocr_min_height_spin)
        self.ocr_max_height_spin = QSpinBox()
        self.ocr_max_height_spin.setRange(0, 5000)
        self.ocr_max_height_spin.setSingleStep(1)
        self.ocr_max_height_spin.setMaximumWidth(90)
        self.ocr_max_height_spin.valueChanged.connect(self._handle_ocr_max_height_changed)
        filter_row.addSpacing(8)
        filter_row.addWidget(QLabel('최대 높이(px)'))
        filter_row.addWidget(self.ocr_max_height_spin)
        self.ocr_min_width_spin = QSpinBox()
        self.ocr_min_width_spin.setRange(0, 5000)
        self.ocr_min_width_spin.setSingleStep(1)
        self.ocr_min_width_spin.setMaximumWidth(90)
        self.ocr_min_width_spin.valueChanged.connect(self._handle_ocr_min_width_changed)
        filter_row.addSpacing(8)
        filter_row.addWidget(QLabel('최소 넓이(px)'))
        filter_row.addWidget(self.ocr_min_width_spin)
        self.ocr_max_width_spin = QSpinBox()
        self.ocr_max_width_spin.setRange(0, 5000)
        self.ocr_max_width_spin.setSingleStep(1)
        self.ocr_max_width_spin.setMaximumWidth(90)
        self.ocr_max_width_spin.valueChanged.connect(self._handle_ocr_max_width_changed)
        filter_row.addSpacing(8)
        filter_row.addWidget(QLabel('최대 넓이(px)'))
        filter_row.addWidget(self.ocr_max_width_spin)
        filter_row.addStretch(1)
        ocr_form.addRow('필터', filter_field)

        # 키워드 알림 (체크 + 입력)
        keyword_field = QWidget()
        keyword_row = QHBoxLayout(keyword_field)
        keyword_row.setContentsMargins(0, 0, 0, 0)
        keyword_row.setSpacing(8)
        self.ocr_keyword_alert_checkbox = QCheckBox('사용')
        self.ocr_keyword_alert_checkbox.setToolTip('검출 텍스트에 키워드가 포함되면 텔레그램 알림 전송')
        self.ocr_keyword_alert_checkbox.toggled.connect(self._handle_ocr_keyword_alert_toggled)
        keyword_row.addWidget(self.ocr_keyword_alert_checkbox)
        self.ocr_keywords_edit = QLineEdit()
        self.ocr_keywords_edit.setPlaceholderText('콤마로 구분: 예) 보스,경고,드랍')
        self.ocr_keywords_edit.editingFinished.connect(self._handle_ocr_keywords_changed)
        keyword_row.addWidget(self.ocr_keywords_edit)
        ocr_form.addRow('키워드 알림', keyword_field)

        ocr_group.setLayout(ocr_form)
        center_layout.addWidget(ocr_group)

        window_anchor_group = QGroupBox("Mapleland 창 좌표 관리")
        # 그룹 높이가 내용만큼만 차지하도록 설정
        window_anchor_group.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum))
        window_anchor_layout = QVBoxLayout()
        self.window_anchor_summary_label = QLabel()
        self.window_anchor_summary_label.setWordWrap(True)
        window_anchor_layout.addWidget(self.window_anchor_summary_label)

        anchor_button_row = QHBoxLayout()
        self.save_window_anchor_btn = QPushButton("창 좌표 저장")
        self.save_window_anchor_btn.clicked.connect(self._handle_save_window_anchor_clicked)
        anchor_button_row.addWidget(self.save_window_anchor_btn)

        self.load_window_anchor_btn = QPushButton("창 좌표 불러오기")
        self.load_window_anchor_btn.clicked.connect(self._handle_load_window_anchor_clicked)
        anchor_button_row.addWidget(self.load_window_anchor_btn)
        anchor_button_row.addStretch(1)

        window_anchor_layout.addLayout(anchor_button_row)
        window_anchor_group.setLayout(window_anchor_layout)
        center_layout.addWidget(window_anchor_group)
        # 중앙 스택을 상단 정렬로 고정하고 남는 공간은 하단으로
        center_layout.addStretch(1)

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
        # 소량 데이터 기본 권장: yolov8s 우선 선택
        try:
            self.base_model_selector.setCurrentText('yolov8s')
        except Exception:
            pass
        train_options_layout.addWidget(self.base_model_selector)
        train_options_layout.addWidget(QLabel("Epochs:"))
        self.epoch_spinbox = QSpinBox()
        self.epoch_spinbox.setRange(10, 500)
        # 조기종료 도입에 맞춰 기본 에폭을 60으로 완화
        self.epoch_spinbox.setValue(60)
        self.epoch_spinbox.setSingleStep(10)
        train_options_layout.addWidget(self.epoch_spinbox)
        # 조기종료(patience) 옵션 추가: 검증 성능이 개선되지 않을 때 조기 종료
        train_options_layout.addWidget(QLabel("Patience:"))
        self.patience_spinbox = QSpinBox()
        self.patience_spinbox.setRange(5, 50)
        self.patience_spinbox.setValue(18)
        self.patience_spinbox.setSingleStep(1)
        self.patience_spinbox.setToolTip("검증 성능이 개선되지 않는 에폭 허용 수 (조기종료)")
        train_options_layout.addWidget(self.patience_spinbox)
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

        # [NEW] 펫 먹이 설정 (HP/MP/EXP 바로 아래)
        pet_feed_group = self._create_pet_feed_group()
        right_layout.addWidget(pet_feed_group)

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
        self._apply_ocr_config_to_ui()
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
        self._refresh_window_anchor_summary()

    def update_status_message(self, message):
        """상태바 메시지 업데이트를 위한 슬롯."""
        self.status_label.setText(message)

    def _suggest_window_anchor_name(self) -> str:
        anchors = list_saved_anchors()
        base = "기본 위치"
        if base not in anchors:
            return base
        for index in range(2, 99):
            candidate = f"위치 {index}"
            if candidate not in anchors:
                return candidate
        return f"위치 {int(time.time())}"

    def _refresh_window_anchor_summary(self) -> None:
        anchors = list_saved_anchors()
        count = len(anchors)
        summary = f"저장된 좌표: {count}개"
        last_used = last_used_anchor_name()
        if last_used and last_used in anchors:
            summary += f" (마지막 사용: {last_used})"
        self.window_anchor_summary_label.setText(summary)
        self.load_window_anchor_btn.setEnabled(count > 0)

    def _handle_save_window_anchor_clicked(self) -> None:
        geometry = get_maple_window_geometry()
        if not geometry:
            QMessageBox.warning(self, "창 검색 실패", "Mapleland 창을 찾을 수 없습니다.")
            return

        dialog = WindowAnchorSaveDialog(geometry, self._suggest_window_anchor_name(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        anchor_name = dialog.anchor_name()
        if not anchor_name:
            QMessageBox.warning(self, "저장 실패", "이름을 입력해주세요.")
            return

        if anchor_exists(anchor_name):
            confirm = QMessageBox.question(
                self,
                "덮어쓰기 확인",
                f"'{anchor_name}' 이름이 이미 존재합니다. 덮어쓸까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        save_window_anchor(anchor_name, geometry)
        set_last_used_anchor(anchor_name)
        QMessageBox.information(self, "저장 완료", f"'{anchor_name}' 좌표를 저장했습니다.")
        self._refresh_window_anchor_summary()

    def _handle_load_window_anchor_clicked(self) -> None:
        anchors = list_saved_anchors()
        if not anchors:
            QMessageBox.information(self, "불러오기", "저장된 창 좌표가 없습니다.")
            return

        dialog = WindowAnchorLoadDialog(anchors, last_used_anchor_name(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_name = dialog.selected_anchor_name()
        if not selected_name:
            return

        anchor = get_anchor(selected_name)
        if anchor is None:
            QMessageBox.warning(self, "불러오기 실패", "선택한 좌표 정보를 읽을 수 없습니다.")
            self._refresh_window_anchor_summary()
            return

        succeeded, message = restore_maple_window(anchor)
        if succeeded:
            set_last_used_anchor(selected_name)
            QMessageBox.information(self, "복원 완료", message)
        else:
            QMessageBox.warning(self, "복원 실패", message)
        self._refresh_window_anchor_summary()

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
            self.nameplate_hold_spin.setEnabled(enabled)
            if hasattr(self, 'nameplate_apply_facing_checkbox'):
                self.nameplate_apply_facing_checkbox.setEnabled(enabled)

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

            hold_value = float(config.get('track_max_hold_sec', 2.0) or 0.0)
            self.nameplate_hold_spin.blockSignals(True)
            self.nameplate_hold_spin.setValue(hold_value)
            self.nameplate_hold_spin.blockSignals(False)

            # 캐릭터 방향 적용 체크 상태
            apply_facing = bool(config.get('apply_facing', False))
            if hasattr(self, 'nameplate_apply_facing_checkbox'):
                self.nameplate_apply_facing_checkbox.blockSignals(True)
                self.nameplate_apply_facing_checkbox.setChecked(apply_facing)
                self.nameplate_apply_facing_checkbox.blockSignals(False)
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

    def _handle_nameplate_hold_changed(self, value: float) -> None:
        if self._nameplate_ui_updating:
            return
        value = float(value)
        updated = self.data_manager.update_monster_nameplate_config({'track_max_hold_sec': value})
        self.nameplate_config = updated
        self._apply_nameplate_config_to_ui()

    def _handle_nameplate_apply_facing_toggled(self, checked: bool) -> None:
        if self._nameplate_ui_updating:
            return
        updated = self.data_manager.update_monster_nameplate_config({'apply_facing': bool(checked)})
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

    # --- [NEW] 펫 먹이 설정 UI/로직 ---
    def _create_pet_feed_group(self) -> QGroupBox:
        group = QGroupBox("펫 먹이 설정")
        layout = QVBoxLayout(group)

        # 헤더: 제목 + 사용
        header = QHBoxLayout()
        header.addWidget(QLabel("펫 먹이"))
        self.pet_feed_enabled_checkbox = QCheckBox("사용")
        header.addWidget(self.pet_feed_enabled_checkbox)
        header.addStretch(1)
        layout.addLayout(header)

        # 조건: EXP 단독 OR 맵/사냥 실행 중
        cond_row = QHBoxLayout()
        cond_row.addWidget(QLabel("조건:"))
        self.pet_feed_cond_exp_chk = QCheckBox("EXP 단독 시")
        self.pet_feed_cond_map_chk = QCheckBox("맵/사냥 실행 중")
        cond_row.addWidget(self.pet_feed_cond_exp_chk)
        cond_row.addWidget(self.pet_feed_cond_map_chk)
        cond_row.addStretch(1)
        layout.addLayout(cond_row)

        # 주기 범위(분): 최소~최대 (랜덤)
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("주기(분):"))
        self.pet_feed_min_spin = QSpinBox()
        self.pet_feed_min_spin.setRange(1, 720)
        self.pet_feed_min_spin.setValue(30)
        interval_row.addWidget(self.pet_feed_min_spin)
        interval_row.addWidget(QLabel("~"))
        self.pet_feed_max_spin = QSpinBox()
        self.pet_feed_max_spin.setRange(1, 720)
        self.pet_feed_max_spin.setValue(30)
        interval_row.addWidget(self.pet_feed_max_spin)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)

        # 명령 프로필(자동제어 기타)
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel("명령 프로필:"))
        self.pet_feed_cmd_combo = QComboBox()
        cmd_row.addWidget(self.pet_feed_cmd_combo)
        cmd_row.addStretch(1)
        layout.addLayout(cmd_row)

        # 남은 시간 표시
        self.pet_feed_next_label = QLabel("다음 실행: -")
        self.pet_feed_next_label.setStyleSheet('color: #666666;')
        layout.addWidget(self.pet_feed_next_label)

        # 연결
        try:
            self.pet_feed_enabled_checkbox.toggled.connect(self._on_pet_feed_enabled_toggled)
            self.pet_feed_cond_exp_chk.toggled.connect(self._on_pet_feed_conditions_toggled)
            self.pet_feed_cond_map_chk.toggled.connect(self._on_pet_feed_conditions_toggled)
            self.pet_feed_min_spin.valueChanged.connect(self._on_pet_feed_min_changed)
            self.pet_feed_max_spin.valueChanged.connect(self._on_pet_feed_max_changed)
            self.pet_feed_cmd_combo.currentIndexChanged.connect(self._on_pet_feed_command_changed)
        except Exception:
            pass

        # 드롭다운 채우기 + UI 반영
        self._load_pet_feed_command_options()
        self._apply_pet_feed_config_to_ui()

        return group

    def _load_pet_feed_command_options(self) -> None:
        try:
            profiles = self.data_manager.list_command_profiles(('기타',))
        except Exception:
            profiles = {'기타': []}
        self.pet_feed_cmd_combo.blockSignals(True)
        self.pet_feed_cmd_combo.clear()
        for name in profiles.get('기타', []):
            self.pet_feed_cmd_combo.addItem(name, name)
        self.pet_feed_cmd_combo.blockSignals(False)

    def _apply_pet_feed_config_to_ui(self) -> None:
        cfg = getattr(self, '_pet_feed_cfg', None) or self.data_manager.get_pet_feed_config()
        self._pet_feed_cfg = cfg

        def _find_and_set(combo: QComboBox, value: str | None):
            if value is None:
                combo.setCurrentIndex(-1 if combo.count() > 0 else 0)
                return
            idx = combo.findData(value)
            if idx == -1:
                combo.addItem(value, value)
                idx = combo.findData(value)
            combo.setCurrentIndex(max(0, idx))

        try:
            self.pet_feed_enabled_checkbox.blockSignals(True)
            self.pet_feed_cond_exp_chk.blockSignals(True)
            self.pet_feed_cond_map_chk.blockSignals(True)
            self.pet_feed_min_spin.blockSignals(True)
            self.pet_feed_max_spin.blockSignals(True)
            self.pet_feed_cmd_combo.blockSignals(True)

            self.pet_feed_enabled_checkbox.setChecked(bool(cfg.get('enabled', False)))
            self.pet_feed_cond_exp_chk.setChecked(bool(cfg.get('when_exp_standalone', True)))
            self.pet_feed_cond_map_chk.setChecked(bool(cfg.get('when_map_or_hunt', True)))
            self.pet_feed_min_spin.setValue(int(cfg.get('min_minutes', 30) or 30))
            self.pet_feed_max_spin.setValue(int(cfg.get('max_minutes', 30) or 30))
            _find_and_set(self.pet_feed_cmd_combo, cfg.get('command_profile'))
        except Exception:
            pass
        finally:
            try:
                self.pet_feed_enabled_checkbox.blockSignals(False)
                self.pet_feed_cond_exp_chk.blockSignals(False)
                self.pet_feed_cond_map_chk.blockSignals(False)
                self.pet_feed_min_spin.blockSignals(False)
                self.pet_feed_max_spin.blockSignals(False)
                self.pet_feed_cmd_combo.blockSignals(False)
            except Exception:
                pass

        # 활성화 상태에 따라 컨트롤 활성화
        enabled = bool(cfg.get('enabled', False))
        for w in (
            self.pet_feed_cond_exp_chk,
            self.pet_feed_cond_map_chk,
            self.pet_feed_min_spin,
            self.pet_feed_max_spin,
            self.pet_feed_cmd_combo,
        ):
            try:
                w.setEnabled(enabled)
            except Exception:
                pass

        # 시작 시점(앱 기동/사용 on)에는 즉시 실행하지 않도록 다음 스케줄을 세팅
        if enabled and float(getattr(self, '_pet_feed_next_due_ts', 0.0) or 0.0) <= 0.0:
            self._schedule_next_pet_feed()
        elif not enabled:
            self._pet_feed_next_due_ts = 0.0
            try:
                self.pet_feed_next_label.setText("다음 실행: -")
            except Exception:
                pass

    def _random_pet_interval_sec(self) -> float:
        cfg = getattr(self, '_pet_feed_cfg', None) or self.data_manager.get_pet_feed_config()
        try:
            min_m = int(cfg.get('min_minutes', 30) or 30)
            max_m = int(cfg.get('max_minutes', 30) or 30)
        except Exception:
            min_m = max_m = 30
        if min_m < 1:
            min_m = 1
        if max_m < 1:
            max_m = 1
        if min_m > 720:
            min_m = 720
        if max_m > 720:
            max_m = 720
        if min_m > max_m:
            min_m, max_m = max_m, min_m
        minutes = random.uniform(float(min_m), float(max_m))
        return max(60.0, minutes * 60.0)

    def _format_due_text(self, due_ts: float) -> str:
        try:
            now = time.time()
            remain = max(0, int(round(due_ts - now)))
            m, s = divmod(remain, 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"다음 실행: {h}시간 {m}분 {s}초 후"
            if m > 0:
                return f"다음 실행: {m}분 {s}초 후"
            return f"다음 실행: {s}초 후"
        except Exception:
            return "다음 실행: -"

    def _schedule_next_pet_feed(self) -> None:
        try:
            self._pet_feed_next_due_ts = time.time() + float(self._random_pet_interval_sec())
            if hasattr(self, 'pet_feed_next_label') and self.pet_feed_next_label is not None:
                self.pet_feed_next_label.setText(self._format_due_text(self._pet_feed_next_due_ts))
        except Exception:
            self._pet_feed_next_due_ts = time.time() + 1800.0

    def _pet_feed_conditions_ok(self) -> bool:
        cfg = getattr(self, '_pet_feed_cfg', None) or self.data_manager.get_pet_feed_config()
        cond_exp = bool(cfg.get('when_exp_standalone', True))
        cond_run = bool(cfg.get('when_map_or_hunt', True))

        ok_exp = False
        try:
            ok_exp = cond_exp and bool(getattr(self._status_config.exp, 'standalone', False))
        except Exception:
            ok_exp = False
        ok_run = cond_run and (bool(getattr(self, '_hunt_active', False)) or bool(getattr(self, '_map_active', False)))
        return (ok_exp or ok_run)

    def _tick_pet_feed(self) -> None:
        try:
            cfg = getattr(self, '_pet_feed_cfg', None) or self.data_manager.get_pet_feed_config()
            self._pet_feed_cfg = cfg
            if not bool(cfg.get('enabled', False)):
                return
            # Maple 창 포그라운드 게이트
            if not is_maple_window_foreground():
                # 라벨만 갱신
                if float(getattr(self, '_pet_feed_next_due_ts', 0.0) or 0.0) > 0:
                    try:
                        self.pet_feed_next_label.setText(self._format_due_text(self._pet_feed_next_due_ts))
                    except Exception:
                        pass
                return
            # 조건 게이트(OR)
            if not self._pet_feed_conditions_ok():
                if float(getattr(self, '_pet_feed_next_due_ts', 0.0) or 0.0) > 0:
                    try:
                        self.pet_feed_next_label.setText(self._format_due_text(self._pet_feed_next_due_ts))
                    except Exception:
                        pass
                return
            # 스케줄 없으면 시작부터 대기 (즉시 실행 금지)
            if float(getattr(self, '_pet_feed_next_due_ts', 0.0) or 0.0) <= 0.0:
                self._schedule_next_pet_feed()
                return
            # 라벨 주기적 갱신
            try:
                self.pet_feed_next_label.setText(self._format_due_text(self._pet_feed_next_due_ts))
            except Exception:
                pass
            # 만기 처리
            now = time.time()
            if now < float(self._pet_feed_next_due_ts):
                return
            # 명령 유효성 검사
            command = cfg.get('command_profile')
            if not isinstance(command, str) or not command.strip():
                # 명령이 없으면 다음 스케줄만 세팅
                self._schedule_next_pet_feed()
                return
            # 실행
            reason = f"pet_feed:{int(cfg.get('min_minutes', 30) or 30)}~{int(cfg.get('max_minutes', 30) or 30)}m"
            self._emit_control_command(command.strip(), reason)
            # 다음 스케줄
            self._schedule_next_pet_feed()
        except Exception:
            pass

    # 이벤트 핸들러들
    def _on_pet_feed_enabled_toggled(self, checked: bool) -> None:
        self._pet_feed_cfg = self.data_manager.update_pet_feed_config({'enabled': bool(checked)})
        # 시작 즉시 실행 방지: on 시 새 스케줄 세팅, off 시 해제
        if bool(checked):
            self._schedule_next_pet_feed()
        else:
            self._pet_feed_next_due_ts = 0.0
            try:
                self.pet_feed_next_label.setText("다음 실행: -")
            except Exception:
                pass
        self._apply_pet_feed_config_to_ui()

    def _on_pet_feed_conditions_toggled(self, _=None) -> None:
        self._pet_feed_cfg = self.data_manager.update_pet_feed_config({
            'when_exp_standalone': bool(self.pet_feed_cond_exp_chk.isChecked()),
            'when_map_or_hunt': bool(self.pet_feed_cond_map_chk.isChecked()),
        })
        # 조건만 바뀔 때는 스케줄 유지
        self._apply_pet_feed_config_to_ui()

    def _on_pet_feed_min_changed(self, value: int) -> None:
        min_v = int(value)
        max_v = int(self.pet_feed_max_spin.value())
        if min_v > max_v:
            max_v = min_v
            self.pet_feed_max_spin.blockSignals(True)
            self.pet_feed_max_spin.setValue(max_v)
            self.pet_feed_max_spin.blockSignals(False)
        self._pet_feed_cfg = self.data_manager.update_pet_feed_config({'min_minutes': min_v, 'max_minutes': max_v})
        # 주기 변경 시 새 스케줄
        if bool(self._pet_feed_cfg.get('enabled', False)):
            self._schedule_next_pet_feed()
        self._apply_pet_feed_config_to_ui()

    def _on_pet_feed_max_changed(self, value: int) -> None:
        max_v = int(value)
        min_v = int(self.pet_feed_min_spin.value())
        if min_v > max_v:
            min_v = max_v
            self.pet_feed_min_spin.blockSignals(True)
            self.pet_feed_min_spin.setValue(min_v)
            self.pet_feed_min_spin.blockSignals(False)
        self._pet_feed_cfg = self.data_manager.update_pet_feed_config({'min_minutes': min_v, 'max_minutes': max_v})
        if bool(self._pet_feed_cfg.get('enabled', False)):
            self._schedule_next_pet_feed()
        self._apply_pet_feed_config_to_ui()

    def _on_pet_feed_command_changed(self, _=None) -> None:
        data = self.pet_feed_cmd_combo.currentData()
        cmd = data if isinstance(data, str) and data.strip() else None
        self._pet_feed_cfg = self.data_manager.update_pet_feed_config({'command_profile': cmd})
        self._apply_pet_feed_config_to_ui()

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
        # [NEW] MP 전용 단독사용 체크박스
        standalone_checkbox = None
        if resource == 'mp':
            standalone_checkbox = QCheckBox('단독사용')
            header_layout.addWidget(standalone_checkbox)
        # [NEW] HP 카드 전용: 저체력 텔레그램 알림 토글 + 설정 버튼
        telegram_checkbox = None
        telegram_settings_btn = None
        if resource == 'hp':
            telegram_checkbox = QCheckBox('텔레그램 알림')
            header_layout.addWidget(telegram_checkbox)
            telegram_settings_btn = QPushButton('설정')
            telegram_settings_btn.setToolTip('초긴급모드 임계값 및 기타 명령프로필 설정')
            telegram_settings_btn.setFixedWidth(48)
            header_layout.addWidget(telegram_settings_btn)
        header_layout.addStretch(1)
        vbox.addLayout(header_layout)

        roi_button_layout = QHBoxLayout()
        roi_button = QPushButton('탐지 범위 설정')
        roi_button.clicked.connect(lambda _, key=resource: self._select_status_roi(key))
        roi_button_layout.addWidget(roi_button)
        preview_button = QPushButton('인식 확인')
        preview_button.setToolTip(f'현재 {title} 탐지 범위를 캡처하여 분석합니다.')
        preview_button.clicked.connect(lambda _, key=resource: self._handle_status_preview(key))
        roi_button_layout.addWidget(preview_button)
        if resource == 'hp':
            emergency_btn = QPushButton('긴급모드')
            emergency_btn.setToolTip('HP 긴급 회복 모드 설정')
            emergency_btn.clicked.connect(self._open_hp_emergency_settings_dialog)
            roi_button_layout.addWidget(emergency_btn)
        roi_button_layout.addStretch(1)
        vbox.addLayout(roi_button_layout)

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
        # [변경] 100 초과 입력(절대 HP)도 허용
        input_field.setValidator(QIntValidator(1, 999999, input_field))
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
            self.hp_roi_button = roi_button
            self.hp_roi_label = roi_label
            self.hp_max_input = max_input
            self.hp_threshold_input = input_field
            self.hp_command_combo = combo
            self.hp_interval_input = interval_input
            self.hp_preview_button = preview_button
            self.hp_enabled_checkbox.toggled.connect(lambda checked: self._on_status_enabled_changed('hp', checked))
            self.hp_max_input.editingFinished.connect(lambda: self._on_status_max_changed('hp'))
            self.hp_threshold_input.editingFinished.connect(lambda: self._on_status_threshold_changed('hp'))
            self.hp_command_combo.currentIndexChanged.connect(lambda _: self._on_status_command_changed('hp'))
            self.hp_interval_input.editingFinished.connect(lambda: self._on_status_interval_changed('hp'))
            # [NEW]
            self.hp_lowhp_telegram_checkbox = telegram_checkbox
            if self.hp_lowhp_telegram_checkbox is not None:
                self.hp_lowhp_telegram_checkbox.toggled.connect(self._on_status_low_hp_telegram_changed)
            self.hp_lowhp_settings_btn = telegram_settings_btn
            if self.hp_lowhp_settings_btn is not None:
                self.hp_lowhp_settings_btn.clicked.connect(self._open_low_hp_settings_dialog)
        else:
            self.mp_enabled_checkbox = enabled_checkbox
            self.mp_standalone_checkbox = standalone_checkbox
            self.mp_roi_button = roi_button
            self.mp_roi_label = roi_label
            self.mp_max_input = max_input
            self.mp_threshold_input = input_field
            self.mp_command_combo = combo
            self.mp_interval_input = interval_input
            self.mp_preview_button = preview_button
            self.mp_enabled_checkbox.toggled.connect(lambda checked: self._on_status_enabled_changed('mp', checked))
            if self.mp_standalone_checkbox is not None:
                self.mp_standalone_checkbox.toggled.connect(self._on_mp_standalone_toggled)
            self.mp_max_input.editingFinished.connect(lambda: self._on_status_max_changed('mp'))
            self.mp_threshold_input.editingFinished.connect(lambda: self._on_status_threshold_changed('mp'))
            self.mp_command_combo.currentIndexChanged.connect(lambda _: self._on_status_command_changed('mp'))
            self.mp_interval_input.editingFinished.connect(lambda: self._on_status_interval_changed('mp'))

        return box

    def _open_hp_emergency_settings_dialog(self) -> None:
        cfg = getattr(self, '_status_config', None)
        if not cfg or not hasattr(cfg, 'hp'):
            QMessageBox.warning(self, '긴급모드', '상태 모니터 구성이 아직 초기화되지 않았습니다.')
            return
        hp_cfg = cfg.hp

        dialog = QDialog(self)
        dialog.setWindowTitle('HP 긴급모드 설정')
        form = QFormLayout(dialog)

        enabled_chk = QCheckBox('긴급모드 사용')
        enabled_chk.setChecked(bool(getattr(hp_cfg, 'emergency_enabled', False)))
        form.addRow(enabled_chk)

        n_spin = QSpinBox(dialog)
        n_spin.setRange(1, 10)
        n_spin.setValue(int(getattr(hp_cfg, 'emergency_trigger_failures', 3) or 3))
        form.addRow('발동조건 N회', n_spin)

        # [NEW] 긴급 발동 HP 임계값(%) - N회 실패 OR HP≤임계값 시 진입
        em_thr_input = QLineEdit(dialog)
        em_thr_input.setPlaceholderText('예: 30 (비워두면 미사용)')
        em_thr_input.setValidator(QIntValidator(1, 99, em_thr_input))
        try:
            current_em_thr = getattr(hp_cfg, 'emergency_trigger_hp_percent', None)
        except Exception:
            current_em_thr = None
        em_thr_input.setText('' if current_em_thr in (None, '') else str(int(current_em_thr)))
        form.addRow('HP 임계값(%)', em_thr_input)

        dur_spin = QDoubleSpinBox(dialog)
        dur_spin.setRange(1.0, 3600.0)
        dur_spin.setDecimals(1)
        dur_spin.setSingleStep(0.5)
        dur_spin.setValue(float(getattr(hp_cfg, 'emergency_max_duration_sec', 10.0) or 10.0))
        dur_spin.setSuffix(' s')
        form.addRow('최대 긴급 유지시간', dur_spin)

        tg_chk = QCheckBox('시간초과 시 텔레그램 전송')
        tg_chk.setChecked(bool(getattr(hp_cfg, 'emergency_timeout_telegram', False)))
        form.addRow(tg_chk)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        form.addRow(buttons)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        updates = {
            'hp': {
                'emergency_enabled': bool(enabled_chk.isChecked()),
                'emergency_trigger_failures': int(n_spin.value()),
                'emergency_max_duration_sec': float(dur_spin.value()),
                'emergency_timeout_telegram': bool(tg_chk.isChecked()),
            }
        }
        # 입력값(비어있으면 미사용)
        em_text = em_thr_input.text().strip()
        if em_text:
            try:
                val = int(em_text)
                if 1 <= val <= 99:
                    updates['hp']['emergency_trigger_hp_percent'] = val
                else:
                    updates['hp']['emergency_trigger_hp_percent'] = None
            except ValueError:
                updates['hp']['emergency_trigger_hp_percent'] = None
        else:
            updates['hp']['emergency_trigger_hp_percent'] = None
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _build_exp_status_card(self) -> QGroupBox:
        box = QGroupBox()
        vbox = QVBoxLayout()
        header_layout = QHBoxLayout()
        title_label = QLabel('EXP')
        title_label.setStyleSheet('font-weight: bold;')
        header_layout.addWidget(title_label)
        self.exp_enabled_checkbox = QCheckBox('사용')
        header_layout.addWidget(self.exp_enabled_checkbox)
        # [NEW] EXP 전용 단독사용 체크박스
        self.exp_standalone_checkbox = QCheckBox('단독사용')
        header_layout.addWidget(self.exp_standalone_checkbox)
        header_layout.addStretch(1)
        vbox.addLayout(header_layout)
        roi_button_layout = QHBoxLayout()
        self.exp_roi_button = QPushButton('탐지 범위 설정')
        self.exp_roi_button.clicked.connect(lambda: self._select_status_roi('exp'))
        roi_button_layout.addWidget(self.exp_roi_button)

        self.exp_preview_button = QPushButton('인식 확인')
        self.exp_preview_button.setToolTip('현재 EXP 탐지 범위에서 캡처한 화면과 OCR 결과를 확인합니다.')
        self.exp_preview_button.clicked.connect(self._handle_exp_preview)
        roi_button_layout.addWidget(self.exp_preview_button)
        roi_button_layout.addStretch(1)
        vbox.addLayout(roi_button_layout)

        self.exp_roi_label = QLabel('범위가 설정되지 않았습니다.')
        self.exp_roi_label.setWordWrap(True)
        vbox.addWidget(self.exp_roi_label)

        # [NEW] EXP 주기(정수) 입력
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel('탐지주기(초):'))
        self.exp_interval_input = QLineEdit()
        self.exp_interval_input.setPlaceholderText('예: 60')
        self.exp_interval_input.setValidator(QIntValidator(1, 3600, self.exp_interval_input))
        interval_layout.addWidget(self.exp_interval_input)
        vbox.addLayout(interval_layout)

        vbox.addStretch(1)
        box.setLayout(vbox)
        self.exp_enabled_checkbox.toggled.connect(lambda checked: self._on_status_enabled_changed('exp', checked))
        # [NEW] 핸들러 연결
        try:
            self.exp_interval_input.editingFinished.connect(lambda: self._on_status_interval_changed('exp'))
        except Exception:
            pass
        try:
            self.exp_standalone_checkbox.toggled.connect(self._on_exp_standalone_toggled)
        except Exception:
            pass
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
            # [NEW] EXP 주기(정수)
            if hasattr(self, 'exp_interval_input') and self.exp_interval_input is not None:
                try:
                    self._set_interval_value(self.exp_interval_input, float(int(round(self._status_config.exp.interval_sec))))
                except Exception:
                    self._set_interval_value(self.exp_interval_input, self._status_config.exp.interval_sec)

            self._set_checkbox_state(self.hp_enabled_checkbox, self._status_config.hp.enabled)
            self._set_checkbox_state(self.mp_enabled_checkbox, self._status_config.mp.enabled)
            # [NEW] MP 단독사용 UI 반영
            if hasattr(self, 'mp_standalone_checkbox') and self.mp_standalone_checkbox is not None:
                try:
                    self._set_checkbox_state(self.mp_standalone_checkbox, bool(getattr(self._status_config.mp, 'standalone', False)))
                except Exception:
                    self._set_checkbox_state(self.mp_standalone_checkbox, False)
            # [NEW] EXP 단독사용 UI 반영
            if hasattr(self, 'exp_standalone_checkbox') and self.exp_standalone_checkbox is not None:
                try:
                    self._set_checkbox_state(self.exp_standalone_checkbox, bool(getattr(self._status_config.exp, 'standalone', False)))
                except Exception:
                    self._set_checkbox_state(self.exp_standalone_checkbox, False)
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
                getattr(self, 'hp_preview_button', None),
                getattr(self, 'hp_max_input', None),
                getattr(self, 'hp_threshold_input', None),
                getattr(self, 'hp_command_combo', None),
                getattr(self, 'hp_interval_input', None),
            ]
        elif resource == 'mp':
            controls = [
                getattr(self, 'mp_roi_button', None),
                getattr(self, 'mp_preview_button', None),
                getattr(self, 'mp_max_input', None),
                getattr(self, 'mp_threshold_input', None),
                getattr(self, 'mp_command_combo', None),
                getattr(self, 'mp_interval_input', None),
                getattr(self, 'mp_standalone_checkbox', None),
            ]
        else:
            controls = [
                getattr(self, 'exp_roi_button', None),
                getattr(self, 'exp_preview_button', None),
                getattr(self, 'exp_interval_input', None),
                getattr(self, 'exp_standalone_checkbox', None),
            ]

        for control in controls:
            if control is not None:
                control.setEnabled(enabled)

    def _capture_status_frame(self, resource: str, title: str) -> tuple[Optional[np.ndarray], StatusRoi]:
        window_title = f'{title} 인식 확인'
        if not hasattr(self, '_status_config') or self._status_config is None:
            QMessageBox.warning(self, window_title, '상태 모니터 구성이 아직 초기화되지 않았습니다.')
            return None, StatusRoi()

        cfg = getattr(self._status_config, resource, None)
        roi = getattr(cfg, 'roi', StatusRoi()) if cfg else StatusRoi()
        if not roi.is_valid():
            QMessageBox.information(
                self,
                window_title,
                '탐지 범위가 설정되지 않아 확인할 수 없습니다. 먼저 ROI를 지정해주세요.',
            )
            return None, roi

        monitor_dict = roi.to_monitor_dict()
        manager = get_capture_manager()
        consumer_name = f"learning:{resource}_preview:{id(self)}:{int(time.time()*1000)}"
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
                QMessageBox.warning(self, window_title, f'화면 캡처에 실패했습니다.\n{exc}')
                return None, roi

            if raw.size == 0:
                QMessageBox.warning(self, window_title, '캡처 결과가 비어 있습니다. ROI 범위를 다시 확인해주세요.')
                return None, roi

            try:
                frame_bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
            except cv2.error as exc:  # pragma: no cover - OpenCV 내부 오류 대비
                QMessageBox.warning(self, window_title, f'이미지 변환 중 오류가 발생했습니다.\n{exc}')
                return None, roi

        return frame_bgr, roi

    def _prepare_bar_preview(self, title: str, image_bgr: np.ndarray) -> dict:
        result: dict = {
            'processed': None,
            'summary_lines': [],
        }

        if image_bgr is None or image_bgr.size == 0:
            result['summary_lines'].append('상태: 캡처 이미지가 비어 있습니다.')
            return result

        height, width = image_bgr.shape[:2]
        result['summary_lines'].append(f'이미지 크기: {width}×{height}px')
        percent = StatusMonitorThread._analyze_bar(image_bgr)
        if percent is None:
            result['summary_lines'].append('상태: 막대 비율을 계산하지 못했습니다.')
        else:
            result['summary_lines'].append('상태: 막대 비율 계산 성공')
            result['summary_lines'].append(f'추정 {title} 비율: {percent:.2f}%')

        return result

    def _handle_status_preview(self, resource: str) -> None:
        title = STATUS_RESOURCE_LABELS.get(resource, resource.upper())
        frame_bgr, roi = self._capture_status_frame(resource, title)
        if frame_bgr is None:
            return

        preview = self._prepare_bar_preview(title, frame_bgr)
        roi_text = self._format_status_roi(roi)
        dialog = StatusRecognitionPreviewDialog(
            self,
            f'{title} 인식 확인',
            f'탐지 범위: {roi_text}',
            frame_bgr,
            None,
            preview.get('summary_lines', []),
        )
        dialog.exec()

    def _handle_exp_preview(self) -> None:
        title = STATUS_RESOURCE_LABELS.get('exp', 'EXP')
        frame_bgr, roi = self._capture_status_frame('exp', title)
        if frame_bgr is None:
            return

        preview = self._prepare_exp_preview(frame_bgr)
        roi_text = self._format_status_roi(roi)
        dialog = StatusRecognitionPreviewDialog(
            self,
            f'{title} 인식 확인',
            f'탐지 범위: {roi_text}',
            frame_bgr,
            preview.get('processed'),
            preview.get('summary_lines', []),
            processed_title='전처리(Threshold)',
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

    # [NEW] 단독실행 체크박스 색상 토글 타이머 핸들러
    def _tick_standalone_ui(self) -> None:
        active_base = (not self._hunt_active) and (not self._map_active) and is_maple_window_foreground()
        # MP
        try:
            mp_on = bool(getattr(self._status_config.mp, 'standalone', False)) and active_base
            if hasattr(self, 'mp_standalone_checkbox') and self.mp_standalone_checkbox is not None:
                self.mp_standalone_checkbox.setStyleSheet('color: red;' if mp_on else '')
        except Exception:
            pass
        # EXP
        try:
            exp_on = bool(getattr(self._status_config.exp, 'standalone', False)) and active_base
            if hasattr(self, 'exp_standalone_checkbox') and self.exp_standalone_checkbox is not None:
                self.exp_standalone_checkbox.setStyleSheet('color: red;' if exp_on else '')
        except Exception:
            pass

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
                # [변경] 1 이상이면 저장 (100 초과는 절대 HP로 해석)
                if 1 <= val:
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
        if resource == 'hp':
            widget = self.hp_interval_input
        elif resource == 'mp':
            widget = self.mp_interval_input
        else:
            widget = getattr(self, 'exp_interval_input', None)
        text = widget.text().strip() if widget else ''
        if not text:
            self._apply_status_config_to_ui()
            return
        if resource == 'exp':
            try:
                ival = int(text)
                if ival <= 0:
                    raise ValueError
            except ValueError:
                self._apply_status_config_to_ui()
                return
            updates = {resource: {'interval_sec': int(ival)}}
        else:
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

    # [NEW] MP 단독사용 토글 핸들러
    def _on_mp_standalone_toggled(self, checked: bool) -> None:
        if self._status_ui_updating:
            return
        updates = {'mp': {'standalone': bool(checked)}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    # [NEW] EXP 단독사용 토글 핸들러
    def _on_exp_standalone_toggled(self, checked: bool) -> None:
        if self._status_ui_updating:
            return
        updates = {'exp': {'standalone': bool(checked)}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _on_status_enabled_changed(self, resource: str, checked: bool) -> None:
        if self._status_ui_updating:
            return
        updates = {resource: {'enabled': bool(checked)}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _on_status_low_hp_telegram_changed(self, checked: bool) -> None:
        if self._status_ui_updating:
            return
        updates = {'hp': {'low_hp_telegram_alert': bool(checked)}}
        self._status_config = self.data_manager.update_status_monitor_config(updates)
        self._apply_status_config_to_ui()

    def _open_low_hp_settings_dialog(self) -> None:
        cfg = getattr(self, '_status_config', None)
        if not cfg or not hasattr(cfg, 'hp'):
            QMessageBox.warning(self, '초긴급모드', '상태 모니터 구성이 아직 초기화되지 않았습니다.')
            return
        hp_cfg = cfg.hp
        dialog = QDialog(self)
        dialog.setWindowTitle('초긴급모드 설정')
        vbox = QVBoxLayout(dialog)
        # 임계값 입력
        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel('임계값(%)'))
        thr_input = QLineEdit(dialog)
        thr_input.setPlaceholderText('예: 3')
        thr_input.setValidator(QIntValidator(1, 99, thr_input))
        current_thr = getattr(hp_cfg, 'urgent_threshold', None)
        thr_input.setText('' if current_thr is None else str(int(current_thr)))
        thr_row.addWidget(thr_input)
        vbox.addLayout(thr_row)
        # 기타 명령프로필 선택
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(QLabel('기타 명령프로필'))
        cmd_combo = QComboBox(dialog)
        cmd_combo.addItem('(선택 없음)', '')
        try:
            profiles = self.data_manager.list_command_profiles(('기타',))
            for name in profiles.get('기타', []):
                cmd_combo.addItem(f"{name}", name)
        except Exception:
            pass
        current_cmd = getattr(hp_cfg, 'urgent_command_profile', None)
        if isinstance(current_cmd, str) and current_cmd:
            idx = cmd_combo.findData(current_cmd)
            if idx == -1:
                cmd_combo.addItem(current_cmd, current_cmd)
                idx = cmd_combo.findData(current_cmd)
            cmd_combo.setCurrentIndex(max(0, idx))
        cmd_row.addWidget(cmd_combo)
        vbox.addLayout(cmd_row)
        # 버튼박스
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        vbox.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = thr_input.text().strip()
            if text:
                try:
                    val = int(text)
                    if not (1 <= val <= 99):
                        raise ValueError
                except ValueError:
                    QMessageBox.warning(self, '초긴급모드', '임계값은 1~99 사이의 정수여야 합니다.')
                    return
                thr_value = val
            else:
                thr_value = None
            cmd_value = cmd_combo.currentData()
            if not isinstance(cmd_value, str) or not cmd_value.strip():
                cmd_value = None
            updates = {'hp': {'urgent_threshold': thr_value, 'urgent_command_profile': cmd_value}}
            self._status_config = self.data_manager.update_status_monitor_config(updates)
            self._apply_status_config_to_ui()

    def _handle_status_config_changed(self, config: StatusMonitorConfig) -> None:
        self._status_config = config
        self._load_status_command_options()
        self._apply_status_config_to_ui()
        # [NEW] 즉시 색상 갱신 시도
        try:
            self._tick_standalone_ui()
        except Exception:
            pass

    # [NEW] 자동 제어 명령 전달 헬퍼
    def _emit_control_command(self, command: str, reason: object = None) -> None:
        try:
            if hasattr(self, 'control_command_issued') and callable(getattr(self, 'control_command_issued').emit):
                self.control_command_issued.emit(command, reason)
        except Exception:
            pass

    # [NEW] 상태 모니터 연결 및 MP 단독 동작 처리
    def attach_status_monitor(self, thread: StatusMonitorThread) -> None:
        try:
            self._status_thread = thread
            thread.status_captured.connect(self._handle_status_snapshot_for_mp_standalone)
        except Exception:
            pass

    def update_tabs_activity(self, hunt_active: bool, map_active: bool) -> None:
        self._hunt_active = bool(hunt_active)
        self._map_active = bool(map_active)
        try:
            self._tick_standalone_ui()
        except Exception:
            pass

    def _handle_status_snapshot_for_mp_standalone(self, payload: dict) -> None:
        try:
            cfg = getattr(self, '_status_config', None)
            if not cfg or not hasattr(cfg, 'mp'):
                return
            mp_cfg = cfg.mp
            # 필수 조건: 사용 + 단독사용 켜짐 + 명령/임계/주기 유효
            if not getattr(mp_cfg, 'enabled', True):
                return
            if not bool(getattr(mp_cfg, 'standalone', False)):
                return
            # [NEW] Mapleland 최상위가 아니면 동작하지 않음
            if not is_maple_window_foreground():
                return
            # 사냥/맵이 실행 중이면 단독 동작은 보류
            if self._hunt_active or self._map_active:
                return
            threshold = getattr(mp_cfg, 'recovery_threshold', None)
            command = (getattr(mp_cfg, 'command_profile', None) or '').strip()
            if not isinstance(threshold, int) or not command:
                return
            mp_info = payload.get('mp') if isinstance(payload, dict) else None
            if not isinstance(mp_info, dict) or not isinstance(mp_info.get('percentage'), (int, float)):
                return
            percent = float(mp_info.get('percentage'))
            if percent > float(threshold):
                return
            now = float(payload.get('timestamp', time.time())) if isinstance(payload.get('timestamp'), (int, float)) else time.time()
            interval = max(0.1, float(getattr(mp_cfg, 'interval_sec', 1.0) or 1.0))
            if (now - float(getattr(self, '_mp_standalone_last_ts', 0.0))) < interval:
                return
            self._mp_standalone_last_ts = now
            # 원인에 현재 퍼센트를 포함해 전달
            percent_text = max(0, min(100, int(round(percent))))
            reason = f'status:mp:{percent_text}'
            self._emit_control_command(command, reason)
        except Exception:
            pass

    # ----- [NEW] 이름표 OCR 보조 메서드들 -----
    def _apply_ocr_config_to_ui(self) -> None:
        try:
            cfg = self.nameplate_config if isinstance(self.nameplate_config, dict) else {}
            ocr_cfg = cfg.get('ocr', {}) if isinstance(cfg.get('ocr'), dict) else {}
            roi = StatusRoi.from_dict(ocr_cfg.get('roi'))
            # 간단 요약만 표기
            if hasattr(self, 'ocr_roi_summary_label'):
                if roi.is_valid():
                    self.ocr_roi_summary_label.setText(f"({roi.left}, {roi.top})  {roi.width}×{roi.height}px")
                else:
                    self.ocr_roi_summary_label.setText('위치/크기 미설정')
            iv = ocr_cfg.get('interval_sec', 5.0)
            try:
                val = float(iv)
            except (TypeError, ValueError):
                val = 5.0
            val = max(0.2, min(600.0, val))
            if hasattr(self, 'ocr_interval_spin'):
                self.ocr_interval_spin.blockSignals(True)
                self.ocr_interval_spin.setValue(val)
                self.ocr_interval_spin.blockSignals(False)
            # GPU 토글 동기화 및 엔진 재초기화(필요 시)
            use_gpu = bool(ocr_cfg.get('use_gpu', False))
            if hasattr(self, 'ocr_gpu_checkbox') and self.ocr_gpu_checkbox is not None:
                self.ocr_gpu_checkbox.blockSignals(True)
                self.ocr_gpu_checkbox.setChecked(use_gpu)
                self.ocr_gpu_checkbox.blockSignals(False)
            # 신뢰도/최소크기/키워드
            if hasattr(self, 'ocr_conf_spin'):
                try:
                    ct = ocr_cfg.get('conf_threshold', 0)
                    # 0~1 스케일 입력을 %로 변환
                    if isinstance(ct, float) and ct <= 1.0001:
                        ct = int(round(ct * 100))
                    self.ocr_conf_spin.blockSignals(True)
                    self.ocr_conf_spin.setValue(int(ct or 0))
                    self.ocr_conf_spin.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_min_height_spin'):
                try:
                    mh = int(ocr_cfg.get('min_height_px') or 0)
                    self.ocr_min_height_spin.blockSignals(True)
                    self.ocr_min_height_spin.setValue(max(0, mh))
                    self.ocr_min_height_spin.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_max_height_spin'):
                try:
                    xh = int(ocr_cfg.get('max_height_px') or 0)
                    self.ocr_max_height_spin.blockSignals(True)
                    self.ocr_max_height_spin.setValue(max(0, xh))
                    self.ocr_max_height_spin.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_min_width_spin'):
                try:
                    mw = int(ocr_cfg.get('min_width_px') or 0)
                    self.ocr_min_width_spin.blockSignals(True)
                    self.ocr_min_width_spin.setValue(max(0, mw))
                    self.ocr_min_width_spin.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_max_width_spin'):
                try:
                    xw = int(ocr_cfg.get('max_width_px') or 0)
                    self.ocr_max_width_spin.blockSignals(True)
                    self.ocr_max_width_spin.setValue(max(0, xw))
                    self.ocr_max_width_spin.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_screenshot_checkbox'):
                try:
                    self.ocr_screenshot_checkbox.blockSignals(True)
                    self.ocr_screenshot_checkbox.setChecked(bool(ocr_cfg.get('save_screenshots', False)))
                    self.ocr_screenshot_checkbox.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_keyword_alert_checkbox'):
                try:
                    self.ocr_keyword_alert_checkbox.blockSignals(True)
                    self.ocr_keyword_alert_checkbox.setChecked(bool(ocr_cfg.get('telegram_enabled', False)))
                    self.ocr_keyword_alert_checkbox.blockSignals(False)
                except Exception:
                    pass
            if hasattr(self, 'ocr_keywords_edit'):
                try:
                    kws = ocr_cfg.get('keywords', [])
                    if not isinstance(kws, list):
                        kws = []
                    text = ",".join([str(x) for x in kws if isinstance(x, str)])
                    self.ocr_keywords_edit.blockSignals(True)
                    self.ocr_keywords_edit.setText(text)
                    self.ocr_keywords_edit.blockSignals(False)
                except Exception:
                    pass
            try:
                cur_env = os.getenv('PADDLE_OCR_USE_GPU', '0').strip().lower()
                cur_flag = cur_env in ('1', 'true', 'yes', 'on')
            except Exception:
                cur_flag = False
            if cur_flag != use_gpu:
                set_paddle_use_gpu(use_gpu)
            if hasattr(self, 'ocr_engine_label'):
                self.ocr_engine_label.setText(get_ocr_engine_label())
                err = get_ocr_last_error()
                self.ocr_engine_label.setToolTip(err or '')
        except Exception:
            pass

    def _handle_ocr_roi_select(self) -> None:
        try:
            selector = StatusRegionSelector(self)
        except RuntimeError as exc:
            QMessageBox.warning(self, '오류', str(exc))
            return
        if selector.exec():
            rect = selector.get_roi()
            updates = {
                'ocr': {
                    'roi': {
                        'left': rect.left(),
                        'top': rect.top(),
                        'width': rect.width(),
                        'height': rect.height(),
                    }
                }
            }
            self.nameplate_config = self.data_manager.update_monster_nameplate_config(updates)
            self._apply_ocr_config_to_ui()

    def _handle_ocr_interval_changed(self, value: float) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        try:
            val = float(value)
        except (TypeError, ValueError):
            return
        val = max(0.2, min(600.0, val))
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'interval_sec': val}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_conf_changed(self, value: int) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        v = max(0, min(100, v))
        # 0은 필터 미적용으로 저장(0 그대로 저장)
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'conf_threshold': v}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_min_height_changed(self, value: int) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        v = max(0, min(1000, v))
        # 0은 필터 미적용으로 처리
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'min_height_px': v}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_max_height_changed(self, value: int) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        v = max(0, min(5000, v))
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'max_height_px': v}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_min_width_changed(self, value: int) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        v = max(0, min(5000, v))
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'min_width_px': v}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_max_width_changed(self, value: int) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        try:
            v = int(value)
        except (TypeError, ValueError):
            return
        v = max(0, min(5000, v))
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'max_width_px': v}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_save_screenshot_toggled(self, checked: bool) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'save_screenshots': bool(checked)}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_keyword_alert_toggled(self, checked: bool) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'telegram_enabled': bool(checked)}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_keywords_changed(self) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        text = (self.ocr_keywords_edit.text() if hasattr(self, 'ocr_keywords_edit') else '').strip()
        if text:
            keywords = [s.strip() for s in text.split(',') if s.strip()]
        else:
            keywords = []
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'keywords': keywords}})
        self._apply_ocr_config_to_ui()

    def _handle_ocr_gpu_toggled(self, checked: bool) -> None:
        if getattr(self, '_nameplate_ui_updating', False):
            return
        use_gpu = bool(checked)
        # 설정 저장
        self.nameplate_config = self.data_manager.update_monster_nameplate_config({'ocr': {'use_gpu': use_gpu}})
        # 엔진 재설정 및 라벨 갱신
        try:
            set_paddle_use_gpu(use_gpu)
        except Exception:
            pass
        if hasattr(self, 'ocr_engine_label'):
            self.ocr_engine_label.setText(get_ocr_engine_label())
            err = get_ocr_last_error()
            self.ocr_engine_label.setToolTip(err or '')

    def _handle_ocr_standalone_toggled(self, checked: bool) -> None:
        # 메인 윈도우에 단독 실행 상태 전달
        try:
            main_window = self.window()
            if main_window and hasattr(main_window, 'api_set_ocr_standalone'):
                main_window.api_set_ocr_standalone(bool(checked))
        except Exception:
            pass
        if checked:
            # 자동으로 탐지 보고 창 열기
            try:
                self._open_ocr_live_report()
            except Exception:
                pass

    def _capture_by_monitor(self, monitor: dict, window_title: str) -> Optional[np.ndarray]:
        manager = get_capture_manager()
        consumer_name = f"learning:ocr_preview:{id(self)}:{int(time.time()*1000)}"
        frame_bgr: Optional[np.ndarray] = None
        try:
            manager.register_region(consumer_name, monitor)
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
                    raw = np.array(sct.grab(monitor))
            except Exception as exc:
                QMessageBox.warning(self, window_title, f'화면 캡처에 실패했습니다.\n{exc}')
                return None
            if raw.size == 0:
                QMessageBox.warning(self, window_title, '캡처 결과가 비어 있습니다. ROI 범위를 다시 확인해주세요.')
                return None
            try:
                frame_bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
            except cv2.error as exc:
                QMessageBox.warning(self, window_title, f'이미지 변환 중 오류가 발생했습니다.\n{exc}')
                return None
        return frame_bgr

    def _handle_ocr_test(self) -> None:
        cfg = self.nameplate_config if isinstance(self.nameplate_config, dict) else {}
        ocr_cfg = cfg.get('ocr', {}) if isinstance(cfg.get('ocr'), dict) else {}
        roi = StatusRoi.from_dict(ocr_cfg.get('roi'))
        if not roi.is_valid():
            QMessageBox.information(self, 'OCR 인식 확인', '탐지 범위가 설정되지 않았습니다. 먼저 ROI를 지정해주세요.')
            return
        monitor = roi.to_monitor_dict()
        frame_bgr = self._capture_by_monitor(monitor, 'OCR 인식 확인')
        if frame_bgr is None:
            return
        # 필터값 반영
        conf_threshold = ocr_cfg.get('conf_threshold', 0) or 0
        min_height_px = ocr_cfg.get('min_height_px', 0) or 0
        max_height_px = ocr_cfg.get('max_height_px', 0) or 0
        min_width_px = ocr_cfg.get('min_width_px', 0) or 0
        max_width_px = ocr_cfg.get('max_width_px', 0) or 0
        # 0은 비적용으로 전달(None 처리는 함수 내부에서 함)
        ct = None if int(conf_threshold) <= 0 else int(conf_threshold)
        mh = None if int(min_height_px) <= 0 else int(min_height_px)
        xh = None if int(max_height_px) <= 0 else int(max_height_px)
        mw = None if int(min_width_px) <= 0 else int(min_width_px)
        xw = None if int(max_width_px) <= 0 else int(max_width_px)
        words = ocr_korean_words(
            frame_bgr,
            psm=11,
            conf_threshold=ct,
            min_height_px=mh,
            max_height_px=xh,
            min_width_px=mw,
            max_width_px=xw,
            preprocess='auto',
        )
        annotated = draw_word_boxes(frame_bgr, words)
        lines: list[str] = []
        engine = get_ocr_engine_label()
        lines.append(f'엔진: {engine}')
        total = len(words)
        lines.append(f'감지 단어 수: {total}개')
        for i, w in enumerate(words[:30]):
            try:
                lines.append(f'[{i+1}] : {w.text} (신뢰도: {int(round(w.conf))}% , W: {int(w.width)} px, H: {int(w.height)} px)')
            except Exception:
                pass
        if len(words) > 30:
            lines.append(f'... 외 {len(words)-30}개 생략')
        # 키워드 검출 수 (A안, 부분일치)
        show_kw = bool(ocr_cfg.get('telegram_enabled', False))
        keywords = ocr_cfg.get('keywords', []) if isinstance(ocr_cfg.get('keywords'), list) else []
        if show_kw and keywords:
            kw_count = 0
            for w in words:
                text = (w.text or '').strip()
                if any((isinstance(kw, str) and kw.strip() and kw.strip() in text) for kw in keywords):
                    kw_count += 1
            lines.append(f'키워드 검출 수: {kw_count}개')
        roi_text = self._format_status_roi(roi)
        # 요구사항: 원본 크기의 OCR 결과 이미지만 표시(원본은 숨김)
        dialog = StatusRecognitionPreviewDialog(
            self,
            'OCR 인식 확인',
            f'탐지 범위: {roi_text}',
            None,
            annotated,
            lines,
            processed_title='OCR 결과',
            scale_images=False,
        )
        # 비모달로 표시, 참조 보유
        self._last_ocr_preview_dialog = dialog
        dialog.show()

    # ---- OCR 실시간 보고 ----
    def attach_ocr_watch(self, thread) -> None:
        self._ocr_thread = thread
        try:
            thread.ocr_detected.connect(self._on_ocr_detected_update)
        except Exception:
            pass

    def detach_ocr_watch(self) -> None:
        th = getattr(self, '_ocr_thread', None)
        if th is not None:
            try:
                th.ocr_detected.disconnect(self._on_ocr_detected_update)
            except Exception:
                pass
        self._ocr_thread = None

    def _get_ocr_monitor(self) -> Optional[dict]:
        try:
            cfg = self.nameplate_config if isinstance(self.nameplate_config, dict) else {}
            ocr_cfg = cfg.get('ocr', {}) if isinstance(cfg.get('ocr'), dict) else {}
            roi = StatusRoi.from_dict(ocr_cfg.get('roi'))
            if not roi.is_valid():
                return None
            return roi.to_monitor_dict()
        except Exception:
            return None

    def _open_ocr_live_report(self) -> None:
        if getattr(self, '_ocr_live_dialog', None) is None:
            self._ocr_live_dialog = OcrLiveReportDialog(self)
        self._ocr_live_dialog.show()
        self._ocr_live_dialog.raise_()

    def _on_ocr_detected_update(self, payload_list: list) -> None:
        # payload_list: [{ 'roi_index': int, 'timestamp': float, 'words': [ {text,conf,left,top,width,height}, ... ] }]
        if not isinstance(payload_list, list) or not payload_list:
            return
        item = payload_list[0]
        words = item.get('words', []) if isinstance(item, dict) else []
        ts = float(item.get('timestamp', 0.0)) if isinstance(item, dict) else 0.0
        if not hasattr(self, '_ocr_live_dialog') or self._ocr_live_dialog is None:
            return
        monitor = self._get_ocr_monitor()
        # 키워드 옵션
        cfg = self.nameplate_config if isinstance(self.nameplate_config, dict) else {}
        ocr_cfg = cfg.get('ocr', {}) if isinstance(cfg.get('ocr'), dict) else {}
        show_keywords = bool(ocr_cfg.get('telegram_enabled', False))
        keywords = ocr_cfg.get('keywords', []) if isinstance(ocr_cfg.get('keywords'), list) else []
        if monitor is None:
            # ROI 미설정 시 텍스트만 갱신
            self._ocr_live_dialog.update_content(annotated_bgr=None, words=words, ts=ts, keywords=keywords, show_keywords=show_keywords)
            return
        # 화면 캡처 후 바운딩 박스 그리기
        frame_bgr = self._capture_by_monitor(monitor, 'OCR 탐지 보고')
        if frame_bgr is None:
            self._ocr_live_dialog.update_content(annotated_bgr=None, words=words, ts=ts, keywords=keywords, show_keywords=show_keywords)
            return
        try:
            # words를 OCRWord 형태로 변환 없이 draw_word_boxes에 맞춰 재구성
            annotated = frame_bgr.copy()
            for w in words:
                try:
                    left = int(w.get('left', 0)); top = int(w.get('top', 0))
                    width = int(w.get('width', 0)); height = int(w.get('height', 0))
                    conf = float(w.get('conf', 0.0))
                    text = str(w.get('text', ''))
                    # 간단 사각형과 라벨 그리기 (draw_word_boxes와 유사)
                    pt1 = (left, top)
                    pt2 = (left + max(1, width), top + max(1, height))
                    cv2.rectangle(annotated, pt1, pt2, (0, 255, 0), 1)
                    label = f"W={width} H={height} C={int(round(conf))}%"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                    bg1 = (pt1[0], max(0, pt1[1] - th - 4))
                    bg2 = (pt1[0] + tw + 6, pt1[1])
                    cv2.rectangle(annotated, bg1, bg2, (0, 0, 0), -1)
                    cv2.putText(annotated, label, (pt1[0] + 3, pt1[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
                except Exception:
                    continue
        except Exception:
            annotated = frame_bgr
        self._ocr_live_dialog.update_content(annotated_bgr=annotated, words=words, ts=ts, keywords=keywords, show_keywords=show_keywords)

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

            # [NEW] 공격 금지 설정 저장
            try:
                if hasattr(dialog, 'attack_forbidden_checkbox') and hasattr(self, 'data_manager') and self.data_manager:
                    forbidden_state = bool(dialog.attack_forbidden_checkbox.isChecked())
                    self.data_manager.set_monster_attack_forbidden(class_name, forbidden_state)
                    if hasattr(self, 'log_viewer'):
                        msg = (
                            f"'{class_name}' 공격 금지 설정을 활성화했습니다."
                            if forbidden_state
                            else f"'{class_name}' 공격 금지 설정을 비활성화했습니다."
                        )
                        self.log_viewer.append(msg)
            except Exception:
                pass

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

    def _thumbnail_disk_prefix(self, image_path):
        return hashlib.sha1(image_path.encode('utf-8', 'ignore')).hexdigest()

    def _thumbnail_disk_key(self, image_path, size_tuple, file_mtime):
        prefix = self._thumbnail_disk_prefix(image_path)
        mtime_tag = str(int(file_mtime * 1000))
        size_tag = f"{size_tuple[0]}x{size_tuple[1]}"
        return f"{prefix}_{mtime_tag}_{size_tag}"

    def _thumbnail_disk_path(self, cache_key):
        return os.path.join(self._thumbnail_cache_dir, f"{cache_key}.png")

    def _load_thumbnail_from_disk(self, cache_key):
        cache_path = self._thumbnail_disk_path(cache_key)
        if not os.path.exists(cache_path):
            return None
        pixmap = QPixmap(cache_path)
        if pixmap.isNull():
            try:
                os.remove(cache_path)
            except OSError:
                pass
            return None
        return QIcon(pixmap)

    def _save_thumbnail_to_disk(self, cache_key, pixmap):
        cache_path = self._thumbnail_disk_path(cache_key)
        try:
            pixmap.save(cache_path, 'PNG')
            self._trim_thumbnail_disk_cache()
        except Exception:
            try:
                if os.path.exists(cache_path):
                    os.remove(cache_path)
            except OSError:
                pass

    def _trim_thumbnail_disk_cache(self):
        try:
            entries = glob.glob(os.path.join(self._thumbnail_cache_dir, '*.png'))
        except Exception:
            return
        if len(entries) <= self._thumbnail_disk_limit:
            return
        def mtime_key(path):
            try:
                return os.path.getmtime(path)
            except OSError:
                return float('inf')
        entries.sort(key=mtime_key)
        excess = len(entries) - self._thumbnail_disk_limit
        for path in entries[:excess]:
            try:
                os.remove(path)
            except OSError:
                pass

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
            cache_entry = None

        disk_key = None
        if file_mtime is not None:
            disk_key = self._thumbnail_disk_key(image_path, size_tuple, file_mtime)
            disk_icon = self._load_thumbnail_from_disk(disk_key)
            if disk_icon is not None:
                self._thumbnail_cache[image_path] = (file_mtime, size_tuple, disk_icon)
                self._thumbnail_cache.move_to_end(image_path)
                while len(self._thumbnail_cache) > self._thumbnail_cache_limit:
                    self._thumbnail_cache.popitem(last=False)
                return disk_icon

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
            if disk_key is not None and placeholder is None:
                self._save_thumbnail_to_disk(disk_key, pixmap)

        return icon

    def _invalidate_thumbnail_cache(self, image_path):
        """지정한 이미지 경로에 대한 캐시를 제거합니다."""
        self._thumbnail_cache.pop(image_path, None)
        prefix = self._thumbnail_disk_prefix(image_path)
        pattern = os.path.join(self._thumbnail_cache_dir, f"{prefix}_*.png")
        for cached_path in glob.glob(pattern):
            try:
                os.remove(cached_path)
            except OSError:
                pass

    def _clear_all_thumbnail_cache(self):
        self._thumbnail_cache.clear()
        pattern = os.path.join(self._thumbnail_cache_dir, '*.png')
        for cached_path in glob.glob(pattern):
            try:
                os.remove(cached_path)
            except OSError:
                pass

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
                self._clear_all_thumbnail_cache()
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
                self._clear_all_thumbnail_cache()
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
        # [NEW] 배치 시작 시점의 초기 클래스 보존
        self._batch_initial_class_name = initial_class_name

        # 캡처 시에는 메인 윈도우를 숨길 필요가 없으므로 hide/show 로직 제거
        try:
            QApplication.processEvents() # UI 업데이트
            QThread.msleep(250)

            target_windows = gw.getWindowsWithTitle('Mapleland')
            if not target_windows:
                QMessageBox.warning(self, '오류', '메이플스토리 게임 창을 찾을 수 없습니다.')
                return

            target_window = target_windows[0]
            if target_window.isMinimized: target_window.restore(); QThread.msleep(500)
            self.update_status_message(f"게임 창 활성화: '{target_window.title}'")

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
                    total = len(selected_pixmaps)
                    for idx, pixmap in enumerate(selected_pixmaps, start=1):
                        self.open_editor_mode_dialog(pixmap, initial_class_name=initial_class_name, seq_index=idx, seq_total=total)
        except Exception as e:
            QMessageBox.critical(self, "캡처 오류", str(e))
        finally:
            self.update_status_message("준비")

    def open_editor_mode_dialog(self, pixmap, image_path=None, initial_polygons=None, initial_class_name=None, *, seq_index: int | None = None, seq_total: int | None = None):
        dialog = EditModeDialog(pixmap, self.sam_predictor is not None, self)
        mode_result = dialog.exec()
        if mode_result == EditModeDialog.CANCEL:
            return

        # [NEW] 초기 클래스 결정: 배치 시작 클래스를 우선, 없으면 최근 저장 클래스 사용
        effective_initial_class = initial_class_name
        if not effective_initial_class:
            effective_initial_class = self._last_used_editor_class
        # 체크되지 않은 클래스는 무시
        if effective_initial_class and getattr(self, '_checked_class_names', None):
            if effective_initial_class not in self._checked_class_names:
                effective_initial_class = None

        editor_dialog = AnnotationEditorDialog(
            pixmap,
            self,
            self.sam_predictor,
            initial_polygons=initial_polygons,
            initial_class_name=effective_initial_class,
            initial_mode=mode_result,
            seq_index=seq_index,
            seq_total=seq_total,
        )

        editor_result = editor_dialog.exec()

        if editor_result == QDialog.DialogCode.Rejected:
            return

        # v1.3: 편집기에서 반환된 결과에 따라 분기 처리
        # 시나리오 1: 일반 저장
        if editor_result == QDialog.DialogCode.Accepted:
            previously_selected_class = editor_dialog.result_class_name() or initial_class_name
            # [NEW] 최근 저장 클래스 업데이트
            self._last_used_editor_class = previously_selected_class

            self.populate_class_list() # 새 클래스가 추가되었을 수 있으므로 목록 갱신

            if previously_selected_class:
                self.select_class_item_by_name(previously_selected_class)

            polygons_data = editor_dialog.result_polygons()
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
        elif editor_result in {PolygonAnnotationEditor.DistractorSaved, SAMAnnotationEditor.DistractorSaved}:
            polygons_data = editor_dialog.result_polygons()
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

        total = len(image_paths_to_edit)
        for i, image_path in enumerate(image_paths_to_edit, start=1):
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
            self.open_editor_mode_dialog(
                QPixmap.fromImage(q_image),
                image_path=image_path,
                initial_polygons=initial_polygons,
                initial_class_name=initial_class_name,
                seq_index=i if total > 1 else None,
                seq_total=total if total > 1 else None,
            )

    def start_training(self):
        if len(self.data_manager.get_class_list()) == 0:
            QMessageBox.warning(self, "오류", "훈련할 클래스가 하나 이상 있어야 합니다.")
            return

        self.log_viewer.clear()
        yaml_path = self.data_manager.create_yaml_file()
        self.log_viewer.append(f"데이터셋 설정 파일 생성 완료: '{yaml_path}'")
        epochs = self.epoch_spinbox.value()
        base_model = self.base_model_selector.currentText()
        patience = self.patience_spinbox.value()

        # v1.5: 체크된 클래스만 학습할지 여부 판단 및 로깅
        all_classes = self.data_manager.get_class_list()
        try:
            selected_indices = self.get_checked_class_indices() or []
        except Exception:
            selected_indices = []

        use_selected_only = False
        if selected_indices and len(selected_indices) < len(all_classes):
            selected_names = [all_classes[i] for i in selected_indices]
            preview = ", ".join(selected_names[:5]) + (" …" if len(selected_names) > 5 else "")
            reply = QMessageBox.question(
                self,
                "선택 클래스 학습",
                f"체크된 클래스 {len(selected_indices)}개만 학습할까요?\n예시: {preview}",
            )
            use_selected_only = reply == QMessageBox.StandardButton.Yes
            if use_selected_only:
                self.log_viewer.append(
                    f"선택된 {len(selected_indices)}개 클래스만 학습합니다: {', '.join(selected_names)}"
                )
            else:
                self.log_viewer.append("전체 클래스로 학습합니다.")
        else:
            self.log_viewer.append("체크된 클래스가 없거나 전체가 선택되어 있어 전체 클래스로 학습합니다.")

        self.train_btn.setEnabled(False)
        
        # (v1.2) TrainingThread에 training_runs 경로 전달
        training_runs_path = os.path.join(self.data_manager.workspace_root, 'training_runs')
        self.training_thread = TrainingThread(
            yaml_path,
            epochs,
            base_model,
            training_runs_path,
            selected_class_indices=selected_indices if use_selected_only else None,
            patience=patience,
        )
        
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
