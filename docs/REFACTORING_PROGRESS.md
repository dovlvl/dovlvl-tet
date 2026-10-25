# 리팩토링 진행 상황

항목 설명은 [REFACTORING_GUIDE_KO.md](REFACTORING_GUIDE_KO.md) 참고. 위에서부터 순서대로 하나씩 처리합니다.

표기: `[ ]` 대기 · `[x]` 완료 · `[-]` 건너뜀. 완료/건너뜀 뒤에 `— 날짜 / 결과 또는 사유`를 적습니다.

## 단계 A — 포매터 (G보다 먼저 완료됨)
- [x] A — Ruff 포매터 적용 — 2026-10-26 / 커밋 `b53c30f`
  - Ruff 0.14.2, 120열. `src`, `tests`, `tools`의 Python 파일 57개와 `pyproject.toml`.
  - 전체 테스트: 변경 전 145개 통과, 변경 후 145개 통과. 중간 검사에서 시간 의존 테스트가 4개/2개 간헐 실패 후 재검사 통과.
  - Python AST 57개 및 주석 모두 동일 (외부 재확인 완료). `ruff format --check` 통과. Ruff 진단 2496→170, lint 자동 수정 안 함.
  - Windows 시작 검사: `started=true`, `auto_running=false`.

## 단계 G — 골든 스냅샷 (다음 항목)
- [ ] G — 결정적 결과 스냅샷 테스트 생성

## 단계 B — 기계적 정리
- [ ] B1 — cellset을 geometry.py로 이동
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
