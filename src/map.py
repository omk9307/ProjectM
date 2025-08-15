# map.py
# 2025년 08月 13日 10:30 (KST)
# 기능: v10.0.0 - 지능형 내비게이션 시스템 도입 (1단계: 데이터 구조 및 UI 확장)
# 설명:
# - v10.0.2: [UI/UX 개선] 편집기 및 실시간 뷰의 가독성과 사용성을 개선.
#           - [편집기 UI] 모든 편집 모드에서 휠 줌 및 휠 클릭 패닝이 가능하도록 개선.
#           - [편집기 UI] '기본' 모드에서 웨이포인트 좌클릭 시 이름을 변경하는 기능 추가 및 관련 드래그 버그 수정.
#           - [편집기 UI] 웨이포인트 추가 시 이름이 UI에 즉시 반영되도록 수정 및 관련 RuntimeError 해결.
#           - [편집기 UI] 웨이포인트 스냅 로직을 개선하여 좁은 지형에서도 스냅이 잘 되도록 수정.
#           - [편집기 UI] 웨이포인트가 다른 요소에 가려지지 않도록 최상위에 표시 (Z-value 조정).
#           - [편집기 데이터] 지형 층 정보 변경 시, 종속된 웨이포인트의 층 정보도 함께 갱신되도록 수정.
#           - [편집기 데이터] 웨이포인트 삭제 시, 모든 경로 프로필에서도 해당 웨이포인트 ID가 함께 삭제되도록 수정.
#           - [실시간 뷰 UI] 웨이포인트 경로의 시작점과 끝점을 '출발지'/'목적지'로 표시하고, 목표 웨이포인트의 텍스트 색상을 흰색으로 변경.
#           - [실시간 뷰 UI] '도착' 알림 텍스트의 위치를 조정.
# - v10.0.1: [기능개선 및 버그수정] 지능형 내비게이션 시스템 1단계 안정화.
#           - [기능개선] 지형 점프 연결(jump_link)이 다른 층 사이에서도 연결 가능하도록 역할을 확장.
#           - [기능개선] 점프 링크의 동적 이름을 '시작층_종료층A/B/C...' 형식으로 변경하여 직관성 향상.
#           - [버그수정] 지형 삭제 시, 종속된 층 이동 오브젝트와 연결된 점프 링크가 UI에 즉시 함께 삭제되도록 수정.
#           - [버그수정] 점프 링크 추가/삭제 시 UI가 즉시 갱신되지 않던 문제와 관련 크래시 현상을 완전히 해결.
# - v10.0.0 (1단계): [구조개편] 층(Floor) 개념, 지형 점프, 경로 분리 등 내비게이션 시스템을 위한 데이터 구조와 UI를 대규모로 확장.
#           - [데이터 구조] 지형선(terrain_lines)에 'floor' 필드 추가.
#           - [데이터 구조] 'waypoints', 'jump_links'를 map_geometry.json에 독립적으로 저장.
#           - [데이터 구조] 경로 프로필의 웨이포인트 목록을 'forward_path'와 'backward_path'로 분리.
#           - [편집기 UI] FullMinimapEditorDialog에 '층 관리', '웨이포인트 추가', '지형 점프 연결' 모드 및 관련 UI 추가.
#           - [메인 UI] MapTab의 웨이포인트 관리 패널을 정방향/역방향 탭 구조로 변경.
#           - [메인 UI] 실시간 네비게이션 정보를 표시할 NavigatorDisplay 위젯 추가.
# - v9.0.0: [시스템개편] 전체 미니맵을 기반으로 실시간 뷰를 렌더링하는 방식으로 시스템을 전면 개편.
#           - [탐지 단순화] AnchorDetectionThread의 역할을 핵심 지형 탐지에만 집중하도록 변경하고, 복잡한 웨이포인트 보정 및 경로 안내 로직 제거.
#           - [전체 맵 렌더링] 프로필 로드 시, 모든 지형/오브젝트 정보를 포함하는 단일 '전체 맵' 이미지를 미리 생성.
#           - [카메라 뷰] 실시간 탐지된 핵심 지형의 로컬/전역 좌표를 이용해 플레이어의 전역 좌표를 계산하고, 전체 맵 위에서 해당 위치를 중심으로 하는 '카메라 뷰'를 실시간으로 렌더링.
#           - [UI/UX 개선] 실시간 미니맵 뷰에 마우스 휠 확대/축소 기능 추가 및 현재 위치 계산의 기준이 되는 활성 지형 시각화 기능 추가.
# - v8.0.2: [버그수정] QPoint와 QPointF 간의 TypeError를 해결하고 전체적인 코드 안정성을 강화.
#           - [수정] update_minimap_view에서 offset 계산 시 QPointF()로 타입을 명시적으로 변환하여 TypeError 해결.
#           - [개선] _calculate_global_positions, populate_scene, on_player_pos_updated 등
#             좌표계를 다루는 여러 메서드의 예외 처리 및 로직을 개선하여 안정성 향상.
# - v8.0.0: [기능구현] 실시간 미니맵 뷰에 지형 데이터가 정확한 위치에 그려지도록 좌표 변환 로직 구현.
#           - [구조변경] 전역 좌표계 계산 로직(_calculate_global_positions)을 MapTab으로 이동.
#           - [좌표변환] 실시간으로 탐지된 기준 지형의 로컬/전역 좌표를 이용해 Offset을 계산하고,
#             이를 통해 지형/오브젝트의 전역 좌표를 실시간 뷰의 로컬 좌표로 변환하여 렌더링.
# - v7.9.7: [기능개선] 실시간 미니맵 뷰에 표시되는 모든 요소가 보기 옵션에 따라 제어되도록 수정.
# - v7.9.6: [기능구현] 모든 보기 옵션의 상태가 맵 프로필에 저장되고 복원되도록 기능 확장.
# - v7.9.5: [기능구현] 편집기의 '보기 옵션' 상태가 저장되지 않던 문제를 해결.
# - v7.9.4: [버그수정] 불완전한 try 구문으로 인한 SyntaxError 해결.
# - v7.9.3: [버그수정] 반복적인 SyntaxError 해결을 위해 MapTab 클래스 전체 코드 교체.
# - v7.8.1: [기능개선] 편집기 UX 개선 (초기 배율 최적화, '기본' 모드 휠 줌 변경 등).
# - v7.8.0: [기능구현] '기본' 모드 및 '뷰 모드 전환' 기능 구현, 불필요한 UI 제거.
# - v7.7.1: [기능개선] 'X축 고정' 기능을 층 이동 오브젝트 생성 시에도 적용하고, '높이 고정'을 'Y축 고정'으로 명칭 변경.
# - v7.6.0: [기능구현] '높이 고정' 기능 추가.
# - v7.5.5: [버그수정] 지형/오브젝트 삭제 시 화면이 즉시 갱신되지 않는 문제 해결.
# - v7.5.2: [기능개선] 오브젝트 데이터에 부모 지형선 ID를 저장하고, 지형선 삭제 시 연쇄 삭제되도록 개선.
# - v7.5.1: [기능개선] 여러 편집 모드에서 우클릭 삭제가 가능하도록 편의성 향상.
# - v7.5.0: [기능구현] 수직 이동 오브젝트(사다리/밧줄) 그리기 기능 추가.
# - v7.4.2: [기능개선] 보기 옵션에 지형선 및 층 이동 오브젝트 가시성 제어 체크박스 추가.
# - v7.4.1: [버그수정] 지형 입력 도구 스냅 기능 개선 및 미완성 라인 생성 버그 수정.
# - v7.3.0: [기능구현] '지형선' 그리기 기능 추가.
# - v7.2.0: [기능개선] 편집기 사용성 및 가독성 향상 (필터링, 휠 줌, 가시성 제어, 색상 구분).
# - v7.1.0: [기능구현] 맵 스티칭 및 시각화 기능 구현.
# - v7.0.0: [기능추가] '전체 미니맵 편집기' 기능 개발 시작 (기반 프레임워크 구축).
# - v6.0.0: [기능고도화] 핵심 지형 관리 시스템 대폭 개선.
# - v5.0.0: [기능추가] '경로 프로필' 시스템 도입.
# - v4.0.0: [구조개편] '맵 프로필' 시스템 도입.
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
import copy
import traceback
from collections import defaultdict, deque 

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QSpinBox, QDialog, QDialogButtonBox, QListWidget,
    QInputDialog, QListWidgetItem, QDoubleSpinBox, QAbstractItemView,
    QLineEdit, QRadioButton, QButtonGroup, QGroupBox, QComboBox,

    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsEllipseItem, QTabWidget
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor, QIcon, QPolygonF, QFontMetrics
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

# --- v10.0.0: 네비게이터 위젯 클래스 ---
class NavigatorDisplay(QWidget):
    """실시간 내비게이션 정보를 그래픽으로 표시하는 위젯."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self.setMaximumHeight(80)

        # 데이터 초기화
        self.current_floor = "N/A"
        self.target_waypoint_name = "없음"
        self.direction = "-"
        self.distance_px = 0
        self.full_path = []
        self.target_wp_id = None

    def update_data(self, floor, target_name, direction, distance, full_path, target_id):
        """MapTab으로부터 최신 내비게이션 정보를 받아와 뷰를 갱신합니다."""
        self.current_floor = str(floor)
        self.target_waypoint_name = target_name
        self.direction = direction
        self.distance_px = distance
        self.full_path = full_path
        self.target_wp_id = target_id
        self.update() # paintEvent 다시 호출


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
        
        # --- 수정 시작: 버튼 레이아웃 변경 ---
        button_layout = QHBoxLayout()
        self.add_feature_btn = QPushButton("새 지형 추가")
        self.add_feature_btn.clicked.connect(self.add_new_feature)
        
        # '전체 웨이포인트 갱신' 버튼 관련 코드 삭제
        # self.update_links_btn = QPushButton("전체 웨이포인트 갱신")
        # self.update_links_btn.setToolTip(...)
        # self.update_links_btn.clicked.connect(self.on_update_all_clicked)
        
        button_layout.addWidget(self.add_feature_btn)
        # button_layout.addWidget(self.update_links_btn) # 삭제
        # --- 수정 끝 ---
        
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

        # --- 수정 시작: pixmap 변수 할당 및 유효성 검사 ---
        pixmap = self._create_context_thumbnail(feature_data)
        
        if pixmap and not pixmap.isNull():
            self.image_preview_label.setPixmap(pixmap.scaled(self.image_preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.image_preview_label.setText("썸네일 이미지\n생성 실패")
        # --- 수정 끝 ---

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
            
            # --- 수정: 데이터 동기화 및 UI 갱신 ---
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
        # --- 수정: 휠 클릭 패닝 로직 추가 ---
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
        # --- 수정: 휠 클릭 패닝 로직 추가 ---
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
        
        # --- 수정: 멤버 변수 다시 정의 ---
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
        self.is_x_locked = False
        self._initial_fit_done = False
        # v10.0.0: 새로운 미리보기 아이템들
        self.preview_waypoint_item = None
        self.is_drawing_jump_link = False
        self.jump_link_start_pos = None
        self.preview_jump_link_item = None
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
            
            if not self.y_indicator_line:
                pen = QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine)
                self.y_indicator_line = self.scene.addLine(0, 0, 1, 1, pen)
                self.y_indicator_line.setZValue(200)
            
            scene_rect = self.scene.sceneRect()
            if not scene_rect.isValid(): return
            
            self.y_indicator_line.setLine(scene_rect.left(), y_pos, scene_rect.right(), y_pos)
            
            if not hasattr(self, 'x_indicator_line'):
                pen = QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine)
                self.x_indicator_line = self.scene.addLine(0, 0, 1, 1, pen)
                self.x_indicator_line.setZValue(200)
            self.x_indicator_line.setLine(x_pos, scene_rect.top(), x_pos, scene_rect.bottom())

            self.y_indicator_line.setVisible(self.is_y_locked)
            self.x_indicator_line.setVisible(self.is_x_locked)
        
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
                
    def populate_scene(self):
            self.scene.clear()
            # --- 수정: 씬 아이템을 참조하는 멤버 변수 초기화 ---
            self.snap_indicator = None
            self.preview_waypoint_item = None # <-- 이 라인 추가
            self.lod_text_items = []
            
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
            
            for obj_data in self.geometry_data.get("transition_objects", []):
                points = obj_data.get("points", [])
                if len(points) == 2:
                    line_item = self._add_object_line(QPointF(points[0][0], points[0][1]), QPointF(points[1][0], points[1][1]), obj_data['id'])
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
                # --- 수정: order_text 대신 wp_data['name']을 중앙 텍스트로 전달 ---
                self._add_waypoint_rect(QPointF(wp_data['pos'][0], wp_data['pos'][1]), wp_data['id'], wp_data['name'], wp_data['name'])
                
            # 5. 모든 층 번호 텍스트를 마지막에 그림
            self._update_all_floor_texts()

            # 초기 LOD 상태 설정
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
        """현재 줌 레벨에 따라 LOD 아이템들의 가시성을 조절합니다."""
        # 뷰의 현재 스케일(줌 배율) 확인. x축 스케일만 봐도 무방.
        current_zoom = self.view.transform().m11()
        
        is_visible = current_zoom >= self.lod_threshold
        
        for item in self.lod_text_items:
            # 보기 옵션 체크박스도 함께 고려
            item_type = item.data(0)
            base_visible = True
            if item_type in ["transition_object_name", "transition_object_name_bg"]:
                base_visible = self.chk_show_objects.isChecked()
            elif item_type in ["jump_link_name", "jump_link_name_bg"]:
                base_visible = self.chk_show_jump_links.isChecked()
            # 지형 이름표(floor_text) 가시성 제어 추가 ---
            elif item_type in ["floor_text", "floor_text_bg"]:
                base_visible = self.chk_show_terrain.isChecked()
            # 웨이포인트 텍스트 가시성 제어 추가 ---
            elif item_type == "waypoint_lod_text":
                base_visible = self.chk_show_waypoints.isChecked()

            item.setVisible(is_visible and base_visible)

    def on_scene_mouse_press(self, scene_pos, button):
        # --- 수정: '기본' 모드에서 웨이포인트 클릭 시 이름 변경 기능 추가 ---
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
                if not self.is_drawing_object:
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
                        self.object_start_pos = start_pos
                        self.current_object_parent_id = parent_line_id
                        parent_line = next((line for line in self.geometry_data["terrain_lines"] if line["id"] == parent_line_id), None)
                        if parent_line:
                            self.current_object_floor = parent_line.get("floor", self.floor_spinbox.value())
                        else:
                            self.current_object_floor = self.floor_spinbox.value()
                else:
                    self._finish_drawing_object(scene_pos)
            
            elif button == Qt.MouseButton.RightButton:
                if self.is_drawing_object:
                    self._finish_drawing_object(cancel=True)
                else:
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
                            "floor": wp_floor, # --- 수정 (7): 자동 할당된 층 사용 ---
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
            if self.is_drawing_object:
                if self.preview_object_item and self.preview_object_item in self.scene.items():
                    self.scene.removeItem(self.preview_object_item)
                
                end_pos = QPointF(self.object_start_pos.x(), scene_pos.y())
                self.preview_object_item = self.scene.addLine(
                    self.object_start_pos.x(), self.object_start_pos.y(), end_pos.x(), end_pos.y(),
                    QPen(QColor(255, 165, 0, 150), 2, Qt.PenStyle.DashLine)
                )
        # --- v10.0.0 수정 시작 ---
        elif self.current_mode == "waypoint":
            terrain_info = self._get_closest_point_on_terrain(scene_pos)
            if terrain_info:
                snap_pos, _ = terrain_info
                # --- 수정: None 체크 강화 ---
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

            # --- 수정: 중앙 텍스트(order_text)에 폰트 크기 동적 조절 로직 추가 ---
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
            
            # --- 수정: 웨이포인트 아이템들을 최상위에 표시하기 위해 Z-value 설정 ---
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
        # --- 수정: 객체가 삭제되었는지 먼저 확인하여 RuntimeError 방지 ---
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
            
            # 이름이 없다면 먼저 부여
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

            # 2b. 종속된 층 이동 오브젝트 삭제
            self.geometry_data["transition_objects"] = [
                obj for obj in self.geometry_data.get("transition_objects", [])
                if obj.get("parent_line_id") not in ids_in_group
            ]
            
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

    def _finish_drawing_object(self, end_pos=None, cancel=False):
        """현재 그리던 오브젝트 그리기를 완료/취소합니다."""
        if not cancel and end_pos:
            final_end_pos = QPointF(self.object_start_pos.x(), end_pos.y())
            obj_id = f"obj-{uuid.uuid4()}"
            self._add_object_line(self.object_start_pos, final_end_pos, obj_id)
            
            self.geometry_data["transition_objects"].append({
                "id": obj_id,
                "parent_line_id": self.current_object_parent_id,
                "points": [[self.object_start_pos.x(), self.object_start_pos.y()], [final_end_pos.x(), final_end_pos.y()]],
                "floor": getattr(self, 'current_object_floor', self.floor_spinbox.value()) # --- 수정 (7): 자동 할당된 층 사용 ---
            })

            # 이름 갱신 및 전체 씬 다시 그리기 ---
            self._assign_dynamic_names()
            self.populate_scene() # populate_scene이 모든 것을 다시 그려주므로 가장 확실함

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

        # --- 수정 시작: 삭제 후 전체 뷰를 갱신하는 로직으로 변경 ---
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
        self.zoom_level = 1.3 # 기본 실시간 미니맵 뷰 확대배율
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

    def update_view_data(self, camera_center, active_features, my_players, other_players, target_wp_id, reached_wp_id, final_player_pos, is_forward):
        """MapTab으로부터 렌더링에 필요한 최신 데이터를 받습니다."""
        self.camera_center_global = camera_center
        self.active_features = active_features
        self.my_player_rects = my_players
        self.other_player_rects = other_players
        self.target_waypoint_id = target_wp_id
        self.last_reached_waypoint_id = reached_wp_id
        self.final_player_pos_global = final_player_pos
        self.is_forward = is_forward
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
        
        # --- 수정 시작: 지형선 및 그룹 이름 렌더링 로직 전체 교체 ---
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
                    
                    # --- 수정: 미감지 시에도 realtime_conf를 사용하도록 수정 ---
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

                # --- 수정: 출발지/목적지 텍스트 처리 ---
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
                    
                    # --- 수정: 텍스트 너비 계산에 여유 공간(패딩) 추가 ---
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
        # --- 수정 끝 ---
        painter.restore()
        
        painter.save()
        painter.setPen(QPen(Qt.GlobalColor.red, 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
        for rect in self.other_player_rects:
            local_top_left = global_to_local(rect.topLeft())
            local_rect = QRectF(local_top_left, rect.size() * self.zoom_level)
            painter.drawRect(local_rect)
        painter.restore()

        # --- 수정 시작: 정확한 플레이어 발밑 위치 표시 ---
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

# --- v9.0.0: 핵심 지형 탐지에만 집중하도록 단순화된 스레드 ---
class AnchorDetectionThread(QThread):
    """
    지정된 미니맵 영역을 계속 스캔하여, 등록된 핵심 지형과 플레이어 아이콘을
    찾아 그 위치 정보를 메인 스레드로 전달하는 역할만 수행합니다.
    """
    detection_ready = pyqtSignal(np.ndarray, list, list, list)
    status_updated = pyqtSignal(str, str)

    def __init__(self, minimap_region, all_key_features):
        super().__init__()
        self.is_running = True
        self.minimap_region = minimap_region
        self.all_key_features = all_key_features
        
        self.feature_templates = {}
        for feature_id, feature_data in self.all_key_features.items():
            try:
                img_data = base64.b64decode(feature_data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if template is not None:
                    self.feature_templates[feature_id] = {
                        "template_gray": cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
                        "threshold": feature_data.get('threshold', 0.85),
                        "size": QSize(template.shape[1], template.shape[0])
                    }
            except Exception as e:
                print(f"Error preparing template for {feature_id}: {e}")

    def run(self):
        with mss.mss() as sct:
            while self.is_running:
                try:
                    # 1. 화면 캡처 및 플레이어 아이콘 탐지
                    sct_img = sct.grab(self.minimap_region)
                    curr_frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
                    
                    my_player_rects = self.find_player_icon(curr_frame_bgr)
                    other_player_rects = self.find_other_player_icons(curr_frame_bgr)

                    # 2. 핵심 지형 탐지 (모든 결과 보고 방식으로 수정)
                    curr_frame_gray = cv2.cvtColor(curr_frame_bgr, cv2.COLOR_BGR2GRAY)
                    all_detected_features = []
                    
                    for feature_id, template_data in self.feature_templates.items():
                        template_gray = template_data["template_gray"]
                        
                        res = cv2.matchTemplate(curr_frame_gray, template_gray, cv2.TM_CCOEFF_NORMED)
                        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

                        top_left = QPointF(max_loc[0], max_loc[1])
                        size = template_data["size"]
                        all_detected_features.append({
                            'id': feature_id,
                            'local_pos': top_left,
                            'conf': max_val,
                            'size': size
                        })
                    
                    # 3. 탐지 결과 전송
                    self.detection_ready.emit(curr_frame_bgr, all_detected_features, my_player_rects, other_player_rects)

                    # 4. 상태 메시지 전송 (MapTab에서 로그를 생성하므로 여기서는 보내지 않음)
                    # 이 부분은 MapTab.on_detection_ready에서 직접 로그를 생성하므로 주석 처리하거나 제거합니다.
                    # 만약 스레드 자체에서 간단한 상태를 계속 보내고 싶다면 이 부분을 유지할 수 있으나,
                    # 현재 구조에서는 on_detection_ready에서 처리하는 것이 더 정확합니다.
                    # 따라서 이 부분의 status_updated 호출은 제거합니다.

                except Exception as e:
                    self.status_updated.emit(f"탐지 스레드 오류: {e}", "red")
                
                self.msleep(100) # 10 FPS

    def find_player_icon(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER)
        
        # 연결 요소 분석 + 크기 필터링 + 표준 크기 정규화 ---
        output = cv2.connectedComponentsWithStats(mask, 8, cv2.CV_32S)
        num_labels = output[0]
        stats = output[2]
        
        valid_rects = []
        for i in range(1, num_labels):
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            
            # 1. 크기 필터링: 9 <= 크기 < 14 범위에 있는지 확인
            if (MIN_ICON_WIDTH <= w < MAX_ICON_WIDTH and
                MIN_ICON_HEIGHT <= h < MAX_ICON_HEIGHT):
                
                # 2. 표준 크기로 정규화
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
        
        #연결 요소 분석 + 크기 필터링 + 표준 크기 정규화 ---
        output = cv2.connectedComponentsWithStats(mask, 8, cv2.CV_32S)
        num_labels = output[0]
        stats = output[2]
        
        valid_rects = []
        for i in range(1, num_labels):
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            
            # 1. 크기 필터링: 9 <= 크기 < 14 범위에 있는지 확인
            if (MIN_ICON_WIDTH <= w < MAX_ICON_WIDTH and
                MIN_ICON_HEIGHT <= h < MAX_ICON_HEIGHT):
                
                # 2. 표준 크기로 정규화
                center_x = x + w / 2
                center_y = y + h / 2
                
                new_x = int(center_x - PLAYER_ICON_STD_WIDTH / 2)
                new_y = int(center_y - PLAYER_ICON_STD_HEIGHT / 2)
                
                valid_rects.append(QRect(new_x, new_y, PLAYER_ICON_STD_WIDTH, PLAYER_ICON_STD_HEIGHT))
                
        return valid_rects

    def stop(self):
        self.is_running = False

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
        
        self.player_nav_state = 'on_terrain'  # 'on_terrain', 'climbing', 'jumping', 'falling'
        self.current_player_floor = None
        self.last_terrain_line_id = None
        
        self.last_player_pos = QPointF(0, 0)
        # 목표 및 경로 추적 변수 새로 추가 ---
        self.target_waypoint_id = None
        self.last_reached_wp_id = None
        self.current_path_index = -1
        self.is_forward = True  # True: 정방향, False: 역방향
        self.start_waypoint_found = False
        
        #지형 간 상대 위치 벡터 저장 ---
        self.feature_offsets = {}
        
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
        
        # 7. 탐지 제어 (기존과 동일)
        detect_groupbox = QGroupBox("7. 탐지 제어")
        detect_layout = QVBoxLayout()
        self.detect_anchor_btn = QPushButton("탐지 시작")
        self.detect_anchor_btn.setCheckable(True)
        self.detect_anchor_btn.clicked.connect(self.toggle_anchor_detection)
        # 디버그 뷰 체크박스 추가
        self.debug_view_checkbox = QCheckBox("디버그 뷰 표시")
        self.debug_view_checkbox.toggled.connect(self.toggle_debug_view)
        detect_layout.addWidget(self.detect_anchor_btn)
        #  체크박스를 레이아웃에 추가 ---
        detect_layout.addWidget(self.debug_view_checkbox)
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

            """주어진 점프 링크 데이터와 라인 아이템을 기반으로 이름표를 생성하여 씬에 추가합니다."""
            if 'dynamic_name' not in link_data or not line_item:
                return

            name = link_data['dynamic_name']
            link_id = link_data['id']

            # 텍스트 아이템 생성
            text_item = QGraphicsTextItem(name)
            font = QFont("맑은 고딕", 3, QFont.Weight.Bold)
            text_item.setFont(font)
            text_item.setDefaultTextColor(QColor("lime"))
            text_item.setData(0, "jump_link_name")
            text_item.setData(1, link_id)

            # 배경 아이템 생성
            text_rect = text_item.boundingRect()
            padding_x, padding_y = -3, -3
            bg_rect_geom = text_rect.adjusted(-padding_x, -padding_y, padding_x, padding_y)
            line_center = line_item.boundingRect().center()
            base_pos_x = line_center.x() - bg_rect_geom.width() / 2
            base_pos_y = line_center.y() - bg_rect_geom.height() / 2 - 7

            background_rect = RoundedRectItem(QRectF(0, 0, bg_rect_geom.width(), bg_rect_geom.height()), 3, 3)
            background_rect.setBrush(QColor(0, 0, 0, 120))
            background_rect.setPen(QPen(Qt.GlobalColor.transparent))
            background_rect.setPos(base_pos_x, base_pos_y)
            background_rect.setData(0, "jump_link_name_bg")
            background_rect.setData(1, link_id)

            text_item.setPos(base_pos_x + padding_x, base_pos_y + padding_y)
            background_rect.setZValue(10)
            text_item.setZValue(11)

            # 씬에 추가 및 LOD 리스트에 등록
            self.scene.addItem(background_rect)
            self.scene.addItem(text_item)
            self.lod_text_items.append(text_item)
            self.lod_text_items.append(background_rect)

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
        profile_path = os.path.join(MAPS_DIR, profile_name)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            self.minimap_region, self.key_features = None, {}
            self.route_profiles, self.active_route_profile_name = {}, None
            self.geometry_data = {}
            self.reference_anchor_id = None

            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            self.reference_anchor_id = config.get('reference_anchor_id')

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
                    
            # 유효한 핵심 지형 데이터만 필터링
            cleaned_features = {
                feature_id: data
                for feature_id, data in features.items()
                if isinstance(data, dict) and 'image_base64' in data
            }
            
            # 정화 작업이 필요했는지 확인
            if len(cleaned_features) != len(features):
                self.update_general_log("경고: 유효하지 않은 데이터가 'map_key_features.json'에서 발견되어 자동 정리합니다.", "orange")
                self.key_features = cleaned_features
                # 정리된 내용으로 즉시 파일 덮어쓰기 (save_profile_data 호출 시 다시 저장되지만, 명시적으로 처리)
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

            # v10.0.0: 데이터 구조 마이그레이션
            # features 변수를 인자에서 제거합니다.
            config_updated, features_updated, geometry_updated = self.migrate_data_structures(config, self.key_features, self.geometry_data)

            self.route_profiles = config.get('route_profiles', {})
            self.active_route_profile_name = config.get('active_route_profile')
            # self.key_features = features 라인을 삭제합니다. (이미 위에서 할당됨)
            self.minimap_region = config.get('minimap_region')

            if config_updated or features_updated or geometry_updated:
                self.save_profile_data()

            self.global_positions = self._calculate_global_positions()
            self._generate_full_map_pixmap()
            self._assign_dynamic_names()
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
            
        return config_updated, features_updated, geometry_updated

    def save_profile_data(self):
        if not self.active_profile_name: return
        profile_path = os.path.join(MAPS_DIR, self.active_profile_name)
        os.makedirs(profile_path, exist_ok=True)
        config_file = os.path.join(profile_path, 'map_config.json')
        features_file = os.path.join(profile_path, 'map_key_features.json')
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            # --- 수정: 저장 전 데이터 정화 ---
            config_data = self._prepare_data_for_json({
                'minimap_region': self.minimap_region,
                'active_route_profile': self.active_route_profile_name,
                'route_profiles': self.route_profiles,
                'render_options': self.render_options,
                'reference_anchor_id': self.reference_anchor_id
            })
            key_features_data = self._prepare_data_for_json(self.key_features)
            geometry_data = self._prepare_data_for_json(self.geometry_data)
            # --- 수정 끝 ---

            with open(config_file, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4, ensure_ascii=False)
            with open(features_file, 'w', encoding='utf-8') as f: json.dump(key_features_data, f, indent=4, ensure_ascii=False)
            with open(geometry_file, 'w', encoding='utf-8') as f: json.dump(geometry_data, f, indent=4, ensure_ascii=False)
            
            # save 후에 뷰 업데이트
            self._update_map_data_and_views()

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
            
            #내비게이션 상태 초기화 로직 추가
            self.player_nav_state = 'on_terrain'
            self.current_player_floor = None
            self.last_terrain_line_id = None
            self.target_waypoint_id = None
            self.last_reached_wp_id = None
            self.current_path_index = -1
            self.is_forward = True
            self.start_waypoint_found = False
            
            if self.debug_view_checkbox.isChecked():
                if not self.debug_dialog:
                    self.debug_dialog = DebugViewDialog(self)
                self.debug_dialog.show()
                
            self.detection_thread = AnchorDetectionThread(self.minimap_region, self.key_features)
            self.detection_thread.detection_ready.connect(self.on_detection_ready)
            # --- 수정: status_updated 시그널을 올바른 슬롯에 연결 ---
            self.detection_thread.status_updated.connect(self.update_detection_log_message)
            self.detection_thread.start()
            self.detect_anchor_btn.setText("탐지 중단")
        else:
            if self.detection_thread and self.detection_thread.isRunning():
                self.detection_thread.stop()
                self.detection_thread.wait()
            self.update_general_log("탐지를 중단합니다.", "black")
            self.detect_anchor_btn.setText("탐지 시작")
            # --- 수정: 올바른 슬롯 호출 ---
            self.update_detection_log_message("탐지 중단됨", "black")
            self.minimap_view_label.setText("탐지 중단됨")
            self.detection_thread = None
            if self.debug_dialog:
                self.debug_dialog.close()

    def on_detection_ready(self, frame_bgr, found_features, my_player_rects, other_player_rects):
        """
        탐지 스레드로부터 받은 정보를 처리하고, RANSAC을 이용해 플레이어의 전역 좌표를 강건하게 추정합니다.
        """
        
        if not my_player_rects:
            self.update_detection_log_message("플레이어 아이콘 탐지 실패", "red")
            # 디버그 뷰에도 현재 상태 전송 (플레이어 위치 없음)
            if self.debug_dialog and self.debug_dialog.isVisible():
                self.debug_dialog.update_debug_info(frame_bgr, {'all_features': found_features, 'inlier_ids': set(), 'player_pos_local': None})
            return

        # --- 핵심 수정: 신뢰도 기반 사전 필터링 ---
        # RANSAC에 입력하기 전에, 각 지형의 개별 threshold를 통과한 지형들만 후보로 삼는다.
        reliable_features = []
        for f in found_features:
            if f['id'] in self.key_features and f['conf'] >= self.key_features[f['id']].get('threshold', 0.85):
                reliable_features.append(f)
        
        # --- 이하 모든 로직은 'found_features' 대신 'reliable_features'를 사용합니다. ---

        # 1. 데이터 준비: RANSAC에 사용할 (로컬 좌표, 전역 좌표) 쌍 생성
        source_points, dest_points, valid_features_map = [], [], {}
        feature_ids = []  # 추가: src/dst와 inliers 마스크를 동일한 순서로 매핑하기 위한 리스트 (중요)

        # --- 수정: found_features -> reliable_features ---
        for feature in reliable_features:
            feature_id = feature['id']
            if feature_id in self.global_positions:
                valid_features_map[feature_id] = feature
                size = feature['size']
                local_pos = QPointF(feature['local_pos'])
                global_pos = self.global_positions[feature_id]
                
                # 중심점 좌표 사용
                src_cx = local_pos.x() + size.width()/2
                src_cy = local_pos.y() + size.height()/2
                dst_cx = global_pos.x() + size.width()/2
                dst_cy = global_pos.y() + size.height()/2
                source_points.append([src_cx, src_cy])
                dest_points.append([dst_cx, dst_cy])
                feature_ids.append(feature_id)

        # 플레이어의 로컬 기준점 계산 (발밑 중앙)
        player_anchor_local = QPointF(self.minimap_region['width'] / 2.0, self.minimap_region['height'] / 2.0)
        if my_player_rects:
            player_rect = my_player_rects[0]
            player_anchor_local = QPointF(player_rect.center().x(), float(player_rect.y() + player_rect.height()) + PLAYER_Y_OFFSET)

        avg_player_global_pos = None
        inlier_ids = set() # 정상치로 판별된 지형 ID 저장용
        transform_matrix = None # 변환 행렬 초기화

        # 2. RANSAC 또는 Fallback 로직으로 위치 추정
        if len(source_points) < 3:
            # Fallback: 탐지된 지형이 3개 미만일 경우, 가중 평균으로 계산
            if valid_features_map:
                total_confidence = sum(f['conf'] for f in valid_features_map.values())
                if total_confidence > 0:
                    weighted_player_x_sum = 0
                    weighted_player_y_sum = 0
                    for feature in valid_features_map.values():
                        feature_center_local = QPointF(feature['local_pos']) + QPointF(feature['size'].width()/2, feature['size'].height()/2)
                        feature_center_global = self.global_positions[feature['id']] + QPointF(feature['size'].width()/2, feature['size'].height()/2)
                        
                        offset = player_anchor_local - feature_center_local
                        player_global_pos = feature_center_global + offset
                        
                        weighted_player_x_sum += player_global_pos.x() * feature['conf']
                        weighted_player_y_sum += player_global_pos.y() * feature['conf']
                    
                    avg_player_global_pos = QPointF(weighted_player_x_sum / total_confidence, weighted_player_y_sum / total_confidence)
                inlier_ids = set(valid_features_map.keys()) # Fallback 시에는 모두 정상치로 간주
        else:
            # RANSAC: 3개 이상 지형 탐지 시
            src_pts = np.float32(source_points)
            dst_pts = np.float32(dest_points)
            
            # 아핀 변환과 정상치를 찾음
            ransac_thresh = getattr(self, 'ransac_reproj_threshold', 3.0)
            max_iters = getattr(self, 'ransac_max_iters', 2000)
            transform_matrix, inliers = cv2.estimateAffinePartial2D(
                src_pts, dst_pts,
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_thresh,
                maxIters=max_iters
            )
             
            if inliers is None:
                transform_matrix = None
            else:
                inliers = inliers.reshape(-1)
                inlier_features = []
                for idx, fid in enumerate(feature_ids):
                    if inliers[idx] == 1:
                        inlier_features.append(valid_features_map[fid])
                        inlier_ids.add(fid)

                min_inliers_for_confidence = getattr(self, 'min_inliers_for_confidence', 3)
                if transform_matrix is not None and len(inlier_features) >= min_inliers_for_confidence:
                    A = transform_matrix[:, :2]
                    t = transform_matrix[:, 2]
                    px, py = player_anchor_local.x(), player_anchor_local.y()
                    transformed = (A @ np.array([px, py], dtype=np.float32)) + t
                    avg_player_global_pos = QPointF(float(transformed[0]), float(transformed[1]))
                else:
                    if inlier_features:
                        total_confidence = sum(f['conf'] for f in inlier_features)
                        if total_confidence > 0:
                            weighted_player_x_sum = 0
                            weighted_player_y_sum = 0
                            for feature in inlier_features:
                                feature_center_local = QPointF(feature['local_pos']) + QPointF(feature['size'].width()/2, feature['size'].height()/2)
                                feature_center_global = self.global_positions[feature['id']] + QPointF(feature['size'].width()/2, feature['size'].height()/2)
                                offset = player_anchor_local - feature_center_local
                                player_global_pos = feature_center_global + offset
                                weighted_player_x_sum += player_global_pos.x() * feature['conf']
                                weighted_player_y_sum += player_global_pos.y() * feature['conf']
                            avg_player_global_pos = QPointF(weighted_player_x_sum / total_confidence, weighted_player_y_sum / total_confidence)

        if avg_player_global_pos is None:
            # 위치 계산 실패 시 디버그 뷰만 업데이트하고 종료
            if self.debug_dialog and self.debug_dialog.isVisible():
                self.debug_dialog.update_debug_info(frame_bgr, {'all_features': found_features, 'inlier_ids': set(), 'player_pos_local': None})
            # --- 수정: 로그 업데이트 추가 ---
            self.update_detection_log_from_features([], [])
            return

        # 3. EMA 필터링으로 위치 스무딩
        min_alpha = getattr(self, 'min_alpha', 0.05)
        max_alpha = getattr(self, 'max_alpha', 0.5)
        inlier_count = max(1, len(inlier_ids))
        avg_conf = 0.0
        if inlier_count > 0:
            try:
                inlier_features_for_conf = [valid_features_map[fid] for fid in inlier_ids]
                avg_conf = sum(f['conf'] for f in inlier_features_for_conf) / len(inlier_features_for_conf)
            except Exception:
                avg_conf = 1.0
        alpha = min_alpha + (max_alpha - min_alpha) * (min(1.0, avg_conf) * min(1.0, inlier_count / 6.0))
        if self.smoothed_player_pos is None:
            self.smoothed_player_pos = avg_player_global_pos
        else:
            new_x = (avg_player_global_pos.x() * alpha) + (self.smoothed_player_pos.x() * (1 - alpha))
            new_y = (avg_player_global_pos.y() * alpha) + (self.smoothed_player_pos.y() * (1 - alpha))
            self.smoothed_player_pos = QPointF(new_x, new_y)
        
        final_player_pos = self.smoothed_player_pos # 최종 플레이어의 전역 좌표

        # 상태 업데이트 메서드 호출 추가
        self._update_player_state_and_navigation(final_player_pos)


        # 4. 디버그 뷰 업데이트
        if self.debug_dialog and self.debug_dialog.isVisible():
            debug_data = {
                'all_features': found_features,
                'inlier_ids': inlier_ids,
                'player_pos_local': player_anchor_local,
                'ransac_matrix': transform_matrix,
                'ransac_inliers': list(inlier_ids)
            }
            self.debug_dialog.update_debug_info(frame_bgr, debug_data)

        # 5. 메인 뷰 렌더링 데이터 준비 및 업데이트
        my_player_global_rects = []
        other_player_global_rects = []
        if transform_matrix is not None:
            A = transform_matrix[:, :2]
            t = transform_matrix[:, 2]
            def transform_point(x, y):
                res = (A @ np.array([x, y], dtype=np.float32)) + t
                return float(res[0]), float(res[1])

            def transform_rect(rect):
                corners = [
                    (rect.left(), rect.top()), (rect.right(), rect.top()),
                    (rect.right(), rect.bottom()), (rect.left(), rect.bottom()),
                ]
                txs, tys = zip(*[transform_point(x, y) for (x, y) in corners])
                min_x, max_x = min(txs), max(txs)
                min_y, max_y = min(tys), max(tys)
                return QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

            my_player_global_rects = [transform_rect(rect) for rect in my_player_rects]
            other_player_global_rects = [transform_rect(rect) for rect in other_player_rects]
        else:
            def local_rect_to_global_center(rect, features_source):
                if not features_source:
                    return QPointF(final_player_pos.x(), final_player_pos.y())

                rx, ry = rect.center().x(), rect.center().y()
                sum_x, sum_y, sum_w = 0.0, 0.0, 0.0
                for f in features_source:
                    fid = f['id']
                    if fid not in self.global_positions: continue
                    f_local = QPointF(f['local_pos']) + QPointF(f['size'].width()/2, f['size'].height()/2)
                    f_global = self.global_positions[fid] + QPointF(f['size'].width()/2, f['size'].height()/2)
                    dx_local, dy_local = rx - f_local.x(), ry - f_local.y()
                    cand_x, cand_y = f_global.x() + dx_local, f_global.y() + dy_local
                    w = f.get('conf', 1.0)
                    sum_x += cand_x * w
                    sum_y += cand_y * w
                    sum_w += w
                if sum_w <= 0: return QPointF(final_player_pos.x(), final_player_pos.y())
                return QPointF(sum_x / sum_w, sum_y / sum_w)

            fallback_features = [valid_features_map[fid] for fid in inlier_ids] if inlier_ids else list(valid_features_map.values())

            for rect in my_player_rects:
                center_global = local_rect_to_global_center(rect, fallback_features)
                my_player_global_rects.append(QRectF(center_global.x() - rect.width()/2, center_global.y() - rect.height()/2, rect.width(), rect.height()))

            for rect in other_player_global_rects:
                center_global = local_rect_to_global_center(rect, fallback_features)
                other_player_global_rects.append(QRectF(center_global.x() - rect.width()/2, center_global.y() - rect.height()/2, rect.width(), rect.height()))
        
        camera_pos_to_send = final_player_pos if self.center_on_player_checkbox.isChecked() else self.minimap_view_label.camera_center_global
        
        self.minimap_view_label.update_view_data(
            camera_center=camera_pos_to_send,
            active_features=found_features,
            my_players=my_player_global_rects,
            other_players=other_player_global_rects,
            target_wp_id=self.target_waypoint_id,
            reached_wp_id=self.last_reached_wp_id,
            final_player_pos=final_player_pos,
            is_forward=self.is_forward
        )
        
        self.global_pos_updated.emit(final_player_pos)
        
        # --- 수정: found_features -> reliable_features ---
        inlier_list = [f for f in reliable_features if f['id'] in inlier_ids]
        outlier_list = [f for f in reliable_features if f['id'] not in inlier_ids]
        
        self.update_detection_log_from_features(inlier_list, outlier_list)

        
    def _generate_full_map_pixmap(self):
            """
            v10.0.0: 모든 핵심 지형의 문맥 이미지를 합성하여 하나의 큰 배경 지도 QPixmap을 생성하고,
            모든 맵 요소의 전체 경계를 계산하여 저장합니다.
            """
            if not self.global_positions:
                self.full_map_pixmap = None
                self.full_map_bounding_rect = QRectF()
                return

            bounding_rect = QRectF()
            all_items_rects = []
            
            # --- 수정: 핵심 지형의 문맥 이미지를 기준으로 경계 계산 ---
            for feature_id, feature_data in self.key_features.items():
                context_pos_key = f"{feature_id}_context"
                if context_pos_key in self.global_positions:
                    context_origin = self.global_positions[context_pos_key]
                    if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
                        try:
                            img_data = base64.b64decode(feature_data['context_image_base64'])
                            pixmap = QPixmap(); pixmap.loadFromData(img_data)
                            if not pixmap.isNull():
                                all_items_rects.append(QRectF(context_origin, QSizeF(pixmap.size())))
                        except Exception as e:
                            print(f"문맥 이미지 로드 오류 (ID: {feature_id}): {e}")
            # --- 수정 끝 ---
            
            # 지형선, 오브젝트 등의 경계도 포함
            all_points = []
            for line in self.geometry_data.get("terrain_lines", []): all_points.extend(line.get("points", []))
            for obj in self.geometry_data.get("transition_objects", []): all_points.extend(obj.get("points", []))
            
            if all_points:
                xs = [p[0] for p in all_points]
                ys = [p[1] for p in all_points]
                all_items_rects.append(QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))

            if not all_items_rects:
                self.full_map_pixmap = None
                self.full_map_bounding_rect = QRectF()
                self.update_general_log("배경 지도 생성 실패: 그릴 이미지가 없습니다.", "orange")
                return

            for rect in all_items_rects:
                bounding_rect = bounding_rect.united(rect)

            bounding_rect.adjust(-50, -50, 50, 50)
            self.full_map_bounding_rect = bounding_rect

            self.full_map_pixmap = QPixmap(bounding_rect.size().toSize())
            self.full_map_pixmap.fill(QColor(50, 50, 50))
            
            painter = QPainter(self.full_map_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(-bounding_rect.topLeft())

            # --- 수정: 핵심 지형의 문맥 이미지 그리기 ---
            if self.render_options.get('background', True):
                painter.setOpacity(0.7) # 투명도 조절
                for feature_id, feature_data in self.key_features.items():
                    context_pos_key = f"{feature_id}_context"
                    if context_pos_key in self.global_positions:
                        context_origin = self.global_positions[context_pos_key]
                        if 'context_image_base64' in feature_data and feature_data['context_image_base64']:
                            try:
                                img_data = base64.b64decode(feature_data['context_image_base64'])
                                pixmap = QPixmap(); pixmap.loadFromData(img_data)
                                if not pixmap.isNull():
                                    painter.drawPixmap(context_origin, pixmap)
                            except Exception as e:
                                print(f"문맥 이미지 그리기 오류 (ID: {feature_id}): {e}")
            # --- 수정 끝 ---
            
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

    def _update_player_state_and_navigation(self, final_player_pos):
            """플레이어의 현재 위치를 기반으로 층, 상태를 판단하고 다음 목표를 결정합니다."""
            if final_player_pos is None:
                return

            # 1. 현재 층 및 상태 판단 로직
            contact_terrain = None
            min_y_dist = 5.0
            player_x = final_player_pos.x()
            player_y = final_player_pos.y()
            for line_data in self.geometry_data.get("terrain_lines", []):
                points = line_data.get("points", [])
                if len(points) < 2: continue
                
                for i in range(len(points) - 1):
                    p1 = points[i]
                    p2 = points[i+1]
                    min_lx, max_lx = min(p1[0], p2[0]), max(p1[0], p2[0])

                    if not (min_lx <= player_x <= max_lx):
                        continue

                    line_y = p1[1] + (p2[1] - p1[1]) * ((player_x - p1[0]) / (p2[0] - p1[0])) if (p2[0] - p1[0]) != 0 else p1[1]
                    y_dist = abs(player_y - line_y)

                    if y_dist < min_y_dist:
                        min_y_dist = y_dist
                        contact_terrain = line_data
            
            if contact_terrain:
                self.player_nav_state = 'on_terrain'
                self.current_player_floor = contact_terrain.get('floor')
                self.last_terrain_line_id = contact_terrain.get('id')
            else:
                is_climbing = False
                climbing_margin = 5
                for obj_data in self.geometry_data.get("transition_objects", []):
                    obj_x = obj_data.get("points", [[0,0]])[0][0]
                    if abs(player_x - obj_x) < climbing_margin:
                        is_climbing = True
                        break
                if is_climbing: self.player_nav_state = 'climbing'
                else:
                    delta_y = player_y - self.last_player_pos.y()
                    if delta_y < -1: self.player_nav_state = 'jumping'
                    elif delta_y > 1: self.player_nav_state = 'falling'

            # 2. 현재 목표(Current Target) 결정 로직
            active_route = self.route_profiles.get(self.active_route_profile_name)
            if not active_route: return
            all_waypoints_map = {wp['id']: wp for wp in self.geometry_data.get("waypoints", [])}
            
            # 2a. 시작점이 아직 찾아지지 않았다면, 지능형 시작점 탐색 실행
            if not self.start_waypoint_found and self.current_player_floor is not None:
                forward_path = active_route.get("forward_path", [])
                backward_path = active_route.get("backward_path", [])
                all_wp_ids_in_path = set(forward_path + backward_path)
                
                if not all_wp_ids_in_path: return
                
                # 1. 경로에 있는 모든 웨이포인트를 층별로 그룹화
                wps_by_floor = defaultdict(list)
                for wp_id in all_wp_ids_in_path:
                    if wp_id in all_waypoints_map:
                        wp_data = all_waypoints_map[wp_id]
                        wps_by_floor[wp_data.get('floor')].append(wp_data)

                if not wps_by_floor: return

                # 2. 가장 가까운 층(들) 찾기
                min_floor_diff = float('inf')
                for floor in wps_by_floor.keys():
                    diff = abs(self.current_player_floor - floor)
                    if diff < min_floor_diff:
                        min_floor_diff = diff
                
                # 3. 최우선 후보군 필터링 (가장 가까운 층에 있는 모든 웨이포인트)
                final_candidate_wps = []
                for floor, wps in wps_by_floor.items():
                    if abs(self.current_player_floor - floor) == min_floor_diff:
                        final_candidate_wps.extend(wps)

                # 4. 최종 후보군 내에서 비용이 가장 낮은 웨이포인트 찾기
                start_wp_candidate = None
                if final_candidate_wps:
                    all_objs = self.geometry_data.get("transition_objects", [])
                    start_wp_candidate = min(final_candidate_wps, 
                                            key=lambda wp: self._calculate_path_cost(final_player_pos, self.current_player_floor, wp, all_objs))

                if start_wp_candidate:
                    start_wp_id = start_wp_candidate['id']
                    
                    # 진행 방향 결정
                    if start_wp_id in forward_path:
                        forward_index = forward_path.index(start_wp_id)
                        forward_len = len(forward_path)
                        dist_to_start = forward_index
                        dist_to_end = forward_len - 1 - forward_index
                        
                        if dist_to_start <= dist_to_end:
                            self.is_forward = True
                            self.current_path_index = forward_index
                        else:
                            self.is_forward = False
                            path_to_use = backward_path if backward_path else list(reversed(forward_path))
                            if start_wp_id in path_to_use: self.current_path_index = path_to_use.index(start_wp_id)
                            else: self.is_forward = True; self.current_path_index = forward_index
                    else:
                        self.is_forward = False
                        path_to_use = backward_path if backward_path else []
                        if start_wp_id in path_to_use: self.current_path_index = path_to_use.index(start_wp_id)
                    
                    self.target_waypoint_id = start_wp_id
                    self.start_waypoint_found = True
                    self.update_general_log(f"가장 가까운 경로의 웨이포인트 '{start_wp_candidate['name']}'({start_wp_candidate['floor']}층)에서 내비게이션 시작.", "purple")

            # 2b. (시작점 찾은 후) 현재 목표에 도달했는지 확인
            elif self.target_waypoint_id:
                target_wp_data = all_waypoints_map.get(self.target_waypoint_id)
                if target_wp_data:
                    target_pos = QPointF(target_wp_data['pos'][0], target_wp_data['pos'][1])
                    if (abs(final_player_pos.x() - target_pos.x()) < 10 and abs(final_player_pos.y() - target_pos.y()) < 15):
                        self.last_reached_wp_id = self.target_waypoint_id
                        
                        current_path_list = active_route.get("forward_path" if self.is_forward else "backward_path", [])
                        if not current_path_list and self.is_forward is False:
                            current_path_list = list(reversed(active_route.get("forward_path", [])))

                        self.current_path_index += 1

                        if self.current_path_index < len(current_path_list):
                            self.target_waypoint_id = current_path_list[self.current_path_index]
                        else:
                            self.is_forward = not self.is_forward
                            next_path_list = active_route.get("forward_path" if self.is_forward else "backward_path", [])
                            if not next_path_list and self.is_forward is False:
                                next_path_list = list(reversed(active_route.get("forward_path", [])))
                            
                            if next_path_list:
                                self.current_path_index = 0
                                self.target_waypoint_id = next_path_list[0]
                            else:
                                self.target_waypoint_id = None
                                self.update_general_log("경로 완주. 순환할 경로가 없습니다.", "green")

            # 3. 마무리
            self.last_player_pos = final_player_pos

    def update_general_log(self, message, color):
        self.general_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.general_log_viewer.verticalScrollBar().setValue(self.general_log_viewer.verticalScrollBar().maximum())
        
    def update_detection_log_from_features(self, inliers, outliers):
        """정상치와 이상치 피처 목록을 받아 탐지 상태 로그를 업데이트합니다."""
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

    def _update_map_data_and_views(self):
            """데이터 변경 후 전역 좌표와 전체 맵 뷰를 갱신합니다."""
            self.global_positions = self._calculate_global_positions()
            self._generate_full_map_pixmap()
            self._assign_dynamic_names() #동적 이름 부여 메서드 호출 추가
            self.update_general_log("맵 데이터를 최신 정보로 갱신했습니다.", "purple")

    def _calculate_global_positions(self):
        """
        v10.0.0: 기준 앵커를 원점으로 하여 모든 핵심 지형과 구버전 웨이포인트의 전역 좌표를 계산합니다.
        핵심 지형 간의 양방향 템플릿 매칭을 통해 웨이포인트 없이도 좌표계를 확장합니다. (임계값 조정 및 디버깅 로그 추가)
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
        
        # 2. 핵심 지형 좌표 계산 (양방향 탐색 로직)
        known_features = {anchor_id}
        pending_features = set(self.key_features.keys()) - known_features
        
        global_positions[anchor_id] = QPointF(0, 0)

        templates = {}
        contexts = {}
        for f_id, f_data in self.key_features.items():
            try:
                img_data = base64.b64decode(f_data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                templates[f_id] = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                if 'context_image_base64' in f_data and f_data['context_image_base64']:
                    context_img_data = base64.b64decode(f_data['context_image_base64'])
                    context_np_arr = np.frombuffer(context_img_data, np.uint8)
                    contexts[f_id] = cv2.imdecode(context_np_arr, cv2.IMREAD_GRAYSCALE)
                else:
                    contexts[f_id] = None
            except Exception as e:
                print(f"이미지 디코딩 오류 (ID: {f_id}): {e}")
                templates[f_id] = None
                contexts[f_id] = None

        MATCH_THRESHOLD = 0.90  # --- 임계값 하향 조정 ---

        for _ in range(len(self.key_features) + 1):
            if not pending_features:
                break
            
            found_in_iteration = set()
            
            for pending_id in pending_features:
                is_found = False
                for known_id in known_features:
                    
                    # 탐색 A: known의 문맥에서 pending 찾기
                    known_context = contexts.get(known_id)
                    pending_template = templates.get(pending_id)
                    if known_context is not None and pending_template is not None:
                        res = cv2.matchTemplate(known_context, pending_template, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        # print(f"[DEBUG] 탐색 A: {known_id}(문맥) -> {pending_id}(템플릿) | 매칭률: {max_val:.4f}") # 디버그 로그
                        if max_val >= MATCH_THRESHOLD:
                            known_global_pos = global_positions[known_id]
                            known_rect = self.key_features[known_id].get('rect_in_context', [0,0,0,0])
                            known_local_pos_in_context = QPointF(known_rect[0], known_rect[1])
                            context_global_origin = known_global_pos - known_local_pos_in_context
                            pending_local_pos_in_context = QPointF(max_loc[0], max_loc[1])
                            pending_global_pos = context_global_origin + pending_local_pos_in_context
                            global_positions[pending_id] = pending_global_pos
                            is_found = True

                    if is_found: break

                    # 탐색 B: pending의 문맥에서 known 찾기
                    pending_context = contexts.get(pending_id)
                    known_template = templates.get(known_id)
                    if pending_context is not None and known_template is not None:
                        res = cv2.matchTemplate(pending_context, known_template, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        # print(f"[DEBUG] 탐색 B: {pending_id}(문맥) -> {known_id}(템플릿) | 매칭률: {max_val:.4f}") # 디버그 로그
                        if max_val >= MATCH_THRESHOLD:
                            known_global_pos = global_positions[known_id]
                            pending_rect = self.key_features[pending_id].get('rect_in_context', [0,0,0,0])
                            pending_local_pos_in_context = QPointF(pending_rect[0], pending_rect[1])
                            known_local_pos_in_pending_context = QPointF(max_loc[0], max_loc[1])
                            context_global_origin = known_global_pos - known_local_pos_in_pending_context
                            pending_global_pos = context_global_origin + pending_local_pos_in_context
                            global_positions[pending_id] = pending_global_pos
                            is_found = True

                    if is_found: break
                
                if is_found:
                    found_in_iteration.add(pending_id)

            if found_in_iteration:
                known_features.update(found_in_iteration)
                pending_features -= found_in_iteration
            else:
                break
        
        if pending_features:
            failed_ids = ", ".join(sorted(list(pending_features)))
            message = (f"경고: 다음 핵심 지형들의 위치를 계산하지 못했습니다: {failed_ids}. ...") # 이하 동일
            self.update_general_log(message, "orange")

        # (이하 문맥 원점 계산 및 구버전 웨이포인트 처리 로직은 동일)
        # ... (이전 답변과 동일한 코드) ...
        # 3. 모든 핵심 지형의 문맥 이미지 원점 좌표 계산
        for feature_id in known_features:
            if feature_id in global_positions:
                feature_data = self.key_features[feature_id]
                if 'rect_in_context' in feature_data and feature_data['rect_in_context']:
                    rect = feature_data['rect_in_context']
                    feature_local_pos_in_context = QPointF(rect[0], rect[1])
                    context_origin_pos = global_positions[feature_id] - feature_local_pos_in_context
                    global_positions[f"{feature_id}_context"] = context_origin_pos

        # 4. 구버전 웨이포인트 처리 (호환성 유지)
        all_waypoints_old = self.get_all_waypoints_with_route_name()
        if all_waypoints_old:
            pending_waypoints = all_waypoints_old[:]
            for _ in range(len(all_waypoints_old) + 5):
                found_new = False
                remaining_waypoints = []
                for wp in pending_waypoints:
                    known_ref_feature = next((link for link in wp.get('key_feature_ids', []) if link['id'] in global_positions), None)
                    if known_ref_feature:
                        found_new = True
                        try:
                            img_data = base64.b64decode(wp['image_base64'])
                            np_arr = np.frombuffer(img_data, np.uint8)
                            wp_map_gray = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                            feature_id = known_ref_feature['id']
                            template = templates.get(feature_id)
                            if wp_map_gray is None or template is None: continue
                            res = cv2.matchTemplate(wp_map_gray, template, cv2.TM_CCOEFF_NORMED)
                            _, _, _, max_loc = cv2.minMaxLoc(res)
                            ref_global_pos = global_positions[feature_id]
                            ref_local_pos_in_wp = QPointF(max_loc[0], max_loc[1])
                            wp_map_global_origin = ref_global_pos - ref_local_pos_in_wp
                            offset_x, offset_y = known_ref_feature['offset_to_target']
                            wp_target_global_pos = ref_global_pos + QPointF(offset_x, offset_y)
                            global_positions[wp['name']] = {'map_origin': wp_map_global_origin, 'target_pos': wp_target_global_pos}
                        except Exception as e:
                            print(f"Error processing old waypoint {wp.get('name', 'N/A')}: {e}")
                    else:
                        remaining_waypoints.append(wp)
                pending_waypoints = remaining_waypoints
                if not found_new or not pending_waypoints:
                    break

        # 5. 모든 핵심 지형 쌍 간의 상대 위치 벡터 미리 계산
        self.feature_offsets.clear()
        known_feature_ids = [fid for fid in known_features if fid in global_positions]
        for i in range(len(known_feature_ids)):
            for j in range(i + 1, len(known_feature_ids)):
                id1 = known_feature_ids[i]
                id2 = known_feature_ids[j]
                pos1 = global_positions[id1]
                pos2 = global_positions[id2]
                
                # 중심점 기준 오프셋 계산
                # --- 수정: 리스트로 저장된 size를 QSize 객체로 변환 ---
                size1_data = self.key_features[id1].get('size')
                size2_data = self.key_features[id2].get('size')
                size1 = QSize(size1_data[0], size1_data[1]) if isinstance(size1_data, list) and len(size1_data) == 2 else QSize(0,0)
                size2 = QSize(size2_data[0], size2_data[1]) if isinstance(size2_data, list) and len(size2_data) == 2 else QSize(0,0)
                # --- 수정 끝 ---
                center1 = pos1 + QPointF(size1.width()/2, size1.height()/2)
                center2 = pos2 + QPointF(size2.width()/2, size2.height()/2)

                offset = center2 - center1
                self.feature_offsets[(id1, id2)] = offset
                self.feature_offsets[(id2, id1)] = -offset

        return global_positions

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
            # 부모 지형 그룹 이름별로 오브젝트 그룹화
            objs_by_parent_group = defaultdict(list)
            for obj in transition_objects:
                parent_id = obj.get('parent_line_id')
                if parent_id and parent_id in line_id_to_group_name:
                    parent_group_name = line_id_to_group_name[parent_id]
                    objs_by_parent_group[parent_group_name].append(obj)

            for parent_name, objs in objs_by_parent_group.items():
                # x축 기준으로 정렬하여 이름 부여
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