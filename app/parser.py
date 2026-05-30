"""Invoice text parser — extracts structured fields from raw OCR text.

Pure computation. No external APIs. Handles common invoice formats.
Panel-reviewed: fixes for currency order, date validation, arithmetic
reconciliation, confidence ordering, and total/subtotal disambiguation.
"""

from __future__ import annotations

import re
from datetime import datetime

from .cache import cache
from .models import InvoiceFields, LineItem


# ── Text preprocessing ────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Normalize OCR artifacts — preserve column spacing for line items."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Normalize tabs to spaces but preserve multi-space column alignment
    text = text.replace("\t", "    ")
    return text.strip()


# ── Date patterns (YMD first — unambiguous) ───────────────────────

_DATE_PATTERNS = [
    (r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", "ymd"),
    (r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", "mdy"),
    (r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b", "dmy_text"),
    (r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})\b", "mdy_text"),
]

_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_date(text: str) -> str | None:
    """Extract and normalize a date string to YYYY-MM-DD. Uses datetime() for validation."""
    for pattern, fmt in _DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        try:
            if fmt == "mdy":
                month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif fmt == "ymd":
                year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif fmt == "dmy_text":
                day = int(m.group(1))
                month = _MONTH_MAP.get(m.group(2).lower()[:3], 0)
                year = int(m.group(3))
            elif fmt == "mdy_text":
                month = _MONTH_MAP.get(m.group(1).lower()[:3], 0)
                day = int(m.group(2))
                year = int(m.group(3))
            else:
                continue
            # FIX: Use datetime constructor to validate (catches Feb 31 etc)
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            continue
    return None


# ── Currency detection (FIX: longer symbols first) ────────────────

_CURRENCY_SYMBOLS = [
    ("CA$", "CAD"), ("A$", "AUD"), ("US$", "USD"),
    ("CHF", "CHF"), ("€", "EUR"), ("£", "GBP"), ("¥", "JPY"),
    ("$", "USD"),  # Must be last — shortest match
]

_CURRENCY_CODES = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "INR", "BRL", "MXN"}


def _detect_currency(text: str) -> str:
    """Detect currency. Checks longer symbols first to avoid CA$ → USD."""
    for symbol, code in _CURRENCY_SYMBOLS:
        if symbol in text:
            return code
    upper = text.upper()
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", upper):
            return code
    return "USD"


# ── Amount extraction ─────────────────────────────────────────────

def _extract_amount(text: str, label_pattern: str) -> float | None:
    """Extract a dollar amount near a label. Handles parens, strict decimal."""
    pattern = rf"{label_pattern}\s*(?:\([^)]*\))?\s*[:\s]*[\$€£]?\s*(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?|\d+(?:\.\d{{1,2}})?)"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            if val >= 0:
                return val
        except ValueError:
            pass
    return None


def _extract_tax(text: str, subtotal: float | None) -> float | None:
    """Extract tax — prefers direct amount, falls back to percentage calc."""
    # Check for percentage format: "Tax (10%)" or "GST 5%" or "VAT: 8.5%"
    percent_pattern = r"\b(?:tax|vat|gst|hst)\s*(?:\(?\s*(\d+(?:\.\d+)?)\s*%)"
    m = re.search(percent_pattern, text, re.IGNORECASE)
    percent_val = None
    if m and subtotal:
        try:
            percent_val = round(subtotal * float(m.group(1)) / 100, 2)
        except ValueError:
            pass

    # If percentage found AND no separate dollar amount exists, use computed
    if percent_val is not None:
        # Check if there's ALSO a dollar amount (e.g. "Tax (8.5%): $628.91")
        dollar_pattern = r"\b(?:tax|vat|gst|hst)\s*(?:\([^)]*\))?\s*[:\s]*[\$€£]\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"
        dm = re.search(dollar_pattern, text, re.IGNORECASE)
        if dm:
            try:
                return float(dm.group(1).replace(",", ""))
            except ValueError:
                pass
        return percent_val

    # No percentage — try direct amount
    direct = _extract_amount(text, r"\b(?:tax|vat|gst|hst|sales\s*tax)\b")
    return direct


def _extract_invoice_number(text: str) -> str | None:
    patterns = [
        r"\binvoice\s+(?:no|num|number)\s*[.:#]?\s*([A-Za-z0-9][\w\-/]{1,25})",
        r"\binvoice\s*#\s*:?\s*([A-Za-z0-9][\w\-/]{1,25})",
        r"\binvoice\s*:\s*([A-Za-z0-9][\w\-/]{1,25})",
        r"\binv\b\s*#?\s*:?\s*([A-Za-z0-9][\w\-/]{1,25})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_po_number(text: str) -> str | None:
    patterns = [
        r"\b(?:purchase\s+order)\s*(?:#|number|num|no)?\s*[.:]?\s*([A-Za-z0-9][\w\-]{1,20})",
        r"\bP\.?O\.?\s*(?:#|number|num|no)?\s*[.:]?\s*([A-Za-z0-9][\w\-]{1,20})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


_COMPANY_INDICATORS = re.compile(
    r"\b(inc\.?|llc|ltd\.?|corp\.?|corporation|gmbh|s\.?a\.?|plc|llp|co\.?)\b",
    re.IGNORECASE,
)


def _extract_vendor(text: str) -> str | None:
    # Try labeled vendor first
    m = re.search(r"(?:from|bill\s*from|sold\s*by|vendor|supplier)\s*[:\n]\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        if len(name) >= 2:
            return name[:100]

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Prefer lines with company indicators (Inc, LLC, etc)
    for line in lines[:8]:
        if _COMPANY_INDICATORS.search(line) and len(line) >= 3:
            return line[:100]

    # Fallback: first non-header line
    for line in lines[:5]:
        if re.match(r"^(invoice|date|bill|total|amount|from|to|ship|page|\d)", line, re.IGNORECASE):
            continue
        if len(line) >= 3 and not line.replace(" ", "").isdigit() and re.search(r"[A-Za-z]", line):
            return line[:100]
    return None


def _extract_dates(text: str) -> tuple[str | None, str | None]:
    invoice_date = None
    due_date = None

    for label, target in [
        (r"(?:invoice\s*date|date\s*of\s*invoice|issued?\s*date|date\s*issued)", "invoice"),
        (r"(?:due\s*date|payment\s*due|date\s*due|pay\s*by)", "due"),
    ]:
        m = re.search(rf"{label}\s*[:\s]*([^\n\r]{{5,40}})", text, re.IGNORECASE)
        if m:
            parsed = _parse_date(m.group(1))
            if parsed:
                if target == "invoice":
                    invoice_date = parsed
                else:
                    due_date = parsed

    if not invoice_date:
        for pattern, fmt in _DATE_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                invoice_date = _parse_date(m.group(0))
                break

    return invoice_date, due_date


def _extract_line_items(text: str) -> list[LineItem]:
    items: list[LineItem] = []

    # Full pattern: description + qty + unit price + amount
    line_pattern = re.compile(
        r"^(.{3,80}?)(?:\t|\s{2,})"
        r"(\d+(?:\.\d+)?)\s+"
        r"[\$€£]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)\s+"
        r"[\$€£]?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)$",
        re.MULTILINE,
    )

    for m in line_pattern.finditer(text):
        desc = m.group(1).strip()
        if re.match(r"^(item|description|qty|quantity|price|amount|total|sub)\s*$", desc, re.IGNORECASE):
            continue
        try:
            items.append(LineItem(
                description=desc,
                quantity=float(m.group(2)),
                unit_price=float(m.group(3).replace(",", "")),
                amount=float(m.group(4).replace(",", "")),
            ))
        except ValueError:
            continue

    # Fallback: description + single amount
    if not items:
        simple_pattern = re.compile(
            r"^(.{5,80}?)(?:\t|\s{2,})[\$€£]?\s*(\d+(?:,\d{3})*\.\d{2})$",
            re.MULTILINE,
        )
        for m in simple_pattern.finditer(text):
            desc = m.group(1).strip()
            if re.match(r"^(item|description|total|sub|tax|balance|amount|due|paid)\s*$", desc, re.IGNORECASE):
                continue
            try:
                items.append(LineItem(
                    description=desc,
                    quantity=None,
                    unit_price=None,
                    amount=float(m.group(2).replace(",", "")),
                ))
            except ValueError:
                continue

    return items[:50]


# ── Confidence with arithmetic validation ─────────────────────────

def _compute_confidence(fields: InvoiceFields) -> float:
    score = 0.0
    checks = [
        (fields.vendor, 15),
        (fields.invoice_number, 15),
        (fields.invoice_date, 15),
        (fields.due_date, 10),
        (fields.total, 20),
        (fields.subtotal, 10),
        (fields.tax is not None, 5),
        (fields.po_number, 5),
        (len(fields.line_items) > 0, 5),
    ]
    for val, weight in checks:
        if val:
            score += weight

    # FIX: Arithmetic validation — subtotal + tax ≈ total
    if fields.subtotal is not None and fields.total is not None:
        tax_val = fields.tax or 0.0
        expected = round(fields.subtotal + tax_val, 2)
        if abs(expected - fields.total) < 0.05:
            score += 10  # Bonus for consistency
        else:
            score -= 15  # Penalty for mismatch

    # Line items sum ≈ subtotal
    if fields.line_items and fields.subtotal is not None:
        items_sum = sum(item.amount for item in fields.line_items if item.amount)
        if abs(items_sum - fields.subtotal) < 1.0:
            score += 5

    return max(0.0, min(100.0, score))


# ── Main parser ───────────────────────────────────────────────────

async def parse_invoice(text: str) -> InvoiceFields:
    text = _clean_text(text)
    cache_key = cache.hash_key(text)
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached.model_copy(update={"cached": True})

    invoice_date, due_date = _extract_dates(text)

    subtotal = _extract_amount(text, r"\bsub\s*-?\s*total\b")
    tax = _extract_tax(text, subtotal)

    # FIX: Parse totals line-by-line, prefer labels near bottom
    total = None
    lines = text.split("\n")
    total_labels = [r"\bgrand\s*total\b", r"\btotal\s*due\b", r"\bamount\s*due\b", r"\bbalance\s*due\b"]
    for label in total_labels:
        for line in reversed(lines):
            if re.search(label, line, re.IGNORECASE):
                total = _extract_amount(line, label)
                if total is not None:
                    break
        if total is not None:
            break

    # Fallback: find "total" (not subtotal) near bottom
    if total is None:
        for line in reversed(lines):
            if re.search(r"\btotal\b", line, re.IGNORECASE) and not re.search(r"\bsub", line, re.IGNORECASE):
                total = _extract_amount(line, r"\btotal\b")
                if total is not None:
                    break

    line_items = _extract_line_items(text)

    # FIX: Derive total BEFORE confidence calculation
    derived_total = False
    if total is None and subtotal is not None:
        total = round(subtotal + (tax or 0), 2)
        derived_total = True

    fields = InvoiceFields(
        vendor=_extract_vendor(text),
        invoice_number=_extract_invoice_number(text),
        invoice_date=invoice_date,
        due_date=due_date,
        po_number=_extract_po_number(text),
        currency=_detect_currency(text),
        subtotal=subtotal,
        tax=tax,
        total=total,
        line_items=line_items,
        raw_length=len(text),
        cached=False,
    )

    field_checks = [fields.vendor, fields.invoice_number, fields.invoice_date,
                    fields.due_date, fields.po_number, fields.subtotal,
                    fields.tax, fields.total]
    fields.fields_found = sum(1 for f in field_checks if f is not None) + (1 if fields.line_items else 0)

    # FIX: Confidence AFTER all fields populated
    fields.confidence = round(_compute_confidence(fields), 1)

    # Small penalty if total was derived, not extracted
    if derived_total:
        fields.confidence = max(0, fields.confidence - 5)

    await cache.set(cache_key, fields, ttl=3600)
    return fields
