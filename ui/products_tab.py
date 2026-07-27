"""
产品物料库管理界面：新增、编辑、删除、模糊搜索、Excel 批量导入
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QDialogButtonBox, QMessageBox, QAbstractItemView, QComboBox, QDoubleSpinBox,
    QFileDialog,
)

from core import storage
from core.models import make_product
from ui.ai_import_helper import (
    show_privacy_notice_once, pick_import_file, run_ai_extraction, ImportReviewDialog,
)

COLUMNS = [
    ("model_no", "型号"),
    ("name_cn", "中文品名"),
    ("name_en", "英文品名"),
    ("hs_code", "HS编码"),
    ("unit", "单位"),
    ("net_weight", "净重(kg)"),
    ("gross_weight", "毛重(kg)"),
    ("unit_price", "单价"),
    ("currency", "币种"),
]

UNITS = ["pcs", "set", "m", "kg", "box", "pair", "roll"]
CURRENCIES = ["USD", "EUR", "RMB"]


def _spin(maximum=1_000_000.0, decimals=3):
    box = QDoubleSpinBox()
    box.setMaximum(maximum)
    box.setDecimals(decimals)
    return box


class ProductEditDialog(QDialog):
    def __init__(self, parent=None, product: dict = None):
        super().__init__(parent)
        self.setWindowTitle("产品物料信息")
        self.setMinimumWidth(420)
        self.product = product or make_product()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.model_no = QLineEdit(self.product.get("model_no", ""))
        self.name_cn = QLineEdit(self.product.get("name_cn", ""))
        self.name_en = QLineEdit(self.product.get("name_en", ""))
        self.hs_code = QLineEdit(self.product.get("hs_code", ""))
        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.unit.addItems(UNITS)
        self.unit.setCurrentText(self.product.get("unit", "pcs"))

        self.net_weight = _spin()
        self.net_weight.setValue(self.product.get("net_weight", 0.0))
        self.gross_weight = _spin()
        self.gross_weight.setValue(self.product.get("gross_weight", 0.0))
        self.length_mm = _spin(100000, 1)
        self.length_mm.setValue(self.product.get("length_mm", 0.0))
        self.width_mm = _spin(100000, 1)
        self.width_mm.setValue(self.product.get("width_mm", 0.0))
        self.height_mm = _spin(100000, 1)
        self.height_mm.setValue(self.product.get("height_mm", 0.0))
        self.unit_price = _spin(10_000_000, 2)
        self.unit_price.setValue(self.product.get("unit_price", 0.0))
        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.currency.setCurrentText(self.product.get("currency", "USD"))
        self.coo = QLineEdit(self.product.get("coo", ""))
        self.remark = QLineEdit(self.product.get("remark", ""))

        form.addRow("型号：", self.model_no)
        form.addRow("中文品名：", self.name_cn)
        form.addRow("英文品名：", self.name_en)
        form.addRow("HS 编码：", self.hs_code)
        form.addRow("单位：", self.unit)
        form.addRow("单台净重(kg)：", self.net_weight)
        form.addRow("单台毛重(kg)：", self.gross_weight)
        form.addRow("外包装长(mm)：", self.length_mm)
        form.addRow("外包装宽(mm)：", self.width_mm)
        form.addRow("外包装高(mm)：", self.height_mm)
        form.addRow("单价：", self.unit_price)
        form.addRow("币种：", self.currency)
        form.addRow("原产国/地区 COO：", self.coo)
        form.addRow("备注：", self.remark)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> dict:
        self.product.update({
            "model_no": self.model_no.text().strip(),
            "name_cn": self.name_cn.text().strip(),
            "name_en": self.name_en.text().strip(),
            "hs_code": self.hs_code.text().strip(),
            "unit": self.unit.currentText().strip(),
            "net_weight": self.net_weight.value(),
            "gross_weight": self.gross_weight.value(),
            "length_mm": self.length_mm.value(),
            "width_mm": self.width_mm.value(),
            "height_mm": self.height_mm.value(),
            "unit_price": self.unit_price.value(),
            "currency": self.currency.currentText(),
            "coo": self.coo.text().strip(),
            "remark": self.remark.text().strip(),
        })
        return self.product


class ProductsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.products = storage.load_products()
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("按型号/品名/HS编码模糊搜索…")
        self.search_box.textChanged.connect(self._refresh_table)
        top.addWidget(QLabel("搜索："))
        top.addWidget(self.search_box)
        top.addStretch()
        add_btn = QPushButton("新增物料")
        add_btn.clicked.connect(self._add_product)
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_product)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_product)
        import_btn = QPushButton("Excel 批量导入")
        import_btn.clicked.connect(self._import_excel)
        ai_import_btn = QPushButton("AI 批量导入（PDF/图片/Excel）")
        ai_import_btn.clicked.connect(self._ai_import_products)
        top.addWidget(add_btn)
        top.addWidget(edit_btn)
        top.addWidget(del_btn)
        top.addWidget(import_btn)
        top.addWidget(ai_import_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_product)
        layout.addWidget(self.table)

    def _filtered(self) -> list:
        term = self.search_box.text().strip().lower()
        if not term:
            return self.products
        result = []
        for p in self.products:
            haystack = " ".join(str(p.get(k, "")) for k, _ in COLUMNS).lower()
            if term in haystack:
                result.append(p)
        return result

    def _refresh_table(self):
        rows = self._filtered()
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            for col_idx, (key, _) in enumerate(COLUMNS):
                self.table.setItem(r, col_idx, QTableWidgetItem(str(p.get(key, ""))))

    def _selected_product(self) -> dict:
        row = self.table.currentRow()
        if row < 0:
            return None
        rows = self._filtered()
        if row >= len(rows):
            return None
        return rows[row]

    def _add_product(self):
        dialog = ProductEditDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            self.products.append(data)
            storage.save_products(self.products)
            self._refresh_table()

    def _edit_product(self):
        product = self._selected_product()
        if not product:
            QMessageBox.information(self, "提示", "请先选择一个物料")
            return
        dialog = ProductEditDialog(self, product)
        if dialog.exec():
            dialog.get_data()
            storage.save_products(self.products)
            self._refresh_table()

    def _delete_product(self):
        product = self._selected_product()
        if not product:
            QMessageBox.information(self, "提示", "请先选择一个物料")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除物料「{product.get('model_no')} {product.get('name_cn')}」吗？",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.products.remove(product)
            storage.save_products(self.products)
            self._refresh_table()

    def _import_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Excel 文件", "", "Excel 文件 (*.xlsx *.xls)"
        )
        if not path:
            return
        try:
            import pandas as pd
            df = pd.read_excel(path)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法读取 Excel 文件：{e}")
            return

        col_map = {
            "型号": "model_no", "model_no": "model_no",
            "中文品名": "name_cn", "name_cn": "name_cn",
            "英文品名": "name_en", "name_en": "name_en",
            "HS编码": "hs_code", "hs_code": "hs_code",
            "单位": "unit", "unit": "unit",
            "净重": "net_weight", "net_weight": "net_weight",
            "毛重": "gross_weight", "gross_weight": "gross_weight",
            "长": "length_mm", "length_mm": "length_mm",
            "宽": "width_mm", "width_mm": "width_mm",
            "高": "height_mm", "height_mm": "height_mm",
            "单价": "unit_price", "unit_price": "unit_price",
            "币种": "currency", "currency": "currency",
            "备注": "remark", "remark": "remark",
        }

        imported = 0
        for _, row in df.iterrows():
            data = {}
            for col in df.columns:
                key = col_map.get(str(col).strip())
                if key:
                    data[key] = row[col]
            if not data.get("model_no") and not data.get("name_cn"):
                continue
            for num_field in ("net_weight", "gross_weight", "length_mm", "width_mm", "height_mm", "unit_price"):
                try:
                    data[num_field] = float(data.get(num_field, 0) or 0)
                except (ValueError, TypeError):
                    data[num_field] = 0.0
            product = make_product(
                model_no=str(data.get("model_no", "")),
                name_cn=str(data.get("name_cn", "")),
                name_en=str(data.get("name_en", "")),
                hs_code=str(data.get("hs_code", "")),
                unit=str(data.get("unit", "pcs")) or "pcs",
                net_weight=data.get("net_weight", 0.0),
                gross_weight=data.get("gross_weight", 0.0),
                length_mm=data.get("length_mm", 0.0),
                width_mm=data.get("width_mm", 0.0),
                height_mm=data.get("height_mm", 0.0),
                unit_price=data.get("unit_price", 0.0),
                currency=str(data.get("currency", "USD")) or "USD",
                remark=str(data.get("remark", "")),
            )
            self.products.append(product)
            imported += 1

        storage.save_products(self.products)
        self._refresh_table()
        QMessageBox.information(self, "导入完成", f"成功导入 {imported} 条物料数据")

    def _ai_import_products(self):
        if not show_privacy_notice_once(self):
            return
        path = pick_import_file(self)
        if not path:
            return
        from core.ai_import import import_products
        extracted = run_ai_extraction(self, import_products, path)
        if extracted is None:
            return
        if not extracted:
            QMessageBox.information(self, "提示", "未能从该文件中识别出任何产品信息")
            return

        review_columns = [
            ("model_no", "型号"), ("name_cn", "中文品名"), ("name_en", "英文品名"),
            ("hs_code", "HS编码"), ("unit", "单位"), ("net_weight", "净重(kg)"),
            ("gross_weight", "毛重(kg)"), ("length_mm", "长(mm)"), ("width_mm", "宽(mm)"),
            ("height_mm", "高(mm)"), ("unit_price", "单价"), ("currency", "币种"),
        ]
        dialog = ImportReviewDialog(self, "审核 AI 识别的产品信息", review_columns, extracted)
        if not dialog.exec():
            return
        confirmed = dialog.get_confirmed_rows()

        added = 0
        for row in confirmed:
            product = make_product(
                model_no=row.get("model_no", ""),
                name_cn=row.get("name_cn", ""),
                name_en=row.get("name_en", ""),
                hs_code=row.get("hs_code", ""),
                unit=row.get("unit", "pcs") or "pcs",
                net_weight=_safe_float(row.get("net_weight")),
                gross_weight=_safe_float(row.get("gross_weight")),
                length_mm=_safe_float(row.get("length_mm")),
                width_mm=_safe_float(row.get("width_mm")),
                height_mm=_safe_float(row.get("height_mm")),
                unit_price=_safe_float(row.get("unit_price")),
                currency=row.get("currency", "USD") or "USD",
                remark=row.get("remark", ""),
            )
            self.products.append(product)
            added += 1

        storage.save_products(self.products)
        self._refresh_table()
        QMessageBox.information(self, "导入完成", f"成功导入 {added} 条产品数据")

    def reload(self):
        self.products = storage.load_products()
        self._refresh_table()


def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
