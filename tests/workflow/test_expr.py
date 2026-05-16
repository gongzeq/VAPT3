"""Tests for :mod:`secbot.workflow.expr` — template interpolation + condition eval."""

from __future__ import annotations

import pytest

from secbot.workflow.expr import ExprError, eval_bool, interpolate


# ---------------------------------------------------------------------------
# interpolate
# ---------------------------------------------------------------------------


def _ctx() -> dict:
    return {
        "inputs": {"target": "10.0.0.0/24", "threads": 50, "enabled": True},
        "steps": {
            "s1": {"result": {"content": "hello", "count": 7, "tags": ["a", "b"]},
                   "status": "ok"},
        },
    }


def test_interpolate_full_placeholder_preserves_native_type() -> None:
    assert interpolate("${inputs.threads}", _ctx()) == 50
    assert interpolate("${inputs.enabled}", _ctx()) is True
    assert interpolate("${steps.s1.result.tags}", _ctx()) == ["a", "b"]


def test_interpolate_embedded_placeholder_stringifies() -> None:
    out = interpolate("host=${inputs.target}, n=${inputs.threads}", _ctx())
    assert out == "host=10.0.0.0/24, n=50"


def test_interpolate_recurses_dict_and_list() -> None:
    args = {
        "target": "${inputs.target}",
        "nested": [{"t": "${inputs.threads}"}],
        "const": 42,
    }
    out = interpolate(args, _ctx())
    assert out == {"target": "10.0.0.0/24", "nested": [{"t": 50}], "const": 42}


def test_interpolate_missing_path_raises() -> None:
    with pytest.raises(ExprError, match="no such variable 'inputs.nope'"):
        interpolate("${inputs.nope}", _ctx())


# ---------------------------------------------------------------------------
# eval_bool
# ---------------------------------------------------------------------------


def test_eval_bool_basic_comparison() -> None:
    ctx = _ctx()
    assert eval_bool("steps.s1.result.count > 0", ctx) is True
    assert eval_bool("steps.s1.result.count == 7", ctx) is True
    assert eval_bool("steps.s1.result.count < 5", ctx) is False


def test_eval_bool_logical_operators() -> None:
    ctx = _ctx()
    assert eval_bool("inputs.enabled and steps.s1.status == 'ok'", ctx) is True
    assert eval_bool("not inputs.enabled or steps.s1.result.count == 0", ctx) is False


def test_eval_bool_empty_returns_true() -> None:
    assert eval_bool("", _ctx()) is True
    assert eval_bool("   ", _ctx()) is True


def test_eval_bool_rejects_function_call() -> None:
    with pytest.raises(ExprError, match="function calls are not allowed"):
        eval_bool("len(steps.s1.result.tags) > 0", _ctx())


def test_eval_bool_rejects_dunder_attribute() -> None:
    # `__class__` would be the usual escape hatch; guard must catch it.
    with pytest.raises(ExprError, match="attribute '__class__' is not allowed"):
        eval_bool("inputs.target.__class__ == str", _ctx())


def test_eval_bool_rejects_import() -> None:
    # Imports would require Call anyway, but keep the behaviour explicit.
    with pytest.raises(ExprError):
        eval_bool("__import__('os').system('ls')", _ctx())


def test_eval_bool_in_operator() -> None:
    ctx = _ctx()
    assert eval_bool("'a' in steps.s1.result.tags", ctx) is True
    assert eval_bool("'z' not in steps.s1.result.tags", ctx) is True


def test_eval_bool_unknown_variable_raises() -> None:
    with pytest.raises(ExprError, match="undefined variable"):
        eval_bool("missing > 0", _ctx())


def test_eval_bool_syntax_error_maps_to_expr_error() -> None:
    with pytest.raises(ExprError, match="syntax error"):
        eval_bool("1 +", _ctx())
