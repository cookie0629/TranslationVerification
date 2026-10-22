/*
 * HW1 - Funny lexer automaton
 * C99, no external dependencies.
 *
 * Pipeline:
 *   regex list -> Thompson NFA -> subset DFA -> Hopcroft minimization
 *   -> transition table / lexer / tests / JSON export
 *
 * Build:
 *   gcc -std=c99 -O2 -Wall -Wextra -pedantic main.c -o funny_hw1
 * Run:
 *   ./funny_hw1
 *
 * The implementation uses ASCII alphabet 0..127.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>

#define ASCII_N 128
#define MAX_NFA_STATES 4096
#define MAX_DFA_STATES 4096
#define MAX_REGEX_LEN 512
#define MAX_TEST_LEN 512
#define MAX_TOKEN_TEXT 512

typedef enum {
    TOK_SKIP = 0,
    TOK_KEYWORD,
    TOK_IDENT,
    TOK_INT,
    TOK_BAD_INT,
    TOK_OPERATOR,
    TOK_DELIM
} TokenKind;

typedef struct {
    const char *name;
    const char *regex;
    TokenKind kind;
    int priority;
} Rule;

static const Rule RULES[] = {
    /* Equal-length matches use smaller priority first. */
    {"KW_FUNCTION", "function", TOK_KEYWORD, 0},
    {"KW_RETURNS", "returns", TOK_KEYWORD, 1},
    {"KW_WHILE", "while", TOK_KEYWORD, 2},
    {"KW_IF", "if", TOK_KEYWORD, 3},
    {"KW_ELSE", "else", TOK_KEYWORD, 4},
    {"KW_ASSERT", "assert", TOK_KEYWORD, 5},
    {"KW_ASSUME", "assume", TOK_KEYWORD, 6},
    {"KW_INVARIANT", "invariant", TOK_KEYWORD, 7},
    {"KW_LENGTH", "length", TOK_KEYWORD, 8},
    /* Keywords of the Funny specification (funny.ru.md) that the parser of
       HW2 needs: pre/postconditions, formula quantifiers and boolean logic.
       Priorities 9..19 fill the gap up to BAD_INT, so a keyword still wins
       over IDENT on an equal-length match. */
    {"KW_REQUIRES", "requires", TOK_KEYWORD, 9},
    {"KW_ENSURES", "ensures", TOK_KEYWORD, 10},
    {"KW_USES", "uses", TOK_KEYWORD, 11},
    {"KW_FORALL", "forall", TOK_KEYWORD, 12},
    {"KW_EXISTS", "exists", TOK_KEYWORD, 13},
    {"KW_TRUE", "true", TOK_KEYWORD, 14},
    {"KW_FALSE", "false", TOK_KEYWORD, 15},
    {"KW_NOT", "not", TOK_KEYWORD, 16},
    {"KW_AND", "and", TOK_KEYWORD, 17},
    {"KW_OR", "or", TOK_KEYWORD, 18},
    {"KW_INT", "int", TOK_KEYWORD, 19},

    {"BAD_INT", "0[0-9]+", TOK_BAD_INT, 20},
    {"INT", "0|[1-9][0-9]*", TOK_INT, 30},
    {"IDENT", "[A-Za-z_][A-Za-z0-9_]*", TOK_IDENT, 40},

    {"EQ", "==", TOK_OPERATOR, 50},
    {"NE", "!=", TOK_OPERATOR, 51},
    {"LE", "<=", TOK_OPERATOR, 52},
    {"GE", ">=", TOK_OPERATOR, 53},
    {"LT", "<", TOK_OPERATOR, 54},
    {"GT", ">", TOK_OPERATOR, 55},
    {"ASSIGN", "=", TOK_OPERATOR, 56},
    {"PLUS", "\\+", TOK_OPERATOR, 57},
    {"MINUS", "-", TOK_OPERATOR, 58},
    {"STAR", "\\*", TOK_OPERATOR, 59},
    {"SLASH", "/", TOK_OPERATOR, 60},
    /* "=>" introduces a formula, "->" is implication; maximal munch keeps
       them apart from "=" and "-". */
    {"IMPLIES", "=>", TOK_OPERATOR, 61},
    {"ARROW", "->", TOK_OPERATOR, 62},

    {"LPAREN", "\\(", TOK_DELIM, 70},
    {"RPAREN", "\\)", TOK_DELIM, 71},
    {"LBRACKET", "\\[", TOK_DELIM, 72},
    {"RBRACKET", "\\]", TOK_DELIM, 73},
    {"LBRACE", "\\{", TOK_DELIM, 74},
    {"RBRACE", "\\}", TOK_DELIM, 75},
    {"COMMA", ",", TOK_DELIM, 76},
    {"SEMICOLON", ";", TOK_DELIM, 77},
    {"COLON", ":", TOK_DELIM, 78},
    {"PIPE", "\\|", TOK_DELIM, 79},

    {"WS", "[ \\t\\r\\n]+", TOK_SKIP, 90},
    {"COMMENT", "//[^\\r\\n]*", TOK_SKIP, 91},
};
#define RULE_COUNT ((int)(sizeof(RULES) / sizeof(RULES[0])))

/* ------------------------- NFA ------------------------- */

typedef struct {
    int to;
    int next;
    unsigned char ch;
    bool epsilon;
} NfaEdge;

typedef struct {
    int first_edge;
    int accept_rule; /* -1 for non-accepting */
} NfaState;

static NfaState nfa[MAX_NFA_STATES];
static NfaEdge nfa_edges[MAX_NFA_STATES * 8];
static int nfa_n = 0, edge_n = 0;

static int new_nfa_state(void) {
    if (nfa_n >= MAX_NFA_STATES) {
        fprintf(stderr, "NFA state limit exceeded\n");
        exit(2);
    }
    nfa[nfa_n].first_edge = -1;
    nfa[nfa_n].accept_rule = -1;
    return nfa_n++;
}

static void add_edge(int from, int to, int ch, bool epsilon) {
    if (edge_n >= (int)(sizeof(nfa_edges) / sizeof(nfa_edges[0]))) {
        fprintf(stderr, "NFA edge limit exceeded\n");
        exit(2);
    }
    nfa_edges[edge_n].to = to;
    nfa_edges[edge_n].next = nfa[from].first_edge;
    nfa_edges[edge_n].ch = (unsigned char)ch;
    nfa_edges[edge_n].epsilon = epsilon;
    nfa[from].first_edge = edge_n++;
}

/* ------------------------- Regex parser ------------------------- */

typedef struct {
    const char *s;
    int pos;
} RegexParser;

typedef struct {
    int start, end;
} Frag;

static Frag frag_epsilon(void) {
    Frag f = {new_nfa_state(), new_nfa_state()};
    add_edge(f.start, f.end, 0, true);
    return f;
}

static Frag frag_char(int ch) {
    Frag f = {new_nfa_state(), new_nfa_state()};
    add_edge(f.start, f.end, ch, false);
    return f;
}

static Frag frag_charset(const bool set[ASCII_N]) {
    Frag f = {new_nfa_state(), new_nfa_state()};
    for (int c = 0; c < ASCII_N; ++c)
        if (set[c]) add_edge(f.start, f.end, c, false);
    return f;
}

static Frag concat_frag(Frag a, Frag b) {
    add_edge(a.end, b.start, 0, true);
    Frag r = {a.start, b.end};
    return r;
}

static Frag alt_frag(Frag a, Frag b) {
    Frag r = {new_nfa_state(), new_nfa_state()};
    add_edge(r.start, a.start, 0, true);
    add_edge(r.start, b.start, 0, true);
    add_edge(a.end, r.end, 0, true);
    add_edge(b.end, r.end, 0, true);
    return r;
}

static Frag star_frag(Frag a) {
    Frag r = {new_nfa_state(), new_nfa_state()};
    add_edge(r.start, r.end, 0, true);
    add_edge(r.start, a.start, 0, true);
    add_edge(a.end, r.end, 0, true);
    add_edge(a.end, a.start, 0, true);
    return r;
}

static Frag plus_frag(Frag a) {
    Frag r = {new_nfa_state(), new_nfa_state()};
    add_edge(r.start, a.start, 0, true);
    add_edge(a.end, r.end, 0, true);
    add_edge(a.end, a.start, 0, true);
    return r;
}

static Frag question_frag(Frag a) {
    Frag r = {new_nfa_state(), new_nfa_state()};
    add_edge(r.start, r.end, 0, true);
    add_edge(r.start, a.start, 0, true);
    add_edge(a.end, r.end, 0, true);
    return r;
}

static int escaped_char(RegexParser *p) {
    char c = p->s[p->pos++];
    switch (c) {
        case 'n': return '\n';
        case 'r': return '\r';
        case 't': return '\t';
        case '\\': return '\\';
        case '[': return '[';
        case ']': return ']';
        case '(': return '(';
        case ')': return ')';
        case '{': return '{';
        case '}': return '}';
        case '+': return '+';
        case '*': return '*';
        case '?': return '?';
        case '|': return '|';
        case '-': return '-';
        case '^': return '^';
        default: return (unsigned char)c;
    }
}

static void parse_charset(RegexParser *p, bool set[ASCII_N]) {
    memset(set, 0, ASCII_N * sizeof(bool));
    if (p->s[p->pos] != '[') {
        fprintf(stderr, "internal charset parser error\n");
        exit(2);
    }
    p->pos++;
    bool negated = false;
    if (p->s[p->pos] == '^') {
        negated = true;
        p->pos++;
    }

    bool any = false;
    while (p->s[p->pos] && p->s[p->pos] != ']') {
        int a;
        if (p->s[p->pos] == '\\') {
            p->pos++;
            a = escaped_char(p);
        } else {
            a = (unsigned char)p->s[p->pos++];
        }
        if (p->s[p->pos] == '-' && p->s[p->pos + 1] != ']' && p->s[p->pos + 1] != '\0') {
            p->pos++;
            int b;
            if (p->s[p->pos] == '\\') {
                p->pos++;
                b = escaped_char(p);
            } else {
                b = (unsigned char)p->s[p->pos++];
            }
            if (a > b || a < 0 || b >= ASCII_N) {
                fprintf(stderr, "bad character range in regex\n");
                exit(2);
            }
            for (int c = a; c <= b; ++c) set[c] = true;
        } else {
            if (a < 0 || a >= ASCII_N) {
                fprintf(stderr, "non-ASCII literal in regex\n");
                exit(2);
            }
            set[a] = true;
        }
        any = true;
    }
    if (p->s[p->pos] != ']') {
        fprintf(stderr, "unterminated character class: %s\n", p->s);
        exit(2);
    }
    p->pos++;
    if (!any) {
        fprintf(stderr, "empty character class: %s\n", p->s);
        exit(2);
    }
    if (negated) {
        for (int c = 0; c < ASCII_N; ++c) set[c] = !set[c];
    }
}

static Frag parse_expr(RegexParser *p);

static Frag parse_atom(RegexParser *p) {
    char c = p->s[p->pos];
    if (c == '\0' || c == ')' || c == '|') return frag_epsilon();

    if (c == '(') {
        p->pos++;
        Frag f = parse_expr(p);
        if (p->s[p->pos] != ')') {
            fprintf(stderr, "missing ')' in regex: %s\n", p->s);
            exit(2);
        }
        p->pos++;
        return f;
    }
    if (c == '[') {
        bool set[ASCII_N];
        parse_charset(p, set);
        return frag_charset(set);
    }
    if (c == '\\') {
        p->pos++;
        return frag_char(escaped_char(p));
    }
    if (c == '.') {
        p->pos++;
        bool set[ASCII_N];
        for (int i = 0; i < ASCII_N; ++i) set[i] = true;
        return frag_charset(set);
    }

    p->pos++;
    return frag_char((unsigned char)c);
}

static Frag parse_factor(RegexParser *p) {
    Frag f = parse_atom(p);
    while (1) {
        char c = p->s[p->pos];
        if (c == '*') { p->pos++; f = star_frag(f); }
        else if (c == '+') { p->pos++; f = plus_frag(f); }
        else if (c == '?') { p->pos++; f = question_frag(f); }
        else break;
    }
    return f;
}

static bool starts_atom(char c) {
    return c != '\0' && c != ')' && c != '|';
}

static Frag parse_term(RegexParser *p) {
    if (!starts_atom(p->s[p->pos])) return frag_epsilon();
    Frag f = parse_factor(p);
    while (starts_atom(p->s[p->pos])) {
        Frag g = parse_factor(p);
        f = concat_frag(f, g);
    }
    return f;
}

static Frag parse_expr(RegexParser *p) {
    Frag f = parse_term(p);
    while (p->s[p->pos] == '|') {
        p->pos++;
        Frag g = parse_term(p);
        f = alt_frag(f, g);
    }
    return f;
}

static Frag build_rule_nfa(const char *regex) {
    RegexParser p = {regex, 0};
    Frag f = parse_expr(&p);
    if (p.s[p.pos] != '\0') {
        fprintf(stderr, "unexpected regex suffix in: %s\n", regex);
        exit(2);
    }
    return f;
}

/* ------------------------- Bitsets ------------------------- */

#define WORDS ((MAX_NFA_STATES + 63) / 64)
typedef struct {
    unsigned long long w[WORDS];
} BitSet;

static void bs_clear(BitSet *b) { memset(b, 0, sizeof(*b)); }
static void bs_set(BitSet *b, int i) { b->w[i >> 6] |= 1ULL << (i & 63); }
static bool bs_test(const BitSet *b, int i) { return (b->w[i >> 6] >> (i & 63)) & 1ULL; }
static bool bs_empty(const BitSet *b) {
    for (int i = 0; i < WORDS; ++i) if (b->w[i]) return false;
    return true;
}
static bool bs_equal(const BitSet *a, const BitSet *b) {
    return memcmp(a, b, sizeof(*a)) == 0;
}

/* epsilon closure */
static void epsilon_closure(BitSet *s) {
    int stack[MAX_NFA_STATES], top = 0;
    for (int i = 0; i < nfa_n; ++i)
        if (bs_test(s, i)) stack[top++] = i;

    while (top) {
        int u = stack[--top];
        for (int e = nfa[u].first_edge; e != -1; e = nfa_edges[e].next) {
            if (nfa_edges[e].epsilon) {
                int v = nfa_edges[e].to;
                if (!bs_test(s, v)) {
                    bs_set(s, v);
                    stack[top++] = v;
                }
            }
        }
    }
}

static BitSet move_set(const BitSet *s, int ch) {
    BitSet r; bs_clear(&r);
    for (int u = 0; u < nfa_n; ++u) if (bs_test(s, u)) {
        for (int e = nfa[u].first_edge; e != -1; e = nfa_edges[e].next) {
            if (!nfa_edges[e].epsilon && nfa_edges[e].ch == (unsigned char)ch)
                bs_set(&r, nfa_edges[e].to);
        }
    }
    return r;
}

/* ------------------------- DFA ------------------------- */

typedef struct {
    BitSet subset;
    int trans[ASCII_N];
    int accept_rule;
} DfaState;

static DfaState dfa[MAX_DFA_STATES];
static int dfa_n = 0;

static int subset_index(const BitSet *b) {
    for (int i = 0; i < dfa_n; ++i)
        if (bs_equal(&dfa[i].subset, b)) return i;
    return -1;
}

static int best_accept_rule(const BitSet *s) {
    int best = -1;
    for (int u = 0; u < nfa_n; ++u) if (bs_test(s, u) && nfa[u].accept_rule >= 0) {
        int r = nfa[u].accept_rule;
        if (best < 0 || RULES[r].priority < RULES[best].priority)
            best = r;
    }
    return best;
}

static void build_dfa(int nfa_start) {
    BitSet start; bs_clear(&start); bs_set(&start, nfa_start); epsilon_closure(&start);
    dfa_n = 1;
    dfa[0].subset = start;
    dfa[0].accept_rule = best_accept_rule(&start);
    for (int c = 0; c < ASCII_N; ++c) dfa[0].trans[c] = -1;

    for (int i = 0; i < dfa_n; ++i) {
        for (int c = 0; c < ASCII_N; ++c) {
            BitSet m = move_set(&dfa[i].subset, c);
            if (bs_empty(&m)) {
                dfa[i].trans[c] = -1;
                continue;
            }
            epsilon_closure(&m);
            int j = subset_index(&m);
            if (j < 0) {
                if (dfa_n >= MAX_DFA_STATES) {
                    fprintf(stderr, "DFA state limit exceeded\n");
                    exit(2);
                }
                j = dfa_n++;
                dfa[j].subset = m;
                dfa[j].accept_rule = best_accept_rule(&m);
                for (int k = 0; k < ASCII_N; ++k) dfa[j].trans[k] = -1;
            }
            dfa[i].trans[c] = j;
        }
    }
}

/* ------------------------- Complete DFA + Hopcroft ------------------------- */

typedef struct {
    int n;
    int **t;
    int *accept;
} Cdfa;

static Cdfa complete_dfa(void) {
    Cdfa x;
    x.n = dfa_n + 1; /* explicit trap */
    x.t = (int**)calloc((size_t)x.n, sizeof(int*));
    x.accept = (int*)malloc((size_t)x.n * sizeof(int));
    if (!x.t || !x.accept) exit(2);

    for (int i = 0; i < x.n; ++i) {
        x.t[i] = (int*)malloc(ASCII_N * sizeof(int));
        if (!x.t[i]) exit(2);
        x.accept[i] = (i < dfa_n) ? dfa[i].accept_rule : -1;
    }
    int trap = x.n - 1;
    for (int i = 0; i < dfa_n; ++i)
        for (int c = 0; c < ASCII_N; ++c)
            x.t[i][c] = (dfa[i].trans[c] < 0) ? trap : dfa[i].trans[c];
    for (int c = 0; c < ASCII_N; ++c) x.t[trap][c] = trap;
    return x;
}

static void free_cdfa(Cdfa *x) {
    for (int i = 0; i < x->n; ++i) free(x->t[i]);
    free(x->t); free(x->accept);
}

/* Straightforward Hopcroft partition refinement. */
static int minimize_hopcroft(const Cdfa *x, int **out_t, int **out_acc, int *out_start) {
    int n = x->n;
    bool *is_accept = (bool*)calloc((size_t)n, sizeof(bool));
    int accept_count = 0;
    for (int i = 0; i < n; ++i) {
        if (x->accept[i] >= 0) { is_accept[i] = true; accept_count++; }
    }

    int *cls = (int*)malloc((size_t)n * sizeof(int));
    int *sizes = (int*)calloc((size_t)n, sizeof(int));
    int class_n = 0;

    /* Initial partition: one class per accepting rule + nonaccepting.
       This preserves token identity; otherwise distinct token classes could
       be merged and the lexer could no longer report token type. */
    int rule_to_class[RULE_COUNT];
    for (int i = 0; i < RULE_COUNT; ++i) rule_to_class[i] = -1;
    int nonacc_class = -1;
    for (int s = 0; s < n; ++s) {
        int r = x->accept[s];
        int c;
        if (r < 0) {
            if (nonacc_class < 0) nonacc_class = class_n++;
            c = nonacc_class;
        } else {
            if (rule_to_class[r] < 0) rule_to_class[r] = class_n++;
            c = rule_to_class[r];
        }
        cls[s] = c;
        sizes[c]++;
    }

    /* Queue all current blocks. */
    int *queue = (int*)malloc((size_t)(n * 4 + 16) * sizeof(int));
    int qh = 0, qt = 0;
    for (int c = 0; c < class_n; ++c) queue[qt++] = c;

    bool *inA = (bool*)calloc((size_t)n, sizeof(bool));
    int *mark = (int*)calloc((size_t)n, sizeof(int));
    int mark_id = 0;

    while (qh < qt) {
        int A = queue[qh++];
        mark_id++;
        for (int a = 0; a < ASCII_N; ++a) {
            /* X = states with transition on a into A */
            int xcount = 0;
            for (int s = 0; s < n; ++s) {
                if (cls[x->t[s][a]] == A) {
                    inA[s] = true;
                    xcount++;
                }
            }
            if (xcount == 0) continue;

            /* Gather affected classes. */
            int *affected = (int*)malloc((size_t)class_n * sizeof(int));
            int affected_n = 0;
            for (int s = 0; s < n; ++s) if (inA[s]) {
                int c = cls[s];
                bool seen = false;
                for (int k = 0; k < affected_n; ++k)
                    if (affected[k] == c) { seen = true; break; }
                if (!seen) affected[affected_n++] = c;
            }

            for (int ai = 0; ai < affected_n; ++ai) {
                int Y = affected[ai];
                if (sizes[Y] <= 1) continue;

                int c1 = class_n++;
                int moved = 0;

                for (int s = 0; s < n; ++s) {
                    if (cls[s] == Y && inA[s]) {
                        cls[s] = c1;
                        moved++;
                    }
                }
                if (moved == 0 || moved == sizes[Y]) {
                    class_n--;
                    for (int s = 0; s < n; ++s)
                        if (cls[s] == c1) cls[s] = Y;
                    continue;
                }
                sizes[c1] = moved;
                sizes[Y] -= moved;

                /* Standard Hopcroft queue update: if Y already queued, add
                   the new block; otherwise add the smaller half. */
                bool y_queued = false;
                for (int k = qh; k < qt; ++k)
                    if (queue[k] == Y) { y_queued = true; break; }
                if (y_queued) {
                    queue[qt++] = c1;
                } else if (sizes[Y] <= sizes[c1]) {
                    queue[qt++] = Y;
                } else {
                    queue[qt++] = c1;
                }
            }

            /* clear inA marks */
            for (int s = 0; s < n; ++s) inA[s] = false;
            (void)mark_id;
            (void)mark;
            free(affected);
        }
    }

    int *class_rep = (int*)malloc((size_t)class_n * sizeof(int));
    for (int c = 0; c < class_n; ++c) class_rep[c] = -1;
    for (int s = 0; s < n; ++s)
        if (class_rep[cls[s]] < 0) class_rep[cls[s]] = s;

    int *old_to_new = (int*)malloc((size_t)class_n * sizeof(int));
    for (int c = 0; c < class_n; ++c) old_to_new[c] = c;

    int *mt = (int*)malloc((size_t)class_n * ASCII_N * sizeof(int));
    int *ma = (int*)malloc((size_t)class_n * sizeof(int));
    for (int c = 0; c < class_n; ++c) {
        int rep = class_rep[c];
        ma[c] = x->accept[rep];
        for (int a = 0; a < ASCII_N; ++a)
            mt[c * ASCII_N + a] = cls[x->t[rep][a]];
    }

    *out_t = mt;
    *out_acc = ma;
    *out_start = cls[0];

    free(old_to_new);
    free(class_rep);
    free(mark);
    free(inA);
    free(queue);
    free(sizes);
    free(cls);
    free(is_accept);
    return class_n;
}

/* ------------------------- Lexer ------------------------- */

typedef struct {
    int rule;
    int start;
    int length;
    char text[MAX_TOKEN_TEXT];
} LexToken;


/*
 * Lexing uses longest-match. Equal lengths use rule priority.
 * BAD_INT is deliberately an error rule so "01" is a negative case.
 * Non-ASCII bytes are outside the ASCII DFA alphabet and are errors.
 */
static int lex_line(const char *s, int *t, int start_state, LexToken *out, int cap) {
    int n = (int)strlen(s), pos = 0, count = 0;
    while (pos < n) {
        unsigned char uc = (unsigned char)s[pos];
        if (uc >= ASCII_N) return -1;

        int state = start_state;
        int best_rule = -1, best_pos = pos;
        int j = pos;

        while (j < n) {
            unsigned char c = (unsigned char)s[j];
            if (c >= ASCII_N) break;
            int ns = t[state * ASCII_N + c];
            if (ns < 0) break;
            state = ns;
            j++;
            int ar = -1;
            /* Acceptance is encoded separately below through accepting state. */
            (void)ar;
            /* We need accepting rule per minimized state; handled by caller
               by storing it in global min_acc. */
            extern int *g_min_acc;
            int r = g_min_acc[state];
            if (r >= 0) {
                if (j > best_pos || (j == best_pos &&
                    (best_rule < 0 || RULES[r].priority < RULES[best_rule].priority))) {
                    best_rule = r;
                    best_pos = j;
                }
            }
        }

        if (best_rule < 0) return -1;
        if (count >= cap) return -2;

        out[count].rule = best_rule;
        out[count].start = pos;
        out[count].length = best_pos - pos;
        int copy_n = out[count].length;
        if (copy_n >= MAX_TOKEN_TEXT) copy_n = MAX_TOKEN_TEXT - 1;
        memcpy(out[count].text, s + pos, (size_t)copy_n);
        out[count].text[copy_n] = '\0';

        if (RULES[best_rule].kind == TOK_BAD_INT) return -3;
        count++;
        pos = best_pos;
    }
    return count;
}

int *g_min_acc = NULL;

/* ------------------------- Output ------------------------- */

static void print_regexes(void) {
    printf("=== REGEX SPECIFICATION ===\n");
    for (int i = 0; i < RULE_COUNT; ++i)
        printf("%2d  %-14s  %s%s\n", i, RULES[i].name, RULES[i].regex,
               RULES[i].kind == TOK_SKIP ? "  [skip]" :
               RULES[i].kind == TOK_BAD_INT ? "  [error]" : "");
    printf("\n");
}

static void export_json(const char *path, int n, const int *tr, const int *acc, int start) {
    FILE *f = fopen(path, "w");
    if (!f) { perror(path); return; }

    fprintf(f, "{\n");
    fprintf(f, "  \"alphabet\": \"ASCII\",\n");
    fprintf(f, "  \"alphabet_size\": 128,\n");
    fprintf(f, "  \"start\": %d,\n", start);
    fprintf(f, "  \"states\": %d,\n", n);
    fprintf(f, "  \"trap\": %d,\n", -1);
    fprintf(f, "  \"accepting\": {\n");
    bool first = true;
    for (int s = 0; s < n; ++s) if (acc[s] >= 0) {
        if (!first) fprintf(f, ",\n");
        fprintf(f, "    \"%d\": \"%s\"", s, RULES[acc[s]].name);
        first = false;
    }
    fprintf(f, "\n  },\n  \"transitions\": [\n");
    for (int s = 0; s < n; ++s) {
        fprintf(f, "    [");
        for (int c = 0; c < ASCII_N; ++c) {
            if (c) fprintf(f, ",");
            fprintf(f, "%d", tr[s * ASCII_N + c]);
        }
        fprintf(f, "]%s\n", s + 1 == n ? "" : ",");
    }
    fprintf(f, "  ]\n}\n");
    fclose(f);
}

typedef struct {
    const char *input;
    const char *expected;
    bool should_pass;
} Test;

static const Test TESTS[] = {
    {"", "", true},
    {"   \t\r\n", "", true},
    {"0", "INT(0)", true},
    {"00", "ERROR", false},
    {"01", "ERROR", false},
    {"12345", "INT(12345)", true},
    {"_", "IDENT(_)", true},
    {"_abc123", "IDENT(_abc123)", true},
    {"abc_", "IDENT(abc_)", true},
    {"function", "KW_FUNCTION(function)", true},
    {"returns", "KW_RETURNS(returns)", true},
    {"while", "KW_WHILE(while)", true},
    {"if", "KW_IF(if)", true},
    {"else", "KW_ELSE(else)", true},
    {"assert", "KW_ASSERT(assert)", true},
    {"assume", "KW_ASSUME(assume)", true},
    {"invariant", "KW_INVARIANT(invariant)", true},
    {"length", "KW_LENGTH(length)", true},
    {"functionx", "IDENT(functionx)", true},

    /* Tokens added for the Funny specification and the HW2 parser. */
    {"requires", "KW_REQUIRES(requires)", true},
    {"ensures", "KW_ENSURES(ensures)", true},
    {"uses", "KW_USES(uses)", true},
    {"forall", "KW_FORALL(forall)", true},
    {"exists", "KW_EXISTS(exists)", true},
    {"true", "KW_TRUE(true)", true},
    {"false", "KW_FALSE(false)", true},
    {"not", "KW_NOT(not)", true},
    {"and", "KW_AND(and)", true},
    {"or", "KW_OR(or)", true},
    {"int", "KW_INT(int)", true},
    /* A keyword only wins when the whole lexeme matches: these stay IDENT. */
    {"requiresx", "IDENT(requiresx)", true},
    {"intx", "IDENT(intx)", true},
    {"notion", "IDENT(notion)", true},
    {"ordering", "IDENT(ordering)", true},
    {"int[]", "KW_INT(int) LBRACKET([) RBRACKET(])", true},
    {"=> ->", "IMPLIES(=>) ARROW(->)", true},
    {": |", "COLON(:) PIPE(|)", true},
    {"i: int | i > 0", "IDENT(i) COLON(:) KW_INT(int) PIPE(|) IDENT(i) GT(>) INT(0)", true},
    /* Maximal munch beats the shorter rules "=" and "-". */
    {"a->b", "IDENT(a) ARROW(->) IDENT(b)", true},
    {"a-1", "IDENT(a) MINUS(-) INT(1)", true},
    {"a = => b", "IDENT(a) ASSIGN(=) IMPLIES(=>) IDENT(b)", true},
    /* Characters outside the Funny token set stay lexical errors. */
    {"%", "ERROR", false},
    {"!", "ERROR", false},
    {"a && b", "ERROR", false},
    {"()", "LPAREN(() RPAREN())", true},
    {"[]{}", "LBRACKET([) RBRACKET(]) LBRACE({) RBRACE(})", true},
    {" ,;", "COMMA(,) SEMICOLON(;)", true},
    {"+ - * /", "PLUS(+) MINUS(-) STAR(*) SLASH(/)", true},
    {"== != <= >= < > =", "EQ(==) NE(!=) LE(<=) GE(>=) LT(<) GT(>) ASSIGN(=)", true},
    {"// hello world", "", true},
    {"// hello\r\nx", "IDENT(x)", true},
    {"a_b 123 function returns", "IDENT(a_b) INT(123) KW_FUNCTION(function) KW_RETURNS(returns)", true},
    {"a@b", "ERROR", false},
    {"é", "ERROR", false},
    {"abc\x01", "ERROR", false},
};
#define TEST_COUNT ((int)(sizeof(TESTS) / sizeof(TESTS[0])))

static void run_tests(const int *tr, int start, const int *acc) {
    g_min_acc = (int*)acc;
    int passed = 0;

    printf("=== TESTS ===\n");
    for (int i = 0; i < TEST_COUNT; ++i) {
        LexToken toks[64];
        int rc = lex_line(TESTS[i].input, (int*)tr, start, toks, 64);
        char got[2048] = "";
        bool error = (rc < 0);
        if (error) {
            snprintf(got, sizeof(got), "ERROR");
        } else {
            for (int j = 0; j < rc; ++j) {
                const Rule *r = &RULES[toks[j].rule];
                if (r->kind == TOK_SKIP) {
                    /* WS / COMMENT are lexer-internal skip tokens and are
                       intentionally omitted from the public token stream. */
                    continue;
                } else {
                    char buf[700];
                    snprintf(buf, sizeof(buf), "%s(%s)", r->name, toks[j].text);
                    if (got[0]) strncat(got, " ", sizeof(got)-strlen(got)-1);
                    strncat(got, buf, sizeof(got)-strlen(got)-1);
                }
            }
        }

        bool ok;
        if (!TESTS[i].should_pass) ok = error;
        else ok = strcmp(got, TESTS[i].expected) == 0;

        printf("[%s] %-28s -> %s\n", ok ? "PASS" : "FAIL", TESTS[i].input, got);
        if (ok) passed++;
    }
    printf("Tests: %d/%d passed\n\n", passed, TEST_COUNT);
}

/*
 * A small machine-readable CSV export is also generated.
 *
 * Format ("v2"): a leading comment carries the start state and the state
 * count, which the table itself does not express.  HW2 loads this file at run
 * time to scan with the minimized automaton, and refuses a table without that
 * line instead of guessing the start state.
 */
static void export_csv(const char *path, int n, const int *tr, const int *acc, int start) {
    FILE *f = fopen(path, "w");
    if (!f) { perror(path); return; }
    fprintf(f, "# funny_dfa v2 start=%d states=%d\n", start, n);
    fprintf(f, "state,accept");
    for (int c = 0; c < ASCII_N; ++c) fprintf(f, ",%d", c);
    fprintf(f, "\n");
    for (int s = 0; s < n; ++s) {
        fprintf(f, "%d,%s", s, acc[s] >= 0 ? RULES[acc[s]].name : "-");
        for (int c = 0; c < ASCII_N; ++c) fprintf(f, ",%d", tr[s * ASCII_N + c]);
        fprintf(f, "\n");
    }
    fclose(f);
}

int main(void) {
    printf("============================================================\n");
    printf(" HW1 Funny Lexer: Regex -> NFA -> DFA -> Hopcroft Min-DFA\n");
    printf("============================================================\n\n");

    print_regexes();

    /* Global NFA start state. */
    int super_start = new_nfa_state();

    for (int r = 0; r < RULE_COUNT; ++r) {
        Frag f = build_rule_nfa(RULES[r].regex);
        add_edge(super_start, f.start, 0, true);
        nfa[f.end].accept_rule = r;
    }

    printf("NFA states: %d\n", nfa_n);
    printf("NFA edges : %d\n", edge_n);

    build_dfa(super_start);
    printf("DFA states before minimization: %d\n", dfa_n);

    Cdfa cd = complete_dfa();

    int *min_t = NULL, *min_acc = NULL, min_start = 0;
    int min_n = minimize_hopcroft(&cd, &min_t, &min_acc, &min_start);
    printf("Minimized DFA states: %d\n", min_n);
    printf("Trap state: represented by explicit complete-DFA state %d before minimization;\n", cd.n - 1);
    printf("           after minimization it is the non-accepting sink class.\n\n");

    export_json("funny_dfa.json", min_n, min_t, min_acc, min_start);
    export_csv("funny_dfa.csv", min_n, min_t, min_acc, min_start);
    printf("Generated: funny_dfa.json\n");
    printf("Generated: funny_dfa.csv\n\n");

    run_tests(min_t, min_start, min_acc);

    free(min_t);
    free(min_acc);
    free_cdfa(&cd);
    return 0;
}
