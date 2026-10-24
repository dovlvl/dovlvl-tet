"""SendInput backend + injectable nonblocking key pulses. No PostMessage fake input."""
import ctypes,sys,threading,os,logging
from ctypes import wintypes
VK={'LEFT':0x25,'UP':0x26,'RIGHT':0x27,'DOWN':0x28,'SPACE':0x20,'SHIFT':0x10,'CTRL':0x11}
VK.update({c:ord(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'})
EXTENDED={0x25,0x26,0x27,0x28}
ULONG_PTR=ctypes.c_size_t
class KEYBDINPUT(ctypes.Structure):
    _fields_=[('wVk',wintypes.WORD),('wScan',wintypes.WORD),('dwFlags',wintypes.DWORD),('time',wintypes.DWORD),('dwExtraInfo',ULONG_PTR)]
class MOUSEINPUT(ctypes.Structure):
    _fields_=[('dx',wintypes.LONG),('dy',wintypes.LONG),('mouseData',wintypes.DWORD),('dwFlags',wintypes.DWORD),('time',wintypes.DWORD),('dwExtraInfo',ULONG_PTR)]
class HARDWAREINPUT(ctypes.Structure):
    _fields_=[('uMsg',wintypes.DWORD),('wParamL',wintypes.WORD),('wParamH',wintypes.WORD)]
class INPUTUNION(ctypes.Union):_fields_=[('ki',KEYBDINPUT),('mi',MOUSEINPUT),('hi',HARDWAREINPUT)]
class INPUT(ctypes.Structure):_anonymous_=('u',);_fields_=[('type',wintypes.DWORD),('u',INPUTUNION)]

def keyboard_event(vk,down,scan):
    event=INPUT(type=1);event.ki=KEYBDINPUT(0,scan,0x0008|(0x0001 if vk in EXTENDED else 0)|(0 if down else 0x0002),0,0)
    return event
class WindowsBackend:
    def __init__(self):
        if sys.platform!='win32':raise OSError('실제 키 입력은 Windows 전용입니다.')
        self.u=ctypes.WinDLL('user32',use_last_error=True)
        self.u.GetForegroundWindow.restype=wintypes.HWND
        self.u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        expected=40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28
        if ctypes.sizeof(INPUT)!=expected:raise RuntimeError('INPUT ABI size error')
        self.last_api={'input_size':ctypes.sizeof(INPUT),'pointer_size':ctypes.sizeof(ctypes.c_void_p),'union_offset':INPUT.u.offset}
        self.u.MapVirtualKeyW.argtypes= [wintypes.UINT,wintypes.UINT]
        self.u.SendInput.argtypes=[wintypes.UINT,ctypes.POINTER(INPUT),ctypes.c_int];self.u.SendInput.restype=wintypes.UINT
    def foreground(self):return self.u.GetForegroundWindow()
    def own_window(self,hwnd):
        pid=wintypes.DWORD();self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));return pid.value==os.getpid()
    def key(self,vk,down):
        # Scan codes generate real keyboard events, arrow keys carry EXTENDEDKEY.
        scan=self.u.MapVirtualKeyW(vk,0)
        event=keyboard_event(vk,down,scan)
        ctypes.set_last_error(0);sent=self.u.SendInput(1,ctypes.byref(event),ctypes.sizeof(INPUT));err=ctypes.get_last_error()
        self.last_api={'vk':vk,'scan':scan,'down':down,'sent':int(sent),'error':err,'input_size':ctypes.sizeof(INPUT)}
        logging.info('SendInput %s',self.last_api)
        if sent!=1:raise OSError('INPUT_API_ERROR: SendInput 반환='+str(sent)+', last_error='+str(err)+'. UIPI 여부는 이 값만으로 확정할 수 없습니다.')

class KeyPulse:
    def __init__(self,backend):self.backend=backend;self.target=None;self.pressed=set();self.release_at=0;self.next_at=0;self.lock=threading.RLock();self.abort=threading.Event()
    def arm(self,target):
        self.release_all();self.target=target;self.abort.clear()
    def cancel(self):
        with self.lock:
            self.abort.set()
            if hasattr(self.backend,'invalidate'):self.backend.invalidate()
            self.release_all()
    def focused(self):return self.target is not None and self.backend.foreground()==self.target
    def press(self,key,now,press_ms,gap_ms):
        with self.lock:
            if self.abort.is_set():raise RuntimeError('입력 중지됨')
            if not self.focused():self.cancel();raise RuntimeError('게임 창 포커스 상실')
            if self.pressed or now<self.next_at:return False
            if not key:raise ValueError('게임 설정에서 키를 확인하고 지정하세요.')
            vk=VK[key];self.pressed.add(vk)
            try:self.backend.key(vk,True)
            except Exception:self.cancel();raise
            self.release_at=now+press_ms/1000;self.next_at=self.release_at+gap_ms/1000;return True
    def tick(self,now):
        with self.lock:
            if self.pressed and (not self.focused() or self.abort.is_set()):self.cancel();raise RuntimeError('포커스 상실/입력 중지')
            if self.pressed and now>=self.release_at:self.release_all()
    def release_all(self):
        with self.lock:
            errors=[]
            for vk in list(self.pressed):
                try:self.backend.key(vk,False);self.pressed.discard(vk)
                except Exception as e:errors.append(e)
            if errors:raise OSError('키 해제 실패: '+str(errors[0]))
