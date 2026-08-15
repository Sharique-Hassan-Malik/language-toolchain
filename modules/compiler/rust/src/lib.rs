pub mod ast;
pub mod lexer;
pub mod parser;
pub mod type_checker;
pub mod codegen;
pub mod vm;

/// Convenience: run Zap source through the entire pipeline and return output lines.
pub fn compile_and_run(src: &str) -> Result<Vec<String>, String> {
    let prog = parser::parse(src)?;
    type_checker::type_check(&prog)?;
    let code = codegen::compile_program(&prog);
    vm::run(&code, None)
}
