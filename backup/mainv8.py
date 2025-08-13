# main.py
# 2025년 08月 08日 18:48 (KST)
# 작성자: Gemini
# 기능: 여러 기능 모듈을 탭 형태로 관리하는 메인 애플리케이션 셸
# 설명:
# - v1.1: QSettings를 사용하여 프로그램 종료 시 창의 위치와 크기를 저장하고,
#         재시작 시 복원하는 기능 추가.
# - QTabWidget을 사용하여 각 기능(.py)을 별도의 탭으로 표시합니다.
# - importlib를 사용하여 모듈을 동적으로 로드하고, 로드 실패 시 에러 탭을 표시합니다.
# - 각 탭은 QWidget을 상속받은 클래스로 구현되어야 합니다.

import sys
import importlib
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel
)
# ==================== v1.1 수정 시작 ====================
from PyQt6.QtCore import Qt, QSettings
# ==================== v1.1 수정 끝 ======================

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
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())
