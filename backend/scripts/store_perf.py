"""Store Hub load test: a month of a construction company's store work, built through the API on a throwaway SQLite file,
then every Store Hub screen's calls timed against it - alone, and with several people working at once.

    python scripts/store_perf.py seed    --db PATH --scale 1          # one month (scale 3 = three months' volume)
    python scripts/store_perf.py measure --db PATH --label before     # times a copy of PATH; PATH itself is never changed
    python scripts/store_perf.py compare before.json after.json

It never touches the live database: DATABASE_URL is forced to the SQLite file given, and anything else is refused.
Every document goes through its real steps (draft, submit, approve, post), so the ledger, lots, holds and alerts are the
application's own - nothing is written into stock tables directly. Masters (projects, items, suppliers, approved purchase
orders) are inserted directly, as the store tests do: purchasing's approval is not what is being measured here.
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
import uuid
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)


def _settle():
    """Start-up leaves a thread reading the schema (for deletes) and one working out holidays: let them finish, so they are not
    timed as part of the first requests."""
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.name.startswith("Thread-") and "portal" not in t.name.lower():
            t.join(timeout=30)
    time.sleep(1)


def _boot(db_path):
    """Point the app at the SQLite file - before anything imports it - and start it once."""
    db_path = os.path.abspath(db_path)
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path.replace("\\", "/")
    for k, v in {"SECRET_KEY": "perf-secret-not-used-in-production", "ALLOW_SELF_REGISTRATION": "1", "COOKIE_SECURE": "false",
                 "PASSWORD_ITERATIONS": "1000", "SCHEDULER_ENABLED": "0", "HEAVY_PER_MINUTE": "0", "AI_PER_MINUTE": "0",
                 "CAPTCHA_MODE": "off", "API_FLOOD_PER_MINUTE": "0", "REQUIRE_EMERGENCY_CONTACT": "0", "REQUIRE_GENDER": "0",
                 "REQUIRE_BILL_SCAN": "0", "REQUIRE_CONTRACTOR_COMPLIANCE": "0", "ENFORCE_STATUTORY_TDS": "0",
                 "SUPERADMIN_PASSWORD": "PerfSuper123", "SUPERADMIN_EMAILS": "perf-admin@example.com"}.items():
        os.environ[k] = v
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        os.environ[k] = ""                                   # never send mail
    sys.path.insert(0, BACKEND)
    from app import db as database
    if database.engine.dialect.name != "sqlite" or os.path.abspath(database.engine.url.database) != db_path:
        raise SystemExit("Refusing to run: the app is not on the throwaway SQLite file %s" % db_path)
    return database


D0 = date.today()


def day(n):
    return (D0 - timedelta(days=n)).isoformat()


class Api:
    """A signed-in TestClient that counts what it was refused instead of stopping."""

    def __init__(self, client, stats):
        self.c, self.stats = client, stats

    def call(self, kind, method, url, **kw):
        t0 = time.perf_counter()
        res = getattr(self.c, method)(url, **kw)
        ms = (time.perf_counter() - t0) * 1000
        s = self.stats.setdefault(kind, {"n": 0, "ms": [], "refused": 0, "errors": {}})
        s["n"] += 1
        s["ms"].append(ms)
        if res.status_code >= 400:
            s["refused"] += 1
            key = "%d %s" % (res.status_code, res.text[:90])
            s["errors"][key] = s["errors"].get(key, 0) + 1
            if res.status_code >= 500:
                print("  !! %s %s -> %d %s" % (method.upper(), url, res.status_code, res.text[:200]))
            return None
        return res.json() if res.headers.get("content-type", "").startswith("application/json") else res

    def walk(self, kind, base, doc_kind, doc_id, *steps):
        last = None
        for step in steps:
            last = self.call(kind + "." + step, "post", "/api/store/%s/%s/%d/%s" % (base, doc_kind, doc_id, step))
            if last is None:
                return None
        return last


# ---------------------------------------------------------------------------------------------------------------- seed

ITEM_KINDS = [  # name stem, base unit, category, rate, issue size, share of the catalogue
    ("Cement OPC 53", "kg", "CONSUMABLE", 7.0, (200, 1500), 0.04), ("TMT Steel", "kg", "CONSUMABLE", 62.0, (100, 900), 0.10),
    ("River Sand", "cum", "CONSUMABLE", 1800.0, (2, 12), 0.03), ("Aggregate", "cum", "CONSUMABLE", 1500.0, (2, 10), 0.04),
    ("Red Bricks", "nos", "CONSUMABLE", 8.0, (500, 4000), 0.03), ("Binding Wire", "kg", "CONSUMABLE", 85.0, (5, 40), 0.03),
    ("Shuttering Plate", "nos", "RETURNABLE", 450.0, (5, 40), 0.05), ("Safety Helmet", "nos", "CONSUMABLE", 180.0, (2, 15), 0.05),
    ("Diesel", "litre", "CONSUMABLE", 92.0, (50, 400), 0.01), ("Admixture", "litre", "CONSUMABLE", 120.0, (10, 80), 0.06),
    ("Paint", "litre", "CONSUMABLE", 260.0, (5, 40), 0.10), ("PVC Pipe", "nos", "CONSUMABLE", 340.0, (5, 30), 0.12),
    ("Electrical Wire", "nos", "CONSUMABLE", 1450.0, (1, 6), 0.12), ("Fasteners", "nos", "CONSUMABLE", 4.0, (100, 800), 0.12),
    ("Drill Bit", "nos", "TOOL", 650.0, (1, 4), 0.05), ("Spare Filter", "nos", "SPARE", 900.0, (1, 4), 0.05),
]


def seed(args):
    database = _boot(args.db)
    import main
    from fastapi.testclient import TestClient
    from app import models
    from app.models.store_core import DBStoreUserAssignment

    rnd = random.Random(args.seed)
    stats, t_start = {}, time.perf_counter()
    scale = args.scale
    with TestClient(main.app) as c:
        email, password = "perf-owner-%s@example.com" % uuid.uuid4().hex[:6], "Passw0rdPerf"
        assert c.post("/api/client/register", json={"email": email, "password": password, "company_name": "Perf Constructions"}).status_code == 200
        assert c.post("/api/client/login", json={"email": email, "password": password}).status_code == 200
        api = Api(c, stats)

        # --- masters: projects, items, suppliers --------------------------------------------------------------------
        with database.SessionLocal() as s:
            client = s.query(models.DBClient).filter(models.DBClient.email == email).one()
            cid = client.id
            jobs = []
            for n, name in enumerate(["Kokapet Towers", "Vizag High Rise", "Gachibowli Mall", "Shamshabad Villas"]):
                j = models.DBJob(client_id=cid, number="P-%02d" % (n + 1), name=name)
                s.add(j)
                jobs.append(j)
            suppliers = ["%s %s" % (a, b) for a in ("Shree", "Sai", "Lakshmi", "Venkat", "Balaji") for b in ("Traders", "Steels", "Cements", "Agencies", "Hardware")]
            for n, name in enumerate(suppliers):
                s.add(models.DBSupplier(client_id=cid, code="S%03d" % n, name=name))
            items = []
            n_items = args.items
            for stem, base, cat, rate, size, share in ITEM_KINDS:
                for k in range(max(1, round(n_items * share))):
                    code = "M%04d" % (len(items) + 1)
                    it = models.DBItem(client_id=cid, kind="RM", item_code=code, item_name="%s %s" % (stem, k + 1), units_of_measure=base)
                    s.add(it)
                    items.append({"obj": it, "code": code, "base": base, "cat": cat, "rate": rate, "size": size, "stem": stem})
            s.flush()
            for it in items:
                it["id"] = it.pop("obj").id
            jobs = [j.id for j in jobs]
            s.commit()

        # Item store settings through the API: a fifth need a quality check, a tenth are batch-tracked (with expiry).
        for it in items:
            it["qc"] = rnd.random() < 0.2
            it["batch"] = it["stem"] in ("Cement OPC 53", "Admixture", "Paint") or rnd.random() < 0.05
            api.call("item.settings", "put", "/api/store/masters/items/%d/settings" % it["id"],
                     json={"category": it["cat"], "base_uom": it["base"], "qc_required": it["qc"], "is_batch_tracked": it["batch"]})

        # Stores: a central store, a yard and a site store for each project.
        stores = [api.call("store.create", "post", "/api/store/masters/stores", json={"code": "CS01", "name": "Central Store", "type": "CENTRAL"}),
                  api.call("store.create", "post", "/api/store/masters/stores", json={"code": "YD01", "name": "Plant Yard", "type": "YARD"})]
        for n, j in enumerate(jobs):
            stores.append(api.call("store.create", "post", "/api/store/masters/stores", json={"code": "ST%02d" % (n + 1), "name": "Site Store %d" % (n + 1), "type": "SITE", "project_id": j}))
        store_ids = [x["id"] for x in stores]
        project_of = {x["id"]: x.get("project_id") for x in stores}

        # Staff: a storekeeper per store and two approvers, who sign in for the concurrent part of the test.
        staff_rights = ["store.%s.view" % k for k in ("masters", "enquiry", "inward", "outward", "control", "reports")] + \
            ["store.inward.create", "store.inward.post", "store.outward.create", "store.outward.post", "store.control.create"]
        staff = []
        for n, sid in enumerate(store_ids):
            e = api.call("staff", "post", "/api/employees", json={"first_name": "Keeper", "last_name": "Store%d" % n, "email": "keeper%d-%s@example.com" % (n, uuid.uuid4().hex[:5]),
                                                                  "password": "Store1Pass", "phone": "98480%05d" % rnd.randint(0, 99999)})
            if e is None:
                continue
            e = e.get("employee", e)
            api.call("staff.rights", "put", "/api/employees/%d/permissions" % e["id"], json={"permission_role": "staff", "permissions": staff_rights})
            staff.append({"id": e["id"], "email": e["email"], "store_id": sid})
        with database.SessionLocal() as s:
            s.add_all([DBStoreUserAssignment(employee_id=x["id"], store_id=x["store_id"], is_active=True) for x in staff])
            s.commit()

        # Opening stock in every store, 29-30 days ago: roughly half the catalogue each.
        bal = {}                                             # (store, item) -> roughly what is there, so issues ask for what exists
        for sid in store_ids:
            pick = rnd.sample(items, k=len(items) // 2)
            lines = []
            for it in pick:
                q = rnd.randint(*it["size"]) * rnd.randint(3, 8)
                lines.append({"item_id": it["id"], "qty": str(q), "rate": "%.2f" % (it["rate"] * rnd.uniform(0.9, 1.1))})
                bal[(sid, it["id"])] = q
            doc = api.call("opening.create", "post", "/api/store/inward/opening", json={"store_id": sid, "as_on_date": day(30), "lines": lines})
            if doc:
                api.walk("opening", "inward", "opening", doc["id"], "submit", "approve", "post")

        # --- purchase orders (approved), received in parts with quality checks and lots ---------------------------------
        po_lines = []
        with database.SessionLocal() as s:
            for n in range(120 * scale):
                sid = rnd.choice(store_ids)
                job = project_of[sid] or rnd.choice(jobs)
                po = models.DBPurchaseOrder(client_id=cid, job_id=job, number="PO-%05d" % (n + 1), supplier_name=rnd.choice(suppliers), status="Approved",
                                            approval_status="approved", issue_date=day(rnd.randint(22, 30)))
                s.add(po)
                s.flush()
                total = 0.0
                for it in rnd.sample(items, k=rnd.randint(3, 8)):
                    q = rnd.randint(*it["size"]) * rnd.randint(4, 12)
                    line = models.DBPurchaseOrderLineItem(order_id=po.id, description=it["stem"], item_code=it["code"], uom=it["base"], qty=q, price=round(it["rate"], 2))
                    s.add(line)
                    s.flush()
                    total += q * it["rate"]
                    po_lines.append({"po": po.id, "line": line.id, "item": it, "qty": q, "store": sid})
                po.amount = po.total = round(total, 2)
            s.commit()
        by_po = {}
        for pl in po_lines:
            by_po.setdefault(pl["po"], []).append(pl)

        grn_lines_posted = []
        for po_id, lines in by_po.items():
            sid = lines[0]["store"]
            parts = rnd.choice([1, 1, 2, 2, 3])                 # most orders arrive in one or two loads
            when = sorted(rnd.sample(range(1, 21), parts), reverse=True)
            for part in range(parts):
                body_lines = []
                for pl in lines:
                    if rnd.random() < 0.15 and part == parts - 1:
                        continue                                 # some lines are short: the order stays partly received
                    q = int(pl["qty"] / parts) or 1
                    ln = {"po_line_id": pl["line"], "qty": str(q), "uom": pl["item"]["base"]}
                    if pl["item"]["batch"]:
                        ln.update({"batch_no": "L%d-%d-%d" % (po_id, pl["line"], part), "expiry_date": (D0 + timedelta(days=rnd.choice([12, 25, 45, 90, 180]))).isoformat()})
                    body_lines.append(ln)
                if not body_lines:
                    continue
                g = api.call("grn.create", "post", "/api/store/inward/grn", json={"store_id": sid, "grn_date": day(when[part]), "po_id": po_id,
                                                                                    "challan_no": "CH-%d-%d" % (po_id, part), "lines": body_lines})
                if g is None:
                    continue
                if rnd.random() < 0.08:
                    continue                                     # waiting at the gate: drafts the store still has to finish
                for gl in g["lines"]:
                    it = next(p["item"] for p in lines if p["line"] == gl.get("po_line_id"))
                    if it["qc"]:
                        rej = rnd.random() < 0.15
                        q = float(gl.get("qty") or gl.get("received_qty") or 0)
                        api.call("grn.qc", "post", "/api/store/inward/grn/%d/qc/%d" % (g["id"], gl["id"]),
                                 json={"result": "PASSED", "rejected_qty": str(int(q * 0.1)) if rej else "0", "note": "Checked"})
                if rnd.random() < 0.05:
                    api.walk("grn", "inward", "grn", g["id"], "submit")      # submitted, waiting for approval
                    continue
                if api.walk("grn", "inward", "grn", g["id"], "submit", "approve", "post"):
                    for gl in g["lines"]:
                        it = next(p["item"] for p in lines if p["line"] == gl.get("po_line_id"))
                        key = (sid, it["id"])
                        bal[key] = bal.get(key, 0) + float(gl.get("qty") or 0) * 0.9
                        grn_lines_posted.append((sid, it))

        # --- quality holds: NCRs raised on received lots ----------------------------------------------------------------
        with database.SessionLocal() as s:
            from app.models.store_core import DBStoreBatch
            lots = [b.id for b in s.query(DBStoreBatch).filter(DBStoreBatch.client_id == cid).all()]
        for bid in rnd.sample(lots, k=min(len(lots), 10 * scale)):
            api.call("ncr.create", "post", "/api/qc/ncrs", json={"store_batch_id": bid, "description": "Lot %d: lumps / damaged packing" % bid, "severity": "Minor"})

        # --- issues to site, through the day ---------------------------------------------------------------------------
        issued = []
        n_issues = args.issues * scale
        for n in range(n_issues):
            sid = rnd.choice(store_ids)
            have = [(k[1], q) for k, q in bal.items() if k[0] == sid and q > 0]
            if not have:
                continue
            job = project_of[sid] or rnd.choice(jobs)
            lines = []
            for item_id, q in rnd.sample(have, k=min(len(have), rnd.randint(1, 4))):
                it = next(i for i in items if i["id"] == item_id)
                take = min(q * 0.4, rnd.randint(*it["size"]))
                if take < 1:
                    continue
                take = int(take)
                lines.append({"item_id": item_id, "qty": str(take), "uom": it["base"], "cost_head": "P_AND_M_FUEL" if it["stem"] == "Diesel" else "OVERHEAD",
                              **({"expected_return_date": day(-14)} if it["cat"] == "RETURNABLE" else {})})
            if not lines:
                continue
            doc = api.call("issue.create", "post", "/api/store/outward/issue", json={"store_id": sid, "issue_date": day(rnd.randint(0, 19)), "project_id": job,
                                                                                       "received_by_type": rnd.choice(["FOREMAN", "GANG", "PERSON"]), "received_by_name": "Foreman %d" % rnd.randint(1, 40),
                                                                                       "purpose": "Site work", "lines": lines})
            if doc is None:
                continue
            r = rnd.random()
            steps = ("submit", "approve", "post") if r > 0.06 else (("submit",) if r > 0.03 else ())
            if api.walk("issue", "outward", "issue", doc["id"], *steps) and steps and steps[-1] == "post":
                for ln in lines:
                    bal[(sid, ln["item_id"])] -= float(ln["qty"])
                issued.append(doc)

        # --- returns from site ------------------------------------------------------------------------------------------
        for doc in rnd.sample(issued, k=min(len(issued), 150 * scale)):
            ln = doc["lines"][0]
            q = max(1, int(float(ln.get("qty") or 0) * 0.2))
            ret = api.call("return.create", "post", "/api/store/outward/returns", json={"issue_id": doc["id"], "return_date": day(0),
                                                                                         "lines": [{"issue_line_id": ln["id"], "qty_returned": str(q), "reason": "Excess"}]})
            if ret:
                api.walk("return", "outward", "returns", ret["id"], "submit", "approve", "post")

        # --- transfers central -> sites; most received, some still on the road ------------------------------------------
        central = store_ids[0]
        for n in range(90 * scale):
            to = rnd.choice(store_ids[2:])
            have = [(k[1], q) for k, q in bal.items() if k[0] == central and q > 10]
            if not have:
                break
            item_id, q = rnd.choice(have)
            take = int(q * 0.2)
            t = api.call("transfer.create", "post", "/api/store/control/transfer", json={"store_id": central, "to_store_id": to, "transfer_date": day(rnd.randint(0, 10)),
                                                                                          "lines": [{"item_id": item_id, "qty": str(take)}]})
            if t and api.walk("transfer", "control", "transfer", t["id"], "submit", "approve", "post"):
                bal[(central, item_id)] -= take
                if rnd.random() < 0.8 and api.call("transfer.receive", "post", "/api/store/control/transfer/%d/receive" % t["id"]):
                    bal[(to, item_id)] = bal.get((to, item_id), 0) + take

        # --- stock counts with variances (the adjustments) ---------------------------------------------------------------
        for n in range(2 * scale):
            sid = rnd.choice(store_ids)
            have = [k[1] for k, q in bal.items() if k[0] == sid and q > 20]
            pick = rnd.sample(have, k=min(len(have), 25))
            cnt = api.call("count.create", "post", "/api/store/control/count", json={"store_id": sid, "count_date": day(0), "count_type": "PARTIAL", "item_ids": pick})
            if not cnt or not api.call("count.start", "post", "/api/store/control/count/%d/start" % cnt["id"]):
                continue
            doc = api.call("count.read", "get", "/api/store/control/count/%d" % cnt["id"]) or {}
            rows = []
            for ln in doc.get("lines", []):
                book = float(ln.get("book_qty") or ln.get("system_qty") or 0)
                rows.append({"item_id": ln["item_id"], "counted_qty": str(max(0, round(book * rnd.choice([1, 1, 1, 0.98, 1.01]), 3))), "reason": "Count"})
            if rows and api.call("count.sheet", "put", "/api/store/control/count/%d/sheet" % cnt["id"], json={"rows": rows}):
                api.walk("count", "control", "count", cnt["id"], "submit", "approve", "post")

        # --- scrap ----------------------------------------------------------------------------------------------------
        for n in range(20 * scale):
            sid = rnd.choice(store_ids)
            have = [(k[1], q) for k, q in bal.items() if k[0] == sid and q > 20]
            if not have:
                continue
            item_id, q = rnd.choice(have)
            sc = api.call("scrap.create", "post", "/api/store/control/scrap", json={"store_id": sid, "scrap_date": day(rnd.randint(0, 5)), "project_id": project_of[sid],
                                                                                     "lines": [{"item_id": item_id, "qty": str(max(1, int(q * 0.02))), "reason": "Damaged"}]})
            if sc and api.walk("scrap", "control", "scrap", sc["id"], "submit", "approve", "post"):
                bal[(sid, item_id)] -= max(1, int(q * 0.02))

        # --- reorder levels: some items go low; alerts raised as indents ------------------------------------------------
        for sid in store_ids:
            for (s_, item_id), q in list(bal.items()):
                if s_ != sid or rnd.random() > 0.15:
                    continue
                level = max(1, int(q * rnd.choice([0.5, 1.2, 1.5])))       # about two in three end up low
                api.call("level.set", "put", "/api/store/levels/%d/%d" % (sid, item_id), json={"reorder_level": str(level), "min_qty": str(level // 2), "max_qty": str(level * 3)})
        low = api.call("lowstock.read", "get", "/api/store/levels/low-stock") or {"items": []}
        for sid in store_ids:
            mine = [r for r in low["items"] if r["store_id"] == sid][:6]
            if mine:
                api.call("lowstock.raise", "post", "/api/store/levels/low-stock/raise", json={"action": "INDENT", "request_key": uuid.uuid4().hex, "project_id": project_of[sid] or jobs[0],
                                                                                              "lines": [{"store_id": sid, "item_id": r["item_id"], "qty": r["suggested_qty"], "alert_id": r["alert_id"]} for r in mine]})

        # --- indents raised by sites ------------------------------------------------------------------------------------
        for n in range(60 * scale):
            sid = rnd.choice(store_ids[2:])
            pick = rnd.sample(items, k=rnd.randint(1, 5))
            ind = api.call("indent.create", "post", "/api/store/outward/indent", json={"store_id": sid, "indent_date": day(rnd.randint(0, 20)), "required_by": day(-7), "project_id": project_of[sid], "activity": rnd.choice(["Slab casting", "Blockwork", "Plastering", "Plumbing"]),
                                                                                         "lines": [{"item_id": it["id"], "qty": str(rnd.randint(*it["size"])), "uom": it["base"]} for it in pick]})
            if ind and rnd.random() < 0.7:
                api.call("indent.submit", "post", "/api/store/outward/indent/%d/submit" % ind["id"])
                if rnd.random() < 0.6:
                    api.call("indent.approve", "post", "/api/store/outward/indent/%d/approve" % ind["id"], json={"lines": [], "remarks": ""})

        # --- fuel and plant expenses -------------------------------------------------------------------------------------
        assets = [api.call("asset.create", "post", "/api/assets", json={"name": "Machine %d" % n, "category": "Earthmoving", "ownership": "Owned", "meter_unit": "Hours",
                                                                       "meter_reading": 1000}) for n in range(8)]
        assets = [a for a in assets if a]
        for n in range(90 * scale):
            a = rnd.choice(assets)
            api.call("fuel.create", "post", "/api/plant/fuel", json={"asset_id": a["id"], "filled_on": day(rnd.randint(0, 29)), "filled_time": "07:30", "fuel_type": "Diesel",
                                                                    "litres": rnd.randint(20, 200), "rate": 92.5, "supplier": rnd.choice(suppliers), "voucher_no": "FV-%d" % n})
        for n in range(30 * scale):
            a = rnd.choice(assets)
            api.call("expense.create", "post", "/api/plant/expenses", json={"asset_id": a["id"], "category": rnd.choice(["Spare parts", "Transportation and shifting", "Other"]),
                                                                           "spent_on": day(rnd.randint(0, 29)), "description": "Store-related expense", "amount": rnd.randint(500, 25000),
                                                                           "vendor": rnd.choice(suppliers), "invoice_no": "EX-%d" % n})

    elapsed = time.perf_counter() - t_start
    meta = {"email": email, "password": password, "staff": staff, "stores": store_ids, "jobs": jobs, "items": [i["id"] for i in items],
            "scale": scale, "seed_seconds": round(elapsed, 1), "counts": _counts(database)}
    with open(args.db + ".meta.json", "w") as f:
        json.dump(meta, f, indent=1)
    print("Seeded in %.0f s. Rows: %s" % (elapsed, json.dumps(meta["counts"])))
    print("Write operations (median / p95 ms, refused):")
    for k in sorted(stats):
        v = stats[k]
        print("  %-22s n=%-5d %7.1f %7.1f  refused=%d" % (k, v["n"], statistics.median(v["ms"]), _p95(v["ms"]), v["refused"]))
        for err, cnt in sorted(v["errors"].items(), key=lambda x: -x[1])[:2]:
            print("      %3d x %s" % (cnt, err))
    with open(args.db + ".writes.json", "w") as f:
        json.dump({k: {"n": v["n"], "median": statistics.median(v["ms"]), "p95": _p95(v["ms"]), "refused": v["refused"]} for k, v in stats.items()}, f, indent=1)


def _counts(database):
    from sqlalchemy import text
    tables = ["store_stock_ledger", "store_stock_balance", "store_batch", "store_batch_balance", "store_grn", "store_grn_line", "store_issue", "store_issue_line",
              "store_issue_return", "store_transfer", "store_rejection", "store_reorder_alert", "store_indent", "purchase_orders", "purchase_order_line_items", "erp_items",
              "plant_fuel", "plant_expenses"]
    out = {}
    with database.engine.connect() as conn:
        have = {r[0] for r in conn.execute(text("select name from sqlite_master where type='table'"))}
        for t in tables:
            if t in have:
                out[t] = conn.execute(text("select count(*) from %s" % t)).scalar()
    return out


def _p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))] if xs else 0.0


# ------------------------------------------------------------------------------------------------------------- measure

def screens(meta):
    """Each Store Hub screen and the calls it makes when it opens (from the frontend's api modules)."""
    s1, s2, item = meta["stores"][0], meta["stores"][2], meta["items"][5]
    L = "limit=200"
    return {
        "Store dashboard": ["/api/store/dashboard"],
        "Store desk (registers)": ["/api/store/enquiry/balances?store_id=%d&limit=1000" % s2, "/api/store/enquiry/balances?store_id=%d&include_zero=true&limit=1000" % s2,
                                   "/api/store/enquiry/receipts?store_id=%d&limit=1000" % s2, "/api/store/enquiry/issues?store_id=%d&limit=1000" % s2, "/api/store/lookup/stores"],
        "Stock balance (all stores)": ["/api/store/enquiry/balances?limit=1000", "/api/store/enquiry/balances?q=steel&limit=1000"],
        "Item stock (one material)": ["/api/store/enquiry/items/%d" % item],
        "Stock ledger": ["/api/store/enquiry/ledger?limit=1000", "/api/store/enquiry/ledger?store_id=%d&item_id=%d&limit=1000" % (s1, item)],
        "Lot-wise stock": ["/api/store/batches?q=&hold_status=&page=1", "/api/store/outward/batches?store_id=%d&item_id=%d" % (s1, item)],
        "Purchase orders": ["/api/purchase-orders"],
        "Pending deliveries": ["/api/store/deliveries/pending", "/api/store/deliveries/suppliers"],
        "Goods receipts": ["/api/store/inward/grn?" + L, "/api/store/inward/grn?status=POSTED&" + L],
        "New goods receipt (PO picker)": ["/api/store/inward/po-options"],
        "Material issues": ["/api/store/outward/issue?" + L, "/api/store/outward/issue?q=foreman&" + L],
        "Material returns": ["/api/store/outward/returns?" + L],
        "Transfers": ["/api/store/control/transfer?" + L, "/api/store/control/in-transit"],
        "Stock counts": ["/api/store/control/count?" + L],
        "Indents": ["/api/store/outward/indent?" + L],
        "Low stock": ["/api/store/levels/low-stock", "/api/store/levels/low-stock?store_id=%d" % s2],
        "Low stock history": ["/api/store/levels/low-stock?view=history"],
        "Rejections / holds": ["/api/store/rejections"],
        "Quick find": ["/api/store/enquiry/quick?q=cem"],
        "Reports: valuation": ["/api/store/reports/valuation"],
        "Reports: movement": ["/api/store/reports/movement"],
        "Reports: consumption": ["/api/store/reports/consumption"],
        "Reports: reorder": ["/api/store/reports/reorder"],
        "Reports: ageing": ["/api/store/reports/ageing"],
        "Reports: slow-moving": ["/api/store/reports/slow-moving"],
        "Reports: reconciliation": ["/api/store/reports/reconciliation"],
        "Item picker": ["/api/store/lookup/items?q=ce", "/api/store/lookup/meta"],
        "Fuel register": ["/api/plant/fuel"],
        "Plant expenses": ["/api/plant/expenses"],
    }


class QueryMeter:
    """Counts the SQL statements a request runs and the time the database spends on them. The app answers on its own thread,
    so the count is global: it is switched on only while one request runs at a time (never in the concurrent part)."""

    def __init__(self, engine):
        from sqlalchemy import event
        self.stats, self.t0 = None, {}
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def _before(self, conn, cursor, statement, params, context, many):
        self.t0[id(cursor)] = time.perf_counter()

    def _after(self, conn, cursor, statement, params, context, many):
        st, t0 = self.stats, self.t0.pop(id(cursor), None)
        if st is None or t0 is None:
            return
        ms = (time.perf_counter() - t0) * 1000
        st["n"] += 1
        st["ms"] += ms
        if args_trace and ms > 5:
            st.setdefault("slow", []).append((round(ms, 1), " ".join(statement.split())[:300]))
        key = " ".join(statement.split())[:160]
        shapes = st.setdefault("shapes", {})
        shapes[key] = shapes.get(key, 0) + 1

    def start(self):
        self.stats = {"n": 0, "ms": 0.0}

    def stop(self):
        st, self.stats = self.stats, None
        return st


args_trace = False


def measure(args):
    global args_trace
    args_trace = args.trace
    meta = json.load(open(args.db + ".meta.json"))
    work = os.path.join(tempfile.mkdtemp(prefix="store_perf_"), "work.db")
    shutil.copyfile(args.db, work)                     # the same dataset for every run; the seed file stays as it was
    database = _boot(work)
    import main
    from fastapi.testclient import TestClient

    meter = QueryMeter(database.engine)
    out = {"label": args.label, "scale": meta["scale"], "counts": meta["counts"], "screens": {}, "writes": {}, "concurrency": {}}
    with TestClient(main.app) as c:
        assert c.post("/api/client/login", json={"email": meta["email"], "password": meta["password"]}).status_code == 200
        _settle()
        # --- each screen alone ---
        for name, urls in screens(meta).items():
            calls = []
            for url in urls:
                c.get(url)                               # warm
                runs, qn, qms, cpu, size, status, shapes = [], 0, 0.0, [], 0, 0, {}
                for _ in range(args.repeat):
                    meter.start()
                    c0, t0 = time.process_time(), time.perf_counter()
                    res = c.get(url)
                    runs.append((time.perf_counter() - t0) * 1000)
                    cpu.append((time.process_time() - c0) * 1000)
                    st = meter.stop()
                    qn, qms, size, status, shapes = st["n"], st["ms"], len(res.content), res.status_code, st.get("shapes", {})
                    slow = st.get("slow", [])
                tracemalloc.start()
                c.get(url)
                peak = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                repeated = sorted(((v, k) for k, v in shapes.items() if v > 5), reverse=True)[:3]
                calls.append({"url": url, "status": status, "sha1": hashlib.sha1(res.content).hexdigest(), "median_ms": round(statistics.median(runs), 1), "p95_ms": round(_p95(runs), 1),
                              "cpu_ms": round(statistics.median(cpu), 1), "queries": qn, "db_ms": round(qms, 1), "bytes": size,
                              "peak_kb": round(peak / 1024), "repeated": repeated, **({"slow_sql": slow[:5]} if args.trace else {})})
            # A screen opens its calls together; the browser waits for the slowest. The sum is what the server does.
            out["screens"][name] = {"calls": calls, "load_ms": max(x["median_ms"] for x in calls), "server_ms": round(sum(x["median_ms"] for x in calls), 1)}
            print("%-28s %8.1f ms  %s" % (name, out["screens"][name]["load_ms"], " | ".join("%s %.0fms q=%d %dKB" % (x["url"].split("/api/")[1][:38], x["median_ms"], x["queries"], x["bytes"] // 1024) for x in calls)))

        # --- the write path: one issue and one receipt-free transfer, created and posted ---
        out["writes"] = _writes(c, meta, meter, args.repeat)

    # --- several people at once ---
    for users in args.users:
        out["concurrency"][users] = _concurrent(main, meta, users, args.rounds)
        r = out["concurrency"][users]
        print("%2d users: %5d requests  %6.1f req/s  p50 %6.1f ms  p95 %7.1f ms  errors %d  (%s)" % (users, r["requests"], r["rps"], r["p50"], r["p95"], r["errors"], r.get("error_kinds", "")))
    out["integrity"] = integrity(database)
    print("Integrity:", json.dumps(out["integrity"]))
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print("Saved", args.out)


def _writes(c, meta, meter, repeat):
    s1 = meta["stores"][0]
    bal = c.get("/api/store/enquiry/balances?store_id=%d" % s1).json()
    rows = [r for r in (bal.get("items") or bal.get("rows") or []) if float(r.get("available") or r.get("on_hand") or 0) > 50]
    out = {}
    site = meta["stores"][2]
    open_lines = [(po["id"], l) for po in c.get("/api/store/inward/po-options").json().get("items", []) for l in po["lines"] if not l.get("needs_item")]
    low = [r for r in c.get("/api/store/levels/low-stock").json().get("items", []) if not r.get("action")]
    for label, make in (("issue: create + submit + approve + post", "issue"), ("transfer: create + submit + approve + post", "transfer"),
                        ("goods receipt: create + submit + approve + post", "grn"), ("indent: create + submit + approve", "indent"),
                        ("low stock: raise an indent for one alert", "raise")):
        times, qs = [], []
        for n in range(repeat):
            r = rows[n % len(rows)]
            meter.start()
            t0 = time.perf_counter()
            if make == "grn":
                po_id, l = open_lines[n % len(open_lines)]
                d = c.post("/api/store/inward/grn", json={"store_id": s1, "grn_date": day(0), "po_id": po_id, "challan_no": "PERF-%d" % n,
                                                          "lines": [{"po_line_id": l["po_line_id"], "qty": "1", "uom": l["base_uom"],
                                                                     **({"batch_no": "PERF-%d" % n, "expiry_date": day(-90)} if l.get("batch_tracked") else {})}]}).json()
                for gl in d.get("lines", []):
                    c.post("/api/store/inward/grn/%d/qc/%d" % (d["id"], gl["id"]), json={"result": "PASSED", "rejected_qty": "0", "note": "ok"})
                for step in ("submit", "approve", "post"):
                    c.post("/api/store/inward/grn/%d/%s" % (d["id"], step))
            elif make == "indent":
                d = c.post("/api/store/outward/indent", json={"store_id": site, "indent_date": day(0), "required_by": day(-7), "project_id": meta["jobs"][0],
                                                              "activity": "Slab casting", "lines": [{"item_id": r["item_id"], "qty": "5"}]}).json()
                c.post("/api/store/outward/indent/%d/submit" % d["id"])
                c.post("/api/store/outward/indent/%d/approve" % d["id"], json={"lines": [], "remarks": ""})
            elif make == "raise":
                a = low[n % len(low)]
                c.post("/api/store/levels/low-stock/raise", json={"action": "INDENT", "request_key": uuid.uuid4().hex, "project_id": a.get("project_id") or meta["jobs"][0],
                                                                  "lines": [{"store_id": a["store_id"], "item_id": a["item_id"], "qty": a["suggested_qty"], "alert_id": a["alert_id"]}]})
            elif make == "issue":
                d = c.post("/api/store/outward/issue", json={"store_id": s1, "issue_date": day(0), "project_id": meta["jobs"][0], "received_by_type": "FOREMAN", "received_by_name": "Perf",
                                                             "lines": [{"item_id": r["item_id"], "qty": "1", "cost_head": "OVERHEAD"}]}).json()
                for step in ("submit", "approve", "post"):
                    c.post("/api/store/outward/issue/%d/%s" % (d["id"], step))
            else:
                d = c.post("/api/store/control/transfer", json={"store_id": s1, "to_store_id": meta["stores"][2], "transfer_date": day(0),
                                                                "lines": [{"item_id": r["item_id"], "qty": "1"}]}).json()
                for step in ("submit", "approve", "post"):
                    c.post("/api/store/control/transfer/%d/%s" % (d["id"], step))
            times.append((time.perf_counter() - t0) * 1000)
            qs.append(meter.stop()["n"])
        out[label] = {"median_ms": round(statistics.median(times), 1), "p95_ms": round(_p95(times), 1), "queries": int(statistics.median(qs))}
        print("%-45s %7.1f ms  q=%d" % (label, out[label]["median_ms"], out[label]["queries"]))
    return out


def _concurrent(main, meta, users, rounds):
    """Each user signs in on their own session and works: mostly reading screens, sometimes issuing material."""
    from fastapi.testclient import TestClient
    urls = [u for us in screens(meta).values() for u in us]
    lat, errors, kinds, lock = [], [0], {}, threading.Lock()

    def person(n):
        rnd = random.Random(n)
        with TestClient(main.app) as c:
            if n % 2 and meta["staff"]:
                who = meta["staff"][n % len(meta["staff"])]
                c.post("/api/employee/auth/login", json={"email": who["email"], "password": "Store1Pass"})
                store = who["store_id"]
            else:
                c.post("/api/client/login", json={"email": meta["email"], "password": meta["password"]})
                store = meta["stores"][0]
            for _ in range(rounds):
                t0 = time.perf_counter()
                if rnd.random() < 0.2:
                    bal = c.get("/api/store/enquiry/balances?store_id=%d" % store).json()
                    rows = [r for r in (bal.get("items") or []) if float(r.get("available") or 0) > 5]
                    res = None
                    if rows:
                        r = rnd.choice(rows)
                        d = c.post("/api/store/outward/issue", json={"store_id": store, "issue_date": day(0), "project_id": meta["jobs"][0], "received_by_type": "FOREMAN",
                                                                     "received_by_name": "Load %d" % n, "lines": [{"item_id": r["item_id"], "qty": "1", "cost_head": "OVERHEAD"}]})
                        res = d
                        if d.status_code == 200:
                            for step in ("submit", "approve", "post"):
                                res = c.post("/api/store/outward/issue/%d/%s" % (d.json()["id"], step))
                                if res.status_code != 200:
                                    break
                else:
                    res = c.get(rnd.choice(urls))
                ms = (time.perf_counter() - t0) * 1000
                with lock:
                    lat.append(ms)
                    if res is not None and res.status_code >= 400 and res.status_code not in (403, 404):
                        errors[0] += 1
                        k = "%d %s" % (res.status_code, res.text[:60])
                        kinds[k] = kinds.get(k, 0) + 1

    t0 = time.perf_counter()
    threads = [threading.Thread(target=person, args=(n,)) for n in range(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    return {"requests": len(lat), "rps": round(len(lat) / wall, 1), "p50": round(statistics.median(lat), 1), "p95": round(_p95(lat), 1), "errors": errors[0],
            "error_kinds": dict(sorted(kinds.items(), key=lambda x: -x[1])[:3])}


def integrity(database):
    """The stock tables agree with the ledger: every balance is the sum of its ledger rows, no balance is negative, every lot's
    balances add up to its item's balance. Checked on whatever the run left behind (after the concurrent issues too)."""
    from sqlalchemy import text
    with database.engine.connect() as conn:
        mismatched = conn.execute(text(
            "select count(*) from store_stock_balance b left join (select store_id, item_id, sum(qty_in) - sum(qty_out) q from store_stock_ledger group by store_id, item_id) l "
            "on l.store_id = b.store_id and l.item_id = b.item_id where abs(coalesce(l.q, 0) - b.qty) > 0.0005")).scalar()
        negative = conn.execute(text("select count(*) from store_stock_balance where qty < -0.0005")).scalar()
        lots_off = conn.execute(text(
            "select count(*) from (select bb.store_id, bb.item_id, sum(bb.qty) q from store_batch_balance bb group by bb.store_id, bb.item_id) x "
            "join store_stock_balance b on b.store_id = x.store_id and b.item_id = x.item_id where abs(x.q - b.qty) > 0.0005")).scalar()
        dup_posts = conn.execute(text(
            "select count(*) from (select ref_doc_type, ref_doc_id, ref_line_id, store_id, count(*) n from store_stock_ledger where reversal_of_id is null and ref_line_id is not null "
            "group by ref_doc_type, ref_doc_id, ref_line_id, store_id, movement_type having count(*) > 1) d")).scalar()
        ledger = conn.execute(text("select count(*) from store_stock_ledger")).scalar()
    return {"ledger_rows": ledger, "balances_not_matching_ledger": mismatched, "negative_balances": negative, "lots_not_matching_stock": lots_off, "lines_posted_twice": dup_posts}


def probe(args):
    """One URL at a time: how many statements, which ones repeat, and where the Python time goes."""
    import cProfile
    import pstats
    meta = json.load(open(args.db + ".meta.json"))
    work = os.path.join(tempfile.mkdtemp(prefix="store_probe_"), "work.db")
    shutil.copyfile(args.db, work)
    database = _boot(work)
    import main
    from fastapi.testclient import TestClient
    meter = QueryMeter(database.engine)
    with TestClient(main.app) as c:
        c.post("/api/client/login", json={"email": meta["email"], "password": meta["password"]})
        _settle()
        for url in args.urls:
            c.get(url)
            meter.start()
            prof = cProfile.Profile()
            t0 = time.perf_counter()
            prof.enable()
            res = c.get(url)
            prof.disable()
            ms = (time.perf_counter() - t0) * 1000
            st = meter.stop()
            print("\n=== %s  %d  %.0f ms  %d queries (%.0f ms in the database)  %d KB" % (url, res.status_code, ms, st["n"], st["ms"], len(res.content) // 1024))
            for k, v in sorted(st.get("shapes", {}).items(), key=lambda x: -x[1])[:args.top]:
                print("  %5d x %s" % (v, k[:150]))
            ps = pstats.Stats(prof)
            ps.sort_stats("cumulative")
            rows = [(v[3], fn) for fn, v in ps.stats.items() if "app" + os.sep in fn[0] or "/app/" in fn[0]]
            for cum, fn in sorted(rows, key=lambda x: -x[0])[:args.top]:
                print("  %7.1f ms  %s:%d %s" % (cum * 1000, os.path.relpath(fn[0], BACKEND), fn[1], fn[2]))


def compare(args):
    a, b = json.load(open(args.before)), json.load(open(args.after))
    same, diff = 0, []
    for name, s in a["screens"].items():
        for x, y in zip(s["calls"], b["screens"].get(name, {}).get("calls", [])):
            if x.get("sha1") == y.get("sha1"):
                same += 1
            else:
                diff.append(x["url"])
    print("Responses identical before and after: %d of %d%s" % (same, same + len(diff), ("; differ: " + ", ".join(diff)) if diff else ""))
    print("%-30s %10s %10s %8s" % ("Screen (slowest call)", a["label"], b["label"], "change"))
    for name, s in a["screens"].items():
        t = b["screens"].get(name)
        if t:
            print("%-30s %8.1fms %8.1fms %7.0f%%" % (name, s["load_ms"], t["load_ms"], 100 * (t["load_ms"] - s["load_ms"]) / max(s["load_ms"], 0.1)))
    for k in a["concurrency"]:
        x, y = a["concurrency"][k], b["concurrency"].get(k)
        if y:
            print("%3s users  p95 %8.1f -> %8.1f ms   %6.1f -> %6.1f req/s   errors %d -> %d" % (k, x["p95"], y["p95"], x["rps"], y["rps"], x["errors"], y["errors"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--db", required=True)
    s.add_argument("--scale", type=int, default=1)
    s.add_argument("--items", type=int, default=300)
    s.add_argument("--issues", type=int, default=1500)
    s.add_argument("--seed", type=int, default=42)
    m = sub.add_parser("measure")
    m.add_argument("--db", required=True)
    m.add_argument("--label", default="run")
    m.add_argument("--out", default="")
    m.add_argument("--repeat", type=int, default=5)
    m.add_argument("--users", type=int, nargs="*", default=[1, 5, 10])
    m.add_argument("--rounds", type=int, default=20)
    m.add_argument("--trace", action="store_true")
    pr = sub.add_parser("probe")
    pr.add_argument("--db", required=True)
    pr.add_argument("--top", type=int, default=10)
    pr.add_argument("urls", nargs="+")
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    a = p.parse_args()
    if a.cmd == "seed":
        if os.path.exists(a.db):
            raise SystemExit("%s exists: seed a new file" % a.db)
        seed(a)
    elif a.cmd == "probe":
        probe(a)
    elif a.cmd == "measure":
        a.out = a.out or "%s.%s.json" % (a.db, a.label)
        measure(a)
    else:
        compare(a)
