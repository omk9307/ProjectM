"""학습탭용 OCR 감시 워커 및 유틸.

요구 사항
- 한글만 인식 (숫자/기호 무시)
- 최소 글자 높이 23px 이상만 유효 텍스트로 인정
- 다중 ROI 주기 캡처, 바운딩 박스 강조 미리보기 지원
- 텔레그램 전송(감지 시 n회, 주기 n초 / 0이면 무제한), 키워드 포함 시 전송

주의
- 실제 전송은 Windows 환경에서 workspace/config/telegram.json 또는 환경변수로 자격을 로드합니다.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from capture_manager import get_capture_manager
from window_anchors import get_maple_window_geometry, resolve_roi_to_absolute

try:
    import pytesseract  # type: ignore

    _PYTESSERACT_AVAILABLE = True
except Exception:  # pragma: no cover - 실행 환경에 따라 미설치일 수 있음
    _PYTESSERACT_AVAILABLE = False


KOREAN_WORD_PATTERN = re.compile(r"[가-힣]+")


@dataclass
class OCRWord:
    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int

    def bbox(self) -> Tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height


def _extract_korean(text: str) -> str:
    """문자열에서 한글만 남겨 결합하여 반환한다."""
    return " ".join(KOREAN_WORD_PATTERN.findall(text or ""))


def ocr_korean_words(
    image_bgr: np.ndarray,
    *,
    psm: int = 11,
    conf_threshold: float = 60.0,
    min_height_px: int = 23,
) -> List[OCRWord]:
    """이미지에서 한글 워드만 추출하여 반환.

    - pytesseract image_to_data 사용 (word 레벨)
    - conf >= conf_threshold, height >= min_height_px
    - 한글만 남긴 text가 비어있지 않은 항목만 반환
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    if not _PYTESSERACT_AVAILABLE:
        return []

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    # 노이즈 경감 (필요 시): 너무 강하게 하면 획이 사라질 수 있어 ksize=3만 적용
    try:
        gray = cv2.medianBlur(gray, 3)
    except Exception:
        pass
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    config = f"--psm {psm} --oem 3"
    # 한국어 전용
    try:
        data = pytesseract.image_to_data(thresh, lang="kor", config=config, output_type=pytesseract.Output.DICT)
    except Exception:
        return []

    n = int(data.get("level") and len(data["level"]) or 0)
    results: List[OCRWord] = []
    for i in range(n):
        try:
            text_raw = data["text"][i] or ""
            text = _extract_korean(text_raw)
            if not text:
                continue
            conf_raw = data["conf"][i]
            conf = float(conf_raw) if conf_raw not in (None, "", "-1") else -1.0
            if conf < conf_threshold:
                continue
            left = int(data["left"][i])
            top = int(data["top"][i])
            width = int(data["width"][i])
            height = int(data["height"][i])
            if height < int(min_height_px):
                continue
            results.append(OCRWord(text=text, conf=conf, left=left, top=top, width=width, height=height))
        except Exception:
            continue
    return results


def draw_word_boxes(image_bgr: np.ndarray, words: List[OCRWord]) -> np.ndarray:
    """바운딩 박스와 라벨을 그린 이미지를 반환한다."""
    if image_bgr is None or image_bgr.size == 0:
        return image_bgr
    out = image_bgr.copy()
    for w in words:
        pt1 = (int(w.left), int(w.top))
        pt2 = (int(w.left + w.width), int(w.top + w.height))
        cv2.rectangle(out, pt1, pt2, (0, 255, 0), 1)
        label = f"{w.text} ({int(round(w.conf))}%, {w.height}px)"
        # 라벨 배경
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        bg1 = (pt1[0], max(0, pt1[1] - th - 4))
        bg2 = (pt1[0] + tw + 6, pt1[1])
        cv2.rectangle(out, bg1, bg2, (0, 0, 0), -1)
        cv2.putText(out, label, (pt1[0] + 3, pt1[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def _load_telegram_credentials() -> Tuple[str, str]:
    """workspace/config/telegram.json 또는 환경변수에서 (token, chat_id) 로드."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    # 파일 candidates (map_ui와 유사한 경로 정책 일부만 적용)
    if not token or not chat_id:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspace", "config"))
        candidates = [
            os.path.join(base, "telegram.json"),
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as fp:
                    lines = fp.readlines()
            except Exception:
                lines = []
            pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\'\"])(.*?)\2\s*$")
            kv: Dict[str, str] = {}
            for raw in lines:
                m = pattern.match(raw.strip())
                if not m:
                    continue
                key, _, val = m.groups()
                kv[key] = val
            token = kv.get("TELEGRAM_BOT_TOKEN", token).strip() or token
            chat_id = kv.get("TELEGRAM_CHAT_ID", chat_id).strip() or chat_id
            if token and chat_id:
                break
    return token, chat_id


def send_telegram_message(message: str) -> None:
    """텔레그램 메시지 전송. 실패는 조용히 무시하고 로그는 호출측에서 처리."""
    token, chat_id = _load_telegram_credentials()
    if not token or not chat_id:
        return
    def _worker() -> None:
        try:
            import requests  # type: ignore
        except Exception:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
        try:
            requests.post(url, data=payload, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


class OCRWatchThread(QThread):
    """다중 ROI에 대해 주기적으로 한글 OCR을 수행하는 워커."""

    ocr_status = pyqtSignal(str)
    ocr_detected = pyqtSignal(list)  # list[dict]: roi_index, words, timestamp

    def __init__(self, *, get_active_profile: callable, get_profile_data: callable) -> None:
        super().__init__()
        self._get_active_profile = get_active_profile
        self._get_profile_data = get_profile_data
        self._running = True
        self._manager = get_capture_manager()
        self._consumers: Dict[str, Dict[str, int]] = {}  # name -> region
        self._last_send_ts: Optional[float] = None
        self._sent_count: int = 0
        self._last_profile_name: Optional[str] = None

    def stop(self) -> None:
        self._running = False
        # 소비자 정리
        for name in list(self._consumers.keys()):
            try:
                self._manager.unregister_region(name)
            except Exception:
                pass
        self._consumers.clear()

    def _ensure_consumers(self, regions: List[Dict[str, int]]) -> List[str]:
        names: List[str] = []
        # 간단히: 현재는 전부 재등록 (규모가 작아 과도한 오버헤드 아님)
        for name in list(self._consumers.keys()):
            try:
                self._manager.unregister_region(name)
            except Exception:
                pass
        self._consumers.clear()
        for idx, region in enumerate(regions):
            name = f"ocr:{id(self)}:{idx}"
            try:
                self._manager.register_region(name, region)
            except Exception:
                continue
            self._consumers[name] = region
            names.append(name)
        return names

    def _resolve_absolute_regions(self, roi_payloads: List[Dict[str, int]]) -> List[Dict[str, int]]:
        window = get_maple_window_geometry()
        regions: List[Dict[str, int]] = []
        for payload in roi_payloads:
            try:
                absolute = resolve_roi_to_absolute(payload, window=window)
                if absolute is None:
                    absolute = resolve_roi_to_absolute(payload)
                if absolute:
                    regions.append({
                        "left": int(absolute["left"]),
                        "top": int(absolute["top"]),
                        "width": max(1, int(absolute["width"])) ,
                        "height": max(1, int(absolute["height"])) ,
                    })
            except Exception:
                continue
        return regions

    def run(self) -> None:  # noqa: D401
        while self._running:
            # 프로필/설정 로드
            profile_name = self._get_active_profile()
            profile = self._get_profile_data(profile_name) if profile_name else None
            if not isinstance(profile, dict):
                time.sleep(0.5)
                continue
            # 프로필 변경 시 전송 카운터 리셋
            if profile_name != self._last_profile_name:
                self._last_profile_name = profile_name
                self._sent_count = 0
                self._last_send_ts = None
            interval = max(1.0, float(profile.get("interval_sec", 30.0)))
            telegram_enabled = bool(profile.get("telegram_enabled", False))
            send_count = int(profile.get("telegram_send_count", 1))
            send_itv = max(1.0, float(profile.get("telegram_send_interval", 5.0)))
            keywords = profile.get("keywords", []) if isinstance(profile.get("keywords"), list) else []
            roi_payloads = profile.get("rois", []) if isinstance(profile.get("rois"), list) else []

            if not roi_payloads:
                # ROI가 없으면 대기
                time.sleep(min(interval, 2.0))
                continue

            regions = self._resolve_absolute_regions(roi_payloads)
            if not regions:
                time.sleep(min(interval, 2.0))
                continue

            names = self._ensure_consumers(regions)
            any_detected = False
            all_texts: List[str] = []
            ts = time.time()
            for idx, name in enumerate(names):
                frame = self._manager.get_frame(name, timeout=0.8)
                if frame is None or frame.size == 0:
                    self.ocr_status.emit(f"[OCR] ROI{idx+1}: 캡처 실패")
                    continue
                words = ocr_korean_words(frame, psm=11, conf_threshold=60.0, min_height_px=23)
                if words:
                    any_detected = True
                all_texts.extend([w.text for w in words])
                self.ocr_detected.emit([
                    {"roi_index": idx, "timestamp": ts, "words": [w.__dict__ for w in words]}
                ])

            # 텔레그램 전송 판단
            joined = " ".join(all_texts).strip()
            matched_keyword = None
            for kw in keywords:
                if isinstance(kw, str) and kw.strip() and kw.strip() in joined:
                    matched_keyword = kw.strip()
                    break

            if any_detected and telegram_enabled:
                now = time.time()
                can_send = False
                if self._last_send_ts is None:
                    can_send = True
                else:
                    if (now - self._last_send_ts) >= send_itv:
                        can_send = True
                if can_send and (send_count == 0 or self._sent_count < send_count):
                    msg = "[OCR] 한글 감지"
                    if matched_keyword:
                        msg += f" (키워드: {matched_keyword})"
                    if joined:
                        msg += f"\n텍스트: {joined[:300]}"
                    send_telegram_message(msg)
                    self._last_send_ts = now
                    if send_count != 0:
                        self._sent_count += 1
            # 대기
            time.sleep(interval)


__all__ = [
    "OCRWatchThread",
    "ocr_korean_words",
    "draw_word_boxes",
]
