"""미니맵 X → 사냥 프레임 X 온라인(자가) 보정기.

용도
- 닉네임 박스 검출 시 (map_x, x_obs) 샘플을 수집하고 최근 윈도우로 선형 보정 y=a*x+b 추정
- 수렴 기준을 만족하면 (a,b)을 파일에 저장하고 "동결"(이후엔 저장값 유지)

정책(기본)
- 저장값이 이미 존재하는 프로필+ROI는 업데이트하지 않고 그대로 유지(동결)
- 아직 저장값이 없으면 온라인 추정치를 우선 적용하고, 수렴 시 자동 저장 후 동결

주의
- 본 모듈은 런타임 상태만 관리. 저장/조회는 map_hunt_calibration 모듈 사용
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple
import math
import time

try:
    # 런타임 분리: 실패 시에도 호출부가 안전하게 폴백하도록 함
    from map_hunt_calibration import (
        roi_signature,
        find_calibration as _find_saved_params,
        save_params as _save_params,
    )
except Exception:  # pragma: no cover - import 실패시에도 안전
    roi_signature = lambda _roi: None  # type: ignore

    def _find_saved_params(_profile: str, _roi: dict | None):  # type: ignore
        return None

    def _save_params(_profile: str, _roi: dict | None, _a: float, _b: float):  # type: ignore
        return False, "map_hunt_calibration 불가"


# 기본 파라미터
WINDOW_SIZE = 60
EDGE_MARGIN_RATIO = 0.05  # 프레임 경계 5% 내 샘플 제외
MAX_RESIDUAL_RATIO = 0.12  # 인라이어 상한: 12% * frame_width
MIN_STD_MAPX = 120.0  # 기본 모드: 맵 X 표준편차 임계
MIN_STD_MAPX_NARROW = 60.0  # 좁은맵 모드: 임계 완화
MIN_INLIERS_SAVE = 20
MIN_INLIERS_SAVE_NARROW = 15
RMSE_THRESH_PX_MIN = 8.0
RMSE_THRESH_RATIO = 0.02  # 2% * frame_width
RMSE_THRESH_RATIO_NARROW = 0.03  # 좁은맵 모드: 3%
CONSEC_OK_REQUIRED = 12
MIN_OBS_WINDOW_SEC = 5.0
WLS_TIME_DECAY_TAU_SEC = 8.0  # 최신 샘플 가중 강화
B_EMA_ALPHA_NARROW = 0.2  # 좁은맵 모드: b만 보정 시 EMA 계수


@dataclass
class Sample:
    map_x: float
    obs_x: float
    frame_w: float
    ts: float


@dataclass
class OnlineState:
    samples: Deque[Sample] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    a: Optional[float] = None
    b: Optional[float] = None
    live_bias: float = 0.0
    last_fit_rmse: Optional[float] = None
    last_fit_inliers: int = 0
    last_fit_ts: float = 0.0
    ok_streak: int = 0
    frozen: bool = False
    first_ts: float = 0.0
    last_note: Optional[str] = None  # 최근 보류/거부 사유


_STATES: Dict[Tuple[str, str], OnlineState] = {}
_NARROW_MAP_MODE: bool = False
_ONLINE_ENABLED: bool = True
_APPLY_ONLINE: bool = True
_AUTO_SAVE: bool = False
_FREEZE_AFTER_SAVE: bool = True


def set_narrow_map_mode(enabled: bool) -> None:
    global _NARROW_MAP_MODE
    _NARROW_MAP_MODE = bool(enabled)


def is_narrow_map_mode() -> bool:
    return bool(_NARROW_MAP_MODE)


def set_online_enabled(enabled: bool) -> None:
    global _ONLINE_ENABLED
    _ONLINE_ENABLED = bool(enabled)


def is_online_enabled() -> bool:
    return bool(_ONLINE_ENABLED)


def set_apply_online_immediately(enabled: bool) -> None:
    global _APPLY_ONLINE
    _APPLY_ONLINE = bool(enabled)


def is_apply_online_immediately() -> bool:
    return bool(_APPLY_ONLINE)


def set_auto_save(enabled: bool) -> None:
    global _AUTO_SAVE
    _AUTO_SAVE = bool(enabled)


def is_auto_save() -> bool:
    return bool(_AUTO_SAVE)


def set_freeze_after_save(enabled: bool) -> None:
    global _FREEZE_AFTER_SAVE
    _FREEZE_AFTER_SAVE = bool(enabled)


def is_freeze_after_save() -> bool:
    return bool(_FREEZE_AFTER_SAVE)


def _min_std_mapx_threshold() -> float:
    return float(MIN_STD_MAPX_NARROW if _NARROW_MAP_MODE else MIN_STD_MAPX)


def _rmse_threshold(frame_w: float) -> float:
    ratio = RMSE_THRESH_RATIO_NARROW if _NARROW_MAP_MODE else RMSE_THRESH_RATIO
    return max(RMSE_THRESH_PX_MIN, (float(frame_w) * ratio) if float(frame_w) > 1.0 else RMSE_THRESH_PX_MIN)


def _min_inliers_save() -> int:
    return int(MIN_INLIERS_SAVE_NARROW if _NARROW_MAP_MODE else MIN_INLIERS_SAVE)


def _key(profile: str, roi: dict | None) -> Optional[Tuple[str, str]]:
    if not isinstance(profile, str) or not profile.strip():
        return None
    sig = roi_signature(roi)
    if not isinstance(sig, str):
        return None
    return (profile.strip(), sig)


def _ols_fit(pairs: list[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if len(pairs) < 2:
        return None
    sx = sy = sxx = sxy = 0.0
    n = float(len(pairs))
    for x, y in pairs:
        sx += x
        sy += y
        sxx += x * x
        sxy += x * y
    den = n * sxx - sx * sx
    if abs(den) < 1e-6:
        return None
    a = (n * sxy - sx * sy) / den
    b = (sy - a * sx) / n
    return a, b


def _compute_std(values: list[float]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(max(0.0, var))


def _wls_fit(pairs: list[Tuple[float, float]], weights: list[float]) -> Optional[Tuple[float, float]]:
    n = len(pairs)
    if n < 2 or len(weights) != n:
        return None
    sw = sx = sy = sxx = sxy = 0.0
    for (x, y), w in zip(pairs, weights):
        w = float(max(0.0, w))
        sw += w
        sx += w * x
        sy += w * y
        sxx += w * x * x
        sxy += w * x * y
    den = sw * sxx - sx * sx
    if abs(den) < 1e-6 or sw <= 0.0:
        return None
    a = (sw * sxy - sx * sy) / den
    b = (sy - a * sx) / sw
    return a, b


def update(
    profile: str,
    roi: dict | None,
    map_x: float,
    x_obs: float,
    frame_w: Optional[float] = None,
    *,
    now_ts: Optional[float] = None,
) -> bool:
    """새 샘플을 업데이트. 수렴 시 파일 저장 후 동결.

    - 저장값이 이미 존재하면 업데이트하지 않음(동결 유지)
    - 유효 샘플만 수집: 프레임 경계 5% 이내 제외
    - 2패스 OLS(잔차 기반 이상치 제거) 추정
    - 수렴 조건 충족 시 자동 저장 및 동결
    """
    k = _key(profile, roi)
    if k is None:
        return False
    if not _ONLINE_ENABLED:
        return False
    state = _STATES.get(k)
    if state is None:
        state = OnlineState()
        _STATES[k] = state

    # 이미 동결되어 있으면 스킵
    if state.frozen:
        return False

    # 저장값이 있으면 동결(기본 정책)
    try:
        saved = _find_saved_params(profile, roi)
        if saved is not None and _FREEZE_AFTER_SAVE:
            state.frozen = True
            return False
    except Exception:
        # 조회 실패는 무시하고 진행
        pass

    try:
        fx = float(map_x)
        ox = float(x_obs)
        fw = float(frame_w or 0.0)
    except Exception:
        return False

    # 프레임 폭 없으면 보수적 임계값 사용
    max_residual_px = fw * MAX_RESIDUAL_RATIO if fw > 1.0 else 60.0
    edge_margin = fw * EDGE_MARGIN_RATIO if fw > 1.0 else 0.0

    ts = float(now_ts) if now_ts is not None else time.time()

    # 경계 근처 샘플은 제외(클리핑 영향 감소)
    if fw > 1.0:
        if not (edge_margin <= ox <= (fw - edge_margin)):
            return False

    # 샘플 추가
    samp = Sample(map_x=fx, obs_x=ox, frame_w=fw, ts=ts)
    state.samples.append(samp)
    if state.first_ts == 0.0:
        state.first_ts = ts

    # 충분 샘플 전에는 추정 생략
    if len(state.samples) < 2:
        return False

    # 1차 OLS
    pairs_all = [(s.map_x, s.obs_x) for s in state.samples]
    fit = _ols_fit(pairs_all)
    if fit is None:
        a0 = state.a if state.a is not None else None
        b0 = state.b if state.b is not None else None
        if a0 is None or b0 is None:
            return False
    a0, b0 = float(a0), float(b0)

    # 잔차 기반 인라이어 추리기
    residuals = [abs(s.obs_x - (a0 * s.map_x + b0)) for s in state.samples]
    # 인라이어 임계값: RMSE 임계 기반(3×thr 또는 40px)과 폭 비례 상한(12%W) 중 작은 값
    fw_last = state.samples[-1].frame_w
    thr_rmse = _rmse_threshold(fw_last)
    inlier_cap = max(40.0, 3.0 * thr_rmse)
    inlier_thresh = min(max_residual_px, inlier_cap)
    inliers_idx = [i for i, r in enumerate(residuals) if r <= inlier_thresh]
    if len(inliers_idx) < 2:
        state.last_note = "인라이어 부족"
        state.ok_streak = 0
        # 닉네임-미니맵 차이를 즉시 바이어스로 소폭 반영
        try:
            x_hat = float(a0) * fx + float(b0) + float(state.live_bias)
            delta = float(ox - x_hat)
            cap = (fw * 0.2) if fw > 1.0 else 80.0
            alpha = 0.25 if _NARROW_MAP_MODE else 0.15
            state.live_bias = float((1.0 - alpha) * float(state.live_bias) + alpha * max(-cap, min(cap, delta)))
        except Exception:
            pass
        return False
    inlier_pairs = [pairs_all[i] for i in inliers_idx]
    # 가중치 계산(시간 감쇠 + 잔차 기반 소프트 가중)
    inlier_samples = [state.samples[i] for i in inliers_idx]
    now_ts_eff = ts
    w_time = [math.exp(-max(0.0, (now_ts_eff - s.ts)) / max(1e-3, WLS_TIME_DECAY_TAU_SEC)) for s in inlier_samples]
    # 잔차 기준 소프트 가중: w = 1/(1+(r/r0)^2)
    r0 = max(1.0, max_residual_px / 3.0)
    w_res = [1.0 / (1.0 + (abs(s.obs_x - (a0 * s.map_x + b0)) / r0) ** 2.0) for s in inlier_samples]
    weights = [wt * wr for wt, wr in zip(w_time, w_res)]
    fit2 = _wls_fit(inlier_pairs, weights)
    if fit2 is None:
        return False
    a, b = fit2

    # map_x 분산 체크(수평 이동 부족): a 업데이트 보류
    std_x = _compute_std([p[0] for p in inlier_pairs])
    if std_x < _min_std_mapx_threshold():
        # 맵 이동이 부족: 좁은맵 모드에서는 'b만 보정'(EMA), 기본 모드는 보류
        if _NARROW_MAP_MODE:
            a_curr = float(state.a) if state.a is not None else float(a0)
            # 고정 a에서 최적 b = 평균(y - a*x) (가중치 사용)
            sw = 0.0
            sy_ax = 0.0
            for (x, y), w in zip(inlier_pairs, weights):
                sw += w
                sy_ax += w * (y - a_curr * x)
            if sw > 0.0:
                b_fixed = sy_ax / sw
                if state.b is None:
                    state.b = float(b_fixed)
                else:
                    state.b = float((1.0 - B_EMA_ALPHA_NARROW) * float(state.b) + B_EMA_ALPHA_NARROW * float(b_fixed))
                state.a = float(a_curr)
                # RMSE(보고용) 계산
                errs_n = [abs(y - (state.a * x + state.b)) for x, y in inlier_pairs]
                rmse_n = math.sqrt(sum(e * e for e in errs_n) / len(errs_n))
                state.last_fit_rmse = float(rmse_n)
                state.last_fit_inliers = int(len(inlier_pairs))
                state.last_fit_ts = ts
                state.last_note = "좁은맵: b만 보정"
                # 수렴 판단(좁은맵에서도 동일 조건)
                thr_here = _rmse_threshold(fw_last)
                ok = (state.last_fit_inliers >= _min_inliers_save()) and (state.last_fit_rmse <= thr_here)
                state.ok_streak = state.ok_streak + 1 if ok else 0
                alive_sec = ts - (state.first_ts or ts)
                if ok and state.ok_streak >= CONSEC_OK_REQUIRED and alive_sec >= MIN_OBS_WINDOW_SEC:
                    try:
                        _save_params(profile, roi, state.a, state.b)
                    except Exception:
                        return False
                    state.frozen = True
                    state.samples.clear()
                    return True
                return False
        # 기본 모드: 보류
        state.last_note = "맵X 이동 부족으로 기울기 추정 보류"
        state.ok_streak = 0
        return False

    # RMSE 계산
    errs = [abs(y - (a * x + b)) for x, y in inlier_pairs]
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    prev_rmse = state.last_fit_rmse
    # 품질 게이트: RMSE가 급증하면 추정 거부
    threshold = _rmse_threshold(state.samples[-1].frame_w)
    if (prev_rmse is not None and rmse > min(prev_rmse * 1.5, threshold * 2.0)) or (rmse > threshold * 3.0):
        state.last_note = f"RMSE 증가로 추정 거부({rmse:.1f})"
        state.ok_streak = 0
        return False
    state.a, state.b = float(a), float(b)
    state.last_fit_rmse = float(rmse)
    state.last_fit_inliers = int(len(inlier_pairs))
    state.last_fit_ts = ts
    state.last_note = None

    # 수렴 판단
    threshold = _rmse_threshold(state.samples[-1].frame_w)
    ok = (state.last_fit_inliers >= _min_inliers_save()) and (rmse <= threshold)
    state.ok_streak = state.ok_streak + 1 if ok else 0

    # 시간 조건
    alive_sec = ts - (state.first_ts or ts)
    if ok and state.ok_streak >= CONSEC_OK_REQUIRED and alive_sec >= MIN_OBS_WINDOW_SEC:
        # 저장 & 동결(옵션)
        if _AUTO_SAVE:
            try:
                _save_params(profile, roi, state.a, state.b)
            except Exception:
                # 저장 실패해도 동결은 수행하지 않음(다음 기회에 재시도)
                return False
            if _FREEZE_AFTER_SAVE:
                state.frozen = True
                state.samples.clear()
            return True

    return False


def export_status(profile: str, roi: dict | None) -> Optional[dict]:
    """현재 온라인 보정 상태/지표를 조회.

    반환 예시:
    {
      'frozen': bool,
      'has_saved': bool,
      'a': float|None,
      'b': float|None,
      'rmse': float|None,
      'inliers': int,
      'samples': int,
      'ok_streak': int,
      'alive_sec': float,
      'threshold': float|None,
    }
    """
    k = _key(profile, roi)
    if k is None:
        return None
    # 저장값 확인
    saved = None
    try:
        saved = _find_saved_params(profile, roi)
    except Exception:
        saved = None
    state = _STATES.get(k)
    if state is None:
        # 온라인 상태 없음: 저장값 유무만 보고 반환
        base = {
            'frozen': bool(saved is not None),
            'has_saved': bool(saved is not None),
            'a': float(saved[0]) if saved else None,
            'b': float(saved[1]) if saved else None,
            'rmse': None,
            'inliers': 0,
            'samples': 0,
            'ok_streak': 0,
            'alive_sec': 0.0,
            'threshold': None,
        }
        base['targets'] = {
            'inliers': int(MIN_INLIERS_SAVE),
            'streak': int(CONSEC_OK_REQUIRED),
            'time_sec': float(MIN_OBS_WINDOW_SEC),
        }
        base['progress_pct'] = 100 if saved is not None else 0
        return base
    # 온라인 상태 존재
    thr = None
    if state.samples:
        fw = float(state.samples[-1].frame_w)
        thr = _rmse_threshold(fw)
    # 진행도 계산
    progress_pct = 0
    try:
        if saved is not None or state.frozen:
            progress_pct = 100
        else:
            # ratios
            rmse_ratio = 0.0
            if thr is not None and state.last_fit_rmse is not None and float(thr) > 1e-9:
                rmse_ratio = max(0.0, min(1.0, (float(thr) - float(state.last_fit_rmse)) / float(thr)))
            inl_ratio = max(0.0, min(1.0, float(state.last_fit_inliers) / float(_min_inliers_save())))
            streak_ratio = max(0.0, min(1.0, float(state.ok_streak) / float(CONSEC_OK_REQUIRED)))
            time_ratio = max(0.0, min(1.0, float((time.time() - state.first_ts) if state.first_ts else 0.0) / float(MIN_OBS_WINDOW_SEC)))
            score = 0.4 * rmse_ratio + 0.3 * streak_ratio + 0.2 * inl_ratio + 0.1 * time_ratio
            progress_pct = int(round(max(0.0, min(1.0, score)) * 100.0))
    except Exception:
        progress_pct = 0

    return {
        'frozen': bool(state.frozen or (saved is not None)),
        'has_saved': bool(saved is not None),
        'a': float(state.a) if state.a is not None else (float(saved[0]) if saved else None),
        'b': float(state.b) if state.b is not None else (float(saved[1]) if saved else None),
        'rmse': float(state.last_fit_rmse) if state.last_fit_rmse is not None else None,
        'inliers': int(state.last_fit_inliers),
        'samples': int(len(state.samples)),
        'ok_streak': int(state.ok_streak),
        'alive_sec': float((time.time() - state.first_ts) if state.first_ts else 0.0),
        'threshold': thr,
        'targets': {
            'inliers': int(MIN_INLIERS_SAVE),
            'streak': int(CONSEC_OK_REQUIRED),
            'time_sec': float(MIN_OBS_WINDOW_SEC),
        },
        'progress_pct': int(progress_pct),
        'note': state.last_note,
        'narrow_mode': bool(_NARROW_MAP_MODE),
        'min_std_mapx': float(_min_std_mapx_threshold()),
        'live_bias': float(state.live_bias),
        'flags': {
            'online_enabled': bool(_ONLINE_ENABLED),
            'apply_online': bool(_APPLY_ONLINE),
            'auto_save': bool(_AUTO_SAVE),
            'freeze_after_save': bool(_FREEZE_AFTER_SAVE),
        },
    }


def get(profile: str, roi: dict | None) -> Optional[Tuple[float, float]]:
    """온라인 추정 (a,b)을 반환. 없으면 None.

    - 동결된 경우 None을 반환하여 저장값(find_calibration) 사용을 유도
    - 2개 이상 유효 샘플 기반 추정이 있어야 반환
    """
    k = _key(profile, roi)
    if k is None:
        return None
    state = _STATES.get(k)
    if state is None:
        return None
    if state.frozen:
        return None
    if not _APPLY_ONLINE:
        return None
    if state.a is None or state.b is None:
        return None
    # 저장값이 있고 '저장 후 동결' 정책이 켜져 있으면 온라인 적용 억제
    try:
        saved = _find_saved_params(profile, roi)
        if saved is not None and _FREEZE_AFTER_SAVE:
            return None
    except Exception:
        pass
    # 품질 게이트: RMSE가 임계보다 큰 동안 온라인 값을 소비하지 않음
    if state.samples:
        fw = float(state.samples[-1].frame_w)
        thr = _rmse_threshold(fw)
        min_half_inliers = max(4, _min_inliers_save() // 2)
        if (state.last_fit_rmse is None) or (float(state.last_fit_rmse) > thr * 1.2) or (int(state.last_fit_inliers) < min_half_inliers):
            return None
    return float(state.a), float((state.b if state.b is not None else 0.0) + state.live_bias)


def reset(profile: str, roi: dict | None) -> None:
    """해당 키의 온라인 추정 상태만 초기화(저장 파일은 건드리지 않음)."""
    k = _key(profile, roi)
    if k is None:
        return
    _STATES.pop(k, None)
