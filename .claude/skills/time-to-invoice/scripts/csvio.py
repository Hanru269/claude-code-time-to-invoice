"""Shared CSV helpers for the Bookkeeping Kit scripts. Standard library only (Python 3.9+).

Copied into every skill's scripts/ folder at build time so each skill is self-contained.
Money is handled with Decimal, never float.
"""
import csv
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ISO_FORMATS = ["%Y-%m-%d", "%Y/%m/%d"]
DAY_FIRST = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d/%m/%y"]
MONTH_FIRST = ["%m/%d/%Y", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y", "%m/%d/%y"]


def parse_amount(text):
    """'1,234.56' '(123.45)' '-12' 'R 1 234,56' '$5' '12.50-' -> Decimal (parentheses / trailing minus = negative)."""
    if text is None:
        return Decimal("0")
    s = str(text).strip()
    if s == "":
        return Decimal("0")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    s = re.sub(r"[^\d.,]", "", s)  # drop currency symbols, spaces
    if not s:
        return Decimal("0")
    # European style: comma is the decimal separator when it is the last separator and followed by 1-2 digits
    if "," in s and ("." not in s or s.rfind(",") > s.rfind(".")):
        head, _, tail = s.rpartition(",")
        if len(tail) in (1, 2):
            s = head.replace(".", "").replace(",", "") + "." + tail
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"cannot parse amount: {text!r}")
    return -d if neg else d


def detect_date_format(samples, month_first=False):
    """Choose the first format that parses every non-empty sample. ISO wins; day-first beats month-first unless month_first."""
    samples = [s.strip() for s in samples if s and s.strip()]
    order = ISO_FORMATS + (MONTH_FIRST + DAY_FIRST if month_first else DAY_FIRST + MONTH_FIRST)
    for fmt in order:
        try:
            for s in samples:
                datetime.strptime(s, fmt)
            return fmt
        except ValueError:
            continue
    raise ValueError("could not determine a single date format for this file; pass --date-format")


def _find(headers, patterns, exclude=()):
    for h in headers:
        low = h.lower().strip()
        if any(re.search(p, low) for p in patterns) and not any(re.search(p, low) for p in exclude):
            return h
    return None


def read_transactions(path, date_format=None, month_first=False, columns=None):
    """Read a bank/ledger CSV into dicts: {row, date, description, amount, raw}. Columns are auto-detected.

    `columns` may override: {"date": "Posted", "description": "Memo", "amount": "Amt"}.
    Separate debit/credit columns are supported (amount = credit - debit).
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    headers = list(rows[0].keys())
    columns = columns or {}
    c_date = columns.get("date") or _find(headers, [r"date"], exclude=[r"due", r"value"]) or _find(headers, [r"date"])
    c_desc = columns.get("description") or _find(headers, [r"desc", r"narrat", r"memo", r"detail", r"payee", r"particulars", r"reference"])
    c_amt = columns.get("amount") or _find(headers, [r"^amount", r"^value", r"^amt", r"^total$"], exclude=[r"balance"])
    c_debit = _find(headers, [r"debit", r"withdraw", r"money out", r"paid out"])
    c_credit = _find(headers, [r"credit", r"deposit", r"money in", r"paid in"])
    if not c_date or not c_desc or not (c_amt or (c_debit and c_credit)):
        raise ValueError(f"{path}: need date, description and amount columns. Found headers: {headers}. Use --map to name them.")
    fmt = date_format or detect_date_format([r[c_date] for r in rows], month_first)
    out = []
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        if not (r.get(c_date) or "").strip():
            continue
        amount = parse_amount(r[c_amt]) if c_amt else parse_amount(r.get(c_credit)) - parse_amount(r.get(c_debit))
        out.append({
            "row": i,
            "date": datetime.strptime(r[c_date].strip(), fmt).date(),
            "description": (r[c_desc] or "").strip(),
            "amount": amount,
            "raw": r,
        })
    return out


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in r.items()})


def parse_map(pairs):
    """--map date=Posted description=Memo amount=Amt  ->  dict"""
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if k and v:
            out[k.strip()] = v.strip()
    return out


def money(d):
    return f"{d:,.2f}"


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


NOISE = {"card", "eft", "pos", "payment", "pmt", "debit", "credit", "direct", "dd", "purchase", "fast", "faster", "receipt", "ref", "the", "ltd", "inc", "llc", "pty", "co", "www", "com",
         "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
         "january", "february", "march", "april", "june", "july", "august", "september", "october", "november", "december"}


def merchant_key(desc):
    """Stable short key for grouping transactions by payee: 'CARD DROPBOX 8812' -> 'dropbox'."""
    words = re.sub(r"[^a-z ]", " ", desc.lower()).split()
    words = [w for w in words if w not in NOISE and len(w) > 1]
    return " ".join(words[:2]) or desc.lower()[:20]
