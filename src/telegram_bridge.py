"""Qt 앱 내부에서 동작하는 텔레그램 브리지.

요구사항 요약
- 한글/영문 명령 모두 지원
- 현재 프로그램 내부 상태/로직 사용(사냥탭의 캐시/예약 로직 그대로 호출)
- credentials.py에서 토큰/Chat ID 로드
- Windows 환경에서만 활성 (화면 캡처/프로세스 종료 연동을 위해)
"""

from __future__ import annotations

import importlib.util
import io
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import QApplication


def _is_windows() -> bool:
    return os.name == "nt"


@dataclass
class _Credentials:
    token: str
    allowed_chat_id: Optional[int]


def _load_credentials() -> Optional[_Credentials]:
    """다음 우선순위로 자격 정보를 로드한다.
    1) workspace/config/telegram.json (KEY="VALUE" 형식)
    2) workspace/config/telegram/credentials.py (기존 폴백)
    3) 환경변수 BOT_TOKEN / ALLOWED_CHAT_IDS
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1) telegram.json (KEY="VALUE" 텍스트)
    #    고정 경로(G:\\Coding\\Project_Maple\\workspace\\config\\telegram.json) 우선
    fixed_path = r"G:\\Coding\\Project_Maple\\workspace\\config\\telegram.json"
    json_like_path = fixed_path if os.path.exists(fixed_path) else os.path.join(base, "workspace", "config", "telegram.json")
    if os.path.exists(json_like_path):
        try:
            with open(json_like_path, "r", encoding="utf-8-sig") as fp:
                lines = fp.readlines()
        except Exception:
            lines = []
        kv: dict[str, str] = {}
        import re

        pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\'\"])(.*?)\2\s*$")
        for raw in lines:
            m = pattern.match(raw.strip())
            if not m:
                continue
            key, _, val = m.groups()
            kv[key] = val
        token = kv.get("TELEGRAM_BOT_TOKEN", "")
        chat_raw = kv.get("TELEGRAM_CHAT_ID", "")
        chat_id: Optional[int] = None
        try:
            if chat_raw:
                chat_id = int(chat_raw.strip().split(",")[0])
        except Exception:
            chat_id = None
        if token:
            return _Credentials(token=token, allowed_chat_id=chat_id)

    # 2) credentials.py (폴백)
    py_path = os.path.join(base, "workspace", "config", "telegram", "credentials.py")
    if os.path.exists(py_path):
        spec = importlib.util.spec_from_file_location("telegram_credentials", py_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:
                module = None
            if module is not None:
                token = getattr(module, "TELEGRAM_BOT_TOKEN", None) or ""
                chat_raw = getattr(module, "TELEGRAM_CHAT_ID", None) or ""
                chat_id: Optional[int] = None
                try:
                    if isinstance(chat_raw, str) and chat_raw.strip():
                        first = chat_raw.split(",")[0].strip()
                        chat_id = int(first)
                    elif isinstance(chat_raw, int):
                        chat_id = int(chat_raw)
                except (TypeError, ValueError):
                    chat_id = None
                if token:
                    return _Credentials(token=token, allowed_chat_id=chat_id)

    # 3) 환경변수 (최종 폴백)
    token = os.environ.get("BOT_TOKEN") or ""
    chat_raw = os.environ.get("ALLOWED_CHAT_IDS") or ""
    chat_id: Optional[int] = None
    try:
        if chat_raw and "," not in chat_raw:
            chat_id = int(chat_raw.strip())
    except ValueError:
        chat_id = None
    if token:
        return _Credentials(token=token, allowed_chat_id=chat_id)
    return None


_INVOKER: Optional["_MainThreadInvoker"] = None


class _MainThreadInvoker(QObject):
    callRequested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        # QueuedConnection 보장: emit를 타 스레드에서 호출해도 수신은 객체 소유 스레드에서 실행
        self.callRequested.connect(self._on_call, Qt.ConnectionType.QueuedConnection)

    def _on_call(self, fn: Callable[[], None]) -> None:  # pragma: no cover - 간단 위임
        try:
            fn()
        except Exception:
            raise


def _ensure_invoker_initialized() -> None:
    global _INVOKER
    if _INVOKER is None:
        # 반드시 메인 스레드에서 생성되도록 보장
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication이 준비되지 않았습니다.")
        _INVOKER = _MainThreadInvoker()


def _run_in_main_thread(func: Callable[[], object], *, timeout: float = 5.0) -> object:
    """Qt 메인 스레드에서 func를 실행하고 결과를 동기 반환한다."""
    _ensure_invoker_initialized()
    assert _INVOKER is not None
    result_holder: dict[str, object] = {}
    event = threading.Event()

    def _wrapper() -> None:
        try:
            result_holder["value"] = func()
        except Exception as exc:  # pragma: no cover - 안전 장치
            result_holder["error"] = exc
        finally:
            event.set()

    # 메인 스레드로 큐잉
    _INVOKER.callRequested.emit(_wrapper)
    if not event.wait(timeout):
        raise TimeoutError("메인 스레드 작업이 제한시간 내에 완료되지 않았습니다.")
    if "error" in result_holder:
        raise result_holder["error"]  # type: ignore[misc]
    return result_holder.get("value")


class TelegramBridge(QObject):
    """텔레그램 명령을 받아 내부 UI/로직을 호출하는 브리지."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._hunt_tab = getattr(main_window, "loaded_tabs", {}).get("사냥")
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._creds = _load_credentials()
        self._bot_app = None
        self._loop = None  # 백그라운드 asyncio 이벤트 루프

    def available(self) -> bool:
        return _is_windows() and self._creds is not None

    def start(self) -> None:
        if not self.available() or self._running:
            return
        try:
            # 지연 임포트(미설치 시 앱은 계속 동작)
            from telegram.ext import ApplicationBuilder, MessageHandler, filters
        except Exception as exc:  # pragma: no cover - 의존성 미설치
            print(f"[TelegramBridge] python-telegram-bot 미설치 또는 임포트 오류: {exc}")
            return

        token = self._creds.token if self._creds else ""
        if not token:
            print("[TelegramBridge] 토큰이 없어 브리지를 시작하지 않습니다.")
            return

        self._running = True
        # 메인 스레드 인보커 초기화 (메인 스레드에서 호출됨)
        try:
            _ensure_invoker_initialized()
        except Exception as exc:
            print(f"[TelegramBridge] 메인 스레드 인보커 초기화 실패: {exc}")
            self._running = False
            return

        def _bot_thread() -> None:
            try:
                import asyncio

                # 전용 이벤트 루프 생성(백그라운드 스레드용)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                app = ApplicationBuilder().token(token).build()
            except Exception as exc:
                print(f"[TelegramBridge] 봇 초기화 실패: {exc}")
                self._running = False
                return

            self._bot_app = app
            self._loop = loop

            async def _handle_text(update, context):  # type: ignore[no-redef]
                try:
                    if update is None or update.effective_chat is None:
                        return
                    chat_id = int(update.effective_chat.id)
                    if self._creds and self._creds.allowed_chat_id is not None:
                        if chat_id != int(self._creds.allowed_chat_id):
                            return
                    text = (update.effective_message.text or "").strip()
                    if not text:
                        return
                    lower = text.lower()

                    # 도움말/명령어
                    if lower in ("/명령어", "/?", "/help"):
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "명령어 목록\n"
                                "- /화면 | /screen: Mapleland 창 스크린샷\n"
                                "- /정보 | /info: HP/MP/EXP 요약\n"
                                "- /정지 | /stop: 탐지 강제중단(ESC 효과)\n"
                                "- /시작 | /start: 사냥 시작\n"
                                "- /금지 | /금지몹: 금지몬스터 감지 테스트(대기 모드 진입)\n"
                                "- /금지해제: 금지 플로우 해제 후 탐지 재시작\n"
                                "- /화면출력 | /display: 사냥탭 화면출력 토글\n"
                                "- /대기모드 | /wait: 즉시 대기모드(무기한) 진입\n"
                                "- /대기종료 | /wait_end: 대기모드 해제\n"
                                "- /종료 | /exit: 즉시 대기모드로 전환해 '게임종료' 명령 실행\n"
                                "- /종료예약 n분 | /exit_in n: n분 뒤 위 플로우 실행 예약\n"
                                "- /종료예약 취소 | /cancel_exit: 예약된 게임 종료 취소\n"
                                "- /ping: 연결 확인"
                            ),
                        )
                        return

                    # ping
                    if lower == "/ping":
                        await context.bot.send_message(chat_id=chat_id, text="pong")
                        return

                    # 화면 캡처
                    if lower in ("/화면", "/screen"):
                        ok, payload = self._capture_screen()
                        if not ok:
                            await context.bot.send_message(chat_id=chat_id, text=str(payload))
                            return
                        image_bytes: bytes = payload  # type: ignore[assignment]
                        await context.bot.send_photo(chat_id=chat_id, photo=image_bytes)
                        return

                    # 정보(상태 요약)
                    if lower in ("/정보", "/info"):
                        summary = self._get_status_summary()
                        lines = [summary.get("hp", "HP: --"), summary.get("mp", "MP: --"), summary.get("exp", "EXP: --")]
                        await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))
                        return

                    # 정지
                    if lower in ("/정지", "/stop"):
                        self._global_stop()
                        await context.bot.send_message(chat_id=chat_id, text="탐지를 강제 중단했습니다.")
                        return

                    # 시작
                    if lower in ("/시작", "/start"):
                        ok, msg = self._start_hunt()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 금지몬스터 테스트 트리거
                    if lower in ("/금지", "/금지몹"):
                        ok, msg = self._trigger_forbidden_test()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 금지몬스터 해제 + 재시작
                    if lower in ("/금지해제",):
                        ok, msg = self._cancel_forbidden_test()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 화면출력 토글
                    if lower in ("/화면출력", "/display", "/screen_output"):
                        ok, msg = self._toggle_screen_output()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 대기모드(무기한) 진입
                    if lower in ("/대기모드", "/wait"):
                        ok, msg = self._enter_wait_indef()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 대기모드 해제
                    if lower in ("/대기종료", "/wait_end"):
                        ok, msg = self._exit_wait_indef()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 종료(즉시 대기 모드 → 명령 실행)
                    if lower in ("/종료", "/exit"):
                        ok, msg = self._schedule_exit_wait(seconds=0)
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 종료예약 취소
                    if lower in ("/종료예약 취소", "/cancel_exit"):
                        ok, msg = self._cancel_exit_wait()
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 종료예약 n분 | /exit_in n
                    if lower.startswith("/종료예약"):
                        minutes = _parse_minutes_korean(text)
                        if minutes is None:
                            await context.bot.send_message(chat_id=chat_id, text="형식: /종료예약 n분 (예: /종료예약 10분)")
                            return
                        ok, msg = self._schedule_exit_wait_in(minutes=minutes)
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    if lower.startswith("/exit_in"):
                        minutes = _parse_minutes_english(text)
                        if minutes is None:
                            await context.bot.send_message(chat_id=chat_id, text="Usage: /exit_in <minutes> (e.g. /exit_in 10)")
                            return
                        ok, msg = self._schedule_exit_wait_in(minutes=minutes)
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                        return

                    # 알 수 없는 명령 → 도움말
                    await context.bot.send_message(chat_id=chat_id, text="알 수 없는 명령입니다. /명령어 를 참고하세요.")
                except Exception as exc:  # pragma: no cover - 안전 장치
                    try:
                        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"오류: {exc}")
                    except Exception:
                        pass

            app.add_handler(MessageHandler(filters.TEXT, _handle_text))

            async def _amain():  # 비동기 폴링 루틴
                try:
                    await app.initialize()
                    await app.start()
                    # Updater가 존재하면 비동기 start_polling 호출
                    updater = getattr(app, "updater", None)
                    if updater and hasattr(updater, "start_polling"):
                        coro = updater.start_polling()
                        # start_polling이 코루틴이면 await
                        if hasattr(coro, "__await__"):
                            await coro
                    # 실행 유지 루프
                    while self._running:
                        await asyncio.sleep(0.5)
                finally:
                    try:
                        updater = getattr(app, "updater", None)
                        if updater and hasattr(updater, "stop"):
                            coro = updater.stop()
                            if hasattr(coro, "__await__"):
                                await coro
                    except Exception:
                        pass
                    try:
                        await app.stop()
                    except Exception:
                        pass
                    try:
                        await app.shutdown()
                    except Exception:
                        pass

            try:
                loop.run_until_complete(_amain())
            except Exception as exc:
                print(f"[TelegramBridge] 폴링 종료: {exc}")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                self._running = False

        self._thread = threading.Thread(target=_bot_thread, name="TelegramBridgeThread", daemon=True)
        self._thread.start()
        print("[TelegramBridge] 시작됨")

    def stop(self) -> None:
        self._running = False
        app = self._bot_app
        # stop()는 비동기 루틴의 종료 루프를 깨우는 용도로 사용
        try:
            # 아무 것도 하지 않아도 루프는 0.5초 내 종료됨
            pass
        except Exception:
            pass
        self._bot_app = None

    # ---------------- 내부 로직(메인 스레드 접근 포함) ----------------
    def _get_status_summary(self) -> dict:
        if self._hunt_tab is None:
            return {"hp": "HP: --", "mp": "MP: --", "exp": "EXP: --"}

        def _call():
            if hasattr(self._hunt_tab, "api_get_status_summary"):
                return dict(self._hunt_tab.api_get_status_summary())
            # 폴백: 내부 캐시 직접 접근
            cache = getattr(self._hunt_tab, "_status_summary_cache", {}) or {}
            return dict(cache)

        try:
            result = _run_in_main_thread(_call)
        except Exception:
            return {"hp": "HP: --", "mp": "MP: --", "exp": "EXP: --"}
        return result if isinstance(result, dict) else {"hp": "HP: --", "mp": "MP: --", "exp": "EXP: --"}

    def _global_stop(self) -> None:
        def _call() -> None:
            handler = getattr(self._main_window, "_handle_global_escape", None)
            if callable(handler):
                handler()
        try:
            _run_in_main_thread(_call)
        except Exception:
            pass

    def _start_hunt(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."

        def _call() -> tuple[bool, str]:
            # 버튼 클릭과 동일한 경로로 실행. 창 활성화는 1회 건너뛰어 포커스 제한 문제 회피.
            try:
                is_running = bool(self._hunt_tab.detect_btn.isChecked())
            except Exception:
                is_running = False
            if is_running:
                return True, "이미 사냥 중입니다."
            try:
                try:
                    setattr(self._hunt_tab, '_skip_window_activation_once', True)
                except Exception:
                    pass
                self._hunt_tab.detect_btn.click()
                return True, "사냥을 시작했습니다."
            except Exception as exc:
                # 폴백: API 있으면 호출
                api = getattr(self._hunt_tab, "api_start_detection", None)
                if callable(api) and bool(api()):
                    return True, "사냥을 시작했습니다."
                return False, f"사냥 시작 실패: {exc}"

        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"사냥 시작 실패: {exc}"

    def _schedule_exit_wait(self, *, seconds: int = 5) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."

        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_schedule_exit_wait", None)
            if callable(api):
                return api(countdown_seconds=seconds)
            return False, "게임 종료 대기 API를 찾을 수 없습니다."

        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"게임 종료 예약 실패: {exc}"

    def _schedule_exit_wait_in(self, *, minutes: int) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."

        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_schedule_exit_wait_in", None)
            if callable(api):
                return api(minutes, countdown_seconds=0)
            return False, "게임 종료 대기 예약 API를 찾을 수 없습니다."

        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"게임 종료 예약 실패: {exc}"

    def _cancel_exit_wait(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."

        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_cancel_exit_wait", None)
            if callable(api):
                return api()
            return False, "게임 종료 대기 취소 API를 찾을 수 없습니다."

        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"게임 종료 예약 취소 실패: {exc}"

    def _schedule_shutdown(self, *, seconds: Optional[int] = None, minutes: Optional[int] = None) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."
        if seconds is None and minutes is None:
            minutes = 1
        total_sec = int(seconds if seconds is not None else int(minutes or 0) * 60)

        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_schedule_shutdown", None)
            if callable(api):
                ok, msg = api(total_sec)
                return ok, msg
            # 폴백: 내부 값 직접 제어
            try:
                if getattr(self._hunt_tab, "shutdown_pid_value", None) is None:
                    detect = getattr(self._hunt_tab, "_auto_detect_mapleland_pid", None)
                    if callable(detect):
                        detect(auto_trigger=True)
                if getattr(self._hunt_tab, "shutdown_pid_value", None) is None:
                    return False, "PID 자동탐지 실패로 종료 예약을 설정하지 못했습니다."
                self._hunt_tab.shutdown_reservation_enabled = True
                self._hunt_tab.shutdown_datetime_target = time.time() + total_sec
                self._hunt_tab._ensure_shutdown_timer_running()
                self._hunt_tab._update_shutdown_labels()
                return True, f"종료 예약을 설정했습니다. {total_sec}초 후 종료합니다."
            except Exception as exc:
                return False, f"종료 예약 실패: {exc}"

        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"종료 예약 실패: {exc}"

    def _cancel_shutdown(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."

        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_cancel_shutdown_reservation", None)
            if callable(api):
                ok, msg = api()
                return ok, msg
            # 폴백
            try:
                had = bool(getattr(self._hunt_tab, "shutdown_datetime_target", None))
                self._hunt_tab.shutdown_datetime_target = None
                self._hunt_tab.shutdown_reservation_enabled = False
                self._hunt_tab._stop_shutdown_timer_if_idle()
                self._hunt_tab._update_shutdown_labels()
                return True, ("종료 예약을 취소했습니다." if had else "취소할 종료 예약이 없습니다.")
            except Exception as exc:
                return False, f"종료 예약 취소 실패: {exc}"

        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"종료 예약 취소 실패: {exc}"

    def _capture_screen(self) -> tuple[bool, object]:
        if not _is_windows():
            return False, "화면 캡처는 Windows에서만 지원됩니다."
        try:
            import mss  # type: ignore
            import cv2  # type: ignore
            import numpy as np  # type: ignore
            from window_anchors import get_maple_window_geometry
        except Exception as exc:
            return False, f"필요 라이브러리 임포트 실패: {exc}"

        try:
            geom = _run_in_main_thread(lambda: get_maple_window_geometry())
        except Exception as exc:
            return False, f"창 좌표 조회 실패: {exc}"
        if geom is None:
            return False, "Mapleland 창을 찾을 수 없습니다."

        region = {"left": int(geom.left), "top": int(geom.top), "width": int(geom.width), "height": int(geom.height)}
        if region["width"] <= 0 or region["height"] <= 0:
            return False, "Mapleland 창 크기가 비정상입니다."

        try:
            with mss.mss() as sct:
                sct_img = sct.grab(region)
                frame_bgra = np.frombuffer(sct_img.raw, dtype=np.uint8).reshape(sct_img.height, sct_img.width, 4)
                frame_bgr = frame_bgra[:, :, :3].copy()
                ok, enc = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if not ok:
                    return False, "이미지 인코딩 실패"
                return True, io.BytesIO(enc.tobytes())
        except Exception as exc:
            return False, f"화면 캡처 실패: {exc}"

    def _enter_wait_indef(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."
        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_enter_indefinite_wait_mode", None)
            if callable(api):
                return api()
            return False, "대기 모드 API를 찾을 수 없습니다."
        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"대기 모드 진입 실패: {exc}"

    def _exit_wait_indef(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."
        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_exit_indefinite_wait_mode", None)
            if callable(api):
                return api()
            return False, "대기 모드 API를 찾을 수 없습니다."
        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"대기 모드 해제 실패: {exc}"

    def _trigger_forbidden_test(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."
        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_trigger_forbidden_monster", None)
            if callable(api):
                return api()
            return False, "금지몬스터 테스트 API를 찾을 수 없습니다."
        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"금지몬스터 테스트 실패: {exc}"

    def _cancel_forbidden_test(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."
        def _call() -> tuple[bool, str]:
            api = getattr(self._hunt_tab, "api_cancel_forbidden_and_restart", None)
            if callable(api):
                return api()
            return False, "금지 플로우 해제 API를 찾을 수 없습니다."
        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"금지 플로우 해제 실패: {exc}"

    def _toggle_screen_output(self) -> tuple[bool, str]:
        if self._hunt_tab is None:
            return False, "사냥탭을 찾을 수 없습니다."
        def _call() -> tuple[bool, str]:
            chk = getattr(self._hunt_tab, 'screen_output_checkbox', None)
            if chk is None:
                return False, "화면출력 체크박스를 찾을 수 없습니다."
            try:
                current = bool(chk.isChecked())
            except Exception:
                current = False
            try:
                chk.setChecked(not current)
                state = "켬" if not current else "끔"
                return True, f"화면출력: {state}"
            except Exception as exc:
                return False, f"화면출력 토글 실패: {exc}"
        try:
            return _run_in_main_thread(_call)  # type: ignore[return-value]
        except Exception as exc:
            return False, f"화면출력 토글 실패: {exc}"

    # --- 외부 알림용 간단 API ---
    def send_text(self, text: str) -> bool:
        """현재 설정된 챗ID로 텍스트를 전송(가능하면 즉시, 실패 시 False)."""
        if not self._running or not self._bot_app or not self._loop:
            return False
        if not self._creds or self._creds.allowed_chat_id is None:
            return False
        try:
            import asyncio
            coro = self._bot_app.bot.send_message(chat_id=int(self._creds.allowed_chat_id), text=str(text))
            asyncio.run_coroutine_threadsafe(coro, self._loop)
            return True
        except Exception:
            return False

    def send_photo(self, image_bytes: bytes, caption: Optional[str] = None) -> bool:
        """현재 설정된 챗ID로 사진을 전송(가능하면 즉시, 실패 시 False)."""
        if not image_bytes:
            return False
        if not self._running or not self._bot_app or not self._loop:
            return False
        if not self._creds or self._creds.allowed_chat_id is None:
            return False
        try:
            import asyncio
            # python-telegram-bot 호환성을 위해 파일류로 래핑
            buf = io.BytesIO(image_bytes if isinstance(image_bytes, (bytes, bytearray)) else bytes(image_bytes))
            kwargs = {
                'chat_id': int(self._creds.allowed_chat_id),
                'photo': buf,
            }
            if caption:
                kwargs['caption'] = caption
            coro = self._bot_app.bot.send_photo(**kwargs)
            asyncio.run_coroutine_threadsafe(coro, self._loop)
            return True
        except Exception:
            return False


def _parse_minutes_korean(text: str) -> Optional[int]:
    # 예: "/종료예약 10분" 또는 공백 여러개 허용
    try:
        s = text.strip().replace("\t", " ")
        if not s.startswith("/종료예약"):
            return None
        rest = s[len("/종료예약"):].strip()
        if not rest:
            return None
        # 끝에 '분'이 붙는 형식
        if rest.endswith("분"):
            rest = rest[:-1]
        minutes = int(rest.strip())
        return minutes if minutes > 0 else None
    except Exception:
        return None


def _parse_minutes_english(text: str) -> Optional[int]:
    # 예: "/exit_in 10"
    try:
        s = text.strip()
        if not s.lower().startswith("/exit_in"):
            return None
        rest = s.split(maxsplit=1)
        if len(rest) < 2:
            return None
        minutes = int(rest[1].strip())
        return minutes if minutes > 0 else None
    except Exception:
        return None


def maybe_start_bridge(main_window) -> Optional[TelegramBridge]:
    """자격이 유효하고 Windows면 브리지를 시작한다."""
    try:
        bridge = TelegramBridge(main_window)
        if bridge.available():
            bridge.start()
            try:
                _set_active_bridge(bridge)
            except Exception:
                pass
            return bridge
        else:
            print("[TelegramBridge] 비활성화(자격 미설정 또는 OS 미지원)")
            return None
    except Exception as exc:  # pragma: no cover - 안전 장치
        print(f"[TelegramBridge] 시작 중 오류: {exc}")
        return None

# ---- 외부에서 간단히 텍스트를 보낼 수 있도록 도우미 제공 ----
_ACTIVE_BRIDGE: Optional[TelegramBridge] = None

def _set_active_bridge(bridge: Optional[TelegramBridge]) -> None:
    global _ACTIVE_BRIDGE
    _ACTIVE_BRIDGE = bridge

def send_telegram_text(text: str) -> bool:
    """활성 브리지로 텍스트 메시지를 보낸다. 실패 시 False."""
    bridge = _ACTIVE_BRIDGE
    if bridge is None:
        return False
    try:
        return bridge.send_text(text)
    except Exception:
        return False


def send_telegram_photo(image_bytes: bytes, caption: Optional[str] = None) -> bool:
    """활성 브리지로 사진을 보낸다. 실패 시 False."""
    bridge = _ACTIVE_BRIDGE
    if bridge is None:
        return False
    try:
        return bridge.send_photo(image_bytes, caption=caption)
    except Exception:
        return False
