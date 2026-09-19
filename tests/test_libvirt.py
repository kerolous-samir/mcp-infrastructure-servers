from __future__ import annotations

from conftest import EXPECTED_TOOLS, check_schema

SERVER = "libvirt"
SAMPLE = "create_snapshot"


def test_initialize_and_list_exact_count(start):
    server = start(SERVER)
    tools = server.tools()
    assert len(tools) == EXPECTED_TOOLS[SERVER], (
        f"{SERVER}: tools/list returned {len(tools)}, expected {EXPECTED_TOOLS[SERVER]}"
    )


def test_sample_tool_present_with_valid_schema(start):
    server = start(SERVER)
    by_name = {t["name"]: t for t in server.tools()}
    assert SAMPLE in by_name, f"{SERVER}: {SAMPLE} missing from tools/list"
    check_schema(by_name[SAMPLE])


def test_every_tool_has_a_valid_schema(start):
    server = start(SERVER)
    for tool in server.tools():
        check_schema(tool)


def test_shuts_down_cleanly(start):
    server = start(SERVER)
    server.tools()
    assert server.shutdown() == 0, f"{SERVER}: non-zero exit on stdin close"
