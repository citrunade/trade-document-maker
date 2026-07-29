"""
PDF 单据导出模块（统一格式，PI / CI / PL 仅标题与是否显示价格不同）
使用 ReportLab 生成 A4 尺寸、中英双语单据。

版式：
- 每页页眉重复显示：左侧 Own（本公司）信头，右侧收件方信息 + 单据标题/页码。
- 每页页脚重复显示：银行基本信息（户名/账号/Swift Code）。
- 页面主体：Delivery Address + Conditions（左列）与 Information（右列）两组信息框，
  随后是产品明细表；最后一页额外附加收款银行详情（作为普通流式内容，自然落在末页）。
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as canvas_module

from core import calc
from core.fonts import ensure_fonts_registered
from core.paths import get_data_path

PAGE_MARGIN = 15 * mm
HEADER_HEIGHT = 68 * mm
FOOTER_HEIGHT = 16 * mm

# 表头/信息框标题栏背景色：由深藏青改为更浅的蓝色
HEADER_BG = colors.HexColor("#5B9BD5")
BOX_TITLE_BG = colors.HexColor("#DCE9F7")

DOC_TITLES = {
    "PI": ("PROFORMA INVOICE", "形式发票"),
    "CI": ("COMMERCIAL INVOICE", "商业发票"),
    "PL": ("PACKING LIST", "装箱单"),
}


def _styles():
    regular, bold = ensure_fonts_registered()
    return {
        "regular_name": regular,
        "bold_name": bold,
        "title": ParagraphStyle("title", fontName=bold, fontSize=14, alignment=TA_RIGHT, leading=17),
        "normal": ParagraphStyle("normal", fontName=regular, fontSize=8.5, alignment=TA_LEFT, leading=11.5),
        "normal_right": ParagraphStyle("normal_right", fontName=regular, fontSize=8.5, alignment=TA_RIGHT, leading=11.5),
        "box_title": ParagraphStyle("box_title", fontName=bold, fontSize=9, alignment=TA_LEFT, leading=12),
        "cell": ParagraphStyle("cell", fontName=regular, fontSize=8, alignment=TA_LEFT, leading=10),
        "cell_center": ParagraphStyle("cell_center", fontName=regular, fontSize=8, alignment=TA_CENTER, leading=10),
        "cell_right": ParagraphStyle("cell_right", fontName=regular, fontSize=8, alignment=TA_RIGHT, leading=10),
        "footer": ParagraphStyle("footer", fontName=regular, fontSize=7.5, alignment=TA_CENTER, leading=10, textColor=colors.grey),
        "bold_small": ParagraphStyle("bold_small", fontName=bold, fontSize=8.5, alignment=TA_LEFT, leading=11),
        "note": ParagraphStyle("note", fontName=regular, fontSize=7.5, alignment=TA_LEFT, leading=10),
    }


def _wrap(text, style):
    return Paragraph(str(text) if text is not None else "", style)


def _nl2br(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\n", "<br/>")


# ---------------- 每页重复的页眉/页脚（通过自定义 Canvas 绘制） ----------------
def _draw_repeating_header(c, styles, own: dict, customer: dict, doc_type: str, page_num: int, total_pages):
    page_w, page_h = A4
    top_y = page_h - PAGE_MARGIN

    regular = styles["regular_name"]
    bold = styles["bold_name"]

    # --- 左：收件方（客户）信息 ---
    recipient_lines = [
        (bold, 9, customer.get("name_en", "")),
        (regular, 8, customer.get("name_cn", "")),
        (regular, 8, customer.get("address_en", "")),
    ]
    if customer.get("tel_phone"):
        recipient_lines.append((regular, 8, f"Phone: {customer.get('tel_phone')}"))
    if customer.get("company_reg_no"):
        recipient_lines.append((regular, 8, f"Company Reg. No.: {customer.get('company_reg_no')}"))
    if customer.get("gst_no"):
        recipient_lines.append((regular, 8, f"GST No.: {customer.get('gst_no')}"))

    y = top_y - 4
    for font, size, text in recipient_lines:
        if not text:
            continue
        c.setFont(font, size)
        c.drawString(PAGE_MARGIN, y, text)
        y -= size + 2.5

    # --- 右：Own 信头（含 Logo，固定不变）+ 单据标题/页码 ---
    right_x = page_w - PAGE_MARGIN
    title_en, title_cn = DOC_TITLES.get(doc_type, DOC_TITLES["PI"])
    c.setFont(bold, 14)
    c.drawRightString(right_x, top_y - 4, title_en)
    c.setFont(regular, 9)
    c.drawRightString(right_x, top_y - 14, title_cn)
    page_label = f"Page {page_num} of {total_pages}" if total_pages else f"Page {page_num}"
    c.setFont(regular, 8)
    c.drawRightString(right_x, top_y - 22, page_label)

    logo_path = get_data_path("logo.png")
    if os.path.exists(logo_path):
        try:
            img = Image(logo_path)
            target_h = 14 * mm
            ratio = img.imageWidth / img.imageHeight if img.imageHeight else 1
            draw_w = target_h * ratio
            c.drawImage(logo_path, right_x - draw_w, top_y - 28 * mm, width=draw_w, height=target_h,
                        preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    own_lines = [
        (bold, 10, own.get("company_name_en", "")),
        (regular, 8.5, own.get("company_name_cn", "")),
    ]
    for line in _nl2br(own.get("address", "")).split("<br/>"):
        own_lines.append((regular, 8, line))
    if own.get("phone"):
        own_lines.append((regular, 8, f"Phone: {own.get('phone')}"))
    if own.get("company_reg_no"):
        own_lines.append((regular, 8, f"Company Reg. No.: {own.get('company_reg_no')}"))
    if own.get("gst_no"):
        own_lines.append((regular, 8, f"GST No.: {own.get('gst_no')}"))

    y = top_y - 34 * mm
    for font, size, text in own_lines:
        if not text:
            continue
        c.setFont(font, size)
        c.drawRightString(right_x, y, text)
        y -= size + 2.5

    c.setStrokeColor(colors.HexColor("#5B9BD5"))
    c.setLineWidth(1)
    c.line(PAGE_MARGIN, page_h - HEADER_HEIGHT + 2 * mm, page_w - PAGE_MARGIN, page_h - HEADER_HEIGHT + 2 * mm)


def _draw_repeating_footer(c, styles, own: dict, banking: dict):
    page_w, _ = A4
    regular = styles["regular_name"]
    bold = styles["bold_name"]
    center_x = page_w / 2

    c.setStrokeColor(colors.lightgrey)
    c.setLineWidth(0.5)
    c.line(PAGE_MARGIN, FOOTER_HEIGHT, page_w - PAGE_MARGIN, FOOTER_HEIGHT)

    y = FOOTER_HEIGHT - 5
    c.setFont(bold, 8)
    c.drawCentredString(center_x, y, own.get("company_name_en", ""))
    y -= 9
    bank_parts = []
    if banking.get("bank_name"):
        bank_parts.append(f"Bank: {banking.get('bank_name')}")
    if banking.get("account_no"):
        bank_parts.append(f"Account No.: {banking.get('account_no')}")
    if banking.get("swift_code"):
        bank_parts.append(f"Swift Code: {banking.get('swift_code')}")
    c.setFont(regular, 7.5)
    c.setFillColor(colors.grey)
    c.drawCentredString(center_x, y, "   ".join(bank_parts))
    c.setFillColor(colors.black)


class _NumberedCanvas(canvas_module.Canvas):
    """
    两遍渲染：先缓存每一页，最后在 save() 时才知道总页数，
    从而能在每页页眉正确显示 "Page X of Y"。
    """
    _context = None  # 由 _canvas_factory 注入

    def __init__(self, *args, **kwargs):
        canvas_module.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_furniture(total)
            canvas_module.Canvas.showPage(self)
        canvas_module.Canvas.save(self)

    def _draw_furniture(self, total_pages):
        ctx = self._context
        self.saveState()
        _draw_repeating_header(self, ctx["styles"], ctx["own"], ctx["customer"], ctx["doc_type"],
                                self.getPageNumber(), total_pages)
        _draw_repeating_footer(self, ctx["styles"], ctx["own"], ctx["banking"])
        self.restoreState()


def _canvas_factory(context: dict):
    return type("_BoundNumberedCanvas", (_NumberedCanvas,), {"_context": context})


# ---------------- 主体信息框（Delivery / Conditions / Information） ----------------
def _boxed_section(title: str, body_text: str, styles, width: float) -> Table:
    title_row = [Paragraph(f"<b>{title}</b>", styles["box_title"])]
    body_row = [Paragraph(body_text, styles["normal"])]
    table = Table([title_row, body_row], colWidths=[width])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#5B9BD5")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#5B9BD5")),
        ("BACKGROUND", (0, 0), (-1, 0), BOX_TITLE_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _left_column(doc: dict, styles, width: float):
    delivery = doc.get("delivery_snapshot", {})
    conditions = doc.get("conditions_snapshot", {})

    delivery_text = f"<b>{delivery.get('company_name', '')}</b><br/>{_nl2br(delivery.get('address', ''))}"
    delivery_box = _boxed_section("Delivery Address", delivery_text, styles, width)

    incoterm_line = conditions.get("incoterm", "")
    if incoterm_line and doc.get("destination"):
        incoterm_line = f"{incoterm_line}  {doc.get('destination')}"
    conditions_text = (
        f"<b>Terms of Payment</b>&nbsp;&nbsp;{conditions.get('terms_of_payment', '')}<br/><br/>"
        f"<b>Incoterms</b>&nbsp;&nbsp;{incoterm_line}<br/><br/>"
        f"<b>Shipment by</b>&nbsp;&nbsp;{conditions.get('shipment_by', '')}"
    )
    conditions_box = _boxed_section("Conditions", conditions_text, styles, width)

    stacked = Table([[delivery_box], [Spacer(1, 4)], [conditions_box]], colWidths=[width])
    stacked.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return stacked


def _right_column(doc: dict, styles, width: float):
    own = doc.get("own_snapshot", {})
    rows = [
        ("Doc No", doc.get("doc_number", "")),
        ("Document Date", doc.get("date", "")),
        ("Validity Start Date", doc.get("validity_start", "")),
        ("Validity End Date", doc.get("validity_end", "")),
        ("", ""),
        ("Our Contact", own.get("contact_person", "")),
        ("Telephone", own.get("telephone", "")),
        ("Email", own.get("email", "")),
    ]
    lines = []
    for label, value in rows:
        if not label:
            lines.append("&nbsp;")
        else:
            lines.append(f"<b>{label}</b>&nbsp;&nbsp;{value}")
    info_text = "<br/>".join(lines)
    return _boxed_section("Information", info_text, styles, width)


# ---------------- 产品明细表 ----------------
FINANCIAL_HEADERS = ["No.", "Description", "Qty", "Unit", "Unit Price", "Total Price",
                     "COO", "Net Weight", "Total N.W.", "HS Code", "Remark"]
PL_HEADERS = ["No.", "Description", "Qty", "Unit", "COO", "Net Weight", "Total N.W.", "HS Code", "Remark"]


def _item_table(computed_lines: list, currency: str, styles, financial: bool, content_width: float):
    headers = FINANCIAL_HEADERS if financial else PL_HEADERS
    data = [[_wrap(h, styles["cell_center"]) for h in headers]]

    for i, line in enumerate(computed_lines, start=1):
        desc = line.get("name_en", "")
        if line.get("name_cn"):
            desc += f"<br/>{line.get('name_cn')}"
        else:
            desc += "<br/>&nbsp;"

        row = [
            _wrap(i, styles["cell_center"]),
            Paragraph(desc, styles["cell"]),
            _wrap(f"{line.get('quantity', 0):g}", styles["cell_right"]),
            _wrap(line.get("unit", ""), styles["cell_center"]),
        ]
        if financial:
            row.append(_wrap(f"{line.get('unit_price', 0):,.2f}", styles["cell_right"]))
            row.append(_wrap(f"{line.get('subtotal', 0):,.2f}", styles["cell_right"]))
        row.extend([
            _wrap(line.get("coo", ""), styles["cell_center"]),
            _wrap(f"{line.get('net_weight', 0):.2f}", styles["cell_right"]),
            _wrap(f"{line['total_net_weight']:.2f}", styles["cell_right"]),
            _wrap(line.get("hs_code", ""), styles["cell_center"]),
            _wrap(line.get("remark", ""), styles["cell"]),
        ])
        data.append(row)

    if financial:
        weights = [7, 24, 8, 8, 12, 12, 8, 10, 10, 12, 12]
    else:
        weights = [7, 28, 9, 9, 9, 11, 11, 13, 13]
    total_weight = sum(weights)
    col_widths = [content_width * w / total_weight for w in weights]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF4FB")]),
    ]))
    return table


def _beneficiary_block(banking: dict, styles) -> Table:
    rows = [
        ("Beneficiary Name", banking.get("beneficiary_name", "")),
        ("Beneficiary Bank Name", banking.get("beneficiary_bank_name", "")),
        ("Swift Code", banking.get("beneficiary_swift_code", "")),
        ("Beneficiary Bank's Correspondent Bank", banking.get("correspondent_bank", "")),
        ("Beneficiary Bank Address", banking.get("beneficiary_bank_address", "")),
        ("Beneficiary Account No.", banking.get("beneficiary_account_no", "")),
    ]
    text = "<br/>".join(f"<b>{k}:</b>&nbsp;&nbsp;{v}" for k, v in rows if v)
    if not text:
        return None
    return _boxed_section("Beneficiary Bank Details / 收款银行详情", text, styles, 180 * mm)


def _make_doc_template(filepath: str):
    return SimpleDocTemplate(
        filepath, pagesize=A4,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        topMargin=HEADER_HEIGHT, bottomMargin=FOOTER_HEIGHT,
        title="Trade Document",
    )


def export_document(doc: dict, filepath: str) -> str:
    """
    统一单据导出入口。doc['doc_type'] 决定标题与是否显示价格（PL 隐藏价格）。
    doc 中的 own_snapshot/delivery_snapshot/conditions_snapshot/banking_snapshot
    为制单时选定模板预设的字段快照。
    """
    styles = _styles()
    doc_type = doc.get("doc_type", "PI")
    financial = doc_type != "PL"
    currency = doc.get("currency", "USD")
    customer = doc.get("customer_snapshot", {})
    own = doc.get("own_snapshot", {})
    banking = doc.get("banking_snapshot", {})

    totals = calc.compute_totals(doc.get("lines", []))
    content_width = A4[0] - 2 * PAGE_MARGIN
    col_width = (content_width - 6 * mm) / 2

    elements = []
    top_row = Table(
        [[_left_column(doc, styles, col_width), _right_column(doc, styles, col_width)]],
        colWidths=[col_width, col_width + 6 * mm],
    )
    top_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(top_row)
    elements.append(Spacer(1, 8))

    elements.append(_item_table(totals["lines"], currency, styles, financial, content_width))
    elements.append(Spacer(1, 6))

    if financial:
        total_line = Table(
            [["", f"Total Amount: {currency} {totals['total_amount']:,.2f}"]],
            colWidths=[content_width - 60 * mm, 60 * mm],
        )
        total_line.setStyle(TableStyle([
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("FONTNAME", (1, 0), (1, 0), styles["bold_name"]),
            ("FONTSIZE", (1, 0), (1, 0), 9.5),
        ]))
        elements.append(total_line)
        elements.append(Spacer(1, 3))
        elements.append(Paragraph(calc.amount_in_words(totals["total_amount"], currency), styles["bold_small"]))
        elements.append(Spacer(1, 6))

    summary_parts = [f"Total Qty: {totals['total_quantity']:g}", f"Total N.W.: {totals['total_net_weight']:.2f} kg"]
    elements.append(Paragraph("    ".join(summary_parts), styles["normal"]))
    elements.append(Spacer(1, 8))

    if doc.get("remark"):
        elements.append(_boxed_section("Note / 备注", _nl2br(doc.get("remark")), styles, content_width))
        elements.append(Spacer(1, 8))

    beneficiary = _beneficiary_block(banking, styles)
    if beneficiary:
        elements.append(beneficiary)

    context = {"styles": styles, "own": own, "customer": customer, "doc_type": doc_type, "banking": banking}
    template = _make_doc_template(filepath)
    template.build(elements, canvasmaker=_canvas_factory(context))
    return filepath
