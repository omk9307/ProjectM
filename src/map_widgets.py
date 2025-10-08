"""맵 탭에서 사용하는 주요 위젯/뷰 클래스."""

from __future__ import annotations

import base64
import ctypes
import math
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer
from PyQt6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QPainter, QImage,
                        QPen, QPixmap, QPolygonF, QGuiApplication)
from PyQt6.QtWidgets import QLabel, QDialog, QWidget

try:
    import mss
except ImportError as exc:
    raise RuntimeError("mss 라이브러리가 필요합니다: pip install mss") from exc

__all__ = ['MultiScreenSnipper', 'NavigatorDisplay', 'RealtimeMinimapView']

class MultiScreenSnipper(QDialog):
    """여러 모니터를 포함한 전체 가상 화면에서 영역을 드래그로 선택합니다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        user32 = ctypes.windll.user32
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79

        virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        virtual_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        virtual_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        screens = QGuiApplication.screens()
        if not screens or virtual_width <= 0 or virtual_height <= 0:
            raise RuntimeError("모니터 정보를 가져올 수 없습니다.")

        self.virtual_origin = QPoint(virtual_left, virtual_top)
        self.virtual_size = QSize(virtual_width, virtual_height)

        # 가상 화면 전체를 덮도록 창을 이동/크기 조정
        self.setGeometry(virtual_left, virtual_top, virtual_width, virtual_height)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self._screenshot = self._build_virtual_screenshot()
        if self._screenshot is None:
            raise RuntimeError("가상 화면 캡처에 실패했습니다.")
        self._begin = QPoint()
        self._end = QPoint()
        self._is_selecting = False
        self._global_roi = QRect()
        self._target_screen = None

    def _build_virtual_screenshot(self):
        """Windows 가상 화면 전체를 캡처해 Pixmap으로 반환합니다."""
        monitor = {
            "left": self.virtual_origin.x(),
            "top": self.virtual_origin.y(),
            "width": self.virtual_size.width(),
            "height": self.virtual_size.height(),
        }

        try:
            with mss.mss() as sct:
                sct_img = sct.grab(monitor)

            self._screenshot_buffer = np.array(sct_img, copy=True)

            # PyQt6 환경에서 지원되는 포맷을 우선 사용 (BGRA → ARGB32 호환)
            image_format = QImage.Format.Format_ARGB32
            if hasattr(QImage.Format, "Format_BGRA8888"):
                image_format = QImage.Format.Format_BGRA8888

            qimage = QImage(
                self._screenshot_buffer.data,
                monitor["width"],
                monitor["height"],
                self._screenshot_buffer.strides[0],
                image_format,
            )
            return QPixmap.fromImage(qimage)
        except Exception as capture_error:
            # mss 캡처에 실패할 경우 Qt 스크린 API로 폴백
            size = self.virtual_size
            pixmap = QPixmap(size)
            pixmap.fill(QColor(0, 0, 0))

            offset_origin = self.virtual_origin
            painter = QPainter(pixmap)

            for screen in QGuiApplication.screens():
                geo = screen.geometry()
                grab = screen.grabWindow(0)
                if grab.width() != geo.width() or grab.height() != geo.height():
                    target_size = QSize(geo.width(), geo.height())
                    grab = grab.scaled(target_size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

                top_left = geo.topLeft() - offset_origin
                painter.drawPixmap(QRect(top_left, geo.size()), grab)

            painter.end()
            self._screenshot_buffer = None
            print(f"[MultiScreenSnipper] mss 캡처 실패, Qt 스크린으로 폴백: {capture_error}")
            return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(QPoint(0, 0), self._screenshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self._is_selecting:
            selected_rect = QRect(self._begin, self._end).normalized()
            painter.drawPixmap(selected_rect, self._screenshot, selected_rect)
            painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine))
            painter.drawRect(selected_rect)
        # 명시적으로 종료하여 활성 페인터 잔존 방지
        painter.end()

    def _resolve_target_screen(self, global_rect):
        best_screen = None
        best_area = 0
        for screen in QGuiApplication.screens():
            intersection = screen.geometry().intersected(global_rect)
            area = intersection.width() * intersection.height()
            if area > best_area:
                best_screen = screen
                best_area = area
        return best_screen

    def mousePressEvent(self, event):
        self._is_selecting = True
        self._begin = event.position().toPoint()
        self._end = self._begin
        self.update()

    def mouseMoveEvent(self, event):
        self._end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event):
        self._is_selecting = False
        self._end = event.position().toPoint()
        selected_rect = QRect(self._begin, self._end).normalized()

        if selected_rect.width() <= 5 or selected_rect.height() <= 5:
            self.reject()
            return

        top_left = QPoint(self.virtual_origin.x() + selected_rect.left(), self.virtual_origin.y() + selected_rect.top())
        self._global_roi = QRect(top_left, selected_rect.size())
        self._target_screen = self._resolve_target_screen(self._global_roi)

        if not self._target_screen:
            self.reject()
            return

        self.accept()

    def get_global_roi(self):
        return self._global_roi

    def get_target_screen(self):
        return self._target_screen


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
        self.direction_slot_label = "-"

    def update_data(self, floor, terrain_name, target_name, prev_name, next_name, 
                    direction, distance, full_path, last_reached_id, target_id, 
                    is_forward, direction_slot_label, intermediate_type, player_state, nav_action):
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
        self.direction_slot_label = direction_slot_label or ("정방향" if is_forward else "역방향")
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
            direction_label = self.direction_slot_label or ("정방향" if self.is_forward else "역방향")
            dist_rect = QRect(left_rect.x(), 50, left_rect.width(), 25)
            painter.drawText(dist_rect, Qt.AlignmentFlag.AlignCenter, direction_label)


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
                    if index == 0: return "[출발]🚩"
                    if index == len(self.full_path) - 1: return "[도착]🏁"
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
                main_target_text = f"[발판] {self.target_name}"
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
            # 명시적으로 종료하여 활성 페인터 잔존 방지
            painter.end()

# --- 위젯 클래스 ---

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

        # 금지벽 등 정적 정보 캐싱용
        self._cached_geometry = {}
        self._cached_key_features = {}
        self._cached_global_positions = {}
        self._display_enabled = True
        self._pending_update = False
        self._cached_static_pixmap = None
        self._cached_static_opts_signature: tuple = ()
        self._cached_static_bounds = QRectF()
        self._cached_static_dirty = True
        self._cached_feature_pixmaps: dict[str, QPixmap] = {}
        self._min_update_interval = 1.0 / 30.0
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(int(self._min_update_interval * 1000))
        self._update_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._flush_pending_update)
        self._min_camera_move_threshold = 1.5
        self._min_player_move_threshold = 1.5
        self._last_paint_time: float | None = None
        self._last_painted_camera_center: QPointF | None = None
        self._last_painted_player_center: QPointF | None = None
        self._update_scheduled_since_last_check = False
    
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

    def update_static_cache(self, *, geometry_data=None, key_features=None, global_positions=None) -> None:
        """MapTab에서 지형/지형 요소 데이터를 갱신할 때 호출되는 보조 함수."""
        if geometry_data is not None:
            self._cached_geometry = geometry_data
        if key_features is not None:
            self._cached_key_features = key_features
        if global_positions is not None:
            self._cached_global_positions = global_positions

        self._cached_static_dirty = True
        self._build_feature_pixmap_cache()

        if self.parent_tab and hasattr(self.parent_tab, 'full_map_bounding_rect'):
            bounding_rect = self.parent_tab.full_map_bounding_rect
            if bounding_rect and not bounding_rect.isNull():
                self.rebuild_static_overlay_now()

        # 프로필이 초기화될 때 기존 렌더링 잔상을 지우기 위한 기본 리셋
        if not geometry_data:
            self.active_features = []
            self.my_player_rects = []
            self.other_player_rects = []
            self.final_player_pos_global = None
        if self._display_enabled:
            self._pending_update = True
            self._update_scheduled_since_last_check = True
            self._schedule_view_update()
        else:
            self._pending_update = True

    def _schedule_view_update(self) -> None:
        if not self._display_enabled:
            return
        if not self._update_timer.isActive():
            self._update_timer.start()

    def _flush_pending_update(self) -> None:
        if not self._display_enabled:
            self._update_timer.stop()
            return
        if not (self._pending_update or self._update_scheduled_since_last_check):
            return
        self._pending_update = False
        self.update()

    def _build_feature_pixmap_cache(self) -> None:
        self._cached_feature_pixmaps.clear()
        for feature_id, feature_data in self._cached_key_features.items():
            image_b64 = feature_data.get('image_base64') if isinstance(feature_data, dict) else None
            if not image_b64:
                continue
            try:
                pixmap = QPixmap()
                pixmap.loadFromData(base64.b64decode(image_b64))
            except Exception:
                continue
            if not pixmap.isNull():
                self._cached_feature_pixmaps[feature_id] = pixmap

    def update_view_data(self, camera_center, active_features, my_players, other_players, target_wp_id, reached_wp_id, final_player_pos, is_forward, intermediate_pos, intermediate_type, nav_action, intermediate_node_type):
        """MapTab으로부터 렌더링에 필요한 최신 데이터를 받습니다."""
        camera_point = self._to_pointf(camera_center)
        if camera_point is not None:
            self.camera_center_global = camera_point
        self.active_features = active_features
        self.my_player_rects = my_players
        self.other_player_rects = other_players
        self.target_waypoint_id = target_wp_id
        self.last_reached_waypoint_id = reached_wp_id
        self.final_player_pos_global = self._to_pointf(final_player_pos) if final_player_pos is not None else None
        self.is_forward = is_forward
        self.intermediate_target_pos = self._to_pointf(intermediate_pos) if intermediate_pos is not None else None
        self.intermediate_target_type = intermediate_type
        self.navigation_action = nav_action
        self.intermediate_node_type = intermediate_node_type

        if not self._display_enabled:
            self._pending_update = True
            self._update_scheduled_since_last_check = False
            return False

        now = time.perf_counter()

        should_update = False
        if self._last_paint_time is None:
            should_update = True
        else:
            camera_delta = 0.0
            player_delta = 0.0

            if isinstance(self.camera_center_global, QPointF) and self._last_painted_camera_center is not None:
                camera_delta = max(
                    abs(self.camera_center_global.x() - self._last_painted_camera_center.x()),
                    abs(self.camera_center_global.y() - self._last_painted_camera_center.y()),
                )

            player_delta = 0.0
            if isinstance(self.final_player_pos_global, QPointF) and self._last_painted_player_center is not None:
                player_delta = max(
                    abs(self.final_player_pos_global.x() - self._last_painted_player_center.x()),
                    abs(self.final_player_pos_global.y() - self._last_painted_player_center.y()),
                )

            if camera_delta >= self._min_camera_move_threshold or player_delta >= self._min_player_move_threshold:
                should_update = True
            elif (now - self._last_paint_time) >= self._min_update_interval:
                should_update = True

        if should_update:
            self._pending_update = True
            self._update_scheduled_since_last_check = True
            self._schedule_view_update()
            return True

        self._pending_update = True
        self._update_scheduled_since_last_check = False
        return False

    def set_display_enabled(self, enabled: bool) -> None:
        self._display_enabled = bool(enabled)
        if self._display_enabled:
            if self._pending_update:
                self._update_scheduled_since_last_check = True
                self._schedule_view_update()
        else:
            self._update_timer.stop()
            self._update_scheduled_since_last_check = False

    def _make_render_opts_signature(self, render_opts: dict) -> tuple:
        keys = ('terrain', 'objects', 'jump_links', 'forbidden_walls')
        return tuple((key, bool(render_opts.get(key, True))) for key in keys)

    def consume_update_flag(self) -> bool:
        value = self._update_scheduled_since_last_check
        self._update_scheduled_since_last_check = False
        return value

    @staticmethod
    def _to_pointf(value) -> QPointF | None:
        if isinstance(value, QPointF):
            return value
        if isinstance(value, QPoint):
            return QPointF(value)
        if hasattr(value, 'x') and hasattr(value, 'y'):
            try:
                return QPointF(float(value.x()), float(value.y()))
            except Exception:
                return None
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            try:
                return QPointF(float(value[0]), float(value[1]))
            except Exception:
                return None
        if isinstance(value, (int, float)):
            return QPointF(float(value), 0.0)
        return None

    def _ensure_static_overlay(self, render_opts: dict, bounding_rect: QRectF) -> None:
        opts_sig = self._make_render_opts_signature(render_opts)
        if (
            self._cached_static_dirty
            or self._cached_static_pixmap is None
            or self._cached_static_pixmap.isNull()
            or self._cached_static_bounds != bounding_rect
            or self._cached_static_opts_signature != opts_sig
        ):
            self._build_static_overlay(render_opts, bounding_rect, opts_sig)

    def _build_static_overlay(self, render_opts: dict, bounding_rect: QRectF, opts_sig: tuple) -> None:
        self._cached_static_dirty = False
        self._cached_static_bounds = QRectF(bounding_rect)
        self._cached_static_opts_signature = opts_sig
        self._cached_static_pixmap = None

        if bounding_rect.isNull():
            return

        size = bounding_rect.size().toSize()
        if size.isEmpty():
            return

        build_started_at = time.perf_counter()

        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(-bounding_rect.topLeft())

        geometry_data = self._cached_geometry if isinstance(self._cached_geometry, dict) else {}

        # 지형선 및 그룹 이름을 캐싱된 레이어에 그리기
        if render_opts.get('terrain', True):
            terrain_lines = geometry_data.get("terrain_lines", [])
            if terrain_lines:
                from collections import defaultdict, deque

                adj = defaultdict(list)
                lines_by_id = {line['id']: line for line in terrain_lines if 'id' in line}

                point_to_lines = defaultdict(list)
                for line in terrain_lines:
                    for p in line.get('points', []):
                        point_to_lines[tuple(p)].append(line.get('id'))

                for ids in point_to_lines.values():
                    for i in range(len(ids)):
                        for j in range(i + 1, len(ids)):
                            a_id, b_id = ids[i], ids[j]
                            if a_id is None or b_id is None:
                                continue
                            adj[a_id].append(b_id)
                            adj[b_id].append(a_id)

                visited = set()
                all_groups = []
                for line_id in lines_by_id:
                    if line_id in visited:
                        continue
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
                    if current_group:
                        all_groups.append(current_group)

                groups_by_floor = defaultdict(list)
                for group in all_groups:
                    floor = group[0].get('floor', 0)
                    groups_by_floor[floor].append(group)

                dynamic_group_names = {}
                for floor, groups in groups_by_floor.items():
                    sorted_groups = sorted(
                        groups,
                        key=lambda g: sum(p[0] for line in g for p in line.get('points', []))
                        / max(1, sum(len(line.get('points', [])) for line in g))
                    )
                    for i, group in enumerate(sorted_groups):
                        first_line = group[0]
                        dynamic_group_names[first_line['id']] = f"{floor}층_{chr(ord('A') + i)}"

                painter.save()
                for group in all_groups:
                    pen = QPen(Qt.GlobalColor.magenta, 2)
                    painter.setPen(pen)

                    group_polygon_global = QPolygonF()
                    for line_data in group:
                        points = [QPointF(float(p[0]), float(p[1])) for p in line_data.get("points", [])]
                        if len(points) < 2:
                            continue
                        painter.drawPolyline(QPolygonF(points))
                        group_polygon_global += QPolygonF(points)

                    first_line = group[0]
                    group_name = dynamic_group_names.get(first_line['id'], f"{first_line.get('floor', 'N/A')}층")
                    group_rect_global = group_polygon_global.boundingRect()
                    if group_rect_global.isNull():
                        continue
                    font = QFont("맑은 고딕", 10, QFont.Weight.Bold)
                    text_pos_global = QPointF(group_rect_global.center().x(), group_rect_global.bottom() + 4)
                    tm = QFontMetrics(font)
                    text_rect = tm.boundingRect(group_name)
                    overlay_center = (text_pos_global - bounding_rect.topLeft()).toPoint()
                    text_rect.moveCenter(overlay_center)
                    self._draw_text_with_outline(
                        painter,
                        text_rect,
                        Qt.AlignmentFlag.AlignCenter,
                        group_name,
                        font,
                        Qt.GlobalColor.white,
                        Qt.GlobalColor.black,
                    )
                painter.restore()

        if render_opts.get('objects', True):
            painter.save()
            painter.setPen(QPen(QColor(255, 165, 0), 3))
            for obj_data in geometry_data.get("transition_objects", []):
                points = obj_data.get("points", [])
                if len(points) != 2:
                    continue
                segment_start = QPointF(float(points[0][0]), float(points[0][1]))
                segment_end = QPointF(float(points[1][0]), float(points[1][1]))
                painter.drawLine(segment_start, segment_end)
            painter.restore()

        if render_opts.get('jump_links', True):
            painter.save()
            pen = QPen(QColor(0, 255, 0, 200), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            for jump_data in geometry_data.get("jump_links", []):
                start_vertex = jump_data.get('start_vertex_pos')
                end_vertex = jump_data.get('end_vertex_pos')
                if not start_vertex or not end_vertex:
                    continue
                p1 = QPointF(float(start_vertex[0]), float(start_vertex[1]))
                p2 = QPointF(float(end_vertex[0]), float(end_vertex[1]))
                painter.drawLine(p1, p2)
            painter.restore()

        if render_opts.get('forbidden_walls', True):
            painter.save()
            for wall_data in geometry_data.get("forbidden_walls", []):
                pos = wall_data.get('pos')
                if not pos or len(pos) < 2:
                    continue
                global_point = QPointF(float(pos[0]), float(pos[1]))
                color = QColor(220, 50, 50) if wall_data.get('enabled') else QColor(150, 90, 90)
                outline = color.darker(150)

                range_left = max(0.0, float(wall_data.get('range_left', 0.0)))
                range_right = max(0.0, float(wall_data.get('range_right', 0.0)))
                range_pen = QPen(QColor(70, 160, 255, 230), 2.0, Qt.PenStyle.SolidLine)
                range_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(range_pen)

                if range_left > 0.0:
                    left_global = QPointF(global_point.x() - range_left, global_point.y())
                    painter.drawLine(left_global, global_point)

                if range_right > 0.0:
                    right_global = QPointF(global_point.x() + range_right, global_point.y())
                    painter.drawLine(global_point, right_global)

                dot_radius = 3.0
                painter.setPen(QPen(outline, 1.5))
                painter.setBrush(QBrush(color))
                painter.drawEllipse(global_point, dot_radius, dot_radius)
            painter.restore()

        painter.end()
        self._cached_static_pixmap = pixmap

        elapsed_ms = (time.perf_counter() - build_started_at) * 1000.0
        parent = getattr(self, 'parent_tab', None)
        if parent is not None:
            try:
                parent._static_rebuild_ms_pending = float(elapsed_ms)
            except Exception:
                pass

    def rebuild_static_overlay_now(self) -> None:
        bounding_rect = self.parent_tab.full_map_bounding_rect
        if not isinstance(bounding_rect, QRectF) or bounding_rect.isNull():
            return
        render_opts = self.parent_tab.render_options
        opts_sig = self._make_render_opts_signature(render_opts)
        self._build_static_overlay(render_opts, bounding_rect, opts_sig)

    def paintEvent(self, event):
        """
        v13.0.4: [BUGFIX] self.last_reached_wp_id 오타를 last_reached_waypoint_id로 수정.
                 [REFACTOR] self.my_player_rects 접근 시 IndexError 방지를 위한 조건문 추가.
        배경 지도 위에 보기 옵션에 따라 모든 요소를 동적으로 렌더링합니다.
        """
        super().paintEvent(event)
        if not self._display_enabled:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        map_bg = self.parent_tab.full_map_pixmap
        bounding_rect = self.parent_tab.full_map_bounding_rect

        if not map_bg or map_bg.isNull() or bounding_rect.isNull():
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
            painter.end()
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

        render_opts = self.parent_tab.render_options
        self._ensure_static_overlay(render_opts, bounding_rect)
        if self._cached_static_pixmap and not self._cached_static_pixmap.isNull():
            painter.drawPixmap(target_rect, self._cached_static_pixmap, image_source_rect)

        def global_to_local(global_pos):
            point = self._to_pointf(global_pos)
            if point is None:
                point = QPointF(0.0, 0.0)
            relative_pos = point - source_rect.topLeft()
            return relative_pos * self.zoom_level

        #핵심 지형 렌더링 (텍스트 스타일 변경) ---
        if render_opts.get('features', True):
            painter.save()
            realtime_conf_map = {f['id']: f['conf'] for f in self.active_features}

            global_positions = self._cached_global_positions if isinstance(self._cached_global_positions, dict) else self.parent_tab.global_positions

            for feature_id, feature_data in self.parent_tab.key_features.items():
                global_pos = global_positions.get(feature_id) if isinstance(global_positions, dict) else None
                if global_pos is None:
                    continue

                pixmap = self._cached_feature_pixmaps.get(feature_id)
                if not pixmap or pixmap.isNull():
                    continue

                if not isinstance(global_pos, QPointF):
                    try:
                        global_pos = QPointF(float(global_pos[0]), float(global_pos[1]))
                    except Exception:
                        continue

                global_rect = QRectF(global_pos, QSizeF(pixmap.size()))
                local_top_left = global_to_local(global_rect.topLeft())
                local_rect = QRectF(local_top_left, global_rect.size() * self.zoom_level)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                realtime_conf = realtime_conf_map.get(feature_id, 0.0)
                threshold = feature_data.get('threshold', 0.85)
                is_detected = realtime_conf >= threshold

                font_name = QFont("맑은 고딕", 9, QFont.Weight.Bold)

                if is_detected:
                    painter.setPen(QPen(QColor(0, 180, 255), 2, Qt.PenStyle.SolidLine))
                    self._draw_text_with_outline(
                        painter,
                        local_rect.toRect(),
                        Qt.AlignmentFlag.AlignCenter,
                        feature_id,
                        font_name,
                        Qt.GlobalColor.white,
                        Qt.GlobalColor.black,
                    )
                else:
                    painter.setPen(QPen(QColor("gray"), 2, Qt.PenStyle.DashLine))
                    self._draw_text_with_outline(
                        painter,
                        local_rect.toRect(),
                        Qt.AlignmentFlag.AlignCenter,
                        feature_id,
                        font_name,
                        QColor("#AAAAAA"),
                        Qt.GlobalColor.black,
                    )

                conf_text = f"{realtime_conf:.2f}"
                font_conf = QFont("맑은 고딕", 10)

                tm_conf = QFontMetrics(font_conf)
                conf_rect = tm_conf.boundingRect(conf_text)
                conf_rect.moveCenter(local_rect.center().toPoint())
                conf_rect.moveTop(int(local_rect.top()) - conf_rect.height() - 2)

                color = Qt.GlobalColor.yellow if is_detected else QColor("#AAAAAA")
                self._draw_text_with_outline(
                    painter,
                    conf_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    conf_text,
                    font_conf,
                    color,
                    Qt.GlobalColor.black,
                )

                painter.drawRect(local_rect)
            painter.restore()

            
        # 웨이포인트 (줌 레벨 연동 크기) ---
        if render_opts.get('waypoints', True):
            painter.save()
            WAYPOINT_SIZE = 12.0 # 전역 좌표계 기준 크기
            
            # 웨이포인트 순서 맵 생성 (현재 실행 중인 여정 우선)
            wp_order_map = {}
            path_ids = []

            if self.parent_tab.journey_plan:
                path_ids = list(self.parent_tab.journey_plan)
            elif self.parent_tab.active_route_profile_name:
                route = self.parent_tab.route_profiles.get(self.parent_tab.active_route_profile_name, {}) or {}

                if self.is_forward:
                    slot_id = getattr(self.parent_tab, "current_forward_slot", "1") or "1"
                    path_ids = self.parent_tab._get_route_slot_waypoints(route, "forward", slot_id)
                    if not path_ids:
                        enabled_slots = self.parent_tab._get_enabled_slot_ids(route, "forward")
                        if enabled_slots:
                            fallback_slot = enabled_slots[0]
                            path_ids = self.parent_tab._get_route_slot_waypoints(route, "forward", fallback_slot)
                else:
                    slot_id = getattr(self.parent_tab, "current_backward_slot", "1") or "1"
                    path_ids = self.parent_tab._get_route_slot_waypoints(route, "backward", slot_id)
                    if not path_ids:
                        enabled_slots = self.parent_tab._get_enabled_slot_ids(route, "backward")
                        if enabled_slots:
                            fallback_slot = enabled_slots[0]
                            path_ids = self.parent_tab._get_route_slot_waypoints(route, "backward", fallback_slot)
                        else:
                            forward_slot = getattr(self.parent_tab, "last_selected_forward_slot", None) or getattr(self.parent_tab, "current_forward_slot", "1")
                            forward_path = self.parent_tab._get_route_slot_waypoints(route, "forward", forward_slot)
                            if forward_path:
                                path_ids = list(reversed(forward_path))
                            else:
                                enabled_forward = self.parent_tab._get_enabled_slot_ids(route, "forward")
                                if enabled_forward:
                                    forward_path = self.parent_tab._get_route_slot_waypoints(route, "forward", enabled_forward[0])
                                    path_ids = list(reversed(forward_path))

            if path_ids:
                for i, wp_id in enumerate(path_ids):
                    wp_order_map[wp_id] = f"{i+1}"

                if len(path_ids) > 1:
                    wp_order_map[path_ids[0]] = "출발지"
                    wp_order_map[path_ids[-1]] = "목적지"
                elif len(path_ids) == 1:
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
                elif wp_data.get('is_event'):
                    painter.setPen(QPen(QColor(0, 135, 255), 2))
                    painter.setBrush(QBrush(QColor(0, 135, 255, 80)))
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
                # [MODIFIED] 오타 수정: self.last_reached_wp_id -> self.last_reached_waypoint_id
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
            # [MODIFIED] IndexError 방지를 위해 조건문 추가
            if self.my_player_rects:
                p1_global = self.my_player_rects[0].center()

            # 끝점: 타입에 따라 보정
            p2_global = self.intermediate_target_pos
            if self.intermediate_node_type == 'waypoint':
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
            icon_center_local = p2_local
            TARGET_ICON_SIZE = 5.0
            scaled_size = TARGET_ICON_SIZE * self.zoom_level
            
            icon_rect = QRectF(
                icon_center_local.x() - scaled_size / 2,
                icon_center_local.y() - scaled_size / 2,
                scaled_size,
                scaled_size
            )
            
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(Qt.GlobalColor.red))
            painter.drawEllipse(icon_rect)
            
            painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(icon_rect)

            painter.setPen(QPen(Qt.GlobalColor.white, 1))
            painter.drawLine(icon_rect.topLeft(), icon_rect.bottomRight())
            painter.drawLine(icon_rect.topRight(), icon_rect.bottomLeft())
            
            painter.restore()

        # 내 캐릭터, 다른 유저 
        painter.save()
        painter.setPen(QPen(Qt.GlobalColor.yellow, 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.final_player_pos_global and self.my_player_rects:
            base_rect = self.my_player_rects[0]
            rect_bottom_center_global = base_rect.center() + QPointF(0, base_rect.height() / 2)
            offset = self.final_player_pos_global - rect_bottom_center_global
            
            for rect in self.my_player_rects:
                corrected_rect_global = rect.translated(offset)
                local_top_left = global_to_local(corrected_rect_global.topLeft())
                local_rect = QRectF(local_top_left, corrected_rect_global.size() * self.zoom_level)
                painter.drawRect(local_rect)
        else:
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
            pen = QPen(QColor(255, 255, 0, 200), 1.5)
            painter.setPen(pen)
            painter.drawLine(local_player_pos + QPointF(-5, 0), local_player_pos + QPointF(5, 0))
            painter.drawLine(local_player_pos + QPointF(0, -5), local_player_pos + QPointF(0, 5))

            painter.setBrush(QBrush(Qt.GlobalColor.yellow))
            painter.drawEllipse(local_player_pos, 2, 2)
            painter.restore()

        self._last_paint_time = time.perf_counter()
        self._last_painted_camera_center = QPointF(self.camera_center_global)
        player_point = self._to_pointf(self.final_player_pos_global)
        self._last_painted_player_center = player_point
        # 명시적으로 종료하여 활성 페인터 잔존 방지
        painter.end()

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
