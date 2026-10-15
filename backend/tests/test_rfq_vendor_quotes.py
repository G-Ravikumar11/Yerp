"""Suppliers quoting through their own link, and quotations read in whatever form they come: Word, Excel, old Office
files, OpenOffice, RTF, CSV, photos and PDFs, typed or scanned."""
import io
import json
import zipfile

import pytest

from app import models
from app.ai import doc_text
from app.db import SessionLocal
from test_comparative_statement import quote, rfq

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(paragraph, rows):
    cells = "".join("<w:tr>%s</w:tr>" % "".join("<w:tc><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:tc>" % c for c in row) for row in rows)
    xml = '<w:document %s><w:body><w:p><w:r><w:t>%s</w:t></w:r></w:p><w:tbl>%s</w:tbl></w:body></w:document>' % (W, paragraph, cells)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def xlsx(rows):
    from openpyxl import Workbook
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def invite(tenant, r, supplier, **extra):
    res = tenant.post("/api/rfqs/%d/invites" % r["rfq"]["id"], json={"supplier_name": supplier, **extra})
    assert res.status_code == 200, res.text
    return res.json()["invite"]


def token_of(inv):
    return inv["link"].split("token=")[1]


def send(client, token, rates=None, file=None, **extra):
    body = {"lines": rates or [], **extra}
    files = {"file": file} if file else None
    return client.post("/api/vendor-quote/%s" % token, data={"quote": json.dumps(body)}, files=files)


# --- reading any document --------------------------------------------------------------------------------------------

def test_word_excel_csv_rtf_and_old_office_files_are_read_into_words():
    kind, text, _ = doc_text.to_text_or_picture(docx("Quotation SR/45", [["Cement OPC 53", "Bags", "385"]]), "q.docx", "application/octet-stream")
    assert kind == "docx" and "Cement OPC 53\tBags\t385" in text and "SR/45" in text
    kind, text, _ = doc_text.to_text_or_picture(xlsx([["Item", "Rate"], ["TMT 12mm", 61500]]), "QUOTE.XLSX", "")
    assert kind == "xlsx" and "TMT 12mm\t61500" in text
    kind, text, _ = doc_text.to_text_or_picture(b"Item,Rate\nSand,1450\n", "q.csv", "text/csv")
    assert kind == "text" and "Sand\t1450" in text
    rtf = rb"{\rtf1\ansi Quotation\par Sand\cell 1450\cell\row}"
    kind, text, _ = doc_text.to_text_or_picture(rtf, "q.rtf", "")
    assert kind == "rtf" and "Sand\t1450" in text
    old = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 300 + "Cement 53 grade Rs 385 per bag".encode("utf-16-le") + b"\x00" * 100
    kind, text, _ = doc_text.to_text_or_picture(old, "q.doc", "application/msword")
    assert kind == "doc" and "Rs 385 per bag" in text


def test_a_file_is_known_by_what_it_is_not_its_name():
    """Vendors send files with the wrong name or none: a Word file called .pdf is still read as Word."""
    kind, text, _ = doc_text.to_text_or_picture(docx("Rates", [["Sand", "1450"]]), "quotation.pdf", "application/pdf")
    assert kind == "docx" and "Sand\t1450" in text


def test_photos_other_than_jpeg_are_made_into_jpegs_and_heic_and_junk_are_refused_in_words():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), "white").save(buf, "BMP")
    kind, _, picture = doc_text.to_text_or_picture(buf.getvalue(), "scan.bmp", "image/bmp")
    assert kind == "picture" and picture[1] == "image/jpeg" and picture[0][:3] == b"\xff\xd8\xff"
    with pytest.raises(doc_text.Unreadable, match="iPhone"):
        doc_text.to_text_or_picture(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 50, "IMG_1.HEIC", "image/heic")
    with pytest.raises(doc_text.Unreadable):
        doc_text.to_text_or_picture(b"\x00\x01\x02" * 40, "x.bin", "")


def test_a_scanned_pdf_is_drawn_as_pages_for_the_model_that_reads_photos():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(50, 50, 200, 200, fill=1)                         # a picture only: no words inside
    c.showPage()
    c.save()
    pages = doc_text.scan_pages(buf.getvalue())
    assert len(pages) == 1 and pages[0][:3] == b"\xff\xd8\xff"


# --- links for suppliers --------------------------------------------------------------------------------------------

def test_a_link_per_supplier_shows_only_the_items_and_marks_when_it_is_opened(tenant, client):
    tenant.post("/api/suppliers", json={"name": "Sri Ram Traders", "phone": "9876543210", "email": "sr@example.com"})
    r = rfq(tenant)
    inv = invite(tenant, r, "Sri Ram Traders")
    assert inv["status"] == "sent" and inv["link"].startswith("/next/quote?token=") and inv["phone"] == "9876543210"
    assert invite(tenant, r, "sri ram traders ")["id"] == inv["id"], "asked again, the same link comes back"
    page = client.get("/api/vendor-quote/%s" % token_of(inv)).json()
    assert page["supplier_name"] == "Sri Ram Traders" and page["rfq"]["number"] == r["rfq"]["number"] and page["open"]
    assert [l["description"] for l in page["lines"]] == ["Cement OPC 53", "TMT Fe500D 12mm"]
    assert "rate" not in page["lines"][0] and "suppliers" not in page, "nobody else's prices are shown"
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    assert st["invites"][0]["status"] == "opened"
    assert client.get("/api/vendor-quote/not-a-real-token").status_code == 404


def test_a_supplier_sends_rates_and_his_word_file_and_it_lands_in_the_comparison(tenant, client):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    inv = invite(tenant, r, "Sri Ram Traders")
    lines = [{"rfq_line_id": r["lines"][0]["rfq_line_id"], "rate": 380, "tax_percent": 28},
             {"rfq_line_id": r["lines"][1]["rfq_line_id"], "rate": 61000, "tax_percent": 18}]
    word = docx("Quotation SR/45", [["Cement", "380"], ["TMT", "61000"]])
    res = send(client, token_of(inv), lines, ("SR quotation.docx", word, "application/octet-stream"), quote_ref="SR/45",
               delivery_days=3, freight=2500, message="Prices valid 15 days")
    assert res.status_code == 200, res.text and "Thank you" in res.json()["message"]
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    sr = next(s for s in st["suppliers"] if s["supplier_name"] == "Sri Ram Traders")
    assert sr["source"] == "vendor" and sr["quote_ref"] == "SR/45" and sr["freight"] == 2500 and sr["delivery_days"] == 3
    assert sr["document"]["name"] == "SR quotation.docx"
    assert tenant.get("/api/files/%d" % sr["document"]["id"]).content == word, "kept as he sent it"
    assert st["invites"][0]["status"] == "quoted" and st["invites"][0]["message"] == "Prices valid 15 days"
    assert next(s for s in st["suppliers"] if s["supplier_name"] == "ACC")["source"] == "buyer"
    with SessionLocal() as db:
        alert = db.query(models.DBAlert).filter(models.DBAlert.kind == "quote_received").first()
        assert alert and "Sri Ram Traders" in alert.title
    # sent again, his quote is revised, not doubled
    lines[0]["rate"] = 375
    assert send(client, token_of(inv), lines, quote_ref="SR/45").status_code == 200
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    assert [s["supplier_name"] for s in st["suppliers"]].count("Sri Ram Traders") == 1
    assert next(o for o in st["lines"][0]["offers"] if o["supplier_name"] == "Sri Ram Traders")["rate"] == 375
    page = client.get("/api/vendor-quote/%s" % token_of(inv)).json()
    assert page["lines"][0]["rate"] == 375 and page["answer"]["quote_ref"] == "SR/45", "he sees what he sent"


def test_a_supplier_can_send_just_his_excel_quotation_for_the_buyer_to_read(tenant, client):
    r = rfq(tenant)
    inv = invite(tenant, r, "Lakshmi Steels")
    sheet = xlsx([["Item", "Rate"], ["TMT 12mm", 61500]])
    res = send(client, token_of(inv), file=("rates.xlsx", sheet, "application/vnd.ms-excel"))
    assert res.status_code == 200, res.text
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    i = st["invites"][0]
    assert i["status"] == "document" and i["document"]["name"] == "rates.xlsx" and st["suppliers"] == []
    assert send(client, token_of(inv)).status_code == 400, "neither rates nor a file"
    bad = send(client, token_of(inv), file=("x.bin", b"\x00\x01\x02" * 40, "application/octet-stream"))
    assert bad.status_code == 400 and "could not be read" in bad.json()["detail"]


def test_a_link_stops_taking_quotes_once_the_enquiry_is_closed_and_can_be_withdrawn(tenant, client):
    r = rfq(tenant)
    inv = invite(tenant, r, "Late Supplier")
    gone = invite(tenant, r, "Withdrawn Supplier")
    assert tenant.delete("/api/rfqs/%d/invites/%d" % (r["rfq"]["id"], gone["id"])).status_code == 200
    assert client.get("/api/vendor-quote/%s" % token_of(gone)).status_code == 404
    assert tenant.post("/api/rfqs/%d/cancel" % r["rfq"]["id"], json={"reason": "Not needed"}).status_code == 200
    page = client.get("/api/vendor-quote/%s" % token_of(inv)).json()
    assert page["open"] is False
    line = [{"rfq_line_id": r["lines"][0]["rfq_line_id"], "rate": 380}]
    res = send(client, token_of(inv), line)
    assert res.status_code == 409 and "closed" in res.json()["detail"]
    assert tenant.post("/api/rfqs/%d/invites" % r["rfq"]["id"], json={"supplier_name": "Another"}).status_code == 409


def test_reading_a_suppliers_file_without_ai_says_to_type_or_send_it(tenant, client, monkeypatch):
    from app.ai import config
    monkeypatch.setattr(config, "enabled", lambda: False)
    r = rfq(tenant)
    inv = invite(tenant, r, "Sri Ram Traders")
    assert client.get("/api/vendor-quote/%s" % token_of(inv)).json()["can_read"] is False
    res = client.post("/api/vendor-quote/%s/read" % token_of(inv), files={"file": ("q.docx", docx("Q", [["Cement", "380"]]), "application/octet-stream")})
    assert res.status_code == 200 and res.json()["available"] is False and "send the file" in res.json()["message"]


def test_the_buyer_keeps_a_quotation_file_of_any_kind_with_a_quote(tenant):
    r = rfq(tenant)
    c = quote(tenant, r, "ACC", 390, 62000)
    qid = c["suppliers"][0]["quote_id"]
    old_word = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 300 + "ACC quotation".encode("utf-16-le")
    res = tenant.post("/api/rfqs/%d/quotes/%d/document" % (r["rfq"]["id"], qid), files={"file": ("ACC.doc", old_word, "application/msword")})
    assert res.status_code == 200, res.text
    st = tenant.get("/api/rfqs/%d/statement" % r["rfq"]["id"]).json()
    assert st["suppliers"][0]["document"]["name"] == "ACC.doc"


def test_deleting_an_enquiry_takes_its_links_and_the_suppliers_files(tenant, client):
    r = rfq(tenant)
    inv = invite(tenant, r, "Sri Ram Traders")
    send(client, token_of(inv), file=("rates.xlsx", xlsx([["Sand", 1450]]), "application/octet-stream"))
    res = tenant.delete("/api/master/rfq/%d" % r["rfq"]["id"])
    assert res.status_code == 200, res.text
    with SessionLocal() as db:
        assert db.query(models.DBRfqInvite).filter(models.DBRfqInvite.rfq_id == r["rfq"]["id"]).count() == 0
        assert db.query(models.DBFile).filter(models.DBFile.attached_type == "rfq_invite",
                                              models.DBFile.attached_id == inv["id"]).count() == 0


# --- checking a quote against the supplier's own quotation (as an RA bill against its hard copy) --------------------

def test_a_quote_is_checked_item_by_item_against_their_quotation(tenant, monkeypatch):
    from app.ai import quote_reader
    from app.ai.llm_client import AiResult
    r = rfq(tenant)
    c = quote(tenant, r, "ACC", 390, 62000, freight=1500, quote_ref="ACC/221")
    cem, stl = r["lines"][0]["rfq_line_id"], r["lines"][1]["rfq_line_id"]
    qid = c["suppliers"][0]["quote_id"]
    assert tenant.post("/api/ai/rfqs/%d/quotes/%d/check" % (r["rfq"]["id"], qid)).status_code == 409, "nothing to check against yet"
    tenant.post("/api/rfqs/%d/quotes/%d/document" % (r["rfq"]["id"], qid), files={"file": ("ACC.docx", docx("ACC/221", [["Cement", "390"]]), "application/octet-stream")})
    paper = {"supplier_name": "ACC", "quote_ref": "ACC/221", "freight": 2500, "delivery_days": None,
             "lines": [{"rfq_line_id": cem, "rate": 390, "tax_percent": 18}, {"rfq_line_id": stl, "rate": 61500, "tax_percent": 18}],
             "unmatched": ["Sand 1450 per cum"], "confidence": 0.9}
    monkeypatch.setattr(quote_reader, "ask_json", lambda *a, **k: AiResult(True, model="t", data=paper))
    monkeypatch.setattr(quote_reader.guard, "run_feature", lambda db, req, client, key, label, ref, call: call())
    res = tenant.post("/api/ai/rfqs/%d/quotes/%d/check" % (r["rfq"]["id"], qid))
    assert res.status_code == 200, res.text
    out = res.json()
    rows = {x["rfq_line_id"]: x for x in out["rows"]}
    assert rows[cem]["status"] == "agrees" and rows[stl]["status"] == "differs"
    assert (rows[stl]["entered_rate"], rows[stl]["paper_rate"]) == (62000, 61500)
    assert [t["item"] for t in out["terms"] if t["status"] == "differs"] == ["Transport to site"]
    assert out["differences"] == 2 and out["agrees"] is False and out["unmatched"] == ["Sand 1450 per cum"]


def test_checking_without_ai_says_so(tenant):
    r = rfq(tenant)
    c = quote(tenant, r, "ACC", 390, 62000)
    qid = c["suppliers"][0]["quote_id"]
    tenant.post("/api/rfqs/%d/quotes/%d/document" % (r["rfq"]["id"], qid), files={"file": ("ACC.xlsx", xlsx([["Cement", 390]]), "application/octet-stream")})
    out = tenant.post("/api/ai/rfqs/%d/quotes/%d/check" % (r["rfq"]["id"], qid)).json()
    assert out["available"] is False


def test_their_word_or_excel_quotation_can_be_read_as_text_beside_the_quote(tenant):
    r = rfq(tenant)
    c = quote(tenant, r, "ACC", 390, 62000)
    qid = c["suppliers"][0]["quote_id"]
    tenant.post("/api/rfqs/%d/quotes/%d/document" % (r["rfq"]["id"], qid), files={"file": ("ACC.xlsx", xlsx([["Cement OPC 53", 390]]), "application/octet-stream")})
    out = tenant.get("/api/rfqs/%d/quotes/%d/document-text" % (r["rfq"]["id"], qid)).json()
    assert out["kind"] == "xlsx" and "Cement OPC 53\t390" in out["text"]
