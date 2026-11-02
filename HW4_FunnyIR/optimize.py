"""Block-local optimization, CFG liveness, interference graph and coloring."""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations

from ir import (binary_value, const, instruction_defs, instruction_uses,
                names_in_ast, operand_refs, refresh_cfg, terminator_uses,
                unary_value)


def source_fields(instruction: dict) -> list[str]:
    return {
        "copy": ["src"], "unary": ["arg"], "binary": ["left", "right"],
        "array_get": ["array", "index"],
        "array_set": ["array", "index", "value"],
        "assert": ["arg"], "assume": ["arg"],
    }.get(instruction["op"], [])


def replace_sources(instruction: dict, known: dict[str, dict]) -> None:
    for field in source_fields(instruction):
        value = instruction[field]
        if "ref" in value and value["ref"] in known:
            instruction[field] = deepcopy(known[value["ref"]])
    if instruction["op"] == "call":
        instruction["args"] = [deepcopy(known.get(arg["ref"], arg)) if "ref" in arg else arg
                               for arg in instruction["args"]]


def known_constant(operand: dict, known: dict[str, dict]) -> dict | None:
    if "const" in operand:
        return operand
    return known.get(operand.get("ref", ""))


def int_value(operand: dict, known: dict[str, dict]) -> int | None:
    resolved = known_constant(operand, known)
    if resolved is not None and resolved.get("type") == "int":
        return resolved["const"]
    return None


def make_const(instruction: dict, value: int | bool) -> dict:
    return {"op": "const", "dest": instruction["dest"], "value": value,
            "type": instruction["type"], "line": instruction["line"],
            "column": instruction["column"]}


def make_copy(instruction: dict, operand: dict) -> dict:
    return {"op": "copy", "dest": instruction["dest"], "src": deepcopy(operand),
            "type": instruction["type"], "line": instruction["line"],
            "column": instruction["column"]}


def simplify_binary(instruction: dict, known: dict[str, dict]) -> dict:
    op = instruction["operator"]
    left, right = instruction["left"], instruction["right"]
    left_int, right_int = int_value(left, known), int_value(right, known)
    if op == "+":
        if right_int == 0:
            return make_copy(instruction, left)
        if left_int == 0:
            return make_copy(instruction, right)
    if op == "-" and right_int == 0:
        return make_copy(instruction, left)
    if op == "*":
        if right_int == 1:
            return make_copy(instruction, left)
        if left_int == 1:
            return make_copy(instruction, right)
    if op == "/" and right_int == 1:
        return make_copy(instruction, left)
    # x*0 is deliberately excluded: an uninitialized direct variable read
    # must not disappear, and DCE must keep operations that may throw.
    return instruction


def optimize_block(block: dict, constants: bool, algebra: bool) -> None:
    known: dict[str, dict] = {}
    rewritten = []
    for original in block["instructions"]:
        instruction = deepcopy(original)
        if constants:
            replace_sources(instruction, known)
        if instruction["op"] == "unary" and constants and "const" in instruction["arg"]:
            instruction = make_const(instruction, unary_value(instruction["operator"],
                                                            instruction["arg"]["const"]))
        elif instruction["op"] == "binary":
            left, right = instruction["left"], instruction["right"]
            if constants and "const" in left and "const" in right:
                try:
                    value = binary_value(instruction["operator"], left["const"], right["const"])
                    instruction = make_const(instruction, value)
                except ZeroDivisionError:
                    pass
            if instruction["op"] == "binary" and algebra:
                instruction = simplify_binary(instruction, known)
        if instruction["op"] == "copy" and constants and "const" in instruction["src"]:
            instruction = make_const(instruction, instruction["src"]["const"])
        for name in instruction_defs(instruction):
            known.pop(name, None)
        if instruction["op"] == "const":
            known[instruction["dest"]] = const(instruction["value"], instruction["type"])
        elif instruction["op"] == "copy" and constants:
            value = known_constant(instruction["src"], known)
            if value is not None:
                known[instruction["dest"]] = deepcopy(value)
        rewritten.append(instruction)
    block["instructions"] = rewritten


def liveness(function: dict) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    blocks = function["blocks"]
    block_use: dict[str, set[str]] = {}
    block_def: dict[str, set[str]] = {}
    for block in blocks:
        uses = names_in_ast(block["invariant"]) if "invariant" in block else set()
        defs: set[str] = set()
        for instruction in block["instructions"]:
            uses.update(instruction_uses(instruction) - defs)
            defs.update(instruction_defs(instruction))
        uses.update(terminator_uses(block["terminator"]) - defs)
        block_use[block["label"]] = uses
        block_def[block["label"]] = defs
    live_in = {block["label"]: set() for block in blocks}
    live_out = {block["label"]: set() for block in blocks}
    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):
            label = block["label"]
            outgoing = set().union(*(live_in[next_label] for next_label in block["successors"])) if block["successors"] else set()
            incoming = block_use[label] | (outgoing - block_def[label])
            if incoming != live_in[label] or outgoing != live_out[label]:
                live_in[label], live_out[label] = incoming, outgoing
                changed = True
    return live_in, live_out


def removable(instruction: dict) -> bool:
    # HW3 checks types but does not reject reads of uninitialized locals.
    # Keep such reads so optimization preserves the runtime error and its order.
    if any(not name.startswith("%t") for name in instruction_uses(instruction)):
        return False
    if instruction["op"] in ("const", "copy", "unary"):
        return True
    return instruction["op"] == "binary" and instruction["operator"] != "/"


def eliminate_dead(function: dict) -> None:
    while True:
        _, live_out = liveness(function)
        removed = False
        for block in function["blocks"]:
            live = live_out[block["label"]] | terminator_uses(block["terminator"])
            kept = []
            for instruction in reversed(block["instructions"]):
                defs = instruction_defs(instruction)
                if defs and not (defs & live) and removable(instruction):
                    removed = True
                    continue
                live.difference_update(defs)
                live.update(instruction_uses(instruction))
                kept.append(instruction)
            block["instructions"] = list(reversed(kept))
        if not removed:
            break


def active_temporaries(function: dict) -> set[str]:
    names = set()
    for block in function["blocks"]:
        for instruction in block["instructions"]:
            names.update(instruction_defs(instruction))
            names.update(instruction_uses(instruction))
        names.update(terminator_uses(block["terminator"]))
    return {name for name in names if name.startswith("%t")}


def interference(function: dict, live_out: dict[str, set[str]]) -> tuple[dict[str, list[str]], dict[str, int]]:
    temporaries = active_temporaries(function)
    graph: dict[str, set[str]] = {name: set() for name in temporaries}

    def connect_live(names: set[str]) -> None:
        for left, right in combinations(sorted(names & temporaries), 2):
            graph[left].add(right)
            graph[right].add(left)

    for block in function["blocks"]:
        live = live_out[block["label"]] | terminator_uses(block["terminator"])
        connect_live(live)
        for instruction in reversed(block["instructions"]):
            defs = instruction_defs(instruction)
            for definition in defs & temporaries:
                for other in live & temporaries - {definition}:
                    graph[definition].add(other)
                    graph[other].add(definition)
            live.difference_update(defs)
            live.update(instruction_uses(instruction))
            connect_live(live)
    colors: dict[str, int] = {}
    for name in sorted(graph, key=lambda item: (-len(graph[item]), item)):
        occupied = {colors[neighbor] for neighbor in graph[name] if neighbor in colors}
        color = 0
        while color in occupied:
            color += 1
        colors[name] = color
    return {name: sorted(neighbors) for name, neighbors in sorted(graph.items())}, colors


def analyze(function: dict) -> None:
    refresh_cfg(function)
    live_in, live_out = liveness(function)
    graph, colors = interference(function, live_out)
    function["liveness"] = {
        block["label"]: {"in": sorted(live_in[block["label"]]),
                          "out": sorted(live_out[block["label"]])}
        for block in function["blocks"]
    }
    function["interference"] = {"edges": graph, "colors": colors}
    active = active_temporaries(function)
    function["temp_types"] = {name: type_name for name, type_name in function["temp_types"].items()
                              if name in active}
    function["metrics"] = {
        "instructions": sum(len(block["instructions"]) + 1 for block in function["blocks"]),
        "temporaries": len(active),
        "colors": len(set(colors.values())),
    }


def optimize_function(function: dict, *, constants: bool = True,
                      algebra: bool = True, dce: bool = True) -> dict:
    optimized = deepcopy(function)
    if constants or algebra:
        for block in optimized["blocks"]:
            optimize_block(block, constants, algebra)
    if dce:
        eliminate_dead(optimized)
    analyze(optimized)
    return optimized
