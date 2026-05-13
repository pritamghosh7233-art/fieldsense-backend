from pydantic import BaseModel, model_validator
from typing import Optional


class ImageData(BaseModel):
    uri: str
    base64: str


class AIFindings(BaseModel):
    anomalies: list[str]
    riskScore: int
    complianceCodes: list[str]
    predictedFailureWindow: str
    maintenancePriority: str
    summary: str


class ZoneObservation(BaseModel):
    zoneId: str
    zoneLabel: str
    transcript: str
    audioUri: str = ""
    severity: str
    images: list[ImageData] = []
    aiFindings: Optional[AIFindings] = None


class Session(BaseModel):
    session_id: str
    created_at: str
    status: str
    companyName: str = ""
    plantName: str
    section: str
    operator: str
    industry: str
    overallRiskScore: int = 0
    zones: list[ZoneObservation] = []
    report_pdf_path: str = ""


class CompanySettings(BaseModel):
    companyName: str = "My Company"
    industry: str = "Electrical"
    logoBase64: str = ""


class AnalyzeRequest(BaseModel):
    transcript: str = ""
    # Mobile sends `images` (list[str]), dashboard sends `imageBase64Array` — accept both
    imageBase64Array: list[str] = []
    images: list[str] = []
    industry: str
    zone: str
    session_id: Optional[str] = None   # sent by mobile, ignored by backend logic
    sessionHistory: list[dict] = []

    @model_validator(mode="after")
    def merge_image_fields(self) -> "AnalyzeRequest":
        """Normalise: merge `images` into `imageBase64Array` so downstream
        code always reads from `imageBase64Array` regardless of which field
        the client used."""
        if self.images:
            combined = list(dict.fromkeys(self.imageBase64Array + self.images))
            object.__setattr__(self, "imageBase64Array", combined)
        return self