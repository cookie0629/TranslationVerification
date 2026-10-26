# HW2 — Funny parser

C99 recursive-descent parser with precedence climbing (LL(1) branch). It uses the **actual HW1 lexer rules and minimized DFA builder** by including `../HW1_FunnyLexer_C/main.c` under a renamed demo entry point. HW2 scans whole files with that DFA and adds 1-based line and column positions. No external library or generated lexer table is needed.

## Build and run

From `HW2_FunnyParser_C`:

```sh
gcc -std=c99 -O2 -Wall -Wextra -pedantic parser.c -o funny_parser
./funny_parser tests/contract.funny
./funny_parser tests/unclosed.funny
./funny_parser --json tests/contract.funny
./funny_parser < tests/contract.funny
python tests/run_tests.py ./funny_parser
```

On Windows PowerShell, build with `-o funny_parser.exe`, then run `.\funny_parser.exe .\tests\unclosed.funny` and `python tests\run_tests.py .\funny_parser.exe`. `make test` works where GNU Make is installed.

By default the CLI prints a readable indented AST tree. On errors, diagnostics are shown **first**, followed by a clearly marked partial tree. For tools, `--json` writes the original compact JSON AST to stdout and positioned diagnostics to stderr. HW3 and the snapshot tests invoke `--json`. Exit status is `0` for a clean parse, `1` for lexical or syntax errors, and `2` for an I/O or usage failure.

For the teacher's example, `.\funny_parser.exe .\tests\unclosed.funny` now starts like this:

```text
Diagnostics (1):
1:40: error: expected ')', found ';' (SEMICOLON)

Partial AST:
- Module [1:1]
  - Function bad [1:1]
    - params: Params [1:5]
      - VarDef x [1:5]
        - Type int [1:8]
    - requires: (omitted)
    - returns: Returns [1:21]
    ...
```

There is no raw JSON in this interactive output. `--json` preserves the HW2→HW3 machine interface.

Example:

```funny
increment(x: int) requires x >= 0 returns y: int ensures y > x {
  y = x + 1;
}
```

The tree starts with `Module → Function(increment)`. In JSON mode the function's children contain `Params`, the `requires` predicate, `Returns`, the `ensures` predicate, a `Missing` optional `uses` clause, and `Block`. For example, `x + 1` becomes a `Binary` node with `value:"+"` and `Var(x)` and `Int(1)` children.

## Grammar and operator rules

The complete implemented grammar is in [grammar.ebnf](grammar.ebnf). Its first section defines the lexical tokens `IDENT`, `INT`, `BAD_INT`, whitespace and comments, plus all reserved words and punctuation. `IDENT` means `[A-Za-z_][A-Za-z0-9_]*` **only after keyword priority is applied**. Thus `requires` is a keyword, `requiresx` is an identifier, and `_x` is an identifier in this HW1-based implementation. `INT` is `0|[1-9][0-9]*`; `01` and `00` are lexical errors. The grammar explicitly defines `EOF` and duplicates the condition and predicate operator levels so implication cannot be nested inside a predicate's parentheses or call arguments.

Function declarations follow [the Funny language specification](../TVDSL/funny.ru.md): they start with a name, not the word `function`. The parser also accepts formula declarations `name(typed parameters) => predicate`. Required `returns` lists have at least one typed variable. `requires`, `ensures`, `uses`, and loop `invariant` are optional. Blocks can be empty. Formula declarations have no terminating semicolon in this implementation.

From weakest to strongest, operators bind as `->` (right associative), `or`, `and`, `not`, comparison, `+ -`, `* /`, unary `-`. Other binary operators associate left. `else` binds to the nearest unmatched `if`. The `=>` token declares a formula and is never an expression operator.

The parser chooses the next branch from one lookahead token, with precedence climbing for operators. `IDENT` at the start of a statement is factored into assignment alternatives; an optional `else` attaches to the nearest unmatched `if`. The grammar documents this disambiguation rather than claiming that the dangling-`else` production alone is conflict-free LL(1).

On an unexpected token the parser reports its 1-based source position and the expected spelling. Within a block, panic recovery skips to `;`, `}`, or the next statement starter. At module level it skips to the next plausible declaration head (`IDENT` followed by `(`). Missing delimiters are diagnosed where they were expected. Each recovery loop advances the token cursor, so malformed input cannot trap the parser.

## AST API (JSON schema v1)

Every node has `kind`, `line`, `column`, and `children`. Some nodes also have `value`. Positions are 1-based and point to the node's first token; list and `Missing` nodes point to the current token when constructed. The order of `children` is stable:

| Kind | `value` | Children |
| --- | --- | --- |
| `Module` | — | Declarations in source order |
| `Function` | name | `Params`, requires or `Missing`, `Returns`, ensures or `Missing`, `Uses` or `Missing`, body |
| `Formula` | name | `Params`, predicate |
| `Params`, `Returns`, `Uses`, `Targets`, `Block` | — | Items in source order |
| `VarDef` | name | `Type` or `Missing` for an inferred local type |
| `Type` | `int` or `int[]` | — |
| `Assign` | — | target `Var`, value |
| `TupleAssign` | — | `Targets`, call |
| `Set` | — | source array, index, new element; functional-copy update |
| `If` | — | condition, then statement, else statement or `Missing` |
| `While` | — | condition, invariant or `Missing`, body |
| `Assert`, `Assume` | — | predicate |
| `Binary`, `Unary` | operator spelling | operands in evaluation order |
| `Call` | function or formula name | Arguments in source order |
| `Index` | — | array expression, index expression |
| `Var`, `Int`, `Bool` | source spelling | — |
| `Quantifier` | `forall` or `exists` | typed variable, predicate |
| `Missing`, `Error` | — | — |

`a[i] = v;` is represented as `Assign(Var(a), Set(Var(a), i, v))`. Nested updates are lowered from the innermost index out; the AST uses `Set` only as a semantic operation and does not expose it as a Funny function call. Downstream phases should reject `Missing`/`Error` nodes or use the nonzero exit status.

## Scope and documented differences from the Funny language specification

- The HW1 lexer recognizes underscores in identifiers, although the language document describes identifiers as starting with a Latin letter and containing only letters or digits. HW2 preserves HW1 tokens for integration.
- The parser accepts one unified expression grammar in arithmetic, condition, and predicate positions. Thus some type-invalid combinations can still produce AST nodes; type checking and name resolution are later phases. `->` is excluded from predicate clauses, as in the document.
- The parser permits chained comparisons, indexing a call result, and quantifier syntax in the unified expression grammar. Whether operands and nesting are meaningful is left to semantic analysis. The document specifies only one comparison at a time and `arrayAccess` from a variable.
- The document shows `a[i][j]` for functional-copy updates despite defining only `int[]`. HW2 parses and lowers that syntax; dimensional type checking is a later phase.
- HW1 recognizes `function` as a keyword for its own tests. In the documented Funny declaration grammar there is no `function` prefix, so HW2 reports it as an unexpected top-level token.
- No semantic checks are attempted for declaration uniqueness, immutable parameters, arity, definite assignment, integer range, or array bounds.

## Tests

`tests/run_tests.py` compares full JSON ASTs against three reviewed structural snapshots and checks seven negative cases for exact positioned diagnostic fragments, nonzero exit status, valid partial JSON, and termination within five seconds. It also checks the readable terminal layout and the `IDENT`/keyword boundary. The eleven test programs cover contracts, formulas, quantifiers, loops, invariants, `if`/`else`, `assert`/`assume`, calls, tuple assignment, arrays, operator precedence, unclosed delimiters, a cross-line error, an extra token, a wrong assignment operator, a bad integer, recovery at the next declaration, and empty input.

The repository contains [TVDSL/funny.ru.md](../TVDSL/funny.ru.md) but no P03/P04 handout files, so that document is the source for the concrete grammar and the differences above.

A short Russian explanation of the lexical rules, parsing choices, and panic-mode synchronization is in [GRAMMAR_AND_ERRORS.ru.md](GRAMMAR_AND_ERRORS.ru.md).
