"""
设置界面：我方公司信息、Logo、银行信息、默认港口/贸易术语
"""
import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QGroupBox, QComboBox, QFileDialog, QMessageBox, QScrollArea,
)

from core import storage, ai_client
from core.paths import get_data_path, get_backups_dir


INCOTERMS = ["FOB", "CIF", "CFR", "EXW", "DAP", "DDP", "FCA", "CPT", "CIP"]


class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.company = storage.load_company()
        self._build_ui()
        self._load_into_form()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        layout = QVBoxLayout(container)

        # --- Logo ---
        logo_box = QGroupBox("公司 Logo")
        logo_layout = QHBoxLayout(logo_box)
        self.logo_preview = QLabel("暂无 Logo")
        self.logo_preview.setFixedSize(200, 80)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet("border: 1px solid #ccc; background: #fafafa;")
        logo_layout.addWidget(self.logo_preview)
        btn_col = QVBoxLayout()
        pick_btn = QPushButton("选择/替换 Logo 图片")
        pick_btn.clicked.connect(self._pick_logo)
        clear_btn = QPushButton("清除 Logo")
        clear_btn.clicked.connect(self._clear_logo)
        btn_col.addWidget(pick_btn)
        btn_col.addWidget(clear_btn)
        btn_col.addStretch()
        logo_layout.addLayout(btn_col)
        logo_layout.addStretch()
        layout.addWidget(logo_box)

        # --- 基本信息 ---
        basic_box = QGroupBox("公司基本信息")
        form = QFormLayout(basic_box)
        self.name_cn = QLineEdit()
        self.name_en = QLineEdit()
        self.address_cn = QLineEdit()
        self.address_en = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.tax_id = QLineEdit()
        form.addRow("公司中文名称：", self.name_cn)
        form.addRow("公司英文名称：", self.name_en)
        form.addRow("中文地址：", self.address_cn)
        form.addRow("英文地址：", self.address_en)
        form.addRow("电话：", self.phone)
        form.addRow("邮箱：", self.email)
        form.addRow("税号：", self.tax_id)
        layout.addWidget(basic_box)

        # --- 银行信息 ---
        bank_box = QGroupBox("Bank Detail 银行信息")
        bform = QFormLayout(bank_box)
        self.bank_name_cn = QLineEdit()
        self.bank_name_en = QLineEdit()
        self.bank_account = QLineEdit()
        self.swift_code = QLineEdit()
        self.bank_address_en = QLineEdit()
        bform.addRow("开户行（中文）：", self.bank_name_cn)
        bform.addRow("开户行（英文）：", self.bank_name_en)
        bform.addRow("账号：", self.bank_account)
        bform.addRow("SWIFT Code：", self.swift_code)
        bform.addRow("银行地址（英文）：", self.bank_address_en)
        layout.addWidget(bank_box)

        # --- 默认贸易设置 ---
        trade_box = QGroupBox("默认贸易设置")
        tform = QFormLayout(trade_box)
        self.default_pol = QLineEdit()
        self.default_incoterm = QComboBox()
        self.default_incoterm.addItems(INCOTERMS)
        tform.addRow("默认离岸港口 (POL)：", self.default_pol)
        tform.addRow("默认贸易术语：", self.default_incoterm)
        layout.addWidget(trade_box)

        # --- AI 导入 (智谱 AI) ---
        ai_box = QGroupBox("AI 文件导入设置（智谱 AI Zhipu/GLM）")
        ai_layout = QVBoxLayout(ai_box)
        ai_notice = QLabel(
            "启用后可在客户档案/物料库/制单页面使用「AI 导入」功能，从 PDF/Excel/图片中自动识别字段。\n"
            "注意：该功能需要联网，会将所选文件内容发送至智谱 AI（Zhipu/BigModel）云端 API，\n"
            "与本软件其余功能的纯本地设计不同，仅在您主动点击「AI 导入」时才会触发。"
        )
        ai_notice.setWordWrap(True)
        ai_notice.setStyleSheet("color: #999; font-size: 11px;")
        ai_layout.addWidget(ai_notice)

        ai_form = QFormLayout()
        self.zhipu_api_key = QLineEdit()
        self.zhipu_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.zhipu_base_url = QLineEdit()
        self.zhipu_base_url.setPlaceholderText(ai_client.DEFAULT_BASE_URL)
        self.zhipu_text_model = QLineEdit()
        self.zhipu_text_model.setPlaceholderText(ai_client.DEFAULT_TEXT_MODEL)
        self.zhipu_vision_model = QLineEdit()
        self.zhipu_vision_model.setPlaceholderText(ai_client.DEFAULT_VISION_MODEL)
        ai_form.addRow("智谱 AI API Key：", self.zhipu_api_key)
        ai_form.addRow("API 地址（留空使用默认）：", self.zhipu_base_url)
        ai_form.addRow("文本模型（留空使用默认）：", self.zhipu_text_model)
        ai_form.addRow("视觉模型（留空使用默认）：", self.zhipu_vision_model)
        ai_layout.addLayout(ai_form)

        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_ai_connection)
        ai_layout.addWidget(test_btn)
        layout.addWidget(ai_box)

        save_btn = QPushButton("保存设置")
        save_btn.setMinimumHeight(36)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        # --- 数据备份与还原 ---
        backup_box = QGroupBox("数据备份与还原")
        backup_layout = QHBoxLayout(backup_box)
        backup_btn = QPushButton("备份数据（导出 ZIP）")
        backup_btn.clicked.connect(self._backup_data)
        restore_btn = QPushButton("从备份还原")
        restore_btn.clicked.connect(self._restore_data)
        backup_layout.addWidget(backup_btn)
        backup_layout.addWidget(restore_btn)
        backup_layout.addStretch()
        layout.addWidget(backup_box)

        layout.addStretch()

    def _load_into_form(self):
        c = self.company
        self.name_cn.setText(c.get("name_cn", ""))
        self.name_en.setText(c.get("name_en", ""))
        self.address_cn.setText(c.get("address_cn", ""))
        self.address_en.setText(c.get("address_en", ""))
        self.phone.setText(c.get("phone", ""))
        self.email.setText(c.get("email", ""))
        self.tax_id.setText(c.get("tax_id", ""))
        self.bank_name_cn.setText(c.get("bank_name_cn", ""))
        self.bank_name_en.setText(c.get("bank_name_en", ""))
        self.bank_account.setText(c.get("bank_account", ""))
        self.swift_code.setText(c.get("swift_code", ""))
        self.bank_address_en.setText(c.get("bank_address_en", ""))
        self.default_pol.setText(c.get("default_pol", ""))
        idx = self.default_incoterm.findText(c.get("default_incoterm", "FOB"))
        self.default_incoterm.setCurrentIndex(max(idx, 0))
        self.zhipu_api_key.setText(c.get("zhipu_api_key", ""))
        self.zhipu_base_url.setText(c.get("zhipu_base_url", ""))
        self.zhipu_text_model.setText(c.get("zhipu_text_model", ""))
        self.zhipu_vision_model.setText(c.get("zhipu_vision_model", ""))
        self._refresh_logo_preview()

    def _refresh_logo_preview(self):
        logo_path = get_data_path("logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                self.logo_preview.setPixmap(
                    pixmap.scaled(200, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
                )
                return
        self.logo_preview.setPixmap(QPixmap())
        self.logo_preview.setText("暂无 Logo")

    def _pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Logo 图片", "", "图片文件 (*.png *.jpg *.jpeg)"
        )
        if not path:
            return
        dest = get_data_path("logo.png")
        try:
            if path.lower().endswith((".jpg", ".jpeg")):
                pixmap = QPixmap(path)
                if pixmap.isNull():
                    raise ValueError("无法读取图片")
                pixmap.save(dest, "PNG")
            else:
                shutil.copy2(path, dest)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"Logo 保存失败：{e}")
            return
        self._refresh_logo_preview()

    def _clear_logo(self):
        dest = get_data_path("logo.png")
        if os.path.exists(dest):
            os.remove(dest)
        self._refresh_logo_preview()

    def _save(self):
        self.company.update({
            "name_cn": self.name_cn.text().strip(),
            "name_en": self.name_en.text().strip(),
            "address_cn": self.address_cn.text().strip(),
            "address_en": self.address_en.text().strip(),
            "phone": self.phone.text().strip(),
            "email": self.email.text().strip(),
            "tax_id": self.tax_id.text().strip(),
            "bank_name_cn": self.bank_name_cn.text().strip(),
            "bank_name_en": self.bank_name_en.text().strip(),
            "bank_account": self.bank_account.text().strip(),
            "swift_code": self.swift_code.text().strip(),
            "bank_address_en": self.bank_address_en.text().strip(),
            "default_pol": self.default_pol.text().strip(),
            "default_incoterm": self.default_incoterm.currentText(),
            "zhipu_api_key": self.zhipu_api_key.text().strip(),
            "zhipu_base_url": self.zhipu_base_url.text().strip(),
            "zhipu_text_model": self.zhipu_text_model.text().strip(),
            "zhipu_vision_model": self.zhipu_vision_model.text().strip(),
        })
        storage.save_company(self.company)
        QMessageBox.information(self, "提示", "设置已保存")

    def _test_ai_connection(self):
        api_key = self.zhipu_api_key.text().strip()
        base_url = self.zhipu_base_url.text().strip() or ai_client.DEFAULT_BASE_URL
        text_model = self.zhipu_text_model.text().strip() or ai_client.DEFAULT_TEXT_MODEL
        try:
            ai_client.test_connection(api_key, base_url, text_model)
        except ai_client.AIClientError as e:
            QMessageBox.warning(self, "连接失败", str(e))
            return
        QMessageBox.information(self, "连接成功", "智谱 AI 连接测试成功！")

    def _backup_data(self):
        try:
            archive_path = storage.backup_data()
        except Exception as e:
            QMessageBox.critical(self, "备份失败", f"备份过程中发生错误：{e}")
            return
        QMessageBox.information(self, "备份完成", f"数据已备份至：\n{archive_path}")

    def _restore_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择备份 ZIP 文件", get_backups_dir(), "ZIP 文件 (*.zip)"
        )
        if not path:
            return
        reply = QMessageBox.question(
            self, "确认还原",
            "还原将覆盖当前客户、物料、单据历史及 Logo 等数据，且此操作不可撤销。\n"
            "建议还原前先执行一次备份。确定要继续吗？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            storage.restore_data(path)
        except Exception as e:
            QMessageBox.critical(self, "还原失败", f"还原过程中发生错误：{e}")
            return
        QMessageBox.information(self, "还原完成", "数据已还原，请重启软件以确保界面完全刷新。")
