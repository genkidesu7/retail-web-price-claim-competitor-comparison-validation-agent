"""PB-7: HITL interrupt boundary.

This agent has no human-in-the-loop path: a price-claim validation is a one-shot
request/response, and the Marketplace runner has no resume channel for an
``AWAITING_HUMAN`` status. The proof of boundary is therefore the negative one —
``hitl.enabled`` is off in config/config.yaml AND no node under src/ can raise a
LangGraph interrupt. Enabling HITL later without wiring an interrupt-aware node
(and its propagation tests) must fail here rather than pass silently.
"""

from __future__ import annotations

import ast
import pathlib

import yaml

_ROOT = pathlib.Path(__file__).parents[2]
_CONFIG_PATH = _ROOT / "config" / "config.yaml"
_SRC_PATH = _ROOT / "src"


def _calls_interrupt(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name == "interrupt":
            return True
    return False


def test_pb7_hitl_is_disabled_in_config() -> None:
    data = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    hitl = data.get("hitl") or {}
    assert not hitl.get("enabled", False), (
        "config/config.yaml enables hitl, but no node in src/ calls interrupt() — "
        "add an interrupt-aware node with propagation tests before enabling HITL"
    )


def test_pb7_no_node_calls_interrupt() -> None:
    offenders = [
        str(path.relative_to(_ROOT))
        for path in sorted(_SRC_PATH.rglob("*.py"))
        if _calls_interrupt(ast.parse(path.read_text()))
    ]
    assert offenders == [], f"interrupt() called without HITL wiring: {offenders}"
