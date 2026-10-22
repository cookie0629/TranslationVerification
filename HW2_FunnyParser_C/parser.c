/* HW2 Funny parser. C99; the DFA and token rules are the HW1 implementation. */
#define main hw1_lexer_demo_main
#include "../HW1_FunnyLexer_C/main.c"
#undef main

#include <stdarg.h>

typedef struct { const char *kind; char *text; int line, col; } Token;
typedef struct Node {
    const char *kind;
    char *value;
    int line, col, count, capacity;
    struct Node **children;
} Node;

static Token *tokens;
static int token_count, token_capacity, cursor, errors;
static int *scanner_table, *scanner_accept, scanner_start, scanner_sink;

static void *checked_alloc(size_t n) {
    void *p = malloc(n ? n : 1);
    if (!p) { fputs("out of memory\n", stderr); exit(2); }
    return p;
}

static char *copy_text(const char *s, size_t n) {
    char *p = checked_alloc(n + 1);
    memcpy(p, s, n);
    p[n] = 0;
    return p;
}

static void diagnostic(int line, int col, const char *fmt, ...) {
    va_list ap;
    fprintf(stderr, "%d:%d: error: ", line, col);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    errors++;
}

static void append_token(const char *kind, const char *s, int length, int line, int col) {
    if (token_count == token_capacity) {
        token_capacity = token_capacity ? token_capacity * 2 : 128;
        Token *p = realloc(tokens, (size_t)token_capacity * sizeof(*tokens));
        if (!p) { fputs("out of memory\n", stderr); exit(2); }
        tokens = p;
    }
    tokens[token_count++] = (Token){kind, copy_text(s, (size_t)length), line, col};
}

static void advance_position(const char *s, int n, int *line, int *col) {
    for (int i = 0; i < n; i++) {
        if (s[i] == '\n') { (*line)++; *col = 1; }
        else (*col)++;
    }
}

static void initialize_scanner(void) {
    int start = new_nfa_state();
    for (int r = 0; r < RULE_COUNT; r++) {
        Frag f = build_rule_nfa(RULES[r].regex);
        add_edge(start, f.start, 0, true);
        nfa[f.end].accept_rule = r;
    }
    build_dfa(start);
    Cdfa complete = complete_dfa();
    (void)minimize_hopcroft(&complete, &scanner_table, &scanner_accept, &scanner_start);
    /* '@' has no HW1 rule; its transition reaches the non-accepting sink. */
    scanner_sink = scanner_table[scanner_start * ASCII_N + '@'];
    free_cdfa(&complete);
}

static void tokenize(const char *source) {
    int length = (int)strlen(source), offset = 0, line = 1, col = 1;
    while (offset < length) {
        int state = scanner_start, best_rule = -1, best_end = offset;
        int j = offset;
        while (j < length && (unsigned char)source[j] < ASCII_N) {
            state = scanner_table[state * ASCII_N + (unsigned char)source[j++]];
            if (state == scanner_sink) break;
            int rule = scanner_accept[state];
            if (rule >= 0) { best_rule = rule; best_end = j; }
        }
        if (best_rule < 0) {
            unsigned char c = (unsigned char)source[offset];
            if (c >= ASCII_N) diagnostic(line, col, "non-ASCII byte 0x%02X", c);
            else diagnostic(line, col, "invalid character '%c'", c);
            advance_position(source + offset, 1, &line, &col);
            offset++;
            continue;
        }
        int n = best_end - offset;
        if (RULES[best_rule].kind == TOK_BAD_INT)
            diagnostic(line, col, "integer with leading zero: %.*s", n, source + offset);
        else if (RULES[best_rule].kind != TOK_SKIP)
            append_token(RULES[best_rule].name, source + offset, n, line, col);
        advance_position(source + offset, n, &line, &col);
        offset = best_end;
    }
    append_token("EOF", "", 0, line, col);
}

static Token *current(void) { return &tokens[cursor]; }
static bool is(const char *kind) { return strcmp(current()->kind, kind) == 0; }
static Token *take(void) { Token *t = current(); if (!is("EOF")) cursor++; return t; }
static bool accept(const char *kind) { if (is(kind)) { take(); return true; } return false; }
static bool expect(const char *kind, const char *display) {
    if (accept(kind)) return true;
    diagnostic(current()->line, current()->col, "expected %s, found %s '%s'",
               display, current()->kind, current()->text);
    return false;
}

static Node *node(const char *kind, Token *at, const char *value) {
    Node *n = checked_alloc(sizeof(*n));
    *n = (Node){kind, value ? copy_text(value, strlen(value)) : NULL,
                at->line, at->col, 0, 0, NULL};
    return n;
}

static void child(Node *parent, Node *item) {
    if (parent->count == parent->capacity) {
        parent->capacity = parent->capacity ? parent->capacity * 2 : 4;
        Node **p = realloc(parent->children, (size_t)parent->capacity * sizeof(*p));
        if (!p) { fputs("out of memory\n", stderr); exit(2); }
        parent->children = p;
    }
    parent->children[parent->count++] = item;
}

static Node *missing(void) { return node("Missing", current(), NULL); }
static Node *parse_expression(int min_prec, bool predicate);
static Node *parse_statement(void);

static int precedence(const char *kind, bool predicate) {
    if (!strcmp(kind, "ARROW")) return predicate ? 0 : 10;
    if (!strcmp(kind, "KW_OR")) return 20;
    if (!strcmp(kind, "KW_AND")) return 30;
    if (!strcmp(kind, "EQ") || !strcmp(kind, "NE") ||
        !strcmp(kind, "LT") || !strcmp(kind, "LE") ||
        !strcmp(kind, "GT") || !strcmp(kind, "GE")) return 40;
    if (!strcmp(kind, "PLUS") || !strcmp(kind, "MINUS")) return 50;
    if (!strcmp(kind, "STAR") || !strcmp(kind, "SLASH")) return 60;
    return 0;
}

static Node *parse_variable_def(bool optional_type) {
    Token *name = current();
    if (!expect("IDENT", "identifier")) {
        if (!is("EOF") && !is("COMMA") && !is("RPAREN")) take();
        return missing();
    }
    Node *def = node("VarDef", name, name->text);
    if (accept("COLON")) {
        Token *type = current();
        expect("KW_INT", "int");
        Node *t = node("Type", type, accept("LBRACKET") ? "int[]" : "int");
        if (!strcmp(t->value, "int[]")) expect("RBRACKET", "']'");
        child(def, t);
    } else if (!optional_type) {
        diagnostic(current()->line, current()->col, "expected ':' and type after %s", name->text);
        child(def, missing());
    } else child(def, missing());
    return def;
}

static Node *parse_def_list(const char *kind, bool optional_type, bool nonempty) {
    Node *list = node(kind, current(), NULL);
    if (is("RPAREN") || is("KW_ENSURES") || is("KW_USES") ||
        is("LBRACE") || is("EOF")) {
        if (nonempty) diagnostic(current()->line, current()->col, "expected variable definition");
        return list;
    }
    child(list, parse_variable_def(optional_type));
    while (accept("COMMA")) {
        int before = cursor;
        child(list, parse_variable_def(optional_type));
        if (cursor == before && !is("EOF")) take();
    }
    return list;
}

static Node *parse_primary(bool predicate) {
    Token *t = current();
    if (is("INT")) { take(); return node("Int", t, t->text); }
    if (is("KW_TRUE") || is("KW_FALSE")) { take(); return node("Bool", t, t->text); }
    if (is("IDENT") || is("KW_LENGTH")) {
        take();
        Node *base = node("Var", t, t->text);
        for (;;) {
            if (is("LPAREN") && !strcmp(base->kind, "Var")) {
                take();
                Node *call = node("Call", t, t->text);
                if (!is("RPAREN")) {
                    child(call, parse_expression(1, predicate));
                    while (accept("COMMA")) child(call, parse_expression(1, predicate));
                }
                expect("RPAREN", "')'");
                base = call;
            } else if (accept("LBRACKET")) {
                Node *index = node("Index", t, NULL);
                child(index, base);
                child(index, parse_expression(1, predicate));
                expect("RBRACKET", "']'");
                base = index;
            } else break;
        }
        return base;
    }
    if (is("KW_FORALL") || is("KW_EXISTS")) {
        take();
        Node *q = node("Quantifier", t, t->text);
        expect("LPAREN", "'('");
        child(q, parse_variable_def(false));
        expect("PIPE", "'|'");
        child(q, parse_expression(1, true));
        expect("RPAREN", "')'");
        return q;
    }
    if (is("MINUS") || is("KW_NOT")) {
        take();
        Node *unary = node("Unary", t, t->text);
        child(unary, parse_expression(!strcmp(t->kind, "MINUS") ? 70 : 35, predicate));
        return unary;
    }
    if (accept("LPAREN")) {
        Node *inside = parse_expression(1, predicate);
        expect("RPAREN", "')'");
        return inside;
    }
    diagnostic(t->line, t->col, "expected expression, found %s '%s'", t->kind, t->text);
    if (!is("EOF") && !is("RPAREN") && !is("RBRACKET") &&
        !is("SEMICOLON") && !is("RBRACE") && !is("COMMA")) take();
    return missing();
}

static Node *parse_expression(int min_prec, bool predicate) {
    Node *left = parse_primary(predicate);
    for (;;) {
        int prec = precedence(current()->kind, predicate);
        if (prec < min_prec) break;
        Token *op = take();
        Node *binary = node("Binary", op, op->text);
        child(binary, left);
        child(binary, parse_expression(prec + (!strcmp(op->kind, "ARROW") ? 0 : 1), predicate));
        left = binary;
    }
    return left;
}

static bool statement_start(void) {
    return is("IDENT") || is("KW_IF") || is("KW_WHILE") ||
           is("LBRACE") || is("KW_ASSERT") || is("KW_ASSUME");
}

/* Rebuild a[i][j]=v as a=set(a,i,set(a[i],j,v)). */
static Node *lower_update(Node *target, Node *value) {
    while (!strcmp(target->kind, "Index") && target->count == 2) {
        Node *set = node("Set", &(Token){"", "", target->line, target->col}, NULL);
        child(set, target->children[0]);
        child(set, target->children[1]);
        child(set, value);
        value = set;
        target = target->children[0];
    }
    Node *assignment = node("Assign", &(Token){"", "", target->line, target->col}, NULL);
    child(assignment, target);
    child(assignment, value);
    return assignment;
}

static Node *parse_assignment(void) {
    Token *start = current();
    Node *target = parse_primary(false);
    Node *targets = node("Targets", start, NULL);
    child(targets, target);
    while (accept("COMMA")) {
        Token *t = current();
        if (expect("IDENT", "identifier after ','")) child(targets, node("Var", t, t->text));
        else if (!is("EOF")) take();
    }
    expect("ASSIGN", "'='");
    Node *value = parse_expression(1, false);
    expect("SEMICOLON", "';'");
    if (targets->count > 1) {
        if (strcmp(value->kind, "Call")) diagnostic(start->line, start->col,
            "multiple targets require a function call");
        Node *assign = node("TupleAssign", start, NULL);
        child(assign, targets);
        child(assign, value);
        return assign;
    }
    if (strcmp(target->kind, "Var") && strcmp(target->kind, "Index"))
        diagnostic(start->line, start->col, "assignment target must be a variable or array element");
    return lower_update(target, value);
}

static Node *parse_statement(void) {
    Token *start = current();
    if (accept("LBRACE")) {
        Node *block = node("Block", start, NULL);
        while (!is("RBRACE") && !is("EOF")) {
            int before = cursor;
            child(block, parse_statement());
            if (cursor == before && !is("EOF")) take();
        }
        expect("RBRACE", "'}'");
        return block;
    }
    if (accept("KW_IF")) {
        Node *n = node("If", start, NULL);
        expect("LPAREN", "'('");
        child(n, parse_expression(1, false));
        expect("RPAREN", "')'");
        child(n, parse_statement());
        child(n, accept("KW_ELSE") ? parse_statement() : missing());
        return n;
    }
    if (accept("KW_WHILE")) {
        Node *n = node("While", start, NULL);
        expect("LPAREN", "'('");
        child(n, parse_expression(1, false));
        expect("RPAREN", "')'");
        child(n, accept("KW_INVARIANT") ? parse_expression(1, true) : missing());
        child(n, parse_statement());
        return n;
    }
    if (is("KW_ASSERT") || is("KW_ASSUME")) {
        take();
        Node *n = node(!strcmp(start->kind, "KW_ASSERT") ? "Assert" : "Assume", start, NULL);
        child(n, parse_expression(1, true));
        expect("SEMICOLON", "';'");
        return n;
    }
    if (is("IDENT")) return parse_assignment();
    diagnostic(start->line, start->col, "expected statement, found %s '%s'", start->kind, start->text);
    Node *bad = node("Error", start, NULL);
    /* Panic: stop before the next statement or closing brace. */
    if (!is("EOF") && !is("RBRACE")) take();
    while (!is("EOF") && !is("RBRACE") && !statement_start()) {
        if (accept("SEMICOLON")) break;
        take();
    }
    return bad;
}

static Node *parse_declaration(void) {
    Token *name = current();
    expect("IDENT", "function or formula name");
    expect("LPAREN", "'('");
    Node *params = parse_def_list("Params", false, false);
    expect("RPAREN", "')'");
    if (accept("IMPLIES")) {
        Node *formula = node("Formula", name, name->text);
        child(formula, params);
        child(formula, parse_expression(1, true));
        return formula;
    }
    Node *fn = node("Function", name, name->text);
    child(fn, params);
    child(fn, accept("KW_REQUIRES") ? parse_expression(1, true) : missing());
    expect("KW_RETURNS", "returns");
    child(fn, parse_def_list("Returns", false, true));
    child(fn, accept("KW_ENSURES") ? parse_expression(1, true) : missing());
    child(fn, accept("KW_USES") ? parse_def_list("Uses", true, true) : missing());
    child(fn, parse_statement());
    return fn;
}

static Node *parse_module(void) {
    Node *module = node("Module", current(), NULL);
    if (is("EOF")) diagnostic(current()->line, current()->col, "empty program: expected a function or formula");
    while (!is("EOF")) {
        int before = cursor;
        if (is("IDENT")) child(module, parse_declaration());
        else {
            diagnostic(current()->line, current()->col, "expected function or formula name, found %s '%s'",
                       current()->kind, current()->text);
            take();
        }
        if (cursor == before && !is("EOF")) take();
    }
    return module;
}

static void json_string(const char *s) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p == '\n') fputs("\\n", stdout);
        else if (*p == '\r') fputs("\\r", stdout);
        else if (*p == '\t') fputs("\\t", stdout);
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static void print_node(const Node *n, int depth) {
    printf("{\"kind\":"); json_string(n->kind);
    if (n->value) { printf(",\"value\":"); json_string(n->value); }
    printf(",\"line\":%d,\"column\":%d,\"children\":[", n->line, n->col);
    for (int i = 0; i < n->count; i++) {
        if (i) putchar(',');
        if (depth < 256) print_node(n->children[i], depth + 1);
        else fputs("null", stdout);
    }
    fputs("]}", stdout);
}

static char *read_source(FILE *f) {
    size_t size = 0, cap = 4096;
    char *s = checked_alloc(cap);
    for (;;) {
        if (size + 4096 + 1 > cap) { cap *= 2; char *p = realloc(s, cap); if (!p) exit(2); s = p; }
        size_t n = fread(s + size, 1, 4096, f);
        size += n;
        if (n < 4096) {
            if (ferror(f)) { perror("read"); exit(2); }
            break;
        }
    }
    s[size] = 0;
    return s;
}

int main(int argc, char **argv) {
    if (argc > 2) { fprintf(stderr, "usage: %s [file.funny]\n", argv[0]); return 2; }
    FILE *f = argc == 2 ? fopen(argv[1], "rb") : stdin;
    if (!f) { perror(argv[1]); return 2; }
    char *source = read_source(f);
    if (f != stdin) fclose(f);
    initialize_scanner();
    tokenize(source);
    Node *module = parse_module();
    print_node(module, 0);
    putchar('\n');
    free(source);
    free(scanner_table);
    free(scanner_accept);
    return errors ? 1 : 0;
}
