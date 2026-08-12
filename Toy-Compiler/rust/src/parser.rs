//! Recursive descent parser for Zap.

use crate::ast::*;
use crate::lexer::{Token, TT};

#[derive(Debug)]
pub struct ParseError(pub String);

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

pub struct Parser {
    tokens: Vec<Token>,
    pos:    usize,
}

impl Parser {
    pub fn new(tokens: Vec<Token>) -> Self {
        Self { tokens, pos: 0 }
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    fn cur(&self) -> &Token      { &self.tokens[self.pos] }
    fn peek(&self) -> &Token     { &self.tokens[(self.pos + 1).min(self.tokens.len() - 1)] }
    fn at(&self, ty: &TT) -> bool { &self.cur().ty == ty }
    fn line(&self) -> usize      { self.cur().line }

    fn advance(&mut self) -> Token {
        let tok = self.tokens[self.pos].clone();
        self.pos += 1;
        tok
    }

    fn eat(&mut self, ty: TT) -> Result<Token, ParseError> {
        let tok = self.cur().clone();
        if tok.ty != ty {
            return Err(ParseError(format!(
                "Line {}: expected {:?}, got {:?} ({:?})",
                tok.line, ty, tok.ty, tok.value
            )));
        }
        self.pos += 1;
        Ok(tok)
    }

    // ── top level ─────────────────────────────────────────────────────────────

    pub fn parse_program(&mut self) -> Result<Program, ParseError> {
        let mut decls = Vec::new();
        while !self.at(&TT::Eof) {
            if self.at(&TT::Fn) {
                decls.push(Decl::Fn(self.parse_fn()?));
            } else {
                decls.push(Decl::Stmt(self.parse_stmt()?));
            }
        }
        Ok(Program { decls })
    }

    fn parse_fn(&mut self) -> Result<FnDecl, ParseError> {
        let line = self.line();
        self.eat(TT::Fn)?;
        let name = self.eat(TT::Ident)?.value;
        self.eat(TT::LParen)?;
        let mut params = Vec::new();
        if !self.at(&TT::RParen) {
            params.push(self.parse_param()?);
            while self.at(&TT::Comma) {
                self.advance();
                params.push(self.parse_param()?);
            }
        }
        self.eat(TT::RParen)?;
        self.eat(TT::Arrow)?;
        let return_type = self.parse_type()?;
        let body = self.parse_block()?;
        Ok(FnDecl { name, params, return_type, body, line })
    }

    fn parse_param(&mut self) -> Result<(String, ZapType), ParseError> {
        let name = self.eat(TT::Ident)?.value;
        self.eat(TT::Colon)?;
        let ty = self.parse_type()?;
        Ok((name, ty))
    }

    fn parse_type(&mut self) -> Result<ZapType, ParseError> {
        let tok = self.cur().clone();
        match tok.ty {
            TT::TInt  => { self.advance(); Ok(ZapType::Int) }
            TT::TBool => { self.advance(); Ok(ZapType::Bool) }
            TT::TVoid => { self.advance(); Ok(ZapType::Void) }
            _ => Err(ParseError(format!("Line {}: expected type, got {:?}", tok.line, tok.value))),
        }
    }

    fn parse_block(&mut self) -> Result<Block, ParseError> {
        self.eat(TT::LBrace)?;
        let mut stmts = Vec::new();
        while !self.at(&TT::RBrace) && !self.at(&TT::Eof) {
            stmts.push(self.parse_stmt()?);
        }
        self.eat(TT::RBrace)?;
        Ok(Block { stmts })
    }

    // ── statements ────────────────────────────────────────────────────────────

    fn parse_stmt(&mut self) -> Result<Stmt, ParseError> {
        match self.cur().ty {
            TT::Let    => self.parse_let(),
            TT::Return => self.parse_return(),
            TT::If     => self.parse_if(),
            TT::While  => self.parse_while(),
            TT::Print  => self.parse_print(),
            _          => self.parse_expr_stmt(),
        }
    }

    fn parse_let(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        self.eat(TT::Let)?;
        let name = self.eat(TT::Ident)?.value;
        self.eat(TT::Colon)?;
        let ty = self.parse_type()?;
        self.eat(TT::Eq)?;
        let value = self.parse_expr()?;
        self.eat(TT::Semi)?;
        Ok(Stmt::Let(LetStmt { name, ty, value, line }))
    }

    fn parse_return(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        self.eat(TT::Return)?;
        let value = if self.at(&TT::Semi) { None } else { Some(self.parse_expr()?) };
        self.eat(TT::Semi)?;
        Ok(Stmt::Return(ReturnStmt { value, line }))
    }

    fn parse_if(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        self.eat(TT::If)?;
        let cond = self.parse_expr()?;
        let then_block = self.parse_block()?;
        let else_block = if self.at(&TT::Else) {
            self.advance();
            Some(self.parse_block()?)
        } else {
            None
        };
        Ok(Stmt::If(IfStmt { cond, then_block, else_block, line }))
    }

    fn parse_while(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        self.eat(TT::While)?;
        let cond = self.parse_expr()?;
        let body = self.parse_block()?;
        Ok(Stmt::While(WhileStmt { cond, body, line }))
    }

    fn parse_print(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        self.eat(TT::Print)?;
        self.eat(TT::LParen)?;
        let value = self.parse_expr()?;
        self.eat(TT::RParen)?;
        self.eat(TT::Semi)?;
        Ok(Stmt::Print(PrintStmt { value, line }))
    }

    fn parse_expr_stmt(&mut self) -> Result<Stmt, ParseError> {
        let line = self.line();
        let expr = self.parse_expr()?;
        self.eat(TT::Semi)?;
        Ok(Stmt::Expr(ExprStmt { expr, line }))
    }

    // ── expressions ───────────────────────────────────────────────────────────

    fn parse_expr(&mut self) -> Result<Expr, ParseError> {
        self.parse_assign()
    }

    fn parse_assign(&mut self) -> Result<Expr, ParseError> {
        if self.at(&TT::Ident) && self.peek().ty == TT::Eq {
            let line  = self.line();
            let name  = self.advance().value;
            self.advance(); // consume '='
            let value = Box::new(self.parse_assign()?);
            return Ok(Expr::Assign { name, value, line });
        }
        self.parse_or()
    }

    fn parse_or(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_and()?;
        while self.at(&TT::Or) {
            let line = self.line();
            self.advance();
            left = Expr::BinOp { op: "||".into(), left: Box::new(left), right: Box::new(self.parse_and()?), line };
        }
        Ok(left)
    }

    fn parse_and(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_eq()?;
        while self.at(&TT::And) {
            let line = self.line();
            self.advance();
            left = Expr::BinOp { op: "&&".into(), left: Box::new(left), right: Box::new(self.parse_eq()?), line };
        }
        Ok(left)
    }

    fn parse_eq(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_cmp()?;
        while matches!(self.cur().ty, TT::EqEq | TT::BangEq) {
            let line = self.line();
            let op = self.advance().value;
            left = Expr::BinOp { op, left: Box::new(left), right: Box::new(self.parse_cmp()?), line };
        }
        Ok(left)
    }

    fn parse_cmp(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_add()?;
        while matches!(self.cur().ty, TT::Lt | TT::Gt | TT::LtEq | TT::GtEq) {
            let line = self.line();
            let op = self.advance().value;
            left = Expr::BinOp { op, left: Box::new(left), right: Box::new(self.parse_add()?), line };
        }
        Ok(left)
    }

    fn parse_add(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_mul()?;
        while matches!(self.cur().ty, TT::Plus | TT::Minus) {
            let line = self.line();
            let op = self.advance().value;
            left = Expr::BinOp { op, left: Box::new(left), right: Box::new(self.parse_mul()?), line };
        }
        Ok(left)
    }

    fn parse_mul(&mut self) -> Result<Expr, ParseError> {
        let mut left = self.parse_unary()?;
        while matches!(self.cur().ty, TT::Star | TT::Slash) {
            let line = self.line();
            let op = self.advance().value;
            left = Expr::BinOp { op, left: Box::new(left), right: Box::new(self.parse_unary()?), line };
        }
        Ok(left)
    }

    fn parse_unary(&mut self) -> Result<Expr, ParseError> {
        if self.at(&TT::Bang) {
            let line = self.line(); self.advance();
            return Ok(Expr::UnaryOp { op: "!".into(), operand: Box::new(self.parse_unary()?), line });
        }
        if self.at(&TT::Minus) {
            let line = self.line(); self.advance();
            return Ok(Expr::UnaryOp { op: "-".into(), operand: Box::new(self.parse_unary()?), line });
        }
        self.parse_call()
    }

    fn parse_call(&mut self) -> Result<Expr, ParseError> {
        let prim = self.parse_primary()?;
        if let Expr::Ident(ref name, _) = prim {
            if self.at(&TT::LParen) {
                let line = self.line();
                let name = name.clone();
                self.advance();
                let mut args = Vec::new();
                if !self.at(&TT::RParen) {
                    args.push(self.parse_expr()?);
                    while self.at(&TT::Comma) {
                        self.advance();
                        args.push(self.parse_expr()?);
                    }
                }
                self.eat(TT::RParen)?;
                return Ok(Expr::Call { name, args, line });
            }
        }
        Ok(prim)
    }

    fn parse_primary(&mut self) -> Result<Expr, ParseError> {
        let tok = self.cur().clone();
        match tok.ty {
            TT::Int => {
                self.advance();
                let v: i64 = tok.value.parse().map_err(|_| {
                    ParseError(format!("Line {}: invalid integer {:?}", tok.line, tok.value))
                })?;
                Ok(Expr::IntLit(v, tok.line))
            }
            TT::True  => { self.advance(); Ok(Expr::BoolLit(true,  tok.line)) }
            TT::False => { self.advance(); Ok(Expr::BoolLit(false, tok.line)) }
            TT::Ident => { self.advance(); Ok(Expr::Ident(tok.value, tok.line)) }
            TT::LParen => {
                self.advance();
                let e = self.parse_expr()?;
                self.eat(TT::RParen)?;
                Ok(e)
            }
            _ => Err(ParseError(format!(
                "Line {}: unexpected token {:?} ({:?})",
                tok.line, tok.ty, tok.value
            ))),
        }
    }
}

pub fn parse(src: &str) -> Result<Program, String> {
    let tokens = crate::lexer::tokenize(src).map_err(|e| e.to_string())?;
    Parser::new(tokens).parse_program().map_err(|e| e.to_string())
}
