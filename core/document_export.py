"""
单据导出格式分发器：根据用户选择的格式（PDF / Word / Excel）
调用对应的导出模块，统一生成输出文件路径。
"""
import os

from core import pdf_export, word_export, excel_export

FORMAT_EXTENSIONS = {"PDF": "pdf", "Word": "docx", "Excel": "xlsx"}

FORMAT_MODULES = {"PDF": pdf_export, "Word": word_export, "Excel": excel_export}


def export_document_in_format(doc: dict, fmt: str, export_dir: str) -> str:
    """
    fmt 为 "PDF" / "Word" / "Excel" 之一。
    返回生成的文件完整路径。
    """
    if fmt not in FORMAT_MODULES:
        raise ValueError(f"不支持的导出格式：{fmt}")
    ext = FORMAT_EXTENSIONS[fmt]
    filepath = os.path.join(export_dir, f"{doc.get('doc_number', 'DOC')}.{ext}")
    module = FORMAT_MODULES[fmt]
    return module.export_document(doc, filepath)
