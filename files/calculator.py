"""Exact arithmetic for the chat.

Small local models often get arithmetic wrong, so the app finds calculations in the
user's message, works them out itself and gives the model the exact answers.
Expressions are evaluated from a parsed syntax tree (never with eval), and only
numbers, + - * / // % ** ^, brackets and a few maths functions are allowed.
"""
import ast
import math
import operator
import re
from fractions import Fraction

FUNCTIONS = {
    'sqrt': math.sqrt, 'abs': abs, 'round': round, 'floor': math.floor, 'ceil': math.ceil,
    'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'exp': math.exp,
    'log': math.log, 'log10': math.log10, 'log2': math.log2, 'factorial': math.factorial,
}
CONSTANTS = {'pi': math.pi}
OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
MAX_RESULT_BITS = 10_000   # keeps 9**9**9-style inputs from freezing the server
MAX_FACTORIAL = 500
MAX_EXPRESSION_LENGTH = 200

# Words that show the user wants a calculation, so "5-3" counts but "5-10 people" doesn't
MATH_INTENT = re.compile(
    r"\b(calculate|compute|evaluate|what(?:'s| is)|how much|equals?|sum|total|times|multiply|"
    r"divided?|minus|plus|math|solve)\b|=\s*\??\s*$|\?\s*$", re.IGNORECASE)
FUNCTION_NAMES = "|".join(sorted(FUNCTIONS, key=len, reverse=True))
NUMBER_WITH_EXPONENT = r"\d[\d.]*[eE][+-]?\d+"
# Runs of characters that can make up a calculation (not starting inside a word)
CANDIDATE = re.compile(
    rf"(?<![A-Za-z_])(?:{NUMBER_WITH_EXPONENT}|\b(?:{FUNCTION_NAMES}|pi)\b|[\d.+\-*/^%()×÷ ,])+")
WORD_OPERATORS = [(r"multiplied by|times", "*"), (r"divided by", "/"), (r"plus", "+"),
                  (r"minus", "-"), (r"to the power of", "**")]
PERCENT_OF = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s+(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
DATE_LIKE = re.compile(r"^\s*\d{1,4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,4}\s*$")


# ---- equations (linear and quadratic, one variable)
# A run of equation characters: numbers, single letters (not inside words), operators
EQ_SIDE = r"(?:\d+(?:\.\d+)?|(?<![A-Za-z])[A-Za-z](?![A-Za-z])|[-+*/^()²³×÷−\s])+"
EQUATION = re.compile(rf"({EQ_SIDE})=({EQ_SIDE})")
SOLVE_INTENT = re.compile(r"\b(solve|roots?|zeros?|solutions?)\b", re.IGNORECASE)
MAX_POLY_DEGREE = 4  # while expanding; the final equation must be degree 1 or 2


class CalculatorError(ValueError):
    """The expression isn't a supported calculation."""


def _check_size(value):
    if isinstance(value, int) and value.bit_length() > MAX_RESULT_BITS:
        raise CalculatorError("number too large")
    if isinstance(value, float) and not math.isfinite(value):
        raise CalculatorError("number too large")
    return value


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in CONSTANTS:
        return CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and isinstance(left, int) and isinstance(right, int):
            if abs(left) > 1 and right > 0 and left.bit_length() * right > MAX_RESULT_BITS:
                raise CalculatorError("number too large")
        return _check_size(OPERATORS[type(node.op)](left, right))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS and not node.keywords):
        args = [_eval(arg) for arg in node.args]
        if node.func.id == 'factorial' and (not args or not isinstance(args[0], int) or args[0] > MAX_FACTORIAL):
            raise CalculatorError("factorial needs a whole number up to 500")
        return _check_size(FUNCTIONS[node.func.id](*args))
    raise CalculatorError("not a supported calculation")


def evaluate(expression):
    """Work out an arithmetic expression like '2*(3+4)^2' or 'sqrt(16) / 3'.

    Raises:
        CalculatorError: If it isn't a supported calculation or can't be worked out
    """
    text = (expression.replace('^', '**').replace('×', '*').replace('÷', '/'))
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)            # 1,234,567 -> 1234567
    text = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", text)      # 12 x 12 -> 12*12
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError("expression too long")
    try:
        return _eval(ast.parse(text.strip(), mode='eval'))
    except ZeroDivisionError:
        raise CalculatorError("division by zero")
    except (OverflowError, MemoryError):
        raise CalculatorError("number too large")
    except (SyntaxError, TypeError, ValueError, RecursionError) as e:
        if isinstance(e, CalculatorError):
            raise
        raise CalculatorError(f"can't work out '{expression.strip()}'")


def _normalize_equation(text):
    """'2x² + 3(x-1) = 0' -> '2*x**2 + 3*(x-1) = 0'"""
    text = (text.replace('²', '**2').replace('³', '**3').replace('^', '**').replace('×', '*')
            .replace('÷', '/').replace('−', '-'))
    text = re.sub(r"(\d)\s*([A-Za-z(])", r"\1*\2", text)       # 2x, 3(x+1)
    text = re.sub(r"([A-Za-z)])\s*\(", r"\1*(", text)             # x(x+1), (x-2)(x-3)
    text = re.sub(r"\)\s*([A-Za-z\d])", r")*\1", text)            # (x+1)x
    return text


def _poly(node, var):
    """Expand an expression into {power: coefficient} for one variable."""
    if isinstance(node, ast.Expression):
        return _poly(node.body, var)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return {0: Fraction(str(node.value))}
    if isinstance(node, ast.Name) and node.id == var:
        return {1: Fraction(1)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _poly(node.operand, var)
        return {k: -v for k, v in inner.items()} if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.BinOp):
        left, right = _poly(node.left, var), _poly(node.right, var)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            sign = 1 if isinstance(node.op, ast.Add) else -1
            result = dict(left)
            for k, v in right.items():
                result[k] = result.get(k, 0) + sign * v
            return result
        if isinstance(node.op, ast.Mult):
            result = {}
            for k1, v1 in left.items():
                for k2, v2 in right.items():
                    if k1 + k2 > MAX_POLY_DEGREE:
                        raise CalculatorError("only equations up to x² can be solved")
                    result[k1 + k2] = result.get(k1 + k2, 0) + v1 * v2
            return result
        if isinstance(node.op, ast.Div):
            if set(right) - {0} or not right.get(0):
                raise CalculatorError("can only divide by a non-zero number")
            return {k: v / right[0] for k, v in left.items()}
        if isinstance(node.op, ast.Pow):
            exponent = right.get(0) if not set(right) - {0} else None
            if exponent is None or exponent.denominator != 1 or not 0 <= exponent <= MAX_POLY_DEGREE:
                raise CalculatorError("powers must be small whole numbers")
            result = {0: Fraction(1)}
            for _ in range(int(exponent)):
                result = _poly(ast.BinOp(left=_Const(result), op=ast.Mult(), right=_Const(left)), var)
            return result
    if isinstance(node, _Const):
        return node.poly
    raise CalculatorError("not a supported equation")


class _Const(ast.AST):
    """An already-expanded polynomial inside a syntax tree (used for powers)."""
    def __init__(self, poly):
        super().__init__()
        self.poly = poly


def _fmt(value):
    """Exact fractions stay exact: 2, -3/2 (-1.5), 1/3 (≈ 0.333333)."""
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    decimal = float(value)
    exact = f"{value.numerator}/{value.denominator}"
    return f"{exact} ({decimal:g})" if len(f"{decimal:g}") <= 8 and float(f"{decimal:g}") == decimal else f"{exact} (≈ {decimal:.6g})"


def _exact_sqrt(value):
    """sqrt of a non-negative Fraction if it is rational, else None."""
    num, den = math.isqrt(value.numerator), math.isqrt(value.denominator)
    return Fraction(num, den) if num * num == value.numerator and den * den == value.denominator else None


def solve_equation(equation):
    """Solve a linear or quadratic equation in one letter, e.g. '2x^2 + 3x - 2 = 0'.

    Without '=' the expression is set equal to 0 ("roots of x^2 - 4").

    Returns:
        str: The solutions, e.g. "x = -2 or x = 1/2 (0.5)"

    Raises:
        CalculatorError: If it isn't a supported equation
    """
    text = _normalize_equation(equation)
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError("equation too long")
    variables = set(re.findall(r"[A-Za-z]+", text))
    if len(variables) != 1 or len(next(iter(variables))) != 1:
        raise CalculatorError("needs exactly one single-letter unknown, like x")
    var = variables.pop()
    sides = text.split('=')
    if len(sides) > 2:
        raise CalculatorError("more than one '='")
    left, right = (sides + ['0'])[:2]
    try:
        poly = _poly(ast.parse(f"({left}) - ({right})", mode='eval'), var)
    except (SyntaxError, RecursionError):
        raise CalculatorError(f"can't read the equation '{equation.strip()}'")
    except ZeroDivisionError:
        raise CalculatorError("division by zero")
    poly = {k: v for k, v in poly.items() if v != 0}
    degree = max(poly, default=0)
    a, b, c = poly.get(2, Fraction(0)), poly.get(1, Fraction(0)), poly.get(0, Fraction(0))

    if degree > 2:
        raise CalculatorError("only equations up to x² can be solved")
    if degree == 0:
        return f"true for every {var}" if c == 0 else "no solution"
    if degree == 1:
        return f"{var} = {_fmt(-c / b)}"

    discriminant = b * b - 4 * a * c
    steps = f"(a = {_fmt(a)}, b = {_fmt(b)}, c = {_fmt(c)}; discriminant b²-4ac = {_fmt(discriminant)})"
    if discriminant == 0:
        return f"{var} = {_fmt(-b / (2 * a))} (one repeated root) {steps}"
    root = _exact_sqrt(abs(discriminant))
    if discriminant > 0:
        if root is not None:
            x1, x2 = sorted([(-b - root) / (2 * a), (-b + root) / (2 * a)])
            return f"{var} = {_fmt(x1)} or {var} = {_fmt(x2)} {steps}"
        d = math.sqrt(discriminant)
        x1, x2 = sorted([(-float(b) - d) / (2 * float(a)), (-float(b) + d) / (2 * float(a))])
        top = f"± √{_fmt(discriminant)}" if b == 0 else f"{_fmt(-b)} ± √{_fmt(discriminant)}"
        return f"{var} = ({top}) / {_fmt(2 * a)} ≈ {x1:.6g} or {x2:.6g} {steps}"
    real = -b / (2 * a)
    imaginary = abs(math.sqrt(-discriminant) / (2 * float(a)))
    return (f"{var} = {_fmt(real)} ± {imaginary:.6g}i (no real solutions; complex roots) {steps}")


def find_equations(message):
    """Find equations to solve in a message.

    Returns:
        tuple: (list of (equation, solution text), message with the equations removed)
    """
    found, spans = [], []
    for match in EQUATION.finditer(message):
        equation = match.group(0).strip()
        if not re.search(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", equation) or not re.search(r"\d", equation):
            continue
        try:
            found.append((equation, solve_equation(equation)))
            spans.append(match.span())
        except CalculatorError:
            continue
    if not found and SOLVE_INTENT.search(message):
        # "roots of x^2 - 5x + 6": the longest run containing a letter and a power/operator
        runs = [m for m in re.finditer(EQ_SIDE, message)
                if re.search(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", m.group(0))
                and re.search(r"\d", m.group(0)) and re.search(r"[-+*^²]", m.group(0))]
        for run in sorted(runs, key=lambda m: len(m.group(0)), reverse=True)[:1]:
            try:
                found.append((f"{run.group(0).strip()} = 0", solve_equation(run.group(0))))
                spans.append(run.span())
            except CalculatorError:
                pass
    for start, end in reversed(spans):
        message = message[:start] + " " + message[end:]
    return found, message


def format_number(value):
    """Integers exactly; other numbers to 12 significant digits."""
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.12g}"
    return str(value)


def find_calculations(message):
    """Find and work out the calculations in a chat message.

    Returns:
        list: (expression, result text) pairs, in the order they appear
    """
    results = []
    has_intent = bool(MATH_INTENT.search(message))

    # Equations first ("solve 2x + 3 = 11"), then plain arithmetic in what's left
    equations, message = find_equations(message)
    results += [(f"Solve {equation}", solution) for equation, solution in equations]

    # "15% of 240"
    for match in PERCENT_OF.finditer(message):
        number = float(match.group(2).replace(',', ''))
        value = float(match.group(1)) / 100 * number
        results.append((match.group(0), format_number(value)))
    message = PERCENT_OF.sub(" ", message)
    message = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", message)  # "12 x 12" before scanning
    for words, symbol in WORD_OPERATORS:                          # "5 times 6" -> "5 * 6"
        message = re.sub(rf"(?<=[\d)])\s+(?:{words})\s+(?=[\d(-])", f" {symbol} ", message, flags=re.IGNORECASE)

    for match in CANDIDATE.finditer(message):
        candidate = match.group(0).strip(" .,")
        # trim unmatched brackets left over from the surrounding sentence
        while candidate.count('(') > candidate.count(')') and candidate.startswith('('):
            candidate = candidate[1:].strip()
        while candidate.count(')') > candidate.count('(') and candidate.endswith(')'):
            candidate = candidate[:-1].strip()
        # "round(2.5, 1)" needs its comma; in "2, 3*4" the comma separates two things
        parts = [candidate] if "(" in candidate else [p.strip() for p in re.split(r",(?!\d{3})", candidate)]
        for part in parts:
            if not re.search(r"\d", part) or DATE_LIKE.match(part):
                continue
            # an operator BETWEEN two values ("+ 1" on its own is not a calculation)
            has_operator = (re.search(r"[\d)i]\s*(?:\*\*|//|[+*/^%×÷])\s*[-+]?\s*[\d(.a-z]", part)
                            or re.search(rf"\b(?:{FUNCTION_NAMES})\s*\(", part))
            only_minus = re.search(r"\d\s*-\s*[\d(]", part)
            if not has_operator and not (only_minus and has_intent):
                continue  # plain numbers, or "5-10 people"
            try:
                value = evaluate(part)
            except CalculatorError as e:
                if "division by zero" in str(e) or "too large" in str(e):
                    results.append((part, f"undefined ({e})"))
                continue
            if isinstance(value, tuple):
                continue
            results.append((part, format_number(value)))
    return results


def math_context(message):
    """Calculator results for the prompt, or "" if the message has no calculations."""
    calculations = find_calculations(message)
    if not calculations:
        return ""
    lines = ["🧮 Calculator results (exact; use these instead of doing the arithmetic yourself):"]
    lines += [f"{expression}: {result}" if expression.startswith("Solve ") else f"{expression} = {result}"
              for expression, result in calculations]
    return "\n".join(lines)
