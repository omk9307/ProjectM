"""닉네임 기반 캐릭터 탐지를 위한 간단한 템플릿 매칭 도우미."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np
import time


@dataclass
class NicknameTemplate:
    template_id: str
    image: np.ndarray  # grayscale image
    width: int
    height: int


class NicknameDetector:
    """닉네임 템플릿을 이용해 캐릭터 위치를 추정한다."""

    WIDTH_SCALE = 1.0
    HEIGHT_SCALE = 2.2

    DEFAULT_MARGIN_X = 210.0
    DEFAULT_MARGIN_TOP = 100.0
    DEFAULT_MARGIN_BOTTOM = 100.0

    def __init__(
        self,
        target_text: str,
        match_threshold: float,
        offset_x: float,
        offset_y: float,
        search_margin_x: float = DEFAULT_MARGIN_X,
        search_margin_top: float = DEFAULT_MARGIN_TOP,
        search_margin_bottom: float = DEFAULT_MARGIN_BOTTOM,
        full_scan_delay_sec: float = 0.0,
    ) -> None:
        self.target_text = target_text
        self.match_threshold = max(0.1, min(0.99, float(match_threshold)))
        self.offset_x = float(offset_x)
        self.offset_y = float(offset_y)
        self.search_margin_x = self._sanitize_margin(search_margin_x, self.DEFAULT_MARGIN_X)
        self.search_margin_top = self._sanitize_margin(search_margin_top, self.DEFAULT_MARGIN_TOP)
        self.search_margin_bottom = self._sanitize_margin(search_margin_bottom, self.DEFAULT_MARGIN_BOTTOM)
        self.templates: list[NicknameTemplate] = []
        self._last_result: Optional[dict] = None
        self._lost_frames: int = 0
        self.max_roi_lost_frames = 8
        self._last_successful_template: Optional[NicknameTemplate] = None # 마지막으로 성공한 템플릿을 기억하기 위한 변수
        self._full_scan_template_index: int = 0 #  전체 화면 스캔 시 순환할 템플릿 인덱스
        self._last_search_region: Optional[dict] = None  # 마지막 템플릿 탐색 영역
        self._last_search_mode: Optional[str] = None
        try:
            self.full_scan_delay_sec = max(0.0, float(full_scan_delay_sec))
        except (TypeError, ValueError):
            self.full_scan_delay_sec = 0.0
        self._last_full_scan_time: float = 0.0
        
    def configure(
        self,
        *,
        target_text: Optional[str] = None,
        match_threshold: Optional[float] = None,
        offset_x: Optional[float] = None,
        offset_y: Optional[float] = None,
        search_margin_x: Optional[float] = None,
        search_margin_top: Optional[float] = None,
        search_margin_bottom: Optional[float] = None,
        full_scan_delay_sec: Optional[float] = None,
    ) -> None:
        if target_text is not None:
            self.target_text = target_text
        if match_threshold is not None:
            self.match_threshold = max(0.1, min(0.99, float(match_threshold)))
        if offset_x is not None:
            self.offset_x = float(offset_x)
        if offset_y is not None:
            self.offset_y = float(offset_y)
        if search_margin_x is not None:
            self.search_margin_x = self._sanitize_margin(search_margin_x, self.DEFAULT_MARGIN_X)
        if search_margin_top is not None:
            self.search_margin_top = self._sanitize_margin(search_margin_top, self.DEFAULT_MARGIN_TOP)
        if search_margin_bottom is not None:
            self.search_margin_bottom = self._sanitize_margin(search_margin_bottom, self.DEFAULT_MARGIN_BOTTOM)
        if full_scan_delay_sec is not None:
            try:
                self.full_scan_delay_sec = max(0.0, float(full_scan_delay_sec))
            except (TypeError, ValueError):
                pass

    def load_templates(self, templates: Iterable[dict]) -> None:
        self.templates = []
        for entry in templates:
            path = entry.get('path')
            template_id = entry.get('id') or entry.get('template_id')
            if not path or not template_id:
                continue
            image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            template = NicknameTemplate(
                template_id=template_id,
                image=image,
                width=int(image.shape[1]),
                height=int(image.shape[0]),
            )
            self.templates.append(template)
        self._last_result = None
        self._lost_frames = 0
        self._last_successful_template = None # 선호 템플릿 초기화
        self._full_scan_template_index = 0
        self._last_search_region = None
        self._last_search_mode = None
        self._last_full_scan_time = 0.0

    def detect(self, frame_bgr: np.ndarray) -> Optional[dict]:
        if not self.templates:
            self._last_search_region = None
            self._last_search_mode = None
            return None
        if frame_bgr is None or frame_bgr.size == 0:
            self._last_search_region = None
            self._last_search_mode = None
            return None

        frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        frame_h, frame_w = frame_gray.shape
        origin_x = 0
        origin_y = 0

        # is_full_scan 플래그로 현재 탐색 모드 구분
        is_full_scan = True
        roi_gray = frame_gray

        if self._last_result and self._lost_frames < self.max_roi_lost_frames:
            # ROI 추적 모드일 경우
            is_full_scan = False
            prev_box = self._last_result.get('nickname_box')
            if prev_box:
                box_x, box_y = float(prev_box.get('x', 0.0)), float(prev_box.get('y', 0.0))
                box_w, box_h = float(prev_box.get('width', 0.0)), float(prev_box.get('height', 0.0))
                margin_x = self.search_margin_x
                margin_top = self.search_margin_top
                margin_bottom = self.search_margin_bottom
                x1 = int(np.clip(box_x - margin_x, 0.0, frame_w))
                y1 = int(np.clip(box_y - margin_top, 0.0, frame_h))
                x2 = int(np.clip(box_x + box_w + margin_x, 0.0, frame_w))
                y2 = int(np.clip(box_y + box_h + margin_bottom, 0.0, frame_h))
                if x2 - x1 > 10 and y2 - y1 > 10:
                    roi_gray = frame_gray[y1:y2, x1:x2]
                    origin_x, origin_y = x1, y1
                else: # ROI가 너무 작으면 안전하게 전체 스캔으로 전환
                    is_full_scan = True
                    roi_gray = frame_gray
        
        roi_h, roi_w = roi_gray.shape
        self._last_search_region = {
            'x': float(origin_x),
            'y': float(origin_y),
            'width': float(roi_w),
            'height': float(roi_h),
        }
        self._last_search_mode = 'full' if is_full_scan else 'roi'

        best_score = 0.0
        best_template: Optional[NicknameTemplate] = None
        best_location = (0, 0)

        # 1. 빠른 경로: ROI 추적 모드일 때
        if not is_full_scan and self._last_successful_template is not None:
            template = self._last_successful_template
            roi_h, roi_w = roi_gray.shape
            if roi_w >= template.width and roi_h >= template.height:
                result = cv2.matchTemplate(roi_gray, template.image, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val >= self.match_threshold:
                    best_score, best_template, best_location = float(max_val), template, max_loc

        # 2. 느린 경로: 빠른 경로에서 못 찾았거나, 전체 스캔 모드일 때
        now_monotonic = time.monotonic()
        should_skip_full_scan = False
        if is_full_scan:
            if self.full_scan_delay_sec > 0.0:
                if self._last_full_scan_time <= 0.0 or (now_monotonic - self._last_full_scan_time) >= self.full_scan_delay_sec:
                    self._last_full_scan_time = now_monotonic
                else:
                    should_skip_full_scan = True
            else:
                self._last_full_scan_time = now_monotonic

        if best_template is None:
            # 분할 탐색 로직
            if is_full_scan:
                if should_skip_full_scan:
                    self.notify_missed()
                    return None
                # 전체 화면 스캔: 한 프레임에 하나씩 순환하며 검사
                if self._full_scan_template_index < len(self.templates):
                    template = self.templates[self._full_scan_template_index]
                    roi_h, roi_w = roi_gray.shape
                    if roi_w >= template.width and roi_h >= template.height:
                        result = cv2.matchTemplate(roi_gray, template.image, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(result)
                        if max_val >= self.match_threshold and max_val > best_score:
                            best_score, best_template, best_location = float(max_val), template, max_loc
                # 다음 프레임을 위해 인덱스 증가 (순환)
                self._full_scan_template_index = (self._full_scan_template_index + 1) % len(self.templates) if self.templates else 0
            else:
                # ROI 스캔 실패 시: 나머지 템플릿들을 모두 검사 (이 영역은 이미 빠름)
                other_templates = [t for t in self.templates if t is not self._last_successful_template]
                for template in other_templates:
                    roi_h, roi_w = roi_gray.shape
                    if roi_w < template.width or roi_h < template.height: continue
                    result = cv2.matchTemplate(roi_gray, template.image, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val >= self.match_threshold and max_val > best_score:
                        best_score, best_template, best_location = float(max_val), template, max_loc

        if not best_template:
            self.notify_missed()
            return None
        
        # 성공 시, 성공한 템플릿과 전체 스캔 인덱스를 기록/초기화
        self._last_successful_template = best_template
        self._full_scan_template_index = 0 # 성공했으므로 다음 전체 스캔은 처음부터 다시 시작

        nick_x, nick_y = origin_x + best_location[0], origin_y + best_location[1]
        nick_w, nick_h = best_template.width, best_template.height
        center_x = nick_x + nick_w / 2.0 + self.offset_x
        center_y = nick_y + nick_h + self.offset_y
        center_x, center_y = float(np.clip(center_x, 0.0, frame_w - 1.0)), float(np.clip(center_y, 0.0, frame_h - 1.0))
        char_width = max(nick_w * self.WIDTH_SCALE, nick_w + 12.0)
        char_height = max(nick_h * self.HEIGHT_SCALE, nick_h + abs(self.offset_y) + 20.0)
        char_width, char_height = float(min(char_width, frame_w)), float(min(char_height, frame_h))
        char_x = float(np.clip(center_x - char_width / 2.0, 0.0, frame_w - char_width))
        char_y = float(np.clip(center_y - char_height / 2.0, 0.0, frame_h - char_height))
        
        detection = {
            'template_id': best_template.template_id, 'score': best_score,
            'nickname_box': {'x': float(nick_x), 'y': float(nick_y), 'width': float(nick_w), 'height': float(nick_h)},
            'character_center': {'x': center_x, 'y': center_y},
            'character_box': {'x': char_x, 'y': char_y, 'width': char_width, 'height': char_height},
        }
        self._last_result = detection
        self._lost_frames = 0
        self._last_full_scan_time = 0.0
        return detection

    def notify_missed(self) -> None:
        if self._last_result is None:
            self._last_search_region = None
            self._last_search_mode = None
            return
        self._lost_frames += 1
        if self._lost_frames >= self.max_roi_lost_frames:
            self._last_result = None
            self._lost_frames = 0
            #  캐릭터를 완전히 놓쳤으므로 선호 템플릿도 초기화
            self._last_successful_template = None
            self._last_search_region = None
            self._last_search_mode = None

    def get_last_search_region(self) -> Optional[dict]:
        if not self._last_search_region:
            return None
        region = dict(self._last_search_region)
        if self._last_search_mode:
            region['mode'] = self._last_search_mode
        return region

    @staticmethod
    def _sanitize_margin(value: Optional[float], default: float) -> float:
        try:
            margin = float(value)
        except (TypeError, ValueError):
            margin = default
        return max(0.0, margin)
