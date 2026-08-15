"""
CDCL (Conflict-Driven Clause Learning) SAT solver.

Algorithm:
    1. Unit propagation (BCP): repeatedly apply unit rule until no unit
       clauses remain or a conflict is detected.
    2. VSIDS decision heuristic: pick the unassigned variable that appears
       most frequently in recently learned conflict clauses.
    3. Conflict analysis: when a conflict occurs, analyse the implication
       graph to derive a conflict clause (learned clause) and a backjump
       level.
    4. Backjump: undo assignments to the backjump level and enqueue the
       asserting literal from the learned clause.
    5. Restart: periodically restart from level 0 while retaining learned
       clauses (Luby restart strategy).

This is a complete solver: it will always find a solution or prove UNSAT.

References:
    Marques-Silva & Sakallah, GRASP (1999)
    Moskewicz et al., Chaff (2001)
    Audemard & Simon, Glucose (2009)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class SolverResult(Enum):
    SAT   = "SAT"
    UNSAT = "UNSAT"


@dataclass
class Assignment:
    value:  bool
    level:  int          # decision level at which this was assigned
    reason: list[int] | None  # clause that forced this (None = decision)


class CDCLSolver:
    """
    CDCL SAT solver operating on integer literals.

    Positive integer i → variable i is True.
    Negative integer i → variable i is False.
    """

    def __init__(self, num_vars: int, clauses: list[list[int]]):
        self._num_vars  = num_vars
        self._clauses:  list[list[int]] = [list(c) for c in clauses]
        self._learned:  list[list[int]] = []

        # Assignment map: var_id → Assignment (1-indexed)
        self._assign: dict[int, Assignment] = {}

        # Decision level
        self._level: int = 0

        # Trail: sequence of assigned literals in order
        self._trail: list[int] = []
        self._trail_lim: list[int] = []   # index into trail for each decision level

        # Occurrence lists: var_id → list of clause indices
        self._occurs: dict[int, list[int]] = defaultdict(list)
        self._build_occurs()

        # VSIDS scores
        self._scores: dict[int, float] = defaultdict(float)
        self._score_bump = 1.0
        self._score_decay = 0.95

        # Propagation queue
        self._prop_queue: list[int] = []

        # Restart schedule (Luby sequence)
        self._luby_unit = 512
        self._conflicts_since_restart = 0
        self._luby_idx = 0

    # ── Public interface ──────────────────────────────────────────────────

    def solve(self) -> tuple[SolverResult, dict[int, bool]]:
        """
        Return (SAT, assignment) or (UNSAT, {}).

        The assignment maps var_id → bool for all variables.
        """
        # Handle trivially empty clauses (immediate UNSAT)
        if any(len(c) == 0 for c in self._clauses):
            return SolverResult.UNSAT, {}

        # Initial unit propagation
        for c_idx, clause in enumerate(self._clauses):
            if len(clause) == 1:
                lit = clause[0]
                if not self._enqueue(lit, reason=clause):
                    return SolverResult.UNSAT, {}

        conflict = self._propagate()
        if conflict is not None:
            return SolverResult.UNSAT, {}

        while True:
            lit = self._pick_branch()
            if lit is None:
                # All variables assigned — SAT
                return SolverResult.SAT, {v: a.value for v, a in self._assign.items()}

            # Decision
            self._level += 1
            self._trail_lim.append(len(self._trail))
            self._enqueue(lit, reason=None)

            while True:
                conflict = self._propagate()
                if conflict is None:
                    break   # no conflict — continue search

                self._conflicts_since_restart += 1
                self._bump_scores(conflict)

                if self._level == 0:
                    return SolverResult.UNSAT, {}

                learned, backjump = self._analyse(conflict)

                if not learned:
                    return SolverResult.UNSAT, {}

                self._learn(learned)
                self._backjump(backjump)

                # The asserting literal is the one not yet set at backjump level
                asserting = next(
                    (l for l in learned if self._var(l) not in self._assign),
                    learned[0],
                )
                self._enqueue(asserting, reason=learned)

                # Restart?
                if self._should_restart():
                    self._restart()
                    break

    # ── Core DPLL/CDCL operations ─────────────────────────────────────────

    def _propagate(self) -> list[int] | None:
        """
        Boolean Constraint Propagation.  Returns the conflicting clause or None.
        """
        while self._prop_queue:
            lit = self._prop_queue.pop(0)
            var = self._var(lit)
            for c_idx in list(self._occurs.get(var, [])):
                clause = self._get_clause(c_idx)
                if clause is None:
                    continue

                # Count unset and falsified literals
                unset = []
                satisfied = False
                for l in clause:
                    if self._lit_value(l) is True:
                        satisfied = True
                        break
                    if self._lit_value(l) is None:
                        unset.append(l)

                if satisfied:
                    continue

                if not unset:
                    # All literals false — conflict
                    return clause

                if len(unset) == 1:
                    # Unit clause — propagate
                    if not self._enqueue(unset[0], reason=clause):
                        return clause

        return None

    def _pick_branch(self) -> int | None:
        """VSIDS: pick the highest-scoring unassigned variable."""
        best_var, best_score = None, -1.0
        for v in range(1, self._num_vars + 1):
            if v not in self._assign:
                s = self._scores.get(v, 0.0)
                if s > best_score:
                    best_score = s
                    best_var = v
        if best_var is None:
            return None
        # Prefer the polarity seen in more learned clauses
        pos = sum(1 for c in self._learned if best_var in c)
        neg = sum(1 for c in self._learned if -best_var in c)
        return best_var if pos >= neg else -best_var

    def _analyse(self, conflict: list[int]) -> tuple[list[int], int]:
        """
        1-UIP conflict analysis.

        Resolve the conflict clause against reason clauses by walking
        backwards along the trail until only one literal from the current
        decision level remains (the UIP literal).

        Returns (learned_clause, backjump_level).
        """
        seen: set[int] = set()
        learned: list[int] = []
        counter = 0
        trail_pos = len(self._trail) - 1

        clause = conflict
        while True:
            for lit in clause:
                var = self._var(lit)
                if var in seen:
                    continue
                seen.add(var)
                a = self._assign.get(var)
                if a is None:
                    continue
                if a.level == self._level:
                    counter += 1
                elif a.level > 0:
                    learned.append(-lit if self._assign[var].value else lit)

            # Find the last assigned variable in the trail that is in seen
            while trail_pos >= 0:
                v = self._var(self._trail[trail_pos])
                trail_pos -= 1
                if v in seen:
                    break
            else:
                break

            counter -= 1
            if counter == 0:
                a = self._assign.get(v)
                if a is not None:
                    uip_lit = v if not a.value else -v
                    learned = [uip_lit] + learned
                break

            a = self._assign.get(v)
            if a is None or a.reason is None:
                break
            clause = a.reason

        if not learned:
            return [], 0

        # Backjump level: second-highest decision level in the learned clause
        levels = sorted(
            {self._assign[self._var(l)].level
             for l in learned
             if self._var(l) in self._assign and self._assign[self._var(l)].level > 0},
            reverse=True,
        )
        backjump = levels[1] if len(levels) >= 2 else 0
        return learned, backjump

    def _learn(self, clause: list[int]):
        idx = len(self._clauses) + len(self._learned)
        self._learned.append(clause)
        for lit in clause:
            self._occurs[self._var(lit)].append(-(len(self._learned)))

    def _backjump(self, level: int):
        while self._level > level:
            if self._trail_lim:
                lim = self._trail_lim.pop()
                while len(self._trail) > lim:
                    lit = self._trail.pop()
                    var = self._var(lit)
                    self._assign.pop(var, None)
            self._level -= 1
        self._prop_queue.clear()

    def _enqueue(self, lit: int, reason: list[int] | None) -> bool:
        var = self._var(lit)
        value = lit > 0
        if var in self._assign:
            return self._assign[var].value == value   # already assigned
        self._assign[var] = Assignment(value=value, level=self._level, reason=reason)
        self._trail.append(lit)
        self._prop_queue.append(lit)
        return True

    # ── Heuristics ────────────────────────────────────────────────────────

    def _bump_scores(self, conflict: list[int]):
        for lit in conflict:
            self._scores[self._var(lit)] += self._score_bump
        # Decay all scores periodically
        if len(self._learned) % 100 == 0:
            for v in self._scores:
                self._scores[v] *= self._score_decay
            self._score_bump /= self._score_decay

    def _should_restart(self) -> bool:
        limit = self._luby_unit * _luby(self._luby_idx + 1)
        if self._conflicts_since_restart >= limit:
            self._luby_idx += 1
            self._conflicts_since_restart = 0
            return True
        return False

    def _restart(self):
        self._backjump(0)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_occurs(self):
        for i, clause in enumerate(self._clauses):
            for lit in clause:
                self._occurs[self._var(lit)].append(i)

    def _get_clause(self, idx: int) -> list[int] | None:
        if idx >= 0:
            return self._clauses[idx] if idx < len(self._clauses) else None
        learned_idx = -(idx + 1)
        return self._learned[learned_idx] if learned_idx < len(self._learned) else None

    def _lit_value(self, lit: int) -> bool | None:
        var = self._var(lit)
        a   = self._assign.get(var)
        if a is None:
            return None
        return a.value if lit > 0 else not a.value

    @staticmethod
    def _var(lit: int) -> int:
        return abs(lit)


def _luby(i: int) -> int:
    """Luby restart sequence: 1,1,2,1,1,2,4,1,1,2,1,1,2,4,8,..."""
    k = 1
    while k < i + 1:
        k <<= 1
    if k == i + 1:
        return k >> 1
    return _luby(i - (k >> 1) + 1)
