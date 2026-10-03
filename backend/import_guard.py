"""
Looking at an uploaded workbook before trusting it.

Every import - the measurement book, the schedule, the registration forms, a register - starts here, so
a file that cannot be read is answered in the same plain words everywhere, and one that could hurt the
server (huge, or a zip made to unpack into gigabytes) is turned away before anything opens it.

Raises ValueError with a message meant to be shown to the person who chose the file.
"""
import io
import zipfile

MAX_UPLOAD = 15 * 1024 * 1024          # a workbook past this is split, not uploaded
MAX_UNPACKED = 250 * 1024 * 1024       # what the workbook may unpack to
MAX_RATIO = 80                         # a real workbook shrinks about 5-15x; a bomb shrinks thousands

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # the old .xls format - and a password-protected .xlsx


def check_workbook_bytes(raw, filename=""):
    """Refuse what cannot be an .xlsx workbook, saying why in words a person can act on."""
    name = (filename or "").lower()
    if not raw:
        raise ValueError("That file is empty.")
    if len(raw) > MAX_UPLOAD:
        raise ValueError("That file is %d MB; the limit is %d MB. Split it and upload it in parts." % (
            len(raw) // (1024 * 1024), MAX_UPLOAD // (1024 * 1024)))
    if raw[:8] == OLE_SIGNATURE:
        if name.endswith(".xls"):
            raise ValueError("That is an old Excel file (.xls). Open it in Excel and use Save As > Excel Workbook (.xlsx), then upload that.")
        raise ValueError("That workbook is password-protected or in the old Excel format. Remove the password, "
                         "or Save As > Excel Workbook (.xlsx), then upload it again.")
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        if name.endswith((".xlsx", ".xlsm")):
            raise ValueError("That file is not a readable Excel workbook - it may be damaged or cut short. Open it in Excel and save it again.")
        raise ValueError("That is not an Excel workbook (.xlsx).")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos = z.infolist()
            names = {i.filename for i in infos}
            unpacked = sum(i.file_size for i in infos)
            if unpacked > MAX_UNPACKED or (len(raw) and unpacked / float(len(raw)) > MAX_RATIO and unpacked > 20 * 1024 * 1024):
                raise ValueError("That workbook unpacks to far more than a measurement book should. Save it again from Excel and retry.")
            if "xl/workbook.xml" not in names:
                raise ValueError("That file is a zip, but not an Excel workbook.")
            bad = z.testzip()
            if bad:
                raise ValueError("That workbook is damaged (%s could not be read). Open it in Excel and save it again." % bad)
    except zipfile.BadZipFile:
        raise ValueError("That workbook is damaged. Open it in Excel and save it again.")
