# HW2 — Funny parser

C99 recursive-descent parser with precedence climbing (LL(1) branch). It uses the **actual HW1 lexer rules and minimized DFA builder** by including `../HW1_FunnyLexer_C/main.c` under a renamed demo entry point. HW2 scans whole files with that DFA and adds 1-based line and column positions. No external library or generated lexer table is needed.

## Build and run

From `HW2_FunnyParser_C`:

```sh
gcc -std=c99 -O2 -Wall -Wextra -pedantic parser.c -o funny_parser
./funny_parser tests/contract.funny
./funny_parser < tests/contract.funny
python tests/run_tests.py ./funny_parser
```

On Windows PowerShell, build with `-o funny_parser.exe`, then run `.\funny_parser.exe tests\contract.funny` and `python tests\run_tests.py .\funny_parser.exe`. `make test` works where GNU Make is installed.

The CLI writes one JSON AST to stdout and diagnostics to stderr. Exit status is `0` for a clean parse, `1` for lexical or syntax errors, and `2` for an I/O or usage failure. A malformed input still yields a partial AST for inspection.

Example:

```funny
increment(x: int) requires x >= 0 returns y: int ensures y > x {
  y = x + 1;
}
```

The JSON starts with `Module → Function(increment)`. The function's children contain `Params`, the `requires` predicate, `Returns`, the `ensures` predicate, a `Missing` optional `uses` clause, and `Block`. For example, `x + 1` becomes a `Binary` node with `value:"+"` and `Var(x)` and `Int(1)` children.

## Grammar and operator rules

The exact implemented grammar is in [grammar.ebnf](grammar.ebnf). Function declarations follow `funny.ru.md`: they start with a name, not the word `function`. The parser also accepts formula declarations `name(typed parameters) => predicate`. Required `returns` lists have at least one typed variable. `requires`, `ensures`, `uses`, and loop `invariant` are optional. Blocks can be empty.

From weakest to strongest, operators bind as `->` (right associative), `or`, `and`, `not`, comparison, `+ -`, `* /`, unary `-`. Other binary operators associate left. `else` binds to the nearest unmatched `if`. The `=>` token declares a formula and is never an expression operator.

The parser chooses the next branch from one lookahead token, with precedence climbing for operators. On an unexpected token it reports the current token position; inside a block, recovery skips through `;`, `}`, or the next statement starter. Missing delimiters are diagnosed at the token where they were expected. Every recovery loop checks that the token cursor moves, so malformed input cannot leave a parsing loop stuck.

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

## Scope and documented differences from `funny.ru.md`

- The HW1 lexer recognizes underscores in identifiers, although the language document describes identifiers as starting with a Latin letter and containing only letters or digits. HW2 preserves HW1 tokens for integration.
- The parser accepts one unified expression grammar in arithmetic, condition, and predicate positions. Thus some type-invalid combinations can still produce AST nodes; type checking and name resolution are later phases. `->` is excluded from predicate clauses, as in the document.
- The parser permits chained comparisons, indexing a call result, and quantifier syntax in the unified expression grammar. Whether operands and nesting are meaningful is left to semantic analysis. The document specifies only one comparison at a time and `arrayAccess` from a variable.
- The document shows `a[i][j]` for functional-copy updates despite defining only `int[]`. HW2 parses and lowers that syntax; dimensional type checking is a later phase.
- HW1 recognizes `function` as a keyword for its own tests. In the documented Funny declaration grammar there is no `function` prefix, so HW2 reports it as an unexpected top-level token.
- No semantic checks are attempted for declaration uniqueness, immutable parameters, arity, definite assignment, integer range, or array bounds.

## Tests

`tests/run_tests.py` compares full JSON ASTs against three reviewed structural snapshots and checks seven negative cases for exact positioned diagnostic fragments, nonzero exit status, valid partial JSON, and termination within five seconds. The inputs cover contracts, formulas, quantifiers, loops, invariants, `if`/`else`, `assert`/`assume`, calls, tuple assignment, arrays, operator precedence, unclosed delimiters, a cross-line error, an extra token, a wrong assignment operator, a bad integer, and empty input.

The repository contains `funny.ru.md` but no P03/P04 handout files, so that document is the source for the concrete grammar and the differences above.
