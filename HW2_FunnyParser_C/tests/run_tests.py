"""Structural AST snapshots and positioned negative diagnostics."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PARSER = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / "funny_parser.exe").resolve()


def invoke(name, json_output=True):
    return subprocess.run(
        [str(PARSER), *(["--json"] if json_output else []), str(ROOT / name)],
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

identifiers = invoke("identifiers.funny")
assert identifiers.returncode == 0, identifiers.stderr
assert [n["value"] for n in json.loads(identifiers.stdout)["children"]] == ["name_1", "requiresx"]
print("PASS identifiers, keyword boundaries, and documented underscore extension")

negative = {
    "unclosed": "1:40: error: expected ')'",
    "multiline_error": "2:13: error: expected ')'",
    "extra": "1:31: error: expected statement, found ';' (SEMICOLON)",
    "operator": "1:26: error: expected '='",
    "lexical": "1:28: error: integer with leading zero",
    "empty": "1:1: error: empty program",
    "recover_top_level": "1:1: error: expected function or formula name, found 'function' (KW_FUNCTION)",
}
for name, fragment in negative.items():
    result = invoke(name + ".funny")
    assert result.returncode == 1, (name, result.returncode)
    assert fragment in result.stderr, (name, result.stderr)
    assert json.loads(result.stdout)["kind"] == "Module", name
    if name == "operator":
        statements = json.loads(result.stdout)["children"][0]["children"][5]["children"]
        assert statements[-1]["kind"] == "Assign" and statements[-1]["children"][1]["value"] == "2"
    if name == "recover_top_level":
        assert [n["value"] for n in json.loads(result.stdout)["children"]] == ["good"]
        assert len(result.stderr.splitlines()) == 1, result.stderr
    print("PASS", name, "positioned error and termination")

print("11/11 parser programs passed")

human = invoke("unclosed.funny", json_output=False)
assert human.returncode == 1 and human.stderr == ""
assert human.stdout.startswith("Diagnostics (1):\n1:40: error: expected ')'")
assert "\nPartial AST:\n- Module [1:1]\n" in human.stdout
assert "  - Function bad [1:1]" in human.stdout
assert "    - body: Block [1:28]" in human.stdout
assert human.stdout.index("Diagnostics (1):") < human.stdout.index("Partial AST:")
print("PASS readable terminal output and diagnostic order")
