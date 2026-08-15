package regex;

/**
 * Thrown when a pattern is malformed. Carries the pattern and the offset where
 * parsing gave up, because "invalid regex" with no position is a bug report
 * nobody can act on.
 */
public final class RegexSyntaxException extends RuntimeException {
    private final String pattern;
    private final int position;

    RegexSyntaxException(String message, String pattern, int position) {
        super(message + " in /" + pattern + "/ at offset " + position);
        this.pattern = pattern;
        this.position = position;
    }

    public String pattern() {
        return pattern;
    }

    public int position() {
        return position;
    }
}
