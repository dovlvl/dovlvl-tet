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
- [ ] B2 — 착지 계산 헬퍼 통일
- [ ] B3 — SRS 킥 조회 헬퍼
- [ ] B4 — 높이/구멍 계산 공통화
- [ ] B5 — 프레임 신선도 헬퍼
- [ ] B6 — 검증 플래그 리셋 헬퍼
- [ ] B7 — 영역 나열 헬퍼
- [ ] B8 — paths.py 경로 헬퍼
- [ ] B9 — 설정값 c[k]로 통일
- [ ] B10 — 안 쓰는 import 제거

## 테스트·빌드 정리
- [ ] T1 — 테스트 sys.path 일원화, Source를 helpers.py로 이동
- [ ] T2 — requirements-dev.txt 분리, Python 버전 문구 통일
- [ ] T3 — 안 쓰는 추적 파일 정리 (삭제 전 사용 여부 확인, 유지 목록 보존, 전체 테스트·골든·Ruff·시작 검사 필수)

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
