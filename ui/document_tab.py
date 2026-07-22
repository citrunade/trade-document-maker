"""
制单界面：选择客户 -> 添加产品明细 -> 填写运输/条款信息 -> 实时联动计算
生成的单据主记录同时驱动 PI / CI / PL 三份单据的导出（见 ui/export_tab.py，阶段三实现）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDoubleSpinBox, QDialog, QDialogButtonBox, QMessageBox, QGroupBox,
    QDateEdit, QAbstractItemView, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import QDate

from core import storage, calc, pdf_export
from core.models import make_document, make_doc_line
from core.paths import get_exports_dir
from ui.ai_import_helper import (
    show_privacy_notice_once, pick_import_file, run_ai_extraction, ImportReviewDialog,
)
import os

INCOTERMS = ["FOB", "CIF", "CFR", "EXW", "DAP", "DDP", "FCA", "CPT", "CIP"]
CURRENCIES = ["USD", "EUR", "RMB"]

def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


LINE_COLUMNS = [
    "型号", "中文品名", "英文品名", "数量", "单价", "小计",
    "净重合计(kg)", "毛重合计(kg)", "体积合计(CBM)", "操作",
]


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
        self._recalculate()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        header_box = QGroupBox("客户与单据信息")
        form = QFormLayout(header_box)

        self.customer_combo = QComboBox()
        self.customer_combo.currentIndexChanged.connect(self._on_customer_changed)
        form.addRow("客户：", self.customer_combo)

        num_row = QHBoxLayout()
        self.pi_number = QLineEdit()
        self.ci_number = QLineEdit()
        self.pl_number = QLineEdit()
        gen_btn = QPushButton("自动生成三份单据编号")
        gen_btn.clicked.connect(self._generate_numbers)
        num_row.addWidget(QLabel("PI#")); num_row.addWidget(self.pi_number)
        num_row.addWidget(QLabel("CI#")); num_row.addWidget(self.ci_number)
        num_row.addWidget(QLabel("PL#")); num_row.addWidget(self.pl_number)
        num_row.addWidget(gen_btn)
        form.addRow("单据编号：", num_row)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("日期：", self.date_edit)

        terms_row = QHBoxLayout()
        self.pol = QLineEdit(storage.load_company().get("default_pol", ""))
        self.pod = QLineEdit()
        self.incoterm = QComboBox()
        self.incoterm.addItems(INCOTERMS)
        self.incoterm.setCurrentText(storage.load_company().get("default_incoterm", "FOB"))
        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.currency.currentTextChanged.connect(self._recalculate)
        terms_row.addWidget(QLabel("POL：")); terms_row.addWidget(self.pol)
        terms_row.addWidget(QLabel("POD：")); terms_row.addWidget(self.pod)
        terms_row.addWidget(QLabel("Incoterm：")); terms_row.addWidget(self.incoterm)
        terms_row.addWidget(QLabel("币种：")); terms_row.addWidget(self.currency)
        form.addRow("运输条款：", terms_row)

        self.payment_terms = QLineEdit("30% T/T in advance, 70% T/T before shipment")
        form.addRow("付款方式：", self.payment_terms)
        self.validity = QLineEdit("30 days")
        form.addRow("报价有效期：", self.validity)
        self.remark = QLineEdit()
        form.addRow("备注：", self.remark)

        layout.addWidget(header_box)

        # ---- 产品明细 ----
        lines_box = QGroupBox("产品明细")
        lines_layout = QVBoxLayout(lines_box)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加产品")
        add_btn.clicked.connect(self._add_line)
        ai_btn = QPushButton("AI 导入产品明细（PO/PDF/图片/Excel）")
        ai_btn.clicked.connect(self._ai_import_lines)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(ai_btn)
        btn_row.addStretch()
        lines_layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(LINE_COLUMNS))
        self.table.setHorizontalHeaderLabels(LINE_COLUMNS)
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
        export_btn = QPushButton("导出 PI / CI / PL PDF")
        export_btn.clicked.connect(self._export_pdfs)
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
        self.customer_combo.addItem("-- 请选择客户 --", None)
        for c in self.customers:
            label = c.get("name_cn") or c.get("name_en") or "未命名客户"
            self.customer_combo.addItem(label, c)
        self.customer_combo.blockSignals(False)

    def _on_customer_changed(self):
        customer = self.customer_combo.currentData()
        if customer:
            self.document["customer_id"] = customer.get("id", "")
            self.document["customer_snapshot"] = customer
            self.pod.setText(customer.get("pod", ""))

    def _generate_numbers(self):
        self.pi_number.setText(storage.generate_doc_number("PI"))
        self.ci_number.setText(storage.generate_doc_number("CI"))
        self.pl_number.setText(storage.generate_doc_number("PL"))

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
            self.document["lines"].append(row)
        self._recalculate()
        QMessageBox.information(
            self, "提示",
            f"已导入 {len(confirmed)} 条产品明细，重量/尺寸信息未包含在采购订单中，"
            "如需精确计算净重/毛重/体积，请在物料库中维护对应产品后手动补充。",
        )

    def _remove_line(self, index: int):
        if 0 <= index < len(self.document["lines"]):
            del self.document["lines"][index]
            self._recalculate()

    def _on_qty_or_price_changed(self):
        for row in range(self.table.rowCount()):
            qty_spin = self.table.cellWidget(row, 3)
            price_spin = self.table.cellWidget(row, 4)
            if qty_spin is None or price_spin is None:
                continue
            self.document["lines"][row]["quantity"] = qty_spin.value()
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
            f"总金额：{currency} {totals['total_amount']:,.2f}    "
            f"总净重：{totals['total_net_weight']} kg    "
            f"总毛重：{totals['total_gross_weight']} kg    "
            f"总体积：{totals['total_cbm']} CBM"
        )
        self.totals_label.setText(summary)
        self.words_label.setText(calc.amount_in_words(totals["total_amount"], currency))

    def _rebuild_table(self, computed_lines: list):
        self.table.setRowCount(len(computed_lines))
        for row, line in enumerate(computed_lines):
            self.table.setItem(row, 0, QTableWidgetItem(line.get("model_no", "")))
            self.table.setItem(row, 1, QTableWidgetItem(line.get("name_cn", "")))
            self.table.setItem(row, 2, QTableWidgetItem(line.get("name_en", "")))

            qty_spin = QDoubleSpinBox()
            qty_spin.setMaximum(1_000_000)
            qty_spin.setDecimals(2)
            qty_spin.setValue(line.get("quantity", 0.0))
            qty_spin.valueChanged.connect(self._on_qty_or_price_changed)
            self.table.setCellWidget(row, 3, qty_spin)

            price_spin = QDoubleSpinBox()
            price_spin.setMaximum(10_000_000)
            price_spin.setDecimals(2)
            price_spin.setValue(line.get("unit_price", 0.0))
            price_spin.valueChanged.connect(self._on_qty_or_price_changed)
            self.table.setCellWidget(row, 4, price_spin)

            self.table.setItem(row, 5, QTableWidgetItem(f"{line['subtotal']:.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"{line['total_net_weight']:.2f}"))
            self.table.setItem(row, 7, QTableWidgetItem(f"{line['total_gross_weight']:.2f}"))
            self.table.setItem(row, 8, QTableWidgetItem(f"{line['total_cbm']:.3f}"))

            del_btn = QPushButton("删除")
            del_btn.clicked.connect(lambda _, r=row: self._remove_line(r))
            self.table.setCellWidget(row, 9, del_btn)

    def _update_computed_cells(self, computed_lines: list):
        for row, line in enumerate(computed_lines):
            self.table.setItem(row, 5, QTableWidgetItem(f"{line['subtotal']:.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"{line['total_net_weight']:.2f}"))
            self.table.setItem(row, 7, QTableWidgetItem(f"{line['total_gross_weight']:.2f}"))
            self.table.setItem(row, 8, QTableWidgetItem(f"{line['total_cbm']:.3f}"))

    # ---------------- persistence ----------------
    def _collect_document(self) -> dict:
        self.document.update({
            "pi_number": self.pi_number.text().strip(),
            "ci_number": self.ci_number.text().strip(),
            "pl_number": self.pl_number.text().strip(),
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "currency": self.currency.currentText(),
            "incoterm": self.incoterm.currentText(),
            "pol": self.pol.text().strip(),
            "pod": self.pod.text().strip(),
            "payment_terms": self.payment_terms.text().strip(),
            "validity": self.validity.text().strip(),
            "remark": self.remark.text().strip(),
        })
        return self.document

    def _new_document(self):
        reply = QMessageBox.question(self, "新建单据", "当前未保存的单据数据将被清空，确定新建吗？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.document = make_document()
        self.pi_number.clear(); self.ci_number.clear(); self.pl_number.clear()
        self.pod.clear(); self.remark.clear()
        self.customer_combo.setCurrentIndex(0)
        self._recalculate()

    def _save_document(self):
        doc = self._collect_document()
        if not doc.get("customer_id"):
            QMessageBox.warning(self, "提示", "请先选择客户")
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

    def _export_pdfs(self):
        doc = self._collect_document()
        if not doc.get("customer_id"):
            QMessageBox.warning(self, "提示", "请先选择客户")
            return
        if not doc.get("lines"):
            QMessageBox.warning(self, "提示", "请至少添加一条产品明细")
            return
        if not (doc.get("pi_number") and doc.get("ci_number") and doc.get("pl_number")):
            self._generate_numbers()
            doc = self._collect_document()

        company = storage.load_company()
        export_dir = get_exports_dir()
        try:
            pi_path = pdf_export.export_pi(doc, os.path.join(export_dir, f"{doc['pi_number']}.pdf"), company)
            ci_path = pdf_export.export_ci(doc, os.path.join(export_dir, f"{doc['ci_number']}.pdf"), company)
            pl_path = pdf_export.export_pl(doc, os.path.join(export_dir, f"{doc['pl_number']}.pdf"), company)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"PDF 生成过程中发生错误：{e}")
            return

        QMessageBox.information(
            self, "导出成功",
            f"三份单据已导出至：\n{export_dir}\n\n{os.path.basename(pi_path)}\n"
            f"{os.path.basename(ci_path)}\n{os.path.basename(pl_path)}",
        )

    def get_current_document(self) -> dict:
        """供导出模块调用，获取当前联动计算后的完整单据数据"""
        return self._collect_document()

    def load_document(self, doc: dict):
        """从历史记录中加载一份单据到编辑界面（供"一键复制新建"使用）"""
        self.document = doc
        self._refresh_customer_combo()
        idx = next(
            (i for i in range(self.customer_combo.count())
             if self.customer_combo.itemData(i) and self.customer_combo.itemData(i).get("id") == doc.get("customer_id")),
            0,
        )
        self.customer_combo.setCurrentIndex(idx)
        self.pi_number.setText(doc.get("pi_number", ""))
        self.ci_number.setText(doc.get("ci_number", ""))
        self.pl_number.setText(doc.get("pl_number", ""))
        self.pol.setText(doc.get("pol", ""))
        self.pod.setText(doc.get("pod", ""))
        self.incoterm.setCurrentText(doc.get("incoterm", "FOB"))
        self.currency.setCurrentText(doc.get("currency", "USD"))
        self.payment_terms.setText(doc.get("payment_terms", ""))
        self.validity.setText(doc.get("validity", ""))
        self.remark.setText(doc.get("remark", ""))
        self._recalculate()
