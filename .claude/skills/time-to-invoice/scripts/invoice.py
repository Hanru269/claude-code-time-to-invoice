#!/usr/bin/env python3
"""Turn a time-tracking CSV into one invoice per client (HTML you can print to PDF) plus a register CSV.

time.csv   : date, client, project, description, hours          (Toggl / Clockify / Harvest exports work after column mapping)
rates.csv  : client, rate, currency[, tax_rate (percent), terms_days, min_charge]
Rounding is applied per entry (--round 0.25 --round-mode up|nearest|none). Money uses exact Decimal maths, half-up to the cent.
A client with time but no rate stops the run with a clear error: nothing is silently skipped.

Usage: python3 invoice.py --time time.csv --rates rates.csv --period 2026-09 [--prefix INV --start 1] [--issue-date 2026-09-30]
                          [--round 0.25] [--round-mode up] [--from-name "Your Name"] [--from-details "Address / tax id"] [--out invoices]
"""
import argparse, csv, html, json, os, re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from csvio import detect_date_format, fail, money, parse_amount, write_csv

CENT = Decimal("0.01")
SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "ZAR": "R", "AUD": "A$", "CAD": "C$", "NZD": "NZ$"}

def q(x): return x.quantize(CENT, rounding=ROUND_HALF_UP)

def round_hours(h, inc, mode):
    if mode == "none" or inc <= 0: return h
    n = h / inc
    n = n.to_integral_value(rounding=ROUND_CEILING if mode == "up" else ROUND_HALF_UP)
    return n * inc

def norm_headers(rows): return [{k.lower().strip().replace(" ", "_"): (v or "").strip() for k, v in r.items()} for r in rows]

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f: return norm_headers(list(csv.DictReader(f)))

def load_time(path, month_first=False):
    rows = read_csv(path)
    need = {"date", "client", "hours"}
    if rows and not need <= set(rows[0]): raise ValueError(f"{path}: need columns date, client, hours (found {sorted(rows[0])})")
    fmt = detect_date_format([r["date"] for r in rows], month_first) if rows else "%Y-%m-%d"
    out = []
    for i, r in enumerate(rows, start=2):
        if not r["date"]: continue
        h = parse_amount(r["hours"])
        if h < 0: raise ValueError(f"{path} row {i}: negative hours")
        out.append({"row": i, "date": datetime.strptime(r["date"], fmt).date(), "client": r["client"], "project": r.get("project", ""), "description": r.get("description", ""), "hours": h})
    return out

def load_rates(path):
    rates = {}
    for r in read_csv(path):
        rates[r["client"].lower()] = {"client": r["client"], "rate": parse_amount(r["rate"]), "currency": (r.get("currency") or "USD").upper(),
                                      "tax_rate": parse_amount(r.get("tax_rate") or "0"), "terms_days": int(r.get("terms_days") or 14), "min_charge": parse_amount(r.get("min_charge") or "0")}
    return rates

def build_invoices(entries, rates, period, inc=Decimal("0.25"), mode="up", prefix="INV", start=1, issue=None):
    y, m = map(int, period.split("-"))
    sel = [e for e in entries if e["date"].year == y and e["date"].month == m]
    missing = sorted({e["client"] for e in sel if e["client"].lower() not in rates})
    if missing: raise ValueError("no rate found in rates.csv for: " + ", ".join(missing))
    issue = issue or (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    invoices, n = [], start
    for client in sorted({e["client"] for e in sel}, key=str.lower):
        r = rates[client.lower()]
        lines = []
        for e in sorted((x for x in sel if x["client"].lower() == client.lower()), key=lambda x: (x["date"], x["row"])):
            h = round_hours(e["hours"], inc, mode)
            lines.append({"date": e["date"], "project": e["project"], "description": e["description"], "raw_hours": e["hours"], "hours": h, "amount": q(h * r["rate"])})
        subtotal = sum((l["amount"] for l in lines), Decimal("0"))
        adj = Decimal("0")
        if r["min_charge"] > subtotal: adj = r["min_charge"] - subtotal; subtotal = r["min_charge"]
        tax = q(subtotal * r["tax_rate"] / 100)
        invoices.append({"number": f"{prefix}-{n:04d}", "client": r["client"], "currency": r["currency"], "rate": r["rate"], "tax_rate": r["tax_rate"], "issue": issue,
                         "due": issue + timedelta(days=r["terms_days"]), "lines": lines, "min_adjustment": adj, "subtotal": subtotal, "tax": tax, "total": subtotal + tax,
                         "hours": sum((l["hours"] for l in lines), Decimal("0"))})
        n += 1
    return invoices

def render_html(inv, from_name, from_details):
    sym = SYMBOL.get(inv["currency"], inv["currency"] + " ")
    e = html.escape
    rows = "".join(f"<tr><td>{l['date']}</td><td>{e(l['project'])}</td><td>{e(l['description'])}</td><td class=n>{l['hours']:.2f}</td><td class=n>{sym}{money(l['amount'])}</td></tr>" for l in inv["lines"])
    if inv["min_adjustment"]: rows += f"<tr><td colspan=4>Minimum charge adjustment</td><td class=n>{sym}{money(inv['min_adjustment'])}</td></tr>"
    tax_row = f"<tr><td colspan=4>Tax ({inv['tax_rate'].normalize():f}%)</td><td class=n>{sym}{money(inv['tax'])}</td></tr>" if inv["tax_rate"] else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Invoice {e(inv['number'])}</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 24px;color:#111}}h1{{margin:0 0 4px}}.meta{{display:flex;justify-content:space-between;gap:24px;margin:24px 0}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}.n{{text-align:right;white-space:nowrap}}
tfoot td{{font-weight:600;border-bottom:0}}.total td{{font-size:1.15em;border-top:2px solid #111}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>Invoice {e(inv['number'])}</h1><div class="meta"><div><strong>From</strong><br>{e(from_name)}<br>{e(from_details).replace(chr(10), '<br>')}</div>
<div><strong>Bill to</strong><br>{e(inv['client'])}</div><div>Issued {inv['issue']}<br><strong>Due {inv['due']}</strong><br>Currency {inv['currency']}</div></div>
<table><thead><tr><th>Date</th><th>Project</th><th>Description</th><th class=n>Hours</th><th class=n>Amount</th></tr></thead><tbody>{rows}</tbody>
<tfoot><tr><td colspan=4>Subtotal ({inv['hours']:.2f} h at {sym}{money(inv['rate'])}/h)</td><td class=n>{sym}{money(inv['subtotal'])}</td></tr>{tax_row}
<tr class="total"><td colspan=4>Total due</td><td class=n>{sym}{money(inv['total'])}</td></tr></tfoot></table></body></html>"""

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--time", required=True); ap.add_argument("--rates", required=True); ap.add_argument("--period", required=True, help="YYYY-MM")
    ap.add_argument("--prefix", default="INV"); ap.add_argument("--start", type=int, default=1); ap.add_argument("--issue-date")
    ap.add_argument("--round", default="0.25"); ap.add_argument("--round-mode", choices=["up", "nearest", "none"], default="up")
    ap.add_argument("--from-name", default="Your Name"); ap.add_argument("--from-details", default=""); ap.add_argument("--out", default="invoices"); ap.add_argument("--month-first", action="store_true")
    a = ap.parse_args()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}", a.period): raise ValueError("--period must look like 2026-09")
        issue = datetime.strptime(a.issue_date, "%Y-%m-%d").date() if a.issue_date else None
        invs = build_invoices(load_time(a.time, a.month_first), load_rates(a.rates), a.period, Decimal(a.round), a.round_mode, a.prefix, a.start, issue)
    except (ValueError, OSError, KeyError) as e:
        fail(str(e))
    os.makedirs(a.out, exist_ok=True)
    for inv in invs:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", inv["client"]).strip("-")
        with open(os.path.join(a.out, f"{inv['number']}_{slug}.html"), "w", encoding="utf-8") as f: f.write(render_html(inv, a.from_name, a.from_details))
    write_csv(os.path.join(a.out, "register.csv"), [{"invoice": i["number"], "customer": i["client"], "issue_date": i["issue"], "due_date": i["due"], "amount": i["total"], "paid": "0", "currency": i["currency"]} for i in invs],
              ["invoice", "customer", "issue_date", "due_date", "amount", "paid", "currency"])
    for i in invs: print(f"{i['number']}  {i['client']:<22} {i['hours']:>7.2f} h  {i['currency']} {money(i['subtotal']):>10} + tax {money(i['tax']):>8} = {money(i['total']):>10}   due {i['due']}")
    print(f"{len(invs)} invoices written to {a.out}/ (open the .html files and print to PDF). register.csv is ready for the client-chasers skill.")

if __name__ == "__main__":
    main()
