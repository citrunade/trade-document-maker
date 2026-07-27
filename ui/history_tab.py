"""
单据历史管理界面：按编号/客户搜索历史单据，支持一键复制新建、重新导出（PDF/Word/Excel）、删除
"""
import copy

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)

from core import storage
from core.document_export import export_document_in_format
from core.paths import get_exports_dir
from ui.toast import notify

COLUMNS = [
    ("doc_type", "类型"),
    ("doc_number", "单据编号"),
    ("date", "日期"),
    ("_customer_name", "收件方"),
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
        self.search_box.setPlaceholderText("按单据编号或收件方名称搜索…")
        self.search_box.setMinimumWidth(240)
        self.search_box.textChanged.connect(self._refresh_table)
        top.addWidget(QLabel("搜索："))
        top.addWidget(self.search_box, 1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_selected)
        top.addWidget(refresh_btn)
        top.addWidget(del_btn)
        layout.addLayout(top)

        # 复制新建/导出相关按钮单独一行，避免与搜索框挤在一起导致文字被裁剪
        action_row = QHBoxLayout()
        dup_btn = QPushButton("复制新建")
        dup_btn.clicked.connect(self._duplicate_selected)
        self.export_format = QComboBox()
        self.export_format.addItems(["PDF", "Word", "Excel"])
        export_btn = QPushButton("重新导出")
        export_btn.clicked.connect(self._reexport_selected)
        action_row.addWidget(dup_btn)
        action_row.addWidget(QLabel("格式："))
        action_row.addWidget(self.export_format)
        action_row.addWidget(export_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
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
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, doc in enumerate(rows):
            display = self._row_display(doc)
            for col_idx, (key, _) in enumerate(COLUMNS):
                item = QTableWidgetItem(str(display.get(key, "")))
                if col_idx == 0:
                    # 类型列携带完整记录引用，使复制/导出/删除不受列排序影响
                    item.setData(Qt.ItemDataRole.UserRole, doc)
                self.table.setItem(r, col_idx, item)
        self.table.setSortingEnabled(True)

    def _selected_document(self) -> dict:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

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
        new_doc["doc_number"] = ""
        self.on_duplicate_to_document(new_doc)
        notify(self, "✓ 已复制到「制单」页面，请生成新的单据编号后保存")

    def _reexport_selected(self):
        doc = self._selected_document()
        if not doc:
            QMessageBox.information(self, "提示", "请先选择一条历史单据")
            return
        export_dir = get_exports_dir()
        try:
            path = export_document_in_format(doc, self.export_format.currentText(), export_dir)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"文件生成过程中发生错误：{e}")
            return
        notify(self, f"✓ 已导出至 {path}")

    def _delete_selected(self):
        doc = self._selected_document()
        if not doc:
            QMessageBox.information(self, "提示", "请先选择一条历史单据")
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除单据「{doc.get('doc_number', '')}」的历史记录吗？"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.documents.remove(doc)
            storage.save_documents(self.documents)
            self._refresh_table()

    def reload(self):
        self.documents = storage.load_documents()
        self._refresh_table()
