# Distribution policy

Git stores the canonical root source, required reference resources, tests and build scripts.
The repository has no separate release automation or binary publication policy.
The previously tracked obsolete EXE is removed from the current source tree.

Fresh builds are local artifacts under `dist/`; ZIPs and extracted release inputs are under
`release/`. Neither directory is committed. When explicitly requested, distribution binaries
belong in GitHub Release assets rather than Git history. Creating or publishing a new public
GitHub Release requires a separate request and is not part of this integration.

Only `src/trainer.py` is the application entry point. Root run/build scripts always change
to the repository root and use root `src/`, `data/` and `packaging/` paths. Reference copies
inside `release/` or `diagnostics/` must not be used as the active implementation.
