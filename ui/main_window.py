"""
主窗口：Tab 页整合设置/客户/物料/制单/历史/模板 各功能模块
"""
from PyQt6.QtWidgets import QMainWindow, QTabWidget

from ui.settings_tab import SettingsTab
from ui.customers_tab import CustomersTab
from ui.products_tab import ProductsTab
from ui.document_tab import DocumentTab
from ui.history_tab import HistoryTab
from ui.templates_tab import TemplatesTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("外贸制单工具 Trade Document Maker")
        self.resize(1200, 800)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.customers_tab = CustomersTab()
        self.products_tab = ProductsTab()
        self.settings_tab = SettingsTab()
        self.templates_tab = TemplatesTab()
        self.document_tab = DocumentTab()
        self.history_tab = HistoryTab(on_duplicate_to_document=self._load_doc_into_document_tab)

        self.tabs.addTab(self.document_tab, "制单")
        self.tabs.addTab(self.customers_tab, "客户档案")
        self.tabs.addTab(self.products_tab, "物料库")
        self.tabs.addTab(self.templates_tab, "模板管理")
        self.tabs.addTab(self.history_tab, "单据历史")
        self.tabs.addTab(self.settings_tab, "设置")

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        # 切换到制单页时刷新客户下拉列表与模板下拉列表，避免其他页改动后未同步
        if widget is self.document_tab:
            self.document_tab._refresh_customer_combo()
            self.document_tab._refresh_template_combos()
        # 切换到历史页时刷新列表，确保新保存的单据可见
        elif widget is self.history_tab:
            self.history_tab.reload()

    def _load_doc_into_document_tab(self, doc: dict):
        self.document_tab.load_document(doc)
        self.tabs.setCurrentWidget(self.document_tab)
