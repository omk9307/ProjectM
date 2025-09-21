# Repository Guidelines

이 문서는 Python 기반 저장소에서 일관된 협업을 돕기 위한 간단한 가이드입니다.

## 답변 언어
- 항상 한국어로 답변.

## 한글 깨짐 유의
- vscode에서 사용중이야. 코드 작성시 한글 깨짐에 주의해서 코드를 작성해. 
- 코드에 한글로 생성된 주석등 내용에 유니코드가 깨졌을 경우 다시 수정해야 함

## 사용방법 or 테스트 방법 제안하기
- 코드를 개선하거나 추가한 뒤, 복잡하고 전문적인 테스트가 아니라 어느정도 제대로 적용되었는지 테스트하는 방법이나 사용방법을 간단히 제안해줘.

## 코드 작성 전 유의사항
- 코드를 작성하기 전에 먼저 계획을 브리핑해주고 사용자의 허가를 받은 뒤 진행해.
- 코드 작성시 질문할 점이 있으면 먼저 자유롭게 물어보고 진행해.

## Project Structure & Module Organization
- `src/` — 애플리케이션/라이브러리 코드(예: `src/auth/`, `src/core/`).
- `tests/` — `src/` 구조를 미러링(예: `tests/auth/` ↔ `src/auth/`).
- `assets/` — 샘플 데이터, 픽스처, 정적 파일.
- `scripts/` — 개발/테스트/릴리즈 보조 스크립트.
- `docs/` — 설계 메모와 ADR. 짧고 목적 지향적으로 유지.

## Build, Test, and Development Commands
- 가상환경: `python -m venv .venv` → 활성화(Win: `.venv\Scripts\activate`, Unix: `source .venv/bin/activate`).
- 의존성: `pip install -U pip setuptools wheel` 후 `pip install -r requirements.txt` (개발: `requirements-dev.txt` 또는 `pip install -e .`).
- 실행: `python -m src.<패키지>` 또는 `scripts/` 내 래퍼 사용(있다면 `./scripts/dev`).
- 테스트: `pytest -q` / 커버리지: `pytest --cov=src --cov-report=term-missing`.
- 품질: `ruff check .`, `black .`, `isort .`, 타입체크 `mypy src`.
- 가능한 경우 `scripts/test`, `scripts/format` 같은 통합 스크립트를 우선 사용.

## Coding Style & Naming Conventions
- PEP 8 준수, 들여쓰기 4칸, 줄 길이 88(black 기본값).
- 네이밍: 함수/변수 `snake_case`, 클래스 `PascalCase`, 상수 `UPPER_SNAKE_CASE`, 모듈/패키지 소문자 스네이크.
- 포맷/정렬: black + isort(프로필 `black`), 린트: ruff. 커밋 전 자동 정리 권장.
- `pre-commit` 설정이 있으면 `pre-commit run -a`로 검증 후 푸시.
- 한글깨짐없도록 유의

## Testing Guidelines
- 테스트는 `tests/`에 `test_*.py`로 배치, `src/` 구조를 반영.
- 단위 테스트 우선, 외부 I/O는 fixture/monkeypatch/mocker로 격리.
- 핵심 경로 커버리지 확보(권장 ≥ 80%). 오류/경계 케이스 포함.
- 예: `pytest -q -m "not slow"`로 느린 테스트 제외 마커 운용 가능.

## Commit & Pull Request Guidelines
- 커밋: 간결한 명령형 제목(≤72자). 예) `feat: 사용자 토큰 갱신 로직 추가`.
- PR: 목적/변경점/테스트 방법/연관 이슈를 명시, UI 변경은 스크린샷 첨부.
- 작은 단위로 제출, 최신 `main`에 리베이스, CI 통과 유지. 관련 문서/예제 갱신.

## Security & Configuration Tips
- 비밀은 커밋 금지. `.env.example`로 키만 공유, 로컬은 `.env` 사용(필요 시 `python-dotenv`).
- 의존성은 버전 범위를 명확히 하고 정기적으로 업데이트 검토.

## Agent-Specific Notes
- 최소·국소 변경 원칙, 기존 구조/스타일 준수.
- 하위 폴더에 별도 `AGENTS.md`가 있으면 그 규칙을 우선 적용.