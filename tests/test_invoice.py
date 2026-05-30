"""Tests for Invoice Field Normalizer API."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.parser import parse_invoice, _parse_date, _detect_currency, _extract_invoice_number, _extract_amount

SAMPLE_INVOICE = """
Acme Corporation
123 Business Ave, Suite 400
New York, NY 10001

Invoice #INV-2024-0847
Date: March 15, 2024
Due Date: April 14, 2024
PO Number: PO-9923

Bill To:
Widget Inc.
456 Commerce St
Chicago, IL 60601

Description                    Qty    Unit Price    Amount
Web Development Services        40      $150.00    $6,000.00
Cloud Hosting (Monthly)          1      $299.99      $299.99
SSL Certificate Renewal          2       $49.50       $99.00
Emergency Support Hours          5      $200.00    $1,000.00

                              Subtotal:            $7,398.99
                              Tax (8.5%):            $628.91
                              Total Due:           $8,027.90

Payment Terms: Net 30
"""

def test_date_parsing():
    print("=== Date Parsing ===")
    assert _parse_date("03/15/2024") == "2024-03-15"
    print("MM/DD/YYYY ✓")
    assert _parse_date("2024-03-15") == "2024-03-15"
    print("YYYY-MM-DD ✓")
    assert _parse_date("March 15, 2024") == "2024-03-15"
    print("Month DD, YYYY ✓")
    assert _parse_date("15 Mar 2024") == "2024-03-15"
    print("DD Mon YYYY ✓")
    assert _parse_date("no date here") is None
    print("No date → None ✓")
    # FIX: Feb 31 should fail
    assert _parse_date("02/31/2024") is None
    print("Feb 31 rejected ✓")
    # FIX: Apr 31 should fail
    assert _parse_date("04/31/2024") is None
    print("Apr 31 rejected ✓")
    print()

def test_currency():
    print("=== Currency Detection ===")
    assert _detect_currency("Total: $500.00") == "USD"
    print("$ → USD ✓")
    assert _detect_currency("Total: €500.00") == "EUR"
    print("€ → EUR ✓")
    assert _detect_currency("Amount: 500 GBP") == "GBP"
    print("GBP code ✓")
    assert _detect_currency("Amount: 500") == "USD"
    print("Default → USD ✓")
    # FIX: CA$ should not be caught as USD
    assert _detect_currency("Total: CA$500.00") == "CAD"
    print("CA$ → CAD ✓")
    assert _detect_currency("Total: A$500.00") == "AUD"
    print("A$ → AUD ✓")
    print()

def test_tax_percentage():
    print("=== Tax Percentage ===")
    from app.parser import _extract_tax
    assert _extract_tax("Tax: $50.00", 500.0) == 50.0
    print("Direct tax amount ✓")
    result = _extract_tax("Tax (10%): see total", 500.0)
    assert result == 50.0
    print("Tax from percentage ✓")
    result = _extract_tax("VAT 8.5%", 1000.0)
    assert result == 85.0
    print("VAT percentage ✓")
    assert _extract_tax("No tax info here", None) is None
    print("No tax → None ✓")
    print()

def test_invoice_number():
    print("=== Invoice Number ===")
    assert _extract_invoice_number("Invoice #INV-2024-0847") == "INV-2024-0847"
    print("Invoice # format ✓")
    assert _extract_invoice_number("Invoice No: A12345") == "A12345"
    print("Invoice No format ✓")
    assert _extract_invoice_number("random text") is None
    print("No invoice → None ✓")
    print()

def test_amount_extraction():
    print("=== Amount Extraction ===")
    assert _extract_amount("Total Due: $8,027.90", r"total\s*(?:due)?") == 8027.90
    print("Total with comma ✓")
    assert _extract_amount("Subtotal: $7,398.99", r"sub\s*-?\s*total") == 7398.99
    print("Subtotal ✓")
    assert _extract_amount("Tax: $628.91", r"tax") == 628.91
    print("Tax ✓")
    print()

def test_full_parse():
    print("=== Full Invoice Parse ===")
    async def _run():
        result = await parse_invoice(SAMPLE_INVOICE)
        print(f"Vendor: {result.vendor}")
        assert result.vendor is not None
        print("  Vendor found ✓")

        print(f"Invoice #: {result.invoice_number}")
        assert result.invoice_number == "INV-2024-0847"
        print("  Invoice number correct ✓")

        print(f"Date: {result.invoice_date}")
        assert result.invoice_date == "2024-03-15"
        print("  Invoice date correct ✓")

        print(f"Due: {result.due_date}")
        assert result.due_date == "2024-04-14"
        print("  Due date correct ✓")

        print(f"PO: {result.po_number}")
        assert result.po_number == "PO-9923"
        print("  PO number correct ✓")

        print(f"Subtotal: {result.subtotal}")
        assert result.subtotal == 7398.99
        print("  Subtotal correct ✓")

        print(f"Tax: {result.tax}")
        assert result.tax == 628.91
        print("  Tax correct ✓")

        print(f"Total: {result.total}")
        assert result.total == 8027.90
        print("  Total correct ✓")

        print(f"Line items: {len(result.line_items)}")
        assert len(result.line_items) >= 3
        print("  Line items found ✓")

        print(f"Confidence: {result.confidence}")
        assert result.confidence >= 70
        print("  High confidence ✓")

        print(f"Currency: {result.currency}")
        assert result.currency == "USD"
        print("  Currency detected ✓")

    asyncio.run(_run())
    print()

def test_app_import():
    print("=== App Import ===")
    from app.main import app
    print(f"App: {app.title} ✓")
    print()

if __name__ == "__main__":
    print("=" * 50)
    print("Invoice Field Normalizer — Tests")
    print("=" * 50)
    print()
    test_date_parsing()
    test_currency()
    test_tax_percentage()
    test_invoice_number()
    test_amount_extraction()
    test_full_parse()
    test_app_import()
    print("=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
