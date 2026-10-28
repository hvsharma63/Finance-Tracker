"""Synthetic PDFs reproducing the layouts of supported institution statements.

Made-up names, numbers and amounts. Each generator reproduces the layout features the parser
depends on (column positions, wrapping, Dr/Cr style, colours, decoy tables) and returns
(pdf_bytes, expected) where expected lists every row the parser must produce.
"""

from __future__ import annotations

import io
from decimal import Decimal as D

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.services.imports.normalization import join_continuation


def joined(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        out = join_continuation(out, ln)
    return out


def _canvas(size=A4):
    buf = io.BytesIO()
    return buf, canvas.Canvas(buf, pagesize=size)


def _y(c, top):  # convert pdfplumber-style "top" to reportlab baseline
    return c._pagesize[1] - top - 7


def _txt(c, x, top, s, font="Helvetica", size=8, rgb=(0, 0, 0)):
    c.setFont(font, size)
    c.setFillColorRGB(*rgb)
    c.drawString(x, _y(c, top), s)
    c.setFillColorRGB(0, 0, 0)


def _rtxt(c, x1, top, s, font="Helvetica", size=8, rgb=(0, 0, 0)):
    c.setFont(font, size)
    c.setFillColorRGB(*rgb)
    c.drawRightString(x1, _y(c, top), s)
    c.setFillColorRGB(0, 0, 0)


def fmt(d: D) -> str:
    return f"{d:,.2f}"


# --------------------------------------------------------------------------- Axis savings

AXIS_SAV_ROWS = [  # date, narration lines, withdrawal, deposit
    ("01-09-2026", ["UPI/P2A/111122223333/TEST PAYEE ONE", "Payeeline/aadhar/Test Bank"], D("700.00"), None),
    ("03-09-2026", ["UPI/P2A/222233334444/SALARY CO", "M/UTIB/UPI/"], None, D("100000.00")),
    ("03-09-2026", ["PPR000011112222"], D("38437.00"), None),
    ("04-09-2026", ["IMPS/P2A/333344445555/GrowwInv/CNA", "/TESTREF1/9100000000000000000"], None, D("1422.78")),
    ("10-09-2026", ["PHR000011112222_EMI_10-09-2026_AB", "C TEST NAME"], D("7915.00"), None),
]
AXIS_SAV_OPEN = D("50037.68")


def axis_savings_pdf():
    buf, c = _canvas((595, 840))
    _txt(c, 30, 40, "Axis Bank Relationship summary as on date 30-09-2026")
    c.showPage()
    _txt(c, 28, 168, "Detailed Statement for a/c no. XXXXXXXXXXX1234 between 01-09-2026 to 30-09-2026")
    _txt(c, 522, 203, "Other")
    for x, s in [(34, "Txn"), (54, "Date"), (155, "Transaction"), (288, "Withdrawals"), (363, "Deposits"), (437, "Balance")]:
        _txt(c, x, 209, s, "Helvetica-Bold", 9)
    _txt(c, 507, 215, "Information", "Helvetica-Bold", 9)
    wr, dr, br = 288 + stringWidth("Withdrawals", "Helvetica-Bold", 9), 363 + stringWidth("Deposits", "Helvetica-Bold", 9), \
        437 + stringWidth("Balance", "Helvetica-Bold", 9)
    _txt(c, 86, 232, "Opening Balance")
    _rtxt(c, br + 12, 232, fmt(AXIS_SAV_OPEN))
    top = 249
    bal = AXIS_SAV_OPEN
    for d, lines, w, dep in AXIS_SAV_ROWS:
        _txt(c, 27, top, d)
        for k, ln in enumerate(lines):
            _txt(c, 86, top + 12 * k, ln)
        if w:
            _rtxt(c, wr, top, fmt(w))
        if dep:
            _rtxt(c, dr + 6, top, fmt(dep))
        bal = bal - (w or 0) + (dep or 0)
        top += 12 * len(lines) + 1
    _txt(c, 86, top, "Closing Balance")
    _rtxt(c, br + 12, top, fmt(bal))
    c.showPage()
    _txt(c, 30, 40, "Legends used in the Statement  CWDR Cash withdrawal through ATM  01-01-2026 example 500.00")
    c.showPage()
    c.save()
    expected = {
        "parser": "axis_savings_pdf", "opening": AXIS_SAV_OPEN, "closing": bal, "account_hint": "XXXXXXXXXXX1234",
        "rows": [(d, joined(lines), -w if w else dep) for d, lines, w, dep in AXIS_SAV_ROWS],
    }
    return buf.getvalue(), expected


# --------------------------------------------------------------------------- SBI savings

SBI_ROWS = [  # date, description lines, credit, debit
    ("01-09-26", ["UPI/DR/100000000001/CARDPAY/UTIB/cardpay@/paym"], None, D("13957.77")),
    ("01-09-26", ["UPI/DR/100000000002/Test Shop/YESB/Q000000001/Payme"], None, D("645.00")),
    ("02-09-26", ["UPI/DR/100000000003/TEST", "GOLD/YESB/TESTGOLD@y/Gold"], None, D("500.00")),
    ("03-09-26", ["UPI/CR/100000000004/TESTNAME/BARB/test37./UPI"], D("32000.00"), None),
    ("25-09-26", ["Salary of Sep 2026"], D("84759.00"), None),
]
SBI_OPEN = D("43576.92")


def sbi_savings_pdf():
    buf, c = _canvas((595, 842))
    _txt(c, 30, 30, "Visithttps://sbi.co.in Customer CareNumber: 1800 1234")
    _txt(c, 30, 60, "TRANSACTION OVERVIEW")
    _txt(c, 30, 75, "SAVING ACCOUNT")
    _txt(c, 30, 87, "XXXXXXX5678")
    xs = [20, 70, 300, 360, 430, 500, 575]
    heads = ["Date", "Transaction Reference", "Ref.No./Chq.No.", "Credit", "Debit", "Balance"]
    rows = [heads, ["Your Opening", "Balance on 01-09-26:", "", "", "", fmt(SBI_OPEN).replace(",", "")]]
    bal = SBI_OPEN
    for d, lines, cr, dr in SBI_ROWS:
        bal = bal + (cr or 0) - (dr or 0)
        rows.append([d, lines, "-", str(cr or 0), str(dr or 0), f"{bal:.2f}"])
    rows.append(["Your Closing Balance on 30-09-26:", "", f"{bal:.2f}", "", "", ""])
    top = 110
    c.setLineWidth(0.5)
    for r in rows:
        h = 24 if any(isinstance(x, list) and len(x) > 1 for x in r) else 16
        y0 = c._pagesize[1] - top
        c.line(xs[0], y0, xs[-1], y0)
        for i, cell in enumerate(r):
            lines = cell if isinstance(cell, list) else [cell]
            for k, ln in enumerate(lines):
                _txt(c, xs[i] + 2, top + 4 + 9 * k, ln, "Helvetica-Bold" if r is heads else "Helvetica", 7)
        top += h
    y_end = c._pagesize[1] - top
    c.line(xs[0], y_end, xs[-1], y_end)
    for x in xs:
        c.line(x, c._pagesize[1] - 110, x, y_end)
    c.showPage()
    c.save()
    expected = {"parser": "sbi_savings_pdf", "opening": SBI_OPEN, "closing": bal, "account_hint": "XXXXXXX5678",
                "rows": [(d, joined(lines), cr if cr else -dr) for d, lines, cr, dr in SBI_ROWS]}
    return buf.getvalue(), expected


# --------------------------------------------------------------------------- Axis credit card

AXIS_CC_ROWS = [  # date, details, category, amount, marker
    ("13/09/2026", "UPI/TEST STORE/PAYTM.S24P6J6@PTY/9000000000", "RETAIL STORES", D("150.00"), "Dr"),
    ("26/09/2026", "GST ON FUEL SURCHARGE", "", D("5.40"), "Dr"),
    ("27/09/2026", "BBPS PAYMENT RECEIVED - DP0000000000000000", "", D("4165.45"), "Cr"),
    ("27/09/2026", "UPI/LENSKART/LENSKARTOFFLINE@YBL/9000000000-4@Y", "CLOTH STORES", D("6599.00"), "Dr"),
]


def axis_credit_card_pdf():
    buf, c = _canvas((612, 1080))
    _txt(c, 30, 30, "Neo Rupay Credit Card Statement")
    _txt(c, 30, 120, "PAYMENT SUMMARY")
    _txt(c, 30, 140, "Total Payment Due Minimum Payment Due Statement Period Payment Due Date Statement Generation Date")
    _txt(c, 30, 152, "2,589.95 Dr 363.00 Dr 12/09/2026 - 10/10/2026 30/10/2026 10/10/2026")
    _txt(c, 30, 175, "600000******1111 222,000.00 206,326.99 0.00")
    _txt(c, 30, 195, "Previous Balance - Payments - Credits + Purchase + Cash Advance + Other Debit&Charges =Total Payment Due")
    _txt(c, 30, 207, "4,165.45 Dr 4,165.45 0.00 6,749.00 0.00 5.40 6,754.40 Dr")
    for x, s in [(50, "DATE"), (172, "TRANSACTION"), (233, "DETAILS"), (370, "MERCHANT"), (418, "CATEGORY"), (510, "AMOUNT"), (548, "(Rs.)")]:
        _txt(c, x, 312, s, "Helvetica-Bold", 7)
    _txt(c, 35, 322, "Card No: 600000******1111 Name TEST CARDHOLDER")
    top = 333
    for d, det, cat, amt, mk in AXIS_CC_ROWS:
        _txt(c, 35, top, d)
        _txt(c, 90, top, det, size=7)
        if cat:
            _txt(c, 360, top, cat, size=7)
        _rtxt(c, 572, top, fmt(amt))
        _txt(c, 574, top, mk)
        top += 10
    _txt(c, 200, top + 10, "**** End of Statement ****")
    c.showPage()
    _txt(c, 30, 40, "Axis Bank Visa Privilege Credit Card Statement  axis.bank.in")
    _txt(c, 30, 60, "Txn Date Type Cr/Db MAD Contribution Amount")
    _txt(c, 30, 72, "25/09/2026 Purchase Db 2% 5000.00 Dr")  # decoy example table
    c.showPage()
    c.save()
    expected = {"parser": "axis_credit_card_pdf", "opening": D("-4165.45"), "closing": D("-6754.40"),
                "account_hint": "XX1111",
                "rows": [(d, det, -a if mk == "Dr" else a) for d, det, _c, a, mk in AXIS_CC_ROWS]}
    return buf.getvalue(), expected


# --------------------------------------------------------------------------- IDFC FIRST credit card

def idfc_credit_card_pdf():
    buf, c = _canvas((594, 842))
    _txt(c, 30, 30, "Credit Card Statement  IDFC FIRST Bank  (FIRST Select XX2222)")
    _txt(c, 30, 45, "25/Sep/2026 - 24/Oct/2026")
    _txt(c, 30, 70, "Opening Balance r7,096.72")
    _txt(c, 30, 82, "Purchases + r600.24")
    _txt(c, 30, 94, "EMI & Other Debits + r2,863.27")
    _txt(c, 30, 106, "Payments & Refunds - r7,616.22")
    _txt(c, 30, 118, "Total Amount Due = r2,944.01 DR")
    c.showPage()
    red = (0.64, 0.09, 0.15)
    _txt(c, 34, 162, "YOUR TRANSACTIONS", "Helvetica-Bold", 9, red)
    for x, s in [(34, "Transaction"), (151, "Transaction"), (197, "Details"), (323, "EMI"), (390, "FX"), (513, "Amount")]:
        _txt(c, x, 192, s, "Helvetica-Bold", 7)
    for x, s in [(34, "Date"), (323, "Eligibility"), (390, "Transactions"), (513, "(In INR)")]:
        _txt(c, x, 200, s, "Helvetica-Bold", 8)
    _txt(c, 35, 216, "Card Number: XXXX 2222", "Helvetica-Bold", 8, red)
    _txt(c, 35, 231, "Purchases, EMIs & Other Debits", "Helvetica-Bold", 8, red)

    def row(top, date, amt, marker, above=None, same=None, below=None):
        if above:
            _txt(c, 152, top - 9, above)
        _txt(c, 35, top, date)
        if same:
            _txt(c, 152, top, same)
        if below:
            _txt(c, 152, top + 9, below)
        _rtxt(c, 545, top, amt)
        _txt(c, 547, top, marker)

    row(255, "14 Oct 26", "74.50", "DR", "AMAZON PAY INDIA PRIVA -", "Interest Amount Amortization -", "<11/12>")
    row(279, "14 Oct 26", "13.41", "DR", same="IGST")
    row(303, "14 Oct 26", "2,775.36", "DR", "AMAZON PAY INDIA PRIVA -", "Principal Amount Amortization -", "<11/12>")
    row(327, "20 Oct 26", "600.24", "DR", same="ORBGEN TECHNOLOGIES, GURGAON")
    _txt(c, 35, 351, "Payments & Other Credits", "Helvetica-Bold", 8, red)
    row(371, "27 Sep 26", "7,096.72", "CR", "BillDesk BBPS CC", None, "Payment/DP0000000TESTTEST")
    row(401, "23 Oct 26", "519.50", "CR", "ORBGEN TECHNOLOGIES - Credit", "Adjustment for Rewards", "Redemption")
    _txt(c, 34, 434, "ACTIVE EMI DETAILS", "Helvetica-Bold", 9, red)
    _txt(c, 34, 450, "24,050.00 1,134.72 16% 25,184.72 20 JUN 26 20 NOV 26 6 4,197.45 1 4,197.45")
    c.showPage()
    c.save()
    expected = {"parser": "idfc_first_credit_card_pdf", "opening": D("-7096.72"), "closing": D("-2944.01"),
                "account_hint": "XX2222", "rows": [
                    ("14-10-2026", "AMAZON PAY INDIA PRIVA - Interest Amount Amortization - <11/12>", D("-74.50")),
                    ("14-10-2026", "IGST", D("-13.41")),
                    ("14-10-2026", "AMAZON PAY INDIA PRIVA - Principal Amount Amortization - <11/12>", D("-2775.36")),
                    ("20-10-2026", "ORBGEN TECHNOLOGIES, GURGAON", D("-600.24")),
                    ("27-09-2026", "BillDesk BBPS CC Payment/DP0000000TESTTEST", D("7096.72")),
                    ("23-10-2026", "ORBGEN TECHNOLOGIES - Credit Adjustment for Rewards Redemption", D("519.50")),
                ]}
    return buf.getvalue(), expected


# --------------------------------------------------------------------------- RBL credit card

def rbl_credit_card_pdf(credit_colour=(0, 0.501, 0)):
    buf, c = _canvas((612, 1008))
    _txt(c, 30, 30, "Hello, TEST CARDHOLDER   RBL Bank Credit Card  rbl.bank.in")
    _txt(c, 30, 150, "ACCOUNT SUMMARY (IN INR)")
    for x, s in [(224, "Date"), (296, "Description"), (539, "Amount")]:
        _txt(c, x, 168, s, "Helvetica-Bold", 10)
    left = ["Card Number XXXXXXXXXXXXXX33", "Total Amount Due PAY NOW 10,686.00", "Min. Amt. Due 535.00",
            "Payment Due Date 11 Nov 2026", "Last Bill Amount 10,347.12", "- Payments & Credits 10,348.00",
            "+ New Debits 10,686.17", "- Transferred to EMI 0.00", "+ Monthly EMI Debits 0.00",
            "+ Fees & Charges 0.00", "+ Goods & Services Tax 0.00", "Statement Period 23-09-2026 to 22-10-2026"]
    for i, s in enumerate(left):
        _txt(c, 30, 189 + 14 * i, s, size=8)
    rows = [("27 Sep 2026", "PAYMENT RECEIVED - BBPS", "10,348.00", credit_colour),
            ("27 Sep 2026", "PAY*BHARATKOSH GOV IN GURGAON HAR", "727.29", (0, 0, 0)),
            ("27 Sep 2026", "BP-MC-CC1790000000000-GUJARAT", "978.00", (0, 0, 0)),
            ("4 Oct 2026", "MSW*TEST PETROLEUM Rajkot IND", "6,171.98", (0, 0, 0)),
            ("20 Oct 2026", "BP-MB-CC600000000-PASCHIM", "2,808.90", (0, 0, 0)),
            ("22 Oct 2026", "Goods & Service Tax", "0.00", (0, 0, 0))]
    top = 189
    for d, desc, amt, col in rows:
        _txt(c, 224, top, d, size=9)
        _txt(c, 296, top, desc, size=9)
        _rtxt(c, 570, top, amt, size=9, rgb=col)
        top += 20
    _txt(c, 537, top - 4, "Eligible for EMI", size=7)
    _txt(c, 330, top + 30, "Get 15% OFF Make payment")
    c.showPage()
    _txt(c, 30, 40, "Sample Transaction Date Transaction Amount")
    _txt(c, 30, 52, "12-Dec-18 Purchase of Groceries 6000.00")
    c.showPage()
    c.save()
    expected = {"parser": "rbl_credit_card_pdf", "opening": D("-10347.12"), "closing": D("-10685.29"),
                "account_hint": "XX33", "rows": [
                    ("27-09-2026", "PAYMENT RECEIVED - BBPS", D("10348.00")),
                    ("27-09-2026", "PAY*BHARATKOSH GOV IN GURGAON HAR", D("-727.29")),
                    ("27-09-2026", "BP-MC-CC1790000000000-GUJARAT", D("-978.00")),
                    ("04-10-2026", "MSW*TEST PETROLEUM Rajkot IND", D("-6171.98")),
                    ("20-10-2026", "BP-MB-CC600000000-PASCHIM", D("-2808.90")),
                ]}
    return buf.getvalue(), expected
