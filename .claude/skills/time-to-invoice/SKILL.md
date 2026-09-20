---
name: time-to-invoice
description: Turn a time-tracking CSV (Toggl, Clockify, Harvest, spreadsheet) into one invoice per client for a month, with rounding, tax, minimum charges and a register CSV. Use when the user asks to invoice, bill a client, or prepare month-end invoices from tracked hours.
---

# Time to invoice

Never edit the user's original files. Copy inputs to `work/`; invoices go to `reports/invoices/`.

1. **Inspect** `head -5` of the time file and the rates file. Confirm with the user: the billing month, rounding policy (default: round each entry UP to 0.25 h; say so), each client's rate, currency, tax/VAT rate, payment terms and any minimum charge. Ask for anything missing - never assume a rate or tax rate. Rates file columns: `client, rate, currency, tax_rate, terms_days, min_charge`.
2. **Run** (the script does all the arithmetic - never total hours or amounts yourself):
   `python3 .claude/skills/time-to-invoice/scripts/invoice.py --time work/time.csv --rates work/rates.csv --period YYYY-MM --prefix INV --start N --from-name "..." --from-details "..." --out reports/invoices`
   Ask for the next invoice number (`--start`) so numbering continues from the last invoice.
3. **Report** each invoice line from the script's printed summary: hours, subtotal, tax, total, due date. If the script stops on a client with no rate, ask the user for it and re-run.
4. **Tell the user** the HTML files can be opened in a browser and printed to PDF, and that `register.csv` feeds the `client-chasers` and `income-dashboard` skills.
5. **Flag, do not fix:** entries with 0 hours, unusual long entries (> 10 h in a day), or clients with time but no matching project name. Ask before changing anything.
Invoices are drafts until the user sends them. Do not claim anything was sent. Tax treatment is the user's decision; you only apply the rate they give you.
