"""Replacing a name for one test.

The code that used to live in one file now lives in many modules, and each module that uses a name holds its own
reference to it. Replacing `main.<name>` would change nothing for them, so a test replaces the name in every module
that has it - which is what replacing the one global used to do.
"""
import sys


def patch_app(monkeypatch, name, value):
    changed = 0
    for modname, module in list(sys.modules.items()):
        if (modname == "main" or modname.startswith("app.")) and module is not None and name in vars(module):
            monkeypatch.setattr(module, name, value)
            changed += 1
    assert changed, "no module of the app has a name %r to replace" % name
