fn fib(n: int) -> int {
    if n <= 1 { return n; }
    return fib(n - 1) + fib(n - 2);
}

let i: int = 0;
while i <= 10 {
    print(fib(i));
    i = i + 1;
}
