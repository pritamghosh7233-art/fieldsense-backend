# FieldSense Backend

FastAPI backend for FieldSense industrial inspection app. Uses AWS Bedrock (Claude Sonnet 4.6) for AI analysis, JSON files for storage, and ReportLab for PDF generation.

## Prerequisites

- Python 3.11+
- AWS account with Bedrock access enabled for Claude Sonnet 4.6
- AWS credentials (Access Key ID + Secret Access Key)

## Setup

```bash
cd fieldsense-backend
pip install -r requirements.txt
cp .env.example .env
# Fill in your AWS credentials in .env
```

## Run

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Find your local IP (for mobile app)

```bash
# Mac/Linux
ifconfig | grep "inet "
# Windows
ipconfig
```

Update `services/api.js` in the mobile app: `http://YOUR_IP:8000`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /health | Health check |
| GET | /api/sessions | List all sessions |
| POST | /api/sessions | Save a session |
| GET | /api/sessions/{id} | Get one session |
| GET | /api/sessions/{id}/trend | Get trend data |
| POST | /api/analyze | AI analysis via Bedrock |
| DELETE | /api/sessions/{id} | Delete session |
| POST | /api/generate-report/{id} | Generate PDF report |
| GET | /api/reports/{id} | Download PDF |
| GET | /api/settings | Get company settings |
| POST | /api/settings | Save company settings |

## AWS Bedrock Setup

1. Go to AWS Console → Bedrock → Model access
2. Request access to **Claude Sonnet 4.6** (`us.anthropic.claude-sonnet-4-6`)
3. Ensure your IAM user has `bedrock:InvokeModel` permission
