"""
analyzed_reports.py — Router for combined analyzed reports
Handles:
  - POST /api/analyzed-reports/store        → store approved report in PostgreSQL
  - GET  /api/analyzed-reports              → list all stored reports
  - POST /api/analyzed-reports/nl-query     → natural language query → matching reports
  - POST /api/analyzed-reports/generate-pdf → generate combined analyzed PDF from records
  - POST /api/analyzed-reports/generate-ppt → generate combined analyzed PPT from records
"""

import os
import json
import logging
import tempfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── optional psycopg2 import ─────────────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger.warning("psycopg2 not installed — falling back to JSON file store")

DATABASE_URL = os.getenv("DATABASE_URL", "")   # postgres://user:pass@host:port/db
FALLBACK_PATH = "data/analyzed_reports.json"   # used when postgres is unavailable


# ─────────────────────────────────────────────────────────────────────────────
#  DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn():
    if not PSYCOPG2_AVAILABLE or not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"[DB] Connection failed: {e}")
        return None


def _ensure_table(conn):
    """Create the analyzed_reports table if it doesn't exist."""
    ddl = """
    CREATE TABLE IF NOT EXISTS analyzed_reports (
        id              SERIAL PRIMARY KEY,
        session_id      TEXT NOT NULL,
        plant_name      TEXT,
        section         TEXT,
        zone_labels     TEXT[],
        operator        TEXT,
        company_name    TEXT,
        industry        TEXT,
        overall_risk    INTEGER,
        report_content  JSONB,
        approved_at     TIMESTAMPTZ,
        created_at      TIMESTAMPTZ DEFAULT now()
    );
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def _read_fallback() -> list:
    if not os.path.exists(FALLBACK_PATH):
        return []
    with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_fallback(records: list):
    os.makedirs("data", exist_ok=True)
    with open(FALLBACK_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
#  Schemas
# ─────────────────────────────────────────────────────────────────────────────

class StoreReportRequest(BaseModel):
    session_id: str
    plant_name: str
    section: str
    zone_labels: list[str] = []
    operator: str
    company_name: str
    industry: str
    overall_risk: int
    report_content: dict
    approved_at: Optional[str] = None


class NLQueryRequest(BaseModel):
    query: str


class GenerateAnalyzedRequest(BaseModel):
    record_ids: list[int]       # IDs from the analyzed_reports table / fallback list
    output_type: str = "pdf"    # "pdf" | "ppt"
    user_query: str = ""


# ─────────────────────────────────────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/analyzed-reports/store")
def store_analyzed_report(req: StoreReportRequest):
    """Persist an approved report to PostgreSQL (or fallback JSON)."""
    approved_at = req.approved_at or datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    if conn:
        try:
            _ensure_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analyzed_reports
                        (session_id, plant_name, section, zone_labels, operator,
                         company_name, industry, overall_risk, report_content, approved_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        req.session_id, req.plant_name, req.section,
                        req.zone_labels, req.operator, req.company_name,
                        req.industry, req.overall_risk,
                        json.dumps(req.report_content), approved_at,
                    ),
                )
                row_id = cur.fetchone()[0]
            conn.commit()
            conn.close()
            return {"stored": True, "id": row_id, "backend": "postgresql"}
        except Exception as e:
            logger.error(f"[store] PG error: {e}")
            conn.close()

    # ── fallback to JSON ──
    records = _read_fallback()
    new_id = max((r.get("id", 0) for r in records), default=0) + 1
    records.append({
        "id": new_id,
        "session_id": req.session_id,
        "plant_name": req.plant_name,
        "section": req.section,
        "zone_labels": req.zone_labels,
        "operator": req.operator,
        "company_name": req.company_name,
        "industry": req.industry,
        "overall_risk": req.overall_risk,
        "report_content": req.report_content,
        "approved_at": approved_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_fallback(records)
    return {"stored": True, "id": new_id, "backend": "json_fallback"}


@router.get("/api/analyzed-reports")
def list_analyzed_reports():
    """Return all stored analyzed reports (summary only)."""
    conn = _get_conn()
    if conn:
        try:
            _ensure_table(conn)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, session_id, plant_name, section, zone_labels, operator,
                           company_name, industry, overall_risk, approved_at, created_at
                    FROM analyzed_reports ORDER BY approved_at DESC
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"[list] PG error: {e}")
            conn.close()

    records = _read_fallback()
    return [
        {k: v for k, v in r.items() if k != "report_content"}
        for r in sorted(records, key=lambda x: x.get("approved_at", ""), reverse=True)
    ]


@router.post("/api/analyzed-reports/nl-query")
def nl_query_reports(req: NLQueryRequest):
    """
    Parse a natural-language query using the AI, then filter stored reports.
    Returns matching records (without full report_content) and a human summary.
    """
    import boto3
    bedrock = boto3.client(
        service_name="bedrock-runtime",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

    # 1. Load all records (summaries)
    all_records = list_analyzed_reports()
    if not all_records:
        return {"matches": [], "summary": "No reports found in the database.", "filters": {}}

    # 2. Ask AI to extract filter intent from the query
    records_summary = json.dumps([
        {k: v for k, v in r.items() if k in
         ("id","plant_name","section","zone_labels","operator","company_name","industry","overall_risk","approved_at")}
        for r in all_records
    ], default=str)

    parse_prompt = f"""
User query: "{req.query}"

Available inspection reports (JSON summary):
{records_summary}

Extract the filter intent and return ONLY valid JSON:
{{
  "plant_name": "string or null",
  "section": "string or null",
  "operator": "string or null",
  "industry": "string or null",
  "zone_label": "string or null",
  "date_from": "ISO date string or null",
  "date_to": "ISO date string or null",
  "min_risk": "number or null",
  "max_risk": "number or null",
  "matching_ids": [list of integer IDs from the provided records that match the query],
  "human_summary": "1-2 sentence description of what the user is looking for"
}}
If no specific filter is clear, return all IDs in matching_ids.
"""
    try:
        resp = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 800,
                "messages": [{"role": "user", "content": parse_prompt}],
            }),
        )
        raw = json.loads(resp["body"].read())["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"[nl_query] AI parse failed: {e}")
        parsed = {"matching_ids": [r["id"] for r in all_records], "human_summary": "Showing all reports."}

    matching_ids = set(parsed.get("matching_ids") or [r["id"] for r in all_records])
    matches = [r for r in all_records if r.get("id") in matching_ids]

    return {
        "matches": matches,
        "summary": parsed.get("human_summary", ""),
        "filters": {k: v for k, v in parsed.items() if k not in ("matching_ids", "human_summary")},
        "total": len(matches),
    }


@router.post("/api/analyzed-reports/generate-pdf")
def generate_analyzed_pdf(req: GenerateAnalyzedRequest):
    """
    Fetch full content for requested record IDs and run the PDF analyzer pipeline.
    Returns a downloadable PDF.
    """
    records = _fetch_full_records(req.record_ids)
    if not records:
        raise HTTPException(status_code=404, detail="No records found for given IDs")

    combined_text = _build_combined_text(records)
    output_path = tempfile.mktemp(suffix="_analyzed_report.pdf", dir="reports")

    try:
        from services.combined_report_service import run_pdf_pipeline
        run_pdf_pipeline(combined_text, req.user_query, output_path)
    except Exception as e:
        logger.error(f"[generate_pdf] {e}")
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    filename = f"analyzed_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return FileResponse(output_path, media_type="application/pdf", filename=filename)


@router.post("/api/analyzed-reports/generate-ppt")
def generate_analyzed_ppt(req: GenerateAnalyzedRequest):
    """
    Fetch full content for requested record IDs and run the PPT generator pipeline.
    Returns a downloadable PPTX file.
    """
    records = _fetch_full_records(req.record_ids)
    if not records:
        raise HTTPException(status_code=404, detail="No records found for given IDs")

    combined_text = _build_combined_text(records)
    output_path = tempfile.mktemp(suffix="_analyzed_report.pptx", dir="reports")

    try:
        from services.combined_report_service import run_ppt_pipeline
        run_ppt_pipeline(combined_text, req.user_query, output_path)
    except Exception as e:
        logger.error(f"[generate_ppt] {e}")
        raise HTTPException(status_code=500, detail=f"PPT generation failed: {e}")

    filename = f"analyzed_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_full_records(record_ids: list[int]) -> list[dict]:
    """Fetch full records (including report_content) for a list of IDs."""
    id_set = set(record_ids)
    conn = _get_conn()
    if conn:
        try:
            _ensure_table(conn)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM analyzed_reports WHERE id = ANY(%s)",
                    (list(id_set),),
                )
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"[fetch_full] PG error: {e}")
            conn.close()

    records = _read_fallback()
    return [r for r in records if r.get("id") in id_set]


def _build_combined_text(records: list[dict]) -> str:
    """Flatten multiple approved inspection records into a single analysable text blob."""
    parts = []
    for r in records:
        parts.append(f"=== INSPECTION REPORT: {r.get('plant_name','')} / {r.get('section','')} ===")
        parts.append(f"Operator: {r.get('operator','')}  |  Company: {r.get('company_name','')}")
        parts.append(f"Industry: {r.get('industry','')}  |  Overall Risk Score: {r.get('overall_risk',0)}")
        parts.append(f"Zones inspected: {', '.join(r.get('zone_labels',[]))}")
        parts.append(f"Approved at: {r.get('approved_at','')}")
        parts.append("")

        rc = r.get("report_content") or {}
        if isinstance(rc, str):
            try:
                rc = json.loads(rc)
            except Exception:
                rc = {}

        if rc.get("executiveSummary"):
            parts.append(f"Executive Summary:\n{rc['executiveSummary']}")
            parts.append("")

        if rc.get("priorityActions"):
            parts.append("Priority Actions:")
            for a in rc["priorityActions"]:
                parts.append(
                    f"  - [{a.get('urgency','')} / Risk {a.get('riskScore','')}] "
                    f"{a.get('zone','')}: {a.get('finding','')}"
                )
            parts.append("")

        if rc.get("maintenanceSchedule"):
            parts.append("Maintenance Schedule:")
            for m in rc["maintenanceSchedule"]:
                parts.append(
                    f"  - [{m.get('priority','')}] {m.get('zone','')}: "
                    f"{m.get('issue','')} → {m.get('action','')} ({m.get('timeframe','')})"
                )
            parts.append("")

        if rc.get("complianceSummary"):
            parts.append("Compliance Summary:")
            for c in rc["complianceSummary"]:
                parts.append(
                    f"  - [{c.get('status','')}] {c.get('standard','')}: {c.get('finding','')}"
                )
            parts.append("")

        parts.append("─" * 60)
        parts.append("")

    return "\n".join(parts)
