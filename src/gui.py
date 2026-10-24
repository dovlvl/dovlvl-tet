import sys,time,copy,json,logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
import numpy as np
from PIL import Image,ImageTk,ImageDraw
from config import load,save,validate,PATH,union
from detection import detect
from windows import WindowSystem,shifted,same_size
from input_win import WindowsBackend,KeyPulse
from controller import AutoController
from runtime import Session
class App:
    def __init__(self,root):
        self.root=root;self.c=load();self.ws=WindowSystem() if sys.platform=='win32' else None;self.backend=WindowsBackend() if self.ws else None;self.ctl=AutoController(KeyPulse(self.backend),self.c) if self.backend else None;self.session=None;self.future=None;self.import_future=None;self.pool=ThreadPoolExecutor(max_workers=1);self.candidates=[];self.photos=[];self.closed=False;self.revision=-1;self.deferred=None
        root.title('Tetris Trainer 0.6 · 일반 Chrome / Edge Auto');root.geometry('1050x850')
        self.status=tk.StringVar(value='Chrome/Edge에서 게임을 직접 열고 게임 찾기를 누르세요.');self.results=tk.StringVar();self.readings=tk.StringVar();self.times=tk.StringVar();self.last=tk.StringVar();self.action=tk.StringVar(value='left');self.target_name=tk.StringVar()
        top=ttk.Frame(root,padding=10);top.pack(fill='x')
        for index,(text,fn) in enumerate([('게임 찾기',self.find),('영역 확인 / 수동 수정',self.regions),('입력 진단',self.diagnose),('Auto 시작·중지',self.button_auto),('중지 F8',self.stop),('키 / 시간 설정',self.options),('진단 캡처 저장',self.snapshot),('로그 저장',self.export_log),('HOLD·NEXT 진단',self.preview_window),('빌드 JSON 가져오기',self.import_opener)]):ttk.Button(top,text=text,command=fn).grid(row=index//5,column=index%5,padx=2,pady=2,sticky='ew')
        targets=ttk.Frame(root,padding=5);targets.pack(fill='x');ttk.Label(targets,text='대상 브라우저 (창 후보이며 게임 탐지 성공과 다름)').pack(side='left');self.combo=ttk.Combobox(targets,textvariable=self.target_name,state='readonly',width=70);self.combo.pack(side='left');self.combo.bind('<<ComboboxSelected>>',self.choose_target)
        for v in (self.status,self.results,self.readings,self.times,self.last):ttk.Label(root,textvariable=v,wraplength=1020).pack(fill='x',padx=12,pady=4)
        ttk.Label(root,text='F6: 게임 창에서 Auto 시작·중지 / F8: 긴급 중지. 입력 진단은 선택한 키 1개를 실제로 보냅니다.').pack(fill='x',padx=12)
        self.preview=tk.Canvas(root,width=1000,height=230,bg='#111827',highlightthickness=0);self.preview.pack(fill='x',padx=10,pady=10)
        self.diag=tk.Text(root,height=23,width=120,font=('Consolas',10),state='disabled');self.diag.pack(fill='both',expand=True,padx=10,pady=5)
        root.report_callback_exception=self.ui_error;root.protocol('WM_DELETE_WINDOW',self.close)
        self.hotkeys=None
        if self.ws:
            from hotkeys import Hotkeys
            self.hotkeys=Hotkeys(self.hotkey_toggle,self.stop,tuple(0x6f+int(self.c.get(k,d)[1:]) for k,d in [('hotkey_toggle','F6'),('hotkey_stop','F8')]))
            try:
                self.candidates=self.ws.browsers();self.update_targets()
                target=self.c.get('target')
                if target and self.ws.info(target['hwnd'])['pid']==target['pid'] and self.c['board']:
                    info=self.ws.info(target['hwnd'])
                    if same_size(self.c['client'],info['client']):self.c.update(shifted(self.c,self.c['client'],info['client']));self.c['client']=info['client'];self.start_session()
            except Exception:logging.exception('saved configuration could not be reused')
        else:self.status.set('이 실행 환경은 Windows가 아닙니다. 화면/실제 입력 기능은 Windows 전용입니다.')
        root.after(10,self.poll);root.after(100,self.render)
    def update_targets(self):
        self.combo['values']=[f"{i+1}. {z['exe']} | {z['title']} | HWND {z['hwnd']}" for i,z in enumerate(self.candidates)]
        if self.candidates:
            index=next((i for i,z in enumerate(self.candidates) if z['hwnd']==self.c.get('target',{}).get('hwnd')),0);self.combo.current(index)
            if not self.c.get('target'):self.c['target']=self.candidates[index];self.c['client']=self.candidates[index]['client']
    def choose_target(self,event=None):
        self.stop();self.end_session();info=self.candidates[self.combo.current()];self.c['target']=info;self.c['client']=info['client'];self.c.update(preview_verified=False,basic_auto_verified=False,opener_enabled=False);self.c['board']=None;self.c['hold']=None;self.c['next_slots']=[None]*self.c.get('next_default_count',3);self.status.set('창 후보 선택됨. 게임 찾기 또는 수동 영역 지정이 필요합니다.')
    def end_session(self):
        if self.session:self.session.stop();self.session=None
    def stop(self):
        self.deferred=None
        try:
            if self.session:self.session.emergency()
            elif self.ctl:self.ctl.stop('F8 긴급 중지')
        except Exception as e:
            logging.exception('Stop/key release failed')
            if self.ctl:self.ctl.running=False;self.ctl.phase='ERROR';self.ctl.reason='KEY_RELEASE_ERROR: '+str(e)
    def start_session(self):
        self.end_session();validate(self.c,True);self.ctl.c=self.c;self.ctl.phase='IDLE';self.ctl.reason='대기: 게임 시작 후 F6 또는 입력 진단';self.session=Session(self.c,self.ctl,self.ws);self.session.start();self.revision=0;save(self.c)
    def find(self,target_only=False):
        if not self.ws:return
        if self.future:return
        self.stop();self.end_session();self.status.set('탐지 중: 브라우저 창 후보와 실제 게임 격자를 구분해 검사합니다.');self.root.withdraw();self.root.after(200,lambda:self.begin_find(target_only))
    def begin_find(self,target_only):
        info=self.c.get('target') if target_only else None;self.future=self.pool.submit(self.find_job,info)
    def find_job(self,selected):
        import mss
        candidates=[self.ws.info(selected['hwnd'])] if selected else self.ws.browsers()
        if not candidates:raise ValueError('WINDOW_NOT_FOUND: 보이는 일반 Chrome/Edge 창이 없습니다.')
        with mss.mss() as src:
            monitor=src.monitors[0];desktop=np.asarray(src.grab(monitor))[:,:,:3][:,:,::-1].copy()
        vx,vy=monitor['left'],monitor['top'];best=None
        for z in candidates:
            if z['minimized']:continue
            x,y,r,b=z['client'];x=max(x,vx);y=max(y,vy);r=min(r,vx+desktop.shape[1]);b=min(b,vy+desktop.shape[0])
            if r-x<100 or b-y<180:continue
            result=detect(desktop[y-vy:b-vy,x-vx:r-vx],(x,y),self.c.get('next_default_count',3))
            if result['board']:
                visible,why=self.ws.visible_regions(z['hwnd'],[result['board'],result['hold'],*result['next_slots']])
                if not visible:result['reasons']['visibility']=why;continue
            score=int(result['board'] is not None)*4+int(result['hold'] is not None)+int(bool(result['next_slots']))
            if best is None or score>best[0]:best=(score,z,result)
        if best is None:raise ValueError('VISIBILITY_ERROR: 창이 최소화되었거나 화면 밖/다른 창에 가려져 있습니다.')
        return candidates,best[1],best[2]
    def poll(self):
        if self.closed:return
        if self.import_future and self.import_future.done():self.finish_import()
        if self.future and self.future.done():
            f=self.future;self.future=None;self.root.deiconify()
            try:
                self.candidates,info,result=f.result()
                if self.c.get('target',{}).get('hwnd')!=info['hwnd'] or any(self.c[k]!=result[k] for k in ('board','hold','next_slots')):self.c.update(preview_verified=False,basic_auto_verified=False,opener_enabled=False)
                self.update_targets();self.combo.current(next(i for i,z in enumerate(self.candidates) if z['hwnd']==info['hwnd']));self.c['target']=info;self.c['client']=info['client'];self.c.update({k:result[k] for k in ('board','hold','next_slots')});self.c['detection']=result
                if not self.c['next_slots']:self.c['next_slots']=[None]*self.c.get('next_default_count',3)
                self.show_geometry(result)
                if result['board']:self.start_session();self.status.set('BOARD 준비. HOLD/NEXT 실패 영역은 수동 수정 가능. BOARD가 확실하면 기본 Auto 가능.')
                else:self.status.set('창 후보는 찾았으나 BOARD 미탐지. 해당 창을 선택하고 수동 영역만으로 설정할 수 있습니다.')
            except Exception as e:logging.exception('find failed');self.status.set(str(e))
        if self.hotkeys:
            from queue import Empty
            while True:
                try:kind,action=self.hotkeys.events.get_nowait()
                except Empty:break
                if kind=='error':self.stop();self.status.set('HOTKEY_ERROR: '+action)
                elif action=='stop':self.stop()
                else:self.toggle_auto()
        if self.deferred and time.monotonic()>=self.deferred:
            self.deferred=None;self.toggle_auto()
        if self.session and self.session.need_detection and self.future is None:self.find(True)
        self.root.after(10,self.poll)
    def hotkey_toggle(self):
        # Called by message thread: no Tk access; starts via the same controller path.
        if not self.session:return
        if self.ctl.running:self.stop();return
        self.start_auto()
    def start_auto(self):
        try:
            if self.hotkeys and not self.hotkeys.ready:raise ValueError('전역 단축키 등록 실패: 설정에서 변경')
            if not self.c.get('board'):raise ValueError('Auto: BOARD 영역을 먼저 지정하세요. 입력 진단은 영역 없이 가능')
            if self.session.error or self.session.visibility_error:raise ValueError(self.session.error or self.session.visibility_error)
            target=self.c['target']['hwnd']
            if self.backend.foreground()!=target:raise ValueError('게임 화면을 클릭하세요: 대상 브라우저 비활성')
            self.session.request_toggle(target)
        except Exception as e:
            logging.exception('Auto start rejected');self.ctl.stop(str(e))
    def toggle_auto(self):
        if not self.session or self.future:self.status.set('먼저 BOARD 영역과 대상 창을 설정하세요.');return
        if self.ctl.running:self.stop();return
        self.start_auto()
    def button_auto(self):
        if self.ctl and self.ctl.running:self.stop();return
        if not self.session:self.status.set('먼저 게임 찾기 또는 BOARD 수동 설정을 완료하세요.');return
        self.deferred=time.monotonic()+self.c.get('input_countdown',3);self.status.set(str(self.c.get('input_countdown',3))+'초 뒤 시작합니다. 게임판으로 돌아가 클릭하세요.');self.root.iconify()
    def show_geometry(self,result=None):
        c=self.c;success=lambda b:'설정됨' if b else '실패/미설정';full=bool(c['board'] and c['hold'] and c['next_slots'] and all(c['next_slots']))
        self.results.set(f"영역 전체: {'설정 완료' if full else '부분 설정'} | BOARD {success(c['board'])} | HOLD {success(c['hold'])} | NEXT "+', '.join(f'{i+1}:{success(b)}' for i,b in enumerate(c['next_slots'])))
    def capture_desktop(self):
        import mss
        with mss.mss() as s:
            m=s.monitors[0];rgb=np.asarray(s.grab(m))[:,:,:3][:,:,::-1].copy()
        return Image.fromarray(rgb),(m['left'],m['top'])
    def regions(self):
        if not self.ws or not self.c.get('target'):self.status.set('게임 찾기 또는 대상 브라우저 선택을 먼저 하세요.');return
        self.stop();self.root.withdraw();self.root.after(200,self.region_dialog)
    def region_dialog(self):
        try:im,origin=self.capture_desktop()
        except Exception as e:self.root.deiconify();self.status.set(str(e));return
        draft=copy.deepcopy(self.c);win=tk.Toplevel(self.root);win.title('영역 확인 / 실패한 영역만 수정 · 정지 화면');scale=min(1,(self.root.winfo_screenwidth()-100)/im.width,(self.root.winfo_screenheight()-200)/im.height)
        photo=ImageTk.PhotoImage(im.resize((round(im.width*scale),round(im.height*scale))));canvas=tk.Canvas(win,width=photo.width(),height=photo.height(),highlightthickness=0);canvas.pack();canvas.create_image(0,0,anchor='nw',image=photo);win.photo=photo;target=tk.StringVar(value='BOARD');bar=ttk.Frame(win);bar.pack(fill='x');combo=ttk.Combobox(bar,textvariable=target,state='readonly',width=14);combo.pack(side='left');number=tk.IntVar(value=len(draft['next_slots']));ttk.Spinbox(bar,from_=1,to=6,textvariable=number,width=4).pack(side='left');note=tk.StringVar(value='수정할 영역만 선택해 내부를 드래그하세요. BOARD 10×20, 글자·테두리 제외. 빈 화면도 저장 가능.');ttk.Label(win,textvariable=note,wraplength=1000).pack();start=[];temp=[None]
        def choices():combo['values']=['BOARD','HOLD']+[f'NEXT {i+1}' for i in range(len(draft['next_slots']))]
        def boxes():return [('BOARD',draft['board']),('HOLD',draft['hold'])]+[(f'NEXT {i+1}',b) for i,b in enumerate(draft['next_slots'])]
        def draw():
            canvas.delete('box')
            for label,b in boxes():
                if not b:continue
                x,y,r,z=b;x=(x-origin[0])*scale;y=(y-origin[1])*scale;r=(r-origin[0])*scale;z=(z-origin[1])*scale;col='lime' if label=='BOARD' else 'yellow' if label=='HOLD' else 'cyan';canvas.create_rectangle(x,y,r,z,outline=col,width=2,tags='box');canvas.create_text(x+4,y+5,text=label,anchor='nw',fill=col,tags='box')
                if label=='BOARD':
                    for i in range(1,10):canvas.create_line(x+(r-x)*i/10,y,x+(r-x)*i/10,z,fill='#22aa66',tags='box')
                    for i in range(1,20):canvas.create_line(x,y+(z-y)*i/20,r,y+(z-y)*i/20,fill='#22aa66',tags='box')
        def count():
            try:n=number.get();assert 1<=n<=6;draft['next_slots']=(draft['next_slots']+[None]*6)[:n];draft['next_default_count']=n;choices();target.set('NEXT 1');draw()
            except Exception:note.set('NEXT 개수는 1~6입니다.')
        ttk.Button(bar,text='NEXT 개수 적용',command=count).pack(side='left')
        def down(e):start[:]=[e.x,e.y];temp[0]=canvas.create_rectangle(e.x,e.y,e.x,e.y,outline='white')
        def move(e):
            if start:canvas.coords(temp[0],*start,e.x,e.y)
        def up(e):
            if not start:return
            x,y=start;start.clear();box=[round(min(x,e.x)/scale)+origin[0],round(min(y,e.y)/scale)+origin[1],round(max(x,e.x)/scale)+origin[0],round(max(y,e.y)/scale)+origin[1]];name=target.get()
            if name=='BOARD':draft['board']=box
            elif name=='HOLD':draft['hold']=box
            else:draft['next_slots'][int(name.split()[1])-1]=box
            canvas.delete(temp[0]);draw()
        def finish(commit=False):
            if commit:
                try:
                    if any(draft[k]!=self.c[k] for k in ('board','hold','next_slots')):draft.update(preview_verified=False,basic_auto_verified=False,opener_enabled=False)
                    validate(draft,True);self.c=draft;self.c['client']=self.ws.info(self.c['target']['hwnd'])['client'];self.start_session();self.show_geometry()
                except Exception as e:note.set(str(e));return
            win.destroy();self.root.deiconify()
        ttk.Button(bar,text='저장',command=lambda:finish(True)).pack(side='right');ttk.Button(bar,text='취소',command=finish).pack(side='right');win.protocol('WM_DELETE_WINDOW',finish);canvas.bind('<ButtonPress-1>',down);canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',up);choices();draw()
    def diagnose(self):
        if self.hotkeys and not self.hotkeys.ready:self.status.set('전역 단축키 등록 실패: 키 / 시간 설정에서 변경 후 진단하세요.');return
        if not self.session:
            if not self.c.get('target'):self.status.set('대상 브라우저를 먼저 선택하세요.');return
            self.ctl.c=self.c;self.session=Session(self.c,self.ctl,self.ws);self.session.start(diagnostic_only=True)
        self.stop();win=tk.Toplevel(self.root);win.title('입력 진단 · 한 동작씩 실제 화면 확인');ttk.Label(win,text='키 1개를 보낸 뒤 실제 변화로 판정합니다. 게임을 시작/재개한 뒤 사용하세요.').pack(padx=15,pady=10)
        def run(action):
            win.destroy();self.session.schedule_diagnostic(action,self.c['target']['hwnd'],time.monotonic());self.status.set(f'입력 진단 {action}: {self.c.get("input_countdown",3)}초 뒤. 게임판으로 돌아가세요.');self.root.iconify()
        for action,title in [('left','좌'),('right','우'),('up','시계 회전'),('down','소프트드롭'),('z','설정된 반시계 회전'),('hold','홀드'),('drop','하드드롭')]:ttk.Button(win,text=title,command=lambda a=action:run(a)).pack(fill='x',padx=15,pady=3)
    def options(self):
        self.stop();dialog=tk.Toplevel(self.root);dialog.title('키 / 입력 / 캡처 / 검증 설정');dialog.geometry('650x720');viewport=tk.Canvas(dialog,highlightthickness=0);scroll=ttk.Scrollbar(dialog,orient='vertical',command=viewport.yview);viewport.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');viewport.pack(fill='both',expand=True);win=ttk.Frame(viewport);viewport.create_window((0,0),window=win,anchor='nw');win.bind('<Configure>',lambda e:viewport.configure(scrollregion=viewport.bbox('all')));vars={};row=0
        for k,v in self.c['keys'].items():
            ttk.Label(win,text=k).grid(row=row,column=0);x=tk.StringVar(value=v);vars['key_'+k]=x;ttk.Combobox(win,textvariable=x,values=['','LEFT','RIGHT','UP','DOWN','SPACE','SHIFT','CTRL',*list('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')]).grid(row=row,column=1);row+=1
        for k in ('press_ms','gap_ms','ack_ms','uncertain_ms','transition_ms','frame_age_ms','input_countdown','capture_fps','vision_fps','ui_fps','min_s','min_v'):
            ttk.Label(win,text=k).grid(row=row,column=0);x=tk.StringVar(value=str(self.c[k]));vars[k]=x;ttk.Entry(win,textvariable=x).grid(row=row,column=1);row+=1
        for k,values in [('hotkey_toggle',['F'+str(i) for i in range(1,25)]),('hotkey_stop',['F'+str(i) for i in range(1,25)]),('auto_mode',['one','continuous'])]:
            ttk.Label(win,text=k).grid(row=row,column=0);x=tk.StringVar(value=self.c[k]);vars[k]=x;ttk.Combobox(win,textvariable=x,values=values,state='readonly').grid(row=row,column=1);row+=1
        rotation=tk.BooleanVar(value=self.c.get('rotation_confirmed',False));ttk.Checkbutton(win,text='게임 설정에서 시계 회전 키 확인 완료 (미확인 시 회전 안 함)',variable=rotation).grid(row=row,columnspan=2);row+=1
        hold_enabled=tk.BooleanVar(value=self.c.get('enable_hold',False));ttk.Checkbutton(win,text='연속 모드에서 설정한 HOLD 키 사용 (프리뷰가 확실할 때)',variable=hold_enabled).grid(row=row,columnspan=2);row+=1
        gates={}
        for key,title in [('preview_verified','현재 게임의 HOLD/NEXT 원본과 판독 결과를 실제 비교 검증 완료'),('basic_auto_verified','현재 게임에서 기본 Auto 목표 위치/고정 결과 검증 완료'),('opener_enabled','선택한 JSON 빌드 실행 (위 두 검증 및 continuous 필요)')]:
            var=tk.BooleanVar(value=self.c.get(key,False));gates[key]=var;ttk.Checkbutton(win,text=title,variable=var).grid(row=row,columnspan=2);row+=1
        msg=tk.StringVar();ttk.Label(win,textvariable=msg,wraplength=450).grid(row=row,columnspan=2);row+=1
        def commit():
            try:
                c=copy.deepcopy(self.c)
                for k,v in vars.items():
                    if k.startswith('key_'):c['keys'][k[4:]]=v.get().upper()
                    elif k in ('hotkey_toggle','hotkey_stop','auto_mode'):c[k]=v.get()
                    else:c[k]=float(v.get()) if k in ('min_s','min_v') else int(v.get())
                c.update({k:v.get() for k,v in gates.items()});c['rotation_confirmed']=rotation.get();c['enable_hold']=hold_enabled.get()
                if any(c[k]!=self.c[k] for k in ('min_s','min_v')):c.update(preview_verified=False,basic_auto_verified=False,opener_enabled=False)
                if c['keys']!=self.c['keys'] or c['rotation_confirmed']!=self.c['rotation_confirmed']:c.update(basic_auto_verified=False,opener_enabled=False)
                validate(c);save(c);self.c=c
                if self.hotkeys:
                    from hotkeys import Hotkeys
                    self.hotkeys.close();self.hotkeys=Hotkeys(self.hotkey_toggle,self.stop,tuple(0x6f+int(c[k][1:]) for k in ('hotkey_toggle','hotkey_stop')))
                if c['board']:self.start_session()
                dialog.destroy()
            except Exception as e:msg.set(str(e))
        ttk.Button(win,text='저장',command=commit).grid(row=row,column=1)
    def render(self):
        if self.closed:return
        s=self.session;o=s.observations.get() if s else None
        if s and s.revision!=self.revision:
            with s.lock:self.c=copy.deepcopy(s.c)
            save(self.c);self.revision=s.revision;self.show_geometry()
        if s and s.error:self.status.set(s.error)
        elif s and s.visibility_error:self.status.set('VISIBILITY_ERROR: '+s.visibility_error)
        elif self.ctl and (self.ctl.running or self.ctl.reason!='중지됨'):self.status.set(self.ctl.phase+' · '+self.ctl.reason)
        self.show_geometry()
        data={'opener':{'enabled':self.c.get('opener_enabled'),'file':self.c.get('opener_file'),'summary':self.c.get('opener_summary'),'preview_verified':self.c.get('preview_verified'),'basic_auto_verified':self.c.get('basic_auto_verified')},'window_candidate':self.c.get('target'),'regions':{k:self.c[k] for k in ('board','hold','next_slots')},'detection':self.c.get('detection'),'hotkeys':{'status':self.hotkeys.status,'received':self.hotkeys.received,'alive':self.hotkeys.thread.is_alive()} if self.hotkeys else None,'workers':s.health if s else None,'worker_alive':{t.name:t.is_alive() for t in s.threads} if s else None,'ui_last':time.strftime('%H:%M:%S'),'stage_age_ms':{k:round((time.monotonic()-v['last'])*1000,1) for k,v in s.health.items()} if s else None,'frame_number':o.seq if o else None,'SendInput':getattr(self.backend,'last_api',{}),'phase':self.ctl.phase if self.ctl else None,'reason':self.ctl.reason if self.ctl else None,'foreground_hwnd':self.backend.foreground() if self.backend else None,'foreground_matches':self.backend.foreground()==self.c.get('target',{}).get('hwnd') if self.backend else False,'game_canvas_clicked':'확인 불가: 게임판을 직접 클릭하세요','blocks':self.ctl.blocks if self.ctl else 0,'countdown':max(0,s.diagnostic_due[0]-time.monotonic()) if s and s.diagnostic_due else None}
        if o:
            def reading(r):return r.__dict__
            self.readings.set('현재: '+(o.active.kind+' '+str(o.active.state) if o.active else '불확실')+' | HOLD: '+(str(o.hold.kind or '비어 있음') if o.hold.valid else '불확실')+' | HOLD 상태: '+o.hold.state+' | NEXT: '+' → '.join(str(r.kind) if r.valid and r.kind else '?' for r in o.nexts))
            self.times.set(f'실측 인식 {o.fps:.1f} FPS | 캡처 {o.capture_ms:.2f} ms | 인식 {o.vision_ms:.2f} ms | 탐색 {s.search_ms:.2f} ms | 입력 프레임 나이 {self.ctl.frame_age_ms:.1f} ms | 최신 프레임 나이 {(time.monotonic()-o.captured)*1000:.1f} ms')
            data.update({'fixed_20x10':o.fixed,'fixed_confidence':o.fixed_confidence,'fixed_updated':o.fixed_updated,'active':o.active.__dict__ if o.active else None,'ghost':{'cells':o.ghost,'confidence':o.ghost_confidence,'updated':o.ghost_updated},'preview_geometry':{k:{kk:vv for kk,vv in v.items() if kk not in ('mask','normalized','raw')} for k,v in (s.preview_debug.get()[1] if s.preview_debug.get() else {}).items()},'hold':reading(o.hold),'next':[reading(r) for r in o.nexts],'reason':o.reason,'confidence':o.confidence,'stable_frames':o.stable,'updated':o.updated,'target':self.c.get('target'),'SendInput':getattr(self.backend,'last_api',{}),'diagnostic':s.last_diagnostic})
            if data['active']:data['active']=dict(data['active'],cells=sorted(data['active']['cells']))
        if self.ctl:self.last.set('마지막 입력: '+self.ctl.last_input+' | 확인: '+self.ctl.last_ack+' | 진단: '+(s.last_diagnostic if s else ''))
        self.diag.configure(state='normal');self.diag.delete('1.0','end');self.diag.insert('end',json.dumps(data,ensure_ascii=False,indent=1));self.diag.configure(state='disabled')
        if s and s.last_image.get():
            rgb,box=s.last_image.get();self.preview.delete('all');self.photos=[];xpos=4
            for label,b in [('BOARD',self.c['board']),('HOLD',self.c['hold'])]+[(f'NEXT {i+1}',b) for i,b in enumerate(self.c['next_slots'])]:
                if not b:continue
                x,y,r,z=b;crop=rgb[y-box[1]:z-box[1],x-box[0]:r-box[0]]
                if crop.size==0:continue
                im=Image.fromarray(crop);im.thumbnail((140,200));photo=ImageTk.PhotoImage(im);self.photos.append(photo);self.preview.create_text(xpos,4,anchor='nw',text=label,fill='white');self.preview.create_image(xpos,24,anchor='nw',image=photo);self.preview.create_rectangle(xpos,24,xpos+im.width,24+im.height,outline='cyan');xpos+=max(im.width,85)+12
        self.root.after(round(1000/self.c['ui_fps']),self.render)
    def import_opener(self):
        self.stop();path=filedialog.askopenfilename(title='오프너 JSON (가져오기만 하며 자동 실행하지 않음)',filetypes=[('JSON','*.json')])
        if not path:return
        from openers import load_book
        self.import_future=self.pool.submit(load_book,path);self.status.set('빌드 JSON 경로/보드 검증 중: 입력 중지')
    def finish_import(self):
        future=self.import_future;self.import_future=None
        try:
            book=future.result();folder=PATH.parent/'openers';folder.mkdir(parents=True,exist_ok=True);dest=folder/'selected.json';dest.write_text(json.dumps(book,ensure_ascii=False,indent=2),encoding='utf-8')
            self.c['opener_file']=str(dest);self.c['opener_enabled']=False;self.c['opener_summary']={'name':book['name'],'variants':len(book['variants']),'source':book['source'],'real_game_verified':False};save(self.c)
            if self.session:self.start_session()
            self.status.set(f"가져오기 완료: {book['name']} / {len(book['variants'])}변형. 모델 검증 완료, 실게임 미검증. 실행은 설정에서 별도 선택")
        except Exception as e:logging.exception('opener import failed');self.status.set('IMPORT_ERROR: '+str(e))
    def preview_window(self):
        win=tk.Toplevel(self.root);win.title('HOLD·NEXT 원본 / 색상 마스크 / 정규화');win.geometry('950x650')
        canvas=tk.Canvas(win,bg='#151b27');bar=ttk.Scrollbar(win,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');canvas.pack(fill='both',expand=True);win.images=[]
        def update():
            if not win.winfo_exists():return
            canvas.delete('all');win.images=[];s=self.session;packet=s.preview_debug.get() if s else None;o=s.observations.get() if s else None;image=s.last_image.get() if s else None
            if not packet or not image:canvas.create_text(15,15,anchor='nw',text='인식 세션 및 프리뷰 영역을 먼저 설정하세요.',fill='white')
            else:
                seq,debug=packet;rgb,box=image;ypos=10
                for name,roi,r in [('hold',self.c['hold'],o.hold if o else None)]+[(f'next{i}',b,o.nexts[i] if o and i<len(o.nexts) else None) for i,b in enumerate(self.c['next_slots'])]:
                    info=debug.get(name,{})
                    if info.get('reading'):
                        from model import Reading
                        r=Reading(**info['reading'])
                    roi=info.get('roi',roi);text=f"{name} ROI={roi} frame={seq} state={r.state if r else '?'} kind={r.kind if r else '?'} confidence={r.confidence if r else 0:.2f}"
                    canvas.create_text(10,ypos,anchor='nw',text=text,fill='white');ypos+=22
                    canvas.create_text(10,ypos,anchor='nw',text=f"{r.reason if r else ''} bbox={info.get('bbox')} raw_shape={info.get('raw_shape')} updated={info.get('updated')} seen={r.seen if r else None}",fill='#cbd5e1');ypos+=22
                    views=[('원본',info['raw'])] if 'raw' in info else []
                    if roi and not views:
                        x,y,rr,b=roi
                        if x>=box[0] and y>=box[1] and rr<=box[2] and b<=box[3]:views.append(('원본',rgb[y-box[1]:b-box[1],x-box[0]:rr-box[0]]))
                    views.extend((label,info[key]) for label,key in [('처리 마스크','mask'),('크기/위치 정규화','normalized')] if key in info)
                    xpos=10;maxh=0
                    for label,pixels in views:
                        if pixels.size==0:continue
                        im=Image.fromarray(pixels);im.thumbnail((240,125));photo=ImageTk.PhotoImage(im);win.images.append(photo);canvas.create_text(xpos,ypos,anchor='nw',text=label,fill='cyan');canvas.create_image(xpos,ypos+20,anchor='nw',image=photo);xpos+=270;maxh=max(maxh,im.height)
                    ypos+=maxh+40
                canvas.configure(scrollregion=(0,0,900,ypos))
            win.after(250,update)
        update()
    def export_log(self):
        import shutil
        folder=(Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])/'diagnostics';folder.mkdir(exist_ok=True)
        for f in PATH.parent.glob('trainer.log*'):shutil.copy2(f,folder/f.name)
        self.status.set('로그 저장: '+str(folder))
    def snapshot(self):
        if not self.session or not self.session.last_image.get():self.status.set('저장할 진단 프레임이 없습니다.');return
        rgb,box=self.session.last_image.get();folder=PATH.parent/'diagnostics';folder.mkdir(parents=True,exist_ok=True);stem=folder/time.strftime('%Y%m%d_%H%M%S');im=Image.fromarray(rgb);d=ImageDraw.Draw(im)
        for label,b in [('BOARD',self.c['board']),('HOLD',self.c['hold'])]+[(f'NEXT{i+1}',b) for i,b in enumerate(self.c['next_slots'])]:
            if b:x,y,r,z=b;d.rectangle((x-box[0],y-box[1],r-box[0],z-box[1]),outline='cyan',width=2);d.text((x-box[0]+2,y-box[1]+2),label,fill='white')
        im.save(str(stem)+'.png');Image.fromarray(rgb).save(str(stem)+'_raw.png');
        packet=self.session.preview_debug.get()
        if packet:
            for name,info in packet[1].items():
                for key in ('raw','mask','normalized'):
                    if key in info:Image.fromarray(info[key]).save(str(stem)+'_'+name+'_'+key+'.png')
        Path(str(stem)+'.json').write_text(json.dumps({'capture_box':box,'config':self.c,'reason':self.ctl.reason,'last_api':getattr(self.backend,'last_api',{}),'preview_meta':{k:{kk:vv for kk,vv in v.items() if kk not in ('raw','mask','normalized')} for k,v in packet[1].items()} if packet else {}},ensure_ascii=False,indent=2),encoding='utf-8');self.status.set('진단 저장: '+str(stem))
    def ui_error(self,kind,error,tb):
        self.stop();logging.error('UI error',exc_info=(kind,error,tb));self.status.set('UI_ERROR: '+str(error))
    def close(self):
        self.closed=True;self.stop();self.end_session();self.pool.shutdown(wait=False,cancel_futures=True)
        if self.hotkeys:self.hotkeys.close()
        self.root.destroy()
