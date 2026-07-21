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
}


def line_subtotal(quantity: float, unit_price: float) -> float:
    return round(quantity * unit_price, 2)


def line_total_net_weight(quantity: float, net_weight: float) -> float:
    return round(quantity * net_weight, 2)


def line_total_gross_weight(quantity: float, gross_weight: float) -> float:
    return round(quantity * gross_weight, 2)


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
        "total_net_weight": round(sum(l["total_net_weight"] for l in computed), 2),
        "total_gross_weight": round(sum(l["total_gross_weight"] for l in computed), 2),
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
