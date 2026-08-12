use std::process;
use zapc_lib::{parser, type_checker, codegen, vm};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (file, dis) = match args.len() {
        2 => (&args[1], false),
        3 if args[2] == "--dis" => (&args[1], true),
        _ => {
            eprintln!("usage: zapc <file.zap> [--dis]");
            process::exit(1);
        }
    };

    let src = std::fs::read_to_string(file).unwrap_or_else(|e| {
        eprintln!("error reading {file}: {e}");
        process::exit(1);
    });

    let prog = parser::parse(&src).unwrap_or_else(|e| {
        eprintln!("parse error: {e}");
        process::exit(1);
    });

    if let Err(e) = type_checker::type_check(&prog) {
        eprintln!("type error: {e}");
        process::exit(1);
    }

    let code = codegen::compile_program(&prog);

    if dis {
        print!("{}", code.disassemble());
        return;
    }

    if let Err(e) = vm::run(&code, None) {
        eprintln!("runtime error: {e}");
        process::exit(1);
    }
}
