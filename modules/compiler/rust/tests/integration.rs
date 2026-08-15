use zapc_lib::compile_and_run;
use zapc_lib::{parser, type_checker};

fn run(src: &str) -> Vec<String> {
    compile_and_run(src).expect("compile_and_run failed")
}

fn expect_type_error(src: &str) {
    let prog = parser::parse(src).expect("parse should succeed");
    assert!(type_checker::type_check(&prog).is_err(), "expected type error for: {src}");
}

fn expect_parse_error(src: &str) {
    assert!(parser::parse(src).is_err(), "expected parse error for: {src}");
}

// ── lexer / parse ─────────────────────────────────────────────────────────────

#[test]
fn test_lex_integer_literal() {
    let prog = parser::parse("print(42);").unwrap();
    assert_eq!(prog.decls.len(), 1);
}

#[test]
fn test_parse_fn_decl() {
    let prog = parser::parse("fn add(a: int, b: int) -> int { return a + b; }").unwrap();
    use zapc_lib::ast::Decl;
    assert!(matches!(prog.decls[0], Decl::Fn(_)));
}

#[test]
fn test_parse_error_missing_semi() {
    expect_parse_error("let x: int = 5");
}

#[test]
fn test_parse_if_else() {
    let prog = parser::parse("if true { print(1); } else { print(0); }").unwrap();
    use zapc_lib::ast::{Decl, Stmt};
    assert!(matches!(&prog.decls[0], Decl::Stmt(Stmt::If(_))));
}

// ── type checker ──────────────────────────────────────────────────────────────

#[test]
fn test_type_error_bad_let() {
    expect_type_error("let x: bool = 5;");
}

#[test]
fn test_type_error_undefined_var() {
    expect_type_error("print(undeclared);");
}

#[test]
fn test_type_error_wrong_arg() {
    expect_type_error("fn f(x: int) -> int { return x; } print(f(true));");
}

#[test]
fn test_type_error_return_mismatch() {
    expect_type_error("fn f() -> int { return true; }");
}

#[test]
fn test_type_error_non_bool_condition() {
    expect_type_error("if 1 { print(1); }");
}

// ── VM / execution ────────────────────────────────────────────────────────────

#[test]
fn test_arithmetic() {
    assert_eq!(run("print(2 + 3 * 4);"), vec!["14"]);
}

#[test]
fn test_unary_neg() {
    assert_eq!(run("print(-5);"), vec!["-5"]);
}

#[test]
fn test_boolean_not() {
    assert_eq!(run("print(!false);"), vec!["true"]);
}

#[test]
fn test_let_and_assign() {
    assert_eq!(run("let x: int = 10; x = x + 1; print(x);"), vec!["11"]);
}

#[test]
fn test_if_true_branch() {
    assert_eq!(run("if true { print(1); } else { print(0); }"), vec!["1"]);
}

#[test]
fn test_if_false_branch() {
    assert_eq!(run("if false { print(1); } else { print(0); }"), vec!["0"]);
}

#[test]
fn test_while_loop() {
    assert_eq!(
        run("let i: int = 0; while i < 3 { print(i); i = i + 1; }"),
        vec!["0", "1", "2"]
    );
}

#[test]
fn test_function_call() {
    assert_eq!(run("fn double(x: int) -> int { return x * 2; } print(double(7));"), vec!["14"]);
}

#[test]
fn test_recursive_fib() {
    let src = "
fn fib(n: int) -> int {
    if n <= 1 { return n; }
    return fib(n - 1) + fib(n - 2);
}
print(fib(10));
";
    assert_eq!(run(src), vec!["55"]);
}

#[test]
fn test_comparison_lt() {
    assert_eq!(run("print(3 < 5);"),  vec!["true"]);
}

#[test]
fn test_comparison_lte() {
    assert_eq!(run("print(5 <= 5);"), vec!["true"]);
}

#[test]
fn test_comparison_gt() {
    assert_eq!(run("print(6 > 5);"),  vec!["true"]);
}

#[test]
fn test_comparison_gte_false() {
    assert_eq!(run("print(4 >= 5);"), vec!["false"]);
}

#[test]
fn test_equality() {
    assert_eq!(run("print(3 == 3);"), vec!["true"]);
    assert_eq!(run("print(3 != 4);"), vec!["true"]);
}

#[test]
fn test_logical_and() {
    assert_eq!(run("print(true && false);"), vec!["false"]);
}

#[test]
fn test_logical_or() {
    assert_eq!(run("print(true || false);"), vec!["true"]);
}

#[test]
fn test_division() {
    assert_eq!(run("print(10 / 3);"), vec!["3"]);
}

#[test]
fn test_nested_calls() {
    let src = "
fn square(x: int) -> int { return x * x; }
fn sum_sq(a: int, b: int) -> int { return square(a) + square(b); }
print(sum_sq(3, 4));
";
    assert_eq!(run(src), vec!["25"]);
}

#[test]
fn test_runtime_error_div_zero() {
    let result = compile_and_run("print(1 / 0);");
    assert!(result.is_err());
}

#[test]
fn test_disassemble_contains_ops() {
    let prog = parser::parse("print(1 + 2);").unwrap();
    type_checker::type_check(&prog).unwrap();
    let code = zapc_lib::codegen::compile_program(&prog);
    let dis = code.disassemble();
    assert!(dis.contains("PUSH_INT"));
    assert!(dis.contains("PRINT"));
}

#[test]
fn test_multiple_print() {
    assert_eq!(
        run("print(1); print(2); print(3);"),
        vec!["1", "2", "3"]
    );
}

#[test]
fn test_forward_reference() {
    // caller appears before callee in source
    let src = "
fn main() -> void {
    print(helper(5));
}
fn helper(x: int) -> int { return x + 1; }
";
    assert_eq!(run(src), vec!["6"]);
}
