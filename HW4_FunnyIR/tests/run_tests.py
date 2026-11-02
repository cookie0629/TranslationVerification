"""End-to-end HW2 -> HW3 -> HW4 tests and IR execution equivalence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
HW2 = REPOSITORY / "HW2_FunnyParser_C"
HW3 = REPOSITORY / "HW3_FunnyTypes" / "checker.py"
sys.path.insert(0, str(ROOT))
from runtime import IRRuntimeError, execute  # noqa: E402


def invoke(parser: Path, source: Path, *options: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "hw4.py"), "--json", "--parser", str(parser),
         *options, str(source)],
        capture_output=True, text=True, timeout=30,
    )


with TemporaryDirectory() as temporary:
    temporary_path = Path(temporary)
    parser = temporary_path / ("funny_parser.exe" if sys.platform == "win32" else "funny_parser")
    build = subprocess.run(
        ["gcc", "-std=c99", "-O2", "-Wall", "-Wextra", "-pedantic",
         "parser.c", "-o", str(parser)], cwd=HW2,
        capture_output=True, text=True, timeout=60,
    )
    assert build.returncode == 0, build.stderr

    cases = {
        "arithmetic.funny": ("calc", [([0], [6]), ([5], [11]), ([-2], [4]),
                                          ([2147483647], [-2147483643])]),
        "control.funny": ("sum_to", [([0], [0]), ([2], [1]), ([5], [5])]),
        "arrays_calls.funny": ("main", [([[4, 7]], [[5, 7], 8]),
                                               ([[0, 3, 9]], [[1, 3, 9], 5])]),
        "short_circuit.funny": ("guard", [([0], [0]), ([2], [1]),
                                                ([10], [0]), ([-1], [0])]),
        "assertions.funny": ("safe", [([0], [1]), ([5], [6])]),
        "logic.funny": ("logic", [([0], [2]), ([2], [2]), ([10], [1])]),
    }
    for file_name, (function_name, examples) in cases.items():
        result = invoke(parser, ROOT / "examples" / file_name)
        assert result.returncode == 0, (file_name, result.stderr)
        program = json.loads(result.stdout)
        assert program["version"] == 1 and program["functions"]
        for arguments, expected in examples:
            original = json.loads(json.dumps(arguments))
            before = execute(program, function_name, arguments, optimized=False)
            after = execute(program, function_name, arguments, optimized=True)
            assert before == after == expected, (file_name, arguments, before, after, expected)
            assert arguments == original, "array parameters must not be modified"
        for function in program["functions"]:
            original_ir, optimized_ir = function["before"], function["after"]
            assert optimized_ir["metrics"]["instructions"] <= original_ir["metrics"]["instructions"]
            labels = {block["label"] for block in optimized_ir["blocks"]}
            for block in optimized_ir["blocks"]:
                assert block["terminator"] and set(block["successors"]) <= labels
                for target in block["successors"]:
                    successor = next(item for item in optimized_ir["blocks"] if item["label"] == target)
                    assert block["label"] in successor["predecessors"]
            graph = optimized_ir["interference"]["edges"]
            colors = optimized_ir["interference"]["colors"]
            for temporary, neighbors in graph.items():
                for neighbor in neighbors:
                    assert temporary in graph[neighbor]
                    assert colors[temporary] != colors[neighbor]
            assert optimized_ir["metrics"]["colors"] == len(set(colors.values()))
        print("PASS equivalence, CFG, coloring:", file_name)

    arithmetic = invoke(parser, ROOT / "examples" / "arithmetic.funny")
    program = json.loads(arithmetic.stdout)
    metrics = program["functions"][0]["metrics"]
    assert metrics["after"]["instructions"] < metrics["before"]["instructions"]
    assert metrics["after"]["temporaries"] < metrics["before"]["temporaries"]
    assert metrics["after"]["colors"] <= metrics["before"]["colors"]

    no_opt = json.loads(invoke(parser, ROOT / "examples" / "arithmetic.funny", "--no-opt").stdout)
    assert no_opt["functions"][0]["before"]["blocks"] == no_opt["functions"][0]["after"]["blocks"]
    assert no_opt["functions"][0]["metrics"]["before"] == no_opt["functions"][0]["metrics"]["after"]
    no_const = json.loads(invoke(parser, ROOT / "examples" / "arithmetic.funny", "--no-const").stdout)
    assert any(instruction["op"] == "binary" and instruction["operator"] == "*"
               for block in no_const["functions"][0]["after"]["blocks"]
               for instruction in block["instructions"])
    no_algebra = json.loads(invoke(parser, ROOT / "examples" / "arithmetic.funny", "--no-algebra").stdout)
    assert any(instruction["op"] == "binary" and instruction["operator"] == "+"
               and instruction["left"] == {"ref": "a"}
               for block in no_algebra["functions"][0]["after"]["blocks"]
               for instruction in block["instructions"])
    no_dce = json.loads(invoke(parser, ROOT / "examples" / "arithmetic.funny", "--no-dce").stdout)
    assert any(instruction.get("dest") == "unused"
               for block in no_dce["functions"][0]["after"]["blocks"]
               for instruction in block["instructions"])
    print("PASS independent optimization flags and metrics")

    spec_result = invoke(parser, REPOSITORY / "HW3_FunnyTypes" / "tests" / "valid.funny")
    assert spec_result.returncode == 0, spec_result.stderr
    specification = json.loads(spec_result.stdout)
    assert [node["value"] for node in specification["formulas"]] == ["positive"]
    assert any(instruction["op"] == "spec_assert"
               for function in specification["functions"]
               for block in function["after"]["blocks"]
               for instruction in block["instructions"])
    main_spec = next(function for function in specification["functions"] if function["name"] == "main")
    assert main_spec["after"]["contracts"]["requires"] is not None
    print("PASS contract and formula preservation")

    spec_path = temporary_path / "spec_liveness.funny"
    spec_path.write_text(
        "nonnegative(x: int) => x >= 0\n"
        "keep(x: int) returns r: int uses tmp: int { "
        "tmp = x; r = 0; assert nonnegative(tmp); }\n",
        encoding="ascii",
    )
    spec_run = invoke(parser, spec_path)
    assert spec_run.returncode == 0, spec_run.stderr
    spec_program = json.loads(spec_run.stdout)
    keep = next(function for function in spec_program["functions"] if function["name"] == "keep")
    assert any(instruction.get("dest") == "tmp"
               for block in keep["after"]["blocks"] for instruction in block["instructions"])
    assert execute(spec_program, "keep", [2]) == [0]
    assert execute(spec_program, "keep", [2], optimized=True) == [0]
    print("PASS DCE preserves values used by specification predicates")

    bad = invoke(parser, ROOT / "examples" / "type_error.funny")
    assert bad.returncode == 1 and bad.stdout == "" and "[TypeError]" in bad.stderr
    print("PASS HW3 error stops IR generation")

    annotated = subprocess.run(
        [sys.executable, str(HW3), "--json", "--parser", str(parser),
         str(ROOT / "examples" / "arithmetic.funny")],
        capture_output=True, text=True, timeout=30,
    )
    assert annotated.returncode == 0, annotated.stderr
    ast_path = temporary_path / "annotated.json"
    ast_path.write_text(annotated.stdout, encoding="utf-8")
    direct = subprocess.run(
        [sys.executable, str(ROOT / "hw4.py"), "--json", "--ast", str(ast_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert direct.returncode == 0, direct.stderr
    assert json.loads(direct.stdout) == program
    print("PASS annotated AST input API")

    dot_directory = temporary_path / "dot"
    dot = invoke(parser, ROOT / "examples" / "control.funny", "--dot-dir", str(dot_directory))
    assert dot.returncode == 0, dot.stderr
    assert "digraph CFG" in (dot_directory / "sum_to.cfg.dot").read_text(encoding="utf-8")
    assert "graph Interference" in (dot_directory / "sum_to.interference.dot").read_text(encoding="utf-8")
    print("PASS DOT exports")

    hazard_path = temporary_path / "hazard.funny"
    hazard_path.write_text(
        "hazard(x: int) returns r: int uses unused: int { unused = 1 / x; r = 1; }\n",
        encoding="ascii",
    )
    hazard_result = invoke(parser, hazard_path)
    assert hazard_result.returncode == 0, hazard_result.stderr
    hazard_program = json.loads(hazard_result.stdout)
    for optimized in (False, True):
        try:
            execute(hazard_program, "hazard", [0], optimized=optimized)
        except ZeroDivisionError:
            pass
        else:
            raise AssertionError("DCE removed a potentially throwing division")
    print("PASS DCE preserves observable division errors")

    uninitialized_path = temporary_path / "uninitialized.funny"
    uninitialized_path.write_text(
        "uninitialized() returns r: int uses dead: int, unused: int { "
        "unused = dead + 1; r = 1; }\n",
        encoding="ascii",
    )
    uninitialized_result = invoke(parser, uninitialized_path)
    assert uninitialized_result.returncode == 0, uninitialized_result.stderr
    uninitialized_program = json.loads(uninitialized_result.stdout)
    for optimized in (False, True):
        try:
            execute(uninitialized_program, "uninitialized", [], optimized=optimized)
        except IRRuntimeError as exc:
            assert "dead" in str(exc), exc
        else:
            raise AssertionError("DCE removed a read of an uninitialized local")
    print("PASS DCE preserves uninitialized-local errors")

print("HW4 tests passed")
