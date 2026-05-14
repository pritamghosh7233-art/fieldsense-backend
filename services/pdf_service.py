import os
import io
import base64
import tempfile
import logging
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase.pdfmetrics import stringWidth
from PIL import Image as PILImage

logger = logging.getLogger(__name__)

PAGE_W, PAGE_H = A4

# ── Colour palette ────────────────────────────────────────────────────────────

GRAY_TEXT  = colors.HexColor("#555555")
LIGHT_GRAY = colors.HexColor("#DDDDDD")
BLACK      = colors.black
RED_TEXT   = colors.HexColor("#A32D2D")
RED_BG     = colors.HexColor("#FCEBEB")
AMBER_TEXT = colors.HexColor("#854F0B")
AMBER_BG   = colors.HexColor("#FAEEDA")
GREEN_TEXT = colors.HexColor("#3B6D11")
GREEN_BG   = colors.HexColor("#EAF3DE")
TABLE_HEAD = colors.HexColor("#2C2C2C")
ROW_ALT    = colors.HexColor("#F7F7F7")


def severity_colors(sev: str):
    return {
        "Critical": (RED_BG,   RED_TEXT),
        "High":     (AMBER_BG, AMBER_TEXT),
        "Medium":   (AMBER_BG, AMBER_TEXT),
        "Low":      (GREEN_BG, GREEN_TEXT),
    }.get(sev, (colors.white, BLACK))


def risk_timeline(priority: str) -> str:
    return {
        "P1": "Immediate (within 24 hrs)",
        "P2": "Within 30 days",
        "P3": "Within 90 days",
    }.get(priority, "As scheduled")


# ── Footer canvas ─────────────────────────────────────────────────────────────

class FooterCanvas(canvas.Canvas):
    """Footer on every body page except the cover (idx 0) and TOC (idx 1).
    Cover is now page 0 in the story itself."""

    def __init__(self, *args, session=None, company_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session          = session or {}
        self.company_settings = company_settings or {}
        self._saved_pages     = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for idx, page in enumerate(self._saved_pages):
            self.__dict__.update(page)
            # idx 0 = cover (no footer), idx 1 = TOC (no footer), idx 2+ = content
            if idx >= 2:
                self._draw_footer(idx - 1)   # page numbers start at 1
            super().showPage()
        super().save()

    def _draw_footer(self, page_num: int):
        self.saveState()
        y       = 18
        company = self.company_settings.get("companyName", "")


# ── Cover page ────────────────────────────────────────────────────────────────

def _draw_cover(c: canvas.Canvas, session: dict, company_settings: dict):
    """Corporate cover — heading block truly centred, inspector pinned to bottom."""
    plant_name  = session.get("plantName", "")
    operator    = session.get("operator", "")
    company     = company_settings.get("companyName", "")
    zones       = session.get("zones", [])
    panel_names = ", ".join(z.get("zoneLabel", "") for z in zones) if zones else "All Zones"

    MARGIN = 60
    MAX_W  = PAGE_W - MARGIN * 2
    CX     = PAGE_W / 2

    # Auto-size heading
    line1 = "Inspection Report on"
    line2 = '"' + plant_name + '"'
    font  = "Times-Bold"
    size  = 36
    while size >= 14:
        if max(stringWidth(line1, font, size), stringWidth(line2, font, size)) <= MAX_W:
            break
        size -= 1

    leading  = size * 1.4
    GAP_RULE = 20
    GAP_SUB  = 22
    SUB_SIZE = 13

    # Total block height and true-centre placement
    block_h = leading + GAP_RULE + GAP_SUB + SUB_SIZE
    line1_y = PAGE_H / 2 + block_h / 2
    line2_y = line1_y - leading
    rule_y  = line2_y - GAP_RULE
    sub_y   = rule_y  - GAP_SUB

    # Heading lines
    c.setFont(font, size)
    c.setFillColor(BLACK)
    c.drawCentredString(CX, line1_y, line1)
    c.drawCentredString(CX, line2_y, line2)

    # Rule
    c.setStrokeColor(BLACK)
    c.setLineWidth(0.8)
    c.line(MARGIN, rule_y, PAGE_W - MARGIN, rule_y)

    # Sub-heading
    sub = "Detailed analysis report on " + panel_names
    while stringWidth(sub, "Times-Roman", SUB_SIZE) > MAX_W and len(sub) > 20:
        sub = sub[:-4] + "..."
    c.setFont("Times-Roman", SUB_SIZE)
    c.setFillColor(GRAY_TEXT)
    c.drawCentredString(CX, sub_y, sub)

    # Inspector block pinned to bottom
    BOTTOM = 72
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(0.5)
    c.line(MARGIN + 60, BOTTOM + 46, PAGE_W - MARGIN - 60, BOTTOM + 46)
    c.setFont("Times-Bold", 13)
    c.setFillColor(BLACK)
    c.drawCentredString(CX, BOTTOM + 24, "Inspected by:  " + operator)
    c.setFont("Times-Roman", 12)
    c.setFillColor(GRAY_TEXT)
    c.drawCentredString(CX, BOTTOM, company)


# ── Cover as an inline Flowable ───────────────────────────────────────────────

class _CoverPageFlowable(Spacer):
    """Renders the cover using canvas primitives as the very first story page.
    Claiming full availHeight forces ReportLab to treat it as a whole page,
    so the following PageBreak lands on a fresh sheet — no PDF merge needed."""

    def __init__(self, session: dict, company_settings: dict):
        super().__init__(width=PAGE_W, height=PAGE_H)
        self._session          = session
        self._company_settings = company_settings

    def draw(self):
        # Reset canvas transform to true page origin (ignores doc margins)
        c = self.canv
        c.saveState()
        c.resetTransforms()
        _draw_cover(c, self._session, self._company_settings)
        c.restoreState()

    def wrap(self, availWidth, availHeight):
        # Return true A4 dimensions so the cover always gets a full page
        from reportlab.lib.pagesizes import A4
        return A4  # (595pt, 842pt) — not the margin-reduced available size

    def split(self, availWidth, availHeight):
        return [self]                    # never split across pages


# ── Table of Contents ─────────────────────────────────────────────────────────

def _build_toc(zones: list) -> list:
    story = []
    story.append(Paragraph("Table of Contents", ParagraphStyle(
        "TOCHeading", fontName="Times-Bold", fontSize=18, leading=26,
        spaceAfter=6, underline=True, textColor=BLACK, alignment=TA_LEFT,
    )))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_GRAY, spaceAfter=14))

    item_style = ParagraphStyle("TOCItem", fontName="Times-Roman", fontSize=12,
                                leading=20, leftIndent=20, spaceAfter=4, textColor=BLACK)
    sub_style  = ParagraphStyle("TOCSub",  fontName="Times-Roman", fontSize=10,
                                leading=16, leftIndent=40, textColor=GRAY_TEXT)

    toc_entries = [
        ("1.", "Zone Analysis"),
        ("2.", "Zone-wise Action Table"),
        ("3.", "Final Recommendation & Conclusion"),
        ("4.", "Inspector Details & Certification"),
    ]
    for num, title in toc_entries:
        story.append(Paragraph(f"{num}  {title}", item_style))
        if num == "1.":
            for i, z in enumerate(zones, 1):
                story.append(Paragraph(
                    f"&nbsp;&nbsp;&nbsp;&nbsp;1.{i}  {z.get('zoneLabel', '')}",
                    sub_style,
                ))
    return story


# ── Shared paragraph helpers ──────────────────────────────────────────────────

def _section_title(text: str) -> list:
    return [
        Paragraph(text, ParagraphStyle(
            "SecTitle", fontName="Times-Bold", fontSize=15, leading=22,
            spaceBefore=18, spaceAfter=4, textColor=BLACK,
        )),
        HRFlowable(width="100%", thickness=0.8, color=BLACK, spaceAfter=10),
    ]


def _zone_sub_title(text: str) -> Paragraph:
    return Paragraph(text, ParagraphStyle(
        "ZoneSub", fontName="Times-Bold", fontSize=13, leading=18,
        spaceBefore=14, spaceAfter=6, textColor=BLACK,
    ))


def _body(text: str) -> Paragraph:
    return Paragraph(text, ParagraphStyle(
        "Body", fontName="Times-Roman", fontSize=11, leading=16,
        spaceAfter=6, textColor=BLACK, alignment=TA_JUSTIFY,
    ))


def _small(text: str, color=None) -> Paragraph:
    return Paragraph(text, ParagraphStyle(
        "Small", fontName="Times-Roman", fontSize=9, leading=13,
        textColor=color or GRAY_TEXT,
    ))


def _p(text: str, font="Times-Roman", size=9, color=BLACK, align=TA_LEFT) -> Paragraph:
    """Generic small Paragraph for use inside table cells."""
    return Paragraph(text, ParagraphStyle(
        "_p", fontName=font, fontSize=size, leading=size * 1.35,
        textColor=color, alignment=align,
    ))


# ── Image helpers ─────────────────────────────────────────────────────────────

def _decode_image(img_data: dict, width_pt: float, height_pt: float):
    try:
        raw     = base64.b64decode(img_data.get("base64", ""))
        pil_img = PILImage.open(io.BytesIO(raw))
        if pil_img.mode not in ("RGB", "L"):
            pil_img = pil_img.convert("RGB")
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        pil_img.save(tmp.name, "JPEG", quality=85)
        tmp.close()
        return Image(tmp.name, width=width_pt, height=height_pt)
    except Exception:
        return None


def _zone_images(zone: dict) -> list:
    story  = []
    images = zone.get("images", [])
    label  = zone.get("zoneLabel", "")
    if not images:
        story.append(_small("No images captured for this zone."))
        return story

    IMG_W, IMG_H = 220, 160
    cap_style = ParagraphStyle("ImgCap", fontName="Times-Italic", fontSize=8,
                               leading=12, alignment=TA_CENTER, textColor=GRAY_TEXT)
    pairs = [_decode_image(img, IMG_W, IMG_H) for img in images]
    pairs = [p for p in pairs if p is not None]

    if not pairs:
        story.append(_small("Images could not be rendered."))
        return story

    for i in range(0, len(pairs), 2):
        left      = pairs[i]
        right     = pairs[i + 1] if i + 1 < len(pairs) else Spacer(IMG_W, IMG_H)
        left_cap  = Paragraph(f"{label} — Photo {i + 1}", cap_style)
        right_cap = Paragraph(f"{label} — Photo {i + 2}", cap_style) \
                    if i + 1 < len(pairs) else Paragraph("", cap_style)

        t = Table(
            [[left, right], [left_cap, right_cap]],
            colWidths=[IMG_W + 10, IMG_W + 10],
        )
        t.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, 0),  "MIDDLE"),
            ("VALIGN",        (0, 1), (-1, 1),  "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("BOX",           (0, 0), (0, 0),   0.5, LIGHT_GRAY),
            ("BOX",           (1, 0), (1, 0),   0.5, LIGHT_GRAY),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    return story


# ── Zone analysis section ─────────────────────────────────────────────────────

def _zone_analysis(zones: list, trend_data: dict) -> list:
    story = []
    story += _section_title("1. Zone Analysis")

    body_style   = ParagraphStyle("BodyNorm", fontName="Times-Roman", fontSize=11,
                                  leading=16, spaceAfter=6, alignment=TA_JUSTIFY)
    bullet_style = ParagraphStyle("Bullet", fontName="Times-Roman", fontSize=10,
                                  leading=15, leftIndent=14, spaceAfter=3)
    code_style   = ParagraphStyle("Code", fontName="Times-Italic", fontSize=9,
                                  leading=13, textColor=colors.HexColor("#0055AA"), spaceAfter=4)

    for idx, zone in enumerate(zones):
        findings = zone.get("aiFindings") or {}
        label    = zone.get("zoneLabel", "")
        severity = zone.get("severity", "")
        risk     = findings.get("riskScore", 0)
        delta    = trend_data.get(zone.get("zoneId", ""), {}).get("delta", 0)
        priority = findings.get("maintenancePriority", "—")
        failure  = findings.get("predictedFailureWindow", "N/A")

        story.append(_zone_sub_title(f"1.{idx + 1}  {label}"))

        bg, fg = severity_colors(severity)

        badge_data = [
            [
                _p(f"Severity: {severity}", font="Times-Bold", size=9, color=fg),
                _p(f"Risk Score: {risk}",   font="Times-Bold", size=9),
            ],
            [
                _p(f"Priority: {priority}", font="Times-Roman", size=9),
                _p(f"Failure Window: {failure}", font="Times-Roman", size=9),
            ],
        ]
        USABLE = PAGE_W - 100
        badge_tbl = Table(badge_data, colWidths=[USABLE / 2, USABLE / 2])
        badge_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), bg),
            ("FONTNAME",      (0, 0), (0, 0), "Times-Bold"),
            ("TEXTCOLOR",     (0, 0), (0, 0), fg),
            ("BOX",           (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
            ("INNERGRID",     (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
            ("BACKGROUND",    (0, 1), (-1, 1),  ROW_ALT),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(badge_tbl)
        story.append(Spacer(1, 8))

        anomalies = findings.get("anomalies", [])
        if anomalies:
            story.append(Paragraph("<b>Observed Anomalies:</b>", body_style))
            for a in anomalies:
                story.append(Paragraph(f"\u2022  {a}", bullet_style))

        summary = findings.get("summary", "")
        if summary:
            story.append(Spacer(1, 4))
            story.append(_body(summary))

        codes = findings.get("complianceCodes", [])
        if codes:
            story.append(Paragraph(
                "<b>Applicable Standards:</b>  " + "  ".join(f"[{c}]" for c in codes),
                code_style,
            ))

        delta_str = f"+{delta}" if delta > 0 else str(delta)
        story.append(_small(f"Trend vs previous inspection: {delta_str} points"))
        story.append(Spacer(1, 10))

        story += _zone_images(zone)
        story.append(Spacer(1, 14))

    return story


# ── Zone-wise action table ────────────────────────────────────────────────────

def _zone_action_table(zones: list, report_content: dict) -> list:
    story = []
    story += _section_title("2. Zone-wise Action Table")

    col_widths = [72, 138, 52, 38, 88, 107]   # sum = 495

    header = [
        _p("Zone / Item",          font="Times-Bold", size=8, color=colors.white),
        _p("Description / Anomaly",font="Times-Bold", size=8, color=colors.white),
        _p("Severity",             font="Times-Bold", size=8, color=colors.white),
        _p("Risk",                 font="Times-Bold", size=8, color=colors.white),
        _p("Timeline to Cure",     font="Times-Bold", size=8, color=colors.white),
        _p("Recommended Action",   font="Times-Bold", size=8, color=colors.white),
    ]
    tbl_data  = [header]
    tbl_style = [
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEAD),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]

    sched_lookup = {item.get("zone", ""): item
                    for item in report_content.get("maintenanceSchedule", [])}

    row_idx = 1
    for zone in zones:
        findings   = zone.get("aiFindings") or {}
        label      = zone.get("zoneLabel", "")
        severity   = zone.get("severity", "")
        risk       = str(findings.get("riskScore", "—"))
        priority   = findings.get("maintenancePriority", "P3")
        timeline   = risk_timeline(priority)
        anomalies  = findings.get("anomalies", ["No anomalies recorded"])
        sched      = sched_lookup.get(label, {})
        rec_action = sched.get("action") or f"Review and address {label} findings per priority {priority}"

        bg, fg = severity_colors(severity)

        for a_idx, anomaly in enumerate(anomalies):
            if a_idx == 0:
                row = [
                    _p(label,      font="Times-Bold", size=8),
                    _p(anomaly,    size=8),
                    _p(severity,   font="Times-Bold", size=8, color=fg),
                    _p(risk,       size=8),
                    _p(timeline,   size=8),
                    _p(rec_action, size=8),
                ]
                tbl_style += [
                    ("BACKGROUND", (2, row_idx), (2, row_idx), bg),
                    ("BACKGROUND", (0, row_idx), (1, row_idx), ROW_ALT) if row_idx % 2 == 0
                    else ("BACKGROUND", (0, row_idx), (1, row_idx), colors.white),
                ]
            else:
                row = [
                    _p("", size=8),
                    _p(anomaly, size=8),
                    _p("", size=8),
                    _p("", size=8),
                    _p("", size=8),
                    _p("", size=8),
                ]
            tbl_data.append(row)
            row_idx += 1

    tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(tbl_style))
    story.append(tbl)
    return story


# ── Final recommendation & conclusion ─────────────────────────────────────────

def _build_fallback_summary(session: dict) -> str:
    zones    = session.get("zones", [])
    plant    = session.get("plantName", "the inspected plant")
    total    = len(zones)
    critical = [z for z in zones if z.get("severity", "").lower() == "critical"]
    high     = [z for z in zones if z.get("severity", "").lower() == "high"]
    scores   = [
        (z.get("aiFindings") or {}).get("riskScore", 0)
        for z in zones if z.get("aiFindings")
    ]
    avg_risk = int(sum(scores) / len(scores)) if scores else 0

    lines = [f"This inspection covered {total} zone{'s' if total != 1 else ''} at {plant}."]
    if critical:
        names = ", ".join(z.get("zoneLabel", "") for z in critical)
        lines.append(f"<b>Critical findings</b> were identified in: {names}. Immediate action is required.")
    if high:
        names = ", ".join(z.get("zoneLabel", "") for z in high)
        lines.append(f"<b>High severity issues</b> were noted in: {names}.")
    lines.append(
        f"The overall average risk score across all zones is <b>{avg_risk}</b>. "
        "All findings should be reviewed by a qualified engineer and addressed within the timelines specified."
    )
    return "  ".join(lines)


def _recommendation_section(report_content: dict, session: dict) -> list:
    story = []
    story += _section_title("3. Final Recommendation & Conclusion")

    exec_summary = report_content.get("executiveSummary", "")
    if (not exec_summary
            or "failed" in exec_summary.lower()
            or "review session data manually" in exec_summary.lower()):
        exec_summary = _build_fallback_summary(session)

    story.append(_body(exec_summary))
    story.append(Spacer(1, 10))

    actions = report_content.get("priorityActions", [])
    if not actions:
        for zone in session.get("zones", []):
            findings = zone.get("aiFindings") or {}
            sev      = zone.get("severity", "Low")
            actions.append({
                "zone":      zone.get("zoneLabel", ""),
                "finding":   findings.get("anomalies", ["Review required"])[0],
                "urgency":   sev,
                "riskScore": findings.get("riskScore", 0),
            })

    if actions:
        story.append(Paragraph("Key Recommendations:", ParagraphStyle(
            "RecHead", fontName="Times-Bold", fontSize=11, leading=16,
            spaceBefore=8, spaceAfter=6,
        )))
        for i, act in enumerate(actions, 1):
            urg    = act.get("urgency", "Low")
            _, fg  = severity_colors(urg)
            zone_b = f"<b>{act.get('zone', '')}</b>"
            finding = act.get("finding", "")
            score   = act.get("riskScore", "")
            txt = (
                f"<b>{i}.</b>  [{urg}]  {zone_b} — {finding}"
                + (f"  <i>(Risk score: {score})</i>" if score else "")
            )
            story.append(Paragraph(txt, ParagraphStyle(
                f"ActItem{i}", fontName="Times-Roman", fontSize=10,
                leading=16, leftIndent=16, spaceAfter=5, textColor=fg,
            )))

    comp = report_content.get("complianceSummary", [])
    if comp:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Compliance Status:", ParagraphStyle(
            "CompHead", fontName="Times-Bold", fontSize=11, leading=16,
            spaceBefore=8, spaceAfter=4,
        )))
        c_header = [
            _p("Finding",  font="Times-Bold", size=9, color=colors.white),
            _p("Standard", font="Times-Bold", size=9, color=colors.white),
            _p("Status",   font="Times-Bold", size=9, color=colors.white),
        ]
        c_data  = [c_header]
        c_style = [
            ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEAD),
            ("GRID",          (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]
        status_fg = {
            "Compliant":     GREEN_TEXT,
            "Non-Compliant": RED_TEXT,
            "Needs Review":  AMBER_TEXT,
        }
        for ri, row in enumerate(comp, 1):
            s = row.get("status", "")
            fg = status_fg.get(s, BLACK)
            c_data.append([
                _p(row.get("finding", ""),  size=9),
                _p(row.get("standard", ""), size=9),
                _p(s, font="Times-Bold",    size=9, color=fg),
            ])
            if ri % 2 == 0:
                c_style.append(("BACKGROUND", (0, ri), (-1, ri), ROW_ALT))
        ctbl = Table(c_data, colWidths=[230, 120, 100])
        ctbl.setStyle(TableStyle(c_style))
        story.append(ctbl)

    return story


# ── Inspector details & certification ────────────────────────────────────────

def _inspector_page(session: dict, company_settings: dict) -> list:
    story = []
    story.append(PageBreak())
    story += _section_title("4. Inspector Details & Certification")

    label_style = ParagraphStyle("Lbl", fontName="Times-Bold",   fontSize=10,
                                 leading=15, textColor=GRAY_TEXT)
    value_style = ParagraphStyle("Val", fontName="Times-Roman",  fontSize=11,
                                 leading=16, textColor=BLACK)

    meta = [
        ("Operator / Inspector", session.get("operator",    "—")),
        ("Date of Inspection",   (session.get("created_at", "—") or "—")[:10]),
        ("Plant Name",           session.get("plantName",   "—")),
        ("Section / Area",       session.get("section",     "—")),
        ("Industry",             session.get("industry",    "—")),
        ("Session ID",           session.get("session_id",  "—")),
        ("Company",              company_settings.get("companyName", "—")),
        ("Overall Risk Score",   str(session.get("overallRiskScore", "—"))),
    ]
    tbl_data = [[Paragraph(k, label_style), Paragraph(v, value_style)] for k, v in meta]
    meta_tbl = Table(tbl_data, colWidths=[160, 335])
    meta_tbl.setStyle(TableStyle([
        ("GRID",          (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
        ("BACKGROUND",    (0, 0), (0, -1),  ROW_ALT),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 40))

    story.append(Paragraph("Signatures", ParagraphStyle(
        "SigHead", fontName="Times-Bold", fontSize=12, leading=18,
        spaceBefore=10, spaceAfter=14,
    )))
    for sig_label in ["Inspector / Operator", "Supervisor / Reviewer", "Date"]:
        story.append(HRFlowable(width="55%", thickness=0.6, color=BLACK, spaceAfter=4))
        story.append(Paragraph(sig_label, label_style))
        story.append(Spacer(1, 24))

    story.append(Spacer(1, 20))
    story.append(_small(
        "This report was generated by FieldSense AI. All findings must be verified by a "
        "qualified engineer prior to any remediation or maintenance action. "
        "Unauthorised reproduction of this document is prohibited.",
        color=GRAY_TEXT,
    ))
    return story


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_report(session: dict, report_content: dict, company_settings: dict, trend_data: dict) -> str:
    os.makedirs("reports", exist_ok=True)
    path  = f"reports/{session['session_id']}.pdf"
    zones = session.get("zones", [])

    # ── Story: Cover → PageBreak → TOC → sections ────────────────────────────
    story  = []
    story.append(_CoverPageFlowable(session, company_settings))
    story.append(PageBreak())
    story += _build_toc(zones)
    story.append(PageBreak())
    story += _zone_analysis(zones, trend_data)
    story.append(PageBreak())
    story += _zone_action_table(zones, report_content)
    story.append(PageBreak())
    story += _recommendation_section(report_content, session)
    story += _inspector_page(session, company_settings)

    # ── Single-pass render — no merge required ────────────────────────────────
    def canvas_factory(session_d, settings_d):
        class _C(FooterCanvas):
            def __init__(self, *a, **kw):
                super().__init__(*a, session=session_d, company_settings=settings_d, **kw)
        return _C

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        topMargin=50, bottomMargin=42,
        leftMargin=50, rightMargin=50,
    )
    doc.build(story, canvasmaker=canvas_factory(session, company_settings))
    logger.info(f"[generate_report] written → {path}")
    return path