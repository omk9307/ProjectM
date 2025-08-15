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
import importlib
import traceback
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel
)
from datetime import datetime
from PyQt6.QtCore import Qt, QSettings

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
    
class MainWindow(QMainWindow):
    """
    메인 윈도우 클래스.
    QTabWidget을 중앙 위젯으로 사용하여 여러 기능 탭을 관리합니다.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Project M - 통합 대시보드')
        
        # ==================== v1.1 수정 시작 ====================
        # 설정 파일 로드 및 창 위치/크기 복원
        # QSettings("회사/조직 이름", "프로그램 이름")
        self.settings = QSettings("Gemini Inc.", "Maple AI Trainer")
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            # 기본 크기 설정
            self.setGeometry(100, 100, 1280, 800)
        # ==================== v1.1 수정 끝 ======================

        # 메인 탭 위젯 생성
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setMovable(True)

        self.setCentralWidget(self.tab_widget)

        # 정의된 탭들을 로드합니다.
        self.load_tabs()

    def load_tabs(self):
        """
        미리 정의된 탭 모듈 목록을 순서대로 로드합니다.
        """
        tabs_to_load = [
            ('Learning', 'LearningTab', '학습'),
            ('map', 'MapTab', '맵')
        ]

        for module_name, class_name, tab_title in tabs_to_load:
            self.load_tab(module_name, class_name, tab_title)

    def load_tab(self, module_name, class_name, tab_title):
        """
        주어진 정보를 바탕으로 모듈을 동적으로 임포트하고 탭을 추가합니다.
        """
        try:
            module = importlib.import_module(module_name)
            TabClass = getattr(module, class_name)
            tab_instance = TabClass()
            self.tab_widget.addTab(tab_instance, tab_title)
            print(f"성공: '{tab_title}' 탭을 로드했습니다.")

        except ImportError as e:
            print(f"오류: 모듈 '{module_name}'을(를) 찾을 수 없습니다. {e}")
            self.add_error_tab(tab_title, f"모듈 파일을 찾을 수 없습니다:\n{module_name}.py")
        except AttributeError as e:
            print(f"오류: 모듈 '{module_name}'에서 클래스 '{class_name}'을(를) 찾을 수 없습니다. {e}")
            self.add_error_tab(tab_title, f"클래스를 찾을 수 없습니다:\n{class_name}")
        except Exception as e:
            print(f"오류: '{tab_title}' 탭 로드 중 예외 발생: {e}")
            self.add_error_tab(tab_title, f"알 수 없는 오류가 발생했습니다:\n{e}")

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

    # ==================== v1.1 수정 시작 ====================
    def closeEvent(self, event):
        """
        메인 윈도우가 닫힐 때 각 탭의 정리(cleanup) 함수를 호출하고,
        창의 위치와 크기를 저장합니다.
        """
        # 창 위치/크기 저장
        self.settings.setValue("geometry", self.saveGeometry())
        
        # 각 탭의 리소스 정리
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if hasattr(widget, 'cleanup_on_close') and callable(getattr(widget, 'cleanup_on_close')):
                print(f"'{self.tab_widget.tabText(i)}' 탭의 리소스를 정리합니다...")
                widget.cleanup_on_close()
        
        event.accept()
    # ==================== v1.1 수정 끝 ======================


if __name__ == '__main__':
    sys.excepthook = log_uncaught_exceptions # 전역 예외 처리기(훅) 설정
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
