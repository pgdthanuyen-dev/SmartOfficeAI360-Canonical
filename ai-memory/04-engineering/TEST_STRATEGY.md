# Test strategy

Updated: 2026-07-24

Run focused QLVB tests for changed behavior, compile changed Python modules, validate this memory, and run `git diff --check`. Treat the recorded `156 passed` as focused evidence only; the latest full suite was not entirely green.
