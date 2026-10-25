# 드롭 전환 중 vision_loop 종료 수정

## 확인한 실제 오류

기존 로그에서 추출한 전체 traceback: `diagnostics/reported_vision_traceback.txt`.

호출 순서: `Session.guard` → `Session.vision_loop` → `MotionTracker.update`.
실패 표현식은 `previous.active.state[2]`이며 `None`이 된 변수는
`previous.active`다. 추적기가 이전 Observation 객체를 그대로 보관한 상태에서
팝업 판정이 같은 객체의 `active`를 None으로 변경했다.

## 변경한 동작

- 팝업 판정 후 모션을 추적하고, 추적기의 과거 관측과 이동 기준점은 독립된 사본으로 저장한다.
- 현재 블록이 없으면 모션 연속성을 해제한다. 캡처·재인식·관측 발행은 계속된다.
- 현재 블록이 없거나 프레임이 불확실하면 키를 해제하며 해당 블록 탐색을 보류한다.
- 짧은 전환은 기존 드롭·HOLD 확인을 이어간다. 제한 시간을 넘으면 이전 대기와 계획을 폐기하고 새 관측에서 재동기화한다. 확인되지 않은 드롭을 성공으로 세지 않는다.
- 복구 구간 이전 탐색 결과는 vision_epoch와 블록 generation으로 거부한다.
- 실제 작업 예외는 숨기지 않는다. 전체 traceback을 세션 진단 폴더의 `<worker>_loop_traceback.txt`에 저장하고 작업을 중단한다.
- 작업 중단이나 오래된 프레임에는 실시간 FPS·처리 시간을 `—`로 표시한다. 작업 상태와 캡처·인식 마지막 성공 시각을 표시하며 진단 데이터에도 상태와 traceback 파일 위치를 포함한다.

## 검증

전체 unittest 135개 통과. GUI 구성 검사 통과.
드롭마다 120ms 동안 현재 블록이 없는 RGB 프레임을 넣는 실제 스레드 파이프라인 테스트에서
줄 2개 삭제, 연속 드롭 4회 확인, 빈 블록 관측 10개 처리 및 캡처·vision·control 스레드 생존을 확인했다.
작업 실패 traceback 저장, 39초 된 프레임의 과거 성능 수치 숨김,
새 블록 미생성 시 드롭 대기 만료도 별도로 검증했다.

실제 Chrome 게임에서의 재검증은 아직 수행하지 않았다.
