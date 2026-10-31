"""Cross-file consistency checks, offline (file reads + regex only).

A renamed agent or a drifted data topic breaks the handshake silently: the
room stays quiet and the recap card never arrives. These tests pin the string
literals on both sides of each seam together — the exact mismatch the
telephony README lists as troubleshooting cause #1.
"""

import json
import re
from pathlib import Path

from bakar_state import END_TOPIC, RECAP_TOPIC

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _agent_name_literal(path: str) -> str:
    match = re.search(r'agent_name="([^"]+)"', _read(*path.split("/")))
    assert match, f"no agent_name= literal found in {path}"
    return match.group(1)


def _agent_name_default(path: str) -> str:
    match = re.search(
        r'os\.getenv\("AGENT_NAME",\s*"([^"]+)"\)', _read(*path.split("/"))
    )
    assert match, f"no AGENT_NAME env default found in {path}"
    return match.group(1)


def test_dispatch_rule_matches_the_inbound_agent() -> None:
    rule = json.loads(
        _read("backend", "src", "telephony", "inbound", "dispatch-rule.json")
    )
    assert rule["roomConfig"]["agents"][0]["agentName"] == _agent_name_literal(
        "backend/src/telephony/inbound/agent.py"
    )


def test_dial_dispatches_the_outbound_agent() -> None:
    assert _agent_name_default(
        "backend/src/telephony/outbound/dial.py"
    ) == _agent_name_literal("backend/src/telephony/outbound/agent.py")


def test_e2e_scripts_target_the_main_agent() -> None:
    main_default = _agent_name_default("backend/src/agent.py")
    assert main_default == "bakar-agent"  # the frontend expects this dispatch name
    for name in ("e2e_end.py", "e2e_recap.py", "e2e_room.py"):
        assert _agent_name_default(f"backend/scripts/{name}") == main_default


def test_recap_topics_match_the_frontend() -> None:
    """The only frontend/backend literal contract that can be checked from here."""
    frontend = _read("frontend", "lib", "recap.ts")
    recap_topic = re.search(r"RECAP_TOPIC\s*=\s*'([^']+)'", frontend)
    end_topic = re.search(r"END_TOPIC\s*=\s*'([^']+)'", frontend)
    assert recap_topic is not None, "RECAP_TOPIC not found in frontend/lib/recap.ts"
    assert end_topic is not None, "END_TOPIC not found in frontend/lib/recap.ts"
    assert recap_topic.group(1) == RECAP_TOPIC
    assert end_topic.group(1) == END_TOPIC
