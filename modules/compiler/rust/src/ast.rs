//! AST node types for Zap.

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ZapType {
    Int,
    Bool,
    Void,
}

impl std::fmt::Display for ZapType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ZapType::Int  => write!(f, "int"),
            ZapType::Bool => write!(f, "bool"),
            ZapType::Void => write!(f, "void"),
        }
    }
}

// ── Top level ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct Program {
    pub decls: Vec<Decl>,
}

#[derive(Debug, Clone)]
pub enum Decl {
    Fn(FnDecl),
    Stmt(Stmt),
}

#[derive(Debug, Clone)]
pub struct FnDecl {
    pub name:        String,
    pub params:      Vec<(String, ZapType)>,
    pub return_type: ZapType,
    pub body:        Block,
    pub line:        usize,
}

#[derive(Debug, Clone)]
pub struct Block {
    pub stmts: Vec<Stmt>,
}

// ── Statements ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub enum Stmt {
    Let(LetStmt),
    Return(ReturnStmt),
    If(IfStmt),
    While(WhileStmt),
    Print(PrintStmt),
    Expr(ExprStmt),
}

#[derive(Debug, Clone)]
pub struct LetStmt {
    pub name:  String,
    pub ty:    ZapType,
    pub value: Expr,
    pub line:  usize,
}

#[derive(Debug, Clone)]
pub struct ReturnStmt {
    pub value: Option<Expr>,
    pub line:  usize,
}

#[derive(Debug, Clone)]
pub struct IfStmt {
    pub cond:       Expr,
    pub then_block: Block,
    pub else_block: Option<Block>,
    pub line:       usize,
}

#[derive(Debug, Clone)]
pub struct WhileStmt {
    pub cond: Expr,
    pub body: Block,
    pub line: usize,
}

#[derive(Debug, Clone)]
pub struct PrintStmt {
    pub value: Expr,
    pub line:  usize,
}

#[derive(Debug, Clone)]
pub struct ExprStmt {
    pub expr: Expr,
    pub line: usize,
}

// ── Expressions ───────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub enum Expr {
    IntLit(i64, usize),
    BoolLit(bool, usize),
    Ident(String, usize),
    BinOp {
        op:    String,
        left:  Box<Expr>,
        right: Box<Expr>,
        line:  usize,
    },
    UnaryOp {
        op:      String,
        operand: Box<Expr>,
        line:    usize,
    },
    Call {
        name: String,
        args: Vec<Expr>,
        line: usize,
    },
    Assign {
        name:  String,
        value: Box<Expr>,
        line:  usize,
    },
}

impl Expr {
    pub fn line(&self) -> usize {
        match self {
            Expr::IntLit(_, l)     => *l,
            Expr::BoolLit(_, l)    => *l,
            Expr::Ident(_, l)      => *l,
            Expr::BinOp { line, .. }    => *line,
            Expr::UnaryOp { line, .. }  => *line,
            Expr::Call { line, .. }     => *line,
            Expr::Assign { line, .. }   => *line,
        }
    }

    pub fn is_assign(&self) -> bool {
        matches!(self, Expr::Assign { .. })
    }
}
