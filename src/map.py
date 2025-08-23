# map.py
# 2025년 08月 22日 12:30 (KST)
# 기능: v11.0.0 - 버그 개선완료 - 미니맵 무한 확장, 미니맵 한장짜리 프로필 오류 해결

import sys
import os
import json
import cv2
import numpy as np
import mss
import base64
import time
import uuid
import math
import shutil
import copy
import traceback
from collections import defaultdict, deque
import threading # <<< [v11.0.0] 추가
import hashlib # [NEW] 동일 컨텍스트 판별용
import math    # [NEW] 0 오프셋 배제용

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QSpinBox, QDialog, QDialogButtonBox, QListWidget,
    QInputDialog, QListWidgetItem, QDoubleSpinBox, QAbstractItemView,
    QLineEdit, QRadioButton, QButtonGroup, QGroupBox, QComboBox,

    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsEllipseItem, QTabWidget,
    QGraphicsSimpleTextItem
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor, QIcon, QPolygonF, QFontMetrics, QFontMetricsF
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint, QRectF, QPointF, QSize, QSizeF

try:
    from Learning import ScreenSnipper
except ImportError:
    class ScreenSnipper(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            QMessageBox.critical(self, "오류", "Learning.py 모듈을 찾을 수 없어\n화면 영역 지정 기능을 사용할 수 없습니다.")
        def exec(self): return 0
        def get_roi(self): return QRect(0, 0, 100, 100)

# === [v11.0.0] 런타임 의존성 체크 (추가) ===
try:
    if not hasattr(cv2, "matchTemplate"):
        raise AttributeError("matchTemplate not found")
except AttributeError:
    raise RuntimeError("OpenCV 빌드에 matchTemplate이 없습니다. opencv-python 설치를 확인해주세요.")
except Exception as e:
    raise RuntimeError(f"필수 라이브러리(cv2, mss, numpy 등) 초기화 실패: {e}")


# === [v11.0.0] MapConfig: 중앙화된 설정 (추가) ===
MapConfig = {
    "downscale": 0.7,                # 탐지용 다운스케일 비율 (0.3~1.0)
    "target_fps": 20,                # 캡처 스레드 목표 FPS
    "detection_threshold_default": 0.85,
    "loop_time_fallback_ms": 120,    # 루프 시간이 이 값을 넘으면 폴백 적용
    "use_new_capture": True,         # Feature flag — 변경 시 레거시 모드로 자동 복귀 가능
}


# --- v4.0.0 경로 구조 변경 ---
SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..', 'workspace'))
CONFIG_PATH = os.path.join(WORKSPACE_ROOT, 'config')
MAPS_DIR = os.path.join(CONFIG_PATH, 'maps') # 모든 맵 프로필을 저장할 최상위 폴더
GLOBAL_MAP_SETTINGS_FILE = os.path.join(CONFIG_PATH, 'global_map_settings.json')

# 내 캐릭터 (노란색 계열)
PLAYER_ICON_LOWER = np.array([22, 120, 120])
PLAYER_ICON_UPPER = np.array([35, 255, 255])

# 다른 유저 (빨간색 계열)
OTHER_PLAYER_ICON_LOWER1 = np.array([0, 120, 120])
OTHER_PLAYER_ICON_UPPER1 = np.array([10, 255, 255])
OTHER_PLAYER_ICON_LOWER2 = np.array([170, 120, 120])
OTHER_PLAYER_ICON_UPPER2 = np.array([180, 255, 255])
PLAYER_Y_OFFSET = 1 # 플레이어 Y축 좌표 보정을 위한 오프셋. 양수 값은 기준점을 아래로 이동시킵니다.

#아이콘 크기 관련 상수 재정의 ---
MIN_ICON_WIDTH = 9
MIN_ICON_HEIGHT = 9
MAX_ICON_WIDTH = 20
MAX_ICON_HEIGHT = 20
PLAYER_ICON_STD_WIDTH = 11
PLAYER_ICON_STD_HEIGHT = 11

# ==================== v10.9.0 상태 판정 시스템 상수 ====================
# [v11.4.0] 사용자 피드백 기반 기본값 대규모 조정 및 신규 상수 추가
IDLE_TIME_THRESHOLD = 0.8       # 정지 상태로 판정되기까지의 시간 (초)
CLIMBING_STATE_FRAME_THRESHOLD = 2 # climbing 상태로 변경되기까지 필요한 연속 프레임
FALLING_STATE_FRAME_THRESHOLD = 10  # falling 상태로 변경되기까지 필요한 연속 프레임
JUMPING_STATE_FRAME_THRESHOLD = 1  # jumping 상태로 변경되기까지 필요한 연속 프레임
ON_TERRAIN_Y_THRESHOLD = 3.0    # 지상 판정 y축 허용 오차 (px)
JUMP_Y_MIN_THRESHOLD = 1.0      # 점프 상태로 인식될 최소 y 오프셋 (px)
JUMP_Y_MAX_THRESHOLD = 10.5     # 점프 상태로 인식될 최대 y 오프셋 (px)
FALL_Y_MIN_THRESHOLD = 4.0      # 낙하 상태로 인식될 최소 y 오프셋 (px)
CLIMB_X_MOVEMENT_THRESHOLD = 1.0 # 등반 상태로 판정될 최대 수평 이동량 (px/frame)
FALL_ON_LADDER_X_MOVEMENT_THRESHOLD = 1.0
Y_MOVEMENT_DEADZONE = 0.5       # 상승/하강으로 인식될 최소 y 이동량 (px/frame)
LADDER_X_GRAB_THRESHOLD = 8.0   # 사다리 근접으로 판정될 x축 허용 오차 (px)
MOVE_DEADZONE = 0.2             # 움직임으로 인식되지 않을 최소 이동 거리 (px)
MAX_JUMP_DURATION = 3.0         # 점프 상태가 강제로 해제되기까지의 최대 시간 (초)
# =================================================================

# --- 도착 판정 기준 ---
WAYPOINT_ARRIVAL_X_THRESHOLD = 8.0 # 웨이포인트 도착 x축 허용 오차 (px)
LADDER_ARRIVAL_X_THRESHOLD = 8.0   # 사다리 도착 x축 허용 오차 (px)
JUMP_LINK_ARRIVAL_X_THRESHOLD = 4.0 # 점프 링크/낭떠러지 도착 x축 허용 오차 (px)

# ==================== v11.5.0 상태 머신 상수 ====================
MAX_LOCK_DURATION = 60.0      # 행동 잠금(locked) 상태의 최대 지속 시간 (초)
PREPARE_TIMEOUT = 60.0         # 행동 준비(prepare_to_*) 상태의 최대 지속 시간 (초)
HYSTERESIS_EXIT_OFFSET = 4.0  # 도착 판정 히스테리시스 오프셋 (px)
# =================================================================

# --- v10.0.0: 네비게이터 위젯 클래스 ---
class NavigatorDisplay(QWidget):
    """실시간 내비게이션 정보를 그래픽으로 표시하는 위젯."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setMaximumHeight(80)

        # 데이터 초기화
        self.current_floor = "N/A"
        self.current_terrain_name = ""
        self.target_name = "없음" 
        self.player_state_text = "대기 중"
        self.nav_action_text = "경로 없음"
        self.previous_waypoint_name = ""
        self.next_waypoint_name = ""
        self.direction = "-"
        self.distance_px = 0
        self.full_path = []
        self.last_reached_wp_id = None
        self.target_wp_id = None
        self.is_forward = True
        self.intermediate_target_type = 'walk'

    def update_data(self, floor, terrain_name, target_name, prev_name, next_name, 
                    direction, distance, full_path, last_reached_id, target_id, 
                    is_forward, intermediate_type, player_state, nav_action):
        """MapTab으로부터 최신 내비게이션 정보를 받아와 뷰를 갱신합니다."""
        self.current_floor = str(floor)
        self.current_terrain_name = terrain_name
        self.target_name = target_name
        self.player_state_text = player_state
        self.nav_action_text = nav_action
        self.previous_waypoint_name = prev_name
        self.next_waypoint_name = next_name
        self.direction = direction
        self.distance_px = distance
        self.full_path = full_path
        self.last_reached_wp_id = last_reached_id
        self.target_wp_id = target_id
        self.is_forward = is_forward
        self.intermediate_target_type = intermediate_type
        self.update() # paintEvent 다시 호출

    def paintEvent(self, event):
            """수신된 내비게이션 데이터를 기반으로 위젯 UI를 그립니다."""
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            painter.fillRect(self.rect(), QColor("#2E2E2E"))

            total_width = self.width()
            total_height = self.height()

            # --- 1. 좌측 영역: 상태 정보 ---
            left_area_width = 100
            left_rect = QRect(0, 0, left_area_width, total_height)
            
            font_floor = QFont("맑은 고딕", 14, QFont.Weight.Bold)
            painter.setFont(font_floor)
            painter.setPen(Qt.GlobalColor.white)
            floor_rect = QRect(left_rect.x(), 5, left_rect.width(), 30)
            painter.drawText(floor_rect, Qt.AlignmentFlag.AlignCenter, f"{self.current_floor}층")

            font_terrain = QFont("맑은 고딕", 8)
            painter.setFont(font_terrain)
            painter.setPen(QColor("#9E9E9E"))
            terrain_rect = QRect(left_rect.x(), 30, left_rect.width(), 20)
            painter.drawText(terrain_rect, Qt.AlignmentFlag.AlignCenter, self.current_terrain_name)

            font_direction_side = QFont("맑은 고딕", 9)
            painter.setFont(font_direction_side)
            painter.setPen(Qt.GlobalColor.yellow)
            direction_text_side = f"{'정방향' if self.is_forward else '역방향'}"
            dist_rect = QRect(left_rect.x(), 50, left_rect.width(), 25)
            painter.drawText(dist_rect, Qt.AlignmentFlag.AlignCenter, direction_text_side)


            # --- 2. 중앙 영역: 경로 및 진행 정보 ---
            center_area_width = (total_width - left_area_width * 2) - 100 # 우측 영역을 위해 폭 조정
            center_area_x = left_area_width + 20
            center_rect = QRect(center_area_x, 0, int(center_area_width), total_height)

            font_dist_top = QFont("맑은 고딕", 11)
            painter.setFont(font_dist_top)
            painter.setPen(Qt.GlobalColor.white)
            dist_text_top = f"{self.direction} {self.distance_px:.0f}px" if self.target_wp_id else "-"
            direction_rect = QRect(center_rect.x(), 5, center_rect.width(), 20)
            painter.drawText(direction_rect, Qt.AlignmentFlag.AlignCenter, dist_text_top)
            
            path_area_rect = QRect(center_rect.x(), 20, center_rect.width(), 35)
            
            indicator_prev, indicator_curr, indicator_next = "", "", ""
            current_idx = -1
            total_steps = len(self.full_path)

            if self.target_wp_id and self.target_wp_id in self.full_path:
                current_idx = self.full_path.index(self.target_wp_id)
                circled_nums = [chr(0x2460 + i) for i in range(20)]

                def get_indicator(index):
                    if not self.full_path: return ""
                    if index == 0: return "🚩"
                    if index == len(self.full_path) - 1: return "🏁"
                    return circled_nums[index] if 0 <= index < len(circled_nums) else str(index + 1)

                indicator_curr = get_indicator(current_idx)
                if current_idx > 0:
                    indicator_prev = get_indicator(current_idx - 1)
                if current_idx < total_steps - 1:
                    indicator_next = get_indicator(current_idx + 1)
            
            font_name_side = QFont("맑은 고딕", 11)
            
            # v10.3.3: 긴 텍스트를 위한 동적 폰트 크기 조절
            if len(self.target_name) > 10:
                font_name_main = QFont("맑은 고딕", 11, QFont.Weight.Bold)
            else:
                font_name_main = QFont("맑은 고딕", 13, QFont.Weight.Bold)
            
            main_target_text = self.target_name
            if self.intermediate_target_type == 'climb':
                main_target_text = f"🔺 {self.target_name}"
            elif self.intermediate_target_type == 'fall':
                main_target_text = f"🔻 {self.target_name}"
            elif self.intermediate_target_type == 'jump':
                main_target_text = f"🤸 {self.target_name}"
            elif self.intermediate_target_type == 'walk':
                main_target_text = f"{indicator_curr} {self.target_name}" if indicator_curr else self.target_name

            painter.setFont(font_name_main)
            painter.setPen(QColor("lime"))
            painter.drawText(path_area_rect, Qt.AlignmentFlag.AlignCenter, main_target_text)

            font_name_side = QFont("맑은 고딕", 11)
            painter.setFont(font_name_side)
            painter.setPen(QColor("#9E9E9E"))
            prev_text = f"{indicator_prev} {self.previous_waypoint_name}" if self.previous_waypoint_name else ""
            painter.drawText(path_area_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, prev_text)
            
            next_text = f"{indicator_next} {self.next_waypoint_name}" if self.next_waypoint_name else ""
            painter.drawText(path_area_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, next_text)

            # 2-3. 하단: 진행 막대
            progress_text = ""
            progress_ratio = 0.0
            if self.full_path:
                total_steps = len(self.full_path)
                current_step = 0
                if self.last_reached_wp_id and self.last_reached_wp_id in self.full_path:
                    current_step = self.full_path.index(self.last_reached_wp_id) + 1
                
                if current_step > 0 or self.target_wp_id:
                    progress_text = f"{current_step} / {total_steps}"
                    if total_steps > 0:
                        progress_ratio = current_step / total_steps

            bar_height = 18
            bar_y = 58
            progress_bar_rect = QRect(center_rect.x(), bar_y, center_rect.width(), bar_height)

            painter.setPen(Qt.GlobalColor.black)
            painter.setBrush(QColor("#1C1C1C"))
            painter.drawRoundedRect(progress_bar_rect, 5, 5)

            if progress_ratio > 0:
                fill_width = int(progress_bar_rect.width() * progress_ratio)
                progress_fill_rect = QRect(progress_bar_rect.x(), progress_bar_rect.y(), fill_width, progress_bar_rect.height())
                painter.setBrush(QColor("dodgerblue"))
                painter.drawRoundedRect(progress_fill_rect, 5, 5)

            if progress_text:
                painter.setPen(Qt.GlobalColor.white)
                painter.setFont(QFont("맑은 고딕", 8, QFont.Weight.Bold))
                painter.drawText(progress_bar_rect, Qt.AlignmentFlag.AlignCenter, progress_text)

            # --- 3. 우측 영역: 상태 및 행동 안내 ---
            right_area_x = center_rect.right() + 20
            right_rect = QRect(right_area_x, 0, total_width - right_area_x, total_height)

            # 3-1. 현재 상태
            painter.setFont(QFont("맑은 고딕", 8))
            painter.setPen(QColor("#9E9E9E"))
            state_title_rect = QRect(right_rect.x(), 5, right_rect.width(), 15)
            painter.drawText(state_title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "현재 상태")
            
            painter.setFont(QFont("맑은 고딕", 11, QFont.Weight.Bold))
            painter.setPen(Qt.GlobalColor.white)
            state_text_rect = QRect(right_rect.x(), 20, right_rect.width(), 25)
            painter.drawText(state_text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.player_state_text)

            # 3-2. 필요 행동
            painter.setFont(QFont("맑은 고딕", 8))
            painter.setPen(QColor("#9E9E9E"))
            action_title_rect = QRect(right_rect.x(), 45, right_rect.width(), 15)
            painter.drawText(action_title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "필요 행동")

            painter.setFont(QFont("맑은 고딕", 11, QFont.Weight.Bold))
            painter.setPen(QColor("yellow"))
            action_text_rect = QRect(right_rect.x(), 55, right_rect.width(), 25)
            painter.drawText(action_text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.nav_action_text)

# --- 위젯 클래스 ---
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
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            # '기본' 모드일 때만 이름 변경 로직이 작동해야 함
            current_mode = self.parent_dialog.current_mode if self.parent_dialog else "select"
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
        self.render_options = render_options
        self.global_positions = global_positions
        self.parent_map_tab = parent
        self.active_route_profile = active_route_profile
        self.lod_threshold = 2.5  # 이름이 보이기 시작하는 줌 LOD 배율 (1.0 = 100%)
        self.lod_text_items = []  # LOD 적용 대상 텍스트 아이템 리스트
        
        # [v11.1.0] 좌표 텍스트를 위한 LOD 시스템 확장 (배율 조정)
        self.lod_coord_threshold = 6.0 # 좌표 텍스트가 보이기 시작하는 줌 배율
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
                font = QFont("맑은 고딕", 4, QFont.Weight.Bold) #층 이름 폰트 크기 미니맵 지형 편집기
                    
                text_item = QGraphicsTextItem(floor_text)
                text_item.setFont(font)
                text_item.setDefaultTextColor(Qt.GlobalColor.white)
                
                # 마우스 이벤트 무시 설정 (클릭 버그 수정)
                text_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

                text_rect = text_item.boundingRect()
                padding_x = -3 # 미니맵 지형 편집기 층 이름 텍스트 박스 크기 조절
                padding_y = -3
                bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

                base_pos_x = center_x - bg_rect_geom.width() / 2
                base_pos_y = max_y + 4

                background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
                background_rect.setBrush(QColor(0, 0, 0, 120))
                background_rect.setPen(QPen(Qt.GlobalColor.transparent))
                background_rect.setPos(base_pos_x, base_pos_y)
                
                text_item.setPos(base_pos_x + padding_x, base_pos_y + padding_y)

                background_rect.setData(0, "floor_text_bg")
                text_item.setData(0, "floor_text")
                
                background_rect.setZValue(5)
                text_item.setZValue(6)

                self.scene.addItem(background_rect)
                self.scene.addItem(text_item)
                # 미니맵 지형 편집기 층 이름 LOD 적용 대상 리스트에 추가 ---
                self.lod_text_items.append(background_rect)
                self.lod_text_items.append(text_item)

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
        self.select_mode_radio.setChecked(True)
        self.select_mode_radio.toggled.connect(lambda: self.set_mode("select"))
        self.terrain_mode_radio.toggled.connect(lambda: self.set_mode("terrain"))
        self.object_mode_radio.toggled.connect(lambda: self.set_mode("object"))
        self.waypoint_mode_radio.toggled.connect(lambda: self.set_mode("waypoint"))
        self.jump_mode_radio.toggled.connect(lambda: self.set_mode("jump"))
        mode_layout.addWidget(self.select_mode_radio)
        mode_layout.addWidget(self.terrain_mode_radio)
        mode_layout.addWidget(self.object_mode_radio)
        mode_layout.addWidget(self.waypoint_mode_radio)
        mode_layout.addWidget(self.jump_mode_radio)
        mode_box.setLayout(mode_layout)

        # 지형 입력 옵션
        terrain_opts_box = QGroupBox("지형 옵션")
        terrain_opts_layout = QVBoxLayout()
        self.y_lock_check = QCheckBox("Y축 고정") 
        self.x_lock_check = QCheckBox("X축 고정")
        self.y_lock_check.toggled.connect(self.on_y_lock_toggled)
        self.x_lock_check.toggled.connect(self.on_x_lock_toggled)
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
            'jump_links': self.chk_show_jump_links.isChecked()
        }
        
    def set_mode(self, mode):
        """편집기 모드를 변경하고 UI를 업데이트합니다."""
        self.current_mode = mode
        if self.is_drawing_line:
            self._finish_drawing_line()
        if self.is_drawing_object:
            self._finish_drawing_object(cancel=True)

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
                            text_item.setFont(QFont("맑은 고딕", 5)) #미니맵 지형 편집기 핵심지형 폰트 크기
                            text_item.setDefaultTextColor(Qt.GlobalColor.white)
                            text_rect = text_item.boundingRect()
                            text_item.setPos(pos + QPointF((pixmap.width() - text_rect.width()) / 2, (pixmap.height() - text_rect.height()) / 2))
                            text_item.setData(0, "feature")

                # 3. 모든 지오메트리 그리기 (층 번호 텍스트 제외)
                for line_data in self.geometry_data.get("terrain_lines", []):
                    points = line_data.get("points", [])
                    if len(points) >= 2:
                        for i in range(len(points) - 1):
                            p1 = QPointF(points[i][0], points[i][1])
                            p2 = QPointF(points[i+1][0], points[i+1][1])
                            self._add_terrain_line_segment(p1, p2, line_data['id'])
                        for p in points:
                            self._add_vertex_indicator(QPointF(p[0], p[1]), line_data['id'])

                        # [v11.2.8] 지형선 양 끝 꼭짓점 좌표 텍스트 (위치 계산 수정)
                        p_start = QPointF(points[0][0], points[0][1])
                        p_end = QPointF(points[-1][0], points[-1][1])

                        left_point = p_start if p_start.x() <= p_end.x() else p_end
                        right_point = p_end if p_start.x() <= p_end.x() else p_start

                        # 좌측 꼭짓점 좌표
                        left_text_str = f"({left_point.x():.1f}, {left_point.y():.1f})"
                        bg_item, text_item = self._create_coord_text_item(left_text_str, QColor("magenta"), None)
                        bg_rect = bg_item.boundingRect()
                        text_rect = text_item.boundingRect()
                        bg_item.setPos(left_point.x() - bg_rect.width() / 2, left_point.y() + 1)
                        text_item.setPos(bg_item.x() + (bg_rect.width() - text_rect.width()) / 2, bg_item.y() + (bg_rect.height() - text_rect.height()) / 2)
                        self.scene.addItem(bg_item)
                        self.scene.addItem(text_item)
                        self.lod_coord_items.extend([bg_item, text_item])
                        
                        # 우측 꼭짓점 좌표
                        if left_point != right_point:
                            right_text_str = f"({right_point.x():.1f}, {right_point.y():.1f})"
                            bg_item, text_item = self._create_coord_text_item(right_text_str, QColor("magenta"), None)
                            bg_rect = bg_item.boundingRect()
                            text_rect = text_item.boundingRect()
                            bg_item.setPos(right_point.x() - bg_rect.width() / 2, right_point.y() - bg_rect.height() - 1)
                            text_item.setPos(bg_item.x() + (bg_rect.width() - text_rect.width()) / 2, bg_item.y() + (bg_rect.height() - text_rect.height()) / 2)
                            self.scene.addItem(bg_item)
                            self.scene.addItem(text_item)
                            self.lod_coord_items.extend([bg_item, text_item])

                for obj_data in self.geometry_data.get("transition_objects", []):
                    points = obj_data.get("points", [])
                    if len(points) == 2:
                        p1_pos = QPointF(points[0][0], points[0][1])
                        p2_pos = QPointF(points[1][0], points[1][1])
                        line_item = self._add_object_line(p1_pos, p2_pos, obj_data['id'])
                        
                        # [v11.2.8] 층 이동 오브젝트 좌표 텍스트 (위치 계산 수정)
                        upper_point = p1_pos if p1_pos.y() < p2_pos.y() else p2_pos
                        lower_point = p2_pos if p1_pos.y() < p2_pos.y() else p1_pos

                        # 위쪽 꼭짓점 좌표
                        upper_text_str = f"({upper_point.x():.1f}, {upper_point.y():.1f})"
                        bg_item, text_item = self._create_coord_text_item(upper_text_str, QColor("orange"), None)
                        bg_rect = bg_item.boundingRect()
                        text_rect = text_item.boundingRect()
                        bg_item.setPos(upper_point.x() - bg_rect.width() / 2, upper_point.y())
                        text_item.setPos(bg_item.x() + (bg_rect.width() - text_rect.width()) / 2, bg_item.y() + (bg_rect.height() - text_rect.height()) / 2)
                        self.scene.addItem(bg_item)
                        self.scene.addItem(text_item)
                        self.lod_coord_items.extend([bg_item, text_item])

                        # 아래쪽 꼭짓점 좌표
                        lower_text_str = f"({lower_point.x():.1f}, {lower_point.y():.1f})"
                        bg_item, text_item = self._create_coord_text_item(lower_text_str, QColor("orange"), None)
                        bg_rect = bg_item.boundingRect()
                        text_rect = text_item.boundingRect()
                        bg_item.setPos(lower_point.x() - bg_rect.width() / 2, lower_point.y() - bg_rect.height())
                        text_item.setPos(bg_item.x() + (bg_rect.width() - text_rect.width()) / 2, bg_item.y() + (bg_rect.height() - text_rect.height()) / 2)
                        self.scene.addItem(bg_item)
                        self.scene.addItem(text_item)
                        self.lod_coord_items.extend([bg_item, text_item])

                        if 'dynamic_name' in obj_data:
                            name = obj_data['dynamic_name']
                            font = QFont("맑은 고딕", 3, QFont.Weight.Bold)
                            text_item = QGraphicsTextItem(name)
                            text_item.setFont(font)
                            text_item.setDefaultTextColor(QColor("orange"))
                            
                            text_rect = text_item.boundingRect()
                            padding_x = -3
                            padding_y = -3
                            bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

                            line_center = line_item.boundingRect().center()
                            
                            base_pos_x = line_center.x() - bg_rect_geom.width() / 2
                            base_pos_y = line_center.y() - bg_rect_geom.height() / 2
                            
                            background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
                            background_rect.setBrush(QColor(0, 0, 0, 120))
                            background_rect.setPen(QPen(Qt.GlobalColor.transparent))
                            background_rect.setPos(base_pos_x, base_pos_y)
                            background_rect.setData(0, "transition_object_name_bg")
                            
                            text_item.setPos(base_pos_x + padding_x, base_pos_y + padding_y)
                            background_rect.setZValue(10)
                            text_item.setZValue(11)
                            
                            self.scene.addItem(background_rect)
                            self.scene.addItem(text_item)
                            
                            self.lod_text_items.append(text_item)
                            self.lod_text_items.append(background_rect)
                
                for jump_data in self.geometry_data.get("jump_links", []):
                    line_item = self._add_jump_link_line(QPointF(jump_data['start_vertex_pos'][0], jump_data['start_vertex_pos'][1]), QPointF(jump_data['end_vertex_pos'][0], jump_data['end_vertex_pos'][1]), jump_data['id'])
                    if 'dynamic_name' in jump_data:
                        name = jump_data['dynamic_name']
                        
                        text_item = QGraphicsTextItem(name)
                        font = QFont("맑은 고딕", 3, QFont.Weight.Bold)
                        text_item.setFont(font)
                        text_item.setDefaultTextColor(QColor("lime"))
                        
                        text_rect = text_item.boundingRect()
                        padding_x = -3
                        padding_y = -3
                        bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)

                        line_center = line_item.boundingRect().center()
                        base_pos_x = line_center.x() - bg_rect_geom.width() / 2
                        base_pos_y = line_center.y() - bg_rect_geom.height() / 2 - 7
                        
                        background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
                        background_rect.setBrush(QColor(0, 0, 0, 120))
                        background_rect.setPen(QPen(Qt.GlobalColor.transparent))
                        background_rect.setPos(base_pos_x, base_pos_y)
                        background_rect.setData(0, "jump_link_name_bg")
                        
                        text_item.setPos(base_pos_x + padding_x, base_pos_y + padding_y)
                        
                        background_rect.setZValue(10)
                        text_item.setZValue(11)
                        
                        self.scene.addItem(background_rect)
                        self.scene.addItem(text_item)
                        
                        self.lod_text_items.append(text_item)
                        self.lod_text_items.append(background_rect)
                            
                # 4. 웨이포인트 순서 계산 및 그리기
                wp_order_map = {}
                route = self.route_profiles.get(self.active_route_profile, {})
                for i, wp_id in enumerate(route.get("forward_path", [])):
                    wp_order_map[wp_id] = f"{i+1}"
                for i, wp_id in enumerate(route.get("backward_path", [])):
                    if wp_id in wp_order_map:
                        wp_order_map[wp_id] = f"{wp_order_map[wp_id]}/{i+1}"
                    else:
                        wp_order_map[wp_id] = f"{i+1}"

                for wp_data in self.geometry_data.get("waypoints", []):
                    self._add_waypoint_rect(QPointF(wp_data['pos'][0], wp_data['pos'][1]), wp_data['id'], wp_data['name'], wp_data['name'])
                    
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

        for item in self.scene.items():
            item_type = item.data(0)
            if item_type == "background":
                item.setVisible(show_bg)
            elif item_type == "feature":
                item.setVisible(show_features)
            elif item_type == "waypoint_v10":
                item.setVisible(show_waypoints)
            elif item_type in ["terrain_line", "vertex"]:
                item.setVisible(show_terrain)
            elif item_type == "floor_text": 
                item.setVisible(show_terrain)
            elif item_type == "transition_object":
                item.setVisible(show_objects)
            elif item_type in ["transition_object_name", "transition_object_name_bg"]: # 수정: _bg 타입 추가
                item.setVisible(show_objects)
            elif item_type == "jump_link":
                item.setVisible(show_jump_links)
            elif item_type in ["jump_link_name", "jump_link_name_bg"]: # 수정: _bg 타입 추가
                item.setVisible(show_jump_links)

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

            item.setVisible(is_name_visible and base_visible)

        # 좌표 텍스트 가시성 제어
        is_coord_visible = current_zoom >= self.lod_coord_threshold
        for item in self.lod_coord_items:
            # [v11.3.3] 통합된 lock_coord_text_item의 가시성 제어
            if item is self.lock_coord_text_item:
                # 줌 레벨이 맞고, X 또는 Y축 고정 중 하나라도 켜져 있으면 보이도록 함
                is_lock_active = self.is_x_locked or self.is_y_locked
                item.setVisible(is_coord_visible and is_lock_active)
            else: # 일반 좌표 텍스트 (지형선, 오브젝트)
                # coord_text_group, coord_text_bg, coord_text 모두 처리
                item.setVisible(is_coord_visible)
                
    def on_scene_mouse_press(self, scene_pos, button):
        #  '기본' 모드에서 웨이포인트 클릭 시 이름 변경 기능 추가 ---
        if self.current_mode == "select" and button == Qt.MouseButton.LeftButton:
            # 클릭 위치의 아이템 가져오기 (View 좌표로 변환 필요)
            view_pos = self.view.mapFromScene(scene_pos)
            item_at_pos = self.view.itemAt(view_pos)
            
            if item_at_pos and item_at_pos.data(0) in ["waypoint_v10", "waypoint_lod_text"]:
                wp_id = item_at_pos.data(1)
                waypoint_data = next((wp for wp in self.geometry_data.get("waypoints", []) if wp.get("id") == wp_id), None)
                
                if waypoint_data:
                    old_name = waypoint_data.get("name", "")
                    new_name, ok = QInputDialog.getText(self, "웨이포인트 이름 변경", "새 이름:", text=old_name)
                    
                    if ok and new_name and new_name != old_name:
                        # 이름 중복 검사
                        if any(wp.get('name') == new_name for wp in self.geometry_data.get("waypoints", [])):
                            QMessageBox.warning(self, "오류", "이미 존재하는 웨이포인트 이름입니다.")
                        else:
                            waypoint_data["name"] = new_name
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
                            "parent_line_id": parent_line_id
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
    
    def _add_waypoint_rect(self, pos, wp_id, name, order_text):
            """씬에 웨이포인트 사각형과 순서를 추가합니다."""
            size = 12
            rect_item = self.scene.addRect(0, 0, size, size, QPen(Qt.GlobalColor.green), QBrush(QColor(0, 255, 0, 80)))
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
        dot = self.scene.addEllipse(0, 0, 6, 6, QPen(Qt.GlobalColor.magenta), QBrush(Qt.GlobalColor.white))
        dot.setPos(pos - QPointF(3, 3))
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
                self.snap_indicator = self.scene.addEllipse(0, 0, 8, 8, QPen(QColor(0, 255, 0, 200), 2))
                self.snap_indicator.setZValue(100)
            self.snap_indicator.setPos(snap_point - QPointF(4, 4))
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
        if self.parent_map_tab and hasattr(self.parent_map_tab, 'route_profiles'):
            for route in self.parent_map_tab.route_profiles.values():
                if "forward_path" in route and isinstance(route["forward_path"], list):
                    route["forward_path"] = [pid for pid in route["forward_path"] if pid != wp_id_to_delete]
                if "backward_path" in route and isinstance(route["backward_path"], list):
                    route["backward_path"] = [pid for pid in route["backward_path"] if pid != wp_id_to_delete]

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
class RealtimeMinimapView(QLabel):
    """
    전체 맵을 기반으로 실시간 카메라 뷰를 렌더링하고, 휠 줌과 마우스 드래그를 지원하는 위젯.
    """
    def __init__(self, parent_tab):
        super().__init__(parent_tab)
        self.parent_tab = parent_tab
        self.setMinimumSize(300, 300)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")
        self.setText("탐지를 시작하세요.")

        # 렌더링 상태 변수
        self.zoom_level = 2.0 # 기본 실시간 미니맵 뷰 확대배율
        self.camera_center_global = QPointF(0, 0)
        self.active_features = []
        self.my_player_rects = []
        self.other_player_rects = []
        self.final_player_pos_global = None
        
        # v10.0.0: 네비게이션 렌더링 데이터
        self.target_waypoint_id = None
        self.last_reached_waypoint_id = None
        #진행 방향 플래그 추가 ---
        self.is_forward = True
        # ==================== v11.6.2 시각화 변수 추가 시작 ====================
        self.intermediate_target_pos = None
        self.intermediate_target_type = None
        # ==================== v11.6.3 상태 변수 추가 시작 ====================
        self.navigation_action = 'move_to_target'
        # ==================== v11.6.3 상태 변수 추가 끝 ======================
        # 패닝(드래그) 상태 변수
        self.is_panning = False
        self.last_pan_pos = QPoint()
    
    def wheelEvent(self, event):
        """마우스 휠 스크롤로 줌 레벨을 조절합니다."""
        if event.angleDelta().y() > 0:
            self.zoom_level *= 1.25
        else:
            self.zoom_level /= 1.25
        self.zoom_level = max(0.1, min(self.zoom_level, 10.0))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = True
            self.last_pan_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_panning:
            delta = event.pos() - self.last_pan_pos
            self.last_pan_pos = event.pos()
            # 줌 레벨을 고려하여 이동량 보정
            self.camera_center_global -= QPointF(delta) / self.zoom_level
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def update_view_data(self, camera_center, active_features, my_players, other_players, target_wp_id, reached_wp_id, final_player_pos, is_forward, intermediate_pos, intermediate_type, nav_action):
        """MapTab으로부터 렌더링에 필요한 최신 데이터를 받습니다."""
        self.camera_center_global = camera_center
        self.active_features = active_features
        self.my_player_rects = my_players
        self.other_player_rects = other_players
        self.target_waypoint_id = target_wp_id
        self.last_reached_waypoint_id = reached_wp_id
        self.final_player_pos_global = final_player_pos
        self.is_forward = is_forward
        self.intermediate_target_pos = intermediate_pos
        self.intermediate_target_type = intermediate_type
        self.navigation_action = nav_action
        self.update()

    def paintEvent(self, event):
        """
        배경 지도 위에 보기 옵션에 따라 모든 요소를 동적으로 렌더링합니다.
        """
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        map_bg = self.parent_tab.full_map_pixmap
        bounding_rect = self.parent_tab.full_map_bounding_rect

        if not map_bg or map_bg.isNull() or bounding_rect.isNull():
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
            return

        view_w, view_h = self.width(), self.height()
        source_w = view_w / self.zoom_level
        source_h = view_h / self.zoom_level
        
        source_rect = QRectF(
            self.camera_center_global.x() - source_w / 2,
            self.camera_center_global.y() - source_h / 2,
            source_w,
            source_h
        )
        
        image_source_rect = source_rect.translated(-bounding_rect.topLeft())
        
        target_rect = QRectF(self.rect())
        painter.drawPixmap(target_rect, map_bg, image_source_rect)

        def global_to_local(global_pos):
            relative_pos = global_pos - source_rect.topLeft()
            return relative_pos * self.zoom_level

        render_opts = self.parent_tab.render_options
        
        # ---  지형선 및 그룹 이름 렌더링 로직 전체 교체 ---
        if render_opts.get('terrain', True):
            painter.save()
            
            # 1. 지형 그룹화 로직 (FullMinimapEditorDialog에서 가져옴)
            from collections import defaultdict, deque
            terrain_lines = self.parent_tab.geometry_data.get("terrain_lines", [])
            if terrain_lines:
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
                
                # 2. 층별 그룹 정렬 및 동적 이름 부여
                groups_by_floor = defaultdict(list)
                for group in all_groups:
                    if group:
                        floor = group[0].get('floor', 0)
                        groups_by_floor[floor].append(group)
                
                dynamic_group_names = {} # key: 첫번째 line_id, value: "n층_A"
                for floor, groups in groups_by_floor.items():
                    # 각 그룹의 중심 x좌표 계산하여 정렬
                    sorted_groups = sorted(groups, key=lambda g: sum(p[0] for line in g for p in line['points']) / sum(len(line['points']) for line in g if line.get('points')))
                    for i, group in enumerate(sorted_groups):
                        group_name = f"{floor}층_{chr(ord('A') + i)}"
                        if group:
                            first_line_id = group[0]['id']
                            dynamic_group_names[first_line_id] = group_name

                # 3. 그룹별로 지형선 및 이름 그리기
                for group in all_groups:
                    if not group: continue
                    
                    pen = QPen(Qt.GlobalColor.magenta, 2)
                    painter.setPen(pen)
                    
                    group_polygon_global = QPolygonF()
                    for line_data in group:
                        points_global = [QPointF(p[0], p[1]) for p in line_data.get("points", [])]
                        if len(points_global) >= 2:
                            points_local = [global_to_local(p) for p in points_global]
                            painter.drawPolyline(QPolygonF(points_local))
                            group_polygon_global += QPolygonF(points_global)

                    # 그룹의 동적 이름 표시
                    first_line_id = group[0]['id']
                    group_name_text = dynamic_group_names.get(first_line_id, f"{group[0].get('floor', 'N/A')}층")
                    
                    group_rect_global = group_polygon_global.boundingRect()
                    font = QFont("맑은 고딕", 10, QFont.Weight.Bold) #실시간 미니맵 뷰 지형층 이름 폰트 크기
                    
                    # 이름 위치 계산 (글로벌 좌표 기준)
                    text_pos_global = QPointF(group_rect_global.center().x(), group_rect_global.bottom() + 4)
                    
                    # 로컬 좌표로 변환하여 그리기
                    text_pos_local = global_to_local(text_pos_global)
                    
                    # 텍스트가 화면 밖으로 나가는 것 방지 (간단한 클리핑)
                    if self.rect().contains(text_pos_local.toPoint()):
                        tm = QFontMetrics(font)
                        text_rect_local = tm.boundingRect(group_name_text)
                        text_rect_local.moveCenter(text_pos_local.toPoint())
                        self._draw_text_with_outline(painter, text_rect_local, Qt.AlignmentFlag.AlignCenter, group_name_text, font, Qt.GlobalColor.white, Qt.GlobalColor.black)

            painter.restore()

        if render_opts.get('objects', True):
            painter.save()
            painter.setPen(QPen(QColor(255, 165, 0), 3))
            for obj_data in self.parent_tab.geometry_data.get("transition_objects", []):
                points = [global_to_local(QPointF(p[0], p[1])) for p in obj_data.get("points", [])]
                if len(points) == 2:
                    painter.drawLine(points[0], points[1])
            painter.restore()
        
        if render_opts.get('jump_links', True):
            painter.save()
            pen = QPen(QColor(0, 255, 0, 200), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            for jump_data in self.parent_tab.geometry_data.get("jump_links", []):
                p1 = global_to_local(QPointF(jump_data['start_vertex_pos'][0], jump_data['start_vertex_pos'][1]))
                p2 = global_to_local(QPointF(jump_data['end_vertex_pos'][0], jump_data['end_vertex_pos'][1]))
                painter.drawLine(p1, p2)
            painter.restore()

        #핵심 지형 렌더링 (텍스트 스타일 변경) ---
        if render_opts.get('features', True):
            painter.save()
            realtime_conf_map = {f['id']: f['conf'] for f in self.active_features}

            for feature_id, feature_data in self.parent_tab.key_features.items():
                if feature_id in self.parent_tab.global_positions:
                    global_pos = self.parent_tab.global_positions[feature_id]
                    img_data = base64.b64decode(feature_data['image_base64'])
                    pixmap = QPixmap(); pixmap.loadFromData(img_data)
                    if pixmap.isNull(): continue

                    global_rect = QRectF(global_pos, QSizeF(pixmap.size()))
                    local_top_left = global_to_local(global_rect.topLeft())
                    local_rect = QRectF(local_top_left, global_rect.size() * self.zoom_level)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    
                    realtime_conf = realtime_conf_map.get(feature_id, 0.0)
                    threshold = feature_data.get('threshold', 0.85)
                    is_detected = realtime_conf >= threshold

                    font_name = QFont("맑은 고딕", 9, QFont.Weight.Bold) # 실시간 뷰의 핵심 지형 이름 폰트 크기
                    
                    if is_detected:
                        painter.setPen(QPen(QColor(0, 180, 255), 2, Qt.PenStyle.SolidLine))
                        self._draw_text_with_outline(painter, local_rect.toRect(), Qt.AlignmentFlag.AlignCenter, feature_id, font_name, Qt.GlobalColor.white, Qt.GlobalColor.black)
                    else:
                        painter.setPen(QPen(QColor("gray"), 2, Qt.PenStyle.DashLine))
                        self._draw_text_with_outline(painter, local_rect.toRect(), Qt.AlignmentFlag.AlignCenter, feature_id, font_name, QColor("#AAAAAA"), Qt.GlobalColor.black)
                    
                    #  미감지 시에도 realtime_conf를 사용하도록 수정 ---
                    conf_text = f"{realtime_conf:.2f}"
                    font_conf = QFont("맑은 고딕", 10)
                    
                    tm_conf = QFontMetrics(font_conf)
                    conf_rect = tm_conf.boundingRect(conf_text)
                    conf_rect.moveCenter(local_rect.center().toPoint())
                    conf_rect.moveTop(int(local_rect.top()) - conf_rect.height() - 2)
                    
                    color = Qt.GlobalColor.yellow if is_detected else QColor("#AAAAAA")
                    self._draw_text_with_outline(painter, conf_rect, Qt.AlignmentFlag.AlignCenter, conf_text, font_conf, color, Qt.GlobalColor.black)
                    
                    painter.drawRect(local_rect)
            painter.restore()

            
        # 웨이포인트 (줌 레벨 연동 크기) ---
        if render_opts.get('waypoints', True):
            painter.save()
            WAYPOINT_SIZE = 12.0 # 전역 좌표계 기준 크기
            
            # 웨이포인트 순서 맵 생성 (현재 방향에 맞는 순서 맵만 생성)
            wp_order_map = {}
            if self.parent_tab.active_route_profile_name:
                route = self.parent_tab.route_profiles.get(self.parent_tab.active_route_profile_name, {})
                path_key = "forward_path" if self.is_forward else "backward_path"
                path_ids = route.get(path_key, [])
                
                if not path_ids and not self.is_forward:
                    path_ids = list(reversed(route.get("forward_path", [])))

                #  출발지/목적지 텍스트 처리 ---
                if path_ids:
                    # 먼저 모든 웨이포인트에 숫자 할당
                    for i, wp_id in enumerate(path_ids):
                        wp_order_map[wp_id] = f"{i+1}"
                    
                    # 시작점과 끝점 텍스트 덮어쓰기
                    if len(path_ids) > 1:
                        wp_order_map[path_ids[0]] = "출발지"
                        wp_order_map[path_ids[-1]] = "목적지"
                    elif len(path_ids) == 1:
                        # 경로에 하나만 있을 경우 목적지로 표시
                        wp_order_map[path_ids[0]] = "목적지"
                    
            for wp_data in self.parent_tab.geometry_data.get("waypoints", []):
                global_pos = QPointF(wp_data['pos'][0], wp_data['pos'][1])
                local_pos = global_to_local(global_pos)
                
                # 줌 레벨에 따라 크기 변경 ---
                scaled_size = WAYPOINT_SIZE * self.zoom_level
                local_rect = QRectF(local_pos.x() - scaled_size/2, local_pos.y() - scaled_size, scaled_size, scaled_size)

                if wp_data['id'] == self.target_waypoint_id:
                    # 목표 웨이포인트는 빨간색으로 강조
                    painter.setPen(QPen(Qt.GlobalColor.red, 2))
                    painter.setBrush(QBrush(QColor(255, 0, 0, 80)))
                else:
                    # 일반 웨이포인트는 초록색
                    painter.setPen(QPen(QColor(0, 255, 0), 2))
                    painter.setBrush(QBrush(QColor(0, 255, 0, 80)))
                
                painter.drawRect(local_rect)
                
                #  순서와 이름 렌더링 로직 변경 ---
                # 1. 중앙에 순서 표시
                order_text = wp_order_map.get(wp_data['id'], "")
                if order_text:
                    font_order = QFont("맑은 고딕", 10, QFont.Weight.Bold) # 실시간 미니맵 뷰 순서 폰트 크기
                    text_color = Qt.GlobalColor.white #목표 웨이포인트의 폰트 색상을 항상 흰색으로 ---
                    self._draw_text_with_outline(painter, local_rect.toRect(), Qt.AlignmentFlag.AlignCenter, order_text, font_order, text_color, Qt.GlobalColor.black)

                # 2. 바깥쪽 좌측 상단에 이름 표시
                name_text = wp_data.get('name', '')
                if name_text:
                    #  이름 폰트 크기 8pt로 변경 ---
                    font_name = QFont("맑은 고딕", 8)
                    
                    #  텍스트 너비 계산에 여유 공간(패딩) 추가 ---
                    tm = QFontMetrics(font_name)
                    # boundingRect는 정수 기반 QRect를 반환합니다.
                    text_bounding_rect = tm.boundingRect(name_text)
                    
                    # 렌더링에 사용할 사각형의 너비를 약간 늘려줍니다.
                    padding_x = 4 # 좌우 2px씩 총 4px의 여유 공간
                    name_render_rect = text_bounding_rect.adjusted(0, 0, padding_x, 0)
                    
                    # 위치를 부동소수점 기반으로 정밀하게 계산
                    new_bottom_left_f = local_rect.topLeft() + QPointF(0, -2)
                    name_render_rect.moveBottomLeft(new_bottom_left_f.toPoint())
                    self._draw_text_with_outline(painter, name_render_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, name_text, font_name, Qt.GlobalColor.white, Qt.GlobalColor.black)
                # 3. "도착" 표시
                if wp_data['id'] == self.last_reached_waypoint_id:
                    font_arrival = QFont("맑은 고딕", 8, QFont.Weight.Bold)
                    arrival_rect = QRectF(local_rect.x(), local_rect.y(), local_rect.width(), local_rect.height() / 2).toRect()
                    # y축으로 1px 정도 살짝 내려서 중앙에 더 가깝게 보이도록 조정
                    arrival_rect.translate(0, -4)
                    
                    self._draw_text_with_outline(painter, arrival_rect, Qt.AlignmentFlag.AlignCenter, "도착", font_arrival, Qt.GlobalColor.yellow, Qt.GlobalColor.black)

            painter.restore()

        # ==================== v11.6.2 시각적 보정 로직 추가 시작 ====================
        if self.intermediate_target_pos and self.final_player_pos_global:
            painter.save()
            
            # --- 시작/끝점 좌표 계산 ---
            # 시작점: 플레이어 아이콘의 중앙
            p1_global = self.final_player_pos_global
            if self.my_player_rects:
                p1_global = self.my_player_rects[0].center()

            # 끝점: 타입에 따라 보정
            p2_global = self.intermediate_target_pos
            if self.intermediate_target_type == 'walk':
                # 목표 웨이포인트 ID 찾기
                target_wp_id_for_render = self.target_waypoint_id
                if self.navigation_action.startswith('prepare_to_') or self.navigation_action.endswith('_in_progress'):
                    pass
                else: # move_to_target
                    target_wp_id_for_render = self.target_waypoint_id
                
                # 웨이포인트 데이터에서 크기 정보 가져오기 (임시 크기 사용)
                WAYPOINT_SIZE = 12.0
                target_wp_rect = QRectF(p2_global.x() - WAYPOINT_SIZE/2, p2_global.y() - WAYPOINT_SIZE, WAYPOINT_SIZE, WAYPOINT_SIZE)
                p2_global = target_wp_rect.center()

            # 1. 경로 안내선 (Guidance Line) - 굵기 3px로 변경
            pen = QPen(QColor("cyan"), 3, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            
            p1_local = global_to_local(p1_global)
            p2_local = global_to_local(p2_global)
            painter.drawLine(p1_local, p2_local)
            
            # 2. 중간 목표 아이콘 (Target Icon) - 스타일 변경
            # 아이콘 위치는 정확한 좌표(p2_global)를 사용
            icon_center_local = p2_local
            TARGET_ICON_SIZE = 5.0 # 전역 좌표계 기준 크기 5x5로 변경
            scaled_size = TARGET_ICON_SIZE * self.zoom_level
            
            icon_rect = QRectF(
                icon_center_local.x() - scaled_size / 2,
                icon_center_local.y() - scaled_size / 2,
                scaled_size,
                scaled_size
            )
            # ==================== v11.6.2 시각적 보정 로직 추가 끝 ======================
            
            # 배경 (단색 빨간색 원)
            painter.setPen(Qt.PenStyle.NoPen) # 배경에는 테두리 없음
            painter.setBrush(QBrush(Qt.GlobalColor.red))
            painter.drawEllipse(icon_rect)
            
            # 테두리 (흰색, 1.5px)
            painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush) # 테두리에는 채우기 없음
            painter.drawEllipse(icon_rect)

            # 흰색 X자 (굵기 1px로 변경)
            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawLine(icon_rect.topLeft(), icon_rect.bottomRight())
            painter.drawLine(icon_rect.topRight(), icon_rect.bottomLeft())
            
            painter.restore()
        # ==================== v11.6.1 시각화 스타일 수정 끝 ======================

        # 내 캐릭터, 다른 유저 
        painter.save()
        painter.setPen(QPen(Qt.GlobalColor.yellow, 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.final_player_pos_global and self.my_player_rects:
            # 첫 번째 탐지된 사각형을 기준으로 위치 보정
            # (보통 my_player_rects에는 하나만 들어있음)
            base_rect = self.my_player_rects[0]
            
            # 1. 전달받은 사각형(base_rect)의 글로벌 아랫변 중앙 좌표 계산
            rect_bottom_center_global = base_rect.center() + QPointF(0, base_rect.height() / 2)
            
            # 2. 이 좌표와 실제 발밑 좌표(final_player_pos_global)의 차이(오프셋) 계산
            offset = self.final_player_pos_global - rect_bottom_center_global
            
            # 3. 모든 my_player_rects에 동일한 오프셋을 적용하여 그리기
            for rect in self.my_player_rects:
                corrected_rect_global = rect.translated(offset)
                
                local_top_left = global_to_local(corrected_rect_global.topLeft())
                local_rect = QRectF(local_top_left, corrected_rect_global.size() * self.zoom_level)
                painter.drawRect(local_rect)
        else:
            # fallback: final_player_pos_global이 없는 경우 기존 방식대로 그림
            for rect in self.my_player_rects:
                local_top_left = global_to_local(rect.topLeft())
                local_rect = QRectF(local_top_left, rect.size() * self.zoom_level)
                painter.drawRect(local_rect)
        
        painter.restore()
        
        painter.save()
        painter.setPen(QPen(Qt.GlobalColor.red, 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
        for rect in self.other_player_rects:
            local_top_left = global_to_local(rect.topLeft())
            local_rect = QRectF(local_top_left, rect.size() * self.zoom_level)
            painter.drawRect(local_rect)
        painter.restore()

        # ---  정확한 플레이어 발밑 위치 표시 ---
        if self.final_player_pos_global:
            local_player_pos = global_to_local(self.final_player_pos_global)
            
            painter.save()
            # 십자선 그리기
            pen = QPen(QColor(255, 255, 0, 200), 1.5)
            painter.setPen(pen)
            painter.drawLine(local_player_pos + QPointF(-5, 0), local_player_pos + QPointF(5, 0))
            painter.drawLine(local_player_pos + QPointF(0, -5), local_player_pos + QPointF(0, 5))
            
            # 중앙 원 그리기
            painter.setBrush(QBrush(Qt.GlobalColor.yellow))
            painter.drawEllipse(local_player_pos, 2, 2)
            painter.restore()

        
    def _draw_text_with_outline(self, painter, rect, flags, text, font, text_color, outline_color):
        """지정한 사각형 영역에 테두리가 있는 텍스트를 그립니다."""
        painter.save()
        painter.setFont(font)
        
        # 테두리 그리기
        painter.setPen(outline_color)
        painter.drawText(rect.translated(1, 1), flags, text)
        painter.drawText(rect.translated(-1, -1), flags, text)
        painter.drawText(rect.translated(1, -1), flags, text)
        painter.drawText(rect.translated(-1, 1), flags, text)
        
        # 원본 텍스트 그리기
        painter.setPen(text_color)
        painter.drawText(rect, flags, text)
        painter.restore()

# === [v11.0.0] 캡처 전담 스레드 (신규 클래스) ===
class MinimapCaptureThread(QThread):
    """지정된 영역을 목표 FPS에 맞춰 캡처하고 최신 프레임을 공유하는 스레드."""
    frame_ready = pyqtSignal(object)  # UI 등에 최신 프레임을 알리기 위한 시그널

    def __init__(self, minimap_region, target_fps=None):
        super().__init__()
        self.minimap_region = minimap_region
        self.target_fps = target_fps or MapConfig["target_fps"]
        self.is_running = False
        self.latest_frame = None
        self._lock = threading.Lock()

    def run(self):
        self.is_running = True
        with mss.mss() as sct:
            interval = 1.0 / max(1, self.target_fps)
            while self.is_running:
                start_t = time.time()
                try:
                    sct_img = sct.grab(self.minimap_region)
                    frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)

                    # 락은 최소 시간만 점유하여 latest_frame을 교체
                    with self._lock:
                        self.latest_frame = frame_bgr

                    # UI 표시 등이 필요하면 시그널을 통해 알림 (성능 민감 시 비활성 가능)
                    try:
                        self.frame_ready.emit(frame_bgr)
                    except Exception:
                        # 시그널 연결 문제는 무시하고 계속 진행 (호환성 보호)
                        pass

                except Exception as e:
                    print(f"[MinimapCaptureThread] 캡처 오류: {e}")
                    traceback.print_exc()

                # 프레임률 제한
                elapsed = time.time() - start_t
                sleep_time = interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

    def stop(self):
        self.is_running = False
        try:
            self.quit()
            self.wait(2000)
        except Exception as e:
            print(f"[MinimapCaptureThread] 정지 대기 실패: {e}")


# === [v11.0.1] 안전한 프레임 읽기 헬퍼 (누락된 함수 추가) ===
def safe_read_latest_frame(capture_thread):
    """
    capture_thread.latest_frame을 안전하게 읽어 복사본을 반환.
    락을 짧게 점유하도록 설계되어 있음.
    """
    if not capture_thread:
        return None
    try:
        with capture_thread._lock:
            src = capture_thread.latest_frame
            if src is None:
                return None
            return src.copy()
    except Exception:
        return None
    
# [v11.0.0] 개편: 캡처 로직 분리 및 탐지 연산 최적화
class AnchorDetectionThread(QThread):
    """
    캡처 스레드로부터 프레임을 받아, 등록된 핵심 지형의 위치만 탐지하여 전달하는 역할.
    """
    # 기존과 호환되는 시그널 시그니처 유지 (호출부 변경 위험 방지)
    detection_ready = pyqtSignal(object, list, list, list)
    status_updated = pyqtSignal(str, str)

    def __init__(self, all_key_features, capture_thread=None, parent_tab=None): # [MODIFIED] parent_tab 추가
        super().__init__()
        self.capture_thread = capture_thread
        self.parent_tab = parent_tab # [NEW] MapTab 인스턴스 저장
        self.all_key_features = all_key_features or {}
        self.is_running = False
        self.feature_templates = {}
        self._downscale = MapConfig["downscale"]

        # 템플릿 전처리
        for fid, fdata in self.all_key_features.items():
            try:
                img_data = base64.b64decode(fdata['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if template is None: continue

                tpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                tpl_small = cv2.resize(tpl_gray, (0, 0), fx=self._downscale, fy=self._downscale, interpolation=cv2.INTER_AREA)

                self.feature_templates[fid] = {
                    "template_gray_small": tpl_small,
                    "threshold": fdata.get('threshold', MapConfig["detection_threshold_default"]),
                    "size": QSize(template.shape[1], template.shape[0]),
                }
            except Exception as e:
                print(f"[AnchorDetectionThread] 템플릿 전처리 실패 ({fid}): {e}")
                traceback.print_exc()

        # 마지막 검출 위치 저장 (ROI 검색에 사용)
        self.last_positions = {k: None for k in self.feature_templates.keys()}

    def run(self):
        self.is_running = True
        while self.is_running:
            loop_start = time.perf_counter()
            try:
                # 안전하게 최신 프레임 읽기 (락 최소점유)
                frame_bgr = safe_read_latest_frame(self.capture_thread) # <<< [v11.0.1] 'self.' 제거
                if frame_bgr is None:
                    time.sleep(0.005)
                    continue

                # [NEW] 플레이어 탐지를 이 스레드에서 먼저 수행
                my_player_rects = []
                other_player_rects = []
                if self.parent_tab: # parent_tab이 전달되었는지 확인
                    my_player_rects = self.parent_tab.find_player_icon(frame_bgr)
                    other_player_rects = self.parent_tab.find_other_player_icons(frame_bgr)

                # 처리용 저해상도 프레임 생성 (연산량 감소)
                frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                frame_gray_small = cv2.resize(frame_gray, (0, 0), fx=self._downscale, fy=self._downscale, interpolation=cv2.INTER_AREA)

                all_detected_features = []
                for fid, tpl_data in self.feature_templates.items():
                    tpl_small = tpl_data["template_gray_small"]
                    t_h, t_w = tpl_small.shape
                    search_result = None

                    # 1) ROI 우선 검색
                    last_pos = self.last_positions.get(fid)
                    if last_pos is not None:
                        lx = int(last_pos.x() * self._downscale)
                        ly = int(last_pos.y() * self._downscale)
                        radius = max(int(max(t_w, t_h) * 1.5), 30)
                        x1, y1 = max(0, lx - radius), max(0, ly - radius)
                        x2, y2 = min(frame_gray_small.shape[1], lx + radius), min(frame_gray_small.shape[0], ly + radius)
                        roi = frame_gray_small[y1:y2, x1:x2]

                        if roi.shape[0] >= t_h and roi.shape[1] >= t_w:
                            res = cv2.matchTemplate(roi, tpl_small, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, max_loc = cv2.minMaxLoc(res)
                            if max_val >= tpl_data["threshold"]:
                                found_x = (x1 + max_loc[0]) / self._downscale
                                found_y = (y1 + max_loc[1]) / self._downscale
                                search_result = {'id': fid, 'local_pos': QPointF(found_x, found_y), 'conf': max_val, 'size': tpl_data['size']}

                    # 2) ROI에서 못 찾으면 전체(저해상도) 검색
                    if search_result is None:
                        res = cv2.matchTemplate(frame_gray_small, tpl_small, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        if max_val >= tpl_data["threshold"]:
                            found_x = max_loc[0] / self._downscale
                            found_y = max_loc[1] / self._downscale
                            search_result = {'id': fid, 'local_pos': QPointF(found_x, found_y), 'conf': max_val, 'size': tpl_data['size']}
                    
                    if search_result:
                        all_detected_features.append(search_result)
                        # ROI 검색을 위해 TopLeft 좌표 저장
                        self.last_positions[fid] = search_result['local_pos']

                # [MODIFIED] 플레이어 탐지 결과를 시그널에 담아 전달
                self.detection_ready.emit(frame_bgr, all_detected_features, my_player_rects, other_player_rects)

                # 루프 시간 측정 및 폴백 적용
                loop_time_ms = (time.perf_counter() - loop_start) * 1000.0
                if loop_time_ms > MapConfig["loop_time_fallback_ms"]:
                    old_scale = self._downscale
                    self._downscale = max(0.3, old_scale * 0.95)
                    MapConfig["downscale"] = self._downscale # 전역 설정도 갱신
                    print(f"[AnchorDetectionThread] 느린 루프 감지 ({loop_time_ms:.1f}ms), 다운스케일 조정: {old_scale:.2f} -> {self._downscale:.2f}")

            except Exception as e:
                # 루프 전체가 죽지 않도록 모든 예외를 잡아 로깅 후 계속
                print(f"[AnchorDetectionThread] 예기치 않은 오류: {e}")
                traceback.print_exc()
                time.sleep(0.02)

    def stop(self):
        self.is_running = False
        try:
            self.quit()
            self.wait(2000)
        except Exception as e:
            print(f"[AnchorDetectionThread] 정지 대기 실패: {e}")

# [v11.3.0] 상태 판정 설정을 위한 팝업 다이얼로그 클래스
class StateConfigDialog(QDialog):
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("판정 설정") # [v11.4.0] 이름 변경
        self.setMinimumWidth(450) # 너비 확장
        
        self.config = current_config.copy()
        
        main_layout = QVBoxLayout(self)
        form_layout = QVBoxLayout()

        def add_spinbox(layout, key, label_text, min_val, max_val, step, is_double=True, decimals=2):
            h_layout = QHBoxLayout()
            label = QLabel(label_text)
            label.setMinimumWidth(200) # 레이블 너비 고정
            h_layout.addWidget(label)
            if is_double:
                spinbox = QDoubleSpinBox()
                spinbox.setDecimals(decimals)
            else:
                spinbox = QSpinBox()
            spinbox.setRange(min_val, max_val)
            spinbox.setSingleStep(step)
            spinbox.setValue(self.config.get(key, 0))
            spinbox.setObjectName(key)
            h_layout.addWidget(spinbox)
            layout.addLayout(h_layout)
            return spinbox

        # [v11.4.0] 사용자 요청에 따라 스핀박스 범위 및 신규 항목 추가
        add_spinbox(form_layout, "idle_time_threshold", "정지 판정 시간(초):", 0.1, 5.0, 0.1)
        add_spinbox(form_layout, "max_jump_duration", "최대 점프 시간(초):", 0.1, 5.0, 0.1)
        add_spinbox(form_layout, "climbing_state_frame_threshold", "등반 판정 프레임:", 1, 100, 1, is_double=False)
        add_spinbox(form_layout, "falling_state_frame_threshold", "낙하 판정 프레임:", 1, 100, 1, is_double=False)
        add_spinbox(form_layout, "jumping_state_frame_threshold", "점프 판정 프레임:", 1, 100, 1, is_double=False)
        
        form_layout.addSpacing(10)

        add_spinbox(form_layout, "on_terrain_y_threshold", "지상 판정 Y오차(px):", 1.0, 30.0, 0.1)
        add_spinbox(form_layout, "jump_y_min_threshold", "점프 최소 Y오프셋(px):", 0.01, 30.0, 0.01)
        add_spinbox(form_layout, "jump_y_max_threshold", "점프 최대 Y오프셋(px):", 1.0, 30.0, 0.1)
        add_spinbox(form_layout, "fall_y_min_threshold", "낙하 최소 Y오프셋(px):", 1.0, 30.0, 0.1)
        
        form_layout.addSpacing(10)

        add_spinbox(form_layout, "move_deadzone", "X/Y 이동 감지 최소값(px):", 0.0, 5.0, 0.01, decimals=2)
        add_spinbox(form_layout, "y_movement_deadzone", "상승/하강 감지 Y최소값(px/f):", 0.01, 5.0, 0.01, decimals=2)
        add_spinbox(form_layout, "climb_x_movement_threshold", "등반 최대 X이동(px/f):", 0.01, 5.0, 0.01)
        add_spinbox(form_layout, "fall_on_ladder_x_movement_threshold", "사다리 낙하 최대 X이동(px/f):", 0.01, 5.0, 0.01)
        add_spinbox(form_layout, "ladder_x_grab_threshold", "사다리 근접 X오차(px):", 0.5, 20.0, 0.1)
        
        form_layout.addSpacing(10)
        
        add_spinbox(form_layout, "waypoint_arrival_x_threshold", "웨이포인트 도착 X오차(px):", 0.0, 20.0, 0.1)
        add_spinbox(form_layout, "ladder_arrival_x_threshold", "사다리 도착 X오차(px):", 0.0, 20.0, 0.1)
        add_spinbox(form_layout, "jump_link_arrival_x_threshold", "점프/낭떠러지 도착 X오차(px):", 0.0, 20.0, 0.1)

        # ==================== v11.5.0 UI 항목 추가 시작 ====================
        form_layout.addSpacing(10)
        add_spinbox(form_layout, "arrival_frame_threshold", "도착 판정 프레임:", 1, 10, 1, is_double=False)
        add_spinbox(form_layout, "action_success_frame_threshold", "행동 성공 판정 프레임:", 1, 10, 1, is_double=False)
        # ==================== v11.5.0 UI 항목 추가 끝 ======================

        main_layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox()
        save_btn = button_box.addButton("저장", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        default_btn = button_box.addButton("기본값 복원", QDialogButtonBox.ButtonRole.ResetRole)
        
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        default_btn.clicked.connect(self.restore_defaults)
        
        main_layout.addWidget(button_box)

    def get_updated_config(self):
        updated_config = {}
        for spinbox in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            key = spinbox.objectName()
            updated_config[key] = spinbox.value()
        return updated_config

    def restore_defaults(self):
        defaults = {
            "idle_time_threshold": IDLE_TIME_THRESHOLD,
            "climbing_state_frame_threshold": CLIMBING_STATE_FRAME_THRESHOLD,
            "falling_state_frame_threshold": FALLING_STATE_FRAME_THRESHOLD,
            "jumping_state_frame_threshold": JUMPING_STATE_FRAME_THRESHOLD,
            "on_terrain_y_threshold": ON_TERRAIN_Y_THRESHOLD,
            "jump_y_min_threshold": JUMP_Y_MIN_THRESHOLD,
            "jump_y_max_threshold": JUMP_Y_MAX_THRESHOLD,
            "fall_y_min_threshold": FALL_Y_MIN_THRESHOLD,
            "climb_x_movement_threshold": CLIMB_X_MOVEMENT_THRESHOLD,
            "fall_on_ladder_x_movement_threshold": FALL_ON_LADDER_X_MOVEMENT_THRESHOLD,
            "ladder_x_grab_threshold": LADDER_X_GRAB_THRESHOLD,
            "move_deadzone": MOVE_DEADZONE,
            "max_jump_duration": MAX_JUMP_DURATION,
            "y_movement_deadzone": Y_MOVEMENT_DEADZONE,
            "waypoint_arrival_x_threshold": WAYPOINT_ARRIVAL_X_THRESHOLD,
            "ladder_arrival_x_threshold": LADDER_ARRIVAL_X_THRESHOLD,
            "jump_link_arrival_x_threshold": JUMP_LINK_ARRIVAL_X_THRESHOLD,
            # ==================== v11.5.0 기본값 추가 시작 ====================
            "arrival_frame_threshold": 2,
            "action_success_frame_threshold": 2,
            # ==================== v11.5.0 기본값 추가 끝 ======================
        }
        for spinbox in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            key = spinbox.objectName()
            if key in defaults:
                spinbox.setValue(defaults[key])

class MapTab(QWidget):
    global_pos_updated = pyqtSignal(QPointF)

    def __init__(self):
            super().__init__()
            self.active_profile_name = None
            self.minimap_region = None
            self.key_features = {}
            self.geometry_data = {} # terrain_lines, transition_objects, waypoints, jump_links 포함
            self.active_route_profile_name = None
            self.route_profiles = {}
            self.detection_thread = None
            self.capture_thread = None
            self.debug_dialog = None
            self.editor_dialog = None 
            self.global_positions = {}
            
            self.full_map_pixmap = None
            self.full_map_bounding_rect = QRectF()
            self.my_player_global_rects = []
            self.other_player_global_rects = []
            self.active_feature_info = []
            self.reference_anchor_id = None
            self.smoothed_player_pos = None
            self.line_id_to_floor_map = {}  # [v11.4.5] 지형선 ID <-> 층 정보 캐싱용 딕셔너리
            
            # [v11.3.7] 설정 변수 선언만 하고 값 할당은 load_profile_data로 위임
            self.cfg_idle_time_threshold = None
            self.cfg_climbing_state_frame_threshold = None
            self.cfg_falling_state_frame_threshold = None
            self.cfg_jumping_state_frame_threshold = None
            self.cfg_on_terrain_y_threshold = None
            self.cfg_jump_y_min_threshold = None
            self.cfg_jump_y_max_threshold = None
            self.cfg_fall_y_min_threshold = None
            self.cfg_climb_x_movement_threshold = None
            self.cfg_fall_on_ladder_x_movement_threshold = None
            self.cfg_ladder_x_grab_threshold = None
            self.cfg_move_deadzone = None
            self.cfg_max_jump_duration = None
            self.cfg_y_movement_deadzone = None
            self.cfg_waypoint_arrival_x_threshold = None
            self.cfg_ladder_arrival_x_threshold = None
            self.cfg_jump_link_arrival_x_threshold = None

            # ==================== v11.5.0 설정 변수 추가 시작 ====================
            self.cfg_arrival_frame_threshold = None
            self.cfg_action_success_frame_threshold = None
            # ==================== v11.5.0 설정 변수 추가 끝 ======================

            # ==================== v10.9.0 수정 시작 ====================
            # --- 상태 판정 시스템 변수 ---
            self.last_movement_time = 0.0
            self.player_state = 'on_terrain' # 초기값
            self.in_jump = False
            self.x_movement_history = deque(maxlen=5) # [v11.3.13] X축 이동 방향 추적을 위한 deque 추가
            self.jump_lock = False # (의사코드에는 있지만, jumping 판정 로직에 통합되어 실제 변수로는 불필요)
            self.jump_start_time = 0.0
            # ==================== v11.5.0 상태 머신 변수 추가 시작 ====================
            self.navigation_action = 'move_to_target' # 초기값 'path_failed'에서 변경
            self.navigation_state_locked = False
            self.state_transition_counters = defaultdict(int) # 상태 전이 프레임 카운터
            self.prepare_timeout_start = 0.0
            self.lock_timeout_start = 0.0
            # ==================== v11.5.0 상태 머신 변수 추가 끝 ======================
            
            self.jumping_candidate_frames = 0
            self.climbing_candidate_frames = 0
            self.falling_candidate_frames = 0
            # ==================== v10.9.0 수정 끝 ======================
            
            self.last_on_terrain_y = 0.0 # 마지막으로 지상에 있었을 때의 y좌표
            
            self.player_nav_state = 'on_terrain'  # 'on_terrain', 'climbing', 'jumping', 'falling'
            self.current_player_floor = None
            self.last_terrain_line_id = None
            
            self.last_player_pos = QPointF(0, 0)
            # 목표 및 경로 추적 변수
            self.target_waypoint_id = None
            self.last_reached_wp_id = None
            self.current_path_index = -1
            self.is_forward = True
            self.start_waypoint_found = False
            
            # v10.2.0: 중간 목표 상태 변수
            self.intermediate_target_pos = None
            self.intermediate_target_type = 'walk' # 'walk', 'climb', 'fall', 'jump'
            # ==================== v11.6.5 변수 추가 시작 ====================
            self.intermediate_target_entry_pos = None
            # ==================== v11.6.5 변수 추가 끝 ======================
            self.intermediate_target_exit_pos = None
            self.intermediate_target_object_name = ""
            self.guidance_text = "없음"

            # --- v12.0.0: A* 경로 탐색 시스템 변수 ---
            self.nav_graph = defaultdict(dict)  # {'node1': {'node2': cost, ...}} 형태의 내비게이션 그래프
            self.nav_nodes = {}                 # {'node_key': {'pos': QPointF, 'type': str, ...}} 노드 정보 저장
            self.journey_plan = []              # [wp_id1, wp_id2, ...] 전체 웨이포인트 여정
            self.current_journey_index = 0      # 현재 여정 진행 인덱스
            self.current_segment_path = []      # 현재 구간의 상세 경로 [node_key1, node_key2, ...]
            self.current_segment_index = 0      # 현재 상세 경로 진행 인덱스
            self.last_path_recalculation_time = 0.0 # <<< [v12.2.0] 추가: 경로 떨림 방지용
            self.expected_terrain_group = None  # 현재 안내 경로가 유효하기 위해 플레이어가 있어야 할 지형 그룹
            # --- v12.0.0: 추가 끝 ---

            #지형 간 상대 위치 벡터 저장
            self.feature_offsets = {}
            
            # [NEW] UI 업데이트 조절(Throttling)을 위한 카운터
            self.log_update_counter = 0
            
            self.render_options = {
                'background': True, 'features': True, 'waypoints': True,
                'terrain': True, 'objects': True, 'jump_links': True
            }
            self.initUI()
            self.perform_initial_setup()
        
    def initUI(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        
        # 1. 프로필 관리
        profile_groupbox = QGroupBox("1. 🗺️ 맵 프로필 관리")
        profile_layout = QVBoxLayout()
        self.profile_selector = QComboBox()
        self.profile_selector.currentIndexChanged.connect(self.on_profile_selected)
        profile_buttons_layout = QHBoxLayout()
        self.add_profile_btn = QPushButton("추가")
        self.rename_profile_btn = QPushButton("이름변경")
        self.delete_profile_btn = QPushButton("삭제")
        self.add_profile_btn.clicked.connect(self.add_profile)
        self.rename_profile_btn.clicked.connect(self.rename_profile)
        self.delete_profile_btn.clicked.connect(self.delete_profile)
        profile_buttons_layout.addWidget(self.add_profile_btn)
        profile_buttons_layout.addWidget(self.rename_profile_btn)
        profile_buttons_layout.addWidget(self.delete_profile_btn)
        profile_layout.addWidget(self.profile_selector)
        profile_layout.addLayout(profile_buttons_layout)
        profile_groupbox.setLayout(profile_layout)
        left_layout.addWidget(profile_groupbox)

        # 2. 경로 프로필 관리
        route_profile_groupbox = QGroupBox("2.  ROUTE 경로 프로필 관리")
        route_profile_layout = QVBoxLayout()
        self.route_profile_selector = QComboBox()
        self.route_profile_selector.currentIndexChanged.connect(self.on_route_profile_selected)
        route_profile_buttons_layout = QHBoxLayout()
        self.add_route_btn = QPushButton("추가")
        self.rename_route_btn = QPushButton("이름변경")
        self.delete_route_btn = QPushButton("삭제")
        self.add_route_btn.clicked.connect(self.add_route_profile)
        self.rename_route_btn.clicked.connect(self.rename_route_profile)
        self.delete_route_btn.clicked.connect(self.delete_route_profile)
        route_profile_buttons_layout.addWidget(self.add_route_btn)
        route_profile_buttons_layout.addWidget(self.rename_route_btn)
        route_profile_buttons_layout.addWidget(self.delete_route_btn)
        route_profile_layout.addWidget(self.route_profile_selector)
        route_profile_layout.addLayout(route_profile_buttons_layout)
        route_profile_groupbox.setLayout(route_profile_layout)
        left_layout.addWidget(route_profile_groupbox)

        # 3. 미니맵 설정
        self.minimap_groupbox = QGroupBox("3. 미니맵 설정")
        minimap_layout = QVBoxLayout(); self.set_area_btn = QPushButton("미니맵 범위 지정"); self.set_area_btn.clicked.connect(self.set_minimap_area)
        minimap_layout.addWidget(self.set_area_btn); self.minimap_groupbox.setLayout(minimap_layout); left_layout.addWidget(self.minimap_groupbox)

        # 4. 웨이포인트 경로 관리 (v10.0.0 개편)
        self.wp_groupbox = QGroupBox("4. 웨이포인트 경로 관리")
        wp_main_layout = QVBoxLayout()
        self.path_tabs = QTabWidget()
        self.forward_path_widget = QWidget()
        self.backward_path_widget = QWidget()
        self.path_tabs.addTab(self.forward_path_widget, "정방향")
        self.path_tabs.addTab(self.backward_path_widget, "역방향")
        
        # 정방향 탭 UI
        fw_layout = QVBoxLayout(self.forward_path_widget)
        self.forward_wp_list = QListWidget()
        self.forward_wp_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.forward_wp_list.model().rowsMoved.connect(self.waypoint_order_changed)
        fw_buttons = QHBoxLayout()
        fw_add_btn = QPushButton("추가"); fw_add_btn.clicked.connect(self.add_waypoint_to_path)
        fw_del_btn = QPushButton("삭제"); fw_del_btn.clicked.connect(self.delete_waypoint_from_path)
        fw_buttons.addWidget(fw_add_btn); fw_buttons.addWidget(fw_del_btn)
        fw_layout.addWidget(self.forward_wp_list)
        fw_layout.addLayout(fw_buttons)
        
        # 역방향 탭 UI
        bw_layout = QVBoxLayout(self.backward_path_widget)
        self.backward_wp_list = QListWidget()
        self.backward_wp_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.backward_wp_list.model().rowsMoved.connect(self.waypoint_order_changed)
        bw_buttons = QHBoxLayout()
        bw_add_btn = QPushButton("추가"); bw_add_btn.clicked.connect(self.add_waypoint_to_path)
        bw_del_btn = QPushButton("삭제"); bw_del_btn.clicked.connect(self.delete_waypoint_from_path)
        bw_buttons.addWidget(bw_add_btn); bw_buttons.addWidget(bw_del_btn)
        bw_layout.addWidget(self.backward_wp_list)
        bw_layout.addLayout(bw_buttons)
        
        wp_main_layout.addWidget(self.path_tabs)
        self.wp_groupbox.setLayout(wp_main_layout)
        left_layout.addWidget(self.wp_groupbox)

        # 5. 핵심 지형 관리 (기존과 동일)
        self.kf_groupbox = QGroupBox("5. 핵심 지형 관리")
        kf_layout = QVBoxLayout(); self.manage_kf_btn = QPushButton("핵심 지형 관리자 열기"); self.manage_kf_btn.clicked.connect(self.open_key_feature_manager)
        kf_layout.addWidget(self.manage_kf_btn); self.kf_groupbox.setLayout(kf_layout); left_layout.addWidget(self.kf_groupbox)

        # 6. 전체 맵 편집 (기존과 동일)
        self.editor_groupbox = QGroupBox("6. 전체 맵 편집")
        editor_layout = QVBoxLayout()
        self.open_editor_btn = QPushButton("미니맵 지형 편집기 열기")
        self.open_editor_btn.clicked.connect(self.open_full_minimap_editor)
        editor_layout.addWidget(self.open_editor_btn)
        self.editor_groupbox.setLayout(editor_layout)
        left_layout.addWidget(self.editor_groupbox)
        
        # 7. 탐지 제어
        # [v11.3.5] UI 순서 및 텍스트 변경
        detect_groupbox = QGroupBox("7. 탐지 제어")
        detect_layout = QHBoxLayout()

        # 좌측: 디버그 뷰 체크박스
        self.debug_view_checkbox = QCheckBox("디버그 뷰")
        self.debug_view_checkbox.toggled.connect(self.toggle_debug_view)
        detect_layout.addWidget(self.debug_view_checkbox)
        
        detect_layout.addStretch(1) # 중앙 공간
        
        # 우측: 버튼들
        self.state_config_btn = QPushButton("판정 설정")
        self.state_config_btn.clicked.connect(self._open_state_config_dialog)
        
        self.detect_anchor_btn = QPushButton("탐지 시작")
        self.detect_anchor_btn.setCheckable(True)
        self.detect_anchor_btn.setStyleSheet("padding: 3px 60px")
        self.detect_anchor_btn.clicked.connect(self.toggle_anchor_detection)
        
        detect_layout.addWidget(self.state_config_btn)
        detect_layout.addWidget(self.detect_anchor_btn)
        
        detect_groupbox.setLayout(detect_layout)
        left_layout.addWidget(detect_groupbox)

        left_layout.addStretch(1)
        
        # 로그 뷰어
        logs_layout = QVBoxLayout()
        logs_layout.addWidget(QLabel("일반 로그"))
        self.general_log_viewer = QTextEdit()
        self.general_log_viewer.setReadOnly(True)
        self.general_log_viewer.setFixedHeight(150)
        logs_layout.addWidget(self.general_log_viewer)
        
        logs_layout.addWidget(QLabel("탐지 상태 로그"))
        self.detection_log_viewer = QTextEdit()
        self.detection_log_viewer.setReadOnly(True)
        logs_layout.addWidget(self.detection_log_viewer)

        # 우측 레이아웃 (네비게이터 + 실시간 뷰)
        view_header_layout = QHBoxLayout()
        view_header_layout.addWidget(QLabel("실시간 미니맵 뷰 (휠: 확대/축소, 드래그: 이동)"))
        self.center_on_player_checkbox = QCheckBox("캐릭터 중심")
        self.center_on_player_checkbox.setChecked(True)
        view_header_layout.addWidget(self.center_on_player_checkbox)
        view_header_layout.addStretch(1)
        
        self.navigator_display = NavigatorDisplay(self)
        self.minimap_view_label = RealtimeMinimapView(self)
        
        right_layout.addWidget(self.navigator_display)
        right_layout.addLayout(view_header_layout)
        right_layout.addWidget(self.minimap_view_label, 1)
        
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(logs_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.update_general_log("MapTab이 초기화되었습니다. 맵 프로필을 선택해주세요.", "black")

    def _get_floor_from_closest_terrain_data(self, point, terrain_lines):
            """주어진 점에서 가장 가까운 지형선 데이터를 찾아 그 층 번호를 반환합니다."""
            min_dist_sq = float('inf')
            closest_floor = 0.0

            for line_data in terrain_lines:
                points = line_data.get("points", [])
                for i in range(len(points) - 1):
                    p1 = QPointF(points[i][0], points[i][1])
                    p2 = QPointF(points[i+1][0], points[i+1][1])
                    
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
        
    def update_detection_log(self, inliers, outliers):
        """정상치와 이상치 정보를 받아 탐지 상태 로그를 업데이트합니다."""
        log_html = "<b>활성 지형:</b> "
        
        if not inliers and not outliers:
            log_html += '<font color="red">탐지된 지형 없음</font>'
            self.detection_log_viewer.setHtml(log_html)
            return

        inlier_texts = []
        if inliers:
            sorted_inliers = sorted(inliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_inliers:
                inlier_texts.append(f'<font color="blue">{f["id"]}({f["conf"]:.2f})</font>')
        
        outlier_texts = []
        if outliers:
            sorted_outliers = sorted(outliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_outliers:
                outlier_texts.append(f'<font color="red">{f["id"]}({f["conf"]:.2f})</font>')

        log_html += ", ".join(inlier_texts)
        if inlier_texts and outlier_texts:
            log_html += ", "
        log_html += ", ".join(outlier_texts)
        
        self.detection_log_viewer.setHtml(log_html)

    def _prepare_data_for_json(self, data):
        """JSON으로 저장하기 전에 PyQt 객체를 순수 Python 타입으로 변환하는 재귀 함수."""
        if isinstance(data, dict):
            return {k: self._prepare_data_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._prepare_data_for_json(v) for v in data]
        elif isinstance(data, QPointF):
            return [data.x(), data.y()]
        elif isinstance(data, QSize):
            return [data.width(), data.height()]
        # QPoint, QRectF 등 다른 PyQt 타입도 필요 시 추가 가능
        return data

    def perform_initial_setup(self):
        os.makedirs(MAPS_DIR, exist_ok=True)
        self.check_and_migrate_old_config()
        self.profile_selector.blockSignals(True)
        self.populate_profile_selector()
        profile_to_load = None
        last_profile = self.load_global_settings()
        if last_profile and last_profile in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
            profile_to_load = last_profile
        elif self.profile_selector.count() > 0:
            profile_to_load = self.profile_selector.itemText(0)
        if profile_to_load:
            self.profile_selector.setCurrentText(profile_to_load)
        self.profile_selector.blockSignals(False)
        if profile_to_load:
            self.load_profile_data(profile_to_load)
        else:
            self.update_ui_for_no_profile()

    def populate_profile_selector(self):
        self.profile_selector.clear()
        try:
            profiles = sorted([d for d in os.listdir(MAPS_DIR) if os.path.isdir(os.path.join(MAPS_DIR, d))])
            self.profile_selector.addItems(profiles)
        except FileNotFoundError:
            pass

    def on_profile_selected(self, index):
        if index == -1:
            self.update_ui_for_no_profile()
            return
        profile_name = self.profile_selector.itemText(index)
        if profile_name == self.active_profile_name:
            return
        self.load_profile_data(profile_name)

    def check_and_migrate_old_config(self):
        old_config_file = os.path.join(CONFIG_PATH, 'map_config.json')
        old_features_file = os.path.join(CONFIG_PATH, 'map_key_features.json')
        if os.path.exists(old_config_file) or os.path.exists(old_features_file):
            reply = QMessageBox.question(self, "구버전 설정 발견",
                                         "구버전 맵 설정 파일이 발견되었습니다.\n'default'라는 이름의 새 프로필로 자동 변환하시겠습니까?\n\n(변환 후 원본 파일은 삭제됩니다.)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                default_profile_path = os.path.join(MAPS_DIR, 'default')
                os.makedirs(default_profile_path, exist_ok=True)
                if os.path.exists(old_config_file):
                    shutil.move(old_config_file, os.path.join(default_profile_path, 'map_config.json'))
                if os.path.exists(old_features_file):
                    shutil.move(old_features_file, os.path.join(default_profile_path, 'map_key_features.json'))
                self.update_general_log("구버전 설정을 'default' 프로필로 마이그레이션했습니다.", "purple")

    def load_profile_data(self, profile_name):
        self.active_profile_name = profile_name
        
        # [NEW] 프로필 변경 시 모든 런타임/탐지 관련 상태 변수 완벽 초기화
        if self.detection_thread and self.detection_thread.isRunning():
            self.toggle_anchor_detection(False) # 탐지 중이었다면 정지
            self.detect_anchor_btn.setChecked(False)

        self.minimap_region = None
        self.key_features = {}
        self.geometry_data = {}
        self.route_profiles = {}
        self.active_route_profile_name = None
        self.reference_anchor_id = None
        
        self.global_positions = {}
        self.feature_offsets = {}
        self.full_map_pixmap = None
        self.full_map_bounding_rect = QRectF()
        
        # 탐지/네비게이션 상태 초기화
        self.smoothed_player_pos = None
        self.last_player_pos = QPointF(0, 0)
        self.player_state = 'on_terrain'
        self.navigation_action = 'move_to_target'
        self.navigation_state_locked = False
        self.start_waypoint_found = False
        self.target_waypoint_id = None
        self.last_reached_wp_id = None
        self.current_path_index = -1
        self.intermediate_target_pos = None
        self.intermediate_target_type = 'walk'
        self.active_feature_info = []
        self.my_player_global_rects = []
        self.other_player_global_rects = []
        
        # 로그 초기화
        self.general_log_viewer.clear()
        self.detection_log_viewer.clear()

        profile_path = os.path.join(MAPS_DIR, profile_name)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            self.minimap_region, self.key_features = None, {}
            self.route_profiles, self.active_route_profile_name = {}, None
            self.geometry_data = {}
            self.reference_anchor_id = None
            
            # [v11.3.7] 설정 로드 로직 변경: 여기서 기본값으로 먼저 초기화
            self.cfg_idle_time_threshold = IDLE_TIME_THRESHOLD
            self.cfg_climbing_state_frame_threshold = CLIMBING_STATE_FRAME_THRESHOLD
            self.cfg_falling_state_frame_threshold = FALLING_STATE_FRAME_THRESHOLD
            self.cfg_jumping_state_frame_threshold = JUMPING_STATE_FRAME_THRESHOLD
            self.cfg_on_terrain_y_threshold = ON_TERRAIN_Y_THRESHOLD
            self.cfg_jump_y_min_threshold = JUMP_Y_MIN_THRESHOLD
            self.cfg_jump_y_max_threshold = JUMP_Y_MAX_THRESHOLD
            self.cfg_fall_y_min_threshold = FALL_Y_MIN_THRESHOLD
            self.cfg_climb_x_movement_threshold = CLIMB_X_MOVEMENT_THRESHOLD
            self.cfg_fall_on_ladder_x_movement_threshold = FALL_ON_LADDER_X_MOVEMENT_THRESHOLD
            self.cfg_ladder_x_grab_threshold = LADDER_X_GRAB_THRESHOLD
            self.cfg_move_deadzone = MOVE_DEADZONE
            self.cfg_max_jump_duration = MAX_JUMP_DURATION
            self.cfg_y_movement_deadzone = Y_MOVEMENT_DEADZONE
            self.cfg_waypoint_arrival_x_threshold = WAYPOINT_ARRIVAL_X_THRESHOLD
            self.cfg_ladder_arrival_x_threshold = LADDER_ARRIVAL_X_THRESHOLD
            self.cfg_jump_link_arrival_x_threshold = JUMP_LINK_ARRIVAL_X_THRESHOLD
            # ==================== v11.5.0 기본값 초기화 추가 시작 ====================
            self.cfg_arrival_frame_threshold = 2
            self.cfg_action_success_frame_threshold = 2
            # ==================== v11.5.0 기본값 초기화 추가 끝 ======================
            
            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            self.reference_anchor_id = config.get('reference_anchor_id')

            # 저장된 상태 판정 설정이 있으면 기본값을 덮어쓰기
            state_config = config.get('state_machine_config', {})
            if state_config:
                self.cfg_idle_time_threshold = state_config.get("idle_time_threshold", self.cfg_idle_time_threshold)
                self.cfg_climbing_state_frame_threshold = state_config.get("climbing_state_frame_threshold", self.cfg_climbing_state_frame_threshold)
                self.cfg_falling_state_frame_threshold = state_config.get("falling_state_frame_threshold", self.cfg_falling_state_frame_threshold)
                self.cfg_jumping_state_frame_threshold = state_config.get("jumping_state_frame_threshold", self.cfg_jumping_state_frame_threshold)
                self.cfg_on_terrain_y_threshold = state_config.get("on_terrain_y_threshold", self.cfg_on_terrain_y_threshold)
                self.cfg_jump_y_min_threshold = state_config.get("jump_y_min_threshold", self.cfg_jump_y_min_threshold)
                self.cfg_jump_y_max_threshold = state_config.get("jump_y_max_threshold", self.cfg_jump_y_max_threshold)
                self.cfg_fall_y_min_threshold = state_config.get("fall_y_min_threshold", self.cfg_fall_y_min_threshold)
                self.cfg_climb_x_movement_threshold = state_config.get("climb_x_movement_threshold", self.cfg_climb_x_movement_threshold)
                self.cfg_fall_on_ladder_x_movement_threshold = state_config.get("fall_on_ladder_x_movement_threshold", self.cfg_fall_on_ladder_x_movement_threshold)
                self.cfg_ladder_x_grab_threshold = state_config.get("ladder_x_grab_threshold", self.cfg_ladder_x_grab_threshold)
                self.cfg_move_deadzone = state_config.get("move_deadzone", self.cfg_move_deadzone)
                self.cfg_max_jump_duration = state_config.get("max_jump_duration", self.cfg_max_jump_duration)
                self.cfg_y_movement_deadzone = state_config.get("y_movement_deadzone", self.cfg_y_movement_deadzone)
                self.cfg_waypoint_arrival_x_threshold = state_config.get("waypoint_arrival_x_threshold", self.cfg_waypoint_arrival_x_threshold)
                self.cfg_ladder_arrival_x_threshold = state_config.get("ladder_arrival_x_threshold", self.cfg_ladder_arrival_x_threshold)
                self.cfg_jump_link_arrival_x_threshold = state_config.get("jump_link_arrival_x_threshold", self.cfg_jump_link_arrival_x_threshold)
                # ==================== v11.5.0 설정 로드 추가 시작 ====================
                self.cfg_arrival_frame_threshold = state_config.get("arrival_frame_threshold", self.cfg_arrival_frame_threshold)
                self.cfg_action_success_frame_threshold = state_config.get("action_success_frame_threshold", self.cfg_action_success_frame_threshold)
                # ==================== v11.5.0 설정 로드 추가 끝 ======================
                
                self.update_general_log("저장된 상태 판정 설정을 로드했습니다.", "gray")

            saved_options = config.get('render_options', {})
            self.render_options = {
                'background': True, 'features': True, 'waypoints': True,
                'terrain': True, 'objects': True, 'jump_links': True
            }
            self.render_options.update(saved_options)

            features = {}
            if os.path.exists(features_file):
                with open(features_file, 'r', encoding='utf-8') as f:
                    features = json.load(f)
                    
            cleaned_features = {
                feature_id: data
                for feature_id, data in features.items()
                if isinstance(data, dict) and 'image_base64' in data
            }
            
            if len(cleaned_features) != len(features):
                self.update_general_log("경고: 유효하지 않은 데이터가 'map_key_features.json'에서 발견되어 자동 정리합니다.", "orange")
                self.key_features = cleaned_features
                profile_path = os.path.join(MAPS_DIR, profile_name)
                with open(os.path.join(profile_path, 'map_key_features.json'), 'w', encoding='utf-8') as f:
                    json.dump(self.key_features, f, indent=4, ensure_ascii=False)
            else:
                self.key_features = features

            if os.path.exists(geometry_file):
                with open(geometry_file, 'r', encoding='utf-8') as f:
                    self.geometry_data = json.load(f)
            else:
                self.geometry_data = {"terrain_lines": [], "transition_objects": [], "waypoints": [], "jump_links": []}

            config_updated, features_updated, geometry_updated = self.migrate_data_structures(config, self.key_features, self.geometry_data)

            self.route_profiles = config.get('route_profiles', {})
            self.active_route_profile_name = config.get('active_route_profile')
            self.minimap_region = config.get('minimap_region')

            if config_updated or features_updated or geometry_updated:
                self.save_profile_data()

            self._build_line_floor_map()    # [v11.4.5] 맵 데이터 로드 후 캐시 빌드
            self.global_positions = self._calculate_global_positions()
            self._generate_full_map_pixmap()
            self._assign_dynamic_names()
            # --- v12.0.0 수정: 현재 경로 기준으로 그래프 생성 ---
            active_route = self.route_profiles.get(self.active_route_profile_name, {})
            wp_ids = set(active_route.get("forward_path", []) + active_route.get("backward_path", []))
            self._build_navigation_graph(list(wp_ids))
            self.update_ui_for_new_profile()
            self.update_general_log(f"'{profile_name}' 맵 프로필을 로드했습니다.", "blue")
            self._center_realtime_view_on_map()
        except Exception as e:
            self.update_general_log(f"'{profile_name}' 프로필 로드 오류: {e}", "red")
            self.update_ui_for_no_profile()

    def migrate_data_structures(self, config, features, geometry):
        config_updated = False
        features_updated = False
        geometry_updated = False

        # v5 마이그레이션
        if 'waypoints' in config and 'route_profiles' not in config:
            self.update_general_log("v5 마이그레이션: 웨이포인트 구조를 경로 프로필로 변환합니다.", "purple")
            config['route_profiles'] = {"기본 경로": {"waypoints": config.pop('waypoints', [])}}
            config['active_route_profile'] = "기본 경로"
            config_updated = True
        
        # v10.0.0 마이그레이션: 경로 프로필 구조 변경
        for route_name, route_data in config.get('route_profiles', {}).items():
            if 'waypoints' in route_data and 'forward_path' not in route_data:
                self.update_general_log(f"v10 마이그레이션: '{route_name}' 경로를 정방향/역방향 구조로 변환합니다.", "purple")
                old_waypoints = route_data.pop('waypoints', [])
                
                # 구버전 웨이포인트를 새로운 geometry_data['waypoints']로 이동
                if 'waypoints' not in geometry: geometry['waypoints'] = []
                
                new_path_ids = []
                for old_wp in old_waypoints:
                    # 중복 방지
                    if not any(wp['name'] == old_wp['name'] for wp in geometry['waypoints']):
                        wp_id = f"wp-{uuid.uuid4()}"
                        
                        # 전역 좌표를 계산해서 저장해야 함
                        # 이 부분은 일단 이름만 저장하고, 사용자가 편집기에서 위치를 다시 지정하도록 유도
                        # 또는 _calculate_global_positions를 먼저 호출해야 함.
                        # 여기서는 임시로 (0,0) 저장
                        new_wp_data = {
                            "id": wp_id,
                            "name": old_wp['name'],
                            "pos": [0,0], # 위치는 재설정 필요
                            "floor": 1.0, # 기본 1층
                            "parent_line_id": None
                        }
                        geometry['waypoints'].append(new_wp_data)
                        new_path_ids.append(wp_id)
                    else: # 이미 존재하는 이름이면 ID를 찾아서 추가
                        existing_wp = next((wp for wp in geometry['waypoints'] if wp['name'] == old_wp['name']), None)
                        if existing_wp:
                            new_path_ids.append(existing_wp['id'])
                
                route_data['forward_path'] = new_path_ids
                route_data['backward_path'] = []
                config_updated = True
                geometry_updated = True

        # v10.0.0 마이그레이션: geometry 데이터 필드 추가
        if "waypoints" not in geometry: geometry["waypoints"] = []; geometry_updated = True
        if "jump_links" not in geometry: geometry["jump_links"] = []; geometry_updated = True
        for line in geometry.get("terrain_lines", []):
            if "floor" not in line: line["floor"] = 1.0; geometry_updated = True
        
        # v6 마이그레이션
        all_waypoints_old = [wp for route in config.get('route_profiles', {}).values() for wp in route.get('waypoints', [])]
        if any('feature_threshold' in wp for wp in all_waypoints_old):
            self.update_general_log("v6 마이그레이션: 정확도 설정을 지형으로 이전합니다.", "purple")
            for wp in all_waypoints_old:
                wp_threshold = wp.pop('feature_threshold')
                for feature_link in wp.get('key_feature_ids', []):
                    feature_id = feature_link['id']
                    if feature_id in self.key_features: # 'features'를 'self.key_features'로 변경
                        if self.key_features[feature_id].get('threshold', 0) < wp_threshold:
                            self.key_features[feature_id]['threshold'] = wp_threshold # 'features'를 'self.key_features'로 변경
                            features_updated = True
            config_updated = True
        
        for feature_id, feature_data in self.key_features.items(): # 'features'를 'self.key_features'로 변경
            if 'threshold' not in feature_data: feature_data['threshold'] = 0.85; features_updated = True
            if 'context_image_base64' not in feature_data: feature_data['context_image_base64'] = ""; features_updated = True
            if 'rect_in_context' not in feature_data: feature_data['rect_in_context'] = []; features_updated = True
        # v10.6.0 마이그레이션: 층 이동 오브젝트 구조 변경
        if 'transition_objects' in geometry:
            old_objects = [obj for obj in geometry['transition_objects'] if 'parent_line_id' in obj]
            if old_objects:
                reply = QMessageBox.information(self, "데이터 구조 업데이트",
                                                "구버전 '층 이동 오브젝트' 데이터가 발견되었습니다.\n"
                                                "새로운 시스템에서는 두 지형을 직접 연결하는 방식으로 변경되어 기존 데이터와 호환되지 않습니다.\n\n"
                                                "확인 버튼을 누르면 기존 층 이동 오브젝트 데이터가 모두 삭제됩니다.\n"
                                                "삭제 후 '미니맵 지형 편집기'에서 새로 생성해주세요.",
                                                QMessageBox.StandardButton.Ok)
                
                # 'parent_line_id'가 없는, 즉 새로운 구조의 오브젝트만 남김
                geometry['transition_objects'] = [obj for obj in geometry['transition_objects'] if 'parent_line_id' not in obj]
                geometry_updated = True
                self.update_general_log("v10.6.0 마이그레이션: 구버전 층 이동 오브젝트 데이터를 삭제했습니다.", "purple")   
        return config_updated, features_updated, geometry_updated

    def save_profile_data(self):
        if not self.active_profile_name: return
        profile_path = os.path.join(MAPS_DIR, self.active_profile_name)
        os.makedirs(profile_path, exist_ok=True)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            # [v11.3.0] 저장할 데이터에 상태 판정 설정 추가
            state_machine_config = {
                "idle_time_threshold": self.cfg_idle_time_threshold,
                "climbing_state_frame_threshold": self.cfg_climbing_state_frame_threshold,
                "falling_state_frame_threshold": self.cfg_falling_state_frame_threshold,
                "jumping_state_frame_threshold": self.cfg_jumping_state_frame_threshold,
                "on_terrain_y_threshold": self.cfg_on_terrain_y_threshold,
                "jump_y_min_threshold": self.cfg_jump_y_min_threshold,
                "jump_y_max_threshold": self.cfg_jump_y_max_threshold,
                "fall_y_min_threshold": self.cfg_fall_y_min_threshold,
                "climb_x_movement_threshold": self.cfg_climb_x_movement_threshold,
                "fall_on_ladder_x_movement_threshold": self.cfg_fall_on_ladder_x_movement_threshold,
                "ladder_x_grab_threshold": self.cfg_ladder_x_grab_threshold,
                "move_deadzone": self.cfg_move_deadzone,
                "max_jump_duration": self.cfg_max_jump_duration,
                "y_movement_deadzone": self.cfg_y_movement_deadzone,
                "waypoint_arrival_x_threshold": self.cfg_waypoint_arrival_x_threshold,
                "ladder_arrival_x_threshold": self.cfg_ladder_arrival_x_threshold,
                "jump_link_arrival_x_threshold": self.cfg_jump_link_arrival_x_threshold,
                # ==================== v11.5.0 설정 저장 추가 시작 ====================
                "arrival_frame_threshold": self.cfg_arrival_frame_threshold,
                "action_success_frame_threshold": self.cfg_action_success_frame_threshold,
                # ==================== v11.5.0 설정 저장 추가 끝 ======================
            }

            config_data = self._prepare_data_for_json({
                'minimap_region': self.minimap_region,
                'active_route_profile': self.active_route_profile_name,
                'route_profiles': self.route_profiles,
                'render_options': self.render_options,
                'reference_anchor_id': self.reference_anchor_id,
                'state_machine_config': state_machine_config # <<< 추가
            })
            
            key_features_data = self._prepare_data_for_json(self.key_features)
            geometry_data = self._prepare_data_for_json(self.geometry_data)
            

            with open(config_file, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4, ensure_ascii=False)
            with open(features_file, 'w', encoding='utf-8') as f: json.dump(key_features_data, f, indent=4, ensure_ascii=False)
            with open(geometry_file, 'w', encoding='utf-8') as f: json.dump(geometry_data, f, indent=4, ensure_ascii=False)
            
            # save 후에 뷰 업데이트
            self._build_line_floor_map() # [v11.4.5] 맵 데이터 저장 후 캐시 빌드 및 뷰 업데이트
            self._update_map_data_and_views()
            # --- v12.0.0 수정: 현재 경로 기준으로 그래프 재생성 ---
            active_route = self.route_profiles.get(self.active_route_profile_name, {})
            wp_ids = set(active_route.get("forward_path", []) + active_route.get("backward_path", []))
            self._build_navigation_graph(list(wp_ids))
            
        except Exception as e:
            self.update_general_log(f"프로필 저장 오류: {e}", "red")

    def load_global_settings(self):
        if os.path.exists(GLOBAL_MAP_SETTINGS_FILE):
            try:
                with open(GLOBAL_MAP_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    return settings.get('active_profile')
            except json.JSONDecodeError:
                return None
        return None

    def save_global_settings(self):
        with open(GLOBAL_MAP_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'active_profile': self.active_profile_name}, f)

    def add_profile(self):
        profile_name, ok = QInputDialog.getText(self, "새 맵 프로필 추가", "프로필 이름 (폴더명으로 사용, 영문/숫자 권장):")
        if ok and profile_name:
            if profile_name in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
                QMessageBox.warning(self, "오류", "이미 존재하는 프로필 이름입니다.")
                return

            new_profile_path = os.path.join(MAPS_DIR, profile_name)
            os.makedirs(new_profile_path, exist_ok=True)
            self.populate_profile_selector()
            self.profile_selector.setCurrentText(profile_name)
            self.update_general_log(f"새 프로필 '{profile_name}'을(를) 생성했습니다.", "green")

    def rename_profile(self):
        if not self.active_profile_name: return

        old_name = self.active_profile_name
        new_name, ok = QInputDialog.getText(self, "맵 프로필 이름 변경", f"'{old_name}'의 새 이름:", text=old_name)

        if ok and new_name and new_name != old_name:
            if new_name in [self.profile_selector.itemText(i) for i in range(self.profile_selector.count())]:
                QMessageBox.warning(self, "오류", "이미 존재하는 프로필 이름입니다.")
                return

            old_path = os.path.join(MAPS_DIR, old_name)
            new_path = os.path.join(MAPS_DIR, new_name)
            try:
                os.rename(old_path, new_path)
                self.update_general_log(f"맵 프로필 이름이 '{old_name}'에서 '{new_name}'(으)로 변경되었습니다.", "blue")

                self.profile_selector.blockSignals(True)
                self.populate_profile_selector()
                self.profile_selector.setCurrentText(new_name)
                self.profile_selector.blockSignals(False)

                self.load_profile_data(new_name)
            except Exception as e:
                QMessageBox.critical(self, "오류", f"이름 변경 실패: {e}")

    def delete_profile(self):
        if not self.active_profile_name: return

        profile_to_delete = self.active_profile_name
        reply = QMessageBox.question(self, "맵 프로필 삭제 확인",
                                     f"'{profile_to_delete}' 맵 프로필과 모든 관련 데이터를 영구적으로 삭제하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)

        if reply == QMessageBox.StandardButton.Yes:
            profile_path = os.path.join(MAPS_DIR, profile_to_delete)
            try:
                shutil.rmtree(profile_path)
                self.update_general_log(f"'{profile_to_delete}' 맵 프로필이 삭제되었습니다.", "orange")

                self.profile_selector.blockSignals(True)
                self.populate_profile_selector()

                profile_to_load = None
                if self.profile_selector.count() > 0:
                    profile_to_load = self.profile_selector.itemText(0)
                    self.profile_selector.setCurrentIndex(0)

                self.profile_selector.blockSignals(False)

                if profile_to_load:
                    self.load_profile_data(profile_to_load)
                else:
                    self.update_ui_for_no_profile()
            except Exception as e:
                QMessageBox.critical(self, "오류", f"프로필 삭제 실패: {e}")

    def update_ui_for_new_profile(self):
        self.minimap_groupbox.setTitle(f"3. 미니맵 설정 (맵: {self.active_profile_name})")
        self.wp_groupbox.setTitle(f"4. 웨이포인트 경로 관리 (경로: {self.active_route_profile_name})")
        self.kf_groupbox.setTitle(f"5. 핵심 지형 관리 (맵: {self.active_profile_name})")
        self.editor_groupbox.setTitle(f"6. 전체 맵 편집 (맵: {self.active_profile_name})")

        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.manage_kf_btn, self.open_editor_btn, self.detect_anchor_btn, self.wp_groupbox
        ]
        for widget in all_widgets:
            widget.setEnabled(True)

        self.populate_route_profile_selector()
        self.minimap_view_label.setText("탐지를 시작하세요.")
        self.save_global_settings()

    def update_ui_for_no_profile(self):
        self.active_profile_name = None
        self.active_route_profile_name = None
        self.route_profiles.clear()
        self.key_features.clear()
        self.geometry_data.clear()
        self.forward_wp_list.clear()
        self.backward_wp_list.clear()
        self.route_profile_selector.clear()
        self.minimap_region = None
        self.full_map_pixmap = None

        self.minimap_groupbox.setTitle("3. 미니맵 설정 (프로필 없음)")
        self.wp_groupbox.setTitle("4. 웨이포인트 경로 관리 (프로필 없음)")
        self.kf_groupbox.setTitle("5. 핵심 지형 관리 (프로필 없음)")
        self.editor_groupbox.setTitle("6. 전체 맵 편집 (프로필 없음)")

        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.manage_kf_btn, self.open_editor_btn, self.detect_anchor_btn, self.wp_groupbox
        ]
        for widget in all_widgets:
            widget.setEnabled(False)

        self.minimap_view_label.setText("맵 프로필을 선택하거나 생성해주세요.")
        self.save_global_settings()

    def populate_route_profile_selector(self):
        self.route_profile_selector.blockSignals(True)
        self.route_profile_selector.clear()

        if not self.route_profiles:
            self.route_profiles["기본 경로"] = {"forward_path": [], "backward_path": []}
            self.active_route_profile_name = "기본 경로"

        routes = list(self.route_profiles.keys())
        self.route_profile_selector.addItems(routes)

        if self.active_route_profile_name in routes:
            self.route_profile_selector.setCurrentText(self.active_route_profile_name)
        elif routes:
            self.active_route_profile_name = routes[0]
            self.route_profile_selector.setCurrentIndex(0)
        else:
            self.active_route_profile_name = None

        self.route_profile_selector.blockSignals(False)
        self.populate_waypoint_list()

    def on_route_profile_selected(self, index):
        if index == -1: return

        route_name = self.route_profile_selector.itemText(index)
        if route_name != self.active_route_profile_name:
            self.active_route_profile_name = route_name
            self.update_general_log(f"'{route_name}' 경로 프로필로 전환했습니다.", "SaddleBrown")
            self.populate_waypoint_list()
            # --- v12.0.0 추가: 경로 프로필 변경 시 그래프 재생성 ---
            active_route = self.route_profiles.get(self.active_route_profile_name, {})
            wp_ids = set(active_route.get("forward_path", []) + active_route.get("backward_path", []))
            self._build_navigation_graph(list(wp_ids))
            # --- 추가 끝 ---
            self.save_profile_data()

    def add_route_profile(self):
        route_name, ok = QInputDialog.getText(self, "새 경로 프로필 추가", "경로 프로필 이름:")
        if ok and route_name:
            if route_name in self.route_profiles:
                QMessageBox.warning(self, "오류", "이미 존재하는 경로 프로필 이름입니다.")
                return

            self.route_profiles[route_name] = {"forward_path": [], "backward_path": []}
            self.active_route_profile_name = route_name
            self.populate_route_profile_selector()
            self.save_profile_data()
            self.update_general_log(f"새 경로 '{route_name}'이(가) 추가되었습니다.", "green")

    def rename_route_profile(self):
        if not self.active_route_profile_name: return

        old_name = self.active_route_profile_name
        new_name, ok = QInputDialog.getText(self, "경로 프로필 이름 변경", f"'{old_name}'의 새 이름:", text=old_name)

        if ok and new_name and new_name != old_name:
            if new_name in self.route_profiles:
                QMessageBox.warning(self, "오류", "이미 존재하는 이름입니다.")
                return

            self.route_profiles[new_name] = self.route_profiles.pop(old_name)
            self.active_route_profile_name = new_name
            self.populate_route_profile_selector()
            self.save_profile_data()
            self.update_general_log(f"경로 이름이 '{old_name}'에서 '{new_name}'(으)로 변경되었습니다.", "blue")

    def delete_route_profile(self):
        if not self.active_route_profile_name: return
        if len(self.route_profiles) <= 1:
            QMessageBox.warning(self, "삭제 불가", "최소 1개의 경로 프로필은 존재해야 합니다.")
            return

        reply = QMessageBox.question(self, "경로 프로필 삭제", f"'{self.active_route_profile_name}' 경로를 삭제하시겠습니까?")
        if reply == QMessageBox.StandardButton.Yes:
            del self.route_profiles[self.active_route_profile_name]
            self.active_route_profile_name = list(self.route_profiles.keys())[0]
            self.populate_route_profile_selector()
            self.save_profile_data()

    def get_all_waypoints_with_route_name(self):
        """(구버전 호환용) 모든 경로 프로필의 웨이포인트에 'route_name'을 추가하여 단일 리스트로 반환합니다."""
        all_waypoints = []
        for route_name, route_data in self.route_profiles.items():
            # v10.0.0 이전 데이터 구조에 대한 호환성 코드
            if 'waypoints' in route_data:
                for wp in route_data['waypoints']:
                    wp_copy = wp.copy()
                    wp_copy['route_name'] = route_name
                    all_waypoints.append(wp_copy)
        return all_waypoints

    def open_key_feature_manager(self):
        all_waypoints = self.get_all_waypoints_with_route_name()
        dialog = KeyFeatureManagerDialog(self.key_features, all_waypoints, self)
        dialog.exec()
        self._generate_full_map_pixmap()

    def open_full_minimap_editor(self):
        """'미니맵 지형 편집기 열기' 버튼에 연결된 슬롯."""
        if not self.active_profile_name:
            QMessageBox.warning(self, "오류", "먼저 맵 프로필을 선택해주세요.")
            return

        self.global_positions = self._calculate_global_positions()
        self._assign_dynamic_names()
        
        self.editor_dialog = FullMinimapEditorDialog(
            profile_name=self.active_profile_name,
            active_route_profile=self.active_route_profile_name,
            key_features=self.key_features,
            route_profiles=self.route_profiles,
            geometry_data=self.geometry_data, # 이름 정보가 포함된 데이터를 전달
            render_options=self.render_options,
            global_positions=self.global_positions,
            parent=self
        )
        self.global_pos_updated.connect(self.editor_dialog.update_locked_position)
        
        try:
            result = self.editor_dialog.exec()
            
            if result:
                self.geometry_data = self.editor_dialog.get_updated_geometry_data()
                self.render_options = self.editor_dialog.get_current_view_options()
                self.save_profile_data()
                self.update_general_log("지형 편집기 변경사항이 저장되었습니다.", "green")
                self.global_positions = self._calculate_global_positions()
                self._generate_full_map_pixmap() 
                self.populate_waypoint_list() # 변경사항을 웨이포인트 경로 관리 UI에 즉시 반영 ---
            else:
                self.update_general_log("지형 편집이 취소되었습니다.", "black")
            
        finally:
            self.global_pos_updated.disconnect(self.editor_dialog.update_locked_position)
            self.editor_dialog = None

    def get_waypoint_name_from_item(self, item):
        if not item:
            return None
        text = item.text()
        return text.split('. ', 1)[1] if '. ' in text and text.split('. ', 1)[0].isdigit() else text

    def process_new_waypoint_data(self, wp_data, final_features_on_canvas, newly_drawn_features, deleted_feature_ids, context_frame_bgr):
        # 이 함수는 v10.0.0에서 더 이상 사용되지 않음. 웨이포인트는 편집기에서 직접 생성됨.
        # 호환성을 위해 남겨둠
        return {}

    def update_all_waypoints_with_features(self):
        """(구버전 호환용) 현재 맵 프로필의 모든 웨이포인트를 순회하며, 등록된 모든 핵심 지형과의 연결을 재구성합니다."""
        all_old_waypoints = self.get_all_waypoints_with_route_name()
        if not all_old_waypoints:
            QMessageBox.information(self, "알림", "갱신할 (구버전) 웨이포인트가 없습니다.")
            return False

        reply = QMessageBox.question(self, "전체 갱신 확인",
                                    f"총 {len(all_old_waypoints)}개의 (구버전) 웨이포인트와 {len(self.key_features)}개의 핵심 지형의 연결을 갱신합니다.\n"
                                    "이 작업은 각 웨이포인트의 기존 핵심 지형 링크를 덮어씁니다. 계속하시겠습니까?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            return False

        self.update_general_log("모든 (구버전) 웨이포인트와 핵심 지형의 연결을 갱신합니다...", "purple")
        QApplication.processEvents()
        updated_count = 0

        for route_name, route_data in self.route_profiles.items():
            if 'waypoints' not in route_data: continue
            for wp in route_data.get('waypoints', []):
                if 'image_base64' not in wp or not wp['image_base64']:
                    continue
                try:
                    # ... (기존 로직과 동일) ...
                    updated_count += 1
                except Exception as e:
                    self.update_general_log(f"'{wp['name']}' 갱신 중 오류: {e}", "red")

        self.save_profile_data()
        self.update_general_log(f"완료: 총 {len(all_old_waypoints)}개 중 {updated_count}개의 웨이포인트 링크를 갱신했습니다.", "purple")
        QMessageBox.information(self, "성공", f"{updated_count}개의 웨이포인트 갱신 완료.")
        return True

    def _get_next_feature_name(self):
        max_num = max([int(name[1:]) for name in self.key_features.keys() if name.startswith("P") and name[1:].isdigit()] or [0])
        return f"P{max_num + 1}"

    def add_waypoint_to_path(self):
        all_wps_in_geom = self.geometry_data.get("waypoints", [])
        if not all_wps_in_geom:
            QMessageBox.information(self, "알림", "편집기에서 먼저 웨이포인트를 생성해주세요.")
            return

        # 현재 경로에 이미 추가된 ID들을 제외
        current_route = self.route_profiles[self.active_route_profile_name]
        current_tab_index = self.path_tabs.currentIndex()
        path_key = "forward_path" if current_tab_index == 0 else "backward_path"
        existing_ids = set(current_route.get(path_key, []))
        
        available_wps = {wp['name']: wp['id'] for wp in all_wps_in_geom if wp['id'] not in existing_ids}
        
        if not available_wps:
            QMessageBox.information(self, "알림", "모든 웨이포인트가 이미 경로에 추가되었습니다.")
            return

        wp_name, ok = QInputDialog.getItem(self, "경로에 웨이포인트 추가", "추가할 웨이포인트를 선택하세요:", sorted(available_wps.keys()), 0, False)

        if ok and wp_name:
            wp_id = available_wps[wp_name]
            current_route.get(path_key, []).append(wp_id)
            self.populate_waypoint_list()
            self.save_profile_data()

    def delete_waypoint_from_path(self):
        current_tab_index = self.path_tabs.currentIndex()
        
        if current_tab_index == 0:
            list_widget = self.forward_wp_list
            path_key = "forward_path"
        else:
            list_widget = self.backward_wp_list
            path_key = "backward_path"
            
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "오류", "삭제할 웨이포인트를 목록에서 선택하세요.")
            return

        current_route = self.route_profiles[self.active_route_profile_name]
        path_ids = current_route.get(path_key, [])
        
        for item in selected_items:
            row = list_widget.row(item)
            if 0 <= row < len(path_ids):
                del path_ids[row]
        
        self.populate_waypoint_list()
        self.save_profile_data()

    def set_minimap_area(self):
        self.update_general_log("화면에서 미니맵 영역을 드래그하여 선택하세요...", "black")
        QApplication.processEvents()
        QThread.msleep(200)
        snipper = ScreenSnipper(self)
        if snipper.exec():
            roi = snipper.get_roi()
            dpr = self.screen().devicePixelRatio()
            self.minimap_region = {
                'top': int(roi.top() * dpr),
                'left': int(roi.left() * dpr),
                'width': int(roi.width() * dpr),
                'height': int(roi.height() * dpr)
            }
            self.update_general_log(f"새 미니맵 범위 지정 완료: {self.minimap_region}", "black")
            self.save_profile_data()
        else:
            self.update_general_log("미니맵 범위 지정이 취소되었습니다.", "black")

    def populate_waypoint_list(self):
        """v10.0.0: 새로운 경로 구조에 맞게 웨이포인트 목록을 채웁니다."""
        self.forward_wp_list.clear()
        self.backward_wp_list.clear()

        if not self.active_route_profile_name or not self.route_profiles:
            self.wp_groupbox.setTitle("4. 웨이포인트 경로 관리 (경로 없음)")
            return

        self.wp_groupbox.setTitle(f"4. 웨이포인트 경로 관리 (경로: {self.active_route_profile_name})")
        
        current_route = self.route_profiles[self.active_route_profile_name]
        all_wps_in_geom = self.geometry_data.get("waypoints", [])
        
        # 정방향 경로 채우기
        forward_path_ids = current_route.get("forward_path", [])
        for i, wp_id in enumerate(forward_path_ids):
            wp_data = next((wp for wp in all_wps_in_geom if wp['id'] == wp_id), None)
            if wp_data:
                item_text = f"{i + 1}. {wp_data.get('name', '이름 없음')} ({wp_data.get('floor', 'N/A')}층)"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, wp_id)
                self.forward_wp_list.addItem(item)
        
        # 역방향 경로 채우기
        backward_path_ids = current_route.get("backward_path", [])
        for i, wp_id in enumerate(backward_path_ids):
            wp_data = next((wp for wp in all_wps_in_geom if wp['id'] == wp_id), None)
            if wp_data:
                item_text = f"{i + 1}. {wp_data.get('name', '이름 없음')} ({wp_data.get('floor', 'N/A')}층)"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, wp_id)
                self.backward_wp_list.addItem(item)


    def get_cleaned_minimap_image(self):
        if not self.minimap_region: return None
        with mss.mss() as sct:
            sct_img = sct.grab(self.minimap_region); frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            my_player_mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER); other_player_mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1); other_player_mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
            other_player_mask = cv2.bitwise_or(other_player_mask1, other_player_mask2); kernel = np.ones((5, 5), np.uint8)
            dilated_my_player_mask = cv2.dilate(my_player_mask, kernel, iterations=1); dilated_other_player_mask = cv2.dilate(other_player_mask, kernel, iterations=1)
            total_ignore_mask = cv2.bitwise_or(dilated_my_player_mask, dilated_other_player_mask)
            return cv2.inpaint(frame_bgr, total_ignore_mask, 3, cv2.INPAINT_TELEA) if np.any(total_ignore_mask) else frame_bgr

    def _get_next_feature_name(self):
        max_num = max([int(name[1:]) for name in self.key_features.keys() if name.startswith("P") and name[1:].isdigit()] or [0])
        return f"P{max_num + 1}"

    def waypoint_order_changed(self):
        if not self.active_route_profile_name: return

        current_route = self.route_profiles[self.active_route_profile_name]
        
        # 정방향 리스트에서 새 순서 가져오기
        new_forward_ids = [self.forward_wp_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.forward_wp_list.count())]
        current_route["forward_path"] = new_forward_ids
        
        # 역방향 리스트에서 새 순서 가져오기
        new_backward_ids = [self.backward_wp_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.backward_wp_list.count())]
        current_route["backward_path"] = new_backward_ids

        # --- v12.0.0 추가: 경로 변경 시 그래프 재생성 ---
        wp_ids = set(new_forward_ids + new_backward_ids)
        self._build_navigation_graph(list(wp_ids))
        # --- 추가 끝 ---

        self.save_profile_data()
        self.update_general_log("웨이포인트 순서가 변경되었습니다.", "SaddleBrown")
        # 순서 변경 후 목록을 다시 채워서 번호 업데이트
        self.populate_waypoint_list()

    def toggle_debug_view(self, checked):
        """디버그 뷰 체크박스의 상태에 따라 디버그 창을 표시하거나 숨깁니다."""
        # 탐지가 실행 중일 때만 동작하도록 함
        if not (self.detection_thread and self.detection_thread.isRunning()):
            if self.debug_dialog:
                self.debug_dialog.close()
            return
            
        if checked:
            if not self.debug_dialog:
                self.debug_dialog = DebugViewDialog(self)
            self.debug_dialog.show()
        else:
            if self.debug_dialog:
                self.debug_dialog.close()

    # [v11.0.0] AnchorDetectionThread에서 책임 이동된 메서드들
    def find_player_icon(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER)
        
        output = cv2.connectedComponentsWithStats(mask, 8, cv2.CV_32S)
        num_labels = output[0]
        stats = output[2]
        
        valid_rects = []
        for i in range(1, num_labels):
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            
            if (MIN_ICON_WIDTH <= w < MAX_ICON_WIDTH and
                MIN_ICON_HEIGHT <= h < MAX_ICON_HEIGHT):
                
                center_x = x + w / 2
                center_y = y + h / 2
                
                new_x = int(center_x - PLAYER_ICON_STD_WIDTH / 2)
                new_y = int(center_y - PLAYER_ICON_STD_HEIGHT / 2)
                
                valid_rects.append(QRect(new_x, new_y, PLAYER_ICON_STD_WIDTH, PLAYER_ICON_STD_HEIGHT))
                
        return valid_rects

    def find_other_player_icons(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1)
        mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
        mask = cv2.bitwise_or(mask1, mask2)
        
        output = cv2.connectedComponentsWithStats(mask, 8, cv2.CV_32S)
        num_labels = output[0]
        stats = output[2]
        
        valid_rects = []
        for i in range(1, num_labels):
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            
            if (MIN_ICON_WIDTH <= w < MAX_ICON_WIDTH and
                MIN_ICON_HEIGHT <= h < MAX_ICON_HEIGHT):
                
                center_x = x + w / 2
                center_y = y + h / 2
                
                new_x = int(center_x - PLAYER_ICON_STD_WIDTH / 2)
                new_y = int(center_y - PLAYER_ICON_STD_HEIGHT / 2)
                
                valid_rects.append(QRect(new_x, new_y, PLAYER_ICON_STD_WIDTH, PLAYER_ICON_STD_HEIGHT))
                
        return valid_rects

    def toggle_anchor_detection(self, checked):
            if checked:
                if not self.minimap_region:
                    QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요.")
                    self.detect_anchor_btn.setChecked(False)
                    return
                if not self.key_features:
                    QMessageBox.warning(self, "오류", "하나 이상의 '핵심 지형'을 등록해야 합니다.")
                    self.detect_anchor_btn.setChecked(False)
                    return
                if not self.full_map_pixmap or self.full_map_pixmap.isNull():
                    QMessageBox.warning(self, "오류", "전체 맵 이미지를 생성할 수 없습니다. 편집기를 통해 맵 데이터를 확인해주세요.")
                    self.detect_anchor_btn.setChecked(False)
                    return

                self.save_profile_data()
                self.general_log_viewer.clear()
                self.detection_log_viewer.clear()
                self.update_general_log("탐지를 시작합니다...", "SaddleBrown")

                # --- [v12.3.1] 모든 내비게이션 상태 변수 완벽 초기화 ---
                self.journey_plan = []
                self.current_journey_index = 0
                self.current_segment_path = []
                self.current_segment_index = 0
                # [수정] start_waypoint_found를 True로 변경하여 시작점 탐색 과정을 생략합니다.
                self.start_waypoint_found = True 
                self.navigation_action = 'move_to_target'
                self.navigation_state_locked = False
                self.last_reached_wp_id = None
                self.target_waypoint_id = None
                self.is_forward = True # 정방향으로 시작
                self.smoothed_player_pos = None
                self.last_player_pos = QPointF(0, 0)
                self.player_state = 'on_terrain'
                self.current_player_floor = None
                # --- 초기화 끝 ---

                if self.debug_view_checkbox.isChecked():
                    if not self.debug_dialog:
                        self.debug_dialog = DebugViewDialog(self)
                    self.debug_dialog.show()

                self.capture_thread = MinimapCaptureThread(self.minimap_region)
                self.capture_thread.start()

                self.detection_thread = AnchorDetectionThread(self.key_features, capture_thread=self.capture_thread, parent_tab=self)
                self.detection_thread.detection_ready.connect(self.on_detection_ready)
                self.detection_thread.status_updated.connect(self.update_detection_log_message)
                self.detection_thread.start()

                self.detect_anchor_btn.setText("탐지 중단")
            else:
                if self.detection_thread and self.detection_thread.isRunning():
                    self.detection_thread.stop()
                    self.detection_thread.wait()
                if self.capture_thread and self.capture_thread.isRunning():
                    self.capture_thread.stop()
                    self.capture_thread.wait()

                self.update_general_log("탐지를 중단합니다.", "black")
                self.detect_anchor_btn.setText("탐지 시작")
                self.update_detection_log_message("탐지 중단됨", "black")
                self.minimap_view_label.setText("탐지 중단됨")

                self.detection_thread = None
                self.capture_thread = None

                # --- [v12.3.1] 탐지 중지 시에도 상태 초기화 ---
                self.journey_plan = []
                self.current_journey_index = 0
                self.current_segment_path = []
                self.current_segment_index = 0
                self.start_waypoint_found = False
                self.navigation_action = 'move_to_target'
                self.navigation_state_locked = False
                self.last_reached_wp_id = None
                self.target_waypoint_id = None
                # --- 초기화 끝 ---

                if self.debug_dialog:
                    self.debug_dialog.close()
                    
    def _open_state_config_dialog(self):
        # 현재 설정값들을 딕셔너리로 만듦
        current_config = {
            "idle_time_threshold": self.cfg_idle_time_threshold,
            "climbing_state_frame_threshold": self.cfg_climbing_state_frame_threshold,
            "falling_state_frame_threshold": self.cfg_falling_state_frame_threshold,
            "jumping_state_frame_threshold": self.cfg_jumping_state_frame_threshold,
            "on_terrain_y_threshold": self.cfg_on_terrain_y_threshold,
            "jump_y_min_threshold": self.cfg_jump_y_min_threshold,
            "jump_y_max_threshold": self.cfg_jump_y_max_threshold,
            "fall_y_min_threshold": self.cfg_fall_y_min_threshold,
            "climb_x_movement_threshold": self.cfg_climb_x_movement_threshold,
            "fall_on_ladder_x_movement_threshold": self.cfg_fall_on_ladder_x_movement_threshold,
            "ladder_x_grab_threshold": self.cfg_ladder_x_grab_threshold,
            "move_deadzone": self.cfg_move_deadzone,
            "max_jump_duration": self.cfg_max_jump_duration,
            "y_movement_deadzone": self.cfg_y_movement_deadzone,
            "waypoint_arrival_x_threshold": self.cfg_waypoint_arrival_x_threshold,
            "ladder_arrival_x_threshold": self.cfg_ladder_arrival_x_threshold,
            "jump_link_arrival_x_threshold": self.cfg_jump_link_arrival_x_threshold,
            # ==================== v11.5.0 설정값 전달 추가 시작 ====================
            "arrival_frame_threshold": self.cfg_arrival_frame_threshold,
            "action_success_frame_threshold": self.cfg_action_success_frame_threshold,
            # ==================== v11.5.0 설정값 전달 추가 끝 ======================
        }
        
        dialog = StateConfigDialog(current_config, self)
        if dialog.exec(): # 사용자가 '저장'을 눌렀을 경우
            updated_config = dialog.get_updated_config()
            
            # 멤버 변수 업데이트
            self.cfg_idle_time_threshold = updated_config.get("idle_time_threshold", self.cfg_idle_time_threshold)
            self.cfg_climbing_state_frame_threshold = updated_config.get("climbing_state_frame_threshold", self.cfg_climbing_state_frame_threshold)
            self.cfg_falling_state_frame_threshold = updated_config.get("falling_state_frame_threshold", self.cfg_falling_state_frame_threshold)
            self.cfg_jumping_state_frame_threshold = updated_config.get("jumping_state_frame_threshold", self.cfg_jumping_state_frame_threshold)
            self.cfg_on_terrain_y_threshold = updated_config.get("on_terrain_y_threshold", self.cfg_on_terrain_y_threshold)
            self.cfg_jump_y_min_threshold = updated_config.get("jump_y_min_threshold", self.cfg_jump_y_min_threshold)
            self.cfg_jump_y_max_threshold = updated_config.get("jump_y_max_threshold", self.cfg_jump_y_max_threshold)
            self.cfg_fall_y_min_threshold = updated_config.get("fall_y_min_threshold", self.cfg_fall_y_min_threshold)
            self.cfg_climb_x_movement_threshold = updated_config.get("climb_x_movement_threshold", self.cfg_climb_x_movement_threshold)
            self.cfg_fall_on_ladder_x_movement_threshold = updated_config.get("fall_on_ladder_x_movement_threshold", self.cfg_fall_on_ladder_x_movement_threshold)
            self.cfg_ladder_x_grab_threshold = updated_config.get("ladder_x_grab_threshold", self.cfg_ladder_x_grab_threshold)
            self.cfg_move_deadzone = updated_config.get("move_deadzone", self.cfg_move_deadzone)
            self.cfg_max_jump_duration = updated_config.get("max_jump_duration", self.cfg_max_jump_duration)
            self.cfg_y_movement_deadzone = updated_config.get("y_movement_deadzone", self.cfg_y_movement_deadzone)
            self.cfg_waypoint_arrival_x_threshold = updated_config.get("waypoint_arrival_x_threshold", self.cfg_waypoint_arrival_x_threshold)
            self.cfg_ladder_arrival_x_threshold = updated_config.get("ladder_arrival_x_threshold", self.cfg_ladder_arrival_x_threshold)
            self.cfg_jump_link_arrival_x_threshold = updated_config.get("jump_link_arrival_x_threshold", self.cfg_jump_link_arrival_x_threshold)
            # ==================== v11.5.0 설정값 업데이트 추가 시작 ====================
            self.cfg_arrival_frame_threshold = updated_config.get("arrival_frame_threshold", self.cfg_arrival_frame_threshold)
            self.cfg_action_success_frame_threshold = updated_config.get("action_success_frame_threshold", self.cfg_action_success_frame_threshold)
            # ==================== v11.5.0 설정값 업데이트 추가 끝 ======================

            self.update_general_log("상태 판정 설정이 업데이트되었습니다.", "blue")
            self.save_profile_data() # 변경사항을 즉시 파일에 저장

    def on_detection_ready(self, frame_bgr, found_features, my_player_rects, other_player_rects):
        """
        [MODIFIED] RANSAC 변환 행렬의 안정성을 종합적으로 검사하고,
        모든 좌표 변환 단계에 안전장치를 추가하여 좌표 튐 현상을 방지합니다.
        데이터 전달 흐름을 명확히 하여 실시간 뷰 렌더링 오류를 수정합니다.
        """
        if not my_player_rects:
            self.update_detection_log_message("플레이어 아이콘 탐지 실패", "red")
            if self.debug_dialog and self.debug_dialog.isVisible():
                self.debug_dialog.update_debug_info(frame_bgr, {'all_features': found_features, 'inlier_ids': set(), 'player_pos_local': None})
            # [NEW] 캐릭터가 없으면 뷰 업데이트를 하지 않고 이전 상태를 유지
            return

        reliable_features = [f for f in found_features if f['id'] in self.key_features and f['conf'] >= self.key_features[f['id']].get('threshold', 0.85)]
        
        valid_features_map = {f['id']: f for f in reliable_features if f['id'] in self.global_positions}
        source_points = []
        dest_points = []
        feature_ids = []

        for fid, feature in valid_features_map.items():
            size = feature['size']
            local_pos = feature['local_pos']
            global_pos = self.global_positions[fid]
            
            src_cx = local_pos.x() + size.width() / 2
            src_cy = local_pos.y() + size.height() / 2
            dst_cx = global_pos.x() + size.width() / 2
            dst_cy = global_pos.y() + size.height() / 2
            source_points.append([src_cx, src_cy])
            dest_points.append([dst_cx, dst_cy])
            feature_ids.append(fid)

        player_anchor_local = QPointF(my_player_rects[0].center().x(), float(my_player_rects[0].bottom()) + PLAYER_Y_OFFSET)

        avg_player_global_pos = None
        inlier_ids = set()
        transform_matrix = None
        
        # --- 좌표 추정 로직 시작 ---
        if len(source_points) >= 3:
            src_pts, dst_pts = np.float32(source_points), np.float32(dest_points)
            matrix, inliers_mask = cv2.estimateAffinePartial2D(src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=5.0)

            if matrix is not None and inliers_mask is not None and np.sum(inliers_mask) >= 3:
                # [NEW] 변환 행렬 안정성 종합 검사
                sx = np.sqrt(matrix[0,0]**2 + matrix[1,0]**2)
                sy = np.sqrt(matrix[0,1]**2 + matrix[1,1]**2)
                # 스케일링, 회전, 이동값이 상식적인 범위 내에 있는지 확인
                if (0.8 < sx < 1.2 and 0.8 < sy < 1.2 and 
                    abs(matrix[0,1]) < 0.5 and abs(matrix[1,0]) < 0.5 and
                    abs(matrix[0,2]) < 10000 and abs(matrix[1,2]) < 10000):
                    transform_matrix = matrix
                    inliers_mask = inliers_mask.flatten()
                    for i, fid in enumerate(feature_ids):
                        if inliers_mask[i]:
                            inlier_ids.add(fid)
        
        # --- 전역 플레이어 위치 계산 (RANSAC 성공/실패 모두 처리) ---
        inlier_features = [valid_features_map[fid] for fid in inlier_ids] if inlier_ids else list(valid_features_map.values())
        
        if transform_matrix is not None:
            px, py = player_anchor_local.x(), player_anchor_local.y()
            transformed = (transform_matrix[:, :2] @ np.array([px, py])) + transform_matrix[:, 2]
            avg_player_global_pos = QPointF(float(transformed[0]), float(transformed[1]))
        elif inlier_features: # RANSAC 실패 시 폴백
            total_conf = sum(f['conf'] for f in inlier_features)
            if total_conf > 0:
                w_sum_x, w_sum_y = 0, 0
                for f in inlier_features:
                    offset = player_anchor_local - (f['local_pos'] + QPointF(f['size'].width()/2, f['size'].height()/2))
                    global_center = self.global_positions[f['id']] + QPointF(f['size'].width()/2, f['size'].height()/2)
                    pos = global_center + offset
                    w_sum_x += pos.x() * f['conf']
                    w_sum_y += pos.y() * f['conf']
                avg_player_global_pos = QPointF(w_sum_x / total_conf, w_sum_y / total_conf)

        if avg_player_global_pos is None:
            if self.smoothed_player_pos is not None:
                avg_player_global_pos = self.smoothed_player_pos
            else:
                self.update_detection_log_message("플레이어 전역 위치 추정 실패", "red")
                return

        # --- 스무딩 ---
        alpha = 0.3
        if self.smoothed_player_pos is None:
            self.smoothed_player_pos = avg_player_global_pos
        else:
            self.smoothed_player_pos = (avg_player_global_pos * alpha) + (self.smoothed_player_pos * (1 - alpha))
        final_player_pos = self.smoothed_player_pos
        
        # --- 아이콘들의 전역 좌표 계산 ---
        my_player_global_rects = []
        other_player_global_rects = []
        
        def transform_rect_safe(rect, matrix, fallback_features):
            if matrix is not None:
                corners = np.float32([[rect.left(), rect.top()], [rect.right(), rect.bottom()]]).reshape(-1, 1, 2)
                t_corners = cv2.transform(corners, matrix).reshape(2, 2)
                return QRectF(QPointF(t_corners[0,0], t_corners[0,1]), QPointF(t_corners[1,0], t_corners[1,1])).normalized()
            else:
                center_local = QPointF(rect.center())
                sum_pos, sum_conf = QPointF(0, 0), 0
                for f in fallback_features:
                    offset = center_local - (f['local_pos'] + QPointF(f['size'].width()/2, f['size'].height()/2))
                    global_center = self.global_positions[f['id']] + QPointF(f['size'].width()/2, f['size'].height()/2)
                    pos = global_center + offset
                    conf = f['conf']
                    sum_pos += pos * conf
                    sum_conf += conf
                
                if sum_conf > 0:
                    center_global = sum_pos / sum_conf
                    # [v12.2.0 BUGFIX] QSize를 QSizeF로 명시적으로 변환하여 TypeError 방지
                    return QRectF(center_global - QPointF(rect.width()/2, rect.height()/2), QSizeF(rect.size()))
                return QRectF()

        for rect in my_player_rects:
            my_player_global_rects.append(transform_rect_safe(rect, transform_matrix, inlier_features))
        for rect in other_player_rects:
            other_player_global_rects.append(transform_rect_safe(rect, transform_matrix, inlier_features))
        
        self.active_feature_info = inlier_features

        # --- 상태 및 뷰 업데이트 ---
        self._update_player_state_and_navigation(final_player_pos)

        if self.debug_dialog and self.debug_dialog.isVisible():
            debug_data = {
                'all_features': found_features, 'inlier_ids': inlier_ids, 'player_pos_local': player_anchor_local,
            }
            self.debug_dialog.update_debug_info(frame_bgr, debug_data)

        camera_pos_to_send = final_player_pos if self.center_on_player_checkbox.isChecked() else self.minimap_view_label.camera_center_global
        
        self.minimap_view_label.update_view_data(
            camera_center=camera_pos_to_send,
            active_features=self.active_feature_info,
            my_players=my_player_global_rects,
            other_players=other_player_global_rects,
            target_wp_id=self.target_waypoint_id,
            reached_wp_id=self.last_reached_wp_id,
            final_player_pos=final_player_pos,
            is_forward=self.is_forward,
            intermediate_pos=self.intermediate_target_pos,
            intermediate_type=self.intermediate_target_type,
            nav_action=self.navigation_action
        )
        self.global_pos_updated.emit(final_player_pos)
        
        outlier_list = [f for f in reliable_features if f['id'] not in inlier_ids]
        self.update_detection_log_from_features(inlier_features, outlier_list)

    def _generate_full_map_pixmap(self):
        """
        v10.0.0: 모든 핵심 지형의 문맥 이미지를 합성하여 하나의 큰 배경 지도 QPixmap을 생성하고,
        모든 맵 요소의 전체 경계를 계산하여 저장합니다.
        [MODIFIED] 비정상적인 좌표값으로 인해 경계가 무한히 확장되는 것을 방지하는 안전장치를 추가합니다.
        """
        if not self.global_positions:
            self.full_map_pixmap = None
            self.full_map_bounding_rect = QRectF()
            return

        all_items_rects = []
        
        # 1. 핵심 지형의 문맥 이미지를 기준으로 경계 계산
        for feature_id, feature_data in self.key_features.items():
            context_pos_key = f"{feature_id}_context"
            if context_pos_key in self.global_positions:
                context_origin = self.global_positions[context_pos_key]
                # [NEW] 비정상적인 좌표값 필터링
                if abs(context_origin.x()) > 1e6 or abs(context_origin.y()) > 1e6:
                    self.update_general_log(f"경고: 비정상적인 문맥 원점 좌표({context_pos_key})가 감지되어 경계 계산에서 제외합니다.", "orange")
                    continue
                
                if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
                    try:
                        img_data = base64.b64decode(feature_data['context_image_base64'])
                        pixmap = QPixmap(); pixmap.loadFromData(img_data)
                        if not pixmap.isNull():
                            all_items_rects.append(QRectF(context_origin, QSizeF(pixmap.size())))
                    except Exception as e:
                        print(f"문맥 이미지 로드 오류 (ID: {feature_id}): {e}")
        
        # 2. 지형선, 오브젝트 등의 경계도 포함
        all_points = []
        for line in self.geometry_data.get("terrain_lines", []): all_points.extend(line.get("points", []))
        for obj in self.geometry_data.get("transition_objects", []): all_points.extend(obj.get("points", []))
        
        if all_points:
            # [NEW] 비정상적인 지형 좌표 필터링
            valid_points = [p for p in all_points if abs(p[0]) < 1e6 and abs(p[1]) < 1e6]
            if valid_points:
                xs = [p[0] for p in valid_points]
                ys = [p[1] for p in valid_points]
                all_items_rects.append(QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))

        if not all_items_rects:
            self.full_map_pixmap = QPixmap(100, 100)
            self.full_map_pixmap.fill(QColor(50, 50, 50))
            self.full_map_bounding_rect = QRectF(0, 0, 100, 100)
            self.update_general_log("배경 지도 생성 실패: 유효한 그리기 요소가 없습니다. 기본 맵을 생성합니다.", "orange")
            return

        # 3. 모든 유효한 경계를 합쳐 최종 경계 계산
        bounding_rect = QRectF()
        for rect in all_items_rects:
            if bounding_rect.isNull():
                bounding_rect = rect
            else:
                bounding_rect = bounding_rect.united(rect)

        # [NEW] 최종 경계 크기 제한 (안전장치)
        MAX_DIMENSION = 20000 # 씬의 최대 크기를 20000px로 제한
        if bounding_rect.width() > MAX_DIMENSION or bounding_rect.height() > MAX_DIMENSION:
            self.update_general_log(f"경고: 계산된 맵 경계({bounding_rect.size().toSize()})가 너무 큽니다. 최대 크기로 제한합니다.", "red")
            bounding_rect = QRectF(
                bounding_rect.x(), bounding_rect.y(),
                min(bounding_rect.width(), MAX_DIMENSION),
                min(bounding_rect.height(), MAX_DIMENSION)
            )

        bounding_rect.adjust(-50, -50, 50, 50)
        self.full_map_bounding_rect = bounding_rect

        # 이하 픽스맵 생성 및 그리기는 기존과 동일
        self.full_map_pixmap = QPixmap(bounding_rect.size().toSize())
        self.full_map_pixmap.fill(QColor(50, 50, 50))
        
        painter = QPainter(self.full_map_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(-bounding_rect.topLeft())

        if self.render_options.get('background', True):
            painter.setOpacity(0.7)
            for feature_id, feature_data in self.key_features.items():
                context_pos_key = f"{feature_id}_context"
                if context_pos_key in self.global_positions:
                    context_origin = self.global_positions[context_pos_key]
                    if abs(context_origin.x()) > 1e6 or abs(context_origin.y()) > 1e6: continue # 렌더링에서도 제외

                    if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
                        try:
                            img_data = base64.b64decode(feature_data['context_image_base64'])
                            pixmap = QPixmap(); pixmap.loadFromData(img_data)
                            if not pixmap.isNull():
                                painter.drawPixmap(context_origin, pixmap)
                        except Exception as e:
                            print(f"문맥 이미지 그리기 오류 (ID: {feature_id}): {e}")
        
        painter.end()
        self.update_general_log(f"배경 지도 이미지 생성 완료. (크기: {self.full_map_pixmap.width()}x{self.full_map_pixmap.height()})", "green")
      
    def _calculate_content_bounding_rect(self):
        """현재 맵의 모든 시각적 요소(지형, 오브젝트 등)를 포함하는 전체 경계를 계산합니다."""
        if not self.global_positions and not self.geometry_data:
            return QRectF()

        content_rect = QRectF()
        
        # 1. 핵심 지형의 경계 계산
        for feature_id, pos in self.global_positions.items():
            if feature_id in self.key_features:
                feature_data = self.key_features[feature_id]
                size_data = feature_data.get('size')
                if size_data and len(size_data) == 2:
                    size = QSizeF(size_data[0], size_data[1])
                    feature_rect = QRectF(pos, size)
                    content_rect = content_rect.united(feature_rect)

        # 2. 모든 지오메트리 포인트 수집
        all_points = []
        for line in self.geometry_data.get("terrain_lines", []):
            all_points.extend(line.get("points", []))
        for obj in self.geometry_data.get("transition_objects", []):
            all_points.extend(obj.get("points", []))
        for wp in self.geometry_data.get("waypoints", []):
            all_points.append(wp.get("pos", [0, 0]))
        for jump in self.geometry_data.get("jump_links", []):
            all_points.append(jump.get("start_vertex_pos", [0, 0]))
            all_points.append(jump.get("end_vertex_pos", [0, 0]))

        # 3. 지오메트리 포인트들의 경계 계산 및 통합
        if all_points:
            min_x = min(p[0] for p in all_points)
            max_x = max(p[0] for p in all_points)
            min_y = min(p[1] for p in all_points)
            max_y = max(p[1] for p in all_points)
            geometry_rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
            content_rect = content_rect.united(geometry_rect)
            
        return content_rect

    def _center_realtime_view_on_map(self):
        """실시간 미니맵 뷰를 맵 콘텐츠의 중앙으로 이동시킵니다."""
        content_rect = self._calculate_content_bounding_rect()
        if not content_rect.isNull():
            center_point = content_rect.center()
            self.minimap_view_label.camera_center_global = center_point
            self.minimap_view_label.update() # 뷰 갱신

    def _calculate_path_cost(self, start_pos, start_floor, target_wp_data, all_transition_objects):
        """
        시작 위치/층에서 목표 웨이포인트까지의 예상 이동 비용(x축 거리)을 계산합니다.
        상승 시에는 층 이동 오브젝트를 경유하는 비용을 누적합니다.
        """
        target_pos = QPointF(target_wp_data['pos'][0], target_wp_data['pos'][1])
        target_floor = target_wp_data['floor']
        
        if start_floor == target_floor:
            # 같은 층: 직선 x축 거리
            return abs(start_pos.x() - target_pos.x())
        
        elif start_floor < target_floor:
            # 올라가야 할 때: 층별로 경유 비용 누적
            total_cost = 0
            current_pos_x = start_pos.x()
            
            # 한 층씩 올라가며 비용 계산
            for floor_level in range(int(start_floor), int(target_floor)):
                next_floor_level = floor_level + 1
                
                # 다음 층(next_floor_level)에 있는 층 이동 오브젝트들을 찾음
                candidate_objects = [obj for obj in all_transition_objects if obj.get('floor') == next_floor_level]
                
                if not candidate_objects:
                    return float('inf') # 올라갈 방법이 없으면 비용 무한대

                # 현재 위치에서 가장 가까운 층 이동 오브젝트 찾기
                closest_obj = min(candidate_objects, key=lambda obj: abs(current_pos_x - obj['points'][0][0]))
                closest_obj_x = closest_obj['points'][0][0]
                
                # 현재 위치에서 오브젝트까지 가는 비용 추가
                total_cost += abs(current_pos_x - closest_obj_x)
                # 위치를 오브젝트 위치로 갱신
                current_pos_x = closest_obj_x

            # 마지막 오브젝트 위치에서 최종 목표 웨이포인트까지의 비용 추가
            total_cost += abs(current_pos_x - target_pos.x())
            return total_cost
        
        else: # start_floor > target_floor
            # 내려가야 할 때: 단순 x축 거리 (낙하 가능)
            return abs(start_pos.x() - target_pos.x())

    def _calculate_total_cost(self, start_pos, final_target_wp, intermediate_candidate):
        """
        v10.7.0: "현재 위치 -> 중간 목표 -> 최종 목표"의 총 이동 비용을 계산합니다.
        비용 = (Cost1: 중간 목표까지 x거리) + (Cost2: 중간 목표 통과 비용) + (Cost3: 중간 목표 이후 x거리)
        """
        if not final_target_wp or not intermediate_candidate:
            return float('inf')

        final_target_pos = QPointF(final_target_wp['pos'][0], final_target_wp['pos'][1])
        total_cost = 0
        
        candidate_type = intermediate_candidate['type']
        
        # --- Cost1: 현재 위치 -> 중간 목표 진입점 ---
        entry_point = intermediate_candidate['entry_point']
        total_cost += abs(start_pos.x() - entry_point.x())

        # --- Cost2 & Cost3 계산을 위한 탈출점 및 다음 시작점 설정 ---
        exit_point = None
        
        if candidate_type == 'walk':
            # walk는 중간 목표가 최종 목표이므로, Cost2와 Cost3는 0입니다.
            return total_cost

        elif candidate_type == 'climb':
            obj = intermediate_candidate['object']
            p1_y, p2_y = obj['points'][0][1], obj['points'][1][1]
            # Cost2: 오브젝트 통과 비용 (수직 이동 거리)
            total_cost += abs(p1_y - p2_y)
            # 탈출점은 오브젝트의 위쪽 끝
            exit_y = min(p1_y, p2_y)
            exit_point = QPointF(obj['points'][0][0], exit_y)

        elif candidate_type == 'fall':
            # Cost2: 낙하 비용은 0
            # 탈출점은 낙하 지점과 동일한 x좌표를 가지지만, 목표 층의 지형 위에 있음
            fall_point = intermediate_candidate['entry_point']
            target_floor = final_target_wp.get('floor')
            
            # 목표 층에서 낙하 지점 바로 아래의 지형 찾기 (y좌표 결정 위함)
            # 이 로직은 단순화를 위해 일단 x좌표만 같다고 가정. 추후 더 정교화 가능.
            exit_point = QPointF(fall_point.x(), final_target_pos.y()) # 임시로 최종 목표의 y 사용

        elif candidate_type == 'jump':
            link = intermediate_candidate['link']
            # Cost2: 점프 링크 통과 비용 (x축 거리)
            total_cost += abs(link['start_vertex_pos'][0] - link['end_vertex_pos'][0])
            exit_point = intermediate_candidate['exit_point']

        # --- Cost3: 중간 목표 탈출점 -> 최종 목표 ---
        if exit_point:
            total_cost += abs(exit_point.x() - final_target_pos.x())
        else:
            # 탈출점이 없는 경우는 오류 상황이므로 비용을 무한대로 처리
            return float('inf')

        return total_cost

    def _determine_player_physical_state(self, final_player_pos, contact_terrain):
        """플레이어의 물리적 상태(걷기, 점프 등)를 판정합니다."""
        previous_state = self.player_state
        x_movement = final_player_pos.x() - self.last_player_pos.x()
        y_movement = self.last_player_pos.y() - final_player_pos.y()
        
        if abs(x_movement) > self.cfg_move_deadzone or abs(y_movement) > self.cfg_move_deadzone:
            self.last_movement_time = time.time()

        new_state = previous_state
        if (time.time() - self.last_movement_time) >= self.cfg_idle_time_threshold:
            new_state = 'idle'
        elif contact_terrain:
            new_state = 'on_terrain'
            self.last_on_terrain_y = final_player_pos.y()
            self.in_jump = False
        else: # 공중 상태
            y_above_terrain = self.last_on_terrain_y - final_player_pos.y()
            is_near_ladder, _, _ = self._check_near_ladder(final_player_pos, self.geometry_data.get("transition_objects", []), self.cfg_ladder_x_grab_threshold, return_dist=True, current_floor=self.current_player_floor)
            
            if self.in_jump:
                if y_above_terrain > self.cfg_jump_y_max_threshold and is_near_ladder: new_state = 'climbing'
                elif y_above_terrain < -self.cfg_fall_y_min_threshold: new_state = 'falling'
                else: new_state = 'jumping'
            else:
                if y_movement > self.cfg_y_movement_deadzone and y_above_terrain > self.cfg_jump_y_min_threshold:
                    new_state = 'jumping'; self.in_jump = True; self.jump_start_time = time.time()
                elif is_near_ladder and abs(y_movement) > self.cfg_y_movement_deadzone:
                    new_state = 'climbing'
                else:
                    new_state = 'falling'
        
        if self.in_jump and (time.time() - self.jump_start_time) > self.cfg_max_jump_duration:
            self.in_jump = False
            if new_state == 'jumping': new_state = 'falling'
        
        return new_state

    def _plan_next_journey(self, active_route):
        """다음 여정을 계획하고 경로 순환 로직을 처리합니다."""
        self.is_forward = not self.is_forward
        path_key = "forward_path" if self.is_forward else "backward_path"
        next_journey = active_route.get(path_key, [])
        if not next_journey and not self.is_forward:
            next_journey = list(reversed(active_route.get("forward_path", [])))

        if not next_journey:
            self.update_general_log("경로 완주. 순환할 경로가 없습니다.", "green")
            self.journey_plan = []
            self.target_waypoint_id = None
            # [수정] 여정이 없으면 start_waypoint_found를 False로 설정
            self.start_waypoint_found = False 
        else:
            self.journey_plan = next_journey
            self.current_journey_index = 0
            # [수정] 새 여정이 시작되므로 start_waypoint_found를 True로 명시적 설정
            self.start_waypoint_found = True 
            direction_text = "정방향" if self.is_forward else "역방향"
            self.update_general_log(f"새로운 여정을 시작합니다. ({direction_text})", "purple")
            print(f"[INFO] 새 여정 계획: {[self.nav_nodes.get(f'wp_{wp_id}', {}).get('name', '??') for wp_id in self.journey_plan]}")

    def _calculate_segment_path(self, final_player_pos):
        """
        [v12.8.1 수정] 플레이어의 실제 위치를 가상 시작 노드로 사용하여 A* 탐색을 수행합니다.
        """
        current_terrain = self._get_contact_terrain(final_player_pos)
        if not current_terrain:
            # 이전에 계산된 경로가 있다면, 잠시 지형을 벗어난 것일 수 있으므로 즉시 경로를 파기하지 않음
            # 단, 새로운 여정을 시작해야 하는 경우는 예외
            if not self.current_segment_path:
                self.update_general_log("경로 계산 실패: 현재 지형을 파악할 수 없습니다.", "red")
                self.journey_plan = []
            return

        start_group = current_terrain.get('dynamic_name')
        if not self.journey_plan or self.current_journey_index >= len(self.journey_plan):
            return

        goal_wp_id = self.journey_plan[self.current_journey_index]
        self.target_waypoint_id = goal_wp_id
        goal_node_key = f"wp_{goal_wp_id}"

        # A* 탐색에 플레이어의 실제 위치와 그룹을 전달
        path, cost = self._find_path_astar(final_player_pos, start_group, goal_node_key)
        
        if path:
            self.current_segment_path = path
            self.current_segment_index = 0
            
            start_name = "현재 위치"
            goal_name = self.nav_nodes.get(goal_node_key, {}).get('name', '??')
            log_msg = f"[경로 탐색 성공] '{start_name}' -> '{goal_name}' (총 비용: {cost:.1f})"
            path_str = " -> ".join([self.nav_nodes.get(p, {}).get('name', '??') for p in path])
            log_msg += f"\n[상세 경로] {path_str}"
            print(log_msg)
            self.update_general_log(log_msg.replace('\n', '<br>'), 'SaddleBrown')
            self.last_path_recalculation_time = time.time()
        else:
            start_name = "현재 위치"
            goal_name = self.nav_nodes.get(goal_node_key, {}).get('name', '??')
            log_msg = f"[경로 탐색 실패] '{start_name}' -> '{goal_name}'"
            log_msg += f"\n[진단] 시작 지형 그룹과 목표 지점이 그래프 상에서 연결되어 있지 않습니다."
            print(log_msg)
            self.update_general_log(log_msg.replace('\n', '<br>'), 'red')
            # 경로 계산 실패 시 현재 여정을 중단하여 무한 재시도를 방지
            self.journey_plan = []

    def _get_arrival_threshold(self, node_type):
        """노드 타입에 맞는 도착 판정 임계값을 반환합니다."""
        if node_type == 'ladder_entry':
            return self.cfg_ladder_arrival_x_threshold
        elif node_type in ['jump_vertex', 'fall_start', 'djump_area']:
            return self.cfg_jump_link_arrival_x_threshold
        return self.cfg_waypoint_arrival_x_threshold

    def _transition_to_action_state(self, new_action_state, prev_node_key):
        """주어진 액션 준비 상태로 전환합니다."""
        if self.navigation_action == new_action_state: return
        self.navigation_action = new_action_state
        self.prepare_timeout_start = time.time()
        prev_node_name = self.nav_nodes.get(prev_node_key, {}).get('name', '??')
        print(f"[상태 변경] '{prev_node_name}' 도착 -> {self.navigation_action}")
        self.update_general_log(f"'{prev_node_name}' 도착. 다음 행동 준비.", "blue")

    def _process_action_preparation(self, final_player_pos):
        """'prepare_to_...' 상태일 때, 이탈 또는 액션 시작을 판정합니다."""
        # 액션 시작점은 항상 현재 세그먼트 인덱스
        action_node_key = self.current_segment_path[self.current_segment_index]
        action_node = self.nav_nodes.get(action_node_key, {})
        action_node_pos = action_node.get('pos')
        if not action_node_pos: return

        # 1. 액션 시작 판정
        action_started = False
        if self.navigation_action == 'prepare_to_climb' and self.player_state == 'climbing': action_started = True
        elif self.navigation_action == 'prepare_to_jump' and self.player_state == 'jumping': action_started = True
        elif self.navigation_action == 'prepare_to_fall' and self.player_state == 'falling': action_started = True
        elif self.navigation_action == 'prepare_to_down_jump' and self.player_state in ['jumping', 'falling']:
            if final_player_pos.y() > self.last_on_terrain_y + self.cfg_y_movement_deadzone:
                action_started = True
        
        if action_started:
            self.navigation_action = self.navigation_action.replace('prepare_to_', '') + '_in_progress'
            self.navigation_state_locked = True
            self.lock_timeout_start = time.time()
            print(f"[INFO] 행동 시작 감지. 상태 잠금 -> {self.navigation_action}")
            return

        # 2. 이탈 판정
        recalc_cooldown = 1.0
        if time.time() - self.last_path_recalculation_time > recalc_cooldown:
            is_off_course = False
            arrival_threshold = self._get_arrival_threshold(action_node.get('type'))
            exit_threshold = arrival_threshold + HYSTERESIS_EXIT_OFFSET

            if self.navigation_action == 'prepare_to_down_jump':
                x_range = action_node.get('x_range')
                if x_range and not (x_range[0] - exit_threshold <= final_player_pos.x() <= x_range[1] + exit_threshold):
                    is_off_course = True
            elif self.navigation_action == 'prepare_to_jump':
                dist_x = abs(final_player_pos.x() - action_node_pos.x())
                dist_y = abs(final_player_pos.y() - action_node_pos.y())
                if dist_x > exit_threshold or dist_y > 20.0:
                    is_off_course = True
            else: # climb, fall
                dist_x = abs(final_player_pos.x() - action_node_pos.x())
                if dist_x > exit_threshold:
                    is_off_course = True
            
            if is_off_course:
                self.update_general_log(f"[경로 이탈 감지] 행동 준비 중 목표에서 벗어났습니다. 경로를 다시 계산합니다.", "orange")
                print(f"[INFO] 경로 이탈 감지. 목표: {self.guidance_text}")
                self.current_segment_path = []
                self.navigation_action = 'move_to_target'
    
    def _process_action_completion(self, final_player_pos, contact_terrain):
        """액션의 완료 또는 실패를 판정하고 상태를 처리합니다."""
        action_completed = False
        action_failed = False
        
        # 예상 도착 지형 그룹 찾기
        expected_group = None
        if self.current_segment_index < len(self.current_segment_path):
            current_node_key = self.current_segment_path[self.current_segment_index]
            
            # 액션 간선을 찾아 target_group을 가져옴
            if 'action' in self.navigation_action:
                for edge_data in self.nav_graph.get(current_node_key, {}).values():
                    if 'target_group' in edge_data:
                        expected_group = edge_data['target_group']
                        break
            # 일반 점프/사다리는 다음 노드의 그룹이 목표 그룹
            elif self.current_segment_index + 1 < len(self.current_segment_path):
                 next_node_key = self.current_segment_path[self.current_segment_index + 1]
                 expected_group = self.nav_nodes.get(next_node_key, {}).get('group')

        if expected_group and contact_terrain and contact_terrain.get('dynamic_name') != expected_group:
            action_failed = True
        
        elif self.navigation_action == 'climb_in_progress':
            if self.intermediate_target_pos:
                dist_x = abs(final_player_pos.x() - self.intermediate_target_pos.x())
                dist_y = abs(final_player_pos.y() - self.intermediate_target_pos.y())
                if dist_y < self.cfg_on_terrain_y_threshold * 2 and dist_x < self.cfg_ladder_arrival_x_threshold:
                    action_completed = True
        else:
            action_completed = True

        if action_failed:
            self.update_general_log(f"행동({self.navigation_action}) 실패. 예상 경로를 벗어났습니다. 경로를 재탐색합니다.", "orange")
            print(f"[INFO] 행동 실패: {self.navigation_action}, 예상 그룹: {expected_group}, 현재 그룹: {contact_terrain.get('dynamic_name')}")
            self.navigation_action = 'move_to_target'
            self.navigation_state_locked = False
            self.current_segment_path = []
            self.expected_terrain_group = None # 실패 시 예상 그룹 초기화

        elif action_completed:
            action_name = self.navigation_action # 로그용으로 저장
            # --- [새로운 부분 시작: 상태 전이 및 맥락 갱신] ---
            # 1. 상태를 정상 '걷기' 모드로 전환
            self.navigation_action = 'move_to_target'
            self.navigation_state_locked = False
            
            # 2. 경로의 다음 단계로 진행
            self.current_segment_index += 1
            
            # 3. 다음 안내를 위한 새로운 '예상 지형 그룹'을 즉시 설정
            if self.current_segment_index < len(self.current_segment_path):
                next_node_key = self.current_segment_path[self.current_segment_index]
                next_node = self.nav_nodes.get(next_node_key, {})
                self.expected_terrain_group = next_node.get('group')
                log_message = f"행동({action_name}) 완료. 다음 목표 그룹: '{self.expected_terrain_group}'"
                print(f"[INFO] {log_message}")
                self.update_general_log(log_message, "green")
            else:
                # 현재 구간의 마지막 단계였다면 예상 그룹을 초기화
                self.expected_terrain_group = None
                log_message = f"행동({action_name}) 완료. 현재 구간 종료."
                print(f"[INFO] {log_message}")
                self.update_general_log(log_message, "green")

    def _update_player_state_and_navigation(self, final_player_pos):
        """
        v12.7.0: [수정] 경로 이탈 판정 로직을 폐기하고,
        목표에서 일정 거리 이상 멀어졌을 때만 경로를 재탐색하는 방식으로 변경.
        """
        current_terrain_name = ""
        contact_terrain = self._get_contact_terrain(final_player_pos)
        
        if contact_terrain:
            self.current_player_floor = contact_terrain.get('floor')
            current_terrain_name = contact_terrain.get('dynamic_name', '')
        
        if final_player_pos is None or self.current_player_floor is None:
            self.navigator_display.update_data("N/A", "", "없음", "", "", "-", 0, [], None, None, self.is_forward, 'walk', "대기 중", "오류: 위치/층 정보 없음")
            return
        
        # Phase 0: 타임아웃 (유지)
        if (self.navigation_state_locked and (time.time() - self.lock_timeout_start > MAX_LOCK_DURATION)) or \
           (self.navigation_action.startswith('prepare_to_') and (time.time() - self.prepare_timeout_start > PREPARE_TIMEOUT)):
            self.update_general_log(f"경고: 행동({self.navigation_action}) 시간 초과. 경로를 재탐색합니다.", "orange")
            self.navigation_action = 'move_to_target'
            self.navigation_state_locked = False
            self.current_segment_path = [] # 경로 초기화하여 재탐색 유도
        
        # Phase 1: 물리적 상태 판정 (유지)
        self.player_state = self._determine_player_physical_state(final_player_pos, contact_terrain)

        # Phase 2: 행동 완료/실패 판정 (유지)
        if self.navigation_state_locked and self.player_state == 'on_terrain':
            self._process_action_completion(final_player_pos, contact_terrain)

        # --- [새로운 경로 관리 로직] ---
        # Phase 3: 경로 계획 및 재탐색 트리거
        active_route = self.route_profiles.get(self.active_route_profile_name)
        if not active_route: self.last_player_pos = final_player_pos; return

        # 3a. 전체 여정이 없거나 끝났으면 새로 계획
        if not self.journey_plan or self.current_journey_index >= len(self.journey_plan):
            self._plan_next_journey(active_route)
        
        # 3b. (핵심 수정) 맥락(Context) 기반 재탐색 트리거
        #    'move_to_target' 상태에서, 예상된 지형 그룹을 벗어났을 때만 재탐색
        RECALCULATION_COOLDOWN = 1.0 # 최소 1초의 재탐색 대기시간
        
        if (self.navigation_action == 'move_to_target' and 
            self.expected_terrain_group is not None and
            contact_terrain and
            contact_terrain.get('dynamic_name') != self.expected_terrain_group and
            time.time() - self.last_path_recalculation_time > RECALCULATION_COOLDOWN):
            
            print(f"[INFO] 경로 재탐색: 예상 지형 그룹('{self.expected_terrain_group}')을 벗어났습니다. (현재: '{contact_terrain.get('dynamic_name')}')")
            self.update_general_log("예상 경로를 벗어나 재탐색합니다.", "orange")
            self.current_segment_path = []      # 재탐색 유도
            self.expected_terrain_group = None  # 예상 그룹 초기화

        # 3c. 상세 구간 경로가 없으면 새로 계산
        if self.journey_plan and self.start_waypoint_found and not self.current_segment_path:
            self._calculate_segment_path(final_player_pos)

        # Phase 4: 상태에 따른 핵심 로직 처리 (유지)
        if self.navigation_state_locked:
            self._handle_action_in_progress(final_player_pos)
        elif self.navigation_action.startswith('prepare_to_'):
            self._handle_action_preparation(final_player_pos)
        else: # move_to_target
            self._handle_move_to_target(final_player_pos)

        # Phase 5: UI 업데이트 (유지)
        self._update_navigator_and_view(final_player_pos, current_terrain_name)
        self.last_player_pos = final_player_pos

    def _update_navigator_and_view(self, final_player_pos, current_terrain_name):
        """
        [v12.4.5] 계산된 모든 상태를 기반으로 UI 위젯들을 업데이트합니다.
        목표가 실제 웨이포인트인지 경유지인지 구분하여 안내 정확도를 높입니다.
        """
        all_waypoints_map = {wp['id']: wp for wp in self.geometry_data.get("waypoints", [])}
        prev_name, next_name, direction, distance = "", "", "-", 0
        
        if self.intermediate_target_pos:
            if self.navigation_action == 'prepare_to_down_jump':
                distance = abs(final_player_pos.y() - self.intermediate_target_pos.y())
                direction = "↓"
            else:
                distance = abs(final_player_pos.x() - self.intermediate_target_pos.x())
                direction = "→" if final_player_pos.x() < self.intermediate_target_pos.x() else "←"

        if self.start_waypoint_found and self.journey_plan:
            if self.current_journey_index > 0:
                prev_wp_id = self.journey_plan[self.current_journey_index - 1]
                prev_name = all_waypoints_map.get(prev_wp_id, {}).get('name', '')
            if self.current_journey_index < len(self.journey_plan) - 1:
                next_wp_id = self.journey_plan[self.current_journey_index + 1]
                next_name = all_waypoints_map.get(next_wp_id, {}).get('name', '')

        state_text_map = {'idle': '정지', 'on_terrain': '걷기', 'climbing': '오르기', 'falling': '내려가기', 'jumping': '점프 중'}
        action_text_map = {
            'move_to_target': "다음 목표로 이동",
            'prepare_to_climb': "점프+↑+방향키를 눌러 오르세요",
            'prepare_to_fall': "낭떠러지로 떨어지세요",
            'prepare_to_down_jump': "아래로 점프하세요",
            'prepare_to_jump': "점프하세요",
            'climb_in_progress': "오르는 중...",
            'fall_in_progress': "낙하 중...",
            'jump_in_progress': "점프 중...",
        }
        player_state_text = state_text_map.get(self.player_state, '알 수 없음')
        nav_action_text = action_text_map.get(self.navigation_action, '대기 중')
        
        # [v12.4.5] 중간 목표 타입 결정 로직 수정
        final_intermediate_type = 'walk' # 기본값
        if self.current_segment_path and self.current_segment_index < len(self.current_segment_path):
            current_node_key = self.current_segment_path[self.current_segment_index]
            current_node_type = self.nav_nodes.get(current_node_key, {}).get('type')

            if self.navigation_action.startswith('prepare_to_') or self.navigation_action.endswith('_in_progress'):
                if 'climb' in self.navigation_action: final_intermediate_type = 'climb'
                elif 'jump' in self.navigation_action: final_intermediate_type = 'jump'
                elif 'fall' in self.navigation_action or 'down_jump' in self.navigation_action: final_intermediate_type = 'fall'
            elif current_node_type != 'waypoint':
                # 걷기 상태이지만, 목표가 WP가 아닌 경유지(사다리 입구 등)인 경우
                final_intermediate_type = 'via_point'
        
        self.intermediate_target_type = final_intermediate_type # 내부 상태도 갱신

        self.navigator_display.update_data(
            floor=self.current_player_floor if self.current_player_floor is not None else "N/A",
            terrain_name=current_terrain_name,
            target_name=self.guidance_text,
            prev_name=prev_name, next_name=next_name, direction=direction, distance=distance,
            full_path=self.journey_plan, last_reached_id=self.last_reached_wp_id,
            target_id=self.target_waypoint_id, is_forward=self.is_forward,
            intermediate_type=self.intermediate_target_type, player_state=player_state_text,
            nav_action=nav_action_text
        )
        
        camera_pos_to_send = final_player_pos if self.center_on_player_checkbox.isChecked() else self.minimap_view_label.camera_center_global
        self.minimap_view_label.update_view_data(
            camera_center=camera_pos_to_send, active_features=self.active_feature_info,
            my_players=self.my_player_global_rects, other_players=self.other_player_global_rects,
            target_wp_id=self.target_waypoint_id, reached_wp_id=self.last_reached_wp_id,
            final_player_pos=final_player_pos, is_forward=self.is_forward,
            intermediate_pos=self.intermediate_target_pos,
            intermediate_type=self.intermediate_target_type, # 수정된 타입을 전달
            nav_action=self.navigation_action
        )
        
    def _handle_move_to_target(self, final_player_pos):
        """
        v12.8.6: [수정] '낭떠러지' 또는 '아래 점프' 지점 도착 시, 다음 경로를 확인하기 전에 먼저 해당 노드의 타입을 확인하고 즉시 행동 준비 상태로 전환하도록 수정하여 경로 실행 오류를 해결합니다.
        'move_to_target' 상태일 때의 도착 판정, 상태 전환, 이탈 판정을 처리합니다.
        """
        if not (self.current_segment_path and self.current_segment_index < len(self.current_segment_path)):
            self.expected_terrain_group = None
            return

        current_node_key = self.current_segment_path[self.current_segment_index]
        current_node = self.nav_nodes.get(current_node_key, {})
        self.intermediate_target_pos = current_node.get('pos')
        self.guidance_text = current_node.get('name', '')
        self.expected_terrain_group = current_node.get('group') 

        if not self.intermediate_target_pos: return

        # 도착 판정
        arrival_threshold = self._get_arrival_threshold(current_node.get('type'))
        target_floor = current_node.get('floor')
        floor_matches = target_floor is None or abs(self.current_player_floor - target_floor) < 0.1
        
        arrived = False
        if current_node.get('type') == 'djump_area':
            x_range = current_node.get('x_range')
            if x_range and x_range[0] <= final_player_pos.x() <= x_range[1] and floor_matches:
                arrived = True
        else: # 일반 노드 (waypoint, ladder_entry, fall_start 등)
            distance_to_target = abs(final_player_pos.x() - self.intermediate_target_pos.x())
            if distance_to_target < arrival_threshold and floor_matches:
                arrived = True

        if arrived:
            print(f"[INFO] 중간 목표 '{self.guidance_text}' 도착.")

            # --- [v12.8.6 수정] 도착한 노드의 타입에 따라 즉시 행동 준비 상태로 전환 ---
            node_type = current_node.get('type')
            if node_type == 'fall_start':
                self._transition_to_action_state('prepare_to_fall', current_node_key)
                return
            elif node_type == 'djump_area':
                self._transition_to_action_state('prepare_to_down_jump', current_node_key)
                return
            # --- 수정 끝 ---
            
            next_index = self.current_segment_index + 1
            if next_index >= len(self.current_segment_path):
                # 구간 완료
                self.last_reached_wp_id = self.journey_plan[self.current_journey_index]
                self.current_journey_index += 1
                self.current_segment_path = []
                self.expected_terrain_group = None
                wp_name = self.nav_nodes.get(f"wp_{self.last_reached_wp_id}", {}).get('name')
                self.update_general_log(f"'{wp_name}' 도착. 다음 구간으로 진행합니다.", "green")
            else:
                # 다음 단계가 액션인지 확인하고 상태 전환
                next_node_key = self.current_segment_path[next_index]
                edge_data = self.nav_graph.get(current_node_key, {}).get(next_node_key, {})
                action = edge_data.get('action') if edge_data else None
                
                next_action_state = None
                if action == 'climb': next_action_state = 'prepare_to_climb'
                elif action == 'jump': next_action_state = 'prepare_to_jump'
                elif action == 'climb_down': next_action_state = 'prepare_to_fall'

                if next_action_state:
                    self._transition_to_action_state(next_action_state, current_node_key)
                else:
                    self.current_segment_index = next_index
            return


    def _handle_action_preparation(self, final_player_pos):
        """'prepare_to_...' 상태일 때의 모든 로직을 담당합니다."""
        # [v12.4.3] 목표 설정 로직을 맨 위로 이동 및 강화
        action_node_key = self.current_segment_path[self.current_segment_index]
        
        if self.navigation_action == 'prepare_to_down_jump':
            self.guidance_text = "아래로 점프하세요"
            action_key_part = f"{action_node_key.split('_', 1)[1]}"
            action_key = f"djump_action_{action_key_part}"
            target_group = self.nav_graph.get(action_node_key, {}).get(action_key, {}).get('target_group')
            if target_group:
                target_line = next((line for line in self.geometry_data.get("terrain_lines", []) if line.get('dynamic_name') == target_group), None)
                if target_line:
                    # 아래층 지형의 정확한 y좌표 계산
                    p1, p2 = target_line['points'][0], target_line['points'][-1]
                    target_y = p1[1] + (p2[1] - p1[1]) * ((final_player_pos.x() - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]
                    self.intermediate_target_pos = QPointF(final_player_pos.x(), target_y)
        
        elif self.current_segment_index + 1 < len(self.current_segment_path):
            next_node_key = self.current_segment_path[self.current_segment_index + 1]
            next_node = self.nav_nodes.get(next_node_key)
            if next_node:
                self.intermediate_target_pos = next_node.get('pos')
                self.guidance_text = next_node.get('name', '')
        
        # 이하 액션 시작 및 이탈 판정 로직은 기존과 동일
        self._process_action_preparation(final_player_pos)

    def _handle_action_in_progress(self, final_player_pos):
        """'..._in_progress' 상태일 때의 로직을 담당합니다."""
        # 목표는 액션의 출구 또는 가상 착지 지점을 계속 유지
        if self.current_segment_index + 1 < len(self.current_segment_path):
            next_node_key = self.current_segment_path[self.current_segment_index + 1]
            if next_node_key in self.nav_nodes:
                self.intermediate_target_pos = self.nav_nodes[next_node_key]['pos']
                self.guidance_text = self.nav_nodes[next_node_key]['name']

    def _get_terrain_id_from_vertex(self, vertex_pos):
        """주어진 꼭짓점(vertex) 좌표에 연결된 지형선 ID를 반환합니다."""
        # 성능을 위해 미리 계산된 맵을 사용하는 것이 좋지만, 여기서는 직접 탐색
        for line in self.geometry_data.get("terrain_lines", []):
            for point in line.get("points", []):
                # 부동소수점 비교를 위해 작은 허용 오차(epsilon) 사용
                if abs(point[0] - vertex_pos[0]) < 1e-6 and abs(point[1] - vertex_pos[1]) < 1e-6:
                    return line['id']
        return None

    def _check_near_ladder(self, pos, transition_objects, x_tol, return_x=False, return_dist=False, current_floor=None):
        """
        주어진 위치가 현재 층과 연결된 사다리 근처인지 확인합니다.
        [v11.4.5] 현재 층 기반 필터링 로직 추가
        """
        min_dist_sq = float('inf')
        nearest_ladder_x = None
        is_near = False
        actual_dist_x = -1

        # [v11.4.5] 1. 현재 층과 연결된 사다리만 필터링
        candidate_ladders = []
        if current_floor is not None:
            for obj in transition_objects:
                start_line_id = obj.get("start_line_id")
                end_line_id = obj.get("end_line_id")
                
                start_floor = self.line_id_to_floor_map.get(start_line_id)
                end_floor = self.line_id_to_floor_map.get(end_line_id)

                if start_floor is not None and end_floor is not None:
                    # 현재 층이 사다리의 시작 또는 끝 층과 일치하는 경우 후보로 추가
                    if abs(current_floor - start_floor) < 0.1 or abs(current_floor - end_floor) < 0.1:
                        candidate_ladders.append(obj)
        else:
            # current_floor 정보가 없으면, 이전처럼 모든 사다리를 검사 (안전장치)
            candidate_ladders = transition_objects

        # [v11.4.5] 2. 필터링된 후보군을 대상으로 근접 검사
        for obj in candidate_ladders:
            points = obj.get("points")
            if not points or len(points) < 2:
                continue
            
            ladder_x = points[0][0]
            dist_x = abs(pos.x() - ladder_x)

            if dist_x**2 < min_dist_sq:
                min_dist_sq = dist_x**2
                nearest_ladder_x = ladder_x
                actual_dist_x = dist_x

            if dist_x <= x_tol:
                min_y = min(points[0][1], points[1][1])
                max_y = max(points[0][1], points[1][1])
                if pos.y() >= min_y and pos.y() <= max_y:
                    is_near = True
        
        if return_dist:
            return is_near, nearest_ladder_x, actual_dist_x
        elif return_x:
            return is_near, nearest_ladder_x
        else:
            return is_near

    def _is_on_terrain(self, pos):
        """주어진 위치가 지형선 위에 있는지 확인합니다."""
        return self._get_contact_terrain(pos) is not None

    def _get_contact_terrain(self, pos):
        """
        주어진 위치에서 접촉하고 있는 지형선 데이터를 반환합니다.
        [v11.1.0] UI에서 조정한 설정값을 사용하도록 수정
        """
        for line_data in self.geometry_data.get("terrain_lines", []):
            points = line_data.get("points", [])
            if len(points) < 2: continue
            for i in range(len(points) - 1):
                p1, p2 = points[i], points[i+1]
                min_lx, max_lx = min(p1[0], p2[0]), max(p1[0], p2[0])

                if not (min_lx <= pos.x() <= max_lx): continue

                line_y = p1[1] + (p2[1] - p1[1]) * ((pos.x() - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]
                # [v11.1.0] 상수 대신 멤버 변수 사용
                if abs(pos.y() - line_y) < self.cfg_on_terrain_y_threshold:
                    return line_data
        return None

    def update_general_log(self, message, color):
        self.general_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.general_log_viewer.verticalScrollBar().setValue(self.general_log_viewer.verticalScrollBar().maximum())
        
    def update_detection_log_from_features(self, inliers, outliers):
        """정상치와 이상치 피처 목록을 받아 탐지 상태 로그를 업데이트합니다."""
        # [NEW] 5프레임마다 한 번씩만 업데이트하도록 조절
        self.log_update_counter += 1
        if self.log_update_counter % 5 != 0:
            return

        log_html = "<b>활성 지형:</b> "
        
        # 임계값 미만이지만 탐지된 모든 지형을 포함
        all_found = inliers + outliers
        if not all_found:
            log_html += '<font color="red">탐지된 지형 없음</font>'
            self.detection_log_viewer.setHtml(log_html)
            return

        inlier_texts = []
        if inliers:
            sorted_inliers = sorted(inliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_inliers:
                inlier_texts.append(f'<font color="blue">{f["id"]}({f["conf"]:.2f})</font>')
        
        outlier_texts = []
        if outliers:
            sorted_outliers = sorted(outliers, key=lambda x: x['conf'], reverse=True)
            for f in sorted_outliers:
                outlier_texts.append(f'<font color="red">{f["id"]}({f["conf"]:.2f})</font>')

        log_html += ", ".join(inlier_texts)
        if inlier_texts and outlier_texts:
            log_html += ", "
        log_html += ", ".join(outlier_texts)
        
        self.detection_log_viewer.setHtml(log_html)

    def update_detection_log_message(self, message, color):
        """단순 텍스트 메시지를 탐지 상태 로그에 표시합니다."""
        self.detection_log_viewer.setHtml(f'<font color="{color}">{message}</font>')
        
    def update_detection_log(self, message, color):
        self.detection_log_viewer.setText(f'<font color="{color}">{message}</font>')
    
    def _build_line_floor_map(self): # [v11.4.5] 지형선 ID와 층 정보를 매핑하는 캐시를 생성하는 헬퍼 메서드
        """self.geometry_data를 기반으로 line_id_to_floor_map을 생성/갱신합니다."""
        self.line_id_to_floor_map.clear()
        if not self.geometry_data or "terrain_lines" not in self.geometry_data:
            return
        
        for line in self.geometry_data.get("terrain_lines", []):
            line_id = line.get("id")
            floor = line.get("floor")
            if line_id is not None and floor is not None:
                self.line_id_to_floor_map[line_id] = floor
        self.update_general_log("지형-층 정보 맵 캐시를 갱신했습니다.", "gray")

    def _update_map_data_and_views(self):
            """데이터 변경 후 전역 좌표와 전체 맵 뷰를 갱신합니다."""
            self.global_positions = self._calculate_global_positions()
            self._generate_full_map_pixmap()
            self._assign_dynamic_names() #동적 이름 부여 메서드 호출 추가
            self.update_general_log("맵 데이터를 최신 정보로 갱신했습니다.", "purple")

    def _calculate_global_positions(self):
            """
            v10.0.0: 기준 앵커를 원점으로 하여 모든 핵심 지형과 구버전 웨이포인트의 전역 좌표를 계산합니다.
            [MODIFIED] 동일 컨텍스트 이미지를 가진 지형 그룹을 해시로 식별하여, 템플릿 매칭 대신
            직접 좌표를 전개함으로써 좌표 붕괴 및 무한 루프 가능성을 방지합니다.
            """
            if not self.key_features:
                self.reference_anchor_id = None
                return {}

            for f_id, f_data in self.key_features.items():
                if 'size' not in f_data:
                    try:
                        img_data = base64.b64decode(f_data['image_base64'])
                        np_arr = np.frombuffer(img_data, np.uint8)
                        template = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                        if template is not None:
                            f_data['size'] = QSize(template.shape[1], template.shape[0])
                    except:
                        pass

            global_positions = {}

            # 1. 기준 앵커 설정
            anchor_id = self.reference_anchor_id
            if not anchor_id or anchor_id not in self.key_features:
                try:
                    anchor_id = sorted(self.key_features.keys())[0]
                    self.reference_anchor_id = anchor_id
                    self.update_general_log(f"경고: 기준 앵커가 없어, '{anchor_id}'을(를) 새 기준으로 자동 설정합니다.", "orange")
                except IndexError:
                    return {}
            
            # [NEW] 정책/가드 옵션 및 해시/템플릿 준비
            identical_context_policy = getattr(self, 'identical_context_policy', 'propagate')
            degenerate_match_eps = float(getattr(self, 'degenerate_match_eps', 2.0))

            templates = {}
            contexts = {}
            context_hashes = {} # 컨텍스트 그룹핑용 해시

            for f_id, f_data in self.key_features.items():
                try:
                    img_data = base64.b64decode(f_data['image_base64'])
                    np_arr = np.frombuffer(img_data, np.uint8)
                    templates[f_id] = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                    if 'context_image_base64' in f_data and f_data['context_image_base64']:
                        context_img_data = base64.b64decode(f_data['context_image_base64'])
                        contexts[f_id] = cv2.imdecode(np.frombuffer(context_img_data, np.uint8), cv2.IMREAD_GRAYSCALE)
                        context_hashes[f_id] = hashlib.sha1(context_img_data).hexdigest()
                    else:
                        contexts[f_id], context_hashes[f_id] = None, None
                except Exception as e:
                    print(f"이미지 디코딩 오류 (ID: {f_id}): {e}")
                    templates[f_id], contexts[f_id], context_hashes[f_id] = None, None, None
            
            # 2. 핵심 지형 좌표 계산 (양방향 탐색 로직)
            known_features = {anchor_id}
            pending_features = set(self.key_features.keys()) - known_features
            global_positions[anchor_id] = QPointF(0, 0)

            # [NEW] 동일 컨텍스트 그룹핑 및 앵커 그룹 사전 전개
            if identical_context_policy in ('propagate', 'forbid'):
                groups = defaultdict(list)
                for fid, h in context_hashes.items():
                    if h: groups[h].append(fid)

                anchor_hash = context_hashes.get(anchor_id)
                if anchor_hash and anchor_hash in groups:
                    anchor_rect_data = self.key_features[anchor_id].get('rect_in_context')
                    # [MODIFIED] rect_in_context 유효성 검사 추가
                    if anchor_rect_data and len(anchor_rect_data) == 4:
                        anchor_local_in_ctx = QPointF(anchor_rect_data[0], anchor_rect_data[1])
                        context_origin = global_positions[anchor_id] - anchor_local_in_ctx

                        for fid in groups[anchor_hash]:
                            if fid not in global_positions:
                                rect_data = self.key_features[fid].get('rect_in_context')
                                # [MODIFIED] rect_in_context 유효성 검사 추가
                                if rect_data and len(rect_data) == 4:
                                    local_in_ctx = QPointF(rect_data[0], rect_data[1])
                                    global_positions[fid] = context_origin + local_in_ctx
                        
                        known_features.update(groups[anchor_hash])
                        pending_features -= set(groups[anchor_hash])
                    else:
                        self.update_general_log(f"경고: 앵커 '{anchor_id}'의 문맥 내 좌표(rect_in_context)가 유효하지 않아 동일 문맥 그룹 전개를 건너뜁니다.", "orange")
            
            MATCH_THRESHOLD = 0.90

            for _ in range(len(self.key_features) + 1):
                if not pending_features: break
                
                found_in_iteration = set()
                
                for pending_id in list(pending_features):
                    is_found = False
                    for known_id in known_features:
                        same_ctx = context_hashes.get(known_id) is not None and context_hashes[known_id] == context_hashes.get(pending_id)

                        # 탐색 A: known의 문맥에서 pending 찾기
                        if not same_ctx:
                            known_context, pending_template = contexts.get(known_id), templates.get(pending_id)
                            if known_context is not None and pending_template is not None:
                                res = cv2.matchTemplate(known_context, pending_template, cv2.TM_CCOEFF_NORMED)
                                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                if max_val >= MATCH_THRESHOLD:
                                    known_global_pos = global_positions[known_id]
                                    known_rect = self.key_features[known_id].get('rect_in_context', [0,0,0,0])
                                    known_local_pos_in_context = QPointF(known_rect[0], known_rect[1])
                                    if not (abs(max_loc[0] - known_local_pos_in_context.x()) <= degenerate_match_eps and abs(max_loc[1] - known_local_pos_in_context.y()) <= degenerate_match_eps):
                                        context_global_origin = known_global_pos - known_local_pos_in_context
                                        pending_local_pos_in_context = QPointF(max_loc[0], max_loc[1])
                                        global_positions[pending_id] = context_global_origin + pending_local_pos_in_context
                                        is_found = True
                        if is_found: break

                        # 탐색 B: pending의 문맥에서 known 찾기
                        if not same_ctx:
                            pending_context, known_template = contexts.get(pending_id), templates.get(known_id)
                            if pending_context is not None and known_template is not None:
                                res = cv2.matchTemplate(pending_context, known_template, cv2.TM_CCOEFF_NORMED)
                                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                if max_val >= MATCH_THRESHOLD:
                                    known_global_pos = global_positions[known_id]
                                    pending_rect = self.key_features[pending_id].get('rect_in_context', [0,0,0,0])
                                    pending_local_pos_in_context = QPointF(pending_rect[0], pending_rect[1])
                                    known_local_pos_in_pending_context = QPointF(max_loc[0], max_loc[1])
                                    if not (abs(max_loc[0] - pending_local_pos_in_context.x()) <= degenerate_match_eps and abs(max_loc[1] - pending_local_pos_in_context.y()) <= degenerate_match_eps):
                                        context_global_origin = known_global_pos - known_local_pos_in_pending_context
                                        global_positions[pending_id] = context_global_origin + pending_local_pos_in_context
                                        is_found = True
                        if is_found: break
                    
                    if is_found:
                        found_in_iteration.add(pending_id)
                        # [NEW] 신규 확정 피처의 동일-컨텍스트 그룹 즉시 전개
                        if identical_context_policy == 'propagate':
                            h = context_hashes.get(pending_id)
                            if h and h in groups:
                                rect_p_data = self.key_features[pending_id].get('rect_in_context')
                                # [MODIFIED] rect_in_context 유효성 검사 추가
                                if rect_p_data and len(rect_p_data) == 4:
                                    local_p = QPointF(rect_p_data[0], rect_p_data[1])
                                    ctx_origin = global_positions[pending_id] - local_p
                                    for fid in groups[h]:
                                        if fid not in global_positions:
                                            rect_f_data = self.key_features[fid].get('rect_in_context')
                                            # [MODIFIED] rect_in_context 유효성 검사 추가
                                            if rect_f_data and len(rect_f_data) == 4:
                                                local_f = QPointF(rect_f_data[0], rect_f_data[1])
                                                global_positions[fid] = ctx_origin + local_f
                                                found_in_iteration.add(fid)

                if found_in_iteration:
                    known_features.update(found_in_iteration)
                    pending_features -= found_in_iteration
                else:
                    break
            
            if pending_features:
                failed_ids = ", ".join(sorted(list(pending_features)))
                message = (f"경고: 다음 핵심 지형들의 위치를 계산하지 못했습니다: {failed_ids}. "
                        "이 지형들이 다른 지형과 연결(문맥 이미지 내 포함)되어 있는지 확인해주세요.")
                self.update_general_log(message, "orange")

            for feature_id in known_features:
                if feature_id in global_positions:
                    feature_data = self.key_features[feature_id]
                    if 'rect_in_context' in feature_data and feature_data['rect_in_context']:
                        rect = feature_data['rect_in_context']
                        feature_local_pos_in_context = QPointF(rect[0], rect[1])
                        context_origin_pos = global_positions[feature_id] - feature_local_pos_in_context
                        global_positions[f"{feature_id}_context"] = context_origin_pos

            all_waypoints_old = self.get_all_waypoints_with_route_name()
            if all_waypoints_old:
                # ... (기존 구버전 웨이포인트 처리 로직은 그대로 유지) ...
                pass # 이 부분은 변경 없음

            self.feature_offsets.clear()
            known_feature_ids = [fid for fid in known_features if fid in global_positions]
            for i in range(len(known_feature_ids)):
                for j in range(i + 1, len(known_feature_ids)):
                    id1, id2 = known_feature_ids[i], known_feature_ids[j]
                    pos1, pos2 = global_positions[id1], global_positions[id2]
                    
                    size1_data, size2_data = self.key_features[id1].get('size'), self.key_features[id2].get('size')
                    size1 = QSize(size1_data[0], size1_data[1]) if isinstance(size1_data, list) and len(size1_data) == 2 else QSize(0,0)
                    size2 = QSize(size2_data[0], size2_data[1]) if isinstance(size2_data, list) and len(size2_data) == 2 else QSize(0,0)
                    
                    center1 = pos1 + QPointF(size1.width()/2, size1.height()/2)
                    center2 = pos2 + QPointF(size2.width()/2, size2.height()/2)

                    offset = center2 - center1
                    # [NEW] 퇴화 방지: 0에 가까운 오프셋은 저장하지 않음
                    if math.hypot(offset.x(), offset.y()) < 1e-3:
                        continue

                    self.feature_offsets[(id1, id2)] = offset
                    self.feature_offsets[(id2, id1)] = -offset

            return global_positions

# === v12.0.0: A* 경로 탐색 시스템 메서드 ===
    def _get_closest_node_to_point(self, point, target_group=None, target_floor=None, walkable_only=False):
        """
        주어진 좌표에서 가장 가까운 내비게이션 그래프 노드를 찾습니다.
        [수정] walkable_only 플래그를 추가하여 탐색 대상을 제한합니다.
        """
        if not self.nav_nodes:
            return None, float('inf')

        min_dist_sq = float('inf')
        closest_node_key = None
        
        candidate_nodes = []
        for key, node_data in self.nav_nodes.items():
            # walkable_only 필터
            if walkable_only and not node_data.get('walkable', False):
                continue
            # 그룹 필터
            if target_group and node_data.get('group') != target_group:
                continue
            # 층 필터 (우선순위)
            if target_floor is not None:
                node_floor = node_data.get('floor')
                if node_floor is not None and abs(node_floor - target_floor) < 0.1:
                    candidate_nodes.append((key, node_data))
            else: # 층 필터가 없으면 모든 후보를 추가
                candidate_nodes.append((key, node_data))

        # 층 필터링된 후보가 없으면, 층 무시하고 다시 탐색
        if target_floor is not None and not candidate_nodes:
            for key, node_data in self.nav_nodes.items():
                if walkable_only and not node_data.get('walkable', False):
                    continue
                if target_group and node_data.get('group') != target_group:
                    continue
                candidate_nodes.append((key, node_data))

        # 최종 후보군에서 거리 계산
        for key, node_data in candidate_nodes:
            pos = node_data.get('pos')
            if pos:
                dist_sq = (point.x() - pos.x())**2 + (point.y() - pos.y())**2
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    closest_node_key = key

        return closest_node_key, math.sqrt(min_dist_sq) if closest_node_key else float('inf')
    
    def _build_navigation_graph(self, waypoint_ids_in_route=None):
            """
            v12.9.2: [수정] '아래 점프' 노드 생성 로직을 전면 개편합니다. 
                     1. 아래층의 웨이포인트 바로 위 지점에 '목표 정렬 노드'를 생성하여 최적의 경로를 제공합니다.
                     2. 점프 가능 구간의 양 끝 지점에도 노드를 생성하여 유연성을 확보합니다.
                     3. 이 모든 과정에서 사다리의 x좌표는 항상 제외하여 키 입력 충돌을 방지합니다.
            v12.9.1: [수정] '아래 점프' 구간 생성 시, 사다리가 차지하는 x좌표를 제외한 나머지 유효 구간에만 노드를 생성하도록 로직을 수정하여 키 입력 충돌 문제를 해결합니다.
            v12.9.0: [수정] '아래 점프' 구간을 생성할 때, 해당 x축 범위에 이미 층 이동 오브젝트(사다리)가 존재하는 경우 '아래 점프' 노드를 생성하지 않도록 수정하여 경로 중복 및 비효율 문제를 해결합니다.
            v12.8.9: [수정] '아래 점프' 지점을 구간의 중앙 한 곳에만 생성하던 문제를 해결하기 위해, 구간의 왼쪽/중앙/오른쪽에 여러 개의 노드를 생성하여 경로 탐색의 유연성을 높입니다.
            v12.8.8: [수정] 요청에 따라 경로 탐색 비용 상수를 조정합니다.
            v12.8.7: [수정] 층 이동 오브젝트(사다리)에서 '낭떠러지'나 '아래 점프' 지점으로 직접 연결되는 비현실적인 경로가 생성되지 않도록 예외 처리 로직을 추가합니다.
            v12.8.5: [수정] '아래 점프' 비용을 독립적으로 제어하기 위해 DOWN_JUMP_COST_MULTIPLIER를 추가하고, 중간층 방해물 확인 로직을 명시합니다.
            v12.8.3: [수정] '낭떠러지' 및 '아래 점프' 노드가 경로 탐색에 포함되도록, walkable 노드와의 연결(간선)을 자동으로 생성하는 로직을 추가합니다.
            v12.8.2: [수정] 사다리 노드(ladder_entry, ladder_exit) 생성 시, 연결된 지형의 층(floor) 정보를 명시적으로 추가하여 도착 판정 오류를 해결합니다.
            v12.6.1: [수정] 누락되었던 is_obstructed 충돌 검사 로직을 복원하여 프로필 로드 오류를 해결합니다.
            """
            self.nav_nodes.clear()
            self.nav_graph = defaultdict(dict)

            if not self.geometry_data: return
            if waypoint_ids_in_route is None:
                waypoint_ids_in_route = [wp['id'] for wp in self.geometry_data.get("waypoints", [])]

            terrain_lines = self.geometry_data.get("terrain_lines", [])
            transition_objects = self.geometry_data.get("transition_objects", [])

            FLOOR_CHANGE_PENALTY = 5.0
            CLIMB_UP_COST_MULTIPLIER = 1.5
            CLIMB_DOWN_COST_MULTIPLIER = 500.0
            JUMP_COST_MULTIPLIER = 1.1
            FALL_COST_MULTIPLIER = 1.6
            DOWN_JUMP_COST_MULTIPLIER = 1.2

            # --- 1. 모든 잠재적 노드 생성 및 역할(walkable) 부여 ---
            for wp in self.geometry_data.get("waypoints", []):
                if wp['id'] in waypoint_ids_in_route:
                    key = f"wp_{wp['id']}"
                    contact_terrain = self._get_contact_terrain(QPointF(*wp['pos']))
                    group = contact_terrain.get('dynamic_name') if contact_terrain else None
                    self.nav_nodes[key] = {'type': 'waypoint', 'pos': QPointF(*wp['pos']), 'floor': wp.get('floor'), 'name': wp.get('name'), 'id': wp['id'], 'group': group, 'walkable': True}

            for obj in transition_objects:
                p1, p2 = QPointF(*obj['points'][0]), QPointF(*obj['points'][1])
                entry_pos, exit_pos = (p1, p2) if p1.y() > p2.y() else (p2, p1)
                entry_key, exit_key = f"ladder_entry_{obj['id']}", f"ladder_exit_{obj['id']}"
                
                entry_terrain, exit_terrain = self._get_contact_terrain(entry_pos), self._get_contact_terrain(exit_pos)
                entry_group = entry_terrain.get('dynamic_name') if entry_terrain else None
                exit_group = exit_terrain.get('dynamic_name') if exit_terrain else None
                entry_floor = entry_terrain.get('floor') if entry_terrain else None
                exit_floor = exit_terrain.get('floor') if exit_terrain else None
                
                base_name = obj.get('dynamic_name', obj['id'])
                
                self.nav_nodes[entry_key] = {'type': 'ladder_entry', 'pos': entry_pos, 'obj_id': obj['id'], 'name': f"{base_name} (입구)", 'group': entry_group, 'walkable': True, 'floor': entry_floor}
                self.nav_nodes[exit_key] = {'type': 'ladder_exit', 'pos': exit_pos, 'obj_id': obj['id'], 'name': f"{base_name} (출구)", 'group': exit_group, 'walkable': True, 'floor': exit_floor}
                
                y_diff = abs(entry_pos.y() - exit_pos.y())
                cost_up, cost_down = (y_diff * CLIMB_UP_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY, (y_diff * CLIMB_DOWN_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY
                self.nav_graph[entry_key][exit_key] = {'cost': cost_up, 'action': 'climb'}
                self.nav_graph[exit_key][entry_key] = {'cost': cost_down, 'action': 'climb_down'}

            for link in self.geometry_data.get("jump_links", []):
                start_pos, end_pos = QPointF(*link['start_vertex_pos']), QPointF(*link['end_vertex_pos'])
                key1, key2 = f"jump_{link['id']}_p1", f"jump_{link['id']}_p2"
                start_terrain, end_terrain = self._get_contact_terrain(start_pos), self._get_contact_terrain(end_pos)
                start_group, end_group = (start_terrain.get('dynamic_name') if start_terrain else None), (end_terrain.get('dynamic_name') if end_terrain else None)
                base_name = link.get('dynamic_name', link['id'])
                self.nav_nodes[key1] = {'type': 'jump_vertex', 'pos': start_pos, 'link_id': link['id'], 'name': f"{base_name} (시작점)", 'group': start_group, 'walkable': True}
                self.nav_nodes[key2] = {'type': 'jump_vertex', 'pos': end_pos, 'link_id': link['id'], 'name': f"{base_name} (도착점)", 'group': end_group, 'walkable': True}
                cost = math.hypot(start_pos.x() - end_pos.x(), start_pos.y() - end_pos.y()) * JUMP_COST_MULTIPLIER
                if start_terrain and end_terrain and start_terrain.get('floor') != end_terrain.get('floor'):
                    cost += FLOOR_CHANGE_PENALTY
                self.nav_graph[key1][key2], self.nav_graph[key2][key1] = {'cost': cost, 'action': 'jump'}, {'cost': cost, 'action': 'jump'}

            for line_above in terrain_lines:
                group_above = line_above.get('dynamic_name')
                for v_idx, vertex in enumerate([line_above['points'][0], line_above['points'][-1]]):
                    for line_below in terrain_lines:
                        if line_above['id'] == line_below['id'] or line_above['floor'] <= line_below['floor']: continue
                        min_x, max_x = min(line_below['points'][0][0], line_below['points'][-1][0]), max(line_below['points'][0][0], line_below['points'][-1][0])
                        if min_x <= vertex[0] <= max_x:
                            is_obstructed = False
                            for other_line in terrain_lines:
                                if (other_line['id'] != line_above['id'] and other_line['id'] != line_below['id'] and
                                    line_below['floor'] < other_line['floor'] < line_above['floor']):
                                    other_min_x, other_max_x = min(other_line['points'][0][0], other_line['points'][-1][0]), max(other_line['points'][0][0], other_line['points'][-1][0])
                                    if other_min_x <= vertex[0] <= other_max_x:
                                        is_obstructed = True
                                        break
                            if is_obstructed: continue
                            start_key = f"fall_start_{line_above['id']}_{v_idx}"
                            self.nav_nodes[start_key] = {'type': 'fall_start', 'pos': QPointF(*vertex), 'name': f"{group_above} 낙하 지점", 'group': group_above, 'walkable': False}
                            cost = (abs(vertex[1] - line_below['points'][0][1]) * FALL_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY
                            target_group, action_key = line_below.get('dynamic_name'), f"fall_action_{line_above['id']}_{v_idx}_{line_below['id']}"
                            self.nav_graph[start_key][action_key] = {'cost': cost, 'action': 'fall', 'target_group': target_group}
                            break

                for line_below in terrain_lines:
                    if line_above['id'] == line_below['id'] or line_above['floor'] <= line_below['floor']: continue
                    y_above, y_below = line_above['points'][0][1], line_below['points'][0][1]
                    y_diff = abs(y_above - y_below)
                    if 0 < y_diff <= 70:
                        ax1, ax2 = min(line_above['points'][0][0], line_above['points'][-1][0]), max(line_above['points'][0][0], line_above['points'][-1][0])
                        bx1, bx2 = min(line_below['points'][0][0], line_below['points'][-1][0]), max(line_below['points'][0][0], line_below['points'][-1][0])
                        overlap_x1, overlap_x2 = max(ax1, bx1), min(ax2, bx2)
                        
                        if overlap_x1 < overlap_x2:
                            ladders_in_overlap = []
                            for obj in transition_objects:
                                ladder_x = obj['points'][0][0]
                                if overlap_x1 <= ladder_x <= overlap_x2:
                                    start_line_id = obj.get('start_line_id')
                                    end_line_id = obj.get('end_line_id')
                                    if {line_above['id'], line_below['id']} == {start_line_id, end_line_id}:
                                        ladders_in_overlap.append(ladder_x)
                            
                            is_obstructed = False
                            for other_line in terrain_lines:
                                if (other_line['id'] != line_above['id'] and other_line['id'] != line_below['id'] and
                                    line_below['floor'] < other_line['floor'] < line_above['floor']):
                                    other_min_x, other_max_x = min(other_line['points'][0][0], other_line['points'][-1][0]), max(other_line['points'][0][0], other_line['points'][-1][0])
                                    if max(overlap_x1, other_min_x) < min(overlap_x2, other_max_x):
                                        is_obstructed = True
                                        break
                            if is_obstructed: continue

                            valid_jump_zones = []
                            current_x = overlap_x1
                            sorted_ladders_x = sorted(ladders_in_overlap)
                            for ladder_x in sorted_ladders_x:
                                if current_x < ladder_x:
                                    valid_jump_zones.append((current_x, ladder_x))
                                current_x = ladder_x
                            if current_x < overlap_x2:
                                valid_jump_zones.append((current_x, overlap_x2))

                            # --- [v12.9.2 수정] 각 유효 점프 구간에 대해 전략적 노드 생성 ---
                            for zone_idx, (zone_x1, zone_x2) in enumerate(valid_jump_zones):
                                LADDER_AVOIDANCE_WIDTH = 5.0
                                if abs(zone_x2 - zone_x1) < LADDER_AVOIDANCE_WIDTH:
                                    continue
                                
                                # 1. 목적지 정렬 노드: 아래층의 WP 바로 위에 노드 생성
                                strategic_x_positions = set()
                                waypoints_on_line_below = [
                                    wp for wp in self.geometry_data.get("waypoints", []) 
                                    if wp.get('parent_line_id') == line_below['id']
                                ]
                                for wp in waypoints_on_line_below:
                                    wp_x = wp['pos'][0]
                                    if zone_x1 <= wp_x <= zone_x2:
                                        strategic_x_positions.add(round(wp_x, 1))

                                # 2. 경계 노드: 구간의 양 끝점에 노드 추가
                                strategic_x_positions.add(round(zone_x1, 1))
                                strategic_x_positions.add(round(zone_x2, 1))
                                
                                # 3. 생성된 전략적 위치에 노드 배치
                                for i, x_pos in enumerate(sorted(list(strategic_x_positions))):
                                    start_key = f"djump_start_{line_above['id']}_{line_below['id']}_{zone_idx}_{i}"
                                    start_pos = QPointF(x_pos, y_above)
                                    
                                    self.nav_nodes[start_key] = {
                                        'type': 'djump_area', 
                                        'pos': start_pos, 
                                        'name': f"{group_above} 아래 점프 지점", 
                                        'group': group_above, 
                                        'x_range': [zone_x1, zone_x2], # 도착 판정은 전체 존(zone)을 기준으로 함
                                        'walkable': False
                                    }
                                    
                                    cost = (y_diff * DOWN_JUMP_COST_MULTIPLIER) + FLOOR_CHANGE_PENALTY
                                    target_group = line_below.get('dynamic_name')
                                    action_key = f"djump_action_{line_above['id']}_{line_below['id']}_{zone_idx}_{i}"
                                    self.nav_graph[start_key][action_key] = {'cost': cost, 'action': 'down_jump', 'target_group': target_group}
            
            # --- 2. 걷기(Walk) 간선 추가 ---
            nodes_by_terrain_group = defaultdict(list)
            for key, node_data in self.nav_nodes.items():
                if node_data.get('walkable'):
                    if node_data.get('group'):
                        nodes_by_terrain_group[node_data['group']].append(key)
            
            for group_name, node_keys in nodes_by_terrain_group.items():
                for i in range(len(node_keys)):
                    for j in range(i + 1, len(node_keys)):
                        key1, key2 = node_keys[i], node_keys[j]
                        pos1, pos2 = self.nav_nodes[key1]['pos'], self.nav_nodes[key2]['pos']
                        cost = abs(pos1.x() - pos2.x())
                        self.nav_graph[key1][key2] = {'cost': cost, 'action': 'walk'}
                        self.nav_graph[key2][key1] = {'cost': cost, 'action': 'walk'}

            # --- 3. 행동 유발(Action Trigger) 노드 연결 ---
            action_trigger_nodes = {key: data for key, data in self.nav_nodes.items() if not data.get('walkable')}
            walkable_nodes = {key: data for key, data in self.nav_nodes.items() if data.get('walkable')}

            for trigger_key, trigger_data in action_trigger_nodes.items():
                trigger_group = trigger_data.get('group')
                if not trigger_group: continue

                for walkable_key, walkable_data in walkable_nodes.items():
                    if walkable_data.get('type') in ['ladder_entry', 'ladder_exit']:
                        continue
                        
                    if walkable_data.get('group') == trigger_group:
                        pos1 = walkable_data['pos']
                        pos2 = trigger_data['pos']
                        cost = abs(pos1.x() - pos2.x())
                        self.nav_graph[walkable_key][trigger_key] = {'cost': cost, 'action': 'walk'}

            self.update_general_log(f"내비게이션 그래프 생성 완료. (노드: {len(self.nav_nodes)}개)", "purple")

    
    def _find_path_astar(self, start_pos, start_group, goal_key):
        """
        v12.8.8: [수정] '아래 점프' 또는 '낙하' 이후의 착지 지점을 계산할 때, '사다리 입/출구'를 후보에서 제외하여 비현실적인 경로 생성을 방지합니다.
        v12.8.1: A* 알고리즘을 수정하여, 플레이어의 실제 위치(가상 노드)에서 탐색을 시작합니다.
        """
        if goal_key not in self.nav_nodes:
            print(f"[A* DEBUG] 목표 노드가 nav_nodes에 없습니다. 목표: {goal_key}")
            return None, float('inf')

        import heapq
        
        goal_pos = self.nav_nodes[goal_key]['pos']

        open_set = []
        came_from = {}
        g_score = {key: float('inf') for key in self.nav_nodes}
        f_score = {key: float('inf') for key in self.nav_nodes}

        nodes_in_start_group = [
            key for key, data in self.nav_nodes.items()
            if data.get('walkable', False) and data.get('group') == start_group
        ]

        if not nodes_in_start_group:
            print(f"[A* DEBUG] 시작 그룹 '{start_group}' 내에 walkable 노드가 없습니다.")
            return None, float('inf')
        
        print("\n" + "="*20 + " A* 탐색 시작 (동적 확장) " + "="*20)
        print(f"[A* DEBUG] 가상 시작점: {start_pos.x():.1f}, {start_pos.y():.1f} (그룹: '{start_group}')")
        print(f"[A* DEBUG] 목표: '{self.nav_nodes[goal_key]['name']}' ({goal_key})")
        
        for node_key in nodes_in_start_group:
            node_pos = self.nav_nodes[node_key]['pos']
            cost_to_node = abs(start_pos.x() - node_pos.x())
            
            g_score[node_key] = cost_to_node
            h_score = math.hypot(node_pos.x() - goal_pos.x(), node_pos.y() - goal_pos.y())
            f_score[node_key] = cost_to_node + h_score
            heapq.heappush(open_set, (f_score[node_key], node_key))
            came_from[node_key] = ("__START__", None)
            
            print(f"[A* DEBUG]  - 초기 탐색 노드: '{self.nav_nodes[node_key]['name']}' | G: {cost_to_node:.1f} | H: {h_score:.1f} | F: {f_score[node_key]:.1f}")
        
        iter_count = 0
        while open_set:
            iter_count += 1
            if iter_count > 2000:
                print("[A* DEBUG] ERROR: 탐색 반복 횟수가 2000회를 초과했습니다. 탐색을 중단합니다.")
                break
                
            _, current_key = heapq.heappop(open_set)

            if current_key == goal_key:
                path = self._reconstruct_path(came_from, current_key, "__START__")
                return path, g_score[goal_key]

            for neighbor_key, edge_data in self.nav_graph.get(current_key, {}).items():
                cost = edge_data.get('cost', float('inf'))
                tentative_g_score = g_score[current_key] + cost
                
                if neighbor_key in self.nav_nodes:
                    if tentative_g_score < g_score[neighbor_key]:
                        came_from[neighbor_key] = (current_key, edge_data)
                        g_score[neighbor_key] = tentative_g_score
                        neighbor_pos = self.nav_nodes[neighbor_key]['pos']
                        h_score = math.hypot(neighbor_pos.x() - goal_pos.x(), neighbor_pos.y() - goal_pos.y())
                        f_score[neighbor_key] = tentative_g_score + h_score
                        heapq.heappush(open_set, (f_score[neighbor_key], neighbor_key))
                
                elif 'target_group' in edge_data:
                    target_group = edge_data['target_group']
                    best_landing_node, min_landing_cost = None, float('inf')
                    action_start_pos = self.nav_nodes[current_key]['pos']
                    for node_key_in_group, node_data in self.nav_nodes.items():
                        if node_data.get('group') == target_group:
                            # [v12.8.8 수정] 착지 지점 후보에서 사다리 입/출구 제외
                            node_type = node_data.get('type')
                            if node_type in ['ladder_entry', 'ladder_exit']:
                                continue

                            landing_pos = node_data['pos']
                            landing_cost = abs(action_start_pos.y() - landing_pos.y()) + abs(action_start_pos.x() - landing_pos.x()) * 0.5
                            if landing_cost < min_landing_cost:
                                min_landing_cost = landing_cost
                                best_landing_node = node_key_in_group
                    if best_landing_node:
                        final_tentative_g_score = tentative_g_score + min_landing_cost
                        if final_tentative_g_score < g_score[best_landing_node]:
                            came_from[best_landing_node] = (current_key, edge_data)
                            g_score[best_landing_node] = final_tentative_g_score
                            landing_node_pos = self.nav_nodes[best_landing_node]['pos']
                            h_score = math.hypot(landing_node_pos.x() - goal_pos.x(), landing_node_pos.y() - goal_pos.y())
                            f_score[best_landing_node] = final_tentative_g_score + h_score
                            heapq.heappush(open_set, (f_score[best_landing_node], best_landing_node))

        return None, float('inf')


    def _reconstruct_path(self, came_from, current_key, start_key):
        """
        v12.8.1: A* 탐색 결과를 바탕으로 최종 경로 리스트를 재구성합니다.
        가상 시작 노드("__START__")를 처리합니다.
        """
        path = [current_key]
        
        while current_key in came_from:
            prev_key, _ = came_from[current_key]
            
            # [수정] 가상 시작 노드에 도달하면 경로 재구성을 중단합니다.
            if prev_key == start_key:
                break
            
            path.insert(0, prev_key)
            current_key = prev_key
            
        return path

    def _find_path_astar(self, start_pos, start_group, goal_key):
        """v12.8.1: A* 알고리즘을 수정하여, 플레이어의 실제 위치(가상 노드)에서 탐색을 시작합니다."""
        if goal_key not in self.nav_nodes:
            print(f"[A* DEBUG] 목표 노드가 nav_nodes에 없습니다. 목표: {goal_key}")
            return None, float('inf')

        import heapq
        
        goal_pos = self.nav_nodes[goal_key]['pos']

        open_set = []
        came_from = {}
        g_score = {key: float('inf') for key in self.nav_nodes}
        f_score = {key: float('inf') for key in self.nav_nodes}

        # --- [핵심 변경] 시작 단계: start_pos에서 연결된 모든 walkable 노드를 open_set에 추가 ---
        nodes_in_start_group = [
            key for key, data in self.nav_nodes.items()
            if data.get('walkable', False) and data.get('group') == start_group
        ]

        if not nodes_in_start_group:
            print(f"[A* DEBUG] 시작 그룹 '{start_group}' 내에 walkable 노드가 없습니다.")
            return None, float('inf')
        
        print("\n" + "="*20 + " A* 탐색 시작 (동적 확장) " + "="*20)
        print(f"[A* DEBUG] 가상 시작점: {start_pos.x():.1f}, {start_pos.y():.1f} (그룹: '{start_group}')")
        print(f"[A* DEBUG] 목표: '{self.nav_nodes[goal_key]['name']}' ({goal_key})")
        
        for node_key in nodes_in_start_group:
            node_pos = self.nav_nodes[node_key]['pos']
            # 비용 = 현재 위치에서 해당 노드까지의 직선 x축 거리 (걷기 비용과 동일하게)
            cost_to_node = abs(start_pos.x() - node_pos.x())
            
            g_score[node_key] = cost_to_node
            h_score = math.hypot(node_pos.x() - goal_pos.x(), node_pos.y() - goal_pos.y())
            f_score[node_key] = cost_to_node + h_score
            heapq.heappush(open_set, (f_score[node_key], node_key))
            came_from[node_key] = ("__START__", None) # 가상 시작 노드임을 표시
            
            print(f"[A* DEBUG]  - 초기 탐색 노드: '{self.nav_nodes[node_key]['name']}' | G: {cost_to_node:.1f} | H: {h_score:.1f} | F: {f_score[node_key]:.1f}")
        
        # --- 이하 A* 메인 루프 (기존과 거의 동일, 디버그 로그 제거) ---
        iter_count = 0
        while open_set:
            iter_count += 1
            if iter_count > 2000:
                print("[A* DEBUG] ERROR: 탐색 반복 횟수가 2000회를 초과했습니다. 탐색을 중단합니다.")
                break
                
            _, current_key = heapq.heappop(open_set)

            if current_key == goal_key:
                path = self._reconstruct_path(came_from, current_key, "__START__")
                return path, g_score[goal_key]

            # 이웃 노드 탐색
            for neighbor_key, edge_data in self.nav_graph.get(current_key, {}).items():
                cost = edge_data.get('cost', float('inf'))
                tentative_g_score = g_score[current_key] + cost
                
                # Case 1: 이웃이 실제 노드인 경우
                if neighbor_key in self.nav_nodes:
                    if tentative_g_score < g_score[neighbor_key]:
                        came_from[neighbor_key] = (current_key, edge_data)
                        g_score[neighbor_key] = tentative_g_score
                        neighbor_pos = self.nav_nodes[neighbor_key]['pos']
                        h_score = math.hypot(neighbor_pos.x() - goal_pos.x(), neighbor_pos.y() - goal_pos.y())
                        f_score[neighbor_key] = tentative_g_score + h_score
                        heapq.heappush(open_set, (f_score[neighbor_key], neighbor_key))
                
                # Case 2: 이웃이 가상 액션 노드인 경우
                elif 'target_group' in edge_data:
                    target_group = edge_data['target_group']
                    best_landing_node, min_landing_cost = None, float('inf')
                    action_start_pos = self.nav_nodes[current_key]['pos']
                    for node_key_in_group, node_data in self.nav_nodes.items():
                        if node_data.get('group') == target_group:
                            landing_pos = node_data['pos']
                            landing_cost = abs(action_start_pos.y() - landing_pos.y()) + abs(action_start_pos.x() - landing_pos.x()) * 0.5
                            if landing_cost < min_landing_cost:
                                min_landing_cost = landing_cost
                                best_landing_node = node_key_in_group
                    if best_landing_node:
                        final_tentative_g_score = tentative_g_score + min_landing_cost
                        if final_tentative_g_score < g_score[best_landing_node]:
                            came_from[best_landing_node] = (current_key, edge_data)
                            g_score[best_landing_node] = final_tentative_g_score
                            landing_node_pos = self.nav_nodes[best_landing_node]['pos']
                            h_score = math.hypot(landing_node_pos.x() - goal_pos.x(), landing_node_pos.y() - goal_pos.y())
                            f_score[best_landing_node] = final_tentative_g_score + h_score
                            heapq.heappush(open_set, (f_score[best_landing_node], best_landing_node))

        return None, float('inf')


    # === v12.0.0: 추가 끝 ===

    def _assign_dynamic_names(self):
        """
        모든 지형, 층 이동 오브젝트, 점프 링크에 동적 이름을 부여합니다.
        이 이름은 저장되지 않고 런타임에 생성됩니다.
        """
        if not self.geometry_data:
            return

        # --- 1. 지형선 그룹화 및 이름 부여 ---
        terrain_lines = self.geometry_data.get("terrain_lines", [])
        lines_by_id = {line['id']: line for line in terrain_lines}
        line_id_to_group_name = {}

        if terrain_lines:
            # 연결된 지형선을 찾기 위한 그래프 생성
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

            # BFS로 연결된 그룹(컴포넌트) 찾기
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

            # 층별로 그룹을 나누고 x축 기준으로 정렬하여 이름 부여
            groups_by_floor = defaultdict(list)
            for group in all_groups:
                if group:
                    floor = group[0].get('floor', 0)
                    groups_by_floor[floor].append(group)
            
            for floor, groups in groups_by_floor.items():
                # 각 그룹의 중심 x좌표를 계산하여 정렬
                sorted_groups = sorted(groups, key=lambda g: sum(p[0] for line in g for p in line['points']) / sum(len(line['points']) for line in g))
                
                for i, group in enumerate(sorted_groups):
                    group_name = f"{floor}층_{chr(ord('A') + i)}"
                    for line in group:
                        line['dynamic_name'] = group_name
                        line_id_to_group_name[line['id']] = group_name

        # --- 2. 층 이동 오브젝트 이름 부여 ---
        transition_objects = self.geometry_data.get("transition_objects", [])
        if transition_objects:
            # 먼저 모든 지형선 ID와 층/동적이름을 매핑
            line_info_map = {
                line['id']: {'floor': line.get('floor', 0), 'name': line.get('dynamic_name', '')}
                for line in terrain_lines
            }

            # {아래층그룹_위층그룹: [오브젝트1, 오브젝트2]} 형식으로 그룹화
            objs_by_connection = defaultdict(list)
            for obj in transition_objects:
                start_line_id = obj.get('start_line_id')
                end_line_id = obj.get('end_line_id')

                if start_line_id in line_info_map and end_line_id in line_info_map:
                    start_info = line_info_map[start_line_id]
                    end_info = line_info_map[end_line_id]

                    # 층 번호를 기준으로 아래/위 결정
                    if start_info['floor'] < end_info['floor']:
                        lower_name, upper_name = start_info['name'], end_info['name']
                    else:
                        lower_name, upper_name = end_info['name'], start_info['name']
                    
                    connection_key = f"{lower_name}_{upper_name}"
                    objs_by_connection[connection_key].append(obj)

            # 각 연결 그룹 내에서 x축 기준으로 정렬하여 이름 부여
            for connection_key, objs in objs_by_connection.items():
                sorted_objs = sorted(objs, key=lambda o: o['points'][0][0])
                for i, obj in enumerate(sorted_objs):
                    obj['dynamic_name'] = f"{connection_key}_{i + 1}"
                    
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
                        start_floor = self._get_floor_from_closest_terrain_data(QPointF(start_pos_tuple[0], start_pos_tuple[1]), terrain_lines)
                    if end_floor is None:
                        end_floor = self._get_floor_from_closest_terrain_data(QPointF(end_pos_tuple[0], end_pos_tuple[1]), terrain_lines)

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
                print(f"Error assigning dynamic names to jump links in MapTab: {e}")

    def cleanup_on_close(self):
        self.save_global_settings()
        if self.detection_thread and self.detection_thread.isRunning():
            self.detection_thread.stop()
            self.detection_thread.wait()
        print("'맵' 탭 정리 완료.")