#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def copy_python_runtime(source: Path, destination: Path) -> None:
    if not (source / "python.exe").is_file() or not (source / "pythonw.exe").is_file():
        raise RuntimeError(f"Python runtime is incomplete: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name.lower() in {"scripts", "include", "libs", "doc", "tools"}:
            continue
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target)

    site_packages = destination / "Lib" / "site-packages"
    shutil.rmtree(site_packages, ignore_errors=True)
    site_packages.mkdir(parents=True, exist_ok=True)


def install_python_dependencies(build_python: Path, runtime: Path, report: Path) -> None:
    requirements = ROOT / "windows" / "app" / "requirements-windows.txt"
    destination = runtime / "Lib" / "site-packages"
    command = [
        str(build_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--only-binary=:all:",
        "--target",
        str(destination),
        "--report",
        str(report),
        "-r",
        str(requirements),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def clean_payload(root: Path) -> None:
    for path in sorted(root.rglob("__pycache__"), reverse=True):
        shutil.rmtree(path, ignore_errors=True)
    for pattern in ("*.pyc", "*.pyo", "*.ps1", "*.bat", "*.cmd"):
        for path in root.rglob(pattern):
            path.unlink(missing_ok=True)
    for path in root.rglob("*.dist-info/RECORD"):
        path.unlink(missing_ok=True)


def write_manifest(root: Path) -> Path:
    manifest = root / "manifest.sha256"
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest:
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    if not lines:
        raise RuntimeError("Windows payload is empty")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return manifest


def write_zip(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            info = ZipInfo(relative, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)


def validate_payload(root: Path, version: str) -> None:
    required = [
        root / "ReelIndex.exe",
        root / "Uninstall ReelIndex.exe",
        root / "runtime" / "python.exe",
        root / "runtime" / "pythonw.exe",
        root / "app" / "windows_launcher.py",
        root / "app" / "app" / "version.py",
        root / "app" / "web" / "index.html",
        root / "manifest.sha256",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing Windows payload files: {missing}")
    version_text = (root / "app" / "app" / "version.py").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in version_text:
        raise RuntimeError("Windows payload version does not match VERSION")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    runtime = output / "runtime"
    app_destination = output / "app"
    report = output.parent / "windows-python-dependencies.json"

    if output.exists():
        for child in output.iterdir():
            if child.name not in {"ReelIndex.exe", "Uninstall ReelIndex.exe"}:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
    else:
        output.mkdir(parents=True)

    shutil.copytree(ROOT / "windows" / "app", app_destination, dirs_exist_ok=True)
    copy_python_runtime(args.python_root.resolve(), runtime)
    install_python_dependencies(Path(sys.executable), runtime, report)
    clean_payload(output)
    write_manifest(output)
    validate_payload(output, args.version)
    write_zip(output, args.archive.resolve())

    summary = {
        "version": args.version,
        "payload_files": sum(1 for path in output.rglob("*") if path.is_file()),
        "payload_bytes": sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        "archive_bytes": args.archive.resolve().stat().st_size,
        "dependency_report": str(report),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
