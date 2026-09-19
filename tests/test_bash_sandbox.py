from __future__ import annotations

import json
import os

import pytest

SERVER = "bash"
SECRET = "sandbox-escape-canary"


def _text(reply: dict) -> str:
    if "error" in reply:
        return json.dumps(reply["error"])
    content = reply.get("result", {}).get("content") or []
    parts = [item.get("text", "") for item in content if isinstance(item, dict)]
    return " ".join(parts) + json.dumps(reply.get("result", {}).get("isError", ""))


REFUSAL_MARKERS = ("path not allowed", "outside the permitted root")


def _refused(reply: dict) -> bool:
    blob = _text(reply).lower()
    return any(marker in blob for marker in REFUSAL_MARKERS)


@pytest.fixture
def sandbox(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text(SECRET + "\n", encoding="utf-8")
    (allowed / "fine.txt").write_text("inside the sandbox\n", encoding="utf-8")
    link = allowed / "escape-link"
    os.symlink(str(secret), str(link))
    dirlink = allowed / "escape-dir"
    os.symlink(str(outside), str(dirlink))
    return {
        "allowed": allowed,
        "outside": outside,
        "secret": secret,
        "link": link,
        "dirlink": dirlink,
    }


@pytest.fixture
def bash(start, sandbox):
    return start(SERVER, {"BASH_MCP_ALLOWED_ROOTS": str(sandbox["allowed"])})


def test_inside_the_allowlist_still_works(bash, sandbox):
    reply = bash.call("read_file", {"path": str(sandbox["allowed"] / "fine.txt")})
    assert not _refused(reply), f"a legitimate in-sandbox read was refused: {_text(reply)[:200]}"
    assert "inside the sandbox" in _text(reply)


def test_absolute_path_outside_allowlist_is_refused(bash, sandbox):
    reply = bash.call("read_file", {"path": str(sandbox["secret"])})
    assert _refused(reply), f"read outside the allowlist was NOT refused: {_text(reply)[:200]}"
    assert SECRET not in _text(reply), "refusal still leaked the file contents"


def test_dotdot_traversal_is_refused(bash, sandbox):
    escape = str(sandbox["allowed"] / ".." / "outside" / "secret.txt")
    reply = bash.call("read_file", {"path": escape})
    assert _refused(reply), f".. traversal was NOT refused: {_text(reply)[:200]}"
    assert SECRET not in _text(reply), "refusal still leaked the file contents"


def test_symlink_to_file_outside_is_refused(bash, sandbox):
    reply = bash.call("read_file", {"path": str(sandbox["link"])})
    assert _refused(reply), f"symlink escape was NOT refused: {_text(reply)[:200]}"
    assert SECRET not in _text(reply), "refusal still leaked the file contents"


def test_symlink_to_directory_outside_is_refused(bash, sandbox):
    reply = bash.call("read_file", {"path": str(sandbox["dirlink"] / "secret.txt")})
    assert _refused(reply), f"symlinked directory escape was NOT refused: {_text(reply)[:200]}"
    assert SECRET not in _text(reply), "refusal still leaked the file contents"


def test_listing_outside_the_allowlist_is_refused(bash, sandbox):
    reply = bash.call("list_directory", {"path": str(sandbox["outside"])})
    assert _refused(reply), f"listing outside the allowlist was NOT refused: {_text(reply)[:200]}"


def test_write_outside_the_allowlist_is_refused(bash, sandbox):
    target = sandbox["outside"] / "planted.txt"
    reply = bash.call("write_file", {"path": str(target), "content": "planted"})
    assert _refused(reply), f"write outside the allowlist was NOT refused: {_text(reply)[:200]}"
    assert not target.exists(), "the file was actually created outside the allowlist"


def test_delete_outside_the_allowlist_is_refused(bash, sandbox):
    reply = bash.call("delete_file", {"path": str(sandbox["secret"])})
    assert _refused(reply), f"delete outside the allowlist was NOT refused: {_text(reply)[:200]}"
    assert sandbox["secret"].exists(), "the file outside the allowlist was deleted"


def test_copy_destination_outside_the_allowlist_is_refused(bash, sandbox):
    target = sandbox["outside"] / "copied.txt"
    reply = bash.call(
        "copy_file", {"src": str(sandbox["allowed"] / "fine.txt"), "dst": str(target)}
    )
    assert _refused(reply), f"copy out of the allowlist was NOT refused: {_text(reply)[:200]}"
    assert not target.exists(), "the file was actually copied outside the allowlist"
