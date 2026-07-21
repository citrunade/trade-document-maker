"""
外贸制单工具 —— 程序入口
纯本地单机 Windows 桌面软件，无网络请求、无云端存储。
"""
import sys

from PyQt6.QtWidgets import QApplication

from core.seed import seed_all
from ui.main_window import MainWindow


def main():
    seed_all()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
