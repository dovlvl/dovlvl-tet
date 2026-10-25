# 리팩토링 작업 가이드

## 사람이 할 일

**Codex에게 "계속해줘"라고만 말하면 됩니다.** git이나 코드를 몰라도 됩니다.

- 한 번 말할 때마다 정리 항목 하나를 끝냅니다. "끝까지 해줘"라고 하면 남은 항목을 이어서 처리합니다.
- 처음 한 번은 GitHub 로그인이 필요할 수 있습니다. Codex가 화면마다 무엇을 누르면 되는지 알려줍니다.
- Codex가 "모두 끝났습니다"라고 하면 끝입니다.
- 새 규칙 파일을 받으면 `AGENTS.md`는 저장소 폴더 맨 위에, 나머지 두 파일은 `docs` 폴더에 덮어쓰고 "계속해줘"라고 하세요.
  Codex가 먼저 규칙 파일을 반영한 다음 작업을 이어갑니다.

작업 규칙은 저장소 루트의 [AGENTS.md](../AGENTS.md)에 있고 Codex가 자동으로 읽습니다.
진행 상황은 [REFACTORING_PROGRESS.md](REFACTORING_PROGRESS.md)에 기록됩니다.

---

## 이하 Codex용 항목 설명

사람 리뷰어가 없으므로 모든 변경은 AGENTS.md의 자동 검증 게이트와 자기 검토를 통과해야 합니다.
**동작을 바꾸지 않는 것**이 모든 항목의 전제입니다.

### 단계 G — 골든 스냅샷 (A 다음, 다른 모든 항목보다 먼저 — 다른 항목의 안전망)

사람 리뷰 대신 "리팩토링 전후 결과가 똑같은지"를 자동으로 확인하는 테스트를 만듭니다.
이 항목은 **코드(`src/`)를 전혀 바꾸지 않습니다.**

- `tests/test_golden.py`와 `tests/golden/*.json`을 만듭니다.
- 시간 제한(deadline/budget)에 영향을 받지 않는 **결정적인** 결과만 기록합니다. 최소한:
  - `geometry`: 7종 × 4회전 `orientations`, 여러 보드에서 `rotate`/`advance`/`settle`/`evaluate` 결과
  - `planner.landings(..., deadline=None)`: 빈 보드, 울퉁불퉁한 보드, T스핀 슬롯 보드(`data/openers/TKI_Fonzie.json`의 마지막 단계 `expected_before`)에서
    7종 각각의 결과를 `cells`, `spin`, `lines`, `path`, `score` 기준으로 정렬해 저장
  - `planner.route_to`, `planner.basic_candidates(deadline=None)`
  - `scoring.tspin`, `scoring.award`의 대표 입력 조합
  - `strategy.position_score`, `strategy.metrics`
  - `timing.route_feasible`, `timing.timing_profile`의 대표 입력
  - `openers.compile_book`(TKI_Fonzie)와 `mirrored_variant` 결과
  - `recognition.sample_board`, `Recognizer.process`, `PreviewCache.classify`: `tests/helpers.py`의 `scene()`으로 만든 이미지와
    `tests/fixtures/*.png`에 대한 결과 중 시간값(`updated`, `seen`, `captured`, `vision_ms` 등)을 뺀 필드
  - `config.validate`가 통과/거부하는 대표 설정과 거부 메시지
  - `ui_status.summary`의 대표 출력
- 실수 값은 `round(x, 9)`로 저장합니다. 집합·딕셔너리는 정렬해서 저장합니다.
- 스냅샷이 없으면 생성하고, 있으면 비교만 하는 구조로 만들되, 생성은 환경변수 `GOLDEN_UPDATE=1`일 때만 하도록 합니다.
- 두 번 연속 실행해서 같은 결과가 나오는지(결정성) 확인한 뒤 커밋합니다.
- 이 항목 이후로 `tests/golden/`은 수정 금지입니다.

### 단계 A — 포매터 (단독 커밋)

- `pyproject.toml`에 ruff 설정 추가 (line-length 120), `ruff`를 개발 의존성으로 설치.
- `ruff format src tests tools` 적용. 세미콜론으로 이어진 문장이 여러 줄로 풀립니다.
- **로직 변경 0.** 이 항목에서는 `ruff check --fix`를 쓰지 않습니다.

### 단계 B — 기계적 정리

| # | 작업 | 대상 |
|---|------|------|
| B1 | `cellset`을 `recognition.py` → `geometry.py`로 이동, import 경로 수정. `recognition`은 `geometry`에서 다시 import해 기존 이름도 유지. 함수 안 지연 import 제거 | planner, openers, controller, timing, blox_import, tools, tests |
| B2 | 착지 계산 헬퍼 하나로 통일 (`while fits(..., y+1): y+=1` 7곳 → `geometry.hard_drop` 등) | controller 3, planner 3, recognition 1 |
| B3 | SRS 킥 조회 헬퍼 `kick_offsets(kind, r, nr)` 추출 | geometry, planner, controller |
| B4 | 높이/구멍 계산 공통화, `strategy.auto_plan`의 `metrics()` 중복 호출 제거 | geometry, strategy, planner |
| B5 | 프레임 신선도 헬퍼 `is_fresh(obs, now, c)` 추출 (약 10곳). 각 위치의 부등호(`<`/`<=`, `0<=` 유무)가 다르면 합치지 말 것 | runtime, controller, gui |
| B6 | 검증 플래그 리셋 헬퍼 (gui 5곳). 위치마다 리셋하는 플래그 조합이 다르므로 그대로 보존 | gui |
| B7 | 영역 나열 헬퍼 `config.regions(c)` → `[(label, box), ...]`. 라벨 표기(`NEXT 1` vs `NEXT1` vs `next0`)가 위치마다 다르므로 표시 문자열은 유지 | config, gui, runtime |
| B8 | 경로 헬퍼 `paths.py` (`app_root()`, `resource_root()`). `build_exe.py`/`verify_embedded_source.py`가 모듈 목록을 검사하면 함께 갱신 | telemetry, gui, strategy, piece_library, tools |
| B9 | `c.get(k, 기본값)` → `c[k]` 통일. **주의:** 테스트나 진단 모드에서 `DEFAULT`를 거치지 않은 설정 dict가 쓰이는지 먼저 확인하고, 그런 경로가 있으면 이 항목은 건너뜀 | 전체 |
| B10 | 안 쓰는 import 제거 (`geometry.deque`, `recognition.SHAPES`, `strategy.evaluate` 등) | — |

### 테스트·빌드 정리

| # | 작업 |
|---|------|
| T1 | 테스트의 `sys.path.insert` 일원화(`tests/__init__.py` 또는 공용 부트스트랩). `test_drop_transition`이 쓰는 `test_session.Source`를 `helpers.py`로 이동. 테스트 수는 그대로여야 함 |
| T2 | `pyinstaller`, `ruff`를 `requirements-dev.txt`로 분리하고 `build_windows.bat`이 둘 다 설치하도록 수정. Python 버전 문구 통일 (`build_windows.bat` "3.11+" → README의 3.12 기준) |
| T3 | 안 쓰는 추적 파일 정리. 아래 삭제·유지 목록과 사용 여부 확인 절차를 따른다. |

#### T3 — 안 쓰는 추적 파일 정리 (T2 다음, 단계 C 전)

- 삭제 후보는 다음 파일로 한정하며, 사용 여부 확인을 통과한 파일만 `git rm`한다.
  - `tools/`의 일회성 도구 12개: `benchmark_auto.py`, `benchmark_highspeed.py`, `benchmark_recognition.py`, `compare_score_policy.py`, `diagnose_tcl.py`, `gui_auto_smoke.py`, `inspect_official_rules.py`, `package_release.py`, `preview_compare.py`, `replay_tracking.py`, `run_revision_benchmarks.py`, `write_revision_report.py`.
  - `data/site_profiles.json` (코드에서 읽지 않는 데이터 파일). `config.py`의 `site_profile` 설정 키는 유지한다.
  - 지난 작업 보고서: `PROJECT_STATUS.md`, `docs/VALIDATION_REPORT_KO.md`, `docs/DROP_TRANSITION_FIX_KO.md`.
- 절대 삭제 금지: `tools/build_exe.py`, `tools/verify_embedded_source.py`, `tools/import_piece_captures.py`, `tests/` 전체(`legacy_preview_reference.py` 포함), `src/` 전체, `data/`의 나머지 전부, 골든 스냅샷.
- 삭제 전에 각 삭제 후보 이름이 `src/`, `tests/`, 남는 `tools/`, `build_windows.bat`, `run_windows.bat`에서 import되거나 실행되는지 검색한다. 쓰이는 곳이 하나라도 있으면 해당 파일은 삭제하지 않고 진행 문서에 유지 이유를 적는다.
- 삭제한 파일을 언급하는 문서(`README.md`, `docs/START_HERE_KO.md`, `docs/RELEASE_POLICY.md` 등)는 해당 문장만 고치거나 지운다. 프로그램 사용법 설명은 바꾸지 않는다.
- 다른 항목의 검증 게이트를 모두 적용한다. 전체 테스트 통과 수 유지, 기존 골든 스냅샷 일치, Ruff 검사를 확인하고, 시작 검사도 반드시 실행해 `started=true`, `auto_running=false`를 확인한다.

### CI — GitHub Actions 검증 추가 (T3 다음, C1 전)

- `.github/workflows/ci.yml`을 만든다. `main`에 push될 때마다 GitHub Actions `windows-latest`에서 Python 3.12로 실행한다.
- 단계: `requirements-lock.txt` 설치 → `pyproject.toml`의 `required-version`과 같은 Ruff 설치 → `ruff format --check src tests tools` → 전체 unittest 실행(골든 테스트 포함).
- `ruff check`는 기존 진단이 남아 있으므로, 현재 진단 수를 기준값 파일로 저장해 두고 그보다 늘었을 때만 실패하게 한다.
- 시간 의존 테스트는 CI 서버에서 간헐적으로 실패할 수 있으므로, 실패한 테스트만 최대 2번 다시 실행해 통과하면 성공으로 처리한다. 테스트의 제한 시간이나 기대값은 고치지 않는다.
- 실제 키 입력, GUI 실행, 시작 검사는 CI에서 하지 않는다.
- 다른 항목과 같은 검증 게이트를 통과해야 하고, push 후 첫 CI 실행이 성공하는 것까지 확인해야 완료다.

### 단계 C — 구조 개선

| # | 작업 |
|---|------|
| C1 | `Recognizer`, `AutoController`의 모든 상태를 `__init__`/`reset()`에 명시. `getattr(self,'x',기본값)`과 `delattr` 제거. 초기값은 기존 getattr 기본값과 똑같이 |
| C2 | `auto_plan`(17개), `opener_plan`(12개) 호출을 키워드 인자로 |
| C3 | `controller.wait` dict → `PendingAction` dataclass, phase 문자열 → `str` 기반 Enum (기존 문자열 값 유지) |
| C4 | 배치 결과 dict → `Placement` dataclass. 프로세스 간 전달(pickle)과 진단 JSON 출력이 그대로 되는지 확인 |
| C5 | `Observation`에 `controlled_motion` 필드 선언 |
| C6 | `ui_status`의 `'팝업' in reason` 문자열 검사 → 사유 코드로. 화면 표시 문구는 그대로 |

### 단계 D — 큰 함수/클래스 분리

| # | 작업 |
|---|------|
| D1 | `gui.App`(430줄) → 설정 창, 영역 편집기, 진단 창, 프리뷰 창 모듈 분리. 화면 캡처 함수 공통화. 시작 검사 필수 |
| D2 | `planner.plan` → PC 탐색 / 빔 탐색 함수 분리 |
| D3 | `Recognizer.process` → 후보 탐색 / 고스트 처리 / 세대 판정 분리 |
| D4 | `Session.control_loop` → 탐색 디스패치 분리 |
| D5 | `controller.tick`의 중복 invalid 조건, `emit`의 착지 이중 계산 정리 |

### 별도 버그 수정 (Codex는 진행하지 않음, 기록용)

동작이 바뀌는 작업이라 사람 확인 없이는 진행하지 않습니다.

- F1: `recognition.py` 보드 ROI가 `None`일 때 `.shape` 오류
- F2: `runtime.py` 디버그 모드에서 observation 이중 put + `beat('vision')` 이중 호출
- F3: `gui.render`와 `_render_diagnostics`가 설정 파일을 중복 저장
- F4: `recognition.py` `components(grid)` 두 번 계산 후 첫 결과 폐기 (의도 불명)
- F5: `strategy.builtin_book` 원본 변형 이중 컴파일

### Z — 로컬 예전 배포본·진단 파일 정리 (D5와 F 다음, 맨 마지막)

git에 올라가지 않은 로컬 파일만 대상으로 한다. 삭제하면 복구할 수 없으므로 아래 목록에 해당하는 것만 지운다.

- 저장소 폴더 안의 `release/` 폴더 전체.
- 저장소 폴더 안의 모든 `*.zip`, `*.zip.sha256` 파일.
- `diagnostics/` 폴더 전체(리팩토링 검증 로그 포함).
- `dist/` 안에서 `TetrisAuto.exe`를 제외한 나머지 전부.
- `build/` 폴더와 `*.spec` 파일.

절대 건드리지 않는 것: `.venv/`, `dist/TetrisAuto.exe`, git에 추적되는 모든 파일, 저장소 폴더 밖의 모든 파일(`%USERPROFILE%\.tetris_trainer` 설정 포함). 위 삭제 목록보다 이 보호 규칙을 우선한다. 폴더 안에 추적 파일이 있으면 해당 파일을 보존한다. 삭제 전 실제 절대 경로가 저장소 안인지 확인하며, 저장소 밖을 가리키는 링크를 따라가지 않는다.

순서는 다음과 같다.

1. 지울 목록과 항목별·전체 용량을 진행 문서에 기록한다.
2. 기록한 대상만 삭제한다.
3. 진행 문서의 예정된 기록 변경을 제외하고 `git status`가 깨끗하며, 삭제로 인해 추적 파일이 하나도 바뀌지 않았는지 확인한다.
4. 전체 테스트와 시작 검사를 다시 실행해 통과를 확인한다(`started=true`, `auto_running=false`).
5. 진행 문서에 `[x]`와 실제 확보한 용량을 기록하고 커밋·push한다. 재검증으로 다시 생긴 파일이 있으면 확보 용량에 반영한다.

이 항목은 코드 변경이 없으므로 브랜치 없이 `main`에서 진행 문서 기록만 커밋해도 된다.
