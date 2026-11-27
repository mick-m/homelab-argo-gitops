# Finishes Flogas bill titles after import (run by post_consume.sh through
# "manage.py shell", so it uses Paperless's own database access).
#
# - Date: Paperless dates a Flogas bill from the first date in its text, the start
#   of the billing period, about two months early. The issue date is in the file
#   name, so take it from there:
#     gas          FGNG_<account>_<invoice>_DD-MM-YYYY_..PDF
#     electricity  YYYYMMDD_CUS<account>_InvoiceElec_<invoice>_..PDF
# - Title: "Flogas Gas Bill 2026-10 (7 Aug–2 Oct)", the billing period read from
#   the bill's "Billing Period dd/mm/yyyy – dd/mm/yyyy" line. Without that line
#   the period is left off.
# Anything else is left untouched. Checked against all 24 Flogas bills in prod
# (2026-11-27): every one has the line, and the periods join up end to end.
import datetime
import os
import re

from documents.models import Document

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GAS = re.compile(r"^FGNG_\d+_\d+_(\d{2})-(\d{2})-(\d{4})_", re.I)
ELEC = re.compile(r"^(\d{4})(\d{2})(\d{2})_CUS\d+_InvoiceElec_", re.I)
D = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})"
PERIOD = re.compile(r"Billing\s*Period[^0-9]{0,30}" + D + r"\s*(?:-|–|to)\s*" + D, re.I)


def flogas_title(original_filename, content):
    """Returns (issue_date, title) for a Flogas bill, or None if it is not one."""
    m = GAS.match(original_filename or "")
    if m:
        kind, issued = "Gas", datetime.date(int(m[3]), int(m[2]), int(m[1]))
    else:
        m = ELEC.match(original_filename or "")
        if not m:
            return None
        kind, issued = "Electricity", datetime.date(int(m[1]), int(m[2]), int(m[3]))
    title = f"Flogas {kind} Bill {issued:%Y-%m}"
    p = PERIOD.search(content or "")
    if p and 1 <= int(p[2]) <= 12 and 1 <= int(p[5]) <= 12:
        y1 = p[3] if len(p[3]) == 4 else "20" + p[3]
        y2 = p[6] if len(p[6]) == 4 else "20" + p[6]
        a, b = f"{int(p[1])} {MON[int(p[2]) - 1]}", f"{int(p[4])} {MON[int(p[5]) - 1]}"
        title += f" ({a}–{b})" if y1 == y2 else f" ({a} {y1}–{b} {y2})"
    return issued, title


def main():
    doc = Document.objects.get(pk=int(os.environ["DOCUMENT_ID"]))
    if not doc.correspondent or doc.correspondent.name != "Flogas":
        return
    found = flogas_title(doc.original_filename, doc.content)
    if not found:
        print(f"post_consume: Flogas document {doc.pk} has an unknown file name pattern; left as is")
        return
    issued, title = found
    if (doc.created, doc.title) == (issued, title):
        return
    doc.created, doc.title = issued, title
    doc.save()
    try:  # keep search results in step with the new title (as Paperless's add_to_index)
        from documents.search import get_backend
        get_backend().add_or_update(doc.root_document if doc.root_document_id else doc)
    except Exception as e:  # noqa: BLE001
        print(f"post_consume: search index not updated for {doc.pk}: {e}")
    print(f"post_consume: document {doc.pk} -> {issued} '{title}'")


if os.environ.get("DOCUMENT_ID"):
    try:
        main()
    except Exception as e:  # noqa: BLE001 - never fail an import
        print(f"post_consume: error, document left as is: {e}")
