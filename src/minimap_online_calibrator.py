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
MAX_RESIDUAL_RATIO = 0.25  # 25% * frame_width 초과 잔차 이상치 제외
MIN_STD_MAPX = 120.0  # 맵 X 표준편차가 너무 작으면 a 업데이트 보류
MIN_INLIERS_SAVE = 20
RMSE_THRESH_PX_MIN = 8.0
RMSE_THRESH_RATIO = 0.02  # 2% * frame_width
CONSEC_OK_REQUIRED = 12
MIN_OBS_WINDOW_SEC = 5.0


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
    last_fit_rmse: Optional[float] = None
    last_fit_inliers: int = 0
    last_fit_ts: float = 0.0
    ok_streak: int = 0
    frozen: bool = False
    first_ts: float = 0.0


_STATES: Dict[Tuple[str, str], OnlineState] = {}


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
        if saved is not None:
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
        return False
    a0, b0 = fit

    # 잔차 기반 인라이어 추리기
    residuals = [abs(s.obs_x - (a0 * s.map_x + b0)) for s in state.samples]
    inliers_idx = [i for i, r in enumerate(residuals) if r <= max_residual_px]
    if len(inliers_idx) < 2:
        return False
    inlier_pairs = [pairs_all[i] for i in inliers_idx]
    fit2 = _ols_fit(inlier_pairs)
    if fit2 is None:
        return False
    a, b = fit2

    # map_x 분산 체크(수평 이동 부족): a 업데이트 보류
    std_x = _compute_std([p[0] for p in inlier_pairs])
    if std_x < MIN_STD_MAPX and state.a is not None:
        # a는 유지, b만 최신 잔차 중앙값으로 보정 유도(간단화: 기존 b 유지)
        a = float(state.a)
        # b 업데이트는 보수적으로: 유지
        b = float(state.b) if state.b is not None else float(b)

    # RMSE 계산
    errs = [abs(y - (a * x + b)) for x, y in inlier_pairs]
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    state.a, state.b = float(a), float(b)
    state.last_fit_rmse = float(rmse)
    state.last_fit_inliers = int(len(inlier_pairs))
    state.last_fit_ts = ts

    # 수렴 판단
    threshold = max(RMSE_THRESH_PX_MIN, (state.samples[-1].frame_w * RMSE_THRESH_RATIO) if state.samples[-1].frame_w > 1.0 else RMSE_THRESH_PX_MIN)
    ok = (state.last_fit_inliers >= MIN_INLIERS_SAVE) and (rmse <= threshold)
    state.ok_streak = state.ok_streak + 1 if ok else 0

    # 시간 조건
    alive_sec = ts - (state.first_ts or ts)
    if ok and state.ok_streak >= CONSEC_OK_REQUIRED and alive_sec >= MIN_OBS_WINDOW_SEC:
        # 저장 & 동결
        try:
            _save_params(profile, roi, state.a, state.b)
        except Exception:
            # 저장 실패해도 동결은 수행하지 않음(다음 기회에 재시도)
            return False
        # 저장 성공 → 동결
        state.frozen = True
        # 메모리 최적화: 버퍼 비우기
        state.samples.clear()
        return True

    return False


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
    if state.a is None or state.b is None:
        return None
    return float(state.a), float(state.b)


def reset(profile: str, roi: dict | None) -> None:
    """해당 키의 온라인 추정 상태만 초기화(저장 파일은 건드리지 않음)."""
    k = _key(profile, roi)
    if k is None:
        return
    _STATES.pop(k, None)
