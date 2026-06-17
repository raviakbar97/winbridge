"""Self-update helpers for Winbridge.

The running Flask app writes an uploaded ZIP to a staging directory, then
spawns this module as a detached process. The updater waits for the old
process to exit, backs up files that will be replaced, copies staged files
into the app directory, and starts a fresh server.py process.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

ALLOWED_TOP_LEVEL_FILES = {"server.py", "AGENT.md", "requirements.txt", "updater.py", "agent_ws.py"}
ALLOWED_DIR_PREFIXES = ("chrome_extension/", "tests/")
STATUS_FILE = ".winbridge-update-status.json"


def _as_posix(path: str) -> str:
    return path.replace("\\", "/")


def is_allowed_member(name: str) -> bool:
    normalized = _as_posix(name).lstrip("/")
    if not normalized or normalized.endswith("/"):
        return True
    if normalized in ALLOWED_TOP_LEVEL_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in ALLOWED_DIR_PREFIXES)


def _safe_destination(root: Path, member_name: str) -> Path:
    normalized = _as_posix(member_name).lstrip("/")
    if not normalized or normalized.endswith("/"):
        return root / normalized
    if "\x00" in normalized:
        raise ValueError(f"unsafe zip path: {member_name!r}")
    dest = (root / normalized).resolve()
    root_resolved = root.resolve()
    if dest != root_resolved and root_resolved not in dest.parents:
        raise ValueError(f"unsafe zip path: {member_name!r}")
    if not is_allowed_member(normalized):
        raise ValueError(f"file not allowed in update bundle: {member_name}")
    return dest


def safe_extract_zip(payload: bytes, destination: Path) -> List[Path]:
    """Extract an update ZIP safely and return extracted file paths."""
    destination.mkdir(parents=True, exist_ok=True)
    extracted: List[Path] = []
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(payload)) as zf:
        for info in zf.infolist():
            dest = _safe_destination(destination, info.filename)
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            extracted.append(dest)
    return extracted


def build_restart_command(app_dir: Path) -> List[str]:
    return [sys.executable, str(app_dir / "server.py")]


def install_requirements_if_present(app_dir: Path, staged_files: List[Path], staging_dir: Path) -> bool:
    """Install requirements when requirements.txt is part of the update bundle."""
    staged_rels = {str(p.relative_to(staging_dir)).replace(os.sep, "/") for p in staged_files}
    if "requirements.txt" not in staged_rels:
        return False
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(app_dir / "requirements.txt")],
        cwd=str(app_dir),
        check=True,
        timeout=180,
    )
    return True


def _write_status(app_dir: Path, data: dict) -> None:
    data = dict(data)
    data.setdefault("timestamp", datetime.utcnow().isoformat(timespec="seconds") + "Z")
    (app_dir / STATUS_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _wait_for_pid_exit(pid: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    if pid <= 0:
        return
    while time.time() < deadline:
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if str(pid) not in result.stdout:
                    return
            else:
                os.kill(pid, 0)
        except Exception:
            return
        time.sleep(0.25)


def _iter_staged_files(staging_dir: Path) -> Iterable[Path]:
    for path in staging_dir.rglob("*"):
        if path.is_file():
            yield path


def apply_update_and_restart(app_dir: Path, staging_dir: Path, old_pid: int) -> None:
    app_dir = app_dir.resolve()
    staging_dir = staging_dir.resolve()
    backup_dir = app_dir / "backups" / datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    try:
        _write_status(app_dir, {"status": "applying", "staging_dir": str(staging_dir), "backup_dir": str(backup_dir)})
        _wait_for_pid_exit(old_pid)
        backup_dir.mkdir(parents=True, exist_ok=True)

        staged_files = list(_iter_staged_files(staging_dir))
        for src in staged_files:
            rel = src.relative_to(staging_dir)
            dest = app_dir / rel
            if dest.exists():
                backup_path = backup_dir / rel
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup_path)

        for src in staged_files:
            rel = src.relative_to(staging_dir)
            dest = app_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        requirements_installed = install_requirements_if_present(app_dir, staged_files, staging_dir)

        _write_status(app_dir, {"status": "success", "backup_dir": str(backup_dir), "files": [str(p.relative_to(staging_dir)).replace(os.sep, "/") for p in staged_files], "requirements_installed": requirements_installed})
        subprocess.Popen(build_restart_command(app_dir), cwd=str(app_dir), close_fds=True)
    except Exception as exc:
        _write_status(app_dir, {"status": "failed", "error": repr(exc), "backup_dir": str(backup_dir)})
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a staged Winbridge update and restart server.py")
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--old-pid", type=int, default=0)
    args = parser.parse_args(argv)
    apply_update_and_restart(Path(args.app_dir), Path(args.staging_dir), args.old_pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
