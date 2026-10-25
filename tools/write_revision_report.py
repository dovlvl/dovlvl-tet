"""Generate an evidence-based report from completed JSON comparisons."""
import json,re,hashlib,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read(name):return json.loads((ROOT/'diagnostics'/name).read_text(encoding='utf-8'))
def combine(prefix,index=0):
    runs=[read(f'{prefix}_common_{i}.json')['pipelines'][index] for i in (1,2)]
    def metric(name):
        entries=[p['telemetry']['metrics'].get(name,{'n':0,'mean':0}) for p in runs]
        return sum(e['mean']*e['n'] for e in entries)/max(1,sum(e['n'] for e in entries))
    return dict(confirmed=sum(p['confirmed'] for p in runs),seconds=sum(p['seconds'] for p in runs),
                pps=sum(p['confirmed'] for p in runs)/sum(p['seconds'] for p in runs),
                pps_range=[min(p['pps'] for p in runs),max(p['pps'] for p in runs)],
                capture_ms=metric('capture_grab_ms'),recognition_ms=metric('recognition_ms'),search_ms=metric('search_ms'),
                search_roundtrip_ms=metric('search_roundtrip_ms'),input_ack_ms=metric('input_ack_ms'),drop_ack_ms=metric('drop_ack_ms'),
                block_ms=metric('block_ms'),valid=sum(p['recognition_ground_truth']['valid'] for p in runs),
                wrong_valid=sum(p['recognition_ground_truth']['wrong_valid'] for p in runs),
                total=sum(p['recognition_ground_truth']['total'] for p in runs),
                target_success=sum(p['target_success'] for p in runs),target_attempts=sum(p['target_attempts'] for p in runs),
                pc_success=sum(p['pc_success'] for p in runs),errors=[p['error'] for p in runs if p['error']])

if __name__=='__main__':
    before,after=combine('before'),combine('after')
    pc_before,pc_after=combine('before',1),combine('after',1)
    micro_before,micro_after=read('recognition_before.json'),read('recognition_after.json')
    fast=read('after_fast.json')['pipelines'][0]
    scores_before,scores_after=read('score_before.json'),read('score_after.json')
    testbytes=(ROOT/'test_latest_results.txt').read_bytes()
    testlog=testbytes.decode('utf-16' if testbytes.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
    test_match=re.search(r'Ran (\d+) tests in ([\d.]+)s',testlog)
    assert test_match and '\nOK\n' in testlog.replace('\r','') and not re.search(r'^FAILED',testlog,re.M)
    report=dict(kind='synthetic_RGB_and_real_clock_mock',real_windows_game=dict(tested=False,actual_pps=None,actual_score=None,
                spin_judgment_verified=False,lock_rules_verified=False,combo_bonus_verified=False,pc_bonus_verified=False),
                before=before,after=after,pc_before=pc_before,pc_after=pc_after,recognition_before=micro_before,recognition_after=micro_after,
                fast_input=fast,tests=int(test_match[1]),test_seconds=float(test_match[2]),
                baseline_data_identical=True,common_input=dict(press_ms=35,gap_ms=35,capture_fps=60,vision_fps=60,configured_budget_ms=160),
                new_effective_realtime_cap_ms=60,source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').glob('*.py')})
    (ROOT/'diagnostics/revision_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for label,key in [('캡처/캡처원 처리','capture_ms'),('인식','recognition_ms'),('탐색 자체','search_ms'),('탐색 왕복','search_roundtrip_ms'),('입력→실제 화면 확인','input_ack_ms'),('드롭→다음 상태 확인','drop_ack_ms'),('블록 전체 처리','block_ms')]:
        rows.append(f"| {label} | {before[key]:.2f} | {after[key]:.2f} |")
    score_rows=[]
    for old,new in zip(scores_before['cases'],scores_after['cases']):
        def val(p):
            e=p['independent_model_projection'] or {}
            return f"{(p['chosen'] or {}).get('lines','?')}줄 / {e.get('spin','?')} / {e.get('expected_points','?')}"
        score_rows.append(f"| {new['name']} | {val(old)} | {val(new)} | {'예' if new['route_replayed'] else '아니오'} |")
    text=f'''# 분석·수정·검증 보고서

## 실제 원인과 변경 파일

1. `strategy.py`, `planner.py`: 기존 평가는 실제 점수가 아닌 지형 가중치였고, 스핀 회전 이력·B2B·입력 비용이 충분히 반영되지 않았다. 공개 점수표 모델과 지형 위험을 분리하고 입력 시간 비용을 강화했다. 시간/빔 제한 탐색이라 전체 최적은 보장하지 않는다.
2. `scoring.py`, `controller.py`: T스핀은 최종 회전·세 모서리·앞쪽 모서리·킥 경로를 검사한다. 실제 경로가 달라지면 스핀 계획을 재탐색한다. 확인된 고정 결과만 모델 점수 이력에 반영하며 실제 사이트 점수 필드는 비워 둔다. 같은 종류 HOLD도 낮은 위치에서 재생성이 유리하면 고려한다.
3. `recognition.py`: 동일 픽셀에도 색상·도형 추론을 반복했고 strided 배열의 `tobytes()` 비용이 컸다. 연속 메모리 CRC, 동일 보드 재사용, 고정 후보 캐시를 적용했다. 새 캡처 시각과 같은 프레임의 HOLD/NEXT는 계속 읽는다.
4. `runtime.py`, `input_win.py`: 160ms 탐색을 반복하며 오래된 결과를 폐기하는 비용이 컸다. 실시간 탐색 상한을 60ms로 두고 중력 창이 짧으면 더 줄인다. 작업 프로세스를 미리 준비하고 확인된 입력은 즉시 해제한다. 화면 확인을 없애지 않는다.
5. `openers.py`: HOLD 후 계획에 `kind`가 빠질 수 있는 오류를 발견해 수정했다. 명시된 단계 보드·키 경로와 마지막 T스핀을 검사한다. 남은 순서를 전부 확인할 수 없으면 개막을 선택하지 않는다.
6. `gui.py`, `ui_status.py`: 메인에는 버튼 4개와 상태 한 줄만 남겼다. 전체 JSON/좌표/시간/오류/캡처는 설정의 별도 진단 창과 파일로 옮겼다. F6/F8, 종료 시 키 해제는 유지한다.
7. 기존 드롭 전환 오류의 원인은 공유한 과거 관측의 `active=None` 변경이었다. 독립 사본·전환 대기 만료·세대/vision_epoch 검사는 유지했고 빈 블록 프레임에서도 캡처·재인식이 계속되는 회귀 검사를 통과했다.

## 같은 조건의 속도·정확도 비교

준비된 같은 기준 데이터, 같은 보드/큐, 캡처/인식 60 FPS, 입력 35/35ms, 설정 탐색 상한 160ms로 버전별 별도 프로세스를 순차 실행했다. 새 버전의 실시간 유효 상한 60ms는 의도한 변경이다. 빌드와 다른 테스트를 동시에 실행하지 않았다. 원본 격리 폴더에 기준 데이터가 누락된 예비 측정은 최종 결과에서 제외하고, 동일 데이터를 복사한 뒤 다시 측정했다.

12블록 실행을 버전별 2회씩 수행했다. 아래 시간은 표본 수로 가중한 평균(ms)이다. 캡처원은 실제 화면이 아니라 RGB를 생성하는 모의 캡처원이므로 Windows 데스크톱 캡처 속도로 해석하지 않는다.

| 단계 | 수정 전 ms | 수정 후 ms |
|---|---:|---:|
{chr(10).join(rows)}

- 수정 전 확인된 배치: {before['confirmed']}개 / {before['seconds']:.3f}초, 합산 {before['pps']:.3f} PPS (실행별 {before['pps_range'][0]:.3f}~{before['pps_range'][1]:.3f}).
- 수정 후 확인된 배치: {after['confirmed']}개 / {after['seconds']:.3f}초, 합산 {after['pps']:.3f} PPS (실행별 {after['pps_range'][0]:.3f}~{after['pps_range'][1]:.3f}).
- 유효 판독 중 오판: 전 {before['wrong_valid']}/{before['valid']}, 후 {after['wrong_valid']}/{after['valid']}. 전체 프레임 수 전 {before['total']}, 후 {after['total']}; 나머지는 시작/전환/불확실을 포함한다. 유효 판독 정확도를 전체 프레임 검출률로 부르지 않는다.
- 계산한 위치 도달: 전 {before['target_success']}/{before['target_attempts']}, 후 {after['target_success']}/{after['target_attempts']}.
- 두 O를 사용하는 별도 PC 시나리오: 전 {pc_before['pc_success']}/2, 후 {pc_after['pc_success']}/2회 PC 확인.
- 준비된 동일 RGB 240프레임: 평균 {micro_before['mean_ms']:.3f}→{micro_after['mean_ms']:.3f}ms, p95 {micro_before['p95_ms']:.3f}→{micro_after['p95_ms']:.3f}ms. 양쪽 유효 240/240, 오판 0. 렌더링·시작 비용은 이 수치에서 제외했다.
- 별도 빠른 입력 20/15ms 시험: {fast['confirmed']}개 / {fast['seconds']:.3f}초 = {fast['pps']:.3f} PPS. 이는 입력 시간이 다른 조건이다. 같은 조건의 비교와 섞지 않는다.

실행 시간은 운영체제 스케줄링과 경로 선택에 따라 달라진다. 일반적인 최대 PPS나 실제 게임 PPS를 보장하지 않는다. 원시 JSON과 전체 보드·큐는 `diagnostics/`에 포함했다.

## 동일 보드·큐의 선택과 점수 비교

200ms/깊이 2, 레벨 1, B2B가 이미 연결됐다는 **모의 가정**으로 양쪽 경로를 독립 재생했다. 표는 `삭제 줄 / 모델 스핀 / 모델 예상 점수`다. 예상 점수는 공격량이 아니며 실제 게임 점수도 아니다. 미확인 콤보·PC 보너스는 0이다.

| 고정 시나리오 | 수정 전 | 수정 후 | 새 경로 도달 검증 |
|---|---|---|---|
{chr(10).join(score_rows)}

모든 예제에서 선택이 개선되었다고 주장하지 않는다. 회전/HOLD PC와 T스핀 더블은 양쪽이 같은 결과를 선택한 경우도 있다. 낮은 위치의 같은 종류 HOLD는 새 버전에서 1줄 득점 경로를 찾았다. 결과는 해당 탐색 범위 안의 선택이다.

## 테스트·빌드·실게임 구분

- 전체 unittest: {report['tests']}개 통과 ({report['test_seconds']:.3f}초). 빈 드롭 전환·줄 삭제·다음 블록 재인식·연속 Auto, 오래된 계획/입력 거부, 회전/HOLD, T스핀 모서리/마지막 회전, PC의 보드 완전 비움, B2B 이력 등을 포함한다.
- GUI 검사: 메인에 버튼 4개 + 상태 한 줄만 있는지, 설정·진단이 별도 창인지, 모의 백엔드에 실제 입력을 보내지 않는지 확인했다.
- EXE 빌드 후 Tcl/Tk 포함·실제 GUI 시작 검사·현재 소스와 내장 모듈 일치 결과는 별도 `exe_startup_highspeed.json`, `embedded_source_check.json`을 제공한다.
- **실제 Windows 테트리스 연속 Auto PPS·실제 점수 변화·현재 게임 T스핀/미니/PC/콤보 판정·고정 시간 일치는 미검증**이다. 실제 점수를 측정한 것처럼 모의 수치를 제시하지 않는다.
- 공개 게임 소스 조회는 403/브라우저 차단으로 실패했다. 실제 게임에서 SRS와 고정 시간이 다르면 설정을 맞추고 다시 검증해야 한다. 확인하지 않은 고정 지연은 자동 확정하지 않았다.
- 구현된 개막은 명시 순서 TKI + 좌우 대칭이다. 모든 가방 분기·LST/ST 전체·확률형 PC 빌드를 학습했다고 주장하지 않는다. 자료별 읽은 범위와 제한은 `STRATEGY_SOURCES_KO.md`에 기록했다.

## 재현

`tools/run_revision_benchmarks.py`는 비교를 순차 실행한다. 별도 `score_before/after.json`에 동일 보드와 경로가 모두 남는다. `tools/benchmark_recognition.py`는 준비된 RGB만 측정한다. 실제 Windows 게임 기록은 사용자가 설정의 로그·진단 캡처 저장으로 남길 수 있다.

기준 자료: [요청한 글](https://hse30.tistory.com/73), [공식 게임 점수·키 표](https://play.tetris.com/games/). 세부 출처는 자료 문서에 연결했다.
'''
    (ROOT/'docs/VALIDATION_REPORT_KO.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(before_pps=before['pps'],after_pps=after['pps'],tests=report['tests'],real_game=False)))
