"""Run nuXmv/NuSMV on both P09 models and summarize the five properties."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
MODELS = {
    "bug": ROOT / "models" / "request_response_bug.smv",
    "fixed": ROOT / "models" / "request_response_fixed.smv",
}
PROPERTIES = {
    "G!at_error": ("S1", "G !at_error"),
    "G(at_ack->Xat_idle)": ("S2", "G (at_ack -> X at_idle)"),
    "G(at_req->X(at_req|at_ack))": ("S3", "G (at_req -> X (at_req | at_ack))"),
    "G(at_req->Fat_ack)": ("L1", "G (at_req -> F at_ack)"),
    "EFat_ack": ("C1", "EF at_ack"),
}
RESULT = re.compile(r"^-- specification\s+(.+?)\s+is\s+(true|false)\s*$", re.MULTILINE)


def find_executable(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("NUXMV")
    if from_env:
        return from_env
    for name in ("nuXmv", "NuSMV"):
        found = shutil.which(name)
        if found:
            return found
    bundled = ROOT / ".tools" / "nuXmv-2.0.0-win64" / "bin" / "nuXmv.exe"
    if bundled.exists():
        return str(bundled)
    raise FileNotFoundError("nuXmv/NuSMV not found; install it or pass --exe PATH")


def check_model(executable: str, name: str, log_dir: Path) -> dict[str, bool]:
    completed = subprocess.run(
        [executable, "-s", str(MODELS[name])],
        cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=60,
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{name}.nuxmv.txt").write_text(
        completed.stdout + completed.stderr, encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{name}: nuXmv exited with code {completed.returncode}; see log")
    found: dict[str, bool] = {}
    for expression, truth in RESULT.findall(completed.stdout):
        normalized = re.sub(r"\s+", "", expression)
        if normalized not in PROPERTIES:
            raise RuntimeError(f"{name}: unexpected property: {expression}")
        if normalized in found:
            raise RuntimeError(f"{name}: repeated property: {expression}")
        found[normalized] = truth == "true"
    if set(found) != set(PROPERTIES):
        missing = set(PROPERTIES) - set(found)
        raise RuntimeError(f"{name}: missing results: {sorted(missing)}; see log")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Check both P09 request/response NuSMV models")
    parser.add_argument("--exe", help="path to nuXmv or NuSMV executable")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = parser.parse_args()
    try:
        executable = find_executable(args.exe)
        results = {name: check_model(executable, name, args.log_dir)
                   for name in MODELS}
    except (FileNotFoundError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"HW5 error: {exc}", file=sys.stderr)
        return 1
    print("Property  Formula                             Bug    Fixed")
    print("----------------------------------------------------------")
    for key, (identifier, formula) in PROPERTIES.items():
        bug = "TRUE" if results["bug"][key] else "FALSE"
        fixed = "TRUE" if results["fixed"][key] else "FALSE"
        print(f"{identifier:8}  {formula:34}  {bug:5}  {fixed}")
    print(f"Raw nuXmv output: {args.log_dir}")
    expected = {"bug": {key: key != "G(at_req->Fat_ack)" for key in PROPERTIES},
                "fixed": {key: True for key in PROPERTIES}}
    if results != expected:
        print("HW5 error: results differ from the documented expectations", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
