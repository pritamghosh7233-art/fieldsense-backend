from pydantic import BaseModel
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
    transcript: str
    imageBase64Array: list[str]
    industry: str
    zone: str
    sessionHistory: list[dict] = []
