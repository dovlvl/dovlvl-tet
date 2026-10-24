"""Dedicated Windows message pump; callbacks must never touch Tk."""
import ctypes, logging, threading, time
from ctypes import wintypes
from queue import Queue
class Hotkeys:
    def __init__(self, toggle=None, emergency=None, keys=(0x75,0x77)):
        self.events=Queue(); self.thread_id=None; self.ready=False
        self.on_toggle=toggle; self.on_emergency=emergency; self.keys=keys
        self.status={}; self.received={}; self.started=threading.Event()
        self.thread=threading.Thread(target=self.worker,daemon=True,name='global-hotkeys'); self.thread.start()
    def worker(self):
        u=ctypes.WinDLL('user32',use_last_error=True)
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        u.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        u.GetMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT]
        u.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        self.thread_id=k.GetCurrentThreadId(); registered=[]
        try:
            for ident,key,name in ((1,self.keys[0],'toggle'),(2,self.keys[1],'stop')):
                ctypes.set_last_error(0); ok=bool(u.RegisterHotKey(None,ident,0x4000,key)); err=ctypes.get_last_error()
                self.status[name]={'registered':ok,'vk':key,'error':err,'message':ctypes.FormatError(err) if err else ''}
                logging.info('RegisterHotKey %s: %s',name,self.status[name])
                if ok:registered.append(ident)
                else:self.events.put(('error',str(self.status[name])))
            self.ready=len(registered)==2; self.started.set(); msg=wintypes.MSG()
            while True:
                result=u.GetMessageW(ctypes.byref(msg),None,0,0)
                if result==0:break
                if result==-1:raise ctypes.WinError(ctypes.get_last_error())
                if msg.message==0x0312:
                    name='toggle' if msg.wParam==1 else 'stop'
                    self.received[name]=time.strftime('%H:%M:%S')
                    logging.info('HOTKEY received %s at %s',name,self.received[name])
                    callback=self.on_toggle if name=='toggle' else self.on_emergency
                    if callback:callback()
        except Exception:
            logging.exception('hotkey pump failed');self.events.put(('error','메시지 루프 실패: 로그 확인'))
        finally:
            self.ready=False;self.started.set()
            for ident in registered:u.UnregisterHotKey(None,ident)
    def close(self):
        self.started.wait(.5)
        if self.thread_id:
            u=ctypes.WinDLL('user32',use_last_error=True)
            u.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            u.PostThreadMessageW(self.thread_id,0x0012,0,0)
        self.thread.join(timeout=1)
