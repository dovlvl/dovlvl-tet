"""Run comparison processes sequentially; do not run builds/tests concurrently."""

import sys, subprocess, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(name, source, press=35, gap=35):
    out = "diagnostics/" + name + ".json"
    print("START " + name, flush=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/benchmark_auto.py"),
            "--source",
            source,
            "--out",
            out,
            "--blocks",
            "12",
            "--repeats",
            "3",
            "--press-ms",
            str(press),
            "--gap-ms",
            str(gap),
        ],
        cwd=ROOT,
        check=True,
    )
    return out


if __name__ == "__main__":
    outputs = []
    for repeat in (1, 2):
        outputs.append(run(f"before_common_{repeat}", "diagnostics/revision_baseline/src"))
        outputs.append(run(f"after_common_{repeat}", "src"))
    outputs.append(run("after_fast", "src", 20, 15))
    for tag, source in [("before", "diagnostics/revision_baseline/src"), ("after", "src")]:
        micro = f"diagnostics/recognition_{tag}.json"
        subprocess.run(
            [sys.executable, str(ROOT / "tools/benchmark_recognition.py"), "--source", source, "--out", micro],
            cwd=ROOT,
            check=True,
        )
        outputs.append(micro)
        out = f"diagnostics/score_{tag}.json"
        subprocess.run(
            [sys.executable, str(ROOT / "tools/compare_score_policy.py"), "--source", source, "--out", out],
            cwd=ROOT,
            check=True,
        )
        outputs.append(out)
    (ROOT / "diagnostics/revision_benchmark_manifest.json").write_text(
        json.dumps(dict(outputs=outputs, real_game_tested=False), indent=2), encoding="utf-8"
    )
    print("ALL_COMPARISONS_COMPLETE", flush=True)
