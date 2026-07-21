"""
PDF 中文字体注册模块
优先加载 Windows 系统自带的微软雅黑 (msyh.ttc)，其次宋体 (simsun.ttc)，
若两者都无法读取（极端情况，如非 Windows 环境或字体缺失），
最终回退到 ReportLab 内置的 CID 字体 STSong-Light，保证任何情况下
都不会出现中文乱码、黑框或程序崩溃。
"""
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from core.paths import get_windows_font_path

_REGISTERED = {"regular": None, "bold": None}


def _try_register_ttc(font_name: str, filename: str, subfont_index: int = 0) -> bool:
    path = get_windows_font_path(filename)
    try:
        pdfmetrics.registerFont(TTFont(font_name, path, subfontIndex=subfont_index))
        return True
    except Exception:
        return False


def ensure_fonts_registered() -> tuple:
    """
    确保中文字体已注册，返回 (常规字体名, 粗体字体名)。
    重复调用是安全的（只会真正注册一次）。
    """
    if _REGISTERED["regular"]:
        return _REGISTERED["regular"], _REGISTERED["bold"]

    # 微软雅黑：msyh.ttc 内通常包含 Regular(0) 与 Bold(1)，不同 Windows 版本可能只有 Regular
    if _try_register_ttc("CJK-Regular", "msyh.ttc", 0):
        regular = "CJK-Regular"
        bold = "CJK-Regular"
        if _try_register_ttc("CJK-Bold", "msyh.ttc", 1):
            bold = "CJK-Bold"
        _REGISTERED["regular"], _REGISTERED["bold"] = regular, bold
        return regular, bold

    # 宋体回退
    if _try_register_ttc("CJK-Regular", "simsun.ttc", 0):
        _REGISTERED["regular"], _REGISTERED["bold"] = "CJK-Regular", "CJK-Regular"
        return _REGISTERED["regular"], _REGISTERED["bold"]

    # 最终回退：ReportLab 内置 CID 字体，无需任何外部文件，绝不会缺失
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        pass
    _REGISTERED["regular"], _REGISTERED["bold"] = "STSong-Light", "STSong-Light"
    return _REGISTERED["regular"], _REGISTERED["bold"]
