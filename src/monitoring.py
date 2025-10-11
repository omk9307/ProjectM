from __future__ import annotations

from typing import Optional
import time
import re

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QThread, QRectF, pyqtSlot, pyqtSignal, QSettings, QSize
from datetime import datetime
from PyQt6.QtGui import QImage, QPixmap, QColor, QKeySequence
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QGroupBox,
    QFrame,
    QCheckBox,
    QDoubleSpinBox,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QPushButton,
    QAbstractItemView,
)

try:
    from .map_widgets import RealtimeMinimapView
except ImportError:
    from map_widgets import RealtimeMinimapView  # type: ignore
try:
    from control_authority_manager import ControlAuthorityManager
except Exception:
    ControlAuthorityManager = None  # type: ignore
try:
    from capture_manager import get_capture_manager
except Exception:
    get_capture_manager = None  # type: ignore
try:
    from window_anchors import is_maple_window_foreground
except Exception:
    # 실행 환경에 따라 모듈이 없을 수 있으므로 안전 폴백
    def is_maple_window_foreground() -> bool:  # type: ignore
        return True


class LogListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        # 행 교차색 비활성화
        self.setAlternatingRowColors(False)
        self.setDragEnabled(True)
        # 가로 스크롤 제거 + 자동 줄바꿈 유지(여백은 현 상태 유지)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        try:
            # QListView 속성: 단어 단위 줄바꿈 활성화
            self.setWordWrap(True)
            self.setUniformItemSizes(False)
        except Exception:
            pass
        # AutoControl 로그 스타일과 유사한 다크 테마 적용
        self.setStyleSheet(
            """
            QListWidget {
                background-color: #2E2E2E;
                color: white;  /* 기본 텍스트는 밝게 */
                border: 1px solid #555;
            }
            QListWidget::item:selected { background: #444; }
            """
        )

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            selected = self.selectedItems()
            if selected:
                text = "\n".join(item.text() for item in selected)
                from PyQt6.QtWidgets import QApplication
                QApplication.clipboard().setText(text)
            return
        super().keyPressEvent(event)

    def append_line(self, text: str, color: str | None = None, *, preserve_color: bool = False) -> None:
        if not text:
            return
        item = QListWidgetItem(text)
        # 밝은 전경색 보장: 어두운 색이 들어오면 자동으로 밝게 보정
        if color and QColor.isValidColor(color):
            q = QColor(color)
            if q.isValid():
                if not preserve_color:
                    # Y' = 0.299R + 0.587G + 0.114B (0~255)
                    y = 0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()
                    if y < 150:  # 어두우면 밝게 보정
                        q = q.lighter(170)
                item.setForeground(q)
        else:
            # 색 정보 없으면 기본 밝은 색상
            item.setForeground(QColor("#EEEEEE"))
        # 현재 바닥 여부 체크(바닥이면 자동 스크롤 유지)
        try:
            sb = self.verticalScrollBar()
            at_bottom = (sb.value() >= sb.maximum() - 2)
        except Exception:
            at_bottom = True
        self.addItem(item)
        # 줄바꿈 후 적절한 높이로 보정
        try:
            h = self._calc_wrapped_height(text)
            item.setSizeHint(QSize(self.viewport().width(), h))
        except Exception:
            pass
        # 롤링(400개 유지)
        if self.count() > 400:
            self.takeItem(0)
        if at_bottom:
            self.scrollToBottom()

    # 리스트 뷰포트 너비 기준 줄바꿈 높이 계산
    def _calc_wrapped_height(self, text: str) -> int:
        try:
            # 여백은 기존 상태를 보전하기 위해 소폭(8px)만 내부 패딩으로 가정
            avail = max(1, self.viewport().width() - 8)
            fm = self.fontMetrics()
            flags = int(Qt.TextFlag.TextWordWrap)
            rect = fm.boundingRect(0, 0, avail, 0, flags, text)
            # 위아래 약간의 패딩 추가
            return max(rect.height() + 6, fm.height() + 6)
        except Exception:
            return self.fontMetrics().height() + 6

    # 리사이즈 시 모든 항목 줄바꿈 높이 재계산
    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            for i in range(self.count()):
                it = self.item(i)
                if it is None:
                    continue
                h = self._calc_wrapped_height(it.text())
                it.setSizeHint(QSize(self.viewport().width(), h))
        except Exception:
            pass


class InfoListWidget(QListWidget):
    """중앙 정보칸: 고정 행(한 줄당 한 항목), 드래그/복사 가능, 갱신시 선택 유지."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setDragEnabled(True)
        self.setStyleSheet(
            """
            QListWidget {
                background-color: #2E2E2E;
                color: #EEEEEE;
                border: 1px solid #555;
            }
            QListWidget::item:selected { background: #444; }
            """
        )
        # 초기 8행 준비
        for _ in range(8):
            self.addItem(QListWidgetItem(""))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            selected = self.selectedItems()
            if selected:
                text = "\n".join(item.text() for item in selected)
                from PyQt6.QtWidgets import QApplication
                QApplication.clipboard().setText(text)
            return
        super().keyPressEvent(event)

    def set_lines(self, lines: list[str]) -> None:
        # 선택 상태 보존
        selected_rows = {i for i in range(self.count()) if self.item(i).isSelected()}
        # 아이템 개수 보정(증감 최소화)
        if self.count() < len(lines):
            for _ in range(len(lines) - self.count()):
                self.addItem(QListWidgetItem(""))
        elif self.count() > len(lines):
            # 뒤에서부터 제거
            for _ in range(self.count() - len(lines)):
                self.takeItem(self.count() - 1)
        # 인플레이스 갱신
        for i, text in enumerate(lines):
            it = self.item(i)
            if it is None:
                it = QListWidgetItem("")
                self.insertItem(i, it)
            if it.text() != text:
                it.setText(text)
        # 선택 복원
        for i in range(self.count()):
            self.item(i).setSelected(i in selected_rows)


class MonitoringTab(QWidget):
    """좌측: 맵 미니맵 미리보기, 우측: 사냥 미리보기, 하단: 로그 3분할."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._map_tab = None
        self._hunt_tab = None
        self._auto_tab = None

        self._ui_visible: bool = True

        # RealtimeMinimapView가 parent_tab를 통해 조회하는 속성 기본값 설정
        self.full_map_pixmap = None
        self.full_map_bounding_rect = QRectF()
        self.render_options = {
            'terrain': True,
            'objects': True,
            'jump_links': True,
            'forbidden_walls': True,
            'features': True,
        }
        self.key_features = {}
        self.global_positions = {}

        # 프리뷰 상태
        self._map_static_bound_synced: bool = False
        self._map_preview_enabled: bool = False
        self._hunt_preview_enabled: bool = False
        # 정보칸 표시용 캐시
        self._current_authority_owner: str = "map"
        self._latest_hp: float | None = None
        self._latest_mp: float | None = None
        self._latest_exp_amount: str | None = None
        self._latest_exp_percent: float | None = None
        # 실행/세션 및 EXP 기준치 관리
        self._map_running: bool = False
        self._hunt_running: bool = False
        self._run_start_ts: float | None = None
        self._exp_standalone_enabled: bool = False
        self._exp_standalone_start_ts: float | None = None
        self._exp_standalone_accum_sec: float = 0.0
        self._exp_standalone_last_top_ts: float | None = None
        self._exp_start_amount: int | None = None
        self._exp_start_percent: float | None = None
        self._exp_last_percent: float | None = None
        self._status_monitor = None
        self._status_data_manager = None
        # 캐릭터 상태/행동/층 스냅샷
        self._last_player_state: str | None = None
        self._last_nav_action: str | None = None
        self._last_floor: float | None = None

        self._init_ui()
        # AutoControl 실시간 로그와 동일한 Δ 및 구분선 처리를 위해 마지막 키로그 시각 저장
        self._last_key_log_ts: float = 0.0
        # 모니터링 미니맵: 캐릭터 중심 해제(고정 카메라)
        self._fixed_camera_center: tuple[float, float] | None = None
        self._fixed_camera_initialized: bool = False

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        # 상하 분할 스플리터(사용자 드래그로 세로 비율 조절)
        self._vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self._vertical_splitter.setChildrenCollapsible(False)

        # 상단: 좌/우 프리뷰
        top_row = QHBoxLayout()

        # 좌측: 맵 미니맵
        map_box = QGroupBox("맵 미니맵 미리보기(맵탭 스타일)")
        map_layout = QVBoxLayout(map_box)
        # 컨트롤 높이를 참조할 수 있도록 위젯 래퍼 사용
        map_ctrl_widget = QWidget()
        map_ctrl = QHBoxLayout(map_ctrl_widget)
        # 시작/정지 버튼 + 연동 체크박스
        self.map_start_btn = QPushButton("시작")
        self.map_start_btn.clicked.connect(self._on_click_map_start)
        self.map_stop_btn = QPushButton("정지")
        self.map_stop_btn.clicked.connect(self._on_click_map_stop)
        self.map_link_checkbox = QCheckBox("연동")
        self.map_link_checkbox.toggled.connect(self._on_link_toggled_from_monitor)
        self.map_preview_checkbox = QCheckBox("표시")
        self.map_preview_checkbox.setChecked(False)
        self.map_preview_checkbox.toggled.connect(self._on_map_preview_toggled)
        self.map_interval_spin = QDoubleSpinBox()
        self.map_interval_spin.setRange(0.5, 5.0)
        self.map_interval_spin.setSingleStep(0.5)
        self.map_interval_spin.setValue(1.0)
        self.map_interval_spin.setSuffix(" s")
        self.map_interval_spin.valueChanged.connect(self._on_map_interval_changed)
        map_ctrl.addWidget(self.map_start_btn)
        map_ctrl.addWidget(self.map_stop_btn)
        map_ctrl.addSpacing(6)
        map_ctrl.addWidget(self.map_link_checkbox)
        map_ctrl.addSpacing(12)
        map_ctrl.addWidget(QLabel("갱신 주기"))
        map_ctrl.addWidget(self.map_interval_spin)
        map_ctrl.addStretch(1)
        map_ctrl.addWidget(self.map_preview_checkbox)
        map_layout.addWidget(map_ctrl_widget)
        self.map_view = RealtimeMinimapView(self)
        self.map_view.setText("미리보기를 켜세요.")
        map_layout.addWidget(self.map_view, 1)

        # 중앙: 정보칸(로그 스타일, 고정 행)
        info_box = QGroupBox("정보")
        info_layout = QVBoxLayout(info_box)
        # 좌우 컨트롤 바 높이에 맞추기 위한 더미 컨트롤 바
        info_ctrl_widget = QWidget()
        info_ctrl_layout = QHBoxLayout(info_ctrl_widget)
        info_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        # 실행시간 라벨(정보 그룹 제목 아래, 좌측 정렬, 검정색)
        self.runtime_label = QLabel("")
        self.runtime_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.runtime_label.setStyleSheet("color: #000000; padding: 2px 6px;")
        info_ctrl_layout.addWidget(self.runtime_label)
        # [NEW] MP/EXP 단독실행 토글(학습 탭과 연동)
        info_ctrl_layout.addSpacing(12)
        self.chk_mp_standalone = QCheckBox("MP")
        self.chk_exp_standalone = QCheckBox("EXP")
        for _cb in (self.chk_mp_standalone, self.chk_exp_standalone):
            _cb.setChecked(False)
            _cb.setToolTip("단독 실행")
        self.chk_mp_standalone.toggled.connect(self._on_toggle_mp_standalone)
        self.chk_exp_standalone.toggled.connect(self._on_toggle_exp_standalone)
        info_ctrl_layout.addWidget(self.chk_mp_standalone)
        info_ctrl_layout.addWidget(self.chk_exp_standalone)
        info_ctrl_layout.addStretch(1)
        info_layout.addWidget(info_ctrl_widget)
        # 정보 행 컨테이너(한 줄씩 아래로, 좌: 정보명 칸, 우: 수치 칸)
        self.info_value_labels: dict[str, QLabel] = {}

        rows_container = QWidget()
        rows_container.setStyleSheet(
            """
            QWidget { background-color: #2E2E2E; }
            QLabel { color: #EEEEEE; }
            """
        )
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(4, 4, 4, 4)
        rows_layout.setSpacing(4)

        def _mk_row(label_text: str, key: str) -> QWidget:
            row = QFrame()
            row.setFrameShape(QFrame.Shape.NoFrame)
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 2, 4, 2)
            h.setSpacing(6)
            name = QLabel(label_text)
            name.setFixedWidth(92)
            name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name.setStyleSheet("color: #CCCCCC; background: rgba(255,255,255,0.03); padding: 2px 6px; border: 1px solid #444;")
            vline = QFrame(); vline.setFrameShape(QFrame.Shape.VLine); vline.setFrameShadow(QFrame.Shadow.Sunken)
            value = QLabel("--")
            value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            value.setStyleSheet("color: #FFFFFF; padding: 2px 6px;")
            h.addWidget(name)
            h.addWidget(vline)
            h.addWidget(value, 1)
            self.info_value_labels[key] = value
            return row

        def _mk_sep() -> QFrame:
            s = QFrame(); s.setFrameShape(QFrame.Shape.HLine); s.setFrameShadow(QFrame.Shadow.Sunken)
            return s

        # 그룹: FPS
        rows_layout.addWidget(_mk_row("FPS", "fps"))
        rows_layout.addWidget(_mk_sep())
        # 그룹: 권한/범위
        for t, k in (("이동권한", "owner"), ("스킬범위", "skill_cnt"), ("X축 범위", "x_cnt"), ("텔레포트 확률", "teleport")):
            rows_layout.addWidget(_mk_row(t, k))
        rows_layout.addWidget(_mk_sep())
        # 그룹: 자원/EXP
        for t, k in (("HP", "hp"), ("MP", "mp"), ("EXP", "exp_amount"), ("EXP(%)", "exp_percent"), ("레벨업", "exp_eta")):
            rows_layout.addWidget(_mk_row(t, k))
        rows_layout.addWidget(_mk_sep())
        # 그룹: 캐릭터
        for t, k in (("현재층", "floor"), ("캐릭터 상태", "state"), ("필요행동", "action")):
            rows_layout.addWidget(_mk_row(t, k))

        info_layout.addWidget(rows_container, 1)

        # 우측: 사냥 미리보기
        hunt_box = QGroupBox("사냥 미리보기")
        hunt_layout = QVBoxLayout(hunt_box)
        hunt_ctrl_widget = QWidget()
        hunt_ctrl = QHBoxLayout(hunt_ctrl_widget)
        # 시작/정지 버튼 + 연동 체크박스(동일 상태 동기화)
        self.hunt_start_btn = QPushButton("시작")
        self.hunt_start_btn.clicked.connect(self._on_click_hunt_start)
        self.hunt_stop_btn = QPushButton("정지")
        self.hunt_stop_btn.clicked.connect(self._on_click_hunt_stop)
        self.hunt_link_checkbox = QCheckBox("연동")
        self.hunt_link_checkbox.toggled.connect(self._on_link_toggled_from_monitor)
        self.hunt_preview_checkbox = QCheckBox("표시")
        self.hunt_preview_checkbox.setChecked(False)
        self.hunt_preview_checkbox.toggled.connect(self._on_hunt_preview_toggled)
        self.hunt_interval_spin = QDoubleSpinBox()
        self.hunt_interval_spin.setRange(0.5, 5.0)
        self.hunt_interval_spin.setSingleStep(0.5)
        self.hunt_interval_spin.setValue(1.0)
        self.hunt_interval_spin.setSuffix(" s")
        self.hunt_interval_spin.valueChanged.connect(self._on_hunt_interval_changed)
        hunt_ctrl.addWidget(self.hunt_start_btn)
        hunt_ctrl.addWidget(self.hunt_stop_btn)
        hunt_ctrl.addSpacing(6)
        hunt_ctrl.addWidget(self.hunt_link_checkbox)
        hunt_ctrl.addSpacing(12)
        hunt_ctrl.addWidget(QLabel("갱신 주기"))
        hunt_ctrl.addWidget(self.hunt_interval_spin)

        # [NEW] 모니터링 전용 오버레이 토글(기본 OFF)
        self.chk_hunt_bundle = QCheckBox("사냥범위")  # hunt_area + primary_area 세트
        self.chk_nickname_range = QCheckBox("닉네임범위")
        self.chk_nameplate_track = QCheckBox("몬스터 이름표 시각화")
        self.chk_cleanup_band = QCheckBox("클린업" )
        self.chk_cluster_window = QCheckBox("군집 중심 범위")
        for _cb in (
            self.chk_hunt_bundle,
            self.chk_nickname_range,
            self.chk_nameplate_track,
            self.chk_cleanup_band,
            self.chk_cluster_window,
        ):
            _cb.setChecked(False)
            _cb.toggled.connect(self._on_monitor_overlay_toggled)
            hunt_ctrl.addWidget(_cb)
        hunt_ctrl.addStretch(1)
        hunt_ctrl.addWidget(self.hunt_preview_checkbox)
        hunt_layout.addWidget(hunt_ctrl_widget)

        # 중앙 정보 컨트롤바 높이를 좌우 컨트롤바와 동일하게 보정
        try:
            ctrl_h = max(map_ctrl_widget.sizeHint().height(), hunt_ctrl_widget.sizeHint().height())
            info_ctrl_widget.setFixedHeight(ctrl_h)
        except Exception:
            pass
        self.hunt_preview_label = QLabel("탐지 대기 중 또는 미리보기 꺼짐.")
        self.hunt_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hunt_preview_label.setStyleSheet("background: black; color: white; min-height: 220px;")
        hunt_layout.addWidget(self.hunt_preview_label, 1)

        # 좌우 가로 리사이즈: 상단 전용 스플리터
        self._top_hsplitter = QSplitter(Qt.Orientation.Horizontal)
        self._top_hsplitter.setChildrenCollapsible(False)
        self._top_hsplitter.addWidget(map_box)
        self._top_hsplitter.addWidget(info_box)
        self._top_hsplitter.addWidget(hunt_box)
        self._top_hsplitter.setStretchFactor(0, 1)
        self._top_hsplitter.setStretchFactor(1, 0)
        self._top_hsplitter.setStretchFactor(2, 1)

        top_container = QWidget()
        _top_layout = QVBoxLayout(top_container)
        _top_layout.setContentsMargins(0, 0, 0, 0)
        _top_layout.addWidget(self._top_hsplitter)

        # 하단: 로그 3분할(제목 포함)
        bottom_row = QHBoxLayout()
        self.map_log = LogListWidget(); self.map_log.setToolTip("맵 로그")
        self.hunt_log = LogListWidget(); self.hunt_log.setToolTip("사냥 로그")
        self.key_log = LogListWidget(); self.key_log.setToolTip("키보드 입력 로그")

        # 로그 더블클릭 → 다른 로그를 가까운 시간대로 스크롤 동기화
        try:
            self.map_log.itemDoubleClicked.connect(lambda item: self._on_log_item_double_clicked(self.map_log, item))
            self.hunt_log.itemDoubleClicked.connect(lambda item: self._on_log_item_double_clicked(self.hunt_log, item))
            self.key_log.itemDoubleClicked.connect(lambda item: self._on_log_item_double_clicked(self.key_log, item))
        except Exception:
            pass

        map_group = QGroupBox("맵 로그")
        map_group_layout = QVBoxLayout(map_group)
        map_group_layout.addWidget(self.map_log)

        hunt_group = QGroupBox("사냥 로그")
        hunt_group_layout = QVBoxLayout(hunt_group)
        hunt_group_layout.addWidget(self.hunt_log)

        key_group = QGroupBox("키보드 입력 로그")
        key_group_layout = QVBoxLayout(key_group)
        key_group_layout.addWidget(self.key_log)

        # 좌우 가로 리사이즈: 하단 로그 전용 스플리터
        self._bottom_hsplitter = QSplitter(Qt.Orientation.Horizontal)
        self._bottom_hsplitter.setChildrenCollapsible(False)
        self._bottom_hsplitter.addWidget(map_group)
        self._bottom_hsplitter.addWidget(hunt_group)
        self._bottom_hsplitter.addWidget(key_group)
        # 기본 동일 비율
        self._bottom_hsplitter.setStretchFactor(0, 1)
        self._bottom_hsplitter.setStretchFactor(1, 1)
        self._bottom_hsplitter.setStretchFactor(2, 1)

        bottom_container = QWidget()
        _bottom_layout = QVBoxLayout(bottom_container)
        _bottom_layout.setContentsMargins(0, 0, 0, 0)
        _bottom_layout.addWidget(self._bottom_hsplitter)

        # 스플리터에 상/하 컨테이너 부착
        self._vertical_splitter.addWidget(top_container)
        self._vertical_splitter.addWidget(bottom_container)
        root.addWidget(self._vertical_splitter, 1)

        # 스플리터 위치 복원(없으면 기본 비율 적용)
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            sizes = settings.value("monitoring/splitter_sizes")
            if isinstance(sizes, list) and len(sizes) == 2:
                # QSettings가 list[str]로 반환하는 경우가 있어 int 변환 시도
                try:
                    sizes = [int(x) for x in sizes]
                except Exception:
                    sizes = [600, 300]
                self._vertical_splitter.setSizes(sizes)  # type: ignore[arg-type]
            else:
                # 기본: 상단 2, 하단 1 비율
                self._vertical_splitter.setSizes([600, 300])
        except Exception:
            self._vertical_splitter.setSizes([600, 300])

        # 상단 좌우 스플리터 복원 (2개/3개 구성 모두 호환)
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            sizes = settings.value("monitoring/top_hsplitter_sizes")
            if isinstance(sizes, list):
                try:
                    sizes = [int(x) for x in sizes]
                except Exception:
                    sizes = []
                if len(sizes) == 3:
                    self._top_hsplitter.setSizes(sizes)  # type: ignore[arg-type]
                elif len(sizes) == 2:
                    left, right = sizes
                    self._top_hsplitter.setSizes([left, 280, right])
                else:
                    self._top_hsplitter.setSizes([400, 280, 400])
            else:
                self._top_hsplitter.setSizes([400, 280, 400])
        except Exception:
            self._top_hsplitter.setSizes([400, 280, 400])

        # 하단 좌우 스플리터 복원
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            sizes = settings.value("monitoring/bottom_hsplitter_sizes")
            if isinstance(sizes, list) and len(sizes) == 3:
                try:
                    sizes = [int(x) for x in sizes]
                except Exception:
                    sizes = [300, 300, 300]
                self._bottom_hsplitter.setSizes(sizes)  # type: ignore[arg-type]
            else:
                self._bottom_hsplitter.setSizes([300, 300, 300])
        except Exception:
            self._bottom_hsplitter.setSizes([300, 300, 300])

        # 체크박스 상태 복원(마지막 표시 상태 + 연동)
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            def _to_bool(v, default=False):
                if v is None:
                    return default
                if isinstance(v, bool):
                    return v
                s = str(v).strip().lower()
                return s in ("1","true","yes","y","on")
            map_checked = _to_bool(settings.value("monitoring/map_preview_checked"), False)
            hunt_checked = _to_bool(settings.value("monitoring/hunt_preview_checked"), False)
            link_checked = _to_bool(settings.value("monitoring/map_hunt_link"), False)
            self.map_preview_checkbox.setChecked(map_checked)
            self.hunt_preview_checkbox.setChecked(hunt_checked)
            self._apply_link_checkbox_state(link_checked, propagate=False)
            # [NEW] 오버레이 체크박스 상태 복원(기본 OFF)
            self.chk_hunt_bundle.setChecked(_to_bool(settings.value("monitoring/ovl_hunt_bundle"), False))
            self.chk_nickname_range.setChecked(_to_bool(settings.value("monitoring/ovl_nickname_range"), False))
            self.chk_nameplate_track.setChecked(_to_bool(settings.value("monitoring/ovl_nameplate_track"), False))
            self.chk_cleanup_band.setChecked(_to_bool(settings.value("monitoring/ovl_cleanup_band"), False))
            self.chk_cluster_window.setChecked(_to_bool(settings.value("monitoring/ovl_cluster_window"), False))
        except Exception:
            pass

        # 체크 상태 변경시 즉시 저장
        try:
            self.map_preview_checkbox.toggled.connect(self._persist_checkbox_states)
            self.hunt_preview_checkbox.toggled.connect(self._persist_checkbox_states)
            self.map_link_checkbox.toggled.connect(self._persist_checkbox_states)
            self.hunt_link_checkbox.toggled.connect(self._persist_checkbox_states)
            # [NEW] 오버레이 상태 저장
            self.chk_hunt_bundle.toggled.connect(self._persist_checkbox_states)
            self.chk_nickname_range.toggled.connect(self._persist_checkbox_states)
            self.chk_nameplate_track.toggled.connect(self._persist_checkbox_states)
            self.chk_cleanup_band.toggled.connect(self._persist_checkbox_states)
            self.chk_cluster_window.toggled.connect(self._persist_checkbox_states)
        except Exception:
            pass

        # 프레임 드롭/주기 관리를 위한 타이머(사냥은 런타임에서 제어되므로 미사용)
        self._map_preview_timer = QTimer(self)
        self._map_preview_timer.setSingleShot(False)
        self._map_preview_timer.timeout.connect(self._tick_map_preview)
        # 정보칸 주기 갱신 타이머(0.5초)
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(False)
        self._info_timer.setInterval(500)
        self._info_timer.timeout.connect(self._tick_info_update)
        self._info_timer.start()

    # --- 탭 간 연결 ---
    def attach_tabs(self, map_tab, hunt_tab, auto_control_tab) -> None:
        self._map_tab = map_tab
        self._hunt_tab = hunt_tab
        self._auto_tab = auto_control_tab
        # 상태 모니터 연결(가능 시)
        try:
            monitor = None
            if map_tab and hasattr(map_tab, 'status_monitor'):
                monitor = getattr(map_tab, 'status_monitor', None)
            if monitor is None and hunt_tab and hasattr(hunt_tab, 'status_monitor'):
                monitor = getattr(hunt_tab, 'status_monitor', None)
            if monitor and hasattr(monitor, 'status_captured'):
                monitor.status_captured.connect(self._on_status_snapshot)
        except Exception:
            pass

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

        # 상태 동기화: 시작/정지 버튼 활성화와 연동 체크박스 미러링
        try:
            if hasattr(map_tab, 'detection_status_changed'):
                map_tab.detection_status_changed.connect(self._on_map_detection_status_changed)
        except Exception:
            pass
        try:
            if hasattr(hunt_tab, 'detection_status_changed'):
                hunt_tab.detection_status_changed.connect(self._on_hunt_detection_status_changed)
        except Exception:
            pass
        # 연동 체크박스 미러링(양방향)
        try:
            if hasattr(map_tab, 'map_link_checkbox') and map_tab.map_link_checkbox:
                map_tab.map_link_checkbox.toggled.connect(self._on_external_link_toggled)
        except Exception:
            pass
        try:
            if hasattr(hunt_tab, 'map_link_checkbox') and hunt_tab.map_link_checkbox:
                hunt_tab.map_link_checkbox.toggled.connect(self._on_external_link_toggled)
        except Exception:
            pass
        # 초기 동기화(외부 상태를 모니터링 탭으로 가져옴)
        self._sync_monitor_buttons_enabled()
        self._sync_link_checkbox_from_external()
        # [NEW] 오버레이 선반영: 기본 OFF를 사냥 탭에 즉시 적용
        try:
            self._on_monitor_overlay_toggled(False)
        except Exception:
            pass
        # 권한 변경 구독 및 초기 상태
        try:
            if ControlAuthorityManager is not None:
                mgr = ControlAuthorityManager.instance()
                try:
                    state = mgr.current_state()
                    self._current_authority_owner = getattr(state, 'owner', 'map')
                except Exception:
                    pass
                mgr.authority_changed.connect(self._on_authority_changed)
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
        # 캐릭터 중심 해제: 초기 1회만 고정 카메라를 세팅하고 이후엔 카메라를 갱신하지 않음
        cam_arg = None
        if not self._fixed_camera_initialized:
            cam_arg = self._fixed_camera_center
        self.map_view.update_view_data(
            camera_center=cam_arg,
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
        if cam_arg is not None:
            self._fixed_camera_initialized = True

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
        # 고정 카메라 중심: 전체 맵 바운딩의 중앙으로 설정(1회 세팅 용)
        try:
            rect = self.full_map_bounding_rect
            if rect and not rect.isNull():
                cx = float(rect.center().x()); cy = float(rect.center().y())
                self._fixed_camera_center = (cx, cy)
                self._fixed_camera_initialized = False
        except Exception:
            self._fixed_camera_center = None
            self._fixed_camera_initialized = False

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

    def _persist_checkbox_states(self) -> None:
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            settings.setValue("monitoring/map_preview_checked", bool(self.map_preview_checkbox.isChecked()))
            settings.setValue("monitoring/hunt_preview_checked", bool(self.hunt_preview_checkbox.isChecked()))
            # 연동 체크박스(두 개는 항상 동일 상태)
            link_state = bool(self.map_link_checkbox.isChecked()) or bool(self.hunt_link_checkbox.isChecked())
            settings.setValue("monitoring/map_hunt_link", link_state)
            # [NEW] 오버레이 체크 상태
            settings.setValue("monitoring/ovl_hunt_bundle", bool(self.chk_hunt_bundle.isChecked()))
            settings.setValue("monitoring/ovl_nickname_range", bool(self.chk_nickname_range.isChecked()))
            settings.setValue("monitoring/ovl_nameplate_track", bool(self.chk_nameplate_track.isChecked()))
            settings.setValue("monitoring/ovl_cleanup_band", bool(self.chk_cleanup_band.isChecked()))
            settings.setValue("monitoring/ovl_cluster_window", bool(self.chk_cluster_window.isChecked()))
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
        # 선행 타임스탬프([HH:MM:SS] 또는 [HH:MM:SS.mmm])가 있으면 제거 후, 모니터링에서만 밀리초 TS 추가
        try:
            cleaned = re.sub(r"^\s*\[(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)\]\s*", "", line)
        except Exception:
            cleaned = line
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.map_log.append_line(f"{ts} {cleaned}", self._brighten_color(color))

    @pyqtSlot(str, str)
    def _on_hunt_log(self, line: str, color: str) -> None:
        self.hunt_log.append_line(line, color)

    @pyqtSlot(str, str)
    def _on_key_log(self, text: str, color: str) -> None:
        now = time.time()
        # 5초 이상 공백 시 구분선 추가(가운데 정렬, 회색)
        try:
            if self._last_key_log_ts and (now - self._last_key_log_ts) > 5:
                sep = QListWidgetItem("──────────")
                sep.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                sep.setForeground(QColor("#888"))
                self.key_log.addItem(sep)
        except Exception:
            pass

        # AutoControl 탭과 동일한 타임스탬프 포맷: [HH:MM:SS:ms]
        ts = datetime.now().strftime("%H:%M:%S:%f")[:-3]
        # 이전 로그와의 간격 Δ 표시
        delta_text = ""
        try:
            if self._last_key_log_ts:
                delta_ms = int((now - self._last_key_log_ts) * 1000)
                delta_text = f" (Δ {delta_ms}ms)"
        except Exception:
            delta_text = ""

        line = f"[{ts}] {text}{delta_text}"
        # 색상은 원색 유지
        self.key_log.append_line(line, color, preserve_color=True)
        self._last_key_log_ts = now

    # --- 상태 모니터 스냅샷 수신 ---
    @pyqtSlot(dict)
    def _on_status_snapshot(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        try:
            hp = payload.get('hp', {})
            if isinstance(hp, dict) and isinstance(hp.get('percentage'), (int, float)):
                self._latest_hp = float(hp['percentage'])
        except Exception:
            pass
        try:
            mp = payload.get('mp', {})
            if isinstance(mp, dict) and isinstance(mp.get('percentage'), (int, float)):
                self._latest_mp = float(mp['percentage'])
        except Exception:
            pass
        try:
            exp = payload.get('exp', {})
            if isinstance(exp, dict):
                amt = exp.get('amount')
                per = exp.get('percent')
                if isinstance(amt, str):
                    self._latest_exp_amount = amt
                if isinstance(per, (int, float)):
                    cur_per = float(per)
                    # 레벨업 감지: 퍼센트 급락 시 기준치 재설정
                    try:
                        if (
                            isinstance(self._exp_last_percent, float)
                            and cur_per < self._exp_last_percent - 10.0
                        ):
                            self._exp_start_percent = cur_per
                            try:
                                self._exp_start_amount = int(self._latest_exp_amount) if isinstance(self._latest_exp_amount, str) and self._latest_exp_amount.isdigit() else None
                            except Exception:
                                self._exp_start_amount = None
                    except Exception:
                        pass
                    self._latest_exp_percent = cur_per
                    self._exp_last_percent = cur_per
                    # 세션이 활성이고 기준치가 없으면 현재값으로 세팅
                    if self._is_any_session_active() and self._exp_start_percent is None:
                        self._exp_start_percent = cur_per
                        try:
                            self._exp_start_amount = int(self._latest_exp_amount) if isinstance(self._latest_exp_amount, str) and self._latest_exp_amount.isdigit() else None
                        except Exception:
                            self._exp_start_amount = None
        except Exception:
            pass

    # --- 로그 동기화(더블클릭) ---
    def _on_log_item_double_clicked(self, source_widget: QListWidget, item: QListWidgetItem) -> None:
        try:
            ts = self._parse_ts_to_seconds(item.text())
        except Exception:
            ts = None
        if ts is None:
            return

        targets = [w for w in (self.map_log, self.hunt_log, self.key_log) if w is not source_widget]
        for w in targets:
            idx = self._find_nearest_index_by_ts(w, ts)
            if idx is None:
                continue
            try:
                w.clearSelection()
                w.setCurrentRow(idx)
                w.scrollToItem(w.item(idx))
            except Exception:
                pass

    def _parse_ts_to_seconds(self, text: str) -> Optional[float]:
        """문자열 앞부분의 타임스탬프를 초 단위(float)로 변환.
        지원 포맷:
          - "[HH:MM:SS.mmm] ..."
          - "[HH:MM:SS:mmm] ..." (ms 앞 구분자 콜론)
          - "HH:MM:SS.mmm ..."
        """
        try:
            m = re.match(r"^\s*\[?(\d{2}):(\d{2}):(\d{2})(?:[\.:](\d{1,3}))?\]?\s*", text)
            if not m:
                return None
            h = int(m.group(1)); mnt = int(m.group(2)); s = int(m.group(3))
            ms = int(m.group(4)) if m.group(4) is not None else 0
            return h * 3600.0 + mnt * 60.0 + s + (ms / 1000.0)
        except Exception:
            return None

    def _find_nearest_index_by_ts(self, widget: QListWidget, target_ts: float) -> Optional[int]:
        best_idx: Optional[int] = None
        best_diff: float = float('inf')
        try:
            for i in range(widget.count()):
                it = widget.item(i)
                ts = self._parse_ts_to_seconds(it.text())
                if ts is None:
                    continue
                diff = abs(ts - target_ts)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
        except Exception:
            return best_idx
        return best_idx

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

    # --- 권한/정보칸 갱신 ---
    @pyqtSlot()
    def _tick_info_update(self) -> None:
        # FPS: 권한 소유자 기준 선호, 없으면 폴백
        fps_text = self._collect_fps_text()
        # 맵탭에서 최신 캐릭터 상태 스냅샷 직접 폴링(권한 신호가 드물어도 갱신)
        try:
            if self._map_tab and hasattr(self._map_tab, 'collect_authority_snapshot'):
                snap = self._map_tab.collect_authority_snapshot()
                if snap is not None:
                    st = getattr(snap, 'player_state', None)
                    na = getattr(snap, 'navigation_action', None)
                    fl = getattr(snap, 'floor', None)
                    if isinstance(st, str):
                        self._last_player_state = st
                    if isinstance(na, str):
                        self._last_nav_action = na
                    try:
                        self._last_floor = float(fl) if fl is not None else self._last_floor
                    except Exception:
                        pass
        except Exception:
            pass
        # 이동권한
        owner_text = "맵" if (self._current_authority_owner or "map") == "map" else "사냥"
        # 스킬범위/ X축 범위(사냥탭 캐시 사용)
        try:
            skill_cnt = getattr(self._hunt_tab, 'latest_primary_monster_count', None)
        except Exception:
            skill_cnt = None
        try:
            x_cnt = getattr(self._hunt_tab, 'latest_monster_count', None)
        except Exception:
            x_cnt = None
        # 텔레포트 확률: 권한 소유자 우선
        teleport_percent = self._collect_teleport_percent()
        # HP/MP/EXP
        hp_val = f"{self._latest_hp:.1f}%" if isinstance(self._latest_hp, float) else "--%"
        mp_val = f"{self._latest_mp:.1f}%" if isinstance(self._latest_mp, float) else "--%"
        # standalone exp 시간 누적(최상위에서만 경과 추가)
        self._tick_exp_standalone_time()
        exp_amount_line, exp_percent_line, exp_eta_line = self._compose_exp_lines()
        floor_line, state_line, action_line = self._compose_char_status_lines()

        # FPS
        self.info_value_labels.get('fps', QLabel()).setText(fps_text)
        # 권한/범위
        self.info_value_labels.get('owner', QLabel()).setText(owner_text)
        self.info_value_labels.get('skill_cnt', QLabel()).setText(str(int(skill_cnt)) if isinstance(skill_cnt, (int, float)) else "--")
        self.info_value_labels.get('x_cnt', QLabel()).setText(str(int(x_cnt)) if isinstance(x_cnt, (int, float)) else "--")
        self.info_value_labels.get('teleport', QLabel()).setText(teleport_percent)
        # 자원/EXP
        self.info_value_labels.get('hp', QLabel()).setText(hp_val)
        self.info_value_labels.get('mp', QLabel()).setText(mp_val)
        self.info_value_labels.get('exp_amount', QLabel()).setText(exp_amount_line.replace('EXP: ', ''))
        self.info_value_labels.get('exp_percent', QLabel()).setText(exp_percent_line.replace('EXP(%): ', ''))
        self.info_value_labels.get('exp_eta', QLabel()).setText(exp_eta_line.replace('레벨업 ', ''))
        # 캐릭터
        self.info_value_labels.get('floor', QLabel()).setText(floor_line.replace('현재층: ', ''))
        self.info_value_labels.get('state', QLabel()).setText(state_line.replace('캐릭터 상태: ', ''))
        self.info_value_labels.get('action', QLabel()).setText(action_line.replace('필요행동: ', ''))

        # 실행시간 라벨 갱신
        self._update_runtime_label()

    # --- 모니터링에서 MP/EXP 단독 토글 → 학습 DataManager로 반영 ---
    def _on_toggle_mp_standalone(self, checked: bool) -> None:
        dm = getattr(self, '_status_data_manager', None)
        if dm and hasattr(dm, 'update_status_monitor_config'):
            try:
                dm.update_status_monitor_config({'mp': {'standalone': bool(checked)}})
            except Exception:
                pass
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            settings.setValue("monitoring/mp_standalone_last", bool(checked))
        except Exception:
            pass

    def _on_toggle_exp_standalone(self, checked: bool) -> None:
        dm = getattr(self, '_status_data_manager', None)
        if dm and hasattr(dm, 'update_status_monitor_config'):
            try:
                dm.update_status_monitor_config({'exp': {'standalone': bool(checked)}})
            except Exception:
                pass
        # 로컬 상태/타이머도 동기화
        self._handle_status_config_update(type('Cfg', (), {'exp': type('RCfg', (), {'standalone': bool(checked)})()})())
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            settings.setValue("monitoring/exp_standalone_last", bool(checked))
        except Exception:
            pass

    def _compose_char_status_lines(self) -> tuple[str, str, str]:
        state = self._last_player_state if isinstance(self._last_player_state, str) and self._last_player_state else "--"
        action = self._last_nav_action if isinstance(self._last_nav_action, str) and self._last_nav_action else "--"
        floor_txt = "--"
        if isinstance(self._last_floor, (int, float)):
            try:
                floor_txt = f"{int(self._last_floor)}층"
            except Exception:
                floor_txt = f"{self._last_floor}층"
        return (
            f"현재층: {floor_txt}",
            f"캐릭터 상태: {state}",
            f"필요행동: {action}",
        )

    def _collect_fps_text(self) -> str:
        owner = (self._current_authority_owner or "map").lower()
        fps: float | None = None
        try:
            if owner == 'map' and self._map_tab is not None:
                stats = getattr(self._map_tab, 'latest_perf_stats', {}) or {}
                val = stats.get('fps')
                if isinstance(val, (int, float)):
                    fps = float(val)
        except Exception:
            pass
        try:
            if fps is None and self._hunt_tab is not None:
                stats = getattr(self._hunt_tab, 'latest_perf_stats', {}) or {}
                val = stats.get('fps')
                if isinstance(val, (int, float)):
                    fps = float(val)
        except Exception:
            pass
        if fps is None and get_capture_manager is not None:
            try:
                mgr = get_capture_manager()
                fps = float(getattr(mgr, 'get_target_fps')())
            except Exception:
                fps = None
        return f"{fps:.1f}" if isinstance(fps, float) else "--"

    def _collect_teleport_percent(self) -> str:
        owner = (self._current_authority_owner or "map").lower()
        percent: float | None = None
        # 권한 기준 우선 수집
        if owner == 'map' and self._map_tab is not None:
            try:
                text = getattr(self._map_tab, '_walk_teleport_probability_text', '') or ''
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)%", text)
                if m:
                    percent = float(m.group(1))
            except Exception:
                percent = None
        if percent is None and self._hunt_tab is not None:
            try:
                if hasattr(self._hunt_tab, '_get_walk_teleport_display_percent'):
                    percent = float(self._hunt_tab._get_walk_teleport_display_percent())
                else:
                    val = getattr(self._hunt_tab, '_walk_teleport_display_percent', None)
                    percent = float(val) if isinstance(val, (int, float)) else None
            except Exception:
                percent = None
        return f"{max(percent, 0.0):.1f}%" if isinstance(percent, float) else "--%"

    # EXP 표기 구성: 
    #  - 1줄: "EXP: amount(+Δ)"
    #  - 2줄: "EXP(%): n.n% (+x.x%)"
    #  - 3줄: "레벨업 HH:MM:SS"
    def _compose_exp_lines(self) -> tuple[str, str, str]:
        if not (isinstance(self._latest_exp_amount, str) and isinstance(self._latest_exp_percent, float)):
            return ("EXP: --", "EXP(%): --%", "레벨업 --:--:--")
        amount_str = self._latest_exp_amount
        percent_cur = float(self._latest_exp_percent)
        # Δ amount
        delta_amount_text = ""
        try:
            cur_amt = int(amount_str) if amount_str.isdigit() else None
            if isinstance(cur_amt, int) and isinstance(self._exp_start_amount, int):
                d_amt = max(0, cur_amt - self._exp_start_amount)
                delta_amount_text = f"(+{d_amt:,})"
        except Exception:
            delta_amount_text = ""
        # Δ percent
        delta_percent_text = ""
        if isinstance(self._exp_start_percent, float):
            d_per = percent_cur - float(self._exp_start_percent)
            sign = "+" if d_per >= 0 else ""
            delta_percent_text = f"({sign}{d_per:.1f}%)"
        # ETA
        eta_text = self._calc_exp_eta_text(percent_cur)
        # 포맷
        try:
            amount_fmt = f"{int(amount_str):,}"
        except Exception:
            amount_fmt = amount_str
        amount_line = f"EXP: {amount_fmt}{(' ' + delta_amount_text) if delta_amount_text else ''}"
        percent_line = f"EXP(%): {percent_cur:.1f}%{(' ' + delta_percent_text) if delta_percent_text else ''}"
        eta_line = f"레벨업 {eta_text}"
        return amount_line, percent_line, eta_line

    def _calc_exp_eta_text(self, percent_cur: float) -> str:
        elapsed = self._get_exp_elapsed_sec()
        if elapsed is None or not isinstance(self._exp_start_percent, float):
            return "--:--:--"
        if elapsed < 1.0:
            return "--:--:--"
        gain = max(0.0, percent_cur - float(self._exp_start_percent))
        if gain <= 0.0:
            return "--:--:--"
        rate_per_sec = gain / elapsed
        remain = max(0.0, 100.0 - percent_cur)
        if rate_per_sec <= 0.0:
            return "--:--:--"
        eta_sec = int(remain / rate_per_sec)
        return self._format_hhmmss(eta_sec)

    def _get_exp_elapsed_sec(self) -> float | None:
        if self._map_running or self._hunt_running:
            return max(0.0, time.time() - self._run_start_ts) if isinstance(self._run_start_ts, float) else None
        if self._exp_standalone_enabled:
            return float(self._exp_standalone_accum_sec)
        return None

    def _tick_exp_standalone_time(self) -> None:
        if not self._exp_standalone_enabled:
            self._exp_standalone_last_top_ts = None
            return
        now = time.time()
        if is_maple_window_foreground():
            if self._exp_standalone_last_top_ts is None:
                self._exp_standalone_last_top_ts = now
            else:
                self._exp_standalone_accum_sec += max(0.0, now - self._exp_standalone_last_top_ts)
                self._exp_standalone_last_top_ts = now
        else:
            self._exp_standalone_last_top_ts = None

    def _update_runtime_label(self) -> None:
        active = False
        elapsed_sec: int | None = None
        if self._map_running or self._hunt_running:
            active = isinstance(self._run_start_ts, float)
            if active:
                elapsed_sec = max(0, int(time.time() - float(self._run_start_ts)))
        elif self._exp_standalone_enabled:
            active = True
            # 누적된 시간만 사용(최상위 아닐 땐 일시정지)
            elapsed_sec = max(0, int(self._exp_standalone_accum_sec))
        if not active or elapsed_sec is None:
            self.runtime_label.setText("")
            return
        self.runtime_label.setText(f"실행시간: {self._format_hhmmss(elapsed_sec)}")

    @staticmethod
    def _format_hhmmss(sec: int) -> str:
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _is_any_session_active(self) -> bool:
        return bool(self._map_running or self._hunt_running or self._exp_standalone_enabled)

    @pyqtSlot(str, dict)
    def _on_authority_changed(self, owner: str, payload: dict) -> None:
        try:
            if owner in ("map", "hunt"):
                self._current_authority_owner = owner
            # 맵 스냅샷의 캐릭터 상태/필요행동/현재층 캐싱
            if isinstance(payload, dict):
                snap = payload.get('map_snapshot')
                if isinstance(snap, dict):
                    st = snap.get('player_state')
                    na = snap.get('navigation_action')
                    fl = snap.get('floor')
                    if isinstance(st, str):
                        self._last_player_state = st
                    if isinstance(na, str):
                        self._last_nav_action = na
                    try:
                        self._last_floor = float(fl) if fl is not None else None
                    except Exception:
                        self._last_floor = None
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

    # --- 모니터링 UI: 시작/정지/연동 동작 ---
    def _on_click_map_start(self) -> None:
        tab = self._map_tab
        try:
            if not tab:
                return
            btn = getattr(tab, 'detect_anchor_btn', None)
            is_running = bool(btn.isChecked()) if btn else bool(getattr(tab, 'is_detection_running', False))
            if not is_running:
                # 맵탭 시작(사용자 클릭과 동일 효과)
                if btn:
                    btn.click()
                else:
                    # 폴백: 외부 토글 호출
                    if hasattr(tab, 'toggle_anchor_detection'):
                        tab.toggle_anchor_detection(True)
        except Exception:
            pass

    def _on_click_hunt_start(self) -> None:
        tab = self._hunt_tab
        try:
            if not tab:
                return
            # 사냥탭은 API 제공
            if hasattr(tab, 'api_start_detection'):
                tab.api_start_detection()
            else:
                btn = getattr(tab, 'detect_btn', None)
                if btn and not btn.isChecked():
                    btn.click()
        except Exception:
            pass

    def _on_click_map_stop(self) -> None:
        """맵탭만 ESC와 동일하게 정지 + 모든 키 떼기."""
        stopped = False
        try:
            if self._map_tab and hasattr(self._map_tab, 'force_stop_detection'):
                # ESC와 동일한 로그/동작을 위해 esc_shortcut 사용
                stopped = self._map_tab.force_stop_detection(reason='esc_shortcut') or stopped
        except Exception:
            pass
        if stopped and self._auto_tab and hasattr(self._auto_tab, 'receive_control_command'):
            try:
                self._auto_tab.receive_control_command("모든 키 떼기", reason="esc:monitoring_stop_map")
            except Exception:
                pass
        self._sync_monitor_buttons_enabled()

    def _on_click_hunt_stop(self) -> None:
        """사냥탭만 ESC와 동일하게 정지 + 모든 키 떼기."""
        stopped = False
        try:
            if self._hunt_tab and hasattr(self._hunt_tab, 'force_stop_detection'):
                stopped = self._hunt_tab.force_stop_detection(reason='esc_shortcut') or stopped
        except Exception:
            pass
        if stopped and self._auto_tab and hasattr(self._auto_tab, 'receive_control_command'):
            try:
                self._auto_tab.receive_control_command("모든 키 떼기", reason="esc:monitoring_stop_hunt")
            except Exception:
                pass
        self._sync_monitor_buttons_enabled()

    def _on_link_toggled_from_monitor(self, checked: bool) -> None:
        """모니터링 탭의 연동 체크박스 변경 → 두 탭 모두에 전파."""
        self._apply_link_checkbox_state(bool(checked), propagate=True)

    def _apply_link_checkbox_state(self, checked: bool, *, propagate: bool) -> None:
        # 로컬 두 체크박스 동기화
        try:
            prev = self.map_link_checkbox.blockSignals(True)
            self.map_link_checkbox.setChecked(checked)
            self.map_link_checkbox.blockSignals(prev)
        except Exception:
            pass
        try:
            prev = self.hunt_link_checkbox.blockSignals(True)
            self.hunt_link_checkbox.setChecked(checked)
            self.hunt_link_checkbox.blockSignals(prev)
        except Exception:
            pass
        # 외부 탭 체크박스에 전파
        if propagate:
            try:
                if self._map_tab and hasattr(self._map_tab, 'map_link_checkbox') and self._map_tab.map_link_checkbox:
                    b = self._map_tab.map_link_checkbox.blockSignals(True)
                    self._map_tab.map_link_checkbox.setChecked(checked)
                    self._map_tab.map_link_checkbox.blockSignals(b)
                    # 맵탭 핸들러 직접 호출
                    if hasattr(self._map_tab, '_on_map_link_toggled'):
                        self._map_tab._on_map_link_toggled(checked)
            except Exception:
                pass
            try:
                if self._hunt_tab and hasattr(self._hunt_tab, 'map_link_checkbox') and self._hunt_tab.map_link_checkbox:
                    b = self._hunt_tab.map_link_checkbox.blockSignals(True)
                    self._hunt_tab.map_link_checkbox.setChecked(checked)
                    self._hunt_tab.map_link_checkbox.blockSignals(b)
                    if hasattr(self._hunt_tab, '_on_map_link_toggled'):
                        self._hunt_tab._on_map_link_toggled(checked)
            except Exception:
                pass
        # 저장
        self._persist_checkbox_states()
        # 버튼 활성화 상태 갱신
        self._sync_monitor_buttons_enabled()

    def _on_external_link_toggled(self, _checked: bool) -> None:
        """외부 탭에서 연동 체크 변경 시 모니터링 탭 체크박스 반영."""
        self._sync_link_checkbox_from_external()

    def _sync_link_checkbox_from_external(self) -> None:
        state = None
        try:
            if self._hunt_tab and hasattr(self._hunt_tab, 'map_link_checkbox') and self._hunt_tab.map_link_checkbox:
                state = bool(self._hunt_tab.map_link_checkbox.isChecked())
        except Exception:
            pass
        try:
            if state is None and self._map_tab and hasattr(self._map_tab, 'map_link_checkbox') and self._map_tab.map_link_checkbox:
                state = bool(self._map_tab.map_link_checkbox.isChecked())
        except Exception:
            pass
        if state is None:
            state = False
        self._apply_link_checkbox_state(state, propagate=False)
        self._persist_checkbox_states()

    def _on_map_detection_status_changed(self, running: bool) -> None:
        self._map_running = bool(running)
        if running:
            if self._run_start_ts is None:
                self._run_start_ts = time.time()
            # 세션 시작 시 EXP 기준치 초기화 후 현재값으로 고정
            self._exp_start_percent = None
            self._exp_start_amount = None
            if isinstance(self._latest_exp_percent, float):
                self._exp_start_percent = float(self._latest_exp_percent)
                try:
                    self._exp_start_amount = int(self._latest_exp_amount) if isinstance(self._latest_exp_amount, str) and self._latest_exp_amount.isdigit() else None
                except Exception:
                    self._exp_start_amount = None
        else:
            if not self._hunt_running:
                self._run_start_ts = None
                if not self._exp_standalone_enabled:
                    self._exp_start_percent = None
                    self._exp_start_amount = None
        self._sync_monitor_buttons_enabled()

    def _on_hunt_detection_status_changed(self, running: bool) -> None:
        self._hunt_running = bool(running)
        if running:
            if self._run_start_ts is None:
                self._run_start_ts = time.time()
            # 세션 시작 시 EXP 기준치 초기화 후 현재값으로 고정
            self._exp_start_percent = None
            self._exp_start_amount = None
            if isinstance(self._latest_exp_percent, float):
                self._exp_start_percent = float(self._latest_exp_percent)
                try:
                    self._exp_start_amount = int(self._latest_exp_amount) if isinstance(self._latest_exp_amount, str) and self._latest_exp_amount.isdigit() else None
                except Exception:
                    self._exp_start_amount = None
        else:
            if not self._map_running:
                self._run_start_ts = None
                if not self._exp_standalone_enabled:
                    self._exp_start_percent = None
                    self._exp_start_amount = None
        self._sync_monitor_buttons_enabled()

    def _sync_monitor_buttons_enabled(self) -> None:
        # 맵탭
        try:
            is_running = False
            if self._map_tab and hasattr(self._map_tab, 'detect_anchor_btn') and self._map_tab.detect_anchor_btn:
                is_running = bool(self._map_tab.detect_anchor_btn.isChecked())
            self.map_start_btn.setEnabled(not is_running)
            self.map_stop_btn.setEnabled(is_running)
        except Exception:
            pass
        # 사냥탭
        try:
            is_running = False
            if self._hunt_tab and hasattr(self._hunt_tab, 'detect_btn') and self._hunt_tab.detect_btn:
                is_running = bool(self._hunt_tab.detect_btn.isChecked())
            self.hunt_start_btn.setEnabled(not is_running)
            self.hunt_stop_btn.setEnabled(is_running)
        except Exception:
            pass

    # [NEW] 모니터링 오버레이 토글 핸들러 → 사냥 탭에 반영
    def _on_monitor_overlay_toggled(self, _checked: bool) -> None:
        if not self._hunt_tab:
            return
        try:
            prefs = {
                'hunt_area': bool(self.chk_hunt_bundle.isChecked()),
                'primary_area': bool(self.chk_hunt_bundle.isChecked()),
                'nickname_range': bool(self.chk_nickname_range.isChecked()),
                'nameplate_tracking': bool(self.chk_nameplate_track.isChecked()),
                'cleanup_chase_area': bool(self.chk_cleanup_band.isChecked()),
                'cluster_window_area': bool(self.chk_cluster_window.isChecked()),
            }
            if hasattr(self._hunt_tab, 'set_overlay_preferences'):
                self._hunt_tab.set_overlay_preferences(prefs)
        except Exception:
            pass

    # 외부에서 상태 모니터/데이터 매니저 연결 (EXP 단독실행 토글 감시 및 스냅샷 구독)
    def attach_status_monitor(self, monitor, data_manager=None) -> None:
        try:
            self._status_monitor = monitor
            if hasattr(monitor, 'status_captured'):
                monitor.status_captured.connect(self._on_status_snapshot)
        except Exception:
            pass
        self._status_data_manager = data_manager
        if data_manager and hasattr(data_manager, 'register_status_config_listener'):
            try:
                data_manager.register_status_config_listener(self._handle_status_config_update)
                cfg = data_manager.load_status_monitor_config() if hasattr(data_manager, 'load_status_monitor_config') else None
                if cfg is not None:
                    self._handle_status_config_update(cfg)
            except Exception:
                pass

    def _handle_status_config_update(self, config) -> None:
        try:
            mp_cfg = getattr(config, 'mp', None)
            exp_cfg = getattr(config, 'exp', None)
            # 모니터링 체크박스 상태 반영 (신호 루프 방지용 blockSignals)
            try:
                if mp_cfg is not None and hasattr(self, 'chk_mp_standalone'):
                    b = self.chk_mp_standalone.blockSignals(True)
                    self.chk_mp_standalone.setChecked(bool(getattr(mp_cfg, 'standalone', False)))
                    self.chk_mp_standalone.blockSignals(b)
            except Exception:
                pass
            if exp_cfg is None:
                return
            new_flag = bool(getattr(exp_cfg, 'standalone', False))
            try:
                if hasattr(self, 'chk_exp_standalone'):
                    b = self.chk_exp_standalone.blockSignals(True)
                    self.chk_exp_standalone.setChecked(new_flag)
                    self.chk_exp_standalone.blockSignals(b)
            except Exception:
                pass
            # 마지막 EXP 단독실행 상태를 QSettings에도 저장
            try:
                settings = QSettings("Gemini Inc.", "Maple AI Trainer")
                settings.setValue("monitoring/exp_standalone_last", new_flag)
            except Exception:
                pass
            if new_flag != self._exp_standalone_enabled:
                self._exp_standalone_enabled = new_flag
                if new_flag:
                    self._exp_standalone_start_ts = time.time()
                    self._exp_standalone_accum_sec = 0.0
                    self._exp_standalone_last_top_ts = None
                    if isinstance(self._latest_exp_percent, float):
                        self._exp_start_percent = float(self._latest_exp_percent)
                    try:
                        self._exp_start_amount = int(self._latest_exp_amount) if isinstance(self._latest_exp_amount, str) and self._latest_exp_amount.isdigit() else None
                    except Exception:
                        self._exp_start_amount = None
                else:
                    self._exp_standalone_start_ts = None
                    self._exp_standalone_accum_sec = 0.0
                    self._exp_standalone_last_top_ts = None
                    if not (self._map_running or self._hunt_running):
                        self._exp_start_percent = None
                        self._exp_start_amount = None
                        self.runtime_label.setText("")
        except Exception:
            pass

    def cleanup_on_close(self) -> None:
        self._stop_map_preview()
        # 스플리터 위치 저장
        try:
            settings = QSettings("Gemini Inc.", "Maple AI Trainer")
            settings.setValue("monitoring/splitter_sizes", self._vertical_splitter.sizes())
            settings.setValue("monitoring/top_hsplitter_sizes", self._top_hsplitter.sizes())
            settings.setValue("monitoring/bottom_hsplitter_sizes", self._bottom_hsplitter.sizes())
            # 체크박스 상태 저장
            settings.setValue("monitoring/map_preview_checked", bool(self.map_preview_checkbox.isChecked()))
            settings.setValue("monitoring/hunt_preview_checked", bool(self.hunt_preview_checkbox.isChecked()))
            settings.setValue("monitoring/ovl_hunt_bundle", bool(self.chk_hunt_bundle.isChecked()))
            settings.setValue("monitoring/ovl_nickname_range", bool(self.chk_nickname_range.isChecked()))
            settings.setValue("monitoring/ovl_nameplate_track", bool(self.chk_nameplate_track.isChecked()))
            settings.setValue("monitoring/ovl_cleanup_band", bool(self.chk_cleanup_band.isChecked()))
            settings.setValue("monitoring/ovl_cluster_window", bool(self.chk_cluster_window.isChecked()))
        except Exception:
            pass
        # 사냥 프리뷰 해제
        try:
            if self._hunt_tab:
                self._hunt_tab.api_set_preview_enabled(False, 0.0)
        except Exception:
            pass

    # --- 색/타임스탬프 유틸 ---
    def _brighten_color(self, color: str | None) -> str:
        try:
            if not color or not QColor.isValidColor(color):
                return "#EEEEEE"
            q = QColor(color)
            # 극도로 어두운 색(검정 포함)은 고정 밝은 회색으로 치환
            y = 0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()
            if y < 10:
                return "#DDDDDD"
            # 목표 최소 밝기(약간 더 밝게)
            TARGET = 200.0
            tries = 0
            while y < TARGET and tries < 6:
                q = q.lighter(130)
                y = 0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()
                tries += 1
            return q.name()
        except Exception:
            return "#EEEEEE"
