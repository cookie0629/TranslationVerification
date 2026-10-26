"""End-to-end parser + type checker tests with positioned diagnostic references."""

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
CHECKER = ROOT.parent / "checker.py"


def run(source):
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", str(ROOT / source)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode in (0, 1), (source, proc.stderr)
    payload = json.loads(proc.stdout)
    return proc.returncode, payload["ast"], payload["diagnostics"]


def nodes(tree):
    yield tree
    for item in tree["children"]:
        yield from nodes(item)


for source in ("valid.funny", "inference.funny", "forward.funny", "quantifier.funny"):
    code, ast, errors = run(source)
    assert code == 0 and not errors, (source, errors)
    assert all("type" in n for n in nodes(ast) if n["kind"] in
               ("Var", "Int", "Bool", "Unary", "Binary", "Call", "Index", "Set", "Quantifier"))
    print("PASS", source)

_, ast, _ = run("valid.funny")
main = next(n for n in ast["children"] if n.get("value") == "main")
uses = main["children"][4]["children"]
assert uses[0]["type"] == "int" and uses[0]["inferred"] is True
assert next(n for n in nodes(main) if n["kind"] == "Set")["type"] == "int[]"
assert next(n for n in nodes(main) if n["kind"] == "Call" and n["value"] == "pair")["type"] == "func(int)->(int,int)"
_, ast, _ = run("inference.funny")
uses = ast["children"][0]["children"][4]["children"]
assert [(n["type"], n["inferred"]) for n in uses] == [("int", True), ("int[]", True)]

references = {
    "errors.funny": [
        (10, 1, "duplicate global declaration 'bad'"),
        (1, 13, "duplicate declaration 'a'"),
        (1, 51, "duplicate declaration 'tmp'"),
        (2, 3, "read-only parameter 'a'"),
        (3, 7, "unknown variable 'missing'"),
        (4, 3, "expected int, got bool"),
        (5, 14, "expected int[], got int"),
        (6, 7, "unknown function or formula 'nofunc'"),
        (1, 61, "cannot infer type of local 'inferred'"),
    ],
    "bad_calls.funny": [
        (3, 10, "expects 1 argument(s), got 2"),
        (4, 7, "2 results; single value required"),
        (5, 3, "2 target(s), call returns 1 value(s)"),
        (6, 10, "assert: expected bool, got int"),
    ],
    "bad_inference.funny": [
        (2, 7, "used before its type is inferred"),
        (4, 3, "expected int, got bool"),
        (1, 30, "cannot infer type of local 'y'"),
    ],
    "array_errors.funny": [
        (2, 3, "read-only parameter 'a'"),
        (2, 5, "array index: expected int, got bool"),
        (3, 9, "array index: expected int, got bool"),
    ],
    "syntax_error.funny": [(1, 34, "expected ')'")],
}

for source, expected in references.items():
    code, ast, errors = run(source)
    assert code == 1 and ast["kind"] == "Module", (source, code, errors)
    for line, column, text in expected:
        assert any(d["line"] == line and d["column"] == column and text in d["message"] for d in errors), (source, expected, errors)
    assert all(isinstance(d["line"], int) and isinstance(d["column"], int)
               and d["category"] and d["message"] for d in errors)
    assert errors == sorted(errors, key=lambda d: (d["line"], d["column"]))
    if source == "syntax_error.funny":
        assert errors[0]["category"] == "SyntaxError"
    if source == "bad_calls.funny":
        assert any(d["category"] == "ArityError" for d in errors)
    print("PASS", source)

print("9/9 test programs passed")

for name, expected_code, heading in (
    ("valid.funny", 0, "Type check: OK"),
    ("errors.funny", 1, "Type check: FAILED (9 error(s))"),
    ("syntax_error.funny", 1, "Type check: FAILED (1 error(s))"),
):
    proc = subprocess.run(
        [sys.executable, str(CHECKER), str(ROOT / name)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == expected_code, (name, proc.returncode, proc.stderr)
    output = proc.stdout if expected_code == 0 else proc.stderr
    assert output.startswith(heading), (name, output)
    if expected_code == 0:
        assert proc.stderr == "" and "Annotated AST:" in output and "- Module [1:1]" in output
    else:
        assert proc.stdout == "" and "Use --tree" in output and "- Module [1:1]" not in output
    if name == "errors.funny":
        assert "[NameError] duplicate declaration 'a'" in output
        assert "[TypeError] assignment to 'tmp': expected int, got bool" in output
        assert "[AssignmentError] cannot assign to read-only parameter 'a'" in output
        assert "[InferenceError] cannot infer type of local 'inferred'" in output
        assert output.index("1:13 [NameError]") < output.index("10:1 [NameError]")
    if name == "syntax_error.funny":
        assert "1:34 [SyntaxError] expected ')'" in output
    print("PASS readable terminal output", name)

tree = subprocess.run(
    [sys.executable, str(CHECKER), "--tree", str(ROOT / "errors.funny")],
    capture_output=True, text=True, timeout=30,
)
assert tree.returncode == 1 and tree.stdout == ""
assert tree.stderr.index("Diagnostics (source order):") < tree.stderr.index("Annotated AST")
assert "- Module [1:1]" in tree.stderr and "Var missing : <error>" in tree.stderr
print("PASS detailed error tree")

lexical = subprocess.run(
    [sys.executable, str(CHECKER), "--json"],
    input="bad() returns r:int { r = 01; }",
    capture_output=True, text=True, timeout=30,
)
assert lexical.returncode == 1
lexical_diagnostics = json.loads(lexical.stdout)["diagnostics"]
assert any(d["category"] == "LexicalError" and "leading zero" in d["message"]
           for d in lexical_diagnostics)
assert "[LexicalError]" in lexical.stderr
print("PASS lexical error notification")
