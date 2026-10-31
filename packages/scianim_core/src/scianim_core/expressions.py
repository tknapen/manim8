"""Safe arithmetic expressions for analytic curves, surfaces and sampled fields.

YAML never carries executable Python. An expression is validated against a whitelist of operators,
functions and names before it is compiled; `^` is accepted as the power operator.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

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


def _array_namespace() -> dict[str, Any]:
    """The whitelist over NumPy arrays: the same names as `ALLOWED_FUNCTIONS`, element-wise."""
    import functools

    import numpy as np

    def smallest(*args: Any) -> Any:
        return functools.reduce(np.minimum, args)

    def largest(*args: Any) -> Any:
        return functools.reduce(np.maximum, args)

    return {
        "exp": np.exp,
        "log": np.log,
        "log10": np.log10,
        "sqrt": np.sqrt,
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "tanh": np.tanh,
        "abs": np.abs,
        "min": smallest,
        "max": largest,
        "pow": np.power,
        "floor": np.floor,
        "ceil": np.ceil,
    }


def compile_expression(
    expression: str, variables: Sequence[str] = ("x",), *, arrays: bool = False
) -> Callable[..., Any]:
    """Return `f(**values) -> float`; non-finite results and domain errors come back as NaN.

    With `arrays=True` the expression is compiled against NumPy instead: the variables may be arrays (and
    scalars, which broadcast), the result is a float array of the broadcast shape, and every element that a
    scalar evaluation would return as NaN (a domain error, a division by zero, an overflow) is NaN. A surface
    grid or a sampled image evaluates in one call this way, and agrees element-wise with the scalar form.
    """
    tree = validate_expression(expression, variables)
    code = compile(tree, "<expression>", "eval")
    if arrays:
        return _array_evaluator(code, variables)
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


def _array_evaluator(code: Any, variables: Sequence[str]) -> Callable[..., Any]:
    import numpy as np

    namespace = {"__builtins__": {}, **_array_namespace(), **ALLOWED_CONSTANTS}

    def evaluate(**values: Any) -> Any:
        missing = set(variables) - set(values)
        if missing:
            raise TypeError(f"missing variable(s) {sorted(missing)}")
        arrays = {name: np.asarray(value, dtype=float) for name, value in values.items()}
        shape = np.broadcast_shapes(*(a.shape for a in arrays.values())) if arrays else ()
        with np.errstate(all="ignore"):
            result = np.asarray(eval(code, namespace, arrays), dtype=float)
        result = np.array(np.broadcast_to(result, shape), dtype=float)
        result[~np.isfinite(result)] = np.nan
        return result

    return evaluate


def sample(expression: str, xs: Iterable[float]) -> list[float]:
    function = compile_expression(expression, ("x",))
    return [function(x=x) for x in xs]
