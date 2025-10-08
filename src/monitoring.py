from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QColor
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QCheckBox,
    QDoubleSpinBox,
    QListWidget,
    QListWidgetItem,
)

try:
    from .map_widgets import RealtimeMinimapView
except ImportError:
    from map_widgets import RealtimeMinimapView  # type: ignore


class LogListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setDragEnabled(True)
        # AutoControl 로그 스타일과 유사한 다크 테마 적용
        self.setStyleSheet(
            """
            QListWidget {
                background-color: #2E2E2E;
                color: white;
                border: 1px solid #555;
            }
            QListWidget::item:selected { background: #444; }
            """
        )

    def keyPressEvent(self, event):
        if event.matches(event.StandardKey.Copy):
            selected = self.selectedItems()
            if selected:
                text = "\n".join(item.text() for item in selected)
                from PyQt6.QtWidgets import QApplication
                QApplication.clipboard().setText(text)
            return
        super().keyPressEvent(event)

    def append_line(self, text: str, color: str | None = None) -> None:
        if not text:
            return
        item = QListWidgetItem(text)
        if color:
            if QColor.isValidColor(color):
                item.setForeground(QColor(color))
        self.addItem(item)
        # 롤링(200개 유지)
        if self.count() > 200:
            self.takeItem(0)
        self.scrollToBottom()


class MonitoringTab(QWidget):
    """좌측: 맵 미니맵 미리보기, 우측: 사냥 미리보기, 하단: 로그 3분할."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._map_tab = None
        self._hunt_tab = None
        self._auto_tab = None

        self._ui_visible: bool = True

        # 프리뷰 상태
        self._map_static_bound_synced: bool = False
        self._map_preview_enabled: bool = False
        self._hunt_preview_enabled: bool = False

        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        # 상단: 좌/우 프리뷰
        top_row = QHBoxLayout()

        # 좌측: 맵 미니맵
        map_box = QGroupBox("맵 미니맵 미리보기(맵탭 스타일)")
        map_layout = QVBoxLayout(map_box)
        map_ctrl = QHBoxLayout()
        self.map_preview_checkbox = QCheckBox("표시")
        self.map_preview_checkbox.setChecked(False)
        self.map_preview_checkbox.toggled.connect(self._on_map_preview_toggled)
        self.map_interval_spin = QDoubleSpinBox()
        self.map_interval_spin.setRange(0.5, 5.0)
        self.map_interval_spin.setSingleStep(0.5)
        self.map_interval_spin.setValue(1.0)
        self.map_interval_spin.setSuffix(" s")
        self.map_interval_spin.valueChanged.connect(self._on_map_interval_changed)
        map_ctrl.addWidget(QLabel("갱신 주기"))
        map_ctrl.addWidget(self.map_interval_spin)
        map_ctrl.addStretch(1)
        map_ctrl.addWidget(self.map_preview_checkbox)
        map_layout.addLayout(map_ctrl)
        self.map_view = RealtimeMinimapView(self)
        self.map_view.setText("미리보기를 켜세요.")
        map_layout.addWidget(self.map_view, 1)

        # 우측: 사냥 미리보기
        hunt_box = QGroupBox("사냥 미리보기")
        hunt_layout = QVBoxLayout(hunt_box)
        hunt_ctrl = QHBoxLayout()
        self.hunt_preview_checkbox = QCheckBox("표시")
        self.hunt_preview_checkbox.setChecked(False)
        self.hunt_preview_checkbox.toggled.connect(self._on_hunt_preview_toggled)
        self.hunt_interval_spin = QDoubleSpinBox()
        self.hunt_interval_spin.setRange(0.5, 5.0)
        self.hunt_interval_spin.setSingleStep(0.5)
        self.hunt_interval_spin.setValue(1.0)
        self.hunt_interval_spin.setSuffix(" s")
        self.hunt_interval_spin.valueChanged.connect(self._on_hunt_interval_changed)
        hunt_ctrl.addWidget(QLabel("갱신 주기"))
        hunt_ctrl.addWidget(self.hunt_interval_spin)
        hunt_ctrl.addStretch(1)
        hunt_ctrl.addWidget(self.hunt_preview_checkbox)
        hunt_layout.addLayout(hunt_ctrl)
        self.hunt_preview_label = QLabel("탐지 대기 중 또는 미리보기 꺼짐.")
        self.hunt_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hunt_preview_label.setStyleSheet("background: black; color: white; min-height: 220px;")
        hunt_layout.addWidget(self.hunt_preview_label, 1)

        top_row.addWidget(map_box, 1)
        top_row.addWidget(hunt_box, 1)
        root.addLayout(top_row, 2)

        # 하단: 로그 3분할
        bottom_row = QHBoxLayout()
        self.map_log = LogListWidget(); self.map_log.setToolTip("맵 로그")
        self.hunt_log = LogListWidget(); self.hunt_log.setToolTip("사냥 로그")
        self.key_log = LogListWidget(); self.key_log.setToolTip("키보드 입력 로그")
        bottom_row.addWidget(self.map_log, 1)
        bottom_row.addWidget(self.hunt_log, 1)
        bottom_row.addWidget(self.key_log, 1)
        root.addLayout(bottom_row, 1)

        # 프레임 드롭/주기 관리를 위한 타이머(사냥은 런타임에서 제어되므로 미사용)
        self._map_preview_timer = QTimer(self)
        self._map_preview_timer.setSingleShot(False)
        self._map_preview_timer.timeout.connect(self._tick_map_preview)

    # --- 탭 간 연결 ---
    def attach_tabs(self, map_tab, hunt_tab, auto_control_tab) -> None:
        self._map_tab = map_tab
        self._hunt_tab = hunt_tab
        self._auto_tab = auto_control_tab

        # 로그 구독
        try:
            if hasattr(map_tab, 'general_log_emitted'):
                map_tab.general_log_emitted.connect(self._on_map_log)
        except Exception:
            pass
        try:
            if hasattr(hunt_tab, 'hunt_log_emitted'):
                hunt_tab.hunt_log_emitted.connect(self._on_hunt_log)
        except Exception:
            pass
        try:
            if hasattr(auto_control_tab, 'log_generated'):
                auto_control_tab.log_generated.connect(self._on_key_log)
        except Exception:
            pass

        # 사냥 프리뷰 프레임 구독
        try:
            if hasattr(hunt_tab, 'preview_frame_ready'):
                hunt_tab.preview_frame_ready.connect(self._on_hunt_frame)
        except Exception:
            pass

    # --- 맵 프리뷰 ---
    def _start_map_preview(self) -> None:
        if not self._map_tab:
            return
        self._sync_map_static()
        # 타이머 주기
        self._map_preview_timer.setInterval(int(float(self.map_interval_spin.value()) * 1000))
        self._map_preview_timer.start()
        self._map_preview_enabled = True
        self.map_view.setText("")

    def _stop_map_preview(self) -> None:
        self._map_preview_enabled = False
        self._map_preview_timer.stop()
        self.map_view.setText("미리보기를 켜세요.")

    @pyqtSlot()
    def _tick_map_preview(self) -> None:
        if not self._map_tab:
            return
        state = None
        try:
            state = self._map_tab.api_export_minimap_view_state()
        except Exception:
            state = None
        if not state:
            return
        self.map_view.update_view_data(
            camera_center=state.get('camera_center'),
            active_features=state.get('active_features'),
            my_players=state.get('my_players'),
            other_players=state.get('other_players'),
            target_wp_id=state.get('target_wp_id'),
            reached_wp_id=state.get('reached_wp_id'),
            final_player_pos=state.get('final_player_pos'),
            is_forward=bool(state.get('is_forward', True)),
            intermediate_pos=state.get('intermediate_pos'),
            intermediate_type=state.get('intermediate_type'),
            nav_action=state.get('nav_action'),
            intermediate_node_type=state.get('intermediate_node_type'),
        )

    def _sync_map_static(self) -> None:
        if not self._map_tab:
            return
        try:
            static = self._map_tab.api_export_static_minimap_data()
        except Exception:
            static = None
        if not static:
            return
        # 부모 탭과 동일 속성 구성
        self.full_map_bounding_rect = static.get('bounding_rect')
        try:
            # MapTab에서 생성한 전체 맵 픽스맵을 공유(깊은 복사 없이 참조)
            self.full_map_pixmap = getattr(self._map_tab, 'full_map_pixmap', None)
        except Exception:
            self.full_map_pixmap = None
        # 렌더 옵션 동기화(없으면 기본값)
        self.render_options = getattr(self._map_tab, 'render_options', {
            'terrain': True, 'objects': True, 'jump_links': True, 'forbidden_walls': True, 'features': True,
        })
        # 키피처/글로벌 좌표 동기화(RealtimeMinimapView는 parent_tab.key_features를 조회)
        self.key_features = static.get('key_features') or {}
        self.global_positions = static.get('global_positions') or {}
        # 정적 데이터 전달
        self.map_view.update_static_cache(
            geometry_data=static.get('geometry_data'),
            key_features=static.get('key_features'),
            global_positions=static.get('global_positions'),
        )

    # --- 사냥 프리뷰 ---
    def _apply_hunt_preview(self) -> None:
        if not self._hunt_tab:
            return
        enabled = bool(self.hunt_preview_checkbox.isChecked() and self._ui_visible)
        interval = float(self.hunt_interval_spin.value() or 1.0)
        try:
            self._hunt_tab.api_set_preview_enabled(enabled, interval)
        except Exception:
            pass

    @pyqtSlot(object)
    def _on_hunt_frame(self, image: QImage) -> None:
        if image is None or image.isNull():
            return
        self.hunt_preview_label.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.hunt_preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # --- 컨트롤 핸들러 ---
    def _on_map_preview_toggled(self, checked: bool) -> None:
        if checked and self._ui_visible:
            self._start_map_preview()
        else:
            self._stop_map_preview()

    def _on_map_interval_changed(self, value: float) -> None:
        if self._map_preview_enabled:
            self._start_map_preview()

    def _on_hunt_preview_toggled(self, checked: bool) -> None:
        self._apply_hunt_preview()

    def _on_hunt_interval_changed(self, value: float) -> None:
        self._apply_hunt_preview()

    # --- 로그 핸들러 ---
    @pyqtSlot(str, str)
    def _on_map_log(self, line: str, color: str) -> None:
        self.map_log.append_line(line, color)

    @pyqtSlot(str, str)
    def _on_hunt_log(self, line: str, color: str) -> None:
        self.hunt_log.append_line(line, color)

    @pyqtSlot(str, str)
    def _on_key_log(self, text: str, color: str) -> None:
        self.key_log.append_line(text, color)

    # --- 표시 도우미 ---
    @staticmethod
    def _update_label_with_bgr(label: QLabel, bgr: np.ndarray) -> None:
        try:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(img).scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(pix)
        except Exception:
            pass

    # 외부 API: 탭 가시성 전파
    def set_tab_visible(self, visible: bool) -> None:
        self._ui_visible = bool(visible)
        # 가려지면 모든 미리보기 OFF
        if not self._ui_visible:
            if self.map_preview_checkbox.isChecked():
                self._stop_map_preview()
            if self.hunt_preview_checkbox.isChecked():
                self._apply_hunt_preview()
        else:
            if self.map_preview_checkbox.isChecked():
                self._start_map_preview()
            if self.hunt_preview_checkbox.isChecked():
                self._apply_hunt_preview()

    def cleanup_on_close(self) -> None:
        self._stop_map_preview()
        # 사냥 프리뷰 해제
        try:
            if self._hunt_tab:
                self._hunt_tab.api_set_preview_enabled(False, 0.0)
        except Exception:
            pass
