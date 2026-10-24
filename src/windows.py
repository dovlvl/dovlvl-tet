"""Physical-pixel window tracking and conservative visible-surface checks."""
import ctypes,sys,os
from ctypes import wintypes as W
class WindowSystem:
    def __init__(self):
        if sys.platform!='win32':raise OSError('Windows 10/11 전용입니다.')
        self.u=ctypes.WinDLL('user32',use_last_error=True);self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.u.GetForegroundWindow.restype=W.HWND;self.u.GetAncestor.argtypes=[W.HWND,W.UINT];self.u.GetAncestor.restype=W.HWND
        self.u.WindowFromPoint.argtypes=[W.POINT];self.u.WindowFromPoint.restype=W.HWND
        for name in ('IsWindow','IsWindowVisible','IsIconic'):getattr(self.u,name).argtypes=[W.HWND]
        self.u.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)];self.u.ClientToScreen.argtypes=[W.HWND,ctypes.POINTER(W.POINT)]
        self.u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];self.u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
        self.u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
        self.k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.k.OpenProcess.restype=W.HANDLE
        self.k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)];self.k.CloseHandle.argtypes=[W.HANDLE]
    def info(self,hwnd):
        if not self.u.IsWindow(hwnd):raise OSError('대상 창이 닫혔습니다.')
        rect=W.RECT();point=W.POINT();self.u.GetClientRect(hwnd,ctypes.byref(rect));self.u.ClientToScreen(hwnd,ctypes.byref(point));buf=ctypes.create_unicode_buffer(1024);cls=ctypes.create_unicode_buffer(128);self.u.GetWindowTextW(hwnd,buf,1024);self.u.GetClassNameW(hwnd,cls,128)
        pid=W.DWORD();self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));exe='';handle=self.k.OpenProcess(0x1000,False,pid.value)
        if handle:
            try:
                path=ctypes.create_unicode_buffer(4096);size=W.DWORD(4096)
                if self.k.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size)):exe=os.path.basename(path.value).lower()
            finally:self.k.CloseHandle(handle)
        return {'hwnd':int(hwnd),'pid':pid.value,'title':buf.value,'class':cls.value,'exe':exe,'client':[point.x,point.y,point.x+rect.right,point.y+rect.bottom],'minimized':bool(self.u.IsIconic(hwnd)),'visible':bool(self.u.IsWindowVisible(hwnd))}
    def browsers(self):
        out=[];callback_type=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        def callback(hwnd,_):
            try:
                z=self.info(hwnd)
                if z['visible'] and z['exe'] in ('chrome.exe','msedge.exe'):out.append(z)
            except Exception:pass
            return True
        cb=callback_type(callback);self.u.EnumWindows.argtypes=[callback_type,W.LPARAM];self.u.EnumWindows(cb,0)
        return sorted(out,key=lambda z:'tetris' not in z['title'].lower())
    def root_at(self,x,y):return self.u.GetAncestor(self.u.WindowFromPoint(W.POINT(round(x),round(y))),2)
    def visible_regions(self,hwnd,boxes):
        info=self.info(hwnd)
        if info['minimized'] or not info['visible']:return False,'최소화/숨김 창은 사용할 수 없습니다.'
        for box in boxes:
            if not box:continue
            x,y,r,b=box
            for fx,fy in ((.08,.08),(.5,.08),(.92,.08),(.08,.5),(.5,.5),(.92,.5),(.08,.92),(.5,.92),(.92,.92)):
                if self.root_at(x+(r-x)*fx,y+(b-y)*fy)!=hwnd:return False,'다른 창/화면 경계가 게임 영역을 가립니다.'
        return True,''
def shifted(regions,old_client,new_client):
    dx=new_client[0]-old_client[0];dy=new_client[1]-old_client[1]
    move=lambda b:[b[0]+dx,b[1]+dy,b[2]+dx,b[3]+dy] if b else None
    return dict(board=move(regions['board']),hold=move(regions['hold']),next_slots=[move(b) for b in regions['next_slots']])
def same_size(a,b):return a[2]-a[0]==b[2]-b[0] and a[3]-a[1]==b[3]-b[1]
