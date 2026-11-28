# Finishes Flogas/Oxigen bill, AIB/Revolut statement and Revenue titles after import (run by post_consume.sh through
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
# AIB statements ("Statement of Account with Allied Irish Banks"): their
#   "Date of Statement" box does not come through in the text, so a statement is
#   dated by its last transaction and titled with the period from its "Balance
#   Forward" date: "AIB Statement 2025-04 (19 Mar–28 Apr)". The 17 statements in
#   prod (2026-11-27) chain end to end that way.
# Revolut statements: the period is in the file name
#   (account-statement_2017-05-01_2026-11-27_en-us_<id>.pdf), the currency opens
#   the text ("EUR Statement"): "Revolut EUR Statement 2026-11 (1 May 2017–27 Nov 2026)",
#   dated by the period's end.
# Revenue documents: kind and tax year from the file name
#   (Tax_Credit_Certificate_2021_<n>.pdf -> "Revenue Tax Credit Certificate 2021");
#   the date stays the issue date Paperless read from the letter.
# Oxigen bills: Paperless dates them from the bin calendar on the page; the real
#   date is the "Payment Request Date". Title "Oxigen Bill 2026-03", plus the
#   "Period Of Cover" when both of its dates read cleanly (OCR often garbles the end).
# Figures (custom fields): see bill_figures() below.
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


AIB_MARK = "statement of account with allied irish banks"
TEXT_DATE = re.compile(r"\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{4})\b", re.I)


def aib_title(content):
    """Returns (statement_date, title) for an AIB statement, or None."""
    text = re.sub(r"\s+", " ", content or "")
    if AIB_MARK not in text.lower():
        return None
    dates = []
    for d, m, y in TEXT_DATE.findall(text):
        try:
            dates.append(datetime.date(int(y), MON.index(m[:3].title()) + 1, int(d)))
        except ValueError:
            continue
    if not dates:
        return None
    first, last = min(dates), max(dates)
    a, b = f"{first.day} {MON[first.month - 1]}", f"{last.day} {MON[last.month - 1]}"
    span = f"{a}–{b}" if first.year == last.year else f"{a} {first.year}–{b} {last.year}"
    return last, f"AIB Statement {last:%Y-%m} ({span})"


REVOLUT_FILE = re.compile(r"^account-statement_(\d{4})-(\d{2})-(\d{2})_(\d{4})-(\d{2})-(\d{2})_", re.I)


def revolut_title(original_filename, content):
    """Returns (end_date, title) for a Revolut statement, or None."""
    m = REVOLUT_FILE.match(original_filename or "")
    if not m:
        return None
    first = datetime.date(int(m[1]), int(m[2]), int(m[3]))
    last = datetime.date(int(m[4]), int(m[5]), int(m[6]))
    cur = re.match(r"\s*([A-Z]{3}) Statement", content or "")
    a, b = f"{first.day} {MON[first.month - 1]}", f"{last.day} {MON[last.month - 1]}"
    span = f"{a}–{b}" if first.year == last.year else f"{a} {first.year}–{b} {last.year}"
    return last, f"Revolut {cur[1] + ' ' if cur else ''}Statement {last:%Y-%m} ({span})"


REVENUE_FILE = re.compile(r"^(.*)_((?:19|20)\d\d)_\d+(?:\.pdf)?$", re.I)
UPPER = {"lpt", "paye", "usc", "vht", "ppsn"}
SMALL = {"of", "and", "for", "to", "the"}


def revenue_title(original_filename):
    """Returns the title for a Revenue download, or None."""
    m = REVENUE_FILE.match(original_filename or "")
    if not m:
        return None
    words = [w for w in re.sub(r"_eng_.*$", "", m[1], flags=re.I).split("_") if w]
    kind = " ".join(w.upper() if w.lower() in UPPER else w.lower() if i and w.lower() in SMALL
                    else w[:1].upper() + w[1:].lower() for i, w in enumerate(words))
    return f"Revenue {kind} {m[2]}"


# The account number sits between the label and the date: allow anything short.
OX_DATE = re.compile(r"Payment\s*Request\s*Date.{0,60}?\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4})", re.I)
OX_PERIOD = re.compile(r"Period\s*Of\s*Cover\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", re.I)


def _date(d, m, y):
    try:
        return datetime.date(int(y), MON.index(m[:3].title()) + 1, int(d))
    except ValueError:
        return None


def oxigen_title(content):
    """Returns (payment_request_date, title) for an Oxigen bill, or None."""
    text = re.sub(r"\s+", " ", content or "")
    m = OX_DATE.search(text)
    issued = _date(*m.groups()) if m else None
    if not issued:
        return None
    title = f"Oxigen Bill {issued:%Y-%m}"
    p = OX_PERIOD.search(text)
    if p:
        a, b = _date(*p.groups()[:3]), _date(*p.groups()[3:])
        if a and b and a <= b:
            sa, sb = f"{a.day} {MON[a.month - 1]}", f"{b.day} {MON[b.month - 1]}"
            title += f" ({sa}–{sb})" if a.year == b.year else f" ({sa} {a.year}–{sb} {b.year})"
    return issued, title


# ---- Figures, saved as custom fields (rules.yaml: custom_fields) ------------
# Only for documents that keep arriving in the same layout; one-off documents
# (invoices, quotes, old payslips, Statements of Liability) were filled in once.
# Unit rates are stored in cent/kWh: gas bills print cent, electricity bills €.
MONEY = r"(-?[\d,]+\.\d{2})"


def _m(x):
    return float(x.replace(",", ""))


def bill_figures(name, title, content):
    """Returns {custom field name: value} for a recurring bill or payslip."""
    t = re.sub(r"\s+", " ", content or "")
    out = {}
    if name == "Flogas":
        if title.startswith("Flogas Gas"):
            lines = re.findall(r"Gas Used kWh ([\d,]+) ([\d.]+) [A-Z]? ?cent/kWh " + MONEY, t)
        else:
            lines = re.findall(r"Units ([\d,]+) ([\d.]+) \d+% €/kWh " + MONEY, t)
        kwh = sum(int(k.replace(",", "")) for k, _, _ in lines)
        cost = sum(_m(c) for _, _, c in lines)
        if kwh:
            out["kWh"] = kwh
            out["Unit rate (c/kWh)"] = round(cost / kwh * 100, 2)   # weighted if the rate changed
        m = re.search(r"Current Bill €?\s?" + MONEY, t)
        if m:
            out["Amount"] = _m(m[1])
    elif name == "Pure Telecom":
        m = re.search(r"Bill Amount €\s?" + MONEY, t)
        if m:
            out["Amount"] = _m(m[1])
    elif name == "Oxigen":
        m = re.search(r"Balance on account €\s?" + MONEY, t)
        if m:
            out["Amount"] = _m(m[1])
    elif name == "Workday" and "Payslip" in title:
        g, n = re.search(r"\+ Gross Pay " + MONEY, t), re.search(r"NETT PAY " + MONEY, t)
        if g and n:
            oc = re.search(r"ON CALL " + MONEY, t)
            out = {"Gross pay": _m(g[1]), "Net pay": _m(n[1]), "On-call pay": _m(oc[1]) if oc else 0.0}
    return out


def set_fields(doc, values):
    from documents.models import CustomField, CustomFieldInstance
    for fname, value in values.items():
        field = CustomField.objects.filter(name=fname).first()
        if not field:
            print(f"post_consume: custom field '{fname}' missing; skipped")
            continue
        store = {"monetary": "value_monetary", "integer": "value_int", "float": "value_float"}[field.data_type]
        if field.data_type == "monetary":
            value = f"EUR{value:.2f}"
        CustomFieldInstance.objects.update_or_create(document=doc, field=field, defaults={store: value})
    if values:
        print(f"post_consume: document {doc.pk} fields {values}")


def main():
    doc = Document.objects.get(pk=int(os.environ["DOCUMENT_ID"]))
    name = doc.correspondent.name if doc.correspondent else ""
    found = None
    if name == "Revenue":
        title = revenue_title(doc.original_filename)
        found = (doc.created, title) if title else None
    elif name == "AIB":
        found = aib_title(doc.content)
    elif name == "Revolut":
        found = revolut_title(doc.original_filename, doc.content)
    elif name == "Oxigen":
        found = oxigen_title(doc.content)
    elif name == "Flogas":
        found = flogas_title(doc.original_filename, doc.content)
    elif name not in ("Pure Telecom", "Workday"):
        return
    if found and (doc.created, doc.title) != found:
        doc.created, doc.title = found
        doc.save()
        try:  # keep search results in step with the new title (as Paperless's add_to_index)
            from documents.search import get_backend
            get_backend().add_or_update(doc.root_document if doc.root_document_id else doc)
        except Exception as e:  # noqa: BLE001
            print(f"post_consume: search index not updated for {doc.pk}: {e}")
        print(f"post_consume: document {doc.pk} -> {found[0]} '{found[1]}'")
    elif found is None and name in ("AIB", "Revolut", "Oxigen", "Flogas"):
        print(f"post_consume: {name} document {doc.pk} not recognised; title left as is")
    try:
        set_fields(doc, bill_figures(name, doc.title, doc.content))
    except Exception as e:  # noqa: BLE001
        print(f"post_consume: fields not set for {doc.pk}: {e}")


if os.environ.get("DOCUMENT_ID"):
    try:
        main()
    except Exception as e:  # noqa: BLE001 - never fail an import
        print(f"post_consume: error, document left as is: {e}")
