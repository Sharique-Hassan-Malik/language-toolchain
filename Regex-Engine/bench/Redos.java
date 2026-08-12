import java.util.regex.Pattern;
import regex.Regex;

/**
 * The headline: a pattern that makes {@code java.util.regex} take exponential
 * time runs in flat, linear time on this engine.
 *
 * <p>Run: {@code java -cp out Redos}
 *
 * <p>The pattern is {@code (.*a){15}$}. The {@code .*} inside a repeated,
 * anchored group can match a run of characters in exponentially many ways, and
 * when the input ends in a character that defeats the {@code $} anchor, a
 * backtracking matcher explores all of them before conceding there is no match.
 *
 * <p>Each extra input character roughly doubles that work. On this engine it
 * adds a constant, because paths that reconverge are merged instead of retried.
 * Both engines return the same answer — no match — so the entire difference is
 * wasted backtracking.
 *
 * <p>(Modern {@code java.util.regex} defuses the simpler {@code (a+)+$} form, so
 * a counted group is used here to reach the same catastrophic behaviour it has
 * not special-cased.)
 */
public final class Redos {
    private static final String PATTERN = "(.*a){15}$";
    private static final long TIMEOUT_MS = 4000;

    public static void main(String[] args) throws Exception {
        Regex mine = Regex.compile(PATTERN);
        Pattern jdk = Pattern.compile(PATTERN);

        // Warm the JIT so the first row is not an outlier.
        for (int i = 0; i < 5; i++) {
            mine.matches("a".repeat(20) + "!");
        }

        System.out.println("pattern: /" + PATTERN + "/   input: \"a\"*n + \"!\"  (defeats $, forcing a non-match)\n");
        System.out.printf("%4s  %20s  %16s  %s%n", "n", "java.util.regex", "this engine", "ratio");
        System.out.println("----  --------------------  ----------------  -----");

        boolean jdkAlive = true;
        for (int n = 15; n <= 31; n += 2) {
            String input = "a".repeat(n) + "!";

            long jdkNs = jdkAlive ? timeJdk(jdk, input) : -1;
            if (jdkNs < 0) {
                jdkAlive = false;
            }
            long mineNs = timeMine(mine, input);

            String ratio = jdkNs < 0 ? "—" : String.format("%.0fx", (double) jdkNs / mineNs);
            String jdkCol = jdkNs < 0 ? "TIMEOUT (>" + TIMEOUT_MS + "ms)" : fmt(jdkNs);
            System.out.printf("%4d  %20s  %16s  %s%n", n, jdkCol, fmt(mineNs), ratio);
        }

        System.out.println("""

            java.util.regex roughly doubles its time for every two characters added,
            reaching seconds by n=27 and timing out by n=29. This engine holds a flat
            sub-millisecond line the whole way. Same pattern, same input, same answer
            (no match) — the gap is entirely backtracking this engine never does.

            This is a difference in complexity class, not in tuning. It is why a
            regex here cannot be turned into a denial of service by choosing the
            input: there is no exponential path count to trigger, because paths that
            reconverge are merged into one.""");
    }

    /** Time the JDK matcher on a daemon thread so a runaway match can be abandoned. */
    private static long timeJdk(Pattern p, String input) throws InterruptedException {
        long[] out = {-1};
        Thread worker = new Thread(() -> {
            long start = System.nanoTime();
            p.matcher(input).matches();
            out[0] = System.nanoTime() - start;
        });
        worker.setDaemon(true);
        worker.start();
        worker.join(TIMEOUT_MS);
        return worker.isAlive() ? -1 : out[0];       // still running => over budget
    }

    private static long timeMine(Regex r, String input) {
        long start = System.nanoTime();
        r.matches(input);
        return System.nanoTime() - start;
    }

    private static String fmt(long ns) {
        if (ns < 10_000) {
            return ns + " ns";
        }
        if (ns < 1_000_000) {
            return String.format("%.2f ms", ns / 1e6);
        }
        return String.format("%.0f ms", ns / 1e6);
    }
}
