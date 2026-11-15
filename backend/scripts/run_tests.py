"""Run the backend tests in several processes at once, and say plainly what failed.

    python scripts/run_tests.py            # as many shares as the machine has cores for (up to 12)
    python scripts/run_tests.py 6          # six shares
    python scripts/run_tests.py 8 -k bill  # anything after the number goes to pytest

Each share is a `TEST_SHARD=i/n` run of pytest (see tests/conftest.py): whole files stay together, shared out so every
share has about the same number of tests, and each share gets its own throwaway database. A share's full output is kept
in backend/.test-logs/share_<i>.log.
"""
import os
import re
import subprocess
import sys
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BACKEND, ".test-logs")


def main():
    args = sys.argv[1:]
    cores = os.cpu_count() or 4
    shares = int(args.pop(0)) if args and args[0].isdigit() else max(2, min(12, cores - 2))
    os.makedirs(LOGS, exist_ok=True)
    env = dict(os.environ, COOKIE_SECURE="false")
    env.setdefault("SECRET_KEY", "test-secret-key-not-used-in-production")
    started = time.time()
    running = []
    for i in range(1, shares + 1):
        log = open(os.path.join(LOGS, "share_%d.log" % i), "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=BACKEND,
                                stdout=log, stderr=subprocess.STDOUT, env=dict(env, TEST_SHARD="%d/%d" % (i, shares)))
        running.append((i, proc, log))
    passed = failed = 0
    failures, broken = [], []
    for i, proc, log in running:
        code = proc.wait()
        log.close()
        text = open(log.name, encoding="utf-8", errors="replace").read()
        failures += re.findall(r"^(?:FAILED|ERROR) (\S+)", text, re.M)
        tail = re.findall(r"^.*\b(?:passed|failed|error|no tests ran)\b.* in [\d.]+s.*$", text, re.M)
        summary = tail[-1].strip("= ") if tail else "no summary - see the log"
        passed += sum(int(n) for n in re.findall(r"(\d+) passed", summary))
        failed += sum(int(n) for n in re.findall(r"(\d+) (?:failed|error)", summary))
        if code not in (0, 1, 5) or not tail:          # 5: a share with no tests in it (a narrow -k)
            broken.append(i)
        print("share %2d: %s" % (i, summary))
    took = time.time() - started
    print("\n%d passed, %d failed in %d min %02d s (%d shares)" % (passed, failed, took // 60, took % 60, shares))
    for name in failures:
        print("  FAILED " + name)
    for i in broken:
        print("  share %d did not finish properly: %s" % (i, os.path.join(LOGS, "share_%d.log" % i)))
    return 1 if failed or failures or broken else 0


if __name__ == "__main__":
    sys.exit(main())
