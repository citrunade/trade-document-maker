"""
制单界面：选择单据类型(PI/CI/PL) -> 选择客户(收件方) -> 选择四类模板预设(Own/收货地址/条款/银行信息)
-> 添加产品明细 -> 实时联动计算 -> 生成/导出单据。
一次只生成一份单据（标题按类型不同，格式统一），不再同时生成三份。
"""
import os

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDoubleSpinBox, QDialog, QDialogButtonBox, QMessageBox, QGroupBox,
    QDateEdit, QAbstractItemView, QListWidget, QListWidgetItem,
)

from core import storage, calc, pdf_export
from core.models import make_document, make_doc_line
from core.paths import get_exports_dir
from ui.ai_import_helper import (
    show_privacy_notice_once, pick_import_file, run_ai_extraction, ImportReviewDialog,
)

CURRENCIES = ["USD", "EUR", "RMB", "SGD"]
DOC_TITLES = {"PI": "PROFORMA INVOICE 形式发票", "CI": "COMMERCIAL INVOICE 商业发票", "PL": "PACKING LIST 装箱单"}

# 财务类单据（PI/CI）显示单价与金额；PL 不显示价格信息
FINANCIAL_LINE_COLUMNS = [
    "Item", "Description 品名", "Qty 数量", "Unit 单位", "Unit Price 单价", "Total Price 金额",
    "COO", "Net Weight 净重(kg)", "Total N.W.(kg)", "HS Code", "Remark", "操作",
]
PL_LINE_COLUMNS = [
    "Item", "Description 品名", "Qty 数量", "Unit 单位",
    "COO", "Net Weight 净重(kg)", "Total N.W.(kg)", "HS Code", "Remark", "操作",
]


def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


class ProductPickerDialog(QDialog):
    """从物料库中模糊搜索并选择产品，用于添加到单据明细"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择产品")
        self.setMinimumSize(500, 400)
        self.products = storage.load_products()
        self.selected_product = None

        layout = QVBoxLayout(self)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("按型号/品名/HS编码搜索…")
        self.search_box.textChanged.connect(self._refresh_list)
        layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_list()

    def _refresh_list(self):
        term = self.search_box.text().strip().lower()
        self.list_widget.clear()
        for p in self.products:
            haystack = f"{p.get('model_no','')} {p.get('name_cn','')} {p.get('name_en','')} {p.get('hs_code','')}".lower()
            if term and term not in haystack:
                continue
            text = f"{p.get('model_no','')} | {p.get('name_cn','')} / {p.get('name_en','')} | {p.get('unit_price',0):.2f} {p.get('currency','USD')}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def accept(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择一个产品")
            return
        self.selected_product = item.data(Qt.ItemDataRole.UserRole)
        super().accept()


class DocumentTab(QWidget):
    def __init__(self):
        super().__init__()
        self.customers = storage.load_customers()
        self.document = make_document()
        self._build_ui()
        self._refresh_customer_combo()
        self._refresh_template_combos()
        self._generate_number()
        self._set_default_dates()
        self._recalculate()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        header_box = QGroupBox("单据基本信息")
        form = QFormLayout(header_box)

        type_row = QHBoxLayout()
        self.doc_type = QComboBox()
        self.doc_type.addItems(["PI", "CI", "PL"])
        self.doc_type.currentTextChanged.connect(self._on_doc_type_changed)
        self.doc_number = QLineEdit()
        gen_btn = QPushButton("生成新编号")
        gen_btn.clicked.connect(self._generate_number)
        type_row.addWidget(QLabel("单据类型："))
        type_row.addWidget(self.doc_type)
        type_row.addWidget(QLabel("单据编号："))
        type_row.addWidget(self.doc_number)
        type_row.addWidget(gen_btn)
        form.addRow(type_row)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("单据日期：", self.date_edit)

        self.customer_combo = QComboBox()
        self.customer_combo.currentIndexChanged.connect(self._on_customer_changed)
        form.addRow("收件方 (Buyer/Seller)：", self.customer_combo)

        po_row = QHBoxLayout()
        self.destination = QLineEdit()
        po_row.addWidget(QLabel("Destination：")); po_row.addWidget(self.destination)
        form.addRow(po_row)

        validity_row = QHBoxLayout()
        self.validity_start = QDateEdit(QDate.currentDate())
        self.validity_start.setCalendarPopup(True)
        self.validity_start.setDisplayFormat("yyyy-MM-dd")
        self.validity_end = QDateEdit(QDate.currentDate().addDays(30))
        self.validity_end.setCalendarPopup(True)
        self.validity_end.setDisplayFormat("yyyy-MM-dd")
        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.currency.currentTextChanged.connect(self._recalculate)
        validity_row.addWidget(QLabel("Validity Start：")); validity_row.addWidget(self.validity_start)
        validity_row.addWidget(QLabel("Validity End：")); validity_row.addWidget(self.validity_end)
        validity_row.addWidget(QLabel("币种：")); validity_row.addWidget(self.currency)
        form.addRow(validity_row)

        # ---- 四类模板预设选择 ----
        template_row = QHBoxLayout()
        self.own_combo = QComboBox()
        self.delivery_combo = QComboBox()
        self.conditions_combo = QComboBox()
        self.banking_combo = QComboBox()
        template_row.addWidget(QLabel("Own：")); template_row.addWidget(self.own_combo)
        template_row.addWidget(QLabel("Delivery：")); template_row.addWidget(self.delivery_combo)
        template_row.addWidget(QLabel("Conditions：")); template_row.addWidget(self.conditions_combo)
        template_row.addWidget(QLabel("Banking：")); template_row.addWidget(self.banking_combo)
        form.addRow("适用模板：", template_row)
        manage_hint = QLabel("模板预设可在「模板管理」页签中新增/编辑")
        manage_hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow("", manage_hint)

        self.remark = QLineEdit()
        form.addRow("备注：", self.remark)

        layout.addWidget(header_box)

        # ---- 产品明细 ----
        lines_box = QGroupBox("产品明细")
        lines_layout = QVBoxLayout(lines_box)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加产品")
        add_btn.clicked.connect(self._add_line)
        ai_btn = QPushButton("AI 导入产品明细（PO/PDF/图片/Excel/Word）")
        ai_btn.clicked.connect(self._ai_import_lines)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(ai_btn)
        btn_row.addStretch()
        lines_layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(FINANCIAL_LINE_COLUMNS))
        self.table.setHorizontalHeaderLabels(FINANCIAL_LINE_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lines_layout.addWidget(self.table)
        layout.addWidget(lines_box)

        # ---- 汇总 ----
        totals_box = QGroupBox("汇总")
        totals_layout = QVBoxLayout(totals_box)
        self.totals_label = QLabel()
        self.totals_label.setStyleSheet("font-weight: bold;")
        self.words_label = QLabel()
        self.words_label.setWordWrap(True)
        totals_layout.addWidget(self.totals_label)
        totals_layout.addWidget(self.words_label)
        layout.addWidget(totals_box)

        # ---- 操作 ----
        action_row = QHBoxLayout()
        new_btn = QPushButton("新建单据")
        new_btn.clicked.connect(self._new_document)
        save_btn = QPushButton("保存到历史")
        save_btn.clicked.connect(self._save_document)
        export_btn = QPushButton("导出 PDF")
        export_btn.clicked.connect(self._export_pdf)
        action_row.addWidget(new_btn)
        action_row.addWidget(save_btn)
        action_row.addWidget(export_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

    # ---------------- data population ----------------
    def _refresh_customer_combo(self):
        self.customers = storage.load_customers()
        self.customer_combo.blockSignals(True)
        self.customer_combo.clear()
        self.customer_combo.addItem("-- 请选择收件方 --", None)
        for c in self.customers:
            label = c.get("name_cn") or c.get("name_en") or "未命名客户"
            self.customer_combo.addItem(label, c)
        self.customer_combo.blockSignals(False)

    def _refresh_template_combos(self):
        templates = storage.load_templates()
        for category, combo in (
            ("own", self.own_combo), ("delivery", self.delivery_combo),
            ("conditions", self.conditions_combo), ("banking", self.banking_combo),
        ):
            current_id = combo.currentData().get("id") if combo.currentData() else None
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("-- 无 --", None)
            restore_idx = 0
            for i, t in enumerate(templates.get(category, []), start=1):
                combo.addItem(t.get("name") or "(未命名预设)", t)
                if current_id and t.get("id") == current_id:
                    restore_idx = i
            combo.setCurrentIndex(restore_idx)
            combo.blockSignals(False)

    def _on_customer_changed(self):
        customer = self.customer_combo.currentData()
        if customer:
            self.document["customer_id"] = customer.get("customer_id", "")
            self.document["customer_snapshot"] = customer
            dest = ", ".join(filter(None, [customer.get("city", ""), customer.get("country_region", "")]))
            self.destination.setText(dest)

    def _on_doc_type_changed(self):
        self._rebuild_table(calc.compute_totals(self.document["lines"])["lines"])

    def _generate_number(self):
        self.doc_number.setText(storage.generate_invoice_number())

    def _set_default_dates(self):
        start, end = storage.compute_validity_dates(30)
        y, m, d = map(int, start.split("-"))
        self.validity_start.setDate(QDate(y, m, d))
        y, m, d = map(int, end.split("-"))
        self.validity_end.setDate(QDate(y, m, d))

    # ---------------- lines management ----------------
    def _add_line(self):
        dialog = ProductPickerDialog(self)
        if dialog.exec() and dialog.selected_product:
            line = make_doc_line(dialog.selected_product, quantity=1)
            self.document["lines"].append(line)
            self._recalculate()

    def _ai_import_lines(self):
        if not show_privacy_notice_once(self):
            return
        path = pick_import_file(self)
        if not path:
            return
        from core.ai_import import import_document_lines
        extracted = run_ai_extraction(self, import_document_lines, path)
        if extracted is None:
            return
        if not extracted:
            QMessageBox.information(self, "提示", "未能从该文件中识别出任何产品明细")
            return

        review_columns = [
            ("model_no", "型号"), ("name_cn", "中文品名"), ("name_en", "英文品名"),
            ("hs_code", "HS编码"), ("unit", "单位"), ("quantity", "数量"), ("unit_price", "单价"),
        ]
        dialog = ImportReviewDialog(self, "审核 AI 识别的产品明细", review_columns, extracted)
        if not dialog.exec():
            return
        confirmed = dialog.get_confirmed_rows()
        for row in confirmed:
            row["quantity"] = _safe_float(row.get("quantity"))
            row["unit_price"] = _safe_float(row.get("unit_price"))
            row.setdefault("coo", "")
            row.setdefault("remark", "")
            self.document["lines"].append(row)
        self._recalculate()
        QMessageBox.information(
            self, "提示",
            f"已导入 {len(confirmed)} 条产品明细，重量/COO 等信息未包含在采购订单中，"
            "如需精确计算，请在物料库中维护对应产品或在明细表中手动补充。",
        )

    def _remove_line(self, index: int):
        if 0 <= index < len(self.document["lines"]):
            del self.document["lines"][index]
            self._recalculate()

    def _is_financial(self) -> bool:
        return self.doc_type.currentText() != "PL"

    def _on_qty_or_price_changed(self):
        financial = self._is_financial()
        qty_col = 2
        price_col = 4 if financial else None
        for row in range(self.table.rowCount()):
            qty_spin = self.table.cellWidget(row, qty_col)
            if qty_spin is not None:
                self.document["lines"][row]["quantity"] = qty_spin.value()
            if price_col is not None:
                price_spin = self.table.cellWidget(row, price_col)
                if price_spin is not None:
                    self.document["lines"][row]["unit_price"] = price_spin.value()
        self._recalculate(rebuild_table=False)

    def _recalculate(self, rebuild_table: bool = True):
        totals = calc.compute_totals(self.document["lines"])
        currency = self.currency.currentText()

        if rebuild_table:
            self._rebuild_table(totals["lines"])
        else:
            self._update_computed_cells(totals["lines"])

        summary = (
            f"总数量：{totals['total_quantity']}    "
            f"总净重：{totals['total_net_weight']} kg    "
        )
        if self._is_financial():
            summary += f"总金额：{currency} {totals['total_amount']:,.2f}    "
        self.totals_label.setText(summary)
        if self._is_financial():
            self.words_label.setText(calc.amount_in_words(totals["total_amount"], currency))
        else:
            self.words_label.setText("")

    def _rebuild_table(self, computed_lines: list):
        financial = self._is_financial()
        columns = FINANCIAL_LINE_COLUMNS if financial else PL_LINE_COLUMNS
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(computed_lines))

        for row, line in enumerate(computed_lines):
            col = 0
            self.table.setItem(row, col, QTableWidgetItem(str(row + 1))); col += 1

            desc = line.get("name_en", "")
            if line.get("name_cn"):
                desc += f"\n{line.get('name_cn')}"
            desc_item = QTableWidgetItem(desc)
            self.table.setItem(row, col, desc_item); col += 1

            qty_spin = QDoubleSpinBox()
            qty_spin.setMaximum(1_000_000)
            qty_spin.setDecimals(2)
            qty_spin.setValue(line.get("quantity", 0.0))
            qty_spin.valueChanged.connect(self._on_qty_or_price_changed)
            self.table.setCellWidget(row, col, qty_spin); col += 1

            self.table.setItem(row, col, QTableWidgetItem(line.get("unit", ""))); col += 1

            if financial:
                price_spin = QDoubleSpinBox()
                price_spin.setMaximum(10_000_000)
                price_spin.setDecimals(2)
                price_spin.setValue(line.get("unit_price", 0.0))
                price_spin.valueChanged.connect(self._on_qty_or_price_changed)
                self.table.setCellWidget(row, col, price_spin); col += 1

                self.table.setItem(row, col, QTableWidgetItem(f"{line['subtotal']:.2f}")); col += 1

            self.table.setItem(row, col, QTableWidgetItem(line.get("coo", ""))); col += 1
            self.table.setItem(row, col, QTableWidgetItem(f"{line.get('net_weight', 0):.2f}")); col += 1
            self.table.setItem(row, col, QTableWidgetItem(f"{line['total_net_weight']:.2f}")); col += 1
            self.table.setItem(row, col, QTableWidgetItem(line.get("hs_code", ""))); col += 1
            self.table.setItem(row, col, QTableWidgetItem(line.get("remark", ""))); col += 1

            del_btn = QPushButton("删除")
            del_btn.clicked.connect(lambda _, r=row: self._remove_line(r))
            self.table.setCellWidget(row, col, del_btn)

    def _update_computed_cells(self, computed_lines: list):
        financial = self._is_financial()
        for row, line in enumerate(computed_lines):
            nw_col = 7 if financial else 5
            tnw_col = nw_col + 1
            self.table.setItem(row, nw_col, QTableWidgetItem(f"{line.get('net_weight', 0):.2f}"))
            self.table.setItem(row, tnw_col, QTableWidgetItem(f"{line['total_net_weight']:.2f}"))
            if financial:
                self.table.setItem(row, 5, QTableWidgetItem(f"{line['subtotal']:.2f}"))

    # ---------------- persistence ----------------
    def _selected_template_snapshot(self, combo: QComboBox) -> dict:
        template = combo.currentData()
        return dict(template.get("fields", {})) if template else {}

    def _collect_document(self) -> dict:
        self.document.update({
            "doc_type": self.doc_type.currentText(),
            "doc_number": self.doc_number.text().strip(),
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "currency": self.currency.currentText(),
            "destination": self.destination.text().strip(),
            "own_snapshot": self._selected_template_snapshot(self.own_combo),
            "delivery_snapshot": self._selected_template_snapshot(self.delivery_combo),
            "conditions_snapshot": self._selected_template_snapshot(self.conditions_combo),
            "banking_snapshot": self._selected_template_snapshot(self.banking_combo),
            "validity_start": self.validity_start.date().toString("yyyy-MM-dd"),
            "validity_end": self.validity_end.date().toString("yyyy-MM-dd"),
            "remark": self.remark.text().strip(),
        })
        return self.document

    def _new_document(self):
        reply = QMessageBox.question(self, "新建单据", "当前未保存的单据数据将被清空，确定新建吗？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.document = make_document()
        self._generate_number()
        self._set_default_dates()
        self.destination.clear(); self.remark.clear()
        self.customer_combo.setCurrentIndex(0)
        self._recalculate()

    def _save_document(self):
        doc = self._collect_document()
        if not doc.get("customer_id"):
            QMessageBox.warning(self, "提示", "请先选择收件方")
            return
        if not doc.get("lines"):
            QMessageBox.warning(self, "提示", "请至少添加一条产品明细")
            return
        documents = storage.load_documents()
        existing_idx = next((i for i, d in enumerate(documents) if d["id"] == doc["id"]), None)
        if existing_idx is not None:
            documents[existing_idx] = doc
        else:
            documents.append(doc)
        storage.save_documents(documents)
        QMessageBox.information(self, "提示", "单据已保存到历史记录")

    def _export_pdf(self):
        doc = self._collect_document()
        if not doc.get("customer_id"):
            QMessageBox.warning(self, "提示", "请先选择收件方")
            return
        if not doc.get("lines"):
            QMessageBox.warning(self, "提示", "请至少添加一条产品明细")
            return
        if not doc.get("doc_number"):
            self._generate_number()
            doc = self._collect_document()

        company = storage.load_company()
        export_dir = get_exports_dir()
        try:
            path = pdf_export.export_document(doc, os.path.join(export_dir, f"{doc['doc_number']}.pdf"), company)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"PDF 生成过程中发生错误：{e}")
            return

        QMessageBox.information(self, "导出成功", f"单据已导出至：\n{path}")

    def get_current_document(self) -> dict:
        """供导出模块调用，获取当前联动计算后的完整单据数据"""
        return self._collect_document()

    def load_document(self, doc: dict):
        """从历史记录中加载一份单据到编辑界面（供"一键复制新建"使用）"""
        self.document = doc
        self._refresh_customer_combo()
        self._refresh_template_combos()
        self.doc_type.setCurrentText(doc.get("doc_type", "PI"))
        idx = next(
            (i for i in range(self.customer_combo.count())
             if self.customer_combo.itemData(i) and self.customer_combo.itemData(i).get("customer_id") == doc.get("customer_id")),
            0,
        )
        self.customer_combo.setCurrentIndex(idx)
        self.doc_number.setText(doc.get("doc_number", ""))
        self.destination.setText(doc.get("destination", ""))
        self.currency.setCurrentText(doc.get("currency", "USD"))
        self.remark.setText(doc.get("remark", ""))
        self._recalculate()
