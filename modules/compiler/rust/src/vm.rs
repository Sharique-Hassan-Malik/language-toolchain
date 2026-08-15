//! Stack-based virtual machine for Zap bytecode.

use std::collections::HashMap;
use crate::codegen::{CompiledProgram, FnChunk, Op};

#[derive(Debug, Clone)]
pub enum Value {
    Int(i64),
    Bool(bool),
}

impl Value {
    fn as_int(&self, line_hint: &str) -> Result<i64, String> {
        match self {
            Value::Int(n) => Ok(*n),
            _ => Err(format!("runtime: expected int {line_hint}")),
        }
    }
    fn is_truthy(&self) -> bool {
        match self {
            Value::Bool(b) => *b,
            Value::Int(n)  => *n != 0,
        }
    }
    pub fn display(&self) -> String {
        match self {
            Value::Int(n)  => n.to_string(),
            Value::Bool(b) => b.to_string(),
        }
    }
}

struct Frame<'a> {
    chunk:  &'a FnChunk,
    ip:     usize,
    locals: HashMap<String, Value>,
    stack:  Vec<Value>,
}

pub struct VM<'a> {
    prog:   &'a CompiledProgram,
    output: Vec<String>,
}

impl<'a> VM<'a> {
    pub fn new(prog: &'a CompiledProgram) -> Self {
        VM { prog, output: Vec::new() }
    }

    pub fn run(mut self, entry: Option<&str>) -> Result<Vec<String>, String> {
        let ep = entry.unwrap_or(&self.prog.entry);
        let chunk = self.prog.functions.get(ep)
            .ok_or_else(|| format!("Entry point '{ep}' not found"))?;

        let mut frames: Vec<Frame> = vec![Frame {
            chunk,
            ip:     0,
            locals: HashMap::new(),
            stack:  Vec::new(),
        }];

        loop {
            if frames.is_empty() { break; }
            let frame = frames.last_mut().unwrap();
            if frame.ip >= frame.chunk.code.len() {
                frames.pop();
                continue;
            }

            let ins = &frame.chunk.code[frame.ip];
            frame.ip += 1;

            match ins.op {
                Op::PushInt  => frame.stack.push(Value::Int(ins.ival)),
                Op::PushBool => frame.stack.push(Value::Bool(ins.ival != 0)),

                Op::Load => {
                    let v = frame.locals.get(&ins.sval)
                        .cloned()
                        .ok_or_else(|| format!("Undefined variable '{}'", ins.sval))?;
                    frame.stack.push(v);
                }
                Op::Store => {
                    let v = frame.stack.pop().unwrap();
                    frame.locals.insert(ins.sval.clone(), v);
                }

                Op::Add => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Int(a + b)); }
                Op::Sub => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Int(a - b)); }
                Op::Mul => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Int(a * b)); }
                Op::Div => {
                    let (a, b) = pop2_int(&mut frame.stack)?;
                    if b == 0 { return Err("Division by zero".to_string()); }
                    frame.stack.push(Value::Int(a / b));
                }
                Op::Neg => {
                    let v = frame.stack.pop().unwrap().as_int("")?;
                    frame.stack.push(Value::Int(-v));
                }

                Op::Eq  => { let (a, b) = pop2(&mut frame.stack); frame.stack.push(Value::Bool(vals_eq(&a, &b))); }
                Op::Neq => { let (a, b) = pop2(&mut frame.stack); frame.stack.push(Value::Bool(!vals_eq(&a, &b))); }
                Op::Lt  => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Bool(a < b)); }
                Op::Gt  => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Bool(a > b)); }
                Op::Leq => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Bool(a <= b)); }
                Op::Geq => { let (a, b) = pop2_int(&mut frame.stack)?; frame.stack.push(Value::Bool(a >= b)); }

                Op::And => {
                    let b = frame.stack.pop().unwrap().is_truthy();
                    let a = frame.stack.pop().unwrap().is_truthy();
                    frame.stack.push(Value::Bool(a && b));
                }
                Op::Or => {
                    let b = frame.stack.pop().unwrap().is_truthy();
                    let a = frame.stack.pop().unwrap().is_truthy();
                    frame.stack.push(Value::Bool(a || b));
                }
                Op::Not => {
                    let v = frame.stack.pop().unwrap().is_truthy();
                    frame.stack.push(Value::Bool(!v));
                }

                Op::Jmp      => { frame.ip = (frame.ip as i64 + ins.ival) as usize; }
                Op::JmpFalse => {
                    if !frame.stack.pop().unwrap().is_truthy() {
                        frame.ip = (frame.ip as i64 + ins.ival) as usize;
                    }
                }

                Op::Call => {
                    let nargs = ins.arg2;
                    let fn_name = ins.sval.clone();
                    let mut args: Vec<Value> = (0..nargs).map(|_| frame.stack.pop().unwrap()).collect();
                    args.reverse();

                    let callee = self.prog.functions.get(&fn_name)
                        .ok_or_else(|| format!("Undefined function '{fn_name}'"))?;
                    let mut new_frame = Frame {
                        chunk:  callee,
                        ip:     0,
                        locals: HashMap::new(),
                        stack:  Vec::new(),
                    };
                    for (name, val) in callee.params.iter().zip(args) {
                        new_frame.locals.insert(name.clone(), val);
                    }
                    frames.push(new_frame);
                }

                Op::Ret => {
                    let ret_val = frames.last_mut().unwrap().stack.pop()
                        .unwrap_or(Value::Bool(false));
                    frames.pop();
                    if let Some(caller) = frames.last_mut() {
                        caller.stack.push(ret_val);
                    }
                }

                Op::Print => {
                    let val = frame.stack.pop().unwrap();
                    let s = val.display();
                    self.output.push(s.clone());
                    println!("{s}");
                }

                Op::Pop  => { frame.stack.pop(); }
                Op::Halt => break,
            }
        }

        Ok(self.output)
    }
}

fn pop2(stack: &mut Vec<Value>) -> (Value, Value) {
    let b = stack.pop().unwrap();
    let a = stack.pop().unwrap();
    (a, b)
}

fn pop2_int(stack: &mut Vec<Value>) -> Result<(i64, i64), String> {
    let b = stack.pop().unwrap().as_int("")?;
    let a = stack.pop().unwrap().as_int("")?;
    Ok((a, b))
}

fn vals_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Int(x),  Value::Int(y))  => x == y,
        (Value::Bool(x), Value::Bool(y)) => x == y,
        _ => false,
    }
}

pub fn run(prog: &CompiledProgram, entry: Option<&str>) -> Result<Vec<String>, String> {
    VM::new(prog).run(entry)
}
