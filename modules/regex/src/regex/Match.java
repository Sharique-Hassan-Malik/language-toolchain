package regex;

/**
 * The result of a successful match: the overall span plus every captured group.
 *
 * Groups are addressed the way {@code java.util.regex} addresses them — group 0
 * is the whole match, group <i>n</i> is the <i>n</i>-th opening parenthesis. A
 * group that did not participate (the untaken side of an alternation, say)
 * reports {@code -1} for its bounds and {@code null} for its text, which is the
 * signal a caller must be able to distinguish from an empty match.
 */
public final class Match {
    private final String input;
    private final int[] caps;
    private final int groupCount;

    Match(String input, int[] caps, int groupCount) {
        this.input = input;
        this.caps = caps;
        this.groupCount = groupCount;
    }

    /** Start index of the whole match. */
    public int start() {
        return caps[0];
    }

    /** End index (exclusive) of the whole match. */
    public int end() {
        return caps[1];
    }

    /** The whole matched substring. */
    public String group() {
        return group(0);
    }

    /** Start index of group {@code n}, or -1 if it did not participate. */
    public int start(int n) {
        checkGroup(n);
        return caps[2 * n];
    }

    /** End index of group {@code n}, or -1 if it did not participate. */
    public int end(int n) {
        checkGroup(n);
        return caps[2 * n + 1];
    }

    /** The substring captured by group {@code n}, or {@code null} if it did not participate. */
    public String group(int n) {
        checkGroup(n);
        int s = caps[2 * n];
        int e = caps[2 * n + 1];
        if (s < 0 || e < 0) {
            return null;
        }
        return input.substring(s, e);
    }

    public int groupCount() {
        return groupCount;
    }

    private void checkGroup(int n) {
        if (n < 0 || n > groupCount) {
            throw new IndexOutOfBoundsException("no group " + n + " (have 0.." + groupCount + ")");
        }
    }

    @Override
    public String toString() {
        return "Match[" + start() + ".." + end() + "]=\"" + group() + "\"";
    }
}
