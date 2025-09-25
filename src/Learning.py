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
from collections import OrderedDict

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QLabel, QDialog, QMessageBox, QFileDialog,
    QListWidgetItem, QInputDialog, QTextEdit, QDialogButtonBox, QCheckBox,
    QComboBox, QDoubleSpinBox, QGroupBox, QScrollArea, QSpinBox,
    QProgressBar, QStatusBar, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QLineEdit
)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QPainter, QPen, QColor, QBrush, QCursor, QPolygon, QDropEvent
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QRect, QPoint, QObject, QMimeData

# AI 어시스트 기능(SAM)과 훈련(YOLO)에 필요한 라이브러리를 import 합니다.
# 만약 라이브러리가 설치되지 않았더라도 프로그램이 실행은 되도록 try-except 구문을 사용합니다.
try:
    import torch
    from segment_anything import sam_model_registry, SamPredictor
    SAM_AVAILABLE = True
except ImportError:
    SAM_AVAILABLE = False

from ultralytics import YOLO

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

        # 사용자 클릭 포인트 그리기
        for i, point in enumerate(self.input_points):
            color = Qt.GlobalColor.green if self.input_labels[i] == 1 else Qt.GlobalColor.red
            painter.setPen(QPen(color, 2)); painter.setBrush(QBrush(color))
            scaled_point = point * self.zoom_factor
            painter.drawEllipse(QPoint(int(scaled_point.x()), int(scaled_point.y())), 5, 5)

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
        self._overlay_listeners: list = []
        self.ensure_dirs_and_files()
        self.migrate_manifest_if_needed()

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
            self._write_direction_config(default_direction_config)
        else:
            try:
                with open(self.direction_config_path, 'r', encoding='utf-8') as f:
                    direction_config = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._write_direction_config(default_direction_config)
            else:
                changed = False
                for key, value in default_direction_config.items():
                    if key not in direction_config:
                        direction_config[key] = value if key not in {'templates_left', 'templates_right'} else list(value)
                        changed = True
                if changed:
                    self._write_direction_config(direction_config)

    def _default_nickname_config(self):
        return {
            "target_text": "버프몬",
            "match_threshold": 0.72,
            "char_offset_x": 0,
            "char_offset_y": 46,
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

    def register_overlay_listener(self, callback):
        if callable(callback) and callback not in self._overlay_listeners:
            self._overlay_listeners.append(callback)

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
        self.last_used_model = settings.get('last_used_model', None)
        self._checked_class_names: set[str] = set(settings.get('hunt_checked_classes', []))
        self.nickname_config = self.data_manager.get_nickname_config()
        self._nickname_ui_updating = False
        self.direction_config = self.data_manager.get_direction_config()
        self._direction_ui_updating = False
        self._thumbnail_cache = OrderedDict()
        self._thumbnail_cache_limit = 256
        self.initUI()
        self.init_sam()

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

        capture_options_layout = QHBoxLayout()
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

        center_layout.addLayout(image_list_header_layout)
        center_layout.addWidget(self.image_list_widget)
        center_layout.addLayout(capture_options_layout)
        center_layout.addLayout(center_buttons_layout)
        
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
        right_layout.addWidget(train_group)

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

        nickname_group = QGroupBox("닉네임 탐지 설정")
        nickname_layout = QVBoxLayout()

        nickname_text_layout = QHBoxLayout()
        nickname_text_layout.addWidget(QLabel("대상 닉네임:"))
        self.nickname_text_input = QLineEdit()
        self.nickname_text_input.setPlaceholderText("예: 버프몬")
        nickname_text_layout.addWidget(self.nickname_text_input, 1)
        self.nickname_overlay_checkbox = QCheckBox("실시간 표기")
        nickname_text_layout.addSpacing(8)
        nickname_text_layout.addWidget(self.nickname_overlay_checkbox)
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
        nickname_layout.addLayout(nickname_threshold_layout)

        self.nickname_template_list = QListWidget()
        self.nickname_template_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.nickname_template_list.setIconSize(QSize(160, 64))
        self.nickname_template_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.nickname_template_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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


        self._apply_nickname_config_to_ui()
        self._apply_direction_config_to_ui()
        self.nickname_text_input.editingFinished.connect(self.on_nickname_text_changed)
        self.nickname_threshold_spin.valueChanged.connect(self.on_nickname_threshold_changed)
        self.nickname_offset_x_spin.valueChanged.connect(self.on_nickname_offset_changed)
        self.nickname_offset_y_spin.valueChanged.connect(self.on_nickname_offset_changed)
        self.nickname_overlay_checkbox.toggled.connect(self.on_nickname_overlay_toggled)
        self.direction_threshold_spin.valueChanged.connect(self.on_direction_threshold_changed)
        self.direction_offset_spin.valueChanged.connect(self.on_direction_offset_changed)
        self.direction_height_spin.valueChanged.connect(self.on_direction_range_changed)
        self.direction_half_width_spin.valueChanged.connect(self.on_direction_range_changed)
        self.direction_overlay_checkbox.toggled.connect(self.on_direction_overlay_toggled)

        self.populate_class_list()
        self.populate_model_list()
        self.populate_preset_list()
        self.populate_nickname_template_list()

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
            self.model_selector.clear()
            saved_models = self.data_manager.get_saved_models()
            self.model_selector.addItems(saved_models)
            
            # v1.4: 마지막으로 사용한 모델이 목록에 있으면 선택
            if self.last_used_model and self.last_used_model in saved_models:
                self.model_selector.setCurrentText(self.last_used_model)

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

    def on_nickname_threshold_changed(self, value: float):
        if self._nickname_ui_updating:
            return
        self.nickname_config = self.data_manager.update_nickname_config({'match_threshold': float(value)})

    def on_nickname_offset_changed(self):
        if self._nickname_ui_updating:
            return
        updates = {
            'char_offset_x': int(self.nickname_offset_x_spin.value()),
            'char_offset_y': int(self.nickname_offset_y_spin.value()),
        }
        self.nickname_config = self.data_manager.update_nickname_config(updates)

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

        temp_manifest = self.data_manager.get_manifest()
        all_categories_in_manifest = list(temp_manifest.keys())

        # v1.3: 카테고리 순서에서 네거티브 샘플 제외
        ordered_categories = CATEGORIES + [cat for cat in all_categories_in_manifest if cat not in CATEGORIES and cat != NEGATIVE_SAMPLES_NAME]

        for category_name in ordered_categories:
            if category_name not in temp_manifest: continue

            category_item = QTreeWidgetItem(self.class_tree_widget, [category_name])
            category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)

            classes_in_category = manifest.get(category_name, {})
            for class_name in classes_in_category:
                class_item = QTreeWidgetItem(category_item, [class_name])
                class_item.setFlags(class_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
                class_item.setCheckState(0, Qt.CheckState.Checked)

            category_item.setExpanded(True)
            
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

    def set_image_sort_mode(self, mode):
        self.current_image_sort_mode = mode
        self.sort_by_name_btn.setChecked(mode == 'name')
        self.sort_by_date_btn.setChecked(mode == 'date')
        self.populate_image_list()

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
                self.open_editor_mode_dialog(captured_pixmaps[0])
            else:
                multi_dialog = MultiCaptureDialog(captured_pixmaps, self)
                if multi_dialog.exec():
                    selected_pixmaps = multi_dialog.get_selected_pixmaps()
                    for pixmap in selected_pixmaps:
                        self.open_editor_mode_dialog(pixmap)
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
