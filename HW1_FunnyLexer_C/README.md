# HW1 — Funny Lexer: Regex → NFA → DFA → Hopcroft Minimization

这是一个**纯 C99、无第三方依赖**的 HW1 实现，完成：

1. 正则表达式规则定义；
2. Thompson 构造法：Regex → ε-NFA；
3. Subset Construction：ε-NFA → DFA；
4. Hopcroft：DFA → 最小 DFA；
5. ASCII 128 字符完整化，并加入 trap/sink；
6. 最大匹配（maximal munch）；
7. 同长度 token 按 priority 决胜；
8. WS / COMMENT 作为 `skip`，不会出现在最终 token stream；
9. `01` / `00` 通过 `BAD_INT` 作为明确的词法错误；
10. 非 ASCII 字符直接报错；
11. 自动输出 JSON / CSV 转移表；
12. 内置正向、负向和边界测试。

## 1. 目录

```text
HW1_FunnyLexer_C/
├── main.c
├── README.md
├── tests.txt
└── Makefile
```

程序运行后还会生成：

```text
funny_dfa.json
funny_dfa.csv
```

## 2. 编译

### Linux / macOS / MinGW

```bash
gcc -std=c99 -O2 -Wall -Wextra -pedantic main.c -o funny_hw1
./funny_hw1
```

### Windows PowerShell + MinGW

```powershell
gcc -std=c99 -O2 -Wall -Wextra -pedantic main.c -o funny_hw1.exe
.\funny_hw1.exe
```

如果使用 Visual Studio Developer Command Prompt：

```bat
cl /std:c11 /O2 main.c
main.exe
```

## 3. 词法规则

本实现使用下面的 Funny token 规则。

| Token | 正则 | 类型 |
|---|---|---|
| `function` | `function` | keyword |
| `returns` | `returns` | keyword |
| `while` | `while` | keyword |
| `if` | `if` | keyword |
| `else` | `else` | keyword |
| `assert` | `assert` | keyword |
| `assume` | `assume` | keyword |
| `invariant` | `invariant` | keyword |
| `length` | `length` | keyword |
| `BAD_INT` | `0[0-9]+` | error |
| `INT` | `0|[1-9][0-9]*` | accepting |
| `IDENT` | `[A-Za-z_][A-Za-z0-9_]*` | accepting |
| `EQ` | `==` | accepting |
| `NE` | `!=` | accepting |
| `LE` | `<=` | accepting |
| `GE` | `>=` | accepting |
| `LT` | `<` | accepting |
| `GT` | `>` | accepting |
| `ASSIGN` | `=` | accepting |
| `PLUS` | `\+` | accepting |
| `MINUS` | `-` | accepting |
| `STAR` | `\*` | accepting |
| `SLASH` | `/` | accepting |
| `LPAREN` | `\(` | accepting |
| `RPAREN` | `\)` | accepting |
| `LBRACKET` | `\[` | accepting |
| `RBRACKET` | `\]` | accepting |
| `LBRACE` | `\{` | accepting |
| `RBRACE` | `\}` | accepting |
| `COMMA` | `,` | accepting |
| `SEMICOLON` | `;` | accepting |
| `WS` | `[ \t\r\n]+` | skip |
| `COMMENT` | `//[^\r\n]*` | skip |

### 为什么有 BAD_INT？

题目明确要求：

```text
0      positive
00     negative
01     negative
```

如果只使用：

```text
INT = 0|[1-9][0-9]*
```

那么普通 maximal-munch lexer 会把 `01` 分成：

```text
INT(0) INT(1)
```

从而无法把整个 `01` 当成错误。

因此这里增加一个**非接受错误规则**：

```text
BAD_INT = 0[0-9]+
```

它优先级高于 `INT`，所以：

```text
01  -> BAD_INT -> lexical error
00  -> BAD_INT -> lexical error
0   -> INT
10  -> INT
123 -> INT
```

这是为了满足 HW1 给出的“01 为 negative example”的测试要求。

## 4. Regex → NFA

程序内部先建立一个超级起点：

```text
                 ε -> regex_0
                 ε -> regex_1
super_start  ----ε -> regex_2
                 ...
                 ε -> regex_n
```

每个正则表达式使用 Thompson construction 转换成 ε-NFA。

支持：

```text
literal
()
|
*
+
?
[]
[^]
[a-z]
\+
\*
\(
\)
\t
\r
\n
```

例如：

```text
[A-Za-z_][A-Za-z0-9_]*
```

会被转换为 Thompson ε-NFA。

## 5. NFA → DFA

使用 subset construction。

一个 DFA state 本质上是：

```text
ε-closure({q1, q2, q7, ...})
```

程序使用 bitset 保存 NFA state subset。

ASCII 固定为：

```text
0 ... 127
```

所以 DFA 每个状态最多有 128 条转移。

## 6. DFA 最小化

使用 Hopcroft partition refinement。

一个重要细节：

普通语言识别 DFA 可以把所有 accepting states 放在同一个初始 partition。

但是 lexer 不可以这么做。

例如：

```text
IF
IDENT
```

二者都是 accepting state，但 lexer 必须知道到底接受成：

```text
IF
```

还是：

```text
IDENT
```

所以这里的初始 partition 是：

```text
NON_ACCEPT
KW_FUNCTION
KW_RETURNS
...
INT
IDENT
EQ
...
```

即：

> 不同 token rule 的 accepting states 不允许在最小化过程中合并。

这样才能同时保持 DFA 的语言识别能力和 lexer 的 token identity。

## 7. Trap / Sink

DFA 被补全为：

```text
所有 ASCII 字符都有转移
```

不存在转移的位置进入 trap：

```text
trap --ASCII--> trap
```

trap 永远不是 accepting state。

因此：

```text
a@b
```

中：

```text
@ 
```

没有任何合法 token rule 可以接受，最终产生 lexical error。

非 ASCII 字符也会直接产生错误，因为：

```text
alphabet = ASCII = 128 symbols
```

例如：

```text
é
```

不是合法输入字母表。

## 8. Lexer 匹配规则

采用经典：

### Longest Match / Maximal Munch

例如：

```text
==
```

不能识别成：

```text
=
=
```

而必须选择长度更长的：

```text
EQ
```

同理：

```text
function
```

虽然也可以被：

```text
IDENT
```

接受，但两个匹配长度都是 8，因此使用 rule priority：

```text
KW_FUNCTION priority = 0
IDENT        priority = 40
```

于是得到：

```text
KW_FUNCTION
```

而：

```text
functionx
```

会因为 IDENT 可以匹配 9 个字符：

```text
IDENT(functionx)
```

## 9. 测试

运行：

```bash
./funny_hw1
```

最后会看到：

```text
=== TESTS ===
[PASS] ...
...
Tests: XX/XX passed
```

覆盖：

- 空字符串；
- 空格；
- tab；
- CR；
- LF；
- `0`；
- `00`；
- `01`；
- 普通整数；
- `_`；
- `_abc123`；
- `abc_`；
- 全部指定 keyword；
- keyword 前缀；
- `()[]{},;`；
- `+ - * /`；
- `== != <= >= < > =`；
- `//...`；
- 注释后继续 token；
- 非法 ASCII 字符；
- 非 ASCII 字符。

## 10. DFA 输出

### JSON

`funny_dfa.json`：

```json
{
  "alphabet": "ASCII",
  "alphabet_size": 128,
  "start": 0,
  "states": 123,
  "accepting": {
    "1": "IDENT"
  },
  "transitions": [
    [ ... ]
  ]
}
```

实际 state 数由构造算法运行结果决定，不应该手工写死。

### CSV

`funny_dfa.csv`：

```text
state,accept,0,1,2,...,127
0,-,...
1,IDENT,...
...
```

可以直接用于后续 T0 lexer。

## 11. 关于 COMMENT 和 WS

两者仍然是 DFA accepting rule：

```text
WS       -> TOK_SKIP
COMMENT  -> TOK_SKIP
```

Lexer 在输出 token 时可以：

```c
if (RULES[rule].kind == TOK_SKIP)
    continue;
```

因此：

```text
"   \t\r\n"
```

不会产生普通 token；测试输出也不会打印 `SKIP`。

## 12. 与 T0 集成

后续 T0 可以直接复用：

```text
funny_dfa.json
```

或者直接从：

```text
main.c
```

中提取：

```text
min_t
min_acc
min_start
```

lexer 核心只需要：

```c
state = start;

for each input character:
    state = transition[state][character];

if accepting[state]:
    emit token;
```

生产版 lexer 建议继续保留：

```text
maximal munch
priority
skip
error/trap
```

这四个机制。

## 13. 报告中建议写的结果

运行程序以后，把实际打印出的：

```text
NFA states: ...
DFA states before minimization: ...
Minimized DFA states: ...
```

填入报告。

不要在报告中手工猜测 state 数。

推荐报告结构：

```text
1. 实验目的
2. Funny token regex specification
3. Thompson NFA construction
4. Subset construction
5. Hopcroft minimization
6. Trap state
7. Lexer maximal munch
8. Test cases
9. DFA size before/after minimization
10. JSON/CSV export
11. T0 reuse
12. Conclusion
```
