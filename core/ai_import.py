"""
AI 文件导入模块
从 PDF / Excel / Word / 图片 (JPG/PNG) 中提取客户信息、产品信息或单据明细，
通过阿里云百炼（Qwen）完成 OCR 与结构化字段抽取。

处理策略：
- Excel：直接读取表格文字内容（本身已是结构化数据，无需 OCR）。若表格文字内容过于稀疏
  （例如产品信息以图片形式贴在单元格中，而非文字），自动改用表格中嵌入的第一张图片调用视觉模型。
- Word (.docx)：提取段落与表格文字；若文字内容过于稀疏（例如整页以图片形式排版），
  自动改用文档中嵌入的第一张图片调用视觉模型。
- PDF：优先提取页面中的文字层（免费、快速）；如果某页没有文字层（如扫描件/图片型 PDF），
  才将该页渲染为图片调用视觉模型（费用更高，仅在必要时使用）。
- JPG/PNG：直接调用视觉模型。

所有函数返回结构化 dict/list，调用方（UI 层）负责展示审核对话框，
本模块不直接写入任何本地数据文件。
"""
import json
import os
import re

import fitz  # PyMuPDF

from core import ai_client
from core.models import make_customer, make_product, make_doc_line

SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".jpg", ".jpeg", ".png"}

# 判定"文字内容过于稀疏、需改用图片识别"的最小有效字符数阈值
MIN_TEXT_CHARS = 20

# 单次识别的 PDF 页数上限；超出时提示拆分，而不是静默截断（此前只读前 5 页，长订单会漏行）
MAX_PDF_PAGES = 10

# 单次发送给模型的文字上限（约 3 万 token）：超大的 Excel/Word 会很慢、费用高，且可能超出模型上限
MAX_TEXT_CHARS = 60_000


class AIImportError(Exception):
    pass


# ---------------- 文件类型识别 ----------------
def get_file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".xlsx", ".xls"):
        return "xlsx"
    if ext == ".docx":
        return "docx"
    if ext == ".doc":
        raise AIImportError(
            "不支持旧版 .doc 格式，请在 Word 中另存为 .docx 格式后重新导入。"
        )
    if ext in (".jpg", ".jpeg", ".png"):
        return "image"
    raise AIImportError(f"不支持的文件类型：{ext}（仅支持 PDF / Excel / Word(.docx) / JPG / PNG）")


# ---------------- PDF 内容提取 ----------------
def extract_pdf_pages(path: str) -> list:
    """
    逐页提取 PDF 内容。
    返回列表，每项为 ("text", str) 或 ("image", bytes)：
    - 若该页存在文字层，返回提取到的文本；
    - 若该页没有文字层（判定为扫描件/图片型页面），返回该页渲染后的 PNG 图片字节。
    """
    results = []
    doc = fitz.open(path)
    try:
        for page in doc:
            text = _page_text_with_tables(page)
            if text:
                results.append(("text", text))
            else:
                # 无文字层，判定为扫描件，渲染为图片交给视觉模型处理
                pix = page.get_pixmap(dpi=200)
                results.append(("image", pix.tobytes("png")))
    finally:
        doc.close()
    return results


def _page_text_with_tables(page) -> str:
    """
    按阅读顺序提取页面文字，并把识别到的表格额外转为 Markdown 附在后面。
    普通 get_text() 会把表格逐单元格拆成独立行，数量/单价/金额列的对应关系丢失，
    这是 AI 把数量与单价填错的主要原因；Markdown 表格保留了行列结构。
    """
    if not page.get_text().strip():
        return ""
    try:
        found = [t for t in page.find_tables().tables if t.to_markdown().strip()]
    except Exception:
        found = []
    if not found:
        return page.get_text(sort=True).strip()

    # 表格区域内的文字只以 Markdown 表格形式发送一次；若再按普通文字重复发送，
    # 同一明细行会出现两次，模型容易重复计数或把数量/单价对应到错误的行。
    table_rects = [fitz.Rect(t.bbox) for t in found]
    outside = []
    for x0, y0, x1, y1, block_text, *_ in page.get_text("blocks", sort=True):
        block = fitz.Rect(x0, y0, x1, y1)
        if any(block.intersects(r) for r in table_rects):
            continue
        if block_text.strip():
            outside.append(block_text.strip())
    tables = "\n\n".join(t.to_markdown().strip() for t in found)
    return "\n".join(outside) + "\n\n【表格（行列结构）】\n\n" + tables


# ---------------- Excel 内容提取 ----------------
def xlsx_to_markdown(path: str) -> str:
    """
    读取所有工作表：发票与装箱单常分属不同工作表（重量通常只在 Packing List 中），
    只读第一张表会漏掉重量。header=None 保留原始表头行，避免出现 "Unnamed: 3" 这类列名。
    """
    import pandas as pd
    sheets = pd.read_excel(path, dtype=str, header=None, sheet_name=None)
    parts = []
    for name, df in sheets.items():
        df = df.fillna("").astype(str)
        df = df.loc[(df != "").any(axis=1), (df != "").any(axis=0)]
        if df.empty:
            continue
        parts.append(f"## 工作表：{name}\n\n" + df.to_markdown(index=False, headers=[""] * df.shape[1]))
    return "\n\n".join(parts)


def xlsx_extract_images(path: str) -> list:
    """
    提取 Excel 文件中直接贴图/嵌入的图片（不含单元格文字），用于表格文字内容
    过于稀疏时的视觉模型回退方案（例如产品目录以图片贴在表格里，而非文字）。
    仅支持 .xlsx（openpyxl），.xls 旧格式不支持嵌入图片提取。
    """
    if os.path.splitext(path)[1].lower() != ".xlsx":
        return []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path)
    except Exception:
        return []
    images = []
    for ws in wb.worksheets:
        for img in getattr(ws, "_images", []):
            try:
                images.append(img._data())
            except Exception:
                continue
    return images


# ---------------- Word 内容提取 ----------------
def extract_docx_content(path: str) -> tuple:
    """
    提取 .docx 文件的段落与表格文字，以及所有嵌入图片。
    返回 (text, images)：text 为拼接后的纯文字内容，images 为图片字节列表。
    """
    import docx
    document = docx.Document(path)

    parts = []
    for para in document.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    text = "\n".join(parts)

    images = []
    for rel in document.part.rels.values():
        if "image" in rel.reltype:
            try:
                images.append(rel.target_part.blob)
            except Exception:
                continue

    return text, images


# ---------------- JSON 解析辅助 ----------------
def _parse_json_response(raw: str):
    """
    从模型回复中提取 JSON。模型有时会用 ```json ... ``` 包裹，需先去除代码块标记。
    解析失败时抛出 AIImportError，绝不返回猜测性的部分数据。
    """
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIImportError(f"AI 返回的内容不是有效的 JSON，无法自动提取字段：{e}\n原始回复：{raw[:500]}")


# ---------------- 提示词 ----------------
CUSTOMER_PROMPT = """你是外贸单据信息提取助手。用户会提供一份文件内容（发票、箱单、产品目录、名片、公司信笺
或类似文件）。只要识别出具备企业主体特征的信息（如买方、卖方、目录内企业信息等），一律判定为客户主体，
不做买方/卖方角色区分；无法明确区分角色时也不要过滤，尽量捕获入库。
请从中提取客户信息，并仅以如下 JSON 格式返回（找不到的字段填空字符串，不要编造信息；地址保持整段
原文文本，不要拆分街道/门牌号/邮编）：
{
  "name_cn": "中文名称",
  "name_en": "英文名称",
  "country_region": "国家/地区",
  "city": "城市",
  "address_en": "英文完整地址（整段文本）",
  "tax_no": "税号/VAT",
  "contact_person": "联系人",
  "email": "电子邮箱",
  "tel_phone": "联系电话",
  "company_reg_no": "公司注册号",
  "gst_no": "GST/增值税登记号",
  "consignee": "收货人信息（如与地址不同，可多行，用\\n分隔）",
  "notify_party": "通知人信息",
  "pod": "目的港（若单据中出现具体港口名）",
  "remark": "其他备注信息"
}
只返回 JSON，不要包含任何其他说明文字。"""

PRODUCT_PROMPT = """你是外贸单据信息提取助手。用户会提供一份产品规格表/报价单/产品目录文件内容，
请从中提取所有产品条目，并仅以如下 JSON 对象格式返回（每个产品一个对象，找不到的字段填 0 或空字符串，不要编造信息）：
{
  "items": [
    {
    "model_no": "型号",
    "name_cn": "中文品名",
    "name_en": "英文品名",
    "hs_code": "HS编码",
    "unit": "单位（如 pcs/set/m）",
    "net_weight": 0.0,
    "gross_weight": 0.0,
    "length_mm": 0.0,
    "width_mm": 0.0,
    "height_mm": 0.0,
    "unit_price": 0.0,
    "currency": "USD",
    "coo": "原产国/地区代码（如 DE/CN，找不到留空）",
    "remark": ""
    }
  ]
}
只返回有效 JSON 对象，不要包含任何其他说明文字。"""

DOCUMENT_LINES_PROMPT = """你是外贸单据信息提取助手。用户会提供一份采购订单(PO)或类似文件内容，
请从中提取所有产品明细行，并仅以如下 JSON 对象格式返回（每行一个对象，找不到的字段填 0 或空字符串，不要编造信息）：
{
  "doc_total_quantity": 0.0,
  "doc_total_amount": 0.0,
  "items": [
    {
    "model_no": "型号",
    "name_cn": "中文品名",
    "name_en": "英文品名",
    "hs_code": "HS编码",
    "unit": "单位",
    "quantity": 0.0,
    "unit_price": 0.0,
    "amount": 0.0,
    "unit_net_weight": 0.0,
    "total_net_weight": 0.0,
    "unit_gross_weight": 0.0,
    "total_gross_weight": 0.0,
    "remark": "备注（找到才填写）"
    }
  ]
}
字段说明（务必区分，不要混淆）：
- quantity：数量/件数（Qty），即购买的件数，通常是较小的整数或简单数字。
- unit_price：单价（Unit Price），即每一件的价格，不是总价/金额（Amount/Total）。
  如果表格中同时存在「单价」和「金额/总价」两列，金额 = 数量 × 单价，
  请只取「单价」列的值填入 unit_price，绝不能把金额或数量误填入 unit_price，
  也不能把单价误填入 quantity。
- amount：金额/总价（Amount/Total），如表格中有该列，原样提取其数字，不要自己计算；
  找不到该列则填 0。此字段仅用于核对 quantity × unit_price 是否正确，不会直接使用。
- doc_total_quantity / doc_total_amount：文件上印刷的合计数量与合计金额（如 "Total Qty"、
  "TOTAL"、"合计"），原样抄录，不要自己计算；找不到填 0。
- 每一个明细行都必须输出且只输出一次，不要遗漏、合并或重复；同一行跨页时按一行处理。
- 重量（单位统一换算为千克 kg；如原文为克 g 则除以 1000）：
  - unit_net_weight / unit_gross_weight：每件的净重/毛重（列名如 "Unit N.W."、"单重"、"N.W./PC"）。
  - total_net_weight / total_gross_weight：该行合计净重/毛重（列名如 "N.W."、"Net Weight"、
    "净重"、"Total N.W."、"G.W."、"毛重"）。多数单据的 N.W./G.W. 列是该行合计值。
  - 原文只有一种时，只填对应字段，另一个填 0，不要自己换算。
  - 若文件含多个工作表/多个部分（如 Invoice 与 Packing List），重量通常在 Packing List 中，
    请按型号/序号与发票行对应后填入同一行。
只返回有效 JSON 对象，不要包含任何其他说明文字。"""


def _run_extraction(path: str, prompt: str, config: dict) -> str:
    """
    根据文件类型选择合适的处理路径，调用阿里云百炼 API，返回模型的原始文本回复。
    """
    api_key = config.get("bailian_api_key", "")
    base_url = config.get("bailian_base_url") or ai_client.DEFAULT_BASE_URL
    text_model = config.get("bailian_text_model") or ai_client.DEFAULT_TEXT_MODEL
    vision_model = config.get("bailian_vision_model") or ai_client.DEFAULT_VISION_MODEL

    kind = get_file_kind(path)

    def _check_size(text: str) -> str:
        if len(text) > MAX_TEXT_CHARS:
            raise AIImportError(
                f"文件内容过多（约 {len(text):,} 字符，上限 {MAX_TEXT_CHARS:,}）。"
                "请删除无关的工作表/内容，或拆分成几个文件分别导入。"
            )
        return text

    if kind == "xlsx":
        table_text = _check_size(xlsx_to_markdown(path))
        if len(table_text.strip()) >= MIN_TEXT_CHARS:
            return ai_client.extract_from_text(api_key, base_url, text_model, prompt, table_text)
        # 表格文字内容过于稀疏（如产品信息以图片贴在单元格中），改用嵌入图片走视觉模型
        images = xlsx_extract_images(path)
        if images:
            return ai_client.extract_from_image(api_key, base_url, vision_model, prompt, images[0], "image/png")
        if table_text.strip():
            return ai_client.extract_from_text(api_key, base_url, text_model, prompt, table_text)
        raise AIImportError("无法从该 Excel 文件中读取任何可识别内容（表格为空且未找到嵌入图片）。")

    if kind == "docx":
        text, images = extract_docx_content(path)
        _check_size(text)
        if len(text.strip()) >= MIN_TEXT_CHARS:
            return ai_client.extract_from_text(api_key, base_url, text_model, prompt, text)
        # 文字内容过于稀疏（如整页以图片排版），改用嵌入图片走视觉模型
        if images:
            return ai_client.extract_from_image(api_key, base_url, vision_model, prompt, images[0], "image/png")
        if text.strip():
            return ai_client.extract_from_text(api_key, base_url, text_model, prompt, text)
        raise AIImportError("无法从该 Word 文件中读取任何可识别内容（文档为空且未找到嵌入图片）。")

    if kind == "image":
        with open(path, "rb") as f:
            image_bytes = f.read()
        ext = os.path.splitext(path)[1].lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        return ai_client.extract_from_image(api_key, base_url, vision_model, prompt, image_bytes, mime)

    if kind == "pdf":
        pages = extract_pdf_pages(path)
        if not pages:
            raise AIImportError("无法从该 PDF 中读取任何内容（可能是空白文件）。")
        if len(pages) > MAX_PDF_PAGES:
            raise AIImportError(
                f"该 PDF 共 {len(pages)} 页，超过单次识别上限 {MAX_PDF_PAGES} 页。"
                "为避免遗漏明细行，请将 PDF 拆分后分别导入。"
            )
        text_pages = [p[1] for p in pages if p[0] == "text"]
        image_pages = [p[1] for p in pages if p[0] == "image"]
        combined_text = _check_size("\n\n".join(text_pages))
        if not image_pages:
            return ai_client.extract_from_text(api_key, base_url, text_model, prompt, combined_text)
        # 存在扫描页：扫描页图片与文字页内容一起交给视觉模型，两者都不遗漏
        return ai_client.extract_from_images(
            api_key, base_url, vision_model, prompt, image_pages, "image/png", extra_text=combined_text,
        )

    raise AIImportError(f"未知文件类型：{kind}")


# ---------------- 对外接口 ----------------
def import_customer(path: str, config: dict) -> dict:
    """从文件中提取客户信息，返回一份符合 make_customer 字段结构的 dict（未保存）"""
    raw = _run_extraction(path, CUSTOMER_PROMPT, config)
    data = _parse_json_response(raw)
    if not isinstance(data, dict):
        raise AIImportError("AI 返回的客户信息格式不正确（应为 JSON 对象）。")
    customer = make_customer()
    for key in (
        "name_cn", "name_en", "country_region", "city", "address_en", "tax_no",
        "contact_person", "email", "tel_phone", "company_reg_no", "gst_no",
        "consignee", "notify_party", "pod", "remark",
    ):
        if key in data and data[key] is not None:
            customer[key] = str(data[key])
    return customer


def import_products(path: str, config: dict) -> list:
    """从文件中提取产品列表，返回符合 make_product 字段结构的 dict 列表（未保存）"""
    raw = _run_extraction(path, PRODUCT_PROMPT, config)
    data = _parse_json_response(raw)
    # 百炼 JSON Mode 顶层使用对象；兼容旧模型曾返回的直接数组格式。
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        raise AIImportError("AI 返回的产品信息格式不正确（应包含 items 数组）。")
    products = []
    for item in data:
        if not isinstance(item, dict):
            continue
        product = make_product(
            model_no=str(item.get("model_no", "")),
            name_cn=str(item.get("name_cn", "")),
            name_en=str(item.get("name_en", "")),
            hs_code=str(item.get("hs_code", "")),
            unit=str(item.get("unit", "pcs")) or "pcs",
            net_weight=_to_float(item.get("net_weight", 0)),
            gross_weight=_to_float(item.get("gross_weight", 0)),
            length_mm=_to_float(item.get("length_mm", 0)),
            width_mm=_to_float(item.get("width_mm", 0)),
            height_mm=_to_float(item.get("height_mm", 0)),
            unit_price=_to_float(item.get("unit_price", 0)),
            currency=str(item.get("currency", "USD")) or "USD",
            coo=str(item.get("coo", "")),
            remark=str(item.get("remark", "")),
        )
        products.append(product)
    return products


class ExtractedLines(list):
    """明细行列表，附带 warnings：与文件上印刷的合计数量/金额核对不一致时的提示。"""
    warnings: list = []


def import_document_lines(path: str, config: dict) -> list:
    """从采购订单(PO)等文件中提取单据明细行，返回符合 make_doc_line 字段结构的 dict 列表（未保存）"""
    raw = _run_extraction(path, DOCUMENT_LINES_PROMPT, config)
    data = _parse_json_response(raw)
    printed_qty = printed_amount = 0.0
    if isinstance(data, dict):
        printed_qty = _to_float(data.get("doc_total_quantity", 0))
        printed_amount = _to_float(data.get("doc_total_amount", 0))
        data = data.get("items", [])
    if not isinstance(data, list):
        raise AIImportError("AI 返回的明细信息格式不正确（应包含 items 数组）。")
    lines = ExtractedLines()
    lines.warnings = []
    for item in data:
        if not isinstance(item, dict):
            continue
        quantity = _to_float(item.get("quantity", 0))
        unit_price = _to_float(item.get("unit_price", 0))
        amount = _to_float(item.get("amount", 0))
        remark = str(item.get("remark", ""))

        # 若源文件本身含有「金额」列，用 数量×单价 与其核对：
        # 注意乘法满足交换律，此核对无法判断数量与单价是否被互换填反，
        # 但能发现两者之一被识别成完全错误数值的情况，提醒用户核对。
        if amount and abs(quantity * unit_price - amount) > max(0.01, amount * 0.01):
            remark = (remark + " ⚠数量×单价与金额不符，请核对").strip()

        net_weight = _per_unit_weight(item, "net", quantity)
        gross_weight = _per_unit_weight(item, "gross", quantity)

        pseudo_product = {
            "id": "",
            "model_no": str(item.get("model_no", "")),
            "name_cn": str(item.get("name_cn", "")),
            "name_en": str(item.get("name_en", "")),
            "hs_code": str(item.get("hs_code", "")),
            "unit": str(item.get("unit", "pcs")) or "pcs",
            "unit_price": unit_price,
            "net_weight": net_weight,
            "gross_weight": gross_weight,
            "length_mm": 0.0,
            "width_mm": 0.0,
            "height_mm": 0.0,
            "coo": str(item.get("coo", "")),
            "remark": remark,
        }
        line = make_doc_line(pseudo_product, quantity=quantity)
        lines.append(line)

    # 与文件上印刷的合计核对：识别错一行（如数量 1 读成 10）时，合计必然对不上
    sum_qty = round(sum(l["quantity"] for l in lines), 3)
    sum_amount = round(sum(l["quantity"] * l["unit_price"] for l in lines), 2)
    if printed_qty and abs(sum_qty - printed_qty) > 0.001:
        lines.warnings.append(
            f"识别出的明细数量合计为 {sum_qty:g}，但文件上印刷的合计数量为 {printed_qty:g}。"
        )
    if printed_amount and abs(sum_amount - printed_amount) > max(0.05, printed_amount * 0.001):
        lines.warnings.append(
            f"识别出的明细金额合计为 {sum_amount:,.2f}，但文件上印刷的合计金额为 {printed_amount:,.2f}。"
        )
    return lines


def _normalize_model(model_no: str) -> str:
    return "".join(str(model_no or "").split()).upper()


# 物料库中可补全的字段：仅在文件中缺少（为空或 0）时补全，文件中已有的值优先
LIBRARY_FILL_FIELDS = (
    "name_cn", "name_en", "hs_code", "coo", "net_weight", "gross_weight",
    "length_mm", "width_mm", "height_mm",
)


def fill_from_product_library(lines: list, products: list) -> int:
    """
    按型号（忽略大小写与空格）把 AI 识别出的明细行与物料库产品对应，补全文件中缺少的
    重量/HS编码/原产国/中文品名/尺寸等字段。单价与数量始终以文件为准。返回匹配到的行数。
    """
    by_model = {}
    for p in products:
        key = _normalize_model(p.get("model_no"))
        if key:
            by_model.setdefault(key, p)
    matched = 0
    for line in lines:
        product = by_model.get(_normalize_model(line.get("model_no")))
        if not product:
            continue
        matched += 1
        line["product_id"] = product.get("id", "")
        for field in LIBRARY_FILL_FIELDS:
            if not line.get(field) and product.get(field):
                line[field] = product[field]
    return matched


def _per_unit_weight(item: dict, kind: str, quantity: float) -> float:
    """单据明细存储的是每件重量；原文只给出行合计重量时按数量折算为每件重量。"""
    unit = _to_float(item.get(f"unit_{kind}_weight", 0))
    if unit:
        return unit
    total = _to_float(item.get(f"total_{kind}_weight", 0))
    if total and quantity:
        return round(total / quantity, 4)
    return 0.0


def _to_float(value) -> float:
    if isinstance(value, str):
        match = re.search(r"-?\d[\d,]*\.?\d*", value)
        value = match.group(0).replace(",", "") if match else ""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
