"""Freelancer Ops Kit tests. Run: python3 -m unittest discover -s tests -v   (expected numbers are recomputed independently or hand-derived)"""
import csv, importlib, math, os, subprocess, sys, tempfile, unittest
from datetime import date
from decimal import Decimal as D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "pack") if os.path.isdir(os.path.join(ROOT, "pack")) else ROOT
SD = os.path.join(PACK, "sample-data"); SK = os.path.join(PACK, ".claude", "skills")
def load(skill, mod):
    p = os.path.join(SK, skill, "scripts")
    if p not in sys.path: sys.path.insert(0, p)
    sys.modules.pop("csvio", None); return importlib.import_module(mod)
def run(skill, script, *args): return subprocess.run([sys.executable, os.path.join(SK, skill, "scripts", script), *args], capture_output=True, text=True)
def rows(p):
    with open(p, newline="") as f: return list(csv.DictReader(f))

class TestInvoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.r = run("time-to-invoice", "invoice.py", "--time", f"{SD}/time_2026-07_08.csv", "--rates", f"{SD}/rates.csv", "--period", "2026-08", "--out", cls.d, "--start", "42", "--from-name", "Juniper & Co")
        cls.reg = {x["customer"]: x for x in rows(f"{cls.d}/register.csv")} if cls.r.returncode == 0 else {}
    def test_ran(self): self.assertEqual(self.r.returncode, 0, self.r.stderr)
    def test_only_billed_clients_and_numbering(self):
        self.assertEqual(sorted(self.reg), ["Acme Ltd", "Brighton Cafe", "Harbour Co"])   # Lumen has a rate but no time -> no invoice
        self.assertEqual(sorted(x["invoice"] for x in self.reg.values()), ["INV-0042", "INV-0043", "INV-0044"])
    def test_acme_rounding_up_no_tax(self):
        hrs = sum(D(x) for x in ("6.25", "4.5", "3.0", "0.5", "6.0", "3.0"))            # 6.1->6.25, 4.4->4.5, 0.4->0.5, 5.9->6.0, 2.83->3.0
        self.assertEqual(D(self.reg["Acme Ltd"]["amount"]), hrs * 95); self.assertEqual(self.reg["Acme Ltd"]["due_date"], "2026-09-14")
    def test_minimum_charge_and_tax(self):
        # 1.6h -> 1.75h x 70 = 122.50 < 150 minimum -> subtotal 150, 20% tax = 30 -> 180.00 ; terms 30 days
        self.assertEqual(D(self.reg["Brighton Cafe"]["amount"]), D("180.00")); self.assertEqual(self.reg["Brighton Cafe"]["due_date"], "2026-09-30")
    def test_harbour_vat(self):
        sub = D("19.5") * 110; self.assertEqual(D(self.reg["Harbour Co"]["amount"]), sub + (sub * D("0.21")).quantize(D("0.01")))
    def test_august_entries_excluded(self):
        self.assertEqual(D(self.reg["Acme Ltd"]["amount"]), D("23.25") * 95)
    def test_html_written_and_escaped(self):
        h = [f for f in os.listdir(self.d) if f.endswith(".html")]; self.assertEqual(len(h), 3)
        txt = open(os.path.join(self.d, h[0])).read(); self.assertIn("Juniper &amp; Co", txt); self.assertNotIn("Juniper & Co", txt)
    def test_missing_rate_stops_with_clear_error(self):
        with tempfile.TemporaryDirectory() as t:
            open(f"{t}/time.csv", "w").write("date,client,project,description,hours\n2026-08-01,Ghost Ltd,X,y,2\n"); open(f"{t}/rates.csv", "w").write("client,rate,currency\nOther,50,USD\n")
            r = run("time-to-invoice", "invoice.py", "--time", f"{t}/time.csv", "--rates", f"{t}/rates.csv", "--period", "2026-08", "--out", f"{t}/o")
            self.assertEqual(r.returncode, 2); self.assertIn("Ghost Ltd", r.stderr)
    def test_rounding_modes(self):
        inv = load("time-to-invoice", "invoice")
        self.assertEqual([inv.round_hours(D(x), D("0.25"), "up") for x in ("0.01", "0.25", "0.26", "1.0")], [D("0.25"), D("0.25"), D("0.5"), D("1.0")])
        self.assertEqual([inv.round_hours(D(x), D("0.25"), "nearest") for x in ("0.1", "0.13", "0.37", "0.38")], [D("0"), D("0.25"), D("0.25"), D("0.5")])
        self.assertEqual(inv.round_hours(D("0.13"), D("0.25"), "none"), D("0.13"))
    def test_half_cent_rounds_up(self):
        inv = load("time-to-invoice", "invoice"); self.assertEqual(inv.q(D("2.675")), D("2.68"))
    def test_december_period_issue_date(self):
        inv = load("time-to-invoice", "invoice")
        e = [{"row": 2, "date": date(2026, 12, 3), "client": "A", "project": "", "description": "", "hours": D("1")}]
        out = inv.build_invoices(e, {"a": {"client": "A", "rate": D("10"), "currency": "USD", "tax_rate": D("0"), "terms_days": 14, "min_charge": D("0")}}, "2026-12")
        self.assertEqual(out[0]["issue"], date(2026, 12, 31)); self.assertEqual(out[0]["due"], date(2027, 1, 14))

if __name__ == "__main__":
    unittest.main()
