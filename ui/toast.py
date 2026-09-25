"""
轻量状态提示：在主窗口状态栏短暂显示提示信息，
用于替代"保存成功"一类无需用户特意确认的常规反馈，避免每次简单操作都弹出
模态对话框打断操作。找不到状态栏时静默忽略，不影响功能。
"""


def notify(widget, message: str, timeout: int = 3500) -> None:
    window = widget.window()
    status_bar_getter = getattr(window, "statusBar", None)
    if not callable(status_bar_getter):
        return
    try:
        status_bar_getter().showMessage(message, timeout)
    except Exception:
        pass


def show_export_done(parent, path: str, extra: str = "") -> None:
    """导出完成后提供「打开文件」「打开所在文件夹」按钮，免去手动查找导出目录。"""
    import os
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setWindowTitle("导出完成")
    box.setText(f"已导出：{os.path.basename(path)}{extra}\n\n{path}")
    open_file = box.addButton("打开文件", QMessageBox.ButtonRole.AcceptRole)
    open_dir = box.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
    box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is open_file:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    elif box.clickedButton() is open_dir:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
