"""Reading a sheet somebody actually sent.

The template is a suggestion, not a contract. These pin down the three things
that stop a good sheet being refused: the kind is read from the rows rather
than declared, columns are matched by name rather than position, and anything
with exactly one right answer is corrected before a person is asked about it.
"""


def sheet(*lines):
    """CRLF, as Excel writes it."""
    return "\r\n".join(lines).encode("utf-8-sig") + b"\r\n"


TEMPLATE_HEADER = ("Item Code,Item Name,Segment,Description,Category,Sub Category,"
                   "HSN Code,Item Tax Type,Item Type,Units Of Measure,Make")


def analyse(tenant, payload, **form):
    return tenant.post("/api/erp/items/analyse",
                       files={"file": ("s.csv", payload, "text/csv")}, data=form)


def commit(tenant, rows):
    return tenant.post("/api/erp/items/commit", json={"rows": rows})


def clean_rows(result):
    return [r for r in result["rows"] if not r.get("_problems")]


# --- Kind detection ---------------------------------------------------------

def test_the_kind_is_read_from_the_sheet_not_declared(tenant):
    """The case that used to fail: an FG sheet uploaded without saying so.

    The old flow made you pick RM or FG first and then refused the file for
    disagreeing with the choice - about a fact the file itself stated.
    """
    r = analyse(tenant, sheet(TEMPLATE_HEADER,
        "FG1,SUPPLY,YPPL,SUPPLY,FINISHED GOOD,FG,3917,18%,Purchased,Meters,")).json()
    assert r["detected"] == {"FG": 1}
    assert r["unknown_kind"] == 0
    assert r["ok"] is True


def test_one_sheet_can_hold_both_kinds(tenant):
    r = analyse(tenant, sheet(TEMPLATE_HEADER,
        "RM1,CONDUIT,YPPL,CONDUIT,RAW MATERIAL,RM,3917,18%,Purchased,Meters,",
        "FG1,SUPPLY,YPPL,SUPPLY,FINISHED GOOD,FG,3917,18%,Purchased,Meters,")).json()
    assert r["detected"] == {"RM": 1, "FG": 1}
    assert commit(tenant, clean_rows(r)).json()["created"] == 2
    assert tenant.get("/api/erp/items").json()["counts"] == {"RM": 1, "FG": 1}


def test_the_code_prefix_is_the_fallback(tenant):
    """No category columns at all - the code still says which series it is."""
    r = analyse(tenant, sheet("Item Code,Item Name",
                              "RM77,CONDUIT", "FG77,SUPPLY")).json()
    assert r["detected"] == {"RM": 1, "FG": 1}


def test_a_row_nobody_can_place_is_flagged_not_guessed(tenant):
    r = analyse(tenant, sheet("Item Code,Item Name", "X1,MYSTERY")).json()
    assert r["unknown_kind"] == 1
    assert r["ok"] is False
    assert r["rows"][0]["_problems"][0]["field"] == "category"


def test_an_explicit_kind_still_wins(tenant):
    """Passing kind forces it, so the strict path keeps its old behaviour."""
    r = analyse(tenant, sheet("Item Code,Item Name", "X1,MYSTERY"), kind="RM").json()
    assert r["detected"] == {"RM": 1}


# --- Header mapping ---------------------------------------------------------

def test_a_suppliers_own_column_names_are_understood(tenant):
    r = analyse(tenant, sheet(
        "Sr.No,Material Code,Particulars,Category,Sub Category,UOM,GST Rate,Nature Type,HSN",
        "1,RM500,20MM CONDUIT,RAW MATERIAL,RM,Meters,18%,Purchased,3917")).json()
    assert r["mapping"]["Material Code"] == "item_code"
    assert r["mapping"]["Particulars"] == "item_name"
    assert r["mapping"]["GST Rate"] == "item_tax_type"
    assert r["mapping"]["Nature Type"] == "item_type"
    assert "Sr.No" in r["unmapped_headers"]
    assert r["ok"] is True


def test_reordered_columns_do_not_shift_the_data(tenant):
    """Positional parsing put every field one to the left and said nothing."""
    r = analyse(tenant, sheet("Category,Sub Category,Item Name,Item Code",
                              "RAW MATERIAL,RM,20MM CONDUIT,RM600")).json()
    row = r["rows"][0]
    assert row["item_code"] == "RM600"
    assert row["item_name"] == "20MM CONDUIT"


def test_a_sheet_with_no_code_column_says_so(tenant):
    res = analyse(tenant, sheet("Name,Price", "Widget,10"))
    assert res.status_code == 400
    assert "item code" in res.json()["detail"].lower()


# --- Automatic repair -------------------------------------------------------

def test_units_are_matched_to_permitted_ones(tenant):
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category,Units Of Measure",
        "RM1,A,RM,mtrs", "RM2,B,RM,MTR", "RM3,C,RM,nos", "RM4,D,RM,kgs")).json()
    assert [x["units_of_measure"] for x in r["rows"]] == ["Meters", "Meters", "Nos", "Kgs"]


def test_tax_is_written_as_a_percentage(tenant):
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category,Item Tax Type",
        "RM1,A,RM,18", "RM2,B,RM,18 %", "RM3,C,RM,0.18", "RM4,D,RM,GST 5")).json()
    assert [x["item_tax_type"] for x in r["rows"]] == ["18%", "18%", "18%", "5%"]


def test_item_type_is_matched_to_a_permitted_one(tenant):
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category,Item Type",
        "FG1,A,FG,purchase", "FG2,B,FG,labour", "FG3,C,FG,installation")).json()
    assert [x["item_type"] for x in r["rows"]] == ["Purchased", "Service", "Service"]


def test_a_blank_description_is_taken_from_the_name(tenant):
    """The house rule is that the two are the same, so a blank is an omission."""
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category,Description",
                              "RM1,20MM CONDUIT,RM,")).json()
    assert r["rows"][0]["description"] == "20MM CONDUIT"


def test_the_category_columns_follow_the_detected_kind(tenant):
    r = analyse(tenant, sheet("Item Code,Item Name,Category,Sub Category",
                              "RM1,CONDUIT,raw material,rm")).json()
    assert r["rows"][0]["category"] == "RAW MATERIAL"
    assert r["rows"][0]["sub_category"] == "RM"


def test_every_repair_is_itemised(tenant):
    """A silent correction to a price list is indistinguishable from a bug."""
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category,Units Of Measure",
                              "RM1,CONDUIT,RM,mtrs")).json()
    uom = [x for x in r["repairs"] if x["field"] == "units_of_measure"][0]
    assert uom["from"] == "mtrs" and uom["to"] == "Meters"
    assert uom["line"] == 2 and uom["note"]


def test_repairs_do_not_silently_invent_a_value(tenant):
    """Something genuinely unrecognisable is left alone and reported."""
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category,Item Type",
                              "FG1,A,FG,qwerty")).json()
    assert r["rows"][0]["item_type"] == "qwerty"
    assert any(p["field"] == "item_type" for p in r["rows"][0]["_problems"])


# --- Problems and their offered fixes ---------------------------------------

def test_a_duplicate_fg_code_comes_with_the_next_free_one(tenant):
    commit(tenant, clean_rows(analyse(tenant, sheet(
        "Item Code,Item Name,Sub Category", "FG1,FIRST,FG")).json()))
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category", "FG1,SECOND,FG")).json()
    problem = r["rows"][0]["_problems"][0]
    assert problem["field"] == "item_code"
    assert problem["fix"] == "FG2", "offer the next code in the series"


def test_a_repeat_inside_one_sheet_is_caught(tenant):
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category",
                              "FG1,A,FG", "FG1,B,FG")).json()
    assert "Also on line 2" in r["rows"][1]["_problems"][0]["message"]


def test_an_existing_rm_code_is_reuse_not_a_problem(tenant):
    commit(tenant, clean_rows(analyse(tenant, sheet(
        "Item Code,Item Name,Sub Category", "RM1,CONDUIT,RM")).json()))
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category", "RM1,CONDUIT,RM")).json()
    assert r["ok"] is True
    assert r["rows"][0]["_line"] in r["reused"]
    out = commit(tenant, clean_rows(r)).json()
    assert out["created"] == 0 and out["reused"] == 1


# --- Committing corrected rows ----------------------------------------------

def test_a_corrected_row_commits(tenant):
    """What the grid does: fix the cell, send the row, no second file."""
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category", "FG1,A,FG")).json()
    commit(tenant, clean_rows(r))
    again = analyse(tenant, sheet("Item Code,Item Name,Sub Category", "FG1,B,FG")).json()
    row = again["rows"][0]
    row["item_code"] = row["_problems"][0]["fix"]      # accept the offer
    row["_problems"] = []
    assert commit(tenant, [row]).json()["created"] == 1


def test_the_good_rows_of_a_partly_bad_sheet_still_land(tenant):
    commit(tenant, clean_rows(analyse(tenant, sheet(
        "Item Code,Item Name,Sub Category", "FG1,FIRST,FG")).json()))
    r = analyse(tenant, sheet("Item Code,Item Name,Sub Category",
                              "FG1,CLASH,FG", "FG9,FINE,FG")).json()
    assert r["summary"]["blocked"] == 1 and r["summary"]["ready"] == 1
    assert commit(tenant, clean_rows(r)).json()["created"] == 1


def test_commit_rechecks_rather_than_trusting_the_grid(tenant):
    """The endpoint is reachable on its own, so it cannot rely on analyse."""
    bad = [{"_line": 2, "_kind": "FG", "item_code": "", "item_name": "NO CODE"}]
    out = commit(tenant, bad).json()
    assert out["ok"] is False and out["created"] == 0


def test_commit_refuses_a_row_with_no_kind(tenant):
    out = commit(tenant, [{"_line": 2, "_kind": "", "item_code": "X1",
                           "item_name": "MYSTERY"}]).json()
    assert out["ok"] is False


def test_a_stranger_cannot_analyse_or_commit(client):
    assert client.post("/api/erp/items/analyse",
                       files={"file": ("s.csv", b"a,b\n1,2\n", "text/csv")}).status_code == 401
    assert client.post("/api/erp/items/commit", json={"rows": []}).status_code == 401
