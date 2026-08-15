//! Code generator: AST → flat bytecode for the Zap stack VM.
//!
//! Jump offsets are signed integers relative to the instruction after the jump.
//! JMP  n  →  ip += n  (signed)
//! JF   n  →  if !pop(): ip += n

use std::collections::HashMap;
use crate::ast::*;

#[derive(Debug, Clone, PartialEq)]
pub enum Op {
    PushInt, PushBool,
    Load, Store,
    Add, Sub, Mul, Div,
    Eq, Neq, Lt, Gt, Leq, Geq,
    And, Or, Not, Neg,
    Jmp, JmpFalse,
    Call,
    Ret,
    Print,
    Pop,
    Halt,
}

#[derive(Debug, Clone)]
pub struct Instr {
    pub op:   Op,
    pub ival: i64,        // integer or bool (0/1) payload
    pub sval: String,     // string payload (Load/Store/Call)
    pub arg2: usize,      // CALL: nargs
}

impl Instr {
    fn int(op: Op, n: i64)  -> Self { Instr { op, ival: n, sval: String::new(), arg2: 0 } }
    fn bool(b: bool)         -> Self { Instr { op: Op::PushBool, ival: b as i64, sval: String::new(), arg2: 0 } }
    fn name(op: Op, s: &str) -> Self { Instr { op, ival: 0, sval: s.to_string(), arg2: 0 } }
    fn call(fn_name: &str, nargs: usize) -> Self {
        Instr { op: Op::Call, ival: 0, sval: fn_name.to_string(), arg2: nargs }
    }
    fn simple(op: Op) -> Self { Instr { op, ival: 0, sval: String::new(), arg2: 0 } }

    pub fn display(&self) -> String {
        match self.op {
            Op::PushInt  => format!("PUSH_INT  {}", self.ival),
            Op::PushBool => format!("PUSH_BOOL {}", self.ival != 0),
            Op::Load     => format!("LOAD      {}", self.sval),
            Op::Store    => format!("STORE     {}", self.sval),
            Op::Jmp      => format!("JMP       {}", self.ival),
            Op::JmpFalse => format!("JMP_FALSE {}", self.ival),
            Op::Call     => format!("CALL      {} {}", self.sval, self.arg2),
            _            => format!("{}", match self.op {
                Op::Add  => "ADD",  Op::Sub  => "SUB", Op::Mul  => "MUL", Op::Div => "DIV",
                Op::Eq   => "EQ",   Op::Neq  => "NEQ", Op::Lt   => "LT",  Op::Gt  => "GT",
                Op::Leq  => "LEQ",  Op::Geq  => "GEQ", Op::And  => "AND", Op::Or  => "OR",
                Op::Not  => "NOT",  Op::Neg  => "NEG", Op::Ret  => "RET", Op::Pop => "POP",
                Op::Halt => "HALT", Op::Print => "PRINT",
                _ => "???",
            }),
        }
    }
}

#[derive(Debug, Clone)]
pub struct FnChunk {
    pub params: Vec<String>,
    pub code:   Vec<Instr>,
}

#[derive(Debug, Clone)]
pub struct CompiledProgram {
    pub functions: HashMap<String, FnChunk>,
    pub entry:     String,
}

impl CompiledProgram {
    pub fn disassemble(&self) -> String {
        let mut out = String::new();
        for (name, chunk) in &self.functions {
            out.push_str(&format!("fn {}({}):\n", name, chunk.params.join(", ")));
            for (i, ins) in chunk.code.iter().enumerate() {
                out.push_str(&format!("  {:4}  {}\n", i, ins.display()));
            }
        }
        out
    }
}

pub struct CodeGen {
    prog:    CompiledProgram,
    current: String,   // name of function being compiled
}

impl CodeGen {
    pub fn new() -> Self {
        let mut functions = HashMap::new();
        functions.insert("__main__".to_string(), FnChunk { params: vec![], code: vec![] });
        CodeGen {
            prog: CompiledProgram { functions, entry: "__main__".to_string() },
            current: "__main__".to_string(),
        }
    }

    pub fn compile(mut self, program: &Program) -> CompiledProgram {
        // Pre-declare all functions so CALL can reference them.
        for decl in &program.decls {
            if let Decl::Fn(fn_decl) = decl {
                let params = fn_decl.params.iter().map(|(n, _)| n.clone()).collect();
                self.prog.functions.insert(
                    fn_decl.name.clone(),
                    FnChunk { params, code: vec![] },
                );
            }
        }

        for decl in &program.decls {
            match decl {
                Decl::Fn(fn_decl) => self.compile_fn(fn_decl),
                Decl::Stmt(stmt)  => {
                    self.current = "__main__".to_string();
                    self.compile_stmt(stmt);
                }
            }
        }

        // Ensure __main__ ends with HALT.
        self.current = "__main__".to_string();
        let code = &self.prog.functions["__main__"].code;
        if code.is_empty() || code.last().map(|i| &i.op) != Some(&Op::Halt) {
            self.emit(Instr::simple(Op::Halt));
        }

        // Prefer user-defined 'main' as entry.
        if self.prog.functions.contains_key("main") {
            self.prog.entry = "main".to_string();
        }

        self.prog
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    fn emit(&mut self, ins: Instr) {
        self.prog.functions.get_mut(&self.current).unwrap().code.push(ins);
    }

    fn here(&self) -> usize {
        self.prog.functions[&self.current].code.len()
    }

    fn patch(&mut self, idx: usize, target: usize) {
        let offset = target as i64 - idx as i64 - 1;
        self.prog.functions.get_mut(&self.current).unwrap().code[idx].ival = offset;
    }

    // ── functions ─────────────────────────────────────────────────────────────

    fn compile_fn(&mut self, fn_decl: &FnDecl) {
        self.current = fn_decl.name.clone();
        for stmt in &fn_decl.body.stmts {
            self.compile_stmt(stmt);
        }
        let code = &self.prog.functions[&self.current].code;
        if code.is_empty() || code.last().map(|i| &i.op) != Some(&Op::Ret) {
            self.emit(Instr::bool(false));
            self.emit(Instr::simple(Op::Ret));
        }
    }

    // ── statements ────────────────────────────────────────────────────────────

    fn compile_stmt(&mut self, stmt: &Stmt) {
        match stmt {
            Stmt::Let(s) => {
                self.compile_expr(&s.value);
                self.emit(Instr::name(Op::Store, &s.name));
            }
            Stmt::Return(s) => {
                match &s.value {
                    Some(e) => self.compile_expr(e),
                    None    => self.emit(Instr::bool(false)),
                }
                self.emit(Instr::simple(Op::Ret));
            }
            Stmt::If(s) => {
                self.compile_expr(&s.cond);
                let jf = self.here();
                self.emit(Instr::int(Op::JmpFalse, 0));
                for stmt in &s.then_block.stmts { self.compile_stmt(stmt); }
                if let Some(else_b) = &s.else_block {
                    let jmp = self.here();
                    self.emit(Instr::int(Op::Jmp, 0));
                    self.patch(jf, self.here());
                    for stmt in &else_b.stmts { self.compile_stmt(stmt); }
                    self.patch(jmp, self.here());
                } else {
                    self.patch(jf, self.here());
                }
            }
            Stmt::While(s) => {
                let loop_start = self.here();
                self.compile_expr(&s.cond);
                let jf = self.here();
                self.emit(Instr::int(Op::JmpFalse, 0));
                for stmt in &s.body.stmts { self.compile_stmt(stmt); }
                let back = self.here();
                let offset = loop_start as i64 - back as i64 - 1;
                self.emit(Instr::int(Op::Jmp, offset));
                self.patch(jf, self.here());
            }
            Stmt::Print(s) => {
                self.compile_expr(&s.value);
                self.emit(Instr::simple(Op::Print));
            }
            Stmt::Expr(s) => {
                self.compile_expr(&s.expr);
                if !s.expr.is_assign() {
                    self.emit(Instr::simple(Op::Pop));
                }
            }
        }
    }

    // ── expressions ───────────────────────────────────────────────────────────

    fn compile_expr(&mut self, expr: &Expr) {
        match expr {
            Expr::IntLit(v, _)  => self.emit(Instr::int(Op::PushInt, *v)),
            Expr::BoolLit(b, _) => self.emit(Instr::bool(*b)),
            Expr::Ident(n, _)   => self.emit(Instr::name(Op::Load, n)),
            Expr::Assign { name, value, .. } => {
                self.compile_expr(value);
                self.emit(Instr::name(Op::Store, name));
            }
            Expr::BinOp { op, left, right, .. } => {
                self.compile_expr(left);
                self.compile_expr(right);
                let op_code = match op.as_str() {
                    "+"  => Op::Add, "-"  => Op::Sub, "*"  => Op::Mul, "/" => Op::Div,
                    "==" => Op::Eq,  "!=" => Op::Neq,
                    "<"  => Op::Lt,  ">"  => Op::Gt, "<=" => Op::Leq, ">=" => Op::Geq,
                    "&&" => Op::And, "||" => Op::Or,
                    _    => panic!("unknown op: {op}"),
                };
                self.emit(Instr::simple(op_code));
            }
            Expr::UnaryOp { op, operand, .. } => {
                self.compile_expr(operand);
                self.emit(Instr::simple(if op == "!" { Op::Not } else { Op::Neg }));
            }
            Expr::Call { name, args, .. } => {
                for arg in args { self.compile_expr(arg); }
                self.emit(Instr::call(name, args.len()));
            }
        }
    }
}

pub fn compile_program(program: &Program) -> CompiledProgram {
    CodeGen::new().compile(program)
}
