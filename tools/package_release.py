"""Package current source, validated EXE, scripts and reproducible evidence."""
from pathlib import Path
import json,hashlib,zipfile
ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

if __name__=='__main__':
    check=json.loads((ROOT/'diagnostics/embedded_source_check.json').read_text(encoding='utf-8'))
    exe=ROOT/'dist/TetrisAuto.exe'
    assert check['all_match'] and sha(exe)==check['exe_sha256'],'Build/source verification required'
    assert (ROOT/'docs/VALIDATION_REPORT_KO.md').exists()
    files=set()
    for name in ('src','data','tests','tools','docs','packaging','diagnostics/revision_baseline/src','diagnostics/revision_baseline/data'):
        for p in (ROOT/name).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'):files.add(p)
    for name in ('README.md','requirements.txt','requirements-lock.txt','run_windows.bat','build_windows.bat','test_latest_results.txt','dist/TetrisAuto.exe'):
        files.add(ROOT/name)
    manifest=json.loads((ROOT/'diagnostics/revision_benchmark_manifest.json').read_text(encoding='utf-8'))
    for name in manifest['outputs']:files.add(ROOT/name)
    for name in ('revision_summary.json','revision_benchmark_manifest.json','embedded_source_check.json','exe_startup_highspeed.json','reported_vision_traceback.txt'):
        p=ROOT/'diagnostics'/name
        if p.exists():files.add(p)
    release=ROOT/'release';release.mkdir(exist_ok=True)
    target=release/'TetrisAuto_20261025.zip'
    checks={str(p.relative_to(ROOT)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(files):z.write(p,'TetrisAuto/'+p.relative_to(ROOT).as_posix())
        z.writestr('TetrisAuto/FILE_MANIFEST.json',json.dumps(checks,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(files)+1
        for name,entry in checks.items():assert hashlib.sha256(z.read('TetrisAuto/'+name)).hexdigest()==entry['sha256']
    digest=sha(target)
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print(json.dumps({'zip':str(target),'bytes':target.stat().st_size,'files':len(files),'sha256':digest}))
