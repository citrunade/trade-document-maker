"""
本地 JSON 存储引擎
所有基础数据（公司信息、客户、物料、单据、编号计数器）均以 JSON 文件形式
存储在 data/ 目录下。不使用任何数据库或网络服务。
"""
import json
import os
import shutil
from datetime import datetime
from typing import Any

from core.paths import get_data_path, get_backups_dir, get_data_dir


def _read_json(filename: str, default: Any) -> Any:
    path = get_data_path(filename)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
    except (json.JSONDecodeError, OSError):
        # 文件损坏时不崩溃，返回默认值，避免软件无法启动
        return default


def _write_json(filename: str, data: Any) -> None:
    path = get_data_path(filename)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 原子替换，防止写入过程中断电/崩溃导致文件损坏
    os.replace(tmp_path, path)


# ---------- 公司信息（设置） ----------
COMPANY_FILE = "company.json"

DEFAULT_COMPANY = {
    "name_cn": "示例贸易有限公司",
    "name_en": "SAMPLE TRADING CO., LTD.",
    "address_cn": "中国广东省深圳市南山区科技园示例路1号",
    "address_en": "No.1 Sample Road, Nanshan District, Shenzhen, Guangdong, China",
    "phone": "+86 755 12345678",
    "email": "sales@sampletrading.com",
    "tax_id": "91440300MA5EXAMPLE",
    "bank_name_cn": "中国银行深圳分行",
    "bank_name_en": "BANK OF CHINA, SHENZHEN BRANCH",
    "bank_account": "1234 5678 9012 3456",
    "swift_code": "BKCHCNBJ400",
    "bank_address_en": "No.88 Sample Ave, Shenzhen, China",
    "default_pol": "Shenzhen, China",
    "default_incoterm": "FOB",
    "logo_path": "logo.png",
    "zhipu_api_key": "",
    "zhipu_base_url": "",
    "zhipu_text_model": "",
    "zhipu_vision_model": "",
}


def load_company() -> dict:
    data = _read_json(COMPANY_FILE, None)
    if data is None:
        data = DEFAULT_COMPANY.copy()
        _write_json(COMPANY_FILE, data)
        return data
    # 兼容旧版本数据文件：自动补全新增字段的默认值，避免 KeyError
    updated = False
    for key, value in DEFAULT_COMPANY.items():
        if key not in data:
            data[key] = value
            updated = True
    if updated:
        _write_json(COMPANY_FILE, data)
    return data


def save_company(data: dict) -> None:
    _write_json(COMPANY_FILE, data)


# ---------- 客户档案 ----------
CUSTOMERS_FILE = "customers.json"


def load_customers() -> list:
    return _read_json(CUSTOMERS_FILE, [])


def save_customers(customers: list) -> None:
    _write_json(CUSTOMERS_FILE, customers)


# ---------- 物料库 ----------
PRODUCTS_FILE = "products.json"


def load_products() -> list:
    return _read_json(PRODUCTS_FILE, [])


def save_products(products: list) -> None:
    _write_json(PRODUCTS_FILE, products)


# ---------- 单据历史 ----------
DOCUMENTS_FILE = "documents.json"


def load_documents() -> list:
    return _read_json(DOCUMENTS_FILE, [])


def save_documents(documents: list) -> None:
    _write_json(DOCUMENTS_FILE, documents)


# ---------- 单据编号计数器 ----------
COUNTERS_FILE = "counters.json"


def load_counters() -> dict:
    return _read_json(COUNTERS_FILE, {})


def save_counters(counters: dict) -> None:
    _write_json(COUNTERS_FILE, counters)


def generate_doc_number(prefix: str) -> str:
    """
    生成单据编号：前缀 + 年月(YYYYMM) + 3位流水号
    例如：PI202607001
    """
    now = datetime.now()
    period = now.strftime("%Y%m")
    key = f"{prefix}{period}"
    counters = load_counters()
    seq = counters.get(key, 0) + 1
    counters[key] = seq
    save_counters(counters)
    return f"{key}{seq:03d}"


# ---------- 数据备份与还原 ----------
def backup_data() -> str:
    """将整个 data/ 目录打包为 zip 备份文件，返回备份文件路径。"""
    backups_dir = get_backups_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_base = os.path.join(backups_dir, f"backup_{timestamp}")
    data_dir = get_data_dir()

    # 备份目录本身不应被打包进自己的备份里
    exclude_dir = os.path.abspath(backups_dir)

    tmp_stage = archive_base + "_stage"
    if os.path.exists(tmp_stage):
        shutil.rmtree(tmp_stage)
    os.makedirs(tmp_stage)

    for item in os.listdir(data_dir):
        src = os.path.join(data_dir, item)
        if os.path.abspath(src) == exclude_dir:
            continue
        dst = os.path.join(tmp_stage, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    archive_path = shutil.make_archive(archive_base, "zip", tmp_stage)
    shutil.rmtree(tmp_stage)
    return archive_path


def restore_data(zip_path: str) -> None:
    """从备份 zip 文件恢复 data/ 目录（覆盖现有 JSON 与 logo）。"""
    data_dir = get_data_dir()
    shutil.unpack_archive(zip_path, data_dir, "zip")
