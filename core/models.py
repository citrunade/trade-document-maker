"""
数据模型定义
使用简单 dict 结构 + 辅助函数，方便直接序列化为 JSON，无需额外 ORM。
"""
import uuid

from core import storage


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def make_customer(
    customer_id=None, name_cn="", name_en="", country_region="", city="",
    address_en="", tax_no="", contact_person="", email="", tel_phone="",
    company_reg_no="", gst_no="", consignee="", notify_party="", pod="", remark="",
) -> dict:
    """
    客户主体信息，字段规范见 docs/客户主体信息设计文档.md。
    customer_id 为主键（格式 CUST-0001），未传入时自动生成新编号。
    company_reg_no/gst_no 为单据表头展示用的扩展字段。
    consignee/notify_party/pod/remark 为外贸制单业务扩展字段，
    不属于 OCR 提取的 10 个核心字段，但制单生成单据时可能用到。
    """
    return {
        "customer_id": customer_id or storage.generate_customer_id(),
        "name_cn": name_cn,
        "name_en": name_en,
        "country_region": country_region,
        "city": city,
        "address_en": address_en,
        "tax_no": tax_no,
        "contact_person": contact_person,
        "email": email,
        "tel_phone": tel_phone,
        "company_reg_no": company_reg_no,
        "gst_no": gst_no,
        "consignee": consignee,
        "notify_party": notify_party,
        "pod": pod,
        "remark": remark,
    }


def make_product(
    model_no="", name_cn="", name_en="", hs_code="", unit="pcs",
    net_weight=0.0, gross_weight=0.0, length_mm=0.0, width_mm=0.0,
    height_mm=0.0, unit_price=0.0, currency="USD", coo="", remark="",
) -> dict:
    return {
        "id": new_id(),
        "model_no": model_no,
        "name_cn": name_cn,
        "name_en": name_en,
        "hs_code": hs_code,
        "unit": unit,
        "net_weight": float(net_weight),
        "gross_weight": float(gross_weight),
        "length_mm": float(length_mm),
        "width_mm": float(width_mm),
        "height_mm": float(height_mm),
        "unit_price": float(unit_price),
        "currency": currency,
        "coo": coo,
        "remark": remark,
    }


def make_doc_line(product: dict = None, quantity: float = 0.0, unit_price: float = None) -> dict:
    """
    单据明细行。从物料库产品创建时会拷贝一份快照数据，
    这样即便日后物料库中该产品被修改/删除，历史单据数据依然完整不变。
    """
    product = product or {}
    return {
        "product_id": product.get("id", ""),
        "model_no": product.get("model_no", ""),
        "name_cn": product.get("name_cn", ""),
        "name_en": product.get("name_en", ""),
        "hs_code": product.get("hs_code", ""),
        "unit": product.get("unit", "pcs"),
        "quantity": float(quantity),
        "unit_price": float(unit_price if unit_price is not None else product.get("unit_price", 0.0)),
        "net_weight": float(product.get("net_weight", 0.0)),
        "gross_weight": float(product.get("gross_weight", 0.0)),
        "length_mm": float(product.get("length_mm", 0.0)),
        "width_mm": float(product.get("width_mm", 0.0)),
        "height_mm": float(product.get("height_mm", 0.0)),
        "coo": product.get("coo", ""),
        "remark": product.get("remark", ""),
    }


TEMPLATE_CATEGORIES = ("own", "delivery", "conditions", "banking")


def make_template(category: str, name: str = "", fields: dict = None) -> dict:
    """
    通用模板预设。category 为四类之一：
    - own：本公司信头（Logo/名称/地址/电话/公司注册号/GST号）
    - delivery：收货地址
    - conditions：付款方式/贸易术语/运输方式
    - banking：银行信息（每页页脚）+ 收款银行详情（仅末页）
    每一类可保存多个命名预设，制单时按需选择。
    """
    assert category in TEMPLATE_CATEGORIES, f"未知模板类别：{category}"
    return {
        "id": new_id(),
        "category": category,
        "name": name,
        "fields": fields or {},
    }


def make_document(
    doc_type="PI", doc_number="", customer: dict = None, currency="USD",
    destination="",
    own_snapshot=None, delivery_snapshot=None, conditions_snapshot=None, banking_snapshot=None,
    lines=None, remark="", date="", validity_start="", validity_end="",
) -> dict:
    """
    单据主记录：一次只生成一份文档（PI / CI / PL 之一，标题不同，其余格式统一）。
    Own/Delivery/Conditions/Banking 四类模板选定后，将其内容快照保存进单据本身，
    确保日后模板被编辑或删除也不影响历史单据的显示与重新导出。
    """
    customer = customer or {}
    return {
        "id": new_id(),
        "doc_type": doc_type,
        "doc_number": doc_number,
        "date": date,
        "customer_id": customer.get("customer_id", ""),
        "customer_snapshot": customer,
        "currency": currency,
        "destination": destination,
        "own_snapshot": own_snapshot or {},
        "delivery_snapshot": delivery_snapshot or {},
        "conditions_snapshot": conditions_snapshot or {},
        "banking_snapshot": banking_snapshot or {},
        "validity_start": validity_start,
        "validity_end": validity_end,
        "lines": lines or [],
        "remark": remark,
    }
