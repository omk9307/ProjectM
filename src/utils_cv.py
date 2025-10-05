"""OpenCV 안전 유틸리티: 템플릿 매칭 시 어서션 회피용 래퍼.

- matchTemplate는 입력 이미지가 템플릿보다 작으면 OpenCV 내부 어서션으로 실패한다.
  본 모듈의 래퍼는 크기/채널을 사전 확인하고, 안전하지 않은 경우 None을 반환한다.
"""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np


def ensure_gray(img: np.ndarray | None) -> np.ndarray | None:
    if img is None:
        return None
    if img.ndim == 2:
        return img
    if img.ndim == 3:
        ch = img.shape[2]
        if ch == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if ch == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    return None


def safe_match_template(
    img: np.ndarray | None,
    tpl: np.ndarray | None,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Optional[Tuple[float, Tuple[int, int]]]:
    """크기/채널 안전 확인 후 matchTemplate 실행.

    반환: (max_val, max_loc) 또는 None
    """
    try:
        img_g = ensure_gray(img)
        tpl_g = ensure_gray(tpl)
        if img_g is None or tpl_g is None:
            return None
        ih, iw = img_g.shape[:2]
        th, tw = tpl_g.shape[:2]
        if ih < th or iw < tw:
            return None
        res = cv2.matchTemplate(img_g, tpl_g, method)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        return float(max_val), (int(max_loc[0]), int(max_loc[1]))
    except cv2.error:
        return None
    except Exception:
        return None


def safe_match_template_matrix(
    img: np.ndarray | None,
    tpl: np.ndarray | None,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Optional[np.ndarray]:
    """크기/채널 안전 확인 후 결과 매트릭스를 반환. 실패 시 None."""
    try:
        img_g = ensure_gray(img)
        tpl_g = ensure_gray(tpl)
        if img_g is None or tpl_g is None:
            return None
        ih, iw = img_g.shape[:2]
        th, tw = tpl_g.shape[:2]
        if ih < th or iw < tw:
            return None
        return cv2.matchTemplate(img_g, tpl_g, method)
    except cv2.error:
        return None
    except Exception:
        return None

