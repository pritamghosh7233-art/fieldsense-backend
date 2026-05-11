import json
import os

DATA_PATH = "data/sessions.json"


def load_sessions() -> list:
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_zone_history(plant_name: str, section: str, zone_label: str) -> list:
    sessions = load_sessions()
    history = []
    for session in sessions:
        if session.get("plantName") == plant_name and session.get("section") == section:
            for zone in session.get("zones", []):
                if zone.get("zoneLabel") == zone_label and zone.get("aiFindings"):
                    history.append({
                        "date": session.get("created_at", ""),
                        "riskScore": zone["aiFindings"].get("riskScore", 0),
                        "session_id": session.get("session_id", ""),
                    })
    return sorted(history, key=lambda x: x["date"])


def get_session_trend(session: dict) -> dict:
    trend_data = {}
    for zone in session.get("zones", []):
        zone_id = zone.get("zoneId")
        zone_label = zone.get("zoneLabel")
        history = get_zone_history(session.get("plantName", ""), session.get("section", ""), zone_label)

        current_score = 0
        if zone.get("aiFindings"):
            current_score = zone["aiFindings"].get("riskScore", 0)

        if len(history) >= 2:
            previous_score = history[-2]["riskScore"]
        elif len(history) == 1:
            previous_score = history[0]["riskScore"]
        else:
            previous_score = current_score

        delta = current_score - previous_score
        delta_percent = round((delta / previous_score * 100) if previous_score else 0, 2)

        trend_data[zone_id] = {
            "previousScore": previous_score,
            "delta": delta,
            "deltaPercent": delta_percent,
        }
    return trend_data
