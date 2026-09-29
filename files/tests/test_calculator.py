import pytest

from calculator import CalculatorError, evaluate, find_calculations, format_number, math_context


@pytest.mark.parametrize("expression,expected", [
    ("1234*5678", 7006652), ("(3+4)^2 / 7", 7.0), ("2**10", 1024), ("2^3^2", 512), ("-5+3", -2),
    ("17 // 5", 3), ("17 % 5", 2), ("sqrt(144)", 12.0), ("abs(-3)", 3), ("round(2.675, 2)", 2.67),
    ("factorial(5)", 120), ("log10(1000)", 3.0), ("1,234,567 * 3", 3703701), ("12 x 12", 144),
    ("6 × 7 ÷ 2", 21.0), ("2.5e3 + 1", 2501.0),
])
def test_evaluate(expression, expected):
    assert evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo hi')", "open('x')", "a + 1", "2 +", "(1).__class__", "[1, 2]",
    "lambda: 1", "sqrt(x=4)", "9**9**9", "10**100000", "factorial(1000)", "1/0", "sqrt(-1)", "1e308*10",
    "True + 1", "'a' * 3", "x" * 300,
])
def test_evaluate_rejects_unsafe_or_bad_input(expression):
    with pytest.raises(CalculatorError):
        evaluate(expression)


def test_format_number():
    assert format_number(7.0) == "7"
    assert format_number(0.1 + 0.2) == "0.3"
    assert format_number(2 ** 0.5) == "1.41421356237"
    assert format_number(10 ** 30) == "1" + "0" * 30
    assert format_number(1e20) == "1e+20"


@pytest.mark.parametrize("message,expected", [
    ("What is 1234*5678?", [("1234*5678", "7006652")]),
    ("what is 15% of 240", [("15% of 240", "36")]),
    ("what is 12 x 12", [("12*12", "144")]),
    ("what is 5 times 6?", [("5 * 6", "30")]),
    ("what is 10 divided by 4", [("10 / 4", "2.5")]),
    ("2 to the power of 10", [("2 ** 10", "1024")]),
    ("what is 2 plus 2 times 3", [("2 + 2 * 3", "8")]),
    ("what is 100-37?", [("100-37", "63")]),
    ("round(pi*2, 3) is what?", [("round(pi*2, 3)", "6.283")]),
    ("what is 5, 6*2", [("6*2", "12")]),
    ("what is 10/0?", [("10/0", "undefined (division by zero)")]),
    ("what is 9**9**9", [("9**9**9", "undefined (number too large)")]),
    ("what is 1e308*10", [("1e308*10", "undefined (number too large)")]),
    # not calculations
    ("I have 2 cats and 3 dogs", []), ("we need 5-10 people", []), ("My birthday is 2024-12-31", []),
    ("Python 3.13 is out", []), ("call 555-1234", []), ("x1*2", []), ("mp3 player", []),
    ("Write a function (x*2) in python", []), ("I have 2, 3 and 4 apples", []),
])
def test_find_calculations(message, expected):
    assert find_calculations(message) == expected


def test_math_context():
    assert math_context("hello there") == ""
    context = math_context("what is 6*7?")
    assert context.splitlines() == [
        "🧮 Calculator results (exact; use these instead of doing the arithmetic yourself):", "6*7 = 42"]


# ---------------- equations

from calculator import solve_equation  # noqa: E402


@pytest.mark.parametrize("equation,answer", [
    ("x^2 - 5x + 6 = 0", "x = 2 or x = 3"),
    ("2x^2 + 3x - 2 = 0", "x = -2 or x = 1/2 (0.5)"),
    ("x² - 4 = 0", "x = -2 or x = 2"),
    ("(x-2)(x-3) = 0", "x = 2 or x = 3"),
    ("x(x - 4) = 0", "x = 0 or x = 4"),
    ("t^2 = 9", "t = -3 or t = 3"),
    ("0.5x^2 - x = 0", "x = 0 or x = 2"),
    ("4x^2 + 4x + 1 = 0", "x = -1/2 (-0.5) (one repeated root)"),
    ("x^2 + 2x + 5 = 0", "x = -1 ± 2i (no real solutions; complex roots)"),
    ("x^2 - 2 = 0", "x = (± √8) / 2 ≈ -1.41421 or 1.41421"),
    ("x^2 + x - 1 = 0", "x = (-1 ± √5) / 2 ≈ -1.61803 or 0.618034"),
    ("3x + 5 = 20", "x = 5"),
    ("x/2 + 1 = 4", "x = 6"),
    ("x/3 = 1", "x = 3"),
    ("2x = 1", "x = 1/2 (0.5)"),
    ("3x = 1", "x = 1/3 (≈ 0.333333)"),
    ("2(x+1) = 2x + 2", "true for every x"),
    ("x + 1 = x + 2", "no solution"),
    ("x^2 - 5x + 6", "x = 2 or x = 3"),  # no '=' means '= 0'
])
def test_solve_equation(equation, answer):
    assert solve_equation(equation).startswith(answer)


def test_quadratic_shows_working():
    assert "(a = 1, b = -5, c = 6; discriminant b²-4ac = 1)" in solve_equation("x^2 - 5x + 6 = 0")


@pytest.mark.parametrize("equation", [
    "x^3 = 8", "x*y = 2", "y = 2x + 1", "x = 1 = 2", "x^x = 4", "x^0.5 = 2", "x/(x+1) = 2", "x/0 = 1",
    "__import__('os') = 1", "(x+1)**9 = 0", "2 = 2", "x" + "+1" * 200 + " = 0",
])
def test_solve_equation_rejects(equation):
    with pytest.raises(CalculatorError):
        solve_equation(equation)


@pytest.mark.parametrize("message,expected", [
    ("solve 2x + 3 = 11 for x", [("Solve 2x + 3 = 11", "x = 4")]),
    ("I think x+1 = 3", [("Solve x+1 = 3", "x = 2")]),
    ("what are the roots of x^2 - 5x + 6?", [("Solve x^2 - 5x + 6 = 0", "x = 2 or x = 3")]),
    ("solve x² - 4", [("Solve x² - 4 = 0", "x = -2 or x = 2")]),
    ("what is 2+2 and solve x^2=16", [("Solve x^2=16", "x = -4 or x = 4"), ("2+2", "4")]),
    ("the score was 3 = 3", []), ("x >= 3", []), ("e = mc^2", []), ("y = 2x + 1", []),
])
def test_find_equations_in_messages(message, expected):
    found = find_calculations(message)
    assert [(e, r[:len(want)]) for (e, r), (_, want) in zip(found, expected)] == expected
    assert len(found) == len(expected)


def test_math_context_for_equations():
    context = math_context("solve x^2 - 5x + 6 = 0")
    assert "Solve x^2 - 5x + 6 = 0: x = 2 or x = 3" in context
