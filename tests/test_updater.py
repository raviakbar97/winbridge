import io
import os
import zipfile
from pathlib import Path

import pytest

from updater import safe_extract_zip, build_restart_command


def make_zip(items):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in items.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_safe_extract_rejects_path_traversal(tmp_path):
    payload = make_zip({"../evil.py": "bad"})
    with pytest.raises(ValueError, match="unsafe zip path"):
        safe_extract_zip(payload, tmp_path)


def test_safe_extract_allows_expected_source_files(tmp_path):
    payload = make_zip({
        "server.py": "print('ok')",
        "agent_ws.py": "print('ok')",
        "agent_session.py": "print('ok')",
        "chrome_bridge.py": "print('ok')",
        "AGENT.md": "docs",
        "README.md": "readme",
        "requirements.txt": "flask",
        "chrome_extension/manifest.json": "{}",
    })
    files = safe_extract_zip(payload, tmp_path)
    assert sorted(str(p.relative_to(tmp_path)).replace(os.sep, "/") for p in files) == [
        "AGENT.md",
        "README.md",
        "agent_session.py",
        "agent_ws.py",
        "chrome_bridge.py",
        "chrome_extension/manifest.json",
        "requirements.txt",
        "server.py",
    ]


def test_safe_extract_rejects_unexpected_top_level_file(tmp_path):
    payload = make_zip({"secrets.env": "TOKEN=x"})
    with pytest.raises(ValueError, match="file not allowed"):
        safe_extract_zip(payload, tmp_path)


def test_restart_command_points_to_server_py(tmp_path):
    cmd = build_restart_command(tmp_path)
    assert cmd[0]
    assert cmd[-1] == str(tmp_path / "server.py")
