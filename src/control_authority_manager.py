"""사냥/맵 탭 권한을 중앙에서 관리하는 ControlAuthorityManager."""

from __future__ import annotations

import dataclasses
import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Literal, Optional, Protocol

from PyQt6.QtCore import QObject, pyqtSignal

AuthorityOwner = Literal["map", "hunt"]
PRIORITY_EVENT_TIMEOUT_SEC = 5.0
DEFAULT_MAP_PROTECT_SEC = 3.0
DEFAULT_MAX_FLOOR_HOLD_SEC = 120.0
DEFAULT_MAX_TOTAL_HOLD_SEC = 180.0
RECENT_SNAPSHOT_THRESHOLD_SEC = 0.5
PENDING_RETRY_DELAY_SEC = 0.2


class AuthorityDecisionStatus(str, enum.Enum):
    """권한 요청 평가 결과."""

    ACCEPTED = "accepted"
    PENDING = "pending"
    REJECTED = "rejected"
    NOOP = "noop"


@dataclass(slots=True)
class PlayerStatusSnapshot:
    """맵 탭이 제공하는 최신 플레이어 상태 스냅샷."""

    timestamp: float
    floor: Optional[float]
    player_state: str
    navigation_action: str
    horizontal_velocity: float
    last_move_command: Optional[str]
    is_forbidden_active: bool
    is_event_active: bool
    priority_override: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "floor": self.floor,
            "player_state": self.player_state,
            "navigation_action": self.navigation_action,
            "horizontal_velocity": self.horizontal_velocity,
            "last_move_command": self.last_move_command,
            "is_forbidden_active": self.is_forbidden_active,
            "is_event_active": self.is_event_active,
            "priority_override": self.priority_override,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class HuntConditionSnapshot:
    """사냥 탭이 제공하는 최신 몬스터/탐지 스냅샷."""

    timestamp: float
    monster_count: int
    primary_monster_count: int
    hunt_monster_threshold: int
    primary_monster_threshold: int
    idle_release_seconds: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_recent(self) -> bool:
        return (time.time() - self.timestamp) <= RECENT_SNAPSHOT_THRESHOLD_SEC

    def as_payload(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "monster_count": self.monster_count,
            "primary_monster_count": self.primary_monster_count,
            "hunt_monster_threshold": self.hunt_monster_threshold,
            "primary_monster_threshold": self.primary_monster_threshold,
            "idle_release_seconds": self.idle_release_seconds,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AuthorityState:
    """현재 권한 소유 상태."""

    owner: AuthorityOwner
    held_since: float
    floor_at_acquire: Optional[float]
    protect_until: float
    map_priority_lock: Optional[str] = None

    def as_payload(self) -> Dict[str, Any]:
        return {
            "owner": self.owner,
            "held_since": self.held_since,
            "floor_at_acquire": self.floor_at_acquire,
            "protect_until": self.protect_until,
            "map_priority_lock": self.map_priority_lock,
        }


@dataclass(slots=True)
class AuthorityRequest:
    """대기 중인 권한 요청 정보."""

    requester: AuthorityOwner
    reason: str
    meta: Dict[str, Any]
    hunt_snapshot: Optional[HuntConditionSnapshot]
    requested_at: float
    failed_reasons: Iterable[str] = field(default_factory=tuple)
    next_retry_ts: float = 0.0

    def as_payload(self) -> Dict[str, Any]:
        return {
            "requester": self.requester,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "failed_reasons": list(self.failed_reasons),
            "hunt_snapshot": self.hunt_snapshot.as_payload() if self.hunt_snapshot else None,
            "meta": dict(self.meta),
        }


@dataclass(slots=True)
class AuthorityDecision:
    status: AuthorityDecisionStatus
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)


class AuthoritySnapshotProvider(Protocol):
    """맵 탭이 구현해야 하는 인터페이스."""

    def collect_authority_snapshot(self) -> Optional[PlayerStatusSnapshot]:
        ...


class AuthorityDecisionListener(Protocol):
    """사냥 탭 측 콜백 타입 정의."""

    def on_authority_changed(self, owner: AuthorityOwner, meta: Dict[str, Any]) -> None:
        ...


class ControlAuthorityManager(QObject):
    """맵/사냥 탭 간 권한을 중앙에서 조정하는 매니저."""

    authority_changed = pyqtSignal(str, dict)
    request_evaluated = pyqtSignal(str, dict)
    priority_event_triggered = pyqtSignal(str, dict)

    _instance: Optional["ControlAuthorityManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        super().__init__()
        now = time.time()
        self._state = AuthorityState(
            owner="map",
            held_since=now,
            floor_at_acquire=None,
            protect_until=now + DEFAULT_MAP_PROTECT_SEC,
        )
        self._map_provider: Optional[AuthoritySnapshotProvider] = None
        self._last_map_snapshot: Optional[PlayerStatusSnapshot] = None
        self._pending_hunt_request: Optional[AuthorityRequest] = None
        self._pending_map_request: Optional[AuthorityRequest] = None
        self._hunt_settings = {
            "map_protect_sec": DEFAULT_MAP_PROTECT_SEC,
            "floor_hold_sec": DEFAULT_MAX_FLOOR_HOLD_SEC,
            "max_total_hold_sec": DEFAULT_MAX_TOTAL_HOLD_SEC,
        }
        self._metrics = {
            "handover_count": 0,
            "total_wait_time": 0.0,
        }
        self._priority_lock_deadline: float = 0.0
        self._mutex = threading.RLock()

    # ------------------------------------------------------------------
    # 싱글턴 관리
    # ------------------------------------------------------------------
    @classmethod
    def instance(cls) -> "ControlAuthorityManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------
    # 외부 연동 API
    # ------------------------------------------------------------------
    def register_map_provider(self, provider: AuthoritySnapshotProvider) -> None:
        with self._mutex:
            self._map_provider = provider

    def update_hunt_settings(
        self,
        *,
        map_protect_sec: Optional[float] = None,
        floor_hold_sec: Optional[float] = None,
        max_total_hold_sec: Optional[float] = None,
    ) -> None:
        with self._mutex:
            if map_protect_sec is not None and map_protect_sec > 0:
                self._hunt_settings["map_protect_sec"] = max(map_protect_sec, 0.1)
            if floor_hold_sec is not None and floor_hold_sec > 0:
                self._hunt_settings["floor_hold_sec"] = max(floor_hold_sec, 1.0)
            if max_total_hold_sec is not None and max_total_hold_sec > 0:
                self._hunt_settings["max_total_hold_sec"] = max(max_total_hold_sec, 1.0)

    def update_map_snapshot(self, snapshot: PlayerStatusSnapshot, *, source: str) -> None:
        with self._mutex:
            self._last_map_snapshot = snapshot
            if self._state.owner == "map" and snapshot.floor is not None:
                self._state.floor_at_acquire = snapshot.floor
            self._evaluate_pending_requests(trigger="map_snapshot", source=source)

    def request_control(
        self,
        requester: AuthorityOwner,
        *,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
        hunt_snapshot: Optional[HuntConditionSnapshot] = None,
    ) -> AuthorityDecision:
        with self._mutex:
            meta = dict(meta or {})
            now = time.time()

            if requester == self._state.owner:
                decision = AuthorityDecision(
                    status=AuthorityDecisionStatus.NOOP,
                    reason="already_owner",
                    payload=self._state.as_payload(),
                )
                self._emit_request_result(requester, decision, meta)
                return decision

            if requester == "hunt":
                decision = self._evaluate_hunt_request(now, reason, meta, hunt_snapshot)
            else:
                decision = self._evaluate_map_request(now, reason, meta)

            if decision.status == AuthorityDecisionStatus.ACCEPTED:
                self._transition_to(requester, source="request", reason=reason, meta=meta)
            elif decision.status == AuthorityDecisionStatus.PENDING:
                self._store_pending_request(
                    AuthorityRequest(
                        requester=requester,
                        reason=reason,
                        meta=meta,
                        hunt_snapshot=hunt_snapshot,
                        requested_at=now,
                        failed_reasons=decision.payload.get("failed", []),
                        next_retry_ts=now + PENDING_RETRY_DELAY_SEC,
                    )
                )

            self._emit_request_result(requester, decision, meta)
            return decision

    def release_control(
        self,
        requester: AuthorityOwner,
        *,
        reason: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> AuthorityDecision:
        with self._mutex:
            meta = dict(meta or {})
            now = time.time()

            if requester != self._state.owner:
                decision = AuthorityDecision(
                    status=AuthorityDecisionStatus.REJECTED,
                    reason="not_owner",
                    payload={"owner": self._state.owner},
                )
                self._emit_request_result(requester, decision, meta)
                return decision

            next_owner: AuthorityOwner = "map" if requester == "hunt" else "hunt"
            decision = AuthorityDecision(
                status=AuthorityDecisionStatus.ACCEPTED,
                reason=reason,
                payload={"requested_at": now},
            )
            self._transition_to(next_owner, source="release", reason=reason, meta=meta)
            self._emit_request_result(requester, decision, meta)
            return decision

    def notify_priority_event(self, kind: str, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._mutex:
            metadata = dict(metadata or {})
            self._priority_lock_deadline = time.time() + PRIORITY_EVENT_TIMEOUT_SEC
            self._state.map_priority_lock = kind
            if self._state.owner != "map":
                self._transition_to("map", source="priority", reason=kind, meta=metadata)
            self.priority_event_triggered.emit(kind, metadata)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _emit_request_result(
        self,
        requester: AuthorityOwner,
        decision: AuthorityDecision,
        meta: Dict[str, Any],
    ) -> None:
        payload = {
            "requester": requester,
            "status": decision.status.value,
            "reason": decision.reason,
            "meta": meta,
        }
        if decision.payload:
            payload["payload"] = decision.payload
        self.request_evaluated.emit(requester, payload)

    def _store_pending_request(self, request: AuthorityRequest) -> None:
        if request.requester == "hunt":
            self._pending_hunt_request = request
        else:
            self._pending_map_request = request

    def _evaluate_pending_requests(self, *, trigger: str, source: str) -> None:
        now = time.time()
        if self._priority_lock_deadline and now > self._priority_lock_deadline:
            self._state.map_priority_lock = None
            self._priority_lock_deadline = 0.0

        if (
            self._pending_hunt_request
            and now >= self._pending_hunt_request.next_retry_ts
        ):
            request = self._pending_hunt_request
            hunt_snapshot = request.hunt_snapshot
            decision = self._evaluate_hunt_request(
                now,
                request.reason,
                request.meta,
                hunt_snapshot,
            )
            if decision.status == AuthorityDecisionStatus.ACCEPTED:
                self._transition_to("hunt", source=trigger, reason=request.reason, meta=request.meta)
                self._pending_hunt_request = None
            else:
                self._pending_hunt_request = dataclasses.replace(
                    request,
                    failed_reasons=decision.payload.get("failed", []),
                    next_retry_ts=now + PENDING_RETRY_DELAY_SEC,
                )
        if (
            self._pending_map_request
            and now >= self._pending_map_request.next_retry_ts
        ):
            request = self._pending_map_request
            decision = self._evaluate_map_request(now, request.reason, request.meta)
            if decision.status == AuthorityDecisionStatus.ACCEPTED:
                self._transition_to("map", source=trigger, reason=request.reason, meta=request.meta)
                self._pending_map_request = None
            else:
                self._pending_map_request = dataclasses.replace(
                    request,
                    failed_reasons=decision.payload.get("failed", []),
                    next_retry_ts=now + PENDING_RETRY_DELAY_SEC,
                )

    def _get_map_snapshot(self) -> Optional[PlayerStatusSnapshot]:
        if self._map_provider:
            snapshot = self._map_provider.collect_authority_snapshot()
            if snapshot:
                self._last_map_snapshot = snapshot
        return self._last_map_snapshot

    def _evaluate_hunt_request(
        self,
        now: float,
        reason: str,
        meta: Dict[str, Any],
        hunt_snapshot: Optional[HuntConditionSnapshot],
    ) -> AuthorityDecision:
        map_snapshot = self._get_map_snapshot()
        failed: list[str] = []

        if not map_snapshot:
            failed.append("MAP_SNAPSHOT_MISSING")
        else:
            if map_snapshot.player_state not in {"on_terrain", "idle"}:
                failed.append("MAP_NOT_WALKING")
            if not self._is_map_idle_ready(map_snapshot):
                failed.append("MAP_STATE_ACTIVE")
            if not self._is_map_protect_passed(now, map_snapshot):
                failed.append("MAP_PROTECT_ACTIVE")
            if self._state.map_priority_lock:
                failed.append("MAP_PRIORITY_LOCK")

        if hunt_snapshot:
            if not hunt_snapshot.is_recent():
                failed.append("HUNT_SNAPSHOT_OUTDATED")
            primary_ready = (
                hunt_snapshot.primary_monster_threshold <= 0
                or hunt_snapshot.primary_monster_count >= hunt_snapshot.primary_monster_threshold
            )
            hunt_ready = (
                hunt_snapshot.hunt_monster_threshold <= 0
                or hunt_snapshot.monster_count >= hunt_snapshot.hunt_monster_threshold
            )
            if not primary_ready and not hunt_ready:
                failed.append("HUNT_MONSTER_SHORTAGE")
        else:
            failed.append("HUNT_SNAPSHOT_MISSING")

        if failed:
            return AuthorityDecision(
                status=AuthorityDecisionStatus.PENDING,
                reason="conditions_not_met",
                payload={
                    "failed": failed,
                    "map_snapshot": map_snapshot.as_payload() if map_snapshot else None,
                    "hunt_snapshot": hunt_snapshot.as_payload() if hunt_snapshot else None,
                    "meta": meta,
                },
            )

        return AuthorityDecision(
            status=AuthorityDecisionStatus.ACCEPTED,
            reason=reason,
            payload={
                "elapsed_since_owner_change": now - self._state.held_since,
                "map_snapshot": map_snapshot.as_payload(),
                "hunt_snapshot": hunt_snapshot.as_payload(),
            },
        )

    def _evaluate_map_request(
        self,
        now: float,
        reason: str,
        meta: Dict[str, Any],
    ) -> AuthorityDecision:
        failed: list[str] = []
        if self._state.owner == "map":
            failed.append("MAP_ALREADY_OWNER")
        else:
            hold_limit = self._hunt_settings.get("max_total_hold_sec", DEFAULT_MAX_TOTAL_HOLD_SEC)
            if hold_limit and (now - self._state.held_since) < hold_limit:
                failed.append("HOLD_LIMIT_NOT_REACHED")
        if failed:
            return AuthorityDecision(
                status=AuthorityDecisionStatus.PENDING,
                reason="conditions_not_met",
                payload={"failed": failed, "meta": meta},
            )
        return AuthorityDecision(
            status=AuthorityDecisionStatus.ACCEPTED,
            reason=reason,
            payload={}
        )

    def _is_map_idle_ready(self, snapshot: PlayerStatusSnapshot) -> bool:
        if snapshot.priority_override:
            return True
        if snapshot.is_forbidden_active or snapshot.is_event_active:
            return False
        navigation_ok = snapshot.navigation_action in {"move_to_target", "resume_after_event", "idle"}
        state_ok = snapshot.player_state in {"idle", "on_terrain"}
        # NOTE: 캐릭터가 지상에서 걷고 있는 상황에서도 사냥 탭이 권한을 얻을 수 있도록
        # 속도 조건은 제거하고, 공중/이벤트 여부만 체크한다.
        return navigation_ok and state_ok

    def _is_map_protect_passed(self, now: float, snapshot: PlayerStatusSnapshot) -> bool:
        if snapshot.priority_override:
            return True
        protect_until = self._state.protect_until
        return now >= protect_until

    def _transition_to(
        self,
        owner: AuthorityOwner,
        *,
        source: str,
        reason: str,
        meta: Dict[str, Any],
    ) -> None:
        now = time.time()
        previous_owner = self._state.owner
        elapsed = now - self._state.held_since
        protect_sec = self._hunt_settings.get("map_protect_sec", DEFAULT_MAP_PROTECT_SEC)

        floor = None
        snapshot = self._last_map_snapshot
        if snapshot:
            floor = snapshot.floor

        self._state = AuthorityState(
            owner=owner,
            held_since=now,
            floor_at_acquire=floor,
            protect_until=now + protect_sec if owner == "map" else now,
            map_priority_lock=self._state.map_priority_lock if owner == "map" else None,
        )

        self._metrics["handover_count"] += 1
        self._metrics["total_wait_time"] += max(0.0, elapsed)

        payload = {
            "owner": owner,
            "previous_owner": previous_owner,
            "reason": reason,
            "source": source,
            "elapsed_since_previous": elapsed,
            "meta": meta,
            "state": self._state.as_payload(),
        }
        if snapshot:
            payload["map_snapshot"] = snapshot.as_payload()

        self.authority_changed.emit(owner, payload)

    # ------------------------------------------------------------------
    # 진단/메트릭
    # ------------------------------------------------------------------
    def current_state(self) -> AuthorityState:
        with self._mutex:
            return dataclasses.replace(self._state)

    def metrics(self) -> Dict[str, Any]:
        with self._mutex:
            return dict(self._metrics)


__all__ = [
    "AuthorityDecision",
    "AuthorityDecisionStatus",
    "AuthorityOwner",
    "AuthorityRequest",
    "AuthoritySnapshotProvider",
    "HuntConditionSnapshot",
    "PlayerStatusSnapshot",
    "ControlAuthorityManager",
    "DEFAULT_MAP_PROTECT_SEC",
    "DEFAULT_MAX_FLOOR_HOLD_SEC",
    "DEFAULT_MAX_TOTAL_HOLD_SEC",
]
