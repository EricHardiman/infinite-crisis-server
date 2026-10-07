"""Syntax-check the scripts and print the messages the server will send."""
import ast
for p in ("login_server.py", "tracer.py"):
    b = open(p, "rb").read()
    assert b.count(bytes([0])) == 0, p + " contains NUL bytes"
    ast.parse(b.decode("utf-8"))
src = open("login_server.py", encoding="utf-8").read()
ns = {"__file__": "login_server.py", "__name__": "check"}
exec(compile(src, "login_server.py", "exec"), ns)
for label, msg in ns["build_initial_events"]():
    print("%-48s %s" % (label, msg.hex()))
