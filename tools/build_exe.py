"""Build with an explicit Tk package path and reject missing GUI dependencies."""
import argparse
import importlib.util
from pathlib import Path
import tkinter
import PyInstaller.__main__

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--name',default='TetrisAuto')
parser.add_argument('--verify-startup',action='store_true')
args=parser.parse_args()
probe=tkinter.Tcl()
print('Tcl preflight:',probe.eval('info library'),probe.eval('info patchlevel'),flush=True)
for module in ('tkinter','tkinter.ttk','tkinter.filedialog','tkinter.messagebox','_tkinter'):
    if importlib.util.find_spec(module) is None:raise SystemExit('Missing build dependency: '+module)
PyInstaller.__main__.run([
    '--noconfirm','--clean','--onefile','--windowed','--name',args.name,
    '--paths',str(root/'src'),'--paths',str(Path(tkinter.__file__).resolve().parent.parent),
    '--hidden-import','tkinter','--hidden-import','tkinter.ttk',
    '--hidden-import','tkinter.filedialog','--hidden-import','tkinter.messagebox',
    '--hidden-import','tkinter.simpledialog',
    '--add-data',str(root/'data')+';data','--manifest',str(root/'packaging/app.manifest'),
    str(root/'src/trainer.py')])
warning=root/'build'/args.name/('warn-'+args.name+'.txt')
if warning.exists() and 'missing module named tkinter ' in warning.read_text(encoding='utf-8'):
    raise SystemExit('BUILD FAILED: tkinter missing from archive')
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader
archive=CArchiveReader(str(root/'dist'/(args.name+'.exe')))
pyz_name=next(n for n in archive.toc if n.endswith('.pyz'))
check=root/'build'/args.name/'gui_check.pyz';check.write_bytes(archive.extract(pyz_name))
pyz=ZlibArchiveReader(str(check))
for module in ('tkinter','tkinter.ttk','tkinter.filedialog','tkinter.messagebox'):
    if module not in pyz.toc:raise SystemExit('BUILD FAILED: missing packaged '+module)
for suffix in ('_tcl_data/init.tcl','_tk_data/tk.tcl'):
    if not any(n.replace('\\','/').endswith(suffix) for n in archive.toc):raise SystemExit('BUILD FAILED: missing '+suffix)
print('Verified packaged tkinter, Tcl init.tcl, Tk tk.tcl',flush=True)
if args.verify_startup:
    import subprocess,os,json
    output=root/'diagnostics/exe_startup_highspeed.json'
    env=os.environ.copy()
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','TCL_LIBRARY','TK_LIBRARY'):env.pop(key,None)
    env['PATH']=os.path.join(env.get('SystemRoot',r'C:\Windows'),'System32')
    subprocess.run([str(root/'dist'/(args.name+'.exe')),'--startup-check',str(output)],
                   env=env,cwd=str(root),timeout=30,check=True)
    report=json.loads(output.read_text(encoding='utf-8'))
    if not all(report[k] for k in ('started','window_exists','frozen','tcl_bundled')):
        raise SystemExit('EXE startup verification failed: '+str(report))
    if report['auto_running']:raise SystemExit('Startup check unexpectedly enabled Auto')
    print('EXE_STARTUP_VERIFIED',json.dumps(report,ensure_ascii=False),flush=True)
