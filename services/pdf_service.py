import os
import io
import base64
import tempfile
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm, inch
pt = 1.0  # In ReportLab, 1 point == 1 unit; 'pt' is not exported by reportlab.lib.units
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from PIL import Image as PILImage

PAGE_W, PAGE_H = A4

# Colors
DARK_BG = colors.HexColor("#1A1A2E")
TEAL = colors.HexColor("#0F6E56")
MUTED_WHITE = colors.HexColor("#8888AA")
RED_BG = colors.HexColor("#FCEBEB")
AMBER_BG = colors.HexColor("#FAEEDA")
GREEN_BG = colors.HexColor("#EAF3DE")
RED_TEXT = colors.HexColor("#A32D2D")
AMBER_TEXT = colors.HexColor("#854F0B")
GREEN_TEXT = colors.HexColor("#3B6D11")
GRAY_TEXT = colors.HexColor("#666666")


def risk_color(score: int):
    if score >= 70:
        return colors.HexColor("#E24B4A")
    elif score >= 40:
        return colors.HexColor("#EF9F27")
    return colors.HexColor("#639922")


def priority_colors(p: str):
    return {
        "P1": (colors.HexColor("#FCEBEB"), RED_TEXT),
        "P2": (colors.HexColor("#FAEEDA"), AMBER_TEXT),
        "P3": (colors.HexColor("#EAF3DE"), GREEN_TEXT),
    }.get(p, (colors.white, colors.black))


def status_color(s: str):
    return {
        "Compliant": GREEN_TEXT,
        "Non-Compliant": RED_TEXT,
        "Needs Review": AMBER_TEXT,
    }.get(s, colors.black)


class HeaderFooterCanvas(canvas.Canvas):
    def __init__(self, *args, session=None, company_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session or {}
        self.company_settings = company_settings or {}
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for i, page in enumerate(self._pages):
            self.__dict__.update(page)
            if i > 0:
                self._draw_header_footer(i + 1, total)
            super().showPage()
        super().save()

    def _draw_header_footer(self, page_num, total):
        self.saveState()
        # Header
        self.setFillColor(DARK_BG)
        self.rect(0, PAGE_H - 28, PAGE_W, 28, fill=1, stroke=0)
        self.setFillColor(colors.white)
        self.setFont("Helvetica-Bold", 10)
        self.drawString(36, PAGE_H - 18, "FieldSense")
        self.setFont("Helvetica", 10)
        self.drawRightString(PAGE_W - 36, PAGE_H - 18, self.session.get("session_id", ""))
        # Footer
        self.setStrokeColor(GRAY_TEXT)
        self.setLineWidth(0.5)
        self.line(36, 30, PAGE_W - 36, 30)
        self.setFillColor(GRAY_TEXT)
        self.setFont("Helvetica", 9)
        self.drawString(36, 18, self.session.get("plantName", ""))
        self.setFont("Helvetica-Bold", 9)
        self.drawCentredString(PAGE_W / 2, 18, self.company_settings.get("companyName", ""))
        self.setFont("Helvetica", 9)
        self.drawRightString(PAGE_W - 36, 18, f"Page {page_num} of {total}")
        self.restoreState()


def _cover_page(c, session, company_settings):
    c.setFillColor(DARK_BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Company name top-left
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 14)
    c.drawString(36, PAGE_H - 50, company_settings.get("companyName", "FieldSense"))

    # FieldSense logo
    c.setFont("Helvetica-Bold", 42)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 160, "FieldSense")

    # Inspection Report
    c.setFont("Helvetica", 18)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 195, "I n s p e c t i o n   R e p o r t")

    # Teal rule
    c.setStrokeColor(TEAL)
    c.setLineWidth(2)
    c.line(60, PAGE_H - 215, PAGE_W - 60, PAGE_H - 215)

    # Session ID + date
    c.setFillColor(MUTED_WHITE)
    c.setFont("Helvetica", 13)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 240, f"{session.get('session_id', '')}  •  {session.get('created_at', '')[:10]}")

    # Stat boxes
    stats = [
        ("Total Zones", str(len(session.get("zones", [])))),
        ("Overall Risk Score", str(session.get("overallRiskScore", 0))),
        ("Critical Findings", str(sum(1 for z in session.get("zones", []) if z.get("severity") == "Critical"))),
    ]
    box_w, box_h = 130, 60
    start_x = (PAGE_W - (box_w * 3 + 20)) / 2
    for i, (label, value) in enumerate(stats):
        bx = start_x + i * (box_w + 10)
        by = PAGE_H - 340
        c.setStrokeColor(colors.white)
        c.setFillColor(DARK_BG)
        c.setLineWidth(1)
        c.rect(bx, by, box_w, box_h, fill=1, stroke=1)
        c.setFillColor(MUTED_WHITE)
        c.setFont("Helvetica", 9)
        c.drawCentredString(bx + box_w / 2, by + 42, label)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(bx + box_w / 2, by + 16, value)

    # Risk oval
    score = session.get("overallRiskScore", 0)
    oval_color = risk_color(score)
    c.setFillColor(oval_color)
    c.ellipse(PAGE_W / 2 - 55, PAGE_H - 440, PAGE_W / 2 + 55, PAGE_H - 370, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 36)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 415, str(score))
    c.setFont("Helvetica", 10)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 445, "OVERALL RISK SCORE")

    # Plant + section
    c.setFillColor(MUTED_WHITE)
    c.setFont("Helvetica", 11)
    c.drawCentredString(PAGE_W / 2, 80, session.get("plantName", ""))
    c.drawCentredString(PAGE_W / 2, 62, session.get("section", ""))

    # Company bottom
    c.setFont("Helvetica", 10)
    c.drawCentredString(PAGE_W / 2, 40, company_settings.get("companyName", ""))


def _section_header(title: str, styles) -> list:
    style = ParagraphStyle(
        "SectionHeader",
        fontSize=13,
        textColor=colors.white,
        backColor=DARK_BG,
        fontName="Helvetica-Bold",
        spaceAfter=10,
        spaceBefore=14,
        leftIndent=8,
        leading=20,
    )
    return [Paragraph(title, style), Spacer(1, 6)]


def generate_report(session: dict, report_content: dict, company_settings: dict, trend_data: dict) -> str:
    os.makedirs("reports", exist_ok=True)
    path = f"reports/{session['session_id']}.pdf"
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle("Body", fontSize=11, leading=15.4, spaceAfter=8)
    label_style = ParagraphStyle("Label", fontSize=10, textColor=GRAY_TEXT)
    italic_style = ParagraphStyle("Italic", fontSize=10, fontName="Helvetica-Oblique", textColor=GRAY_TEXT)
    toc_style = ParagraphStyle("TOC", fontSize=13, fontName="Helvetica-Bold", spaceAfter=14)

    story = []

    # --- TABLE OF CONTENTS (page 1 in story; cover drawn separately) ---
    story.append(Paragraph("Table of Contents", ParagraphStyle("TOCHead", fontSize=20, fontName="Helvetica-Bold", spaceAfter=20)))
    toc_items = [
        "01  Executive Summary",
        "02  Priority Action List",
        "03  Zone-by-Zone Analysis",
        "04  Photo Documentation",
        "05  Trend Memory",
        "06  Predictive Maintenance Schedule",
        "07  Compliance Mapping",
    ]
    for item in toc_items:
        story.append(Paragraph(item, ParagraphStyle("TOCItem", fontSize=12, spaceAfter=10, leftIndent=10)))
    story.append(PageBreak())

    # --- SECTION 01: EXECUTIVE SUMMARY ---
    story += _section_header("01  Executive Summary", styles)
    story.append(Paragraph(report_content.get("executiveSummary", ""), body_style))
    story.append(Spacer(1, 10))
    meta = [
        ["Operator", session.get("operator", "")],
        ["Date", session.get("created_at", "")[:10]],
        ["Industry", session.get("industry", "")],
        ["Plant", session.get("plantName", "")],
        ["Section", session.get("section", "")],
    ]
    meta_table = Table([[Paragraph(k, label_style), Paragraph(v, body_style)] for k, v in meta], colWidths=[120, 340])
    meta_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F5F5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(PageBreak())

    # --- SECTION 02: PRIORITY ACTION LIST ---
    story += _section_header("02  Priority Action List", styles)
    pa_data = [["Priority", "Zone", "Finding", "Risk Score", "Urgency"]]
    urgency_bg = {"Critical": RED_BG, "High": AMBER_BG, "Medium": AMBER_BG, "Low": GREEN_BG}
    urgency_fg = {"Critical": RED_TEXT, "High": AMBER_TEXT, "Medium": AMBER_TEXT, "Low": GREEN_TEXT}
    pa_style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]
    for i, action in enumerate(report_content.get("priorityActions", []), 1):
        urg = action.get("urgency", "Low")
        pa_data.append([
            str(i), action.get("zone", ""), action.get("finding", ""),
            str(action.get("riskScore", "")), urg,
        ])
        pa_style.append(("BACKGROUND", (0, i), (-1, i), urgency_bg.get(urg, colors.white)))
        pa_style.append(("TEXTCOLOR", (4, i), (4, i), urgency_fg.get(urg, colors.black)))

    pa_table = Table(pa_data, colWidths=[40, 90, 210, 70, 70])
    pa_table.setStyle(TableStyle(pa_style))
    story.append(pa_table)
    story.append(PageBreak())

    # --- SECTION 03: ZONE-BY-ZONE ANALYSIS ---
    story += _section_header("03  Zone-by-Zone Analysis", styles)
    severity_colors_map = {"Critical": RED_TEXT, "High": AMBER_TEXT, "Medium": AMBER_TEXT, "Low": GREEN_TEXT}
    for zone in session.get("zones", []):
        findings_obj = zone.get("aiFindings") or {}
        zone_id = zone.get("zoneId", "")
        severity = zone.get("severity", "")
        trend = trend_data.get(zone_id, {})

        zone_header = ParagraphStyle(
            "ZoneH", fontSize=11, fontName="Helvetica-Bold",
            textColor=colors.white, backColor=colors.HexColor("#2A2A4E"),
            leftIndent=6, leading=18, spaceAfter=6, spaceBefore=10,
        )
        story.append(Paragraph(f"{zone.get('zoneLabel', '')}  [{severity}]", zone_header))

        for anomaly in findings_obj.get("anomalies", []):
            story.append(Paragraph(f"• {anomaly}", body_style))

        delta = trend.get("delta", 0)
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        story.append(Paragraph(f"<i>Trend note: {delta_str} from previous inspection</i>", italic_style))

        prio = findings_obj.get("maintenancePriority", "P3")
        prio_color = RED_TEXT if prio == "P1" else (AMBER_TEXT if prio == "P2" else GREEN_TEXT)
        story.append(Paragraph(
            f"Predicted failure: {findings_obj.get('predictedFailureWindow', 'N/A')}",
            ParagraphStyle("Fail", fontSize=10, textColor=prio_color),
        ))

        codes = "  ".join([f"[{c}]" for c in findings_obj.get("complianceCodes", [])])
        if codes:
            story.append(Paragraph(codes, ParagraphStyle("Codes", fontSize=9, textColor=TEAL)))
        story.append(Spacer(1, 8))
    story.append(PageBreak())

    # --- SECTION 04: PHOTO DOCUMENTATION ---
    story += _section_header("04  Photo Documentation", styles)
    for zone in session.get("zones", []):
        story.append(Paragraph(zone.get("zoneLabel", ""), ParagraphStyle("ZoneSub", fontSize=11, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=8)))
        images = zone.get("images", [])
        if not images:
            story.append(Paragraph("No photos captured for this zone.", italic_style))
            continue
        img_row = []
        for img_data in images:
            try:
                raw = base64.b64decode(img_data.get("base64", ""))
                pil_img = PILImage.open(io.BytesIO(raw))
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                pil_img.save(tmp.name, "JPEG")
                tmp.close()
                rl_img = Image(tmp.name, width=220, height=160)
                caption = Paragraph(zone.get("zoneLabel", ""), ParagraphStyle("Cap", fontSize=9, textColor=GRAY_TEXT, alignment=TA_CENTER))
                img_row.append([rl_img, caption])
                if len(img_row) == 2:
                    t = Table([[img_row[0][0], img_row[1][0]], [img_row[0][1], img_row[1][1]]], colWidths=[240, 240])
                    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
                    story.append(t)
                    story.append(Spacer(1, 8))
                    img_row = []
            except Exception:
                story.append(Paragraph("Image could not be rendered.", italic_style))
        if img_row:
            t = Table([[img_row[0][0]], [img_row[0][1]]], colWidths=[240])
            t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
            story.append(t)
    story.append(PageBreak())

    # --- SECTION 05: TREND MEMORY ---
    story += _section_header("05  Trend Memory", styles)
    trend_table_data = [["Zone", "Previous Score", "Current Score", "Change", "Trend"]]
    for zone in session.get("zones", []):
        zid = zone.get("zoneId", "")
        t = trend_data.get(zid, {})
        current = (zone.get("aiFindings") or {}).get("riskScore", 0)
        prev = t.get("previousScore", current)
        delta = t.get("delta", 0)
        delta_label = f"+{delta}" if delta > 0 else str(delta)
        if delta > 0:
            trend_label = "↑ Worsening"
        elif delta < 0:
            trend_label = "↓ Improving"
        else:
            trend_label = "→ Stable"
        trend_table_data.append([zone.get("zoneLabel", ""), str(prev), str(current), delta_label, trend_label])

    trend_table = Table(trend_table_data, colWidths=[120, 100, 100, 80, 100])
    trend_style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]
    for i, zone in enumerate(session.get("zones", []), 1):
        delta = trend_data.get(zone.get("zoneId", ""), {}).get("delta", 0)
        if delta > 0:
            trend_style.append(("TEXTCOLOR", (3, i), (3, i), RED_TEXT))
            trend_style.append(("TEXTCOLOR", (4, i), (4, i), RED_TEXT))
        elif delta < 0:
            trend_style.append(("TEXTCOLOR", (3, i), (3, i), GREEN_TEXT))
            trend_style.append(("TEXTCOLOR", (4, i), (4, i), GREEN_TEXT))
    trend_table.setStyle(TableStyle(trend_style))
    story.append(trend_table)
    story.append(PageBreak())

    # --- SECTION 06: MAINTENANCE SCHEDULE ---
    story += _section_header("06  Predictive Maintenance Schedule", styles)
    ms_data = [["Zone", "Issue", "Priority", "Recommended Action", "Timeframe"]]
    ms_style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]
    for i, item in enumerate(report_content.get("maintenanceSchedule", []), 1):
        p = item.get("priority", "P3")
        bg, fg = priority_colors(p)
        ms_data.append([item.get("zone", ""), item.get("issue", ""), p, item.get("action", ""), item.get("timeframe", "")])
        ms_style.append(("BACKGROUND", (2, i), (2, i), bg))
        ms_style.append(("TEXTCOLOR", (2, i), (2, i), fg))
        ms_style.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))

    ms_table = Table(ms_data, colWidths=[80, 120, 55, 170, 75])
    ms_table.setStyle(TableStyle(ms_style))
    story.append(ms_table)
    story.append(PageBreak())

    # --- SECTION 07: COMPLIANCE MAPPING ---
    story += _section_header("07  Compliance Mapping", styles)
    comp_data = [["Finding", "Standard Code", "Standard Name", "Status"]]
    compliance_names = {
        "OSHA 1910.303": "Electrical wiring methods",
        "ISO 50001": "Energy management systems",
        "IEC 60079-14": "Explosive atmospheres",
        "API 570": "Piping inspection code",
        "NFPA 72": "Fire alarm and signaling",
        "ISO 45001": "Occupational health and safety",
        "API 510": "Pressure vessel inspection",
        "ASHRAE 15": "Refrigeration safety",
    }
    comp_style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]
    for i, item in enumerate(report_content.get("complianceSummary", []), 1):
        std = item.get("standard", "")
        s = item.get("status", "")
        comp_data.append([item.get("finding", ""), std, compliance_names.get(std, std), s])
        comp_style.append(("TEXTCOLOR", (3, i), (3, i), status_color(s)))
        comp_style.append(("FONTNAME", (3, i), (3, i), "Helvetica-Bold"))

    comp_table = Table(comp_data, colWidths=[160, 90, 130, 100])
    comp_table.setStyle(TableStyle(comp_style))
    story.append(comp_table)
    story.append(Spacer(1, 30))

    # --- SIGNATURE BLOCK ---
    story.append(Paragraph("Report Certification", ParagraphStyle("SigHead", fontSize=14, fontName="Helvetica-Bold", spaceAfter=20)))
    for label in ["Operator", "Supervisor", "Date"]:
        story.append(HRFlowable(width="60%", thickness=0.5, color=GRAY_TEXT))
        story.append(Paragraph(label, label_style))
        story.append(Spacer(1, 20))
    story.append(Paragraph(
        "This report was generated by FieldSense AI. All findings should be verified by a qualified engineer before remediation.",
        ParagraphStyle("Disclaimer", fontSize=9, textColor=GRAY_TEXT, fontName="Helvetica-Oblique"),
    ))

    # Build PDF with cover as first page
    doc = SimpleDocTemplate(
        path, pagesize=A4,
        topMargin=50, bottomMargin=50,
        leftMargin=36, rightMargin=36,
    )

    class MyCanvas(HeaderFooterCanvas):
        pass

    # We build normally; cover is page 0 (no header/footer)
    # We draw cover manually on a temp canvas then prepend
    from reportlab.lib.utils import ImageReader
    import copy

    # Build story pages
    tmp_path = path + ".tmp.pdf"
    doc2 = SimpleDocTemplate(
        tmp_path, pagesize=A4,
        topMargin=50, bottomMargin=50,
        leftMargin=36, rightMargin=36,
    )

    def make_canvas_factory(session_d, settings_d):
        class _Canvas(HeaderFooterCanvas):
            def __init__(self, *a, **kw):
                super().__init__(*a, session=session_d, company_settings=settings_d, **kw)
        return _Canvas

    doc2.build(story, canvasmaker=make_canvas_factory(session, company_settings))

    # Now create final PDF: cover page + story pages merged
    from reportlab.pdfgen import canvas as pdfcanvas
    cover_path = path + ".cover.pdf"
    c = pdfcanvas.Canvas(cover_path, pagesize=A4)
    _cover_page(c, session, company_settings)
    c.showPage()
    c.save()

    # Merge cover + story using basic approach
    try:
        import PyPDF2
        merger = PyPDF2.PdfMerger()
        merger.append(cover_path)
        merger.append(tmp_path)
        merger.write(path)
        merger.close()
        os.remove(cover_path)
        os.remove(tmp_path)
    except ImportError:
        # If PyPDF2 not available, just use the story PDF
        os.rename(tmp_path, path)
        if os.path.exists(cover_path):
            os.remove(cover_path)

    return path
