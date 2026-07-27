"""
设置界面：Logo、AI 导入 API Key、数据备份与还原
（公司名称/地址/联系方式已迁移至「模板管理」页签的 Own 分类；
银行信息已迁移至「模板管理」页签的 Banking 分类）
"""
import os
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QGroupBox, QComboBox, QFileDialog, QMessageBox, QScrollArea, QApplication,
)

from core import storage, ai_client
from core.paths import get_data_path, get_backups_dir
from ui.style import apply_theme
from ui.toast import notify

THEME_LABELS = {"light": "浅色", "dark": "深色"}
THEME_KEYS = {v: k for k, v in THEME_LABELS.items()}


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

        info_hint = QLabel(
            "公司名称/地址/联系方式现已迁移至「模板管理」页签的 Own 分类中管理（支持保存多套预设，制单时按需选择）。\n"
            "银行信息现已迁移至「模板管理」页签的 Banking 分类中管理。"
        )
        info_hint.setWordWrap(True)
        info_hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info_hint)

        # --- 界面主题 ---
        theme_box = QGroupBox("界面主题")
        theme_layout = QHBoxLayout(theme_box)
        theme_hint = QLabel(
            "本设置独立于 Windows 系统的深色模式，切换后立即生效，"
            "可避免系统深色模式与软件界面显示不一致导致的花屏问题。"
        )
        theme_hint.setWordWrap(True)
        theme_hint.setStyleSheet("color: #888; font-size: 11px;")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEME_LABELS.values()))
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addWidget(theme_hint, stretch=1)
        layout.addWidget(theme_box)

        # --- AI 导入（阿里云百炼 / Qwen） ---
        ai_box = QGroupBox("AI 文件导入设置（阿里云百炼 / Qwen）")
        ai_layout = QVBoxLayout(ai_box)
        ai_notice = QLabel(
            "启用后可在客户档案/物料库/制单页面使用「AI 导入」功能，从 PDF/Excel/图片中自动识别字段。\n"
            "注意：该功能需要联网，会将所选文件内容发送至阿里云百炼（Qwen）云端 API，\n"
            "与本软件其余功能的纯本地设计不同，仅在您主动点击「AI 导入」时才会触发。"
        )
        ai_notice.setWordWrap(True)
        ai_notice.setStyleSheet("color: #999; font-size: 11px;")
        ai_layout.addWidget(ai_notice)

        ai_form = QFormLayout()
        self.bailian_api_key = QLineEdit()
        self.bailian_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.bailian_base_url = QLineEdit()
        self.bailian_base_url.setPlaceholderText(ai_client.DEFAULT_BASE_URL)
        self.bailian_text_model = QLineEdit()
        self.bailian_text_model.setPlaceholderText(ai_client.DEFAULT_TEXT_MODEL)
        self.bailian_vision_model = QLineEdit()
        self.bailian_vision_model.setPlaceholderText(ai_client.DEFAULT_VISION_MODEL)
        ai_form.addRow("百炼 API Key：", self.bailian_api_key)
        ai_form.addRow("API 地址（留空使用中国北京默认）：", self.bailian_base_url)
        ai_form.addRow("文本模型（留空使用默认）：", self.bailian_text_model)
        ai_form.addRow("视觉模型（留空使用默认）：", self.bailian_vision_model)
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
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentText(THEME_LABELS.get(c.get("ui_theme", "light"), "浅色"))
        self.theme_combo.blockSignals(False)
        self.bailian_api_key.setText(c.get("bailian_api_key", ""))
        self.bailian_base_url.setText(c.get("bailian_base_url", ""))
        self.bailian_text_model.setText(c.get("bailian_text_model", ""))
        self.bailian_vision_model.setText(c.get("bailian_vision_model", ""))
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

    def _on_theme_changed(self, label: str):
        theme_key = THEME_KEYS.get(label, "light")
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme_key)
        self.company["ui_theme"] = theme_key
        storage.save_company(self.company)
        notify(self, f"✓ 已切换为{label}主题")

    def _save(self):
        self.company.update({
            "bailian_api_key": self.bailian_api_key.text().strip(),
            "bailian_base_url": self.bailian_base_url.text().strip(),
            "bailian_text_model": self.bailian_text_model.text().strip(),
            "bailian_vision_model": self.bailian_vision_model.text().strip(),
        })
        storage.save_company(self.company)
        notify(self, "✓ 设置已保存")

    def _test_ai_connection(self):
        api_key = self.bailian_api_key.text().strip()
        base_url = self.bailian_base_url.text().strip() or ai_client.DEFAULT_BASE_URL
        text_model = self.bailian_text_model.text().strip() or ai_client.DEFAULT_TEXT_MODEL
        try:
            ai_client.test_connection(api_key, base_url, text_model)
        except ai_client.AIClientError as e:
            QMessageBox.warning(self, "连接失败", str(e))
            return
        notify(self, "✓ 阿里云百炼连接测试成功")

    def _backup_data(self):
        try:
            archive_path = storage.backup_data()
        except Exception as e:
            QMessageBox.critical(self, "备份失败", f"备份过程中发生错误：{e}")
            return
        notify(self, f"✓ 数据已备份至 {archive_path}")

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
