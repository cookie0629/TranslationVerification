"""Funny HW3 semantic analysis over the JSON AST produced by HW2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import dataclass


ROOT = Path(__file__).resolve().parent
PARSER = ROOT.parent / "HW2_FunnyParser_C" / ("funny_parser.exe" if sys.platform == "win32" else "funny_parser")
ERROR = "<error>"
UNKNOWN = "<unknown>"


@dataclass
class Symbol:
    name: str
    type: str
    role: str
    definition: dict


@dataclass
class Signature:
    name: str
    params: list[str]
    returns: list[str]
    kind: str
    definition: dict | None = None


class Analyzer:
    def __init__(self, ast: dict):
        self.ast = ast
        self.errors: list[dict] = []
        self.globals: dict[str, Signature] = {
            "length": Signature("length", ["int[]"], ["int"], "builtin")
        }
        self.scopes: list[dict[str, Symbol]] = []

    def error(self, node: dict, message: str) -> None:
        self.errors.append({"line": node["line"], "column": node["column"], "message": message})

    @staticmethod
    def kind(node: dict) -> str:
        return node["kind"]

    @staticmethod
    def children(node: dict) -> list[dict]:
        return node["children"]

    @staticmethod
    def at(node: dict, index: int) -> dict:
        return node["children"][index]

    @staticmethod
    def annotated(node: dict, type_name: str) -> str:
        node["type"] = None if type_name in (ERROR, UNKNOWN) else type_name
        return type_name

    def require(self, got: str, wanted: str, node: dict, context: str) -> bool:
        if got in (ERROR, UNKNOWN) or wanted in (ERROR, UNKNOWN):
            return False
        if got != wanted:
            self.error(node, f"{context}: expected {wanted}, got {got}")
            return False
        return True

    def variable_type(self, definition: dict, required: bool) -> str:
        children = self.children(definition)
        if not children or self.kind(children[0]) != "Type":
            if required:
                self.error(definition, f"'{definition.get('value', '?')}' requires an explicit type")
                return ERROR
            return UNKNOWN
        type_name = children[0]["value"]
        if type_name not in ("int", "int[]"):
            self.error(children[0], f"unsupported type {type_name}")
            return ERROR
        definition["type"] = type_name
        return type_name

    def signatures(self) -> None:
        for declaration in self.children(self.ast):
            name = declaration.get("value", "")
            if name in self.globals:
                self.error(declaration, f"duplicate global declaration '{name}'")
                continue
            if self.kind(declaration) == "Function":
                params = [self.variable_type(d, True) for d in self.children(self.at(declaration, 0))]
                returns = [self.variable_type(d, True) for d in self.children(self.at(declaration, 2))]
                signature = Signature(name, params, returns, "function", declaration)
            elif self.kind(declaration) == "Formula":
                params = [self.variable_type(d, True) for d in self.children(self.at(declaration, 0))]
                signature = Signature(name, params, ["bool"], "formula", declaration)
            else:
                continue
            self.globals[name] = signature
            declaration["type"] = self.signature_text(signature)

    @staticmethod
    def signature_text(signature: Signature) -> str:
        return "func(" + ",".join(signature.params) + ")->(" + ",".join(signature.returns) + ")"

    def declare(self, definition: dict, role: str, required: bool) -> None:
        if self.kind(definition) != "VarDef":
            return
        name = definition.get("value", "")
        current = self.scopes[-1]
        if name in current:
            self.error(definition, f"duplicate declaration '{name}'")
            return
        current[name] = Symbol(name, self.variable_type(definition, required), role, definition)

    def lookup(self, node: dict) -> Symbol | None:
        name = node.get("value", "")
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        self.error(node, f"unknown variable '{name}' (not declared in scope)")
        return None

    def check_call(self, node: dict, use: str) -> list[str]:
        name = node.get("value", "")
        signature = self.globals.get(name)
        arguments = self.children(node)
        actual = [self.expression(argument) for argument in arguments]
        if signature is None:
            node["type"] = None
            self.error(node, f"unknown function or formula '{name}'")
            return [ERROR]
        if use == "value" and signature.kind == "formula":
            self.error(node, f"formula '{name}' cannot be used as a value")
        if use == "tuple" and signature.kind == "formula":
            self.error(node, f"formula '{name}' cannot be used in tuple assignment")
        if len(arguments) != len(signature.params):
            self.error(node, f"call to '{name}' expects {len(signature.params)} argument(s), got {len(arguments)}")
        for index, (argument, got, wanted) in enumerate(zip(arguments, actual, signature.params), 1):
            self.require(got, wanted, argument, f"argument {index} of '{name}'")
        node["type"] = self.signature_text(signature) if use == "tuple" else (
            signature.returns[0] if len(signature.returns) == 1 else None
        )
        if use != "tuple" and len(signature.returns) != 1:
            self.error(node, f"call to '{name}' has {len(signature.returns)} results; single value required")
            return [ERROR]
        return signature.returns

    def expression(self, node: dict, predicate: bool = False) -> str:
        kind = self.kind(node)
        if kind == "Missing" or kind == "Error":
            return self.annotated(node, ERROR)
        if kind == "Int":
            return self.annotated(node, "int")
        if kind == "Bool":
            return self.annotated(node, "bool")
        if kind == "Var":
            symbol = self.lookup(node)
            if symbol is None:
                return self.annotated(node, ERROR)
            if symbol.type == UNKNOWN:
                self.error(node, f"local '{symbol.name}' used before its type is inferred")
                return self.annotated(node, ERROR)
            return self.annotated(node, symbol.type)
        if kind == "Call":
            result = self.check_call(node, "predicate" if predicate else "value")
            return result[0] if len(result) == 1 else ERROR
        if kind == "Index":
            base = self.expression(self.at(node, 0))
            index = self.expression(self.at(node, 1))
            valid = self.require(base, "int[]", self.at(node, 0), "array access")
            valid &= self.require(index, "int", self.at(node, 1), "array index")
            return self.annotated(node, "int" if valid else ERROR)
        if kind == "Set":
            base = self.expression(self.at(node, 0))
            index = self.expression(self.at(node, 1))
            value = self.expression(self.at(node, 2))
            valid = self.require(base, "int[]", self.at(node, 0), "array update")
            valid &= self.require(index, "int", self.at(node, 1), "array index")
            valid &= self.require(value, "int", self.at(node, 2), "array element")
            return self.annotated(node, "int[]" if valid else ERROR)
        if kind == "Unary":
            op = node["value"]
            wanted = "bool" if op == "not" else "int"
            got = self.expression(self.at(node, 0), predicate=predicate)
            valid = self.require(got, wanted, self.at(node, 0), f"operand of '{op}'")
            return self.annotated(node, wanted if valid else ERROR)
        if kind == "Binary":
            op = node["value"]
            logical = op in ("and", "or", "->")
            comparison = op in ("==", "!=", "<", "<=", ">", ">=")
            wanted = "bool" if logical else "int"
            left = self.expression(self.at(node, 0), predicate=predicate)
            right = self.expression(self.at(node, 1), predicate=predicate)
            ok = self.require(left, wanted, self.at(node, 0), f"left operand of '{op}'")
            ok &= self.require(right, wanted, self.at(node, 1), f"right operand of '{op}'")
            return self.annotated(node, ("bool" if logical or comparison else "int") if ok else ERROR)
        if kind == "Quantifier":
            definition = self.at(node, 0)
            name = definition.get("value", "")
            if any(name in scope for scope in self.scopes):
                self.error(definition, f"quantifier variable '{name}' duplicates a visible declaration")
            self.scopes.append({})
            self.declare(definition, "quantifier", True)
            body = self.expression(self.at(node, 1), predicate=True)
            self.require(body, "bool", self.at(node, 1), "quantifier body")
            self.scopes.pop()
            return self.annotated(node, "bool" if body == "bool" else ERROR)
        self.error(node, f"unsupported expression '{kind}'")
        return self.annotated(node, ERROR)

    def check_predicate(self, node: dict, context: str) -> None:
        if self.kind(node) == "Missing":
            return
        got = self.expression(node, predicate=True)
        self.require(got, "bool", node, context)

    def assign_target(self, target: dict, got: str) -> None:
        if self.kind(target) != "Var":
            self.error(target, "assignment target must be a variable")
            return
        symbol = self.lookup(target)
        if symbol is None:
            self.annotated(target, ERROR)
            return
        if symbol.role in ("parameter", "quantifier"):
            self.error(target, f"cannot assign to read-only {symbol.role} '{symbol.name}'")
        if got == ERROR:
            self.annotated(target, symbol.type)
            return
        if symbol.type == UNKNOWN:
            if got in ("int", "int[]") and symbol.role == "local":
                symbol.type = got
                symbol.definition["type"] = got
                symbol.definition["inferred"] = True
            else:
                self.error(target, f"cannot infer type of local '{symbol.name}' from {got}")
        else:
            self.require(got, symbol.type, target, f"assignment to '{symbol.name}'")
        self.annotated(target, symbol.type)

    def statement(self, node: dict) -> None:
        kind = self.kind(node)
        if kind == "Block":
            self.scopes.append({})
            for item in self.children(node):
                self.statement(item)
            self.scopes.pop()
        elif kind == "Assign":
            got = self.expression(self.at(node, 1))
            self.assign_target(self.at(node, 0), got)
        elif kind == "TupleAssign":
            call = self.at(node, 1)
            if self.kind(call) != "Call":
                self.error(call, "tuple assignment requires a function call")
                return
            returns = self.check_call(call, "tuple")
            targets = self.children(self.at(node, 0))
            if returns != [ERROR] and len(returns) != len(targets):
                self.error(node, f"tuple assignment has {len(targets)} target(s), call returns {len(returns)} value(s)")
            for target, got in zip(targets, returns):
                self.assign_target(target, got)
        elif kind == "If":
            condition = self.at(node, 0)
            self.require(self.expression(condition), "bool", condition, "if condition")
            self.statement(self.at(node, 1))
            self.statement(self.at(node, 2))
        elif kind == "While":
            condition = self.at(node, 0)
            self.require(self.expression(condition), "bool", condition, "while condition")
            self.check_predicate(self.at(node, 1), "loop invariant")
            self.statement(self.at(node, 2))
        elif kind in ("Assert", "Assume"):
            self.check_predicate(self.at(node, 0), kind.lower())
        elif kind not in ("Missing", "Error"):
            self.error(node, f"unsupported statement '{kind}'")

    def declaration(self, node: dict) -> None:
        self.scopes = [{}]
        if self.kind(node) == "Formula":
            for definition in self.children(self.at(node, 0)):
                self.declare(definition, "parameter", True)
            self.check_predicate(self.at(node, 1), "formula body")
            return
        for definition in self.children(self.at(node, 0)):
            self.declare(definition, "parameter", True)
        self.check_predicate(self.at(node, 1), "requires")
        for definition in self.children(self.at(node, 2)):
            self.declare(definition, "return", True)
        self.check_predicate(self.at(node, 3), "ensures")
        uses = self.at(node, 4)
        if self.kind(uses) != "Missing":
            for definition in self.children(uses):
                self.declare(definition, "local", False)
        self.statement(self.at(node, 5))
        for symbol in self.scopes[0].values():
            if symbol.role == "local" and symbol.type == UNKNOWN:
                self.error(symbol.definition, f"cannot infer type of local '{symbol.name}': no valid assignment")

    def run(self) -> None:
        self.signatures()
        for declaration in self.children(self.ast):
            if self.kind(declaration) in ("Function", "Formula"):
                self.declaration(declaration)


def parser_diagnostics(stderr: str) -> list[dict]:
    diagnostics = []
    for line in stderr.splitlines():
        match = re.match(r"(\d+):(\d+): error: (.*)", line)
        if match:
            diagnostics.append({"line": int(match[1]), "column": int(match[2]), "message": match[3]})
        elif line.strip():
            diagnostics.append({"line": 0, "column": 0, "message": line.strip()})
    return diagnostics


def main() -> int:
    argument_parser = argparse.ArgumentParser(description="Type-check Funny source and emit annotated AST JSON")
    argument_parser.add_argument("source", nargs="?", help="Funny file; reads stdin if omitted")
    argument_parser.add_argument("--parser", type=Path, default=PARSER, help="HW2 parser executable")
    options = argument_parser.parse_args()
    try:
        source = Path(options.source).read_bytes() if options.source else sys.stdin.buffer.read()
        result = subprocess.run([str(options.parser)], input=source, capture_output=True, timeout=20)
        ast = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"checker: {exc}", file=sys.stderr)
        return 2
    diagnostics = parser_diagnostics(result.stderr.decode("utf-8", errors="replace"))
    if result.returncode == 0:
        analyzer = Analyzer(ast)
        analyzer.run()
        diagnostics.extend(analyzer.errors)
    payload = {"ast": ast, "diagnostics": diagnostics}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
