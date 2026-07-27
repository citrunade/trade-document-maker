"""
内置默认测试数据
仅在对应的 JSON 数据文件不存在或为空列表时才会写入，避免覆盖用户已录入的数据。
提供一套通用 Exporter/Importer 示例及 5 条物料数据，方便用户第一次打开软件时
即可体验完整的制单流程。
"""
from core import storage
from core.models import make_customer, make_product, make_template


def seed_customers_if_empty() -> None:
    if storage.load_customers():
        return
    customers = [
        make_customer(
            name_cn="环球进口贸易公司",
            name_en="GLOBAL IMPORT TRADING CO., LTD.",
            country_region="United States",
            city="Los Angeles",
            address_en="123 Harbor Street, Los Angeles, CA 90001, USA",
            tax_no="US-EXAMPLE-000123",
            contact_person="John Smith",
            email="purchase@globalimport-example.com",
            tel_phone="+1 213 555 0123",
            consignee="Global Import Trading Co., Ltd.\n123 Harbor Street, Los Angeles, CA 90001, USA",
            notify_party="Same as Consignee",
            pod="Los Angeles, USA",
            remark="示例客户，可编辑或删除",
        )
    ]
    storage.save_customers(customers)


def seed_products_if_empty() -> None:
    if storage.load_products():
        return
    products = [
        make_product(
            model_no="MP-1001", name_cn="精密齿轮箱", name_en="Precision Gearbox",
            hs_code="8483.40", unit="pcs", net_weight=4.2, gross_weight=4.8,
            length_mm=300, width_mm=200, height_mm=150, unit_price=85.50, currency="USD",
        ),
        make_product(
            model_no="MP-1002", name_cn="不锈钢紧固件套装", name_en="Stainless Steel Fastener Kit",
            hs_code="7318.15", unit="set", net_weight=0.8, gross_weight=1.0,
            length_mm=150, width_mm=100, height_mm=80, unit_price=12.30, currency="USD",
        ),
        make_product(
            model_no="MP-1003", name_cn="工业控制模块", name_en="Industrial Control Module",
            hs_code="8537.10", unit="pcs", net_weight=1.5, gross_weight=1.9,
            length_mm=220, width_mm=180, height_mm=90, unit_price=156.00, currency="USD",
        ),
        make_product(
            model_no="MP-1004", name_cn="液压密封圈", name_en="Hydraulic Seal Ring",
            hs_code="4016.93", unit="pcs", net_weight=0.05, gross_weight=0.08,
            length_mm=50, width_mm=50, height_mm=20, unit_price=2.15, currency="USD",
        ),
        make_product(
            model_no="MP-1005", name_cn="铝合金外壳", name_en="Aluminum Alloy Housing",
            hs_code="7616.99", unit="pcs", net_weight=2.3, gross_weight=2.7,
            length_mm=260, width_mm=210, height_mm=110, unit_price=34.80, currency="USD",
        ),
    ]
    storage.save_products(products)


def seed_templates_if_empty() -> None:
    templates = storage.load_templates()
    if any(templates.values()):
        return
    templates["own"].append(make_template("own", "默认信头", {
        "company_name_en": "SAMPLE TRADING CO., LTD.",
        "company_name_cn": "示例贸易有限公司",
        "address": "No.1 Sample Road, Nanshan District, Shenzhen, Guangdong, China",
        "phone": "+86 755 12345678",
        "company_reg_no": "REG-EXAMPLE-0001",
        "gst_no": "",
        "contact_person": "Sales Team",
        "telephone": "+86 755 12345678",
        "email": "sales@sampletrading.com",
    }))
    templates["delivery"].append(make_template("delivery", "默认收货地址", {
        "company_name": "GLOBAL IMPORT TRADING CO., LTD.",
        "address": "123 Harbor Street, Los Angeles, CA 90001, USA",
    }))
    templates["conditions"].append(make_template("conditions", "默认条款", {
        "terms_of_payment": "30% deposit, 70% before shipment",
        "incoterm": "FOB",
        "shipment_by": "Sea Freight",
    }))
    templates["banking"].append(make_template("banking", "默认银行信息", {
        "bank_name": "BANK OF CHINA, SHENZHEN BRANCH",
        "account_no": "1234 5678 9012 3456",
        "swift_code": "BKCHCNBJ400",
        "beneficiary_name": "SAMPLE TRADING CO., LTD.",
        "beneficiary_bank_name": "BANK OF CHINA, SHENZHEN BRANCH",
        "beneficiary_swift_code": "BKCHCNBJ400",
        "correspondent_bank": "",
        "beneficiary_bank_address": "No.88 Sample Ave, Shenzhen, China",
        "beneficiary_account_no": "1234 5678 9012 3456",
    }))
    storage.save_templates(templates)


def seed_all() -> None:
    seed_customers_if_empty()
    seed_products_if_empty()
    seed_templates_if_empty()
