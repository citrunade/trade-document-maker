"""
数据模型定义
使用简单 dict 结构 + 辅助函数，方便直接序列化为 JSON，无需额外 ORM。
"""
import uuid


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def make_customer(
    name_cn="", name_en="", consignee="", notify_party="",
    dest_country="", pod="", vat_id="", email="", remark="",
) -> dict:
    return {
        "id": new_id(),
        "name_cn": name_cn,
        "name_en": name_en,
        "consignee": consignee,
        "notify_party": notify_party,
        "dest_country": dest_country,
        "pod": pod,
        "vat_id": vat_id,
        "email": email,
        "remark": remark,
    }


def make_product(
    model_no="", name_cn="", name_en="", hs_code="", unit="pcs",
    net_weight=0.0, gross_weight=0.0, length_mm=0.0, width_mm=0.0,
    height_mm=0.0, unit_price=0.0, currency="USD", remark="",
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
    }


def make_document(
    pi_number="", ci_number="", pl_number="", customer: dict = None, currency="USD",
    incoterm="FOB", pol="", pod="", payment_terms="", validity="",
    lines=None, remark="", date="",
) -> dict:
    """
    单据主记录（一套业务对应一份 PI + CI + PL，共用客户/产品/条款数据）。
    三份单据各自拥有独立编号，但明细行、客户、贸易条款完全联动共享，
    确保同一笔业务的三份单据数据始终一致。
    """
    customer = customer or {}
    return {
        "id": new_id(),
        "pi_number": pi_number,
        "ci_number": ci_number,
        "pl_number": pl_number,
        "date": date,
        "customer_id": customer.get("id", ""),
        "customer_snapshot": customer,
        "currency": currency,
        "incoterm": incoterm,
        "pol": pol,
        "pod": pod,
        "payment_terms": payment_terms,
        "validity": validity,
        "lines": lines or [],
        "remark": remark,
    }
