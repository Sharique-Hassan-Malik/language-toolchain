//! Lexer for Zap. Produces a Vec<Token> from source text.

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TT {
    Int, Ident,
    // keywords
    Fn, Let, Return, If, Else, While, Print, True, False,
    TInt, TBool, TVoid,
    // operators
    Plus, Minus, Star, Slash,
    Eq, EqEq, Bang, BangEq,
    Lt, LtEq, Gt, GtEq,
    And, Or, Arrow,
    // delimiters
    LParen, RParen, LBrace, RBrace,
    Comma, Colon, Semi,
    Eof,
}

#[derive(Debug, Clone)]
pub struct Token {
    pub ty:    TT,
    pub value: String,
    pub line:  usize,
}

#[derive(Debug)]
pub struct LexError(pub String);

impl std::fmt::Display for LexError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

pub fn tokenize(src: &str) -> Result<Vec<Token>, LexError> {
    let chars: Vec<char> = src.chars().collect();
    let mut tokens = Vec::new();
    let mut i = 0;
    let mut line = 1usize;
    let n = chars.len();

    while i < n {
        let c = chars[i];

        if " \t\r".contains(c) { i += 1; continue; }
        if c == '\n'            { line += 1; i += 1; continue; }

        // line comment
        if c == '/' && i + 1 < n && chars[i + 1] == '/' {
            while i < n && chars[i] != '\n' { i += 1; }
            continue;
        }

        // integer
        if c.is_ascii_digit() {
            let start = i;
            while i < n && chars[i].is_ascii_digit() { i += 1; }
            tokens.push(tok(TT::Int, &chars[start..i], line));
            continue;
        }

        // identifier / keyword
        if c.is_alphabetic() || c == '_' {
            let start = i;
            while i < n && (chars[i].is_alphanumeric() || chars[i] == '_') { i += 1; }
            let word: String = chars[start..i].iter().collect();
            let ty = keyword(&word);
            tokens.push(Token { ty, value: word, line });
            continue;
        }

        // two-char tokens
        if i + 1 < n {
            let two: String = chars[i..i + 2].iter().collect();
            if let Some(tt) = two_char(&two) {
                tokens.push(Token { ty: tt, value: two, line });
                i += 2;
                continue;
            }
        }

        // single-char tokens
        if let Some(tt) = one_char(c) {
            tokens.push(Token { ty: tt, value: c.to_string(), line });
            i += 1;
            continue;
        }

        return Err(LexError(format!("Line {line}: unexpected character {c:?}")));
    }

    tokens.push(Token { ty: TT::Eof, value: String::new(), line });
    Ok(tokens)
}

fn tok(ty: TT, chars: &[char], line: usize) -> Token {
    Token { ty, value: chars.iter().collect(), line }
}

fn keyword(s: &str) -> TT {
    match s {
        "fn"     => TT::Fn,     "let"    => TT::Let,   "return" => TT::Return,
        "if"     => TT::If,     "else"   => TT::Else,  "while"  => TT::While,
        "print"  => TT::Print,  "true"   => TT::True,  "false"  => TT::False,
        "int"    => TT::TInt,   "bool"   => TT::TBool, "void"   => TT::TVoid,
        _        => TT::Ident,
    }
}

fn two_char(s: &str) -> Option<TT> {
    match s {
        "==" => Some(TT::EqEq), "!=" => Some(TT::BangEq),
        "<=" => Some(TT::LtEq), ">=" => Some(TT::GtEq),
        "&&" => Some(TT::And),  "||" => Some(TT::Or),
        "->" => Some(TT::Arrow),
        _    => None,
    }
}

fn one_char(c: char) -> Option<TT> {
    match c {
        '+' => Some(TT::Plus),   '-' => Some(TT::Minus),
        '*' => Some(TT::Star),   '/' => Some(TT::Slash),
        '=' => Some(TT::Eq),     '!' => Some(TT::Bang),
        '<' => Some(TT::Lt),     '>' => Some(TT::Gt),
        '(' => Some(TT::LParen), ')' => Some(TT::RParen),
        '{' => Some(TT::LBrace), '}' => Some(TT::RBrace),
        ',' => Some(TT::Comma),  ':' => Some(TT::Colon),
        ';' => Some(TT::Semi),
        _   => None,
    }
}
