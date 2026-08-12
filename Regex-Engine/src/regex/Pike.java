package regex;

import java.util.ArrayList;
import java.util.List;

/**
 * The Pike VM: runs a compiled {@link Program} against input in guaranteed
 * linear time, with submatch capture.
 *
 * <h2>Why this cannot blow up</h2>
 *
 * A backtracking matcher explores one path at a time and, on failure, unwinds
 * and tries the next. For a pattern like {@code (a+)+} the number of ways to
 * partition a run of {@code a}s is exponential, so a backtracker can try an
 * exponential number of paths before rejecting — the vulnerability known as
 * ReDoS.
 *
 * This VM instead advances <em>every</em> live path simultaneously, one input
 * character at a time. Two paths that arrive at the same instruction are
 * indistinguishable from that point on, so the second is discarded
 * ({@code visited[pc] == gen}). The number of distinct instructions is fixed at
 * compile time, so at any input position there are at most
 * {@code program.length} live threads. Total work is therefore
 * {@code O(inputLength × programLength)} — linear in the input — no matter what
 * the pattern is. There is no path count to explode because paths that reconverge
 * are merged.
 *
 * <h2>Leftmost-first semantics</h2>
 *
 * Threads are kept in priority order, and a SPLIT queues its preferred branch
 * first. When a thread reaches MATCH, every lower-priority thread in the current
 * step is abandoned. That reproduces Perl/PCRE "leftmost-first" behaviour —
 * greedy quantifiers prefer more, lazy prefer less, and {@code a|ab} on
 * {@code "ab"} matches {@code "a"} — without any backtracking.
 */
final class Pike {

    /** One thread of execution: a program counter plus its capture slots. */
    private record Thread(int pc, int[] caps) {}

    private final Program prog;
    private final int[] visited;          // visited[pc] == gen means pc already queued this step
    private int gen;

    Pike(Program prog) {
        this.prog = prog;
        this.visited = new int[prog.insts.length];
    }

    /**
     * @param input   the string to match against
     * @param start   index to begin at
     * @param anchored if true, the match must begin exactly at {@code start};
     *                 if false, the leftmost match at or after {@code start} is found
     * @return the capture slots of the match, or {@code null} if none
     */
    int[] run(String input, int start, boolean anchored) {
        List<Thread> clist = new ArrayList<>();
        List<Thread> nlist = new ArrayList<>();
        int[] matched = null;

        gen++;
        addThread(clist, 0, start, freshCaps(), input);

        for (int sp = start; sp <= input.length(); sp++) {
            gen++;
            char c = sp < input.length() ? input.charAt(sp) : '\0';

            for (int t = 0; t < clist.size(); t++) {
                Thread th = clist.get(t);
                Program.Inst inst = prog.insts[th.pc];
                switch (inst.op) {
                    case CHAR -> {
                        if (sp < input.length() && c == inst.ch) {
                            addThread(nlist, th.pc + 1, sp + 1, th.caps, input);
                        }
                    }
                    case ANY -> {
                        // '.' matches any char except newline, the common convention.
                        if (sp < input.length() && c != '\n') {
                            addThread(nlist, th.pc + 1, sp + 1, th.caps, input);
                        }
                    }
                    case CLASS -> {
                        if (sp < input.length() && inst.cls.matches(c)) {
                            addThread(nlist, th.pc + 1, sp + 1, th.caps, input);
                        }
                    }
                    case MATCH -> {
                        matched = th.caps;
                        // Leftmost-first: this thread had higher priority than any
                        // that follow it in clist, so their matches are irrelevant.
                        clist.subList(t + 1, clist.size()).clear();
                    }
                    default -> throw new IllegalStateException("non-consuming op in clist: " + inst.op);
                }
            }

            // Unanchored search: keep offering a fresh start at each later
            // position, but only until something matches — appended last so it
            // has lower priority than any in-progress thread, which is what
            // makes the match leftmost.
            if (!anchored && matched == null && sp < input.length()) {
                addThread(nlist, 0, sp + 1, freshCaps(), input);
            }

            List<Thread> swap = clist;
            clist = nlist;
            nlist = swap;
            nlist.clear();
        }
        return matched;
    }

    /**
     * Follow all epsilon transitions from {@code pc} and queue the resulting
     * character-consuming (or MATCH) threads, deduplicating by program counter.
     *
     * The dedup is the linear-time guarantee in one line: a program counter
     * already reached this step is not queued again, so a reconverging fork adds
     * no work.
     *
     * Recursion depth is bounded by {@code program.length} because {@code visited}
     * cuts every cycle, so this cannot overflow the stack for any pattern.
     */
    private void addThread(List<Thread> list, int pc, int sp, int[] caps, String input) {
        if (visited[pc] == gen) {
            return;
        }
        visited[pc] = gen;
        Program.Inst inst = prog.insts[pc];
        switch (inst.op) {
            case JMP -> addThread(list, inst.x, sp, caps, input);
            case SPLIT -> {
                addThread(list, inst.x, sp, caps, input);   // preferred branch first
                addThread(list, inst.y, sp, caps, input);
            }
            case SAVE -> {
                // Copy-on-save: threads share a capture array until one writes,
                // so forking is cheap and a write never disturbs a sibling.
                int[] next = caps.clone();
                next[inst.slot] = sp;
                addThread(list, pc + 1, sp, next, input);
            }
            case BOL -> {
                if (sp == 0) {
                    addThread(list, pc + 1, sp, caps, input);
                }
            }
            case EOL -> {
                if (sp == input.length()) {
                    addThread(list, pc + 1, sp, caps, input);
                }
            }
            default -> list.add(new Thread(pc, caps));       // CHAR, ANY, CLASS, MATCH
        }
    }

    private int[] freshCaps() {
        int[] caps = new int[prog.slotCount];
        java.util.Arrays.fill(caps, -1);
        return caps;
    }
}
