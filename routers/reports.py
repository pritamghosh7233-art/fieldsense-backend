import json
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from services import ai_service, pdf_service, trend_service

router = APIRouter()
SESSIONS_PATH = "data/sessions.json"
SETTINGS_PATH = "data/settings.json"


def _read_sessions() -> list:
    with open(SESSIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_sessions(sessions: list):
    with open(SESSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


def _read_settings() -> dict:
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/api/generate-report/{session_id}")
def generate_report(session_id: str):
    try:
        sessions = _read_sessions()
        session = next((s for s in sessions if s["session_id"] == session_id), None)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        company_settings = _read_settings()
        report_content = ai_service.generate_report_content(session)
        trend_data = trend_service.get_session_trend(session)
        pdf_path = pdf_service.generate_report(session, report_content, company_settings, trend_data)

        for s in sessions:
            if s["session_id"] == session_id:
                s["report_pdf_path"] = pdf_path
        _write_sessions(sessions)

        return {"report_path": pdf_path, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/reports/{session_id}")
def get_report(session_id: str):
    path = f"reports/{session_id}.pdf"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not yet generated")
    return FileResponse(path, media_type="application/pdf", filename=f"{session_id}_report.pdf")
