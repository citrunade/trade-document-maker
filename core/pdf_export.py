"""
PDF 单据导出模块（PI / CI / PL）
使用 ReportLab 生成 A4 尺寸、中英双语、ICC 通用外贸标准格式单据。
三种单据共用同一份联动数据（core.calc 计算结果），确保数据一致。
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

from core import calc
from core.fonts import ensure_fonts_registered
from core.paths import get_data_path

PAGE_MARGIN = 15 * mm


def _styles():
    regular, bold = ensure_fonts_registered()
    return {
        "title": ParagraphStyle(
            "title", fontName=bold, fontSize=16, alignment=TA_CENTER, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=regular, fontSize=9, alignment=TA_CENTER, textColor=colors.grey,
        ),
        "company_name": ParagraphStyle(
            "company_name", fontName=bold, fontSize=12, alignment=TA_LEFT, leading=15,
        ),
        "normal": ParagraphStyle(
            "normal", fontName=regular, fontSize=8.5, alignment=TA_LEFT, leading=12,
        ),
        "normal_right": ParagraphStyle(
            "normal_right", fontName=regular, fontSize=8.5, alignment=TA_RIGHT, leading=12,
        ),
        "section_head": ParagraphStyle(
            "section_head", fontName=bold, fontSize=9.5, alignment=TA_LEFT,
            spaceBefore=6, spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "cell", fontName=regular, fontSize=8, alignment=TA_LEFT, leading=10,
        ),
        "cell_center": ParagraphStyle(
            "cell_center", fontName=regular, fontSize=8, alignment=TA_CENTER, leading=10,
        ),
        "cell_right": ParagraphStyle(
            "cell_right", fontName=regular, fontSize=8, alignment=TA_RIGHT, leading=10,
        ),
        "footer": ParagraphStyle(
            "footer", fontName=regular, fontSize=7.5, alignment=TA_LEFT,
            leading=10, textColor=colors.grey,
        ),
        "bold_small": ParagraphStyle(
            "bold_small", fontName=bold, fontSize=8.5, alignment=TA_LEFT, leading=11,
        ),
    }


def _build_header(company: dict, doc_title_en: str, doc_title_cn: str, styles):
    """
    构建 PDF 页眉：左侧 Logo + 公司信息，右侧单据标题。
    容错：若 data/logo.png 不存在，自动跳过图片，仅显示公司名称文本，不报错。
    """
    logo_path = get_data_path("logo.png")
    logo_cell = ""
    if os.path.exists(logo_path):
        try:
            img = Image(logo_path)
            # 等比例缩放，高度控制在约 18mm
            target_h = 18 * mm
            ratio = img.imageWidth / img.imageHeight if img.imageHeight else 1
            img.drawHeight = target_h
            img.drawWidth = target_h * ratio
            logo_cell = img
        except Exception:
            logo_cell = ""

    company_text = (
        f"<b>{company.get('name_en', '')}</b><br/>{company.get('name_cn', '')}<br/>"
        f"{company.get('address_en', '')}<br/>{company.get('address_cn', '')}<br/>"
        f"Tel: {company.get('phone', '')}  Email: {company.get('email', '')}<br/>"
        f"Tax ID: {company.get('tax_id', '')}"
    )
    company_para = Paragraph(company_text, styles["normal"])

    left_content = [logo_cell, company_para] if logo_cell else [company_para]
    left_table = Table([[c] for c in left_content], colWidths=[95 * mm])
    left_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    title_para = Paragraph(f"{doc_title_en}<br/><font size=9>{doc_title_cn}</font>", styles["title"])

    header_table = Table([[left_table, title_para]], colWidths=[95 * mm, 85 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return header_table


def _party_info_table(doc: dict, doc_number: str, styles, include_payment: bool):
    customer = doc.get("customer_snapshot", {})
    consignee = customer.get("consignee", "") or customer.get("address_en", "")
    tax_no = customer.get("tax_no", "")
    left_text = (
        f"<b>To / 致：</b><br/>{customer.get('name_en', '')}<br/>{customer.get('name_cn', '')}<br/>"
        f"<b>Consignee / 收货人：</b><br/>{consignee.replace(chr(10), '<br/>')}<br/>"
        f"<b>Notify Party / 通知人：</b><br/>{customer.get('notify_party', '').replace(chr(10), '<br/>')}"
        + (f"<br/><b>Tax No. / VAT：</b>{tax_no}" if tax_no else "")
    )
    right_rows = [
        ("No. / 单号：", doc_number),
        ("Date / 日期：", doc.get("date", "")),
        ("POL / 起运港：", doc.get("pol", "")),
        ("POD / 目的港：", doc.get("pod", "")),
        ("Incoterm / 贸易术语：", doc.get("incoterm", "")),
        ("Destination / 目的国：", customer.get("country_region", "")),
    ]
    if include_payment:
        right_rows.append(("Payment / 付款方式：", doc.get("payment_terms", "")))
        right_rows.append(("Validity / 有效期：", doc.get("validity", "")))

    right_text = "<br/>".join(f"<b>{k}</b>{v}" for k, v in right_rows)

    table = Table(
        [[Paragraph(left_text, styles["normal"]), Paragraph(right_text, styles["normal"])]],
        colWidths=[95 * mm, 85 * mm],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _wrap(text, style):
    return Paragraph(str(text) if text is not None else "", style)


def _financial_lines_table(computed_lines: list, currency: str, styles):
    headers = [
        "No.", "Model / 型号", "Description / 品名", "HS Code",
        "Qty / 数量", "Unit / 单位", "Unit Price / 单价", "Amount / 金额",
    ]
    data = [[_wrap(h, styles["cell_center"]) for h in headers]]
    for i, line in enumerate(computed_lines, start=1):
        desc = f"{line.get('name_en', '')}<br/>{line.get('name_cn', '')}"
        data.append([
            _wrap(i, styles["cell_center"]),
            _wrap(line.get("model_no", ""), styles["cell"]),
            Paragraph(desc, styles["cell"]),
            _wrap(line.get("hs_code", ""), styles["cell_center"]),
            _wrap(f"{line.get('quantity', 0):g}", styles["cell_right"]),
            _wrap(line.get("unit", ""), styles["cell_center"]),
            _wrap(f"{line.get('unit_price', 0):,.2f}", styles["cell_right"]),
            _wrap(f"{line.get('subtotal', 0):,.2f}", styles["cell_right"]),
        ])
    col_widths = [10*mm, 22*mm, 55*mm, 18*mm, 16*mm, 14*mm, 22*mm, 23*mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f6fa")]),
    ]))
    return table


def _packing_lines_table(computed_lines: list, styles):
    headers = [
        "No.", "Model / 型号", "Description / 品名", "Qty / 数量",
        "N.W./pc", "G.W./pc", "Total N.W.(kg)", "Total G.W.(kg)",
        "Ctn Size (mm)", "CBM",
    ]
    data = [[_wrap(h, styles["cell_center"]) for h in headers]]
    for i, line in enumerate(computed_lines, start=1):
        desc = f"{line.get('name_en', '')}<br/>{line.get('name_cn', '')}"
        ctn_size = f"{line.get('length_mm', 0):g}x{line.get('width_mm', 0):g}x{line.get('height_mm', 0):g}"
        data.append([
            _wrap(i, styles["cell_center"]),
            _wrap(line.get("model_no", ""), styles["cell"]),
            Paragraph(desc, styles["cell"]),
            _wrap(f"{line.get('quantity', 0):g}", styles["cell_right"]),
            _wrap(f"{line.get('net_weight', 0):.2f}", styles["cell_right"]),
            _wrap(f"{line.get('gross_weight', 0):.2f}", styles["cell_right"]),
            _wrap(f"{line.get('total_net_weight', 0):.2f}", styles["cell_right"]),
            _wrap(f"{line.get('total_gross_weight', 0):.2f}", styles["cell_right"]),
            _wrap(ctn_size, styles["cell_center"]),
            _wrap(f"{line.get('total_cbm', 0):.3f}", styles["cell_right"]),
        ])
    col_widths = [9*mm, 18*mm, 38*mm, 13*mm, 14*mm, 14*mm, 18*mm, 18*mm, 26*mm, 12*mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f6fa")]),
    ]))
    return table


def _footer_terms(doc_type: str, company: dict, styles):
    if doc_type == "PI":
        text = (
            "Terms & Conditions / 条款声明：<br/>"
            "1. This Proforma Invoice is issued for reference only and is subject to final confirmation.<br/>"
            "2. Prices are valid within the validity period stated above and may change thereafter.<br/>"
            "3. Delivery time will be confirmed upon receipt of advance payment.<br/>"
            "本形式发票仅供参考，最终以双方确认为准；价格在有效期内有效，过期需重新确认；交货期以收到预付款后确认为准。"
        )
    elif doc_type == "CI":
        text = (
            "Declaration / 声明：<br/>"
            "We hereby certify that this invoice is true and correct, and that the goods are of "
            "the origin stated above. This invoice is issued for customs clearance purposes.<br/>"
            "兹证明此发票内容真实准确，货物原产地如上所述。本发票仅用于海关报关用途。"
        )
    else:
        text = (
            "Note / 备注：<br/>"
            "This Packing List is issued for customs and shipping purposes. Prices and amounts are "
            "intentionally omitted in compliance with customs confidentiality requirements.<br/>"
            "本装箱单仅用于报关及运输用途，出于海关保密规范，不含单价及金额信息。"
        )
    return Paragraph(text, styles["footer"])


def _bank_info_table(company: dict, styles):
    text = (
        f"<b>Bank Details / 银行信息：</b><br/>"
        f"Bank Name / 开户行：{company.get('bank_name_en', '')} {company.get('bank_name_cn', '')}<br/>"
        f"Account No. / 账号：{company.get('bank_account', '')}<br/>"
        f"SWIFT Code：{company.get('swift_code', '')}<br/>"
        f"Bank Address：{company.get('bank_address_en', '')}"
    )
    return Paragraph(text, styles["normal"])


def _make_doc_template(filepath: str):
    return SimpleDocTemplate(
        filepath, pagesize=A4,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
        title="Trade Document",
    )


def _add_page_number(canvas, doc):
    canvas.saveState()
    regular, _ = ensure_fonts_registered()
    canvas.setFont(regular, 8)
    canvas.setFillColor(colors.grey)
    page_text = f"Page {doc.page}"
    canvas.drawRightString(A4[0] - PAGE_MARGIN, 10 * mm, page_text)
    canvas.restoreState()


def _build_financial_pdf(doc: dict, doc_type: str, filepath: str, company: dict) -> str:
    """PI 与 CI 共用的构建逻辑，仅标题、条款、是否含付款信息不同"""
    styles = _styles()
    totals = calc.compute_totals(doc.get("lines", []))
    currency = doc.get("currency", "USD")
    doc_number = doc.get("pi_number" if doc_type == "PI" else "ci_number", "")

    title_en = "PROFORMA INVOICE" if doc_type == "PI" else "COMMERCIAL INVOICE"
    title_cn = "形式发票" if doc_type == "PI" else "商业发票"

    elements = []
    elements.append(_build_header(company, title_en, title_cn, styles))
    elements.append(Spacer(1, 6))
    elements.append(_party_info_table(doc, doc_number, styles, include_payment=(doc_type == "PI")))
    elements.append(Spacer(1, 8))
    elements.append(_financial_lines_table(totals["lines"], currency, styles))
    elements.append(Spacer(1, 4))

    total_line = Table(
        [["", f"Total Amount / 总金额：{currency} {totals['total_amount']:,.2f}"]],
        colWidths=[130 * mm, 50 * mm],
    )
    total_line.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("FONTNAME", (1, 0), (1, 0), styles["bold_small"].fontName),
        ("FONTSIZE", (1, 0), (1, 0), 9.5),
    ]))
    elements.append(total_line)
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(calc.amount_in_words(totals["total_amount"], currency), styles["bold_small"]))
    elements.append(Spacer(1, 8))

    summary_text = (
        f"Total Qty / 总数量：{totals['total_quantity']:g}    "
        f"Total N.W. / 总净重：{totals['total_net_weight']:.2f} kg    "
        f"Total G.W. / 总毛重：{totals['total_gross_weight']:.2f} kg    "
        f"Total CBM / 总体积：{totals['total_cbm']:.3f}"
    )
    elements.append(Paragraph(summary_text, styles["normal"]))
    elements.append(Spacer(1, 8))

    if doc_type == "PI":
        elements.append(_bank_info_table(company, styles))
        elements.append(Spacer(1, 8))

    elements.append(HRFlowable(width="100%", color=colors.lightgrey))
    elements.append(Spacer(1, 4))
    elements.append(_footer_terms(doc_type, company, styles))

    template = _make_doc_template(filepath)
    template.build(elements, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    return filepath


def export_pi(doc: dict, filepath: str, company: dict) -> str:
    return _build_financial_pdf(doc, "PI", filepath, company)


def export_ci(doc: dict, filepath: str, company: dict) -> str:
    return _build_financial_pdf(doc, "CI", filepath, company)


def export_pl(doc: dict, filepath: str, company: dict) -> str:
    styles = _styles()
    totals = calc.compute_totals(doc.get("lines", []))
    doc_number = doc.get("pl_number", "")

    elements = []
    elements.append(_build_header(company, "PACKING LIST", "装箱单", styles))
    elements.append(Spacer(1, 6))
    elements.append(_party_info_table(doc, doc_number, styles, include_payment=False))
    elements.append(Spacer(1, 8))
    elements.append(_packing_lines_table(totals["lines"], styles))
    elements.append(Spacer(1, 6))

    summary_text = (
        f"<b>Total Qty / 总数量：</b>{totals['total_quantity']:g}    "
        f"<b>Total N.W. / 总净重：</b>{totals['total_net_weight']:.2f} kg    "
        f"<b>Total G.W. / 总毛重：</b>{totals['total_gross_weight']:.2f} kg    "
        f"<b>Total CBM / 总体积：</b>{totals['total_cbm']:.3f}"
    )
    elements.append(Paragraph(summary_text, styles["bold_small"]))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", color=colors.lightgrey))
    elements.append(Spacer(1, 4))
    elements.append(_footer_terms("PL", company, styles))

    template = _make_doc_template(filepath)
    template.build(elements, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    return filepath
