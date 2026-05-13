import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
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

SAMPLE_SESSIONS = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    for folder in ["data", "reports", "uploads"]:
        os.makedirs(folder, exist_ok=True)

    if not os.path.exists("data/sessions.json"):
        with open("data/sessions.json", "w", encoding="utf-8") as f:
            json.dump(SAMPLE_SESSIONS, f, indent=2)

    if not os.path.exists("data/settings.json"):
        with open("data/settings.json", "w", encoding="utf-8") as f:
            json.dump({"companyName": "", "industry": "", "logoBase64": ""}, f, indent=2)

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