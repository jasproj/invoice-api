"""Response models for Invoice Field Normalizer API."""
from __future__ import annotations
from pydantic import BaseModel, Field

class LineItem(BaseModel):
    description: str = Field(..., description="Item description")
    quantity: float | None = Field(None, description="Quantity")
    unit_price: float | None = Field(None, description="Unit price")
    amount: float | None = Field(None, description="Line total")

class InvoiceFields(BaseModel):
    vendor: str | None = Field(None, description="Vendor/company name")
    invoice_number: str | None = Field(None, description="Invoice number")
    invoice_date: str | None = Field(None, description="Invoice date (normalized YYYY-MM-DD)")
    due_date: str | None = Field(None, description="Due date (normalized YYYY-MM-DD)")
    po_number: str | None = Field(None, description="Purchase order number")
    currency: str = Field("USD", description="Detected currency")
    subtotal: float | None = Field(None, description="Subtotal before tax")
    tax: float | None = Field(None, description="Tax amount")
    total: float | None = Field(None, description="Total amount due")
    line_items: list[LineItem] = Field(default_factory=list, description="Extracted line items")
    confidence: float = Field(0.0, description="Overall extraction confidence 0-100")
    fields_found: int = Field(0, description="Number of fields successfully extracted")
    raw_length: int = Field(0, description="Character count of input text")
    cached: bool = False

class BatchRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=10, description="List of invoice texts (max 10)")

class BatchResponse(BaseModel):
    count: int
    results: list[InvoiceFields]

class HealthResponse(BaseModel):
    status: str = "ok"
    cache_size: int = 0

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
