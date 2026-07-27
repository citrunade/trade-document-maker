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
