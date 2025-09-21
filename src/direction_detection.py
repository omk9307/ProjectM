"""캐릭터 방향을 판별하기 위한 템플릿 기반 검출 도우미."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import cv2
import numpy as np


@dataclass
class DirectionTemplate:
    template_id: str
    side: str
    image: np.ndarray
    width: int
    height: int


class DirectionDetector:
    """닉네임 주변의 작은 영역에서 방향 템플릿을 매칭한다."""

    def __init__(
        self,
        match_threshold: float,
        search_offset_y: float,
        search_height: float,
        search_half_width: float,
    ) -> None:
        self.match_threshold = max(0.1, min(0.99, float(match_threshold)))
        self.search_offset_y = float(search_offset_y)
        self.search_height = max(4.0, float(search_height))
        self.search_half_width = max(4.0, float(search_half_width))

        self.templates: Dict[str, List[DirectionTemplate]] = {
            'left': [],
            'right': [],
        }
        self._preferred_template: Dict[str, Optional[DirectionTemplate]] = {
            'left': None,
            'right': None,
        }
        self._scan_index: Dict[str, int] = {
            'left': 0,
            'right': 0,
        }
        self._last_result: Optional[dict] = None
        self._last_roi_rect: Optional[dict] = None
        self._lost_frames: int = 0
        self.max_lost_frames: int = 8

    def configure(
        self,
        *,
        match_threshold: Optional[float] = None,
        search_offset_y: Optional[float] = None,
        search_height: Optional[float] = None,
        search_half_width: Optional[float] = None,
    ) -> None:
        if match_threshold is not None:
            self.match_threshold = max(0.1, min(0.99, float(match_threshold)))
        if search_offset_y is not None:
            self.search_offset_y = float(search_offset_y)
        if search_height is not None:
            self.search_height = max(4.0, float(search_height))
        if search_half_width is not None:
            self.search_half_width = max(4.0, float(search_half_width))

    def load_templates(
        self,
        left_templates: Iterable[dict],
        right_templates: Iterable[dict],
    ) -> None:
        def _load(entries: Iterable[dict], side: str) -> List[DirectionTemplate]:
            loaded: List[DirectionTemplate] = []
            for entry in entries:
                path = entry.get('path')
                template_id = entry.get('id') or entry.get('template_id')
                if not path or not template_id:
                    continue
                image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if image is None:
                    continue
                loaded.append(
                    DirectionTemplate(
                        template_id=template_id,
                        side=side,
                        image=image,
                        width=int(image.shape[1]),
                        height=int(image.shape[0]),
                    )
                )
            return loaded

        self.templates['left'] = _load(left_templates, 'left')
        self.templates['right'] = _load(right_templates, 'right')
        self._preferred_template = {'left': None, 'right': None}
        self._scan_index = {'left': 0, 'right': 0}
        self._last_result = None
        self._last_roi_rect = None
        self._lost_frames = 0

    def _compute_roi(self, frame_shape, nickname_info: dict) -> Optional[tuple[int, int, int, int]]:
        box = nickname_info.get('nickname_box') or {}
        if not box:
            return None
        frame_h, frame_w = frame_shape[:2]
        nick_x = float(box.get('x', 0.0))
        nick_y = float(box.get('y', 0.0))
        nick_w = float(box.get('width', 0.0))
        nick_h = float(box.get('height', 0.0))
        if nick_w <= 0 or nick_h <= 0:
            return None
        center_x = nick_x + nick_w / 2.0
        start_y = nick_y - self.search_offset_y
        start_y = max(0.0, min(start_y, frame_h - 1.0))
        roi_height = min(self.search_height, frame_h - start_y)
        if roi_height < 4:
            return None
        left = center_x - self.search_half_width
        right = center_x + self.search_half_width
        left = max(0.0, min(left, frame_w - 1.0))
        right = max(left + 1.0, min(right, frame_w))
        roi_width = right - left
        if roi_width < 4:
            return None
        x1 = int(round(left))
        y1 = int(round(start_y))
        w = int(round(roi_width))
        h = int(round(roi_height))
        x1 = max(0, min(x1, frame_w - 1))
        y1 = max(0, min(y1, frame_h - 1))
        w = max(4, min(w, frame_w - x1))
        h = max(4, min(h, frame_h - y1))
        return x1, y1, w, h

    def detect(self, frame_bgr: np.ndarray, nickname_info: Optional[dict]) -> Optional[dict]:
        if nickname_info is None:
            self.notify_missed()
            return None
        if frame_bgr is None or frame_bgr.size == 0:
            self.notify_missed()
            return None
        if not (self.templates['left'] or self.templates['right']):
            return None

        roi_rect = self._compute_roi(frame_bgr.shape, nickname_info)
        if roi_rect is None:
            self.notify_missed()
            return None
        x1, y1, w, h = roi_rect
        roi_gray = cv2.cvtColor(frame_bgr[y1:y1 + h, x1:x1 + w], cv2.COLOR_BGR2GRAY)
        self._last_roi_rect = {
            'x': float(x1),
            'y': float(y1),
            'width': float(w),
            'height': float(h),
        }

        best_side: Optional[str] = None
        best_template: Optional[DirectionTemplate] = None
        best_score: float = 0.0
        best_location: Optional[tuple[int, int]] = None

        for side in ('left', 'right'):
            templates = self.templates[side]
            if not templates or roi_gray.shape[0] < 4 or roi_gray.shape[1] < 4:
                continue
            side_best_score = 0.0
            side_best_template: Optional[DirectionTemplate] = None
            side_best_loc: Optional[tuple[int, int]] = None

            # 1) 선호 템플릿 우선 검사
            preferred = self._preferred_template.get(side)
            if preferred is not None and roi_gray.shape[0] >= preferred.height and roi_gray.shape[1] >= preferred.width:
                result = cv2.matchTemplate(roi_gray, preferred.image, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val >= self.match_threshold:
                    side_best_score = float(max_val)
                    side_best_template = preferred
                    side_best_loc = max_loc

            # 2) 선호 템플릿 실패 시, 한 장씩 순환 검사
            if side_best_template is None:
                idx = self._scan_index.get(side, 0)
                if idx >= len(templates):
                    idx = 0
                template = templates[idx]
                self._scan_index[side] = (idx + 1) % len(templates)
                if roi_gray.shape[0] >= template.height and roi_gray.shape[1] >= template.width:
                    result = cv2.matchTemplate(roi_gray, template.image, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val >= self.match_threshold:
                        side_best_score = float(max_val)
                        side_best_template = template
                        side_best_loc = max_loc

            if side_best_template and side_best_loc:
                if side_best_score > best_score:
                    best_score = side_best_score
                    best_template = side_best_template
                    best_location = side_best_loc
                    best_side = side

        result_payload: dict = {
            'matched': False,
            'side': None,
            'score': 0.0,
            'roi_rect': self._last_roi_rect.copy() if self._last_roi_rect else None,
            'match_rect': None,
            'template_id': None,
        }

        if best_template is None or best_location is None:
            self._lost_frames += 1
            if self._lost_frames >= self.max_lost_frames:
                self._last_result = None
                self._preferred_template = {'left': None, 'right': None}
            return result_payload

        self._lost_frames = 0
        self._preferred_template[best_side or 'left'] = best_template

        match_x = x1 + best_location[0]
        match_y = y1 + best_location[1]
        match_rect = {
            'x': float(match_x),
            'y': float(match_y),
            'width': float(best_template.width),
            'height': float(best_template.height),
        }

        result_payload.update(
            {
                'matched': True,
                'side': best_side,
                'score': best_score,
                'match_rect': match_rect,
                'template_id': best_template.template_id,
            }
        )
        self._last_result = result_payload
        return result_payload

    def notify_missed(self) -> None:
        self._lost_frames += 1
        if self._lost_frames >= self.max_lost_frames:
            self._last_result = None
            self._preferred_template = {'left': None, 'right': None}
            self._lost_frames = 0
            self._last_roi_rect = None

    @property
    def last_roi_rect(self) -> Optional[dict]:
        return self._last_roi_rect.copy() if self._last_roi_rect else None

    @property
    def last_result(self) -> Optional[dict]:
        return dict(self._last_result) if self._last_result else None
