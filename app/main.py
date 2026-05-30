"""Invoice Field Normalizer API."""
from __future__ import annotations
import asyncio, time
from fastapi import FastAPI, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from .cache import cache
from .models import InvoiceFields, BatchRequest, BatchResponse, HealthResponse
from pydantic import BaseModel, Field
from .parser import parse_invoice

app = FastAPI(title="Invoice Field Normalizer API", description="Extract structured fields from raw invoice text. Post-OCR normalization — vendor, dates, amounts, line items. Pure computation, no external APIs.", version="1.0.0", docs_url="/docs", redoc_url="/redoc")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-Ms"] = str(round((time.perf_counter() - t0) * 1000, 1))
    return response

class ParseRequest(BaseModel):
    text: str = Field(..., min_length=10, max_length=50000, description="Raw invoice text from OCR or copy-paste")

@app.post("/parse", response_model=InvoiceFields, summary="Parse invoice text", tags=["Parse"])
async def parse(body: ParseRequest):
    return await parse_invoice(body.text)

@app.post("/parse/batch", response_model=BatchResponse, summary="Parse multiple invoices", tags=["Parse"])
async def parse_batch(body: BatchRequest):
    results = await asyncio.gather(*[parse_invoice(t) for t in body.texts])
    return BatchResponse(count=len(results), results=results)

@app.get("/health", response_model=HealthResponse, summary="Health check", tags=["Ops"])
async def health():
    return HealthResponse(status="ok", cache_size=cache.size)

@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Invoice Field Normalizer API", "version": "1.0.0", "docs": "/docs"}
