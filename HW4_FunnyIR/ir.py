"""Typed Funny AST -> three-address IR, CFG, and a small reference interpreter."""

from __future__ import annotations

from copy import deepcopy


def ref(name: str) -> dict:
    return {"ref": name}


def const(value: int | bool, type_name: str) -> dict:
    return {"const": value, "type": type_name}


def i32(value: int) -> int:
    return ((int(value) + 2**31) % 2**32) - 2**31


def binary_value(op: str, left: int | bool, right: int | bool) -> int | bool:
    if op == "+":
        return i32(left + right)
    if op == "-":
        return i32(left - right)
    if op == "*":
        return i32(left * right)
    if op == "/":
        if right == 0:
            raise ZeroDivisionError("division by zero")
        quotient = abs(left) // abs(right)
        return i32(-quotient if (left < 0) != (right < 0) else quotient)
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    raise ValueError(f"unsupported binary operator {op!r}")


def unary_value(op: str, value: int | bool) -> int | bool:
    if op == "-":
        return i32(-value)
    if op == "not":
        return not value
    raise ValueError(f"unsupported unary operator {op!r}")


def names_in_ast(node: dict) -> set[str]:
    names = {node["value"]} if node["kind"] == "Var" else set()
    for child in node["children"]:
        names.update(names_in_ast(child))
    return names


def has_spec_expression(node: dict, formula_names: set[str]) -> bool:
    if node["kind"] == "Quantifier":
        return True
    if node["kind"] == "Call" and node["value"] in formula_names:
        return True
    return any(has_spec_expression(child, formula_names) for child in node["children"])


def operand_refs(operand: dict) -> set[str]:
    return {operand["ref"]} if "ref" in operand else set()


def instruction_defs(instruction: dict) -> set[str]:
    if "dest" in instruction:
        return {instruction["dest"]}
    return set(instruction.get("dests", []))


def instruction_uses(instruction: dict) -> set[str]:
    op = instruction["op"]
    if op == "copy":
        return operand_refs(instruction["src"])
    if op == "unary":
        return operand_refs(instruction["arg"])
    if op == "binary":
        return operand_refs(instruction["left"]) | operand_refs(instruction["right"])
    if op == "array_get":
        return operand_refs(instruction["array"]) | operand_refs(instruction["index"])
    if op == "array_set":
        return (operand_refs(instruction["array"]) | operand_refs(instruction["index"])
                | operand_refs(instruction["value"]))
    if op == "call":
        return set().union(*(operand_refs(arg) for arg in instruction["args"])) if instruction["args"] else set()
    if op in ("assert", "assume"):
        return operand_refs(instruction["arg"])
    if op in ("spec_assert", "spec_assume"):
        return names_in_ast(instruction["predicate"])
    return set()


def terminator_uses(terminator: dict) -> set[str]:
    if terminator["op"] == "branch":
        return operand_refs(terminator["cond"])
    if terminator["op"] == "ret":
        return set().union(*(operand_refs(value) for value in terminator["values"])) if terminator["values"] else set()
    return set()


def successors(terminator: dict) -> list[str]:
    if terminator["op"] == "jump":
        return [terminator["target"]]
    if terminator["op"] == "branch":
        return list(dict.fromkeys((terminator["true"], terminator["false"])))
    return []


def refresh_cfg(function: dict) -> None:
    by_label = {block["label"]: block for block in function["blocks"]}
    for block in function["blocks"]:
        block["successors"] = successors(block["terminator"])
        block["predecessors"] = []
    for block in function["blocks"]:
        for label in block["successors"]:
            by_label[label]["predecessors"].append(block["label"])


def definitions(list_node: dict) -> list[dict]:
    result = []
    for definition in list_node["children"]:
        if definition["kind"] != "VarDef" or definition.get("type") not in ("int", "int[]"):
            raise ValueError(f"missing annotated type at {definition['line']}:{definition['column']}")
        result.append({"name": definition["value"], "type": definition["type"]})
    return result


class Lowerer:
    def __init__(self, declaration: dict, signatures: dict[str, list[str]], formula_names: set[str]):
        self.declaration = declaration
        self.signatures = signatures
        self.formula_names = formula_names
        self.blocks: list[dict] = []
        self.current: dict = {}
        self.temp_types: dict[str, str] = {}
        self.temp_index = 0
        self.new_block("entry")

    def new_block(self, hint: str) -> dict:
        block = {"label": f"B{len(self.blocks)}", "hint": hint,
                 "instructions": [], "terminator": None}
        self.blocks.append(block)
        self.current = block
        return block

    def temp(self, type_name: str) -> str:
        if type_name not in ("int", "int[]", "bool"):
            raise ValueError(f"expression lacks a valid type: {type_name!r}")
        name = f"%t{self.temp_index}"
        self.temp_index += 1
        self.temp_types[name] = type_name
        return name

    def emit(self, op: str, node: dict, **fields) -> dict:
        instruction = {"op": op, **fields, "line": node["line"], "column": node["column"]}
        self.current["instructions"].append(instruction)
        return instruction

    def terminate(self, op: str, **fields) -> None:
        if self.current["terminator"] is not None:
            raise ValueError("basic block already has a terminator")
        self.current["terminator"] = {"op": op, **fields}

    def expression(self, node: dict) -> dict:
        kind = node["kind"]
        type_name = node.get("type")
        if kind == "Var":
            return ref(node["value"])
        if kind in ("Int", "Bool"):
            name = self.temp(type_name)
            value = i32(int(node["value"])) if kind == "Int" else node["value"] == "true"
            self.emit("const", node, dest=name, value=value, type=type_name)
            return ref(name)
        if kind == "Unary":
            arg = self.expression(node["children"][0])
            name = self.temp(type_name)
            self.emit("unary", node, dest=name, operator=node["value"], arg=arg, type=type_name)
            return ref(name)
        if kind == "Binary":
            if node["value"] in ("and", "or", "->"):
                return self.logical_expression(node)
            left = self.expression(node["children"][0])
            right = self.expression(node["children"][1])
            name = self.temp(type_name)
            self.emit("binary", node, dest=name, operator=node["value"],
                      left=left, right=right, type=type_name)
            return ref(name)
        if kind == "Index":
            array = self.expression(node["children"][0])
            index = self.expression(node["children"][1])
            name = self.temp(type_name)
            self.emit("array_get", node, dest=name, array=array, index=index, type=type_name)
            return ref(name)
        if kind == "Set":
            array = self.expression(node["children"][0])
            index = self.expression(node["children"][1])
            value = self.expression(node["children"][2])
            name = self.temp(type_name)
            self.emit("array_set", node, dest=name, array=array,
                      index=index, value=value, type=type_name)
            return ref(name)
        if kind == "Call":
            args = [self.expression(arg) for arg in node["children"]]
            returns = self.signatures[node["value"]]
            if len(returns) != 1:
                raise ValueError(f"multi-result call '{node['value']}' in an expression")
            name = self.temp(returns[0])
            self.emit("call", node, dests=[name], function=node["value"],
                      args=args, types=returns)
            return ref(name)
        raise ValueError(f"unsupported executable expression {kind} at {node['line']}:{node['column']}")

    def logical_expression(self, node: dict) -> dict:
        op = node["value"]
        left = self.expression(node["children"][0])
        result = self.temp("bool")
        left_block = self.current
        right_block = self.new_block("logical_right")
        short_block = self.new_block("logical_short")
        join_block = self.new_block("logical_join")
        self.current = left_block
        if op == "and":
            self.terminate("branch", cond=left, true=right_block["label"], false=short_block["label"])
            short_value = False
        elif op == "or":
            self.terminate("branch", cond=left, true=short_block["label"], false=right_block["label"])
            short_value = True
        else:  # implication: false -> x is true; true -> x evaluates x
            self.terminate("branch", cond=left, true=right_block["label"], false=short_block["label"])
            short_value = True
        self.current = short_block
        self.emit("const", node, dest=result, value=short_value, type="bool")
        self.terminate("jump", target=join_block["label"])
        self.current = right_block
        right = self.expression(node["children"][1])
        self.emit("copy", node, dest=result, src=right, type="bool")
        self.terminate("jump", target=join_block["label"])
        self.current = join_block
        return ref(result)

    def statement(self, node: dict) -> None:
        kind = node["kind"]
        if kind == "Missing":
            return
        if kind == "Block":
            for item in node["children"]:
                self.statement(item)
            return
        if kind == "Assign":
            target, value = node["children"]
            source = self.expression(value)
            self.emit("copy", node, dest=target["value"], src=source, type=target["type"])
            return
        if kind == "TupleAssign":
            targets, call = node["children"]
            args = [self.expression(arg) for arg in call["children"]]
            return_types = self.signatures[call["value"]]
            dests = [self.temp(type_name) for type_name in return_types]
            self.emit("call", call, dests=dests, function=call["value"],
                      args=args, types=return_types)
            for target, source in zip(targets["children"], dests):
                self.emit("copy", target, dest=target["value"],
                          src=ref(source), type=target["type"])
            return
        if kind in ("Assert", "Assume"):
            predicate = node["children"][0]
            if has_spec_expression(predicate, self.formula_names):
                self.emit("spec_assert" if kind == "Assert" else "spec_assume",
                          node, predicate=deepcopy(predicate))
            else:
                value = self.expression(predicate)
                self.emit("assert" if kind == "Assert" else "assume", node, arg=value)
            return
        if kind == "If":
            condition, then_part, else_part = node["children"]
            cond = self.expression(condition)
            condition_block = self.current
            then_block = self.new_block("if_then")
            else_block = self.new_block("if_else") if else_part["kind"] != "Missing" else None
            join_block = self.new_block("if_join")
            self.current = condition_block
            self.terminate("branch", cond=cond, true=then_block["label"],
                           false=(else_block or join_block)["label"])
            self.current = then_block
            self.statement(then_part)
            if self.current["terminator"] is None:
                self.terminate("jump", target=join_block["label"])
            if else_block:
                self.current = else_block
                self.statement(else_part)
                if self.current["terminator"] is None:
                    self.terminate("jump", target=join_block["label"])
            self.current = join_block
            return
        if kind == "While":
            condition, invariant, body = node["children"]
            preceding = self.current
            header = self.new_block("while_header")
            body_block = self.new_block("while_body")
            exit_block = self.new_block("while_exit")
            self.current = preceding
            self.terminate("jump", target=header["label"])
            self.current = header
            if invariant["kind"] != "Missing":
                header["invariant"] = deepcopy(invariant)
            cond = self.expression(condition)
            self.terminate("branch", cond=cond, true=body_block["label"], false=exit_block["label"])
            self.current = body_block
            self.statement(body)
            if self.current["terminator"] is None:
                self.terminate("jump", target=header["label"])
            self.current = exit_block
            return
        raise ValueError(f"unsupported statement {kind} at {node['line']}:{node['column']}")

    def finish(self) -> dict:
        declaration = self.declaration
        params = definitions(declaration["children"][0])
        returns = definitions(declaration["children"][2])
        uses = declaration["children"][4]
        locals_ = definitions(uses) if uses["kind"] == "Uses" else []
        self.statement(declaration["children"][5])
        self.terminate("ret", values=[ref(item["name"]) for item in returns])
        function = {
            "name": declaration["value"], "params": params,
            "returns": returns, "locals": locals_,
            "contracts": {
                "requires": deepcopy(declaration["children"][1]) if declaration["children"][1]["kind"] != "Missing" else None,
                "ensures": deepcopy(declaration["children"][3]) if declaration["children"][3]["kind"] != "Missing" else None,
            },
            "entry": "B0", "temp_types": self.temp_types, "blocks": self.blocks,
        }
        refresh_cfg(function)
        return function


def lower_program(ast: dict) -> dict:
    if ast["kind"] != "Module":
        raise ValueError("expected an annotated Module AST")
    formulas = [deepcopy(node) for node in ast["children"] if node["kind"] == "Formula"]
    formula_names = {node["value"] for node in formulas}
    signatures = {"length": ["int"]}
    for node in ast["children"]:
        if node["kind"] == "Function":
            signatures[node["value"]] = [d["type"] for d in definitions(node["children"][2])]
    functions = []
    for node in ast["children"]:
        if node["kind"] == "Function":
            functions.append(Lowerer(node, signatures, formula_names).finish())
    return {"version": 1, "functions": functions, "formulas": formulas}
