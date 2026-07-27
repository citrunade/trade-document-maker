"""
外贸制单工具 —— 程序入口
纯本地单机 Windows 桌面软件，无网络请求、无云端存储。
"""
import sys

from PyQt6.QtWidgets import QApplication

from core import storage
from core.seed import seed_all
from ui.main_window import MainWindow
from ui.style import apply_theme


def main():
    seed_all()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app, storage.load_company().get("ui_theme", "light"))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
