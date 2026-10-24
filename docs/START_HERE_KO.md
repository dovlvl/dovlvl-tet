# 수정본 실행 및 진단 순서

압축을 새 폴더에 풀고 run_windows.bat(Python 3.11+ x64) 또는 dist/TetrisTrainer_v06_fixed.exe를 실행합니다. 일반 Chrome/Edge + Windows 캡처 방식입니다. F6 시작·중지 / F8 긴급 중지와 키 해제.

1. 실제 게임 창을 고르고 입력 진단부터 실행합니다. HOLD는 C, 좌우/아래는 방향키, 하드드롭은 Space입니다. 회전은 게임 설정을 직접 확인하고 키를 지정하세요. Blox의 C=180도 회전/왼쪽 Shift=HOLD는 실제 게임에 적용하지 않습니다.
2. 게임 찾기 또는 수동 영역 지정. BOARD 10×20 내부를 지정하고 HOLD 및 각 NEXT 슬롯은 글자/테두리보다 블록과 여백을 포함하도록 별도 지정합니다. NEXT 1이 맨 위입니다. 확대/축소 또는 슬롯 개수가 다르면 수동 수정하세요.
3. ‘HOLD·NEXT 진단’에서 각 슬롯 원본·처리 마스크·정규화와 ROI/bbox를 확인합니다. empty=빈 HOLD, disabled=어두운 사용 불가 후보, unknown=판독 실패입니다. NEXT의 ?를 임의 블록으로 채우지 않습니다.
4. 기본 Auto one 모드로 한 블록의 실제 목표 배치를 확인한 뒤 continuous로 연속 배치를 확인합니다. 프리뷰 검증 체크를 하지 않으면 기본 배치는 현재 블록만 사용합니다. HOLD 키를 바꿨다는 사실로 프리뷰 검증을 완료 처리하지 마세요.
5. 실제 프리뷰를 비교하려면 ‘진단 캡처 저장’을 누릅니다. 화면에 표시된 폴더의 _raw.png, .json 및 슬롯별 raw/mask/normalized 파일을 사용하세요. 원본에는 게임 정보가 포함될 수 있으니 공유할 파일은 직접 확인하세요.
6. 오프너는 위 검증 뒤에 사용합니다. ‘빌드 JSON 가져오기’에서 data/openers/TKI_Fonzie.json 선택. 이는 Blox의 명시적 7단계 1변형이며 전체 TKI 큐 조건을 지원하지 않습니다. 가져오기만으로 실행하지 않습니다. 설정에서 현재 게임 프리뷰/기본 Auto 실제 검증 완료를 기록하고 continuous·회전 확인 후 빌드 실행을 체크하세요. HOLD가 필요하다면 키 C 및 HOLD 사용도 별도로 활성화하세요. 조건 불일치 시 이유를 표시하고 중지합니다.
7. 설정 창은 세로 스크롤됩니다. 대상/영역/키/인식 임계값이 바뀌면 관련 검증을 다시 수행하세요. 전역 키 등록 오류가 있으면 설정에서 F1~F24 중 다른 키로 바꿀 수 있습니다.

## 실제 캡처 전후 비교
전체 무주석 캡처와 같은 이름의 메타데이터 JSON을 준비합니다. 예:
```
.venv\Scripts\python src\preview_compare.py diagnostics\20261025_120000_raw.png diagnostics\20261025_120000.json --output real_comparison
```
비교 JSON에 이전 판독/새 판독을 함께 기록하고 슬롯별 원본·마스크·정규화를 저장합니다. 실제 정답은 사용자가 직접 확인해야 하며 프로그램이 정확도를 자동 인증하지 않습니다. 

## 빌드 데이터 지원 형식
data/openers/TKI_Fonzie.json이 실제 지원 데이터입니다. tetris-opener-v1 JSON: 출처 source, 이름 name, 좌표 visible-10x20-x-right-y-down, 변형 배열 variants, 각 변형의 name/order_status=explicit/hold_policy=visible-only-single-hold, 단계별 kind와 네 개의 절대 cells가 필수입니다. x=0~9 좌→우, y=0~19 위→아래. 실행 회전 r=0~3 시계 방향/SRS이며 cells가 기준입니다. 검증 시 expected_before/expected_after/lines/state를 계산하고 기존 값이 있으면 일치를 검사합니다. 초기 보드는 빈 보드만 지원합니다. 완료는 모든 단계 고정/보드 확인, 실패는 보드·큐·HOLD·경로·입력 확인 불일치입니다. 동적 조건, 순서 없는 완성 모양, 알 수 없는 분기 데이터는 실행하지 않습니다.

사용자가 보유한 Blox의 공개 모듈 파일 중 명시적 Piece 배열만 가져올 수도 있습니다(자바스크립트 실행 없음):
```
.venv\Scripts\python src\blox_import.py opener-module.js imported.json --name TKI --variation Fonzie --url https://blox-server.herokuapp.com/js/dist/chunks/opener-NCSNWVO7.js
```
사이트 갱신으로 구문이 달라지면 실패하도록 구현했습니다. 내려받지 못했거나 원본에 순서가 없으면 이를 학습/실행 가능으로 취급하지 않습니다. 네트워크 접근 및 자료 사용 조건은 출처를 확인하세요. Blox 키 프로필은 data/site_profiles.json에 참고용으로만 있습니다.

검증/제한: 실제 게임과 사용자 캡처 비교는 미검증입니다.

로그는 %USERPROFILE%/.tetris_trainer/trainer.log, 설정은 config_v6.json입니다. ‘로그 저장’으로 실행 파일/소스 옆 diagnostics에 복사합니다. 전체 테스트는 .venv\Scripts\python -m unittest discover -s tests -v, 빌드는 build_windows.bat입니다.
