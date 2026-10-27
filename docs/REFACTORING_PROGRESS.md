# 리팩토링 진행 상황

항목 설명은 [REFACTORING_GUIDE_KO.md](REFACTORING_GUIDE_KO.md) 참고. 위에서부터 순서대로 하나씩 처리합니다.

표기: `[ ]` 대기 · `[x]` 완료 · `[-]` 건너뜀. 완료/건너뜀 뒤에 `— 날짜 / 결과 또는 사유`를 적습니다.

## 단계 A — 포매터 (G보다 먼저 완료됨)
- [x] A — Ruff 포매터 적용 — 2026-10-26 / 커밋 `b53c30f`
  - Ruff 0.14.2, 120열. `src`, `tests`, `tools`의 Python 파일 57개와 `pyproject.toml`.
  - 전체 테스트: 변경 전 145개 통과, 변경 후 145개 통과. 중간 검사에서 시간 의존 테스트가 4개/2개 간헐 실패 후 재검사 통과.
  - Python AST 57개 및 주석 모두 동일 (외부 재확인 완료). `ruff format --check` 통과. Ruff 진단 2496→170, lint 자동 수정 안 함.
  - Windows 시작 검사: `started=true`, `auto_running=false`.

## 단계 G — 골든 스냅샷
- [x] G — 결정적 결과 스냅샷 테스트 생성 — 2026-10-26 / 145→153 통과, 골든 2회 연속 일치
  - `tests/test_golden.py` 8개 테스트와 `tests/golden/*.json` 7개 추가. geometry 7종×4회전, 3종 보드의 planner 착지/경로/기본 후보, scoring/strategy, timing, TKI 원본·미러, 합성 이미지 8개·기존 PNG 2개 인식, 설정 검증·상태 문구 기록.
  - 시간 제한 없는 탐색만 사용. 인식 시간 필드 제외, 실수 9자리 반올림, 집합·키·배치 결과 정렬. 스냅샷 누락 시 `GOLDEN_UPDATE=1`에서만 생성하며 기존 파일 덮어쓰기 거부도 테스트.
  - 작업 전 145개 통과(35.655초), 작업 후 153개 통과(43.146초). 간헐 실패 없음. 골든 별도 비교 2회 모두 8개 통과(5.359초/6.105초).
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 자기 검토 완료: `src/`, 기존 테스트·기대값, data·fixtures·의존성 변경 없음. 안전 조건·호출 순서·사용자 메시지 유지.
  - 시작 검사 대상 파일 변경 없음. 실제 Auto·입력 진단 실행 안 함. 상세 로그: 로컬 `diagnostics/refactor_g/`. 다음 항목은 B1.

## 단계 B — 기계적 정리
- [x] B1 — cellset을 geometry.py로 이동 — 2026-10-26 / 153→153 통과, 골든 일치
  - `cellset` 본문·인자를 그대로 geometry로 이동. recognition에서 같은 함수를 재노출하며 planner/openers/controller/timing/blox_import와 관련 tools/tests의 import 정리. 관련 geometry 지연 import 제거.
  - 이전 소스를 선택하는 벤치마크의 `--source` 호환성을 위해 recognition의 기존 공개 이름과 경로 선택 후 import 시점은 유지. 중첩 경로 검사에서는 바깥 import를 재사용.
  - 전체 테스트: 작업 전 153개 통과(44.723초), 최종 작업 후 153개 통과(43.815초). 간헐 실패 없음. 포함된 골든 8개 모두 기존 스냅샷과 일치, 스냅샷 파일 변경 없음.
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 전체 diff 자기 검토 및 import·함수 이동을 제외한 AST 비교 통과. 기존 테스트 기대값·안전 조건·호출 순서·사용자 메시지 유지.
  - 시작 검사 대상 파일 변경 없음. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b1/`. 다음 항목은 B2.
- [x] B2 — 착지 계산 헬퍼 통일 — 2026-10-26 / 153→153 통과, 골든 일치
  - `geometry.hard_drop(board, p, x, y)`로 기존 `while fits(..., y+1)` 반복을 통합. controller 3곳, planner 3곳, recognition 2곳(가이드의 예상 1곳보다 실제 1곳 추가)에 적용. planner의 캐시·비트마스크 기반 `valid` 반복은 유지.
  - 전체 테스트: 작업 전 153개 통과(46.066초), 최종 작업 후 153개 통과(45.226초). 간헐 실패 없음. 골든 8개 모두 기존 스냅샷과 일치, 기존 테스트·기대값·스냅샷 수정 없음.
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 전체 diff 자기 검토 및 헬퍼 호출을 원래 반복문으로 펼친 AST 비교 통과. `obs.fixed`/`trial` 등 인자, 안전 조건·호출 순서·사용자 메시지 유지.
  - 시작 검사 대상 파일 변경 없음. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b2/`. 다음 항목은 B3.
- [x] B3 — SRS 킥 조회 헬퍼 — 2026-10-26 / 153→153 통과, 골든 일치
  - `geometry.kick_offsets(kind, r, nr)`에 기존 O/I/나머지 분기식을 그대로 추출하고 geometry.rotate, planner.landings, controller 입력 확인의 조회 3곳에 적용. 킥 표·후보 순서·좌표 부호·킥 인덱스 판정은 유지.
  - 전체 테스트: 작업 전 153개 통과(45.520초), 작업 후 153개 통과(44.695초). 간헐 실패 없음. 골든 8개 모두 기존 스냅샷과 일치, 테스트·기대값·스냅샷 수정 없음.
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 전체 diff 자기 검토 및 헬퍼 호출을 원래 조회식으로 펼친 AST 비교 통과. 기존 인자·기본값·안전 조건·호출 순서·사용자 메시지 유지.
  - 시작 검사 대상 파일 변경 없음. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b3/`. 다음 항목은 B4.
- [x] B4 — 높이/구멍 계산 공통화 — 2026-10-26 / 153→153 통과, 골든 일치
  - 기존 `strategy.metrics` 계산식을 `geometry.board_metrics`로 이동하고 기존 이름은 import로 유지. geometry 점수 계산과 planner 최대 높이 계산에서 공통 함수를 사용. `auto_plan`의 두 번째 `metrics(board)` 호출은 첫 계산의 `buried` 값으로 대체.
  - 전체 테스트: 작업 전 153개 통과(46.769초), 최종 작업 후 153개 통과(43.822초, 종료 코드 0). 간헐 실패 없음. 포함된 골든 8개 모두 기존 스냅샷과 일치, 테스트·기대값·스냅샷 수정 없음.
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 빈 보드·전체 채움·각 단일 셀·고정 난수 보드 총 1,202개에서 기존 metrics·최대 높이·evaluate·position_score(0~4줄) 결과와 정확히 일치.
  - 전체 diff 자기 검토 완료. 인자·임계값·안전 조건·호출 순서·사용자 메시지 유지. 시작 검사 대상 파일 변경 없음. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b4/`. 다음 항목은 B5.
- [x] B5 — 프레임 신선도 헬퍼 — 2026-10-26 / 153→153 통과(간헐 실패 재실행 포함), 골든 일치
  - `timing.is_fresh(obs, now, c)`의 엄격한 `<` 검사(runtime 2곳)와 `is_stale`의 엄격한 `>` 검사(controller 3곳, gui 1곳)를 별도 함수로 추출. 관측값 유무·valid·신뢰도·세대 검사의 위치와 단락 평가 순서 유지.
  - `0 <= age < limit` 입력 가드, 입력 직전 밀리초 계산, 원시 캡처 타임스탬프 검사, 표시·추적용 별도 제한은 계산식과 경계가 달라 그대로 유지. `is_stale`을 `not is_fresh`로 바꾸지 않아 경계값·NaN 처리도 유지.
  - 전체 테스트: 작업 전 153개 통과(45.278초). 작업 후 전체 153개 중 149개 통과, 시간 의존 4개 간헐 실패(90.976초). 실패한 4개만 1차 재실행하여 3개 통과(31.086초); 남은 오프너 파이프라인 1개는 2차 재실행 통과(7블록 확인, 7.391초). 제한 시간·기대값 수정 없음. 기존 골든 8개 모두 일치, 테스트·스냅샷 변경 없음.
  - 간헐 실패: `test_desktop`의 `test_diagnostic_api_success_without_change_fails`, `test_diagnostic_left_waits_for_screen_ack`, `test_previews_openers`의 `test_opener_runtime_pipeline_seven_simulated_blocks`, `test_strategy`의 `test_auto_runtime_finishes_opener_and_keeps_playing`. 작업 전 main 기준 검사는 모두 통과했음.
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 4개 변경 모듈에서 헬퍼 6회 호출을 원래 식으로 펼친 AST 전체가 main과 동일. 경계 직전·동일·직후, 미래 시각, 기본/명시 설정, 무한대·NaN 등 32개 경계 검사 통과.
  - 전체 diff 자기 검토 완료: 안전 조건·키 해제·호출 순서·사용자 메시지 유지. Windows 시작 검사 `started=true`, `auto_running=false`. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b5/`. 다음 항목은 B6.
- [x] B6 — 검증 플래그 리셋 헬퍼 — 2026-10-26 / 153→153 통과(간헐 실패 재실행 포함), 골든 일치
  - gui의 독립적인 리셋 5곳을 `reset_verification(c, *, reset_preview=True)`로 추출. 4곳의 preview/basic/opener 3개 초기화와 키·회전 변경 시 basic/opener 2개만 초기화를 별도 분기로 보존. 원래 설정 객체에 한 번의 `update`로 같은 순서로 적용.
  - 게임 열기의 영역 설정과 결합된 update 및 빌드 가져오기의 opener 단독 해제는 그대로 유지. `rotation_confirmed`와 각 위치의 조건·호출 순서·저장·검증 절차 및 사용자 메시지 변경 없음.
  - 전체 테스트: 작업 전 153개 중 152개 통과(68.629초), 시간 의존 `test_strategy.AdaptiveAutoTests.test_tetris_and_perfect_clear_take_priority`는 1차 단독 재실행 통과(0.090초). 작업 후 153개 중 152개 통과(73.675초), 시간 의존 `test_session.PipelineTests.test_board_only_pipeline_places_five_simulated_blocks`는 1차 단독 재실행 통과(3.904초, 5블록 확인). 두 간헐 실패는 서로 다른 테스트이며 제한 시간·기대값 수정 없음.
  - 기존 골든 8개 모두 일치, 테스트·스냅샷 변경 없음. Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 헬퍼 호출 5곳을 원래 코드로 펼친 gui 전체 AST가 main과 동일. 누락/false/true 설정을 조합한 162개 사례에서 값·키 삽입 순서·update 횟수·비대상 값 유지 확인.
  - 전체 diff 자기 검토 완료: 검증 게이트·안전 조건·키 해제·호출 순서 유지. Windows 시작 검사 `started=true`, `auto_running=false`. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b6/`. 다음 항목은 B7.
- [x] B7 — 영역 나열 헬퍼 — 2026-10-27 / 153→153 통과(기준 검사 간헐 실패 재실행 포함), 골든 일치
  - `config.regions(c, *, next_prefix="NEXT ")`로 영역 순회 6곳을 공통화. BOARD/HOLD/NEXT 순서와 None 보존, 검증·편집기의 `NEXT 1` 및 이미지 저장의 `NEXT1` 표기를 유지. 판독값을 결합하는 별도 순회(`next0` 포함)는 그대로 유지.
  - 작업 전 전체 153개 중 152개 통과(26.480초), 시간 의존 `test_core.RecognitionTests.test_preview_cache_timestamp` 단독 1차 재실행 통과(0.054초). 작업 후 전체 153개 통과(26.837초), 포함된 골든 8개 모두 일치. 기존 테스트·기대값·스냅샷 수정 없음.
  - Ruff 0.14.2 포맷 검사 통과, 진단 170→170. 공통 함수 호출을 원래 영역 나열식으로 펼친 config/gui/runtime 전체 AST가 main과 동일. 전체 diff 자기 검토 완료: 안전 조건·호출 순서·키 해제·사용자 문구 유지.
  - Windows 시작 검사 `started=true`, `auto_running=false`. 실제 Auto·입력 진단 실행 안 함. 로컬 검증 로그: `diagnostics/refactor_b7/`. 다음 항목은 B8.
- [x] B8 — paths.py 경로 헬퍼 — 2026-10-27 / 153→153 통과, 골든 일치
  - paths.py로 4곳의 경로 계산 이동. GUI의 실행 파일 resolve 유무 및 _MEIPASS 동작 보존, 임베디드 모듈 필수 목록 갱신. 일반/배포·상대/절대 경로 비교 통과. Ruff 포맷 통과·진단 170→169, 시작 started=true/auto_running=false. 전체 diff 자기 검토: 안전 조건·호출 순서·문구 유지. 실제 Auto·입력 진단 실행 안 함. 로그 diagnostics/refactor_b8/.
- [-] B9 — 설정값 c[k]로 통일 — 2026-10-27 / DEFAULT를 거치지 않은 부분 설정 경로가 있어 가이드에 따라 건너뜀. tests/test_startup_connect.py의 부분 app.c 및 tests/test_golden.py의 route_feasible(..., {})가 존재하므로 get 기본값 제거 시 동작이 바뀔 수 있음. 코드 변경 없음.
- [x] B10 — 안 쓰는 import 제거 — 2026-10-27 / 153→153 통과, 골든 일치
  - 사용처 검색 후 미사용 import 26개 제거. import 이외 전체 AST 동일, 테스트·기대값·골든 변경 없음. Ruff 포맷 통과·진단 169→142, 시작 started=true/auto_running=false. 전체 diff 자기 검토: 안전 조건·호출 순서·문구 유지. 실제 입력 실행 안 함. 로그 diagnostics/refactor_b10/.

## 테스트·빌드 정리
- [x] T1 — 테스트 sys.path 일원화, Source를 helpers.py로 이동 — 2026-10-27 / 153→153 통과, 골든 일치
  - tests/bootstrap.py로 경로 설정 일원화, Source 본문을 helpers.py로 그대로 이동하고 4곳 import 갱신. 테스트·기대값·골든 유지. Ruff 포맷 통과·진단 142→142, 전체 diff 자기 검토: 테스트 본문 및 src 변경 없음. 실제 입력 실행 안 함. 로그 diagnostics/refactor_t1/.
- [x] T2 — requirements-dev.txt 분리, Python 버전 문구 통일 — 2026-10-27 / 153→153 통과, 골든 일치
  - requirements.txt의 PyInstaller를 requirements-dev.txt로 분리하고 Ruff 0.14.2 명시, 빌드는 잠금 파일과 개발 의존성 모두 설치. 기존 잠금 파일 유지. Python 3.12 안내 통일. 의존성 dry-run·Ruff 포맷 통과, 진단 142 유지. 전체 diff 자기 검토: src·테스트·안전 동작 변경 없음. 로그 diagnostics/refactor_t2/.
- [x] T3 — 안 쓰는 추적 파일 정리 (삭제 전 사용 여부 확인, 유지 목록 보존, 전체 테스트·골든·Ruff·시작 검사 필수) — 2026-10-27 / 153→153 통과, 골든 일치
  - 가이드의 삭제 후보 16개 모두 남는 src/tests/tools 및 실행 스크립트에서 사용하지 않음을 검색 확인 후 삭제. src·tests·골든·필수 도구·나머지 data 보존. 삭제 파일의 문서 참조만 정리. Ruff 포맷 통과·진단 142→113, 시작 started=true/auto_running=false. 전체 변경 목록·diff 자기 검토 완료, 실제 입력 실행 안 함. 로그 diagnostics/refactor_t3/.
  - 시간 의존 간헐 실패 후 최대 2회 단독 재실행 통과: 기준 ; 변경 후 test_core.RecognitionTests.test_preview_cache_timestamp. 제한 시간·기대값 유지.

## CI — GitHub Actions 검증 추가 (T3 다음, C1 전)
- [x] CI — GitHub Actions 검증 추가 — 2026-10-27 / 153→153 통과, 골든 일치
  - main 업로드마다 windows-latest/Python 3.12에서 잠금 의존성·Ruff 0.14.2 설치 후 포맷·진단 기준값(113)·전체 unittest 검사. 실패 테스트만 최대 2회 재실행. 로컬 153개·골든·Ruff 통과, GitHub 첫 CI 성공 확인: https://github.com/dovlvl/dovlvl-tet/actions/runs/40367946140 . src·기존 테스트·안전 동작 변경 없음. 실제 키 입력·GUI·시작 검사 실행 안 함.
  - 시간 의존 간헐 실패 후 최대 2회 단독 재실행 통과: 기준 test_core.RecognitionTests.test_preview_cache_timestamp; 변경 후 . 제한 시간·기대값 유지.
  - `.github/workflows/ci.yml`: main push마다 windows-latest, Python 3.12. 잠금 의존성·지정 Ruff 설치 → 포맷 검사 → 전체 unittest(골든 포함).
  - Ruff 진단 수는 기준값 파일보다 증가할 때만 실패. 시간 의존 테스트 실패 시 해당 테스트만 최대 2회 재실행하며 제한 시간·기대값은 유지.
  - CI에서 실제 키 입력·GUI 실행·시작 검사 금지. 다른 항목과 같은 검증 게이트 통과 및 push 후 첫 CI 실행 성공 확인까지 완료 조건.

## 단계 C — 구조 개선
- [x] C1 — 상태 속성 __init__/reset에 명시 — 2026-10-27 / 153→153 통과, 골든 일치
  - 기존 getattr 기본값으로 상태 필드 선언, start의 동적 삭제를 같은 초기 상태로 대체. Recognizer.reset이 추적 상태를 보존하던 동작 유지, 기준/수정 인식기 7프레임 및 reset 전후 출력 비교 일치. ack_bound의 0/None은 timing_profile의 기존 or 0 처리와 같은 결과. Ruff 포맷·진단 113 유지, 전체 diff 자기 검토: 안전 조건·키 해제·순서·문구 유지. 실제 입력 실행 안 함. 로그 diagnostics/refactor_c1/.
- [x] C2 — auto_plan/opener_plan 키워드 인자화 — 2026-10-27 / 153→153 통과, 골든 일치
  - auto_plan/opener_plan 및 pool.submit 포함 호출 17곳에 인자 이름 명시. 인자 평가 순서·식·기본값 보존, 키워드 형태로 정규화한 변경 모듈 전체 AST가 기준과 동일. Ruff 포맷·진단 113 유지, 시작 started=true/auto_running=false. 전체 diff 자기 검토: 안전 조건·순서·문구 및 테스트 기대값 유지. 실제 입력 실행 안 함. 로그 diagnostics/refactor_c2/.
  - 시간 의존 간헐 실패 후 최대 2회 단독 재실행 통과: 기준 test_core.RecognitionTests.test_preview_cache_timestamp; 변경 후 . 제한 시간·기대값 유지.
- [x] C3 — PendingAction dataclass, Phase Enum — 2026-10-27 / 153→153 통과, 골든 일치
  - PendingAction dataclass로 대기 정보 필드 선언, Phase StrEnum은 기존 문자열 값·표시·JSON·동등 비교 유지. 누락 필드 기본값과 expected_board의 관측 보드 기본값 보존. pickle 왕복 검사·전체 테스트·골든·Ruff 포맷 통과, 진단 113 유지, 시작 started=true/auto_running=false. 전체 diff 자기 검토: F8·포커스·세대·나이 제한·입력 확인·키 해제 조건 및 순서 유지. 실제 입력 실행 안 함. 로그 diagnostics/refactor_c3/.
  - 시간 의존 간헐 실패 후 최대 2회 단독 재실행 통과: 기준 test_core.RecognitionTests.test_preview_cache_timestamp; 변경 후 . 제한 시간·기대값 유지.
- [x] C4 — Placement dataclass — 2026-10-27 / 153→153 통과, 골든 일치
  - Placement dataclass는 기존 dict 호환을 유지해 선택적 키·복사·비교·JSON 형식 보존. 324개 결정적 배치의 키 순서 포함 JSON 및 pickle 왕복이 기준과 정확히 일치. 골든 변환기는 dict 호환 자료형을 기존 매핑 경로로 처리하며 기대값·스냅샷 불변. 프로세스 파이프라인 포함 전체 테스트·Ruff 포맷 통과, 진단 113 유지. 전체 diff 자기 검토: 계산식·안전 조건·순서·문구 유지. 실제 입력 실행 안 함. 로그 diagnostics/refactor_c4/.
  - 시간 의존 간헐 실패 후 최대 2회 단독 재실행 통과: 기준 test_core.RecognitionTests.test_preview_cache_timestamp; 변경 후 test_core.RecognitionTests.test_preview_cache_timestamp. 제한 시간·기대값 유지.
- [-] C5 — Observation 필드 정리 — 2026-10-27 / 골든 스냅샷 보존 규칙과 충돌하여 건너뜀
  - 작업 전 전체 153개 통과, Ruff 진단 113. `controlled_motion: bool = False`를 dataclass 필드로 선언하면 `asdict(Observation)`에 새 키가 추가되어 인식 골든 비교가 실패(8개 중 1개). 기존 스냅샷·기대값을 바꾸거나 직렬화 방식을 우회하지 않고는 항목과 완전 일치 조건을 함께 만족할 수 없어 코드 변경을 취소함. 안전 조건·호출 순서·화면 문구 변경 없음. 실제 입력 실행 안 함. 로그 `diagnostics/refactor_c5/`.
  - 원복 후 전체 153개 통과(간헐 실패 없음), 골든 8개 일치, Ruff 포맷 통과·진단 113 유지. 전체 diff 자기 검토: 진행 문서만 변경, 코드·기존 테스트·스냅샷 불변.
- [x] C6 — 사유 코드 enum — 2026-10-27 / 153→153 통과, 골든 일치
  - 기존 사유 문구를 `ReasonCode`로 변환하는 공통 함수를 model에 두고 ui_status는 코드로 가림을 판단. 기존 문구·직렬화·분기 순서 유지, 신선도 경계와 오류·탐색·유효 상태를 포함한 224개 조합의 표시 결과가 기준과 동일. 전체 diff 자기 검토, Ruff 포맷 통과·진단 113 유지. 실제 입력 실행 안 함. 로그 `diagnostics/refactor_c6/`.
  - 시간 의존 간헐 실패: 작업 후 `test_core.RecognitionTests.test_preview_cache_timestamp`만 1회 재실행 통과. 작업 전 실패 없음. 제한 시간·기대값 유지.

## 단계 D — 큰 함수/클래스 분리
- [x] D1 — gui.App 분리 — 2026-10-27 / 153→153 통과, 골든 일치
  - 설정·영역 편집·진단·프리뷰 창을 4개 mixin 모듈로 분리하고 데스크톱 RGB 캡처를 공통화. 기존 App 메서드 이름과 reset_verification 공개 경로 유지. 31개 메서드의 AST가 기준과 동일하며 캡처 두 호출의 배열 변환·좌표·반환 형식 유지. 새 모듈을 EXE 소스 검사 필수 목록에 추가(이번 작업에서 EXE 재빌드하지 않음).
  - 전체 테스트·골든·Ruff 포맷 통과, 진단 113 유지, 시작 started=true/auto_running=false. 간헐 실패 없음. 추출 초기 Ruff 진단 1개 증가는 새 파일의 복수 import를 분리하여 해결. 전체 diff 자기 검토: 안전 조건·호출 순서·사용자 문구 유지, 기존 테스트·스냅샷 불변. 실제 입력 실행 안 함. 로그 `diagnostics/refactor_d1/`.
- [x] D2 — planner.plan 분리 — 2026-10-27 / 153→153 통과, 골든 일치
  - plan 내부의 PC 탐색 실행과 빔 탐색을 각각 이름 있는 함수로 분리. 기존 캐시·후보 생성·점수 계산을 같은 클로저로 공유하고 예산 초과 예외 처리 및 부분 결과 보존. 두 함수를 원래 자리에 펼친 planner 전체 AST가 기준과 동일. 고정 시계로 I/O/T/L·HOLD·점수 사용 여부 16개 조합의 전체 결과 패킷이 정확히 일치.
  - 전체 테스트·골든·Ruff 포맷 통과, 진단 113 유지, 간헐 실패 없음. 전체 diff 자기 검토: 후보 순서·임계값·안전 조건·문구 유지, 기존 테스트·스냅샷 불변. 시작 검사 대상 변경 없음, 실제 입력 실행 안 함. 로그 `diagnostics/refactor_d2/`.
- [x] D3 — Recognizer.process 분리 — 2026-10-27 / 153→153 통과, 골든 일치
  - 후보 탐색·채워진 고스트 처리·세대 갱신을 각각 메서드로 추출. 인자·반환값·리스트 변경·캐시 무효화와 신뢰도 검사의 순서 유지. 세 메서드를 호출 자리에 펼친 recognition 전체 AST가 기준과 동일.
  - 전체 테스트·골든·Ruff 포맷 통과, 진단 113 유지, 간헐 실패 없음. 전체 diff 자기 검토: 부등호·기본값·안전 조건·문구 및 기존 테스트·스냅샷 유지. 시작 검사 대상 변경 없음, 실제 입력 실행 안 함. 로그 `diagnostics/refactor_d3/`.
- [x] D4 — Session.control_loop 분리 — 2026-10-27 / 153→153 통과, 골든 일치
  - 탐색 요청의 프리뷰·HOLD 준비, 긴급 탐색, 오프너·일반 탐색 제출을 dispatch_search로 이동. 제어 루프의 실행 조건과 결과 수락·신선도·계획 나이·워치독 동작은 유지. 원래 continue 두 곳을 같은 반복 건너뜀 결과로 연결했고, 함수를 펼쳐 continue를 복원한 runtime 전체 AST가 기준과 동일.
  - 전체 테스트·골든·Ruff 포맷 통과, 진단 113 유지, 시작 started=true/auto_running=false. 전체 diff 자기 검토: OPENER_GATE·검증 플래그·시간 제한·안전 조건·문구 및 기존 테스트·스냅샷 유지. 실제 입력 실행 안 함. 로그 `diagnostics/refactor_d4/`.
- [x] D5 — controller.tick/emit 중복 정리 — 2026-10-27 / 153→153 통과, 골든 일치
  - invalid 관측 조건과 착지 상태 계산의 중복 코드를 각각 공통 메서드로 추출. 검사 결과를 캐시하지 않고 원래 두 위치에서 다시 판단하며, 입력 전 검증과 입력 후 확인 정보 생성의 착지 계산도 각각 실행해 순서를 보존함(계산 횟수·속도 개선 주장은 없음). 두 메서드를 펼친 controller 전체 AST가 기준과 동일.
  - 전체 테스트·골든·Ruff 포맷 통과, 진단 113 유지, 간헐 실패 없음. 전체 diff 자기 검토: F8·포커스·인식 불확실·세대·프레임 나이·입력 확인·키 해제 조건과 순서 및 화면 문구 유지. 기존 테스트·스냅샷 불변. 시작 검사 대상 변경 없음, 실제 입력 실행 안 함. 로그 `diagnostics/refactor_d5/`.

## 별도 버그 수정 (사람 확인 필요 — Codex는 진행하지 않음)
- [-] F1 — recognition.py 보드 ROI None 처리
- [-] F2 — runtime 디버그 모드 이중 put/beat
- [-] F3 — gui 설정 파일 중복 저장
- [-] F4 — recognition components() 이중 계산
- [-] F5 — builtin_book 이중 컴파일

## 발견한 버그 (작업 중 Codex가 기록, 수정하지 않음)

- 시간 제한에 의존하는 시뮬레이션 테스트가 실행 부하에 따라 간헐적으로 실패함 (A 작업 중 발견). 수정하지 않음.

## 로컬 정리 (D5와 F 다음, 맨 마지막)
- [x] Z — 로컬 예전 배포본·진단 파일 정리 — 2026-10-27 / 정리 및 재검증 통과
  - 삭제·재검증 후 실제 정리 용량(파일 크기 합계 기준): 384,995,443바이트 (367.16 MiB). 재생성한 진단·Ruff 캐시 377,984바이트를 차감한 값.
  - 추적 파일·보호 EXE 무변경 확인, 전체 153개·골든 8개·Ruff 포맷 통과(진단 113 유지), 시작 started=true/auto_running=false. 실제 입력 실행 안 함.
  - 시간 의존 간헐 실패: 없음. 제한 시간·기대값 변경 없음.
  - 삭제 전 확정 목록(각 경로 아래의 미추적 파일만, 추적 파일·링크·.venv·dist/TetrisAuto.exe 제외):
    - `TetrisAuto.spec`: 1개, 1,138바이트.
    - `build/`: 15개, 85,183,149바이트.
    - `diagnostics/`: 2425개, 111,307,491바이트.
    - `dist/`: 75개, 11,369,569바이트.
    - `release/`: 433개, 177,512,080바이트.
  - 삭제 예정 합계: 2,949개, 385,373,427바이트 (367.52 MiB). 절대 경로와 링크 여부를 확인한 개별 파일 목록은 임시 검증 목록에 고정하고, 그 파일만 삭제한다.
  - 실행 시 삭제 목록과 항목별·전체 용량을 먼저 기록한다. 가이드의 허용 목록에 해당하는 미추적 파일만 삭제하며 `.venv/`, `dist/TetrisAuto.exe`, 모든 추적 파일과 저장소 밖 파일은 보존한다.
  - 삭제 후 추적 파일 무변경 확인, 전체 테스트·시작 검사 통과, 실제 확보 용량 기록 후 진행 문서만 커밋·push한다. `main`에서 브랜치 없이 진행 가능.

## 사용자 승인 후 별도 버그 수정
- [x] LATE-SURVIVAL — 후반 입력 시간·NEXT 평가 및 중지 원인 기록 보완 — 2026-10-27
  - 사용자가 실제 3만 점 이후 기록 검토 후 "수정해라"로 승인. `20261027_115723`은 32,580점 직후 낮은 보드에서 시작해 36,000점대에 탑이 커지고, 안전 경로 미발견 재탐색 후 공통 실패 제한으로 중지한 기록. 마지막 게임오버는 36,236점. 이 기록은 예측 점수와 구분해 저장 화면으로 확인함.
  - PC 목표의 일반 탐색은 T를 포함해 회전·이동·하드드롭 후보와 폭 4 빔을 사용해 짧은 예산 내 관측 NEXT 한 개를 평가하도록 보완. 모든 끼워 넣기 경로의 완전 탐색은 아니며 기존 점수 목표 함수·명시적 오프너 모드는 유지.
  - 일반·긴급 평가에 다음 블록의 낙하 공간과 관측 입력 확인 시간을 반영한 불이익 추가. 안전 판정을 대신하는 조건이 아니라 중앙 탑으로 조작 여유를 잃는 배치를 예방하는 휴리스틱. 미확인 NEXT 순서 추측 없음.
  - PC 후보의 최초 배치에도 기존 경로 시간 검사를 적용하고 HOLD 전후 경로에 자신의 실측 HOLD 확인 시간을 반영. 실제 HOLD 이후 새 관측 확인도 유지. `execution_window_failed`/`controller_stop`에 원인·세대·실패 수를 기록해 공통 중지 문구의 실제 원인을 추적 가능하게 함.
  - F8·포커스·키 해제·관측/계획 나이·검증 플래그·HOLD 1회·입력 확인·연속 5회/블록당 8회 실패 중지·watchdog 조건 및 기존 표시 문구 유지. 실패 수 초기화나 안전 조건 완화 없음. 실제 게임에 키를 보내는 실행·진단은 수행하지 않음.
  - 기준 173개 → 179개 통과, 기존 골든 8개 일치, Ruff 0.14.2 포맷 통과·진단 113 유지. 기존 시간 의존 `test_core.RecognitionTests.test_preview_cache_timestamp`만 변경 후 전체 검사에서 1회 간헐 실패 후 단독 재실행 통과. 기대값·시간 제한 불변.
  - 새 테스트 6개: 실제 seq5154 보드의 NEXT 평가와 5칸→4칸 이하 배치, 다음 입력 여유 평가, HOLD 실측 시간, 안전 경로 없음, 실패 한도·F8·원인 기록, 런타임 HOLD 시간 전달. 결정 테스트는 시계를 고정했으므로 속도 개선의 증거가 아님.
  - 별도 모형(중력 12칸/초·이동 확인 180ms·HOLD 확인 300ms·화면 나이 70ms·NEXT 한 개·60ms 예산) 세 순서에서 각 60수의 경로 검사 통과. 최고 높이 4/7/4칸, PC 모두 0회. 실제 게임 후반 끊김 해결과 PC 성공률은 미검증.
  - 소스 및 새 `dist/TetrisAuto.exe` 시작 검사 started=true/auto_running=false, EXE frozen=true/tcl_bundled=true, 패키지 소스 대조 통과. 이전 EXE 보관. 전체 diff 자기 검토 완료, 기존 테스트·골든·data·fixtures·잠금 의존성·AGENTS.md 불변. 근거: `diagnostics/late_survival/`.

- [x] PC-GOAL — 일반 Auto를 퍼펙트 클리어 목표로 전환 — 2026-10-27
  - 사용자 요청: "후반에 가면서 오토가 끊겨", "자꾸 탑을 쌓아서", "퍼펙트 클리어를 목표로 하자". 동작 변경을 승인한 별도 작업이며 기존 F1~F5와 분리.
  - 일반 실행 경로에서 PC 목표를 명시하고 점수 오프너 자동 진입을 제외. 보이는 NEXT 한 개/HOLD만 사용하며 확인된 PC 경로는 점수 비교로 포기하지 않음. 경로가 없으면 줄 삭제·낮은 높이·구멍 감소를 평가하며 예상 점수는 표시용으로만 계산. 기존 점수 정책 함수와 명시적 오프너 모드는 보존.
  - 짧은 예산에서는 회전·이동·하드드롭 PC 후보부터 검사하고 검색 범위를 `pc_route_scope`에 기록. 완전 탐색이나 미래 PC 보장이 아님. 후반 긴급 탐색은 짧은 이동·회전을 먼저 검사하고 동일한 낮은 보드 평가 사용.
  - F8·포커스·키 해제·관측/계획 나이·HOLD 1회·입력 확인·불확실 인식·실패 제한·높은 보드 PC 생존 양보 조건 유지. controller/input/timing/recognition 코드 변경 없음. 실제 게임 키 입력 및 입력 진단 실행 안 함.
  - 기준 165개 → 173개 통과, 기존 골든 8개 일치, Ruff 0.14.2 포맷 검사 통과·진단 113 유지. 추가 테스트 8개: PC 우선, 두 O/HOLD PC 경로 재생, 점수 오프너 제외, 높이 평가, 관측 중력 경로, 짧은 회전 우선, 미확인 NEXT, 일반/긴급 실행 정책 연결. 최종 전체 검사 간헐 실패 없음.
  - 오프라인 비교 3개 7-bag 순서·NEXT 한 개·60ms·80수: 양쪽 모두 80수 재생, 기존 최고 높이 7/8/9 → PC 목표 6/7/6. 무작위 PC는 양쪽 모두 0회. 실제 게임의 후반 끊김 원인이나 해결을 확인한 결과는 아니며 PC 성공률 개선도 미검증.
  - 소스 및 갱신한 `dist/TetrisAuto.exe` 시작 검사 started=true/auto_running=false, EXE frozen=true/tcl_bundled=true. 패키지 소스 대조 통과. 자기 검토 완료, 기존 테스트·골든·data·fixtures·잠금 의존성 불변. 근거: `diagnostics/pc_goal/`.

- [x] FIX-LATE — NEXT 한 개 인식 및 후반부 실행 시간·복구 수정 — 2026-10-27
  - 사용자가 원인 설명 후 "그래 수정하도록"으로 이 동작 변경을 명시적으로 승인함. 완료된 리팩토링 및 기존 F1~F5와 별도 범위.
  - 저장된 실제 실행 기록에서 NEXT ROI가 세 블록을 포함해 135회 결정 모두 다음 큐가 비었고, 후반 조작 시간 부족으로 Auto가 정지한 것을 확인. 정지 이후 쌓인 화면만으로 최초 원인을 인식 실패라고 단정하지 않음.
  - NEXT 개수는 한 개 유지. 첫 프레임에 메뉴가 떠 있어 보정하지 못해도, 이후 0.5초 간격으로 기존 NEXT 영역 안의 첫 완전한 블록이 검증될 때만 영역을 축소. BOARD 재탐지 성공에 의존하지 않음. 영역 변경 시 키 해제·관측 무효화·검증 플래그 초기화·revision 갱신 후 저장되며, 불확실한 프리뷰를 추측하지 않음.
  - 이동·홀드·드롭의 실측 화면 확인 시간을 분리해 줄 삭제·블록 생성 시간이 이동 한 번의 시간에 섞이지 않도록 수정. HOLD는 자신의 실측 확인 시간도 확보되어야 함. 화면 확인 성공 조건과 홀드/드롭 2회 확인은 유지.
  - 일반 Auto의 실행 시간 부족 시 키를 해제하고 실패한 프레임보다 새로운 유효 관측에서 제한된 긴급 탐색으로 복구. 경로 안전 검증·프레임/계획 나이·포커스·F8·HOLD 1회·입력 확인·연속 5회/블록당 8회 실패 시 중지는 유지. 진단·오프너 모드는 기존처럼 즉시 중지. 불가능한 경로에서 강제로 입력하거나 F8 이후 재시작하지 않음.
  - 검증: 기준 153개 → 최종 165개 통과(추가 회귀 테스트 12개), 기존 골든 8개 일치, Ruff 0.14.2 포맷 통과·진단 113 유지. 최종 전체 검사 간헐 실패 없음. 중간 163개 검사에서 기존 `test_preview_cache_timestamp`만 1회 재실행 통과, 제한 시간·기대값 변경 없음.
  - 저장된 실패 화면 3장 재생: 기존 NEXT unknown → 첫 블록 J/I/J를 각각 올바르게 인식, 출력 슬롯은 모두 한 개. 새 회귀 테스트는 메뉴 이후 재인식·이동/전환 시간 분리·HOLD 시간 보장·새 프레임 재탐색·안전 경로 복귀·반복 실패 한도·F8/진단/오프너 차단을 검증.
  - 소스 및 새 `dist/TetrisAuto.exe` 시작 검사 started=true/auto_running=false, EXE frozen=true/tcl_bundled=true. 패키지의 전체 포함 소스 비교 all_match=true. 기존 EXE는 로컬 진단 폴더에 보관. 실제 게임에 키를 보내는 검증은 수행하지 않았으며, 실제 후반부 플레이 개선 여부는 아직 재검증하지 않음.
  - 변경: `src/controller.py`, `src/detection.py`, `src/runtime.py`, `tests/test_late_game_recovery.py`, 이 진행 문서. 기존 테스트·기대값·골든·fixtures·data·잠금 의존성·AGENTS.md 불변. 근거는 `diagnostics/late_game_fix/`.


- [x] ARTICLE-OPENERS — 요청 글 기반 스틱스핀·SDPC 개막 빌드 추가 — 2026-10-27
  - 사용자 요청: https://hse30.tistory.com/73 을 읽고 빌드 추가. 동작을 추가하는 별도 승인 작업이며 기존 F 항목과 분리. `data/openers/Stickspin.json`, `SDPC.json` 추가를 포함하는 범위.
  - 상세 글 `/1031`, `/483`의 기본 1~2가방 배치를 직접 좌표화. 두 빌드 각각 원형·좌우대칭, T스핀 싱글→더블, 14개 배치 후 기존 완료 중지. PC·DPC·트리플 후속 및 모든 가방 순서 지원은 아님.
  - `stage-targets` 형식의 가방 목표에서 정확한 중간 보드별 SRS 경로와 완성 가능한 전이만 컴파일. 현재 블록 우선, 확인된 HOLD 또는 NEXT 첫 개로 1회 교환만 허용. 보이지 않는 큐 추정 없음. 불일치 시 기존 중지. 저장된 파생 경로는 신뢰하지 않고 다시 검증.
  - 설정에 기본 제공 빌드 선택 추가. 불러오면 입력 중지·opener_enabled=false 유지. 기존 JSON 가져오기·TKI 지원 및 일반 Auto의 PC 목표 유지.
  - 기준 179개→185개 전체 통과(간헐 실패 없음), 기존 골든 8개 일치, Ruff 포맷 통과·진단 113 유지. 추가 6개 테스트: 전체 1,160개 전이 경로 재생·다음 완성 경로, 원문 2가방 시작 보드, 4변형 완성, 미확인 큐·HOLD 반복·보드 불일치 중지, 저장/재검증 및 파생 자료 위조 거부, 두 빌드 각 14개 모의 제어(NEXT 1개).
  - 소스 시작 검사 started=true/auto_running=false. 안전장치 파일 controller/input/timing/runtime/config/recognition 변경 없음. 기존 테스트·기대값·골든·lock·fixtures·기존 TKI 데이터 불변. 실제 게임 키 전송 및 입력 진단 실행 안 함. 실게임 성공률 미검증. 근거 `diagnostics/article_openers/`, 사용 안내 `docs/OPENERS_KO.md`.
  - `dist/TetrisAuto.exe` 재생성, EXE started=true/frozen=true/tcl_bundled=true/auto_running=false. 세 JSON의 EXE 포함 내용이 소스와 바이트 단위 일치. 바이너리는 배포 정책에 따라 로컬에만 보관. 전체 diff 자기 검토 완료.

- [x] LATE-MOVEMENT — 후반 조작 여유 평가와 이동 대기 감소 — 2026-10-27
  - 사용자 요청: 후반 확인 후 "이동이 너무 느려 빠르게도 부탁해", "다시 작업해줘". 후반 문제와 이동 속도 개선을 승인한 별도 작업. 기존 F 항목 및 완료한 정리와 분리.
  - 실제 `dist/diagnostics/sessions/20261027_143409`는 46,110점·레벨 8·71줄에서 종료. 중앙 탑 상승 이후 안전 경로 없음 5회로 중지했고, 이후 창 닫힘은 최초 원인이 아님. 기록된 190개 배치는 실제 입력 기록과 구분 없이 모의 성능으로 재해석하지 않음.
  - 이동·회전 ACK 프레임에서 남은 경로·프레임 나이·세대·보드·포커스·observation_guard를 다시 검사. 키 간격 만료나 탐색 완료 시에도 미확인 입력이 없고 기존 관측이 신선한 경우에만 재검사해 불필요한 다음 캡처 대기를 줄임. 키 누름/간격 35ms 기본값, HOLD·드롭 두 번 확인, 실패 한도·F8·키 해제·중력 경로·watchdog 조건 유지.
  - Latest에 관측 변경 알림을 추가해 제어 루프가 새 관측 도착 즉시 깨어나도록 변경. 기존 5ms 타임아웃은 유지. 다음 블록의 조작 여유 부족에 입력 확인 주기 단위의 제곱 불이익을 추가하며 안전 판정은 그대로 유지.
  - 기준 185개→191개 전체 통과, 간헐 실패 없음. 골든 8개 일치, Ruff 포맷 통과·진단 113 유지, 소스 started=true/auto_running=false. 추가 6개 회귀 검사: ACK 프레임 연속 진행, 키 간격 후 신선한 관측 재사용, 탐색 결과 대기 감소, 오래된/불확실/불일치 보드·포커스·F8·backend guard 중지, 관측 알림, 실제 후반 보드 배치 및 경로 시간 검사.
  - 실제 세대 247 보드의 오프라인 재생에서 중앙 13칸 대신 오른쪽 12칸 경로를 선택. 지연 화면 모형(50ms 캡처·40ms 처리 지연·누름/간격 각각 35ms·NEXT 한 개·중력 없음)의 동일 20개 배치/75회 입력: 9.450→7.655초, 2.116→2.613 PPS. 실제 게임 속도·생존 향상은 미검증. 실제 게임 입력이나 입력 진단은 실행하지 않음.
  - 자기 검토: 안전 게이트와 사용자 표시 문구 불변. 기존 테스트·기대값·골든·data·fixtures·의존성·AGENTS.md 불변. 근거 `diagnostics/late_movement/`, 설명 `docs/AUTO_STRATEGY_KO.md`.
  - 이전 EXE를 진단 폴더에 보관한 뒤 `dist/TetrisAuto.exe` 갱신. EXE started=true/frozen=true/tcl_bundled=true/auto_running=false, 포함된 전체 소스 대조 all_match=true. 바이너리는 로컬 배포물로만 보관.
