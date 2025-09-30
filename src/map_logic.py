"""맵 탭 실행에 필요한 비-UI 로직 구성 요소."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import traceback

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QSize, QThread, pyqtSignal

from capture_manager import get_capture_manager

try:
    from .map import MapConfig
except ImportError:
    from map import MapConfig  # type: ignore

try:
    from sklearn.ensemble import RandomForestClassifier
    import joblib
except ImportError:
    raise RuntimeError(
        "머신러닝 기반 동작 인식을 위해 scikit-learn과 joblib 라이브러리가 필요합니다.\n"
        "pip install scikit-learn joblib"
    )


class MinimapCaptureThread(QThread):
    """지정된 영역을 목표 FPS에 맞춰 캡처하고 최신 프레임을 공유하는 스레드."""

    frame_ready = pyqtSignal(object)

    def __init__(self, minimap_region, target_fps=None):
        super().__init__()
        self.minimap_region = minimap_region
        self.target_fps = target_fps or MapConfig["target_fps"]
        self.is_running = False
        self.latest_frame = None
        self._lock = threading.Lock()
        self._manager = get_capture_manager()
        self._consumer_name = f"minimap:{id(self)}"

    def run(self):
        if not self.minimap_region:
            return

        self.is_running = True
        interval = 1.0 / max(1, self.target_fps)
        self._manager.register_region(self._consumer_name, self.minimap_region)
        try:
            while self.is_running:
                start_t = time.time()
                try:
                    frame_bgr = self._manager.get_frame(self._consumer_name, timeout=1.0)
                    if frame_bgr is None:
                        continue

                    with self._lock:
                        self.latest_frame = frame_bgr

                    try:
                        self.frame_ready.emit(frame_bgr)
                    except Exception:
                        pass

                except Exception as e:
                    print(f"[MinimapCaptureThread] 캡처 오류: {e}")
                    traceback.print_exc()

                elapsed = time.time() - start_t
                sleep_time = interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            self._manager.unregister_region(self._consumer_name)

    def stop(self):
        self.is_running = False
        try:
            self.quit()
            self.wait(2000)
        except Exception as e:
            print(f"[MinimapCaptureThread] 정지 대기 실패: {e}")

    def update_region(self, region: dict) -> None:
        if not isinstance(region, dict):
            return
        self.minimap_region = region
        if self.isRunning():
            try:
                self._manager.update_region(self._consumer_name, region)
            except KeyError:
                # 등록이 아직 안 된 상태라면 다음 run 루프에서 등록됨
                pass


def safe_read_latest_frame(capture_thread):
    """캡처 스레드로부터 최신 프레임을 안전하게 복사해 반환합니다."""

    if not capture_thread:
        return None
    try:
        with capture_thread._lock:
            src = capture_thread.latest_frame
            if src is None:
                return None
            return src.copy()
    except Exception:
        return None


class AnchorDetectionThread(QThread):
    """등록된 핵심 지형 위치를 탐지하는 스레드."""

    detection_ready = pyqtSignal(object, list, list, list)
    status_updated = pyqtSignal(str, str)
    perf_sampled = pyqtSignal(dict)

    def __init__(self, all_key_features, capture_thread=None, parent_tab=None):
        super().__init__()
        self.capture_thread = capture_thread
        self.parent_tab = parent_tab
        self.all_key_features = all_key_features or {}
        self.is_running = False
        self.feature_templates = {}
        self._downscale = MapConfig["downscale"]
        self._frame_index = 0

        for fid, fdata in self.all_key_features.items():
            try:
                img_data = base64.b64decode(fdata['image_base64'])
                np_arr = np.frombuffer(img_data, np.uint8)
                template = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if template is None:
                    continue

                tpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                tpl_small = cv2.resize(tpl_gray, (0, 0), fx=self._downscale, fy=self._downscale, interpolation=cv2.INTER_AREA)

                self.feature_templates[fid] = {
                    "template_gray_small": tpl_small,
                    "threshold": fdata.get('threshold', MapConfig["detection_threshold_default"]),
                    "size": QSize(template.shape[1], template.shape[0]),
                }
            except Exception as e:
                print(f"[AnchorDetectionThread] 템플릿 전처리 실패 ({fid}): {e}")
                traceback.print_exc()

        self.last_positions = {k: None for k in self.feature_templates.keys()}

    def run(self):
        self.is_running = True
        while self.is_running:
            loop_start = time.perf_counter()
            perf = {
                'timestamp': time.time(),
                'loop_start_monotonic': loop_start,
                'frame_index': self._frame_index,
                'downscale': float(self._downscale),
                'template_count': len(self.feature_templates),
            }
            self._frame_index += 1
            perf_emitted = False
            try:
                capture_start = time.perf_counter()
                frame_bgr = safe_read_latest_frame(self.capture_thread)
                perf['capture_ms'] = (time.perf_counter() - capture_start) * 1000.0

                if frame_bgr is None:
                    perf['frame_status'] = 'no_frame'
                    perf['sleep_ms'] = 5.0
                    perf['loop_total_ms'] = (time.perf_counter() - loop_start) * 1000.0
                    try:
                        self.perf_sampled.emit(perf)
                        perf_emitted = True
                    except Exception:
                        pass
                    time.sleep(0.005)
                    continue

                perf['frame_status'] = 'ok'
                perf['frame_width'] = int(frame_bgr.shape[1])
                perf['frame_height'] = int(frame_bgr.shape[0])

                my_player_rects = []
                other_player_rects = []

                player_icon_start = time.perf_counter()
                if self.parent_tab:
                    my_player_rects = self.parent_tab.find_player_icon(frame_bgr)
                perf['player_icon_ms'] = (time.perf_counter() - player_icon_start) * 1000.0
                perf['player_icon_count'] = len(my_player_rects)

                other_icon_start = time.perf_counter()
                if self.parent_tab:
                    other_player_rects = self.parent_tab.find_other_player_icons(frame_bgr)
                perf['other_player_icon_ms'] = (time.perf_counter() - other_icon_start) * 1000.0
                perf['other_player_icon_count'] = len(other_player_rects)

                preprocess_start = time.perf_counter()
                frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                frame_gray_small = cv2.resize(
                    frame_gray,
                    (0, 0),
                    fx=self._downscale,
                    fy=self._downscale,
                    interpolation=cv2.INTER_AREA,
                )
                perf['preprocess_ms'] = (time.perf_counter() - preprocess_start) * 1000.0

                all_detected_features = []
                feature_start = time.perf_counter()
                for fid, tpl_data in self.feature_templates.items():
                    tpl_small = tpl_data["template_gray_small"]
                    t_h, t_w = tpl_small.shape
                    search_result = None

                    last_pos = self.last_positions.get(fid)
                    if last_pos is not None:
                        lx = int(last_pos.x() * self._downscale)
                        ly = int(last_pos.y() * self._downscale)
                        radius = max(int(max(t_w, t_h) * 1.5), 30)
                        x1, y1 = max(0, lx - radius), max(0, ly - radius)
                        x2, y2 = min(frame_gray_small.shape[1], lx + radius), min(frame_gray_small.shape[0], ly + radius)
                        roi = frame_gray_small[y1:y2, x1:x2]

                        if roi.shape[0] >= t_h and roi.shape[1] >= t_w:
                            res = cv2.matchTemplate(roi, tpl_small, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, max_loc = cv2.minMaxLoc(res)
                            if max_val >= tpl_data["threshold"]:
                                found_x = (x1 + max_loc[0]) / self._downscale
                                found_y = (y1 + max_loc[1]) / self._downscale
                                search_result = {
                                    'id': fid,
                                    'local_pos': QPointF(found_x, found_y),
                                    'conf': max_val,
                                    'size': tpl_data['size'],
                                }

                    if search_result is None:
                        res = cv2.matchTemplate(frame_gray_small, tpl_small, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        if max_val >= tpl_data["threshold"]:
                            found_x = max_loc[0] / self._downscale
                            found_y = max_loc[1] / self._downscale
                            search_result = {
                                'id': fid,
                                'local_pos': QPointF(found_x, found_y),
                                'conf': max_val,
                                'size': tpl_data['size'],
                            }

                    if search_result:
                        all_detected_features.append(search_result)
                        self.last_positions[fid] = search_result['local_pos']

                perf['feature_match_ms'] = (time.perf_counter() - feature_start) * 1000.0
                perf['features_detected'] = len(all_detected_features)

                dispatch_t0 = time.perf_counter()
                perf['signal_dispatch_t0'] = dispatch_t0
                self.detection_ready.emit(frame_bgr, all_detected_features, my_player_rects, other_player_rects)
                perf['emit_ms'] = (time.perf_counter() - dispatch_t0) * 1000.0

                loop_time_ms = (time.perf_counter() - loop_start) * 1000.0
                perf['loop_total_ms'] = loop_time_ms
                perf['sleep_ms'] = 0.0

                if loop_time_ms > MapConfig["loop_time_fallback_ms"]:
                    old_scale = self._downscale
                    self._downscale = max(0.3, old_scale * 0.95)
                    MapConfig["downscale"] = self._downscale
                    perf['downscale_adjusted'] = float(self._downscale)
                    print(
                        f"[AnchorDetectionThread] 느린 루프 감지 ({loop_time_ms:.1f}ms), "
                        f"다운스케일 조정: {old_scale:.2f} -> {self._downscale:.2f}"
                    )

            except Exception as e:
                perf['frame_status'] = 'error'
                perf['error'] = str(e)
                perf['loop_total_ms'] = (time.perf_counter() - loop_start) * 1000.0
                print(f"[AnchorDetectionThread] 예기치 않은 오류: {e}")
                traceback.print_exc()
                time.sleep(0.02)
            finally:
                perf.setdefault('frame_status', 'unknown')
                if 'loop_total_ms' not in perf:
                    perf['loop_total_ms'] = (time.perf_counter() - loop_start) * 1000.0
                perf.setdefault('sleep_ms', 0.0)
                perf.setdefault('loop_start_monotonic', loop_start)
                perf.setdefault('signal_dispatch_t0', perf.get('loop_start_monotonic', loop_start))
                perf.setdefault('capture_ms', 0.0)
                perf.setdefault('player_icon_ms', 0.0)
                perf.setdefault('other_player_icon_ms', 0.0)
                perf.setdefault('preprocess_ms', 0.0)
                perf.setdefault('feature_match_ms', 0.0)
                perf.setdefault('emit_ms', 0.0)
                perf.setdefault('features_detected', 0)
                perf.setdefault('player_icon_count', 0)
                perf.setdefault('other_player_icon_count', 0)
                perf.setdefault('frame_width', 0)
                perf.setdefault('frame_height', 0)
                perf.setdefault('error', '')
                perf.setdefault('downscale_adjusted', None)
                if not perf_emitted:
                    try:
                        self.perf_sampled.emit(perf)
                    except Exception:
                        pass

    def stop(self):
        self.is_running = False
        try:
            self.quit()
            self.wait(2000)
        except Exception as e:
            print(f"[AnchorDetectionThread] 정지 대기 실패: {e}")


class ActionTrainingThread(QThread):
    """수집된 동작 데이터를 학습하는 스레드."""

    progress_updated = pyqtSignal(str, int)
    training_finished = pyqtSignal(bool, str)

    def __init__(self, model_dir_path, parent_tab):
        super().__init__()
        self.model_dir_path = model_dir_path
        self.parent_map_tab = parent_tab
        self.is_running = True

    def run(self):
        try:
            data_dir = os.path.join(self.model_dir_path, 'action_data')
            model_path = os.path.join(self.model_dir_path, 'action_model.joblib')

            if not os.path.exists(data_dir):
                self.training_finished.emit(False, "학습 데이터가 없습니다. 먼저 데이터를 수집해주세요.")
                return

            self.progress_updated.emit("데이터 로딩 중...", 10)

            X, y = [], []
            files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
            for i, filename in enumerate(files):
                if not self.is_running:
                    self.training_finished.emit(False, "학습이 사용자에 의해 취소되었습니다.")
                    return

                filepath = os.path.join(data_dir, filename)
                with open(filepath, 'r') as f:
                    data = json.load(f)

                sequence = data.get("sequence", [])
                action = data.get("action")

                if len(sequence) > 5 and action:
                    trimmed_sequence = self.parent_map_tab._trim_sequence_noise(
                        sequence,
                        self.parent_map_tab.cfg_move_deadzone,
                    )

                    if len(trimmed_sequence) >= 5:
                        features = self.parent_map_tab._extract_features_from_sequence(trimmed_sequence)
                        X.append(features)
                        y.append(action)

                self.progress_updated.emit(
                    f"데이터 처리 중... ({i+1}/{len(files)})",
                    10 + int(60 * (i + 1) / len(files)) if files else 70,
                )

            if len(set(y)) < 2:
                self.training_finished.emit(
                    False,
                    f"학습을 위해 최소 2가지 종류의 동작 데이터가 필요합니다. (현재: {len(set(y))}종류)",
                )
                return

            self.progress_updated.emit("모델 학습 중...", 80)

            X = np.array(X)
            y = np.array(y)

            model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
            model.fit(X, y)

            self.progress_updated.emit("모델 저장 중...", 95)
            joblib.dump(model, model_path)

            self.training_finished.emit(
                True,
                f"모델 학습이 완료되었습니다.\n총 {len(X)}개의 정제된 데이터로 학습했습니다.",
            )

        except Exception as e:
            self.training_finished.emit(False, f"학습 중 오류가 발생했습니다:\n{e}")

    def stop(self):
        self.is_running = False


__all__ = [
    "MinimapCaptureThread",
    "safe_read_latest_frame",
    "AnchorDetectionThread",
    "ActionTrainingThread",
]
