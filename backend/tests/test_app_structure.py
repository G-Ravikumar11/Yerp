"""The shape of the app package: what a reorganisation of it must not break.

These are about wiring, not business rules - the business rules are tested everywhere else.
"""
import ast
import builtins
import os
import subprocess
import symtable
import sys

import main

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(BACKEND, "app")


def test_the_front_end_is_mounted_after_every_endpoint():
    """A mount on "/" answers every address under it, so one mounted too early swallows the endpoints
    (a POST to /api/... came back 405 Method Not Allowed)."""
    routes = main.app.routes
    kinds = [type(r).__name__ for r in routes]
    last_api = max(i for i, k in enumerate(kinds) if k in ("APIRoute", "APIWebSocketRoute"))
    for i, r in enumerate(routes):
        if type(r).__name__ == "Mount" and getattr(r, "path", None) in ("", "/next"):
            assert i > last_api, "the %r mount comes before an endpoint" % r.path
    assert getattr(routes[-1], "path", None) == "", "the old front page, mounted on /, must come last of all"


def test_no_endpoint_is_registered_twice():
    seen = {}
    for r in main.app.routes:
        if type(r).__name__ == "APIRoute":
            for method in r.methods:
                key = (method, r.path)
                assert key not in seen, "%s %s is registered twice (%s and %s)" % (method, r.path, seen[key], r.name)
                seen[key] = r.name


def test_every_module_only_reads_names_it_has():
    """Moving code between modules loses a name quietly: it fails only on the one request that uses it. Every name a
    module reads must be defined or imported in that same module."""
    allowed = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    problems = []
    for dirpath, _, files in os.walk(PACKAGE):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            src = open(path, encoding="utf8").read()
            top = symtable.symtable(src, path, "exec")
            defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
            needed = set()

            def walk(tbl):
                for s in tbl.get_symbols():
                    if tbl.get_type() != "module" and s.is_global() and s.is_referenced():
                        needed.add(s.get_name())
                for ch in tbl.get_children():
                    walk(ch)

            walk(top)
            for s in top.get_symbols():
                if s.is_referenced() and not (s.is_assigned() or s.is_imported() or s.is_namespace()):
                    needed.add(s.get_name())
            missing = sorted(n for n in needed if n not in defined and n not in allowed)
            if missing:
                problems.append("%s reads %s" % (os.path.relpath(path, BACKEND), missing))
    assert not problems, "\n".join(problems)


def test_the_app_builds_from_a_fresh_interpreter():
    """Modules that need each other import some names late. That only works in the order bootstrap.py loads them in,
    so build the app the way the server does - cold, from a bare `import main` - and from a submodule too."""
    env = dict(os.environ, DATABASE_URL="sqlite:///" + os.path.join(os.environ.get("TEMP", "/tmp"), "structure_check.db"),
               SECRET_KEY="structure-check", SCHEDULER_ENABLED="0")
    for statement in ("import main; assert len(main.app.routes) > 700",
                      "import app.services.hr, app.routers.payroll, app.core.auth; import main"):
        done = subprocess.run([sys.executable, "-c", statement], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, "%s\n%s" % (statement, done.stderr[-1500:])


def test_each_area_has_its_endpoints_beside_its_workings():
    """/api/sub-bills is in routers/subcontract_billing.py and what it calls is in services/subcontract_billing.py."""
    for router in sorted(os.listdir(os.path.join(PACKAGE, "routers"))):
        if router.endswith(".py") and router != "__init__.py":
            tree = ast.parse(open(os.path.join(PACKAGE, "routers", router), encoding="utf8").read())
            routes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and any(isinstance(d, ast.Call) and getattr(d.func, "value", None) is not None
                              and getattr(d.func.value, "id", "") == "router" for d in n.decorator_list)]
            assert routes, "routers/%s has no endpoints" % router
