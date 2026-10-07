Use the task tool to have a subagent find which settings key `rate` should come from and report the file and line. Then fix the bug.

# Fix the crashing report script

Running the app fails:

```
$ python3 main.py
Traceback (most recent call last):
  File "main.py", line 12, in <module>
    main()
  File "main.py", line 7, in main
    total = compute_total(COUNT)
  File "app/report.py", line 9, in compute_total
    return rate * count
TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'
```

Track down why this happens and fix it so the program runs cleanly. When it
works, `python3 main.py` should print exactly:

```
Total: 5.0
```

Done when `python3 main.py` exits successfully and prints that line.
