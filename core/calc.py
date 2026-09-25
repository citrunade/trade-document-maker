"""
外贸单据核心计算逻辑
所有金额/重量/体积的计算集中在此，PDF 导出与界面显示共用同一套逻辑，
避免出现界面与导出 PDF 数据不一致的问题。
"""

ONES = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]
TEENS = ["TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN",
         "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]
SCALES = ["", "THOUSAND", "MILLION", "BILLION", "TRILLION"]

CURRENCY_NAMES = {
    "USD": "US DOLLARS",
    "EUR": "EUROS",
    "RMB": "RMB YUAN",
    "CNY": "RMB YUAN",
    "SGD": "SINGAPORE DOLLARS",
    "HKD": "HONG KONG DOLLARS",
    "GBP": "POUNDS STERLING",
    "JPY": "JAPANESE YEN",
}


def line_subtotal(quantity: float, unit_price: float) -> float:
    return round(quantity * unit_price, 2)


def line_total_net_weight(quantity: float, net_weight: float) -> float:
    # 保留 3 位：小件（如 3 × 0.004 kg）按 2 位会被舍成 0.01
    return round(quantity * net_weight, 3)


def line_total_gross_weight(quantity: float, gross_weight: float) -> float:
    return round(quantity * gross_weight, 3)


def line_total_cbm(quantity: float, length_mm: float, width_mm: float, height_mm: float) -> float:
    cbm = quantity * (length_mm * width_mm * height_mm) / 1_000_000_000
    return round(cbm, 3)


def compute_line(line: dict) -> dict:
    """给一条单据明细行补充计算字段，返回新 dict（不修改原对象）。"""
    result = dict(line)
    qty = line.get("quantity", 0.0)
    result["subtotal"] = line_subtotal(qty, line.get("unit_price", 0.0))
    result["total_net_weight"] = line_total_net_weight(qty, line.get("net_weight", 0.0))
    result["total_gross_weight"] = line_total_gross_weight(qty, line.get("gross_weight", 0.0))
    result["total_cbm"] = line_total_cbm(
        qty, line.get("length_mm", 0.0), line.get("width_mm", 0.0), line.get("height_mm", 0.0)
    )
    return result


def compute_totals(lines: list) -> dict:
    """计算整份单据的汇总值：总数量/总金额/总净重/总毛重/总体积。"""
    computed = [compute_line(l) for l in lines]
    return {
        "total_quantity": round(sum(l.get("quantity", 0.0) for l in computed), 3),
        "total_amount": round(sum(l["subtotal"] for l in computed), 2),
        "total_net_weight": round(sum(l["total_net_weight"] for l in computed), 3),
        "total_gross_weight": round(sum(l["total_gross_weight"] for l in computed), 3),
        "total_cbm": round(sum(l["total_cbm"] for l in computed), 3),
        "lines": computed,
    }


def _under_thousand_words(n: int) -> str:
    words = []
    if n >= 100:
        words.append(ONES[n // 100] + " HUNDRED")
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10])
        if n % 10:
            words.append(ONES[n % 10])
    elif n >= 10:
        words.append(TEENS[n - 10])
    elif n > 0:
        words.append(ONES[n])
    return " ".join(words)


def number_to_words(n: int) -> str:
    """将整数转换为英文大写单词，如 1234 -> ONE THOUSAND TWO HUNDRED THIRTY FOUR"""
    if n == 0:
        return "ZERO"
    parts = []
    scale_idx = 0
    while n > 0:
        chunk = n % 1000
        if chunk:
            chunk_words = _under_thousand_words(chunk)
            if SCALES[scale_idx]:
                chunk_words += " " + SCALES[scale_idx]
            parts.append(chunk_words)
        n //= 1000
        scale_idx += 1
    return " ".join(reversed(parts))


def amount_in_words(amount: float, currency: str = "USD") -> str:
    """
    生成标准外贸大写金额声明，如：
    SAY TOTAL US DOLLARS ONE THOUSAND TWO HUNDRED AND THIRTY FOUR AND CENTS FIFTY ONLY
    """
    currency_name = CURRENCY_NAMES.get(currency.upper(), currency.upper())
    whole = int(amount)
    cents = round((amount - whole) * 100)
    if cents == 100:
        whole += 1
        cents = 0

    whole_words = number_to_words(whole) if whole > 0 else "ZERO"
    text = f"SAY TOTAL {currency_name} {whole_words}"
    if cents > 0:
        cents_words = number_to_words(cents)
        text += f" AND CENTS {cents_words} ONLY"
    else:
        text += " ONLY"
    return text


# ---------------- 付款条件（定金/尾款拆分） ----------------
# deposit_pct 为定金百分比：None 表示不拆分（沿用 Conditions 模板中的付款方式文字），
# 100 表示 100% 预付，其余如 50 表示 50% 定金 + 50% 尾款。
PAYMENT_PRESETS = [
    ("按模板（不拆分金额）", None),
    ("100% 预付", 100),
    ("50% 定金 + 50% 尾款", 50),
    ("30% 定金 + 70% 尾款", 30),
]


def payment_terms_text(deposit_pct) -> str:
    if deposit_pct is None:
        return ""
    if deposit_pct >= 100:
        return "100% T/T in advance"
    return f"{deposit_pct:g}% deposit by T/T, {100 - deposit_pct:g}% balance before shipment"


def payment_schedule(total_amount: float, deposit_pct) -> list:
    """
    返回 [(label, amount), ...]。尾款 = 总额 - 定金，保证两次付款相加恰好等于总额，
    不会因四舍五入产生 0.01 的差额。
    """
    if deposit_pct is None:
        return []
    if deposit_pct >= 100:
        return [("100% Payment in Advance", round(total_amount, 2))]
    deposit = round(total_amount * deposit_pct / 100, 2)
    balance = round(total_amount - deposit, 2)
    return [
        (f"{deposit_pct:g}% Deposit (due upon order confirmation)", deposit),
        (f"{100 - deposit_pct:g}% Balance (due before shipment)", balance),
    ]


def fmt_weight(value: float) -> str:
    """重量为 0（即没有重量信息）时显示空白，而不是 0.00。"""
    if not value:
        return ""
    text = f"{value:.3f}"
    return text[:-1] if text.endswith("0") else text


def effective_terms_of_payment(doc: dict) -> str:
    """选定了付款拆分时用其生成的文字，否则沿用 Conditions 模板中的付款方式。"""
    return payment_terms_text(doc.get("deposit_pct")) or doc.get("conditions_snapshot", {}).get("terms_of_payment", "")


def fmt_qty(value: float) -> str:
    """数量：整数不带小数位，带千分位；避免 :g 在大数时输出科学计数法（如 1.2e+06）。"""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


PRICE_DECIMALS = 4


def fmt_unit_price(value: float) -> str:
    """单价至少 2 位、最多 4 位小数：0.125 显示为 0.125 而不是 0.13，保证 单价×数量 与总价对得上。"""
    text = f"{value:,.{PRICE_DECIMALS}f}"
    while text.endswith("0") and len(text.split(".")[1]) > 2:
        text = text[:-1]
    return text


def summary_parts(totals: dict) -> list:
    """单据底部汇总：总数量 + 有数据时才显示的总净重/总毛重/总体积（没有数据不显示 0）。"""
    parts = [f"Total Qty: {fmt_qty(totals['total_quantity'])}"]
    if totals["total_net_weight"]:
        parts.append(f"Total N.W.: {fmt_weight(totals['total_net_weight'])} kg")
    if totals["total_gross_weight"]:
        parts.append(f"Total G.W.: {fmt_weight(totals['total_gross_weight'])} kg")
    if totals["total_cbm"]:
        parts.append(f"Total Measurement: {totals['total_cbm']:.3f} CBM")
    return parts
