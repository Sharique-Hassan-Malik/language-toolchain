package regex;

/**
 * A tiny CLI so the engine is runnable by hand:
 *
 * <pre>
 *   java -cp out regex.Main '\d+' 'order 42 and 1000'   # find + groups
 *   java -cp out regex.Main --matches '^a+$' 'aaaa'      # full-match test
 *   java -cp out regex.Main --disasm '(a|b)*'            # show the program
 * </pre>
 */
public final class Main {
    public static void main(String[] args) {
        if (args.length == 0) {
            System.err.println("usage: regex.Main [--matches|--disasm] <pattern> [input]");
            System.exit(2);
        }
        String mode = args[0].startsWith("--") ? args[0] : "--find";
        int base = args[0].startsWith("--") ? 1 : 0;
        String pattern = args[base];
        try {
            Regex r = Regex.compile(pattern);
            switch (mode) {
                case "--disasm" -> System.out.print(r.disassemble());
                case "--matches" -> System.out.println(r.matches(args[base + 1]));
                default -> {
                    var m = r.find(args[base + 1]);
                    if (m.isEmpty()) {
                        System.out.println("no match");
                    } else {
                        Match match = m.get();
                        System.out.println("match: \"" + match.group() + "\" at [" + match.start() + ".." + match.end() + ")");
                        for (int g = 1; g <= match.groupCount(); g++) {
                            System.out.println("  group " + g + ": " + (match.group(g) == null ? "(none)" : "\"" + match.group(g) + "\""));
                        }
                    }
                }
            }
        } catch (RegexSyntaxException e) {
            System.err.println("syntax error: " + e.getMessage());
            System.exit(1);
        }
    }
}
