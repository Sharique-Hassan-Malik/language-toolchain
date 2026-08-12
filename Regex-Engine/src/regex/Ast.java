package regex;

import java.util.List;

/**
 * The abstract syntax tree. A sealed hierarchy so {@link Compiler} must handle
 * every node kind — a new node without codegen becomes a compile error rather
 * than a silent runtime surprise.
 */
sealed interface Ast {

    /** The empty pattern, matching the empty string. Shared: it carries no state. */
    Ast EMPTY = new Empty();
    /** {@code .} — any single character except newline. */
    Ast DOT = new Dot();
    /** {@code ^} — assert start of input. */
    Ast BEGIN = new Begin();
    /** {@code $} — assert end of input. */
    Ast END = new End();

    record Empty() implements Ast {}

    record Lit(char ch) implements Ast {}

    record Dot() implements Ast {}

    record Begin() implements Ast {}

    record End() implements Ast {}

    /** A character class as a list of inclusive [lo, hi] code-point ranges. */
    record CharClass(List<int[]> ranges, boolean negated) implements Ast {
        boolean matches(char c) {
            boolean in = false;
            for (int[] r : ranges) {
                if (c >= r[0] && c <= r[1]) {
                    in = true;
                    break;
                }
            }
            return in != negated;
        }
    }

    record Concat(Ast left, Ast right) implements Ast {}

    record Alt(Ast left, Ast right) implements Ast {}

    /** {@code *} — zero or more. {@code greedy} decides thread priority, not correctness. */
    record Star(Ast body, boolean greedy) implements Ast {}

    /** {@code +} — one or more. */
    record Plus(Ast body, boolean greedy) implements Ast {}

    /** {@code ?} — zero or one. */
    record Quest(Ast body, boolean greedy) implements Ast {}

    /** {@code (...)} — a capturing group. {@code index} is its 1-based number. */
    record Group(int index, Ast body) implements Ast {}
}
