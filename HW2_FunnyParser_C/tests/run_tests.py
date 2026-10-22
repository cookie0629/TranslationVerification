"""Structural AST snapshots and positioned negative diagnostics."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PARSER = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "funny_parser.exe").resolve()


def invoke(name):
    return subprocess.run(
        [str(PARSER), str(ROOT / name)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


for name in ("contract", "precedence", "array_tuple"):
    result = invoke(name + ".funny")
    assert result.returncode == 0, (name, result.stderr)
    actual = json.loads(result.stdout)
    expected = json.loads((ROOT / "expected" / (name + ".json")).read_text(encoding="utf-8"))
    assert actual == expected, name + ": AST differs from reference"
    print("PASS", name, "AST snapshot")

negative = {
    "unclosed": "1:40: error: expected ')'",
    "unclosed_index": "1:39: error: expected ']'",
    "multiline_error": "2:13: error: expected ')'",
    "extra": "1:31: error: expected statement, found SEMICOLON ';'",
    "operator": "1:26: error: expected '='",
    "lexical": "1:28: error: integer with leading zero",
    "empty": "1:1: error: empty program",
}
for name, fragment in negative.items():
    result = invoke(name + ".funny")
    assert result.returncode == 1, (name, result.returncode)
    assert fragment in result.stderr, (name, result.stderr)
    assert json.loads(result.stdout)["kind"] == "Module", name
    if name == "operator":
        statements = json.loads(result.stdout)["children"][0]["children"][5]["children"]
        assert statements[-1]["kind"] == "Assign" and statements[-1]["children"][1]["value"] == "2"
    print("PASS", name, "positioned error and termination")

print("10/10 tests passed")
