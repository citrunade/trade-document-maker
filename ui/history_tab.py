"""
单据历史管理界面：按编号/客户搜索历史单据，支持一键复制新建、重新导出 PDF、删除
"""
import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)

from core import storage, pdf_export
from core.paths import get_exports_dir

COLUMNS = [
    ("pi_number", "PI 编号"),
    ("ci_number", "CI 编号"),
    ("pl_number", "PL 编号"),
    ("date", "日期"),
    ("_customer_name", "客户"),
    ("currency", "币种"),
]


class HistoryTab(QWidget):
    def __init__(self, on_duplicate_to_document=None):
        """
        on_duplicate_to_document: 回调函数，接收一份单据 dict，
        用于将历史单据加载回"制单"页面进行"一键复制新建"。
        """
        super().__init__()
        self.on_duplicate_to_document = on_duplicate_to_document
        self.documents = storage.load_documents()
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("按 PI/CI/PL 编号或客户名称搜索…")
        self.search_box.textChanged.connect(self._refresh_table)
        top.addWidget(QLabel("搜索："))
        top.addWidget(self.search_box)
        top.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload)
        dup_btn = QPushButton("复制新建")
        dup_btn.clicked.connect(self._duplicate_selected)
        export_btn = QPushButton("重新导出 PDF")
        export_btn.clicked.connect(self._reexport_selected)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_selected)
        top.addWidget(refresh_btn)
        top.addWidget(dup_btn)
        top.addWidget(export_btn)
        top.addWidget(del_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

    def _row_display(self, doc: dict) -> dict:
        customer = doc.get("customer_snapshot", {})
        display = dict(doc)
        display["_customer_name"] = customer.get("name_cn") or customer.get("name_en") or ""
        return display

    def _filtered(self) -> list:
        term = self.search_box.text().strip().lower()
        if not term:
            return self.documents
        result = []
        for d in self.documents:
            display = self._row_display(d)
            haystack = " ".join(str(display.get(k, "")) for k, _ in COLUMNS).lower()
            if term in haystack:
                result.append(d)
        return result

    def _refresh_table(self):
        rows = self._filtered()
        self.table.setRowCount(len(rows))
        for r, doc in enumerate(rows):
            display = self._row_display(doc)
            for col_idx, (key, _) in enumerate(COLUMNS):
                self.table.setItem(r, col_idx, QTableWidgetItem(str(display.get(key, ""))))

    def _selected_document(self) -> dict:
        row = self.table.currentRow()
        if row < 0:
            return None
        rows = self._filtered()
        if row >= len(rows):
            return None
        return rows[row]

    def _duplicate_selected(self):
        doc = self._selected_document()
        if not doc:
            QMessageBox.information(self, "提示", "请先选择一条历史单据")
            return
        if not self.on_duplicate_to_document:
            return
        new_doc = copy.deepcopy(doc)
        from core.models import new_id
        new_doc["id"] = new_id()
        new_doc["pi_number"] = ""
        new_doc["ci_number"] = ""
        new_doc["pl_number"] = ""
        self.on_duplicate_to_document(new_doc)
        QMessageBox.information(self, "提示", "已复制到「制单」页面，请生成新的单据编号后保存")

    def _reexport_selected(self):
        doc = self._selected_document()
        if not doc:
            QMessageBox.information(self, "提示", "请先选择一条历史单据")
            return
        company = storage.load_company()
        export_dir = get_exports_dir()
        try:
            pi = pdf_export.export_pi(doc, os.path.join(export_dir, f"{doc.get('pi_number', 'PI')}.pdf"), company)
            ci = pdf_export.export_ci(doc, os.path.join(export_dir, f"{doc.get('ci_number', 'CI')}.pdf"), company)
            pl = pdf_export.export_pl(doc, os.path.join(export_dir, f"{doc.get('pl_number', 'PL')}.pdf"), company)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"PDF 生成过程中发生错误：{e}")
            return
        QMessageBox.information(
            self, "导出成功",
            f"三份单据已导出至：\n{export_dir}\n\n"
            f"{os.path.basename(pi)}\n{os.path.basename(ci)}\n{os.path.basename(pl)}",
        )

    def _delete_selected(self):
        doc = self._selected_document()
        if not doc:
            QMessageBox.information(self, "提示", "请先选择一条历史单据")
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除单据「{doc.get('pi_number', '')}」的历史记录吗？"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.documents.remove(doc)
            storage.save_documents(self.documents)
            self._refresh_table()

    def reload(self):
        self.documents = storage.load_documents()
        self._refresh_table()
