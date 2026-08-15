package regex;

import java.util.ArrayList;
import java.util.List;

/**
 * Recursive-descent parser: pattern text to an abstract syntax tree.
 *
 * The grammar is the ordinary one, and its shape encodes operator precedence
 * directly — each level of the recursion is one precedence tier:
 *
 * <pre>
 *   alternation := concatenation ('|' concatenation)*      lowest
 *   concatenation := repetition*
 *   repetition := atom ('*' | '+' | '?')* ('?' lazy-marker)?
 *   atom := '(' alternation ')' | '[' class ']' | '.' | '^' | '$' | literal   highest
 * </pre>
 *
 * Parsing to an AST first, rather than compiling the text straight to
 * instructions, keeps the two hard problems apart: this file worries only about
 * what the pattern <em>means</em>, and {@link Compiler} worries only about how
 * to run it. A grammar bug and a codegen bug then live in different files.
 */
final class Parser {
    private final String src;
    private int pos;
    /** Next capture-group index. Group 0 is the whole match, assigned by {@link Compiler}. */
    private int groupCount = 1;

    private Parser(String pattern) {
        this.src = pattern;
    }

    static Ast parse(String pattern) {
        Parser p = new Parser(pattern);
        Ast ast = p.alternation();
        if (p.pos != p.src.length()) {
            throw new RegexSyntaxException("unexpected '" + p.peek() + "' at " + p.pos, pattern, p.pos);
        }
        return ast;
    }

    int groupCount() {
        return groupCount;
    }

    // -- grammar -------------------------------------------------------------

    private Ast alternation() {
        Ast left = concatenation();
        while (!eof() && peek() == '|') {
            next();
            left = new Ast.Alt(left, concatenation());
        }
        return left;
    }

    private Ast concatenation() {
        List<Ast> parts = new ArrayList<>();
        while (!eof() && peek() != '|' && peek() != ')') {
            parts.add(repetition());
        }
        if (parts.isEmpty()) {
            return Ast.EMPTY;                       // e.g. the branches of "a|"
        }
        Ast node = parts.get(0);
        for (int i = 1; i < parts.size(); i++) {
            node = new Ast.Concat(node, parts.get(i));
        }
        return node;
    }

    /** Counted repetition {n} may not unroll to more than this, to bound program size. */
    private static final int MAX_REPEAT = 1000;

    private Ast repetition() {
        Ast atom = atom();
        while (!eof()) {
            char c = peek();
            if (c == '{') {
                atom = counted(atom);
                continue;
            }
            if (c != '*' && c != '+' && c != '?') {
                break;
            }
            next();
            // A trailing '?' after a quantifier makes it lazy: "a*?" prefers the
            // shortest match. Lazy vs greedy is not a different algorithm here,
            // only the order two threads are queued — see Compiler.
            boolean lazy = !eof() && peek() == '?';
            if (lazy && c != '?') {                 // "??" is lazy-optional, "?" alone is not
                next();
            } else {
                lazy = false;
            }
            switch (c) {
                case '*' -> atom = new Ast.Star(atom, !lazy);
                case '+' -> atom = new Ast.Plus(atom, !lazy);
                case '?' -> atom = new Ast.Quest(atom, !lazy);
            }
        }
        return atom;
    }

    /**
     * Counted repetition {@code {n} {n,} {n,m}}, unrolled at parse time.
     *
     * Unrolling — rather than a runtime counter — is what keeps the linear-time
     * guarantee: the compiled program grows, but the matcher still sees a fixed
     * graph and merges reconverging paths. The same sub-AST is reused for every
     * copy, so a captured group inside {@code (x){n}} keeps its single index and
     * reports the last iteration, exactly as {@code java.util.regex} does.
     *
     * The {@link #MAX_REPEAT} cap exists so {@code a{999999999}} fails loudly at
     * compile time instead of trying to allocate a program that cannot fit in
     * memory — a denial of service of its own kind.
     */
    private Ast counted(Ast atom) {
        expect('{');
        int min = number();
        int max;
        if (!eof() && peek() == ',') {
            next();
            max = (!eof() && peek() == '}') ? Integer.MAX_VALUE : number();
        } else {
            max = min;                              // {n} means exactly n
        }
        expect('}');
        boolean lazy = !eof() && peek() == '?';
        if (lazy) {
            next();
        }
        if (max != Integer.MAX_VALUE && max < min) {
            throw new RegexSyntaxException("repetition {" + min + "," + max + "} has max < min", src, pos);
        }
        int bounded = max == Integer.MAX_VALUE ? min : max;
        if (bounded > MAX_REPEAT) {
            throw new RegexSyntaxException("repetition count " + bounded + " exceeds the limit " + MAX_REPEAT,
                src, pos);
        }

        // n mandatory copies …
        Ast result = Ast.EMPTY;
        for (int i = 0; i < min; i++) {
            result = concatOf(result, atom);
        }
        if (max == Integer.MAX_VALUE) {
            // {n,} — the tail is a Kleene star on the same atom.
            result = concatOf(result, new Ast.Star(atom, !lazy));
        } else {
            // {n,m} — (m - n) optional copies.
            for (int i = min; i < max; i++) {
                result = concatOf(result, new Ast.Quest(atom, !lazy));
            }
        }
        return result;
    }

    private static Ast concatOf(Ast left, Ast right) {
        if (left == Ast.EMPTY) {
            return right;
        }
        return new Ast.Concat(left, right);
    }

    private int number() {
        int startPos = pos;
        int value = 0;
        while (!eof() && Character.isDigit(peek())) {
            value = value * 10 + (next() - '0');
            if (value > 10_000_000) {               // stop before overflow; MAX_REPEAT rejects it later
                value = 10_000_001;
                while (!eof() && Character.isDigit(peek())) {
                    next();
                }
                break;
            }
        }
        if (pos == startPos) {
            throw new RegexSyntaxException("expected a number in {…}", src, pos);
        }
        return value;
    }

    private Ast atom() {
        char c = peek();
        switch (c) {
            case '(' -> {
                next();
                int group = groupCount++;
                Ast inner = alternation();
                expect(')');
                return new Ast.Group(group, inner);
            }
            case '[' -> {
                return characterClass();
            }
            case '.' -> {
                next();
                return Ast.DOT;
            }
            case '^' -> {
                next();
                return Ast.BEGIN;
            }
            case '$' -> {
                next();
                return Ast.END;
            }
            case '\\' -> {
                next();
                return escape();
            }
            case ')', '|', '*', '+', '?' ->
                throw new RegexSyntaxException("unexpected '" + c + "'", src, pos);
            default -> {
                next();
                return new Ast.Lit(c);
            }
        }
    }

    /**
     * A character class {@code [...]}. Supports ranges ({@code a-z}), negation
     * ({@code [^...]}) and escaped members. Membership is a set test at match
     * time, which is what lets a class of any size cost one instruction.
     */
    private Ast characterClass() {
        expect('[');
        boolean negated = false;
        if (!eof() && peek() == '^') {
            next();
            negated = true;
        }
        List<int[]> ranges = new ArrayList<>();
        // A ']' immediately after '[' or '[^' is a literal ']', not a close.
        boolean first = true;
        while (!eof() && (peek() != ']' || first)) {
            first = false;
            char lo = classChar();
            if (!eof() && peek() == '-' && pos + 1 < src.length() && src.charAt(pos + 1) != ']') {
                next();
                char hi = classChar();
                if (hi < lo) {
                    throw new RegexSyntaxException("range out of order: " + lo + "-" + hi, src, pos);
                }
                ranges.add(new int[] {lo, hi});
            } else {
                ranges.add(new int[] {lo, lo});
            }
        }
        expect(']');
        return new Ast.CharClass(ranges, negated);
    }

    private char classChar() {
        char c = next();
        if (c == '\\') {
            char e = next();
            return switch (e) {
                case 'n' -> '\n';
                case 't' -> '\t';
                case 'r' -> '\r';
                default -> e;                        // \\, \], \-, \^ etc. are literal
            };
        }
        return c;
    }

    private Ast escape() {
        char e = next();
        return switch (e) {
            case 'n' -> new Ast.Lit('\n');
            case 't' -> new Ast.Lit('\t');
            case 'r' -> new Ast.Lit('\r');
            case 'd' -> new Ast.CharClass(List.of(new int[] {'0', '9'}), false);
            case 'D' -> new Ast.CharClass(List.of(new int[] {'0', '9'}), true);
            case 'w' -> new Ast.CharClass(
                List.of(new int[] {'a', 'z'}, new int[] {'A', 'Z'}, new int[] {'0', '9'}, new int[] {'_', '_'}), false);
            case 's' -> new Ast.CharClass(
                List.of(new int[] {' ', ' '}, new int[] {'\t', '\t'}, new int[] {'\n', '\n'}, new int[] {'\r', '\r'}), false);
            // Any other escaped char is the literal char: \. \* \( etc.
            default -> new Ast.Lit(e);
        };
    }

    // -- cursor --------------------------------------------------------------

    private boolean eof() {
        return pos >= src.length();
    }

    private char peek() {
        if (eof()) {
            throw new RegexSyntaxException("unexpected end of pattern", src, pos);
        }
        return src.charAt(pos);
    }

    private char next() {
        char c = peek();
        pos++;
        return c;
    }

    private void expect(char c) {
        if (eof() || src.charAt(pos) != c) {
            throw new RegexSyntaxException("expected '" + c + "'", src, pos);
        }
        pos++;
    }
}
