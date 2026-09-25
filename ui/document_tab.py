"""
制单界面：选择单据类型(PI/CI/PL) -> 选择客户(收件方) -> 选择四类模板预设(Own/收货地址/条款/银行信息)
-> 添加产品明细 -> 实时联动计算 -> 生成/导出单据。
一次只生成一份单据（标题按类型不同，格式统一），不再同时生成三份。
支持导出为 PDF / Word / Excel 三种格式（core.document_export 统一分发）。
"""
import copy
import os

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QDoubleSpinBox, QSpinBox, QDialog, QDialogButtonBox, QMessageBox, QGroupBox,
    QDateEdit, QAbstractItemView, QListWidget, QListWidgetItem, QScrollArea,
)

from core import storage, calc
from core.document_export import export_document_in_format, FORMAT_EXTENSIONS
from core.models import make_document, make_doc_line
from core.paths import get_exports_dir
from ui.toast import notify, show_export_done
from ui.style import disable_accidental_scroll_edits
from ui.ai_import_helper import (
    show_privacy_notice_once, pick_import_file, run_ai_extraction, ImportReviewDialog,
)

CURRENCIES = ["USD", "EUR", "RMB", "SGD"]
CUSTOM_DEPOSIT = "custom"
DOC_TITLES = {"PI": "PROFORMA INVOICE 形式发票", "CI": "COMMERCIAL INVOICE 商业发票", "PL": "PACKING LIST 装箱单"}

# 明细表列定义（key, 表头）。财务类单据（PI/CI）显示单价与金额；
# 装箱单（PL）不显示价格，改为显示毛重，便于报关/订舱。
FINANCIAL_LINE_COLUMNS = [
    ("no", "No."), ("model_no", "Model"), ("desc", "Description"), ("quantity", "Qty"), ("unit", "Unit"),
    ("unit_price", "Unit Price"), ("subtotal", "Total Price"), ("coo", "COO"),
    ("net_weight", "Net Weight"), ("total_net_weight", "Total N.W."),
    ("hs_code", "HS Code"), ("remark", "Remark"), ("op", "操作"),
]
PL_LINE_COLUMNS = [
    ("no", "No."), ("model_no", "Model"), ("desc", "Description"), ("quantity", "Qty"), ("unit", "Unit"),
    ("coo", "COO"), ("net_weight", "Net Weight"), ("total_net_weight", "Total N.W."),
    ("gross_weight", "Gross Weight"), ("total_gross_weight", "Total G.W."),
    ("hs_code", "HS Code"), ("remark", "Remark"), ("op", "操作"),
]
WEIGHT_KEYS = {"net_weight", "gross_weight"}
TEXT_KEYS = {"model_no", "unit", "coo", "hs_code", "remark"}
COMPUTED_KEYS = {"no", "subtotal", "total_net_weight", "total_gross_weight"}


class _TrimmedSpinBox(QDoubleSpinBox):
    """数字框不显示多余的 0：4.000 显示为 4，167.4000 显示为 167.40（单价至少保留 2 位小数）。"""

    def __init__(self, min_decimals: int = 0):
        super().__init__()
        self._min_decimals = min_decimals

    def textFromValue(self, value: float) -> str:
        text = f"{value:.{self.decimals()}f}"
        if "." in text:
            whole, frac = text.split(".")
            frac = frac.rstrip("0").ljust(self._min_decimals, "0")
            text = f"{whole}.{frac}" if frac else whole
        return text


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
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)

        header_box = QGroupBox("单据基本信息")
        form = QFormLayout(header_box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        type_row = QHBoxLayout()
        self.doc_type = QComboBox()
        self.doc_type.addItems(["PI", "CI", "PL"])
        self.doc_type.currentTextChanged.connect(self._on_doc_type_changed)
        self.doc_number = QLineEdit()
        gen_btn = QPushButton("生成新编号")
        gen_btn.clicked.connect(self._generate_number)
        type_row.addWidget(self.doc_type)
        type_row.addWidget(QLabel("编号："))
        type_row.addWidget(self.doc_number)
        type_row.addWidget(gen_btn)
        form.addRow("单据类型：", type_row)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("单据日期：", self.date_edit)

        self.customer_combo = QComboBox()
        self.customer_combo.currentIndexChanged.connect(self._on_customer_changed)
        form.addRow("收件方 (Buyer/Seller)：", self.customer_combo)

        self.destination = QLineEdit()
        form.addRow("Destination：", self.destination)

        validity_row = QHBoxLayout()
        self.validity_start = QDateEdit(QDate.currentDate())
        self.validity_start.setCalendarPopup(True)
        self.validity_start.setDisplayFormat("yyyy-MM-dd")
        self.validity_end = QDateEdit(QDate.currentDate().addDays(30))
        self.validity_end.setCalendarPopup(True)
        self.validity_end.setDisplayFormat("yyyy-MM-dd")
        # Start 变化时 End 自动保持 "Start + 30 天"，避免改了开始日期却忘记同步调整结束日期
        self.validity_start.dateChanged.connect(
            lambda d: self.validity_end.setDate(d.addDays(30))
        )
        validity_row.addWidget(self.validity_start)
        validity_row.addWidget(QLabel("至"))
        validity_row.addWidget(self.validity_end)
        form.addRow("Validity 有效期：", validity_row)

        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.currency.currentTextChanged.connect(self._recalculate)
        form.addRow("币种：", self.currency)

        # 付款条件：选择拆分方式后，导出单据末页会在总金额下方列出每次应付金额
        payment_row = QHBoxLayout()
        self.payment_combo = QComboBox()
        for label, pct in calc.PAYMENT_PRESETS:
            self.payment_combo.addItem(label, pct)
        self.payment_combo.addItem("自定义定金比例", CUSTOM_DEPOSIT)
        self.deposit_spin = QSpinBox()
        self.deposit_spin.setRange(1, 99)
        self.deposit_spin.setValue(40)
        self.deposit_spin.setSuffix(" % 定金")
        self.deposit_spin.setVisible(False)
        self.payment_combo.currentIndexChanged.connect(self._on_payment_changed)
        self.deposit_spin.valueChanged.connect(lambda _: self._recalculate(rebuild_table=False))
        payment_row.addWidget(self.payment_combo)
        payment_row.addWidget(self.deposit_spin)
        payment_row.addStretch()
        form.addRow("付款条件：", payment_row)

        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #E5E9ED;")
        form.addRow(line)

        # ---- 四类模板预设选择 ----
        template_row = QHBoxLayout()
        self.own_combo = QComboBox()
        self.delivery_combo = QComboBox()
        self.conditions_combo = QComboBox()
        self.banking_combo = QComboBox()
        for label, combo in (("Own", self.own_combo), ("Delivery", self.delivery_combo),
                             ("Conditions", self.conditions_combo), ("Banking", self.banking_combo)):
            template_row.addWidget(QLabel(f"{label}："))
            template_row.addWidget(combo)
        form.addRow("适用模板：", template_row)
        manage_hint = QLabel("↳ 模板预设可在「模板管理」页签中新增/编辑")
        manage_hint.setStyleSheet("color: #96A2AC; font-size: 11px;")
        form.addRow("", manage_hint)

        self.remark = QLineEdit()
        form.addRow("备注：", self.remark)

        layout.addWidget(header_box, 0)

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
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(lambda: self._move_selected_lines(-1))
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(lambda: self._move_selected_lines(1))
        del_sel_btn = QPushButton("删除所选")
        del_sel_btn.clicked.connect(self._remove_selected_lines)
        for b in (up_btn, down_btn, del_sel_btn):
            btn_row.addWidget(b)
        lines_layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(FINANCIAL_LINE_COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in FINANCIAL_LINE_COLUMNS])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)  # 行号已在 No. 列中显示
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.cellChanged.connect(self._on_cell_changed)
        # 保证产品明细表始终至少能看到约 6 行，避免被上方较长的表单挤到只剩一行
        self.table.setMinimumHeight(240)
        lines_layout.addWidget(self.table)
        # 拉伸系数=1，使产品明细表优先获得多余的垂直空间，
        # 而不是让上方表单的每一行被拉伸得过高（这正是之前"表格只显示一行"的原因）
        layout.addWidget(lines_box, 1)

        # ---- 汇总 ----
        totals_box = QGroupBox("汇总")
        totals_layout = QVBoxLayout(totals_box)
        self.totals_label = QLabel()
        self.totals_label.setStyleSheet("font-weight: bold;")
        self.words_label = QLabel()
        self.words_label.setWordWrap(True)
        totals_layout.addWidget(self.totals_label)
        totals_layout.addWidget(self.words_label)
        layout.addWidget(totals_box, 0)

        # ---- 操作 ----
        action_row = QHBoxLayout()
        new_btn = QPushButton("新建单据")
        new_btn.clicked.connect(self._new_document)
        save_btn = QPushButton("保存到历史")
        save_btn.clicked.connect(self._save_document)
        self.export_format = QComboBox()
        self.export_format.addItems(["PDF", "Word", "Excel"])
        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export_document)
        action_row.addWidget(new_btn)
        action_row.addWidget(save_btn)
        action_row.addWidget(QLabel("导出格式："))
        action_row.addWidget(self.export_format)
        action_row.addWidget(export_btn)
        action_row.addStretch()
        outer.addLayout(action_row)

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

    def _template_combos(self):
        return (
            ("own", self.own_combo), ("delivery", self.delivery_combo),
            ("conditions", self.conditions_combo), ("banking", self.banking_combo),
        )

    def _refresh_template_combos(self):
        templates = storage.load_templates()
        extras = getattr(self, "_snapshot_templates", {})
        for category, combo in self._template_combos():
            current_id = combo.currentData().get("id") if combo.currentData() else None
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("-- 无 --", None)
            restore_idx = 0
            options = list(templates.get(category, []))
            if category in extras:
                options.append(extras[category])
            for i, t in enumerate(options, start=1):
                combo.addItem(t.get("name") or "(未命名预设)", t)
                if current_id and t.get("id") == current_id:
                    restore_idx = i
            combo.setCurrentIndex(restore_idx)
            combo.blockSignals(False)

    def _select_templates_for(self, doc: dict):
        """
        按单据中保存的模板快照选回对应预设：内容完全一致的预设优先；
        若原预设已被修改或删除，则增加一项「原单据内容」保留旧快照，避免悄悄换成别的银行/地址。
        """
        self._snapshot_templates = {}
        templates = storage.load_templates()
        for category, _combo in self._template_combos():
            snapshot = doc.get(f"{category}_snapshot") or {}
            if snapshot and not any(t.get("fields", {}) == snapshot for t in templates.get(category, [])):
                self._snapshot_templates[category] = {
                    "id": f"__snapshot_{category}", "name": "(原单据内容)", "fields": dict(snapshot),
                }
        self._refresh_template_combos()
        for category, combo in self._template_combos():
            snapshot = doc.get(f"{category}_snapshot") or {}
            idx = 0
            if snapshot:
                idx = next((i for i in range(1, combo.count())
                            if combo.itemData(i).get("fields", {}) == snapshot), 0)
            combo.setCurrentIndex(idx)

    def _on_customer_changed(self):
        customer = self.customer_combo.currentData()
        if customer:
            self.document["customer_id"] = customer.get("customer_id", "")
            self.document["customer_snapshot"] = customer
            dest = ", ".join(filter(None, [customer.get("city", ""), customer.get("country_region", "")]))
            self.destination.setText(dest)

    def _on_doc_type_changed(self):
        self._rebuild_table(calc.compute_totals(self.document["lines"])["lines"])

    def _on_payment_changed(self):
        self.deposit_spin.setVisible(self.payment_combo.currentData() == CUSTOM_DEPOSIT)
        self._recalculate(rebuild_table=False)

    def _deposit_pct(self):
        data = self.payment_combo.currentData()
        if data == CUSTOM_DEPOSIT:
            return self.deposit_spin.value()
        return data

    def _set_deposit_pct(self, pct):
        self.payment_combo.blockSignals(True)
        idx = self.payment_combo.findData(pct) if pct is not None else 0
        if idx < 0:
            idx = self.payment_combo.findData(CUSTOM_DEPOSIT)
            self.deposit_spin.setValue(int(pct))
        self.payment_combo.setCurrentIndex(idx)
        self.payment_combo.blockSignals(False)
        self.deposit_spin.setVisible(self.payment_combo.currentData() == CUSTOM_DEPOSIT)

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
            product = dialog.selected_product
            product_currency = (product.get("currency") or "").upper()
            doc_currency = self.currency.currentText().upper()
            if product_currency and product_currency != doc_currency and product.get("unit_price"):
                QMessageBox.warning(
                    self, "币种不一致",
                    f"该产品在物料库中的单价为 {product_currency} {product.get('unit_price', 0):,.2f}，"
                    f"而当前单据币种为 {doc_currency}。\n软件不会自动换算汇率，请在明细表中核对并修改单价。",
                )
            line = make_doc_line(product, quantity=1)
            self.document["lines"].append(line)
            self._recalculate()

    def _ai_import_lines(self):
        if not show_privacy_notice_once(self):
            return
        replace_existing = False
        if self.document["lines"]:
            box = QMessageBox(self)
            box.setWindowTitle("已有产品明细")
            box.setText(
                f"当前单据已有 {len(self.document['lines'])} 条产品明细。\n"
                "导入的明细要替换现有明细，还是追加在后面？"
            )
            replace_btn = box.addButton("替换现有明细", QMessageBox.ButtonRole.DestructiveRole)
            append_btn = box.addButton("追加", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() not in (replace_btn, append_btn):
                return
            replace_existing = box.clickedButton() is replace_btn
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

        from core.ai_import import fill_from_product_library
        matched = fill_from_product_library(extracted, storage.load_products())

        review_columns = [
            ("model_no", "型号"), ("name_cn", "中文品名"), ("name_en", "英文品名"),
            ("hs_code", "HS编码"), ("unit", "单位"), ("quantity", "数量"), ("unit_price", "单价"),
            ("net_weight", "单件净重kg"), ("gross_weight", "单件毛重kg"), ("coo", "原产国"),
            ("remark", "备注"),
        ]
        warnings = getattr(extracted, "warnings", [])
        if warnings:
            QMessageBox.warning(
                self, "请核对识别结果",
                "\n".join(warnings) + "\n\n可能有明细行识别错误或遗漏，请在接下来的审核表中逐行核对。",
            )
        dialog = ImportReviewDialog(self, "审核 AI 识别的产品明细", review_columns, extracted)
        if not dialog.exec():
            return
        confirmed = dialog.get_confirmed_rows()
        if replace_existing:
            self.document["lines"] = []
        for row in confirmed:
            row["quantity"] = _safe_float(row.get("quantity"))
            row["unit_price"] = _safe_float(row.get("unit_price"))
            row["net_weight"] = _safe_float(row.get("net_weight"))
            row["gross_weight"] = _safe_float(row.get("gross_weight"))
            row.setdefault("coo", "")
            row.setdefault("remark", "")
            self.document["lines"].append(row)
        self._recalculate()
        QMessageBox.information(
            self, "提示",
            f"已导入 {len(confirmed)} 条产品明细，其中 {matched} 条按型号从物料库补全了"
            "文件中缺少的重量/HS编码/原产国等信息。\n其余缺少的信息可在明细表中手动补充。",
        )

    def _remove_line(self, index: int):
        if 0 <= index < len(self.document["lines"]):
            del self.document["lines"][index]
            self._recalculate()

    def _selected_rows(self) -> list:
        return sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})

    def _remove_selected_lines(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在明细表中选中要删除的行（可按住 Ctrl / Shift 多选）")
            return
        reply = QMessageBox.question(self, "删除明细", f"确定删除选中的 {len(rows)} 条明细吗？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        for r in reversed(rows):
            del self.document["lines"][r]
        self._recalculate()

    def _move_selected_lines(self, step: int):
        rows = self._selected_rows()
        lines = self.document["lines"]
        if not rows or (step < 0 and rows[0] == 0) or (step > 0 and rows[-1] == len(lines) - 1):
            return
        for r in (rows if step < 0 else reversed(rows)):
            lines[r + step], lines[r] = lines[r], lines[r + step]
        self._recalculate()
        self.table.clearSelection()
        mode = self.table.selectionMode()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for r in rows:
            self.table.selectRow(r + step)
        self.table.setSelectionMode(mode)

    def _is_financial(self) -> bool:
        return self.doc_type.currentText() != "PL"

    def _columns(self) -> list:
        return FINANCIAL_LINE_COLUMNS if self._is_financial() else PL_LINE_COLUMNS

    def _col(self, key: str):
        keys = [k for k, _ in self._columns()]
        return keys.index(key) if key in keys else None

    def _on_qty_or_price_changed(self):
        qty_col, price_col = self._col("quantity"), self._col("unit_price")
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

        parts = [f"总数量：{calc.fmt_qty(totals['total_quantity'])}"]
        if totals["total_net_weight"]:
            parts.append(f"总净重：{calc.fmt_weight(totals['total_net_weight'])} kg")
        if totals["total_gross_weight"]:
            parts.append(f"总毛重：{calc.fmt_weight(totals['total_gross_weight'])} kg")
        if totals["total_cbm"]:
            parts.append(f"总体积：{totals['total_cbm']:.3f} CBM")
        if self._is_financial():
            parts.append(f"总金额：{currency} {totals['total_amount']:,.2f}")
        self.totals_label.setText("    ".join(parts))
        if self._is_financial():
            words = calc.amount_in_words(totals["total_amount"], currency)
            for label, amount in calc.payment_schedule(totals["total_amount"], self._deposit_pct()):
                words += f"\n{label}:  {currency} {amount:,.2f}"
            self.words_label.setText(words)
        else:
            self.words_label.setText("")

    def _apply_column_sizing(self, columns: list):
        """
        表头文字长短不一，若所有列均等分宽度（Stretch），较长的表头文字会被裁剪。
        让"Description"这类需要较多空间的列拉伸，其余较短的列按内容自适应宽度。
        """
        header = self.table.horizontalHeader()
        narrow_columns = {"no", "unit", "coo", "hs_code", "op"}
        # 描述列固定一个较宽的初始宽度，剩余空间留给备注列，避免窗口较小时描述被挤到只剩几个字
        fixed_widths = {"quantity": 95, "unit_price": 105, "model_no": 110, "desc": 240}
        for col, (key, _label) in enumerate(columns):
            if key in narrow_columns:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            elif key == "remark":
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(col, fixed_widths.get(key, 90))

    def _on_cell_changed(self, row: int, col: int):
        if row >= len(self.document["lines"]):
            return
        item = self.table.item(row, col)
        if item is None:
            return
        text = item.text()
        line = self.document["lines"][row]
        key = self._columns()[col][0]
        if key == "desc":
            parts = text.split("\n", 1)
            line["name_en"] = parts[0]
            line["name_cn"] = parts[1] if len(parts) > 1 else ""
        elif key in WEIGHT_KEYS:
            try:
                line[key] = float(text) if text.strip() else 0.0
            except ValueError:
                return
            self._recalculate(rebuild_table=False)
        elif key in TEXT_KEYS:
            line[key] = text

    def _rebuild_table(self, computed_lines: list):
        columns = self._columns()
        self.table.blockSignals(True)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([label for _, label in columns])
        self.table.clearContents()
        self._apply_column_sizing(columns)
        self.table.setRowCount(len(computed_lines))

        for row, line in enumerate(computed_lines):
            for col, (key, _label) in enumerate(columns):
                if key == "quantity" or key == "unit_price":
                    spin = _TrimmedSpinBox(0 if key == "quantity" else 2)
                    spin.setMaximum(100_000_000)
                    spin.setDecimals(3 if key == "quantity" else calc.PRICE_DECIMALS)
                    spin.setValue(line.get(key, 0.0))
                    spin.valueChanged.connect(self._on_qty_or_price_changed)
                    disable_accidental_scroll_edits(spin)
                    self.table.setCellWidget(row, col, spin)
                elif key == "op":
                    del_btn = QPushButton("删除")
                    del_btn.clicked.connect(lambda _, r=row: self._remove_line(r))
                    self.table.setCellWidget(row, col, del_btn)
                else:
                    self.table.setItem(row, col, self._cell_item(key, line, row))

        self.table.blockSignals(False)

    def _cell_item(self, key: str, line: dict, row: int) -> QTableWidgetItem:
        if key == "no":
            text = str(row + 1)
        elif key == "desc":
            text = line.get("name_en", "")
            if line.get("name_cn"):
                text += f"\n{line.get('name_cn')}"
        elif key == "subtotal":
            text = f"{line['subtotal']:,.2f}"
        elif key in WEIGHT_KEYS or key in ("total_net_weight", "total_gross_weight"):
            text = calc.fmt_weight(line.get(key, 0))
        else:
            text = str(line.get(key, ""))
        item = QTableWidgetItem(text)
        if key in COMPUTED_KEYS:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _update_computed_cells(self, computed_lines: list):
        # 只刷新计算列；必须屏蔽信号，否则写入显示用的（已四舍五入的）文字会被
        # _on_cell_changed 当作用户输入写回数据，悄悄改掉原始重量
        self.table.blockSignals(True)
        for row, line in enumerate(computed_lines):
            for key in COMPUTED_KEYS - {"no"}:
                col = self._col(key)
                if col is not None:
                    self.table.setItem(row, col, self._cell_item(key, line, row))
        self.table.blockSignals(False)

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
            "deposit_pct": self._deposit_pct(),
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
        self._set_deposit_pct(None)
        self._recalculate()

    def _save_document(self):
        doc = self._collect_document()
        if not doc.get("customer_id"):
            QMessageBox.warning(self, "提示", "请先选择收件方")
            return
        if not doc.get("lines"):
            QMessageBox.warning(self, "提示", "请至少添加一条产品明细")
            return
        if not self._ensure_unique_number():
            return
        doc = self._collect_document()
        self._write_to_history(doc)
        notify(self, f"✓ 单据 {doc.get('doc_number', '')} 已保存到历史记录")

    def _ensure_unique_number(self) -> bool:
        """编号已被历史中另一份单据使用时，提示并换成新编号；返回 False 表示用户取消。"""
        doc = self._collect_document()
        clash = any(d.get("doc_number") == doc.get("doc_number") and d["id"] != doc["id"]
                    for d in storage.load_documents())
        if not clash:
            return True
        reply = QMessageBox.question(
            self, "编号重复",
            f"单据编号 {doc.get('doc_number')} 已被历史中的另一份单据使用。\n是否换成新编号？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        self._generate_number()
        return True

    def _write_to_history(self, doc: dict):
        documents = storage.load_documents()
        existing_idx = next((i for i, d in enumerate(documents) if d["id"] == doc["id"]), None)
        if existing_idx is not None:
            documents[existing_idx] = copy.deepcopy(doc)
        else:
            documents.append(copy.deepcopy(doc))
        storage.save_documents(documents)

    def has_unsaved_changes(self) -> bool:
        """当前单据有明细、且与历史中保存的版本不同（或从未保存）时返回 True。"""
        doc = self._collect_document()
        if not doc.get("lines"):
            return False
        saved = next((d for d in storage.load_documents() if d["id"] == doc["id"]), None)
        return saved != doc

    def _export_document(self):
        doc = self._collect_document()
        if not doc.get("customer_id"):
            QMessageBox.warning(self, "提示", "请先选择收件方")
            return
        if not doc.get("lines"):
            QMessageBox.warning(self, "提示", "请至少添加一条产品明细")
            return
        if not doc.get("doc_number"):
            self._generate_number()
        if not self._ensure_unique_number():
            return
        doc = self._collect_document()

        fmt = self.export_format.currentText()
        export_dir = get_exports_dir()
        target = os.path.join(export_dir, f"{doc.get('doc_number', 'DOC')}.{FORMAT_EXTENSIONS[fmt]}")
        if os.path.exists(target):
            reply = QMessageBox.question(
                self, "文件已存在",
                f"{os.path.basename(target)} 已存在，是否覆盖？\n（如需保留旧文件，请先点「生成新编号」）",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            path = export_document_in_format(doc, fmt, export_dir)
        except PermissionError:
            QMessageBox.critical(
                self, "导出失败",
                f"无法写入 {os.path.basename(target)}：该文件可能正在 Word / Excel / PDF 阅读器中打开，"
                "请关闭后重试。",
            )
            return
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"文件生成过程中发生错误：{e}")
            return

        # 导出即保存：保证历史记录与发给客户的文件一致
        self._write_to_history(doc)
        show_export_done(self, path, "（已同时保存到历史记录）")

    def get_current_document(self) -> dict:
        """供导出模块调用，获取当前联动计算后的完整单据数据"""
        return self._collect_document()

    def load_document(self, doc: dict):
        """从历史记录中加载一份单据到编辑界面（供"一键复制新建"使用）"""
        self.document = doc
        self._refresh_customer_combo()
        self._select_templates_for(doc)
        # 复制新建视为一份新单据：日期与有效期按今天重新生成
        self.date_edit.setDate(QDate.currentDate())
        self._set_default_dates()
        self.doc_type.setCurrentText(doc.get("doc_type", "PI"))
        idx = next(
            (i for i in range(self.customer_combo.count())
             if self.customer_combo.itemData(i) and self.customer_combo.itemData(i).get("customer_id") == doc.get("customer_id")),
            0,
        )
        self.customer_combo.setCurrentIndex(idx)
        self.doc_number.setText(doc.get("doc_number", ""))
        if not self.doc_number.text():
            self._generate_number()
        self.destination.setText(doc.get("destination", ""))
        self.currency.setCurrentText(doc.get("currency", "USD"))
        self.remark.setText(doc.get("remark", ""))
        self._set_deposit_pct(doc.get("deposit_pct"))
        self._recalculate()
