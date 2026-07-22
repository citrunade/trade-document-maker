"""
客户档案管理界面：新增、编辑、删除、模糊搜索
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QDialogButtonBox, QMessageBox, QAbstractItemView,
)

from core import storage
from core.models import make_customer
from ui.ai_import_helper import show_privacy_notice_once, pick_import_file, run_ai_extraction

COLUMNS = [
    ("name_cn", "客户中文名称"),
    ("name_en", "客户英文名称"),
    ("dest_country", "目的国"),
    ("pod", "目的港 (POD)"),
    ("email", "邮箱"),
]


class CustomerEditDialog(QDialog):
    def __init__(self, parent=None, customer: dict = None):
        super().__init__(parent)
        self.setWindowTitle("客户信息")
        self.setMinimumWidth(420)
        self.customer = customer or make_customer()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_cn = QLineEdit(self.customer.get("name_cn", ""))
        self.name_en = QLineEdit(self.customer.get("name_en", ""))
        self.consignee = QLineEdit(self.customer.get("consignee", ""))
        self.notify_party = QLineEdit(self.customer.get("notify_party", ""))
        self.dest_country = QLineEdit(self.customer.get("dest_country", ""))
        self.pod = QLineEdit(self.customer.get("pod", ""))
        self.vat_id = QLineEdit(self.customer.get("vat_id", ""))
        self.email = QLineEdit(self.customer.get("email", ""))
        self.remark = QLineEdit(self.customer.get("remark", ""))

        form.addRow("客户中文名称：", self.name_cn)
        form.addRow("客户英文名称：", self.name_en)
        form.addRow("收货人 Consignee：", self.consignee)
        form.addRow("通知人 Notify Party：", self.notify_party)
        form.addRow("目的国：", self.dest_country)
        form.addRow("目的港 POD：", self.pod)
        form.addRow("税号/VAT ID：", self.vat_id)
        form.addRow("邮箱：", self.email)
        form.addRow("备注：", self.remark)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> dict:
        self.customer.update({
            "name_cn": self.name_cn.text().strip(),
            "name_en": self.name_en.text().strip(),
            "consignee": self.consignee.text().strip(),
            "notify_party": self.notify_party.text().strip(),
            "dest_country": self.dest_country.text().strip(),
            "pod": self.pod.text().strip(),
            "vat_id": self.vat_id.text().strip(),
            "email": self.email.text().strip(),
            "remark": self.remark.text().strip(),
        })
        return self.customer


class CustomersTab(QWidget):
    def __init__(self):
        super().__init__()
        self.customers = storage.load_customers()
        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("按名称/国家/港口/邮箱模糊搜索…")
        self.search_box.textChanged.connect(self._refresh_table)
        top.addWidget(QLabel("搜索："))
        top.addWidget(self.search_box)
        top.addStretch()
        add_btn = QPushButton("新增客户")
        add_btn.clicked.connect(self._add_customer)
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_customer)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_customer)
        ai_btn = QPushButton("AI 导入客户")
        ai_btn.clicked.connect(self._ai_import_customer)
        top.addWidget(add_btn)
        top.addWidget(edit_btn)
        top.addWidget(del_btn)
        top.addWidget(ai_btn)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_customer)
        layout.addWidget(self.table)

    def _filtered(self) -> list:
        term = self.search_box.text().strip().lower()
        if not term:
            return self.customers
        result = []
        for c in self.customers:
            haystack = " ".join(str(c.get(k, "")) for k, _ in COLUMNS).lower()
            if term in haystack:
                result.append(c)
        return result

    def _refresh_table(self):
        rows = self._filtered()
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            for col_idx, (key, _) in enumerate(COLUMNS):
                self.table.setItem(r, col_idx, QTableWidgetItem(str(c.get(key, ""))))

    def _selected_customer(self) -> dict:
        row = self.table.currentRow()
        if row < 0:
            return None
        rows = self._filtered()
        if row >= len(rows):
            return None
        return rows[row]

    def _add_customer(self):
        dialog = CustomerEditDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            self.customers.append(data)
            storage.save_customers(self.customers)
            self._refresh_table()

    def _edit_customer(self):
        customer = self._selected_customer()
        if not customer:
            QMessageBox.information(self, "提示", "请先选择一个客户")
            return
        dialog = CustomerEditDialog(self, customer)
        if dialog.exec():
            dialog.get_data()
            storage.save_customers(self.customers)
            self._refresh_table()

    def _delete_customer(self):
        customer = self._selected_customer()
        if not customer:
            QMessageBox.information(self, "提示", "请先选择一个客户")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除客户「{customer.get('name_cn') or customer.get('name_en')}」吗？",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.customers.remove(customer)
            storage.save_customers(self.customers)
            self._refresh_table()

    def _ai_import_customer(self):
        if not show_privacy_notice_once(self):
            return
        path = pick_import_file(self)
        if not path:
            return
        from core.ai_import import import_customer
        extracted = run_ai_extraction(self, import_customer, path)
        if extracted is None:
            return
        dialog = CustomerEditDialog(self, extracted)
        if dialog.exec():
            data = dialog.get_data()
            self.customers.append(data)
            storage.save_customers(self.customers)
            self._refresh_table()

    def reload(self):
        self.customers = storage.load_customers()
        self._refresh_table()
