"""The programme's arithmetic: every case in data/programme_cases.json, which the frontend's copy of the engine runs too,
so both answer the same; and what only this side checks (size, a week with no working day)."""
import json
import os
import time
from datetime import date

import pytest

from app.services.programme_engine import (Calendar, Link, Row, format_predecessors, parse_predecessors,
                                           planned_percent, schedule)

CASES = json.load(open(os.path.join(os.path.dirname(__file__), "data", "programme_cases.json"), encoding="utf-8"))
DATE_FIELDS = ("start", "end", "not_before")


def _d(s):
    return date.fromisoformat(s) if s else None


def _calendar(spec):
    spec = spec or {}
    return Calendar(calendar_days=bool(spec.get("calendar_days")), weekly_off=frozenset(spec.get("weekly_off", [7])),
                    holidays=frozenset(_d(h) for h in spec.get("holidays", [])))


def _rows(case):
    out = []
    for r in case["rows"]:
        r = dict(r)
        for f in DATE_FIELDS:
            if f in r:
                r[f] = _d(r[f])
        out.append(Row(**r))
    return out


def _links(case):
    return [Link(**ln) for ln in case.get("links", [])]


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_shared_case(case):
    cal = _calendar(case.get("calendar"))
    prog = schedule(_rows(case), _links(case), cal)
    for rid, want in case.get("expect", {}).items():
        got = prog.rows[int(rid)]
        for k, v in want.items():
            have = getattr(got, k)
            if k in ("start", "end"):
                have = have.isoformat() if have else None
            if k == "percent":
                assert have == pytest.approx(v, abs=0.01), (rid, k, have, v)
            else:
                assert have == v, (case["name"], rid, k, have, v)
    if "expect_project" in case:
        p = case["expect_project"]
        assert prog.start.isoformat() == p["start"] and prog.finish.isoformat() == p["finish"]
        assert prog.duration == p["duration"]
    for text in case.get("expect_errors", []):
        assert any(text in e for e in prog.errors), (text, prog.errors)
    if not case.get("expect_errors"):
        assert prog.errors == []
    if "expect_broken_links" in case:
        assert len(prog.broken_links) == case["expect_broken_links"]
    for check in case.get("planned", []):
        pct = planned_percent(prog, cal, _d(check["as_of"]))
        for rid, v in check["expect"].items():
            key = rid if rid == "project" else int(rid)
            assert pct[key] == pytest.approx(v, abs=0.01), (check["as_of"], rid, pct[key], v)


@pytest.mark.parametrize("case", CASES["parse"], ids=[c["text"] for c in CASES["parse"]])
def test_predecessors_are_read_from_text(case):
    links, problems = parse_predecessors(case["text"], case["wbs"])
    assert [list(x) for x in links] == case["links"]
    assert len(problems) == case["problems"]


@pytest.mark.parametrize("case", CASES["format"])
def test_predecessors_are_written_as_text(case):
    wbs = {int(k): v for k, v in case["wbs"].items()}
    assert format_predecessors([tuple(x) for x in case["links"]], wbs) == case["text"]


def test_changing_a_predecessor_moves_everything_after_it_and_its_parents():
    rows = [Row(10, name="Slab"), Row(1, 10, 1, "Reinforcement", date(2026, 11, 2), days=3),
            Row(2, 10, 2, "Shuttering", days=2), Row(3, None, 2, "Plastering", days=1)]
    links = [Link(2, 1), Link(3, 2)]
    before = schedule(rows, links)
    rows[1].days = 5                                                    # reinforcement takes two days longer
    after = schedule(rows, links)
    assert (after.rows[2].start - before.rows[2].start).days == 2     # Thu 5 -> Sat 7 (no Sunday in between)
    assert after.rows[3].start == date(2026, 11, 10)        # shuttering Sat 7 + Mon 9, then Tue 10
    assert after.rows[10].end == after.rows[2].end
    assert after.finish > before.finish


def test_a_week_with_no_working_day_is_refused():
    with pytest.raises(ValueError):
        Calendar(weekly_off=frozenset(range(1, 8)))


def test_two_thousand_rows_are_worked_out_in_well_under_a_second():
    rows, links = [], []
    rid = 0
    for block in range(20):                               # 20 blocks x 10 units x 9 activities = 2,000 rows with headings
        rid += 1
        b = rid
        rows.append(Row(b, name="Block %d" % block, order=block))
        for unit in range(10):
            rid += 1
            u = rid
            rows.append(Row(u, b, unit, "Unit %d" % unit))
            prev = None
            for act in range(8):
                rid += 1
                rows.append(Row(rid, u, act, "Activity %d" % act, date(2026, 11, 2) if prev is None else None, days=3))
                if prev:
                    links.append(Link(rid, prev, "FS", 0))
                prev = rid
    t = time.perf_counter()
    prog = schedule(rows, links)
    took = time.perf_counter() - t
    assert len(prog.order) == len(rows) >= 1800
    assert not prog.errors and prog.finish == date(2026, 11, 28)    # 24 working days from Mon 2 Nov, past 3 Sundays
    assert took < 1.0, "took %.2f s" % took
