"""닉네임 기반 캐릭터 탐지를 위한 간단한 템플릿 매칭 도우미."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np


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

    def __init__(
        self,
        target_text: str,
        match_threshold: float,
        offset_x: float,
        offset_y: float,
    ) -> None:
        self.target_text = target_text
        self.match_threshold = max(0.1, min(0.99, float(match_threshold)))
        self.offset_x = float(offset_x)
        self.offset_y = float(offset_y)
        self.templates: list[NicknameTemplate] = []
        self._last_result: Optional[dict] = None
        self._lost_frames: int = 0
        self.max_roi_lost_frames = 8
        self.search_margin_x = 210.0  # 가로(텔레포트) 검색 여백
        self.search_margin_y = 100.0  # 세로(점프) 검색 여백
        
    def configure(
        self,
        *,
        target_text: Optional[str] = None,
        match_threshold: Optional[float] = None,
        offset_x: Optional[float] = None,
        offset_y: Optional[float] = None,
    ) -> None:
        if target_text is not None:
            self.target_text = target_text
        if match_threshold is not None:
            self.match_threshold = max(0.1, min(0.99, float(match_threshold)))
        if offset_x is not None:
            self.offset_x = float(offset_x)
        if offset_y is not None:
            self.offset_y = float(offset_y)

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

    def detect(self, frame_bgr: np.ndarray) -> Optional[dict]:
        if not self.templates:
            return None
        if frame_bgr is None or frame_bgr.size == 0:
            return None

        frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        frame_h, frame_w = frame_gray.shape
        origin_x = 0
        origin_y = 0
        roi_gray = frame_gray
        if self._last_result and self._lost_frames < self.max_roi_lost_frames:
            prev_box = self._last_result.get('nickname_box')
            if prev_box:
                box_x = float(prev_box.get('x', 0.0))
                box_y = float(prev_box.get('y', 0.0))
                box_w = float(prev_box.get('width', 0.0))
                box_h = float(prev_box.get('height', 0.0))
                margin_x = max(self.search_margin_x, box_w * 1.5)
                margin_y = max(self.search_margin_y, box_h * 1.5)
                x1 = int(np.clip(box_x - margin_x, 0.0, frame_w))
                y1 = int(np.clip(box_y - margin_y, 0.0, frame_h))
                x2 = int(np.clip(box_x + box_w + margin_x, 0.0, frame_w))
                y2 = int(np.clip(box_y + box_h + margin_y, 0.0, frame_h))
                if x2 - x1 > 10 and y2 - y1 > 10:
                    roi_gray = frame_gray[y1:y2, x1:x2]
                    origin_x = x1
                    origin_y = y1

        best_score = 0.0
        best_template: Optional[NicknameTemplate] = None
        best_location = (0, 0)

        roi_h, roi_w = roi_gray.shape
        for template in self.templates:
            if roi_w < template.width or roi_h < template.height:
                continue
            result = cv2.matchTemplate(roi_gray, template.image, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= self.match_threshold and max_val > best_score:
                best_score = float(max_val)
                best_template = template
                best_location = max_loc

        if not best_template:
            self.notify_missed()
            return None

        nick_x = origin_x + best_location[0]
        nick_y = origin_y + best_location[1]
        nick_w, nick_h = best_template.width, best_template.height

        center_x = nick_x + nick_w / 2.0 + self.offset_x
        center_y = nick_y + nick_h + self.offset_y

        center_x = float(np.clip(center_x, 0.0, frame_w - 1.0))
        center_y = float(np.clip(center_y, 0.0, frame_h - 1.0))

        char_width = max(nick_w * self.WIDTH_SCALE, nick_w + 12.0)
        char_height = max(nick_h * self.HEIGHT_SCALE, nick_h + abs(self.offset_y) + 20.0)
        char_width = float(min(char_width, frame_w))
        char_height = float(min(char_height, frame_h))

        char_x = float(np.clip(center_x - char_width / 2.0, 0.0, frame_w - char_width))
        char_y = float(np.clip(center_y - char_height / 2.0, 0.0, frame_h - char_height))
        detection = {
            'template_id': best_template.template_id,
            'score': best_score,
            'nickname_box': {
                'x': float(nick_x),
                'y': float(nick_y),
                'width': float(nick_w),
                'height': float(nick_h),
            },
            'character_center': {
                'x': center_x,
                'y': center_y,
            },
            'character_box': {
                'x': char_x,
                'y': char_y,
                'width': char_width,
                'height': char_height,
            },
        }
        self._last_result = detection
        self._lost_frames = 0
        return detection

    def notify_missed(self) -> None:
        if self._last_result is None:
            return
        self._lost_frames += 1
        if self._lost_frames >= self.max_roi_lost_frames:
            self._last_result = None
            self._lost_frames = 0
