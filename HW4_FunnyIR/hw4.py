"""HW4 command line: Funny source -> HW3 typed AST -> IR/CFG/optimization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from ir import lower_program
from optimize import analyze, optimize_function


ROOT = Path(__file__).resolve().parent
DEFAULT_CHECKER = ROOT.parent / "HW3_FunnyTypes" / "checker.py"


def load_ast(options) -> dict:
    if options.ast:
        payload = json.loads(options.ast.read_text(encoding="utf-8"))
    else:
        source = Path(options.source).read_bytes() if options.source else sys.stdin.buffer.read()
        command = [sys.executable, str(options.checker), "--json"]
        if options.parser:
            command.extend(("--parser", str(options.parser)))
        result = subprocess.run(command, input=source, capture_output=True, timeout=30)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"HW3 did not produce JSON: {detail or exc}") from exc
    if payload.get("kind") == "Module":
        return payload
    for error in payload.get("diagnostics", []):
        print(f"{error['line']}:{error['column']} "
              f"[{error.get('category', 'Error')}] {error['message']}", file=sys.stderr)
    if payload.get("diagnostics"):
        raise ValueError("HW3 reported errors; IR generation stopped")
    ast = payload.get("ast")
    if not isinstance(ast, dict) or ast.get("kind") != "Module":
        raise ValueError("expected an HW3 annotated Module AST")
    return ast


def generate(ast: dict, *, constants: bool = True, algebra: bool = True,
             dce: bool = True) -> dict:
    lowered = lower_program(ast)
    functions = []
    for original in lowered["functions"]:
        analyze(original)
        optimized = optimize_function(original, constants=constants, algebra=algebra, dce=dce)
        functions.append({
            "name": original["name"], "before": original, "after": optimized,
            "metrics": {"before": original["metrics"], "after": optimized["metrics"]},
        })
    return {"version": 1, "formulas": lowered["formulas"], "functions": functions,
            "optimizations": {"constants": constants, "algebra": algebra, "dce": dce}}


def operand_text(operand: dict) -> str:
    if "ref" in operand:
        return operand["ref"]
    return "true" if operand["const"] is True else "false" if operand["const"] is False else str(operand["const"])


def instruction_text(instruction: dict) -> str:
    op = instruction["op"]
    if op == "const":
        return f"{instruction['dest']} = {operand_text({'const': instruction['value']})}"
    if op == "copy":
        return f"{instruction['dest']} = {operand_text(instruction['src'])}"
    if op == "unary":
        return f"{instruction['dest']} = {instruction['operator']} {operand_text(instruction['arg'])}"
    if op == "binary":
        return (f"{instruction['dest']} = {operand_text(instruction['left'])} "
                f"{instruction['operator']} {operand_text(instruction['right'])}")
    if op == "array_get":
        return f"{instruction['dest']} = {operand_text(instruction['array'])}[{operand_text(instruction['index'])}]"
    if op == "array_set":
        return (f"{instruction['dest']} = set({operand_text(instruction['array'])}, "
                f"{operand_text(instruction['index'])}, {operand_text(instruction['value'])})")
    if op == "call":
        targets = ", ".join(instruction["dests"])
        args = ", ".join(operand_text(arg) for arg in instruction["args"])
        return f"{targets} = call {instruction['function']}({args})"
    if op in ("assert", "assume"):
        return f"{op} {operand_text(instruction['arg'])}"
    if op in ("spec_assert", "spec_assume"):
        return f"{op} <predicate at {instruction['line']}:{instruction['column']}>"
    raise ValueError(f"unknown instruction {op}")


def terminator_text(terminator: dict) -> str:
    if terminator["op"] == "jump":
        return f"jump {terminator['target']}"
    if terminator["op"] == "branch":
        return (f"branch {operand_text(terminator['cond'])} "
                f"? {terminator['true']} : {terminator['false']}")
    if terminator["op"] == "ret":
        return "return " + ", ".join(operand_text(value) for value in terminator["values"])
    raise ValueError(f"unknown terminator {terminator['op']}")


def format_ir(function: dict) -> str:
    lines = []
    for block in function["blocks"]:
        lines.append(f"  {block['label']} ({block['hint']}):")
        if "invariant" in block:
            lines.append(f"    invariant <AST at {block['invariant']['line']}:{block['invariant']['column']}>")
        for instruction in block["instructions"]:
            lines.append("    " + instruction_text(instruction))
        lines.append("    " + terminator_text(block["terminator"]))
    return "\n".join(lines)


def format_program(program: dict) -> str:
    lines = ["Funny IR, version 1"]
    if program["formulas"]:
        lines.append("Specification formulas preserved: " +
                     ", ".join(node["value"] for node in program["formulas"]))
    enabled = [name for name, value in program["optimizations"].items() if value]
    lines.append("Optimizations: " + (", ".join(enabled) if enabled else "off"))
    for item in program["functions"]:
        original, optimized = item["before"], item["after"]
        params = ", ".join(f"{p['name']}:{p['type']}" for p in original["params"])
        returns = ", ".join(f"{p['name']}:{p['type']}" for p in original["returns"])
        lines.extend(("", f"Function {item['name']}({params}) -> ({returns})",
                      "Before optimization:", format_ir(original),
                      "After optimization:", format_ir(optimized), "CFG:"))
        for block in optimized["blocks"]:
            targets = ", ".join(block["successors"]) or "exit"
            lines.append(f"  {block['label']} -> {targets}")
        lines.append("Interference graph (optimized temporaries):")
        graph = optimized["interference"]["edges"]
        for name, neighbors in graph.items():
            lines.append(f"  {name}: {', '.join(neighbors) if neighbors else '(none)'}")
        colors = optimized["interference"]["colors"]
        lines.append("Register colors: " +
                     (", ".join(f"{name}=R{color}" for name, color in colors.items()) if colors else "(none)"))
        before, after = item["metrics"]["before"], item["metrics"]["after"]
        lines.append("Metrics (before -> after): " +
                     f"instructions {before['instructions']} -> {after['instructions']}; " +
                     f"temporaries {before['temporaries']} -> {after['temporaries']}; " +
                     f"colors {before['colors']} -> {after['colors']}")
    return "\n".join(lines) + "\n"


def write_dot(program: dict, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for item in program["functions"]:
        name = re.sub(r"[^A-Za-z0-9_]", "_", item["name"])
        function = item["after"]
        cfg = ["digraph CFG {", "  node [shape=box];"]
        for block in function["blocks"]:
            cfg.append(f'  {block["label"]} [label="{block["label"]}: {block["hint"]}"];')
            for target in block["successors"]:
                cfg.append(f'  {block["label"]} -> {target};')
        cfg.append("}")
        cfg_path = directory / f"{name}.cfg.dot"
        cfg_path.write_text("\n".join(cfg) + "\n", encoding="utf-8")
        written.append(cfg_path)
        graph = function["interference"]["edges"]
        colors = function["interference"]["colors"]
        conflicts = ["graph Interference {"]
        for temporary in graph:
            conflicts.append(f'  "{temporary}" [label="{temporary} / R{colors[temporary]}"];')
        for left, neighbors in graph.items():
            for right in neighbors:
                if left < right:
                    conflicts.append(f'  "{left}" -- "{right}";')
        conflicts.append("}")
        graph_path = directory / f"{name}.interference.dot"
        graph_path.write_text("\n".join(conflicts) + "\n", encoding="utf-8")
        written.append(graph_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and optimize Funny three-address IR")
    parser.add_argument("source", nargs="?", help="Funny source file; stdin if omitted")
    parser.add_argument("--ast", type=Path, help="HW3 annotated AST JSON instead of source")
    parser.add_argument("--checker", type=Path, default=DEFAULT_CHECKER)
    parser.add_argument("--parser", type=Path, help="HW2 parser executable for the HW3 stage")
    parser.add_argument("--json", action="store_true", help="indented, machine-readable IR/CFG/graph JSON")
    parser.add_argument("--dot-dir", type=Path, help="write CFG and interference DOT files")
    parser.add_argument("--no-opt", action="store_true", help="disable all optimizations")
    parser.add_argument("--no-const", action="store_true", help="disable local constant propagation/folding")
    parser.add_argument("--no-algebra", action="store_true", help="disable algebraic simplification")
    parser.add_argument("--no-dce", action="store_true", help="disable dead-code elimination")
    options = parser.parse_args()
    if options.ast and options.source:
        parser.error("source and --ast are mutually exclusive")
    try:
        ast = load_ast(options)
        constants = not (options.no_opt or options.no_const)
        algebra = not (options.no_opt or options.no_algebra)
        dce = not (options.no_opt or options.no_dce)
        program = generate(ast, constants=constants, algebra=algebra, dce=dce)
        if options.dot_dir:
            paths = write_dot(program, options.dot_dir)
            print("Wrote DOT: " + ", ".join(str(path) for path in paths), file=sys.stderr)
        if options.json:
            print(json.dumps(program, ensure_ascii=False, indent=2))
        else:
            print(format_program(program), end="")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"HW4 error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
