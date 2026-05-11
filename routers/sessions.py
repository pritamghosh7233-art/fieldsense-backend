import json
import os
from fastapi import APIRouter, HTTPException
from models.schemas import Session, AnalyzeRequest
from services import ai_service, trend_service

router = APIRouter()
SESSIONS_PATH = "data/sessions.json"


def _read_sessions() -> list:
    with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_sessions(sessions: list):
    with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


@router.get("/api/sessions")
def list_sessions():
    try:
        sessions = _read_sessions()
        return sorted(sessions, key=lambda s: s.get("created_at", ""), reverse=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sessions")
def create_session(session: Session):
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

        sessions.append(data)
        _write_sessions(sessions)
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
    """
    Endpoint called by the mobile app's ai.js service.
    Proxies to AWS Bedrock via ai_service — no AI credentials stored in mobile.
    """
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
