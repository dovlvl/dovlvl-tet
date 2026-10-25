"""Check executable PYZ code against all current application modules."""

from pathlib import Path
import types, json, hashlib
import argparse, marshal
from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--exe", default="dist/TetrisAuto.exe")
parser.add_argument("--out", default="diagnostics/embedded_source_check.json")
args = parser.parse_args()
exe = root / args.exe
archive = CArchiveReader(str(exe))
pyz_entry = next(n for n in archive.toc if n.endswith(".pyz"))
temp = root / "diagnostics/embedded_check.pyz"
temp.write_bytes(archive.extract(pyz_entry))
pyz = ZlibArchiveReader(str(temp))


def signature(c):
    if isinstance(c, types.CodeType):
        return (
            c.co_code,
            c.co_names,
            c.co_varnames,
            c.co_freevars,
            c.co_cellvars,
            c.co_argcount,
            c.co_kwonlyargcount,
            c.co_flags,
            c.co_exceptiontable,
            tuple(signature(x) for x in c.co_consts),
        )
    return c


results = {}
for p in sorted((root / "src").glob("*.py")):
    if p.stem == "trainer" and p.stem in archive.toc:
        results[p.name] = signature(marshal.loads(archive.extract(p.stem))) == signature(
            compile(p.read_bytes(), str(p), "exec")
        )
        continue
    if p.stem not in pyz.toc:
        continue
    results[p.name] = signature(pyz.extract(p.stem)) == signature(compile(p.read_bytes(), str(p), "exec"))
required = {
    "trainer.py",
    "gui.py",
    "ui_status.py",
    "controller.py",
    "runtime.py",
    "recognition.py",
    "timing.py",
    "planner.py",
    "strategy.py",
    "scoring.py",
    "openers.py",
}
missing = sorted(required - set(results))
report = {
    "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
    "modules": results,
    "missing_required_modules": missing,
    "all_match": not missing and all(results.values()),
}
(root / args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["all_match"] else 1)
