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
- 长文件：按内容量拆成多段分别调用模型（并行、临时错误自动重试）后合并结果，避免一次塞入
  太多页导致漏行。PDF 文字页按字数分段、扫描页每段最多 2 页；Excel 按工作表、Word 按表格分段，
  只有单个表超长时才按行拆开。续段附带表头与相邻段交界处的文字作参考；合并时把装箱单的重量
  并入发票行、去掉跨段重复的行。

所有函数返回结构化 dict/list，调用方（UI 层）负责展示审核对话框，
本模块不直接写入任何本地数据文件。
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import fitz  # PyMuPDF

from core import ai_client
from core.models import make_customer, make_product, make_doc_line

SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".jpg", ".jpeg", ".png"}

# 判定"文字内容过于稀疏、需改用图片识别"的最小有效字符数阈值
MIN_TEXT_CHARS = 20

# 长文件分段识别：一次塞入太多页时模型容易漏行、串行，因此按页/按字数拆成多次调用后合并结果
TEXT_CHUNK_CHARS = 8_000
# PDF 每段页数上限：文字很少的页也不要无限合并；扫描页图片较"重"，每段最多 2 页
PDF_MAX_PAGES_PER_CHUNK = 6
PDF_MAX_IMAGES_PER_CHUNK = 2
# 续段附带的表头（列名），帮助模型理解没有表头的续段表格
CHUNK_HEAD_CHARS = 1_500
# 相邻段交界处附带的参考文字，用于还原被分页截断的明细行
BOUNDARY_CONTEXT_CHARS = 600
# 分段数上限；超出时提示拆分，而不是静默截断
MAX_CHUNKS = 20
# 同时进行的请求数：过多容易触发百炼限流（429）
MAX_PARALLEL_REQUESTS = 3
# 网络抖动/限流等临时错误的重试等待秒数（共重试 len 次）
RETRY_DELAYS = (3, 8)


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
def xlsx_sections(path: str) -> list:
    """
    读取所有工作表，返回 [("工作表：名称", Markdown 表格), ...]。
    发票与装箱单常分属不同工作表（重量通常只在 Packing List 中），只读第一张表会漏掉重量。
    header=None 保留原始表头行，避免出现 "Unnamed: 3" 这类列名。
    """
    import pandas as pd
    sheets = pd.read_excel(path, dtype=str, header=None, sheet_name=None)
    sections = []
    for name, df in sheets.items():
        df = df.fillna("").astype(str)
        df = df.loc[(df != "").any(axis=1), (df != "").any(axis=0)]
        if df.empty:
            continue
        sections.append((f"工作表：{name}", df.to_markdown(index=False, headers=[""] * df.shape[1])))
    return sections


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
    返回 (sections, images)：sections 为 [("正文" / "表格 n", 文字), ...]，
    每个表格单独成一节，长文件分段时不会把两个表格拆散混在一起；images 为图片字节列表。
    """
    import docx
    document = docx.Document(path)

    sections = []
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    if paragraphs:
        sections.append(("正文", "\n".join(paragraphs)))
    for n, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            sections.append((f"表格 {n}", "\n".join(rows)))

    images = []
    for rel in document.part.rels.values():
        if "image" in rel.reltype:
            try:
                images.append(rel.target_part.blob)
            except Exception:
                continue

    return sections, images


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


class ImportCancelled(AIImportError):
    """用户在进度窗口中点了取消。"""


def _split_text(text: str, limit: int = TEXT_CHUNK_CHARS) -> list:
    """按行把长文字切成不超过 limit 字符的若干段（不在行中间切断，避免拆散表格行）。"""
    chunks, current, size = [], [], 0
    for line in text.splitlines():
        while len(line) > limit:  # 极端情况：单行超长，只能硬切
            if current:
                chunks.append("\n".join(current))
                current, size = [], 0
            chunks.append(line[:limit])
            line = line[limit:]
        if size + len(line) + 1 > limit and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


def _head_lines(text: str, limit: int) -> str:
    """取文字开头的若干整行，总长不超过 limit（至少一行）。"""
    out, size = [], 0
    for line in text.splitlines():
        if out and size + len(line) + 1 > limit:
            break
        out.append(line[:limit])
        size += len(line) + 1
    return "\n".join(out).strip()


def _tail_lines(text: str, limit: int) -> str:
    """取文字结尾的若干整行，总长不超过 limit（至少一行）。"""
    out, size = [], 0
    for line in reversed(text.splitlines()):
        if out and size + len(line) + 1 > limit:
            break
        out.insert(0, line[-limit:])
        size += len(line) + 1
    return "\n".join(out).strip()


def _part_note(index: int, total: int, where: str = "", boundary: bool = False) -> str:
    if total <= 1:
        return ""
    where = f"（{where}）" if where else ""
    note = (
        f"注意：这是一份长文件的第 {index}/{total} 部分{where}，文件被拆成多段分别识别。"
        "只提取【以下是本部分需要提取的内容】中出现的明细行/产品，标注“仅供参考”的内容一律不要提取，"
        "也不要猜测或补充其他部分的内容；合计数量/金额只在本部分中印有整份文件的总计时才填写，否则填 0。"
    )
    if boundary:
        note += (
            "如果某个明细行被分页截断、跨越两个部分，由该行开始所在的部分输出完整的一行"
            "（可参考【下一部分开头】补全），后一部分不要重复输出它。"
        )
    return note


def _compose(note: str, contexts: list, content: str) -> str:
    """把分段说明、参考上下文与本段内容拼成发给模型的文字。contexts: [(标题, 文字), ...]"""
    if not note:
        return content
    parts = [note]
    for title, text in contexts:
        if text and text.strip():
            parts.append(f"【{title}】\n{text.strip()}")
    parts.append("【以下是本部分需要提取的内容】\n" + content)
    return "\n\n".join(parts)


def _pack_sections(sections: list) -> list:
    """
    把 [(标题, 文字), ...]（工作表/Word 表格）打包成若干段：
    - 整个工作表放得下时绝不拆开，几个小工作表合在同一段（发票与装箱单在同一次调用中才能按型号合并重量）；
    - 单个工作表超长时才按行拆分，续段附带该工作表自己的开头（表头行），而不是第一张表的表头。
    返回 [{"content", "head", "source"}, ...]
    """
    chunks, current, titles, size = [], [], [], 0

    def flush():
        nonlocal current, titles, size
        if current:
            chunks.append({"content": "\n\n".join(current), "head": "", "source": "、".join(t for t in titles if t)})
        current, titles, size = [], [], 0

    for title, text in sections:
        if not text.strip():
            continue
        block = f"## {title}\n\n{text}" if title else text
        if len(block) <= TEXT_CHUNK_CHARS:
            if current and size + len(block) > TEXT_CHUNK_CHARS:
                flush()
            current.append(block)
            titles.append(title)
            size += len(block) + 2
            continue
        flush()
        pieces = _split_text(block)
        head = _head_lines(block, CHUNK_HEAD_CHARS)
        for j, piece in enumerate(pieces, start=1):
            source = f"{title} 第 {j}/{len(pieces)} 段" if title else f"第 {j}/{len(pieces)} 段"
            chunks.append({"content": piece, "head": head if j > 1 else "", "source": source})
    flush()
    return chunks


def _section_tasks(sections: list) -> list:
    chunks = _pack_sections(sections)
    total = len(chunks)
    tasks = []
    for i, chunk in enumerate(chunks, start=1):
        note = _part_note(i, total, chunk["source"])
        contexts = [("本表开头（仅供参考：用于理解表头/列含义，不要从这里提取任何明细行或产品）", chunk["head"])]
        tasks.append({
            "kind": "text",
            "text": _compose(note, contexts, chunk["content"]),
            "source": chunk["source"] if total > 1 else "",
        })
    return tasks


def _pdf_head(page_text: str) -> str:
    """第 1 页的表头参考：表格前的文字（抬头等）+ 表格的表头行；避免把第 1 页的明细行也当作参考。"""
    marker = "【表格（行列结构）】"
    if marker not in page_text:
        return _head_lines(page_text, CHUNK_HEAD_CHARS)
    before, tables = page_text.split(marker, 1)
    table_lines = [l for l in tables.splitlines() if l.strip()][:2]  # 表头行 + 分隔行
    return (_head_lines(before, CHUNK_HEAD_CHARS - 300) + "\n\n" + "\n".join(table_lines)).strip()


def _group_pdf_pages(pages: list) -> list:
    """
    按内容量分组：文字页按字数累计（文字少的页可以多放几页，减少调用次数与跨段截断），
    扫描页较"重"，每段最多 PDF_MAX_IMAGES_PER_CHUNK 页。返回 [[(页码, 页内容), ...], ...]
    """
    groups, current, chars, images = [], [], 0, 0
    for number, page in enumerate(pages, start=1):
        is_image = page[0] == "image"
        length = 0 if is_image else len(page[1])
        if current and (
            len(current) >= PDF_MAX_PAGES_PER_CHUNK
            or (is_image and images >= PDF_MAX_IMAGES_PER_CHUNK)
            or chars + length > TEXT_CHUNK_CHARS
        ):
            groups.append(current)
            current, chars, images = [], 0, 0
        current.append((number, page))
        chars += length
        images += is_image
    if current:
        groups.append(current)
    return groups


def _pdf_chunk_tasks(pages: list) -> list:
    """纯文字段走文本模型，含扫描页的段走视觉模型；续段附带第 1 页表头与相邻段的交界文字。"""
    groups = _group_pdf_pages(pages)
    total = len(groups)
    texts = ["\n\n".join(p[1] for _, p in g if p[0] == "text") for g in groups]
    first_page_head = _pdf_head(pages[0][1]) if pages[0][0] == "text" else ""
    tasks = []
    for i, group in enumerate(groups):
        first, last = group[0][0], group[-1][0]
        pages_label = f"第 {first} 页" if first == last else f"第 {first}–{last} 页"
        note = _part_note(i + 1, total, f"{pages_label}，共 {len(pages)} 页", boundary=True)
        contexts = []
        if total > 1:
            if i > 0:
                contexts.append((
                    "文件第 1 页的抬头与表头（仅供参考：用于理解表头/列含义，不要从这里提取任何明细行或产品）",
                    first_page_head,
                ))
                contexts.append(("上一部分结尾（仅供参考，不要提取）", _tail_lines(texts[i - 1], BOUNDARY_CONTEXT_CHARS)))
            if i + 1 < total:
                contexts.append(("下一部分开头（仅供参考，不要提取）", _head_lines(texts[i + 1], BOUNDARY_CONTEXT_CHARS)))
        images = [p[1] for _, p in group if p[0] == "image"]
        source = pages_label if total > 1 else ""
        if images:
            # 存在扫描页：扫描页图片与文字页内容一起交给视觉模型，两者都不遗漏
            context_text = "\n\n".join(f"【{t}】\n{c}" for t, c in contexts if c and c.strip())
            tasks.append({
                "kind": "images", "images": images, "text": texts[i],
                "note": (note + "\n\n" + context_text).strip(), "source": source,
            })
        else:
            tasks.append({"kind": "text", "text": _compose(note, contexts, texts[i]), "source": source})
    return tasks


def _build_tasks(path: str) -> list:
    """
    根据文件类型把文件内容整理成一个或多个识别任务（dict）：
    kind = "text"（text）/ "image"（image, mime）/ "images"（images, text, note），
    source 为该段在原文件中的位置（第几页/哪个工作表），单段文件为空。
    """
    kind = get_file_kind(path)

    if kind == "xlsx":
        sections = xlsx_sections(path)
        table_text = "".join(text for _, text in sections)
        if len(table_text.strip()) >= MIN_TEXT_CHARS:
            return _section_tasks(sections)
        # 表格文字内容过于稀疏（如产品信息以图片贴在单元格中），改用嵌入图片走视觉模型
        images = xlsx_extract_images(path)
        if images:
            return [{"kind": "image", "image": images[0], "mime": "image/png", "source": ""}]
        if table_text.strip():
            return _section_tasks(sections)
        raise AIImportError("无法从该 Excel 文件中读取任何可识别内容（表格为空且未找到嵌入图片）。")

    if kind == "docx":
        sections, images = extract_docx_content(path)
        text = "".join(t for _, t in sections)
        if len(text.strip()) >= MIN_TEXT_CHARS:
            return _section_tasks(sections)
        # 文字内容过于稀疏（如整页以图片排版），改用嵌入图片走视觉模型
        if images:
            return [{"kind": "image", "image": images[0], "mime": "image/png", "source": ""}]
        if text.strip():
            return _section_tasks(sections)
        raise AIImportError("无法从该 Word 文件中读取任何可识别内容（文档为空且未找到嵌入图片）。")

    if kind == "image":
        with open(path, "rb") as f:
            image_bytes = f.read()
        ext = os.path.splitext(path)[1].lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        return [{"kind": "image", "image": image_bytes, "mime": mime, "source": ""}]

    if kind == "pdf":
        pages = extract_pdf_pages(path)
        if not pages:
            raise AIImportError("无法从该 PDF 中读取任何内容（可能是空白文件）。")
        return _pdf_chunk_tasks(pages)

    raise AIImportError(f"未知文件类型：{kind}")


def _run_extraction(path: str, prompt: str, config: dict, *, first_part_only: bool = False,
                    progress=None, cancel=None) -> list:
    """
    调用阿里云百炼 API 识别文件，返回 [(模型原始回复, 来源位置), ...]（按文件顺序）。
    长文件会拆成多段并行识别；first_part_only 只识别第一段（如客户信息通常只在开头）。
    progress(done, total) 在每段完成后回调（在工作线程中调用）；
    cancel 为 threading.Event，置位后尽快停止（已发出的请求无法中断，结果被丢弃）。
    """
    api_key = config.get("bailian_api_key", "")
    base_url = config.get("bailian_base_url") or ai_client.DEFAULT_BASE_URL
    text_model = config.get("bailian_text_model") or ai_client.DEFAULT_TEXT_MODEL
    vision_model = config.get("bailian_vision_model") or ai_client.DEFAULT_VISION_MODEL

    tasks = _build_tasks(path)
    if first_part_only:
        tasks = tasks[:1]
    if len(tasks) > MAX_CHUNKS:
        raise AIImportError(
            f"文件内容过多（需拆成 {len(tasks)} 段识别，上限 {MAX_CHUNKS} 段）。"
            "请删除无关的页面/工作表，或拆分成几个文件分别导入。"
        )

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ImportCancelled("已取消导入。")

    def call(task):
        if task["kind"] == "text":
            return ai_client.extract_from_text(api_key, base_url, text_model, prompt, task["text"])
        if task["kind"] == "image":
            return ai_client.extract_from_image(
                api_key, base_url, vision_model, prompt, task["image"], task["mime"],
            )
        return ai_client.extract_from_images(
            api_key, base_url, vision_model, prompt, task["images"], "image/png",
            extra_text=task["text"], note=task["note"],
        )

    def run(task):
        # 分段越多，越可能碰上一次网络抖动/限流；临时性错误自动重试，而不是让整个导入失败
        for attempt in range(len(RETRY_DELAYS) + 1):
            check_cancel()
            try:
                return call(task)
            except ai_client.AIClientError as exc:
                if not exc.retryable or attempt == len(RETRY_DELAYS):
                    raise
            delay = RETRY_DELAYS[attempt]
            if cancel is not None:
                cancel.wait(delay)
            else:
                time.sleep(delay)

    total = len(tasks)
    if progress:
        progress(0, total)
    if total == 1:
        raw = run(tasks[0])
        check_cancel()
        if progress:
            progress(1, 1)
        return [(raw, tasks[0]["source"])]

    results = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
        futures = [pool.submit(run, t) for t in tasks]
        try:
            for i, future in enumerate(futures, start=1):
                try:
                    results.append((future.result(), tasks[i - 1]["source"]))
                except ai_client.AIClientError as exc:
                    raise ai_client.AIClientError(f"第 {i}/{total} 部分识别失败：{exc}") from exc
                check_cancel()
                if progress:
                    progress(i, total)
        except BaseException:
            # 一段失败即整体失败（绝不返回缺段的部分结果），取消尚未开始的请求
            for f in futures:
                f.cancel()
            raise
    return results


def _parse_items(results: list, what: str) -> tuple:
    """
    解析每段回复中的 items 数组。
    返回 ([(段序号, item), ...], [每段的顶层 JSON 对象])；item 的 "_source" 记录其在原文件中的位置。
    """
    items, objects = [], []
    for part, (raw, source) in enumerate(results, start=1):
        data = _parse_json_response(raw)
        # 百炼 JSON Mode 顶层使用对象；兼容旧模型曾返回的直接数组格式。
        if isinstance(data, dict):
            objects.append(data)
            data = data.get("items", [])
        if not isinstance(data, list):
            raise AIImportError(f"AI 返回的{what}格式不正确（应包含 items 数组）。")
        for item in data:
            if isinstance(item, dict):
                item["_source"] = source
                items.append((part, item))
    return items, objects


def _models_text(models: list) -> str:
    return "、".join(models[:8]) + ("等" if len(models) > 8 else "")


class ExtractedLines(list):
    """识别结果列表，附带 warnings：需要用户核对的提示（合计不符、重复行、自动合并等）。"""
    warnings: list = []


# ---------------- 对外接口 ----------------
def import_customer(path: str, config: dict, progress=None, cancel=None) -> dict:
    """从文件中提取客户信息，返回一份符合 make_customer 字段结构的 dict（未保存）"""
    # 客户信息位于文件开头（抬头/买方信息），长文件只识别第一段即可
    raw, _ = _run_extraction(
        path, CUSTOMER_PROMPT, config, first_part_only=True, progress=progress, cancel=cancel,
    )[0]
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


def _is_blank(value) -> bool:
    if isinstance(value, (int, float)):
        return not value
    return not str(value or "").strip()


def _merge_repeated_products(items: list) -> tuple:
    """
    同一型号在不同段中各出现一次（目录的索引页与详情页、跨段重复等）时合并为一条：
    保留第一次出现的条目，其空白/为 0 的字段用后面条目补全。返回 (合并后的 items, 被合并的型号)。
    """
    first_seen, kept, merged = {}, [], []
    for part, item in items:
        key = _normalize_model(item.get("model_no"))
        if key in first_seen and first_seen[key][0] != part:
            target = first_seen[key][1]
            for field, value in item.items():
                if field == "_source":
                    if value and value not in target.get("_source", ""):
                        target["_source"] = "、".join(s for s in (target.get("_source"), value) if s)
                elif _is_blank(target.get(field)) and not _is_blank(value):
                    target[field] = value
            if key not in merged:
                merged.append(key)
            continue
        if key:
            first_seen.setdefault(key, (part, item))
        kept.append((part, item))
    return kept, merged


def import_products(path: str, config: dict, progress=None, cancel=None) -> list:
    """从文件中提取产品列表，返回符合 make_product 字段结构的 dict 列表（未保存）"""
    results = _run_extraction(path, PRODUCT_PROMPT, config, progress=progress, cancel=cancel)
    items, _ = _parse_items(results, "产品信息")
    items, merged = _merge_repeated_products(items)
    products = ExtractedLines()
    products.warnings = []
    if merged:
        products.warnings.append(
            f"文件较长，已分 {len(results)} 段识别；型号 {_models_text(merged)} 在多个部分中重复出现，"
            "已自动合并为一条（空白的字段用后面出现的内容补全）。"
        )
    for _part, item in items:
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
        product["_source"] = item.get("_source", "")
        products.append(product)
    return products


WEIGHT_FIELDS = ("unit_net_weight", "total_net_weight", "unit_gross_weight", "total_gross_weight")


def _has_weight(item: dict) -> bool:
    return any(_to_float(item.get(f, 0)) for f in WEIGHT_FIELDS)


def _is_priced(item: dict) -> bool:
    return bool(_to_float(item.get("unit_price", 0)) or _to_float(item.get("amount", 0)))


def _line_total_weight(item: dict, kind: str):
    """该行的合计重量；只有每件重量却没有数量时无法得出合计，返回 None。"""
    total = _to_float(item.get(f"total_{kind}_weight", 0))
    if total:
        return total
    unit = _to_float(item.get(f"unit_{kind}_weight", 0))
    quantity = _to_float(item.get("quantity", 0))
    if not unit:
        return 0.0
    return unit * quantity if quantity else None


def _merge_packing_rows(items: list) -> tuple:
    """
    发票与装箱单落在不同段时，同一型号会出现「有单价无重量」的发票行和「有重量无单价」的装箱单行。
    把装箱单行的重量并入发票行并去掉装箱单行。返回 (合并后的 items, 被合并的型号)。
    - 该型号只有一条发票行：装箱单各行（可能按箱拆成多行）的合计重量相加后填入；
    - 有多条发票行：按数量相同一一对应；对不上的保留原样，由重复提示提醒用户核对。
    """
    by_model = {}
    for idx, (part, item) in enumerate(items):
        key = _normalize_model(item.get("model_no"))
        if key:
            by_model.setdefault(key, []).append(idx)
    drop, merged = set(), []
    for key, idxs in by_model.items():
        if len({items[i][0] for i in idxs}) < 2:
            continue
        priced = [i for i in idxs if _is_priced(items[i][1]) and not _has_weight(items[i][1])]
        packing = [i for i in idxs if not _is_priced(items[i][1]) and _has_weight(items[i][1])]
        if not priced or not packing:
            continue
        if len(priced) == 1:
            target_part, target = items[priced[0]]
            rows = [i for i in packing if items[i][0] != target_part]
            if not rows:
                continue
            if len(rows) == 1:
                for f in WEIGHT_FIELDS:
                    target[f] = items[rows[0]][1].get(f, 0)
            else:
                totals = {k: [_line_total_weight(items[i][1], k) for i in rows] for k in ("net", "gross")}
                if any(v is None for vals in totals.values() for v in vals):
                    continue
                for k in ("net", "gross"):
                    target[f"unit_{k}_weight"] = 0
                    target[f"total_{k}_weight"] = round(sum(totals[k]), 4)
            drop.update(rows)
            merged.append(key)
            continue
        used = set()
        for i in packing:
            qty = _to_float(items[i][1].get("quantity", 0))
            for j in priced:
                if j in used or items[j][0] == items[i][0]:
                    continue
                if qty and abs(_to_float(items[j][1].get("quantity", 0)) - qty) < 1e-6:
                    for f in WEIGHT_FIELDS:
                        items[j][1][f] = items[i][1].get(f, 0)
                    used.add(j)
                    drop.add(i)
                    if key not in merged:
                        merged.append(key)
                    break
    return [it for idx, it in enumerate(items) if idx not in drop], merged


def _drop_boundary_duplicates(items: list) -> list:
    """
    兜底：跨页截断的行可能被相邻两段各输出一次。若上一段最后一行与下一段第一行的
    型号、数量、单价完全相同，去掉后一条。返回去掉的行的型号列表。
    """
    removed = []
    i = 1
    while i < len(items):
        (prev_part, prev), (part, item) = items[i - 1], items[i]
        model = _normalize_model(item.get("model_no"))
        if (
            part == prev_part + 1
            and model
            and model == _normalize_model(prev.get("model_no"))
            and _to_float(item.get("quantity", 0)) == _to_float(prev.get("quantity", 0))
            and _to_float(item.get("unit_price", 0)) == _to_float(prev.get("unit_price", 0))
        ):
            removed.append(str(item.get("model_no", "")))
            del items[i]
            continue
        i += 1
    return removed


def _total_mismatch(computed: float, printed: list, tolerance) -> bool:
    """文件上可能印有多个合计（发票合计、装箱单合计、每页小计）：与其中任何一个相符即视为一致。"""
    return bool(printed) and not any(abs(computed - p) <= tolerance(p) for p in printed)


def import_document_lines(path: str, config: dict, progress=None, cancel=None) -> list:
    """从采购订单(PO)等文件中提取单据明细行，返回符合 make_doc_line 字段结构的 dict 列表（未保存）"""
    results = _run_extraction(path, DOCUMENT_LINES_PROMPT, config, progress=progress, cancel=cancel)
    items, objects = _parse_items(results, "明细信息")
    printed_qty = sorted({q for q in (_to_float(o.get("doc_total_quantity", 0)) for o in objects) if q})
    printed_amount = sorted({a for a in (_to_float(o.get("doc_total_amount", 0)) for o in objects) if a})

    lines = ExtractedLines()
    lines.warnings = []
    items, merged = _merge_packing_rows(items)
    if merged:
        lines.warnings.append(
            f"文件较长，已分 {len(results)} 段识别；已把装箱单中型号 {_models_text(merged)} 的重量"
            "合并到对应的发票行，请核对重量。"
        )
    removed = _drop_boundary_duplicates(items)
    if removed:
        lines.warnings.append(
            f"型号 {_models_text(list(dict.fromkeys(removed)))} 在相邻两部分的交界处各识别出一次（跨页的行），已去掉重复的一条。"
        )

    parts_by_model = {}
    for part, item in items:
        key = _normalize_model(item.get("model_no"))
        if key:
            parts_by_model.setdefault(key, set()).add(part)
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
        line["_source"] = item.get("_source", "")
        lines.append(line)

    # 与文件上印刷的合计核对：识别错一行（如数量 1 读成 10）时，合计必然对不上
    sum_qty = round(sum(l["quantity"] for l in lines), 3)
    sum_amount = round(sum(l["quantity"] * l["unit_price"] for l in lines), 2)
    if _total_mismatch(sum_qty, printed_qty, lambda p: 0.001):
        lines.warnings.append(
            f"识别出的明细数量合计为 {sum_qty:g}，但文件上印刷的合计数量为 "
            f"{' / '.join(f'{q:g}' for q in printed_qty)}。"
        )
    if _total_mismatch(sum_amount, printed_amount, lambda p: max(0.05, p * 0.001)):
        lines.warnings.append(
            f"识别出的明细金额合计为 {sum_amount:,.2f}，但文件上印刷的合计金额为 "
            f"{' / '.join(f'{a:,.2f}' for a in printed_amount)}。"
        )
    # 合并后仍在多个部分重复出现的型号（如发票与装箱单都带单价，无法自动判断）
    repeated = sorted(k for k, parts in parts_by_model.items() if len(parts) > 1)
    if repeated:
        lines.warnings.append(
            f"文件较长，已分 {len(results)} 段识别；型号 {_models_text(repeated)} 在多个部分中重复出现，"
            "可能是发票与装箱单的重复行，请对照“来源”列核对后取消勾选多余的行。"
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
