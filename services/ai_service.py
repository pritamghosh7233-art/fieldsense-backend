import boto3
import json
import os
import time
import logging

logger = logging.getLogger(__name__)

bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


def _invoke_with_retry(body: dict) -> dict:
    for attempt in range(3):
        try:
            logger.info(f"[Bedrock] Attempt {attempt + 1} — model={MODEL_ID}")
            response = bedrock.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
            response_body = json.loads(response["body"].read())
            logger.info("[Bedrock] Response received OK")
            return response_body
        except Exception as e:
            logger.error(f"[Bedrock] Attempt {attempt + 1} failed: {type(e).__name__}: {e}")
            if "ThrottlingException" in str(e) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise  # re-raise so the caller sees the real error


def analyze_observation(
    transcript: str,
    image_base64_array: list,
    industry: str,
    zone: str,
    session_history: list,
) -> dict:
    logger.info(
        f"[analyze_observation] zone={zone!r} industry={industry!r} "
        f"images={len(image_base64_array)} transcript_len={len(transcript)}"
    )

    content = [
        {
            "type": "text",
            "text": (
                f"Industry: {industry}\nZone: {zone}\n"
                f"Voice transcript: {transcript}\n\n"
                f"Previous inspection history for this zone:\n{json.dumps(session_history)}"
            ),
        }
    ]

    # Attach images — skip any empty/None base64 strings
    for i, b64 in enumerate(image_base64_array):
        if not b64:
            logger.warning(f"[analyze_observation] Skipping empty base64 at index {i}")
            continue
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "system": (
            "You are an expert industrial inspection AI. Analyze the voice transcript and images from a field inspection. "
            'Return ONLY valid JSON (no markdown, no explanation) with this exact schema: {"anomalies": ["string"], '
            '"riskScore": number 0-100, "complianceCodes": ["string"], "predictedFailureWindow": "string", '
            '"maintenancePriority": "P1|P2|P3", "summary": "string"}. '
            "Risk score guide: <40 low, 40-69 medium, 70+ high. "
            "Maintenance priority: P1=immediate, P2=within 30 days, P3=within 90 days. "
            "Map findings to these compliance codes where relevant: "
            "OSHA 1910.303, ISO 50001, IEC 60079-14, API 570, NFPA 72, ISO 45001, API 510, ASHRAE 15."
        ),
        "messages": [{"role": "user", "content": content}],
    }

    try:
        response_body = _invoke_with_retry(body)
        text = response_body["content"][0]["text"]
        logger.info(f"[analyze_observation] Raw response text: {text[:300]}")

        # Strip accidental markdown fences Claude sometimes adds
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()

        result = json.loads(clean)
        logger.info(f"[analyze_observation] Parsed OK — riskScore={result.get('riskScore')}")
        return result

    except Exception as e:
        logger.error(f"[analyze_observation] FAILED: {type(e).__name__}: {e}")
        return {
            "anomalies": ["Analysis unavailable — manual review required"],
            "riskScore": 50,
            "complianceCodes": [],
            "predictedFailureWindow": "Unknown",
            "maintenancePriority": "P2",
            "summary": f"AI analysis failed ({type(e).__name__}): {str(e)[:200]}",
        }


def generate_report_content(session: dict) -> dict:
    try:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "system": (
                "You are an expert industrial inspection report writer. Given a full inspection session JSON, "
                "generate a structured report content object. Return ONLY valid JSON with this schema: "
                '{"executiveSummary": "string (3-5 sentences)", '
                '"priorityActions": [{"zone": "string", "finding": "string", "urgency": "Critical|High|Medium|Low", "riskScore": number}], '
                '"maintenanceSchedule": [{"zone": "string", "issue": "string", "priority": "P1|P2|P3", "action": "string", "timeframe": "string"}], '
                '"complianceSummary": [{"finding": "string", "standard": "string", "status": "Compliant|Non-Compliant|Needs Review"}]}'
            ),
            "messages": [
                {"role": "user", "content": f"Generate report for this inspection session:\n{json.dumps(session)}"}
            ],
        }
        response_body = _invoke_with_retry(body)
        text = response_body["content"][0]["text"]
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
            clean = clean.strip()
        return json.loads(clean)
    except Exception as e:
        logger.error(f"[generate_report_content] FAILED: {type(e).__name__}: {e}")
        return {
            "executiveSummary": "Report generation failed. Please review session data manually.",
            "priorityActions": [],
            "maintenanceSchedule": [],
            "complianceSummary": [],
        }


def get_trend_analysis(zone_label: str, plant_name: str, past_sessions: list) -> dict:
    try:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "system": (
                "You are an industrial inspection trend analyst. Analyze how a zone's risk has changed across inspection sessions. "
                'Return ONLY valid JSON: {"deteriorationRate": number (percent change), "trend": "improving|stable|worsening", "trendNote": "string"}'
            ),
            "messages": [
                {
                    "role": "user",
                    "content": f"Zone: {zone_label}\nPlant: {plant_name}\nPast inspection risk scores:\n{json.dumps(past_sessions)}",
                }
            ],
        }
        response_body = _invoke_with_retry(body)
        text = response_body["content"][0]["text"]
        return json.loads(text)
    except Exception as e:
        logger.error(f"[get_trend_analysis] FAILED: {type(e).__name__}: {e}")
        return {"deteriorationRate": 0, "trend": "stable", "trendNote": "Trend analysis unavailable."}