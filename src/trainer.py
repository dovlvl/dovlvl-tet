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
    root=tk.Tk();App(root);root.mainloop()
if __name__=='__main__':main()
