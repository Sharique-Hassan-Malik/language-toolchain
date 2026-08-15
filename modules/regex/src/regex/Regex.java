package regex;

import java.util.Optional;

/**
 * A regular-expression engine that runs in time linear in the input length,
 * for every pattern.
 *
 * <p>The public surface mirrors what people expect from {@code java.util.regex},
 * minus the features that require backtracking (backreferences, lookaround) —
 * which is not a coincidence: those are exactly the features that make linear
 * time impossible, and their absence is why this engine cannot be attacked with
 * a catastrophic-backtracking input.
 *
 * <pre>{@code
 *   Regex r = Regex.compile("(\\d+)-(\\d+)");
 *   Optional<Match> m = r.find("order 42-1000 shipped");
 *   m.get().group(1);   // "42"
 *   m.get().group(2);   // "1000"
 * }</pre>
 *
 * Supported: literals, {@code . ^ $}, {@code * + ?} (greedy and lazy),
 * alternation {@code |}, grouping and capture {@code ( )}, character classes
 * {@code [a-z] [^…]}, and the escapes {@code \d \D \w \s \n \t \r}.
 */
public final class Regex {
    private final Program program;
    private final int groupCount;
    private final String pattern;
    private final ThreadLocal<Pike> vm;

    private Regex(String pattern, Program program, int groupCount) {
        this.pattern = pattern;
        this.program = program;
        this.groupCount = groupCount;
        // A Pike VM holds a per-instruction scratch array, so one instance is not
        // safe to share across threads. A compiled Regex, being immutable, is —
        // so each thread lazily gets its own VM over the shared program.
        this.vm = ThreadLocal.withInitial(() -> new Pike(program));
    }

    /**
     * Compile a pattern.
     *
     * @throws RegexSyntaxException if the pattern is malformed
     */
    public static Regex compile(String pattern) {
        Ast ast = Parser.parse(pattern);
        int groups = countGroups(ast);                 // capturing groups, not counting group 0
        Program program = Program.compile(ast, groups + 1);
        return new Regex(pattern, program, groups);
    }

    /** True iff the whole input is matched by the pattern (implicitly anchored both ends). */
    public boolean matches(String input) {
        int[] caps = vm.get().run(input, 0, true);
        return caps != null && caps[1] == input.length();
    }

    /** The leftmost match anywhere in the input, if any. */
    public Optional<Match> find(String input) {
        return find(input, 0);
    }

    /** The leftmost match at or after {@code start}. */
    public Optional<Match> find(String input, int start) {
        if (start < 0 || start > input.length()) {
            throw new IndexOutOfBoundsException("start " + start + " out of [0, " + input.length() + "]");
        }
        int[] caps = vm.get().run(input, start, false);
        return caps == null ? Optional.empty() : Optional.of(new Match(input, caps, groupCount));
    }

    /** True iff the pattern matches somewhere in the input. */
    public boolean test(String input) {
        return vm.get().run(input, 0, false) != null;
    }

    /** Number of capturing groups, not counting the whole-match group 0. */
    public int groupCount() {
        return groupCount;
    }

    public String pattern() {
        return pattern;
    }

    /** The compiled instructions, for inspection. */
    public String disassemble() {
        return program.disassemble();
    }

    private static int countGroups(Ast node) {
        return switch (node) {
            case Ast.Group g -> 1 + countGroups(g.body());
            case Ast.Concat c -> countGroups(c.left()) + countGroups(c.right());
            case Ast.Alt a -> countGroups(a.left()) + countGroups(a.right());
            case Ast.Star s -> countGroups(s.body());
            case Ast.Plus p -> countGroups(p.body());
            case Ast.Quest q -> countGroups(q.body());
            default -> 0;
        };
    }
}
