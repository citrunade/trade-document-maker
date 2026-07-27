"""
模板管理页面：Own(本公司信头) / Delivery(收货地址) / Conditions(条款) / Banking(银行信息)
每一类支持保存多个命名预设，制单时按需选择对应预设应用到单据。
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QDialog, QDialogButtonBox,
    QMessageBox, QTabWidget, QTextEdit,
)
from PyQt6.QtCore import Qt

from core import storage
from core.models import make_template

# 每类模板的字段规格： (key, label, multiline)
CATEGORY_FIELDS = {
    "own": [
        ("company_name_en", "公司英文名称", False),
        ("company_name_cn", "公司中文名称", False),
        ("address", "地址", True),
        ("phone", "电话", False),
        ("company_reg_no", "Company Reg. No.", False),
        ("gst_no", "GST No.", False),
        ("contact_person", "Our Contact 经办联系人", False),
        ("telephone", "Telephone", False),
        ("email", "Email", False),
    ],
    "delivery": [
        ("company_name", "收货单位名称", False),
        ("address", "收货地址", True),
    ],
    "conditions": [
        ("terms_of_payment", "Terms of Payment 付款方式", False),
        ("incoterm", "Incoterms 贸易术语", False),
        ("shipment_by", "Shipment by 运输方式", False),
    ],
    "banking": [
        ("bank_name", "Bank Name 银行名称", False),
        ("account_no", "Account No. 账号", False),
        ("swift_code", "Swift Code", False),
        ("beneficiary_name", "Beneficiary Name 收款人名称", False),
        ("beneficiary_bank_name", "Beneficiary Bank Name 收款银行名称", False),
        ("beneficiary_swift_code", "Beneficiary Swift Code", False),
        ("beneficiary_account_no", "Beneficiary Account No. 收款账号", False),
        ("correspondent_bank", "Correspondent Bank 代理行", False),
        ("beneficiary_bank_address", "Beneficiary Bank Address 收款银行地址", True),
    ],
}

CATEGORY_LABELS = {
    "own": "Own 本公司信头",
    "delivery": "Delivery Address 收货地址",
    "conditions": "Conditions 条款",
    "banking": "Banking 银行信息",
}


class TemplateEditDialog(QDialog):
    def __init__(self, parent, category: str, template: dict = None):
        super().__init__(parent)
        self.category = category
        self.template = template or make_template(category)
        self.setWindowTitle(f"{CATEGORY_LABELS[category]} - 预设编辑")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(self.template.get("name", ""))
        form.addRow("预设名称：", self.name_edit)
        layout.addLayout(form)

        self.field_widgets = {}
        field_form = QFormLayout()
        fields = self.template.get("fields", {})
        for key, label, multiline in CATEGORY_FIELDS[category]:
            if multiline:
                widget = QTextEdit()
                widget.setPlainText(fields.get(key, ""))
                widget.setMaximumHeight(70)
            else:
                widget = QLineEdit(fields.get(key, ""))
            self.field_widgets[key] = (widget, multiline)
            field_form.addRow(f"{label}：", widget)
        layout.addLayout(field_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> dict:
        fields = {}
        for key, (widget, multiline) in self.field_widgets.items():
            fields[key] = widget.toPlainText().strip() if multiline else widget.text().strip()
        self.template.update({"name": self.name_edit.text().strip(), "fields": fields})
        return self.template


class TemplateCategoryPanel(QWidget):
    def __init__(self, category: str):
        super().__init__()
        self.category = category
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        hint = QLabel(f"可保存多套「{CATEGORY_LABELS[self.category]}」预设，制单时按需选择其中一套应用到单据。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("新增预设")
        add_btn.clicked.connect(self._add)
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.list_widget = QListWidget()
        self.list_widget.doubleClicked.connect(self._edit)
        layout.addWidget(self.list_widget)

    def _refresh_list(self):
        templates = storage.load_templates()
        self.list_widget.clear()
        for t in templates.get(self.category, []):
            item = QListWidgetItem(t.get("name") or "(未命名预设)")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.list_widget.addItem(item)

    def _selected_template(self) -> dict:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _add(self):
        dialog = TemplateEditDialog(self, self.category)
        if dialog.exec():
            data = dialog.get_data()
            try:
                templates = storage.load_templates()
                templates.setdefault(self.category, []).append(data)
                storage.save_templates(templates)
            except Exception as e:
                storage.log_error(f"新增模板预设失败 category={self.category} data={data}", e)
                QMessageBox.critical(self, "保存失败", f"保存预设时发生错误，已记录到 data/error.log：\n{e}")
                return
            self._refresh_list()

    def _edit(self):
        template = self._selected_template()
        if not template:
            QMessageBox.information(self, "提示", "请先选择一个预设")
            return
        dialog = TemplateEditDialog(self, self.category, template)
        if dialog.exec():
            data = dialog.get_data()
            try:
                templates = storage.load_templates()
                category_list = templates.setdefault(self.category, [])
                for i, t in enumerate(category_list):
                    if t["id"] == data["id"]:
                        category_list[i] = data
                        break
                storage.save_templates(templates)
            except Exception as e:
                storage.log_error(f"编辑模板预设失败 category={self.category} data={data}", e)
                QMessageBox.critical(self, "保存失败", f"保存预设时发生错误，已记录到 data/error.log：\n{e}")
                return
            self._refresh_list()

    def _delete(self):
        template = self._selected_template()
        if not template:
            QMessageBox.information(self, "提示", "请先选择一个预设")
            return
        reply = QMessageBox.question(self, "确认删除", f"确定要删除预设「{template.get('name')}」吗？")
        if reply == QMessageBox.StandardButton.Yes:
            try:
                templates = storage.load_templates()
                templates[self.category] = [
                    t for t in templates.get(self.category, []) if t["id"] != template["id"]
                ]
                storage.save_templates(templates)
            except Exception as e:
                storage.log_error(f"删除模板预设失败 category={self.category}", e)
                QMessageBox.critical(self, "删除失败", f"删除预设时发生错误：\n{e}")
                return
            self._refresh_list()

    def reload(self):
        self._refresh_list()


class TemplatesTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.sub_tabs = QTabWidget()
        layout.addWidget(self.sub_tabs)

        self.panels = {}
        for category in ("own", "delivery", "conditions", "banking"):
            panel = TemplateCategoryPanel(category)
            self.panels[category] = panel
            self.sub_tabs.addTab(panel, CATEGORY_LABELS[category])

    def reload(self):
        for panel in self.panels.values():
            panel.reload()
