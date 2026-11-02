"""Reference execution of HW4 IR for before/after equivalence tests."""

from __future__ import annotations

from ir import binary_value, i32, unary_value


class IRRuntimeError(Exception):
    pass


def clone(value):
    return value.copy() if isinstance(value, list) else value


def parameter_value(type_name: str, value):
    if type_name == "int":
        return i32(value)
    if type_name == "int[]":
        if not isinstance(value, list):
            raise IRRuntimeError("int[] parameter expects a list")
        return [i32(item) for item in value]
    raise IRRuntimeError(f"unsupported parameter type {type_name}")


def read(operand: dict, environment: dict):
    if "const" in operand:
        return operand["const"]
    name = operand["ref"]
    if name not in environment:
        raise IRRuntimeError(f"uninitialized value {name}")
    return environment[name]


def array_index(array, index):
    if not isinstance(array, list):
        raise IRRuntimeError("array operation on a non-array value")
    if index < 0 or index >= len(array):
        raise IndexError(f"array index {index} out of range")


def execute(program: dict, name: str, args: list, *, optimized: bool = False,
            step_limit: int = 10000) -> list:
    """Execute a function and return its ordered result list.

    Specification-only clauses (requires/ensures/invariant/quantifiers/formula
    references) are carried by the IR for verification but not evaluated here.
    """
    functions = {item["name"]: item for item in program["functions"]}
    steps = [0]

    def invoke(function_name: str, arguments: list) -> list:
        if function_name == "length":
            if len(arguments) != 1 or not isinstance(arguments[0], list):
                raise IRRuntimeError("length expects one int[]")
            return [i32(len(arguments[0]))]
        if function_name not in functions:
            raise IRRuntimeError(f"unknown function {function_name}")
        item = functions[function_name]
        function = item["after" if optimized else "before"] if "before" in item else item
        if len(arguments) != len(function["params"]):
            raise IRRuntimeError(f"{function_name} expects {len(function['params'])} arguments")
        environment = {param["name"]: parameter_value(param["type"], value)
                       for param, value in zip(function["params"], arguments)}
        blocks = {block["label"]: block for block in function["blocks"]}
        label = function["entry"]
        while True:
            block = blocks[label]
            for instruction in block["instructions"]:
                steps[0] += 1
                if steps[0] > step_limit:
                    raise IRRuntimeError("execution step limit exceeded")
                op = instruction["op"]
                if op == "const":
                    environment[instruction["dest"]] = clone(instruction["value"])
                elif op == "copy":
                    environment[instruction["dest"]] = clone(read(instruction["src"], environment))
                elif op == "unary":
                    environment[instruction["dest"]] = unary_value(
                        instruction["operator"], read(instruction["arg"], environment))
                elif op == "binary":
                    environment[instruction["dest"]] = binary_value(
                        instruction["operator"], read(instruction["left"], environment),
                        read(instruction["right"], environment))
                elif op == "array_get":
                    array = read(instruction["array"], environment)
                    index = read(instruction["index"], environment)
                    array_index(array, index)
                    environment[instruction["dest"]] = array[index]
                elif op == "array_set":
                    array = read(instruction["array"], environment)
                    index = read(instruction["index"], environment)
                    value = read(instruction["value"], environment)
                    array_index(array, index)
                    updated = array.copy()
                    updated[index] = value
                    environment[instruction["dest"]] = updated
                elif op == "call":
                    values = invoke(instruction["function"],
                                    [clone(read(arg, environment)) for arg in instruction["args"]])
                    if len(values) != len(instruction["dests"]):
                        raise IRRuntimeError("call returned the wrong number of values")
                    for destination, value in zip(instruction["dests"], values):
                        environment[destination] = clone(value)
                elif op == "assert":
                    if not read(instruction["arg"], environment):
                        raise AssertionError("Funny assert failed")
                elif op == "assume":
                    if not read(instruction["arg"], environment):
                        raise IRRuntimeError("Funny assume rejected this execution path")
                elif op in ("spec_assert", "spec_assume"):
                    continue
                else:
                    raise IRRuntimeError(f"unknown instruction {op}")
            steps[0] += 1
            if steps[0] > step_limit:
                raise IRRuntimeError("execution step limit exceeded")
            terminator = block["terminator"]
            if terminator["op"] == "jump":
                label = terminator["target"]
            elif terminator["op"] == "branch":
                label = terminator["true"] if read(terminator["cond"], environment) else terminator["false"]
            elif terminator["op"] == "ret":
                return [clone(read(value, environment)) for value in terminator["values"]]
            else:
                raise IRRuntimeError(f"unknown terminator {terminator['op']}")

    return invoke(name, args)
