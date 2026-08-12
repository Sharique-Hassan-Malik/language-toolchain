"""Lexer for Zap. Produces a flat list of Tokens from source text."""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto


class TT(Enum):
    INT      = auto()
    IDENT    = auto()
    # keywords
    FN       = auto()
    LET      = auto()
    RETURN   = auto()
    IF       = auto()
    ELSE     = auto()
    WHILE    = auto()
    PRINT    = auto()
    TRUE     = auto()
    FALSE    = auto()
    T_INT    = auto()
    T_BOOL   = auto()
    T_VOID   = auto()
    # operators
    PLUS     = auto()
    MINUS    = auto()
    STAR     = auto()
    SLASH    = auto()
    EQ       = auto()     # =
    EQ_EQ    = auto()     # ==
    BANG     = auto()     # !
    BANG_EQ  = auto()     # !=
    LT       = auto()
    LT_EQ    = auto()
    GT       = auto()
    GT_EQ    = auto()
    AND      = auto()     # &&
    OR       = auto()     # ||
    ARROW    = auto()     # ->
    # delimiters
    LPAREN   = auto()
    RPAREN   = auto()
    LBRACE   = auto()
    RBRACE   = auto()
    COMMA    = auto()
    COLON    = auto()
    SEMI     = auto()
    # sentinel
    EOF      = auto()


KEYWORDS: dict[str, TT] = {
    "fn":     TT.FN,    "let":    TT.LET,   "return": TT.RETURN,
    "if":     TT.IF,    "else":   TT.ELSE,  "while":  TT.WHILE,
    "print":  TT.PRINT, "true":   TT.TRUE,  "false":  TT.FALSE,
    "int":    TT.T_INT, "bool":   TT.T_BOOL,"void":   TT.T_VOID,
}

TWO_CHAR: dict[str, TT] = {
    "==": TT.EQ_EQ, "!=": TT.BANG_EQ, "<=": TT.LT_EQ,
    ">=": TT.GT_EQ, "&&": TT.AND,     "||": TT.OR,  "->": TT.ARROW,
}

ONE_CHAR: dict[str, TT] = {
    "+": TT.PLUS,  "-": TT.MINUS, "*": TT.STAR,  "/": TT.SLASH,
    "=": TT.EQ,    "!": TT.BANG,  "<": TT.LT,    ">": TT.GT,
    "(": TT.LPAREN,")" :TT.RPAREN,"{": TT.LBRACE,"}": TT.RBRACE,
    ",": TT.COMMA, ":": TT.COLON, ";": TT.SEMI,
}


@dataclass(frozen=True)
class Token:
    ty:    TT
    value: str
    line:  int


class LexError(Exception):
    pass


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i, line, n = 0, 1, len(src)

    while i < n:
        c = src[i]

        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            line += 1; i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue

        if c.isdigit():
            j = i
            while i < n and src[i].isdigit():
                i += 1
            tokens.append(Token(TT.INT, src[j:i], line))
            continue

        if c.isalpha() or c == "_":
            j = i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            word = src[j:i]
            tokens.append(Token(KEYWORDS.get(word, TT.IDENT), word, line))
            continue

        two = src[i:i + 2]
        if two in TWO_CHAR:
            tokens.append(Token(TWO_CHAR[two], two, line))
            i += 2
            continue

        if c in ONE_CHAR:
            tokens.append(Token(ONE_CHAR[c], c, line))
            i += 1
            continue

        raise LexError(f"Line {line}: unexpected character {c!r}")

    tokens.append(Token(TT.EOF, "", line))
    return tokens
