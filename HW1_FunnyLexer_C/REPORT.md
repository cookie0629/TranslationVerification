


# HW1 实验报告模板

## 1. 实验目的

本实验使用 C99 实现 Funny 语言词法自动机生成器，完成：

Regex → Thompson ε-NFA → subset DFA → Hopcroft Min-DFA → transition table。

## 2. 实验环境

- Language: C99
- Compiler: GCC / MinGW / MSVC
- Alphabet: ASCII, 128 symbols
- External dependencies: none

## 3. Regular expressions

见 `README.md` 中的完整规则表。

## 4. 构造过程

### 4.1 Thompson

每个 token regex 独立构造 ε-NFA，再通过超级起点的 ε-transition 合并。

### 4.2 Subset construction

DFA state 使用 NFA-state bitset 表示，并计算 epsilon closure。

### 4.3 Hopcroft

初始 partition 按 token rule 区分 accepting states，避免不同 token 类型在最小化时被错误合并。

## 5. Trap

DFA 对 ASCII 0..127 完整化。

所有不存在的转移进入 non-accepting sink/trap。

非 ASCII 输入不属于 DFA alphabet，因此直接报 lexical error。

## 6. Lexer policy

采用 maximal munch。

若多个规则匹配相同长度，使用 priority 决定 token。

`WS` 与 `COMMENT` 为 skip。

`BAD_INT = 0[0-9]+` 用于满足题目要求的 `00` / `01` negative cases。

## 7. 实际实验数据

运行：

```bash
./funny_hw1
```

填写：

```text
NFA states: ______
DFA states before minimization: ______
Minimized DFA states: ______
Tests: ______ / ______
```

## 8. 测试结果

全部测试应为 PASS。

重点：

```text
0       -> INT
00      -> ERROR
01      -> ERROR
function -> KW_FUNCTION
functionx -> IDENT
==      -> EQ
// ...  -> SKIP
é       -> ERROR
```

## 9. 输出

- `funny_dfa.json`
- `funny_dfa.csv`

用于后续 T0 lexer。

Regex → NFA → DFA → минимизированный DFA.

Сначала я использовал алгоритм Томпсона для построения ε-НКА из регулярных выражений Funny. Затем методом subset construction преобразовал НКА в ДКА. После этого применил алгоритм Хопкрофта для минимизации ДКА.

Для алфавита использовал ASCII из 128 символов и добавил trap state для символов, которые не покрываются ни одним правилом.

Для lexer также реализован maximal munch: выбирается самое длинное совпадение, а при одинаковой длине используется приоритет правил. WS и COMMENT помечены как skip.

Я также добавил тесты для ключевых слов, идентификаторов, чисел, операторов, разделителей, комментариев, `0`, `00`, `01`, пустой строки и non-ASCII символов.

В моей реализации было 79 состояний ДКА до минимизации и 77 состояний после минимизации. Все 30 тестов прошли успешно.



Обычный DFA может объединять эквивалентные принимающие состояния, но для lexer нужно сохранять тип токена. Например, if и обычный IDENT могут оба быть принимающими, но результат должен быть разным: KW_IF и IDENT. Поэтому начальное разбиение при минимизации учитывает тип token rule.

中文：

普通 DFA 最小化时，可以把等价的接受状态合并。但 Lexer 必须保留 Token 类型。例如 if 和普通标识符都是接受状态，但是最终结果分别必须是 KW_IF 和 IDENT。所以在 Hopcroft 最小化时，我按照 Token rule 对接受状态进行了区分。

• 它是怎么工作的？
它的核心思想是“切蛋糕”（划分与精炼）。
	1. 初始划分：首先把 DFA 的所有状态分成两大类——接收状态（终态）和非接收状态（非终态）。
	2. 不断迭代切分：检查每一个分组。如果一个分组里的状态 \(A\) 和状态 \(B\)，在输入同一个字符 \(x\) 时，分别跳到了不同的分组里，说明 \(A\) 和 \(B\) 其实不等价！算法就会把这个分组切开。
	3. 结束条件：重复这个切分过程，直到没有任何一个分组可以再被切开为止。此时，留在同一个分组里的状态就是完全等价的，可以直接合并为一个状态。

• 它的核心思想是“打包”。算法从 NFA 的起始状态出发，找出所有通过 \(\varepsilon \)（空转移）能到达的状态，把它们打包成一个“子集”。这个“子集”就成了新 DFA 的一个新状态。
	• 核心概念 \(\varepsilon\text{-closure}\)（空闭包）：从某个状态出发，不读任何字符，光靠空转移能走到的所有状态的集合。
	• 通过不断计算各个字符引发的转移和空闭包，直到没有新的子集产生，DFA 就构建完成了。

它将复杂的正则表达式拆解为最基本的简单元素，为每个元素构建一个微型的 NFA，然后通过特定的规则（使用 ε-转移，即不需要读入字符就能发生的状态跳转）将它们拼装成一个完整的大型 NFA。