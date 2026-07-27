"""
外贸制单工具 —— 程序入口
纯本地单机 Windows 桌面软件，无网络请求、无云端存储。
"""
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from core import storage
from core.paths import check_data_dir_writable, get_app_root
from core.seed import seed_all
from ui.main_window import MainWindow
from ui.style import apply_theme


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if not check_data_dir_writable():
        QMessageBox.critical(
            None, "无法保存数据",
            f"程序无法写入数据目录：\n{get_app_root()}\\data\n\n"
            "常见原因：程序被放在「C:\\Program Files」等受系统保护的目录下。\n"
            "请将程序整个文件夹移动到桌面或「文档」等普通目录后重新打开，"
            "否则新增/修改的内容可能无法真正保存。",
        )
    seed_all()
    apply_theme(app, storage.load_company().get("ui_theme", "light"))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
