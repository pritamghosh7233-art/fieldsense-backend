import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from models.schemas import Session, AnalyzeRequest
from services import ai_service, trend_service, pdf_service

router = APIRouter()
SESSIONS_PATH = "data/sessions.json"
SETTINGS_PATH = "data/settings.json"
APPROVED_PATH = "data/approved_records.json"


def _read_sessions() -> list:
    with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_sessions(sessions: list):
    with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


def _read_approved() -> list:
    if not os.path.exists(APPROVED_PATH):
        return []
    with open(APPROVED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_approved(records: list):
    with open(APPROVED_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _generate_report_background(session_id: str, session_data: dict):
    """Run report generation in background after session is saved."""
    try:
        sessions = _read_sessions()
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            company_settings = json.load(f)
        if session_data.get("companyName"):
            company_settings = {**company_settings, "companyName": session_data["companyName"]}

        report_content = ai_service.generate_report_content(session_data)
        trend_data = trend_service.get_session_trend(session_data)
        pdf_path = pdf_service.generate_report(session_data, report_content, company_settings, trend_data)

        # Save report_pdf_path and report_content back onto the session
        for s in sessions:
            if s["session_id"] == session_id:
                s["report_pdf_path"] = pdf_path
                s["report_content"] = report_content
        _write_sessions(sessions)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[background report] {session_id}: {e}")


@router.get("/api/sessions")
def list_sessions():
    try:
        sessions = _read_sessions()
        return sorted(sessions, key=lambda s: s.get("created_at", ""), reverse=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sessions")
def create_session(session: Session, background_tasks: BackgroundTasks):
    try:
        sessions = _read_sessions()
        data = session.model_dump()

        # Calculate overall risk score
        scores = [
            z["aiFindings"]["riskScore"]
            for z in data["zones"]
            if z.get("aiFindings") and z["aiFindings"].get("riskScore") is not None
        ]
        data["overallRiskScore"] = int(sum(scores) / len(scores)) if scores else 0

        # Attach trend delta to each zone
        for zone in data["zones"]:
            history = trend_service.get_zone_history(data["plantName"], data["section"], zone["zoneLabel"])
            if history and zone.get("aiFindings"):
                prev = history[-1]["riskScore"]
                current = zone["aiFindings"]["riskScore"]
                zone["aiFindings"]["trendDelta"] = current - prev
                zone["aiFindings"]["previousScore"] = prev

        data["report_pdf_path"] = ""
        data["report_content"] = None
        data["approved"] = False
        data["approvedAt"] = None

        sessions.append(data)
        _write_sessions(sessions)

        # Keep settings.json company name in sync
        if data.get("companyName"):
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                if settings.get("companyName") in ("", "My Company", None):
                    settings["companyName"] = data["companyName"]
                    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                        json.dump(settings, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Kick off report generation in the background immediately
        background_tasks.add_task(_generate_report_background, data["session_id"], data)

        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    try:
        sessions = _read_sessions()
        for s in sessions:
            if s["session_id"] == session_id:
                return s
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/sessions/{session_id}/trend")
def get_session_trend(session_id: str):
    try:
        sessions = _read_sessions()
        for s in sessions:
            if s["session_id"] == session_id:
                return trend_service.get_session_trend(s)
        raise HTTPException(status_code=404, detail="Session not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sessions/{session_id}/approve")
def approve_session(session_id: str):
    """
    Mark a session as approved. Stores a full approved record in
    approved_records.json (future migration target: PostgreSQL/Supabase).
    """
    try:
        sessions = _read_sessions()
        session = next((s for s in sessions if s["session_id"] == session_id), None)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.get("approved"):
            return {"message": "Already approved", "session_id": session_id}

        approved_at = datetime.now(timezone.utc).isoformat()

        # Update session record — set both approved flag AND status
        for s in sessions:
            if s["session_id"] == session_id:
                s["approved"] = True
                s["approvedAt"] = approved_at
                s["status"] = "approved"
        _write_sessions(sessions)

        # Write to approved_records store — structured for easy Postgres migration
        records = _read_approved()
        records.append({
            "record_id": f"APR-{session_id}",
            "session_id": session_id,
            "approvedAt": approved_at,
            "plantName": session.get("plantName", ""),
            "section": session.get("section", ""),
            "operator": session.get("operator", ""),
            "companyName": session.get("companyName", ""),
            "industry": session.get("industry", ""),
            "overallRiskScore": session.get("overallRiskScore", 0),
            "report_pdf_path": session.get("report_pdf_path", ""),
            "report_content": session.get("report_content"),
            "zones": session.get("zones", []),
            "created_at": session.get("created_at", ""),
        })
        _write_approved(records)

        return {"approved": True, "approvedAt": approved_at, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/approved-records")
def list_approved_records():
    """Return all approved inspection records."""
    try:
        return _read_approved()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    try:
        history = trend_service.get_zone_history("", "", request.zone)
        findings = ai_service.analyze_observation(
            request.transcript,
            request.imageBase64Array,
            request.industry,
            request.zone,
            request.sessionHistory or history,
        )
        return findings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/analyze-zone")
def analyze_zone(request: AnalyzeRequest):
    try:
        history = trend_service.get_zone_history("", "", request.zone)
        findings = ai_service.analyze_observation(
            request.transcript,
            request.imageBase64Array,
            request.industry,
            request.zone,
            request.sessionHistory or history,
        )
        return findings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    try:
        sessions = _read_sessions()
        updated = [s for s in sessions if s["session_id"] != session_id]
        if len(updated) == len(sessions):
            raise HTTPException(status_code=404, detail="Session not found")
        _write_sessions(updated)
        return {"deleted": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))