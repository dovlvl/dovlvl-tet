"""Hidden GUI construction check; no screen capture or real keyboard input."""
import copy,sys,types
from pathlib import Path
from unittest.mock import patch
from queue import Queue
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import tkinter as tk
import gui
from config import DEFAULT
from helpers import FakeBackend

class Hotkeys:
    def __init__(self,*args):
        self.status={};self.received=[];self.events=Queue();self.ready=True
        self.thread=types.SimpleNamespace(is_alive=lambda:True)
    def close(self):pass

def main():
    with patch.dict(sys.modules,{'hotkeys':types.SimpleNamespace(Hotkeys=Hotkeys)}), \
         patch.object(gui,'load',lambda:copy.deepcopy(DEFAULT)), \
         patch.object(gui,'save',lambda c:None), \
         patch.object(gui,'WindowSystem',lambda:types.SimpleNamespace(browsers=lambda:[])), \
         patch.object(gui,'WindowsBackend',FakeBackend):
        root=tk.Tk();root.withdraw();app=gui.App(root)
        try:
            app.render();root.update()
            assert root.title()=='Tetris Auto · 전략 자동 플레이'
            assert 'UI_ERROR' not in app.status.get(),app.status.get()
            main=[w for w in root.winfo_children() if w.winfo_manager()]
            assert len(main)==2,[(w.winfo_class(),w.winfo_manager()) for w in main]
            buttons=main[0].winfo_children()
            assert len(buttons)==4
            assert [w.cget('text') if not w.cget('textvariable') else root.getvar(w.cget('textvariable')) for w in buttons]==['게임찾기','실행','끝내기','설정']
            assert app.summary.get().startswith('보드: ')
            assert not root.cget('menu')
            app.options();root.update()
            app.diagnostics();root.update()
            assert app.diag.winfo_exists()
            assert not app.backend.events,'GUI must never send gameplay keys'
            print('GUI_AUTO_SMOKE PASS: exactly four buttons + one status row; separate settings and diagnostics; real inputs=0')
        finally:app.close()

if __name__=='__main__':main()
