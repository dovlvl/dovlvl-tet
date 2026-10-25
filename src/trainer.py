import sys,multiprocessing

def main():
    multiprocessing.freeze_support()
    if sys.platform=='win32':
        import ctypes
        try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:pass
    import logging
    from logging.handlers import RotatingFileHandler
    from config import PATH
    PATH.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[RotatingFileHandler(PATH.parent/'trainer.log',maxBytes=1000000,backupCount=3,encoding='utf-8')])
    import tkinter as tk
    from gui import App
    root=tk.Tk();app=App(root,launch_game='--startup-check' not in sys.argv)
    if '--startup-check' in sys.argv:
        import json
        from pathlib import Path
        output=Path(sys.argv[sys.argv.index('--startup-check')+1])
        def startup_check():
            app.render();root.update_idletasks()
            frozen=bool(getattr(sys,'frozen',False));bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).parent)).resolve()
            tcl=Path(root.tk.eval('info library')).resolve()
            report=dict(started=True,window_exists=bool(root.winfo_exists()),window_title=root.title(),
                        frozen=frozen,executable=sys.executable,tcl_library=str(tcl),tk_version=root.tk.eval('package require Tk'),
                        tcl_bundled=tcl.is_relative_to(bundle),status=app.status.get(),auto_running=bool(app.ctl and app.ctl.running))
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            app.close()
        root.after(1500,startup_check)
    root.mainloop()
if __name__=='__main__':main()
