# map.py
# 2025년 08月 22日 15:00 (KST)
# 기능: 전체 맵 이미지 기반 실시간 뷰 및 내비게이션 시스템
# 설명:
# - v8.1.0: [구조개선] 실시간 미니맵 시스템을 전체 맵 이미지 기반으로 전면 개편.
#           - [추가] `MinimapViewWidget`: 전체 맵 이미지를 렌더링하고 줌/패닝을 지원하는 커스텀 위젯 추가.
#           - [수정] `AnchorDetectionThread`: 복잡한 위치 추정 로직을 제거하고, 순수 객체(핵심 지형, 플레이어) 탐지 역할만 수행하도록 단순화.
#           - [수정] `MapTab`: 탐지된 지형의 로컬/전역 좌표를 비교하여 오프셋을 계산하고, 이를 `MinimapViewWidget`에 전달하여 전체 맵을 패닝하는 방식으로 렌더링 로직 변경.
#           - [추가] `FullMinimapEditorDialog`: 편집기 저장 시, 현재 씬을 `global_map.png` 파일로 자동 저장하는 기능 추가.
#           - [개선] 모든 좌표 계산 로직에서 QPointF를 사용하여 타입 오류를 방지하고 정밀도 향상.
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
# - v7.7.2: [버그수정] X,Y축 동시 고정 모드에서 발생하던 AttributeError 해결.
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

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QMessageBox, QSpinBox, QDialog, QDialogButtonBox, QListWidget,
    QInputDialog, QListWidgetItem, QDoubleSpinBox, QAbstractItemView,
    QLineEdit, QRadioButton, QButtonGroup, QGroupBox, QComboBox,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QCheckBox, QGraphicsRectItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsEllipseItem
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QCursor, QIcon, QTransform
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

# --- v7.2.0: 마우스 휠 줌 기능이 추가된 커스텀 QGraphicsView ---
class CustomGraphicsView(QGraphicsView):
    mousePressed = pyqtSignal(QPointF, Qt.MouseButton)
    mouseMoved = pyqtSignal(QPointF)
    mouseReleased = pyqtSignal(QPointF, Qt.MouseButton)

    # --- v7.8.1 수정: 부모 다이얼로그 참조를 위한 __init__ 수정 ---
    def __init__(self, scene, parent_dialog=None):
        super().__init__(scene)
        self.parent_dialog = parent_dialog

    def wheelEvent(self, event):
        # --- v7.8.1 수정: 모드별 휠 동작 분기 ---
        current_mode = self.parent_dialog.current_mode if self.parent_dialog else "select"

        if current_mode == "select": # '기본' 모드일 때
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept() # 이벤트 전파를 막아 스크롤 방지
        else: # '지형 입력', '오브젝트 추가' 모드일 때
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
                self.scale(factor, factor)
            else:
                super().wheelEvent(event) # 기본 스크롤 동작 수행
    
    def mousePressEvent(self, event):
        self.mousePressed.emit(self.mapToScene(event.pos()), event.button())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.mouseMoved.emit(self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.mouseReleased.emit(self.mapToScene(event.pos()), event.button())
        super().mouseReleaseEvent(event)

# --- v7.0.0: 전체 미니맵 편집기 다이얼로그 추가 ---
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
        self.all_waypoints = [wp for route in route_profiles.values() for wp in route.get('waypoints', [])]
        # --- v7.5.4 수정: 원본 데이터 대신 깊은 복사본을 사용 ---
        self.geometry_data = copy.deepcopy(geometry_data)
        # --- v7.9.5 수정: 렌더링 옵션 저장 ---
        self.render_options = render_options
        # --- v8.0.0: 외부에서 계산된 전역 좌표 사용 ---
        self.global_positions = global_positions
        self.parent_map_tab = parent
        self.active_route_profile = active_route_profile
        
        # --- v7.3.0: 그리기 상태 변수 추가 ---
        self.current_mode = "select" # "select", "terrain", "object"
        self.is_drawing_line = False
        self.current_line_points = []
        self.preview_line_item = None
        self.snap_indicator = None
        self.snap_radius = 10
        # --- v7.5.0: 오브젝트 그리기 상태 변수 추가 ---
        self.is_drawing_object = False
        self.object_start_pos = None
        self.preview_object_item = None
        # --- v7.5.2: 오브젝트 부모 ID 저장 변수 추가 ---
        self.current_object_parent_id = None
        # --- v7.7.1: 명칭 변경 (height -> y) ---
        self.is_y_locked = False
        self.locked_position = None # (x, y) 좌표를 저장할 QPointF
        self.y_indicator_line = None
        # --- v7.7.0: X축 고정 상태 변수 추가 ---
        self.is_x_locked = False
        # --- v7.8.1 추가: 초기 배율 조정을 한 번만 실행하기 위한 플래그 ---
        self._initial_fit_done = False
        # --- v7.2.0: 핵심 지형별 색상 맵 생성 ---
        self.feature_color_map = self._create_feature_color_map()
        self.initUI()
        self.populate_scene()
        self._update_visibility()

    def showEvent(self, event):
        """다이얼로그가 화면에 표시될 때 초기 배율을 설정합니다."""
        super().showEvent(event)
        if not self._initial_fit_done:
            bounding_rect = self.scene.itemsBoundingRect()
            if not bounding_rect.isNull():
                bounding_rect.adjust(-50, -50, 50, 50)
                self.view.fitInView(bounding_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._initial_fit_done = True
            
    def initUI(self):
        main_layout = QHBoxLayout(self)

        # 좌측: 도구 모음
        toolbar_group = QGroupBox("도구")
        toolbar_layout = QVBoxLayout()
        toolbar_group.setLayout(toolbar_layout)
        toolbar_group.setFixedWidth(220)

        # --- v7.2.0: 경로 프로필 선택 콤보박스 추가 ---
        route_box = QGroupBox("경로 프로필 필터")
        route_layout = QVBoxLayout()
        self.route_profile_selector = QComboBox()
        self.route_profile_selector.addItems(list(self.route_profiles.keys()))
        if self.active_route_profile in self.route_profiles:
            self.route_profile_selector.setCurrentText(self.active_route_profile)
        self.route_profile_selector.currentIndexChanged.connect(self._update_visibility)
        route_layout.addWidget(self.route_profile_selector)
        route_box.setLayout(route_layout)

        # 편집 모드
        mode_box = QGroupBox("편집 모드")
        mode_layout = QVBoxLayout()
        # --- v7.8.0: 텍스트 변경 ---
        self.select_mode_radio = QRadioButton("기본") 
        self.terrain_mode_radio = QRadioButton("지형 입력")
        self.object_mode_radio = QRadioButton("층 이동 오브젝트 추가")
        self.select_mode_radio.setChecked(True)
        self.select_mode_radio.toggled.connect(lambda: self.set_mode("select"))
        self.terrain_mode_radio.toggled.connect(lambda: self.set_mode("terrain"))
        self.object_mode_radio.toggled.connect(lambda: self.set_mode("object"))
        mode_layout.addWidget(self.select_mode_radio)
        mode_layout.addWidget(self.terrain_mode_radio)
        mode_layout.addWidget(self.object_mode_radio)
        mode_box.setLayout(mode_layout)

        # 지형 입력 옵션
        terrain_opts_box = QGroupBox("지형 옵션")
        terrain_opts_layout = QVBoxLayout()
        # --- v7.7.1: 명칭 변경 및 변수명 변경 ---
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
        
        # --- v7.9.6 수정: 모든 체크박스가 저장된 값으로 초기화되도록 변경 ---
        self.chk_show_background = QCheckBox("미니맵 배경")
        self.chk_show_background.setChecked(self.render_options.get('background', True))
        self.chk_show_background.stateChanged.connect(self._update_visibility)
        
        self.chk_show_features = QCheckBox("핵심 지형")
        self.chk_show_features.setChecked(self.render_options.get('features', True))
        self.chk_show_features.stateChanged.connect(self._update_visibility)
        
        self.chk_show_waypoints = QCheckBox("웨이포인트")
        self.chk_show_waypoints.setChecked(self.render_options.get('waypoints', True))
        self.chk_show_waypoints.stateChanged.connect(self._update_visibility)
        
        self.chk_show_links = QCheckBox("관계선")
        self.chk_show_links.setChecked(self.render_options.get('links', True))
        self.chk_show_links.stateChanged.connect(self._update_visibility)
        
        self.chk_show_terrain = QCheckBox("지형선")
        self.chk_show_terrain.setChecked(self.render_options.get('terrain', True))
        self.chk_show_terrain.stateChanged.connect(self._update_visibility)
        
        self.chk_show_objects = QCheckBox("층 이동 오브젝트")
        self.chk_show_objects.setChecked(self.render_options.get('objects', True))
        self.chk_show_objects.stateChanged.connect(self._update_visibility)
        
        zoom_layout = QHBoxLayout()
        zoom_in_btn = QPushButton("확대")
        zoom_out_btn = QPushButton("축소")
        zoom_in_btn.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        zoom_out_btn.clicked.connect(lambda: self.view.scale(1/1.2, 1/1.2))
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addWidget(zoom_out_btn)

        view_opts_layout.addWidget(self.chk_show_background)
        view_opts_layout.addWidget(self.chk_show_features)
        view_opts_layout.addWidget(self.chk_show_waypoints)
        view_opts_layout.addWidget(self.chk_show_links)
        view_opts_layout.addWidget(self.chk_show_terrain)
        view_opts_layout.addWidget(self.chk_show_objects)
        view_opts_layout.addLayout(zoom_layout)
        view_opts_box.setLayout(view_opts_layout)

        toolbar_layout.addWidget(route_box)
        toolbar_layout.addWidget(mode_box)
        toolbar_layout.addWidget(terrain_opts_box)
        toolbar_layout.addWidget(view_opts_box)
        toolbar_layout.addStretch(1)

        # 우측: 그래픽 뷰 (캔버스)
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor(50, 50, 50))) # 어두운 회색 배경
        # --- v7.8.1 수정: CustomGraphicsView 생성 시 부모 참조 전달 ---
        self.view = CustomGraphicsView(self.scene, parent_dialog=self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag) # 마우스 드래그로 패닝
        # --- v7.3.0: 마우스 이벤트 시그널 연결 ---
        self.view.mousePressed.connect(self.on_scene_mouse_press)
        self.view.mouseMoved.connect(self.on_scene_mouse_move)
        
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
            'links': self.chk_show_links.isChecked(),
            'terrain': self.chk_show_terrain.isChecked(),
            'objects': self.chk_show_objects.isChecked()
        }
        
    def set_mode(self, mode):
        """편집기 모드를 변경하고 UI를 업데이트합니다."""
        self.current_mode = mode
        # 그리던 라인이 있다면 종료
        if self.is_drawing_line:
            self._finish_drawing_line()
        if self.is_drawing_object:
            self._finish_drawing_object(cancel=True)

        if mode == "terrain" or mode == "object":
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
            
    def update_locked_position(self, y_pos, x_pos):
        self.locked_position = QPointF(x_pos, y_pos)
        if not self.y_indicator_line:
            pen = QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine)
            self.y_indicator_line = self.scene.addLine(0, 0, 1, 1, pen)
            self.y_indicator_line.setZValue(200)
        
        scene_rect = self.scene.sceneRect()
        if not scene_rect.isValid(): return
        self.y_indicator_line.setLine(scene_rect.left(), y_pos, scene_rect.right(), y_pos)
        
        if self.is_y_locked:
            self.y_indicator_line.setVisible(True)
        else:
            self.y_indicator_line.setVisible(False)
        
    def update_locked_y_position(self, y_pos):
        self.locked_y_position = y_pos
        if not self.height_indicator_line:
            # 씬의 경계를 가로지르는 긴 선으로 생성
            pen = QPen(QColor(255, 0, 0, 150), 1, Qt.PenStyle.DashLine)
            self.height_indicator_line = self.scene.addLine(0, 0, 1, 1, pen)
            self.height_indicator_line.setZValue(200) # 항상 위에 보이도록
        
        scene_rect = self.scene.sceneRect()
        self.height_indicator_line.setLine(scene_rect.left(), y_pos, scene_rect.right(), y_pos)
        
        if self.is_height_locked:
            self.height_indicator_line.setVisible(True)
        else:
            self.height_indicator_line.setVisible(False)

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

    def populate_scene(self):
        self.scene.clear()
        
        # --- v8.0.0: 자체 계산 대신 전달받은 전역 좌표 사용 ---
        if not self.global_positions:
            text_item = self.scene.addText("표시할 데이터가 부족합니다.\n핵심 지형과 웨이포인트를 1개 이상 등록해주세요.")
            text_item.setDefaultTextColor(Qt.GlobalColor.white)
            return

        # 2. 웨이포인트 미니맵 이미지 그리기 (배경)
        for wp in self.all_waypoints:
            if wp['name'] in self.global_positions:
                pos_data = self.global_positions[wp['name']]
                img_data = base64.b64decode(wp['image_base64'])
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                
                pixmap_item = self.scene.addPixmap(pixmap)
                pixmap_item.setPos(pos_data['map_origin'])
                pixmap_item.setOpacity(0.5) # 반투명하게 설정
                pixmap_item.setZValue(-10) # 맨 뒤로 보내기
                pixmap_item.setData(0, "background")

        # 3. 핵심 지형 및 웨이포인트 목표 지점 그리기
        for item_id, pos in self.global_positions.items():
            # 핵심 지형 그리기
            if item_id in self.key_features:
                feature_data = self.key_features[item_id]
                img_data = base64.b64decode(feature_data['image_base64'])
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                
                rect_item = self.scene.addRect(0, 0, pixmap.width(), pixmap.height(), QPen(QColor(0, 255, 255)), QBrush(QColor(0, 255, 255, 80)))
                rect_item.setPos(pos)
                rect_item.setData(0, "feature")
                text_item = self.scene.addText(item_id)
                text_item.setDefaultTextColor(Qt.GlobalColor.white)
                text_item.setPos(pos)
                text_item.setData(0, "feature")
            
            # 웨이포인트 목표 지점 그리기
            elif isinstance(pos, dict) and 'target_pos' in pos:
                wp_data = next((wp for wp in self.all_waypoints if wp['name'] == item_id), None)
                if wp_data:
                    rect_norm = wp_data['rect_normalized']
                    # 웨이포인트의 원본 미니맵 크기를 기준으로 target rect 크기 계산
                    img_data = base64.b64decode(wp_data['image_base64'])
                    pixmap = QPixmap(); pixmap.loadFromData(img_data)
                    w, h = int(rect_norm[2] * pixmap.width()), int(rect_norm[3] * pixmap.height())
                    
                    rect_item = self.scene.addRect(0, 0, w, h, QPen(QColor(0, 255, 0)), QBrush(QColor(0, 255, 0, 80)))
                    rect_item.setPos(pos['target_pos'])
                    rect_item.setData(0, "waypoint")
                    rect_item.setData(1, item_id) # 웨이포인트 이름 저장
                    text_item = self.scene.addText(item_id)
                    text_item.setDefaultTextColor(Qt.GlobalColor.white)
                    text_item.setPos(pos['target_pos'])
                    text_item.setData(0, "waypoint")
                    text_item.setData(1, item_id)

        # 4. 연결선 그리기
        for wp in self.all_waypoints:
            if wp['name'] in self.global_positions:
                wp_pos = self.global_positions[wp['name']]['target_pos']
                for link in wp.get('key_feature_ids', []):
                    if link['id'] in self.global_positions:
                        feature_pos = self.global_positions[link['id']]
                        # 중심점으로 연결
                        feature_data = self.key_features[link['id']]
                        img_data = base64.b64decode(feature_data['image_base64'])
                        pixmap = QPixmap(); pixmap.loadFromData(img_data)
                        feature_center = feature_pos + QPointF(pixmap.width()/2, pixmap.height()/2)
                        
                        wp_data = next((w for w in self.all_waypoints if w['name'] == wp['name']), None)
                        rect_norm = wp_data['rect_normalized']
                        img_data = base64.b64decode(wp_data['image_base64'])
                        wp_pixmap = QPixmap(); wp_pixmap.loadFromData(img_data)
                        w, h = int(rect_norm[2] * wp_pixmap.width()), int(rect_norm[3] * wp_pixmap.height())
                        wp_center = wp_pos + QPointF(w/2, h/2)

                        pen_color = self.feature_color_map.get(link['id'], Qt.GlobalColor.yellow)
                        line_item = self.scene.addLine(wp_center.x(), wp_center.y(), feature_center.x(), feature_center.y(), QPen(pen_color, 1, Qt.PenStyle.DashLine))
                        line_item.setZValue(-5)
                        line_item.setData(0, "link")
                        line_item.setData(1, wp['name']) # 이 선이 속한 웨이포인트 이름 저장

        # --- v7.3.0: 저장된 지형선 복원 ---
        for line_data in self.geometry_data.get("terrain_lines", []):
            points = line_data.get("points", [])
            if len(points) >= 2:
                for i in range(len(points) - 1):
                    p1 = QPointF(points[i][0], points[i][1])
                    p2 = QPointF(points[i+1][0], points[i+1][1])
                    self._add_terrain_line_segment(p1, p2, line_data['id'])
                # 꼭짓점 추가
                for p in points:
                    self._add_vertex_indicator(QPointF(p[0], p[1]), line_data['id'])
        
        # --- v7.5.0: 저장된 오브젝트 복원 ---
        for obj_data in self.geometry_data.get("transition_objects", []):
            points = obj_data.get("points", [])
            if len(points) == 2:
                p1 = QPointF(points[0][0], points[0][1])
                p2 = QPointF(points[1][0], points[1][1])
                self._add_object_line(p1, p2, obj_data['id'])

    def _update_visibility(self):
        """UI 컨트롤 상태에 따라 QGraphicsScene의 아이템 가시성을 업데이트합니다."""
        show_bg = self.chk_show_background.isChecked()
        # --- v7.8.3 수정: 누락된 변수 선언 복원 ---
        show_features = self.chk_show_features.isChecked()
        show_waypoints = self.chk_show_waypoints.isChecked()
        show_links = self.chk_show_links.isChecked()
        show_terrain = self.chk_show_terrain.isChecked()
        show_objects = self.chk_show_objects.isChecked()
        
        selected_route = self.route_profile_selector.currentText()
        waypoints_in_route = {wp['name'] for wp in self.route_profiles.get(selected_route, {}).get('waypoints', [])}

        for item in self.scene.items():
            item_type = item.data(0)
            if item_type == "background":
                item.setVisible(show_bg)
            elif item_type == "feature":
                item.setVisible(show_features)
            elif item_type == "waypoint":
                wp_name = item.data(1)
                item.setVisible(show_waypoints and wp_name in waypoints_in_route)
            elif item_type == "link":
                wp_name = item.data(1)
                item.setVisible(show_links and wp_name in waypoints_in_route)
            elif item_type in ["terrain_line", "vertex"]:
                item.setVisible(show_terrain)
            elif item_type == "transition_object":
                item.setVisible(show_objects)

    def on_scene_mouse_press(self, scene_pos, button):
        if self.current_mode == "terrain":
            if button == Qt.MouseButton.LeftButton:
                final_pos = None
                # --- v7.7.2 버그 수정: is_height_locked -> is_y_locked ---
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
                    # --- v7.7.2 버그 수정: is_height_locked -> is_y_locked ---
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
                    # 오브젝트 그리기 시작
                    start_info = None
                    if self.is_x_locked and self.locked_position:
                        # X축 고정 모드: 캐릭터 X좌표 기준
                        start_info = self._get_closest_point_on_terrain_vertical(
                            self.locked_position.x(), self.locked_position.y()
                        )
                    else:
                        # 일반 모드: 마우스 클릭 위치 기준
                        start_info = self._get_closest_point_on_terrain(scene_pos)
                    
                    if start_info:
                        start_pos, parent_line_id = start_info
                        self.is_drawing_object = True
                        self.object_start_pos = start_pos
                        self.current_object_parent_id = parent_line_id
                else:
                    # 오브젝트 그리기 완료
                    self._finish_drawing_object(scene_pos)
            
            elif button == Qt.MouseButton.RightButton:
                if self.is_drawing_object:
                    self._finish_drawing_object(cancel=True)
                else:
                    # --- v7.5.5 수정: _delete_object_at 대신 직접 로직 구현 ---
                    items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                    for item in items_at_pos:
                        if item.data(0) == "transition_object":
                            self._delete_object_by_id(item.data(1))
                            break

        elif self.current_mode == "select":
            if button == Qt.MouseButton.RightButton:
                # --- v7.5.5 수정: _delete_object_at 대신 직접 로직 구현 ---
                deleted = False
                items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
                for item in items_at_pos:
                    if item.data(0) == "transition_object":
                        self._delete_object_by_id(item.data(1))
                        deleted = True
                        break # 하나만 삭제
                if not deleted:
                    # 오브젝트가 삭제되지 않았을 때만 지형선 삭제 시도
                    self._delete_terrain_at(scene_pos)

    def on_scene_mouse_move(self, scene_pos):
        if self.current_mode == "terrain":
            # --- v7.7.2 버그 수정: is_height_locked -> is_y_locked ---
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

                # --- v7.7.2 버그 수정: is_height_locked -> is_y_locked ---
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
                
                # 수직선으로 미리보기
                end_pos = QPointF(self.object_start_pos.x(), scene_pos.y())
                self.preview_object_item = self.scene.addLine(
                    self.object_start_pos.x(), self.object_start_pos.y(), end_pos.x(), end_pos.y(),
                    QPen(QColor(255, 165, 0, 150), 2, Qt.PenStyle.DashLine)
                )

    def _get_closest_point_on_terrain_vertical(self, target_x, target_y):
        """주어진 X좌표의 수직선상에서 Y좌표가 가장 가까운 지형선 위의 점과 ID를 찾습니다."""
        min_y_dist = float('inf')
        closest_point_info = None

        terrain_lines = [item for item in self.scene.items() if isinstance(item, QGraphicsLineItem) and item.data(0) == "terrain_line"]

        for line_item in terrain_lines:
            p1 = line_item.line().p1()
            p2 = line_item.line().p2()

            # 선분이 target_x를 포함하는지 확인
            if (p1.x() <= target_x <= p2.x()) or (p2.x() <= target_x <= p1.x()):
                # 선분의 방정식 y = mx + c 에서 m과 c를 구함
                dx = p2.x() - p1.x()
                if abs(dx) < 1e-6: # 수직선인 경우
                    y_on_line = p1.y() # 수직선 위의 모든 점은 y값이 다름, 이 경우는 거의 없음
                else:
                    m = (p2.y() - p1.y()) / dx
                    c = p1.y() - m * p1.x()
                    y_on_line = m * target_x + c
                
                y_dist = abs(y_on_line - target_y)
                if y_dist < min_y_dist:
                    min_y_dist = y_dist
                    closest_point_info = (QPointF(target_x, y_on_line), line_item.data(1))

        # 일정 Y거리 (예: 50px) 이내에 있을 때만 스냅
        if min_y_dist < 50:
            return closest_point_info
        return None    
    
    def _finish_drawing_line(self):
        """현재 그리던 지형선 그리기를 완료하고 데이터를 저장합니다."""
        if len(self.current_line_points) >= 2:
            # 완성된 선분 데이터 저장
            points_data = [[p.x(), p.y()] for p in self.current_line_points]
            self.geometry_data["terrain_lines"].append({
                "id": self.current_line_id,
                "points": points_data
            })
        elif len(self.current_line_points) == 1:
            # 미완성 선분(점 1개)의 경우, 생성했던 꼭짓점 아이템들을 씬에서 제거
            items_to_remove = []
            for item in self.scene.items():
                if item.data(1) == self.current_line_id:
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.scene.removeItem(item)

        # 그리기 상태 초기화
        self.is_drawing_line = False
        self.current_line_points = []
        if self.preview_line_item and self.preview_line_item in self.scene.items():
            self.scene.removeItem(self.preview_line_item)
        self.preview_line_item = None

    def _add_terrain_line_segment(self, p1, p2, line_id):
        """씬에 지형선 세그먼트를 추가합니다."""
        line_item = self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), QPen(Qt.GlobalColor.magenta, 2))
        line_item.setData(0, "terrain_line")
        line_item.setData(1, line_id) # 라인 ID 저장
        return line_item

    def _add_vertex_indicator(self, pos, line_id):
        """지형선의 꼭짓점을 씬에 추가합니다."""
        dot = self.scene.addEllipse(0, 0, 6, 6, QPen(Qt.GlobalColor.magenta), QBrush(Qt.GlobalColor.white))
        dot.setPos(pos - QPointF(3, 3))
        dot.setData(0, "vertex")
        dot.setData(1, line_id) # 라인 ID 저장
        return dot

    def _get_snap_point(self, scene_pos):
        """주어진 위치에서 스냅할 꼭짓점을 찾습니다."""
        items = self.view.items(self.view.mapFromScene(scene_pos))
        for item in items:
            if isinstance(item, QGraphicsEllipseItem) and item.data(0) == "vertex":
                # 꼭짓점 원의 중심점을 반환
                return item.pos() + QPointF(3, 3) # 원의 반지름만큼 더해 중심 계산
        return None
    
    def _update_snap_indicator(self, snap_point):
        """스냅 가능한 위치에 표시기를 업데이트합니다."""
        if not hasattr(self, 'snap_indicator'):
            self.snap_indicator = None

        if snap_point and not self.snap_indicator:
            self.snap_indicator = self.scene.addEllipse(0, 0, 8, 8, QPen(QColor(0, 255, 0, 200), 2))
            self.snap_indicator.setZValue(100)
        
        if self.snap_indicator:
            if snap_point:
                self.snap_indicator.setPos(snap_point - QPointF(4, 4))
                self.snap_indicator.setVisible(True)
            else:
                self.snap_indicator.setVisible(False)
                     
    def _delete_terrain_at(self, scene_pos):
        """주어진 위치에 있는 지형선 전체와 종속된 오브젝트를 삭제합니다."""
        items_at_pos = self.view.items(self.view.mapFromScene(scene_pos))
        line_id_to_delete = None
        for item in items_at_pos:
            if item.data(0) == "terrain_line":
                line_id_to_delete = item.data(1)
                break
        
        if line_id_to_delete:
            # 1. 이 지형선에 종속된 모든 오브젝트를 찾아서 삭제
            dependent_objects = [
                obj for obj in self.geometry_data.get("transition_objects", [])
                if obj.get("parent_line_id") == line_id_to_delete
            ]
            for obj in dependent_objects:
                # _delete_object_by_id는 내부적으로 화면 갱신을 호출하므로 여기서는 중복 호출 필요 없음
                self._delete_object_by_id(obj['id'], update_view=False)

            # 2. 기존 지형선 삭제 로직 수행
            items_to_remove = []
            for item in self.scene.items():
                if item.data(1) == line_id_to_delete:
                    items_to_remove.append(item)
            
            for item in items_to_remove:
                self.scene.removeItem(item)

            self.geometry_data["terrain_lines"] = [
                line for line in self.geometry_data.get("terrain_lines", [])
                if line.get("id") != line_id_to_delete
            ]

            # --- v7.5.5 수정: 화면 갱신 및 스냅 표시기 숨김 보강 ---
            self._update_snap_indicator(None)
            self.view.viewport().update()

    def _get_closest_point_on_terrain(self, scene_pos):
        """씬의 특정 위치에서 가장 가까운 지형선 위의 점과 해당 지형선의 ID를 찾습니다."""
        min_dist = float('inf')
        closest_point_info = None
        
        terrain_lines = [item for item in self.scene.items() if isinstance(item, QGraphicsLineItem) and item.data(0) == "terrain_line"]

        for line_item in terrain_lines:
            p1 = line_item.line().p1()
            p2 = line_item.line().p2()
            
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            if dx == 0 and dy == 0: continue
            
            t = ((scene_pos.x() - p1.x()) * dx + (scene_pos.y() - p1.y()) * dy) / (dx**2 + dy**2)
            t = max(0, min(1, t))
            
            point_on_line = QPointF(p1.x() + t * dx, p1.y() + t * dy)
            dist = math.hypot(scene_pos.x() - point_on_line.x(), scene_pos.y() - point_on_line.y())
            
            if dist < min_dist:
                min_dist = dist
                closest_point_info = (point_on_line, line_item.data(1)) # (점, 라인 ID)
        
        if min_dist < 20:
            return closest_point_info
        return None

    def _finish_drawing_object(self, end_pos=None, cancel=False):
        """현재 그리던 오브젝트 그리기를 완료/취소합니다."""
        if not cancel and end_pos:
            final_end_pos = QPointF(self.object_start_pos.x(), end_pos.y())
            obj_id = f"obj-{uuid.uuid4()}"
            self._add_object_line(self.object_start_pos, final_end_pos, obj_id)
            
            # --- v7.5.2 수정: 데이터 저장 시 parent_line_id 추가 ---
            self.geometry_data["transition_objects"].append({
                "id": obj_id,
                "parent_line_id": self.current_object_parent_id,
                "points": [[self.object_start_pos.x(), self.object_start_pos.y()], [final_end_pos.x(), final_end_pos.y()]]
            })

        if self.preview_object_item and self.preview_object_item in self.scene.items():
            self.scene.removeItem(self.preview_object_item)
        
        self.is_drawing_object = False
        self.object_start_pos = None
        self.preview_object_item = None
        self.current_object_parent_id = None # 상태 변수 초기화
        
    def _add_object_line(self, p1, p2, obj_id):
        """씬에 수직 이동 오브젝트 라인을 추가합니다."""
        line = self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), QPen(QColor(255, 165, 0), 3))
        line.setData(0, "transition_object")
        line.setData(1, obj_id)
        return line

    def _delete_object_by_id(self, obj_id_to_delete, update_view=True):
        """주어진 ID를 가진 수직 이동 오브젝트를 삭제합니다."""
        if obj_id_to_delete:
            items_to_remove = [item for item in self.scene.items() if item.data(1) == obj_id_to_delete]
            for item in items_to_remove:
                self.scene.removeItem(item)
            
            self.geometry_data["transition_objects"] = [
                obj for obj in self.geometry_data.get("transition_objects", [])
                if obj.get("id") != obj_id_to_delete
            ]

            # --- v7.5.5 수정: 화면 갱신 및 스냅 표시기 숨김 보강 ---
            if update_view:
                self._update_snap_indicator(None)
                self.view.viewport().update()

    def get_updated_geometry_data(self):
        """편집된 지오메트리 데이터의 복사본을 반환합니다."""
        return self.geometry_data
    
    # --- v8.1.0: 새로운 메서드 추가 ---
    def render_scene_to_pixmap(self):
        """현재 씬의 모든 보이는 아이템을 QPixmap으로 렌더링합니다."""
        # 씬의 모든 아이템을 포함하는 정확한 경계 사각형 계산
        rect = self.scene.itemsBoundingRect()
        if not rect.isValid():
            return None

        # QPixmap을 생성하고 투명 배경으로 채움
        pixmap = QPixmap(rect.size().toSize())
        pixmap.fill(Qt.GlobalColor.transparent)

        # QPainter를 사용하여 씬을 QPixmap에 그립니다.
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 씬의 원점이 (0,0)이 아닐 수 있으므로, 씬의 좌상단을 기준으로 렌더링
        source_rect = rect
        target_rect = QRectF(0, 0, rect.width(), rect.height())
        self.scene.render(painter, target=target_rect, source=source_rect)
        
        painter.end()
        return pixmap

    def accept(self):
        # 그리던 라인이 있으면 완료 처리
        if self.is_drawing_line:
            self._finish_drawing_line()
        if self.is_drawing_object:
            self._finish_drawing_object(cancel=True)

        # --- v8.1.0: accept가 호출되기 전에 씬을 이미지로 렌더링 ---
        global_map_pixmap = self.render_scene_to_pixmap()
        if global_map_pixmap:
            # 부모(MapTab)를 통해 파일 저장 경로를 얻어와 저장
            if self.parent_map_tab and self.parent_map_tab.active_profile_name:
                profile_path = os.path.join(MAPS_DIR, self.parent_map_tab.active_profile_name)
                save_path = os.path.join(profile_path, 'global_map.png')
                if global_map_pixmap.save(save_path, "PNG"):
                    print(f"전체 맵 이미지를 저장했습니다: {save_path}")
                else:
                    print(f"오류: 전체 맵 이미지 저장 실패: {save_path}")
            else:
                print("오류: 프로필 정보가 없어 전체 맵 이미지를 저장할 수 없습니다.")
        else:
            print("씬에 아이템이 없어 전체 맵 이미지를 저장하지 않았습니다.")

        super().accept()

class MinimapViewWidget(QWidget):
    """
    v8.1.4: 실시간 미니맵 뷰를 위한 커스텀 위젯.
    가장 단순한 렌더링 파이프라인을 사용하여 좌표계 불일치 문제를 해결합니다.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.global_map_pixmap = QPixmap()
        self.map_offset = QPointF(0, 0)
        self.pan_offset = QPointF(0, 0)
        self.zoom_level = 1.0
        
        self.panning = False
        self.pan_last_mouse_pos = QPoint()

        self.my_players_local = []
        self.other_players_local = []
        self.detected_features_local = []
        
        self.setMinimumSize(300, 300)
        self.setStyleSheet("background-color: black;")
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_global_map(self, pixmap):
        self.global_map_pixmap = pixmap
        self.reset_view()
        self.update()

    def reset_view(self):
        """뷰의 줌과 패닝을 초기 상태로 되돌립니다."""
        self.zoom_level = 1.0
        self.pan_offset = QPointF(0, 0)
        self.map_offset = QPointF(0, 0)
        # 모든 오버레이 요소 초기화
        self.my_players_local = []
        self.other_players_local = []
        self.detected_features_local = []
        self.update()

    def update_data(self, map_offset, my_players, other_players, features):
        self.map_offset = map_offset
        self.my_players_local = my_players
        self.other_players_local = other_players
        self.detected_features_local = features
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.global_map_pixmap.isNull():
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "전체 맵 이미지가 없습니다.\n(편집기에서 저장 필요)")
            return

        painter.save()

        # 1. 줌/패닝 변환 적용
        # 뷰의 중심이 아닌 (0,0)을 기준으로 scale하고, 패닝을 적용
        painter.scale(self.zoom_level, self.zoom_level)
        painter.translate(self.pan_offset)

        # 2. 배경(전역 맵) 그리기
        # map_offset만큼 이동하여 전역 맵을 그림
        painter.drawPixmap(self.map_offset, self.global_map_pixmap)

        # 3. 오버레이(탐지 요소) 그리기
        # 배경과 달리, 오버레이는 map_offset 없이 로컬 좌표 그대로 그림
        
        # 기준 지형 강조
        painter.setBrush(QBrush(QColor(0, 255, 255, 60)))
        painter.setPen(QPen(QColor(0, 255, 255), 2))
        for feature in self.detected_features_local:
            painter.drawRect(feature['rect'])

        # 내 캐릭터 그리기
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
        for rect in self.my_players_local:
            painter.drawRect(rect)

        # 다른 유저 그리기
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        for rect in self.other_players_local:
            painter.drawRect(rect)
            
        painter.restore()
        painter.end()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.zoom_level *= factor
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.panning = True
            self.pan_last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.panning:
            # 줌 레벨을 고려하여 패닝 오프셋을 조정
            delta = QPointF(event.pos() - self.pan_last_mouse_pos) / self.zoom_level
            self.pan_offset += delta
            self.pan_last_mouse_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)

class AnchorDetectionThread(QThread):
    # --- v8.1.0: 시그널 변경 ---
    detection_results = pyqtSignal(list, list, list) # detected_features, my_player_rects, other_player_rects
    status_updated = pyqtSignal(str, str)

    # --- v8.1.0: __init__ 메서드 수정 ---
    def __init__(self, minimap_region, diff_threshold, all_key_features):
        super().__init__()
        self.is_running = True
        self.minimap_region = minimap_region
        self.diff_threshold = float(diff_threshold)
        self.prev_frame_gray = None
        self.all_key_features = all_key_features
        # 템플릿을 미리 로드하여 성능 향상
        self.feature_templates = self._prepare_features()

    def _prepare_features(self):
        templates = {}
        for feature_id, data in self.all_key_features.items():
            try:
                img_data = base64.b64decode(data['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
                if template is not None:
                    templates[feature_id] = {
                        'template': template,
                        'threshold': data.get('threshold', 0.85)
                    }
            except Exception as e:
                print(f"오류: 핵심 지형 '{feature_id}' 로드 실패: {e}")
        return templates

    def run(self):
        with mss.mss() as sct:
            while self.is_running:
                sct_img = sct.grab(self.minimap_region)
                curr_frame_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
                curr_frame_gray = cv2.cvtColor(curr_frame_bgr, cv2.COLOR_BGR2GRAY)

                # 플레이어 아이콘 탐지
                _, _, my_player_rects = self.find_player_icon(curr_frame_bgr)
                other_player_rects = self.find_other_player_icons(curr_frame_bgr)

                if self.prev_frame_gray is not None:
                    # 미니맵 스크롤 감지 로직
                    all_rects_for_mask = my_player_rects + other_player_rects
                    comparison_mask = np.zeros(curr_frame_gray.shape, dtype=np.uint8)
                    for rect in all_rects_for_mask:
                        # QRectF 객체의 메서드를 사용하고, cv2 함수를 위해 int로 변환
                        pt1 = (int(rect.x()), int(rect.y()))
                        pt2 = (int(rect.x() + rect.width()), int(rect.y() + rect.height()))
                        cv2.rectangle(comparison_mask, pt1, pt2, 255, -1)
                    
                    prev_frame_masked = self.prev_frame_gray.copy()
                    curr_frame_masked = curr_frame_gray.copy()
                    prev_frame_masked[comparison_mask != 0] = 0
                    curr_frame_masked[comparison_mask != 0] = 0
                    diff = cv2.absdiff(prev_frame_masked, curr_frame_masked)
                    diff_sum = float(np.sum(diff))

                    if diff_sum < self.diff_threshold:
                        self.status_updated.emit(f"앵커 상태 (변화량: {diff_sum:.0f})", "green")
                    else:
                        self.status_updated.emit(f"미니맵 스크롤 중 (변화량: {diff_sum:.0f})", "red")
                
                # 핵심 지형 탐지
                detected_features = self.find_key_features(curr_frame_gray)

                # 탐지 결과 전송
                self.detection_results.emit(detected_features, my_player_rects, other_player_rects)

                self.prev_frame_gray = curr_frame_gray
                self.msleep(100)

    def find_key_features(self, current_frame_gray):
        """현재 프레임에서 모든 핵심 지형을 찾습니다."""
        found = []
        for feature_id, data in self.feature_templates.items():
            template = data['template']
            h, w = template.shape
            res = cv2.matchTemplate(current_frame_gray, template, cv2.TM_CCOEFF_NORMED)
            
            loc = np.where(res >= data['threshold'])
            for pt in zip(*loc[::-1]):
                is_duplicate = False
                for f in found:
                    # QRectF를 사용한 거리 계산
                    if (QPointF(f['rect'].x(), f['rect'].y()) - QPointF(pt[0], pt[1])).manhattanLength() < 10:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    # QRectF로 저장하여 정밀도 유지
                    found.append({'id': feature_id, 'rect': QRectF(float(pt[0]), float(pt[1]), float(w), float(h))})
        return found
    
    def find_player_icon(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV); mask = cv2.inRange(hsv, PLAYER_ICON_LOWER, PLAYER_ICON_UPPER); contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) > 5: 
                x, y, w, h = cv2.boundingRect(c)
                player_rect = QRectF(float(x), float(y), float(w), float(h))
                return (player_rect.x() + player_rect.width() / 2, player_rect.y() + player_rect.height() / 2), player_rect, [player_rect]
        return None, None, []

    def find_other_player_icons(self, frame_bgr):
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV); mask1 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER1, OTHER_PLAYER_ICON_UPPER1); mask2 = cv2.inRange(hsv, OTHER_PLAYER_ICON_LOWER2, OTHER_PLAYER_ICON_UPPER2)
        mask = cv2.bitwise_or(mask1, mask2); contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rects = []
        for c in contours:
            if cv2.contourArea(c) > 5:
                x, y, w, h = cv2.boundingRect(c)
                rects.append(QRectF(float(x), float(y), float(w), float(h)))
        return rects

    def stop(self): self.is_running = False

class MapTab(QWidget):
    def __init__(self):
        super().__init__()
        self.active_profile_name = None
        self.minimap_region = None
        self.key_features = {}
        self.geometry_data = {}
        self.active_route_profile_name = None
        self.route_profiles = {}
        self.detection_thread = None
        self.editor_dialog = None 
        self.global_positions = {}
        # --- v8.1.0: 전체 맵 이미지 변수 추가 ---
        self.global_map_pixmap = QPixmap()
        
        self.initUI()
        self.perform_initial_setup()

    def initUI(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        
        # --- 좌측 UI (프로필, 웨이포인트 등) ---
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
        minimap_layout = QVBoxLayout(); self.set_area_btn = QPushButton("미니맵 범위 지정"); self.set_area_btn.clicked.connect(self.set_minimap_area)
        minimap_layout.addWidget(self.set_area_btn); self.minimap_groupbox.setLayout(minimap_layout); left_layout.addWidget(self.minimap_groupbox)
        
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

        self.editor_groupbox = QGroupBox("6. 전체 맵 편집")
        editor_layout = QVBoxLayout()
        self.open_editor_btn = QPushButton("미니맵 지형 편집기 열기")
        self.open_editor_btn.clicked.connect(self.open_full_minimap_editor)
        editor_layout.addWidget(self.open_editor_btn)
        self.editor_groupbox.setLayout(editor_layout)
        left_layout.addWidget(self.editor_groupbox)
        
        detect_groupbox = QGroupBox("7. 탐지 제어")
        detect_layout = QVBoxLayout(); threshold_layout = QHBoxLayout(); threshold_layout.addWidget(QLabel("변화량 임계값:"))
        self.diff_threshold_spinbox = QSpinBox(); self.diff_threshold_spinbox.setRange(1000, 1000000); self.diff_threshold_spinbox.setSingleStep(1000); self.diff_threshold_spinbox.setValue(50000)
        threshold_layout.addWidget(self.diff_threshold_spinbox); self.detect_anchor_btn = QPushButton("탐지 시작"); self.detect_anchor_btn.setCheckable(True)
        self.detect_anchor_btn.clicked.connect(self.toggle_anchor_detection); detect_layout.addLayout(threshold_layout); detect_layout.addWidget(self.detect_anchor_btn)
        detect_groupbox.setLayout(detect_layout); left_layout.addWidget(detect_groupbox); left_layout.addStretch(1)
        
        # --- 중앙 로그 ---
        logs_layout = QVBoxLayout()
        logs_layout.addWidget(QLabel("일반 로그")); self.general_log_viewer = QTextEdit(); self.general_log_viewer.setReadOnly(True); logs_layout.addWidget(self.general_log_viewer)
        logs_layout.addWidget(QLabel("앵커 상태 로그")); self.anchor_log_viewer = QTextEdit(); self.anchor_log_viewer.setReadOnly(True); self.anchor_log_viewer.setFixedHeight(100); logs_layout.addWidget(self.anchor_log_viewer)
        
        # --- 우측 뷰 ---
        right_layout.addWidget(QLabel("실시간 미니맵 (휠: 줌, 드래그: 이동)"))
        self.minimap_view = MinimapViewWidget()
        right_layout.addWidget(self.minimap_view, 1)

        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(logs_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.update_general_log("MapTab이 초기화되었습니다. 맵 프로필을 선택해주세요.", "black")

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
        # --- v8.1.0: 전체 맵 이미지 경로 추가 ---
        global_map_path = os.path.join(profile_path, 'global_map.png')

        try:
            self.minimap_region, self.key_features = None, {}
            self.route_profiles, self.active_route_profile_name = {}, None
            self.geometry_data = {}
            self.diff_threshold_spinbox.setValue(50000)

            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f: config = json.load(f)

            saved_options = config.get('render_options', {})
            self.render_options = {
                'background': True, 'features': True, 'waypoints': True,
                'links': True, 'terrain': True, 'objects': True
            }
            self.render_options.update(saved_options)

            features = {}
            if os.path.exists(features_file):
                with open(features_file, 'r', encoding='utf-8') as f: features = json.load(f)
            
            if os.path.exists(geometry_file):
                with open(geometry_file, 'r', encoding='utf-8') as f: self.geometry_data = json.load(f)
            else:
                self.geometry_data = {"terrain_lines": [], "transition_objects": []}

            # --- v8.1.0: 전체 맵 이미지 로드 ---
            if os.path.exists(global_map_path):
                self.global_map_pixmap = QPixmap(global_map_path)
            else:
                self.global_map_pixmap = QPixmap()
            
            if hasattr(self, 'minimap_view'):
                self.minimap_view.set_global_map(self.global_map_pixmap)

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
            self.key_features = features

            if config_updated or features_updated:
                self.save_profile_data()

            self.global_positions = self._calculate_global_positions()
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
        geometry_file = os.path.join(profile_path, 'map_geometry.json')

        try:
            config_data = {
                'minimap_region': self.minimap_region,
                'diff_threshold': self.diff_threshold_spinbox.value(),
                'active_route_profile': self.active_route_profile_name,
                'route_profiles': self.route_profiles,
                'render_options': self.render_options
            }
            with open(config_file, 'w', encoding='utf-8') as f: json.dump(config_data, f, indent=4, ensure_ascii=False)
            with open(features_file, 'w', encoding='utf-8') as f: json.dump(self.key_features, f, indent=4, ensure_ascii=False)
            with open(geometry_file, 'w', encoding='utf-8') as f: json.dump(self.geometry_data, f, indent=4, ensure_ascii=False)

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
        self.wp_groupbox.setTitle(f"4. 웨이포인트 관리 (경로: {self.active_route_profile_name})")
        self.kf_groupbox.setTitle(f"5. 핵심 지형 관리 (맵: {self.active_profile_name})")
        self.editor_groupbox.setTitle(f"6. 전체 맵 편집 (맵: {self.active_profile_name})")

        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.add_wp_btn, self.edit_wp_btn, self.del_wp_btn,
            self.manage_kf_btn, self.open_editor_btn, self.detect_anchor_btn
        ]
        for widget in all_widgets:
            widget.setEnabled(True)

        self.populate_route_profile_selector()
        self.save_global_settings()

    def update_ui_for_no_profile(self):
        self.active_profile_name = None
        self.active_route_profile_name = None
        self.route_profiles.clear()
        self.key_features.clear()
        self.geometry_data.clear()
        self.waypoint_list_widget.clear()
        self.route_profile_selector.clear()
        self.minimap_region = None
        self.global_map_pixmap = QPixmap()
        if hasattr(self, 'minimap_view'):
            self.minimap_view.set_global_map(self.global_map_pixmap)

        self.minimap_groupbox.setTitle("3. 미니맵 설정 (프로필 없음)")
        self.wp_groupbox.setTitle("4. 웨이포인트 관리 (프로필 없음)")
        self.kf_groupbox.setTitle("5. 핵심 지형 관리 (프로필 없음)")
        self.editor_groupbox.setTitle("6. 전체 맵 편집 (프로필 없음)")

        all_widgets = [
            self.route_profile_selector, self.add_route_btn, self.rename_route_btn, self.delete_route_btn,
            self.set_area_btn, self.add_wp_btn, self.edit_wp_btn, self.del_wp_btn,
            self.manage_kf_btn, self.open_editor_btn, self.detect_anchor_btn
        ]
        for widget in all_widgets:
            widget.setEnabled(False)

        self.save_global_settings()

    def populate_route_profile_selector(self):
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

            self.route_profiles[route_name] = {"waypoints": []}
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
        """모든 경로 프로필의 웨이포인트에 'route_name'을 추가하여 단일 리스트로 반환합니다."""
        all_waypoints = []
        for route_name, route_data in self.route_profiles.items():
            for wp in route_data['waypoints']:
                wp_copy = wp.copy()
                wp_copy['route_name'] = route_name
                all_waypoints.append(wp_copy)
        return all_waypoints

    def open_key_feature_manager(self):
        all_waypoints = []
        for route_name, route_data in self.route_profiles.items():
            for wp in route_data['waypoints']:
                wp_copy = wp.copy()
                wp_copy['route_name'] = route_name
                all_waypoints.append(wp_copy)

        dialog = KeyFeatureManagerDialog(self.key_features, all_waypoints, self)
        dialog.exec()

    def open_full_minimap_editor(self):
        """'미니맵 지형 편집기 열기' 버튼에 연결된 슬롯."""
        if not self.active_profile_name:
            QMessageBox.warning(self, "오류", "먼저 맵 프로필을 선택해주세요.")
            return

        self.editor_dialog = FullMinimapEditorDialog(
            profile_name=self.active_profile_name,
            active_route_profile=self.active_route_profile_name,
            key_features=self.key_features,
            route_profiles=self.route_profiles,
            geometry_data=self.geometry_data,
            render_options=self.render_options,
            global_positions=self.global_positions,
            parent=self
        )
        
        try:
            result = self.editor_dialog.exec()
            
            if result:
                self.geometry_data = self.editor_dialog.get_updated_geometry_data()
                # --- v8.1.0: 편집기 저장 후 전체 맵 이미지 즉시 리로드 ---
                profile_path = os.path.join(MAPS_DIR, self.active_profile_name)
                global_map_path = os.path.join(profile_path, 'global_map.png')
                if os.path.exists(global_map_path):
                    self.global_map_pixmap.load(global_map_path)
                    self.minimap_view.set_global_map(self.global_map_pixmap)
                
                self.save_profile_data() # geometry_data 저장
                self.update_general_log("지형 편집기 변경사항이 저장되고, 전체 맵이 갱신되었습니다.", "green")
            else:
                self.update_general_log("지형 편집이 취소되었습니다.", "black")
            
            self.render_options = self.editor_dialog.get_current_view_options()

        finally:
            self.editor_dialog = None

    def get_waypoint_name_from_item(self, item):
        if not item:
            return None
        text = item.text()
        return text.split('. ', 1)[1] if '. ' in text and text.split('. ', 1)[0].isdigit() else text

    def process_new_waypoint_data(self, wp_data, final_features_on_canvas, newly_drawn_features, deleted_feature_ids, context_frame_bgr):
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

        return {'name': wp_data['name'], 'image_base64': img_base64, 'rect_normalized': target_rect_norm, 'key_feature_ids': key_feature_links}

    def update_all_waypoints_with_features(self):
        """현재 맵 프로필의 모든 웨이포인트를 순회하며, 등록된 모든 핵심 지형과의 연결을 재구성합니다."""
        all_waypoints = [wp for route in self.route_profiles.values() for wp in route['waypoints']]
        if not all_waypoints:
            QMessageBox.information(self, "알림", "갱신할 웨이포인트가 없습니다.")
            return False

        reply = QMessageBox.question(self, "전체 갱신 확인",
                                    f"총 {len(all_waypoints)}개의 웨이포인트와 {len(self.key_features)}개의 핵심 지형의 연결을 갱신합니다.\n"
                                    "이 작업은 웨이포인트의 'key_feature_ids' 설정을 덮어씁니다. 계속하시겠습니까?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            return False

        self.update_general_log("모든 웨이포인트와 핵심 지형의 연결을 갱신합니다...", "purple")
        QApplication.processEvents()
        updated_count = 0

        for wp in all_waypoints:
            if 'image_base64' not in wp or not wp['image_base64']:
                continue
            try:
                img_data = base64.b64decode(wp['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                wp_map_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                wp_map_gray = cv2.cvtColor(wp_map_bgr, cv2.COLOR_BGR2GRAY)
                h, w, _ = wp_map_bgr.shape

                new_key_feature_links = []
                target_rect_norm = wp['rect_normalized']
                target_rect_pixel = QRect(int(target_rect_norm[0] * w), int(target_rect_norm[1] * h), int(target_rect_norm[2] * w), int(target_rect_norm[3] * h))

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
                        feature_rect_pixel = QRect(max_loc[0], max_loc[1], template.shape[1], template.shape[0])
                        offset_x = target_rect_pixel.x() - feature_rect_pixel.x()
                        offset_y = target_rect_pixel.y() - feature_rect_pixel.y()
                        new_key_feature_links.append({'id': feature_id, 'offset_to_target': [offset_x, offset_y]})

                wp['key_feature_ids'] = new_key_feature_links
                updated_count += 1
            except Exception as e:
                self.update_general_log(f"'{wp['name']}' 갱신 중 오류: {e}", "red")

        self.save_profile_data()
        self.update_general_log(f"완료: 총 {len(all_waypoints)}개 중 {updated_count}개의 웨이포인트 링크를 갱신했습니다.", "purple")
        QMessageBox.information(self, "성공", f"{updated_count}개의 웨이포인트 갱신 완료.")
        return True

    def _get_next_feature_name(self):
        max_num = max([int(name[1:]) for name in self.key_features.keys() if name.startswith("P") and name[1:].isdigit()] or [0])
        return f"P{max_num + 1}"

    def add_waypoint(self):
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

                new_wp = self.process_new_waypoint_data(wp_data, final_features, new_features, deleted_ids, frame_bgr)
                current_waypoints.append(new_wp)
                self.populate_waypoint_list()
                self.save_profile_data()
                self.update_general_log(f"'{name}' 웨이포인트가 '{self.active_route_profile_name}' 경로에 추가되었습니다.", "green")
        except Exception as e: self.update_general_log(f"웨이포인트 추가 오류: {e}", "red")

    def edit_waypoint(self):
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

                processed_data = self.process_new_waypoint_data(new_data, final_features, new_features, deleted_ids, frame_bgr)
                wp_data.update(processed_data)
                self.update_general_log(f"웨이포인트 '{old_name}'이(가) '{new_name}'(으)로 수정되었습니다.", "black")
                self.populate_waypoint_list()
                self.save_profile_data()
        except Exception as e: self.update_general_log(f"웨이포인트 편집 오류: {e}", "red")

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

    def waypoint_order_changed(self):
        if not self.active_route_profile_name: return

        current_waypoints = self.route_profiles[self.active_route_profile_name]['waypoints']
        new_waypoints_order = [self.get_waypoint_name_from_item(self.waypoint_list_widget.item(i)) for i in range(self.waypoint_list_widget.count())]
        current_waypoints.sort(key=lambda wp: new_waypoints_order.index(wp['name']))

        self.save_profile_data()
        self.update_general_log("웨이포인트 순서가 변경되었습니다.", "SaddleBrown")

        # v8.1.0: 웨이포인트 순서 변경은 더 이상 탐지 스레드에 영향을 주지 않음

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
            if not self.minimap_region:
                QMessageBox.warning(self, "오류", "먼저 '미니맵 범위 지정'을 해주세요.")
                self.detect_anchor_btn.setChecked(False); return
            if self.global_map_pixmap.isNull():
                 QMessageBox.warning(self, "오류", "전체 맵 이미지가 없습니다.\n먼저 '미니맵 지형 편집기'를 열고 저장하여 전체 맵을 생성해주세요.")
                 self.detect_anchor_btn.setChecked(False); return

            self.save_profile_data()
            self.general_log_viewer.clear()
            self.anchor_log_viewer.clear()
            
            self.detection_thread = AnchorDetectionThread(
                self.minimap_region, 
                self.diff_threshold_spinbox.value(), 
                self.key_features
            )

            self.detection_thread.detection_results.connect(self.update_minimap_view)
            self.detection_thread.status_updated.connect(self.update_anchor_log)
            
            self.detection_thread.start()
            self.detect_anchor_btn.setText("탐지 중단")
            self.update_general_log("탐지를 시작합니다.", "SaddleBrown")
        else:
                    if self.detection_thread and self.detection_thread.isRunning():
                        self.detection_thread.stop()
                        self.detection_thread.wait()
                    
                    self.update_general_log("탐지를 중단합니다.", "black")
                    self.detect_anchor_btn.setText("탐지 시작")
                    self.detection_thread = None
                    
                    # 탐지 중단 시 뷰 초기화
                    self.minimap_view.reset_view()
                    
    def update_minimap_view(self, detected_features_local, my_players_local, other_players_local):
            """
            v8.1.2: 탐지된 로컬/전역 좌표를 이용해 오프셋을 계산하고,
            오프셋과 로컬 좌표를 뷰 위젯에 전달하여 렌더링을 요청합니다.
            """
            if not detected_features_local or not self.global_positions:
                # 기준 지형이 없으면 뷰 업데이트 중단 (오프셋 계산 불가)
                return

            # 1. 로컬 좌표와 전역 좌표를 이용해 오프셋 목록 계산
            offsets = []
            for feature in detected_features_local:
                feature_id = feature['id']
                if feature_id in self.global_positions:
                    local_pos = feature['rect'].topLeft()
                    global_pos = self.global_positions[feature_id]
                    
                    # offset: 전역 좌표계의 원점을 로컬 좌표계의 어디에 두어야 하는가
                    # offset = Local_Position - Global_Position
                    offset = local_pos - global_pos
                    offsets.append(offset)

            if not offsets:
                return

            # 2. 평균 오프셋 계산 (렌더링 떨림 방지)
            avg_offset_x = sum(o.x() for o in offsets) / len(offsets)
            avg_offset_y = sum(o.y() for o in offsets) / len(offsets)
            final_offset = QPointF(avg_offset_x, avg_offset_y)

            # 3. MinimapViewWidget에 오프셋과 로컬 좌표 그대로 전달
            self.minimap_view.update_data(final_offset, my_players_local, other_players_local, detected_features_local)
            
            feature_names = ", ".join([f['id'] for f in detected_features_local])
            self.general_log_viewer.setText(f"기준 지형: {feature_names}") # append 대신 setText로 최신 상태만 표시

    def update_general_log(self, message, color): 
        self.general_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.general_log_viewer.verticalScrollBar().setValue(self.general_log_viewer.verticalScrollBar().maximum())
        
    def update_anchor_log(self, message, color): 
        self.anchor_log_viewer.append(f'<font color="{color}">{message}</font>')
        self.anchor_log_viewer.verticalScrollBar().setValue(self.anchor_log_viewer.verticalScrollBar().maximum())

    def _calculate_global_positions(self):
        """핵심 지형과 웨이포인트의 관계를 분석하여 전역 좌표를 계산합니다."""
        if not self.key_features:
            return {}

        all_waypoints = self.get_all_waypoints_with_route_name()
        
        global_positions = {}
        
        sorted_keys = sorted(self.key_features.keys())
        if not sorted_keys:
            return {}
            
        first_feature_id = sorted_keys[0]
        global_positions[first_feature_id] = QPointF(0, 0)
        
        if not all_waypoints:
            for feature_id in sorted_keys[1:]:
                global_positions[feature_id] = QPointF(0, 0)
            return global_positions

        pending_waypoints = all_waypoints[:]
        
        for _ in range(len(all_waypoints) + len(self.key_features)):
            found_new = False
            remaining_waypoints = []

            for wp in pending_waypoints:
                known_ref_feature = None
                for link in wp.get('key_feature_ids', []):
                    if link['id'] in global_positions:
                        known_ref_feature = link
                        break

                if known_ref_feature:
                    found_new = True
                    
                    try:
                        img_data = base64.b64decode(wp['image_base64'])
                        np_arr = np.frombuffer(img_data, np.uint8)
                        wp_map_gray = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)

                        feature_id = known_ref_feature['id']
                        feature_data = self.key_features[feature_id]
                        f_img_data = base64.b64decode(feature_data['image_base64'])
                        f_np_arr = np.frombuffer(f_img_data, np.uint8)
                        template = cv2.imdecode(f_np_arr, cv2.IMREAD_GRAYSCALE)
                        
                        if wp_map_gray is None or template is None: continue

                        res = cv2.matchTemplate(wp_map_gray, template, cv2.TM_CCOEFF_NORMED)
                        _, _, _, max_loc = cv2.minMaxLoc(res)
                        
                        ref_global_pos = global_positions[feature_id]
                        ref_local_pos = QPointF(float(max_loc[0]), float(max_loc[1]))
                        wp_map_global_origin = ref_global_pos - ref_local_pos
                        
                        offset_x, offset_y = known_ref_feature['offset_to_target']
                        wp_target_global_pos = ref_global_pos + QPointF(float(offset_x), float(offset_y))
                        
                        global_positions[wp['name']] = {
                            'map_origin': wp_map_global_origin,
                            'target_pos': wp_target_global_pos
                        }

                        for link in wp.get('key_feature_ids', []):
                            if link['id'] not in global_positions:
                                target_rect_norm = wp['rect_normalized']
                                w, h = float(wp_map_gray.shape[1]), float(wp_map_gray.shape[0])
                                target_local_pos = QPointF(target_rect_norm[0] * w, target_rect_norm[1] * h)
                                
                                feature_local_pos = target_local_pos - QPointF(float(link['offset_to_target'][0]), float(link['offset_to_target'][1]))
                                feature_global_pos = wp_map_global_origin + feature_local_pos
                                global_positions[link['id']] = feature_global_pos
                    except Exception as e:
                        print(f"전역 좌표 계산 중 오류 (웨이포인트: {wp.get('name')}): {e}")
                        continue
                else:
                    remaining_waypoints.append(wp)
            
            pending_waypoints = remaining_waypoints
            if not found_new:
                break

        return global_positions

    def cleanup_on_close(self):
        self.save_global_settings()
        if self.detection_thread and self.detection_thread.isRunning():
            self.detection_thread.stop()
            self.detection_thread.wait()
        print("'맵' 탭 정리 완료.")