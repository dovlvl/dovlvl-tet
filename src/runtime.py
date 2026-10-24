import threading,time,copy,multiprocessing,logging
from queue import Queue,Empty
from concurrent.futures import ProcessPoolExecutor
from config import union,validate
from recognition import Recognizer
from planner import plan
from openers import load_book,opener_plan
from detection import panel_occluded,fit_grid
from windows import shifted,same_size
class Latest:
    def __init__(self):self.lock=threading.Lock();self.value=None
    def put(self,v):
        with self.lock:self.value=v
    def get(self):
        with self.lock:return self.value
class Session:
    def __init__(self,c,controller,windows=None,source_factory=None):
        self.c=copy.deepcopy(c);self.controller=controller;self.windows=windows;self.source_factory=source_factory;self.lock=threading.RLock();self.stop_event=threading.Event();self.frames=Latest();self.observations=Latest();self.last_image=Latest();self.preview_debug=Latest();self.recognizer=Recognizer();self.threads=[];self.pool=None;self.future=None;self.job=None;self.search_ms=0;self.revision=0;self.need_detection=False;self.visibility_error='';self.error='';self.diagnostic_due=None;self.last_diagnostic='';self.last_packet=None;self.opener_book=None;self.commands=Queue();self.generation=0;self.health={k:{'last':time.monotonic(),'count':0,'ms':0} for k in ('capture','vision','control','search')}
    def request_toggle(self,target):
        self.commands.put((self.generation,target))
    def beat(self,stage,begin):
        h=self.health[stage];h.update(last=time.monotonic(),count=h['count']+1,ms=(time.monotonic()-begin)*1000)
    def watchdog_loop(self):
        while not self.stop_event.wait(.05):
            now=time.monotonic()
            try:self.controller.pulse.tick(now)
            except Exception:self.emergency('포커스 상실 또는 키 해제 오류')
            for stage in (('control',) if getattr(self,'diagnostic_only',False) else ('capture','vision','control')):
                if now-self.health[stage]['last']>2:
                    self.emergency('WORKER_STALL: '+stage+' 마지막 정상 처리 2초 초과')
            if self.future and now-self.future_started>3:
                self.emergency('SEARCH_TIMEOUT: 배치 탐색 3초 초과');self.future.cancel()
    def start(self,diagnostic_only=False):
        self.diagnostic_only=diagnostic_only
        validate(self.c,not diagnostic_only);self.pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
        for fn in ((self.control_loop,self.watchdog_loop) if diagnostic_only else (self.capture_loop,self.vision_loop,self.control_loop,self.watchdog_loop)):
            t=threading.Thread(target=self.guard,args=(fn,),daemon=True);self.threads.append(t);t.start()
    def guard(self,fn):
        try:fn()
        except Exception as e:
            logging.exception('%s failed',fn.__name__);self.error=fn.__name__+': '+str(e)
            try:self.emergency(self.error)
            finally:self.stop_event.set()
    def emergency(self,reason='F8 긴급 중지'):
        self.generation+=1
        errors=[]
        try:self.controller.pulse.cancel()
        except Exception as e:errors.append(str(e));logging.exception('Key release failed')
        with self.lock:
            self.diagnostic_due=None
            try:self.controller.stop(reason)
            except Exception as e:errors.append(str(e));logging.exception('Controller release failed')
            if errors:self.controller.running=False;self.controller.phase='ERROR';self.controller.reason='KEY_RELEASE_ERROR: '+' / '.join(errors)
    def stop(self):
        self.emergency('세션 중지');self.stop_event.set()
        for t in self.threads:t.join(timeout=.5)
        if self.pool:self.pool.shutdown(wait=False,cancel_futures=True)
    def schedule_diagnostic(self,action,target,now):
        self.emergency('입력 진단 준비')
        with self.lock:self.controller.diagnostic=False;self.diagnostic_due=(now+self.c.get('input_countdown',3),action,target);self.last_diagnostic='예약됨: '+action
    def monitor(self,source,now):
        if not self.windows:return
        target=self.c['target'];info=self.windows.info(target['hwnd'])
        if info['pid']!=target['pid']:raise OSError('대상 HWND가 다른 프로세스로 바뀌었습니다. 게임 찾기를 다시 실행하세요.')
        old=self.c['client'];new=info['client']
        if not same_size(old,new):
            self.emergency('LAYOUT_CHANGED: 창 크기 변경. 재탐지 중 입력 중지');self.need_detection=True;return
        if old[:2]!=new[:2]:
            self.emergency('창 이동 감지: 좌표 보정 완료 후 F6으로 재시작하세요.')
            with self.lock:
                self.c.update(shifted(self.c,old,new));self.c['client']=new;self.revision+=1;self.observations.put(None)
        boxes=[self.c['board'],self.c['hold'],*self.c['next_slots']]
        visible,why=self.windows.visible_regions(target['hwnd'],boxes)
        self.visibility_error='' if visible else why
        if not visible:
            if not self.diagnostic_due or now>=self.diagnostic_due[0]:self.emergency('VISIBILITY_ERROR: '+why)
            self.observations.put(None)
    def capture_loop(self):
        import numpy as np
        if self.source_factory:source=self.source_factory()
        else:
            import mss
            source=mss.mss()
        last_check=0
        try:
            while not self.stop_event.is_set():
                begin=time.monotonic()
                if begin-last_check>.1:self.monitor(source,begin);last_check=begin
                if not self.visibility_error and not self.need_detection:
                    with self.lock:c=copy.deepcopy(self.c);rev=self.revision
                    box=union(c);x,y,r,b=box
                    grab_begin=time.monotonic();frame=source.grab({'left':x,'top':y,'width':r-x,'height':b-y});rgb=np.asarray(frame)[:,:,:3][:,:,::-1].copy()
                    self.frames.put((time.monotonic_ns(),grab_begin,rgb,box,(time.monotonic()-grab_begin)*1000,rev,c))
                    self.beat('capture',begin)
                self.stop_event.wait(max(.001,1/self.c['capture_fps']-(time.monotonic()-begin)))
        finally:source.close()
    def vision_loop(self):
        last=None;rev=None;seq=0;fps_start=time.monotonic();count=0;fps=0;grid_check=0;bad_grid=0
        while not self.stop_event.is_set():
            begin=time.monotonic();f=self.frames.get()
            if f and f[0]!=last and not self.visibility_error and not self.need_detection:
                key,captured,rgb,box,cap_ms,revision,c=f;last=key
                if revision!=self.revision:continue
                if revision!=rev:self.recognizer=Recognizer();rev=revision
                x,y,r,b=c['board'];ox,oy,_,_=box;board_image=rgb[y-oy:b-oy,x-ox:r-ox]
                # Large neutral panels are not tetrominoes. Do not infer through a popup.
                reading_begin=time.perf_counter();popup=panel_occluded(board_image)
                if self.windows and begin-grid_check>.5:
                    grid_check=begin;bad_grid=bad_grid+1 if fit_grid(board_image,[0,0,board_image.shape[1],board_image.shape[0]]) is None else 0
                    if bad_grid>=2 and not popup:
                        self.emergency('LAYOUT_CHANGED: 확대율/페이지 배치 변경 의심. 재탐지 중');self.need_detection=True;self.observations.put(None);continue
                seq+=1;pending=self.controller.wait;expected=pending.get('expected_board') if pending and pending.get('action')=='drop' else None
                o=self.recognizer.process(rgb,box,c,seq,captured,cap_ms,expected_fixed=expected)
                if popup:o.active=None;o.confidence=0;o.stable=0;o.fixed_confidence=0;o.reason='RECOGNITION_ERROR: BOARD에 팝업/중성 패널 가림 의심'
                o.vision_ms=(time.perf_counter()-reading_begin)*1000
                count+=1;elapsed=time.monotonic()-fps_start
                if elapsed>=1:fps=count/elapsed;count=0;fps_start=time.monotonic()
                o.fps=fps;self.last_image.put((rgb,box))
                debug=copy.deepcopy(self.recognizer.cache.debug)
                for name,roi,reading in [('hold',c['hold'],o.hold)]+[(f'next{i}',b,o.nexts[i]) for i,b in enumerate(c['next_slots'])]:
                    info=debug.setdefault(name,{});info['roi']=roi;info['reading']=reading.__dict__;info['frame']=seq
                    if roi:
                        xx,yy,rr,bb=roi
                        if xx>=box[0] and yy>=box[1] and rr<=box[2] and bb<=box[3]:info['raw']=rgb[yy-box[1]:bb-box[1],xx-box[0]:rr-box[0]].copy()
                self.preview_debug.put((seq,debug));self.observations.put(o)
                self.beat('vision',begin)
            self.stop_event.wait(max(.001,1/self.c['vision_fps']-(time.monotonic()-begin)))
    def signature(self,o,used):return (o.board_key,o.active.kind,used,o.hold.kind,o.hold.valid,o.queue)
    def control_loop(self):
        if self.c.get('opener_enabled'):self.opener_book=load_book(self.c['opener_file'])
        while not self.stop_event.is_set():
            begin=time.monotonic();o=self.observations.get()
            ctl=self.controller
            try:
                generation,target=self.commands.get_nowait()
                if generation==self.generation:
                    if ctl.running:self.emergency('사용자 Auto 중지')
                    elif not self.error and not self.visibility_error:
                        try:ctl.start(target,begin)
                        except Exception as e:logging.exception('Auto start failed');ctl.stop(str(e))
            except Empty:pass
            if self.diagnostic_due and begin>=self.diagnostic_due[0]:
                _,action,target=self.diagnostic_due;self.diagnostic_due=None
                try:
                    if self.visibility_error or self.need_detection:raise ValueError('VISIBILITY_ERROR: 대상 영역 사용 불가')
                    ctl.begin_diagnostic(target,o,action,begin);self.last_diagnostic='확인 중: '+action
                except Exception as e:ctl.stop(str(e));self.last_diagnostic=str(e)
            ctl.tick(o,begin)
            if ctl.diagnostic and not ctl.running:self.last_diagnostic=ctl.reason
            if self.future and self.future.done():
                self.beat('search',self.future_started);packet=self.future.result();job=self.job;self.future=None;self.search_ms=packet['search_ms']
                if ctl.running and not ctl.diagnostic and o and o.active and job==self.signature(o,ctl.hold_used) and begin-o.captured<self.c.get('frame_age_ms',200)/1000 and begin-self.future_started<self.c.get('plan_age_ms',500)/1000:
                    packet['key']=(o.board_key,o.active.kind,ctl.hold_used);self.last_packet=packet;ctl.accept_plan(packet,o)
                elif ctl.running and not ctl.diagnostic:ctl.replan('STALE_PLAN: 탐색 결과/화면 나이 또는 상태 불일치. 최신 화면 재탐색')
            if ctl.running and not ctl.diagnostic and ctl.wait is None and ctl.plan is None and not self.future and o and o.valid:
                previews=ctl.hold_clear(o);clear=previews and self.c.get('enable_hold',False) and bool(self.c['keys']['hold']);nexts=list(o.queue) if previews and self.c.get('auto_mode')=='continuous' else [];held=o.hold.kind if clear else None
                self.job=self.signature(o,ctl.hold_used);self.future_started=begin
                if self.opener_book:
                    if not self.c.get('preview_verified') or not self.c.get('basic_auto_verified') or not o.hold.valid or not all(r.valid and r.kind for r in o.nexts):
                        ctl.stop('OPENER_GATE: 기본 Auto/프리뷰 실게임 검증 미완료 또는 HOLD/NEXT 불확실');continue
                    self.future=self.pool.submit(opener_plan,self.opener_book,ctl.blocks,ctl.opener_variant,o.fixed,o.active.kind,o.active.state,o.hold.kind,list(o.queue),ctl.hold_used,o.hold.state!='disabled' and self.c.get('enable_hold',False) and bool(self.c['keys']['hold']),self.c.get('rotation_confirmed',False))
                else:self.future=self.pool.submit(plan,o.fixed,o.active.kind,o.active.state,held,nexts,clear,not ctl.hold_used and clear,self.c.get('rotation_confirmed',True))
            if self.future and ctl.running and not ctl.diagnostic and not ctl.wait:
                ctl.phase='SEARCH';ctl.reason=f'배치 탐색 결과 대기 {begin-self.future_started:.2f}초 (제한 3초)'
            self.beat('control',begin)
            self.stop_event.wait(max(.001,.005-(time.monotonic()-begin)))
