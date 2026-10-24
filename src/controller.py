"""Closed-loop controller: one acknowledged action at a time."""
import time,logging
from geometry import advance,settle,orientations,fits
from recognition import cellset
from planner import route_to
class AutoController:
    def __init__(self,pulse,config):self.pulse=pulse;self.c=config;self.running=False;self.phase='STOPPED';self.reason='중지됨';self.last_seq=-1;self.hold_used=False;self.failures=0;self.plan=None;self.wait=None;self.uncertain_since=None;self.block_failures=0;self.diagnostic=False;self.last_input='';self.last_ack='';self.frame_age_ms=0;self.blocks=0;self.raw_diagnostic=None;self.opener_variant=None
    def start(self,target,now):
        if self.pulse.backend.own_window(target):raise ValueError('게임 창을 클릭하고 F6을 누르세요.')
        logging.info('Auto start target=%s',target)
        self.blocks=0;self.raw_diagnostic=None;self.opener_variant=None
        self.pulse.arm(target);self.block_failures=0;self.diagnostic=False;self.running=True;self.phase='WAIT_VALID';self.reason='유효 상태 대기';self.hold_used=False;self.failures=0;self.wait=None;self.plan=None;self.uncertain_since=now;self.last_seq=-1
    def stop(self,reason='사용자 중지'):
        if self.running or self.reason!=reason:logging.info('Controller stop: %s',reason)
        self.running=False;self.phase='STOPPED';self.reason=reason;self.plan=None;self.wait=None;self.pulse.cancel()
    def replan(self,reason):
        self.plan=None;self.wait=None;self.phase='WAIT_VALID';self.reason=reason;self.last_ack=reason;self.failures+=1;self.block_failures+=1
        if self.failures>=5 or self.block_failures>=8:self.stop('입력 확인 반복 실패 (연속 5회 / 블록당 8회): 조작 키/입력 길이/영역을 확인하세요.')
    def accept_plan(self,packet,obs):
        if not self.running or self.pulse.abort.is_set() or not obs or not obs.active:return
        if packet['key']!=(obs.board_key,obs.active.kind,self.hold_used):return
        if packet['result'] is None:self.stop(packet.get('reason','현재 상태에서 배치 경로를 찾지 못했습니다.'));return
        self.plan=packet['result'];self.opener_variant=self.plan.get('opener_variant',self.opener_variant);self.phase='DECIDE';self.reason='배치 결정 완료'
    def tick(self,obs,now):
        if not self.running:return
        try:
            self.pulse.tick(now)
            if self.raw_diagnostic:
                action,started=self.raw_diagnostic
                if not self.pulse.focused():self.stop('진단 포커스 상실');return
                if now-started>max(.5,(self.c['press_ms']+self.c['gap_ms'])/1000):
                    self.last_ack='확인 불가: 단일 키 API 전송 완료. 게임판 클릭/키 설정 확인 필요'
                    self.stop(self.last_ack)
                return
            if not self.pulse.focused():self.stop('게임 창 포커스 상실');return
            if self.wait and now-self.wait['sent']>self.c['transition_ms']/1000 and self.phase in ('WAIT_DROP','WAIT_HOLD'):
                reason='INPUT_CONFIRMATION_ERROR: 드롭/홀드 후 새 상태를 확인하지 못했습니다.'
                if self.diagnostic and self.wait['action']=='hold' and not self.hold_clear(self.wait['before']):reason='RECOGNITION_ERROR: 홀드 키는 보냈으나 프리뷰 불확실 및 현재 블록의 명확한 교체 변화가 없어 성공 판정 불가'
                self.stop(reason);return
            if obs is None or now-obs.captured>self.c.get('frame_age_ms',200)/1000 or not obs.valid or obs.confidence<self.c['confidence']:
                self.uncertain_since=self.uncertain_since or now
                self.reason=obs.reason if obs and obs.reason else 'RECOGNITION_ERROR: BOARD/현재 블록 불확실 또는 오래된 프레임'
                # Release early on uncertainty, never keep pressing while blind.
                self.pulse.release_all()
                if now-self.uncertain_since>self.c['uncertain_ms']/1000:self.stop('인식 대기 시간 초과: '+self.reason)
                return
            self.uncertain_since=None
            if obs.seq==self.last_seq:return
            self.last_seq=obs.seq
            if self.wait:
                self.verify(obs,now);return
            if self.plan is None:self.phase='WAIT_VALID';return
            if self.plan['hold']:
                if not self.hold_clear(obs):self.replan('프리뷰 불확실: 홀드 없이 재탐색');return
                if self.hold_used:self.replan('한 블록당 홀드 1회 제한');return
                self.emit('hold',obs,now);return
            path=route_to(obs.fixed,obs.active.kind,obs.active.state,self.plan['cells'],self.c.get('rotation_confirmed',True))
            if path is None:self.replan('중력/지형 변화: 현재 위치에서 경로 재탐색');return
            self.emit(path[0],obs,now)
        except Exception as e:
            logging.exception('controller failed');self.stop('입력/제어 오류: '+str(e))
    def emit(self,action,obs,now):
        if obs is None or obs.active is None:raise ValueError('RECOGNITION_ERROR: 현재 블록 없이 입력할 수 없습니다.')
        age=(time.monotonic()-obs.captured)*1000
        if age>self.c.get('frame_age_ms',200):self.reason='RECOGNITION_ERROR: 입력 직전 프레임 나이 초과';return
        if action=='drop' and self.plan and 'expected_after' in self.plan:
            x,y,r=obs.active.state;p=orientations(obs.active.kind)[r]
            while fits(obs.fixed,p,x,y+1):y+=1
            expected=tuple(tuple(row) for row in settle(obs.fixed,p,x,y)[0])
            if expected!=tuple(tuple(row) for row in self.plan['expected_after']):self.stop('OPENER_BOARD_ERROR: 예상 고정 보드 불일치');return
        if not self.pulse.press(self.c['keys'][action],now,self.c['press_ms'],self.c['gap_ms']):return
        self.frame_age_ms=max(0,age);self.last_input=action;self.last_ack=action+' 확인 대기';logging.info('Input %s frame_age_ms=%.2f',action,self.frame_age_ms)
        wait={'action':action,'sent':now,'seq':obs.seq,'before':obs,'hits':0,'seen':False}
        if action=='drop':
            x,y,r=obs.active.state;p=orientations(obs.active.kind)[r]
            while fits(obs.fixed,p,x,y+1):y+=1
            wait['expected_board']=tuple(tuple(row) for row in settle(obs.fixed,p,x,y)[0]);self.phase='WAIT_DROP'
        elif action=='hold':self.phase='WAIT_HOLD'
        else:wait['expected']=advance(obs.fixed,obs.active.kind,obs.active.state,action);self.phase='WAIT_ACK'
        self.wait=wait;self.reason=action+' 입력 → 화면 확인 중'
    def verify(self,obs,now):
        w=self.wait
        if obs.seq<=w['seq'] or obs.captured<=w['sent']:return
        before=w['before'];action=w['action'];ok=False
        if action=='hold':
            expected=before.hold.kind or (before.queue[0] if before.queue else None)
            ok=obs.hold.valid and obs.hold.kind==before.active.kind and obs.active.kind==expected and min(y for x,y in obs.active.cells)<=3
            if self.diagnostic and not self.hold_clear(before):ok=obs.board_key==before.board_key and obs.active.kind!=before.active.kind and min(y for x,y in obs.active.cells)<=3
            # Require a visible change: same-kind swap is intentionally not auto-issued.
            ok=ok and (obs.hold.kind!=before.hold.kind or obs.active.kind!=before.active.kind or obs.queue!=before.queue)
        elif action=='drop':
            board_changed=obs.board_key!=before.board_key;queue_changed=obs.queue!=before.queue
            ok=obs.board_key==w['expected_board'] and min(y for x,y in obs.active.cells)<=3 and (board_changed or queue_changed)
        else:
            expected=w['expected']
            if expected is not None and obs.active.kind==before.active.kind and obs.board_key==before.board_key:
                x,y,r=expected
                ok=any(cellset(obs.active.kind,(x,y+dy,r))==obs.active.cells for dy in range(4))
        if ok:
            w['hits']+=1
            if action in ('hold','drop') and w['hits']<2:return
            self.wait=None;self.failures=0;self.last_ack=action+' 실제 화면 변화 확인';self.reason=self.last_ack
            if self.diagnostic:self.stop('입력 진단 성공: '+self.last_ack);return
            if action=='hold':self.block_failures=0;self.hold_used=True;self.plan=None;self.phase='WAIT_VALID'
            elif action=='drop':
                self.blocks+=1;self.block_failures=0;self.hold_used=False;self.plan=None;self.phase='WAIT_VALID'
                if self.c.get('auto_mode','continuous')=='one':self.stop('한 블록 완료: 고정 및 새 블록 화면 확인')
            else:self.phase='DECIDE'
        else:
            w['hits']=0
            if action not in ('hold','drop') and now-w['sent']>self.c['ack_ms']/1000:
                self.pulse.release_all()
                if self.diagnostic:self.stop('INPUT_CONFIRMATION_ERROR: 진단 키의 실제 이동/회전을 확인하지 못했습니다.');return
                self.replan('이동/회전 실패 또는 상태 불일치: 최신 화면 재탐색')

    def hold_clear(self,obs):
        return self.c.get('preview_verified',False) and obs.hold.valid and obs.hold.state!='disabled' and all(r.valid and r.kind is not None for r in obs.nexts) and bool(obs.nexts)
    def begin_diagnostic(self,target,obs,action,now):
        if not obs or not obs.valid or now-obs.captured>self.c.get('frame_age_ms',200)/1000 or action=='down':
            self.start(target,now);self.diagnostic=True;self.raw_diagnostic=(action,now)
            self.pulse.press(self.c['keys'][action],now,self.c['press_ms'],self.c['gap_ms'])
            self.last_input=action;self.last_ack='API 전송 완료 / 실제 화면 변화 확인 불가';self.phase='DIAGNOSTIC';return
        self.start(target,now);self.diagnostic=True;self.emit(action,obs,now)
