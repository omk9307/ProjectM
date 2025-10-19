"""학습탭용 OCR 감시 워커 및 유틸.

요구 사항
- 한글/숫자만 인식(영문/기호 제거)
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
import traceback

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

# PaddleOCR(선택적) 지원 - 지연 임포트로 전환하여 초기 임포트 충돌을 회피
_PADDLE_AVAILABLE = False
_PADDLE_GPU_AVAILABLE = False
_paddle_ocr_instance = None
_paddle_runtime_label: Optional[str] = None
_paddle_error_detail: Optional[str] = None
_paddle_lock = threading.Lock()
_paddle_import_attempted = False
_PaddleOCR_cls = None  # type: ignore

def _ensure_paddle_import() -> None:
    global _PADDLE_AVAILABLE, _PADDLE_GPU_AVAILABLE, _paddle_error_detail, _paddle_import_attempted, _PaddleOCR_cls
    if _paddle_import_attempted:
        return
    _paddle_import_attempted = True
    try:  # pragma: no cover - 환경에 따라 미설치 가능
        import paddle  # type: ignore
        from paddleocr import PaddleOCR as _POCR  # type: ignore
        _PaddleOCR_cls = _POCR
        _PADDLE_AVAILABLE = True
        try:
            _PADDLE_GPU_AVAILABLE = bool(getattr(paddle, "is_compiled_with_cuda", lambda: False)())
        except Exception:
            _PADDLE_GPU_AVAILABLE = False
    except Exception as exc:
        _PADDLE_AVAILABLE = False
        _PADDLE_GPU_AVAILABLE = False
        try:
            _paddle_error_detail = f"import error: {exc}"
        except Exception:
            _paddle_error_detail = "import error"


# 텍스트 정규화: 한글+숫자 이외 문자는 제거하고, 공백은 정리합니다.
_TEXT_NORMALIZE_WS = re.compile(r"\s+")
_ALLOWED_CHARS = re.compile(r"[가-힣0-9:]+")

_KOR_LANG_OK: Optional[bool] = None

def _kor_lang_available() -> bool:
    global _KOR_LANG_OK
    if not _PYTESSERACT_AVAILABLE:
        _KOR_LANG_OK = False
        return False
    if _KOR_LANG_OK is not None:
        return bool(_KOR_LANG_OK)
    try:
        langs = pytesseract.get_languages(config="")  # type: ignore[attr-defined]
        if isinstance(langs, (list, tuple)):
            _KOR_LANG_OK = ("kor" in langs)
        else:
            # 일부 환경은 빈 리스트를 반환할 수 있어, 일단 통과시킴
            _KOR_LANG_OK = True
    except Exception:
        # get_languages 미지원 환경: 일단 통과시킴
        _KOR_LANG_OK = True
    return bool(_KOR_LANG_OK)


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
    """OCR 원문에서 한글/숫자만 남기고 공백을 정리한다."""
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        return ""
    s = s.replace("\n", " ")
    # 허용 문자만 추출하여 공백으로 연결
    tokens = _ALLOWED_CHARS.findall(s)
    filtered: List[str] = []
    for token in tokens:
        digit_sequences = re.findall(r"\d+", token)
        if any(len(seq) > 2 for seq in digit_sequences):
            continue
        filtered.append(token)
    s2 = " ".join(filtered).strip()
    s2 = _TEXT_NORMALIZE_WS.sub(" ", s2)
    return s2


def is_paddle_available() -> bool:
    """PaddleOCR 사용 가능 여부 반환."""
    return bool(_PADDLE_AVAILABLE)


def _get_paddle_ocr() -> Optional["PaddleOCR"]:
    """지연 초기화된 PaddleOCR 인스턴스를 반환한다.

    - 기본: 한글 모델(`lang='korean'`)
    - GPU: 가능하면 자동 사용(설치가 GPU 빌드인 경우). 기본은 CPU
    """
    global _paddle_ocr_instance, _paddle_runtime_label, _paddle_error_detail
    _ensure_paddle_import()
    if not _PADDLE_AVAILABLE or _PaddleOCR_cls is None:
        return None
    if _paddle_ocr_instance is not None:
        return _paddle_ocr_instance
    # 기본은 CPU. 환경변수로만 GPU 사용을 명시적으로 허용
    #   PADDLE_OCR_USE_GPU=1|true|yes|on 인 경우에 한해, GPU 빌드일 때만 사용
    def _want_gpu() -> bool:
        val = os.getenv("PADDLE_OCR_USE_GPU", "0").strip().lower()
        return val in ("1", "true", "yes", "on")

    use_gpu = bool(_PADDLE_GPU_AVAILABLE and _want_gpu())
    device = "gpu:0" if use_gpu else "cpu"
    # 초기화 시도 순서: 최소 인자 → 최신 서명 → 구버전 서명
    errors: List[str] = []
    # 0) 최신 시그니처 우선(use_textline_orientation/device, 검출 민감도 보정)
    try:
        with _paddle_lock:
            _paddle_ocr_instance = _PaddleOCR_cls(
                lang="korean",
                device=device,
                # 문서 권장 파이프라인: 불필요한 보조 모듈 비활성화
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                # 검출 민감도는 기본값 사용(필요 시 프로필에서 조절)
            )
        _paddle_runtime_label = f"PaddleOCR ({'GPU' if use_gpu else 'CPU'})"
        return _paddle_ocr_instance
    except Exception:
        try:
            errors.append(traceback.format_exc())
        except Exception:
            pass
    # 1) 최소 인자만 (가장 호환성 높음)
    try:
        with _paddle_lock:
            _paddle_ocr_instance = _PaddleOCR_cls(lang="korean")
        # 레이블: 실제 디바이스 조회 시도
        try:
            import paddle as _pd  # type: ignore
            dev = getattr(_pd.device, "get_device", lambda: "cpu")()
            _paddle_runtime_label = f"PaddleOCR ({'GPU' if str(dev).startswith('gpu') else 'CPU'})"
        except Exception:
            _paddle_runtime_label = "PaddleOCR"
        return _paddle_ocr_instance
    except Exception:
        try:
            errors.append(traceback.format_exc())
        except Exception:
            pass
    # 2) 구버전 서명(use_gpu, use_angle_cls)
    try:
        with _paddle_lock:
            _paddle_ocr_instance = _PaddleOCR_cls(
                use_angle_cls=True,
                lang="korean",
                use_gpu=use_gpu,
            )
        _paddle_runtime_label = f"PaddleOCR ({'GPU' if use_gpu else 'CPU'})"
        return _paddle_ocr_instance
    except Exception:
        try:
            errors.append(traceback.format_exc())
        except Exception:
            pass
    # 모두 실패
    _paddle_ocr_instance = None
    _paddle_error_detail = ("\n".join(e for e in errors if e)).strip() or "init error"
    return _paddle_ocr_instance


def get_ocr_engine_label() -> str:
    """현재 사용할 OCR 엔진 라벨을 반환한다.

    - PaddleOCR 초기화 성공 시: "PaddleOCR (CPU|GPU)"
    - 그렇지 않고 Tesseract 가능 시: "Tesseract (kor)" 또는 "Tesseract (kor 미설치)"
    - 그 외: "엔진 사용 불가"
    """
    _ensure_paddle_import()
    if _PADDLE_AVAILABLE:
        # 인스턴스가 아직 없을 수 있으므로 생성 시도
        ocr = _get_paddle_ocr()
        if ocr is not None:
            return _paddle_runtime_label or "PaddleOCR"
    return "엔진 사용 불가"


def get_ocr_last_error() -> Optional[str]:
    """Paddle 임포트/초기화 중 마지막 오류 문자열(있으면) 반환."""
    return _paddle_error_detail


def set_paddle_use_gpu(use_gpu: bool) -> None:
    """GPU 사용 여부를 설정하고 PaddleOCR 엔진을 재초기화한다.

    - 환경변수 `PADDLE_OCR_USE_GPU`를 1/0으로 설정
    - 기존 인스턴스를 파기하고 다음 호출에서 재생성되도록 함
    - 즉시 재초기화를 시도하여 라벨/오류를 갱신
    """
    try:
        os.environ["PADDLE_OCR_USE_GPU"] = "1" if use_gpu else "0"
    except Exception:
        pass
    global _paddle_ocr_instance, _paddle_runtime_label, _paddle_error_detail
    with _paddle_lock:
        _paddle_ocr_instance = None
        _paddle_runtime_label = None
        _paddle_error_detail = None
    try:
        _ = _get_paddle_ocr()
    except Exception:
        # 오류는 내부에 기록됨
        pass


def ocr_korean_words(
    image_bgr: np.ndarray,
    *,
    psm: int = 11,
    conf_threshold: float | None = None,
    min_height_px: int | None = None,
    preprocess: str = "auto",
    debug: bool = False,
) -> List[OCRWord]:
    """이미지에서 한글 워드만 추출하여 반환.

    - PaddleOCR만 사용(전처리 없이 원본 컬러 입력)
    - conf/min_height 필터는 전달된 경우에만 적용
    - 한글만 남긴 text가 비어있지 않은 항목만 반환
    """
    if image_bgr is None or image_bgr.size == 0:
        return []

    # 추가 전처리 없이 원본 이미지를 그대로 사용

    # 1) PaddleOCR 경로 (단일 엔진)
    if _PADDLE_AVAILABLE:
        ocr = _get_paddle_ocr()
        if ocr is not None:
            # 입력 준비: 알파 채널이 있으면 흰색 합성, 너무 작은 경우 업스케일
            img = image_bgr
            try:
                if img.ndim == 3 and img.shape[2] == 4:
                    # RGBA → RGB(흰 배경)
                    b, g, r, a = cv2.split(img)
                    alpha = a.astype(np.float32) / 255.0
                    bg = np.full_like(b, 255, dtype=np.uint8)
                    for c in (b, g, r):
                        c[:] = (c.astype(np.float32) * alpha + bg.astype(np.float32) * (1.0 - alpha)).astype(np.uint8)
                    img = cv2.merge([b, g, r])
            except Exception:
                pass
            try:
                h, w = img.shape[:2]
                min_side = min(h, w)
                max_side = max(h, w)
                # 작은 ROI에서 검출률 향상을 위해 최소 한 변을 320 이상으로 업스케일
                target = 320
                scale = 1.0
                if max_side < target:
                    scale = max(scale, float(target) / float(max(1, max_side)))
                elif min_side < 128:
                    scale = max(scale, 128.0 / float(max(1, min_side)))
                if scale > 1.0:
                    img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_LANCZOS4)
            except Exception:
                pass
            results: List[OCRWord] = []
            _raw_candidates = 0
            _accepted = 0
            _conf_sum = 0.0
            out = None
            # v3.x 표준: predict() 우선, 실패 시 ocr() 폴백
            try:
                out = ocr.predict(img)
                if debug:
                    try:
                        print("[OCR DEBUG] call=predict")
                    except Exception:
                        pass
            except Exception:
                try:
                    out = ocr.ocr(img)
                    if debug:
                        try:
                            print("[OCR DEBUG] call=ocr(fallback)")
                        except Exception:
                            pass
                except Exception:
                    # 예외는 상위에 노출할 수 있도록 저장
                    try:
                        import traceback as _tb  # type: ignore
                        global _paddle_error_detail
                        _paddle_error_detail = (_tb.format_exc() or "ocr() error").strip()
                    except Exception:
                        pass
                    out = None
            if out:
                if debug:
                    try:
                        otype = type(out).__name__
                        olen = len(out) if hasattr(out, '__len__') else -1
                        first = out[0] if (isinstance(out, (list, tuple)) and len(out) > 0) else None
                        ftype = type(first).__name__ if first is not None else 'None'
                        # 첫 요소 속성 요약 + res/json 여부
                        if first is not None:
                            has_boxes = hasattr(first, 'boxes')
                            has_texts = hasattr(first, 'texts') or hasattr(first, 'rec_texts')
                            has_scores = hasattr(first, 'scores') or hasattr(first, 'rec_scores')
                            has_res = hasattr(first, 'res')
                            has_json = hasattr(first, 'json')
                            try:
                                b = getattr(first, 'boxes', None)
                                n_boxes = (len(b) if b is not None and hasattr(b, '__len__') else -1)
                            except Exception:
                                n_boxes = -1
                            try:
                                t = getattr(first, 'texts', None) or getattr(first, 'rec_texts', None)
                                n_texts = (len(t) if t is not None and hasattr(t, '__len__') else -1)
                            except Exception:
                                n_texts = -1
                            print(f"[OCR DEBUG] img={img.shape} dtype={img.dtype} out_type={otype} out_len={olen} first_type={ftype} has_boxes={has_boxes} has_texts={has_texts} has_scores={has_scores} has_res={has_res} has_json={has_json} n_boxes={n_boxes} n_texts={n_texts}")
                            if has_res:
                                try:
                                    d = getattr(first, 'res', None)
                                    if isinstance(d, dict):
                                        k = list(d.keys())
                                        ln = {kk: (len(d[kk]) if hasattr(d[kk], '__len__') else -1) for kk in k}
                                        print(f"[OCR DEBUG] res_keys={k} lens={ln}")
                                except Exception:
                                    pass
                            if (not has_res) and has_json:
                                try:
                                    d = getattr(first, 'json', None)
                                    if isinstance(d, dict):
                                        k = list(d.keys())
                                        ln = {kk: (len(d[kk]) if hasattr(d[kk], '__len__') else -1) for kk in k}
                                        print(f"[OCR DEBUG] json_keys={k} lens={ln}")
                                except Exception:
                                    pass
                        else:
                            print(f"[OCR DEBUG] img={img.shape} dtype={img.dtype} out_type={otype} out_len={olen} first_type=None")
                    except Exception:
                        pass
                # 다양한 반환 타입을 허용하는 파서
                def _yield_items():
                    try:
                        # v3.x OCRResult.res 또는 OCRResult.json 우선 처리
                        try:
                            if isinstance(out, (list, tuple)) and len(out) > 0 and (hasattr(out[0], 'res') or hasattr(out[0], 'json')):
                                for r in out:
                                    d = None
                                    try:
                                        d = getattr(r, 'res', None)
                                    except Exception:
                                        d = None
                                    if not isinstance(d, dict):
                                        try:
                                            d = getattr(r, 'json', None)
                                        except Exception:
                                            d = None
                                    if not isinstance(d, dict):
                                        continue
                                    try:
                                        texts = d.get('rec_texts') or d.get('texts') or []
                                        scores = d.get('rec_scores') or d.get('scores') or []
                                        boxes = d.get('rec_boxes') or d.get('rec_polys') or d.get('dt_polys')
                                    except Exception:
                                        texts, scores, boxes = [], [], None
                                    for i, text_raw in enumerate(texts or []):
                                        try:
                                            score = float(scores[i]) if (scores and i < len(scores)) else 1.0
                                        except Exception:
                                            score = 1.0
                                        box = None
                                        try:
                                            if boxes is not None and i < len(boxes):
                                                box = boxes[i]
                                        except Exception:
                                            box = None
                                        yield box, text_raw, score
                                return
                        except Exception:
                            pass
                        for line in out:
                            # 2.x 호환: list of [ [box, (text, score)], ... ]
                            if isinstance(line, (list, tuple)):
                                for item in (line or []):
                                    if isinstance(item, (list, tuple)):
                                        if len(item) >= 2:
                                            box = item[0]
                                            rec = item[1]
                                            if isinstance(rec, (list, tuple)) and len(rec) >= 2:
                                                text_raw, score = rec[0], rec[1]
                                            else:
                                                text_raw, score = str(rec), 1.0
                                            yield box, text_raw, float(score)
                                        elif len(item) >= 3:
                                            box, text_raw, score = item[0], item[1], item[2]
                                            yield box, str(text_raw), float(score)
                                    elif isinstance(item, dict):
                                        box = item.get('box') or item.get('bbox') or item.get('poly') or item.get('points')
                                        text_raw = (
                                            item.get('text')
                                            or item.get('rec_text')
                                            or item.get('label')
                                            or item.get('transcription')
                                        )
                                        score = (
                                            item.get('score')
                                            or item.get('rec_score')
                                            or item.get('conf')
                                            or item.get('confidence')
                                            or 0.0
                                        )
                                        if box is not None and text_raw is not None:
                                            yield box, str(text_raw), float(score)
                            # 3.x 일부 구현: 객체 속성 형태
                            elif hasattr(line, 'boxes') and (hasattr(line, 'rec_texts') or hasattr(line, 'texts')):
                                boxes = getattr(line, 'boxes', None)
                                texts = getattr(line, 'rec_texts', None) or getattr(line, 'texts', None)
                                scores = getattr(line, 'rec_scores', None) or getattr(line, 'scores', None)
                                try:
                                    for i, box in enumerate(boxes or []):
                                        text_raw = (texts or [None])[i]
                                        score = (scores or [1.0])[i]
                                        if text_raw is None:
                                            continue
                                        yield box, str(text_raw), float(score)
                                except Exception:
                                    pass
                            # 3.x 다른 구현: dt_boxes/dt_polys 등
                            elif any(hasattr(line, name) for name in ('dt_boxes','dt_polys','det_boxes','det_polys')):
                                def _pick(obj, names):
                                    for nm in names:
                                        val = getattr(obj, nm, None)
                                        if val is not None:
                                            return val, nm
                                    return None, None
                                boxes, bname = _pick(line, ('boxes','dt_boxes','det_boxes','polys','dt_polys','det_polys'))
                                texts, tname = _pick(line, ('texts','rec_texts','transcriptions','labels','text_lines'))
                                scores, sname = _pick(line, ('scores','rec_scores','confidences','confs'))
                                if debug:
                                    try:
                                        blen = (len(boxes) if boxes is not None and hasattr(boxes,'__len__') else -1)
                                        tlen = (len(texts) if texts is not None and hasattr(texts,'__len__') else -1)
                                        slen = (len(scores) if scores is not None and hasattr(scores,'__len__') else -1)
                                        print(f"[OCR DEBUG] pick attrs boxes={bname}({blen}) texts={tname}({tlen}) scores={sname}({slen})")
                                    except Exception:
                                        pass
                                try:
                                    if boxes is not None and texts is not None:
                                        for i, box in enumerate(boxes or []):
                                            text_raw = (texts or [None])[i]
                                            score = (scores or [1.0])[i] if (scores is not None and i < len(scores)) else 1.0
                                            if text_raw is None:
                                                continue
                                            yield box, str(text_raw), float(score)
                                except Exception:
                                    pass
                            elif isinstance(line, dict):
                                boxes = line.get('boxes') or line.get('det_boxes') or line.get('polys') or line.get('box') or line.get('bbox')
                                texts = line.get('texts') or line.get('rec_texts') or line.get('labels') or line.get('text') or line.get('transcriptions')
                                scores = line.get('scores') or line.get('rec_scores') or line.get('confs') or line.get('confidences')
                                if boxes and texts:
                                    for i, box in enumerate(boxes):
                                        text_raw = (texts or [None])[i]
                                        score = float((scores or [1.0])[i]) if (scores and i < len(scores)) else 1.0
                                        if text_raw is None:
                                            continue
                                        yield box, str(text_raw), float(score)
                            else:
                                # 미지의 객체(OCRResult 등): dict로 변환을 시도
                                if debug:
                                    try:
                                        attrs = [a for a in dir(line) if not a.startswith('__')][:40]
                                        print(f"[OCR DEBUG] object attrs={attrs}")
                                    except Exception:
                                        pass
                                d = None
                                try:
                                    if hasattr(line, 'to_dict') and callable(getattr(line, 'to_dict')):
                                        d = line.to_dict()
                                except Exception:
                                    d = None
                                if d is None and debug:
                                    try:
                                        print(f"[OCR DEBUG] object to_dict() not available")
                                    except Exception:
                                        pass
                                if d is None:
                                    try:
                                        import dataclasses as _dc  # type: ignore
                                        if _dc.is_dataclass(line):
                                            d = _dc.asdict(line)
                                    except Exception:
                                        d = None
                                if d is None and hasattr(line, '__dict__'):
                                    try:
                                        d = dict(getattr(line, '__dict__'))
                                    except Exception:
                                        d = None
                                if isinstance(d, dict):
                                    if debug:
                                        try:
                                            klist = list(d.keys())[:20]
                                            print(f"[OCR DEBUG] object->dict keys={klist}")
                                        except Exception:
                                            pass
                                    # 1) 평면 키 조합 시도
                                    combos = [
                                        ('boxes', 'texts', 'scores'),
                                        ('boxes', 'rec_texts', 'rec_scores'),
                                        ('polys', 'texts', 'scores'),
                                        ('det_boxes', 'rec_texts', 'rec_scores'),
                                        ('det_polys', 'rec_texts', 'rec_scores'),
                                        ('boxes', 'transcriptions', 'confidences'),
                                    ]
                                    parsed = False
                                    for bk, tk, sk in combos:
                                        try:
                                            _boxes = d.get(bk)
                                            _texts = d.get(tk)
                                            _scores = d.get(sk)
                                            if _boxes is not None and _texts is not None:
                                                for i, box in enumerate(_boxes or []):
                                                    text_raw = (_texts or [None])[i]
                                                    score = float((_scores or [1.0])[i]) if (_scores and i < len(_scores)) else 1.0
                                                    if text_raw is None:
                                                        continue
                                                    yield box, str(text_raw), float(score)
                                                parsed = True
                                                break
                                        except Exception:
                                            continue
                                    if parsed:
                                        continue
                                    # 2) 중첩 리스트 탐색(results/items/data/lines)
                                    for key in ('results', 'items', 'data', 'lines', 'det_results', 'ocr_result', 'ocr_results'):
                                        try:
                                            arr = d.get(key)
                                            if isinstance(arr, (list, tuple)):
                                                for item in arr:
                                                    if isinstance(item, dict):
                                                        box = item.get('box') or item.get('bbox') or item.get('poly') or item.get('points')
                                                        text_raw = item.get('text') or item.get('rec_text') or item.get('label') or item.get('transcription')
                                                        score = item.get('score') or item.get('rec_score') or item.get('conf') or item.get('confidence') or 0.0
                                                        if box is not None and text_raw is not None:
                                                            yield box, str(text_raw), float(score)
                                                break
                                        except Exception:
                                            continue
                                elif isinstance(d, (list, tuple)):
                                    # to_dict가 리스트를 반환하는 경우: 각 항목을 dict로 가정
                                    if debug:
                                        try:
                                            print(f"[OCR DEBUG] object->list len={len(d)} first_type={type(d[0]).__name__ if d else 'None'}")
                                        except Exception:
                                            pass
                                    for item in d:
                                        try:
                                            if isinstance(item, dict):
                                                box = item.get('box') or item.get('bbox') or item.get('poly') or item.get('points')
                                                text_raw = item.get('text') or item.get('rec_text') or item.get('label') or item.get('transcription')
                                                score = item.get('score') or item.get('rec_score') or item.get('conf') or item.get('confidence') or 0.0
                                                if box is not None and text_raw is not None:
                                                    yield box, str(text_raw), float(score)
                                            elif hasattr(item, '__dict__'):
                                                idict = dict(getattr(item, '__dict__'))
                                                text_raw = idict.get('text') or idict.get('rec_text') or idict.get('label') or idict.get('transcription')
                                                box = idict.get('box') or idict.get('bbox') or idict.get('poly') or idict.get('points')
                                                score = idict.get('score') or idict.get('rec_score') or idict.get('conf') or idict.get('confidence') or 0.0
                                                if box is not None and text_raw is not None:
                                                    yield box, str(text_raw), float(score)
                                        except Exception:
                                            continue
                                else:
                                    if debug:
                                        try:
                                            print(f"[OCR DEBUG] object no-dict: type={type(line).__name__}")
                                        except Exception:
                                            pass
                    except Exception:
                        return

                for box, text_raw, score in _yield_items():
                    try:
                        _raw_candidates += 1
                        text = _extract_korean(text_raw)
                        if not text:
                            continue
                        # 신뢰도 스케일 보정(0~1 또는 0~100)
                        conf = float(score) * 100.0
                        if conf_threshold is not None:
                            thr = float(conf_threshold)
                            thr = thr * 100.0 if thr <= 1.0001 else thr
                            if conf < thr:
                                continue
                        # polygon to axis-aligned rect
                        xs = ys = None
                        if isinstance(box, np.ndarray):
                            try:
                                arr = np.asarray(box)
                                if arr.ndim == 2 and arr.shape[1] == 2:
                                    xs = arr[:, 0].astype(int).tolist()
                                    ys = arr[:, 1].astype(int).tolist()
                                elif arr.ndim == 1 and arr.size >= 4:
                                    xs = [int(arr[0]), int(arr[2])]
                                    ys = [int(arr[1]), int(arr[3])]
                                else:
                                    arr = arr.reshape(-1, 2)
                                    xs = arr[:, 0].astype(int).tolist()
                                    ys = arr[:, 1].astype(int).tolist()
                            except Exception:
                                xs = ys = None
                        elif isinstance(box, (list, tuple)) and len(box) >= 4:
                            try:
                                xs = [int(pt[0]) for pt in box]
                                ys = [int(pt[1]) for pt in box]
                            except Exception:
                                # 일부 구현은 [x1,y1,x2,y2] 형태
                                if len(box) >= 4:
                                    xs = [int(box[0]), int(box[2])]
                                    ys = [int(box[1]), int(box[3])]
                                else:
                                    continue
                        elif isinstance(box, dict):
                            # dict 형태 지원
                            if all(k in box for k in ('left','top','width','height')):
                                xs = [int(box['left']), int(box['left']) + int(box['width'])]
                                ys = [int(box['top']), int(box['top']) + int(box['height'])]
                            else:
                                pts = box.get('points') or box.get('poly')
                                if not pts:
                                    continue
                                xs = [int(pt[0]) for pt in pts]
                                ys = [int(pt[1]) for pt in pts]
                        else:
                            continue
                        if xs is None or ys is None:
                            continue
                        left = max(0, min(xs))
                        top = max(0, min(ys))
                        width = max(1, max(xs) - left)
                        height = max(1, max(ys) - top)
                        if (min_height_px is not None) and height < int(min_height_px):
                            continue
                        results.append(OCRWord(text=text, conf=conf, left=left, top=top, width=width, height=height))
                        _accepted += 1
                        _conf_sum += conf
                    except Exception:
                        continue
                if debug:
                    try:
                        _avg = (_conf_sum / _accepted) if _accepted > 0 else 0.0
                        print(f"[OCR DEBUG] candidates={_raw_candidates}, accepted={_accepted}, avg_conf={_avg:.1f}")
                    except Exception:
                        pass
                return results
            else:
                if debug:
                    try:
                        msg = _paddle_error_detail or ""
                        tail = msg.strip().splitlines()[-1] if msg else ""
                        print(f"[OCR DEBUG] paddle returned empty result. last_error='{tail}'")
                    except Exception:
                        pass
    # PaddleOCR을 사용할 수 없는 경우 빈 결과 반환
    return []


def draw_word_boxes(image_bgr: np.ndarray, words: List[OCRWord]) -> np.ndarray:
    """바운딩 박스와 라벨(W/H/Conf)을 그린 이미지를 반환한다."""
    if image_bgr is None or image_bgr.size == 0:
        return image_bgr
    out = image_bgr.copy()
    for w in words:
        pt1 = (int(w.left), int(w.top))
        pt2 = (int(w.left + w.width), int(w.top + w.height))
        cv2.rectangle(out, pt1, pt2, (0, 255, 0), 1)
        # OpenCV 기본 폰트는 한글을 지원하지 않음 → ASCII만 표기
        label = f"W={int(w.width)} H={int(w.height)} C={int(round(w.conf))}%"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        bg1 = (pt1[0], max(0, pt1[1] - th - 4))
        bg2 = (pt1[0] + tw + 6, pt1[1])
        cv2.rectangle(out, bg1, bg2, (0, 0, 0), -1)
        cv2.putText(out, label, (pt1[0] + 3, pt1[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return out


# ----- PaddleOCR 3.x simple API (override) -----
def ocr_korean_words(
    image_bgr: np.ndarray,
    *,
    psm: int = 11,  # 미사용(호환)
    conf_threshold: float | None = None,
    min_height_px: int | None = None,
    max_height_px: int | None = None,
    min_width_px: int | None = None,
    max_width_px: int | None = None,
    preprocess: str = "auto",  # 미사용(호환)
    debug: bool = False,  # 미사용(호환)
) -> List[OCRWord]:
    """PaddleOCR 3.x 공식 가이드대로 predict()만 사용해 단순 파싱.

    - 입력: numpy.ndarray(BGR)
    - 출력: OCRWord 리스트(text, conf(0~100), bbox)
    - 필터: conf/min_height는 전달된 경우에만 적용
    """
    if image_bgr is None or image_bgr.size == 0:
        return []
    if not _PADDLE_AVAILABLE:
        return []
    ocr = _get_paddle_ocr()
    if ocr is None:
        return []
    try:
        res_list = ocr.predict(image_bgr)
    except Exception:
        return []
    if not res_list:
        return []
    r0 = res_list[0]
    meta = None
    try:
        meta = getattr(r0, "json", None)
    except Exception:
        meta = None
    if not isinstance(meta, dict):
        try:
            meta = getattr(r0, "res", None)
        except Exception:
            meta = None
    # 일부 버전은 json이 {"res": {...}} 래퍼 형태
    if isinstance(meta, dict) and isinstance(meta.get("res"), dict):
        meta = meta["res"]
    if not isinstance(meta, dict):
        return []
    texts = meta.get("rec_texts") or meta.get("texts") or []
    scores = meta.get("rec_scores") or meta.get("scores") or []
    boxes = meta.get("rec_boxes") or meta.get("rec_polys") or meta.get("dt_polys")
    out: List[OCRWord] = []
    n = len(texts) if hasattr(texts, "__len__") else 0
    for i in range(n):
        try:
            raw = texts[i]
            score = float(scores[i]) if (scores and i < len(scores)) else 1.0
            conf = score * 100.0
            if conf_threshold is not None:
                thr = float(conf_threshold)
                thr = thr * 100.0 if thr <= 1.0001 else thr
                if conf < thr:
                    continue
            # bbox
            b = boxes[i] if (boxes is not None and i < len(boxes)) else None
            xs = ys = None
            if b is not None:
                if isinstance(b, np.ndarray):
                    arr = np.asarray(b)
                    if arr.ndim == 2 and arr.shape[1] == 2:
                        xs = arr[:, 0].astype(int).tolist()
                        ys = arr[:, 1].astype(int).tolist()
                    elif arr.ndim == 1 and arr.size >= 4:
                        xs = [int(arr[0]), int(arr[2])]
                        ys = [int(arr[1]), int(arr[3])]
                    else:
                        arr = arr.reshape(-1, 2)
                        xs = arr[:, 0].astype(int).tolist()
                        ys = arr[:, 1].astype(int).tolist()
                elif isinstance(b, (list, tuple)) and len(b) >= 4:
                    if isinstance(b[0], (list, tuple)):
                        xs = [int(pt[0]) for pt in b]
                        ys = [int(pt[1]) for pt in b]
                    else:
                        xs = [int(b[0]), int(b[2])]
                        ys = [int(b[1]), int(b[3])]
            if xs is None or ys is None:
                left = top = 0
                width = height = 0
            else:
                left = max(0, min(xs))
                top = max(0, min(ys))
                width = max(1, max(xs) - left)
                height = max(1, max(ys) - top)
                # 크기 필터
                if (min_height_px is not None) and int(min_height_px) > 0 and height < int(min_height_px):
                    continue
                if (max_height_px is not None) and int(max_height_px) > 0 and height > int(max_height_px):
                    continue
                if (min_width_px is not None) and int(min_width_px) > 0 and width < int(min_width_px):
                    continue
                if (max_width_px is not None) and int(max_width_px) > 0 and width > int(max_width_px):
                    continue
            text = _extract_korean(raw)
            if not text:
                continue
            out.append(OCRWord(text=text, conf=conf, left=left, top=top, width=width, height=height))
        except Exception:
            continue
    return out

def _load_telegram_credentials() -> Tuple[str, str]:
    """workspace/config/telegram.json 또는 환경변수에서 (token, chat_id) 로드."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    # 파일 candidates (고정 경로 우선)
    if not token or not chat_id:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspace", "config"))
        candidates = []
        # Windows 고정 경로 최우선
        try:
            candidates.append(r"G:\\Coding\\Project_Maple\\workspace\\config\\telegram.json")
        except Exception:
            pass
        candidates.append(os.path.join(base, "telegram.json"))
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


def send_telegram_text_and_screenshot(message: str, image_bgr: Optional[np.ndarray] = None) -> None:
    """텍스트와 Mapleland 창 스크린샷을 동시에 전송.
    - 자격 없거나 의존성 누락 시 조용히 무시
    - 텍스트/사진 각각 별도의 스레드에서 전송
    """
    token, chat_id = _load_telegram_credentials()
    if not token or not chat_id:
        return

    if image_bgr is not None:
        def _send_photo_with_caption() -> None:
            try:
                import requests  # type: ignore
                import cv2  # type: ignore
            except Exception:
                return
            try:
                ok, buf = cv2.imencode(".png", image_bgr)
                if not ok:
                    return
                png_bytes = bytes(buf)
            except Exception:
                return
            try:
                url = f"https://api.telegram.org/bot{token}/sendPhoto"
                data = {"chat_id": chat_id}
                if message:
                    data["caption"] = message
                files = {"photo": ("ocr_detected.png", png_bytes, "image/png")}
                requests.post(url, data=data, files=files, timeout=8)
            except Exception:
                pass

        threading.Thread(target=_send_photo_with_caption, daemon=True).start()
        return

    def _send_text() -> None:
        try:
            import requests  # type: ignore
        except Exception:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
            requests.post(url, data=payload, timeout=5)
        except Exception:
            pass

    def _send_photo() -> None:
        try:
            import requests  # type: ignore
            import mss  # type: ignore
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return
        try:
            geo = get_maple_window_geometry()
            if geo is None or int(geo.width) <= 0 or int(geo.height) <= 0:
                return
            region = {"left": int(geo.left), "top": int(geo.top), "width": int(geo.width), "height": int(geo.height)}
            with mss.mss() as sct:
                shot = sct.grab(region)
            frame_rgb = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode('.png', frame_bgr)
            if not ok:
                return
            png_bytes = bytes(buf)
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            data = {"chat_id": chat_id}
            files = {"photo": ("maple.png", png_bytes, "image/png")}
            requests.post(url, data=data, files=files, timeout=8)
        except Exception:
            pass

    threading.Thread(target=_send_text, daemon=True).start()
    threading.Thread(target=_send_photo, daemon=True).start()


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
        self._keyword_alert_active: bool = False

    def stop(self) -> None:
        self._running = False
        # 소비자 정리
        for name in list(self._consumers.keys()):
            try:
                self._manager.unregister_region(name)
            except Exception:
                pass
        self._consumers.clear()

    # 협조적 슬립: 긴 대기 시간을 잘게 쪼개 _running 플래그를 주기적으로 확인
    def _cooperative_sleep(self, total_seconds: float) -> None:
        try:
            remaining = max(0.0, float(total_seconds))
        except (TypeError, ValueError):
            remaining = 0.0
        if remaining <= 0.0:
            return
        step = 0.05
        while self._running and remaining > 0.0:
            slice_sec = step if remaining > step else remaining
            time.sleep(slice_sec)
            remaining -= slice_sec

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
                self._cooperative_sleep(0.5)
                continue
            # 프로필 변경 시 전송 카운터 리셋
            if profile_name != self._last_profile_name:
                self._last_profile_name = profile_name
                self._sent_count = 0
                self._last_send_ts = None
                self._keyword_alert_active = False
            # 엔진 가용성 알림: Paddle 미설치/초기화 실패 시 안내
            if (not is_paddle_available()) or (_get_paddle_ocr() is None):
                detail = get_ocr_last_error()
                if detail:
                    # 너무 길 경우 마지막 줄만 간단히 출력
                    tail = detail.strip().splitlines()[-1][:300]
                    self.ocr_status.emit(f"[OCR] PaddleOCR 준비 실패: {tail}")
                else:
                    self.ocr_status.emit("[OCR] PaddleOCR 미설치 또는 초기화 실패. 설치/네트워크 확인이 필요합니다.")
            interval = max(1.0, float(profile.get("interval_sec", 30.0)))
            # 키워드 알림 체크 여부(체크 시 키워드 일치시에만 전송)
            telegram_keyword_mode = bool(profile.get("telegram_enabled", False))
            send_count = int(profile.get("telegram_send_count", 1))
            send_itv = max(1.0, float(profile.get("telegram_send_interval", 5.0)))
            keywords = profile.get("keywords", []) if isinstance(profile.get("keywords"), list) else []
            # 필터는 설정이 있는 경우에만 적용 (기본은 미적용)
            try:
                _mh = profile.get("min_height_px", None)
                if _mh in (None, ""):
                    min_height_px = None
                else:
                    _mhi = int(_mh)
                    min_height_px = None if _mhi <= 0 else _mhi
            except (TypeError, ValueError):
                min_height_px = None
            try:
                _xh = profile.get("max_height_px", None)
                if _xh in (None, ""):
                    max_height_px = None
                else:
                    _xhi = int(_xh)
                    max_height_px = None if _xhi <= 0 else _xhi
            except (TypeError, ValueError):
                max_height_px = None
            try:
                _mw = profile.get("min_width_px", None)
                if _mw in (None, ""):
                    min_width_px = None
                else:
                    _mwi = int(_mw)
                    min_width_px = None if _mwi <= 0 else _mwi
            except (TypeError, ValueError):
                min_width_px = None
            try:
                _xw = profile.get("max_width_px", None)
                if _xw in (None, ""):
                    max_width_px = None
                else:
                    _xwi = int(_xw)
                    max_width_px = None if _xwi <= 0 else _xwi
            except (TypeError, ValueError):
                max_width_px = None
            save_screenshots = bool(profile.get("save_screenshots", False))
            try:
                _ct = profile.get("conf_threshold", None)
                conf_threshold = float(_ct) if _ct not in (None, "") else None
            except (TypeError, ValueError):
                conf_threshold = None
            # 복합 ROI 파츠(상대좌표 리스트)
            roi_parts = profile.get("roi_parts", []) if isinstance(profile.get("roi_parts"), list) else None
            if (not roi_parts) and isinstance(profile.get("rois"), list):
                # 하위호환: 기존 rois를 단일 파츠로 간주
                roi_parts = profile.get("rois", [])

            if not roi_parts:
                self._cooperative_sleep(min(interval, 2.0))
                continue

            absolute_parts = self._resolve_absolute_regions(roi_parts)
            if not absolute_parts:
                self._cooperative_sleep(min(interval, 2.0))
                continue

            # 복합 ROI의 바운딩 박스를 만들고, 파츠는 바운딩 기준 상대좌표로 변환
            bx1 = min(p["left"] for p in absolute_parts)
            by1 = min(p["top"] for p in absolute_parts)
            bx2 = max(p["left"] + p["width"] for p in absolute_parts)
            by2 = max(p["top"] + p["height"] for p in absolute_parts)
            bounding = {"left": int(bx1), "top": int(by1), "width": int(bx2 - bx1), "height": int(by2 - by1)}
            rel_parts: List[Dict[str, int]] = []
            for p in absolute_parts:
                rel_parts.append({
                    "left": int(p["left"] - bx1),
                    "top": int(p["top"] - by1),
                    "width": int(p["width"]),
                    "height": int(p["height"]),
                })

            names = self._ensure_consumers([bounding])
            name = names[0] if names else None
            any_detected = False
            all_texts: List[str] = []
            ts = time.time()
            if name is None:
                self._cooperative_sleep(min(interval, 1.0))
                continue
            frame = self._manager.get_frame(name, timeout=2.0)
            if frame is None or frame.size == 0:
                self.ocr_status.emit("[OCR] 캡처 실패")
                self._cooperative_sleep(min(interval, 1.0))
                continue
            # 마스킹: 바운딩 내에서 파츠 영역만 남기고 나머지는 흰색 처리
            masked = _apply_parts_mask(frame, rel_parts)
            # 단일 시도: 추가 전처리/재시도 없음
            words = ocr_korean_words(
                masked,
                psm=11,
                conf_threshold=conf_threshold,
                min_height_px=min_height_px,
                max_height_px=max_height_px,
                min_width_px=min_width_px,
                max_width_px=max_width_px,
                preprocess="auto",
            )
            annotated_frame = draw_word_boxes(frame, words)
            if words:
                any_detected = True
            all_texts.extend([w.text for w in words])
            self.ocr_detected.emit([
                {"roi_index": 0, "timestamp": ts, "words": [w.__dict__ for w in words]}
            ])

            # 스크린샷 저장(주기마다, 옵션 켜짐 시)
            if save_screenshots:
                try:
                    log_dir = r"G:\\Coding\\Project_Maple\\log"
                    try:
                        os.makedirs(log_dir, exist_ok=True)
                    except Exception:
                        pass
                    annotated = annotated_frame
                    timestr = time.strftime("%y%m%d_%H%M%S", time.localtime(ts))
                    ocr_path = os.path.join(log_dir, f"{timestr}_OCR.png")
                    try:
                        cv2.imwrite(ocr_path, annotated)
                    except Exception:
                        pass
                    try:
                        existing = []
                        for fname in os.listdir(log_dir):
                            if fname.endswith("_OCR.png"):
                                full = os.path.join(log_dir, fname)
                                try:
                                    stat = os.stat(full)
                                    existing.append((stat.st_mtime, full))
                                except Exception:
                                    continue
                        existing.sort()
                        while len(existing) > 1000:
                            _, oldest_path = existing.pop(0)
                            try:
                                os.remove(oldest_path)
                            except Exception:
                                pass
                    except Exception:
                        pass
                except Exception:
                    pass

            # 텔레그램 전송 판단
            joined = " ".join(all_texts).strip()
            matched_word_infos: List[Tuple[str, OCRWord]] = []
            for w in words:
                for kw in keywords:
                    if not isinstance(kw, str):
                        continue
                    kw_clean = kw.strip()
                    if not kw_clean:
                        continue
                    if kw_clean in w.text:
                        matched_word_infos.append((kw_clean, w))
                        break

            alert_triggered = bool(matched_word_infos) if telegram_keyword_mode else False
            if telegram_keyword_mode:
                if alert_triggered:
                    self._keyword_alert_active = True
                else:
                    self._keyword_alert_active = False
            else:
                self._keyword_alert_active = False

            # 텔레그램 전송 조건
            should_send = False
            if any_detected:
                if telegram_keyword_mode:
                    should_send = alert_triggered
                else:
                    should_send = True
            if should_send:
                now = time.time()
                bypass_limits = bool(telegram_keyword_mode and self._keyword_alert_active)
                can_send = False
                if bypass_limits:
                    can_send = True
                else:
                    if self._last_send_ts is None or (now - self._last_send_ts) >= send_itv:
                        if send_count == 0 or self._sent_count < send_count:
                            can_send = True
                if can_send:
                    if telegram_keyword_mode and self._keyword_alert_active:
                        time_local = time.localtime(ts)
                        time_label = f"{time_local.tm_hour:02d}시 {time_local.tm_min:02d}분 {time_local.tm_sec:02d}초"
                        keyword_names: List[str] = []
                        for kw_name, _ in matched_word_infos:
                            if kw_name not in keyword_names:
                                keyword_names.append(kw_name)
                        keyword_summary = ", ".join(keyword_names) if keyword_names else "-"
                        message_lines: List[str] = [f"[OCR] 키워드 감지 {time_label}"]
                        count = len(matched_word_infos)
                        message_lines.append(f"감지한 키워드 수: {count}개 ({keyword_summary})")
                        for idx, (keyword_name, word) in enumerate(matched_word_infos, start=1):
                            conf_pct = int(round(word.conf))
                            message_lines.append(
                                f"[{idx}] 키워드: {keyword_name} > {word.text} "
                                f"(신뢰도: {conf_pct}%, 가로: {int(word.width)}px, 세로: {int(word.height)}px)"
                            )
                        if joined:
                            message_lines.append(f"전체 텍스트: {joined[:300]}")
                        msg = "\n".join(message_lines)
                        image_for_send = annotated_frame
                    else:
                        msg = "[OCR] 한글 감지"
                        if joined:
                            msg += f"\n텍스트: {joined[:300]}"
                        image_for_send = None
                    send_telegram_text_and_screenshot(msg, image_for_send)
                    self._last_send_ts = now
                    if not bypass_limits and send_count != 0:
                        self._sent_count += 1
            # 대기(협조적)
            effective_interval = 5.0 if (telegram_keyword_mode and self._keyword_alert_active) else interval
            self._cooperative_sleep(effective_interval)


__all__ = [
    "OCRWatchThread",
    "ocr_korean_words",
    "draw_word_boxes",
    "is_paddle_available",
    "get_ocr_engine_label",
    "get_ocr_last_error",
    "set_paddle_use_gpu",
]


# -------------------- 내부 유틸 --------------------
def _apply_parts_mask(frame_bgr: np.ndarray, rel_parts: List[Dict[str, int]]) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for p in rel_parts:
        try:
            x1 = max(0, int(p["left"]))
            y1 = max(0, int(p["top"]))
            x2 = min(w, x1 + int(p["width"]))
            y2 = min(h, y1 + int(p["height"]))
            if x2 > x1 and y2 > y1:
                mask[y1:y2, x1:x2] = 255
        except Exception:
            continue
    out = frame_bgr.copy()
    # 마스크 외부는 흰색(255)으로 채워 OCR에 영향 최소화
    inv = cv2.bitwise_not(mask)
    if out.ndim == 3:
        inv3 = cv2.merge([inv, inv, inv])
        white = np.full_like(out, 255, dtype=np.uint8)
        out = cv2.bitwise_and(out, out, mask=mask)
        bg = cv2.bitwise_and(white, white, mask=inv)
        out = cv2.add(out, bg)
    else:
        out = cv2.bitwise_and(out, out, mask=mask)
        out[inv > 0] = 255
    return out
