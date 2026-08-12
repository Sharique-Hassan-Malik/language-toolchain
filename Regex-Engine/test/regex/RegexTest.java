package regex;

import java.util.regex.Pattern;

/**
 * The test suite, plus a zero-dependency runner.
 *
 * There is no JUnit here on purpose: the whole engine compiles and tests with
 * nothing but {@code javac} and {@code java}, which is the point of a
 * self-contained project. {@link #main} runs every {@code test*} method,
 * prints a summary, and exits non-zero on any failure.
 *
 * Many cases cross-check against {@code java.util.regex} on inputs where the two
 * engines are specified to agree (no backtracking-only features involved). That
 * turns "I believe this is right" into "it matches the reference on 500 random
 * strings" — differential testing being far better at finding parser and
 * capture bugs than hand-picked cases.
 */
public final class RegexTest {

    // -- basic matching ------------------------------------------------------

    void testLiterals() {
        eq(Regex.compile("abc").matches("abc"), true);
        eq(Regex.compile("abc").matches("abd"), false);
        eq(Regex.compile("abc").matches("ab"), false);
        eq(Regex.compile("").matches(""), true);
        eq(Regex.compile("").matches("x"), false);
    }

    void testDot() {
        eq(Regex.compile("a.c").matches("abc"), true);
        eq(Regex.compile("a.c").matches("axc"), true);
        eq(Regex.compile("a.c").matches("ac"), false);
        eq(Regex.compile(".").matches("\n"), false);       // dot excludes newline
    }

    void testStar() {
        eq(Regex.compile("a*").matches(""), true);
        eq(Regex.compile("a*").matches("aaaa"), true);
        eq(Regex.compile("ab*c").matches("ac"), true);
        eq(Regex.compile("ab*c").matches("abbbc"), true);
    }

    void testPlus() {
        eq(Regex.compile("a+").matches(""), false);
        eq(Regex.compile("a+").matches("aaa"), true);
        eq(Regex.compile("ab+c").matches("ac"), false);
    }

    void testQuest() {
        eq(Regex.compile("colou?r").matches("color"), true);
        eq(Regex.compile("colou?r").matches("colour"), true);
        eq(Regex.compile("colou?r").matches("colouur"), false);
    }

    void testAlternation() {
        eq(Regex.compile("cat|dog").matches("cat"), true);
        eq(Regex.compile("cat|dog").matches("dog"), true);
        eq(Regex.compile("cat|dog").matches("cow"), false);
        eq(Regex.compile("a|b|c").matches("b"), true);
        eq(Regex.compile("").matches(""), true);
        eq(Regex.compile("a|").matches(""), true);         // empty alternative
    }

    void testGrouping() {
        eq(Regex.compile("(ab)+").matches("ababab"), true);
        eq(Regex.compile("(ab)+").matches("aba"), false);
        eq(Regex.compile("(a|b)*c").matches("ababc"), true);
        eq(Regex.compile("(a(b(c)))").matches("abc"), true);
    }

    void testCharClass() {
        eq(Regex.compile("[abc]").matches("b"), true);
        eq(Regex.compile("[abc]").matches("d"), false);
        eq(Regex.compile("[a-z]+").matches("hello"), true);
        eq(Regex.compile("[a-z]+").matches("Hello"), false);
        eq(Regex.compile("[^0-9]+").matches("abc"), true);
        eq(Regex.compile("[^0-9]+").matches("ab3"), false);
        eq(Regex.compile("[]a]").matches("]"), true);       // ']' right after '[' is literal
        eq(Regex.compile("[a-]").matches("-"), true);       // trailing '-' is literal
    }

    void testEscapes() {
        eq(Regex.compile("\\d+").matches("12345"), true);
        eq(Regex.compile("\\d+").matches("12a45"), false);
        eq(Regex.compile("\\w+").matches("hello_123"), true);
        eq(Regex.compile("\\s").matches(" "), true);
        eq(Regex.compile("a\\.b").matches("a.b"), true);
        eq(Regex.compile("a\\.b").matches("axb"), false);   // escaped dot is literal
        eq(Regex.compile("\\(").matches("("), true);
    }

    void testAnchors() {
        eq(Regex.compile("^abc$").matches("abc"), true);
        eq(Regex.compile("abc").test("xabcx"), true);
        eq(Regex.compile("^abc").test("xabc"), false);
        eq(Regex.compile("abc$").test("abcx"), false);
        eq(Regex.compile("^abc$").test("abc"), true);
    }

    void testCountedRepetition() {
        eq(Regex.compile("a{3}").matches("aaa"), true);
        eq(Regex.compile("a{3}").matches("aa"), false);
        eq(Regex.compile("a{2,4}").matches("aaa"), true);
        eq(Regex.compile("a{2,4}").matches("a"), false);
        eq(Regex.compile("a{2,4}").matches("aaaaa"), false);
        eq(Regex.compile("a{2,}").matches("aaaaaa"), true);
        eq(Regex.compile("a{0,2}").matches(""), true);
        eq(Regex.compile("(ab){3}").matches("ababab"), true);
    }

    // -- search and capture --------------------------------------------------

    void testFind() {
        eq(Regex.compile("\\d+").find("abc123def").get().group(), "123");
        eq(Regex.compile("\\d+").find("abc123def").get().start(), 3);
        eq(Regex.compile("\\d+").find("abc123def").get().end(), 6);
        eq(Regex.compile("xyz").find("abc").isPresent(), false);
    }

    void testCaptureGroups() {
        Match m = Regex.compile("(\\d+)-(\\d+)").find("order 42-1000 x").get();
        eq(m.group(0), "42-1000");
        eq(m.group(1), "42");
        eq(m.group(2), "1000");
        eq(m.start(1), 6);
        eq(m.end(2), 13);
    }

    void testNonParticipatingGroup() {
        // The untaken side of an alternation must report null, not "".
        Match m = Regex.compile("(a)|(b)").find("b").get();
        eq(m.group(1), null);
        eq(m.group(2), "b");
        eq(m.start(1), -1);
    }

    void testGroupKeepsLastIteration() {
        // (\d){3} captures the last digit, matching java.util.regex.
        eq(Regex.compile("(\\d){3}").find("x123y").get().group(1), "3");
        eq(Regex.compile("(ab)+").find("ababab").get().group(1), "ab");
    }

    void testLeftmostFirst() {
        // Ordered alternation prefers the earlier branch.
        eq(Regex.compile("a|ab").find("ab").get().group(), "a");
        eq(Regex.compile("ab|a").find("ab").get().group(), "ab");
    }

    void testGreedyVsLazy() {
        eq(Regex.compile("a*").find("aaa").get().group(), "aaa");
        eq(Regex.compile("a*?").find("aaa").get().group(), "");
        eq(Regex.compile("<.*>").find("<a><b>").get().group(), "<a><b>");
        eq(Regex.compile("<.*?>").find("<a><b>").get().group(), "<a>");
    }

    void testLeftmostSearch() {
        // The match must be the earliest starting position, not just any.
        eq(Regex.compile("a+").find("xaaxaaa").get().start(), 1);
        eq(Regex.compile("a+").find("xaaxaaa").get().group(), "aa");
    }

    // -- syntax errors -------------------------------------------------------

    void testSyntaxErrors() {
        throwsSyntax(() -> Regex.compile("("));
        throwsSyntax(() -> Regex.compile(")"));
        throwsSyntax(() -> Regex.compile("[a-"));
        throwsSyntax(() -> Regex.compile("*"));
        throwsSyntax(() -> Regex.compile("a{5,2}"));
        throwsSyntax(() -> Regex.compile("a{2000}"));       // exceeds the repeat cap
        throwsSyntax(() -> Regex.compile("[z-a]"));         // reversed range
    }

    // -- the property that names the project ---------------------------------

    void testLinearTimeOnRedos() {
        // The pattern that hangs a backtracker must finish quickly here. A
        // generous ceiling: the point is "does not explode", and any regression
        // to backtracking would blow past seconds, not milliseconds.
        Regex r = Regex.compile("(.*a){20}$");
        String input = "a".repeat(40) + "!";
        long start = System.nanoTime();
        boolean matched = r.matches(input);
        long ms = (System.nanoTime() - start) / 1_000_000;
        eq(matched, false);
        assertTrue(ms < 500, "ReDoS input took " + ms + " ms (should be a few)");
    }

    // -- differential testing against java.util.regex ------------------------

    void testAgainstReference() {
        // Patterns using only features both engines agree on (no backreferences,
        // no lookaround). If they ever disagree on an input, one has a bug.
        String[] patterns = {
            "a+b*c?", "(ab|cd)+", "[a-z]+@[a-z]+", "x(y|z)*w", "\\d{2,4}-\\d{2}",
            "(a|b)(c|d)(e|f)", "^[A-Za-z][A-Za-z0-9]*$", "a.*b.*c", "colou?rs?",
            "[^aeiou]+", "(foo)+bar", "\\w+\\s\\w+",
        };
        String alphabet = "abcdefghijxyz0123-@_ ";
        java.util.Random rng = new java.util.Random(12345);
        int checks = 0;
        for (String pat : patterns) {
            Regex mine = Regex.compile(pat);
            Pattern ref = Pattern.compile(pat);
            for (int i = 0; i < 400; i++) {
                StringBuilder sb = new StringBuilder();
                int len = rng.nextInt(12);
                for (int j = 0; j < len; j++) {
                    sb.append(alphabet.charAt(rng.nextInt(alphabet.length())));
                }
                String s = sb.toString();
                boolean a = mine.matches(s);
                boolean b = ref.matcher(s).matches();
                eq("matches /" + pat + "/ ~ \"" + s + "\"", a, b);
                boolean a2 = mine.test(s);
                boolean b2 = ref.matcher(s).find();
                eq("find /" + pat + "/ ~ \"" + s + "\"", a2, b2);
                checks += 2;
            }
        }
        note(checks + " differential checks against java.util.regex");
    }

    // ========================================================================
    // runner
    // ========================================================================

    private int passed, failed;
    private final StringBuilder notes = new StringBuilder();

    public static void main(String[] args) throws Exception {
        RegexTest t = new RegexTest();
        for (var method : RegexTest.class.getDeclaredMethods()) {
            if (method.getName().startsWith("test") && method.getParameterCount() == 0) {
                int before = t.failed;
                try {
                    method.invoke(t);
                    String mark = t.failed == before ? "ok  " : "FAIL";
                    System.out.printf("  %s %s%n", mark, method.getName());
                } catch (Exception e) {
                    t.failed++;
                    System.out.printf("  ERR  %s: %s%n", method.getName(),
                        e.getCause() != null ? e.getCause() : e);
                }
            }
        }
        System.out.println(t.notes);
        System.out.printf("%n%d passed, %d failed%n", t.passed, t.failed);
        System.exit(t.failed == 0 ? 0 : 1);
    }

    private void eq(Object got, Object want) {
        eq(null, got, want);
    }

    private void eq(String label, Object got, Object want) {
        if (java.util.Objects.equals(got, want)) {
            passed++;
        } else {
            failed++;
            System.out.printf("       assert failed%s: got <%s> want <%s>%n",
                label == null ? "" : " [" + label + "]", got, want);
        }
    }

    private void assertTrue(boolean cond, String message) {
        if (cond) {
            passed++;
        } else {
            failed++;
            System.out.println("       " + message);
        }
    }

    private void throwsSyntax(Runnable r) {
        try {
            r.run();
            failed++;
            System.out.println("       expected RegexSyntaxException, none thrown");
        } catch (RegexSyntaxException e) {
            passed++;
        }
    }

    private void note(String s) {
        notes.append("  note: ").append(s).append(System.lineSeparator());
    }
}
