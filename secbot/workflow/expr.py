"""Expression and template interpolation for the workflow engine.

Two surface functions:

* :func:`interpolate` — recursively substitute ``${path.to.value}``
  placeholders inside ``dict`` / ``list`` / ``str`` structures, pulling
  values from a context like ``{"inputs": {...}, "steps": {<id>: {...}}}``.
  Non-string positions (ints, bools) are replaced by their native Python
  values when the whole string is a single placeholder; otherwise they
  are stringified.

* :func:`eval_bool` — evaluate a user-supplied condition like
  ``steps.s2.result.errors > 0`` against the same context. Parsing uses
  :mod:`ast` with a strict node whitelist; ``eval()`` is never called,
  ``__import__`` / dunder attribute access / function calls / lambdas
  are all rejected at compile time.

Both helpers are sync, side-effect free, and safe to call from an async
runner loop.

Spec: ``.trellis/tasks/05-11-workflow-builder-ui/api-spec.md §1.3``.
"""

from __future__ import annotations

import ast
import re
from typing import Any


class ExprError(ValueError):
    """Raised on expression parse / evaluation errors (always user-facing)."""


# ---------------------------------------------------------------------------
# Template interpolation
# ---------------------------------------------------------------------------

# Allow dotted paths only (no arithmetic, no calls). The full-match regex
# is used to detect "the whole string is one placeholder" and return the
# native value (int / bool / dict) rather than a str.
_PLACEHOLDER = re.compile(r"\$\{([a-zA-Z_][\w.\[\]'\"-]*)\}")
_FULL = re.compile(r"^\$\{([a-zA-Z_][\w.\[\]'\"-]*)\}$")


def _resolve_path(path: str, ctx: dict[str, Any]) -> Any:
    """Walk ``ctx`` along a dotted path like ``inputs.target`` or
    ``steps.s1.result.errors``. Missing segments raise :class:`ExprError`
    with the exact path that failed, so the user sees useful errors in
    run history instead of a bare ``KeyError``.
    """
    parts = path.split(".")
    cur: Any = ctx
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise ExprError(f"no such list index '{'.'.join(walked)}'") from exc
        else:
            raise ExprError(f"no such variable '{'.'.join(walked)}'")
    return cur


def interpolate(value: Any, ctx: dict[str, Any]) -> Any:
    """Recursively substitute ``${path}`` placeholders inside ``value``.

    Rules:
    - A string that is *exactly* one placeholder returns the native value
      (``int``, ``dict``, etc.) so downstream executors receive the right
      type without eval.
    - A string with embedded placeholders returns a string; non-string
      native values are ``str()``-ified at the insertion point.
    - ``dict`` and ``list`` are walked in place (a new container is
      returned, input is not mutated).
    - All other types pass through unchanged.
    """
    if isinstance(value, str):
        full = _FULL.match(value)
        if full:
            return _resolve_path(full.group(1), ctx)

        def _sub(m: re.Match[str]) -> str:
            v = _resolve_path(m.group(1), ctx)
            return str(v) if v is not None else ""

        return _PLACEHOLDER.sub(_sub, value)

    if isinstance(value, dict):
        return {k: interpolate(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(x, ctx) for x in value]
    return value


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

# Whitelist of AST node types. Any node not in this set causes a parse
# error — this is the core defence against arbitrary code execution.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Constant,
    ast.Attribute,
    ast.Subscript,
    ast.Index,  # py<3.9 fallback; harmless on 3.11
    ast.Load,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UAdd,
    ast.USub,
    # Binary / comparison operators.
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.FloorDiv,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.List,
    ast.Tuple,
)


def _check_node(node: ast.AST) -> None:
    """Raise :class:`ExprError` if any descendant is outside the whitelist.

    Two extra guards beyond the node-type whitelist:
    - Attribute access to names starting with ``_`` is banned (blocks
      ``__class__`` / ``__import__`` / ``__subclasses__`` escapes).
    - ``Call`` nodes are NOT in the whitelist, so function invocation is
      impossible; this is reiterated here for self-documentation.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            raise ExprError("function calls are not allowed in conditions")
        if not isinstance(child, _ALLOWED_NODES):
            raise ExprError(f"expression node not allowed: {type(child).__name__}")
        if isinstance(child, ast.Attribute) and child.attr.startswith("_"):
            raise ExprError(f"attribute '{child.attr}' is not allowed")
        if isinstance(child, ast.Name) and child.id.startswith("_"):
            raise ExprError(f"name '{child.id}' is not allowed")


def _eval(node: ast.AST, ctx: dict[str, Any]) -> Any:
    """Recursive evaluator for the whitelisted AST subset."""
    if isinstance(node, ast.Expression):
        return _eval(node.body, ctx)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in ctx:
            raise ExprError(f"undefined variable '{node.id}'")
        return ctx[node.id]
    if isinstance(node, ast.Attribute):
        obj = _eval(node.value, ctx)
        if isinstance(obj, dict) and node.attr in obj:
            return obj[node.attr]
        raise ExprError(f"no such attribute '{node.attr}'")
    if isinstance(node, ast.Subscript):
        obj = _eval(node.value, ctx)
        slice_node = node.slice
        if isinstance(slice_node, ast.Index):  # py<3.9 fallback
            slice_node = slice_node.value  # type: ignore[attr-defined]
        key = _eval(slice_node, ctx)
        try:
            return obj[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExprError(f"subscript lookup failed: {exc}") from exc
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not v
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = _eval(v, ctx)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for v in node.values:
                result = _eval(v, ctx)
                if result:
                    return result
            return result
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, ctx), _eval(node.right, ctx)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Mod):
            return a % b
        if isinstance(node.op, ast.FloorDiv):
            return a // b
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, ctx)
            if isinstance(op, ast.Eq) and not (left == right):
                return False
            if isinstance(op, ast.NotEq) and not (left != right):
                return False
            if isinstance(op, ast.Lt) and not (left < right):
                return False
            if isinstance(op, ast.LtE) and not (left <= right):
                return False
            if isinstance(op, ast.Gt) and not (left > right):
                return False
            if isinstance(op, ast.GtE) and not (left >= right):
                return False
            if isinstance(op, ast.In) and not (left in right):
                return False
            if isinstance(op, ast.NotIn) and not (left not in right):
                return False
            if isinstance(op, ast.Is) and not (left is right):
                return False
            if isinstance(op, ast.IsNot) and not (left is not right):
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(x, ctx) for x in node.elts]
    raise ExprError(f"unsupported node: {type(node).__name__}")


def eval_bool(expr: str, ctx: dict[str, Any]) -> bool:
    """Evaluate ``expr`` against ``ctx`` and coerce the result to bool.

    Raises :class:`ExprError` on syntax, whitelist or lookup failures —
    the caller is expected to map this to
    ``workflow.validation.condition`` / ``workflow.dag.invalid`` per
    ``api-spec.md §4``.
    """
    expr = (expr or "").strip()
    if not expr:
        return True
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"syntax error: {exc.msg}") from exc
    _check_node(tree)
    return bool(_eval(tree, ctx))
