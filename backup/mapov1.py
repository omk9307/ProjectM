# map.py
# 2025년 08月 16日 09:00 (KST)
# 작성자: Gemini
# 기능: 지형 관리 시스템 고도화 (문맥적 썸네일, 지형별 정확도, 명확한 사용처 표시)
# 설명:
# - v6.0.0: [기능고도화] 핵심 지형 관리 시스템 대폭 개선.
#           - [추가] 문맥적 썸네일: 핵심 지형 등록 시, 지형 조각뿐만 아니라
#             전체 미니맵과 선택 영역을 함께 저장하여 지형의 위치를 직관적으로 파악 가능.
#             (KeyFeatureManagerDialog, Waypoint Editor 모두에 적용)
#           - [변경] 탐지 정확도 설정 주체 변경: 웨이포인트별 설정에서 '핵심 지형'별
#             설정으로 변경하여 중앙에서 효율적으로 관리.
#           - [개선] 사용처 표시 개선: 핵심 지형 관리자에서 사용처를 '[경로명] 웨이포인트명'
#             형식으로 표시하여 중복된 이름의 웨이포인트를 명확히 구분.
#           - [데이터] 위 기능들을 지원하기 위해 map_key_features.json 데이터 구조 변경.
#           - [마이그레이션] 구버전 데이터 구조를 새 구조로 자동 변환하는 기능 추가.
# - v5.0.0: [기능추가] '경로 프로필' 시스템 도입. 하나의 '맵 프로필' 내에서 여러 개의
#           독립적인 웨이포인트 경로(루트)를 생성하고 관리할 수 있도록 구조 변경.
# - v4.0.0: [구조개편] '맵 프로필' 시스템 도입. 각 맵의 설정(미니맵 범위, 웨이포인트, 핵심 지형)을
#           독립적으로 관리할 수 있도록 모든 파일 I/O 및 UI 로직을 재설계.
# - v3.6.0: 핵심 지형 관리 기능 강화 및 시각화/로깅 개선.

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

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QSpinBox, QDialog, QDialogButtonBox, QListWidget,
    QInputDialog, QListWidgetItem, QDoubleSpinBox, QAbstractItemView,
    QLineEdit, QRadioButton, QButtonGroup, QGroupBox, QComboBox, QCheckBox
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint, QRectF, QPointF, QSize

try:
    from Learning import ScreenSnipper
except ImportError:
    class ScreenSnipper(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            QMessageBox.critical(self, "오류", "Learning.py 모듈을 찾을 수 없어\n화면 영역 지정 기능을 사용할 수 없습니다.")
        def exec(self): return 0
        def get_roi(self): return QRect(0, 0, 100, 100)

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

# --- 위젯 클래스 ---
# --- v7.0.0 (Step 2) 새로운 알고리즘 클래스 ---
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
class Stitcher:
    def __init__(self, key_features, all_waypoints):
        self.key_features = key_features
        self.all_waypoints = all_waypoints
        self.waypoints_map = {wp['name']: wp for wp in all_waypoints}

    def _get_feature_coords_in_waypoint(self, waypoint_name, feature_id):
        """특정 웨이포인트의 미니맵 내에서 특정 핵심 지형의 좌표를 찾습니다."""
        waypoint = self.waypoints_map.get(waypoint_name)
        if not waypoint or 'image_base64' not in waypoint:
            return None

        img_data = base64.b64decode(waypoint['image_base64'])
        np_arr = np.frombuffer(img_data, np.uint8)
        wp_map_gray = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)

        feature_data = self.key_features.get(feature_id)
        if not feature_data:
            return None
            
        f_img_data = base64.b64decode(feature_data['image_base64'])
        f_np_arr = np.frombuffer(f_img_data, np.uint8)
        template = cv2.imdecode(f_np_arr, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return None

        res = cv2.matchTemplate(wp_map_gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        threshold = feature_data.get('threshold', 0.90)
        if max_val >= threshold:
            return max_loc # (x, y) 튜플 반환
        return None

    def stitch_maps(self):
        if not self.all_waypoints:
            return None, {}

        # 1. 데이터 준비
        feature_to_waypoints = {}
        for wp in self.all_waypoints:
            for feature_link in wp.get('key_feature_ids', []):
                feature_id = feature_link['id']
                if feature_id not in feature_to_waypoints:
                    feature_to_waypoints[feature_id] = []
                feature_to_waypoints[feature_id].append(wp['name'])

        # 2. 위치 계산 (BFS)
        map_offsets = {}
        placed_maps = set()
        queue = []

        start_wp_name = self.all_waypoints[0]['name']
        map_offsets[start_wp_name] = QPoint(0, 0)
        placed_maps.add(start_wp_name)
        queue.append(start_wp_name)

        while queue:
            current_wp_name = queue.pop(0)
            current_wp_data = self.waypoints_map[current_wp_name]
            
            for feature_link in current_wp_data.get('key_feature_ids', []):
                feature_id = feature_link['id']
                
                # 이 지형을 공유하는 다른 웨이포인트 찾기
                for neighbor_wp_name in feature_to_waypoints.get(feature_id, []):
                    if neighbor_wp_name not in placed_maps:
                        coords_in_current = self._get_feature_coords_in_waypoint(current_wp_name, feature_id)
                        coords_in_neighbor = self._get_feature_coords_in_waypoint(neighbor_wp_name, feature_id)

                        if coords_in_current and coords_in_neighbor:
                            current_offset = map_offsets[current_wp_name]
                            
                            # 오프셋 계산
                            offset_x = current_offset.x() + coords_in_current[0] - coords_in_neighbor[0]
                            offset_y = current_offset.y() + coords_in_current[1] - coords_in_neighbor[1]
                            
                            map_offsets[neighbor_wp_name] = QPoint(offset_x, offset_y)
                            placed_maps.add(neighbor_wp_name)
                            queue.append(neighbor_wp_name)

        # 3. 전체 캔버스 크기 및 전역 오프셋 계산
        if not map_offsets: return None, {}
        
        min_x, max_x, min_y, max_y = 0, 0, 0, 0
        for name, offset in map_offsets.items():
            img_data = base64.b64decode(self.waypoints_map[name]['image_base64'])
            pixmap = QPixmap(); pixmap.loadFromData(img_data)
            min_x = min(min_x, offset.x())
            min_y = min(min_y, offset.y())
            max_x = max(max_x, offset.x() + pixmap.width())
            max_y = max(max_y, offset.y() + pixmap.height())

        canvas_width = max_x - min_x
        canvas_height = max_y - min_y
        global_offset = QPoint(-min_x, -min_y)

        # 4. 이미지 렌더링
        full_map_pixmap = QPixmap(canvas_width, canvas_height)
        full_map_pixmap.fill(Qt.GlobalColor.black)
        painter = QPainter(full_map_pixmap)
        
        for name, offset in map_offsets.items():
            img_data = base64.b64decode(self.waypoints_map[name]['image_base64'])
            pixmap = QPixmap(); pixmap.loadFromData(img_data)
            painter.drawPixmap(offset + global_offset, pixmap)
        painter.end()
        
        # 5. 모든 요소의 절대 좌표 계산
        coordinates = {
            'waypoints': {},
            'key_features': {}
        }
        for name, offset in map_offsets.items():
            wp_data = self.waypoints_map[name]
            rect_norm = wp_data['rect_normalized']
            img_data = base64.b64decode(wp_data['image_base64'])
            pixmap = QPixmap(); pixmap.loadFromData(img_data)
            w, h = pixmap.width(), pixmap.height()
            
            wp_abs_rect = QRect(
                offset.x() + global_offset.x() + int(rect_norm[0] * w),
                offset.y() + global_offset.y() + int(rect_norm[1] * h),
                int(rect_norm[2] * w),
                int(rect_norm[3] * h)
            )
            coordinates['waypoints'][name] = {'rect': wp_abs_rect, 'route_name': wp_data['route_name']}

            for feature_link in wp_data.get('key_feature_ids', []):
                feature_id = feature_link['id']
                if feature_id not in coordinates['key_features']:
                    coords_in_wp = self._get_feature_coords_in_waypoint(name, feature_id)
                    if coords_in_wp:
                        f_data = self.key_features[feature_id]
                        f_rect_coords = f_data['rect_in_context']
                        f_w, f_h = f_rect_coords[2], f_rect_coords[3]

                        kf_abs_rect = QRect(
                            offset.x() + global_offset.x() + coords_in_wp[0],
                            offset.y() + global_offset.y() + coords_in_wp[1],
                            f_w, f_h
                        )
                        coordinates['key_features'][feature_id] = {'rect': kf_abs_rect}

        return full_map_pixmap, coordinates
    
class FeatureCropDialog(QDialog):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("새로운 핵심 지형 추가 (영역을 드래그하세요)")
        self.base_pixmap = pixmap
        self.drawing = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        layout = QVBoxLayout(self)
        self.canvas_label = CroppingLabel(self.base_pixmap, self)
        self.canvas_label.setCursor(Qt.CursorShape.CrossCursor)
        self.canvas_label.mousePressEvent = self.canvas_mousePressEvent
        self.canvas_label.mouseMoveEvent = self.canvas_mouseMoveEvent
        self.canvas_label.mouseReleaseEvent = self.canvas_mouseReleaseEvent
        layout.addWidget(self.canvas_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setFixedSize(self.base_pixmap.size().width() + 40, self.base_pixmap.size().height() + 80)
    def canvas_mousePressEvent(self, event): self.drawing = True; self.start_point = event.pos(); self.end_point = event.pos(); self.canvas_label.update()
    def canvas_mouseMoveEvent(self, event):
        if self.drawing: self.end_point = event.pos(); self.canvas_label.update()
    def canvas_mouseReleaseEvent(self, event): self.drawing = False; self.canvas_label.update()
    def get_selected_rect(self): return QRect(self.start_point, self.end_point).normalized()
    
# --- v7.0.0 (Step 3) 새로운 캔버스 클래스 ---
# --- v7.0.0 (Step 3) 새로운 캔버스 클래스 ---
class MapCanvas(QWidget):
    shape_drawn = pyqtSignal(dict) # 그린 객체 정보를 전달하기 위한 시그널

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.coordinates = {}
        self.layer_visibility = {}
        self.terrain_data = []
        self.layer_objects = []

        self.zoom_factor = 1.0
        self.offset = QPointF(0, 0)
        
        self.panning = False
        self.pan_start_pos = QPoint()
        
        # 그리기 관련 변수
        self.mode = 'select' # 'select', 'draw_line', 'draw_rect'
        self.drawing = False
        self.start_point = QPointF()
        self.current_point = QPointF()

        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #2E2E2E;")

    def set_data(self, pixmap, coordinates, terrain_data, layer_objects):
        self.pixmap = pixmap
        self.coordinates = coordinates
        self.terrain_data = terrain_data
        self.layer_objects = layer_objects
        self.fit_to_view()
        self.update()

    def set_layer_visibility(self, visibility_dict):
        self.layer_visibility = visibility_dict
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        if 'draw' in mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _to_world_coords(self, view_pos):
        """화면 좌표(클릭 위치)를 지도 좌표(절대 좌표)로 변환합니다."""
        if self.zoom_factor == 0: return QPointF(0, 0)
        return (view_pos - self.offset) / self.zoom_factor

    def fit_to_view(self):
        if self.pixmap.isNull(): return
        canvas_size = self.size()
        pixmap_size = self.pixmap.size()
        if canvas_size.width() == 0 or canvas_size.height() == 0: return
        w_ratio = canvas_size.width() / pixmap_size.width()
        h_ratio = canvas_size.height() / pixmap_size.height()
        self.zoom_factor = min(w_ratio, h_ratio) * 0.95
        scaled_w = pixmap_size.width() * self.zoom_factor
        scaled_h = pixmap_size.height() * self.zoom_factor
        self.offset = QPointF((canvas_size.width() - scaled_w) / 2, (canvas_size.height() - scaled_h) / 2)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.pixmap.isNull():
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "여기에 전체 지도가 표시됩니다.\n'전체 미니맵 자동 생성'을 눌러 시작하세요.")
            return

        painter.translate(self.offset)
        painter.scale(self.zoom_factor, self.zoom_factor)

        # 1. 배경 그리기
        if self.layer_visibility.get('background', True):
            painter.drawPixmap(0, 0, self.pixmap)

        # 2. 핵심 지형 그리기
        if self.layer_visibility.get('features', True) and 'key_features' in self.coordinates:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.cyan, 2 / self.zoom_factor))
            painter.setBrush(QBrush(QColor(0, 255, 255, 50)))
            font = painter.font(); font.setPointSizeF(10 / self.zoom_factor); painter.setFont(font)
            for feature_id, data in self.coordinates['key_features'].items():
                painter.drawRect(data['rect'])
                painter.drawText(data['rect'].topLeft() + QPoint(2, 12), feature_id)
            painter.restore()

        # 3. 웨이포인트 그리기
        if self.layer_visibility.get('waypoints', True) and 'waypoints' in self.coordinates:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.green, 2 / self.zoom_factor))
            painter.setBrush(QBrush(QColor(0, 255, 0, 50)))
            font = painter.font(); font.setPointSizeF(10 / self.zoom_factor); painter.setFont(font)
            for wp_name, data in self.coordinates['waypoints'].items():
                painter.drawRect(data['rect'])
                painter.drawText(data['rect'].topLeft() - QPoint(0, 2), f"[{data['route_name']}] {wp_name}")
            painter.restore()

        # 4. 지형(선) 그리기
        if self.layer_visibility.get('terrain', True) and self.terrain_data:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.yellow, 3 / self.zoom_factor))
            for line in self.terrain_data:
                points = line.get('points', [])
                if len(points) == 2:
                    p1 = QPointF(points[0][0], points[0][1])
                    p2 = QPointF(points[1][0], points[1][1])
                    painter.drawLine(p1, p2)
            painter.restore()

        # 5. 층 이동 오브젝트(사각형) 그리기
        if self.layer_visibility.get('objects', True) and self.layer_objects:
            painter.save()
            painter.setPen(QPen(Qt.GlobalColor.magenta, 2 / self.zoom_factor))
            painter.setBrush(QBrush(QColor(255, 0, 255, 50)))
            for rect_data in self.layer_objects:
                points = rect_data.get('points', [])
                if len(points) == 4:
                    painter.drawRect(QRectF(*points))
            painter.restore()

        # 6. 현재 그리고 있는 객체 그리기
        if self.drawing:
            painter.save()
            pen = QPen(Qt.GlobalColor.red, 2 / self.zoom_factor, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            if self.mode == 'draw_line':
                painter.drawLine(self.start_point, self.current_point)
            elif self.mode == 'draw_rect':
                painter.drawRect(QRectF(self.start_point, self.current_point).normalized())
            painter.restore()

    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        if event.angleDelta().y() > 0: zoom_factor = zoom_in_factor
        else: zoom_factor = zoom_out_factor
        old_zoom = self.zoom_factor
        self.zoom_factor *= zoom_factor
        mouse_pos = event.position()
        self.offset = mouse_pos - (mouse_pos - self.offset) * (self.zoom_factor / old_zoom)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True
            self.pan_start_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.LeftButton and 'draw' in self.mode:
            self.drawing = True
            self.start_point = self._to_world_coords(event.position())
            self.current_point = self.start_point

    def mouseMoveEvent(self, event):
        if self.panning:
            delta = event.position() - self.pan_start_pos
            self.offset += delta
            self.pan_start_pos = event.position()
            self.update()
        elif self.drawing:
            self.current_point = self._to_world_coords(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor if self.mode == 'select' else Qt.CursorShape.CrossCursor)
        elif event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            end_point = self._to_world_coords(event.position())
            
            if self.mode == 'draw_line':
                line_data = {'type': 'line', 'points': [
                    [self.start_point.x(), self.start_point.y()],
                    [end_point.x(), end_point.y()]
                ]}
                self.shape_drawn.emit(line_data)
            elif self.mode == 'draw_rect':
                rect = QRectF(self.start_point, end_point).normalized()
                rect_data = {'type': 'rect', 'points': [
                    rect.x(), rect.y(), rect.width(), rect.height()
                ]}
                self.shape_drawn.emit(rect_data)
            self.update()
            
class MapEditorDialog(QDialog):
    def __init__(self, key_features, all_waypoints, terrain_data, layer_objects, parent=None):
        super().__init__(parent)
        self.parent_tab = parent
        self.setWindowTitle("미니맵 지형 편집기")
        self.setMinimumSize(1000, 800)
        
        # 데이터 저장
        self.key_features = key_features
        self.all_waypoints = all_waypoints
        self.terrain_data = terrain_data
        self.layer_objects = layer_objects
        
        # 메인 레이아웃
        main_layout = QHBoxLayout(self)

        # 왼쪽: 툴바 및 레이어 제어판
        left_panel_layout = QVBoxLayout()

        # 툴바 그룹
        toolbar_group = QGroupBox("도구")
        toolbar_layout = QVBoxLayout()
        self.btn_generate_map = QPushButton("전체 미니맵 자동 생성")
        self.btn_generate_map.clicked.connect(self.generate_full_map)
        self.btn_terrain_mode = QPushButton("지형 입력 (선)")
        self.btn_object_mode = QPushButton("층 이동 오브젝트 (사각형)")
        self.btn_select_mode = QPushButton("선택/이동")
        
        self.btn_terrain_mode.setCheckable(True)
        self.btn_object_mode.setCheckable(True)
        self.btn_select_mode.setCheckable(True)
        self.btn_select_mode.setChecked(True)

        self.tool_button_group = QButtonGroup(self)
        self.tool_button_group.setExclusive(True) # <<-- 한 번에 하나만 선택되도록 설정

        self.tool_button_group.addButton(self.btn_select_mode, 0)
        self.tool_button_group.addButton(self.btn_terrain_mode, 1)
        self.tool_button_group.addButton(self.btn_object_mode, 2)

        self.tool_button_group.idClicked.connect(self.set_canvas_mode) # <<-- buttonClicked를 idClicked로 변경

        toolbar_layout.addWidget(self.btn_generate_map)
        toolbar_layout.addWidget(self.btn_select_mode)
        toolbar_layout.addWidget(self.btn_terrain_mode)
        toolbar_layout.addWidget(self.btn_object_mode)
        toolbar_group.setLayout(toolbar_layout)

        # 레이어 제어판 그룹
        layer_group = QGroupBox("레이어 보기")
        layer_layout = QVBoxLayout()
        self.chk_show_background = QCheckBox("실제 미니맵 배경")
        self.chk_show_features = QCheckBox("핵심 지형")
        self.chk_show_waypoints = QCheckBox("웨이포인트")
        self.chk_show_terrain = QCheckBox("지형")
        self.chk_show_objects = QCheckBox("층 이동 오브젝트")
        
        self.layer_checkboxes = {
            'background': self.chk_show_background, 'features': self.chk_show_features,
            'waypoints': self.chk_show_waypoints, 'terrain': self.chk_show_terrain,
            'objects': self.chk_show_objects
        }

        for chk in self.layer_checkboxes.values():
            chk.setChecked(True)
            chk.stateChanged.connect(self.update_canvas_layers)

        layer_layout.addWidget(self.chk_show_background); layer_layout.addWidget(self.chk_show_features)
        layer_layout.addWidget(self.chk_show_waypoints); layer_layout.addWidget(self.chk_show_terrain)
        layer_layout.addWidget(self.chk_show_objects)
        layer_group.setLayout(layer_layout)

        left_panel_layout.addWidget(toolbar_group)
        left_panel_layout.addWidget(layer_group)
        left_panel_layout.addStretch(1)

        # 중앙: 캔버스 영역
        canvas_group = QGroupBox("지도 캔버스 (마우스 휠: 줌, 가운데 버튼 드래그: 이동)")
        canvas_layout = QVBoxLayout()
        self.canvas = MapCanvas()
        self.canvas.shape_drawn.connect(self.on_shape_drawn)
        canvas_layout.addWidget(self.canvas)
        canvas_group.setLayout(canvas_layout)

        # 하단: 저장/취소 버튼
        bottom_layout = QVBoxLayout()
        bottom_layout.addWidget(canvas_group)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        bottom_layout.addWidget(self.button_box)

        main_layout.addLayout(left_panel_layout, 1)
        main_layout.addLayout(bottom_layout, 4)

    def generate_full_map(self):
        """'전체 미니맵 자동 생성' 버튼에 연결된 슬롯."""
        if not self.all_waypoints:
            QMessageBox.warning(self, "오류", "전체 지도를 생성하려면 하나 이상의 웨이포인트가 필요합니다.")
            return

        # 임시 메시지 표시
        temp_pixmap = QPixmap(self.canvas.size())
        temp_pixmap.fill(QColor("#2E2E2E"))
        painter = QPainter(temp_pixmap)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(temp_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "전체 미니맵 생성 중... 잠시만 기다려주세요.")
        painter.end()
        self.canvas.pixmap = temp_pixmap # 임시 pixmap 설정
        self.canvas.update()
        QApplication.processEvents()

        stitcher = Stitcher(self.key_features, self.all_waypoints)
        full_map_pixmap, coordinates = stitcher.stitch_maps()

        if full_map_pixmap:
            self.canvas.set_data(full_map_pixmap, coordinates, self.terrain_data, self.layer_objects)
            self.update_canvas_layers() # 초기 레이어 상태 전달
        else:
            temp_pixmap.fill(QColor("#2E2E2E"))
            painter.begin(temp_pixmap)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(temp_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "지도 생성에 실패했습니다.\n웨이포인트 간 공통 핵심 지형이 부족할 수 있습니다.")
            painter.end()
            self.canvas.pixmap = temp_pixmap
            self.canvas.update()

    def set_canvas_mode(self, button_id):
        """툴바 버튼 ID 클릭 시 호출되어 캔버스의 모드를 변경합니다."""
        # idClicked 시그널이 직접 정수 ID를 전달
        if button_id == 0: self.canvas.set_mode('select')
        elif button_id == 1: self.canvas.set_mode('draw_line')
        elif button_id == 2: self.canvas.set_mode('draw_rect')

    def on_shape_drawn(self, shape_data):
        if shape_data['type'] == 'line':
            self.terrain_data.append(shape_data)
        elif shape_data['type'] == 'rect':
            self.layer_objects.append(shape_data)
        self.update_canvas_layers() # 캔버스를 다시 그려서 추가된 객체 표시

    def update_canvas_layers(self):
        visibility = {name: chk.isChecked() for name, chk in self.layer_checkboxes.items()}
        self.canvas.set_layer_visibility(visibility)

    def get_edited_data(self):
        """다이얼로그가 닫힐 때 MapTab으로 데이터를 반환합니다."""
        return self.terrain_data, self.layer_objects

    def update_canvas_layers(self):
        """체크박스 상태가 변경될 때 호출되어 캔버스의 레이어 가시성을 업데이트합니다."""
        visibility = {name: chk.isChecked() for name, chk in self.layer_checkboxes.items()}
        self.canvas.set_layer_visibility(visibility)
        
    def draw_canvas(self):
        """저장된 지도 데이터와 레이어 설정에 따라 캔버스를 다시 그립니다."""
        if not self.full_map_pixmap:
            return

        # 배경 그리기
        if self.chk_show_background.isChecked():
            # 원본 지도 이미지를 복사하여 사용
            canvas_pixmap = self.full_map_pixmap.copy()
        else:
            # 배경 없는 버전을 위해 검은색 배경 생성
            canvas_pixmap = QPixmap(self.full_map_pixmap.size())
            canvas_pixmap.fill(Qt.GlobalColor.black)

        painter = QPainter(canvas_pixmap)
        
        # 핵심 지형 그리기
        if self.chk_show_features.isChecked() and 'key_features' in self.coordinates:
            painter.setPen(QPen(Qt.GlobalColor.cyan, 1))
            painter.setBrush(QBrush(QColor(0, 255, 255, 50)))
            for feature_id, data in self.coordinates['key_features'].items():
                painter.drawRect(data['rect'])
                painter.drawText(data['rect'].topLeft() + QPoint(2, 12), feature_id)
        
        # 웨이포인트 그리기
        if self.chk_show_waypoints.isChecked() and 'waypoints' in self.coordinates:
            painter.setPen(QPen(Qt.GlobalColor.green, 1))
            painter.setBrush(QBrush(QColor(0, 255, 0, 50)))
            for wp_name, data in self.coordinates['waypoints'].items():
                painter.drawRect(data['rect'])
                painter.drawText(data['rect'].topLeft() - QPoint(0, 2), wp_name)

        # TODO: 지형, 층 이동 오브젝트 그리기 (3단계에서 구현)

        painter.end()
        
        # QLabel 크기에 맞춰 스케일링하여 표시
        self.canvas_label.setPixmap(canvas_pixmap.scaled(
            self.canvas_label.size(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        ))

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
        self.feature_list_widget.setIconSize(QSize(128, 128)) # 썸네일 크기 증가
        self.feature_list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.feature_list_widget.itemSelectionChanged.connect(self.show_feature_details)
        button_layout = QHBoxLayout()
        self.add_feature_btn = QPushButton("새 지형 추가")
        self.add_feature_btn.clicked.connect(self.add_new_feature)
        self.update_links_btn = QPushButton("전체 웨이포인트 갱신")
        self.update_links_btn.setToolTip("현재 프로필의 모든 웨이포인트의 미니맵을 다시 스캔하여\n핵심 지형과의 연결을 최신화합니다.")
        self.update_links_btn.clicked.connect(self.on_update_all_clicked)
        button_layout.addWidget(self.add_feature_btn)
        button_layout.addWidget(self.update_links_btn)
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
        self.rename_button = QPushButton("이름 변경")
        self.rename_button.clicked.connect(self.rename_selected_feature)
        self.rename_button.setEnabled(False)
        self.delete_button = QPushButton("선택한 지형 삭제")
        self.delete_button.clicked.connect(self.delete_selected_feature)
        self.delete_button.setEnabled(False)
        control_buttons_layout.addWidget(self.rename_button)
        control_buttons_layout.addWidget(self.delete_button)
        
        right_layout.addWidget(self.image_preview_label, 1)
        right_layout.addLayout(info_layout)
        right_layout.addWidget(self.usage_label)
        right_layout.addWidget(self.usage_list_widget, 1)
        right_layout.addLayout(control_buttons_layout)
        right_group.setLayout(right_layout)
        
        main_layout.addWidget(left_group, 2)
        main_layout.addWidget(right_group, 1)
        
    def on_update_all_clicked(self):
        """'전체 웨이포인트 갱신' 버튼 클릭 시 호출되는 슬롯."""
        # MapTab의 갱신 메서드를 호출하고 성공 여부를 받음
        success = self.parent_map_tab.update_all_waypoints_with_features()

        if success:
            # 성공했다면, MapTab으로부터 최신 웨이포인트 데이터를 다시 가져와 내부 데이터를 갱신
            self.all_waypoints = self.parent_map_tab.get_all_waypoints_with_route_name()
            
            # 현재 선택된 아이템의 상세 정보를 다시 로드하여 UI를 새로고침
            self.show_feature_details()

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
        else: # 하위 호환
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
        crop_dialog = FeatureCropDialog(pixmap, self)
        if crop_dialog.exec():
            rect = crop_dialog.get_selected_rect()
            if rect.width() < 5 or rect.height() < 5:
                QMessageBox.warning(self, "오류", "너무 작은 영역은 지형으로 등록할 수 없습니다.")
                return

            # 문맥적 썸네일 데이터 생성
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
                'threshold': 0.85 # 기본값
            }
            
            self.parent_map_tab.save_profile_data()
            self.parent_map_tab.update_general_log(f"새 핵심 지형 '{new_id}'가 추가되었습니다.", "green")
            self.populate_feature_list()
            
            # 새로 추가된 지형이 선택되도록 함
            for i in range(self.feature_list_widget.count()):
                item = self.feature_list_widget.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == new_id:
                    item.setSelected(True)
                    break
                    
            # 사용자에게 즉시 갱신할지 물어봄
            reply = QMessageBox.question(self, "갱신 확인",
                                        "새로운 핵심 지형이 추가되었습니다.\n"
                                        "즉시 전체 웨이포인트와의 연결을 갱신하시겠습니까?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                # 기존에 만들어둔, UI 갱신까지 책임지는 슬롯을 호출
                self.on_update_all_clicked()

    def populate_feature_list(self):
        self.feature_list_widget.clear()
        sorted_keys = sorted(self.key_features.keys(), key=lambda x: int(x[1:]) if x.startswith("P") and x[1:].isdigit() else float('inf'))
        for feature_id in sorted_keys:
            data = self.key_features[feature_id]
            try:
                thumbnail = self._create_context_thumbnail(data)
                item = QListWidgetItem(QIcon(thumbnail), feature_id)
                item.setData(Qt.ItemDataRole.UserRole, feature_id)
                self.feature_list_widget.addItem(item)
            except Exception as e: print(f"지형 로드 오류 (ID: {feature_id}): {e}")

    def show_feature_details(self):
        selected_items = self.feature_list_widget.selectedItems()
        if not selected_items:
            self.delete_button.setEnabled(False)
            self.rename_button.setEnabled(False)
            self.threshold_spinbox.setEnabled(False)
            return
        
        item = selected_items[0]
        feature_id = item.data(Qt.ItemDataRole.UserRole)
        feature_data = self.key_features.get(feature_id)
        if not feature_data: return

        # 미리보기 이미지 업데이트
        pixmap = self._create_context_thumbnail(feature_data)
        self.image_preview_label.setPixmap(pixmap.scaled(self.image_preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        
        # 정보 업데이트
        self.info_label.setText(f"<b>이름:</b> {feature_id}")
        
        self.threshold_spinbox.blockSignals(True)
        self.threshold_spinbox.setValue(feature_data.get('threshold', 0.85))
        self.threshold_spinbox.setEnabled(True)
        self.threshold_spinbox.blockSignals(False)

        # 사용처 목록 업데이트
        self.usage_list_widget.clear()
        used_by = [f"[{wp['route_name']}] {wp['name']}" for wp in self.all_waypoints if any(f['id'] == feature_id for f in wp.get('key_feature_ids', []))]
        if used_by: self.usage_list_widget.addItems(used_by)
        else: self.usage_list_widget.addItem("사용하는 웨이포인트 없음")
            
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
        used_by_waypoints = [f"[{wp['route_name']}] {wp['name']}" for wp in self.all_waypoints if any(f['id'] == feature_id for f in wp.get('key_feature_ids', []))]
        warning_message = f"'{feature_id}' 지형을 영구적으로 삭제하시겠습니까?"
        if used_by_waypoints:
            warning_message += "\n\n경고: 이 지형은 아래 웨이포인트에서 사용 중입니다.\n삭제 시, 해당 웨이포인트들의 위치 정확도가 떨어질 수 있습니다.\n\n- " + "\n- ".join(used_by_waypoints)
        reply = QMessageBox.question(self, "삭제 확인", warning_message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            if feature_id in self.key_features: del self.key_features[feature_id]
            for wp in self.all_waypoints:
                if 'key_feature_ids' in wp: wp['key_feature_ids'] = [f for f in wp['key_feature_ids'] if f['id'] != feature_id]
            self.parent_map_tab.save_profile_data()
            self.parent_map_tab.update_general_log(f"핵심 지형 '{feature_id}'가 영구적으로 삭제되었습니다.", "orange")
            self.populate_feature_list(); self.image_preview_label.setText("지형을 선택하세요."); self.info_label.setText("이름: -"); self.usage_list_widget.clear(); self.delete_button.setEnabled(False); self.rename_button.setEnabled(False); self.threshold_spinbox.setEnabled(False)

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
        # ... (이 메서드는 변경 없음)
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
        self.setWindowTitle("웨이포인트 편집")
        self.pixmap = pixmap; self.all_key_features = all_key_features; self.parent_map_tab = parent; initial_data = initial_data or {}
        self.found_features = self.pre_scan_for_features(pixmap)
        layout = QVBoxLayout(self)
        self.canvas = AdvancedWaypointCanvas(pixmap, initial_data.get('rect_normalized'), self.found_features, self)
        layout.addWidget(self.canvas)
        name_layout = QHBoxLayout(); name_layout.addWidget(QLabel("이름:")); self.name_edit = QLineEdit(initial_data.get('name', '')); name_layout.addWidget(self.name_edit); layout.addLayout(name_layout)
        mode_box = QGroupBox("편집 모드 (우클릭으로 공용 지형 영구 삭제)"); mode_layout = QHBoxLayout()
        self.target_radio = QRadioButton("목표 지점 (초록)"); self.feature_radio = QRadioButton("핵심 지형 (주황/파랑)")
        self.target_radio.setChecked(True); self.target_radio.toggled.connect(lambda: self.canvas.set_editing_mode('target')); self.feature_radio.toggled.connect(lambda: self.canvas.set_editing_mode('feature'))
        mode_layout.addWidget(self.target_radio); mode_layout.addWidget(self.feature_radio); mode_box.setLayout(mode_layout); layout.addWidget(mode_box)
        
        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); dialog_buttons.accepted.connect(self.accept); dialog_buttons.rejected.connect(self.reject); layout.addWidget(dialog_buttons)
        self.setFixedSize(pixmap.width() + 40, pixmap.height() + 160)

    def pre_scan_for_features(self, pixmap):
        found = []; q_image = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8); ptr = q_image.bits(); ptr.setsize(q_image.sizeInBytes())
        arr = np.array(ptr).reshape(q_image.height(), q_image.bytesPerLine()); current_map_gray = arr[:, :q_image.width()].copy()
        
        for feature_id, feature_data in self.all_key_features.items():
            try:
                img_data = base64.b64decode(feature_data['image_base64']); np_arr = np.frombuffer(img_data, np.uint8); template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                if template is None: continue
                
                threshold = feature_data.get('threshold', 0.90)
                res = cv2.matchTemplate(current_map_gray, template, cv2.TM_CCOEFF_NORMED)
                
                # 임계값 이상의 모든 위치를 찾음
                loc = np.where(res >= threshold)
                for pt in zip(*loc[::-1]):
                    h, w = template.shape
                    # 중복 방지를 위해 간단한 거리 체크
                    is_duplicate = False
                    for f in found:
                        existing_rect = QRect(*f['rect_in_context'])
                        if (QPoint(pt[0], pt[1]) - existing_rect.topLeft()).manhattanLength() < 10:
                            is_duplicate = True
                            break
                    if not is_duplicate:
                        # rect_in_context 키를 사용하여 픽셀 좌표 리스트를 저장
                        found.append({'id': feature_id, 'rect_in_context': [pt[0], pt[1], w, h]})

            except Exception as e: print(f"Pre-scan error for feature {feature_id}: {e}")
        return found

    def get_waypoint_data(self):
        target_rect = self.canvas.normalize_rect(self.canvas.target_rect)
        if not target_rect: QMessageBox.warning(self, "저장 불가", "목표 지점(초록색)을 설정해야 합니다."); return None, None, None, None
        final_features_on_canvas = self.canvas.existing_features_data; newly_drawn_features = self.canvas.newly_drawn_features; deleted_feature_ids = self.canvas.deleted_feature_ids
        waypoint_data = {'name': self.name_edit.text(), 'rect_normalized': target_rect}
        return waypoint_data, final_features_on_canvas, newly_drawn_features, deleted_feature_ids

class AnchorDetectionThread(QThread):
    frame_ready = pyqtSignal(QImage, list, list, str)
    navigation_updated = pyqtSignal(str, str, str)
    status_updated = pyqtSignal(str, str)
    waypoints_updated = pyqtSignal(dict)
    correction_status = pyqtSignal(str, str, list)
    features_detected = pyqtSignal(list)
    initial_position_ready = pyqtSignal(dict, tuple)
    
    def __init__(self, minimap_region, diff_threshold, waypoints_data, all_key_features):
        super().__init__()
        self.is_running = True; self.minimap_region = minimap_region; self.diff_threshold = float(diff_threshold); self.prev_frame_gray = None
        self.all_key_features = all_key_features; self.waypoints = self.prepare_waypoints(waypoints_data)
        self.target_index = 0; self.is_path_forward = True; self.initial_signal_sent = False
        
    def set_target_index(self, index): self.target_index = index
    def set_path_direction(self, is_forward): self.is_path_forward = is_forward
    
    def prepare_waypoints(self, waypoints_data):
        templates = []
        for wp in waypoints_data:
            try: 
                templates.append({'name': wp['name'], 'rect_normalized': wp.get('rect_normalized'), 'key_feature_ids': wp.get('key_feature_ids', [])})
            except Exception as e: print(f"웨이포인트 '{wp.get('name', 'N/A')}' 준비 오류: {e}")
        return templates
        
    def run(self):
        with mss.mss() as sct:
            while self.is_running:
                sct_img = sct.grab(self.minimap_region); curr_frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR); curr_frame_gray = cv2.cvtColor(curr_frame_bgr, cv2.COLOR_BGR2GRAY)
                player_pos, player_rect, my_player_rects = self.find_player_icon(curr_frame_bgr); other_player_rects = self.find_other_player_icons(curr_frame_bgr)
                active_waypoints_data = {}; all_found_features = []
                display_frame_bgr = curr_frame_bgr.copy()
                if self.prev_frame_gray is not None:
                                # --- v6.1.2: Inpaint 로직 최종 수정 (바운딩 박스 전체 사용) ---

                                # 1. 바운딩 박스를 기반으로 마스크 생성
                                all_rects = my_player_rects + other_player_rects
                                comparison_mask = np.zeros(curr_frame_gray.shape, dtype=np.uint8)
                                
                                # Inpaint에 사용할 마지막 바운딩 박스의 크기를 저장
                                last_w, last_h = 0, 0 
                                for x, y, w, h in all_rects:
                                    cv2.rectangle(comparison_mask, (x, y), (x + w, y + h), 255, -1)
                                    last_w, last_h = w, h

                                # 2. 앵커 상태 비교 로직 수행
                                prev_frame_masked = self.prev_frame_gray.copy()
                                curr_frame_masked = curr_frame_gray.copy()
                                prev_frame_masked[comparison_mask != 0] = 0
                                curr_frame_masked[comparison_mask != 0] = 0
                                diff = cv2.absdiff(prev_frame_masked, curr_frame_masked)
                                diff_sum = float(np.sum(diff))
                                
                                if diff_sum < self.diff_threshold: 
                                    self.status_updated.emit(f"앵커 상태 (변화량: {diff_sum:.0f})", "green" if diff_sum < self.diff_threshold * 0.3 else "red")
                                else: 
                                    self.status_updated.emit(f"미니맵 스크롤 중 (변화량: {diff_sum:.0f})", "black")

                                # 3. Inpaint 실행
                                if np.any(comparison_mask):
                                    # 복원 반경을 아이콘 크기에 비례하게 설정하여 자연스러움 극대화
                                    radius = max(3, int(min(last_w, last_h) * 0.7))
                                    display_frame_bgr = cv2.inpaint(display_frame_bgr, comparison_mask, radius, cv2.INPAINT_TELEA)

                                # --- Inpaint 로직 최종 수정 끝 ---

                                # 4. 웨이포인트 검증 및 나머지 로직 수행
                                active_waypoints_data, all_found_features = self.verify_waypoints(curr_frame_gray, player_rect)
                                if not self.initial_signal_sent and player_pos and active_waypoints_data: 
                                    self.initial_position_ready.emit(active_waypoints_data, player_pos)
                                    self.initial_signal_sent = True
                self.guide_to_target(player_pos)
                self.waypoints_updated.emit(active_waypoints_data); self.features_detected.emit(all_found_features)
                self.prev_frame_gray = curr_frame_gray
                rgb_image = cv2.cvtColor(display_frame_bgr, cv2.COLOR_BGR2RGB); h, w, ch = rgb_image.shape; qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format.Format_RGB888)
                primary_target_name = self.waypoints[self.target_index]['name'] if self.target_index < len(self.waypoints) else ""
                self.frame_ready.emit(qt_image.copy(), my_player_rects, other_player_rects, primary_target_name); self.msleep(100)

    def find_player_icon(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV); mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER); contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) > 5: player_rect = cv2.boundingRect(c); return (player_rect[0] + player_rect[2] // 2, player_rect[1] + player_rect[3] // 2), player_rect, [player_rect]
        return None, None, []

    def find_other_player_icons(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV); mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1); mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
        mask = cv2.bitwise_or(mask1, mask2); contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 5]
        
    def guide_to_target(self, player_pos):
        if not player_pos or self.prev_frame_gray is None or not self.waypoints: return
        target_wp = self.waypoints[self.target_index] if self.target_index < len(self.waypoints) else None
        if not target_wp: self.navigation_updated.emit("목표를 찾을 수 없습니다.", "red", ""); return
        target_rect_normalized = target_wp.get('rect_normalized')
        if not target_rect_normalized: self.navigation_updated.emit(f"'{target_wp['name']}'의 목표 지점이 설정되지 않았습니다.", "red", target_wp['name']); return
        frame_h, frame_w = self.prev_frame_gray.shape; px, py = player_pos; rect_x = int(target_rect_normalized[0] * frame_w); rect_y = int(target_rect_normalized[1] * frame_h); rect_w = int(target_rect_normalized[2] * frame_w); rect_h = int(target_rect_normalized[3] * frame_h)
        target_x_pixel = rect_x + rect_w / 2; target_y_pixel = rect_y + rect_h / 2
        distance_x = target_x_pixel - px; direction_x = "좌측" if distance_x < 0 else "우측"; distance_y = target_y_pixel - py; direction_y = "위로" if distance_y < 0 else "아래로"
        report_msg = f"-> 다음 목표 '{target_wp['name']}'까지 {direction_x} {abs(distance_x):.0f}px, {direction_y} {abs(distance_y):.0f}px 이동 필요."
        self.navigation_updated.emit(report_msg, "green", target_wp['name'])

    def verify_waypoints(self, current_frame_gray, player_rect):
        active_waypoints = {}; found_features_for_vis = []
        for wp in self.waypoints:
            temp_wp = wp.copy()
            if temp_wp.get('key_feature_ids'):
                correction_result = self.refine_location(current_frame_gray, temp_wp)
                if correction_result:
                    corrected_target_rect, found_features, used_features_with_conf = correction_result; temp_wp['rect_normalized'] = corrected_target_rect
                    found_features_for_vis.extend(found_features); active_waypoints[temp_wp['name']] = {'rect_normalized': temp_wp['rect_normalized']}
                    self.correction_status.emit(f"'{temp_wp['name']}' 위치 추정 성공!", "blue", used_features_with_conf)
                    if self.is_player_in_wp(player_rect, temp_wp, current_frame_gray.shape): self.status_updated.emit(f"ARRIVED:{temp_wp['name']}", "DarkViolet")
        return active_waypoints, found_features_for_vis

    def refine_location(self, current_frame_gray, wp_data):
        estimated_target_positions = []; found_feature_rects_for_vis = []; used_features_with_conf = []
        for feature_id_data in wp_data.get('key_feature_ids', []):
            feature_id = feature_id_data['id']
            feature_info = self.all_key_features.get(feature_id)
            if not feature_info: continue

            img_data = base64.b64decode(feature_info['image_base64'])
            np_arr = np.frombuffer(img_data, np.uint8)
            feature_template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
            if feature_template is None: continue

            feature_h, feature_w = feature_template.shape
            res = cv2.matchTemplate(current_frame_gray, feature_template, cv2.TM_CCOEFF_NORMED)
            
            threshold = feature_info.get('threshold', 0.85)
            loc = np.where(res >= threshold)
            
            # 임계값을 넘는 모든 위치에 대해 처리
            match_points = list(zip(*loc[::-1]))
            if not match_points: continue

            # 가장 신뢰도가 높은 위치 하나만 사용 (탐지 안정성을 위해)
            top_left = max(match_points, key=lambda pt: res[pt[1], pt[0]])
            max_val = res[top_left[1], top_left[0]]
            
            offset_x, offset_y = feature_id_data['offset_to_target']
            est_x = top_left[0] + offset_x
            est_y = top_left[1] + offset_y
            
            estimated_target_positions.append((est_x, est_y))
            found_feature_rects_for_vis.append({'id': feature_id, 'rect': QRect(top_left[0], top_left[1], feature_w, feature_h)})
            used_features_with_conf.append({'id': feature_id, 'conf': max_val})
        
        if not estimated_target_positions: return None
        avg_x = int(sum(p[0] for p in estimated_target_positions) / len(estimated_target_positions))
        avg_y = int(sum(p[1] for p in estimated_target_positions) / len(estimated_target_positions))
        original_target_rect_norm = wp_data['rect_normalized']
        frame_h, frame_w = current_frame_gray.shape
        new_target_rect_normalized = [avg_x / frame_w, avg_y / frame_h, original_target_rect_norm[2], original_target_rect_norm[3]]
        return new_target_rect_normalized, found_feature_rects_for_vis, used_features_with_conf

    def is_player_in_wp(self, player_rect, wp_data, frame_shape):
        if not player_rect: return False
        target_rect_normalized = wp_data.get('rect_normalized')
        if not target_rect_normalized: return False
        frame_h, frame_w = frame_shape; wp_x = int(target_rect_normalized[0] * frame_w); wp_y = int(target_rect_normalized[1] * frame_h); wp_w = int(target_rect_normalized[2] * frame_w); wp_h = int(target_rect_normalized[3] * frame_h)
        pl_x, pl_y, pl_w, pl_h = player_rect
        return (wp_x < pl_x + pl_w and wp_x + wp_w > pl_x and wp_y < pl_y + pl_h and wp_y + wp_h > pl_y)
        
    def stop(self): self.is_running = False

class MapTab(QWidget):
    
    def __init__(self):
        super().__init__()
        self.active_profile_name = None
        self.minimap_region = None
        self.key_features = {}
        self.active_route_profile_name = None
        self.route_profiles = {}
        self.terrain_data = []
        self.layer_objects = []
        self.detection_thread = None
        self.active_waypoints_info = {}
        self.arrived_waypoint_name = None
        self.current_waypoint_index = 0
        self.is_path_forward = True
        self.is_in_initial_search = False
        self.last_simple_nav_message = ""
        self.primary_target_name = None
        self.detected_feature_rects = []
        self.initUI()
        self.perform_initial_setup()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
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
        self.minimap_groupbox = QGroupBox("3. 미니맵 설정")
        minimap_layout = QVBoxLayout(); self.set_area_btn = QPushButton("미니맵 범위 지정"); self.set_area_btn.clicked.connect(self.set_minimap_area); self.open_editor_btn = QPushButton("미니맵 지형 편집기 열기"); self.open_editor_btn.clicked.connect(self.open_map_editor)
        minimap_layout.addWidget(self.set_area_btn); minimap_layout.addWidget(self.open_editor_btn); self.minimap_groupbox.setLayout(minimap_layout); left_layout.addWidget(self.minimap_groupbox)
        self.wp_groupbox = QGroupBox("4. 웨이포인트 관리")
        wp_layout = QVBoxLayout(); self.waypoint_list_widget = QListWidget(); self.waypoint_list_widget.itemDoubleClicked.connect(self.edit_waypoint)
        self.waypoint_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove); self.waypoint_list_widget.model().rowsMoved.connect(self.waypoint_order_changed)
        wp_buttons = QHBoxLayout(); self.add_wp_btn = QPushButton("추가"); self.edit_wp_btn = QPushButton("편집"); self.del_wp_btn = QPushButton("삭제")
        self.add_wp_btn.clicked.connect(self.add_waypoint); self.edit_wp_btn.clicked.connect(self.edit_waypoint); self.del_wp_btn.clicked.connect(self.delete_waypoint)
        wp_buttons.addWidget(self.add_wp_btn); wp_buttons.addWidget(self.edit_wp_btn); wp_buttons.addWidget(self.del_wp_btn)
        wp_layout.addWidget(self.waypoint_list_widget); wp_layout.addLayout(wp_buttons); self.wp_groupbox.setLayout(wp_layout); left_layout.addWidget(self.wp_groupbox)
        self.kf_groupbox = QGroupBox("5. 핵심 지형 관리")
        kf_layout = QVBoxLayout(); self.manage_kf_btn = QPushButton("핵심 지형 관리자 열기"); self.manage_kf_btn.clicked.connect(self.open_key_feature_manager)
        kf_layout.addWidget(self.manage_kf_btn); self.kf_groupbox.setLayout(kf_layout); left_layout.addWidget(self.kf_groupbox)
        detect_groupbox = QGroupBox("6. 탐지 제어")
        detect_layout = QVBoxLayout(); threshold_layout = QHBoxLayout(); threshold_layout.addWidget(QLabel("변화량 임계값:"))
        self.diff_threshold_spinbox = QSpinBox(); self.diff_threshold_spinbox.setRange(1000, 1000000); self.diff_threshold_spinbox.setSingleStep(1000); self.diff_threshold_spinbox.setValue(50000)
        threshold_layout.addWidget(self.diff_threshold_spinbox); self.detect_anchor_btn = QPushButton("탐지 시작"); self.detect_anchor_btn.setCheckable(True)
        self.detect_anchor_btn.clicked.connect(self.toggle_anchor_detection); detect_layout.addLayout(threshold_layout); detect_layout.addWidget(self.detect_anchor_btn)
        detect_groupbox.setLayout(detect_layout); left_layout.addWidget(detect_groupbox); left_layout.addStretch(1)
        logs_layout = QVBoxLayout()
        logs_layout.addWidget(QLabel("네비게이션 로그")); self.nav_log_viewer = QTextEdit(); self.nav_log_viewer.setReadOnly(True); self.nav_log_viewer.setFixedHeight(50); logs_layout.addWidget(self.nav_log_viewer)
        logs_layout.addWidget(QLabel("일반 로그")); self.general_log_viewer = QTextEdit(); self.general_log_viewer.setReadOnly(True); self.general_log_viewer.setFixedHeight(150); logs_layout.addWidget(self.general_log_viewer)
        logs_layout.addWidget(QLabel("앵커 상태 로그")); self.anchor_log_viewer = QTextEdit(); self.anchor_log_viewer.setReadOnly(True); self.anchor_log_viewer.setFixedHeight(80); logs_layout.addWidget(self.anchor_log_viewer)
        logs_layout.addWidget(QLabel("핵심 지형 보정 로그")); self.correction_log_viewer = QTextEdit(); self.correction_log_viewer.setReadOnly(True); logs_layout.addWidget(self.correction_log_viewer)
        right_layout.addWidget(QLabel("실시간 미니맵")); self.minimap_view_label = QLabel("맵 프로필을 선택하거나 생성해주세요."); self.minimap_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.minimap_view_label.setStyleSheet("background-color: black; color: white;"); self.minimap_view_label.setMinimumSize(300, 300); right_layout.addWidget(self.minimap_view_label, 1)
        main_layout.addLayout(left_layout, 1); main_layout.addLayout(logs_layout, 1); main_layout.addLayout(right_layout, 2)
        self.update_general_log("MapTab이 초기화되었습니다. 맵 프로필을 선택해주세요.", "black")
        
    def open_map_editor(self):
        """미니맵 지형 편집기 다이얼로그를 엽니다."""
        if not self.active_profile_name:
            QMessageBox.warning(self, "오류", "먼저 맵 프로필을 선택해주세요.")
            return
        
        all_waypoints = self.get_all_waypoints_with_route_name()
        # deepcopy를 사용하여 원본 데이터가 직접 수정되는 것을 방지
        import copy
        editor_dialog = MapEditorDialog(
            self.key_features, 
            all_waypoints,
            copy.deepcopy(self.terrain_data), 
            copy.deepcopy(self.layer_objects), 
            self
        )
        
        if editor_dialog.exec() == QDialog.DialogCode.Accepted:
            # 사용자가 '저장'을 누른 경우에만 데이터 업데이트
            self.terrain_data, self.layer_objects = editor_dialog.get_edited_data()
            self.save_profile_data()
            self.update_general_log("미니맵 지형 정보가 저장되었습니다.", "blue")
            
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

    # ... (이하 모든 메서드는 이전 답변의 최종 수정안과 동일합니다)
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
        profile_path = os.path.join(MAPS_DIR, profile_name)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        try:
            self.minimap_region, self.key_features = None, {}
            self.route_profiles, self.active_route_profile_name = {}, None
            self.diff_threshold_spinbox.setValue(50000)
            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            features = {}
            if os.path.exists(features_file):
                with open(features_file, 'r', encoding='utf-8') as f:
                    features = json.load(f)
            config_updated, features_updated = self.migrate_data_structures(config, features)
            if config_updated:
                self.route_profiles = config.get('route_profiles', {})
                self.active_route_profile_name = config.get('active_route_profile')
            if features_updated:
                self.key_features = features
            self.minimap_region = config.get('minimap_region')
            self.diff_threshold_spinbox.setValue(config.get('diff_threshold', 50000))
            self.route_profiles = config.get('route_profiles', {})
            self.active_route_profile_name = config.get('active_route_profile')
            self.terrain_data = config.get('terrain_data', [])
            self.layer_objects = config.get('layer_objects', [])
            self.key_features = features
            if config_updated or features_updated:
                self.save_profile_data()
            self.update_ui_for_new_profile()
            self.update_general_log(f"'{profile_name}' 맵 프로필을 로드했습니다.", "blue")
        except Exception as e:
            self.update_general_log(f"'{profile_name}' 프로필 로드 오류: {e}", "red")
            self.update_ui_for_no_profile()

    def migrate_data_structures(self, config, features):
        config_updated = False
        features_updated = False
        if 'waypoints' in config and 'route_profiles' not in config:
            self.update_general_log("v5 마이그레이션: 웨이포인트 구조를 경로 프로필로 변환합니다.", "purple")
            config['route_profiles'] = {"기본 경로": {"waypoints": config.pop('waypoints', [])}}
            config['active_route_profile'] = "기본 경로"
            config_updated = True
        all_waypoints = [wp for route in config.get('route_profiles', {}).values() for wp in route.get('waypoints', [])]
        if any('feature_threshold' in wp for wp in all_waypoints):
            self.update_general_log("v6 마이그레이션: 정확도 설정을 지형으로 이전합니다.", "purple")
            for wp in all_waypoints:
                wp_threshold = wp.pop('feature_threshold')
                for feature_link in wp.get('key_feature_ids', []):
                    feature_id = feature_link['id']
                    if feature_id in features:
                        if features[feature_id].get('threshold', 0) < wp_threshold:
                            features[feature_id]['threshold'] = wp_threshold
                            features_updated = True
            config_updated = True
        for feature_id, feature_data in features.items():
            if 'threshold' not in feature_data:
                feature_data['threshold'] = 0.85
                features_updated = True
            if 'context_image_base64' not in feature_data:
                feature_data['context_image_base64'] = ""
                features_updated = True
            if 'rect_in_context' not in feature_data:
                feature_data['rect_in_context'] = []
                features_updated = True
        return config_updated, features_updated
    
    def save_profile_data(self):
        if not self.active_profile_name: return
        profile_path = os.path.join(MAPS_DIR, self.active_profile_name)
        os.makedirs(profile_path, exist_ok=True)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')

        try:
            config_data = {
                'minimap_region': self.minimap_region,
                'diff_threshold': self.diff_threshold_spinbox.value(),
                'active_route_profile': self.active_route_profile_name,
                'route_profiles': self.route_profiles,
                'terrain_data': getattr(self, 'terrain_data', []),
                'layer_objects': getattr(self, 'layer_objects', [])
            }
            with open(config_file, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4, ensure_ascii=False)
            with open(features_file, 'w', encoding='utf-8') as f: json.dump(self.key_features, f, indent=4, ensure_ascii=False)
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
        # ... (이전 답변의 최종 수정안과 동일)
        self.minimap_groupbox.setTitle(f"3. 미니맵 설정 (맵: {self.active_profile_name})")
        self.wp_groupbox.setTitle(f"4. 웨이포인트 관리 (경로: {self.active_route_profile_name})")
        self.kf_groupbox.setTitle(f"5. 핵심 지형 관리 (맵: {self.active_profile_name})")
        
        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.add_wp_btn, self.edit_wp_btn, self.del_wp_btn,
            self.manage_kf_btn, self.detect_anchor_btn
        ]
        for widget in all_widgets:
            widget.setEnabled(True)
        
        self.populate_route_profile_selector()
        self.minimap_view_label.setText("탐지를 시작하세요.")
        self.save_global_settings()

    def update_ui_for_no_profile(self):
        # ... (이전 답변의 최종 수정안과 동일)
        self.active_profile_name = None
        self.active_route_profile_name = None
        self.route_profiles.clear()
        self.key_features.clear()
        self.waypoint_list_widget.clear()
        self.route_profile_selector.clear()
        self.minimap_region = None
        
        self.minimap_groupbox.setTitle("3. 미니맵 설정 (프로필 없음)")
        self.wp_groupbox.setTitle("4. 웨이포인트 관리 (프로필 없음)")
        self.kf_groupbox.setTitle("5. 핵심 지형 관리 (프로필 없음)")
        
        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.add_wp_btn, self.edit_wp_btn, self.del_wp_btn,
            self.manage_kf_btn, self.detect_anchor_btn
        ]
        for widget in all_widgets:
            widget.setEnabled(False)
            
        self.minimap_view_label.setText("맵 프로필을 선택하거나 생성해주세요.")
        self.save_global_settings()
    
    def populate_route_profile_selector(self):
        # ... (이전 답변과 동일)
        self.route_profile_selector.blockSignals(True)
        self.route_profile_selector.clear()
        
        if not self.route_profiles:
            self.route_profiles["기본 경로"] = {"waypoints": []}
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
        # ... (이전 답변과 동일)
        if index == -1: return
        
        route_name = self.route_profile_selector.itemText(index)
        if route_name != self.active_route_profile_name:
            self.active_route_profile_name = route_name
            self.update_general_log(f"'{route_name}' 경로 프로필로 전환했습니다.", "SaddleBrown")
            self.populate_waypoint_list()
            self.save_profile_data()

    def add_route_profile(self):
        # ... (이전 답변과 동일)
        route_name, ok = QInputDialog.getText(self, "새 경로 프로필 추가", "경로 프로필 이름:")
        if ok and route_name:
            if route_name in self.route_profiles:
                QMessageBox.warning(self, "오류", "이미 존재하는 경로 프로필 이름입니다.")
                return
            
            self.route_profiles[route_name] = {"waypoints": []}
            self.active_route_profile_name = route_name
            self.populate_route_profile_selector()
            self.save_profile_data()
            self.update_general_log(f"새 경로 '{route_name}'이(가) 추가되었습니다.", "green")

    def rename_route_profile(self):
        # ... (이전 답변과 동일)
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
        # ... (이전 답변과 동일)
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
        """모든 경로 프로필의 웨이포인트에 'route_name'을 추가하여 단일 리스트로 반환합니다."""
        all_waypoints = []
        for route_name, route_data in self.route_profiles.items():
            for wp in route_data['waypoints']:
                wp_copy = wp.copy()
                wp_copy['route_name'] = route_name
                all_waypoints.append(wp_copy)
        return all_waypoints

    def open_key_feature_manager(self):
        # v6.0.0: 사용처 표기를 위해 route_name을 추가해서 전달
        all_waypoints = []
        for route_name, route_data in self.route_profiles.items():
            for wp in route_data['waypoints']:
                wp_copy = wp.copy()
                wp_copy['route_name'] = route_name
                all_waypoints.append(wp_copy)
                
        dialog = KeyFeatureManagerDialog(self.key_features, all_waypoints, self)
        dialog.exec()
    
    def get_waypoint_name_from_item(self, item):
        #QListWidgetItem에서 순수한 웨이포인트 이름을 추출합니다. (예: '1. 입구' -> '입구')
        if not item: 
            return None
        text = item.text()
        return text.split('. ', 1)[1] if '. ' in text and text.split('. ', 1)[0].isdigit() else text
    
    def process_new_waypoint_data(self, wp_data, final_features_on_canvas, newly_drawn_features, deleted_feature_ids, context_frame_bgr):
        # v6.0.0: context_frame_bgr을 인자로 받아 문맥적 썸네일 생성
        h, w, _ = context_frame_bgr.shape
        if deleted_feature_ids:
            for feature_id in deleted_feature_ids:
                if feature_id in self.key_features: del self.key_features[feature_id]
            
            all_waypoints = [wp for route in self.route_profiles.values() for wp in route['waypoints']]
            for wp in all_waypoints:
                if 'key_feature_ids' in wp: wp['key_feature_ids'] = [f for f in wp['key_feature_ids'] if f['id'] not in deleted_feature_ids]
            self.update_general_log(f"{len(deleted_feature_ids)}개의 공용 핵심 지형이 영구적으로 삭제되었습니다.", "orange")
        
        newly_created_features = []
        if newly_drawn_features:
            next_num = int(self._get_next_feature_name().replace("P", ""))
            _, context_buffer = cv2.imencode('.png', context_frame_bgr)
            context_base64 = base64.b64encode(context_buffer).decode('utf-8')

            for feature_rect_pixel in newly_drawn_features:
                feature_img = context_frame_bgr[feature_rect_pixel.y():feature_rect_pixel.y()+feature_rect_pixel.height(), feature_rect_pixel.x():feature_rect_pixel.x()+feature_rect_pixel.width()]
                _, feature_buffer = cv2.imencode('.png', feature_img); feature_base64 = base64.b64encode(feature_buffer).decode('utf-8')
                
                new_id = f"P{next_num}"
                self.key_features[new_id] = {
                    'image_base64': feature_base64,
                    'context_image_base64': context_base64,
                    'rect_in_context': [feature_rect_pixel.x(), feature_rect_pixel.y(), feature_rect_pixel.width(), feature_rect_pixel.height()],
                    'threshold': 0.85
                }
                newly_created_features.append({'id': new_id, 'rect_in_context': [feature_rect_pixel.x(), feature_rect_pixel.y(), feature_rect_pixel.width(), feature_rect_pixel.height()]}); next_num += 1

            self.update_general_log(f"{len(newly_created_features)}개의 새 공용 핵심 지형이 추가되었습니다.", "cyan")
            self.update_all_waypoints_with_features()
            
        all_linked_features = final_features_on_canvas + newly_created_features; target_rect_norm = wp_data['rect_normalized']
        target_rect_pixel = QRect(int(target_rect_norm[0] * w), int(target_rect_norm[1] * h), int(target_rect_norm[2] * w), int(target_rect_norm[3] * h))
        key_feature_links = []
        for feature in all_linked_features:
            feature_id = feature['id']; feature_rect_coords = feature['rect_in_context']
            feature_rect_pixel = QRect(*feature_rect_coords)
            offset_x = target_rect_pixel.x() - feature_rect_pixel.x(); offset_y = target_rect_pixel.y() - feature_rect_pixel.y()
            key_feature_links.append({'id': feature_id, 'offset_to_target': [offset_x, offset_y]})
        
        _, buffer = cv2.imencode('.png', context_frame_bgr); img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # v6.0.0: 웨이포인트에서 threshold 제거
        return {'name': wp_data['name'], 'image_base64': img_base64, 'rect_normalized': target_rect_norm, 'key_feature_ids': key_feature_links}
    
    def update_all_waypoints_with_features(self):
        """현재 맵 프로필의 모든 웨이포인트를 순회하며, 등록된 모든 핵심 지형과의 연결을 재구성합니다."""
        all_waypoints = [wp for route in self.route_profiles.values() for wp in route['waypoints']]
        if not all_waypoints:
            QMessageBox.information(self, "알림", "갱신할 웨이포인트가 없습니다.")
            return False # <<-- 추가

        reply = QMessageBox.question(self, "전체 갱신 확인",
                                    f"총 {len(all_waypoints)}개의 웨이포인트와 {len(self.key_features)}개의 핵심 지형의 연결을 갱신합니다.\n"
                                    "이 작업은 웨이포인트의 'key_feature_ids' 설정을 덮어씁니다. 계속하시겠습니까?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            return False # <<-- 추가

        self.update_general_log("모든 웨이포인트와 핵심 지형의 연결을 갱신합니다...", "purple")
        QApplication.processEvents()
        updated_count = 0

        for wp in all_waypoints:
            if 'image_base64' not in wp or not wp['image_base64']:
                continue
            try:
                # 웨이포인트의 기준 미니맵 이미지 로드
                img_data = base64.b64decode(wp['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                wp_map_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                wp_map_gray = cv2.cvtColor(wp_map_bgr, cv2.COLOR_BGR2GRAY)
                h, w, _ = wp_map_bgr.shape

                new_key_feature_links = []
                target_rect_norm = wp['rect_normalized']
                target_rect_pixel = QRect(int(target_rect_norm[0] * w), int(target_rect_norm[1] * h), int(target_rect_norm[2] * w), int(target_rect_norm[3] * h))

                # 모든 핵심 지형에 대해 템플릿 매칭 수행
                for feature_id, feature_data in self.key_features.items():
                    f_img_data = base64.b64decode(feature_data['image_base64'])
                    f_np_arr = np.frombuffer(f_img_data, np.uint8)
                    template = cv2.imdecode(f_np_arr, cv2.IMREAD_GRAYSCALE)
                    if template is None:
                        continue

                    threshold = feature_data.get('threshold', 0.90)
                    res = cv2.matchTemplate(wp_map_gray, template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)

                    if max_val >= threshold:
                        # 지형이 발견되면, 목표 지점까지의 오프셋을 다시 계산하여 링크 추가
                        feature_rect_pixel = QRect(max_loc[0], max_loc[1], template.shape[1], template.shape[0])
                        offset_x = target_rect_pixel.x() - feature_rect_pixel.x()
                        offset_y = target_rect_pixel.y() - feature_rect_pixel.y()
                        new_key_feature_links.append({'id': feature_id, 'offset_to_target': [offset_x, offset_y]})
                
                # 기존 링크를 새로운 링크로 덮어쓰기
                wp['key_feature_ids'] = new_key_feature_links
                updated_count += 1
            except Exception as e:
                self.update_general_log(f"'{wp['name']}' 갱신 중 오류: {e}", "red")

        self.save_profile_data()
        self.update_general_log(f"완료: 총 {len(all_waypoints)}개 중 {updated_count}개의 웨이포인트 링크를 갱신했습니다.", "purple")
        QMessageBox.information(self, "성공", f"{updated_count}개의 웨이포인트 갱신 완료.")
        return True # <<-- 추가
        
    def _get_next_feature_name(self):
       #새로운 핵심 지형의 다음 번호 이름을 생성합니다. (예: P1, P2 -> P3)
        max_num = max([int(name[1:]) for name in self.key_features.keys() if name.startswith("P") and name[1:].isdigit()] or [0])
        return f"P{max_num + 1}"

    def add_waypoint(self):
        # ... (이전 답변과 동일하나, process_new_waypoint_data 호출 시 frame_bgr 전달)
        if not self.minimap_region: QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요."); return
        if not self.active_route_profile_name: QMessageBox.warning(self, "오류", "먼저 경로 프로필을 선택하거나 추가해주세요."); return
        
        name, ok = QInputDialog.getText(self, "웨이포인트 추가", "새 웨이포인트 이름:")
        if not (ok and name): return
        
        current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
        if any(wp['name'] == name for wp in current_waypoints): QMessageBox.warning(self, "오류", "현재 경로에 이미 존재하는 이름입니다."); return

        self.update_general_log(f"'{name}' 웨이포인트의 기준 미니맵을 캡처 및 정제합니다...", "black")
        try:
            frame_bgr = self.get_cleaned_minimap_image()
            if frame_bgr is None: return
            pixmap = QPixmap.fromImage(QImage(frame_bgr.data, frame_bgr.shape[1], frame_bgr.shape[0], frame_bgr.strides[0], QImage.Format.Format_BGR888))
            editor = AdvancedWaypointEditorDialog(pixmap, {'name': name}, self.key_features, self)
            if editor.exec():
                wp_data, final_features, new_features, deleted_ids = editor.get_waypoint_data()
                if not wp_data: return
                
                new_wp = self.process_new_waypoint_data(wp_data, final_features, new_features, deleted_ids, frame_bgr) # frame_bgr 전달
                current_waypoints.append(new_wp)
                self.populate_waypoint_list()
                self.save_profile_data()
                self.update_general_log(f"'{name}' 웨이포인트가 '{self.active_route_profile_name}' 경로에 추가되었습니다.", "green")
        except Exception as e: self.update_general_log(f"웨이포인트 추가 오류: {e}", "red")

    def edit_waypoint(self):
        # ... (이전 답변과 동일하나, process_new_waypoint_data 호출 시 frame_bgr 전달)
        if not self.active_route_profile_name: return
        selected_item = self.waypoint_list_widget.currentItem()
        if not selected_item: QMessageBox.warning(self, "오류", "편집할 웨이포인트를 목록에서 선택하세요."); return
        
        current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
        current_row = self.waypoint_list_widget.row(selected_item)
        wp_data = current_waypoints[current_row]
        old_name = wp_data['name']
        
        try:
            if 'image_base64' in wp_data and wp_data['image_base64']:
                img_data = base64.b64decode(wp_data['image_base64']); np_arr = np.frombuffer(img_data, np.uint8); frame_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                pixmap = QPixmap.fromImage(QImage.fromData(img_data))
            else:
                QMessageBox.information(self, "호환성 안내", "이 웨이포인트는 구 버전 형식입니다.\n현재 미니맵을 기준으로 편집하며, 저장 시 새 형식으로 업데이트됩니다.")
                frame_bgr = self.get_cleaned_minimap_image()
                if frame_bgr is None: QMessageBox.warning(self, "오류", "미니맵을 캡처할 수 없습니다."); return
                pixmap = QPixmap.fromImage(QImage(frame_bgr.data, frame_bgr.shape[1], frame_bgr.shape[0], frame_bgr.strides[0], QImage.Format.Format_BGR888))
            
            editor = AdvancedWaypointEditorDialog(pixmap, wp_data, self.key_features, self)
            if editor.exec():
                new_data, final_features, new_features, deleted_ids = editor.get_waypoint_data()
                if not new_data: return
                
                new_name = new_data.get('name')
                if new_name != old_name and any(wp['name'] == new_name for wp in current_waypoints): 
                    QMessageBox.warning(self, "오류", "이미 존재하는 이름입니다. 변경이 취소되었습니다."); return
                
                processed_data = self.process_new_waypoint_data(new_data, final_features, new_features, deleted_ids, frame_bgr) # frame_bgr 전달
                wp_data.update(processed_data)
                self.update_general_log(f"웨이포인트 '{old_name}'이(가) '{new_name}'(으)로 수정되었습니다.", "black")
                self.populate_waypoint_list()
                self.save_profile_data()
        except Exception as e: self.update_general_log(f"웨이포인트 편집 오류: {e}", "red")

    def update_correction_log(self, message, color, used_features_with_conf):
        # v6.0.0: 신뢰도(conf)를 함께 표시
        log_message = f'<font color="{color}">{message}</font>'
        if used_features_with_conf:
            features_str = ", ".join([f"{f['id']}({f['conf']:.2f})" for f in used_features_with_conf])
            log_message += f' <font color="gray">(근거: {features_str})</font>'
        self.correction_log_viewer.append(log_message)
        self.correction_log_viewer.verticalScrollBar().setValue(self.correction_log_viewer.verticalScrollBar().maximum())
        
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
        self.waypoint_list_widget.clear()
        if not self.active_route_profile_name or not self.route_profiles:
            self.wp_groupbox.setTitle("4. 웨이포인트 관리 (경로 없음)")
            return
        
        self.wp_groupbox.setTitle(f"4. 웨이포인트 관리 (경로: {self.active_route_profile_name})")
        current_waypoints = self.route_profiles[self.active_route_profile_name].get('waypoints', [])
        for i, wp in enumerate(current_waypoints):
            self.waypoint_list_widget.addItem(f"{i + 1}. {wp.get('name', '이름 없음')}")

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
        
        current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
        new_waypoints_order = [self.get_waypoint_name_from_item(self.waypoint_list_widget.item(i)) for i in range(self.waypoint_list_widget.count())]
        current_waypoints.sort(key=lambda wp: new_waypoints_order.index(wp['name']))
        
        self.save_profile_data()
        self.update_general_log("웨이포인트 순서가 변경되었습니다.", "SaddleBrown")
        
        if self.detection_thread and self.detection_thread.isRunning():
            try:
                current_target_name = current_waypoints[self.current_waypoint_index]['name']
                self.current_waypoint_index = new_waypoints_order.index(current_target_name)
                self.detection_thread.set_target_index(self.current_waypoint_index)
            except (ValueError, IndexError): 
                self.current_waypoint_index = 0
                self.detection_thread.set_target_index(0)
        
        self.populate_waypoint_list()

    def delete_waypoint(self):
        if not self.active_route_profile_name: return
        selected_item = self.waypoint_list_widget.currentItem()
        if not selected_item: return
        
        wp_name = self.get_waypoint_name_from_item(selected_item)
        reply = QMessageBox.question(self, "삭제 확인", f"'{wp_name}' 웨이포인트를 삭제하시겠습니까?")
        if reply == QMessageBox.StandardButton.Yes:
            current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
            self.route_profiles[self.active_route_profile_name]['waypoints'] = [wp for wp in current_waypoints if wp['name'] != wp_name]
            self.populate_waypoint_list(); self.save_profile_data()
            
    def toggle_anchor_detection(self, checked):
        if checked:
            if not self.minimap_region: QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요."); self.detect_anchor_btn.setChecked(False); return
            if not self.active_route_profile_name or not self.route_profiles[self.active_route_profile_name]['waypoints']:
                QMessageBox.warning(self, "오류", "하나 이상의 웨이포인트가 포함된 경로를 선택해야 합니다."); self.detect_anchor_btn.setChecked(False); return
            
            self.save_profile_data(); self.general_log_viewer.clear(); self.anchor_log_viewer.clear(); self.nav_log_viewer.clear(); self.correction_log_viewer.clear()
            self.is_in_initial_search = True; self.update_general_log("탐지 시작... 현재 위치를 기반으로 가장 가까운 경로를 탐색합니다.", "SaddleBrown"); self.arrived_waypoint_name = None
            
            waypoints_to_run = self.route_profiles[self.active_route_profile_name]['waypoints']
            self.detection_thread = AnchorDetectionThread(self.minimap_region, self.diff_threshold_spinbox.value(), waypoints_to_run, self.key_features)
            
            self.detection_thread.navigation_updated.connect(self.dispatch_nav_log); self.detection_thread.status_updated.connect(self.dispatch_status_log)
            self.detection_thread.waypoints_updated.connect(self.handle_waypoints_update); self.detection_thread.frame_ready.connect(self.update_minimap_view)
            self.detection_thread.correction_status.connect(self.update_correction_log); self.detection_thread.features_detected.connect(self.handle_features_detected)
            self.detection_thread.initial_position_ready.connect(self._start_path_from_closest_waypoint)
            self.detection_thread.start(); self.detect_anchor_btn.setText("탐지 중단")
        else:
            if self.detection_thread and self.detection_thread.isRunning(): self.detection_thread.stop(); self.detection_thread.wait()
            self.update_general_log("탐지를 중단합니다.", "black"); self.detect_anchor_btn.setText("탐지 시작"); self.detection_thread = None
            self.is_in_initial_search = False; self.minimap_view_label.setText("탐지 중단됨"); self.active_waypoints_info.clear(); self.arrived_waypoint_name = None

    def handle_features_detected(self, feature_data): self.detected_feature_rects = feature_data

    def _start_path_from_closest_waypoint(self, active_waypoints, player_pos):
        if not self.is_in_initial_search: return
        self.is_in_initial_search = False
        
        current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
        
        if not active_waypoints or not player_pos: 
            self.update_general_log("초기 위치를 찾지 못했습니다. 기본 경로(1번)부터 시작합니다.", "red")
            self.current_waypoint_index = 0
            self.is_path_forward = True
        else:
            min_dist = float('inf'); closest_wp_name = None; w, h = self.minimap_region['width'], self.minimap_region['height']
            for name, data in active_waypoints.items():
                rect = data['rect_normalized']; wp_center_x = (rect[0] + rect[2] / 2) * w; wp_center_y = (rect[1] + rect[3] / 2) * h
                dist = math.sqrt((wp_center_x - player_pos[0])**2 + (wp_center_y - player_pos[1])**2)
                if dist < min_dist: min_dist = dist; closest_wp_name = name
            
            if closest_wp_name:
                try:
                    all_wp_names = [wp['name'] for wp in current_waypoints]
                    initial_index = all_wp_names.index(closest_wp_name)
                    self.current_waypoint_index = initial_index
                    self.is_path_forward = False if initial_index > (len(current_waypoints) - 1) / 2 else True
                    self.update_general_log(f"가장 가까운 '{closest_wp_name}'에서 {'역' if not self.is_path_forward else '정'}방향으로 경로를 시작합니다.", "SaddleBrown")
                except (ValueError, IndexError): 
                    self.current_waypoint_index = 0; self.is_path_forward = True; self.update_general_log("오류 발생. 기본 경로(1번)부터 시작합니다.", "red")
            else: 
                self.current_waypoint_index = 0; self.is_path_forward = True; self.update_general_log("활성화된 웨이포인트 없음. 기본 경로(1번)부터 시작합니다.", "red")
        
        if self.detection_thread: 
            self.detection_thread.set_target_index(self.current_waypoint_index)
            self.detection_thread.set_path_direction(self.is_path_forward)

    def handle_waypoints_update(self, active_data):
        self.active_waypoints_info = active_data
        active_names = list(self.active_waypoints_info.keys())
        if self.arrived_waypoint_name and self.arrived_waypoint_name not in active_names: self.arrived_waypoint_name = None

    def update_minimap_view(self, q_image, my_player_rects, other_player_rects, primary_target_name):
        self.primary_target_name = primary_target_name; original_pixmap = QPixmap.fromImage(q_image)
        if original_pixmap.isNull(): return
        label_size = self.minimap_view_label.size(); final_pixmap = QPixmap(label_size); final_pixmap.fill(Qt.GlobalColor.black)
        scaled_pixmap = original_pixmap.scaled(label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        offset_x = (label_size.width() - scaled_pixmap.width()) / 2; offset_y = (label_size.height() - scaled_pixmap.height()) / 2
        painter = QPainter(final_pixmap); painter.translate(offset_x, offset_y); painter.drawPixmap(0, 0, scaled_pixmap)
        scaled_w, scaled_h = scaled_pixmap.width(), scaled_pixmap.height(); font = QFont(); font.setBold(True); font.setPointSize(10); painter.setFont(font)
        original_w, original_h = original_pixmap.width(), original_pixmap.height()
        
        # --- 1. 핵심 지형 그리기 ---
        if original_w > 0 and original_h > 0:
            painter.save() # <<-- 상태 저장 1
            scale_x, scale_y = scaled_w / original_w, scaled_h / original_h
            painter.setPen(QPen(QColor(0, 255, 255), 2)); painter.setBrush(QBrush(QColor(0, 255, 255, 40)))
            for feature in self.detected_feature_rects:
                rect = feature['rect']; scaled_rect = QRectF(rect.x() * scale_x, rect.y() * scale_y, rect.width() * scale_x, rect.height() * scale_y)
                painter.drawRect(scaled_rect); painter.setPen(Qt.GlobalColor.white); painter.drawText(scaled_rect.topLeft() + QPointF(2, -2), feature['id'])
                painter.setPen(QPen(QColor(0, 255, 255), 2))
            painter.restore() # <<-- 상태 복원 1
        
        # --- 2. 웨이포인트 그리기 ---
        if self.active_route_profile_name:
            painter.save() # <<-- 상태 저장 2
            current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
            wp_name_to_index = {wp['name']: i for i, wp in enumerate(current_waypoints)}
            for name, data in self.active_waypoints_info.items():
                target_rect_normalized = data.get('rect_normalized')
                if not target_rect_normalized: continue
                pixel_rect = QRectF(target_rect_normalized[0] * scaled_w, target_rect_normalized[1] * scaled_h, target_rect_normalized[2] * scaled_w, target_rect_normalized[3] * scaled_h)
                is_primary_target = (self.primary_target_name == name); is_arrived = (self.arrived_waypoint_name == name)
                pen_color = QColor(255, 100, 255) if is_arrived else (QColor(0, 255, 0) if is_primary_target else QColor(0, 180, 255))
                brush_color = QColor(pen_color.red(), pen_color.green(), pen_color.blue(), 100 if is_arrived else 70)
                painter.setPen(QPen(pen_color, 3)); painter.setBrush(QBrush(brush_color)); painter.drawRect(pixel_rect)
                painter.setPen(Qt.GlobalColor.red if is_primary_target and not is_arrived else Qt.GlobalColor.white)
                font.setPointSize(14 if is_arrived else 10); painter.setFont(font)
                painter.drawText(pixel_rect, Qt.AlignmentFlag.AlignCenter if is_arrived else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "도착!" if is_arrived else f" {wp_name_to_index.get(name, -1) + 1}")
            painter.restore() # <<-- 상태 복원 2
        
        if original_w > 0 and original_h > 0:
            scale_x, scale_y = scaled_w / original_w, scaled_h / original_h
            
            # --- 3. 내 캐릭터 그리기 ---
            if my_player_rects:
                painter.save() # <<-- 상태 저장 3
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
                for rect_coords in my_player_rects: 
                    painter.drawRect(QRectF(rect_coords[0] * scale_x, rect_coords[1] * scale_y, rect_coords[2] * scale_x, rect_coords[3] * scale_y))
                painter.restore() # <<-- 상태 복원 3

            # --- 4. 다른 유저 그리기 ---
            if other_player_rects:
                painter.save() # <<-- 상태 저장 4
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(Qt.GlobalColor.red, 2))
                for rect_coords in other_player_rects: 
                    painter.drawRect(QRectF(rect_coords[0] * scale_x, rect_coords[1] * scale_y, rect_coords[2] * scale_x, rect_coords[3] * scale_y))
                painter.restore() # <<-- 상태 복원 4
        
        painter.end(); self.minimap_view_label.setPixmap(final_pixmap)

    def update_general_log(self, message, color): self.general_log_viewer.append(f'<font color="{color}">{message}</font>'); self.general_log_viewer.verticalScrollBar().setValue(self.general_log_viewer.verticalScrollBar().maximum())
    def update_anchor_log(self, message, color): self.anchor_log_viewer.append(f'<font color="{color}">{message}</font>'); self.anchor_log_viewer.verticalScrollBar().setValue(self.anchor_log_viewer.verticalScrollBar().maximum())

    def dispatch_nav_log(self, message, color, target_name):
        if "px" in message:
            current_waypoints = self.route_profiles.get(self.active_route_profile_name, {}).get('waypoints', [])
            wp_names = [wp['name'] for wp in current_waypoints]
            prefix = f"[ {wp_names.index(target_name) + 1} ]" if target_name in wp_names else ""
            parts = message.split("'"); new_message = f"{parts[0]}'{prefix} {target_name}'{parts[-1]}" if len(parts) > 1 else message
            self.nav_log_viewer.setText(f'<font color="{color}">{new_message}</font>')
        elif self.last_simple_nav_message != message: self.update_general_log(message, color); self.last_simple_nav_message = message

    def _update_path_target(self, arrived_index):
        current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
        num_waypoints = len(current_waypoints)
        if num_waypoints <= 1: return
        
        last_index = num_waypoints - 1
        if self.is_path_forward:
            if arrived_index >= last_index: 
                self.is_path_forward = False; self.update_general_log("<b>>> 역방향 경로 시작 <<</b>", "Teal")
                self.current_waypoint_index = max(0, last_index - 1)
            else: self.current_waypoint_index = arrived_index + 1
        else:
            if arrived_index <= 0: 
                self.is_path_forward = True; self.update_general_log("<b>>> 정방향 경로 시작 <<</b>", "Teal")
                self.current_waypoint_index = min(1, last_index)
            else: self.current_waypoint_index = arrived_index - 1
        
        if self.detection_thread: 
            self.detection_thread.set_target_index(self.current_waypoint_index)
            self.detection_thread.set_path_direction(self.is_path_forward)
        
        next_target_name = current_waypoints[self.current_waypoint_index]['name']
        self.update_general_log(f"<b>다음 목표 설정: [ {self.current_waypoint_index + 1} ] {next_target_name}</b>", "blue")

    def dispatch_status_log(self, message, color):
        if "앵커" in message or "스크롤" in message or "상태와 일치" in message: self.update_anchor_log(message, color)
        elif message.startswith("ARRIVED:"):
            name = message.split(":")[1]
            if self.arrived_waypoint_name == name: return
            
            self.arrived_waypoint_name = name
            current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
            wp_names = [wp['name'] for wp in current_waypoints]
            
            try: 
                arrived_index = wp_names.index(name)
                self.update_general_log(f"<b>** 목표 [ {arrived_index + 1} ] {name} 도착! **</b>", 'DarkViolet')
                self._update_path_target(arrived_index)
            except (ValueError, IndexError): pass
        else: self.update_general_log(message, color)

    def cleanup_on_close(self):
        self.save_global_settings()
        if self.detection_thread and self.detection_thread.isRunning(): self.detection_thread.stop(); self.detection_thread.wait()
        print("'맵' 탭 정리 완료.")