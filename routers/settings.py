import json
from fastapi import APIRouter, HTTPException
from models.schemas import CompanySettings

router = APIRouter()
SETTINGS_PATH = "data/settings.json"


@router.get("/api/settings")
def get_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/settings")
def save_settings(settings: CompanySettings):
    try:
        data = settings.model_dump()
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
