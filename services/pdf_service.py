import os
import io
import base64
import tempfile
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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage

PAGE_W, PAGE_H = A4

# ── Severity / risk helpers ──────────────────────────────────────────────────

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
        "P2": "Short-term (within 30 days)",
        "P3": "Planned (within 90 days)",
    }.get(priority, "As scheduled")


# ── Footer canvas (applied from page 3 onward; pages 1 & 2 = cover & TOC) ──

class FooterCanvas(canvas.Canvas):
    """Draws a minimal footer on every page except the cover (page index 0)
    and the TOC page (page index 1)."""

    def __init__(self, *args, session=None, company_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session          = session or {}
        self.company_settings = company_settings or {}
        self._saved_pages     = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total       = len(self._saved_pages)
        # Body PDF page layout (cover is merged separately as page 1):
        #   idx 0 → TOC          – no footer
        #   idx 1+ → content     – footer with page numbers 1, 2, 3 …
        content_total = total - 1  # exclude TOC from page count
        for idx, page in enumerate(self._saved_pages):
            self.__dict__.update(page)
            if idx >= 1:                        # skip TOC (idx 0)
                self._draw_footer(idx, content_total)
            super().showPage()
        super().save()

    def _draw_footer(self, page_idx: int, content_total: int):
        """Tiny three-column footer: page# | CONFIDENTIAL | company name"""
        self.saveState()
        y       = 18
        company = self.company_settings.get("companyName", "")
        page_no = page_idx          # content pages: 1, 2, 3 …
        # thin rule
        self.setStrokeColor(LIGHT_GRAY)
        self.setLineWidth(0.5)
        self.line(36, y + 10, PAGE_W - 36, y + 10)
        # text – 7pt Times-Roman
        self.setFont("Times-Roman", 7)
        self.setFillColor(GRAY_TEXT)
        self.drawString(36, y, f"Page {page_no}")              # left
        self.drawCentredString(PAGE_W / 2, y, "CONFIDENTIAL")  # centre
        self.drawRightString(PAGE_W - 36, y, company)           # right
        self.restoreState()


# ── Cover page (pure canvas) ──────────────────────────────────────────────────

def _draw_cover(c: canvas.Canvas, session: dict, company_settings: dict):
    """White, minimal, corporate cover – no colours."""
    plant_name   = session.get("plantName", "")
    operator     = session.get("operator", "")
    company      = company_settings.get("companyName", "")
    zones        = session.get("zones", [])
    panel_names  = ", ".join(z.get("zoneLabel", "") for z in zones) if zones else "All Zones"

    # ── Heading: two centered lines, largest font size that fits the page ────
    from reportlab.pdfbase.pdfmetrics import stringWidth
    MARGIN = 60
    MAX_W  = PAGE_W - MARGIN * 2
    line1  = "Inspection Report on"
    line2  = f'"{plant_name}"'
    font   = "Times-Bold"
    size   = 36
    while size >= 14:
        if max(stringWidth(line1, font, size), stringWidth(line2, font, size)) <= MAX_W:
            break
        size -= 1
    leading = size * 1.28
    top_y   = PAGE_H - 196
    c.setFont(font, size)
    c.setFillColor(BLACK)
    c.drawCentredString(PAGE_W / 2, top_y,           line1)
    c.drawCentredString(PAGE_W / 2, top_y - leading, line2)
    rule_y = top_y - leading - 18
    # thin rule below heading
    c.setStrokeColor(BLACK)
    c.setLineWidth(0.6)
    c.line(60, rule_y, PAGE_W - 60, rule_y)

    # ── Sub-heading: detailed analysis report on [panel names] ────────────────
    c.setFont("Times-Roman", 9)
    c.setFillColor(GRAY_TEXT)
    sub = f"Detailed analysis report on {panel_names}"
    c.drawCentredString(PAGE_W / 2, rule_y - 22, sub)

    # ── Gap then inspected-by line ────────────────────────────────────────────
    c.setFont("Times-Roman", 10)
    c.setFillColor(BLACK)
    c.drawCentredString(PAGE_W / 2, rule_y - 72, f"Inspected by  {operator}")

    # ── Company name ──────────────────────────────────────────────────────────
    c.setFont("Times-Roman", 10)
    c.setFillColor(GRAY_TEXT)
    c.drawCentredString(PAGE_W / 2, rule_y - 90, company)


# ── Table-of-Contents page ────────────────────────────────────────────────────

def _build_toc(zones: list) -> list:
    """Return platypus story elements for the TOC page."""
    story = []

    heading_style = ParagraphStyle(
        "TOCHeading",
        fontName="Times-Bold",
        fontSize=18,
        leading=26,
        spaceAfter=6,
        underline=True,
        textColor=BLACK,
        alignment=TA_LEFT,
    )
    item_style = ParagraphStyle(
        "TOCItem",
        fontName="Times-Roman",
        fontSize=12,
        leading=20,
        leftIndent=20,
        spaceAfter=4,
        textColor=BLACK,
    )

    story.append(Paragraph("Table of Contents", heading_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_GRAY, spaceAfter=14))

    toc_entries = [
        ("1.", "Zone Analysis"),
        ("2.", "Zone-wise Action Table"),
        ("3.", "Final Recommendation & Conclusion"),
        ("4.", "Inspector Details & Certification"),
    ]
    # Inject zone sub-entries under Zone Analysis
    for num, title in toc_entries:
        story.append(Paragraph(f"{num}  {title}", item_style))
        if num == "1.":
            for i, z in enumerate(zones, 1):
                story.append(Paragraph(
                    f"&nbsp;&nbsp;&nbsp;&nbsp;1.{i}  {z.get('zoneLabel', '')}",
                    ParagraphStyle("TOCSub", fontName="Times-Roman", fontSize=10,
                                   leading=16, leftIndent=40, textColor=GRAY_TEXT),
                ))

    return story


# ── Helpers ───────────────────────────────────────────────────────────────────

def _section_title(text: str) -> list:
    """Bold Times section header with underline rule."""
    style = ParagraphStyle(
        "SecTitle",
        fontName="Times-Bold",
        fontSize=15,
        leading=22,
        spaceBefore=18,
        spaceAfter=4,
        textColor=BLACK,
    )
    return [
        Paragraph(text, style),
        HRFlowable(width="100%", thickness=0.8, color=BLACK, spaceAfter=10),
    ]


def _zone_sub_title(text: str) -> Paragraph:
    return Paragraph(text, ParagraphStyle(
        "ZoneSub",
        fontName="Times-Bold",
        fontSize=13,
        leading=18,
        spaceBefore=14,
        spaceAfter=6,
        textColor=BLACK,
    ))


def _body(text: str) -> Paragraph:
    return Paragraph(text, ParagraphStyle(
        "Body",
        fontName="Times-Roman",
        fontSize=11,
        leading=16,
        spaceAfter=6,
        textColor=BLACK,
        alignment=TA_JUSTIFY,
    ))


def _small(text: str, color=None) -> Paragraph:
    return Paragraph(text, ParagraphStyle(
        "Small",
        fontName="Times-Roman",
        fontSize=9,
        leading=13,
        textColor=color or GRAY_TEXT,
    ))


def _decode_image(img_data: dict, width_pt: float, height_pt: float):
    """Decode a base64 image dict and return a ReportLab Image object, or None."""
    try:
        raw     = base64.b64decode(img_data.get("base64", ""))
        pil_img = PILImage.open(io.BytesIO(raw))
        # Convert RGBA / palette → RGB so JPEG save works
        if pil_img.mode not in ("RGB", "L"):
            pil_img = pil_img.convert("RGB")
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        pil_img.save(tmp.name, "JPEG", quality=85)
        tmp.close()
        return Image(tmp.name, width=width_pt, height=height_pt)
    except Exception:
        return None


# ── Zone images layout ────────────────────────────────────────────────────────

def _zone_images(zone: dict) -> list:
    """Return a story block with zone images in a 2-up grid with captions."""
    story    = []
    images   = zone.get("images", [])
    label    = zone.get("zoneLabel", "")
    if not images:
        story.append(_small("No images captured for this zone."))
        return story

    IMG_W, IMG_H = 220, 160
    cap_style = ParagraphStyle("ImgCap", fontName="Times-Italic", fontSize=8,
                               leading=12, alignment=TA_CENTER, textColor=GRAY_TEXT)

    pairs = []
    for img_data in images:
        rl_img = _decode_image(img_data, IMG_W, IMG_H)
        if rl_img:
            pairs.append(rl_img)

    if not pairs:
        story.append(_small("Images could not be rendered."))
        return story

    # Arrange in rows of 2
    for i in range(0, len(pairs), 2):
        left  = pairs[i]
        right = pairs[i + 1] if i + 1 < len(pairs) else Spacer(IMG_W, IMG_H)
        left_cap  = Paragraph(f"{label} — Photo {i + 1}", cap_style)
        right_cap = Paragraph(f"{label} — Photo {i + 2}", cap_style) if i + 1 < len(pairs) else Paragraph("", cap_style)

        t = Table(
            [[left,     right],
             [left_cap, right_cap]],
            colWidths=[IMG_W + 10, IMG_W + 10],
        )
        t.setStyle(TableStyle([
            ("ALIGN",   (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",  (0, 0), (-1, 0),  "MIDDLE"),
            ("VALIGN",  (0, 1), (-1, 1),  "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            # thin border around each image cell
            ("BOX",  (0, 0), (0, 0), 0.5, LIGHT_GRAY),
            ("BOX",  (1, 0), (1, 0), 0.5, LIGHT_GRAY),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    return story


# ── Zone action table ─────────────────────────────────────────────────────────

def _zone_action_table(zones: list, report_content: dict) -> list:
    """Build the consolidated zone-wise action table."""
    story = []
    story += _section_title("2. Zone-wise Action Table")

    header = ["Zone / Item", "Description / Anomaly", "Severity", "Risk Score",
              "Timeline to Cure", "Recommended Action"]
    col_widths = [70, 140, 55, 50, 90, 115]

    tbl_data  = [header]
    tbl_style = [
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEAD),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Times-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME",      (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, ROW_ALT]),
    ]

    # Build a lookup: zone label → maintenance schedule entry
    sched_lookup = {}
    for item in report_content.get("maintenanceSchedule", []):
        sched_lookup[item.get("zone", "")] = item

    row_idx = 1
    for zone in zones:
        findings  = zone.get("aiFindings") or {}
        label     = zone.get("zoneLabel", "")
        severity  = zone.get("severity", "")
        risk      = findings.get("riskScore", "—")
        priority  = findings.get("maintenancePriority", "P3")
        timeline  = risk_timeline(priority)
        anomalies = findings.get("anomalies", ["No anomalies recorded"])
        sched     = sched_lookup.get(label, {})
        rec_action = sched.get("action", findings.get("summary", "—"))

        # One row per anomaly, first row carries zone label
        for a_idx, anomaly in enumerate(anomalies):
            zone_cell = label if a_idx == 0 else ""
            sev_cell  = severity if a_idx == 0 else ""
            risk_cell = str(risk) if a_idx == 0 else ""
            time_cell = timeline if a_idx == 0 else ""
            rec_cell  = rec_action if a_idx == 0 else ""

            tbl_data.append([zone_cell, anomaly, sev_cell, risk_cell, time_cell, rec_cell])

            if a_idx == 0 and severity:
                bg, fg = severity_colors(severity)
                tbl_style.append(("BACKGROUND", (2, row_idx), (2, row_idx), bg))
                tbl_style.append(("TEXTCOLOR",  (2, row_idx), (2, row_idx), fg))
                tbl_style.append(("FONTNAME",   (2, row_idx), (2, row_idx), "Times-Bold"))
            row_idx += 1

    tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(tbl_style))
    story.append(tbl)
    return story


# ── Final recommendation & conclusion ─────────────────────────────────────────

def _recommendation_section(report_content: dict, session: dict) -> list:
    story = []
    story += _section_title("3. Final Recommendation & Conclusion")

    exec_summary = report_content.get("executiveSummary", "")
    story.append(_body(exec_summary))
    story.append(Spacer(1, 10))

    # Priority action highlights
    actions = report_content.get("priorityActions", [])
    if actions:
        story.append(Paragraph("Key Recommendations:", ParagraphStyle(
            "RecHead", fontName="Times-Bold", fontSize=11, leading=16,
            spaceBefore=8, spaceAfter=4)))
        for i, act in enumerate(actions, 1):
            urg = act.get("urgency", "Low")
            _, fg = severity_colors(urg)
            txt  = (f"<b>{i}.</b> [{urg}]  <b>{act.get('zone', '')}</b> — "
                    f"{act.get('finding', '')}")
            story.append(Paragraph(txt, ParagraphStyle(
                f"ActItem{i}", fontName="Times-Roman", fontSize=10,
                leading=15, leftIndent=16, spaceAfter=3, textColor=fg)))

    # Compliance summary
    comp = report_content.get("complianceSummary", [])
    if comp:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Compliance Status:", ParagraphStyle(
            "CompHead", fontName="Times-Bold", fontSize=11, leading=16,
            spaceBefore=8, spaceAfter=4)))
        c_header = ["Finding", "Standard", "Status"]
        c_data   = [c_header]
        c_style  = [
            ("BACKGROUND",    (0, 0), (-1, 0), TABLE_HEAD),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("GRID",          (0, 0), (-1, -1), 0.4, LIGHT_GRAY),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME",      (0, 1), (-1, -1), "Times-Roman"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ]
        status_fg = {"Compliant": GREEN_TEXT, "Non-Compliant": RED_TEXT, "Needs Review": AMBER_TEXT}
        for ri, row in enumerate(comp, 1):
            s   = row.get("status", "")
            c_data.append([row.get("finding", ""), row.get("standard", ""), s])
            if s in status_fg:
                c_style.append(("TEXTCOLOR",  (2, ri), (2, ri), status_fg[s]))
                c_style.append(("FONTNAME",   (2, ri), (2, ri), "Times-Bold"))
        ctbl = Table(c_data, colWidths=[230, 120, 100])
        ctbl.setStyle(TableStyle(c_style))
        story.append(ctbl)

    return story


# ── Inspector details & signature ─────────────────────────────────────────────

def _inspector_page(session: dict, company_settings: dict) -> list:
    story = []
    story.append(PageBreak())
    story += _section_title("4. Inspector Details & Certification")

    label_style = ParagraphStyle("Lbl", fontName="Times-Bold", fontSize=10,
                                 leading=15, textColor=GRAY_TEXT)
    value_style = ParagraphStyle("Val", fontName="Times-Roman", fontSize=11,
                                 leading=16, textColor=BLACK)

    meta = [
        ("Operator / Inspector", session.get("operator", "—")),
        ("Date of Inspection",   session.get("created_at", "—")[:10]),
        ("Plant Name",           session.get("plantName", "—")),
        ("Section / Area",       session.get("section", "—")),
        ("Industry",             session.get("industry", "—")),
        ("Session ID",           session.get("session_id", "—")),
        ("Company",              company_settings.get("companyName", "—")),
        ("Overall Risk Score",   str(session.get("overallRiskScore", "—"))),
    ]
    tbl_data = [[Paragraph(k, label_style), Paragraph(v, value_style)] for k, v in meta]
    meta_tbl = Table(tbl_data, colWidths=[160, 330])
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

    # Signature lines
    story.append(Paragraph("Signatures", ParagraphStyle("SigHead", fontName="Times-Bold",
                            fontSize=12, leading=18, spaceBefore=10, spaceAfter=14)))
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
    path     = f"reports/{session['session_id']}.pdf"
    zones    = session.get("zones", [])

    # ── 1. Draw cover page onto a temporary PDF ───────────────────────────────
    cover_path = path + ".cover.pdf"
    c = canvas.Canvas(cover_path, pagesize=A4)
    _draw_cover(c, session, company_settings)
    c.showPage()
    c.save()

    # ── 2. Build story (TOC → Analysis → Action table → Recommendation → Inspector) ──
    story = []

    # TOC page
    story += _build_toc(zones)
    story.append(PageBreak())

    # ── Section 1: Zone-by-Zone Analysis with images ──────────────────────────
    story += _section_title("1. Zone Analysis")

    body_style = ParagraphStyle("BodyNorm", fontName="Times-Roman", fontSize=11,
                                leading=16, spaceAfter=6, alignment=TA_JUSTIFY)
    bullet_style = ParagraphStyle("Bullet", fontName="Times-Roman", fontSize=10,
                                  leading=15, leftIndent=14, spaceAfter=3)
    code_style = ParagraphStyle("Code", fontName="Times-Italic", fontSize=9,
                                leading=13, textColor=colors.HexColor("#0055AA"), spaceAfter=4)

    for zone in zones:
        findings  = zone.get("aiFindings") or {}
        label     = zone.get("zoneLabel", "")
        severity  = zone.get("severity", "")
        risk      = findings.get("riskScore", 0)
        trend     = trend_data.get(zone.get("zoneId", ""), {})
        delta     = trend.get("delta", 0)

        # Zone sub-title
        story.append(_zone_sub_title(f"1.{zones.index(zone)+1}  {label}"))

        # Severity badge row
        bg, fg = severity_colors(severity)
        badge_data = [[f"Severity: {severity}", f"Risk Score: {risk}", f"Priority: {findings.get('maintenancePriority','—')}",
                       f"Failure Window: {findings.get('predictedFailureWindow','N/A')}"]]
        badge_tbl = Table(badge_data, colWidths=[120, 100, 90, 150])
        badge_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), bg),
            ("TEXTCOLOR",     (0, 0), (0, 0), fg),
            ("FONTNAME",      (0, 0), (-1, 0), "Times-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 9),
            ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
            ("VALIGN",        (0, 0), (-1, 0), "MIDDLE"),
            ("BOX",           (0, 0), (-1, 0), 0.4, LIGHT_GRAY),
            ("INNERGRID",     (0, 0), (-1, 0), 0.4, LIGHT_GRAY),
            ("TOPPADDING",    (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ]))
        story.append(badge_tbl)
        story.append(Spacer(1, 8))

        # Anomalies
        anomalies = findings.get("anomalies", [])
        if anomalies:
            story.append(Paragraph("<b>Observed Anomalies:</b>", body_style))
            for a in anomalies:
                story.append(Paragraph(f"\u2022  {a}", bullet_style))

        # Summary
        summary = findings.get("summary", "")
        if summary:
            story.append(Spacer(1, 4))
            story.append(_body(summary))

        # Compliance codes
        codes = findings.get("complianceCodes", [])
        if codes:
            story.append(Paragraph(
                "Applicable Standards: " + "  ".join(f"[{c}]" for c in codes),
                code_style
            ))

        # Trend note
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        trend_note = f"Trend vs previous inspection: {delta_str} points"
        story.append(_small(trend_note))
        story.append(Spacer(1, 10))

        # Images
        story += _zone_images(zone)
        story.append(Spacer(1, 14))

    story.append(PageBreak())

    # ── Section 2: Zone-wise Action Table ────────────────────────────────────
    story += _zone_action_table(zones, report_content)
    story.append(PageBreak())

    # ── Section 3: Final Recommendation & Conclusion ──────────────────────────
    story += _recommendation_section(report_content, session)

    # ── Section 4: Inspector Details & Certification ──────────────────────────
    story += _inspector_page(session, company_settings)

    # ── 3. Render story pages with footer canvas ──────────────────────────────
    tmp_path = path + ".body.pdf"

    def canvas_factory(session_d, settings_d):
        class _C(FooterCanvas):
            def __init__(self, *a, **kw):
                super().__init__(*a, session=session_d, company_settings=settings_d, **kw)
        return _C

    doc = SimpleDocTemplate(
        tmp_path, pagesize=A4,
        topMargin=50, bottomMargin=42,
        leftMargin=50, rightMargin=50,
    )
    doc.build(story, canvasmaker=canvas_factory(session, company_settings))

    # ── 4. Merge cover + body ─────────────────────────────────────────────────
    try:
        import pypdf
        merger = pypdf.PdfWriter()
        for src in [cover_path, tmp_path]:
            reader = pypdf.PdfReader(src)
            for pg in reader.pages:
                merger.add_page(pg)
        with open(path, "wb") as f:
            merger.write(f)
        os.remove(cover_path)
        os.remove(tmp_path)
    except Exception:
        # Fallback: ship body only
        os.rename(tmp_path, path)
        if os.path.exists(cover_path):
            os.remove(cover_path)

    return path