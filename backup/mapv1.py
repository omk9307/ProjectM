# map.py
# 2025년 08月 10日 14:55 (KST)
# 작성자: Gemini
# 기능: 미니맵 인식 및 앵커 탐지 기능이 포함된 '맵' 탭 위젯
# 설명:
# - v3.0.3: 경로 탐색 로직 및 시작 방식 개선.
#           - 경로 탐색: 웨이포인트 개수와 상관없이 안정적으로 왕복하도록 경로 업데이트 로직을 별도 메서드로 분리 및 수정. (6개 이상 오류 해결)
#           - 시작 방식: 탐지 시작 시 5초 대기 로직을 제거하고, 즉시 캐릭터와 가장 가까운 웨이포인트를 찾아 경로를 시작하도록 변경.
# - v3.0.2: 웨이포인트 편집기에서 우클릭으로 핵심 지형 삭제 시, 중앙 저장소(json)에서도 해당 지형이 영구적으로 삭제되도록 수정.
# - v3.0.1: '기타 웨이포인트' 관련 기능 및 UI 요소를 완전히 제거하고, 순서형 웨이포인트 관리 로직에 집중하도록 코드를 정리.

import sys
import os
import json
import cv2
import numpy as np
import mss
import base64
import time
import uuid
import math # v3.0.3: 거리 계산을 위해 math 모듈 추가

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QSpinBox, QDialog, QDialogButtonBox, QListWidget,
    QInputDialog, QListWidgetItem, QDoubleSpinBox, QAbstractItemView,
    QLineEdit, QRadioButton, QButtonGroup, QGroupBox
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint, QRectF, QPointF

try:
    from Learning import ScreenSnipper
except ImportError:
    class ScreenSnipper(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            QMessageBox.critical(self, "오류", "Learning.py 모듈을 찾을 수 없어\n화면 영역 지정 기능을 사용할 수 없습니다.")
        def exec(self): return 0
        def get_roi(self): return QRect(0, 0, 100, 100)

SRC_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(SRC_ROOT, '..', 'workspace'))
CONFIG_PATH = os.path.join(WORKSPACE_ROOT, 'config')
MAP_CONFIG_FILE = os.path.join(CONFIG_PATH, 'map_config.json')
KEY_FEATURES_FILE = os.path.join(CONFIG_PATH, 'map_key_features.json')


# 내 캐릭터 (노란색 계열)
PLAYER_ICON_LOWER = np.array([22, 120, 120])
PLAYER_ICON_UPPER = np.array([35, 255, 255])

# 다른 유저 (빨간색 계열)
OTHER_PLAYER_ICON_LOWER1 = np.array([0, 120, 120])
OTHER_PLAYER_ICON_UPPER1 = np.array([10, 255, 255])
OTHER_PLAYER_ICON_LOWER2 = np.array([170, 120, 120])
OTHER_PLAYER_ICON_UPPER2 = np.array([180, 255, 255])

class AdvancedWaypointCanvas(QLabel):
    def __init__(self, pixmap, initial_target=None, initial_features=None, parent=None):
        super().__init__(parent)
        self.base_pixmap = pixmap
        self.setPixmap(self.base_pixmap)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setMouseTracking(True)
        
        self.target_rect = self.denormalize_rect(initial_target) if initial_target else QRect()
        
        self.existing_features_data = initial_features if initial_features else []
        self.existing_features = [self.denormalize_rect(f.get('rect_normalized')) for f in self.existing_features_data]
        self.deleted_feature_ids = []
        
        self.newly_drawn_features = []
        
        self.drawing = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.editing_mode = 'target'

    def denormalize_rect(self, norm_rect):
        if not norm_rect: return QRect()
        w, h = self.base_pixmap.width(), self.base_pixmap.height()
        return QRect(int(norm_rect[0]*w), int(norm_rect[1]*h), int(norm_rect[2]*w), int(norm_rect[3]*h))

    def normalize_rect(self, rect):
        if rect.isNull(): return None
        w, h = self.base_pixmap.width(), self.base_pixmap.height()
        if w > 0 and h > 0: return [rect.x()/w, rect.y()/h, rect.width()/w, rect.height()/h]
        return None

    def set_editing_mode(self, mode):
        self.editing_mode = mode
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.update()
        elif event.button() == Qt.MouseButton.RightButton and self.editing_mode == 'feature':
            for i, feature_rect in reversed(list(enumerate(self.newly_drawn_features))):
                if feature_rect.contains(event.pos()):
                    del self.newly_drawn_features[i]
                    self.update()
                    return

            for i, feature_rect in reversed(list(enumerate(self.existing_features))):
                if feature_rect.contains(event.pos()):
                    deleted_feature = self.existing_features_data.pop(i)
                    self.deleted_feature_ids.append(deleted_feature['id'])
                    del self.existing_features[i]
                    self.update()
                    return

    def mouseMoveEvent(self, event):
        if self.drawing:
            self.end_point = event.pos()
            self.update()
        else:
            cursor_on_feature = False
            if self.editing_mode == 'feature':
                for feature_rect in self.existing_features + self.newly_drawn_features:
                    if feature_rect.contains(event.pos()):
                        cursor_on_feature = True
                        break
            if cursor_on_feature:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            new_rect = QRect(self.start_point, self.end_point).normalized()
            if new_rect.width() > 5 and new_rect.height() > 5:
                if self.editing_mode == 'target':
                    self.target_rect = new_rect
                else:
                    self.newly_drawn_features.append(new_rect)
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        if not self.target_rect.isNull():
            painter.setPen(QPen(QColor(0, 255, 0, 200), 2))
            painter.setBrush(QBrush(QColor(0, 255, 0, 50)))
            painter.drawRect(self.target_rect)

        painter.setPen(QPen(QColor(0, 180, 255, 200), 2))
        painter.setBrush(QBrush(QColor(0, 180, 255, 50)))
        for rect in self.existing_features:
            painter.drawRect(rect)

        painter.setPen(QPen(QColor(255, 165, 0, 200), 2))
        painter.setBrush(QBrush(QColor(255, 165, 0, 50)))
        for rect in self.newly_drawn_features:
            painter.drawRect(rect)

        if self.drawing:
            painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRect(self.start_point, self.end_point).normalized())

class AdvancedWaypointEditorDialog(QDialog):
    def __init__(self, pixmap, initial_data, all_key_features, parent=None):
        super().__init__(parent)
        self.setWindowTitle("웨이포인트 고급 편집")
        self.pixmap = pixmap
        self.all_key_features = all_key_features
        initial_data = initial_data or {}
        
        found_features = self.pre_scan_for_features(pixmap)
        
        layout = QVBoxLayout(self)
        self.canvas = AdvancedWaypointCanvas(pixmap, 
                                             initial_data.get('rect_normalized'), 
                                             found_features, 
                                             self)
        layout.addWidget(self.canvas)
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("이름:"))
        self.name_edit = QLineEdit(initial_data.get('name', ''))
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        mode_box = QGroupBox("편집 모드 (우클릭으로 지형 삭제)")
        mode_layout = QHBoxLayout()
        self.target_radio = QRadioButton("목표 지점 (초록)")
        self.feature_radio = QRadioButton("핵심 지형 (주황/파랑)")
        self.target_radio.setChecked(True)
        self.target_radio.toggled.connect(lambda: self.canvas.set_editing_mode('target'))
        self.feature_radio.toggled.connect(lambda: self.canvas.set_editing_mode('feature'))
        mode_layout.addWidget(self.target_radio)
        mode_layout.addWidget(self.feature_radio)
        mode_box.setLayout(mode_layout)
        layout.addWidget(mode_box)

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("핵심 지형 정확도:"))
        self.feature_threshold_spinbox = QDoubleSpinBox()
        self.feature_threshold_spinbox.setRange(0.5, 1.0); self.feature_threshold_spinbox.setSingleStep(0.01)
        self.feature_threshold_spinbox.setValue(initial_data.get('feature_threshold', 0.85))
        settings_layout.addWidget(self.feature_threshold_spinbox)
        layout.addLayout(settings_layout)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)

        self.setFixedSize(pixmap.width() + 40, pixmap.height() + 200)

    def pre_scan_for_features(self, pixmap):
        found = []
        q_image = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        
        ptr = q_image.bits()
        ptr.setsize(q_image.sizeInBytes())
        arr = np.array(ptr).reshape(q_image.height(), q_image.bytesPerLine())
        current_map_gray = arr[:, :q_image.width()].copy()

        for feature_id, feature_data in self.all_key_features.items():
            try:
                img_data = base64.b64decode(feature_data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                
                if template is None: continue
                
                res = cv2.matchTemplate(current_map_gray, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                
                if max_val > 0.95:
                    h, w = template.shape
                    found.append({
                        'id': feature_id,
                        'rect_normalized': [max_loc[0]/pixmap.width(), max_loc[1]/pixmap.height(), w/pixmap.width(), h/pixmap.height()]
                    })
            except Exception as e:
                print(f"Pre-scan error for feature {feature_id}: {e}")
        return found

    def get_waypoint_data(self):
        target_rect = self.canvas.normalize_rect(self.canvas.target_rect)
        if not target_rect:
            QMessageBox.warning(self, "저장 불가", "목표 지점(초록색)을 설정해야 합니다.")
            return None, None
        
        all_features = self.canvas.existing_features + self.canvas.newly_drawn_features
        if not all_features:
            QMessageBox.warning(self, "저장 불가", "핵심 지형을 최소 1개 이상 설정해야 합니다.")
            return None, None

        waypoint_data = {
            'name': self.name_edit.text(),
            'rect_normalized': target_rect,
            'existing_features': [self.canvas.normalize_rect(f) for f in self.canvas.existing_features],
            'newly_drawn_features': [self.canvas.normalize_rect(f) for f in self.canvas.newly_drawn_features],
            'feature_threshold': self.feature_threshold_spinbox.value()
        }
        
        deleted_ids = self.canvas.deleted_feature_ids
        return waypoint_data, deleted_ids

class AnchorDetectionThread(QThread):
    frame_ready = pyqtSignal(QImage, list, list, str)
    navigation_updated = pyqtSignal(str, str, str)
    status_updated = pyqtSignal(str, str)
    waypoints_updated = pyqtSignal(dict)
    correction_status = pyqtSignal(str, str)
    features_detected = pyqtSignal(list, list)
    # v3.0.3: 초기 위치 탐지 시그널 추가
    initial_position_ready = pyqtSignal(dict, tuple)

    def __init__(self, minimap_region, diff_threshold, waypoints_data, all_key_features):
        super().__init__()
        self.is_running = True
        self.minimap_region = minimap_region
        self.diff_threshold = float(diff_threshold)
        self.prev_frame_gray = None
        self.all_key_features = all_key_features
        self.waypoints = self.prepare_waypoints(waypoints_data)
        self.target_index = 0
        self.is_path_forward = True
        # v3.0.3: 초기 위치 시그널을 한 번만 보내기 위한 플래그
        self.initial_signal_sent = False

    def set_target_index(self, index): self.target_index = index
    def set_path_direction(self, is_forward): self.is_path_forward = is_forward

    def prepare_waypoints(self, waypoints_data):
        templates = []
        for wp in waypoints_data:
            try:
                template_item = {
                    'name': wp['name'],
                    'rect_normalized': wp.get('rect_normalized'),
                    'key_feature_ids': wp.get('key_feature_ids', []),
                    'feature_threshold': wp.get('feature_threshold', 0.85)
                }
                templates.append(template_item)
            except Exception as e: print(f"웨이포인트 '{wp.get('name', 'N/A')}' 준비 오류: {e}")
        return templates

    def run(self):
        with mss.mss() as sct:
            while self.is_running:
                sct_img = sct.grab(self.minimap_region)
                curr_frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
                curr_frame_gray = cv2.cvtColor(curr_frame_bgr, cv2.COLOR_BGR2GRAY)
                
                player_pos, player_rect, my_player_rects = self.find_player_icon(curr_frame_bgr)
                other_player_rects = self.find_other_player_icons(curr_frame_bgr)
                
                active_waypoints_data = {}
                all_found_features = []

                display_frame_bgr = curr_frame_bgr.copy()

                if self.prev_frame_gray is not None:
                    hsv = cv2.cvtColor(curr_frame_bgr, cv2.COLOR_BGR2HSV)
                    
                    my_player_mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER)
                    other_player_mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1)
                    other_player_mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
                    other_player_mask = cv2.bitwise_or(other_player_mask1, other_player_mask2)
                    
                    kernel = np.ones((5, 5), np.uint8)
                    dilated_my_player_mask = cv2.dilate(my_player_mask, kernel, iterations=1)
                    dilated_other_player_mask = cv2.dilate(other_player_mask, kernel, iterations=1)
                    total_ignore_mask = cv2.bitwise_or(dilated_my_player_mask, dilated_other_player_mask)

                    if np.any(total_ignore_mask):
                        display_frame_bgr = cv2.inpaint(display_frame_bgr, total_ignore_mask, 3, cv2.INPAINT_TELEA)

                    prev_frame_masked = self.prev_frame_gray.copy()
                    curr_frame_masked = curr_frame_gray.copy()
                    comparison_mask = cv2.bitwise_or(my_player_mask, other_player_mask)
                    prev_frame_masked[comparison_mask != 0] = 0
                    curr_frame_masked[comparison_mask != 0] = 0
                    
                    diff = cv2.absdiff(prev_frame_masked, curr_frame_masked)
                    diff_sum = float(np.sum(diff))
                    
                    if diff_sum < self.diff_threshold:
                        stable_threshold = self.diff_threshold * 0.3
                        if diff_sum < stable_threshold: self.status_updated.emit(f"앵커 상태 (변화량: {diff_sum:.0f})", "green")
                        else: self.status_updated.emit(f"앵커 상태 의심 (변화량: {diff_sum:.0f})", "red")
                    else:
                        self.status_updated.emit(f"미니맵 스크롤 중 (변화량: {diff_sum:.0f})", "black")
                    
                    active_waypoints_data, all_found_features = self.verify_waypoints(curr_frame_gray, player_rect)

                    # v3.0.3: 초기 위치 탐지 시그널 발생 로직
                    if not self.initial_signal_sent and player_pos and active_waypoints_data:
                        self.initial_position_ready.emit(active_waypoints_data, player_pos)
                        self.initial_signal_sent = True
                    
                self.guide_to_target(player_pos)
                
                self.waypoints_updated.emit(active_waypoints_data)
                self.features_detected.emit(all_found_features, [])
                
                self.prev_frame_gray = curr_frame_gray
                
                rgb_image = cv2.cvtColor(display_frame_bgr, cv2.COLOR_BGR2RGB)
                
                h, w, ch = rgb_image.shape
                qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format.Format_RGB888)
                
                primary_target_name = self.waypoints[self.target_index]['name'] if self.target_index < len(self.waypoints) else ""
                self.frame_ready.emit(qt_image.copy(), my_player_rects, other_player_rects, primary_target_name)
                self.msleep(100)

    def find_player_icon(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) > 5:
                player_rect = cv2.boundingRect(c)
                cx = player_rect[0] + player_rect[2] // 2
                cy = player_rect[1] + player_rect[3] // 2
                return (cx, cy), player_rect, [player_rect]
        return None, None, []

    def find_other_player_icons(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1)
        mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
        mask = cv2.bitwise_or(mask1, mask2)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        rects = []
        for c in contours:
            if cv2.contourArea(c) > 5:
                rects.append(cv2.boundingRect(c))
        return rects

    def guide_to_target(self, player_pos):
        if not player_pos or self.prev_frame_gray is None or not self.waypoints:
            return
        
        if self.target_index < len(self.waypoints):
            target_wp = self.waypoints[self.target_index]
        else:
            self.navigation_updated.emit("목표를 찾을 수 없습니다.", "red", "", "")
            return

        target_rect_normalized = target_wp.get('rect_normalized')

        if not target_rect_normalized:
            self.navigation_updated.emit(f"'{target_wp['name']}'의 목표 지점이 설정되지 않았습니다.", "red", target_wp['name'])
            return

        frame_h, frame_w = self.prev_frame_gray.shape
        px, py = player_pos
        rect_x = int(target_rect_normalized[0] * frame_w)
        rect_y = int(target_rect_normalized[1] * frame_h)
        rect_w = int(target_rect_normalized[2] * frame_w)
        rect_h = int(target_rect_normalized[3] * frame_h)
        
        target_x_pixel = rect_x + rect_w / 2
        target_y_pixel = rect_y + rect_h / 2
        
        distance_x = target_x_pixel - px
        direction_x = "좌측" if distance_x < 0 else "우측"
        distance_y = target_y_pixel - py
        direction_y = "위로" if distance_y < 0 else "아래로"
        
        report_msg = (f"-> 다음 목표 '{target_wp['name']}'까지 {direction_x} {abs(distance_x):.0f}px, {direction_y} {abs(distance_y):.0f}px 이동 필요.")
        
        self.navigation_updated.emit(report_msg, "green", target_wp['name'])

    def verify_waypoints(self, current_frame_gray, player_rect):
        active_waypoints = {}
        found_features_for_vis = []
        
        for wp in self.waypoints:
            temp_wp = wp.copy()

            if temp_wp.get('key_feature_ids'):
                correction_result = self.refine_location(current_frame_gray, temp_wp)
                if correction_result:
                    corrected_target_rect, found_features, _ = correction_result
                    temp_wp['rect_normalized'] = corrected_target_rect
                    
                    found_features_for_vis.extend(found_features)
                    
                    active_waypoints[temp_wp['name']] = {
                        'rect_normalized': temp_wp['rect_normalized']
                    }
                    self.correction_status.emit(f"'{temp_wp['name']}' 위치 추정 성공!", "blue")
                    
                    if self.is_player_in_wp(player_rect, temp_wp, current_frame_gray.shape):
                        self.status_updated.emit(f"ARRIVED:{temp_wp['name']}", "DarkViolet")
                        
        return active_waypoints, found_features_for_vis
        
    def refine_location(self, current_frame_gray, wp_data):
        estimated_target_positions = []
        found_feature_rects_for_vis = []

        for feature_id_data in wp_data.get('key_feature_ids', []):
            feature_id = feature_id_data['id']
            feature_info = self.all_key_features.get(feature_id)
            if not feature_info: continue

            img_data = base64.b64decode(feature_info['image_base64'])
            np_arr = np.frombuffer(img_data, np.uint8)
            feature_template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)

            feature_h, feature_w = feature_template.shape
            res = cv2.matchTemplate(current_frame_gray, feature_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, top_left = cv2.minMaxLoc(res)

            if max_val >= wp_data['feature_threshold']:
                offset_x, offset_y = feature_id_data['offset_to_target']
                
                est_x = top_left[0] + offset_x
                est_y = top_left[1] + offset_y
                estimated_target_positions.append((est_x, est_y))

                found_feature_rects_for_vis.append(QRect(top_left[0], top_left[1], feature_w, feature_h))

        if not estimated_target_positions:
            return None

        avg_x = int(sum(p[0] for p in estimated_target_positions) / len(estimated_target_positions))
        avg_y = int(sum(p[1] for p in estimated_target_positions) / len(estimated_target_positions))

        original_target_rect_norm = wp_data['rect_normalized']
        frame_h, frame_w = current_frame_gray.shape
        
        new_target_rect_normalized = [
            avg_x / frame_w,
            avg_y / frame_h,
            original_target_rect_norm[2],
            original_target_rect_norm[3]
        ]

        predicted_target_w_pixel = int(original_target_rect_norm[2] * frame_w)
        predicted_target_h_pixel = int(original_target_rect_norm[3] * frame_h)
        predicted_target_rect = QRect(avg_x, avg_y, predicted_target_w_pixel, predicted_target_h_pixel)

        return new_target_rect_normalized, found_feature_rects_for_vis, predicted_target_rect

    def is_player_in_wp(self, player_rect, wp_data, frame_shape):
        if not player_rect: return False
        
        target_rect_normalized = wp_data.get('rect_normalized')
            
        if not target_rect_normalized: return False
        
        frame_h, frame_w = frame_shape
        wp_x = int(target_rect_normalized[0] * frame_w)
        wp_y = int(target_rect_normalized[1] * frame_h)
        wp_w = int(target_rect_normalized[2] * frame_w)
        wp_h = int(target_rect_normalized[3] * frame_h)
        
        pl_x, pl_y, pl_w, pl_h = player_rect
        return (wp_x < pl_x + pl_w and wp_x + wp_w > pl_x and
                wp_y < pl_y + pl_h and wp_y + wp_h > pl_y)

    def stop(self): self.is_running = False

class MapTab(QWidget):
    def __init__(self):
        super().__init__()
        self.minimap_region = None
        self.waypoints = []
        self.key_features = {}
        self.detection_thread = None
        self.active_waypoints_info = {}
        self.arrived_waypoint_name = None
        self.current_waypoint_index = 0
        self.is_path_forward = True
        self.is_in_initial_search = False
        self.last_simple_nav_message = ""
        self.primary_target_name = None
        self.detected_feature_rects = []
        self.predicted_waypoint_rects = []
        self.initUI()
        self.load_config()
        self.populate_waypoint_list()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        
        minimap_groupbox = QGroupBox("1. 미니맵 설정")
        minimap_layout = QVBoxLayout()
        self.set_area_btn = QPushButton("미니맵 범위 지정")
        self.set_area_btn.clicked.connect(self.set_minimap_area)
        minimap_layout.addWidget(self.set_area_btn)
        minimap_groupbox.setLayout(minimap_layout)
        left_layout.addWidget(minimap_groupbox)

        wp_groupbox = QGroupBox("2. 웨이포인트 관리 (드래그로 순서 변경)")
        wp_layout = QVBoxLayout()
        self.waypoint_list_widget = QListWidget()
        self.waypoint_list_widget.itemDoubleClicked.connect(self.edit_waypoint)
        self.waypoint_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.waypoint_list_widget.model().rowsMoved.connect(self.waypoint_order_changed)
        wp_buttons = QHBoxLayout()
        self.add_wp_btn = QPushButton("추가")
        self.edit_wp_btn = QPushButton("편집")
        self.del_wp_btn = QPushButton("삭제")
        self.add_wp_btn.clicked.connect(self.add_waypoint)
        self.edit_wp_btn.clicked.connect(self.edit_waypoint)
        self.del_wp_btn.clicked.connect(self.delete_waypoint)
        wp_buttons.addWidget(self.add_wp_btn); wp_buttons.addWidget(self.edit_wp_btn); wp_buttons.addWidget(self.del_wp_btn)
        wp_layout.addWidget(self.waypoint_list_widget)
        wp_layout.addLayout(wp_buttons)
        wp_groupbox.setLayout(wp_layout)
        left_layout.addWidget(wp_groupbox)

        detect_groupbox = QGroupBox("3. 탐지 제어")
        detect_layout = QVBoxLayout()
        
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("변화량 임계값:"))
        self.diff_threshold_spinbox = QSpinBox()
        self.diff_threshold_spinbox.setRange(1000, 1000000); self.diff_threshold_spinbox.setSingleStep(1000); self.diff_threshold_spinbox.setValue(50000)
        threshold_layout.addWidget(self.diff_threshold_spinbox)
        
        self.detect_anchor_btn = QPushButton("탐지 시작")
        self.detect_anchor_btn.setCheckable(True)
        self.detect_anchor_btn.clicked.connect(self.toggle_anchor_detection)
        detect_layout.addLayout(threshold_layout)
        detect_layout.addWidget(self.detect_anchor_btn)
        detect_groupbox.setLayout(detect_layout)
        left_layout.addWidget(detect_groupbox)
        left_layout.addStretch(1)

        logs_layout = QVBoxLayout()
        logs_layout.addWidget(QLabel("네비게이션 로그"))
        self.nav_log_viewer = QTextEdit(); self.nav_log_viewer.setReadOnly(True); self.nav_log_viewer.setFixedHeight(50)
        logs_layout.addWidget(self.nav_log_viewer)
        
        logs_layout.addWidget(QLabel("일반 로그"))
        self.general_log_viewer = QTextEdit(); self.general_log_viewer.setReadOnly(True); self.general_log_viewer.setFixedHeight(150)
        logs_layout.addWidget(self.general_log_viewer)
        
        logs_layout.addWidget(QLabel("앵커 상태 로그"))
        self.anchor_log_viewer = QTextEdit(); self.anchor_log_viewer.setReadOnly(True); self.anchor_log_viewer.setFixedHeight(80)
        logs_layout.addWidget(self.anchor_log_viewer)

        logs_layout.addWidget(QLabel("핵심 지형 보정 로그"))
        self.correction_log_viewer = QTextEdit(); self.correction_log_viewer.setReadOnly(True)
        logs_layout.addWidget(self.correction_log_viewer)

        right_layout.addWidget(QLabel("실시간 미니맵"))
        self.minimap_view_label = QLabel("미니맵 범위 지정 또는 탐지를 시작하세요.")
        self.minimap_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.minimap_view_label.setStyleSheet("background-color: black; color: white;")
        self.minimap_view_label.setMinimumSize(300, 300)
        right_layout.addWidget(self.minimap_view_label, 1)
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(logs_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.update_general_log("MapTab이 초기화되었습니다.", "black")

    def get_waypoint_name_from_item(self, item):
        if not item: return None
        text = item.text()
        if '. ' in text and text.split('. ', 1)[0].isdigit():
            return text.split('. ', 1)[1]
        return text

    def waypoint_order_changed(self):
        new_waypoints_order = [self.get_waypoint_name_from_item(self.waypoint_list_widget.item(i)) for i in range(self.waypoint_list_widget.count())]
        self.waypoints.sort(key=lambda wp: new_waypoints_order.index(wp['name']))
        self.save_config()
        self.update_general_log("웨이포인트 순서가 변경되었습니다.", "SaddleBrown")
        if self.detection_thread and self.detection_thread.isRunning():
            try:
                current_target_name = self.waypoints[self.current_waypoint_index]['name']
                self.current_waypoint_index = new_waypoints_order.index(current_target_name)
                self.detection_thread.set_target_index(self.current_waypoint_index)
            except (ValueError, IndexError):
                self.current_waypoint_index = 0
                self.detection_thread.set_target_index(0)
        self.populate_waypoint_list()

    def load_config(self):
        try:
            os.makedirs(CONFIG_PATH, exist_ok=True)
            if os.path.exists(MAP_CONFIG_FILE):
                with open(MAP_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.minimap_region = config.get('minimap_region')
                    self.diff_threshold_spinbox.setValue(config.get('diff_threshold', 50000))
                    self.waypoints = [wp for wp in config.get('waypoints', []) if isinstance(wp, dict) and 'name' in wp]
            if os.path.exists(KEY_FEATURES_FILE):
                with open(KEY_FEATURES_FILE, 'r') as f:
                    self.key_features = json.load(f)
        except Exception as e:
            self.update_general_log(f"설정 파일 로드 오류: {e}", "red")
            self.minimap_region, self.waypoints, self.key_features = None, [], {}

    def save_config(self):
        try:
            os.makedirs(CONFIG_PATH, exist_ok=True)
            config_data = {
                'minimap_region': self.minimap_region,
                'waypoints': self.waypoints,
                'diff_threshold': self.diff_threshold_spinbox.value(),
            }
            with open(MAP_CONFIG_FILE, 'w') as f: json.dump(config_data, f, indent=4)
            with open(KEY_FEATURES_FILE, 'w') as f: json.dump(self.key_features, f, indent=4)
        except Exception as e: self.update_general_log(f"설정 파일 저장 오류: {e}", "red")

    def set_minimap_area(self):
        self.update_general_log("화면에서 미니맵 영역을 드래그하여 선택하세요...", "black")
        QThread.msleep(200)
        snipper = ScreenSnipper(self)
        if snipper.exec():
            roi = snipper.get_roi()
            self.minimap_region = {'top': roi.top(), 'left': roi.left(), 'width': roi.width(), 'height': roi.height()}
            self.update_general_log(f"새 미니맵 범위 지정 완료: {self.minimap_region}", "black")
            self.save_config()
        else: self.update_general_log("미니맵 범위 지정이 취소되었습니다.", "black")

    def populate_waypoint_list(self):
        self.waypoint_list_widget.clear()
        for i, wp in enumerate(self.waypoints):
            self.waypoint_list_widget.addItem(f"{i + 1}. {wp.get('name', '이름 없음')}")
            
    def get_cleaned_minimap_image(self):
        if not self.minimap_region:
            return None
        
        with mss.mss() as sct:
            sct_img = sct.grab(self.minimap_region)
            frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
            
            hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
            
            my_player_mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER)
            other_player_mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1)
            other_player_mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
            other_player_mask = cv2.bitwise_or(other_player_mask1, other_player_mask2)
            
            kernel = np.ones((5, 5), np.uint8)
            dilated_my_player_mask = cv2.dilate(my_player_mask, kernel, iterations=1)
            dilated_other_player_mask = cv2.dilate(other_player_mask, kernel, iterations=1)
            total_ignore_mask = cv2.bitwise_or(dilated_my_player_mask, dilated_other_player_mask)

            cleaned_frame = frame_bgr
            if np.any(total_ignore_mask):
                cleaned_frame = cv2.inpaint(frame_bgr, total_ignore_mask, 3, cv2.INPAINT_TELEA)
                
            return cleaned_frame

    def add_waypoint(self):
        if not self.minimap_region:
            QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요."); return
        name, ok = QInputDialog.getText(self, "웨이포인트 추가", "새 웨이포인트 이름:")
        if not (ok and name): return
        if any(wp['name'] == name for wp in self.waypoints):
            QMessageBox.warning(self, "오류", "이미 존재하는 이름입니다."); return
        self.update_general_log(f"'{name}' 웨이포인트의 기준 미니맵을 캡처 및 정제합니다...", "black")
        try:
            frame_bgr = self.get_cleaned_minimap_image()
            if frame_bgr is None: return

            pixmap = QPixmap.fromImage(QImage(frame_bgr.data, frame_bgr.shape[1], frame_bgr.shape[0], frame_bgr.strides[0], QImage.Format.Format_BGR888))
            editor = AdvancedWaypointEditorDialog(pixmap, {'name': name}, self.key_features, self)
            
            if editor.exec():
                wp_data, deleted_ids = editor.get_waypoint_data()
                if not wp_data: return

                if deleted_ids:
                    for feature_id in deleted_ids:
                        if feature_id in self.key_features:
                            del self.key_features[feature_id]
                    self.update_general_log(f"{len(deleted_ids)}개의 핵심 지형이 영구적으로 삭제되었습니다.", "orange")
                
                new_wp = self.process_new_waypoint_data(wp_data, frame_bgr)
                
                self.waypoints.append(new_wp)
                self.populate_waypoint_list()
                self.save_config()
                self.update_general_log(f"정제된 '{name}' 웨이포인트가 추가되었습니다.", "green")
        except Exception as e: self.update_general_log(f"웨이포인트 추가 오류: {e}", "red")

    def edit_waypoint(self):
        selected_item = self.waypoint_list_widget.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "오류", "편집할 웨이포인트를 목록에서 선택하세요."); return

        current_row = self.waypoint_list_widget.row(selected_item)
        wp_data = self.waypoints[current_row]
        old_name = wp_data['name']

        try:
            frame_bgr = None
            pixmap = None

            if 'image_base64' in wp_data and wp_data['image_base64']:
                img_data = base64.b64decode(wp_data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                frame_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                pixmap = QPixmap.fromImage(QImage.fromData(img_data))
            else:
                QMessageBox.information(self, "호환성 안내", "이 웨이포인트는 구 버전 형식입니다.\n현재 미니맵을 기준으로 편집하며, 저장 시 새 형식으로 업데이트됩니다.")
                frame_bgr = self.get_cleaned_minimap_image()
                if frame_bgr is None:
                    QMessageBox.warning(self, "오류", "미니맵을 캡처할 수 없습니다."); return
                pixmap = QPixmap.fromImage(QImage(frame_bgr.data, frame_bgr.shape[1], frame_bgr.shape[0], frame_bgr.strides[0], QImage.Format.Format_BGR888))

            editor = AdvancedWaypointEditorDialog(pixmap, wp_data, self.key_features, self)
            if editor.exec():
                new_data_from_editor, deleted_ids = editor.get_waypoint_data()
                if not new_data_from_editor: return

                if deleted_ids:
                    for feature_id in deleted_ids:
                        if feature_id in self.key_features:
                            del self.key_features[feature_id]
                    self.update_general_log(f"{len(deleted_ids)}개의 핵심 지형이 영구적으로 삭제되었습니다.", "orange")
                
                new_name = new_data_from_editor.get('name')
                if new_name != old_name and any(wp['name'] == new_name for wp in self.waypoints):
                    QMessageBox.warning(self, "오류", "이미 존재하는 이름입니다. 변경이 취소되었습니다.")
                    return
                
                processed_data = self.process_new_waypoint_data(new_data_from_editor, frame_bgr)
                
                wp_data.update(processed_data)
                
                self.update_general_log(f"웨이포인트 '{old_name}'이(가) '{new_name}'(으)로 수정되었습니다.", "black")
                self.populate_waypoint_list()
                self.save_config()
        except Exception as e: self.update_general_log(f"웨이포인트 편집 오류: {e}", "red")

    def process_new_waypoint_data(self, wp_data_from_editor, frame_bgr):
        h, w, _ = frame_bgr.shape
        
        target_rect_norm = wp_data_from_editor['rect_normalized']
        target_rect_pixel = QRect(int(target_rect_norm[0] * w), int(target_rect_norm[1] * h), 
                                  int(target_rect_norm[2] * w), int(target_rect_norm[3] * h))

        key_feature_ids = []

        for feature_rect_norm in wp_data_from_editor.get('existing_features', []):
            for feature_id, feature_data in self.key_features.items():
                if np.allclose(feature_data['rect_normalized'], feature_rect_norm):
                    feature_rect_pixel = QRect(int(feature_rect_norm[0] * w), int(feature_rect_norm[1] * h),
                                               int(feature_rect_norm[2] * w), int(feature_rect_norm[3] * h))
                    offset_x = target_rect_pixel.x() - feature_rect_pixel.x()
                    offset_y = target_rect_pixel.y() - feature_rect_pixel.y()
                    key_feature_ids.append({'id': feature_id, 'offset_to_target': [offset_x, offset_y]})
                    break
        
        for feature_rect_norm in wp_data_from_editor.get('newly_drawn_features', []):
            feature_rect_pixel = QRect(int(feature_rect_norm[0] * w), int(feature_rect_norm[1] * h),
                                       int(feature_rect_norm[2] * w), int(feature_rect_norm[3] * h))
            
            offset_x = target_rect_pixel.x() - feature_rect_pixel.x()
            offset_y = target_rect_pixel.y() - feature_rect_pixel.y()

            feature_img = frame_bgr[feature_rect_pixel.y():feature_rect_pixel.y()+feature_rect_pixel.height(),
                                    feature_rect_pixel.x():feature_rect_pixel.x()+feature_rect_pixel.width()]
            _, feature_buffer = cv2.imencode('.png', feature_img)
            feature_base64 = base64.b64encode(feature_buffer).decode('utf-8')
            
            new_id = str(uuid.uuid4())
            self.key_features[new_id] = {
                'image_base64': feature_base64,
                'rect_normalized': feature_rect_norm
            }
            key_feature_ids.append({'id': new_id, 'offset_to_target': [offset_x, offset_y]})

        _, buffer = cv2.imencode('.png', frame_bgr)
        img_base64 = base64.b64encode(buffer).decode('utf-8')

        return {
            'name': wp_data_from_editor['name'],
            'image_base64': img_base64,
            'rect_normalized': target_rect_norm,
            'key_feature_ids': key_feature_ids,
            'feature_threshold': wp_data_from_editor['feature_threshold']
        }

    def delete_waypoint(self):
        selected_item = self.waypoint_list_widget.currentItem()
        if not selected_item: return
        wp_name = self.get_waypoint_name_from_item(selected_item)
        reply = QMessageBox.question(self, "삭제 확인", f"'{wp_name}' 웨이포인트를 삭제하시겠습니까?")
        if reply == QMessageBox.StandardButton.Yes:
            self.waypoints = [wp for wp in self.waypoints if wp['name'] != wp_name]
            self.populate_waypoint_list()
            self.save_config()

    def toggle_anchor_detection(self, checked):
        if checked:
            if not self.minimap_region:
                QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요."); self.detect_anchor_btn.setChecked(False); return
            if not self.waypoints:
                QMessageBox.warning(self, "오류", "하나 이상의 웨이포인트를 추가해야 합니다."); self.detect_anchor_btn.setChecked(False); return
            
            self.save_config()
            self.general_log_viewer.clear()
            self.anchor_log_viewer.clear()
            self.nav_log_viewer.clear()
            self.correction_log_viewer.clear()

            # v3.0.3: 5초 타이머 로직 제거, 즉시 시작하도록 변경
            self.is_in_initial_search = True
            self.update_general_log("탐지 시작... 현재 위치를 기반으로 가장 가까운 경로를 탐색합니다.", "SaddleBrown")

            self.arrived_waypoint_name = None
            
            self.detection_thread = AnchorDetectionThread(self.minimap_region, self.diff_threshold_spinbox.value(), self.waypoints, self.key_features)
            
            self.detection_thread.navigation_updated.connect(self.dispatch_nav_log)
            self.detection_thread.status_updated.connect(self.dispatch_status_log)
            self.detection_thread.waypoints_updated.connect(self.handle_waypoints_update)
            self.detection_thread.frame_ready.connect(self.update_minimap_view)
            self.detection_thread.correction_status.connect(self.update_correction_log)
            self.detection_thread.features_detected.connect(self.handle_features_detected)
            # v3.0.3: 새로운 시그널 연결
            self.detection_thread.initial_position_ready.connect(self._start_path_from_closest_waypoint)
            
            self.detection_thread.start()
            self.detect_anchor_btn.setText("탐지 중단")
        else:
            if self.detection_thread and self.detection_thread.isRunning():
                self.detection_thread.stop()
                self.detection_thread.wait()

            self.update_general_log("탐지를 중단합니다.", "black")
            self.detect_anchor_btn.setText("탐지 시작")
            self.detection_thread = None
            self.is_in_initial_search = False
            self.minimap_view_label.setText("탐지 중단됨")
            self.active_waypoints_info.clear()
            self.arrived_waypoint_name = None

    def handle_features_detected(self, feature_rects, predicted_rects):
        self.detected_feature_rects = feature_rects
        self.predicted_waypoint_rects = predicted_rects

    # v3.0.3: 가장 가까운 웨이포인트에서 경로를 시작하는 새로운 메서드
    def _start_path_from_closest_waypoint(self, active_waypoints, player_pos):
        if not self.is_in_initial_search:
            return
        
        self.is_in_initial_search = False # 한 번만 실행되도록 플래그 변경

        if not active_waypoints or not player_pos:
            self.update_general_log("초기 위치를 찾지 못했습니다. 기본 경로(1번)부터 시작합니다.", "red")
            self.current_waypoint_index = 0
            self.is_path_forward = True
        else:
            min_dist = float('inf')
            closest_wp_name = None
            
            w, h = self.minimap_region['width'], self.minimap_region['height']
            
            for name, data in active_waypoints.items():
                rect = data['rect_normalized']
                wp_center_x = (rect[0] + rect[2] / 2) * w
                wp_center_y = (rect[1] + rect[3] / 2) * h
                
                dist = math.sqrt((wp_center_x - player_pos[0])**2 + (wp_center_y - player_pos[1])**2)
                
                if dist < min_dist:
                    min_dist = dist
                    closest_wp_name = name
            
            if closest_wp_name:
                try:
                    all_wp_names = [wp['name'] for wp in self.waypoints]
                    initial_index = all_wp_names.index(closest_wp_name)
                    self.current_waypoint_index = initial_index
                    
                    midpoint = (len(self.waypoints) - 1) / 2
                    if initial_index > midpoint:
                        self.is_path_forward = False
                        self.update_general_log(f"가장 가까운 '{closest_wp_name}'에서 역방향으로 경로를 시작합니다.", "SaddleBrown")
                    else:
                        self.is_path_forward = True
                        self.update_general_log(f"가장 가까운 '{closest_wp_name}'에서 정방향으로 경로를 시작합니다.", "SaddleBrown")

                except (ValueError, IndexError):
                    self.current_waypoint_index = 0
                    self.is_path_forward = True
                    self.update_general_log("오류 발생. 기본 경로(1번)부터 시작합니다.", "red")
            else:
                 self.current_waypoint_index = 0
                 self.is_path_forward = True
                 self.update_general_log("활성화된 웨이포인트 없음. 기본 경로(1번)부터 시작합니다.", "red")

        if self.detection_thread:
            self.detection_thread.set_target_index(self.current_waypoint_index)
            self.detection_thread.set_path_direction(self.is_path_forward)

    def handle_waypoints_update(self, active_data):
        # v3.0.3: 초기 탐색 로직이 별도 시그널로 분리되어 이 메서드는 단순 업데이트만 수행
        self.active_waypoints_info = active_data
        
        active_names = list(self.active_waypoints_info.keys())
        if self.arrived_waypoint_name and self.arrived_waypoint_name not in active_names:
            self.arrived_waypoint_name = None

    def update_minimap_view(self, q_image, my_player_rects, other_player_rects, primary_target_name):
        self.primary_target_name = primary_target_name
        
        original_pixmap = QPixmap.fromImage(q_image)
        if original_pixmap.isNull(): return
        label_size = self.minimap_view_label.size()
        final_pixmap = QPixmap(label_size)
        final_pixmap.fill(Qt.GlobalColor.black)
        scaled_pixmap = original_pixmap.scaled(label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        offset_x = (label_size.width() - scaled_pixmap.width()) / 2
        offset_y = (label_size.height() - scaled_pixmap.height()) / 2
        painter = QPainter(final_pixmap)
        painter.translate(offset_x, offset_y)
        painter.drawPixmap(0, 0, scaled_pixmap)
        scaled_w, scaled_h = scaled_pixmap.width(), scaled_pixmap.height()
        font = QFont(); font.setBold(True); font.setPointSize(10)
        painter.setFont(font)
        
        original_w, original_h = original_pixmap.width(), original_pixmap.height()
        if original_w > 0 and original_h > 0:
            scale_x, scale_y = scaled_w / original_w, scaled_h / original_h

            painter.setPen(QPen(QColor(0, 255, 255), 2)) # Cyan
            painter.setBrush(QBrush(QColor(0, 255, 255, 40)))
            for rect in self.detected_feature_rects:
                scaled_rect = QRectF(rect.x() * scale_x, rect.y() * scale_y, rect.width() * scale_x, rect.height() * scale_y)
                painter.drawRect(scaled_rect)

        wp_name_to_index = {wp['name']: i for i, wp in enumerate(self.waypoints)}

        for name, data in self.active_waypoints_info.items():
            target_rect_normalized = data.get('rect_normalized')
            if not target_rect_normalized: continue

            pixel_rect = QRectF(target_rect_normalized[0] * scaled_w, target_rect_normalized[1] * scaled_h, target_rect_normalized[2] * scaled_w, target_rect_normalized[3] * scaled_h)
            
            is_primary_target = (self.primary_target_name == name)
            is_arrived = (self.arrived_waypoint_name == name)
            
            if is_arrived:
                pen_color = QColor(255, 100, 255, 255)
                brush_color = QColor(255, 100, 255, 100)
            elif is_primary_target:
                pen_color = QColor(0, 255, 0, 255)
                brush_color = QColor(0, 255, 0, 70)
            else:
                pen_color = QColor(0, 180, 255, 255)
                brush_color = QColor(0, 180, 255, 70)
            
            painter.setPen(QPen(pen_color, 3))
            painter.setBrush(QBrush(brush_color))
            painter.drawRect(pixel_rect)
            
            painter.setPen(Qt.GlobalColor.red if is_primary_target and not is_arrived else Qt.GlobalColor.white)
            
            if is_arrived:
                font.setPointSize(14); painter.setFont(font)
                painter.drawText(pixel_rect, Qt.AlignmentFlag.AlignCenter, "도착!")
            else:
                font.setPointSize(10); painter.setFont(font)
                text_to_draw = str(wp_name_to_index.get(name, -1) + 1)
                painter.drawText(pixel_rect.topLeft() + QPointF(5, 15), text_to_draw)

        if original_w > 0 and original_h > 0:
            if my_player_rects:
                painter.setPen(QPen(Qt.GlobalColor.yellow, 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
                for rect_coords in my_player_rects:
                    scaled_rect = QRectF(rect_coords[0] * scale_x, rect_coords[1] * scale_y, rect_coords[2] * scale_x, rect_coords[3] * scale_y)
                    painter.drawRect(scaled_rect)

            if other_player_rects:
                painter.setPen(QPen(Qt.GlobalColor.red, 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
                for rect_coords in other_player_rects:
                    scaled_rect = QRectF(rect_coords[0] * scale_x, rect_coords[1] * scale_y, rect_coords[2] * scale_x, rect_coords[3] * scale_y)
                    painter.drawRect(scaled_rect)

        painter.end()
        self.minimap_view_label.setPixmap(final_pixmap)

    def update_general_log(self, message, color):
        self.general_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.general_log_viewer.verticalScrollBar().setValue(self.general_log_viewer.verticalScrollBar().maximum())

    def update_anchor_log(self, message, color):
        self.anchor_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.anchor_log_viewer.verticalScrollBar().setValue(self.anchor_log_viewer.verticalScrollBar().maximum())
        
    def update_correction_log(self, message, color):
        self.correction_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.correction_log_viewer.verticalScrollBar().setValue(self.correction_log_viewer.verticalScrollBar().maximum())
        
    def dispatch_nav_log(self, message, color, target_name):
        if "px" in message:
            prefix = ""
            try:
                idx = [wp['name'] for wp in self.waypoints].index(target_name)
                prefix = f"[ {idx + 1} ]"
            except ValueError:
                pass
            
            parts = message.split("'")
            if len(parts) > 1:
                distance_info = parts[-1]
                new_message = f"{parts[0]}'{prefix} {target_name}'{distance_info}"
                self.nav_log_viewer.setText(f'<font color="{color}">{new_message}</font>')
            else:
                 self.nav_log_viewer.setText(f'<font color="{color}">{message}</font>')
        else:
            if self.last_simple_nav_message != message:
                self.update_general_log(message, color)
                self.last_simple_nav_message = message

    # v3.0.3: 경로 업데이트 로직을 별도 메서드로 분리
    def _update_path_target(self, arrived_index):
        """도착한 웨이포인트 인덱스를 기반으로 다음 목표와 경로 방향을 갱신합니다."""
        num_waypoints = len(self.waypoints)
        if num_waypoints <= 1:
            return # 웨이포인트가 하나뿐이면 경로를 변경할 필요 없음

        last_index = num_waypoints - 1

        if self.is_path_forward:
            if arrived_index >= last_index: # 정방향 마지막 지점 도착
                self.is_path_forward = False
                self.update_general_log("<b>>> 역방향 경로 시작 <<</b>", "Teal")
                self.current_waypoint_index = max(0, last_index - 1)
            else: # 정방향 진행 중
                self.current_waypoint_index = arrived_index + 1
        else: # 역방향 진행 중
            if arrived_index <= 0: # 역방향 마지막(시작) 지점 도착
                self.is_path_forward = True
                self.update_general_log("<b>>> 정방향 경로 시작 <<</b>", "Teal")
                self.current_waypoint_index = min(1, last_index)
            else: # 역방향 진행 중
                self.current_waypoint_index = arrived_index - 1
        
        if self.detection_thread:
            self.detection_thread.set_target_index(self.current_waypoint_index)
            self.detection_thread.set_path_direction(self.is_path_forward)

        next_target_name = self.waypoints[self.current_waypoint_index]['name']
        self.update_general_log(f"<b>다음 목표 설정: [ {self.current_waypoint_index + 1} ] {next_target_name}</b>", "blue")

    def dispatch_status_log(self, message, color):
        if "앵커" in message or "스크롤" in message or "상태와 일치" in message:
            self.update_anchor_log(message, color)
        elif message.startswith("ARRIVED:"):
            name = message.split(":")[1]
            if self.arrived_waypoint_name == name: return
            self.arrived_waypoint_name = name
            
            try:
                arrived_index = [wp['name'] for wp in self.waypoints].index(name)
                self.update_general_log(f"<b>** 목표 [ {arrived_index + 1} ] {name} 도착! **</b>", 'DarkViolet')
                
                # v3.0.3: 분리된 경로 업데이트 메서드 호출
                self._update_path_target(arrived_index)

            except (ValueError, IndexError): pass
        else:
            self.update_general_log(message, color)

    def cleanup_on_close(self):
        self.save_config()
        if self.detection_thread:
            self.detection_thread.stop()
            self.detection_thread.wait()
        print("'맵' 탭 정리 완료.")
