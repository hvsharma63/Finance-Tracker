"""Deterministic synthetic statements for tests. Contain no real personal data."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

# (date, description, ref, withdrawal, deposit) — opening balance 10,000.00
BANK_ROWS = [
    ("01/04/2026", "UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl/Food", "412345678901", "450.00", ""),
    ("02/04/2026", "NEFT CR-HDFC0000001-ACME PAYROLL SERVICES-SALARY APR", "HDFCN52026040200001", "", "100,000.00"),
    ("03/04/2026", "ATM WDL/SBI ATM ANDHERI", "", "5,000.00", ""),
    ("05/04/2026", "IMPS/P2A/509876543210/OWN SAVINGS TRANSFER", "509876543210", "20,000.00", ""),
    ("05/04/2026", "UPI/DR/412345678999/BIGBASKET/ICIC/bb@icici/Groceries", "412345678999", "2,345.50", ""),
    ("10/04/2026", "BBPS/CREDIT CARD PAYMENT/XX4321", "", "25,000.00", ""),
    ("15/04/2026", "SMS CHARGES QTR", "", "17.70", ""),
    ("30/04/2026", "INT.PD 01-04-2026 TO 30-04-2026", "", "", "123.45"),
]
BANK_OPENING = Decimal("10000.00")


def bank_balances() -> list[Decimal]:
    bal = BANK_OPENING
    out = []
    for _, _, _, w, d in BANK_ROWS:
        bal = bal - Decimal(w.replace(",", "") or 0) + Decimal(d.replace(",", "") or 0)
        out.append(bal)
    return out


BANK_CLOSING = bank_balances()[-1]


def fmt(d: Decimal) -> str:
    return f"{d:,.2f}"


def bank_csv(extra_preamble: bool = True) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    if extra_preamble:
        w.writerow(["Synthetic Bank Ltd - Account Statement"])
        w.writerow(["Account No: XXXXXXXX9876"])
        w.writerow(["Statement Period: 01/04/2026 to 30/04/2026"])
        w.writerow([])
    w.writerow(["Txn Date", "Value Date", "Narration", "Chq./Ref.No.", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
    w.writerow(["", "", "Opening Balance", "", "", "", fmt(BANK_OPENING)])
    for (d, desc, ref, wd, dep), bal in zip(BANK_ROWS, bank_balances(), strict=False):
        w.writerow([d, d, desc, ref, wd, dep, fmt(bal)])
    w.writerow(["", "", "Closing Balance", "", "", "", fmt(BANK_CLOSING)])
    return buf.getvalue().encode()


def bank_xlsx() -> bytes:
    from datetime import datetime

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Statement"
    ws.append(["Synthetic Bank Ltd"])
    ws.append(["Statement period from 01/04/2026 to 30/04/2026"])
    ws.append([])
    ws.append(["Date", "Particulars", "Debit", "Credit", "Balance"])
    for (d, desc, _ref, wd, dep), bal in zip(BANK_ROWS, bank_balances(), strict=False):
        ws.append([
            datetime.strptime(d, "%d/%m/%Y"), desc,
            float(wd.replace(",", "")) if wd else None,
            float(dep.replace(",", "")) if dep else None,
            float(bal),
        ])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def bank_html_xls() -> bytes:
    rows = "".join(
        f"<tr><td>{d}</td><td>{desc}</td><td>{wd}</td><td>{dep}</td><td>{fmt(bal)}</td></tr>"
        for (d, desc, _r, wd, dep), bal in zip(BANK_ROWS, bank_balances(), strict=False)
    )
    return (f"<html><body><table><tr><th>Date</th><th>Description</th><th>Withdrawals</th>"
            f"<th>Deposits</th><th>Balance</th></tr>{rows}</table></body></html>").encode()


def bank_pdf(ruled: bool = False, rows_per_page: int = 5) -> bytes:
    """Multi-page statement PDF. ruled=False draws an unruled table (positional parsing)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    cols = [("Date", 30), ("Narration", 95), ("Withdrawal", 360), ("Deposit", 440), ("Balance", 515)]

    def header(y):
        c.setFont("Helvetica-Bold", 8)
        for label, x in cols:
            if label in ("Withdrawal", "Deposit", "Balance"):
                c.drawRightString(x + 50, y, label)
            else:
                c.drawString(x, y, label)
        if ruled:
            c.line(25, y - 3, 570, y - 3)

    page_rows = [BANK_ROWS[i:i + rows_per_page] for i in range(0, len(BANK_ROWS), rows_per_page)]
    balances = bank_balances()
    k = 0
    for pi, chunk in enumerate(page_rows):
        y = height - 50
        c.setFont("Helvetica", 9)
        if pi == 0:
            c.drawString(30, y, "Synthetic Bank Ltd  Savings Account Statement")
            y -= 14
            c.drawString(30, y, "Account No: XXXXXXXX9876")
            y -= 14
            c.drawString(30, y, "Statement Period: 01/04/2026 to 30/04/2026")
            y -= 14
            c.drawString(30, y, f"Opening Balance: {fmt(BANK_OPENING)}")
            y -= 24
        header(y)
        y -= 16
        c.setFont("Helvetica", 8)
        for d, desc, _ref, wd, dep in chunk:
            cut = desc.rfind("/", 0, 48) + 1 if len(desc) > 48 else len(desc)
            first, rest = desc[:cut], desc[cut:]
            c.drawString(30, y, d)
            c.drawString(95, y, first)
            if wd:
                c.drawRightString(410, y, wd)
            if dep:
                c.drawRightString(490, y, dep)
            c.drawRightString(565, y, fmt(balances[k]))
            if rest:  # wrapped narration on a second line
                y -= 10
                c.drawString(95, y, rest)
            y -= 14
            k += 1
        c.setFont("Helvetica", 7)
        c.drawString(30, 30, f"Page {pi + 1} of {len(page_rows)}  This is a computer generated statement.")
        c.showPage()
    c.setFont("Helvetica", 9)
    c.drawString(30, height - 50, f"Closing Balance: {fmt(BANK_CLOSING)}")
    c.showPage()
    c.save()
    return buf.getvalue()


# Credit card CSV: purchases positive, payments with Cr marker
CARD_ROWS = [
    ("03/04/2026", "AMAZON PAY INDIA", "12,000.00"),
    ("07/04/2026", "ZOMATO BANGALORE", "1,000.00"),
    ("09/04/2026", "IRCTC WEB", "12,000.00"),
    ("12/04/2026", "PAYMENT RECEIVED - THANK YOU", "25,000.00 Cr"),
]


def card_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Synthetic Card Services - Credit Card Statement"])
    w.writerow(["Card No: XXXX XXXX XXXX 4321", "Payment Due Date: 25/04/2026"])
    w.writerow(["Total Amount Due: 0.00", "Minimum Amount Due: 0.00"])
    w.writerow(["Transaction Date", "Transaction Details", "Amount (INR)"])
    for d, desc, amt in CARD_ROWS:
        w.writerow([d, desc, amt])
    return buf.getvalue().encode()
