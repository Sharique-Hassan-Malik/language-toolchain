//! Type checker for Zap. Walks the AST and enforces static types.

use std::collections::HashMap;
use crate::ast::*;

struct Scope {
    vars:   HashMap<String, ZapType>,
    parent: Option<Box<Scope>>,
}

impl Scope {
    fn new() -> Self { Self { vars: HashMap::new(), parent: None } }

    fn push(self) -> Self {
        Self { vars: HashMap::new(), parent: Some(Box::new(self)) }
    }

    fn pop(self) -> Self {
        *self.parent.expect("popped root scope")
    }

    fn define(&mut self, name: String, ty: ZapType) {
        self.vars.insert(name, ty);
    }

    fn lookup(&self, name: &str) -> Option<&ZapType> {
        self.vars.get(name).or_else(|| self.parent.as_ref()?.lookup(name))
    }
}

pub struct TypeChecker {
    fns:         HashMap<String, (Vec<ZapType>, ZapType)>,
    scope:       Scope,
    return_type: ZapType,
}

impl TypeChecker {
    pub fn new() -> Self {
        Self {
            fns:         HashMap::new(),
            scope:       Scope::new(),
            return_type: ZapType::Void,
        }
    }

    pub fn check(&mut self, program: &Program) -> Result<(), String> {
        for decl in &program.decls {
            if let Decl::Fn(fn_decl) = decl {
                let param_types: Vec<ZapType> = fn_decl.params.iter().map(|(_, t)| t.clone()).collect();
                self.fns.insert(fn_decl.name.clone(), (param_types, fn_decl.return_type.clone()));
            }
        }
        for decl in &program.decls {
            match decl {
                Decl::Fn(fn_decl) => self.check_fn(fn_decl)?,
                Decl::Stmt(stmt)  => self.check_stmt(stmt)?,
            }
        }
        Ok(())
    }

    fn enter(&mut self) {
        let old = std::mem::replace(&mut self.scope, Scope::new());
        self.scope = old.push();
    }

    fn leave(&mut self) {
        let old = std::mem::replace(&mut self.scope, Scope::new());
        self.scope = old.pop();
    }

    fn check_fn(&mut self, fn_decl: &FnDecl) -> Result<(), String> {
        let saved_ret = self.return_type.clone();
        self.return_type = fn_decl.return_type.clone();
        self.enter();
        for (name, ty) in &fn_decl.params {
            self.scope.define(name.clone(), ty.clone());
        }
        for stmt in &fn_decl.body.stmts { self.check_stmt(stmt)?; }
        self.leave();
        self.return_type = saved_ret;
        Ok(())
    }

    fn check_block(&mut self, block: &Block) -> Result<(), String> {
        self.enter();
        for stmt in &block.stmts { self.check_stmt(stmt)?; }
        self.leave();
        Ok(())
    }

    fn check_stmt(&mut self, stmt: &Stmt) -> Result<(), String> {
        match stmt {
            Stmt::Let(s) => {
                let got = self.check_expr(&s.value)?;
                if got != s.ty {
                    return Err(format!("Line {}: let {}: declared {}, got {}", s.line, s.name, s.ty, got));
                }
                self.scope.define(s.name.clone(), s.ty.clone());
            }
            Stmt::Return(s) => {
                let ty = match &s.value { None => ZapType::Void, Some(e) => self.check_expr(e)? };
                if ty != self.return_type {
                    return Err(format!("Line {}: return {} in {} function", s.line, ty, self.return_type));
                }
            }
            Stmt::If(s) => {
                let ct = self.check_expr(&s.cond)?;
                if ct != ZapType::Bool {
                    return Err(format!("Line {}: if condition must be bool, got {}", s.line, ct));
                }
                self.check_block(&s.then_block)?;
                if let Some(b) = &s.else_block { self.check_block(b)?; }
            }
            Stmt::While(s) => {
                let ct = self.check_expr(&s.cond)?;
                if ct != ZapType::Bool {
                    return Err(format!("Line {}: while condition must be bool, got {}", s.line, ct));
                }
                self.check_block(&s.body)?;
            }
            Stmt::Print(s) => { self.check_expr(&s.value)?; }
            Stmt::Expr(s)  => { self.check_expr(&s.expr)?; }
        }
        Ok(())
    }

    fn check_expr(&mut self, expr: &Expr) -> Result<ZapType, String> {
        match expr {
            Expr::IntLit(_, _)  => Ok(ZapType::Int),
            Expr::BoolLit(_, _) => Ok(ZapType::Bool),
            Expr::Ident(name, line) => {
                self.scope.lookup(name).cloned()
                    .ok_or_else(|| format!("Line {line}: undefined variable '{name}'"))
            }
            Expr::Assign { name, value, line } => {
                let existing = self.scope.lookup(name).cloned()
                    .ok_or_else(|| format!("Line {line}: undefined variable '{name}'"))?;
                let got = self.check_expr(value)?;
                if got != existing {
                    return Err(format!("Line {line}: cannot assign {got} to {existing} variable '{name}'"));
                }
                Ok(existing)
            }
            Expr::BinOp { op, left, right, line } => {
                let lt = self.check_expr(left)?;
                let rt = self.check_expr(right)?;
                match op.as_str() {
                    "+" | "-" | "*" | "/" => {
                        if lt != ZapType::Int || rt != ZapType::Int {
                            return Err(format!("Line {line}: {op} requires int operands, got {lt} and {rt}"));
                        }
                        Ok(ZapType::Int)
                    }
                    "<" | ">" | "<=" | ">=" => {
                        if lt != ZapType::Int || rt != ZapType::Int {
                            return Err(format!("Line {line}: {op} requires int operands"));
                        }
                        Ok(ZapType::Bool)
                    }
                    "==" | "!=" => {
                        if lt != rt {
                            return Err(format!("Line {line}: {op} requires matching types, got {lt} and {rt}"));
                        }
                        Ok(ZapType::Bool)
                    }
                    "&&" | "||" => {
                        if lt != ZapType::Bool || rt != ZapType::Bool {
                            return Err(format!("Line {line}: {op} requires bool operands"));
                        }
                        Ok(ZapType::Bool)
                    }
                    _ => Err(format!("Unknown binary operator '{op}'")),
                }
            }
            Expr::UnaryOp { op, operand, line } => {
                let ty = self.check_expr(operand)?;
                match op.as_str() {
                    "!" => {
                        if ty != ZapType::Bool { return Err(format!("Line {line}: '!' requires bool, got {ty}")); }
                        Ok(ZapType::Bool)
                    }
                    "-" => {
                        if ty != ZapType::Int { return Err(format!("Line {line}: unary '-' requires int, got {ty}")); }
                        Ok(ZapType::Int)
                    }
                    _ => Err(format!("Unknown unary operator '{op}'")),
                }
            }
            Expr::Call { name, args, line } => {
                let (param_types, ret) = self.fns.get(name).cloned()
                    .ok_or_else(|| format!("Line {line}: undefined function '{name}'"))?;
                if args.len() != param_types.len() {
                    return Err(format!("Line {line}: '{name}' expects {} args, got {}", param_types.len(), args.len()));
                }
                for (i, (arg, expected)) in args.iter().zip(param_types.iter()).enumerate() {
                    let got = self.check_expr(arg)?;
                    if got != *expected {
                        return Err(format!("Line {line}: arg {i} of '{name}': expected {expected}, got {got}"));
                    }
                }
                Ok(ret)
            }
        }
    }
}

pub fn type_check(program: &Program) -> Result<(), String> {
    TypeChecker::new().check(program)
}
