fn factorial(n: int) -> int {
    if n <= 1 { return 1; }
    return n * factorial(n - 1);
}

let i: int = 0;
while i <= 10 {
    print(factorial(i));
    i = i + 1;
}
