fn divisible(n: int, d: int) -> bool {
    return (n / d) * d == n;
}

let i: int = 1;
while i <= 20 {
    if divisible(i, 15) {
        print(15);
    } else {
        if divisible(i, 3) {
            print(3);
        } else {
            if divisible(i, 5) {
                print(5);
            } else {
                print(i);
            }
        }
    }
    i = i + 1;
}
