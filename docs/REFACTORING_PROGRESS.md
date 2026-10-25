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
- [ ] B6 — 검증 플래그 리셋 헬퍼
- [ ] B7 — 영역 나열 헬퍼
- [ ] B8 — paths.py 경로 헬퍼
- [ ] B9 — 설정값 c[k]로 통일
- [ ] B10 — 안 쓰는 import 제거

## 테스트·빌드 정리
- [ ] T1 — 테스트 sys.path 일원화, Source를 helpers.py로 이동
- [ ] T2 — requirements-dev.txt 분리, Python 버전 문구 통일
- [ ] T3 — 안 쓰는 추적 파일 정리 (삭제 전 사용 여부 확인, 유지 목록 보존, 전체 테스트·골든·Ruff·시작 검사 필수)

## CI — GitHub Actions 검증 추가 (T3 다음, C1 전)
- [ ] CI — GitHub Actions 검증 추가
  - `.github/workflows/ci.yml`: main push마다 windows-latest, Python 3.12. 잠금 의존성·지정 Ruff 설치 → 포맷 검사 → 전체 unittest(골든 포함).
  - Ruff 진단 수는 기준값 파일보다 증가할 때만 실패. 시간 의존 테스트 실패 시 해당 테스트만 최대 2회 재실행하며 제한 시간·기대값은 유지.
  - CI에서 실제 키 입력·GUI 실행·시작 검사 금지. 다른 항목과 같은 검증 게이트 통과 및 push 후 첫 CI 실행 성공 확인까지 완료 조건.

## 단계 C — 구조 개선
- [ ] C1 — 상태 속성 __init__/reset에 명시
- [ ] C2 — auto_plan/opener_plan 키워드 인자화
- [ ] C3 — PendingAction dataclass, Phase Enum
- [ ] C4 — Placement dataclass
- [ ] C5 — Observation 필드 정리
- [ ] C6 — 사유 코드 enum

## 단계 D — 큰 함수/클래스 분리
- [ ] D1 — gui.App 분리
- [ ] D2 — planner.plan 분리
- [ ] D3 — Recognizer.process 분리
- [ ] D4 — Session.control_loop 분리
- [ ] D5 — controller.tick/emit 중복 정리

## 별도 버그 수정 (사람 확인 필요 — Codex는 진행하지 않음)
- [-] F1 — recognition.py 보드 ROI None 처리
- [-] F2 — runtime 디버그 모드 이중 put/beat
- [-] F3 — gui 설정 파일 중복 저장
- [-] F4 — recognition components() 이중 계산
- [-] F5 — builtin_book 이중 컴파일

## 발견한 버그 (작업 중 Codex가 기록, 수정하지 않음)

- 시간 제한에 의존하는 시뮬레이션 테스트가 실행 부하에 따라 간헐적으로 실패함 (A 작업 중 발견). 수정하지 않음.

## 로컬 정리 (D5와 F 다음, 맨 마지막)
- [ ] Z — 로컬 예전 배포본·진단 파일 정리
  - 실행 시 삭제 목록과 항목별·전체 용량을 먼저 기록한다. 가이드의 허용 목록에 해당하는 미추적 파일만 삭제하며 `.venv/`, `dist/TetrisAuto.exe`, 모든 추적 파일과 저장소 밖 파일은 보존한다.
  - 삭제 후 추적 파일 무변경 확인, 전체 테스트·시작 검사 통과, 실제 확보 용량 기록 후 진행 문서만 커밋·push한다. `main`에서 브랜치 없이 진행 가능.
