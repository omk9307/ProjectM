# main.py
# 2025년 08月 08日 18:48 (KST)
# 기능: 여러 기능 모듈을 탭 형태로 관리하는 메인 애플리케이션 셸
# 설명:
# - v1.1: QSettings를 사용하여 프로그램 종료 시 창의 위치와 크기를 저장하고,
#         재시작 시 복원하는 기능 추가.
# - QTabWidget을 사용하여 각 기능(.py)을 별도의 탭으로 표시.
# - importlib를 사용하여 모듈을 동적으로 로드하고, 로드 실패 시 에러 탭을 표시합니다.
# - 각 탭은 QWidget을 상속받은 클래스로 구현되어야 합니다.

import sys
import os
import ctypes
import importlib
import traceback
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel, QTabBar,
    QStylePainter, QStyleOptionTab, QStyle
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QAbstractNativeEventFilter
from PyQt6.QtGui import QColor, QPainter

from status_monitor import StatusMonitorThread
from ocr_watch import OCRWatchThread
from control_authority_manager import ControlAuthorityManager


if os.name == 'nt':
    from ctypes import wintypes

    WM_HOTKEY = 0x0312
    VK_ESCAPE = 0x1B
    MOD_SHIFT = 0x0004

    class _EscHotkeyEventFilter(QAbstractNativeEventFilter):
        def __init__(self, hotkey_ids: set[int], callback):
            super().__init__()
            self.hotkey_ids = set(hotkey_ids)
            self.callback = callback

        def nativeEventFilter(self, event_type, message):
            if event_type == "windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam in self.hotkey_ids:
                    self.callback()
            return False, 0

    class _EscHotkeyManager:
        _NEXT_ID = 1000

        def __init__(self):
            self.user32 = ctypes.windll.user32
            self._registered: dict[tuple[int, int], int] = {}

        def register_hotkey(self, modifiers: int, key_code: int) -> int:
            combo = (modifiers, key_code)
            existing_id = self._registered.pop(combo, None)
            if existing_id is not None:
                self.user32.UnregisterHotKey(None, existing_id)

            hotkey_id = _EscHotkeyManager._NEXT_ID
            _EscHotkeyManager._NEXT_ID += 1

            if not self.user32.RegisterHotKey(None, hotkey_id, modifiers, key_code):
                raise RuntimeError(f"RegisterHotKey failed for modifiers={modifiers:#04x}, key_code={key_code:#04x}")

            self._registered[combo] = hotkey_id
            return hotkey_id

        def register_multiple(self, combos: list[tuple[int, int]]) -> set[int]:
            registered_ids: list[int] = []
            try:
                for modifiers, key_code in combos:
                    registered_ids.append(self.register_hotkey(modifiers, key_code))
                return set(registered_ids)
            except Exception as exc:
                for modifiers, key_code in combos:
                    self.unregister_hotkey(modifiers, key_code)
                raise exc

        def unregister_hotkey(self, modifiers: int, key_code: int) -> None:
            combo = (modifiers, key_code)
            hotkey_id = self._registered.pop(combo, None)
            if hotkey_id is not None:
                self.user32.UnregisterHotKey(None, hotkey_id)

        def unregister_all(self) -> None:
            for modifiers, key_code in list(self._registered.keys()):
                self.unregister_hotkey(modifiers, key_code)
else:
    _EscHotkeyEventFilter = None
    _EscHotkeyManager = None

def log_uncaught_exceptions(ex_cls, ex, tb):
    """
    처리되지 않은 예외를 잡아 crash_log.txt 파일에 기록하는 전역 핸들러.
    """
    log_file = "crash_log.txt"
    
    # 현재 시간 기록
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 오류 정보 포맷팅
    tb_text = ''.join(traceback.format_tb(tb))
    exception_text = f"Timestamp: {timestamp}\n"
    exception_text += f"Exception Type: {ex_cls.__name__}\n"
    exception_text += f"Exception Message: {ex}\n"
    exception_text += "Traceback:\n"
    exception_text += tb_text
    
    # 콘솔에도 출력
    print(exception_text)
    
    # 파일에 기록 (기존 내용에 추가)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write("="*80 + "\n")
        f.write(exception_text)
        f.write("="*80 + "\n\n")
        
    # Qt 기본 핸들러도 호출 (선택 사항, 하지만 보통 함께 호출해주는 것이 좋음)
    sys.__excepthook__(ex_cls, ex, tb)
    
class ColoredTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_colors: dict[int, str] = {}

    def set_tab_color(self, index: int, color: str | None) -> None:
        if color:
            self._tab_colors[index] = color
        else:
            self._tab_colors.pop(index, None)
        self.update()

    def clear_colors(self) -> None:
        if not self._tab_colors:
            return
        self._tab_colors.clear()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)

        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            color_name = self._tab_colors.get(index)
            if color_name:
                color = QColor(color_name)
                if color.isValid():
                    rect = option.rect.adjusted(1, 1, -1, -1)
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    border_pen = QColor(color).darker(130)
                    painter.setPen(border_pen)
                    painter.setBrush(color)
                    painter.drawRoundedRect(rect, 6, 6)
                    painter.setPen(Qt.GlobalColor.white)
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, option.text)
                    painter.restore()
                    continue
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, option)


class MainWindow(QMainWindow):
    """
    메인 윈도우 클래스.
    QTabWidget을 중앙 위젯으로 사용하여 여러 기능 탭을 관리합니다.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Project M - 통합 대시보드')
        
        self.settings = QSettings("Gemini Inc.", "Maple AI Trainer")
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(100, 100, 1280, 800)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setMovable(True)

        tab_bar = ColoredTabBar()
        tab_bar.tabMoved.connect(self._handle_tab_moved)
        self.tab_widget.setTabBar(tab_bar)

        self.setCentralWidget(self.tab_widget)

        # [수정] 로드된 탭 인스턴스를 저장할 딕셔너리
        self.loaded_tabs = {}
        self.status_monitor_thread: StatusMonitorThread | None = None
        self._ocr_watch_thread: OCRWatchThread | None = None
        self._data_manager = None
        self.esc_hotkey_manager = None
        self.esc_hotkey_filter = None
        self._tab_color_states: dict[str, str] = {}
        self._hunt_detection_active = False
        self._map_detection_active = False
        self._current_authority_owner: str | None = None
        self._authority_manager = ControlAuthorityManager.instance()
        self._authority_manager.authority_changed.connect(self._handle_global_authority_changed)

        self.load_tabs()
        # 텔레그램 브리지 핸들러 보관용
        self._telegram_bridge = None

    def load_tabs(self):
        """
        미리 정의된 탭 모듈 목록을 순서대로 로드합니다.
        """
        tabs_to_load = [
            ('Learning', 'LearningTab', '학습'),
            ('hunt', 'HuntTab', '사냥'),
            ('map', 'MapTab', '맵'),
            ('auto_control', 'AutoControlTab', '자동 제어') # [추가]
        ]

        for module_name, class_name, tab_title in tabs_to_load:
            self.load_tab(module_name, class_name, tab_title)
            
        # [추가] 모든 탭 로드 후 시그널-슬롯 연결
        self.connect_tabs()
        self._update_global_hotkey_state()
        try:
            current_state = self._authority_manager.current_state()
            self._handle_global_authority_changed(current_state.owner, {})
        except Exception:
            pass

        # 텔레그램 브리지 시작(자격이 유효한 Windows에서만)
        try:
            from telegram_bridge import maybe_start_bridge

            self._telegram_bridge = maybe_start_bridge(self)
        except Exception as exc:
            print(f"[Main] 텔레그램 브리지 시작 실패: {exc}")

    def load_tab(self, module_name, class_name, tab_title):
        """
        주어진 정보를 바탕으로 모듈을 동적으로 임포트하고 탭을 추가합니다.
        """
        try:
            module = importlib.import_module(module_name)
            TabClass = getattr(module, class_name)
            tab_instance = TabClass()
            self.tab_widget.addTab(tab_instance, tab_title)
            
            # [수정] 인스턴스를 딕셔너리에 저장
            self.loaded_tabs[tab_title] = tab_instance
            
            print(f"성공: '{tab_title}' 탭을 로드했습니다.")

        except ImportError as e:
            # ... (기존 오류 처리 코드는 동일) ...
            print(f"오류: 모듈 '{module_name}'을(를) 찾을 수 없습니다. {e}")
            self.add_error_tab(tab_title, f"모듈 파일을 찾을 수 없습니다:\n{module_name}.py")
        except AttributeError as e:
            print(f"오류: 모듈 '{module_name}'에서 클래스 '{class_name}'을(를) 찾을 수 없습니다. {e}")
            self.add_error_tab(tab_title, f"클래스를 찾을 수 없습니다:\n{class_name}")
        except Exception as e:
            print(f"오류: '{tab_title}' 탭 로드 중 예외 발생: {e}")
            self.add_error_tab(tab_title, f"알 수 없는 오류가 발생했습니다:\n{e}")

    # [추가] 시그널-슬롯 연결을 위한 새 메서드
    def connect_tabs(self):
        """
        로드된 탭들 간의 필요한 시그널-슬롯을 연결합니다.
        """
        if '학습' in self.loaded_tabs and '사냥' in self.loaded_tabs:
            learning_tab = self.loaded_tabs['학습']
            hunt_tab = self.loaded_tabs['사냥']

            data_manager = None
            if hasattr(learning_tab, 'get_data_manager'):
                data_manager = learning_tab.get_data_manager()
            elif hasattr(learning_tab, 'data_manager'):
                data_manager = getattr(learning_tab, 'data_manager')

            if data_manager:
                # OCR에서 사용할 데이터 매니저 보관
                self._data_manager = data_manager
                hunt_tab.attach_data_manager(data_manager)
                print("성공: '학습' 탭의 데이터 매니저를 '사냥' 탭에 연결했습니다.")

                if self.status_monitor_thread is None:
                    status_config = data_manager.load_status_monitor_config()
                    roi_payloads = data_manager.get_status_roi_payloads()
                    self.status_monitor_thread = StatusMonitorThread(
                        status_config,
                        roi_payloads=roi_payloads,
                        roi_provider=data_manager.get_status_roi_payloads,
                    )
                    data_manager.register_status_config_listener(self.status_monitor_thread.update_config)
                    if '사냥' in self.loaded_tabs:
                        self.loaded_tabs['사냥'].attach_status_monitor(self.status_monitor_thread)
                    if '맵' in self.loaded_tabs:
                        map_tab_instance = self.loaded_tabs['맵']
                        if hasattr(map_tab_instance, 'attach_status_monitor'):
                            map_tab_instance.attach_status_monitor(self.status_monitor_thread, data_manager)
                    self.status_monitor_thread.start()
            else:
                print("경고: '학습' 탭에서 데이터 매니저를 찾을 수 없어 '사냥' 탭 연동을 건너뜁니다.")

        if '사냥' in self.loaded_tabs and '자동 제어' in self.loaded_tabs:
            hunt_tab = self.loaded_tabs['사냥']
            auto_control_tab = self.loaded_tabs['자동 제어']

            hunt_tab.control_command_issued.connect(auto_control_tab.receive_control_command)
            auto_control_tab.log_generated.connect(hunt_tab.append_log)
            auto_control_tab.sequence_completed.connect(hunt_tab.on_sequence_completed)

            if hasattr(hunt_tab, 'append_log'):
                hunt_tab.append_log("자동 제어 탭과 연동이 설정되었습니다.")

            print("성공: '사냥' 탭과 '자동 제어' 탭을 연결했습니다.")

            if hasattr(hunt_tab, 'detection_status_changed'):
                try:
                    hunt_tab.detection_status_changed.connect(self._on_hunt_detection_status_changed)
                    current = bool(getattr(hunt_tab, '_detection_status', False))
                    self._on_hunt_detection_status_changed(current)
                except Exception:
                    pass
        else:
            print("경고: '사냥' 또는 '자동 제어' 탭을 찾을 수 없어 연결하지 못했습니다.")

        if '맵' in self.loaded_tabs and '자동 제어' in self.loaded_tabs:
            map_tab = self.loaded_tabs['맵']
            auto_control_tab = self.loaded_tabs['자동 제어']

            map_tab.control_command_issued.connect(auto_control_tab.receive_control_command)
            map_tab.detection_status_changed.connect(auto_control_tab.update_map_detection_status)
            
            # [추가] AutoControlTab의 탐지 토글 요청을 MapTab의 버튼 클릭 슬롯에 연결
            auto_control_tab.request_detection_toggle.connect(map_tab.detect_anchor_btn.click)
            auto_control_tab.sequence_completed.connect(map_tab.on_sequence_completed)
            auto_control_tab.command_profile_renamed.connect(map_tab.on_command_profile_renamed)

            if hasattr(map_tab, 'attach_auto_control_tab'):
                map_tab.attach_auto_control_tab(auto_control_tab)

            print("성공: '맵' 탭과 '자동 제어' 탭을 연결했습니다.")

            if hasattr(map_tab, 'detection_status_changed'):
                try:
                    map_tab.detection_status_changed.connect(self._on_map_detection_status_changed)
                    current = bool(getattr(map_tab, 'is_detection_running', False))
                    self._on_map_detection_status_changed(current)
                except Exception:
                    pass
        else:
            print("경고: '맵' 또는 '자동 제어' 탭을 찾을 수 없어 연결하지 못했습니다.")

        hunt_tab_instance = self.loaded_tabs.get('사냥')
        map_tab_instance = self.loaded_tabs.get('맵')
        if hunt_tab_instance and map_tab_instance:
            if hasattr(hunt_tab_instance, 'attach_map_tab'):
                hunt_tab_instance.attach_map_tab(map_tab_instance)
            if hasattr(map_tab_instance, 'attach_hunt_tab'):
                map_tab_instance.attach_hunt_tab(hunt_tab_instance)

    # ... (add_error_tab, closeEvent 메서드는 기존과 동일) ...
    def _handle_global_authority_changed(self, owner: str, payload: dict) -> None:
        tab_bar = self.tab_widget.tabBar()
        if not isinstance(tab_bar, ColoredTabBar):
            return

        map_index = self._find_tab_index('맵')
        hunt_index = self._find_tab_index('사냥')

        self._current_authority_owner = owner
        self._refresh_tab_colors()

    def _find_tab_index(self, title: str) -> Optional[int]:
        for index in range(self.tab_widget.count()):
            if self.tab_widget.tabText(index) == title:
                return index
        return None

    def add_error_tab(self, title, message):
        """
        탭 로딩 실패 시, 사용자에게 오류를 알리는 탭을 추가합니다.
        """
        error_widget = QWidget()
        layout = QVBoxLayout()
        error_label = QLabel(f"'{title}' 탭을 불러오는 중 오류가 발생했습니다.\n\n{message}")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setStyleSheet("color: red; font-size: 16px;")
        layout.addWidget(error_label)
        error_widget.setLayout(layout)
        self.tab_widget.addTab(error_widget, f"{title} (오류)")

    def closeEvent(self, event):
        """
        메인 윈도우가 닫힐 때 각 탭의 정리(cleanup) 함수를 호출하고,
        창의 위치와 크기를 저장합니다.
        """
        self.settings.setValue("geometry", self.saveGeometry())

        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if hasattr(widget, 'cleanup_on_close') and callable(getattr(widget, 'cleanup_on_close')):
                print(f"'{self.tab_widget.tabText(i)}' 탭의 리소스를 정리합니다...")
                widget.cleanup_on_close()

        monitor = getattr(self, 'status_monitor_thread', None)
        if monitor:
            monitor.stop()
            monitor.wait(2000)
        # OCR 워커 정리
        self._stop_ocr_watch()

        self._teardown_global_hotkeys()

        event.accept()

    def _update_global_hotkey_state(self) -> None:
        should_enable = self._hunt_detection_active or self._map_detection_active
        currently_enabled = self.esc_hotkey_manager is not None and self.esc_hotkey_filter is not None

        if should_enable and not currently_enabled:
            self._setup_global_hotkeys()
        elif not should_enable and currently_enabled:
            self._teardown_global_hotkeys()

    def _setup_global_hotkeys(self) -> None:
        if self.esc_hotkey_manager or self.esc_hotkey_filter:
            return
        if _EscHotkeyManager is None or _EscHotkeyEventFilter is None:
            return

        app = QApplication.instance()
        if app is None:
            return

        try:
            self.esc_hotkey_manager = _EscHotkeyManager()
            combos = [(0, VK_ESCAPE), (MOD_SHIFT, VK_ESCAPE)]
            hotkey_ids = self.esc_hotkey_manager.register_multiple(combos)
            self.esc_hotkey_filter = _EscHotkeyEventFilter(hotkey_ids, self._handle_global_escape)
            app.installNativeEventFilter(self.esc_hotkey_filter)
            print("성공: ESC 및 SHIFT+ESC 전역 단축키를 등록했습니다.")
        except Exception as exc:
            print(f"경고: ESC 전역 단축키 등록에 실패했습니다: {exc}")
            self._teardown_global_hotkeys()

    def _teardown_global_hotkeys(self) -> None:
        app = QApplication.instance()
        if self.esc_hotkey_filter and app:
            try:
                app.removeNativeEventFilter(self.esc_hotkey_filter)
            except Exception:
                pass
        if self.esc_hotkey_manager:
            try:
                self.esc_hotkey_manager.unregister_all()
            except Exception:
                pass
        self.esc_hotkey_filter = None
        self.esc_hotkey_manager = None

    def _handle_global_escape(self) -> None:
        stopped_any = False

        hunt_tab = self.loaded_tabs.get('사냥')
        if hasattr(hunt_tab, 'force_stop_detection'):
            try:
                stopped_any = hunt_tab.force_stop_detection(reason='esc_shortcut') or stopped_any
            except Exception as exc:
                print(f"경고: 사냥 탭 강제 중단 중 오류: {exc}")

        map_tab = self.loaded_tabs.get('맵')
        if hasattr(map_tab, 'force_stop_detection'):
            try:
                stopped_any = map_tab.force_stop_detection(reason='esc_shortcut') or stopped_any
            except Exception as exc:
                print(f"경고: 맵 탭 강제 중단 중 오류: {exc}")

        if stopped_any:
            self._schedule_release_all_keys()

    def _schedule_release_all_keys(self) -> None:
        auto_control_tab = self.loaded_tabs.get('자동 제어')
        if not auto_control_tab:
            print("경고: '자동 제어' 탭을 찾을 수 없어 '모든 키 떼기' 명령을 전송하지 못했습니다.")
            return

        def _send_release():
            try:
                auto_control_tab.receive_control_command("모든 키 떼기", reason="esc:global_stop")
            except Exception as exc:
                print(f"경고: '모든 키 떼기' 명령 전송 실패: {exc}")

        QTimer.singleShot(500, _send_release)

    def _handle_tab_moved(self, from_index: int, to_index: int) -> None:  # noqa: ARG002
        self._reapply_tab_colors()

    def _set_tab_color(self, tab_title: str, color: str | None) -> None:
        widget = self.loaded_tabs.get(tab_title)
        if widget is None:
            return
        index = self.tab_widget.indexOf(widget)
        if index == -1:
            return

        tab_bar = self.tab_widget.tabBar()
        if not isinstance(tab_bar, ColoredTabBar):
            return

        if color:
            self._tab_color_states[tab_title] = color
        else:
            self._tab_color_states.pop(tab_title, None)

        tab_bar.set_tab_color(index, color)

    def _reapply_tab_colors(self) -> None:
        tab_bar = self.tab_widget.tabBar()
        if not isinstance(tab_bar, ColoredTabBar):
            return

        tab_bar.clear_colors()
        for tab_title, color in self._tab_color_states.items():
            widget = self.loaded_tabs.get(tab_title)
            if widget is None:
                continue
            index = self.tab_widget.indexOf(widget)
            if index != -1:
                tab_bar.set_tab_color(index, color)

    def _on_hunt_detection_status_changed(self, active: bool) -> None:
        self._hunt_detection_active = bool(active)
        self._update_global_hotkey_state()
        self._refresh_tab_colors()
        self._update_ocr_watch_state()

    def _on_map_detection_status_changed(self, active: bool) -> None:
        self._map_detection_active = bool(active)
        self._update_global_hotkey_state()
        self._refresh_tab_colors()
        self._update_ocr_watch_state()

    def _refresh_tab_colors(self) -> None:
        tab_bar = self.tab_widget.tabBar()
        if not isinstance(tab_bar, ColoredTabBar):
            return

        owner = self._current_authority_owner
        map_index = self._find_tab_index('맵')
        hunt_index = self._find_tab_index('사냥')

        map_color = '#1E88E5' if self._map_detection_active else None
        hunt_color = '#D32F2F' if self._hunt_detection_active else None

        if owner == 'map' and self._map_detection_active:
            map_color = '#1cbb7f'
        elif owner == 'hunt' and self._hunt_detection_active:
            hunt_color = '#1cbb7f'

        if map_index is not None:
            self._set_tab_color('맵', map_color)
        if hunt_index is not None:
            self._set_tab_color('사냥', hunt_color)

    # ===== OCR Watch 관리 =====
    def _update_ocr_watch_state(self) -> None:
        any_active = bool(self._hunt_detection_active or self._map_detection_active)
        if any_active and self._data_manager is not None:
            self._ensure_ocr_watch_started()
        else:
            self._stop_ocr_watch()

    def _ensure_ocr_watch_started(self) -> None:
        if self._ocr_watch_thread is not None and self._ocr_watch_thread.isRunning():
            return

        def _get_active_profile() -> str:
            return 'default'

        def _get_profile_data(_: str) -> dict:
            dm = self._data_manager
            out: dict = {}
            try:
                cfg = dm.get_monster_nameplate_config() if dm else {}
                ocr_cfg = cfg.get('ocr', {}) if isinstance(cfg.get('ocr'), dict) else {}
                roi = ocr_cfg.get('roi', {}) if isinstance(ocr_cfg.get('roi'), dict) else {}
                parts = []
                if isinstance(roi, dict) and int(roi.get('width', 0)) > 0 and int(roi.get('height', 0)) > 0:
                    parts = [{
                        'left': int(roi.get('left', 0)),
                        'top': int(roi.get('top', 0)),
                        'width': int(roi.get('width', 0)),
                        'height': int(roi.get('height', 0)),
                    }]
                out = {
                    'interval_sec': float(ocr_cfg.get('interval_sec', 5.0) or 5.0),
                    'roi_parts': parts,
                    'telegram_enabled': bool(ocr_cfg.get('telegram_enabled', False)),
                    'keywords': list(ocr_cfg.get('keywords', [])) if isinstance(ocr_cfg.get('keywords'), list) else [],
                    'conf_threshold': ocr_cfg.get('conf_threshold', None),
                    'min_height_px': ocr_cfg.get('min_height_px', None),
                }
            except Exception:
                pass
            return out

        try:
            # 이전 스레드가 있었다면 정리
            if self._ocr_watch_thread is not None:
                try:
                    self._ocr_watch_thread.stop()
                except Exception:
                    pass
                try:
                    self._ocr_watch_thread.wait(500)
                except Exception:
                    pass
            self._ocr_watch_thread = OCRWatchThread(get_active_profile=_get_active_profile, get_profile_data=_get_profile_data)
            self._ocr_watch_thread.start()
        except Exception as exc:
            print(f"[Main] OCR 워커 시작 실패: {exc}")
            self._ocr_watch_thread = None

    def _stop_ocr_watch(self) -> None:
        thr = self._ocr_watch_thread
        self._ocr_watch_thread = None
        if thr is not None:
            try:
                thr.stop()
            except Exception:
                pass
            try:
                thr.wait(1500)
            except Exception:
                pass


if __name__ == '__main__':
    sys.excepthook = log_uncaught_exceptions # 전역 예외 처리기(훅) 설정
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
