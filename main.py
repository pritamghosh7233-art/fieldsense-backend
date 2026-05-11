import os
import json
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routers import sessions, reports, settings

COMPLIANCE_RULES = [
    {"code": "OSHA 1910.303", "name": "Electrical wiring methods", "description": "General requirements for electrical installations and wiring", "keywords": ["wiring", "panel", "terminal", "corrosion", "insulation", "grounding", "circuit"]},
    {"code": "ISO 50001", "name": "Energy management systems", "description": "Requirements for energy performance, efficiency and consumption", "keywords": ["energy", "meter", "efficiency", "consumption", "power", "monitor"]},
    {"code": "IEC 60079-14", "name": "Explosive atmospheres", "description": "Electrical installations design in hazardous areas", "keywords": ["explosion", "hazardous", "flammable", "gas", "zone", "spark"]},
    {"code": "API 570", "name": "Piping inspection code", "description": "Inspection, repair and alteration of in-service piping", "keywords": ["pipe", "corrosion", "leak", "thickness", "rust", "flow"]},
    {"code": "NFPA 72", "name": "Fire alarm and signaling", "description": "Requirements for fire alarm systems and emergency communications", "keywords": ["fire", "alarm", "smoke", "detector", "sprinkler", "heat"]},
    {"code": "ISO 45001", "name": "Occupational health and safety", "description": "Requirements for occupational health and safety management", "keywords": ["safety", "hazard", "PPE", "risk", "incident", "injury"]},
    {"code": "API 510", "name": "Pressure vessel inspection", "description": "Inspection, repair, alteration of pressure vessels", "keywords": ["pressure", "vessel", "weld", "crack", "integrity", "relief"]},
    {"code": "ASHRAE 15", "name": "Refrigeration safety", "description": "Safety code for mechanical and absorption refrigeration systems", "keywords": ["refrigerant", "leak", "compressor", "cooling", "hvac", "chiller"]},
]

SAMPLE_SESSIONS = [
    {
        "session_id": "FS-2024-001",
        "created_at": "2024-11-15T09:30:00Z",
        "status": "synced",
        "plantName": "Sunrise Power Plant",
        "section": "Section B — Electrical",
        "industry": "Electrical",
        "operator": "John Smith",
        "overallRiskScore": 74,
        "report_pdf_path": "",
        "zones": [
            {
                "zoneId": "z1", "zoneLabel": "Zone A", "transcript": "Corrosion on terminal block observed.",
                "audioUri": "", "severity": "Critical", "images": [],
                "aiFindings": {"anomalies": ["Corrosion on terminal block", "Oxidation on bus bars"], "riskScore": 78, "complianceCodes": ["OSHA 1910.303", "IEC 60079-14"], "predictedFailureWindow": "4-8 weeks", "maintenancePriority": "P1", "summary": "Critical corrosion requiring immediate action."},
            },
            {
                "zoneId": "z2", "zoneLabel": "Zone B", "transcript": "Loose wiring and heat discolouration noted.",
                "audioUri": "", "severity": "High", "images": [],
                "aiFindings": {"anomalies": ["Loose wiring", "Heat discolouration on panel"], "riskScore": 65, "complianceCodes": ["OSHA 1910.303"], "predictedFailureWindow": "6-10 weeks", "maintenancePriority": "P2", "summary": "Wiring issues require scheduled repair within 30 days."},
            },
            {
                "zoneId": "z3", "zoneLabel": "Zone C", "transcript": "Minor insulation wear on cables.",
                "audioUri": "", "severity": "Low", "images": [],
                "aiFindings": {"anomalies": ["Minor insulation wear"], "riskScore": 32, "complianceCodes": ["OSHA 1910.303"], "predictedFailureWindow": "12-16 weeks", "maintenancePriority": "P3", "summary": "Monitor insulation wear at next scheduled inspection."},
            },
        ],
    },
    {
        "session_id": "FS-2024-002",
        "created_at": "2024-11-20T14:00:00Z",
        "status": "pending_sync",
        "plantName": "Metro HVAC Block C",
        "section": "Cooling Section",
        "industry": "HVAC",
        "operator": "Sarah Jones",
        "overallRiskScore": 58,
        "report_pdf_path": "",
        "zones": [
            {
                "zoneId": "z1", "zoneLabel": "Zone 1", "transcript": "Refrigerant leak suspected near compressor.",
                "audioUri": "", "severity": "Critical", "images": [],
                "aiFindings": {"anomalies": ["Refrigerant leak suspected"], "riskScore": 72, "complianceCodes": ["ASHRAE 15"], "predictedFailureWindow": "2-4 weeks", "maintenancePriority": "P1", "summary": "Suspected refrigerant leak requires immediate inspection and repair."},
            },
            {
                "zoneId": "z2", "zoneLabel": "Zone 2", "transcript": "Compressor showing signs of wear.",
                "audioUri": "", "severity": "Medium", "images": [],
                "aiFindings": {"anomalies": ["Compressor wear detected", "Unusual vibration levels"], "riskScore": 44, "complianceCodes": ["ASHRAE 15", "ISO 50001"], "predictedFailureWindow": "8-12 weeks", "maintenancePriority": "P2", "summary": "Schedule compressor maintenance within 30 days to prevent failure."},
            },
        ],
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    for folder in ["data", "reports", "uploads"]:
        os.makedirs(folder, exist_ok=True)

    if not os.path.exists("data/sessions.json"):
        with open("data/sessions.json", "w", encoding="utf-8") as f:
            json.dump(SAMPLE_SESSIONS, f, indent=2)

    if not os.path.exists("data/settings.json"):
        with open("data/settings.json", "w", encoding="utf-8") as f:
            json.dump({"companyName": "My Company", "industry": "Electrical", "logoBase64": ""}, f, indent=2)

    with open("data/compliance_rules.json", "w", encoding="utf-8") as f:
        json.dump(COMPLIANCE_RULES, f, indent=2)

    yield


app = FastAPI(title="FieldSense Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(reports.router)
app.include_router(settings.router)


@app.get("/health")
def health():
    return {"status": "ok", "model": os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")}
