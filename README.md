ProjectM - 통합 기술 상세 설명서 (v9.0.6 - 편집기 줌/패닝 및 동기화 강화 버전)
이 문서는 ProjectM 애플리케이션의 아키텍처, 주요 기능 모듈, 그리고 각 클래스의 역할 및 최근 업데이트 내역을 상세하게 설명합니다.
전체 시스템 아키텍처
이 애플리케이션은 모듈형 탭 기반 아키텍처를 채택하고 있습니다.
메인 셸 (main.py): QTabWidget을 사용하여 각 기능 모듈(Learning.py, map.py 등)을 동적으로 로드하는 껍데기(Shell) 역할을 합니다. 이를 통해 각 기능 탭은 독립적으로 개발 및 수정될 수 있으며, 한 탭에서 오류가 발생하더라도 다른 탭에 영향을 주지 않습니다.
기능 모듈 (탭): 각 .py 파일은 하나의 탭에 해당하는 완전한 기능을 구현합니다. 모든 탭은 QWidget을 상속받은 메인 클래스(예: LearningTab, MapTab)를 포함하며, 이 클래스가 해당 탭의 UI와 로직을 총괄합니다.
UI와 로직의 분리: 복잡한 탭(LearningTab)의 경우, UI를 담당하는 메인 클래스와 데이터 처리를 담당하는 백엔드 클래스(DataManager)를 분리하여 코드의 가독성과 유지보수성을 높였습니다.
비동기 처리 (QThread): 모델 훈련, 실시간 객체 탐지, 미니맵 분석 등 시간이 많이 소요되는 작업은 모두 별도의 QThread에서 실행됩니다. 이는 GUI의 "응답 없음" 상태를 방지하고 사용자 경험을 향상시키는 핵심적인 설계 원칙입니다. 스레드는 pyqtSignal을 사용하여 작업 진행 상황, 결과, 에러 등을 메인 GUI 스레드로 안전하게 전달합니다.
리소스 관리: main.py의 closeEvent는 프로그램 종료 시 각 탭에 정의된 cleanup_on_close 메서드를 호출하여, 실행 중인 모든 스레드를 안전하게 종료하고 설정을 저장하는 등 리소스를 정리하는 역할을 수행합니다.
향후 계획: map.py의 내비게이션 알고리즘을 기반으로, 라즈베리파이를 COM 포트를 통해 키보드처럼 연동할 예정입니다. PC에서는 이동 명령(조작키)를 생성하여 라즈베리파이로 전송하고, 라즈베리파이가 PC에 키 입력을 보내 캐릭터를 조작하도록 구현하여 탐지 위험을 감소시킬 것입니다.
Learning.py - 데이터 관리 및 AI 훈련/탐지 모듈
데이터셋 구축, YOLOv8 모델 훈련, 실시간 객체 탐지 기능을 통합 제공하는 애플리케이션의 핵심 모듈입니다. 사용자는 이 탭을 통해 이미지 캡처부터 라벨링, 훈련, 실시간 테스트까지 AI 모델 개발의 전체 파이프라인을 GUI 환경에서 수행할 수 있습니다.
YOLOv8: Ultralytics의 YOLOv8 모델을 사용하여 객체 분할(Segmentation) 모델을 훈련하고 추론합니다.
Segment Anything (SAM): Meta AI의 SAM 모델을 'AI 어시스트' 기능으로 활용하여, 사용자가 몇 번의 클릭만으로 객체의 마스크를 손쉽게 생성할 수 있도록 지원합니다.
데이터 중심 워크플로우: workspace/ 폴더를 중심으로 모든 데이터(이미지, 라벨, 모델)를 체계적으로 관리합니다.
Learning.py 클래스별 상세 분석:
LearningTab(QWidget): '학습' 탭의 모든 UI와 비즈니스 로직을 총괄하는 메인 클래스.
역할: 3단 레이아웃(클래스 목록, 이미지 목록, 훈련/탐지)을 구성하고, 모든 버튼과 위젯의 시그널-슬롯 연결을 관리합니다.
주요 상호작용: 사용자 입력(버튼 클릭 등)을 받아 DataManager에 데이터 처리를 요청합니다. 훈련, 탐지 등 무거운 작업을 TrainingThread, DetectionThread 등 별도 스레드로 위임합니다. PolygonAnnotationEditor, SAMAnnotationEditor 같은 편집 다이얼로그를 생성하고, 결과 데이터를 받아 DataManager를 통해 저장합니다. SAMManager를 통해 AI 어시스트 모델의 로딩을 관리합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
DataManager: 파일 시스템과의 모든 상호작용을 담당하는 백엔드 클래스.
역할: workspace/ 폴더 내의 모든 경로를 관리하며, 클래스, 이미지, 라벨, 모델, 프리셋에 대한 CRUD(생성, 읽기, 갱신, 삭제) 로직을 캡슐화합니다.
주요 메서드:
get_manifest() / save_manifest(): 클래스 구조와 이미지 목록을 담은 manifest.json을 관리.
rename_class(): 클래스 이름 변경 시, manifest.json 뿐만 아니라 모든 .txt 라벨 파일의 클래스 인덱스까지 자동으로 업데이트하여 데이터 정합성을 유지합니다.
rebuild_manifest_from_labels(): manifest.json이 손상되었을 때, 모든 라벨 파일을 스캔하여 데이터 목록을 복구하는 강력한 기능을 제공합니다.
create_yaml_file(): 훈련 시작 전, 현재 클래스 목록을 기반으로 YOLO 훈련에 필요한 data.yaml 파일을 동적으로 생성합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
TrainingThread(QThread): YOLOv8 모델 훈련을 백그라운드에서 수행.
역할: model.train()을 호출하여 훈련을 실행하고, progress 시그널로 로그를, finished 시그널로 결과를 GUI에 전달합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
ExportThread(QThread): 훈련된 .pt 모델을 TensorRT(.engine) 형식으로 최적화.
역할: 모델 최적화 작업을 백그라운드에서 처리합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
DetectionThread(QThread): 실시간 객체 탐지를 수행.
역할: 지정된 화면 영역을 mss로 계속 캡처하고, YOLO 모델로 추론한 뒤, 결과가 그려진 프레임을 frame_ready 시그널로 GUI에 전송합니다. 캐릭터와 몬스터의 신뢰도를 분리 적용하고, 캐릭터는 가장 신뢰도 높은 하나만 탐지하는 로직을 포함합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
SAMManager(QObject): SAM 모델의 다운로드 및 로딩을 관리.
역할: LearningTab의 init_sam에서 생성되어 별도 스레드로 이동됩니다. 모델 파일이 없을 경우 자동으로 다운로드하고, GPU를 사용하여 모델을 메모리에 로드합니다. 로딩이 완료되면 model_ready 시그널을 통해 SamPredictor 객체를 LearningTab에 전달합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
PolygonAnnotationEditor(QDialog) / SAMAnnotationEditor(QDialog): 각각 수동, AI 어시스트 라벨링을 위한 다이얼로그 창.
역할: 내부에 전용 캔버스(CanvasLabel 또는 SAMCanvasLabel)를 포함하며, 확대/축소, 클래스 선택, 단축키(C, D, Z, R) 처리 등 편집에 필요한 모든 UI와 로직을 제공합니다.
주요 상호작용: LearningTab의 data_manager로부터 전체 클래스 목록을 받아와 선택 UI를 구성하고, 저장 시 편집된 다각형 데이터를 반환합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
BaseCanvasLabel(QLabel): 두 캔버스의 공통 기능을 정의하는 부모 클래스.
역할: 줌/패닝, 기존 다각형 그리기, 마우스 오버 시 하이라이트, 다각형 삭제 등 공통 로직을 처리하여 코드 중복을 방지합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
CanvasLabel(BaseCanvasLabel): 수동 편집용 캔버스.
역할: 현재 사용자가 그리고 있는 다각형을 추가로 그리는 로직을 포함.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
SAMCanvasLabel(BaseCanvasLabel): AI 편집용 캔버스.
역할: SAM이 예측한 마스크와 사용자의 입력(긍정/부정 클릭)을 시각화.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
ClassTreeWidget(QTreeWidget): 클래스 목록을 위한 커스텀 위젯.
역할: 클래스-카테고리 간 드래그앤드롭을 지원하며, 계층 구조 규칙(예: 클래스를 최상위로 이동 불가)을 강제합니다. 드롭 완료 시 drop_completed 시그널을 발생시켜 manifest.json을 업데이트하도록 합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
ScreenSnipper, DetectionPopup, EditModeDialog, MultiCaptureDialog: 각각 화면 영역 지정, 탐지 뷰 팝업, 편집 모드 선택, 다중 캡처 선택을 위한 유틸리티 다이얼로그.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
map.py - 전체 미니맵 편집 및 내비게이션 시스템
v9.0.0 대규모 시스템 개편을 기점으로, 기존의 웨이포인트 기반 위치 추정 방식에서 벗어나 전체 맵 데이터를 직접 활용하는 '카메라 뷰' 방식으로 시스템을 전면 개편했습니다. 이를 통해 시스템의 복잡도를 낮추고 정확성과 직관성을 크게 향상시켰습니다.
핵심 개념 변경 사항:
전체 맵 기반 렌더링: 더 이상 개별 웨이포인트의 미니맵 조각을 사용하지 않습니다. 대신, 프로필 로드 시 _generate_full_map_pixmap을 통해 모든 웨이포인트 배경과 지형/오브젝트 정보를 합성한 단 하나의 거대한 '전체 맵' 이미지를 미리 생성합니다.
탐지 로직 단순화: AnchorDetectionThread의 역할이 대폭 축소되었습니다. 이제 이 스레드는 복잡한 위치 보정이나 경로 안내 없이, 오직 실시간 미니맵 화면에서 '핵심 지형'과 '플레이어'를 탐지하고 그 로컬 좌표를 MapTab에 전달하는 역할만 수행합니다.
카메라 뷰 (Camera View): RealtimeMinimapView라는 새로운 위젯이 실시간 뷰를 전담합니다. 이 위젯은 MapTab으로부터 플레이어의 전역 좌표를 전달받아, 미리 생성된 '전체 맵' 이미지 위에서 해당 좌표를 중심으로 하는 영역을 잘라내어 보여줍니다. 이는 마치 거대한 지도 위를 카메라가 따라다니는 것과 같은 효과를 냅니다.
데이터 동기화 강화 (v9.0.6): 데이터가 변경(추가, 수정, 삭제)될 때마다 save_profile_data 함수가 호출됩니다. 이 함수는 파일 저장 직후, _update_map_data_and_views라는 중앙 관리 함수를 호출하여 전역 좌표계 재계산과 전체 맵 이미지 재생성을 자동으로 수행합니다. 이를 통해 '핵심 지형 관리자', '웨이포인트 편집기', '실시간 뷰' 간의 데이터 불일치 문제를 해결하고 항상 최신 상태를 유지합니다.
map.py 클래스별 상세 분석:
CroppingLabel(QLabel): FeatureCropDialog에서 영역을 시각적으로 표시하는 데 사용되는 간단한 QLabel 서브클래스.
역할: FeatureCropDialog의 배경 이미지 위에 사용자가 드래그하는 사각형 영역을 실시간으로 그려줍니다.
최근 변경 사항: FeatureCropDialog가 QGraphicsView 기반으로 변경되면서, 이 클래스는 현재 사용되지 않습니다. (다만 코드 파일에는 여전히 존재합니다.)
FeatureCropDialog(QDialog): 새로운 핵심 지형을 추가할 때, 미니맵 이미지에서 특정 영역을 잘라낼 수 있도록 돕는 다이얼로그.
역할: 캡처된 미니맵 이미지 위에서 사용자가 마우스 드래그로 핵심 지형 영역을 지정하고, 해당 영역의 이미지 데이터를 반환합니다.
주요 상호작용: MapTab에서 호출되며, 선택된 영역의 QRect 객체를 반환합니다.
최근 변경 사항 (v9.0.5):
기존 QLabel 기반에서 QGraphicsView 기반(ZoomableView)으로 전환되어 휠 확대/축소 및 휠 클릭 패닝 기능이 추가되었습니다.
다이얼로그가 화면에 완전히 표시된 후 fitInView를 호출하여 초기 배율이 최적화되었습니다 (이미지가 너무 작게 보이던 문제 해결).
영역 지정 시 커서가 십자(+) 모양으로 고정됩니다.
KeyFeatureManagerDialog(QDialog): 등록된 핵심 지형을 관리(추가, 이름 변경, 삭제)하고, 각 지형이 어떤 웨이포인트에서 사용되고 있는지 보여주는 다이얼로그.
역할: 핵심 지형 데이터(self.key_features)의 CRUD 작업을 수행하고, 관련 웨이포인트와의 연결 상태를 시각화합니다.
주요 상호작용: MapTab의 self.key_features와 self.route_profiles를 참조하여 데이터를 표시하고 수정합니다. parent_map_tab.save_profile_data()를 호출하여 변경사항을 저장합니다.
최근 변경 사항 (v9.0.6):
'전체 웨이포인트 갱신' (on_update_all_clicked) 기능이 MapTab.update_all_waypoints_with_features를 호출하도록 변경되어, 웨이포인트와 핵심 지형 간의 연결 정보 불일치 문제를 해결했습니다.
지형 삭제 시 MapTab의 원본 웨이포인트 데이터에서 해당 지형 링크가 즉시 제거되고 저장됩니다.
AdvancedWaypointCanvas(QLabel): AdvancedWaypointEditorDialog에서 웨이포인트의 목표 지점 및 관련 핵심 지형을 그리는 데 사용되던 캔버스.
역할: 웨이포인트 편집 시 배경 미니맵 이미지 위에 목표 지점(초록색)과 탐지된 핵심 지형(파란색)을 표시하고, 사용자가 새로운 핵심 지형(주황색)을 그리거나 기존 지형을 삭제할 수 있도록 마우스 이벤트를 처리했습니다.
최근 변경 사항: AdvancedWaypointEditorDialog가 QGraphicsView 기반으로 완전히 재구현되면서, 이 클래스는 현재 사용되지 않습니다. (다만 코드 파일에는 여전히 존재합니다.)
AdvancedWaypointEditorDialog(QDialog): 개별 웨이포인트를 상세하게 편집하는 다이얼로그. 목표 지점 및 연결된 핵심 지형을 지정/수정할 수 있습니다.
역할: 특정 웨이포인트의 이름, 미니맵 이미지, 목표 지점, 그리고 웨이포인트와 관련된 핵심 지형(이미 탐지된 것, 새로 추가할 것, 삭제할 것)을 시각적으로 편집할 수 있도록 합니다.
주요 상호작용: MapTab에서 호출되며, 수정된 웨이포인트 데이터와 핵심 지형 변경 정보를 MapTab으로 전달합니다. parent_map_tab.key_features를 참조하여 편집합니다.
최근 변경 사항 (v9.0.5):
기존 QLabel 기반에서 QGraphicsView 기반(ZoomableView)으로 전환되어 휠 확대/축소 및 휠 클릭 패닝 기능이 추가되었습니다.
다이얼로그가 화면에 완전히 표시된 후 fitInView를 호출하여 초기 배율이 최적화되었습니다.
편집 모드(목표 지점, 핵심 지형)에 따라 커서가 십자(+) 모양으로 유지됩니다.
CustomGraphicsView(QGraphicsView): FullMinimapEditorDialog에서 사용되는 커스텀 QGraphicsView.
역할: 전체 맵 편집기에서 확대/축소, 패닝, 마우스 이벤트 전달 기능을 제공합니다.
주요 상호작용: FullMinimapEditorDialog의 on_scene_mouse_press, on_scene_mouse_move 등과 연결되어 지형 그리기/삭제 로직을 수행합니다.
최근 변경 사항: map.py의 CustomGraphicsView 자체에는 v7.8.1 이후 직접적인 변경 사항이 없습니다.
FullMinimapEditorDialog(QDialog): 전체 맵에 지형선(terrain_lines)과 층 이동 오브젝트(transition_objects)를 직접 그리고 편집하는 다이얼로그.
역할: 모든 웨이포인트의 미니맵들을 합성한 전체 맵 위에서, 플레이어가 이동 가능한 지형과 층 이동 오브젝트의 위치 및 형태를 정의합니다.
주요 상호작용: MapTab으로부터 모든 맵 데이터(key_features, route_profiles, geometry_data, global_positions)를 받아 맵을 렌더링하고, 변경된 geometry_data를 MapTab으로 반환하여 저장하도록 합니다. MapTab의 실시간 플레이어 위치(global_pos_updated 시그널)를 받아 Y/X축 고정선 위치를 업데이트합니다.
최근 변경 사항: map.py의 FullMinimapEditorDialog 자체에는 직접적인 변경 사항이 없습니다.
RealtimeMinimapView(QLabel): (신규 클래스, v9.0.0 도입) 전체 맵을 기반으로 플레이어 시점의 '카메라 뷰'를 실시간으로 렌더링하는 커스텀 위젯.
역할: MapTab에서 계산된 플레이어의 전역 좌표를 중심으로 전체 맵의 일부를 잘라내어 표시하고, 그 위에 플레이어, 다른 유저, 핵심 지형, 웨이포인트, 지형선, 오브젝트 등을 동적으로 오버레이하여 보여줍니다. 마우스 휠 줌 및 드래그 패닝을 지원합니다.
주요 상호작용: MapTab으로부터 camera_center, active_features, my_players, other_players 등 렌더링에 필요한 최신 데이터를 update_view_data 메서드를 통해 전달받아 화면을 갱신합니다.
최근 변경 사항 (v9.0.1+):
(v9.0.1) 핵심 지형 렌더링 개선: 감지된 지형은 파란색 실선, 미감지 지형은 흰색 점선 테두리로 표시하며, 내부를 채우지 않도록 변경되었습니다. 핵심 지형 이름은 사각형 중앙에 표시됩니다.
(v9.0.1) 웨이포인트 렌더링 개선: 웨이포인트 이름 대신 경로 순서(숫자)가 사각형 중앙에 표시됩니다.
(v9.0.2) 탐지 정확도 표시: 감지된 핵심 지형 사각형의 바깥쪽 위(수평 중앙)에 실시간 탐지 정확도(소수점 둘째 자리까지, 노란색, 7pt, 일반 폰트)가 표시됩니다.
(v9.0.4) 카메라 자동 추적 제어: MapTab의 '캐릭터 중심' 체크박스 상태에 따라 카메라가 플레이어를 자동 추적할지(self.camera_center_global 업데이트) 아니면 사용자가 드래그한 위치에 머무를지 결정하도록 로직이 변경되었습니다.
AnchorDetectionThread(QThread): 지정된 미니맵 영역을 계속 스캔하여, 등록된 핵심 지형과 플레이어 아이콘의 로컬 좌표를 탐지하고 메인 스레드로 전달하는 역할만 수행하는 스레드.
역할: 스크린샷 캡처, HSV 색상 마스킹을 통한 플레이어 아이콘 탐지, 템플릿 매칭을 통한 핵심 지형 탐지를 백그라운드에서 수행합니다. 탐지된 객체의 id, local_pos, conf 정보를 detection_ready 시그널을 통해 MapTab으로 전달합니다.
최근 변경 사항: map.py의 AnchorDetectionThread 자체에는 직접적인 변경 사항이 없습니다.
MapTab(QWidget): '맵' 탭의 모든 UI와 핵심 로직을 총괄하는 메인 컨트롤러 클래스.
역할: 맵 프로필 로드/저장, 미니맵 영역 설정, 웨이포인트/경로 프로필/핵심 지형 관리, 전체 맵 데이터(지형선, 오브젝트) 편집기 실행, 실시간 탐지 제어 등 맵 시스템 전반을 관리합니다. _calculate_global_positions로 전역 좌표계를 계산하고 _generate_full_map_pixmap으로 전체 맵 이미지를 생성하여 메모리에 보관합니다.
주요 상호작용: AnchorDetectionThread로부터 탐지 결과를 받아 플레이어의 전역 좌표를 계산하고 RealtimeMinimapView에 렌더링을 지시합니다. KeyFeatureManagerDialog, AdvancedWaypointEditorDialog, FullMinimapEditorDialog 등 모든 하위 다이얼로그와 데이터를 주고받으며, save_profile_data를 통해 데이터 무결성을 보장합니다. global_pos_updated 시그널로 FullMinimapEditorDialog에 플레이어 위치를 전달합니다.
최근 변경 사항:
(v9.0.3) global_pos_updated 시그널의 타입이 (float, float)에서 QPointF로 변경되어 X, Y 좌표 전달의 정확성과 안정성이 향상되었습니다.
(v9.0.3) on_detection_ready 메서드에서 플레이어의 Y축 위치 계산 시 player_rect.bottom() 대신 float(player_rect.y() + player_rect.height())를 사용하여 정확한 바닥 좌표를 얻도록 수정되었고, PLAYER_Y_OFFSET 상수를 통해 미세 Y 좌표 보정 기능이 추가되었습니다.
(v9.0.4) initUI에 '실시간 미니맵 뷰' 라벨 옆에 **'캐릭터 중심' QCheckBox**가 추가되었습니다.
(v9.0.4) on_detection_ready 메서드에서 이 체크박스의 상태에 따라 RealtimeMinimapView의 카메라가 플레이어를 자동 추적할지 여부를 제어하도록 로직이 변경되었습니다.
(v9.0.6) update_all_waypoints_with_features 메서드가 self.route_profiles의 원본 데이터를 직접 수정하도록 변경되어, 핵심 지형과 웨이포인트 간의 연결 정보 동기화 문제(사용처 불일치 등)가 완전히 해결되었습니다.
ZoomableView(QGraphicsView): (v9.0.5 도입) QGraphicsView를 상속받아 휠 확대/축소 및 휠 클릭 패닝 기능을 제공하는 재사용 가능한 뷰 클래스.
역할: FeatureCropDialog와 AdvancedWaypointEditorDialog의 핵심 뷰로 사용되어, 이미지 편집 시 사용자에게 유연한 뷰 제어 기능을 제공합니다. set_drawing_mode 메서드를 통해 커서 모양(십자 또는 손바닥)과 드래그 모드를 전환할 수 있습니다.
주요 상호작용: mousePressEvent, mouseMoveEvent, mouseReleaseEvent를 오버라이딩하여 휠 클릭 이벤트를 처리합니다.
최근 변경 사항: ZoomableView의 도입 자체가 최근 변경 사항의 핵심입니다.
main.py - 애플리케이션 셸 및 로더
애플리케이션의 진입점(Entry Point)으로, 전체 프로그램의 뼈대를 구성하고 각 기능 모듈을 탭으로 통합하는 역할을 합니다.
MainWindow(QMainWindow): 애플리케이션의 메인 윈도우.
역할: QTabWidget을 중앙 위젯으로 설정하고, load_tabs 메서드를 통해 지정된 모듈들을 순차적으로 로드합니다.
주요 기능:
동적 모듈 로딩: importlib를 사용하여 모듈 이름(문자열)으로 실제 모듈을 임포트합니다. 이 덕분에 설정 파일 변경만으로 새로운 탭을 쉽게 추가하거나 제거할 수 있는 확장성 있는 구조를 가집니다.
오류 처리: try-except 구문을 사용하여 특정 탭 로딩에 실패하더라도 프로그램이 중단되지 않고, 대신 사용자에게 원인을 알려주는 '오류 탭'을 표시합니다.
상태 저장 (QSettings): 프로그램 종료 시 closeEvent에서 현재 창의 위치와 크기를 저장하고, 재시작 시 이를 복원하여 사용자 편의성을 높입니다.
자원 해제: closeEvent에서 각 탭 위젯의 cleanup_on_close 메서드를 순차적으로 호출하여, 모든 백그라운드 스레드가 안전하게 종료되도록 보장합니다.
최근 변경 사항: map.py와 관련된 직접적인 변경 사항은 없습니다.
향후 개발 계획 (변동 가능성 있음): 층간 내비게이션 시스템
현재까지 구축된 '전체 미니맵 편집기'의 지형 데이터를 활용하여, 복층 구조의 맵에서 층간 이동을 포함한 최단 경로를 탐색하는 고차원 내비게이션 시스템을 구현합니다.
목표: 사용자가 맵의 어느 지점이든 목표로 설정하면, 현재 위치에서 목표까지 지형선을 따라 이동하고, 필요한 경우 층 이동 오브젝트(사다리, 포탈)를 사용하여 층을 바꾸는 전체 경로를 생성하고 안내합니다.
핵심 개념:
층 (Floor) 관리: 사용자가 "1층", "2층" 등 층 정보를 생성하고 관리하는 기능.
지형선에 층 정보 할당: 사용자가 편집기에서 특정 지형선을 선택하고, 해당 지형선이 몇 층에 속하는지 지정하는 기능. (기본값은 1층)
층 이동 오브젝트 연결: 사용자가 층 이동 오브젝트(사다리 등)를 선택하고, 이 오브젝트가 어떤 지형선(시작 층)에서 시작하여 어떤 지형선(도착 층)으로 연결되는지 명시적으로 지정하는 기능. 이는 양방향 이동을 기본으로 합니다.
구현 계획:
데이터 구조 확장: map_geometry.json을 수정합니다.
terrain_lines의 각 객체에 "floor": 1 과 같은 층 정보 필드를 추가합니다.
transition_objects의 각 객체에 "start_line_id": "...", "end_line_id": "..." 와 같이 연결된 두 지형선의 ID를 저장하는 필드를 추가합니다.
편집기 UI/UX 추가: FullMinimapEditorDialog에 다음 기능을 추가합니다.
층 관리 패널: 층을 추가/삭제/이름 변경할 수 있는 UI.
지형선 속성 편집: 지형선을 선택하고 드롭다운 메뉴 등을 통해 생성된 층 목록 중 하나를 할당하는 기능.
오브젝트 연결 도구: 층 이동 오브젝트를 선택한 후, 시작 지형선과 도착 지형선을 순서대로 클릭하여 연결 관계를 설정하는 기능.
내비게이션 알고리즘 고도화:
경로 탐색 시, 맵 전체를 하나의 거대한 **그래프(Graph)**로 간주합니다.
노드(Node): 모든 지형선의 각 꼭짓점, 층 이동 오브젝트의 시작/끝점.
엣지(Edge):
같은 지형선 위의 인접한 꼭짓점들을 잇는 선분 (가중치: 거리).
층 이동 오브젝트 자체 (가중치: 이동 시간 또는 거리).
층 이동 오브젝트의 끝점과 연결된 지형선 위의 가장 가까운 점을 잇는 가상의 연결선.
A* (A-Star) 알고리즘 등을 사용하여 이 그래프 상에서 현재 위치에서 목표 지점까지의 최단 경로를 계산합니다. 계산된 경로는 [지형선 이동 -> 오브젝트 이용 -> 다른 지형선 이동] 과 같은 일련의 행동 계획으로 출력됩니다.