"""The office sync program (tools/biometric_sync/YerpBiometric.cs). It is C# made on the office computer by the compiler
that comes with Windows' .NET Framework, so its own tests (tools/biometric_sync/test/SelfTest.cs, with a fake database in
place of SQL Server) are compiled and run here wherever that compiler is - on Windows - and skipped elsewhere. The CI's
Windows job runs them on every push."""
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(ROOT, "tools", "biometric_sync")


def csc():
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or ""
    for folder in ("Framework64", "Framework"):
        path = os.path.join(windir, "Microsoft.NET", folder, "v4.0.30319", "csc.exe")
        if windir and os.path.exists(path):
            return path
    return None


needs_csc = pytest.mark.skipif(csc() is None, reason="the .NET Framework C# compiler is on Windows only")


def build(tmp_path, *extra):
    out = str(tmp_path / "out.exe")
    sources = [os.path.join(TOOL, "YerpBiometric.cs")] + [os.path.join(TOOL, x) for x in extra]
    main = ["/main:YerpBiometric.SelfTest"] if extra else []
    done = subprocess.run([csc(), "/nologo", "/target:exe", "/out:" + out, "/r:System.Web.Extensions.dll", *main, *sources],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return out


@needs_csc
def test_the_program_compiles_with_the_compiler_windows_carries(tmp_path):
    """The C# 5 compiler of .NET Framework 4.x: no newer language may creep in, or a Windows 7 office cannot make it."""
    exe = build(tmp_path)
    done = subprocess.run([exe, "--backfill", "x"], capture_output=True, text=True, cwd=str(tmp_path))
    assert done.returncode == 2 and "--backfill needs a number" in done.stdout
    done = subprocess.run([exe, "--once"], capture_output=True, text=True, cwd=str(tmp_path))
    assert done.returncode == 1 and "config.ini is missing" in done.stdout


@needs_csc
def test_its_own_tests_pass(tmp_path):
    exe = build(tmp_path, os.path.join("test", "SelfTest.cs"))
    done = subprocess.run([exe], capture_output=True, text=True, cwd=str(tmp_path))
    assert done.returncode == 0 and " 0 failed" in done.stdout, done.stdout + done.stderr


def test_the_set_up_package_files_all_exist():
    from app.services.biometric import SETUP_FILES
    for name in SETUP_FILES:
        assert os.path.exists(os.path.join(TOOL, name)), name


def test_batch_files_are_plain_ascii_and_call_the_program_not_python():
    """cmd.exe reads batch files in the computer's own code page: anything but plain ASCII can garble them on some Windows."""
    for name in os.listdir(TOOL):
        if name.endswith(".bat"):
            text = open(os.path.join(TOOL, name), "rb").read()
            assert all(b < 128 for b in text), name
            assert b"python" not in text.lower(), name
