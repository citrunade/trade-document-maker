"""
客户档案管理界面：新增、编辑、删除、模糊搜索
字段规范见 docs/客户主体信息设计文档.md（10 个核心字段 + 制单业务扩展字段）
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
    ("customer_id", "客户编号"),
    ("name_cn", "中文名称"),
    ("name_en", "英文名称"),
    ("country_region", "国家/地区"),
    ("city", "城市"),
    ("email", "邮箱"),
    ("tel_phone", "联系电话"),
]


class CustomerEditDialog(QDialog):
    def __init__(self, parent=None, customer: dict = None):
        super().__init__(parent)
        self.setWindowTitle("客户信息")
        self.setMinimumWidth(440)
        self.customer = customer or make_customer()

        layout = QVBoxLayout(self)

        id_label = QLabel(f"客户编号：{self.customer.get('customer_id', '')}（系统自动生成，不可编辑）")
        id_label.setStyleSheet("color: #888;")
        layout.addWidget(id_label)

        form = QFormLayout()
        self.name_cn = QLineEdit(self.customer.get("name_cn", ""))
        self.name_en = QLineEdit(self.customer.get("name_en", ""))
        self.country_region = QLineEdit(self.customer.get("country_region", ""))
        self.city = QLineEdit(self.customer.get("city", ""))
        self.address_en = QLineEdit(self.customer.get("address_en", ""))
        self.tax_no = QLineEdit(self.customer.get("tax_no", ""))
        self.contact_person = QLineEdit(self.customer.get("contact_person", ""))
        self.email = QLineEdit(self.customer.get("email", ""))
        self.tel_phone = QLineEdit(self.customer.get("tel_phone", ""))
        self.company_reg_no = QLineEdit(self.customer.get("company_reg_no", ""))
        self.gst_no = QLineEdit(self.customer.get("gst_no", ""))

        form.addRow("中文名称：", self.name_cn)
        form.addRow("英文名称：", self.name_en)
        form.addRow("国家/地区：", self.country_region)
        form.addRow("城市：", self.city)
        form.addRow("英文完整地址：", self.address_en)
        form.addRow("税号 (VAT)：", self.tax_no)
        form.addRow("联系人：", self.contact_person)
        form.addRow("邮箱：", self.email)
        form.addRow("联系电话：", self.tel_phone)
        form.addRow("Company Reg. No.：", self.company_reg_no)
        form.addRow("GST No.：", self.gst_no)
        layout.addLayout(form)

        shipping_label = QLabel("以下为制单专用字段（生成 PI/CI/PL 时使用，可与上方地址不同）")
        shipping_label.setStyleSheet("color: #888; margin-top: 6px;")
        layout.addWidget(shipping_label)

        shipping_form = QFormLayout()
        self.consignee = QLineEdit(self.customer.get("consignee", ""))
        self.notify_party = QLineEdit(self.customer.get("notify_party", ""))
        self.pod = QLineEdit(self.customer.get("pod", ""))
        self.remark = QLineEdit(self.customer.get("remark", ""))
        shipping_form.addRow("收货人 Consignee：", self.consignee)
        shipping_form.addRow("通知人 Notify Party：", self.notify_party)
        shipping_form.addRow("默认目的港 POD：", self.pod)
        shipping_form.addRow("备注：", self.remark)
        layout.addLayout(shipping_form)

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
            "country_region": self.country_region.text().strip(),
            "city": self.city.text().strip(),
            "address_en": self.address_en.text().strip(),
            "tax_no": self.tax_no.text().strip(),
            "contact_person": self.contact_person.text().strip(),
            "email": self.email.text().strip(),
            "tel_phone": self.tel_phone.text().strip(),
            "company_reg_no": self.company_reg_no.text().strip(),
            "gst_no": self.gst_no.text().strip(),
            "consignee": self.consignee.text().strip(),
            "notify_party": self.notify_party.text().strip(),
            "pod": self.pod.text().strip(),
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
        self.search_box.setPlaceholderText("按编号/名称/国家/城市/邮箱/电话模糊搜索…")
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
