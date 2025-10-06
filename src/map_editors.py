"""맵 탭 편집기 및 다이얼로그 구성 요소."""

from __future__ import annotations

import base64
import copy
import ctypes
import json
import math
import os
import traceback
import uuid
from collections import defaultdict, deque
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import win32api
import win32con
from PyQt6.QtCore import (
    QEasingCurve,
    QAbstractNativeEventFilter,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QLineF,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from .map import (
        CONFIG_PATH,
        GLOBAL_ACTION_MODEL_DIR,
        load_baseline_state_machine_config,
        LADDER_ARRIVAL_X_THRESHOLD,
        LADDER_ARRIVAL_SHORT_THRESHOLD,
        LADDER_AVOIDANCE_WIDTH,
        LADDER_X_GRAB_THRESHOLD,
        MAPS_DIR,
        MAX_JUMP_DURATION,
        MAX_LOCK_DURATION,
        MapConfig,
        MOVE_DEADZONE,
        ROUTE_SLOT_IDS,
        WAYPOINT_ARRIVAL_X_THRESHOLD,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT,
        Y_MOVEMENT_DEADZONE,
        CLIMBING_STATE_FRAME_THRESHOLD,
        CLIMB_X_MOVEMENT_THRESHOLD,
        FALLING_STATE_FRAME_THRESHOLD,
        FALL_ON_LADDER_X_MOVEMENT_THRESHOLD,
        FALL_Y_MIN_THRESHOLD,
        IDLE_TIME_THRESHOLD,
        PREPARE_TIMEOUT,
        AIRBORNE_RECOVERY_WAIT_DEFAULT,
        LADDER_RECOVERY_RESEND_DELAY_DEFAULT,
        JUMPING_STATE_FRAME_THRESHOLD,
        JUMP_LINK_ARRIVAL_X_THRESHOLD,
        JUMP_Y_MAX_THRESHOLD,
        JUMP_Y_MIN_THRESHOLD,
        STUCK_DETECTION_WAIT_DEFAULT,
        ON_TERRAIN_Y_THRESHOLD,
        load_event_profiles,
        load_skill_profiles,
    )
except ImportError:
    from map import (  # type: ignore
        CONFIG_PATH,
        GLOBAL_ACTION_MODEL_DIR,
        load_baseline_state_machine_config,
        LADDER_ARRIVAL_X_THRESHOLD,
        LADDER_ARRIVAL_SHORT_THRESHOLD,
        LADDER_AVOIDANCE_WIDTH,
        LADDER_X_GRAB_THRESHOLD,
        MAPS_DIR,
        MAX_JUMP_DURATION,
        MAX_LOCK_DURATION,
        MapConfig,
        MOVE_DEADZONE,
        ROUTE_SLOT_IDS,
        WAYPOINT_ARRIVAL_X_THRESHOLD,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT,
        WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT,
        Y_MOVEMENT_DEADZONE,
        CLIMBING_STATE_FRAME_THRESHOLD,
        CLIMB_X_MOVEMENT_THRESHOLD,
        FALLING_STATE_FRAME_THRESHOLD,
        FALL_ON_LADDER_X_MOVEMENT_THRESHOLD,
        FALL_Y_MIN_THRESHOLD,
        IDLE_TIME_THRESHOLD,
        PREPARE_TIMEOUT,
        AIRBORNE_RECOVERY_WAIT_DEFAULT,
        LADDER_RECOVERY_RESEND_DELAY_DEFAULT,
        JUMPING_STATE_FRAME_THRESHOLD,
        JUMP_LINK_ARRIVAL_X_THRESHOLD,
        JUMP_Y_MAX_THRESHOLD,
        JUMP_Y_MIN_THRESHOLD,
        STUCK_DETECTION_WAIT_DEFAULT,
        ON_TERRAIN_Y_THRESHOLD,
        load_event_profiles,
        load_skill_profiles,
    )

if 'WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT' not in globals():
    WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT = WAYPOINT_ARRIVAL_X_THRESHOLD
if 'WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT' not in globals():
    WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT = WAYPOINT_ARRIVAL_X_THRESHOLD
if 'WALK_TELEPORT_PROBABILITY_DEFAULT' not in globals():
    WALK_TELEPORT_PROBABILITY_DEFAULT = 3.0
if 'WALK_TELEPORT_INTERVAL_DEFAULT' not in globals():
    WALK_TELEPORT_INTERVAL_DEFAULT = 0.5
if 'WALK_TELEPORT_BONUS_DELAY_DEFAULT' not in globals():
    WALK_TELEPORT_BONUS_DELAY_DEFAULT = 1.0
if 'WALK_TELEPORT_BONUS_STEP_DEFAULT' not in globals():
    WALK_TELEPORT_BONUS_STEP_DEFAULT = 10.0
if 'WALK_TELEPORT_BONUS_MAX_DEFAULT' not in globals():
    WALK_TELEPORT_BONUS_MAX_DEFAULT = 50.0

try:
    from . import map as _map_module  # type: ignore
except ImportError:
    import map as _map_module  # type: ignore

WALK_TELEPORT_PROBABILITY_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_PROBABILITY_DEFAULT",
    WALK_TELEPORT_PROBABILITY_DEFAULT,
)
WALK_TELEPORT_INTERVAL_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_INTERVAL_DEFAULT",
    WALK_TELEPORT_INTERVAL_DEFAULT,
)
WALK_TELEPORT_BONUS_DELAY_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_BONUS_DELAY_DEFAULT",
    WALK_TELEPORT_BONUS_DELAY_DEFAULT,
)
WALK_TELEPORT_BONUS_STEP_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_BONUS_STEP_DEFAULT",
    WALK_TELEPORT_BONUS_STEP_DEFAULT,
)
WALK_TELEPORT_BONUS_MAX_DEFAULT = getattr(
    _map_module,
    "WALK_TELEPORT_BONUS_MAX_DEFAULT",
    WALK_TELEPORT_BONUS_MAX_DEFAULT,
)

try:
    from .map_widgets import MultiScreenSnipper
except ImportError:
    from map_widgets import MultiScreenSnipper  # type: ignore

try:
    from .map_logic import ActionTrainingThread
except ImportError:
    from map_logic import ActionTrainingThread  # type: ignore

__all__ = [
    'ZoomableView', 'CroppingLabel', 'FeatureCropDialog', 'KeyFeatureManagerDialog',
    'AdvancedWaypointCanvas', 'AdvancedWaypointEditorDialog', 'CustomGraphicsView',
    'DebugViewDialog', 'RoundedRectItem', 'WaypointEditDialog', 'ForbiddenWallDialog', 'FullMinimapEditorDialog',
    'ActionLearningDialog', 'StateConfigDialog', 'WinEventFilter', 'HotkeyManager',
    'HotkeySettingDialog'
]

class ZoomableView(QGraphicsView):
    """휠 확대를 지원하고, 휠 클릭 패닝이 가능한 QGraphicsView."""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        
        self._is_panning = False
        self._last_pan_pos = QPoint()
        self._is_drawing_mode = False
        
        self.set_drawing_mode(False)

    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor

        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

    def set_drawing_mode(self, is_drawing):
        self._is_drawing_mode = is_drawing
        if is_drawing:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.pos() - self._last_pan_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._last_pan_pos = event.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._is_panning:
            self._is_panning = False
            # 현재 모드에 맞는 커서로 복원
            if self._is_drawing_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

class CroppingLabel(QLabel):
    def __init__(self, pixmap, parent_dialog):
        super().__init__()
        self.setPixmap(pixmap)
        self.parent_dialog = parent_dialog
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if self.parent_dialog.drawing or not self.parent_dialog.get_selected_rect().isNull():
            painter.setPen(QPen(QColor(255, 165, 0, 200), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(255, 165, 0, 50)))
            painter.drawRect(self.parent_dialog.get_selected_rect())

class FeatureCropDialog(QDialog):
    def __init__(self, pixmap, frame_bgr, all_key_features, feature_offsets, parent):
        super().__init__(parent)
        self.setWindowTitle("새로운 핵심 지형 추가 (휠 클릭: 이동, 휠 스크롤: 확대/축소)")
        self.base_pixmap = pixmap
        self.frame_bgr = frame_bgr
        self.all_key_features = all_key_features
        self.feature_offsets = feature_offsets

        self.scene = QGraphicsScene(self)
        self.view = ZoomableView(self.scene, self)
        self.pixmap_item = self.scene.addPixmap(self.base_pixmap)
        
        self.original_mousePressEvent = self.view.mousePressEvent
        self.original_mouseMoveEvent = self.view.mouseMoveEvent
        self.original_mouseReleaseEvent = self.view.mouseReleaseEvent

        self.drawing = False
        self.start_point_scene = QPointF()
        self.preview_rect_item = QGraphicsRectItem()
        pen = QPen(QColor(255, 165, 0, 200), 2, Qt.PenStyle.DashLine)
        brush = QBrush(QColor(255, 165, 0, 50))
        self.preview_rect_item.setPen(pen)
        self.preview_rect_item.setBrush(brush)
        self.scene.addItem(self.preview_rect_item)
        self.preview_rect_item.setVisible(False)

        self.view.mousePressEvent = self.view_mousePressEvent
        self.view.mouseMoveEvent = self.view_mouseMoveEvent
        self.view.mouseReleaseEvent = self.view_mouseReleaseEvent

        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setFixedSize(self.base_pixmap.width() + 60, self.base_pixmap.height() + 100)
        self.view.set_drawing_mode(True)

        self._display_existing_features() # --- 다른 지형 표시 함수 호출 ---

    def showEvent(self, event):
        super().showEvent(event)
        if not event.spontaneous():
            self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def view_mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.start_point_scene = self.view.mapToScene(event.pos())
            self.preview_rect_item.setRect(QRectF(self.start_point_scene, QSizeF(0, 0)))
            self.preview_rect_item.setVisible(True)
        else:
            self.original_mousePressEvent(event)

    def view_mouseMoveEvent(self, event):
        if self.drawing:
            current_point_scene = self.view.mapToScene(event.pos())
            rect = QRectF(self.start_point_scene, current_point_scene).normalized()
            self.preview_rect_item.setRect(rect)
        else:
            self.original_mouseMoveEvent(event)
    def view_mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
        else:
            self.original_mouseReleaseEvent(event)

    def get_selected_rect(self):
        return self.preview_rect_item.rect().toRect()
    
    def _group_rects(self, rect_list, threshold=20):
        """가까운 사각형들을 그룹화합니다."""
        if not rect_list:
            return []

        # 신뢰도 순으로 정렬
        rect_list.sort(key=lambda x: x[1], reverse=True)
        
        groups = []
        while rect_list:
            base_rect, base_conf = rect_list.pop(0)
            current_group = [(base_rect, base_conf)]
            
            remaining_rects = []
            for other_rect, other_conf in rect_list:
                # 중심점 간의 거리(Manhattan distance)로 근접성 판단
                if abs(base_rect.center().x() - other_rect.center().x()) + \
                    abs(base_rect.center().y() - other_rect.center().y()) < threshold:
                    current_group.append((other_rect, other_conf))
                else:
                    remaining_rects.append((other_rect, other_conf))
            
            groups.append(current_group)
            rect_list = remaining_rects
            
        # 각 그룹에서 가장 신뢰도가 높은 사각형 하나만 반환
        final_rects = [max(group, key=lambda x: x[1])[0] for group in groups]
        return final_rects
       
    def _display_existing_features(self):
        """상호 검증을 통해, 구조적으로 가장 올바른 위치의 핵심 지형 하나만 표시합니다."""
        if self.frame_bgr is None or not self.all_key_features:
            return

        current_map_gray = cv2.cvtColor(self.frame_bgr, cv2.COLOR_BGR2GRAY)
        
        # 1. 모든 지형에 대해 가능한 모든 후보 위치 찾기
        all_candidates = defaultdict(list)
        for feature_id, feature_data in self.all_key_features.items():
            try:
                img_data = base64.b64decode(feature_data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                if template is None: continue

                h, w = template.shape
                threshold = feature_data.get('threshold', 0.85)
                res = cv2.matchTemplate(current_map_gray, template, cv2.TM_CCOEFF_NORMED)
                
                loc = np.where(res >= threshold)
                for pt in zip(*loc[::-1]):
                    # (위치, 신뢰도) 쌍으로 저장
                    confidence = res[pt[1], pt[0]]
                    center_pos = QPointF(pt[0] + w/2, pt[1] + h/2)
                    all_candidates[feature_id].append({'pos': center_pos, 'conf': confidence, 'size': QSize(w, h)})
            except Exception as e:
                print(f"Error finding candidates for {feature_id}: {e}")

        # 2. 각 지형별로 가장 가능성 높은 위치 하나만 선택 (상호 검증)
        final_positions = {}
        VALIDATION_DISTANCE = 25.0
        
        sorted_candidates = sorted(all_candidates.keys())

        for target_id in sorted_candidates:
            best_candidate = None
            max_support = -1

            for candidate in all_candidates[target_id]:
                support_count = 0
                for source_id in sorted_candidates:
                    if source_id == target_id: continue
                    
                    offset = self.feature_offsets.get((source_id, target_id))
                    if not offset: continue

                    for source_candidate in all_candidates[source_id]:
                        predicted_pos = source_candidate['pos'] + offset
                        distance = math.hypot((predicted_pos - candidate['pos']).x(), (predicted_pos - candidate['pos']).y())
                        
                        if distance < VALIDATION_DISTANCE:
                            support_count += 1
                            break # 하나의 source에 대해선 한 번만 카운트
                
                if support_count > max_support:
                    max_support = support_count
                    best_candidate = candidate
            
            if best_candidate:
                final_positions[target_id] = best_candidate

        # 3. 최종 선택된 위치를 화면에 그리기
        for feature_id, data in final_positions.items():
            center_pos = data['pos']
            size = data['size']
            top_left = center_pos - QPointF(size.width()/2, size.height()/2)
            rect_f = QRectF(top_left, QSizeF(size))
            
            self.scene.addRect(rect_f, QPen(QColor(0, 180, 255, 200), 2), QBrush(QColor(0, 180, 255, 50)))
            text_item = self.scene.addText(feature_id)
            text_item.setDefaultTextColor(Qt.GlobalColor.white)
            text_rect = text_item.boundingRect()
            text_item.setPos(rect_f.center() - QPointF(text_rect.width()/2, text_rect.height()/2))

class KeyFeatureManagerDialog(QDialog):
    def __init__(self, key_features, all_waypoints, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"핵심 지형 관리자 (맵 프로필: {parent.active_profile_name})")
        self.key_features = key_features
        self.all_waypoints = all_waypoints
        self.parent_map_tab = parent
        self.setMinimumSize(800, 600)
        self.initUI()
        self.populate_feature_list()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        left_group = QGroupBox("등록된 핵심 지형 (문맥 썸네일)")
        left_layout = QVBoxLayout()
        self.feature_list_widget = QListWidget()
        self.feature_list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.feature_list_widget.setIconSize(QSize(128, 128))
        self.feature_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.feature_list_widget.itemSelectionChanged.connect(self.show_feature_details)
        self.feature_list_widget.itemDoubleClicked.connect(self.edit_feature)
        
        # ---  버튼 레이아웃 변경 ---
        button_layout = QHBoxLayout()
        self.add_feature_btn = QPushButton("새 지형 추가")
        self.add_feature_btn.clicked.connect(self.add_new_feature)
        
        # '전체 웨이포인트 갱신' 버튼 관련 코드 삭제
        # self.update_links_btn = QPushButton("전체 웨이포인트 갱신")
        # self.update_links_btn.setToolTip(...)
        # self.update_links_btn.clicked.connect(self.on_update_all_clicked)
        
        button_layout.addWidget(self.add_feature_btn)
        # button_layout.addWidget(self.update_links_btn) # 삭제
        
        
        left_layout.addWidget(self.feature_list_widget)
        left_layout.addLayout(button_layout)
        left_group.setLayout(left_layout)

        right_group = QGroupBox("상세 정보")
        right_layout = QVBoxLayout()
        self.image_preview_label = QLabel("지형을 선택하세요.")
        self.image_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview_label.setMinimumSize(200, 200)
        self.image_preview_label.setStyleSheet("background-color: #333; border-radius: 5px;")

        info_layout = QHBoxLayout()
        self.info_label = QLabel("이름: -")
        info_layout.addWidget(self.info_label)
        info_layout.addStretch(1)
        info_layout.addWidget(QLabel("탐지 정확도:"))
        self.threshold_spinbox = QDoubleSpinBox()
        self.threshold_spinbox.setRange(0.5, 1.0)
        self.threshold_spinbox.setSingleStep(0.01)
        self.threshold_spinbox.valueChanged.connect(self.on_threshold_changed)
        self.threshold_spinbox.setEnabled(False)
        info_layout.addWidget(self.threshold_spinbox)

        self.usage_label = QLabel("사용 중인 웨이포인트:")
        self.usage_list_widget = QListWidget()
        control_buttons_layout = QHBoxLayout()
        
        self.set_as_anchor_btn = QPushButton("기준 앵커로 지정")
        self.set_as_anchor_btn.setToolTip("이 지형을 맵 전체의 (0, 0) 원점으로 설정합니다.\n기준 앵커는 맵 좌표계의 기준이 됩니다.")
        self.set_as_anchor_btn.clicked.connect(self.set_as_reference_anchor)
        self.set_as_anchor_btn.setEnabled(False)
        
        self.rename_button = QPushButton("이름 변경")
        self.rename_button.clicked.connect(self.rename_selected_feature)
        self.rename_button.setEnabled(False)
        self.delete_button = QPushButton("선택한 지형 삭제")
        self.delete_button.clicked.connect(self.delete_selected_feature)
        self.delete_button.setEnabled(False)
        
        control_buttons_layout.addWidget(self.set_as_anchor_btn)
        control_buttons_layout.addWidget(self.rename_button)
        control_buttons_layout.addWidget(self.delete_button)

        right_layout.addWidget(self.image_preview_label, 1)
        right_layout.addLayout(info_layout)
        right_layout.addWidget(self.usage_label)
        right_layout.addWidget(self.usage_list_widget, 1)
        self.match_rate_label = QLabel("탐색 매칭률 (선택된 지형의 문맥 이미지 기준):")
        self.match_rate_list_widget = QListWidget()
        self.match_rate_list_widget.setStyleSheet("background-color: #2E2E2E;") 
        right_layout.addWidget(self.match_rate_label)
        right_layout.addWidget(self.match_rate_list_widget, 1)      
        right_layout.addLayout(control_buttons_layout)
        right_group.setLayout(right_layout)

        main_layout.addWidget(left_group, 2)
        main_layout.addWidget(right_group, 1)

    def set_as_reference_anchor(self):
        """선택된 지형을 맵의 기준 앵커로 설정하고, 모든 좌표계를 변환합니다."""
        selected_items = self.feature_list_widget.selectedItems()
        if not selected_items: return
        
        new_anchor_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        old_anchor_id = self.parent_map_tab.reference_anchor_id

        if old_anchor_id == new_anchor_id:
            QMessageBox.information(self, "알림", "이미 기준 앵커로 설정되어 있습니다.")
            return

        # 1. 현재 (old_anchor 기준) 전역 좌표계 계산
        #    _calculate_global_positions는 항상 최신 상태를 반영하므로 그대로 사용
        current_global_pos = self.parent_map_tab.global_positions
        if not current_global_pos or new_anchor_id not in current_global_pos:
            QMessageBox.warning(self, "오류", "좌표 변환에 필요한 정보를 계산할 수 없습니다.\n"
                                          "모든 핵심 지형이 연결되어 있는지 확인해주세요.")
            return
            
        # 2. 새로운 원점이 될 지형의 현재 좌표를 구함. 이것이 변환 벡터가 됨.
        translation_vector = current_global_pos[new_anchor_id]

        # 3. 모든 절대 좌표를 가진 데이터(지형, 오브젝트 등)를 이동
        geometry_data = self.parent_map_tab.geometry_data
        for line in geometry_data.get("terrain_lines", []):
            line['points'] = [[p[0] - translation_vector.x(), p[1] - translation_vector.y()] for p in line['points']]
        for obj in geometry_data.get("transition_objects", []):
            obj['points'] = [[p[0] - translation_vector.x(), p[1] - translation_vector.y()] for p in obj['points']]
        for wp in geometry_data.get("waypoints", []):
            wp['pos'] = [wp['pos'][0] - translation_vector.x(), wp['pos'][1] - translation_vector.y()]
        for jump in geometry_data.get("jump_links", []):
            jump['start_vertex_pos'] = [jump['start_vertex_pos'][0] - translation_vector.x(), jump['start_vertex_pos'][1] - translation_vector.y()]
            jump['end_vertex_pos'] = [jump['end_vertex_pos'][0] - translation_vector.x(), jump['end_vertex_pos'][1] - translation_vector.y()]
        
        # 4. 핵심 지형 간의 상대적 관계 데이터는 전혀 수정하지 않음!
        #    (image_base64, rect_in_context 등은 불변)
        
        # 5. 새로운 기준 앵커 ID를 설정
        self.parent_map_tab.reference_anchor_id = new_anchor_id
        
        # 6. 변경된 모든 데이터를 저장.
        #    save_profile_data는 내부적으로 _calculate_global_positions를 다시 호출하며,
        #    새로운 앵커 기준으로 좌표계를 올바르게 재구성함.
        self.parent_map_tab.save_profile_data()
        self.parent_map_tab.update_general_log(f"'{new_anchor_id}'이(가) 새로운 기준 앵커로 설정되었습니다. 모든 좌표가 재계산되었습니다.", "purple")
        
        # 7. UI 즉시 갱신
        self.populate_feature_list()
        for i in range(self.feature_list_widget.count()):
            item = self.feature_list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == new_anchor_id:
                item.setSelected(True)
                break

    def on_threshold_changed(self, value):
        selected_items = self.feature_list_widget.selectedItems()
        if not selected_items: return
        feature_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if feature_id in self.key_features:
            self.key_features[feature_id]['threshold'] = value
            self.parent_map_tab.save_profile_data()

    def _create_context_thumbnail(self, feature_data):
        if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
            context_img_data = base64.b64decode(feature_data['context_image_base64'])
            pixmap = QPixmap()
            pixmap.loadFromData(context_img_data)
            painter = QPainter(pixmap)
            rect_coords = feature_data.get('rect_in_context')
            if rect_coords and len(rect_coords) == 4:
                rect = QRect(*rect_coords)
                painter.setPen(QPen(QColor(255, 165, 0, 220), 2, Qt.PenStyle.SolidLine))
                painter.setBrush(QBrush(QColor(255, 165, 0, 70)))
                painter.drawRect(rect)
            painter.end()
            return pixmap
        else:
            img_data = base64.b64decode(feature_data['image_base64'])
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)
            return pixmap

    def add_new_feature(self):
        if not self.parent_map_tab.minimap_region:
            QMessageBox.warning(self, "오류", "먼저 메인 화면에서 '미니맵 범위 지정'을 해주세요.")
            return
        self.parent_map_tab.update_general_log("새 핵심 지형 추가를 위해 미니맵을 캡처합니다...", "black")
        frame_bgr = self.parent_map_tab.get_cleaned_minimap_image()
        if frame_bgr is None:
            QMessageBox.warning(self, "오류", "미니맵 이미지를 가져올 수 없습니다.")
            return

        pixmap = QPixmap.fromImage(QImage(frame_bgr.data, frame_bgr.shape[1], frame_bgr.shape[0], frame_bgr.strides[0], QImage.Format.Format_BGR888))
        crop_dialog = FeatureCropDialog(pixmap, frame_bgr, self.key_features, self.parent_map_tab.feature_offsets, parent=self)
        if crop_dialog.exec():
            rect = crop_dialog.get_selected_rect()
            if rect.width() < 5 or rect.height() < 5:
                QMessageBox.warning(self, "오류", "너무 작은 영역은 지형으로 등록할 수 없습니다.")
                return

            _, context_buffer = cv2.imencode('.png', frame_bgr)
            context_base64 = base64.b64encode(context_buffer).decode('utf-8')

            feature_img = frame_bgr[rect.y():rect.y()+rect.height(), rect.x():rect.x()+rect.width()]
            _, feature_buffer = cv2.imencode('.png', feature_img)
            feature_base64 = base64.b64encode(feature_buffer).decode('utf-8')

            new_id = self.parent_map_tab._get_next_feature_name()
            self.key_features[new_id] = {
                'image_base64': feature_base64,
                'context_image_base64': context_base64,
                'rect_in_context': [rect.x(), rect.y(), rect.width(), rect.height()],
                'threshold': 0.85
            }

            self.parent_map_tab.save_profile_data()
            self.parent_map_tab.update_general_log(f"새 핵심 지형 '{new_id}'가 추가되었습니다.", "green")
            self.populate_feature_list()

            for i in range(self.feature_list_widget.count()):
                item = self.feature_list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == new_id:
                    item.setSelected(True)
                    break

    def populate_feature_list(self):
        """리스트를 채울 때 기준 앵커를 시각적으로 표시합니다."""
        self.feature_list_widget.clear()
        sorted_keys = sorted(self.key_features.keys(), key=lambda x: int(x[1:]) if x.startswith("P") and x[1:].isdigit() else float('inf'))
        anchor_id = self.parent_map_tab.reference_anchor_id
        
        for feature_id in sorted_keys:
            data = self.key_features[feature_id]
            try:
                # 데이터 유효성 검사 추가
                if not isinstance(data, dict) or 'image_base64' not in data:
                    print(f"경고: 잘못된 형식의 지형 데이터 건너뜀 (ID: {feature_id})")
                    continue

                thumbnail = self._create_context_thumbnail(data)
                
                display_name = f"★ {feature_id}" if feature_id == anchor_id else feature_id
                
                item = QListWidgetItem(QIcon(thumbnail), display_name)
                item.setData(Qt.ItemDataRole.UserRole, feature_id)
                self.feature_list_widget.addItem(item)
            except Exception as e: print(f"지형 로드 오류 (ID: {feature_id}): {e}")

    def show_feature_details(self):
        self.all_waypoints = self.parent_map_tab.get_all_waypoints_with_route_name()
        selected_items = self.feature_list_widget.selectedItems()
        if not selected_items:
            self.delete_button.setEnabled(False)
            self.rename_button.setEnabled(False)
            self.threshold_spinbox.setEnabled(False)
            self.set_as_anchor_btn.setEnabled(False)
            self.match_rate_list_widget.clear() # --- 리스트 클리어 추가 ---
            self.image_preview_label.setText("지형을 선택하세요.")
            self.info_label.setText("이름: -")
            self.usage_list_widget.clear()
            return

        item = selected_items[0]
        feature_id = item.data(Qt.ItemDataRole.UserRole)
        feature_data = self.key_features.get(feature_id)
        if not feature_data: return

        # ---  pixmap 변수 할당 및 유효성 검사 ---
        pixmap = self._create_context_thumbnail(feature_data)
        
        if pixmap and not pixmap.isNull():
            self.image_preview_label.setPixmap(pixmap.scaled(self.image_preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.image_preview_label.setText("썸네일 이미지\n생성 실패")
        

        anchor_id = self.parent_map_tab.reference_anchor_id
        if feature_id == anchor_id:
            self.info_label.setText(f"<b>이름:</b> {feature_id} <font color='cyan'>(기준 앵커)</font>")
            self.set_as_anchor_btn.setEnabled(False)
        else:
            self.info_label.setText(f"<b>이름:</b> {feature_id}")
            self.set_as_anchor_btn.setEnabled(True)

        self.threshold_spinbox.blockSignals(True)
        self.threshold_spinbox.setValue(feature_data.get('threshold', 0.85))
        self.threshold_spinbox.setEnabled(True)
        self.threshold_spinbox.blockSignals(False)

        self.usage_list_widget.clear()
        used_by = [f"[{wp['route_name']}] {wp['name']}" for wp in self.all_waypoints if any(f['id'] == feature_id for f in wp.get('key_feature_ids', []))]
        if used_by: self.usage_list_widget.addItems(used_by)
        else: self.usage_list_widget.addItem("사용하는 웨이포인트 없음")
        
        self.update_match_rates(feature_id, feature_data)

        self.delete_button.setEnabled(True)
        self.rename_button.setEnabled(True)

    def rename_selected_feature(self):
        selected_items = self.feature_list_widget.selectedItems()
        if not selected_items: return
        old_name = selected_items[0].data(Qt.ItemDataRole.UserRole)
        new_name, ok = QInputDialog.getText(self, "핵심 지형 이름 변경", f"'{old_name}'의 새 이름:", text=old_name)
        if ok and new_name and new_name != old_name:
            if new_name in self.key_features: QMessageBox.warning(self, "오류", "이미 존재하는 이름입니다."); return
            self.key_features[new_name] = self.key_features.pop(old_name)
            for wp in self.all_waypoints:
                if 'key_feature_ids' in wp:
                    for feature_link in wp['key_feature_ids']:
                        if feature_link['id'] == old_name: feature_link['id'] = new_name
            
            if self.parent_map_tab.reference_anchor_id == old_name:
                self.parent_map_tab.reference_anchor_id = new_name
            
            self.parent_map_tab.save_profile_data()
            self.parent_map_tab.update_general_log(f"핵심 지형 '{old_name}'의 이름이 '{new_name}'(으)로 변경되었습니다.", "blue")
            self.populate_feature_list()
            for i in range(self.feature_list_widget.count()):
                item = self.feature_list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == new_name: item.setSelected(True); break

    def delete_selected_feature(self):
        selected_items = self.feature_list_widget.selectedItems()
        if not selected_items: return
        feature_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        
        if feature_id == self.parent_map_tab.reference_anchor_id:
            QMessageBox.warning(self, "삭제 불가", "기준 앵커로 지정된 지형은 삭제할 수 없습니다.\n다른 지형을 먼저 기준 앵커로 지정해주세요.")
            return

        used_by_waypoints = [f"[{wp['route_name']}] {wp['name']}" for wp in self.all_waypoints if any(f['id'] == feature_id for f in wp.get('key_feature_ids', []))]
        warning_message = f"'{feature_id}' 지형을 영구적으로 삭제하시겠습니까?"
        if used_by_waypoints:
            warning_message += "\n\n경고: 이 지형은 아래 웨이포인트에서 사용 중입니다.\n삭제 시, 해당 웨이포인트들의 위치 정확도가 떨어질 수 있습니다.\n\n- " + "\n- ".join(used_by_waypoints)
        reply = QMessageBox.question(self, "삭제 확인", warning_message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            if feature_id in self.key_features:
                del self.key_features[feature_id]

            for route_profile in self.parent_map_tab.route_profiles.values():
                for wp in route_profile.get('waypoints', []):
                    if 'key_feature_ids' in wp:
                        wp['key_feature_ids'] = [f for f in wp['key_feature_ids'] if f['id'] != feature_id]
            
            self.parent_map_tab.save_profile_data()
            self.parent_map_tab.update_general_log(f"핵심 지형 '{feature_id}'가 영구적으로 삭제되었습니다.", "orange")
            
            self.populate_feature_list()
            self.image_preview_label.setText("지형을 선택하세요.")
            self.info_label.setText("이름: -")
            self.usage_list_widget.clear()
            self.delete_button.setEnabled(False)
            self.rename_button.setEnabled(False)
            self.threshold_spinbox.setEnabled(False)
            self.set_as_anchor_btn.setEnabled(False)
            
    def update_match_rates(self, selected_feature_id, selected_feature_data):
        """선택된 지형의 문맥 이미지에서 다른 모든 지형의 템플릿을 찾아 매칭률을 표시합니다."""
        self.match_rate_list_widget.clear()

        if 'context_image_base64' not in selected_feature_data or not selected_feature_data['context_image_base64']:
            self.match_rate_list_widget.addItem("문맥 이미지가 없습니다.")
            return
        
        try:
            context_img_data = base64.b64decode(selected_feature_data['context_image_base64'])
            context_np_arr = np.frombuffer(context_img_data, np.uint8)
            context_gray = cv2.imdecode(context_np_arr, cv2.IMREAD_GRAYSCALE)
            if context_gray is None:
                self.match_rate_list_widget.addItem("문맥 이미지 로드 실패.")
                return
        except Exception as e:
            self.match_rate_list_widget.addItem(f"문맥 이미지 오류: {e}")
            return

        match_results = []
        for other_id, other_data in self.key_features.items():
            if other_id == selected_feature_id:
                continue
            
            try:
                img_data = base64.b64decode(other_data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                if template is None: continue

                res = cv2.matchTemplate(context_gray, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                match_results.append((other_id, max_val))
            except Exception:
                continue

        # 매칭률 높은 순으로 정렬
        match_results.sort(key=lambda x: x[1], reverse=True)

        for other_id, max_val in match_results:
            text = f"{selected_feature_id}(미니맵) > {other_id}(핵심지형): {max_val:.4f}"
            item = QListWidgetItem(text)
            if max_val >= 0.90:
                item.setForeground(QColor("lime"))
            elif max_val >= 0.80:
                item.setForeground(QColor("yellow"))
            else:
                item.setForeground(QColor("red"))
            self.match_rate_list_widget.addItem(item)

    def edit_feature(self, item):
        """선택된 핵심 지형을 다시 잘라내도록 편집합니다."""
        feature_id = item.data(Qt.ItemDataRole.UserRole)
        feature_data = self.key_features.get(feature_id)

        if not feature_data or 'context_image_base64' not in feature_data or not feature_data['context_image_base64']:
            QMessageBox.warning(self, "편집 불가", "이 핵심 지형은 편집에 필요한 문맥 이미지를 가지고 있지 않습니다.")
            return

        try:
            context_img_data = base64.b64decode(feature_data['context_image_base64'])
            np_arr = np.frombuffer(context_img_data, np.uint8)
            frame_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            pixmap = QPixmap()
            pixmap.loadFromData(context_img_data)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"문맥 이미지 로드 중 오류 발생: {e}")
            return
            
        crop_dialog = FeatureCropDialog(pixmap,frame_bgr, self.key_features,self.parent_map_tab.feature_offsets, parent=self)
        if crop_dialog.exec():
            rect = crop_dialog.get_selected_rect()
            if rect.width() < 5 or rect.height() < 5:
                QMessageBox.warning(self, "오류", "너무 작은 영역은 지형으로 등록할 수 없습니다.")
                return

            feature_img = frame_bgr[rect.y():rect.y()+rect.height(), rect.x():rect.x()+rect.width()]
            _, feature_buffer = cv2.imencode('.png', feature_img)
            feature_base64 = base64.b64encode(feature_buffer).decode('utf-8')

            self.key_features[feature_id]['image_base64'] = feature_base64
            self.key_features[feature_id]['rect_in_context'] = [rect.x(), rect.y(), rect.width(), rect.height()]
            
            # save_profile_data는 내부적으로 MapTab의 모든 데이터를 갱신함
            self.parent_map_tab.save_profile_data()
            QApplication.processEvents() 
            self.parent_map_tab.update_general_log(f"핵심 지형 '{feature_id}'가 수정되었습니다.", "blue")
            
            #  데이터 동기화 및 UI 갱신 ---
            # GUI 이벤트 큐를 처리하여 MapTab의 데이터 변경이 반영되도록 함
            QApplication.processEvents()
            
            # MapTab의 최신 데이터로 다이얼로그의 데이터를 갱신
            self.key_features = self.parent_map_tab.key_features
            
            # UI 즉시 갱신
            self.populate_feature_list()
            for i in range(self.feature_list_widget.count()):
                list_item = self.feature_list_widget.item(i)
                if list_item.data(Qt.ItemDataRole.UserRole) == feature_id:
                    list_item.setSelected(True)
                    self.show_feature_details()
                    break
                    
class AdvancedWaypointCanvas(QLabel):
    def __init__(self, pixmap, initial_target=None, initial_features_data=None, parent=None):
        super().__init__(parent)
        self.base_pixmap = pixmap; self.setPixmap(self.base_pixmap); self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft); self.setMouseTracking(True)
        self.target_rect = self.denormalize_rect_normalized(initial_target) if initial_target else QRect()
        self.existing_features_data = initial_features_data if initial_features_data else []
        # rect_in_context (픽셀 좌표)를 직접 사용하도록 수정
        self.existing_features = [self.denormalize_rect_pixel(f.get('rect_in_context')) for f in self.existing_features_data]
        self.deleted_feature_ids = []
        self.newly_drawn_features = []; self.drawing = False; self.start_point = QPoint(); self.end_point = QPoint(); self.editing_mode = 'target'

    def denormalize_rect_normalized(self, norm_rect):
        """정규화된 좌표(0-1)를 픽셀 좌표(QRect)로 변환합니다."""
        if not norm_rect: return QRect()
        w, h = self.base_pixmap.width(), self.base_pixmap.height()
        return QRect(int(norm_rect[0]*w), int(norm_rect[1]*h), int(norm_rect[2]*w), int(norm_rect[3]*h))

    def denormalize_rect_pixel(self, rect_coords):
        """픽셀 좌표 리스트 [x, y, w, h]를 QRect 객체로 변환합니다."""
        if not rect_coords or len(rect_coords) != 4: return QRect()
        return QRect(*rect_coords)

    def normalize_rect(self, rect):
        if rect.isNull(): return None
        w, h = self.base_pixmap.width(), self.base_pixmap.height()
        if w > 0 and h > 0: return [rect.x()/w, rect.y()/h, rect.width()/w, rect.height()/h]
        return None

    def set_editing_mode(self, mode): self.editing_mode = mode; self.setCursor(Qt.CursorShape.CrossCursor); self.update()
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.drawing = True; self.start_point = event.pos(); self.end_point = event.pos(); self.update()
        elif event.button() == Qt.MouseButton.RightButton and self.editing_mode == 'feature':
            for i, feature_rect in reversed(list(enumerate(self.newly_drawn_features))):
                if feature_rect.contains(event.pos()): del self.newly_drawn_features[i]; self.update(); return
            for i, feature_rect in reversed(list(enumerate(self.existing_features))):
                if feature_rect.contains(event.pos()):
                    deleted_feature = self.existing_features_data.pop(i)
                    self.deleted_feature_ids.append(deleted_feature['id'])
                    del self.existing_features[i]; self.update(); return
    def mouseMoveEvent(self, event):
        if self.drawing: self.end_point = event.pos(); self.update()
        else:
            cursor_on_feature = any(rect.contains(event.pos()) for rect in self.existing_features + self.newly_drawn_features) if self.editing_mode == 'feature' else False
            self.setCursor(Qt.CursorShape.PointingHandCursor if cursor_on_feature else Qt.CursorShape.CrossCursor)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False; new_rect = QRect(self.start_point, self.end_point).normalized()
            if new_rect.width() > 5 and new_rect.height() > 5:
                if self.editing_mode == 'target': self.target_rect = new_rect
                else: self.newly_drawn_features.append(new_rect)
            self.update()
    def paintEvent(self, event):
        super().paintEvent(event); painter = QPainter(self)
        if not self.target_rect.isNull(): painter.setPen(QPen(QColor(0, 255, 0, 200), 2)); painter.setBrush(QBrush(QColor(0, 255, 0, 50))); painter.drawRect(self.target_rect)
        painter.setPen(QPen(QColor(0, 180, 255, 200), 2)); painter.setBrush(QBrush(QColor(0, 180, 255, 50)))
        for rect in self.existing_features: painter.drawRect(rect)
        painter.setPen(QPen(QColor(255, 165, 0, 200), 2)); painter.setBrush(QBrush(QColor(255, 165, 0, 50)))
        for rect in self.newly_drawn_features: painter.drawRect(rect)
        if self.drawing:
            color = Qt.GlobalColor.red if self.editing_mode == 'target' else QColor(255, 165, 0)
            painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawRect(QRect(self.start_point, self.end_point).normalized())

class AdvancedWaypointEditorDialog(QDialog):
    def __init__(self, pixmap, initial_data, all_key_features, parent=None):
        super().__init__(parent)
        self.setWindowTitle("웨이포인트 편집 (휠 클릭: 이동, 휠 스크롤: 확대/축소)")
        self.all_key_features = all_key_features
        self.parent_map_tab = parent
        initial_data = initial_data or {}

        layout = QVBoxLayout(self)
        self.scene = QGraphicsScene(self)
        self.view = ZoomableView(self.scene, self)
        self.pixmap_item = self.scene.addPixmap(pixmap)
        layout.addWidget(self.view)

        self.original_mousePressEvent = self.view.mousePressEvent
        self.original_mouseMoveEvent = self.view.mouseMoveEvent
        self.original_mouseReleaseEvent = self.view.mouseReleaseEvent

        self.editing_mode = 'target'
        self.drawing = False
        self.draw_start_pos = QPointF()
        self.preview_item = None
        self.deleted_feature_ids = set()

        self.target_item = None
        self.feature_items = {}
        self.new_feature_items = []
        
        self._load_initial_data(pixmap, initial_data)
        
        self.view.mousePressEvent = self.view_mousePressEvent
        self.view.mouseMoveEvent = self.view_mouseMoveEvent
        self.view.mouseReleaseEvent = self.view_mouseReleaseEvent

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("이름:"))
        self.name_edit = QLineEdit(initial_data.get('name', ''))
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        mode_box = QGroupBox("편집 모드")
        mode_layout = QHBoxLayout()
        self.target_radio = QRadioButton("목표 지점 (초록)")
        self.feature_radio = QRadioButton("핵심 지형 (주황/파랑)")
        self.target_radio.setChecked(True)
        self.target_radio.toggled.connect(lambda: self.set_editing_mode('target'))
        self.feature_radio.toggled.connect(lambda: self.set_editing_mode('feature'))
        mode_layout.addWidget(self.target_radio)
        mode_layout.addWidget(self.feature_radio)
        mode_box.setLayout(mode_layout)
        layout.addWidget(mode_box)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

        self.setFixedSize(pixmap.width() + 60, pixmap.height() + 180)
        self.set_editing_mode('target')

    def showEvent(self, event):
        super().showEvent(event)
        if not event.spontaneous():
            self.view.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def _load_initial_data(self, pixmap, initial_data):
        if 'rect_normalized' in initial_data and initial_data['rect_normalized']:
            norm_rect = initial_data['rect_normalized']
            w, h = pixmap.width(), pixmap.height()
            pixel_rect = QRectF(norm_rect[0]*w, norm_rect[1]*h, norm_rect[2]*w, norm_rect[3]*h)
            self.target_item = self._add_item_to_scene(pixel_rect, 'target')

        found_features = self.pre_scan_for_features(pixmap)
        for feature in found_features:
            feature_id = feature['id']
            pixel_rect = QRectF(*feature['rect_in_context'])
            item = self._add_item_to_scene(pixel_rect, 'existing_feature', feature_id)
            if feature_id not in self.feature_items:
                self.feature_items[feature_id] = []
            self.feature_items[feature_id].append(item)

    def _add_item_to_scene(self, rect, item_type, data=None):
        item = QGraphicsRectItem(rect)
        item.setData(0, item_type)
        item.setData(1, data)
        
        if item_type == 'target':
            item.setPen(QPen(QColor(0, 255, 0, 200), 2))
            item.setBrush(QBrush(QColor(0, 255, 0, 50)))
        elif item_type == 'existing_feature':
            item.setPen(QPen(QColor(0, 180, 255, 200), 2))
            item.setBrush(QBrush(QColor(0, 180, 255, 50)))
        elif item_type == 'new_feature':
            item.setPen(QPen(QColor(255, 165, 0, 200), 2))
            item.setBrush(QBrush(QColor(255, 165, 0, 50)))
        
        self.scene.addItem(item)
        return item

    def set_editing_mode(self, mode):
        self.editing_mode = mode
        self.view.set_drawing_mode(True)
        if self.drawing:
            self.drawing = False
            if self.preview_item:
                self.scene.removeItem(self.preview_item)
                self.preview_item = None

    def view_mousePressEvent(self, event):
        pos_scene = self.view.mapToScene(event.pos())
        if event.button() in [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton]:
            if event.button() == Qt.MouseButton.LeftButton:
                self.drawing = True
                self.draw_start_pos = pos_scene
            elif event.button() == Qt.MouseButton.RightButton:
                item_to_delete = self.view.itemAt(event.pos())
                if isinstance(item_to_delete, QGraphicsRectItem):
                    item_type = item_to_delete.data(0)
                    if item_type == 'existing_feature':
                        feature_id = item_to_delete.data(1)
                        if feature_id in self.feature_items and item_to_delete in self.feature_items[feature_id]:
                           self.feature_items[feature_id].remove(item_to_delete)
                        self.deleted_feature_ids.add(feature_id)
                        self.scene.removeItem(item_to_delete)
                    elif item_type == 'new_feature' and item_to_delete in self.new_feature_items:
                        self.new_feature_items.remove(item_to_delete)
                        self.scene.removeItem(item_to_delete)
                    elif item_type == 'target' and self.target_item == item_to_delete:
                        self.scene.removeItem(self.target_item)
                        self.target_item = None
        else:
            self.original_mousePressEvent(event)

    def view_mouseMoveEvent(self, event):
        if self.drawing:
            pos_scene = self.view.mapToScene(event.pos())
            rect = QRectF(self.draw_start_pos, pos_scene).normalized()
            if not self.preview_item:
                self.preview_item = QGraphicsRectItem(rect)
                self.preview_item.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.DashLine))
                self.scene.addItem(self.preview_item)
            else:
                self.preview_item.setRect(rect)
        else:
            self.original_mouseMoveEvent(event)

    def view_mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            if self.preview_item:
                new_rect = self.preview_item.rect()
                self.scene.removeItem(self.preview_item)
                self.preview_item = None

                if new_rect.width() > 5 and new_rect.height() > 5:
                    if self.editing_mode == 'target':
                        if self.target_item:
                            self.scene.removeItem(self.target_item)
                        self.target_item = self._add_item_to_scene(new_rect, 'target')
                    else:
                        item = self._add_item_to_scene(new_rect, 'new_feature')
                        self.new_feature_items.append(item)
        else:
            self.original_mouseReleaseEvent(event)

    def pre_scan_for_features(self, pixmap):
        found = []; q_image = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8); ptr = q_image.bits(); ptr.setsize(q_image.sizeInBytes())
        arr = np.array(ptr).reshape(q_image.height(), q_image.bytesPerLine()); current_map_gray = arr[:, :q_image.width()].copy()

        for feature_id, feature_data in self.all_key_features.items():
            try:
                img_data = base64.b64decode(feature_data['image_base64']); np_arr = np.frombuffer(img_data, np.uint8); template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                if template is None: continue

                threshold = feature_data.get('threshold', 0.90)
                res = cv2.matchTemplate(current_map_gray, template, cv2.TM_CCOEFF_NORMED)

                loc = np.where(res >= threshold)
                for pt in zip(*loc[::-1]):
                    h, w = template.shape
                    is_duplicate = False
                    for f in found:
                        existing_rect = QRect(*f['rect_in_context'])
                        if (QPoint(pt[0], pt[1]) - existing_rect.topLeft()).manhattanLength() < 10:
                            is_duplicate = True
                            break
                    if not is_duplicate:
                        found.append({'id': feature_id, 'rect_in_context': [pt[0], pt[1], w, h]})
            except Exception as e: print(f"Pre-scan error for feature {feature_id}: {e}")
        return found

    def get_waypoint_data(self):
        if not self.target_item:
            QMessageBox.warning(self, "저장 불가", "목표 지점(초록색)을 설정해야 합니다.")
            return None, None, None, None

        pixmap_size = self.pixmap_item.pixmap().size()
        w, h = pixmap_size.width(), pixmap_size.height()
        if w == 0 or h == 0: return None, None, None, None

        # 1. 목표 지점 (정규화된 좌표)
        target_rect_pixel = self.target_item.rect() # QRectF
        target_rect_norm = [target_rect_pixel.x()/w, target_rect_pixel.y()/h, target_rect_pixel.width()/w, target_rect_pixel.height()/h]
        
        # 2. 최종 캔버스에 남은 지형들
        final_features_on_canvas = []
        for item in self.scene.items():
            if isinstance(item, QGraphicsRectItem) and item.data(0) == 'existing_feature':
                feature_id = item.data(1)
                if feature_id not in self.deleted_feature_ids:
                    
                    rectF = item.rect()  # QRectF (float)
                    rect = rectF.toRect() # QRect (int)
                    
                    final_features_on_canvas.append({
                        'id': feature_id, 
                        'rect_in_context': [rect.x(), rect.y(), rect.width(), rect.height()]
                    })
        
        # 3. 새로 그려진 지형들
        newly_drawn_features = [item.rect().toRect() for item in self.new_feature_items]

        waypoint_data = {'name': self.name_edit.text(), 'rect_normalized': target_rect_norm}
        return waypoint_data, final_features_on_canvas, newly_drawn_features, list(self.deleted_feature_ids)

# --- v7.2.0: 마우스 휠 줌 기능이 추가된 커스텀 QGraphicsView ---
class CustomGraphicsView(QGraphicsView):
    mousePressed = pyqtSignal(QPointF, Qt.MouseButton)
    mouseMoved = pyqtSignal(QPointF)
    mouseReleased = pyqtSignal(QPointF, Qt.MouseButton)
    zoomChanged = pyqtSignal()
    
    def __init__(self, scene, parent_dialog=None):
        super().__init__(scene)
        self.parent_dialog = parent_dialog
        self._is_panning = False
        self._last_pan_pos = QPoint()

    def wheelEvent(self, event):
        # 모드와 관계없이 항상 휠 줌으로 작동 ---
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.zoomChanged.emit()
        event.accept()

    def mousePressEvent(self, event):
        # 휠 클릭 패닝 로직 (기존과 동일)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        
        #  웨이포인트 위에서 좌클릭 시 드래그 방지 ---
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            item = self.itemAt(event.pos())
            current_mode = self.parent_dialog.current_mode if self.parent_dialog else "select"
            if current_mode == "select" and item and item.data(0) in ["forbidden_wall", "forbidden_wall_indicator", "forbidden_wall_range"]:
                self.mousePressed.emit(self.mapToScene(event.pos()), event.button())
                event.accept()
                return

            if current_mode == "select" and item and item.data(0) in ["waypoint_v10", "waypoint_lod_text"]:
                # 웨이포인트가 클릭되었으므로, 이름 변경을 위해 시그널만 방출하고
                # QGraphicsView의 기본 드래그 로직이 시작되지 않도록 이벤트를 여기서 종료한다.
                self.mousePressed.emit(self.mapToScene(event.pos()), event.button())
                event.accept()
                return

        # 웨이포인트 위에서의 클릭이 아니거나 다른 버튼 클릭이면, 기존 로직 수행
        self.mousePressed.emit(self.mapToScene(event.pos()), event.button())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        #  휠 클릭 패닝 로직 추가 ---
        if self._is_panning:
            delta = event.pos() - self._last_pan_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._last_pan_pos = event.pos()
            event.accept()
            return
            
        # 휠 클릭이 아니면 기존 로직 수행
        self.mouseMoved.emit(self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        #  휠 클릭 패닝 로직 추가 ---
        if event.button() == Qt.MouseButton.MiddleButton and self._is_panning:
            self._is_panning = False
            # 현재 모드에 맞는 커서로 복원
            current_mode = self.parent_dialog.current_mode if self.parent_dialog else "select"
            if current_mode == "select":
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return

        # 휠 클릭이 아니면 기존 로직 수행
        self.mouseReleased.emit(self.mapToScene(event.pos()), event.button())
        super().mouseReleaseEvent(event)

class DebugViewDialog(QDialog):
    """실시간 위치 추정 알고리즘을 시각화하여 디버깅하는 대화 상자."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("실시간 탐지 디버그 뷰")
        self.setMinimumSize(400, 400)
        
        self.image_label = QLabel("탐지 대기 중...", self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout = QVBoxLayout(self)
        layout.addWidget(self.image_label)
        
        #  멤버 변수 다시 정의 ---
        self.base_pixmap = None
        self.debug_data = {}

    def update_debug_info(self, frame_bgr, debug_data):
        """MapTab으로부터 디버깅 정보를 받아 멤버 변수에 저장하고, paintEvent를 다시 호출합니다."""
        if frame_bgr is None:
            self.base_pixmap = None
            self.debug_data = {}
            self.image_label.setText("프레임 없음")
            return
            
        h, w, ch = frame_bgr.shape
        bytes_per_line = ch * w
        q_image = QImage(frame_bgr.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
        self.base_pixmap = QPixmap.fromImage(q_image)
        self.debug_data = debug_data
        
        # paintEvent를 다시 트리거하기 위해 위젯을 업데이트합니다.
        self.update()

    def paintEvent(self, event):
        """
        저장된 base_pixmap과 debug_data를 사용하여 모든 시각적 요소를 그립니다.
        이 메서드가 모든 드로잉을 책임집니다.
        """
        # QLabel의 기본 paintEvent를 먼저 호출합니다.
        super().paintEvent(event)
        
        if not self.base_pixmap or self.base_pixmap.isNull():
            # 기본 텍스트("탐지 대기 중...")가 표시되도록 합니다.
            # update_debug_info에서 이미 처리했으므로 여기서는 아무것도 안해도 됩니다.
            return

        # QLabel의 크기에 맞게 스케일된 Pixmap을 생성합니다.
        scaled_pixmap = self.base_pixmap.scaled(self.image_label.size(),
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)

        # 이 스케일된 Pixmap 위에 그림을 그립니다.
        painter = QPainter(scaled_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 원본 이미지와 스케일된 이미지의 비율을 계산합니다.
        # 드로잉 좌표를 스케일링하기 위해 필요합니다.
        scale_x = scaled_pixmap.width() / self.base_pixmap.width()
        scale_y = scaled_pixmap.height() / self.base_pixmap.height()

        # 모든 탐지된 지형 그리기
        all_features = self.debug_data.get('all_features', [])
        inlier_ids = self.debug_data.get('inlier_ids', set())
        
        for feature in all_features:
            # 원본 좌표를 스케일링합니다.
            rect = QRectF(feature['local_pos'], QSizeF(feature['size']))
            scaled_rect = QRectF(rect.x() * scale_x, rect.y() * scale_y,
                                 rect.width() * scale_x, rect.height() * scale_y)
            
            conf = feature['conf']
            feature_id = feature['id']
            
            pen = QPen()
            pen.setWidth(2)
            if feature_id in inlier_ids:
                pen.setColor(QColor("lime")) # 정상치(Inlier)는 초록색
            else:
                pen.setColor(QColor("red")) # 이상치(Outlier)는 빨간색
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(scaled_rect)
            
            # 텍스트
            painter.setFont(QFont("맑은 고딕", 8, QFont.Weight.Bold))
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(scaled_rect.bottomLeft() + QPointF(0, 12), f"{feature_id} ({conf:.2f})")
            
        # 추정된 플레이어 위치 그리기
        player_pos_local = self.debug_data.get('player_pos_local')
        if player_pos_local:
            scaled_player_pos = QPointF(player_pos_local.x() * scale_x, player_pos_local.y() * scale_y)
            painter.setPen(QPen(Qt.GlobalColor.yellow, 3))
            painter.setBrush(Qt.GlobalColor.yellow)
            painter.drawEllipse(scaled_player_pos, 3, 3)
        
        painter.end()

        # 최종적으로 모든 것이 그려진 Pixmap을 QLabel에 설정합니다.
        self.image_label.setPixmap(scaled_pixmap)

# --- v7.0.0: 전체 미니맵 편집기 다이얼로그 추가 ---

# 둥근 모서리 사각형을 위한 커스텀 아이템 추가 ---
class RoundedRectItem(QGraphicsRectItem):
    def __init__(self, rect, radius_x, radius_y, parent=None):
        super().__init__(rect, parent)
        self.radius_x = radius_x
        self.radius_y = radius_y

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawRoundedRect(self.rect(), self.radius_x, self.radius_y)

class WaypointEditDialog(QDialog):
    def __init__(self, waypoint_data, event_profiles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("웨이포인트 편집")
        self._event_profiles = event_profiles or []

        self.name_edit = QLineEdit(waypoint_data.get('name', ''))
        self.event_checkbox = QCheckBox("이벤트 웨이포인트")
        self.event_checkbox.setChecked(bool(waypoint_data.get('is_event')))
        self.event_always_checkbox = QCheckBox("항상 실행")
        self.event_always_checkbox.setChecked(bool(waypoint_data.get('event_always')))

        self.profile_combo = QComboBox()
        self.profile_combo.addItem("프로필 선택", "")
        for profile in self._event_profiles:
            self.profile_combo.addItem(profile, profile)

        existing_profile = waypoint_data.get('event_profile') or ""
        idx = self.profile_combo.findData(existing_profile)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)

        event_enabled = self.event_checkbox.isChecked()
        self.profile_combo.setEnabled(event_enabled and bool(self._event_profiles))
        self.event_always_checkbox.setEnabled(event_enabled)

        form_layout = QFormLayout()
        form_layout.addRow("이름", self.name_edit)
        form_layout.addRow("이벤트", self.event_checkbox)
        form_layout.addRow("명령 프로필", self.profile_combo)
        form_layout.addRow("", self.event_always_checkbox)

        self.hint_label = QLabel("이벤트 명령 프로필은 '자동 제어' 탭에서 '이벤트' 카테고리로 등록되어야 합니다.")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #888;")

        if not self._event_profiles:
            self.hint_label.setText("이벤트 명령 프로필이 없습니다. '자동 제어' 탭에서 '이벤트' 카테고리 명령을 추가해주세요.")
            self.profile_combo.setEnabled(False)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._handle_accept)
        button_box.rejected.connect(self.reject)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.hint_label)
        main_layout.addWidget(button_box)

        self.event_checkbox.toggled.connect(self._on_event_toggled)

    def _on_event_toggled(self, checked):
        self.profile_combo.setEnabled(checked and bool(self._event_profiles))
        self.event_always_checkbox.setEnabled(checked)
        if not checked:
            self.profile_combo.setCurrentIndex(0)
            self.event_always_checkbox.setChecked(False)

    def _handle_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "오류", "웨이포인트 이름을 입력해주세요.")
            return

        if self.event_checkbox.isChecked():
            selected_profile = self.profile_combo.currentData()
            if not selected_profile:
                QMessageBox.warning(self, "오류", "이벤트 명령 프로필을 선택해주세요.")
                return

        self.accept()

    def get_values(self):
        name = self.name_edit.text().strip()
        is_event = self.event_checkbox.isChecked()
        profile = self.profile_combo.currentData() if is_event else ""
        if profile is None:
            profile = ""
        always_run = self.event_always_checkbox.isChecked() if is_event else False
        return name, is_event, profile, always_run


class ForbiddenWallDialog(QDialog):
    def __init__(self, wall_data: dict, skill_profiles: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("금지벽 설정")
        self.setModal(True)
        self._skill_profiles = skill_profiles or []

        # 기본값 구성
        enabled = bool(wall_data.get('enabled', False))
        range_left = float(wall_data.get('range_left', 0.0))
        range_right = float(wall_data.get('range_right', 0.0))
        dwell_sec = max(0.0, float(wall_data.get('dwell_seconds', 3.0)))
        cooldown_sec = max(0.0, float(wall_data.get('cooldown_seconds', 5.0)))
        instant_on_contact = bool(wall_data.get('instant_on_contact', False))
        selected_profiles = set(wall_data.get('skill_profiles', []))

        self.enabled_checkbox = QCheckBox("금지 설정 사용")
        self.enabled_checkbox.setChecked(enabled)

        self.range_left_spin = QDoubleSpinBox()
        self.range_left_spin.setRange(0.0, 2000.0)
        self.range_left_spin.setDecimals(1)
        self.range_left_spin.setSingleStep(1.0)
        self.range_left_spin.setValue(range_left)
        self.range_left_spin.setSuffix(" px")

        self.range_right_spin = QDoubleSpinBox()
        self.range_right_spin.setRange(0.0, 2000.0)
        self.range_right_spin.setDecimals(1)
        self.range_right_spin.setSingleStep(1.0)
        self.range_right_spin.setValue(range_right)
        self.range_right_spin.setSuffix(" px")

        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setRange(0.0, 120.0)
        self.dwell_spin.setDecimals(1)
        self.dwell_spin.setSingleStep(0.5)
        self.dwell_spin.setValue(dwell_sec)
        self.dwell_spin.setSuffix(" s")

        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0.0, 600.0)
        self.cooldown_spin.setDecimals(1)
        self.cooldown_spin.setSingleStep(0.5)
        self.cooldown_spin.setValue(cooldown_sec)
        self.cooldown_spin.setSuffix(" s")

        self.instant_checkbox = QCheckBox("금지벽 접촉 시 즉시 실행")
        self.instant_checkbox.setChecked(instant_on_contact)

        config_form = QFormLayout()
        config_form.addRow("좌측 범위", self.range_left_spin)
        config_form.addRow("우측 범위", self.range_right_spin)
        config_form.addRow("대기 시간", self.dwell_spin)
        config_form.addRow("쿨타임", self.cooldown_spin)
        config_form.addRow("", self.instant_checkbox)

        self.config_widget = QWidget()
        self.config_widget.setLayout(config_form)

        self.skill_checks: List[QCheckBox] = []
        skills_layout = QVBoxLayout()
        skills_layout.setSpacing(4)

        if self._skill_profiles:
            for profile_name in self._skill_profiles:
                checkbox = QCheckBox(profile_name)
                checkbox.setChecked(profile_name in selected_profiles)
                self.skill_checks.append(checkbox)
                skills_layout.addWidget(checkbox)
        else:
            hint = QLabel("스킬 탭에 등록된 명령 프로필이 없습니다.")
            hint.setStyleSheet("color: #888;")
            skills_layout.addWidget(hint)

        skills_container = QWidget()
        skills_container.setLayout(skills_layout)
        self.skills_container = skills_container

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self._handle_accept)
        button_box.rejected.connect(self.reject)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.enabled_checkbox)
        main_layout.addWidget(self.config_widget)
        self.skills_label = QLabel("실행할 명령 프로필")
        main_layout.addWidget(self.skills_label)
        main_layout.addWidget(skills_container)
        main_layout.addStretch(1)
        main_layout.addWidget(button_box)

        self.enabled_checkbox.toggled.connect(self._update_enabled_state)
        self._update_enabled_state(enabled)

    def _update_enabled_state(self, checked: bool) -> None:
        self.config_widget.setEnabled(checked)
        self.skills_container.setEnabled(checked)
        if hasattr(self, 'skills_label'):
            self.skills_label.setEnabled(checked)

    def _handle_accept(self) -> None:
        if self.enabled_checkbox.isChecked():
            selected = [chk.text() for chk in self.skill_checks if chk.isChecked()]
            if not selected:
                QMessageBox.warning(self, "오류", "금지벽이 동작할 명령 프로필을 하나 이상 선택해주세요.")
                return
        self.accept()

    def get_values(self) -> dict:
        return {
            "enabled": self.enabled_checkbox.isChecked(),
            "range_left": float(self.range_left_spin.value()),
            "range_right": float(self.range_right_spin.value()),
            "dwell_seconds": float(self.dwell_spin.value()),
            "cooldown_seconds": float(self.cooldown_spin.value()),
            "instant_on_contact": self.instant_checkbox.isChecked(),
            "skill_profiles": [chk.text() for chk in self.skill_checks if chk.isChecked()],
        }

class HuntZoneConfigDialog(QDialog):
    """사냥범위 조절칸(영역) 설정 다이얼로그."""
    def __init__(self, zone: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("사냥범위 설정")
        self.setMinimumWidth(320)

        self.zone = zone or {}
        ranges = self.zone.get('ranges') or {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 활성화
        self.enabled_checkbox = QCheckBox("활성화")
        self.enabled_checkbox.setChecked(bool(self.zone.get('enabled', False)))
        form.addRow(self.enabled_checkbox)

        # 전/후 사냥/주스킬(대칭 숨김)
        def _spin(min_v, max_v, step, val):
            sp = QSpinBox()
            sp.setRange(min_v, max_v)
            sp.setSingleStep(step)
            sp.setValue(int(val))
            return sp

        self.enemy_front_spin = _spin(0, 2000, 10, int(ranges.get('enemy_front', 400)))
        self.enemy_back_spin = _spin(0, 2000, 10, int(ranges.get('enemy_back', 400)))
        self.primary_front_spin = _spin(0, 1200, 10, int(ranges.get('primary_front', 200)))
        self.primary_back_spin = _spin(0, 1200, 10, int(ranges.get('primary_back', 200)))
        self.y_height_spin = _spin(10, 400, 5, int(ranges.get('y_band_height', 40)))
        self.y_offset_spin = _spin(-200, 200, 5, int(ranges.get('y_band_offset', 0)))

        form.addRow("사냥 전방 X(px)", self.enemy_front_spin)
        form.addRow("사냥 후방 X(px)", self.enemy_back_spin)
        form.addRow("주 스킬 전방 X(px)", self.primary_front_spin)
        form.addRow("주 스킬 후방 X(px)", self.primary_back_spin)
        form.addRow("Y 범위 높이(px)", self.y_height_spin)
        form.addRow("Y 오프셋(px)", self.y_offset_spin)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> dict:
        return {
            'enabled': bool(self.enabled_checkbox.isChecked()),
            'ranges': {
                'enemy_front': int(self.enemy_front_spin.value()),
                'enemy_back': int(self.enemy_back_spin.value()),
                'primary_front': int(self.primary_front_spin.value()),
                'primary_back': int(self.primary_back_spin.value()),
                'y_band_height': int(self.y_height_spin.value()),
                'y_band_offset': int(self.y_offset_spin.value()),
            }
        }

class FullMinimapEditorDialog(QDialog):
    """
    맵 프로필의 모든 지형/웨이포인트 정보를 종합하여 전체 맵을 시각화하고,
    사용자가 직접 이동 가능한 지형(선)과 층 이동 오브젝트(사각형)를 편집하는 도구.
    """
    def __init__(self, profile_name, active_route_profile, key_features, route_profiles, geometry_data, render_options, global_positions, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"전체 미니맵 지형 편집기 (맵: {profile_name})")
        self.setMinimumSize(1200, 800)

        # 데이터 초기화
        self.key_features = key_features
        self.route_profiles = route_profiles
        self.all_waypoints_in_profile = geometry_data.get("waypoints", []) # v10.0.0: 프로필의 모든 웨이포인트
        self.geometry_data = copy.deepcopy(geometry_data)
        if "forbidden_walls" not in self.geometry_data:
            self.geometry_data["forbidden_walls"] = []
        # [신규] 사냥범위 존 기본 키 보장
        if "hunt_range_zones" not in self.geometry_data:
            self.geometry_data["hunt_range_zones"] = []
        self._ensure_waypoint_event_fields()
        self.render_options = render_options
        self.global_positions = global_positions
        self.parent_map_tab = parent
        self.active_route_profile = active_route_profile
        self.lod_threshold = 2.5  # 이름이 보이기 시작하는 줌 LOD 배율 (1.0 = 100%)
        self.lod_text_items = []  # LOD 적용 대상 텍스트 아이템 리스트
        
        # [v11.1.0] 좌표 텍스트를 위한 LOD 시스템 확장 (배율 조정)
        self.lod_coord_threshold = 10.0 # 좌표 텍스트가 보이기 시작하는 줌 배율 (요청에 따라 상향)
        self.lod_coord_items = [] # 좌표 텍스트 아이템 리스트

        # 그리기 상태 변수
        self.current_mode = "select" # "select", "terrain", "object", "waypoint", "jump"
        self.is_drawing_line = False
        self.current_line_points = []
        self.preview_line_item = None
        self.snap_indicator = None
        self.snap_radius = 10
        self.is_drawing_object = False
        self.object_start_pos = None
        self.preview_object_item = None
        self.current_object_parent_id = None
        self.is_y_locked = False
        self.locked_position = None # (x, y) 좌표를 저장할 QPointF
        self.y_indicator_line = None
        self.lock_coord_text_item = None
        self.is_x_locked = False
        self.x_indicator_line = None
        self._initial_fit_done = False
        # v10.0.0: 새로운 미리보기 아이템들
        self.preview_waypoint_item = None
        self.is_drawing_jump_link = False
        self.jump_link_start_pos = None
        self.preview_jump_link_item = None
        # [신규] 사냥범위 드로잉 상태
        self.is_drawing_hunt_zone = False
        self.hunt_zone_start_pos = None
        self.preview_hunt_zone_item = None
        self.feature_color_map = self._create_feature_color_map()
        
        # ==================== v10.6.0 ====================
        # 그리기 상태 변수
        self.current_mode = "select" # "select", "terrain", "object", "waypoint", "jump"
        
        # 지형 그리기 상태
        self.is_drawing_line = False
        self.current_line_points = []
        self.preview_line_item = None
        
        # 층 이동 오브젝트 그리기 상태
        self.is_drawing_object = False
        self.object_start_info = None # {'pos': QPointF, 'line_id': str}
        self.preview_object_item = None

        # 웨이포인트/점프 그리기 상태
        self.preview_waypoint_item = None
        self.is_drawing_jump_link = False
        self.jump_link_start_pos = None
        self.preview_jump_link_item = None

        # 공통 그리기 상태
        self.snap_indicator = None
        self.snap_radius = 15 # v10.6.0: 10 -> 15로 변경 및 스냅 반경 상수화
        self.is_y_locked = False
        self.locked_position = None
        self.y_indicator_line = None
        self.is_x_locked = False
        self.x_indicator_line = None # v10.6.0: x_indicator_line 추가
        self._initial_fit_done = False
        
        self.feature_color_map = self._create_feature_color_map()

        self.initUI()
        self.populate_scene()
        self._update_visibility()

    def _ensure_waypoint_event_fields(self):
        for waypoint in self.geometry_data.get("waypoints", []):
            if 'is_event' not in waypoint:
                waypoint['is_event'] = False
            if 'event_profile' not in waypoint or waypoint['event_profile'] is None:
                waypoint['event_profile'] = ""
            if 'event_always' not in waypoint:
                waypoint['event_always'] = False


    def _get_floor_from_closest_terrain(self, point, terrain_lines):
            """주어진 점에서 가장 가까운 지형선을 찾아 그 층 번호를 반환합니다."""
            min_dist_sq = float('inf')
            closest_floor = 0.0  # 기본값

            for line_data in terrain_lines:
                points = line_data.get("points", [])
                for i in range(len(points) - 1):
                    p1 = QPointF(points[i][0], points[i][1])
                    p2 = QPointF(points[i+1][0], points[i+1][1])
                    
                    # 선분과의 거리 제곱 계산 (sqrt를 피하기 위해 제곱으로 비교)
                    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                    if dx == 0 and dy == 0:
                        dist_sq = (point.x() - p1.x())**2 + (point.y() - p1.y())**2
                    else:
                        t = ((point.x() - p1.x()) * dx + (point.y() - p1.y()) * dy) / (dx**2 + dy**2)
                        t = max(0, min(1, t))
                        closest_point_on_segment = QPointF(p1.x() + t * dx, p1.y() + t * dy)
                        dist_sq = (point.x() - closest_point_on_segment.x())**2 + (point.y() - closest_point_on_segment.y())**2

                    if dist_sq < min_dist_sq:
                        min_dist_sq = dist_sq
                        closest_floor = line_data.get('floor', 0.0)
            
            return closest_floor

    def _update_all_floor_texts(self):
            # 기존 층 번호 텍스트 모두 삭제
            items_to_remove = []
            for item in self.scene.items():
                if item.data(0) in ["floor_text", "floor_text_bg"]:
                    items_to_remove.append(item)
            
            for item in items_to_remove:
                self.scene.removeItem(item)

            # 기존 층 이름 리더 라인 삭제 및 그룹 정리
            if hasattr(self, "_name_label_groups"):
                for g in list(self._name_label_groups):
                    if g.get("type") == "floor_text":
                        leader = g.get("leader")
                        if leader and leader.scene() is not None:
                            self.scene.removeItem(leader)
                # 해당 타입 그룹 제거 (재생성 예정)
                self._name_label_groups = [g for g in self._name_label_groups if g.get("type") != "floor_text"]

            from collections import defaultdict, deque
            terrain_lines = self.geometry_data.get("terrain_lines", [])
            if not terrain_lines: return

            adj = defaultdict(list)
            lines_by_id = {line['id']: line for line in terrain_lines}
            point_to_lines = defaultdict(list)
            for line in terrain_lines:
                for p in line['points']:
                    point_to_lines[tuple(p)].append(line['id'])
            for p, ids in point_to_lines.items():
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        adj[ids[i]].append(ids[j])
                        adj[ids[j]].append(ids[i])
            visited = set()
            groups = []
            for line_id in lines_by_id:
                if line_id not in visited:
                    current_group_data = []
                    q = deque([line_id])
                    visited.add(line_id)
                    while q:
                        current_id = q.popleft()
                        current_group_data.append(lines_by_id[current_id])
                        for neighbor_id in adj[current_id]:
                            if neighbor_id not in visited:
                                visited.add(neighbor_id)
                                q.append(neighbor_id)
                    groups.append(current_group_data)

            for group in groups:
                if not group: continue
                
                all_points_x = [p[0] for line_data in group for p in line_data.get("points", [])]
                max_y = max(p[1] for line_data in group for p in line_data.get("points", [])) if any(line_data.get("points") for line_data in group) else 0
                
                if not all_points_x: continue
                center_x = sum(all_points_x) / len(all_points_x)
                
                floor_text = group[0].get('dynamic_name', f"{group[0].get('floor', 'N/A')}층")
                font = QFont("맑은 고딕", 3, QFont.Weight.Bold) # 웨이포인트 수준의 기본 크기

                text_item = QGraphicsTextItem(floor_text)
                text_item.setFont(font)
                text_item.setDefaultTextColor(Qt.GlobalColor.white)
                
                # 마우스 이벤트 무시 설정 (클릭 버그 수정)
                text_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

                text_rect = text_item.boundingRect()
                padding_x = -3 # 미니맵 지형 편집기 층 이름 텍스트 박스 크기 조절
                padding_y = -3
                bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

                # 요청: 지형의 이름은 충돌회피 없이 항상 가운데 아래에 고정 배치 (점프링크 이름과 너무 멀지 않게 조금만 아래)
                base_pos_x = center_x - bg_rect_geom.width() / 2
                base_pos_y = max_y + 8

                background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
                background_rect.setBrush(QColor(0, 0, 0, 120))
                background_rect.setPen(QPen(Qt.GlobalColor.transparent))
                background_rect.setPos(base_pos_x, base_pos_y)

                background_rect.setData(0, "floor_text_bg")
                text_item.setData(0, "floor_text")
                
                background_rect.setZValue(5)
                text_item.setZValue(6)

                self.scene.addItem(background_rect)
                # 텍스트 위치를 배경 중앙 정렬로 배치
                text_item.setPos(base_pos_x + padding_x, base_pos_y + padding_y)
                self.scene.addItem(text_item)
                # 미니맵 지형 편집기 층 이름 LOD 적용 대상 리스트에 추가 ---
                self.lod_text_items.append(background_rect)
                self.lod_text_items.append(text_item)
                # 충돌회피에 참여하지 않음. 단, 다른 라벨 배치 시 장애물로는 취급됨.

    def _draw_text_with_outline(self, painter, rect, flags, text, font, text_color, outline_color):
        """지정한 사각형 영역에 테두리가 있는 텍스트를 그립니다."""
        painter.save()
        painter.setFont(font)
        painter.setPen(outline_color)
        painter.drawText(rect.translated(1, 1), flags, text)
        painter.drawText(rect.translated(-1, -1), flags, text)
        painter.drawText(rect.translated(1, -1), flags, text)
        painter.drawText(rect.translated(-1, 1), flags, text)
        painter.setPen(text_color)
        painter.drawText(rect, flags, text)
        painter.restore()

    def showEvent(self, event):
        """다이얼로그가 화면에 표시될 때 초기 배율을 설정합니다."""
        super().showEvent(event)
        if not self._initial_fit_done:
            bounding_rect = self.scene.itemsBoundingRect()
            if not bounding_rect.isNull():
                bounding_rect.adjust(-50, -50, 50, 50)
                self.view.fitInView(bounding_rect, Qt.AspectRatioMode.KeepAspectRatio)
                self.view.scale(1.4, 1.4) #미니맵 지형 편집기 초기 배율 확대 1.0 기본
            self._initial_fit_done = True
            self._update_lod_visibility()
            
    def initUI(self):
        main_layout = QHBoxLayout(self)

        # 좌측: 도구 모음
        toolbar_group = QGroupBox("도구")
        toolbar_layout = QVBoxLayout()
        toolbar_group.setLayout(toolbar_layout)
        toolbar_group.setFixedWidth(220)

        # v10.0.0: 층 관리 UI
        floor_box = QGroupBox("현재 편집 층")
        floor_layout = QHBoxLayout()
        self.floor_spinbox = QDoubleSpinBox()
        self.floor_spinbox.setRange(0, 1000)
        self.floor_spinbox.setDecimals(1)
        self.floor_spinbox.setSingleStep(1.0)
        self.floor_spinbox.setValue(1.0)
        floor_layout.addWidget(self.floor_spinbox)
        floor_box.setLayout(floor_layout)

        # 편집 모드
        mode_box = QGroupBox("편집 모드")
        mode_layout = QVBoxLayout()
        self.select_mode_radio = QRadioButton("기본 (Q)") 
        self.terrain_mode_radio = QRadioButton("지형 입력 (T)")
        self.object_mode_radio = QRadioButton("층 이동 오브젝트 추가 (O)")
        self.waypoint_mode_radio = QRadioButton("웨이포인트 추가 (W)")
        self.jump_mode_radio = QRadioButton("지형 점프 연결 (J)")
        self.forbidden_wall_mode_radio = QRadioButton("금지벽 추가 (F)")
        # [신규] 사냥범위 조절칸 추가 모드
        self.hunt_zone_mode_radio = QRadioButton("사냥범위 조절칸 추가 (H)")
        self.select_mode_radio.setChecked(True)
        self.select_mode_radio.toggled.connect(lambda: self.set_mode("select"))
        self.terrain_mode_radio.toggled.connect(lambda: self.set_mode("terrain"))
        self.object_mode_radio.toggled.connect(lambda: self.set_mode("object"))
        self.waypoint_mode_radio.toggled.connect(lambda: self.set_mode("waypoint"))
        self.jump_mode_radio.toggled.connect(lambda: self.set_mode("jump"))
        self.forbidden_wall_mode_radio.toggled.connect(lambda: self.set_mode("forbidden_wall"))
        self.hunt_zone_mode_radio.toggled.connect(lambda: self.set_mode("hunt_zone"))
        mode_layout.addWidget(self.select_mode_radio)
        mode_layout.addWidget(self.terrain_mode_radio)
        mode_layout.addWidget(self.object_mode_radio)
        mode_layout.addWidget(self.waypoint_mode_radio)
        mode_layout.addWidget(self.jump_mode_radio)
        mode_layout.addWidget(self.forbidden_wall_mode_radio)
        mode_layout.addWidget(self.hunt_zone_mode_radio)
        mode_box.setLayout(mode_layout)

        # 지형 입력 옵션
        terrain_opts_box = QGroupBox("지형 옵션")
        terrain_opts_layout = QVBoxLayout()
        self.y_lock_check = QCheckBox("Y축 고정") 
        self.x_lock_check = QCheckBox("X축 고정")
        self.y_lock_check.toggled.connect(self.on_y_lock_toggled)
        self.x_lock_check.toggled.connect(self.on_x_lock_toggled)
        # 요청: 기본적으로 체크되어 있도록 설정
        self.y_lock_check.setChecked(True)
        self.x_lock_check.setChecked(True)
        terrain_opts_layout.addWidget(self.y_lock_check)
        terrain_opts_layout.addWidget(self.x_lock_check)
        terrain_opts_box.setLayout(terrain_opts_layout)

        # 뷰 옵션
        view_opts_box = QGroupBox("보기 옵션")
        view_opts_layout = QVBoxLayout()
        
        self.chk_show_background = QCheckBox("미니맵 배경")
        self.chk_show_background.setChecked(self.render_options.get('background', True))
        self.chk_show_background.stateChanged.connect(self._update_visibility)
        
        self.chk_show_features = QCheckBox("핵심 지형")
        self.chk_show_features.setChecked(self.render_options.get('features', True))
        self.chk_show_features.stateChanged.connect(self._update_visibility)
        
        self.chk_show_waypoints = QCheckBox("웨이포인트")
        self.chk_show_waypoints.setChecked(self.render_options.get('waypoints', True))
        self.chk_show_waypoints.stateChanged.connect(self._update_visibility)
        
        self.chk_show_terrain = QCheckBox("지형선")
        self.chk_show_terrain.setChecked(self.render_options.get('terrain', True))
        self.chk_show_terrain.stateChanged.connect(self._update_visibility)
        
        self.chk_show_objects = QCheckBox("층 이동 오브젝트")
        self.chk_show_objects.setChecked(self.render_options.get('objects', True))
        self.chk_show_objects.stateChanged.connect(self._update_visibility)
        
        # v10.0.0: 지형 점프 연결 보기 옵션 추가
        self.chk_show_jump_links = QCheckBox("지형 점프 연결")
        self.chk_show_jump_links.setChecked(self.render_options.get('jump_links', True))
        self.chk_show_jump_links.stateChanged.connect(self._update_visibility)
        # 좌표 라벨 표시 옵션 (LOD 대신)
        self.chk_show_coords = QCheckBox("좌표 라벨")
        self.chk_show_coords.setChecked(self.render_options.get('coords', True))
        self.chk_show_coords.stateChanged.connect(self._update_lod_visibility)

        self.chk_show_forbidden_walls = QCheckBox("금지벽")
        self.chk_show_forbidden_walls.setChecked(self.render_options.get('forbidden_walls', True))
        self.chk_show_forbidden_walls.stateChanged.connect(self._update_visibility)
        # [신규] 사냥범위 표시 토글
        self.chk_show_hunt_zones = QCheckBox("사냥범위")
        self.chk_show_hunt_zones.setChecked(self.render_options.get('hunt_zones', True))
        self.chk_show_hunt_zones.stateChanged.connect(self._update_visibility)

        zoom_layout = QHBoxLayout()
        zoom_in_btn = QPushButton("확대")
        zoom_out_btn = QPushButton("축소")
        
        #버튼 클릭 시 LOD 업데이트 함수 호출 추가
        def zoom_in_and_update():
            self.view.scale(1.2, 1.2)
            self._update_lod_visibility()

        def zoom_out_and_update():
            self.view.scale(1/1.2, 1/1.2)
            self._update_lod_visibility()

        zoom_in_btn.clicked.connect(zoom_in_and_update)
        zoom_out_btn.clicked.connect(zoom_out_and_update)
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addWidget(zoom_out_btn)

        view_opts_layout.addWidget(self.chk_show_background)
        view_opts_layout.addWidget(self.chk_show_features)
        view_opts_layout.addWidget(self.chk_show_waypoints)
        view_opts_layout.addWidget(self.chk_show_terrain)
        view_opts_layout.addWidget(self.chk_show_objects)
        view_opts_layout.addWidget(self.chk_show_jump_links)
        view_opts_layout.addWidget(self.chk_show_coords)
        view_opts_layout.addWidget(self.chk_show_forbidden_walls)
        view_opts_layout.addWidget(self.chk_show_hunt_zones)
        view_opts_layout.addLayout(zoom_layout)
        view_opts_box.setLayout(view_opts_layout)

        toolbar_layout.addWidget(floor_box)
        toolbar_layout.addWidget(mode_box)
        toolbar_layout.addWidget(terrain_opts_box)
        toolbar_layout.addWidget(view_opts_box)
        toolbar_layout.addStretch(1)

        # 우측: 그래픽 뷰 (캔버스)
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor(50, 50, 50)))
        self.view = CustomGraphicsView(self.scene, parent_dialog=self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.mousePressed.connect(self.on_scene_mouse_press)
        self.view.mouseMoved.connect(self.on_scene_mouse_move)
        
        self.view.zoomChanged.connect(self._update_lod_visibility)
        
        # 하단 버튼
        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.view)
        right_layout.addWidget(dialog_buttons)

        main_layout.addWidget(toolbar_group)
        main_layout.addLayout(right_layout, 1)

    def get_current_view_options(self):
        """현재 보기 옵션 체크박스 상태를 딕셔너리로 반환합니다."""
        return {
            'background': self.chk_show_background.isChecked(),
            'features': self.chk_show_features.isChecked(),
            'waypoints': self.chk_show_waypoints.isChecked(),
            'terrain': self.chk_show_terrain.isChecked(),
            'objects': self.chk_show_objects.isChecked(),
            'jump_links': self.chk_show_jump_links.isChecked(),
            'coords': getattr(self, 'chk_show_coords', None).isChecked() if hasattr(self, 'chk_show_coords') else True,
            'forbidden_walls': self.chk_show_forbidden_walls.isChecked(),
            'hunt_zones': self.chk_show_hunt_zones.isChecked() if hasattr(self, 'chk_show_hunt_zones') else True,
        }
        
    def set_mode(self, mode):
        """편집기 모드를 변경하고 UI를 업데이트합니다."""
        self.current_mode = mode
        if self.is_drawing_line:
            self._finish_drawing_line()
        if self.is_drawing_object:
            self._finish_drawing_object(cancel=True)
        # 사냥범위 드로잉 취소
        if getattr(self, 'is_drawing_hunt_zone', False):
            if getattr(self, 'preview_hunt_zone_item', None) and self.preview_hunt_zone_item in self.scene.items():
                self.scene.removeItem(self.preview_hunt_zone_item)
            self.preview_hunt_zone_item = None
            self.is_drawing_hunt_zone = False
            self.hunt_zone_start_pos = None

        if mode != "select":
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.setCursor(Qt.CursorShape.CrossCursor)
        else: # select
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
            
    def on_x_lock_toggled(self, checked):
        self.is_x_locked = checked
        
    def on_y_lock_toggled(self, checked):
        self.is_y_locked = checked
        if not checked and self.y_indicator_line:
            self.y_indicator_line.setVisible(False)
        elif checked and self.y_indicator_line and self.locked_position is not None:
            self.y_indicator_line.setVisible(True)

    def update_locked_position(self, global_pos):
        self.locked_position = global_pos
        y_pos = global_pos.y()
        x_pos = global_pos.x()
        
        pen = QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine)
        coord_font = QFont("맑은 고딕", 2, QFont.Weight.Bold)
        
        # Y축 고정선
        if not self.y_indicator_line:
            self.y_indicator_line = self.scene.addLine(0, 0, 1, 1, pen)
            self.y_indicator_line.setZValue(200)

        # X축 고정선
        if not self.x_indicator_line:
            self.x_indicator_line = self.scene.addLine(0, 0, 1, 1, pen)
            self.x_indicator_line.setZValue(200)

        # [MODIFIED] 씬 경계 대신 현재 보이는 뷰포트 영역을 기준으로 라인을 그림
        view_rect = self.view.viewport().rect()
        scene_visible_rect = self.view.mapToScene(view_rect).boundingRect()

        if not scene_visible_rect.isValid(): return
        
        # Y축 고정선 업데이트
        if self.y_indicator_line and self.y_indicator_line.scene():
            self.y_indicator_line.setLine(scene_visible_rect.left(), y_pos, scene_visible_rect.right(), y_pos)
            self.y_indicator_line.setVisible(self.is_y_locked)
            
        # X축 고정선 업데이트
        if self.x_indicator_line and self.x_indicator_line.scene():
            self.x_indicator_line.setLine(x_pos, scene_visible_rect.top(), x_pos, scene_visible_rect.bottom())
            self.x_indicator_line.setVisible(self.is_x_locked)

        # [v11.2.4] X/Y축 고정 좌표 텍스트 (QGraphicsSimpleTextItem으로 변경)
        if not self.lock_coord_text_item:
            # QGraphicsSimpleTextItem은 더 가볍고 안정적임
            self.lock_coord_text_item = QGraphicsSimpleTextItem()
            self.lock_coord_text_item.setFont(coord_font)
            self.lock_coord_text_item.setBrush(QColor("red"))
            self.lock_coord_text_item.setZValue(201)
            self.scene.addItem(self.lock_coord_text_item)
            self.lod_coord_items.append(self.lock_coord_text_item)

        # 텍스트 내용 동적 생성
        text_parts = []
        if self.is_x_locked:
            text_parts.append(f"X: {x_pos:.1f}")
        if self.is_y_locked:
            text_parts.append(f"Y: {y_pos:.1f}")
        
        full_text = "  ".join(text_parts)
        self.lock_coord_text_item.setText(full_text)
        
        # 위치 업데이트 (교차점 우측 하단)
        self.lock_coord_text_item.setPos(x_pos + 5, y_pos + 5)
        
        # 가시성 업데이트 (둘 중 하나라도 켜져 있으면 보이도록)
        self.lock_coord_text_item.setVisible(self.is_x_locked or self.is_y_locked)
        
        # LOD 업데이트 강제 호출
        self._update_lod_visibility()

    def _create_feature_color_map(self):
        """핵심 지형 ID별로 고유한 색상을 할당합니다."""
        color_map = {}
        colors = [
            QColor("#FF5733"), QColor("#33FF57"), QColor("#3357FF"),
            QColor("#FF33A1"), QColor("#A133FF"), QColor("#33FFA1"),
            QColor("#FFC300"), QColor("#DAF7A6"), QColor("#FFC0CB")
        ]
        sorted_features = sorted(self.key_features.keys())
        for i, feature_id in enumerate(sorted_features):
            color_map[feature_id] = colors[i % len(colors)]
        return color_map

    #MapTab의 _assign_dynamic_names 메서드를 여기에 복사 ---
    def _assign_dynamic_names(self):
        """
        (Dialog 내부용) 현재 편집 중인 geometry_data에 동적 이름을 부여합니다.
        """
        if not self.geometry_data:
            return

        terrain_lines = self.geometry_data.get("terrain_lines", [])
        lines_by_id = {line['id']: line for line in terrain_lines}
        line_id_to_group_name = {}

        if terrain_lines:
            adj = defaultdict(list)
            point_to_lines = defaultdict(list)
            for line in terrain_lines:
                for p in line['points']:
                    point_to_lines[tuple(p)].append(line['id'])
            
            for p, ids in point_to_lines.items():
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        adj[ids[i]].append(ids[j])
                        adj[ids[j]].append(ids[i])

            visited = set()
            all_groups = []
            for line_id in lines_by_id:
                if line_id not in visited:
                    current_group = []
                    q = deque([line_id])
                    visited.add(line_id)
                    while q:
                        current_id = q.popleft()
                        current_group.append(lines_by_id[current_id])
                        for neighbor_id in adj[current_id]:
                            if neighbor_id not in visited:
                                visited.add(neighbor_id)
                                q.append(neighbor_id)
                    all_groups.append(current_group)

            groups_by_floor = defaultdict(list)
            for group in all_groups:
                if group:
                    floor = group[0].get('floor', 0)
                    groups_by_floor[floor].append(group)
            
            for floor, groups in groups_by_floor.items():
                sorted_groups = sorted(groups, key=lambda g: sum(p[0] for line in g for p in line['points']) / sum(len(line['points']) for line in g))
                
                for i, group in enumerate(sorted_groups):
                    group_name = f"{floor}층_{chr(ord('A') + i)}"
                    for line in group:
                        line['dynamic_name'] = group_name
                        line_id_to_group_name[line['id']] = group_name

        transition_objects = self.geometry_data.get("transition_objects", [])
        if transition_objects:
            objs_by_parent_group = defaultdict(list)
            for obj in transition_objects:
                parent_id = obj.get('parent_line_id')
                if parent_id and parent_id in line_id_to_group_name:
                    parent_group_name = line_id_to_group_name[parent_id]
                    objs_by_parent_group[parent_group_name].append(obj)

            for parent_name, objs in objs_by_parent_group.items():
                sorted_objs = sorted(objs, key=lambda o: o['points'][0][0])
                for i, obj in enumerate(sorted_objs):
                    obj['dynamic_name'] = f"{parent_name}_{i + 1}"

        # --- 3. 지형 점프 연결 이름 부여 (v10.0.1 로직 개편 및 안정성 강화) ---
        jump_links = self.geometry_data.get("jump_links", [])
        if jump_links:
            try:
                # 1. 모든 지형선 꼭짓점의 위치와 층 정보를 매핑
                vertex_to_floor_map = {}
                for line in terrain_lines:
                    floor = line.get('floor', 0)
                    for p in line['points']:
                        vertex_to_floor_map[tuple(p)] = floor

                # 2. 각 점프 링크의 시작/종료 층 정보 찾기
                for jump in jump_links:
                    start_pos_tuple = tuple(jump['start_vertex_pos'])
                    end_pos_tuple = tuple(jump['end_vertex_pos'])

                    start_floor = vertex_to_floor_map.get(start_pos_tuple)
                    end_floor = vertex_to_floor_map.get(end_pos_tuple)

                    # Fallback: 만약 꼭짓점 맵에 없다면, 가장 가까운 지형선에서 층 정보 추론
                    if start_floor is None:
                        start_floor = self._get_floor_from_closest_terrain(QPointF(start_pos_tuple[0], start_pos_tuple[1]), terrain_lines)
                    if end_floor is None:
                        end_floor = self._get_floor_from_closest_terrain(QPointF(end_pos_tuple[0], end_pos_tuple[1]), terrain_lines)

                    # 층 번호를 정렬하여 그룹 키로 사용
                    floor_key = tuple(sorted((start_floor, end_floor)))
                    jump['temp_floor_key'] = floor_key

                # 3. (시작층, 종료층) 그룹별로 이름 부여
                jumps_by_floor_pair = defaultdict(list)
                for jump in jump_links:
                    jumps_by_floor_pair[jump['temp_floor_key']].append(jump)

                for floor_pair, jumps in jumps_by_floor_pair.items():
                    sorted_jumps = sorted(jumps, key=lambda j: (j['start_vertex_pos'][0] + j['end_vertex_pos'][0]) / 2)
                    
                    f1_str = f"{floor_pair[0]:g}"
                    f2_str = f"{floor_pair[1]:g}"
                    
                    for i, jump in enumerate(sorted_jumps):
                        jump['dynamic_name'] = f"{f1_str}층_{f2_str}층{chr(ord('A') + i)}"
                        if 'temp_floor_key' in jump:
                            del jump['temp_floor_key']
            except Exception as e:
                print(f"Error assigning dynamic names to jump links: {e}")

    # [v11.2.0] 좌표 텍스트와 배경을 생성하는 헬퍼 메서드
    def _create_coord_text_item(self, text, color, font):
        """
        좌표 텍스트와 텍스트에 딱 맞는 모서리 둥근 반투명 배경 아이템을 각각 생성하여
        튜플 (background_item, text_item) 형태로 반환합니다.
        [v11.2.8] 텍스트/배경 분리 반환 및 패딩 조정
        """
        if font is None:
            fixed_font = QFont("맑은 고딕", 2)
        else:
            fixed_font = font

        text_item = QGraphicsTextItem(text)
        text_item.setFont(fixed_font)
        text_item.setDefaultTextColor(color)

        fm = QFontMetricsF(fixed_font)
        text_rect = fm.boundingRect(text)

        # [v11.2.8] 패딩 조정 (좌우 1px, 상하 0px)
        pad_x = 1
        pad_y = 0

        bg_width = text_rect.width() + pad_x * 2
        bg_height = text_rect.height() + pad_y * 2
        bg_rect_geom = QRectF(0, 0, bg_width, bg_height)

        background_item = RoundedRectItem(bg_rect_geom, 4, 4)
        background_item.setBrush(QColor(0, 0, 0, 170))
        background_item.setPen(QPen(Qt.GlobalColor.transparent))

        background_item.setData(0, "coord_text_bg")
        text_item.setData(0, "coord_text")
        background_item.setZValue(11)
        text_item.setZValue(12)

        # [v11.2.8] 두 아이템을 독립적으로 반환
        return background_item, text_item
    
    # --- 좌표 라벨 배치 유틸리티 (겹침 방지 + 재배치 지원) ---
    def _place_coord_label_items(self, bg_item, text_item, anchor_point: QPointF, placed_rects: list, preferred: str = "above", allowed_directions: list[str] | None = None, max_steps: int = 12) -> None:
        """
        좌표 라벨 배경/텍스트 아이템의 위치를 anchor_point 주변으로 배치한다.
        이미 배치된 placed_rects와의 충돌을 피하며, 선호 방향(preferred)을 우선 시도한다.
        preferred: "above"|"below"
        allowed_directions: 지정 시 해당 방향만 사용 (예: ["below"]).
        """
        current_zoom = max(self.view.transform().m11(), 1e-6)
        # 좌표 라벨과의 기본 간격(px). 너무 멀어지지 않도록 6px로 조정
        gap_px = 6.0
        gap_scene = gap_px / current_zoom

        bg_rect_local = bg_item.boundingRect()
        w, h = bg_rect_local.width(), bg_rect_local.height()

        def make_pos(direction: str, shift_idx: int = 0) -> QPointF:
            if direction == "above":
                return QPointF(anchor_point.x() - w / 2, anchor_point.y() - h - gap_scene - shift_idx * (h + gap_scene))
            # below
            return QPointF(anchor_point.x() - w / 2, anchor_point.y() + gap_scene + shift_idx * (h + gap_scene))

        opposite = "below" if preferred == "above" else "above"
        directions = allowed_directions if allowed_directions else [preferred, opposite]

        def overlaps(rect: QRectF) -> bool:
            # 여유 간격을 반영한 충돌 검사
            inflated = rect.adjusted(-gap_scene/2, -gap_scene/2, gap_scene/2, gap_scene/2)
            return any(inflated.intersects(r) for r in placed_rects)

        placed = False
        for d in directions:
            for s in range(0, max_steps):
                pos = make_pos(d, s)
                bg_item.setPos(pos)
                # 텍스트는 배경 중앙에 정렬
                text_rect_local = text_item.boundingRect()
                text_item.setPos(
                    bg_item.x() + (w - text_rect_local.width()) / 2,
                    bg_item.y() + (h - text_rect_local.height()) / 2,
                )
                rect_scene = bg_item.sceneBoundingRect()
                if not overlaps(rect_scene):
                    placed_rects.append(rect_scene)
                    placed = True
                    break
            if placed:
                break

        if not placed:
            # 마지막 수단: preferred 위치에 고정(충돌 허용)
            pos = make_pos(preferred, 0)
            bg_item.setPos(pos)
            text_rect_local = text_item.boundingRect()
            text_item.setPos(
                bg_item.x() + (w - text_rect_local.width()) / 2,
                bg_item.y() + (h - text_rect_local.height()) / 2,
            )

    def _relayout_all_labels(self) -> None:
        """좌표/이름/피처 라벨을 하나의 충돌 회피 패스로 재배치한다 (웨이포인트 라벨 제외)."""
        coord_groups = getattr(self, "_coord_label_groups", []) or []
        name_groups = getattr(self, "_name_label_groups", []) or []
        # 우선순위: 이름 라벨 먼저, 좌표 라벨 나중 (이름 가독성 우선)
        combined = list(name_groups) + list(coord_groups)
        if not combined:
            return
        placed_rects: list[QRectF] = []
        # 웨이포인트 라벨은 그대로 두되, 충돌 회피 시에는 장애물로 취급하여 겹치지 않도록 함
        try:
            for item in self.scene.items():
                if item.data(0) in ("waypoint_lod_text", "floor_text", "floor_text_bg") and item.isVisible():
                    placed_rects.append(item.sceneBoundingRect())
        except Exception:
            pass
        # 좌표 라벨은 아래쪽을 우선 시도하고, 불가할 때만 위쪽으로 시도
        for group in combined:
            anchor = group["anchor"]
            bg_item = group["bg"]
            text_item = group["text"]
            preferred = group.get("preferred", "above")
            label_type = group.get("type", "")
            allowed = None
            if label_type == "jump_link_name":
                # 요청: 점프 링크는 항상 바로 아래 고정 배치
                fixed_base = group.get("fixed_base")
                if fixed_base:
                    # 배경/텍스트 크기 산출 후 바로 아래 위치로 고정
                    bg_rect_local = bg_item.boundingRect()
                    w, h = bg_rect_local.width(), bg_rect_local.height()
                    base_x = fixed_base.get("center_x", anchor.x()) - w / 2
                    # 요청: 점프링크 바로 밑에 더 가깝게 위치하도록 오프셋 축소
                    base_y = fixed_base.get("bottom_y", anchor.y()) + 2
                    bg_item.setPos(base_x, base_y)
                    text_rect_local = text_item.boundingRect()
                    text_item.setPos(
                        bg_item.x() + (w - text_rect_local.width()) / 2,
                        bg_item.y() + (h - text_rect_local.height()) / 2,
                    )
                    placed_rects.append(bg_item.sceneBoundingRect())
                    # 리더 라인 업데이트(고정)
                    rect_scene = bg_item.sceneBoundingRect()
                    left, right, top, bottom = rect_scene.left(), rect_scene.right(), rect_scene.top(), rect_scene.bottom()
                    cx = min(max(anchor.x(), left), right)
                    cy = min(max(anchor.y(), top), bottom)
                    distances = [
                        (abs(cx - left), QPointF(left, cy)),
                        (abs(cx - right), QPointF(right, cy)),
                        (abs(cy - top), QPointF(cx, top)),
                        (abs(cy - bottom), QPointF(cx, bottom)),
                    ]
                    _, target = min(distances, key=lambda t: t[0])
                    if "leader" not in group or group["leader"] is None or group["leader"].scene() is None:
                        line_item = self.scene.addLine(anchor.x(), anchor.y(), target.x(), target.y(), QPen(QColor("red"), 0))
                        line_item.setZValue(9)
                        line_item.setData(0, "jump_link_name_leader")
                        group["leader"] = line_item
                        if line_item not in self.lod_text_items:
                            self.lod_text_items.append(line_item)
                    else:
                        group["leader"].setLine(anchor.x(), anchor.y(), target.x(), target.y())
                    # 점프 링크는 고정 배치이므로 일반 배치 로직 건너뜀
                    continue
                else:
                    allowed = ["below"]
            elif label_type == "coord_text":
                # 좌표 라벨은 아래쪽을 우선(필요 시 위쪽)으로만 분산
                preferred = "below"
                allowed = ["below", "above"]
            # 위치 배치 (충돌 회피)
            max_steps = 8 if label_type == "coord_text" else 12
            self._place_coord_label_items(bg_item, text_item, anchor, placed_rects, preferred, allowed, max_steps)
            # 리더 라인 업데이트
            rect_scene = bg_item.sceneBoundingRect()
            left, right, top, bottom = rect_scene.left(), rect_scene.right(), rect_scene.top(), rect_scene.bottom()
            cx = min(max(anchor.x(), left), right)
            cy = min(max(anchor.y(), top), bottom)
            distances = [
                (abs(cx - left), QPointF(left, cy)),
                (abs(cx - right), QPointF(right, cy)),
                (abs(cy - top), QPointF(cx, top)),
                (abs(cy - bottom), QPointF(cx, bottom)),
            ]
            _, target = min(distances, key=lambda t: t[0])
            if "leader" not in group or group["leader"] is None or group["leader"].scene() is None:
                # 타입별 색상: 좌표=흰색, 점프링크=초록, 사다리/오브젝트=주황, 그 외=빨강
                pen = QPen(QColor("red"), 0)
                if label_type == "coord_text":
                    pen = QPen(QColor("white"), 0)
                elif label_type == "jump_link_name":
                    pen = QPen(QColor("green"), 0)
                elif label_type == "transition_object_name":
                    pen = QPen(QColor("orange"), 0)
                line_item = self.scene.addLine(anchor.x(), anchor.y(), target.x(), target.y(), pen)
                line_item.setZValue(9)
                # 타입별로 data 설정
                if label_type == "transition_object_name":
                    line_item.setData(0, "transition_object_name_leader")
                    if line_item not in self.lod_text_items:
                        self.lod_text_items.append(line_item)
                elif label_type == "jump_link_name":
                    line_item.setData(0, "jump_link_name_leader")
                    if line_item not in self.lod_text_items:
                        self.lod_text_items.append(line_item)
                elif label_type == "floor_text":
                    line_item.setData(0, "floor_text_leader")
                    if line_item not in self.lod_text_items:
                        self.lod_text_items.append(line_item)
                elif label_type == "feature_name":
                    line_item.setData(0, "feature_name_leader")
                    # feature 리더는 LOD 리스트에 넣지 않음 (기존 feature 가시성 정책 유지)
                else:
                    # 좌표 라벨 등
                    line_item.setData(0, "coord_text_leader")
                    if line_item not in self.lod_coord_items:
                        self.lod_coord_items.append(line_item)
                group["leader"] = line_item
            else:
                group["leader"].setLine(anchor.x(), anchor.y(), target.x(), target.y())
                # 타입별 색상 갱신
                pen = None
                if label_type == "coord_text":
                    pen = QPen(QColor("white"), 0)
                elif label_type == "jump_link_name":
                    pen = QPen(QColor("green"), 0)
                elif label_type == "transition_object_name":
                    pen = QPen(QColor("orange"), 0)
                if pen is not None:
                    group["leader"].setPen(pen)
    
    def populate_scene(self):
                self.scene.clear()
                # --- v10.3.4 수정: 씬 아이템을 참조하는 멤버 변수 초기화 ---
                # [v11.3.2 BUGFIX] RuntimeError 방지를 위해 초기화 강화
                self.snap_indicator = None
                self.preview_waypoint_item = None
                self.lod_text_items = []
                self.y_indicator_line = None
                self.x_indicator_line = None
                
                # [v11.1.0] 좌표 텍스트 아이템 리스트 초기화
                self.lod_coord_items = []
                # [v11.3.2] lock_coord_text_item 초기화를 명시적으로 수행
                self.lock_coord_text_item = None
                # 좌표 라벨 그룹(재배치용) 초기화
                self._coord_label_groups = []
                # 이름 라벨 그룹(재배치용) 초기화
                self._name_label_groups = []
                
                # 1. 배경 이미지 설정
                if self.parent_map_tab.full_map_pixmap and not self.parent_map_tab.full_map_pixmap.isNull():
                    background_item = self.scene.addPixmap(self.parent_map_tab.full_map_pixmap)
                    background_item.setPos(self.parent_map_tab.full_map_bounding_rect.topLeft())
                    background_item.setZValue(-100)
                    background_item.setData(0, "background")
                else:
                    text_item = self.scene.addText("배경 맵을 생성할 수 없습니다.\n핵심 지형을 1개 이상 등록하고, 문맥 이미지가 있는지 확인해주세요.")
                    text_item.setDefaultTextColor(Qt.GlobalColor.white)
                    return

                # 2. 핵심 지형 그리기
                if self.global_positions:
                    for item_id, pos in self.global_positions.items():
                        if item_id in self.key_features:
                            feature_data = self.key_features[item_id]
                            img_data = base64.b64decode(feature_data['image_base64'])
                            pixmap = QPixmap(); pixmap.loadFromData(img_data)
                            rect_item = self.scene.addRect(0, 0, pixmap.width(), pixmap.height(), QPen(QColor(0, 255, 255)), QBrush(QColor(0, 255, 255, 80)))
                            rect_item.setPos(pos)
                            rect_item.setData(0, "feature")
                            text_item = self.scene.addText(item_id)
                            text_item.setFont(QFont("맑은 고딕", 3)) # 웨이포인트 수준의 기본 크기
                            text_item.setDefaultTextColor(Qt.GlobalColor.white)
                            text_rect = text_item.boundingRect()
                            center = pos + QPointF(pixmap.width() / 2, pixmap.height() / 2)
                            text_item.setPos(center - QPointF(text_rect.width() / 2, text_rect.height() / 2))
                            text_item.setData(0, "feature")
                            # 이름 라벨 그룹 등록 (충돌 회피 + 리더 라인, 웨이포인트 제외)
                            self._name_label_groups.append({
                                "anchor": center,
                                "bg": text_item,  # 배경 없음: 텍스트 자체를 배치 대상으로 사용
                                "text": text_item,
                                "preferred": "above",
                                "type": "feature_name"
                            })

                # 3. 모든 지오메트리 그리기 (층 번호 텍스트 제외)
                unique_vertices = set()
                for line_data in self.geometry_data.get("terrain_lines", []):
                    points = line_data.get("points", [])
                    if len(points) >= 2:
                        for i in range(len(points) - 1):
                            p1 = QPointF(points[i][0], points[i][1])
                            p2 = QPointF(points[i+1][0], points[i+1][1])
                            self._add_terrain_line_segment(p1, p2, line_data['id'])
                        for p in points:
                            q = QPointF(p[0], p[1])
                            self._add_vertex_indicator(q, line_data['id'])
                            unique_vertices.add((q.x(), q.y()))

                # 유니크 꼭짓점만 좌표 라벨 1회 생성
                for vx, vy in unique_vertices:
                    anchor = QPointF(vx, vy)
                    text_str = f"({vx:.1f}, {vy:.1f})"
                    bg_item, text_item = self._create_coord_text_item(text_str, QColor("magenta"), None)
                    self.scene.addItem(bg_item)
                    self.scene.addItem(text_item)
                    self.lod_coord_items.extend([bg_item, text_item])
                    self._coord_label_groups.append({
                        "anchor": anchor, "bg": bg_item, "text": text_item, "preferred": "above", "type": "coord_text"
                    })

                for obj_data in self.geometry_data.get("transition_objects", []):
                    points = obj_data.get("points", [])
                    if len(points) == 2:
                        p1_pos = QPointF(points[0][0], points[0][1])
                        p2_pos = QPointF(points[1][0], points[1][1])
                        line_item = self._add_object_line(p1_pos, p2_pos, obj_data['id'])
                        
                        # [v11.2.8] 층 이동 오브젝트 좌표 텍스트 (위치 계산 수정)
                        upper_point = p1_pos if p1_pos.y() < p2_pos.y() else p2_pos
                        lower_point = p2_pos if p1_pos.y() < p2_pos.y() else p1_pos

                        # 위쪽 꼭짓점 좌표 (원래 로직은 아래쪽으로 배치)
                        upper_text_str = f"({upper_point.x():.1f}, {upper_point.y():.1f})"
                        bg_item_u, text_item_u = self._create_coord_text_item(upper_text_str, QColor("orange"), None)
                        self.scene.addItem(bg_item_u)
                        self.scene.addItem(text_item_u)
                        self.lod_coord_items.extend([bg_item_u, text_item_u])
                        self._coord_label_groups.append({
                            "anchor": upper_point, "bg": bg_item_u, "text": text_item_u, "preferred": "below", "type": "coord_text"
                        })

                        # 아래쪽 꼭짓점 좌표 (원래 로직은 위쪽으로 배치)
                        lower_text_str = f"({lower_point.x():.1f}, {lower_point.y():.1f})"
                        bg_item_l, text_item_l = self._create_coord_text_item(lower_text_str, QColor("orange"), None)
                        self.scene.addItem(bg_item_l)
                        self.scene.addItem(text_item_l)
                        self.lod_coord_items.extend([bg_item_l, text_item_l])
                        self._coord_label_groups.append({
                            "anchor": lower_point, "bg": bg_item_l, "text": text_item_l, "preferred": "above", "type": "coord_text"
                        })

                        if 'dynamic_name' in obj_data:
                            name = obj_data['dynamic_name']
                            font = QFont("맑은 고딕", 3, QFont.Weight.Bold)  # 웨이포인트 수준의 기본 크기
                            text_item = QGraphicsTextItem(name)
                            text_item.setFont(font)
                            text_item.setDefaultTextColor(QColor("orange"))

                            text_rect = text_item.boundingRect()
                            padding_x = -3
                            padding_y = -3
                            bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

                            line_center = line_item.boundingRect().center()
                            # 사다리(수직형) 판별: 거의 수직이면 중앙 고정 배치
                            dx = abs(p2_pos.x() - p1_pos.x())
                            dy = abs(p2_pos.y() - p1_pos.y())
                            is_vertical = dx <= 3 and dy > 0

                            background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
                            background_rect.setBrush(QColor(0, 0, 0, 120))
                            background_rect.setPen(QPen(Qt.GlobalColor.transparent))
                            background_rect.setData(0, "transition_object_name_bg")

                            text_item.setData(0, "transition_object_name")
                            background_rect.setZValue(10)
                            text_item.setZValue(11)

                            self.scene.addItem(background_rect)
                            self.scene.addItem(text_item)

                            self.lod_text_items.append(text_item)
                            self.lod_text_items.append(background_rect)
                            if is_vertical:
                                # 중앙에 고정 배치 (충돌회피 제외)
                                bg_rect = background_rect.boundingRect()
                                background_rect.setPos(line_center.x() - bg_rect.width() / 2, line_center.y() - bg_rect.height() / 2)
                                txt_rect = text_item.boundingRect()
                                text_item.setPos(background_rect.x() + (bg_rect.width() - txt_rect.width()) / 2,
                                                 background_rect.y() + (bg_rect.height() - txt_rect.height()) / 2)
                            else:
                                # 이름 라벨 그룹 등록 (앵커는 선의 중앙, 위 선호)
                                self._name_label_groups.append({
                                    "anchor": line_center,
                                    "bg": background_rect,
                                    "text": text_item,
                                    "preferred": "above",
                                    "type": "transition_object_name"
                                })
                
                for jump_data in self.geometry_data.get("jump_links", []):
                    line_item = self._add_jump_link_line(QPointF(jump_data['start_vertex_pos'][0], jump_data['start_vertex_pos'][1]), QPointF(jump_data['end_vertex_pos'][0], jump_data['end_vertex_pos'][1]), jump_data['id'])
                    if 'dynamic_name' in jump_data:
                        name = jump_data['dynamic_name']

                        text_item = QGraphicsTextItem(name)
                        font = QFont("맑은 고딕", 3, QFont.Weight.Bold)  # 웨이포인트 수준의 기본 크기
                        text_item.setFont(font)
                        text_item.setDefaultTextColor(QColor("lime"))

                        text_rect = text_item.boundingRect()
                        padding_x = -3
                        padding_y = -3
                        bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

                        line_center = line_item.boundingRect().center()

                        background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
                        background_rect.setBrush(QColor(0, 0, 0, 120))
                        background_rect.setPen(QPen(Qt.GlobalColor.transparent))
                        background_rect.setData(0, "jump_link_name_bg")

                        text_item.setData(0, "jump_link_name")

                        background_rect.setZValue(10)
                        text_item.setZValue(11)

                        self.scene.addItem(background_rect)
                        self.scene.addItem(text_item)

                        self.lod_text_items.append(text_item)
                        self.lod_text_items.append(background_rect)
                        # 이름 라벨 그룹 등록 (앵커는 선의 중앙, 아래 선호 + 아래만 허용)
                        line_rect = line_item.boundingRect()
                        self._name_label_groups.append({
                            "anchor": line_center,
                            "bg": background_rect,
                            "text": text_item,
                            "preferred": "below",
                            "type": "jump_link_name",
                            "fixed_base": {"center_x": line_rect.center().x(), "bottom_y": line_rect.bottom()}
                        })

                # 좌표/이름 라벨 초기 배치 수행 (통합 충돌회피)
                self._relayout_all_labels()
                            
                # 4. 웨이포인트 순서 계산 및 그리기
                wp_order_map = {}
                route = self.route_profiles.get(self.active_route_profile, {}) or {}

                forward_slots = route.get("forward_slots", {})
                for slot in ROUTE_SLOT_IDS:
                    slot_data = forward_slots.get(slot, {}) or {}
                    waypoints = slot_data.get("waypoints", []) or []
                    for idx, wp_id in enumerate(waypoints):
                        label = f"F{slot}-{idx + 1}"
                        if wp_id in wp_order_map:
                            wp_order_map[wp_id] = f"{wp_order_map[wp_id]}, {label}"
                        else:
                            wp_order_map[wp_id] = label

                backward_slots = route.get("backward_slots", {})
                for slot in ROUTE_SLOT_IDS:
                    slot_data = backward_slots.get(slot, {}) or {}
                    waypoints = slot_data.get("waypoints", []) or []
                    for idx, wp_id in enumerate(waypoints):
                        label = f"B{slot}-{idx + 1}"
                        if wp_id in wp_order_map:
                            wp_order_map[wp_id] = f"{wp_order_map[wp_id]}, {label}"
                        else:
                            wp_order_map[wp_id] = label

                for wall_data in self.geometry_data.get("forbidden_walls", []):
                    self._add_forbidden_wall_graphics(wall_data)

                for wp_data in self.geometry_data.get("waypoints", []):
                    is_event = bool(wp_data.get('is_event'))
                    self._add_waypoint_rect(QPointF(wp_data['pos'][0], wp_data['pos'][1]), wp_data['id'], wp_data['name'], wp_data['name'], is_event=is_event)

                # 사냥범위 존 그리기
                for zone in self.geometry_data.get("hunt_range_zones", []):
                    rect = zone.get('rect') or [0, 0, 0, 0]
                    if not (isinstance(rect, list) and len(rect) == 4):
                        continue
                    x, y, w, h = [float(v) for v in rect]
                    pen = QPen(QColor(255, 165, 0, 200), 2, Qt.PenStyle.DashLine)
                    brush = QBrush(QColor(255, 165, 0, 60))
                    item = self.scene.addRect(x, y, w, h, pen, brush)
                    item.setZValue(180)
                    item.setData(0, "hunt_zone")
                    item.setData(1, zone.get('id'))
                    # 툴팁 간략 정보
                    enabled = bool(zone.get('enabled', False))
                    ranges = zone.get('ranges') or {}
                    ef = int(ranges.get('enemy_front', 0))
                    eb = int(ranges.get('enemy_back', 0))
                    pf = int(ranges.get('primary_front', 0))
                    pb = int(ranges.get('primary_back', 0))
                    yh = int(ranges.get('y_band_height', 0))
                    yo = int(ranges.get('y_band_offset', 0))
                    tip = f"활성화: {'예' if enabled else '아니오'}\n사냥 전/후: {ef}/{eb}\n주스킬 전/후: {pf}/{pb}\nY 높이/오프셋: {yh}/{yo}"
                    item.setToolTip(tip)
                    
                # 5. 모든 층 번호 텍스트를 마지막에 그림
                self._update_all_floor_texts()

                # v10.3.5: 보기 옵션 및 LOD 상태를 항상 마지막에 다시 적용
                self._update_visibility()
                self._update_lod_visibility()

    def _update_visibility(self):
        """UI 컨트롤 상태에 따라 QGraphicsScene의 아이템 가시성을 업데이트합니다."""
        show_bg = self.chk_show_background.isChecked()
        show_features = self.chk_show_features.isChecked()
        show_waypoints = self.chk_show_waypoints.isChecked()
        show_terrain = self.chk_show_terrain.isChecked()
        show_objects = self.chk_show_objects.isChecked()
        show_jump_links = self.chk_show_jump_links.isChecked()
        show_forbidden_walls = self.chk_show_forbidden_walls.isChecked()
        show_hunt_zones = self.chk_show_hunt_zones.isChecked()

        for item in self.scene.items():
            item_type = item.data(0)
            if item_type == "background":
                item.setVisible(show_bg)
            elif item_type == "feature":
                item.setVisible(show_features)
            elif item_type == "feature_name_leader":
                item.setVisible(show_features)
            elif item_type == "waypoint_v10":
                item.setVisible(show_waypoints)
            elif item_type in ["terrain_line", "vertex"]:
                item.setVisible(show_terrain)
            elif item_type in ["floor_text", "floor_text_leader"]:
                item.setVisible(show_terrain)
            elif item_type == "transition_object":
                item.setVisible(show_objects)
            elif item_type in ["transition_object_name", "transition_object_name_bg", "transition_object_name_leader"]: # 수정: _bg/leader 타입 추가
                item.setVisible(show_objects)
            elif item_type == "jump_link":
                item.setVisible(show_jump_links)
            elif item_type in ["jump_link_name", "jump_link_name_bg", "jump_link_name_leader"]: # 수정: _bg/leader 타입 추가
                item.setVisible(show_jump_links)
            elif item_type in ["forbidden_wall", "forbidden_wall_indicator", "forbidden_wall_range"]:
                item.setVisible(show_forbidden_walls)
            elif item_type == "hunt_zone":
                item.setVisible(show_hunt_zones)

    def _update_lod_visibility(self):
        """
        현재 줌 레벨에 따라 LOD 아이템들의 가시성을 조절합니다.
        [v11.3.3 BUGFIX] AttributeError 해결: 통합된 lock_coord_text_item 참조
        """
        current_zoom = self.view.transform().m11()
        
        # 이름표(지형, 오브젝트 등) 가시성 제어
        is_name_visible = current_zoom >= self.lod_threshold
        for item in self.lod_text_items:
            item_type = item.data(0)
            base_visible = True
            if item_type in ["transition_object_name", "transition_object_name_bg"]:
                base_visible = self.chk_show_objects.isChecked()
            elif item_type in ["jump_link_name", "jump_link_name_bg"]:
                base_visible = self.chk_show_jump_links.isChecked()
            elif item_type in ["floor_text", "floor_text_bg"]:
                base_visible = self.chk_show_terrain.isChecked()
            elif item_type == "waypoint_lod_text":
                base_visible = self.chk_show_waypoints.isChecked()
            elif item_type == "transition_object_name_leader":
                base_visible = self.chk_show_objects.isChecked()
            elif item_type == "jump_link_name_leader":
                base_visible = self.chk_show_jump_links.isChecked()
            elif item_type == "floor_text_leader":
                base_visible = self.chk_show_terrain.isChecked()

            item.setVisible(is_name_visible and base_visible)

        # 이름 라벨 동적 스케일링: 줌이 낮을수록 크게, 확대할수록 줄어듦(상/하한 적용)
        def clamp(v, lo, hi):
            return max(lo, min(hi, v))
        # 기준 줌에서 1.0배가 되도록 설정 (예: 2.5)
        base_zoom = max(self.lod_threshold, 2.5)
        # 스케일 상/하한 (과도한 확대/축소 방지)
        min_s, max_s = 0.6, 1.8
        dynamic_scale = clamp(base_zoom / max(current_zoom, 1e-6), min_s, max_s)
        for item in self.lod_text_items:
            t = item.data(0)
            if t in ("floor_text", "floor_text_bg", "transition_object_name", "transition_object_name_bg", "jump_link_name", "jump_link_name_bg"):
                try:
                    item.setScale(dynamic_scale)
                except Exception:
                    pass

        # 좌표 텍스트 가시성 제어 (LOD 대신 보기 옵션 체크박스)
        is_coord_visible = True
        try:
            is_coord_visible = self.chk_show_coords.isChecked()
        except Exception:
            pass
        for item in self.lod_coord_items:
            # [v11.3.3] 통합된 lock_coord_text_item의 가시성 제어
            if item is self.lock_coord_text_item:
                # 줌 레벨이 맞고, X 또는 Y축 고정 중 하나라도 켜져 있으면 보이도록 함
                is_lock_active = self.is_x_locked or self.is_y_locked
                item.setVisible(is_coord_visible and is_lock_active)
            else: # 일반 좌표 텍스트 (지형선, 오브젝트)
                # coord_text_group, coord_text_bg, coord_text 모두 처리
                item.setVisible(is_coord_visible)
        
        # 줌 변화에 따른 좌표 라벨 재배치 (겹침 최소화)
        self._relayout_all_labels()
                
    # -------------------- 사냥범위 편의 메서드 --------------------
    def _get_default_hunt_ranges(self) -> dict:
        """사냥탭에서 현재 범위를 받아 초기값으로 사용. 실패 시 안전 기본값."""
        try:
            hunt_tab = getattr(self.parent_map_tab, '_hunt_tab', None)
            if hunt_tab and hasattr(hunt_tab, 'api_get_current_ranges'):
                ranges = hunt_tab.api_get_current_ranges()
                if isinstance(ranges, dict):
                    return {
                        'enemy_front': int(ranges.get('enemy_front', 400)),
                        'enemy_back': int(ranges.get('enemy_back', 400)),
                        'primary_front': int(ranges.get('primary_front', 200)),
                        'primary_back': int(ranges.get('primary_back', 200)),
                        'y_band_height': int(ranges.get('y_band_height', 40)),
                        'y_band_offset': int(ranges.get('y_band_offset', 0)),
                    }
        except Exception:
            pass
        return {
            'enemy_front': 400,
            'enemy_back': 400,
            'primary_front': 200,
            'primary_back': 200,
            'y_band_height': 40,
            'y_band_offset': 0,
        }

    def _rects_intersect(self, a: QRectF, b: QRectF) -> bool:
        return a.intersects(b)

    def _any_hunt_zone_overlaps(self, rect: QRectF, exclude_id: Optional[str] = None) -> bool:
        for zone in self.geometry_data.get('hunt_range_zones', []):
            if exclude_id and zone.get('id') == exclude_id:
                continue
            r = zone.get('rect') or [0, 0, 0, 0]
            if not (isinstance(r, list) and len(r) == 4):
                continue
            zr = QRectF(float(r[0]), float(r[1]), float(r[2]), float(r[3]))
            if self._rects_intersect(rect, zr):
                return True
        return False

    def _delete_hunt_zone_by_id(self, zone_id: str) -> None:
        if not zone_id:
            return
        zones = self.geometry_data.get('hunt_range_zones', [])
        new_zones = [z for z in zones if z.get('id') != zone_id]
        if len(new_zones) != len(zones):
            self.geometry_data['hunt_range_zones'] = new_zones
            if self.parent_map_tab:
                try:
                    self.parent_map_tab.save_profile_data()
                except Exception:
                    pass
            self.populate_scene()

    def _edit_hunt_zone(self, zone_id: str) -> None:
        if not zone_id:
            return
        zones = self.geometry_data.get('hunt_range_zones', [])
        zone = next((z for z in zones if z.get('id') == zone_id), None)
        if not zone:
            return
        if 'ranges' not in zone or not isinstance(zone['ranges'], dict):
            zone['ranges'] = self._get_default_hunt_ranges()
        dlg = HuntZoneConfigDialog(zone, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            values = dlg.get_values()
            zone['enabled'] = bool(values.get('enabled', False))
            zone['ranges'] = dict(values.get('ranges') or {})
            if self.parent_map_tab:
                try:
                    self.parent_map_tab.save_profile_data()
                except Exception:
                    pass
            self.populate_scene()

    def on_scene_mouse_press(self, scene_pos, button):
        #  '기본' 모드에서 웨이포인트 클릭 시 이름 변경 기능 추가 ---
        if self.current_mode == "select" and button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            # 클릭 위치의 아이템 가져오기 (View 좌표로 변환 필요)
            view_pos = self.view.mapFromScene(scene_pos)
            item_at_pos = self.view.itemAt(view_pos)
            
            # [신규] 사냥범위: 기본 모드에서 좌클릭=설정, 우클릭=삭제
            if item_at_pos and item_at_pos.data(0) == "hunt_zone":
                zone_id = item_at_pos.data(1)
                if zone_id:
                    if button == Qt.MouseButton.LeftButton:
                        self._edit_hunt_zone(zone_id)
                    else:
                        self._delete_hunt_zone_by_id(zone_id)
                return

            if item_at_pos and item_at_pos.data(0) in ["forbidden_wall", "forbidden_wall_indicator", "forbidden_wall_range"]:
                wall_id = item_at_pos.data(1)
                if wall_id:
                    if button == Qt.MouseButton.LeftButton:
                        self._edit_forbidden_wall(wall_id)
                    else:
                        self._delete_forbidden_wall_by_id(wall_id)
                return

            if button == Qt.MouseButton.LeftButton and item_at_pos and item_at_pos.data(0) in ["waypoint_v10", "waypoint_lod_text"]:
                wp_id = item_at_pos.data(1)
                waypoint_data = next((wp for wp in self.geometry_data.get("waypoints", []) if wp.get("id") == wp_id), None)

                if waypoint_data:
                    dialog = WaypointEditDialog(waypoint_data, load_event_profiles(), self)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        new_name, is_event, event_profile, event_always = dialog.get_values()
                        old_name = waypoint_data.get("name", "")
                        if new_name != old_name and any(wp.get('name') == new_name for wp in self.geometry_data.get("waypoints", [])):
                            QMessageBox.warning(self, "오류", "이미 존재하는 웨이포인트 이름입니다.")
                        else:
                            waypoint_data["name"] = new_name
                            waypoint_data["is_event"] = is_event
                            waypoint_data["event_profile"] = event_profile if is_event else ""
                            waypoint_data["event_always"] = event_always if is_event else False
                            self.populate_scene() # UI 즉시 갱신
                    return # 이름 변경 로직 후 드래그 패닝 방지
                
        if self.current_mode == "terrain":
            if button == Qt.MouseButton.LeftButton:
                final_pos = None
                if self.is_y_locked and self.is_x_locked and self.locked_position:
                    final_pos = self.locked_position
                else:
                    snapped_point = self._get_snap_point(scene_pos)
                    final_pos = snapped_point if snapped_point else scene_pos
                    if self.is_y_locked and self.locked_position is not None:
                        final_pos.setY(self.locked_position.y())

                if final_pos is None: return

                if not self.is_drawing_line:
                    self.is_drawing_line = True
                    self.current_line_points = [final_pos]
                    self.current_line_id = f"line-{uuid.uuid4()}"
                    self._add_vertex_indicator(final_pos, self.current_line_id)
                else:
                    last_point = self.current_line_points[-1]
                    self._add_terrain_line_segment(last_point, final_pos, self.current_line_id)
                    self.current_line_points.append(final_pos)
                    self._add_vertex_indicator(final_pos, self.current_line_id)
                    if self.is_y_locked and self.is_x_locked:
                        self._finish_drawing_line()

            elif button == Qt.MouseButton.RightButton:
                if self.is_drawing_line:
                    self._finish_drawing_line()
                else:
                    items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                    for item in items_at_pos:
                        if item.data(0) in ["forbidden_wall", "forbidden_wall_indicator", "forbidden_wall_range"]:
                            wall_id = item.data(1)
                            if wall_id:
                                self._delete_forbidden_wall_by_id(wall_id)
                            break
                    else:
                        self._delete_terrain_at(scene_pos)
                    
        elif self.current_mode == "object":
            if button == Qt.MouseButton.LeftButton:
                # --- 2단계 생성 로직 ---
                if not self.is_drawing_object:
                    # 1. 첫 번째 클릭: 시작 지형선 찾기
                    start_info = None
                    if self.is_x_locked and self.locked_position:
                        start_info = self._get_closest_point_on_terrain_vertical(
                            self.locked_position.x(), self.locked_position.y()
                        )
                    else:
                        start_info = self._get_closest_point_on_terrain(scene_pos)
                    
                    if start_info:
                        start_pos, parent_line_id = start_info
                        self.is_drawing_object = True
                        self.object_start_info = {'pos': start_pos, 'line_id': parent_line_id}
                
                else:
                    # 2. 두 번째 클릭: 종료 지형선 찾기 및 오브젝트 생성
                    end_info = self._get_closest_point_on_terrain(scene_pos)

                    if not end_info:
                        self._finish_drawing_object(cancel=True)
                        return

                    end_pos, end_line_id = end_info
                    start_line_id = self.object_start_info['line_id']

                    # 유효성 검사
                    if end_line_id == start_line_id:
                        print("오류: 같은 지형선에 연결할 수 없습니다.")
                        self._finish_drawing_object(cancel=True)
                        return

                    start_line_data = next((line for line in self.geometry_data["terrain_lines"] if line["id"] == start_line_id), None)
                    end_line_data = next((line for line in self.geometry_data["terrain_lines"] if line["id"] == end_line_id), None)

                    if not start_line_data or not end_line_data or start_line_data.get('floor') == end_line_data.get('floor'):
                        print("오류: 서로 다른 층의 지형선에만 연결할 수 있습니다.")
                        self._finish_drawing_object(cancel=True)
                        return
                    
                    # 데이터 생성 및 추가
                    obj_id = f"obj-{uuid.uuid4()}"
                    
                    # x좌표는 시작점 기준으로 통일
                    final_start_pos = self.object_start_info['pos']
                    final_end_pos = QPointF(final_start_pos.x(), end_pos.y())

                    new_obj = {
                        "id": obj_id,
                        "start_line_id": start_line_id,
                        "end_line_id": end_line_id,
                        "points": [[final_start_pos.x(), final_start_pos.y()], [final_end_pos.x(), final_end_pos.y()]]
                    }
                    self.geometry_data["transition_objects"].append(new_obj)
                    self._finish_drawing_object(cancel=False)

            elif button == Qt.MouseButton.RightButton:
                if self.is_drawing_object:
                    self._finish_drawing_object(cancel=True)
                else:
                    # 기존 삭제 로직 유지
                    items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                    for item in items_at_pos:
                        if item.data(0) == "transition_object":
                            self._delete_object_by_id(item.data(1))
                            break
        
        elif self.current_mode == "forbidden_wall":
            if button == Qt.MouseButton.LeftButton:
                terrain_info = self._get_closest_point_on_terrain(scene_pos)
                if not terrain_info:
                    QMessageBox.information(self, "금지벽 추가", "금지벽은 지형선 위에서만 추가할 수 있습니다.")
                    return

                snap_pos, parent_line_id = terrain_info
                wall_id = f"fw-{uuid.uuid4()}"
                parent_line = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get("id") == parent_line_id), None)
                wall_floor = parent_line.get("floor") if parent_line else None

                new_wall = {
                    "id": wall_id,
                    "line_id": parent_line_id,
                    "pos": [snap_pos.x(), snap_pos.y()],
                    "floor": wall_floor,
                    "enabled": False,
                    "range_left": 0.0,
                    "range_right": 0.0,
                    "dwell_seconds": 3.0,
                    "cooldown_seconds": 5.0,
                    "instant_on_contact": False,
                    "skill_profiles": [],
                }

                self.geometry_data.setdefault("forbidden_walls", []).append(new_wall)
                self.populate_scene()
                self._edit_forbidden_wall(wall_id)

            elif button == Qt.MouseButton.RightButton:
                items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                for item in items_at_pos:
                    if item.data(0) in ["forbidden_wall", "forbidden_wall_indicator", "forbidden_wall_range"]:
                        self._delete_forbidden_wall_by_id(item.data(1))
                        break

        elif self.current_mode == "waypoint":
            if button == Qt.MouseButton.LeftButton:
                terrain_info = self._get_closest_point_on_terrain(scene_pos)
                if terrain_info:
                    snap_pos, parent_line_id = terrain_info
                    wp_name, ok = QInputDialog.getText(self, "웨이포인트 추가", "새 웨이포인트 이름:")
                    if ok and wp_name:
                        if any(wp.get('name') == wp_name for wp in self.geometry_data.get("waypoints", [])):
                            QMessageBox.warning(self, "오류", "이미 존재하는 웨이포인트 이름입니다.")
                            return
                        
                        parent_line = next((line for line in self.geometry_data["terrain_lines"] if line["id"] == parent_line_id), None)
                        wp_floor = parent_line.get("floor", self.floor_spinbox.value()) if parent_line else self.floor_spinbox.value()
                        
                        wp_id = f"wp-{uuid.uuid4()}"
                        new_wp = {
                            "id": wp_id,
                            "name": wp_name,
                            "pos": [snap_pos.x(), snap_pos.y()],
                            "floor": wp_floor, # --- : 자동 할당된 층 사용 ---
                            "parent_line_id": parent_line_id,
                            "is_event": False,
                            "event_profile": ""
                        }
                        self.geometry_data["waypoints"].append(new_wp)
                        self.populate_scene()
        
        elif self.current_mode == "jump":
            if button == Qt.MouseButton.LeftButton:
                snapped_vertex_pos = self._get_snap_point(scene_pos)
                if not snapped_vertex_pos: return

                if not self.is_drawing_jump_link:
                    self.is_drawing_jump_link = True
                    self.jump_link_start_pos = snapped_vertex_pos
                else:
                    # --- 단계 1: 새 링크 데이터 생성 및 추가 ---
                    link_id = f"jump-{uuid.uuid4()}"
                    new_link = {
                        "id": link_id,
                        "start_vertex_pos": [self.jump_link_start_pos.x(), self.jump_link_start_pos.y()],
                        "end_vertex_pos": [snapped_vertex_pos.x(), snapped_vertex_pos.y()],
                        "floor": self.floor_spinbox.value()
                    }
                    self.geometry_data["jump_links"].append(new_link)
                    
                    # --- 단계 2: 그리기 상태를 먼저 안전하게 종료 ---
                    # populate_scene() 호출 전에 현재 씬의 미리보기 아이템을 제거해야 함
                    self._finish_drawing_jump_link()

                    # --- 단계 3: 이름 갱신 및 전체 씬 다시 그리기 ---
                    self._assign_dynamic_names()
                    self.populate_scene()

            elif button == Qt.MouseButton.RightButton:
                if self.is_drawing_jump_link:
                    self._finish_drawing_jump_link()
                else:
                    items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                    for item in items_at_pos:
                        if item.data(0) == "jump_link":
                            self._delete_jump_link_by_id(item.data(1))
                            break

        elif self.current_mode == "hunt_zone":
            if button == Qt.MouseButton.LeftButton:
                # 2-클릭 생성 방식: 클릭 시작 -> 이동 미리보기 -> 클릭 종료
                if not self.is_drawing_hunt_zone:
                    self.is_drawing_hunt_zone = True
                    self.hunt_zone_start_pos = scene_pos
                    # 프리뷰 생성
                    if self.preview_hunt_zone_item and self.preview_hunt_zone_item in self.scene.items():
                        self.scene.removeItem(self.preview_hunt_zone_item)
                        self.preview_hunt_zone_item = None
                    pen = QPen(QColor(255, 165, 0, 200), 2, Qt.PenStyle.DashLine)
                    brush = QBrush(QColor(255, 165, 0, 60))
                    self.preview_hunt_zone_item = self.scene.addRect(QRectF(scene_pos, scene_pos).normalized(), pen, brush)
                    self.preview_hunt_zone_item.setZValue(500)
                else:
                    # 종료: 영역 확정
                    start = self.hunt_zone_start_pos if self.hunt_zone_start_pos else scene_pos
                    rect = QRectF(start, scene_pos).normalized()
                    # 최소 크기
                    if rect.width() < 4 or rect.height() < 4:
                        QMessageBox.information(self, "사냥범위", "너무 작은 영역입니다.")
                        # 프리뷰 정리
                        if self.preview_hunt_zone_item and self.preview_hunt_zone_item in self.scene.items():
                            self.scene.removeItem(self.preview_hunt_zone_item)
                        self.preview_hunt_zone_item = None
                        self.is_drawing_hunt_zone = False
                        self.hunt_zone_start_pos = None
                        return
                    # 겹침 금지
                    if self._any_hunt_zone_overlaps(rect):
                        QMessageBox.warning(self, "사냥범위", "다른 사냥범위와 겹칠 수 없습니다.")
                        if self.preview_hunt_zone_item and self.preview_hunt_zone_item in self.scene.items():
                            self.scene.removeItem(self.preview_hunt_zone_item)
                        self.preview_hunt_zone_item = None
                        self.is_drawing_hunt_zone = False
                        self.hunt_zone_start_pos = None
                        return
                    # 생성
                    zone_id = f"hz-{uuid.uuid4()}"
                    ranges = self._get_default_hunt_ranges()
                    new_zone = {
                        'id': zone_id,
                        'rect': [float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height())],
                        'enabled': False,
                        'ranges': ranges,
                    }
                    self.geometry_data.setdefault('hunt_range_zones', []).append(new_zone)
                    # 프리뷰 정리 및 저장/갱신
                    if self.preview_hunt_zone_item and self.preview_hunt_zone_item in self.scene.items():
                        self.scene.removeItem(self.preview_hunt_zone_item)
                    self.preview_hunt_zone_item = None
                    self.is_drawing_hunt_zone = False
                    self.hunt_zone_start_pos = None
                    if self.parent_map_tab:
                        try:
                            self.parent_map_tab.save_profile_data()
                        except Exception:
                            pass
                    self.populate_scene()
            elif button == Qt.MouseButton.RightButton:
                # 드로잉 취소 또는 우클릭 삭제
                if self.is_drawing_hunt_zone:
                    if self.preview_hunt_zone_item and self.preview_hunt_zone_item in self.scene.items():
                        self.scene.removeItem(self.preview_hunt_zone_item)
                    self.preview_hunt_zone_item = None
                    self.is_drawing_hunt_zone = False
                    self.hunt_zone_start_pos = None
                else:
                    items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                    for item in items_at_pos:
                        if item.data(0) == 'hunt_zone':
                            self._delete_hunt_zone_by_id(item.data(1))
                            break

        elif self.current_mode == "select":
            if button == Qt.MouseButton.LeftButton:
                items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                line_id_to_change = None
                for item in items_at_pos:
                    if item.data(0) == "terrain_line":
                        line_id_to_change = item.data(1)
                        break
                
                if line_id_to_change:
                    new_floor = self.floor_spinbox.value()
                    
                    clicked_line = next((line for line in self.geometry_data["terrain_lines"] if line["id"] == line_id_to_change), None)
                    if clicked_line:
                        if 'dynamic_name' not in clicked_line:
                            self._assign_dynamic_names()
                        
                        target_group_name = clicked_line.get('dynamic_name')
                        
                        # 1. 같은 그룹에 속한 모든 라인의 층 변경 및 ID 수집
                        changed_line_ids = set()
                        for line_data in self.geometry_data["terrain_lines"]:
                            if line_data.get('dynamic_name') == target_group_name:
                                line_data["floor"] = new_floor
                                changed_line_ids.add(line_data["id"])

                        # 2. 종속된 층 이동 오브젝트의 층 정보 동기화
                        for obj_data in self.geometry_data.get("transition_objects", []):
                            if obj_data.get("parent_line_id") in changed_line_ids:
                                obj_data["floor"] = new_floor

                        # 종속된 웨이포인트의 층 정보 동기화 ---
                        for wp_data in self.geometry_data.get("waypoints", []):
                            if wp_data.get("parent_line_id") in changed_line_ids:
                                wp_data["floor"] = new_floor

                    # 3. 이름 재계산 및 UI 갱신
                    self._assign_dynamic_names()
                    self._update_all_floor_texts()
                    
            elif button == Qt.MouseButton.RightButton:
                deleted = False
                items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                for item in items_at_pos:
                    item_type = item.data(0)
                    if item_type == "transition_object":
                        self._delete_object_by_id(item.data(1))
                        deleted = True
                        break
                    elif item_type == "waypoint_v10":
                        self._delete_waypoint_by_id(item.data(1))
                        deleted = True
                        break
                    elif item_type == "jump_link":
                        self._delete_jump_link_by_id(item.data(1))
                        deleted = True
                        break
                if not deleted:
                    self._delete_terrain_at(scene_pos)

    def on_scene_mouse_move(self, scene_pos):
        if self.current_mode == "terrain":
            if self.is_y_locked and self.is_x_locked:
                if self.preview_line_item and self.preview_line_item in self.scene.items():
                    self.scene.removeItem(self.preview_line_item)
                return

            snapped_point = self._get_snap_point(scene_pos)
            self._update_snap_indicator(snapped_point)

            if self.is_drawing_line:
                if self.preview_line_item and self.preview_line_item in self.scene.items():
                    self.scene.removeItem(self.preview_line_item)
                
                last_point = self.current_line_points[-1]
                final_pos = snapped_point if snapped_point else scene_pos

                if self.is_y_locked and self.locked_position is not None:
                    final_pos.setY(self.locked_position.y())

                self.preview_line_item = self.scene.addLine(
                    last_point.x(), last_point.y(), final_pos.x(), final_pos.y(),
                    QPen(QColor(255, 255, 0, 150), 2, Qt.PenStyle.DashLine)
                )
        elif self.current_mode == "object":
            if self.is_drawing_object and self.object_start_info:
                # RuntimeError 방지
                if self.preview_object_item and self.preview_object_item.scene():
                    self.scene.removeItem(self.preview_object_item)
                
                start_pos = self.object_start_info['pos']
                end_pos = QPointF(start_pos.x(), scene_pos.y()) # 수직선 유지
                
                self.preview_object_item = self.scene.addLine(
                    start_pos.x(), start_pos.y(), end_pos.x(), end_pos.y(),
                    QPen(QColor(255, 165, 0, 150), 2, Qt.PenStyle.DashLine)
                )
                self.preview_object_item.setZValue(150) # 다른 요소 위에 보이도록
        # --- v10.0.0  ---
        elif self.current_mode == "waypoint":
            terrain_info = self._get_closest_point_on_terrain(scene_pos)
            if terrain_info:
                snap_pos, _ = terrain_info
                #  None 체크 강화 ---
                if self.preview_waypoint_item is None:
                    size = 12
                    self.preview_waypoint_item = self.scene.addRect(0, 0, size, size, QPen(QColor(0, 255, 0, 150), 2, Qt.PenStyle.DashLine))
                
                # self.preview_waypoint_item이 None이 아님을 보장
                if self.preview_waypoint_item:
                    self.preview_waypoint_item.setPos(snap_pos - QPointF(self.preview_waypoint_item.rect().width()/2, self.preview_waypoint_item.rect().height()))
                    self.preview_waypoint_item.setVisible(True)
            elif self.preview_waypoint_item:
                self.preview_waypoint_item.setVisible(False)

        elif self.current_mode == "jump":
            snapped_vertex_pos = self._get_snap_point(scene_pos)
            self._update_snap_indicator(snapped_vertex_pos)

            if self.is_drawing_jump_link:
                if self.preview_jump_link_item:
                    self.scene.removeItem(self.preview_jump_link_item)
                
                end_pos = snapped_vertex_pos if snapped_vertex_pos else scene_pos
                self.preview_jump_link_item = self.scene.addLine(
                    self.jump_link_start_pos.x(), self.jump_link_start_pos.y(), end_pos.x(), end_pos.y(),
                    QPen(QColor(0, 255, 0, 150), 2, Qt.PenStyle.DashLine)
                )
        # --- v10.0.0 수정 끝 ---
        elif self.current_mode == "hunt_zone":
            if self.is_drawing_hunt_zone and self.hunt_zone_start_pos is not None:
                if self.preview_hunt_zone_item and self.preview_hunt_zone_item in self.scene.items():
                    self.scene.removeItem(self.preview_hunt_zone_item)
                pen = QPen(QColor(255, 165, 0, 200), 2, Qt.PenStyle.DashLine)
                brush = QBrush(QColor(255, 165, 0, 60))
                rect = QRectF(self.hunt_zone_start_pos, scene_pos).normalized()
                self.preview_hunt_zone_item = self.scene.addRect(rect, pen, brush)
                self.preview_hunt_zone_item.setZValue(500)
    
    def _add_waypoint_rect(self, pos, wp_id, name, order_text, is_event=False):
            """씬에 웨이포인트 사각형과 순서를 추가합니다."""
            size = 12
            if is_event:
                pen = QPen(QColor(0, 135, 255))
                brush = QBrush(QColor(0, 135, 255, 80))
            else:
                pen = QPen(Qt.GlobalColor.green)
                brush = QBrush(QColor(0, 255, 0, 80))

            rect_item = self.scene.addRect(0, 0, size, size, pen, brush)
            rect_item.setPos(pos - QPointF(size/2, size))
            rect_item.setData(0, "waypoint_v10")
            rect_item.setData(1, wp_id)

            # 이름 텍스트는 툴팁으로 변경
            rect_item.setToolTip(name)

            #  중앙 텍스트(order_text)에 폰트 크기 동적 조절 로직 추가 ---
            text_item = QGraphicsTextItem(order_text)
            
            # --- 미니맵 편집기 웨이포인트 이름 폰트 크기 조정 ---
            font_size = 3 # 기본 8 -> 5
            if len(order_text) > 5:
                font_size = 2 # 6 -> 3
            elif len(order_text) > 8:
                font_size = 1 # 4 -> 2 (매우 작으므로 최소 2로 설정)

            font = QFont("맑은 고딕", font_size, QFont.Weight.Bold)
            text_item.setFont(font)
            text_item.setDefaultTextColor(Qt.GlobalColor.white)
            
            text_rect = text_item.boundingRect()
            center_pos = rect_item.pos() + QPointF(size/2, size/2)
            text_item.setPos(center_pos - QPointF(text_rect.width()/2, text_rect.height()/2))
            
            # LOD 제어를 위해 텍스트 아이템에 별도 타입 부여 및 리스트 추가 ---
            text_item.setData(0, "waypoint_lod_text") # 사각형(waypoint_v10)과 구분
            text_item.setData(1, wp_id)
            # 텍스트도 마우스 이벤트를 무시하도록 설정
            text_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            
            #  웨이포인트 아이템들을 최상위에 표시하기 위해 Z-value 설정 ---
            rect_item.setZValue(20)
            text_item.setZValue(21)
            
            self.scene.addItem(text_item)
            
            # LOD 제어 대상 리스트에 추가
            self.lod_text_items.append(text_item)
            
            return rect_item

    def _format_forbidden_wall_tooltip(self, wall_data: dict) -> str:
        status = "사용" if wall_data.get('enabled') else "비활성"
        range_left = float(wall_data.get('range_left', 0.0))
        range_right = float(wall_data.get('range_right', 0.0))
        dwell = float(wall_data.get('dwell_seconds', 0.0))
        cooldown = float(wall_data.get('cooldown_seconds', 5.0))
        instant = "예" if wall_data.get('instant_on_contact') else "아니오"
        skills = wall_data.get('skill_profiles') or []
        skill_text = ", ".join(skills) if skills else "-"
        return (
            f"상태: {status}\n"
            f"좌측 범위: {range_left:.1f}px\n"
            f"우측 범위: {range_right:.1f}px\n"
            f"대기 시간: {dwell:.1f}s\n"
            f"쿨타임: {cooldown:.1f}s\n"
            f"접촉 즉시 실행: {instant}\n"
            f"명령 프로필: {skill_text}"
        )

    def _add_forbidden_wall_graphics(self, wall_data: dict) -> None:
        wall_id = wall_data.get('id')
        pos = wall_data.get('pos') or [0.0, 0.0]
        if len(pos) < 2:
            return

        x, y = float(pos[0]), float(pos[1])
        enabled = bool(wall_data.get('enabled'))
        color = QColor(220, 50, 50) if enabled else QColor(150, 90, 90)
        outline = QColor(120, 30, 30) if enabled else QColor(80, 60, 60)

        dot_radius = 2.0
        dot_pen = QPen(outline, 0.8)
        dot_brush = QBrush(color)
        dot_item = self.scene.addEllipse(x - dot_radius, y - dot_radius, dot_radius * 2, dot_radius * 2, dot_pen, dot_brush)
        dot_item.setZValue(400)
        dot_item.setData(0, "forbidden_wall")
        dot_item.setData(1, wall_id)
        dot_item.setToolTip(self._format_forbidden_wall_tooltip(wall_data))

        range_left = max(0.0, float(wall_data.get('range_left', 0.0)))
        range_right = max(0.0, float(wall_data.get('range_right', 0.0)))
        range_pen = QPen(QColor(60, 150, 255, 180), 1.5)
        range_pen.setCapStyle(Qt.PenCapStyle.FlatCap)

        tooltip = self._format_forbidden_wall_tooltip(wall_data)

        if range_left > 0.0:
            left_line = self.scene.addLine(x - range_left, y, x, y, range_pen)
            left_line.setZValue(395)
            left_line.setData(0, "forbidden_wall_range")
            left_line.setData(1, wall_id)
            left_line.setToolTip(tooltip)

        if range_right > 0.0:
            right_line = self.scene.addLine(x, y, x + range_right, y, range_pen)
            right_line.setZValue(395)
            right_line.setData(0, "forbidden_wall_range")
            right_line.setData(1, wall_id)
            right_line.setToolTip(tooltip)

    def _edit_forbidden_wall(self, wall_id: str) -> None:
        if not wall_id:
            return
        walls = self.geometry_data.get("forbidden_walls", [])
        wall = next((w for w in walls if w.get('id') == wall_id), None)
        if not wall:
            return

        # 라인 층 정보 최신화
        parent_line = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get("id") == wall.get('line_id')), None)
        if parent_line and parent_line.get('floor') is not None:
            wall['floor'] = parent_line.get('floor')

        dialog = ForbiddenWallDialog(wall, load_skill_profiles(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            wall.update(dialog.get_values())
            self.populate_scene()

    def _delete_forbidden_wall_by_id(self, wall_id: str) -> None:
        if not wall_id:
            return
        original_len = len(self.geometry_data.get("forbidden_walls", []))
        self.geometry_data["forbidden_walls"] = [
            wall for wall in self.geometry_data.get("forbidden_walls", [])
            if wall.get('id') != wall_id
        ]
        if len(self.geometry_data.get("forbidden_walls", [])) != original_len:
            self.populate_scene()

    def _add_jump_link_line(self, p1, p2, link_id):
        """씬에 지형 점프 연결선을 추가합니다."""
        pen = QPen(QColor(0, 255, 0, 200), 2, Qt.PenStyle.DashLine)
        line_item = self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), pen)
        line_item.setData(0, "jump_link")
        line_item.setData(1, link_id)
        return line_item

    def _get_closest_point_on_terrain_vertical(self, target_x, target_y):
        """주어진 X좌표의 수직선상에서 Y좌표가 가장 가까운 지형선 위의 점과 ID를 찾습니다."""
        min_y_dist = float('inf')
        closest_point_info = None

        terrain_lines = [item for item in self.scene.items() if isinstance(item, QGraphicsLineItem) and item.data(0) == "terrain_line"]

        for line_item in terrain_lines:
            p1 = line_item.line().p1()
            p2 = line_item.line().p2()

            if (p1.x() <= target_x <= p2.x()) or (p2.x() <= target_x <= p1.x()):
                dx = p2.x() - p1.x()
                if abs(dx) < 1e-6:
                    y_on_line = p1.y()
                else:
                    m = (p2.y() - p1.y()) / dx
                    c = p1.y() - m * p1.x()
                    y_on_line = m * target_x + c
                
                y_dist = abs(y_on_line - target_y)
                if y_dist < min_y_dist:
                    min_y_dist = y_dist
                    closest_point_info = (QPointF(target_x, y_on_line), line_item.data(1))

        if min_y_dist < 50:
            return closest_point_info
        return None    
    
    def _finish_drawing_line(self):
        """현재 그리던 지형선 그리기를 완료하고 데이터를 저장합니다."""
        if len(self.current_line_points) >= 2:
            points_data = [[p.x(), p.y()] for p in self.current_line_points]
            self.geometry_data["terrain_lines"].append({
                "id": self.current_line_id,
                "points": points_data,
                "floor": self.floor_spinbox.value()
            })
            
            # 1. 모든 동적 이름을 다시 계산
            self._assign_dynamic_names()
            # 2. 갱신된 이름을 사용하여 텍스트 다시 그리기
            self._update_all_floor_texts()
            
        elif len(self.current_line_points) == 1:
            # 점만 하나 찍고 끝낸 경우, 해당 꼭짓점 아이템 삭제
            items_to_remove = []
            for item in self.scene.items():
                if item.data(1) == self.current_line_id:
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.scene.removeItem(item)

        self.is_drawing_line = False
        self.current_line_points = []
        if self.preview_line_item and self.preview_line_item in self.scene.items():
            self.scene.removeItem(self.preview_line_item)
        self.preview_line_item = None

    def _add_terrain_line_segment(self, p1, p2, line_id):
        """씬에 지형선 세그먼트를 추가합니다."""
        line_item = self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), QPen(Qt.GlobalColor.magenta, 2))
        line_item.setData(0, "terrain_line")
        line_item.setData(1, line_id)
        return line_item

    def _add_vertex_indicator(self, pos, line_id):
        """지형선의 꼭짓점을 씬에 추가합니다."""
        # 기본 6 -> 3 (요청 반영)
        dot = self.scene.addEllipse(0, 0, 3.0, 3.0, QPen(Qt.GlobalColor.magenta), QBrush(Qt.GlobalColor.white))
        dot.setPos(pos - QPointF(1.5, 1.5))
        dot.setData(0, "vertex")
        dot.setData(1, line_id)
        return dot

    def _get_snap_point(self, scene_pos):
        """주어진 위치에서 스냅할 꼭짓점을 찾습니다."""
        items = self.view.items(self.view.mapFromScene(scene_pos))
        for item in items:
            if isinstance(item, QGraphicsEllipseItem) and item.data(0) == "vertex":
                return item.pos() + QPointF(3, 3)
        return None
    
    def _update_snap_indicator(self, snap_point):
        """스냅 가능한 위치에 표시기를 업데이트합니다."""
        #  객체가 삭제되었는지 먼저 확인하여 RuntimeError 방지 ---
        if hasattr(self, 'snap_indicator') and self.snap_indicator and self.snap_indicator.scene() is None:
            self.snap_indicator = None

        if snap_point:
            if not self.snap_indicator:
                # 스냅 원 8 -> 3 (요청 반영)
                self.snap_indicator = self.scene.addEllipse(0, 0, 3.0, 3.0, QPen(QColor(0, 255, 0, 200), 1))
                self.snap_indicator.setZValue(100)
            self.snap_indicator.setPos(snap_point - QPointF(1.5, 1.5))
            self.snap_indicator.setVisible(True)
        else:
            if self.snap_indicator:
                self.snap_indicator.setVisible(False)
                     
    def _delete_terrain_at(self, scene_pos):
        """주어진 위치의 지형 그룹 전체와, 종속된 오브젝트 및 점프 링크를 삭제합니다."""
        items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
        line_id_to_delete = None
        for item in items_at_pos:
            if item.data(0) == "terrain_line":
                line_id_to_delete = item.data(1)
                break
        
        if line_id_to_delete:
            # --- 단계 1: 삭제할 지형 그룹과 모든 꼭짓점 식별 ---
            line_to_delete_data = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get("id") == line_id_to_delete), None)
            if not line_to_delete_data: return
            
            if 'dynamic_name' not in line_to_delete_data:
                self._assign_dynamic_names()
            target_group_name = line_to_delete_data.get('dynamic_name')

            ids_in_group = set()
            vertices_in_group = set()
            for line in self.geometry_data.get("terrain_lines", []):
                if line.get('dynamic_name') == target_group_name:
                    ids_in_group.add(line['id'])
                    for p in line.get("points", []):
                        vertices_in_group.add(tuple(p))

            # --- 단계 2: 데이터에서 모든 종속 항목 연쇄 삭제 ---

            # 2a. 연결된 점프 링크 삭제
            self.geometry_data["jump_links"] = [
                jump for jump in self.geometry_data.get("jump_links", [])
                if tuple(jump.get("start_vertex_pos")) not in vertices_in_group and \
                   tuple(jump.get("end_vertex_pos")) not in vertices_in_group
            ]

            # ==================== v10.6.0 수정 시작 ====================
            # 2b. 종속된 층 이동 오브젝트 삭제 (start_line_id 또는 end_line_id 기준)
            self.geometry_data["transition_objects"] = [
                obj for obj in self.geometry_data.get("transition_objects", [])
                if obj.get("start_line_id") not in ids_in_group and obj.get("end_line_id") not in ids_in_group
            ]
            # ==================== v10.6.0 수정 끝 ======================
            
            # 2c. 지형 그룹 자체 삭제
            self.geometry_data["terrain_lines"] = [
                line for line in self.geometry_data.get("terrain_lines", [])
                if line.get("id") not in ids_in_group
            ]

            # 2d. 금지벽 삭제
            if "forbidden_walls" in self.geometry_data:
                self.geometry_data["forbidden_walls"] = [
                    wall for wall in self.geometry_data.get("forbidden_walls", [])
                    if wall.get("line_id") not in ids_in_group
                ]

            # --- 단계 3: UI 전체 갱신 ---
            self.populate_scene()
            self.view.viewport().update()
    def _get_closest_point_on_terrain(self, scene_pos):
        """
        씬의 특정 위치에서 가장 적합한 지형선 위의 점과 ID를 찾습니다. (x좌표 우선 탐색)
        """
        mouse_x, mouse_y = scene_pos.x(), scene_pos.y()
        
        candidate_lines = []
        
        # 1. 마우스의 x좌표를 포함하는 모든 지형선을 후보로 수집
        all_terrain_lines = [item for item in self.scene.items() if isinstance(item, QGraphicsLineItem) and item.data(0) == "terrain_line"]
        
        for line_item in all_terrain_lines:
            p1 = line_item.line().p1()
            p2 = line_item.line().p2()
            
            min_x, max_x = min(p1.x(), p2.x()), max(p1.x(), p2.x())
            
            # x좌표가 지형선 범위 내에 있는지 확인 (약간의 여유 허용)
            if min_x - 1 <= mouse_x <= max_x + 1:
                # 해당 x좌표에서의 지형선 y좌표 계산
                dx = p2.x() - p1.x()
                if abs(dx) < 1e-6: # 수직선일 경우
                    line_y_at_mouse_x = p1.y()
                else: # 일반적인 경우
                    slope = (p2.y() - p1.y()) / dx
                    line_y_at_mouse_x = p1.y() + slope * (mouse_x - p1.x())
                
                # 마우스 y좌표와의 거리 계산
                y_distance = abs(mouse_y - line_y_at_mouse_x)
                
                candidate_lines.append({
                    "y_dist": y_distance,
                    "point": QPointF(mouse_x, line_y_at_mouse_x),
                    "id": line_item.data(1)
                })

        if not candidate_lines:
            return None
            
        # 2. 후보들 중에서 마우스 y좌표와 가장 가까운 지형선을 최종 선택
        closest_line = min(candidate_lines, key=lambda c: c["y_dist"])
        
        # 3. 최종 선택된 지형선이 스냅 임계값 이내인지 확인
        SNAP_THRESHOLD_Y = 15.0
        if closest_line["y_dist"] <= SNAP_THRESHOLD_Y:
            return (closest_line["point"], closest_line["id"])
            
        return None

    def _finish_drawing_object(self, cancel=False):
        """현재 그리던 오브젝트 그리기를 완료/취소하고 상태를 초기화합니다."""
        # 1. 미리보기 아이템 안전하게 제거
        if self.preview_object_item and self.preview_object_item.scene():
            self.scene.removeItem(self.preview_object_item)
        
        # 2. 상태 변수 초기화 (성공/취소 공통)
        self.is_drawing_object = False
        self.object_start_info = None
        self.preview_object_item = None
        
        # 3. 성공 시에만 데이터 갱신 및 UI 다시 그리기
        if not cancel:
            self._assign_dynamic_names()
            self.populate_scene()
            self.view.viewport().update()

        if self.preview_object_item and self.preview_object_item in self.scene.items():
            self.scene.removeItem(self.preview_object_item)
        
        self.is_drawing_object = False
        self.object_start_pos = None
        self.preview_object_item = None
        self.current_object_parent_id = None
        # --- 추가: 임시 층 정보 변수 초기화 ---
        if hasattr(self, 'current_object_floor'):
            del self.current_object_floor
        
    def _add_object_line(self, p1, p2, obj_id):
        """씬에 수직 이동 오브젝트 라인을 추가합니다."""
        line = self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), QPen(QColor(255, 165, 0), 3))
        line.setData(0, "transition_object")
        line.setData(1, obj_id)
        return line

    def _delete_object_by_id(self, obj_id_to_delete, update_view=True):
        """주어진 ID를 가진 수직 이동 오브젝트와 관련 이름표를 삭제하고 뷰를 갱신합니다."""
        if not obj_id_to_delete: return

        # ---  삭제 후 전체 뷰를 갱신하는 로직으로 변경 ---
        # 1. 데이터에서 해당 오브젝트 삭제
        original_count = len(self.geometry_data.get("transition_objects", []))
        self.geometry_data["transition_objects"] = [
            obj for obj in self.geometry_data.get("transition_objects", [])
            if obj.get("id") != obj_id_to_delete
        ]
        
        # 삭제가 실제로 일어났는지 확인
        if len(self.geometry_data.get("transition_objects", [])) < original_count:
            if update_view:
                # 2. 이름 다시 부여
                self._assign_dynamic_names()
                # 3. 전체 씬을 다시 그려서 완벽하게 갱신
                self.populate_scene()

    def _finish_drawing_jump_link(self):
        """점프 연결선 그리기를 완료/취소합니다."""
        self.is_drawing_jump_link = False
        self.jump_link_start_pos = None
        if self.preview_jump_link_item:
            self.scene.removeItem(self.preview_jump_link_item)
            self.preview_jump_link_item = None

    def _delete_waypoint_by_id(self, wp_id_to_delete):
        """주어진 ID를 가진 웨이포인트를 삭제하고, 모든 경로 프로필에서 해당 ID를 제거합니다."""
        if not wp_id_to_delete: return
        
        # 씬에서 아이템 삭제
        items_to_remove = [item for item in self.scene.items() if item.data(1) == wp_id_to_delete]
        for item in items_to_remove:
            self.scene.removeItem(item)
            
        # 다이얼로그의 geometry_data 복사본에서 웨이포인트 삭제
        self.geometry_data["waypoints"] = [
            wp for wp in self.geometry_data.get("waypoints", [])
            if wp.get("id") != wp_id_to_delete
        ]
        
        # MapTab의 원본 route_profiles 데이터에서 직접 ID 제거 ---
        if self.parent_map_tab and hasattr(self.parent_map_tab, '_remove_waypoint_from_all_routes'):
            self.parent_map_tab._remove_waypoint_from_all_routes(wp_id_to_delete)

        self.view.viewport().update()

    def _delete_jump_link_by_id(self, link_id_to_delete):
        """주어진 ID의 점프 링크를 삭제하고, UI를 즉시 갱신합니다."""
        if not link_id_to_delete: return

        try:
            # --- 단계 1: 데이터에서 링크 제거 ---
            initial_count = len(self.geometry_data.get("jump_links", []))
            self.geometry_data["jump_links"] = [
                link for link in self.geometry_data.get("jump_links", [])
                if link.get("id") != link_id_to_delete
            ]
            
            # 실제로 데이터가 삭제되었는지 확인 후 UI 갱신
            if len(self.geometry_data.get("jump_links", [])) < initial_count:
                
                # --- 단계 2: 이름 갱신 및 전체 씬 다시 그리기 (성공 사례 모방) ---
                self._assign_dynamic_names()
                self.populate_scene()
                self.view.viewport().update()

        except Exception as e:
            print(f"ERROR in _delete_jump_link_by_id: {e}")
            traceback.print_exc()
            
    def get_updated_geometry_data(self):
        """편집된 지오메트리 데이터의 복사본을 반환합니다."""
        return self.geometry_data
    
    def accept(self):
        if self.is_drawing_line:
            self._finish_drawing_line()
        if self.is_drawing_object:
            self._finish_drawing_object(cancel=True)
        super().accept()

# --- v9.0.0: 실시간 뷰를 위한 커스텀 위젯 ---



class ActionLearningDialog(QDialog):
    """플레이어의 동작을 학습시키기 위한 데이터 수집 UI."""
    #  삭제 버튼 상태 업데이트를 위한 시그널
    enable_delete_button_signal = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_map_tab = parent
        self.setWindowTitle("동작 학습 모드")
        self.setMinimumSize(400, 320)

        # 학습 목록에서 on_ladder_idle 제거
        self.actions = [
            "climb_up_ladder",
            "climb_down_ladder",
            "fall"
        ]
        self.action_labels = {
            "climb_up_ladder": "사다리 오르기",
            "climb_down_ladder": "사다리 내려오기",
            "fall": "낙하 (아래점프 or 낭떠러지)"
        }

        # --- UI 위젯 생성 ---
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.action_combo = QComboBox()
        for action in self.actions:
            self.action_combo.addItem(self.action_labels[action], action)
        
        self.status_label = QLabel("학습할 동작을 선택하고 버튼을 누르세요.")
        self.status_label.setWordWrap(True)
        
        self.data_count_label = QTextEdit()
        self.data_count_label.setReadOnly(True)
        self.data_count_label.setFixedHeight(100)

        form_layout.addRow("동작 선택:", self.action_combo)
        form_layout.addRow("상태:", self.status_label)
        form_layout.addRow("수집된 데이터:", self.data_count_label)
        
        layout.addLayout(form_layout)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("학습 시작")
        self.delete_last_button = QPushButton("마지막 학습 삭제")
        self.train_button = QPushButton("모델 학습")
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.delete_last_button)
        button_layout.addWidget(self.train_button)
        layout.addLayout(button_layout)
        
        self.close_button = QPushButton("닫기")
        layout.addWidget(self.close_button)

        # --- 시그널-슬롯 연결 및 초기 상태 설정 ---
        self.start_button.clicked.connect(self.start_learning)
        self.delete_last_button.clicked.connect(self.delete_last_data)
        self.train_button.clicked.connect(self.train_model)
        self.close_button.clicked.connect(self.accept)
        
        self.enable_delete_button_signal.connect(self.delete_last_button.setEnabled)
        self.parent_map_tab.collection_status_signal.connect(self.on_collection_status_changed)

        # --- 초기화 호출 ---
        self.delete_last_button.setEnabled(False)
        self.update_data_counts()

    def start_learning(self):
        """1초 대기 후 움직임 감지 상태로 전환하거나, 수집을 취소합니다."""
        # '취소' 기능
        if self.parent_map_tab.is_waiting_for_movement:
            self.parent_map_tab.cancel_action_collection()
            return

        if not self.parent_map_tab.detection_thread or not self.parent_map_tab.detection_thread.isRunning():
            QMessageBox.warning(self, "오류", "먼저 '탐지 시작'을 눌러주세요.")
            return

        self.set_buttons_enabled(False)
        self.start_button.setEnabled(True)
        self.start_button.setText("취소")
        self.status_label.setText("1초 후 움직임을 감지합니다...")
        
        QTimer.singleShot(1000, self.prepare_for_movement_detection)

    def prepare_for_movement_detection(self):
        """MapTab에 감지 시작을 요청하고 UI를 업데이트합니다."""
        action_text = self.action_combo.currentText()
        selected_action = self.action_combo.currentData()
        
        # [MODIFIED] action_text를 직접 인자로 전달
        self.parent_map_tab.prepare_for_action_collection(selected_action, action_text)

    def on_collection_status_changed(self, status, message, can_delete):
        """MapTab으로부터 데이터 수집 상태 변경 신호를 받아 UI를 갱신합니다."""
        self.status_label.setText(message)

        if status == "finished":
            self.update_data_counts()
            self.set_buttons_enabled(True)
            self.start_button.setText("학습 시작")
            self.delete_last_button.setEnabled(can_delete)
        elif status == "waiting":
            self.start_button.setText("취소")
        elif status == "collecting":
            self.start_button.setText("수집 중단")
        elif status == "canceled":
            self.set_buttons_enabled(True)
            self.start_button.setText("학습 시작")

    # start_learning 메서드 전체 교체
    def start_learning(self):
        """
        [MODIFIED] v16.1: 수동 수집 로직 제거 후 단일 자동 수집 로직으로 복원.
        1초 대기 후 움직임 감지 상태로 전환하거나, 수집을 취소합니다.
        """
        # '취소' 기능 (is_waiting_for_movement는 MapTab의 변수)
        if self.parent_map_tab.is_waiting_for_movement:
            self.parent_map_tab.cancel_action_collection()
            return

        if not self.parent_map_tab.detection_thread or not self.parent_map_tab.detection_thread.isRunning():
            QMessageBox.warning(self, "오류", "먼저 '탐지 시작'을 눌러주세요.")
            return

        self.set_buttons_enabled(False)
        self.start_button.setEnabled(True)
        self.start_button.setText("취소")
        self.status_label.setText("1초 후 움직임을 감지합니다...")
        
        QTimer.singleShot(1000, self.prepare_for_movement_detection)

    def delete_last_data(self):
        self.parent_map_tab.delete_last_action_data()
        self.update_data_counts()
        self.delete_last_button.setEnabled(False)
        self.status_label.setText("마지막 데이터를 삭제했습니다.")

    def set_buttons_enabled(self, enabled):
        self.start_button.setEnabled(enabled)
        self.delete_last_button.setEnabled(enabled and self.parent_map_tab.last_collected_filepath is not None)
        self.train_button.setEnabled(enabled)
        self.action_combo.setEnabled(enabled)

    def train_model(self):
        """학습 스레드를 시작하고 진행률 대화 상자를 표시합니다."""
        # <<< [수정] 아래 profile_path 가져오는 부분 수정
        model_path = self.parent_map_tab._get_global_action_model_path()

        self.set_buttons_enabled(False)

        self.progress_dialog = QProgressDialog("모델 학습 준비 중...", "취소", 0, 100, self)
        self.progress_dialog.setWindowTitle("학습 진행 중")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()

        # <<< [수정] ActionTrainingThread 생성자 인자 수정
        self.training_thread = ActionTrainingThread(model_path, self.parent_map_tab)
        self.training_thread.progress_updated.connect(self.update_progress)
        self.training_thread.training_finished.connect(self.on_training_finished)
        self.progress_dialog.canceled.connect(self.training_thread.stop)
        self.training_thread.start()
        
    def update_progress(self, message, value):
        if self.progress_dialog:
            self.progress_dialog.setLabelText(message)
            self.progress_dialog.setValue(value)

    def on_training_finished(self, success, message):
        if self.progress_dialog:
            self.progress_dialog.close()
        
        if success:
            QMessageBox.information(self, "학습 완료", message)
            self.parent_map_tab.load_action_model()
        else:
            QMessageBox.critical(self, "학습 실패", message)

        self.set_buttons_enabled(True)
        
    def update_data_counts(self):
        """수집된 데이터 파일의 개수를 세어 UI에 표시합니다."""
        # <<< [수정] 아래 data_dir 가져오는 부분 수정
        model_dir = self.parent_map_tab._get_global_action_model_path()
        data_dir = os.path.join(model_dir, 'action_data')
        
        if not os.path.exists(data_dir):
            self.data_count_label.setText("수집된 데이터가 없습니다.")
            return
        
        counts = {action: 0 for action in self.actions}
        for filename in os.listdir(data_dir):
            for action in self.actions:
                if filename.startswith(action):
                    counts[action] += 1
        
        text = ""
        for action, count in counts.items():
            text += f"- {self.action_labels[action]}: {count}개\n"
        self.data_count_label.setText(text)

    def cancel_action_collection(self):
        """데이터 수집 대기 또는 진행을 취소합니다."""
        was_waiting = self.is_waiting_for_movement
        was_collecting = self.is_collecting_action_data

        self.is_waiting_for_movement = False
        self.is_collecting_action_data = False
        self.action_data_buffer = []
        self.last_pos_before_collection = None

        if was_waiting or was_collecting:
            self.collection_status_signal.emit("canceled", "학습이 취소되었습니다. 다시 시작하세요.", False)

# [v11.3.0] 상태 판정 설정을 위한 팝업 다이얼로그 클래스
class StateConfigDialog(QDialog):
    def __init__(self, current_config, parent=None):
        """
        [MODIFIED] v14.3.10: 누락된 메서드 복원 및 UI 생성 로직 개선.
        """
        super().__init__(parent)
        self.parent_map_tab = parent 
        self.setWindowTitle("판정 설정")
        self.setMinimumWidth(450)
        
        self.config = current_config.copy()
        if isinstance(self.config.get("walk_teleport_probability"), (int, float)) and self.config["walk_teleport_probability"] <= 1.0:
            self.config["walk_teleport_probability"] *= 100.0
        self.config.setdefault("walk_teleport_bonus_delay", WALK_TELEPORT_BONUS_DELAY_DEFAULT)
        self.config.setdefault("walk_teleport_bonus_step", WALK_TELEPORT_BONUS_STEP_DEFAULT)
        self.config.setdefault("walk_teleport_bonus_max", WALK_TELEPORT_BONUS_MAX_DEFAULT)
        self.config.setdefault("prepare_timeout", PREPARE_TIMEOUT)
        self.config.setdefault("max_lock_duration", MAX_LOCK_DURATION)
        self.config.setdefault("ladder_avoidance_width", LADDER_AVOIDANCE_WIDTH)
        self.config.setdefault("edgefall_timeout_sec", 3.0)
        
        main_layout = QVBoxLayout(self)
        self.spinboxes = {}

        # --- UI 생성 시작 ---

        # 1. 점프 특성 그룹
        jump_profile_group = QGroupBox("점프 특성 (자동 측정 권장)")
        jump_form_layout = QFormLayout(jump_profile_group)

        # 최대 점프 시간
        h_layout_duration = QHBoxLayout()
        spinbox_duration = QDoubleSpinBox()
        spinbox_duration.setRange(0.1, 10.0); spinbox_duration.setSingleStep(0.1)
        spinbox_duration.setValue(self.config.get("max_jump_duration", 3.0))
        self.spinboxes["max_jump_duration"] = spinbox_duration
        btn_measure = QPushButton("자동 측정 (10회)")
        btn_measure.setToolTip("버튼을 누르고, 게임 화면에서 평소처럼 10회 점프하세요.\n가장 신뢰성 있는 평균값이 자동으로 계산됩니다.")
        btn_measure.clicked.connect(self.measure_jump_profile)
        h_layout_duration.addWidget(spinbox_duration)
        h_layout_duration.addWidget(btn_measure)
        jump_form_layout.addRow("최대 점프 시간(초):", h_layout_duration)

        # 최대 점프 Y 오프셋 (측정 버튼은 하나로 통합)
        spinbox_y_offset = QDoubleSpinBox()
        spinbox_y_offset.setRange(1.0, 50.0); spinbox_y_offset.setSingleStep(0.1)
        spinbox_y_offset.setValue(self.config.get("jump_y_max_threshold", 10.5))
        self.spinboxes["jump_y_max_threshold"] = spinbox_y_offset
        jump_form_layout.addRow("최대 점프 Y오프셋(px):", spinbox_y_offset)
        
        main_layout.addWidget(jump_profile_group)

        # 2. 기타 판정 설정 그룹
        other_settings_group = QGroupBox("기타 판정 설정")
        form_layout = QFormLayout(other_settings_group)
        main_layout.addWidget(other_settings_group)
        
        # 스핀박스들을 동적으로 추가하는 헬퍼 함수
        def add_spinbox(key, label, min_val, max_val, step, is_double=True, decimals=2):
            default_val = 0.0 if is_double else 0
            if is_double:
                spinbox = QDoubleSpinBox()
                spinbox.setDecimals(decimals)
            else:
                spinbox = QSpinBox()
            
            spinbox.setRange(min_val, max_val)
            spinbox.setSingleStep(step)
            value = self.config.get(key, default_val)
            if value is None:
                value = default_val
            try:
                spinbox.setValue(value)
            except TypeError:
                spinbox.setValue(default_val)
            self.spinboxes[key] = spinbox
            form_layout.addRow(label, spinbox)

        add_spinbox("idle_time_threshold", "정지 판정 시간(초):", 0.1, 5.0, 0.1)
        add_spinbox("climbing_state_frame_threshold", "등반 판정 프레임:", 1, 100, 1, is_double=False)
        add_spinbox("falling_state_frame_threshold", "낙하 판정 프레임:", 1, 100, 1, is_double=False)
        add_spinbox("jumping_state_frame_threshold", "점프 판정 프레임:", 1, 100, 1, is_double=False)
        form_layout.addRow(QLabel("---"))
        add_spinbox("on_terrain_y_threshold", "지상 판정 Y오차(px):", 1.0, 30.0, 0.1)
        add_spinbox("jump_y_min_threshold", "점프 최소 Y오프셋(px):", 0.01, 30.0, 0.01)
        add_spinbox("fall_y_min_threshold", "낙하 최소 Y오프셋(px):", 1.0, 30.0, 0.1)
        form_layout.addRow(QLabel("---"))
        add_spinbox("move_deadzone", "X/Y 이동 감지 최소값(px):", 0.0, 5.0, 0.01, decimals=2)
        add_spinbox("y_movement_deadzone", "상승/하강 감지 Y최소값(px/f):", 0.01, 5.0, 0.01, decimals=2)
        add_spinbox("climb_x_movement_threshold", "등반 최대 X이동(px/f):", 0.01, 5.0, 0.01)
        add_spinbox("fall_on_ladder_x_movement_threshold", "사다리 낙하 최대 X이동(px/f):", 0.01, 5.0, 0.01)
        add_spinbox("ladder_x_grab_threshold", "사다리 근접 X오차(px):", 0.5, 20.0, 0.1)
        add_spinbox("ladder_avoidance_width", "사다리 주변 안전거리(px):", 0.0, 30.0, 0.1)
        # [신규] 사다리 주변 아래점프 안전거리(px): 아래점프 키 전송 허용 최소 거리
        add_spinbox("ladder_down_jump_min_distance", "사다리 주변 아래점프 안전거리(px):", 0.0, 30.0, 0.1)
        add_spinbox("stuck_detection_wait", "자동 복구 대기시간(초):", 0.1, 5.0, 0.1)
        add_spinbox("airborne_recovery_wait", "공중 자동복구 대기시간(초):", 0.5, 10.0, 0.1)
        add_spinbox("ladder_recovery_resend_delay", "사다리 복구 재전송 지연(초):", 0.05, 10.0, 0.05)
        add_spinbox("prepare_timeout", "행동 준비 시간 제한(초):", 0.5, 30.0, 0.5)
        add_spinbox("edgefall_timeout_sec", "낭떠러지 낙하 대기시간(초):", 0.5, 10.0, 0.1)
        # [신규] 낭떠러지 낙하 활성 임계 X거리(px)
        add_spinbox("edgefall_trigger_distance", "낭떠러지 낙하 임계거리(px):", 0.0, 20.0, 0.1)
        add_spinbox("max_lock_duration", "행동 진행 잠금 시간(초):", 0.5, 30.0, 0.5)
        add_spinbox("on_ladder_enter_frame_threshold", "사다리 탑승 판정 프레임:", 1, 10, 1, is_double=False)
        add_spinbox("jump_initial_velocity_threshold", "점프 초기 속도 임계값(px/f):", 1.0, 10.0, 0.1)
        add_spinbox("climb_max_velocity", "등반 최대 속도(px/f):", 1.0, 10.0, 0.1)
        form_layout.addRow(QLabel("---"))
        add_spinbox("waypoint_arrival_x_threshold_min", "웨이포인트 도착 X오차 최소값(px):", 0.0, 20.0, 0.1)
        add_spinbox("waypoint_arrival_x_threshold_max", "웨이포인트 도착 X오차 최대값(px):", 0.0, 20.0, 0.1)
        add_spinbox("ladder_arrival_x_threshold", "사다리 도착 X오차(px):", 0.0, 20.0, 0.1)
        add_spinbox("ladder_arrival_short_threshold", "사다리 도착 짧은 X오차(px):", 0.0, 20.0, 0.1)
        short_default = self.config.get("ladder_arrival_short_threshold", LADDER_ARRIVAL_SHORT_THRESHOLD)
        if short_default is None:
            short_default = LADDER_ARRIVAL_SHORT_THRESHOLD
        try:
            self.spinboxes["ladder_arrival_short_threshold"].setValue(short_default)
        except TypeError:
            self.spinboxes["ladder_arrival_short_threshold"].setValue(LADDER_ARRIVAL_SHORT_THRESHOLD)
        add_spinbox("jump_link_arrival_x_threshold", "점프/낭떠러지 도착 X오차(px):", 0.0, 20.0, 0.1)
        form_layout.addRow(QLabel("---"))
        add_spinbox("arrival_frame_threshold", "도착 판정 프레임:", 1, 10, 1, is_double=False)
        add_spinbox("action_success_frame_threshold", "행동 성공 판정 프레임:", 1, 10, 1, is_double=False)
        form_layout.addRow(QLabel("---"))
        add_spinbox("walk_teleport_probability", "걷기 텔레포트 확률(%):", 0.0, 100.0, 1.0, decimals=1)
        add_spinbox("walk_teleport_interval", "걷기 텔레포트 판정 주기(초):", 0.1, 10.0, 0.1)
        add_spinbox("walk_teleport_bonus_delay", "걷기 텔레포트 보너스 간격(초):", 0.1, 10.0, 0.1)
        add_spinbox("walk_teleport_bonus_step", "걷기 텔레포트 보너스 증가율(%):", 0.0, 100.0, 1.0, decimals=1)
        add_spinbox("walk_teleport_bonus_max", "걷기 텔레포트 보너스 최대(%):", 0.0, 100.0, 1.0, decimals=1)
        
        # 3. 하단 버튼
        button_box = QDialogButtonBox()
        save_btn = button_box.addButton("저장", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        default_btn = button_box.addButton("기본값 복원", QDialogButtonBox.ButtonRole.ResetRole)
        main_layout.addWidget(button_box)
        
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        default_btn.clicked.connect(self.restore_defaults)
        
        if self.parent_map_tab:
            self.parent_map_tab.jump_profile_measured_signal.connect(self.update_jump_profile)

    def measure_jump_profile(self):
        """
        [PATCH] v14.3.10: MapTab에 점프 특성 프로파일링을 요청하고 진행률 대화 상자를 표시합니다.
        """
        if not self.parent_map_tab or not hasattr(self.parent_map_tab, 'detection_thread'):
            QMessageBox.critical(self, "오류", "부모 MapTab에 접근할 수 없습니다.")
            return

        if not self.parent_map_tab.detection_thread or not self.parent_map_tab.detection_thread.isRunning():
            QMessageBox.warning(self, "오류", "먼저 '탐지 시작'을 눌러주세요.")
            return
        
        # MapTab에 프로파일링 시작을 알림
        self.parent_map_tab.start_jump_profiling()
        
        # 진행률 표시줄 생성 및 설정
        self.progress_dialog = QProgressDialog("점프 0/10회 수행됨. 게임에서 점프하세요.", "취소", 0, 10, self)
        self.progress_dialog.setWindowTitle("점프 특성 측정 중")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        
        # 시그널 연결
        self.progress_dialog.canceled.connect(self.parent_map_tab.cancel_jump_profiling)
        self.parent_map_tab.jump_profile_progress_signal.connect(self.progress_dialog.setValue)
        self.parent_map_tab.jump_profile_progress_signal.connect(lambda val: self.progress_dialog.setLabelText(f"점프 {val}/10회 수행됨. 계속 점프하세요."))
        
        self.progress_dialog.show()

    def update_jump_profile(self, duration, y_offset):
        """
        [PATCH] v14.3.10: 측정된 값으로 스핀박스 값을 업데이트하고 결과 팝업을 표시합니다.
        """
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()

        if duration > 0 and y_offset > 0:
            if "max_jump_duration" in self.spinboxes:
                self.spinboxes["max_jump_duration"].setValue(duration)
            if "jump_y_max_threshold" in self.spinboxes:
                self.spinboxes["jump_y_max_threshold"].setValue(y_offset)
            
            QMessageBox.information(self, "측정 완료", f"측정이 완료되었습니다.\n- 최대 점프 시간: {duration:.2f}초\n- 최대 점프 Y오프셋: {y_offset:.2f}px")
        else:
            QMessageBox.warning(self, "측정 실패", "유효한 점프 데이터가 10회 수집되지 않았습니다.\n다시 시도해주세요.")

    #  v14.3.10: 누락되었던 메서드 복원
    def get_updated_config(self):
        """UI의 현재 값들을 딕셔너리로 반환합니다."""
        updated_config = {}
        for key, spinbox in self.spinboxes.items():
            updated_config[key] = spinbox.value()
        return updated_config

    #  v14.3.10: 누락되었던 메서드 복원
    def restore_defaults(self):
        """모든 설정 값을 코드에 정의된 기본값으로 복원합니다."""
        # 동바산6의 판정설정 값을 우선 적용, 없으면 코드 상수로 대체
        _baseline = {}
        try:
            _baseline = load_baseline_state_machine_config()
        except Exception:
            _baseline = {}

        defaults = {
            "idle_time_threshold": IDLE_TIME_THRESHOLD,
            "max_jump_duration": MAX_JUMP_DURATION,
            "climbing_state_frame_threshold": CLIMBING_STATE_FRAME_THRESHOLD,
            "falling_state_frame_threshold": FALLING_STATE_FRAME_THRESHOLD,
            "jumping_state_frame_threshold": JUMPING_STATE_FRAME_THRESHOLD,
            "on_terrain_y_threshold": ON_TERRAIN_Y_THRESHOLD,
            "jump_y_min_threshold": JUMP_Y_MIN_THRESHOLD,
            "jump_y_max_threshold": JUMP_Y_MAX_THRESHOLD,
            "fall_y_min_threshold": FALL_Y_MIN_THRESHOLD,
            "move_deadzone": MOVE_DEADZONE,
            "y_movement_deadzone": Y_MOVEMENT_DEADZONE,
            "climb_x_movement_threshold": CLIMB_X_MOVEMENT_THRESHOLD,
            "fall_on_ladder_x_movement_threshold": FALL_ON_LADDER_X_MOVEMENT_THRESHOLD,
            "ladder_x_grab_threshold": LADDER_X_GRAB_THRESHOLD,
            "ladder_avoidance_width": LADDER_AVOIDANCE_WIDTH,
            # [신규 기본값] 아래점프 허용 최소 사다리 거리(px)
            "ladder_down_jump_min_distance": 2.0,
            "on_ladder_enter_frame_threshold": 1,
            "jump_initial_velocity_threshold": 1.0,
            "climb_max_velocity": 1.0,
            "waypoint_arrival_x_threshold": WAYPOINT_ARRIVAL_X_THRESHOLD,
            "waypoint_arrival_x_threshold_min": WAYPOINT_ARRIVAL_X_THRESHOLD_MIN_DEFAULT,
            "waypoint_arrival_x_threshold_max": WAYPOINT_ARRIVAL_X_THRESHOLD_MAX_DEFAULT,
            "ladder_arrival_x_threshold": LADDER_ARRIVAL_X_THRESHOLD,
            "ladder_arrival_short_threshold": LADDER_ARRIVAL_SHORT_THRESHOLD,
            "jump_link_arrival_x_threshold": JUMP_LINK_ARRIVAL_X_THRESHOLD,
            "arrival_frame_threshold": 2,
            "action_success_frame_threshold": 2,
            "stuck_detection_wait": STUCK_DETECTION_WAIT_DEFAULT,
            "airborne_recovery_wait": AIRBORNE_RECOVERY_WAIT_DEFAULT,
            "ladder_recovery_resend_delay": LADDER_RECOVERY_RESEND_DELAY_DEFAULT,
            "prepare_timeout": PREPARE_TIMEOUT,
            "max_lock_duration": MAX_LOCK_DURATION,
            "walk_teleport_probability": WALK_TELEPORT_PROBABILITY_DEFAULT,
            "walk_teleport_interval": WALK_TELEPORT_INTERVAL_DEFAULT,
            "walk_teleport_bonus_delay": WALK_TELEPORT_BONUS_DELAY_DEFAULT,
            "walk_teleport_bonus_step": WALK_TELEPORT_BONUS_STEP_DEFAULT,
            "walk_teleport_bonus_max": WALK_TELEPORT_BONUS_MAX_DEFAULT,
            "edgefall_timeout_sec": 3.0,
            "edgefall_trigger_distance": 2.0,
        }
        # baseline 값으로 덮어쓰기(존재하는 키만)
        for k, v in (_baseline.items() if isinstance(_baseline, dict) else {}).items():
            if k in defaults:
                defaults[k] = v
        for key, spinbox in self.spinboxes.items():
            if key in defaults:
                spinbox.setValue(defaults[key])

#  WinEventFilter: PyQt의 네이티브 이벤트 필터를 사용하여 WM_HOTKEY 메시지를 감지
class WinEventFilter(QAbstractNativeEventFilter):
    def __init__(self, callback, hotkey_id=None):
        super().__init__()
        self.callback = callback
        self.hotkey_id = hotkey_id

    def nativeEventFilter(self, event_type, message):
        if event_type == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == win32con.WM_HOTKEY and (self.hotkey_id is None or msg.wParam == self.hotkey_id):
                self.callback()
        return False, 0

#  HotkeyManager: 단축키 문자열을 파싱하고 win32api를 호출하여 등록/해제하는 역할만 담당 (스레드 아님)
class HotkeyManager:
    def __init__(self):
        self.hotkey_id = 1
        self.current_hotkey_str = None
        self.MOD_MAP = {"alt": win32con.MOD_ALT, "ctrl": win32con.MOD_CONTROL, "shift": win32con.MOD_SHIFT}
        self.VK_MAP = {f"f{i}": getattr(win32con, f"VK_F{i}") for i in range(1, 13)}
        
        # --- [수정] ctypes를 사용하여 user32.dll에서 직접 함수를 가져옴 ---
        self.user32 = ctypes.windll.user32

    def register_hotkey(self, hotkey_str):
        self.unregister_hotkey() # 기존 단축키가 있다면 먼저 해제
        self.current_hotkey_str = hotkey_str.lower()
        
        if not self.current_hotkey_str or self.current_hotkey_str == 'none':
            print("[HotkeyManager] 등록할 단축키가 없습니다.")
            return

        parts = self.current_hotkey_str.split('+')
        mods, vk = 0, None
        for part in parts:
            if part in self.MOD_MAP:
                mods |= self.MOD_MAP[part]
            elif part in self.VK_MAP:
                vk = self.VK_MAP[part]
        
        if vk is not None:
            # --- [수정] win32api 대신 self.user32.RegisterHotKey 사용 ---
            if self.user32.RegisterHotKey(None, self.hotkey_id, mods, vk):
                print(f"[HotkeyManager] 전역 단축키 '{self.current_hotkey_str.upper()}' 등록 성공.")
            else:
                # 실패 시 에러 코드 확인
                error_code = ctypes.windll.kernel32.GetLastError()
                print(f"[HotkeyManager] 전역 단축키 '{self.current_hotkey_str.upper()}' 등록 실패. (에러 코드: {error_code})")


    def unregister_hotkey(self):
        if self.current_hotkey_str:
            try:
                # --- [수정] win32api 대신 self.user32.UnregisterHotKey 사용 ---
                self.user32.UnregisterHotKey(None, self.hotkey_id)
                print(f"[HotkeyManager] 단축키 '{self.current_hotkey_str.upper()}' 해제 완료.")
                self.current_hotkey_str = None
            except Exception as e:
                # 프로그램 종료 시 이미 해제되었을 수 있으므로 오류를 무시
                pass

# HotkeySettingDialog: 사용자로부터 새로운 단축키 입력을 받는 다이얼로그
class HotkeySettingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("단축키 설정")
        self.setFixedSize(300, 100)
        self.hotkey_str = ""
        
        layout = QVBoxLayout(self)
        self.label = QLabel("새로운 단축키를 누르세요...\n(Alt, Ctrl, Shift + F1~F12 조합만 가능)")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        
        mod_map = {
            Qt.KeyboardModifier.AltModifier: "alt",
            Qt.KeyboardModifier.ControlModifier: "ctrl",
            Qt.KeyboardModifier.ShiftModifier: "shift"
        }
        
        vk_map = {getattr(Qt.Key, f"Key_F{i}"): f"f{i}" for i in range(1, 13)}

        if key in vk_map:
            key_str = vk_map[key]
            mod_parts = [name for mod, name in mod_map.items() if mods & mod]
            
            self.hotkey_str = "+".join(sorted(mod_parts) + [key_str])
            self.label.setText(f"설정된 키: {self.hotkey_str.upper()}")
            QTimer.singleShot(500, self.accept) # 0.5초 후 자동 닫기
        else:
            self.label.setText("F1~F12 키만 기본 키로 사용할 수 있습니다.")
