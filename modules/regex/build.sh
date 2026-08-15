#!/usr/bin/env bash
# Build, test and benchmark the regex engine. Needs only a JDK (17+) on PATH.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf out && mkdir -p out

echo "== compiling =="
javac -d out src/regex/*.java

echo "== tests =="
javac -cp out -d out test/regex/RegexTest.java
java -cp out regex.RegexTest

echo
echo "== benchmark (ReDoS: this engine vs java.util.regex) =="
javac -cp out -d out bench/Redos.java
java -cp out Redos
