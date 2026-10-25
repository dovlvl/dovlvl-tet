# Project status

## Canonical implementation

- Application source: repository-root `src/`.
- Entry point: `src/trainer.py` → `gui.App` → `runtime.Session`.
- Run: `run_windows.bat`; build: `build_windows.bat` → `tools/build_exe.py`.
- Dependencies: `requirements-lock.txt`; resources: `data/`; Windows manifest: `packaging/app.manifest`.
- Local executable: `dist/TetrisAuto.exe`, built only from root source. Binaries are not tracked.

## Release integration (2026-10-26)

The input is `release/TetrisAuto_20261025/TetrisAuto/`, identified by its Python entry point,
two-row GUI, scoring/recognition/runtime modules and pinned Windows build scripts.
Its 88 source/resource/test/tool/document/build files were byte-identical to the existing
uncommitted root implementation. That implementation is the merge baseline; no older
application behavior was copied over it. The previous Git HEAD was `16963d6`.

The input release, its ZIP and the original working changes are preserved locally.
A recoverable source checkpoint is under ignored `diagnostics/merge_checkpoint_*.zip`.
The extracted release and diagnostic baseline copies are reference material, not executable source roots.
The pre-existing deletion of `dist/TetrisTrainer_v06_fixed.exe` is retained; it must not be mistaken for a current build.

Old preview recognition is retained only as a regression-test reference under `tests/`.
Its offline comparison CLI is under `tools/`, separate from the application modules.

## Validation

- Related preview/opener, resource and status tests: passed (20 tests).
- Full regression: 145 tests passed in 33.668 seconds (`diagnostics/merge_full_tests.log`).
- `python -m pip check`: no broken requirements.
- Compact GUI smoke: four buttons + one status row, separate settings/diagnostics; no game input sent.
- Fresh root-source EXE build: passed with `--verify-startup`; native Windows GUI/Tcl/Tk startup confirmed and Auto remained off.
- Embedded-source verification: all required modules present and matching the final source.
- Final diff checks and candidate secret/large-file scan: passed; no credentials, logs or distribution binaries included.

Native GUI startup and real-game Auto are separate checks. Live Chrome gameplay,
scoring judgments and real-game PPS were not validated during this integration.
The source push target is the existing `origin/main`; no force push is used.

## Distribution

Source/resources/tests/scripts are committed to `main`. EXE/ZIP, user configuration,
logs, captures, caches and the virtual environment are excluded. See
`docs/RELEASE_POLICY.md`. No GitHub Release is published by this integration.
