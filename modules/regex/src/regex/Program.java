package regex;

import java.util.ArrayList;
import java.util.List;

/**
 * A compiled pattern: a flat array of instructions for the {@link Pike} VM.
 *
 * The instruction set is Thompson's, as popularised by Russ Cox. It is
 * deliberately tiny — nine opcodes — because the entire linear-time guarantee
 * rests on the VM being able to treat the program as a graph of at most
 * {@code program.length} states, and a small instruction set keeps that graph
 * small.
 *
 * The two control-flow opcodes are the whole trick:
 * <ul>
 *   <li>{@code SPLIT x, y} — the current thread forks into two, trying {@code x}
 *       first and {@code y} second. Alternation and every quantifier compile to
 *       a SPLIT. This is where a backtracking engine would instead push a
 *       choice point and, on failure, retry — the step that goes exponential.
 *   <li>{@code JMP x} — an unconditional branch, used to loop a quantifier back
 *       to its SPLIT.
 * </ul>
 * Because the VM runs all threads in lockstep and discards duplicates by program
 * counter, forking can never produce more than {@code program.length} live
 * threads at any input position. That bound is what a SPLIT buys over a
 * backtracking retry.
 */
final class Program {
    enum Op { CHAR, ANY, CLASS, MATCH, JMP, SPLIT, SAVE, BOL, EOL }

    /** One instruction. Only the fields relevant to its op are meaningful. */
    static final class Inst {
        final Op op;
        char ch;                 // CHAR
        int x, y;                // JMP target (x); SPLIT targets (x, y)
        int slot;                // SAVE slot
        Ast.CharClass cls;       // CLASS

        Inst(Op op) {
            this.op = op;
        }

        @Override
        public String toString() {
            return switch (op) {
                case CHAR -> "char '" + ch + "'";
                case ANY -> "any";
                case CLASS -> "class " + (cls.negated() ? "[^…]" : "[…]");
                case MATCH -> "match";
                case JMP -> "jmp " + x;
                case SPLIT -> "split " + x + ", " + y;
                case SAVE -> "save " + slot;
                case BOL -> "assert ^";
                case EOL -> "assert $";
            };
        }
    }

    final Inst[] insts;
    /** Number of capture slots = 2 * (groups + 1). Slots 0,1 are the whole match. */
    final int slotCount;

    private Program(Inst[] insts, int slotCount) {
        this.insts = insts;
        this.slotCount = slotCount;
    }

    static Program compile(Ast ast, int groupCount) {
        List<Inst> out = new ArrayList<>();
        Inst save0 = new Inst(Op.SAVE);
        save0.slot = 0;
        out.add(save0);                              // record whole-match start
        emit(out, ast);
        Inst save1 = new Inst(Op.SAVE);
        save1.slot = 1;
        out.add(save1);                              // record whole-match end
        out.add(new Inst(Op.MATCH));
        return new Program(out.toArray(new Inst[0]), 2 * groupCount);
    }

    // -- code generation -----------------------------------------------------

    private static void emit(List<Inst> out, Ast node) {
        switch (node) {
            case Ast.Empty ignored -> { }

            case Ast.Lit lit -> {
                Inst i = new Inst(Op.CHAR);
                i.ch = lit.ch();
                out.add(i);
            }

            case Ast.Dot ignored -> out.add(new Inst(Op.ANY));

            case Ast.Begin ignored -> out.add(new Inst(Op.BOL));

            case Ast.End ignored -> out.add(new Inst(Op.EOL));

            case Ast.CharClass cls -> {
                Inst i = new Inst(Op.CLASS);
                i.cls = cls;
                out.add(i);
            }

            case Ast.Concat c -> {
                emit(out, c.left());
                emit(out, c.right());
            }

            case Ast.Group g -> {
                Inst open = new Inst(Op.SAVE);
                open.slot = 2 * g.index();
                out.add(open);
                emit(out, g.body());
                Inst close = new Inst(Op.SAVE);
                close.slot = 2 * g.index() + 1;
                out.add(close);
            }

            // alt := split L1, L2 ; L1: <left> ; jmp End ; L2: <right> ; End:
            case Ast.Alt a -> {
                Inst split = new Inst(Op.SPLIT);
                out.add(split);
                split.x = out.size();
                emit(out, a.left());
                Inst jmp = new Inst(Op.JMP);
                out.add(jmp);
                split.y = out.size();
                emit(out, a.right());
                jmp.x = out.size();
            }

            // star := L1: split Body, End ; Body: <body> ; jmp L1 ; End:
            case Ast.Star s -> {
                int l1 = out.size();
                Inst split = new Inst(Op.SPLIT);
                out.add(split);
                int body = out.size();
                emit(out, s.body());
                Inst jmp = new Inst(Op.JMP);
                jmp.x = l1;
                out.add(jmp);
                int end = out.size();
                setPriority(split, s.greedy(), body, end);
            }

            // plus := Body: <body> ; split Body, End ; End:
            case Ast.Plus p -> {
                int body = out.size();
                emit(out, p.body());
                Inst split = new Inst(Op.SPLIT);
                out.add(split);
                int end = out.size();
                setPriority(split, p.greedy(), body, end);
            }

            // quest := split Body, End ; Body: <body> ; End:
            case Ast.Quest q -> {
                Inst split = new Inst(Op.SPLIT);
                out.add(split);
                int body = out.size();
                emit(out, q.body());
                int end = out.size();
                setPriority(split, q.greedy(), body, end);
            }
        }
    }

    /**
     * Greedy and lazy differ only in which SPLIT branch has priority.
     *
     * A SPLIT tries {@code x} before {@code y}. Greedy means "try to match the
     * body again before giving up", so the body branch goes first; lazy means
     * "try to stop before matching more", so the exit branch goes first. Same
     * instruction, opposite ordering — the reason {@code a*} and {@code a*?}
     * cost exactly the same to run.
     */
    private static void setPriority(Inst split, boolean greedy, int bodyTarget, int exitTarget) {
        if (greedy) {
            split.x = bodyTarget;
            split.y = exitTarget;
        } else {
            split.x = exitTarget;
            split.y = bodyTarget;
        }
    }

    String disassemble() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < insts.length; i++) {
            sb.append(String.format("%3d: %s%n", i, insts[i]));
        }
        return sb.toString();
    }
}
