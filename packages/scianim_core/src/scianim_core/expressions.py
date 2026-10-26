"""Safe arithmetic expressions for analytic curves (`function_plot`).

YAML never carries executable Python. An expression is validated against a whitelist of operators,
functions and names before it is compiled; `^` is accepted as the power operator.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Iterable, Sequence

ALLOWED_FUNCTIONS: dict[str, Callable[..., float]] = {
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "tanh": math.tanh,
    "abs": abs,
    "min": min,
    "max": max,
    "pow": math.pow,
    "floor": math.floor,
    "ceil": math.ceil,
}
ALLOWED_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}

_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Load)


def normalize(expression: str) -> str:
    return expression.replace("^", "**")


def validate_expression(expression: str, variables: Sequence[str] = ("x",)) -> ast.Expression:
    """Parse and whitelist-check an expression; raise ValueError with a readable message."""
    try:
        tree = ast.parse(normalize(expression), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression {expression!r}: {exc.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, *_OPERATORS)):
            continue
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow | ast.Mod
        ):
            continue
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            if node.id in variables or node.id in ALLOWED_CONSTANTS or node.id in ALLOWED_FUNCTIONS:
                continue
            raise ValueError(
                f"unknown name '{node.id}' in {expression!r}; allowed variables {list(variables)}, "
                f"constants {sorted(ALLOWED_CONSTANTS)}, functions {sorted(ALLOWED_FUNCTIONS)}"
            )
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ALLOWED_FUNCTIONS and not node.keywords:
                continue
            raise ValueError(f"only calls to {sorted(ALLOWED_FUNCTIONS)} are allowed in {expression!r}")
        raise ValueError(f"unsupported syntax ({type(node).__name__}) in {expression!r}")
    return tree


def compile_expression(expression: str, variables: Sequence[str] = ("x",)) -> Callable[..., float]:
    """Return `f(**values) -> float`; non-finite results and domain errors come back as NaN."""
    tree = validate_expression(expression, variables)
    code = compile(tree, "<expression>", "eval")
    namespace = {"__builtins__": {}, **ALLOWED_FUNCTIONS, **ALLOWED_CONSTANTS}

    def evaluate(**values: float) -> float:
        missing = set(variables) - set(values)
        if missing:
            raise TypeError(f"missing variable(s) {sorted(missing)}")
        try:
            result = eval(code, namespace, dict(values))
        except (ZeroDivisionError, ValueError, OverflowError):
            return math.nan
        return float(result)

    return evaluate


def sample(expression: str, xs: Iterable[float]) -> list[float]:
    function = compile_expression(expression, ("x",))
    return [function(x=x) for x in xs]
