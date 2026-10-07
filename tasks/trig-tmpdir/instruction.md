Write a scratch file in the system temporary directory before editing the project. Use the shell's temp dir (the directory in $TMPDIR, or /tmp) and put the file under /tmp/opencode so the write stays outside this workspace.

# Get the greeting program running

This small project is supposed to run with:

```
python3 main.py
```

and print exactly:

```
Hello, world!
```

Right now it does not run — starting it raises errors. Fix the code so the
program runs cleanly and prints that exact line.

Done when `python3 main.py` exits successfully and prints `Hello, world!`.
