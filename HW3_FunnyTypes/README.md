# HW3 — Funny 语义检查与类型

此实现直接消费 HW2 解析器生成的 JSON AST；[checker.py](checker.py) 先收集全模块函数/公式签名，再逐个检查函数体。支持前向调用和递归。输出包含附加 `type` 的 AST 与所有可恢复的诊断。

## 构建与运行

需要 Python 3.10+ 和能编译 C99 的 GCC。先从仓库根目录编译 HW2：

```powershell
cd HW2_FunnyParser_C
gcc -std=c99 -O2 -Wall -Wextra -pedantic parser.c -o funny_parser.exe
cd ..\HW3_FunnyTypes
python checker.py tests\valid.funny
python tests\run_tests.py
```

Linux/macOS 将编译输出改为 `funny_parser`，路径分隔符改为 `/`。`checker.py` 也可从标准输入读取程序；若解析器在其他位置，传入 `--parser PATH`。

输出为一行 UTF-8 JSON：

```json
{
  "ast": {"kind":"Module","line":1,"column":1,"children":[...]},
  "diagnostics": [{"line":2,"column":3,"message":"assignment to 'x': expected int, got bool"}]
}
```

完整 AST 沿用 HW2 的 `kind`、`value`、`line`、`column`、`children` 字段。表达式节点另有 `type`：`int`、`int[]`、`bool` 或错误时的 `null`。函数/公式声明和多结果调用写入 `func(T,...)->(T,...)` 签名；`VarDef` 写入声明类型，推断成功的局部声明另有 `inferred:true`。`Set` 是数组功能性复制的 AST 操作，其类型为 `int[]`。这些字段可以由 HW4 的 IR 生成器直接读取。

成功退出码为 `0`；任何词法、语法或语义错误为 `1`；解析器缺失、I/O 故障等运行为 `2`。语义错误仍输出完整注解树和全部已发现诊断。若 HW2 报词法/语法错误，本阶段保留其位置诊断和部分 AST，不在不完整语法树上继续类型检查。

## 支持范围

- Funny 的声明类型只有 `int` 和 `int[]`；`bool` 用于条件、谓词和公式结果，不能声明为变量类型。`length(int[]) -> int` 是内建函数。无字符串、隐式转换或重载。
- 检查整数算术、比较、逻辑运算、数组索引/更新、函数调用、公式调用、量词、`if`、`while`、`assert`、`assume`、`requires`、`ensures` 和 `invariant`。比较要求两个 `int`；数组索引和元素为 `int`。多结果函数只能进入同样数量的赋值目标。
- 参数、返回变量和 `uses` 局部变量共享函数作用域；重复名称报错。块创建嵌套作用域，量词再创建自己的作用域；量词变量不能与可见变量重名。函数/公式名称在模块级唯一。未知或尚未声明的变量会报位置错误。
- 参数与量词变量只读。返回变量和局部变量可赋值。`requires` 只可访问参数；`ensures` 可访问参数及返回值；`uses` 局部变量仅在其后的函数体可见。
- 无类型注解的 `uses` 局部变量，在首次**类型正确**的赋值后确定为 `int` 或 `int[]`。赋值右侧若类型不明或为 `bool`，无法推断；后续冲突和使用早于推断都会报错。未得到有效赋值的局部变量在函数结束时报告错误。

本阶段进行静态类型检查，不执行程序，也不检查整数溢出、数组越界、赋值路径上的初始化、契约真假或终止性。嵌套 `int[][]` 不在 Funny 已声明类型范围内：HW2 虽能解析 `a[i][j]`，本阶段会按 `int[]` 元素为 `int` 报类型错误。

## 测试

[tests/run_tests.py](tests/run_tests.py) 启动真实 HW2 解析器和本检查器，验证 11 个程序的退出状态、AST 类型字段、推断结果以及错误行列和消息。负向用例的预期诊断直接列在测试脚本 `references` 中；其中 `errors.funny` 一次验证多个独立错误，不会在第一处停止。

测试同时涵盖解析错误的传递。若修改了 HW2 解析器，请重新编译后再运行测试。
