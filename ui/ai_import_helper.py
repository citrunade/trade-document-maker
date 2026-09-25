"""
AI 导入功能的公共辅助逻辑：隐私提示、文件选择、忙碌光标、通用审核表格对话框。
供 customers_tab / products_tab / document_tab 复用。
"""
from PyQt6.QtCore import Qt, QThread, QEventLoop, QTimer
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox, QCheckBox,
    QHeaderView, QLabel, QProgressDialog,
)

from core import storage

_notice_shown_this_session = False

FILE_FILTER = "支持的文件 (*.pdf *.xlsx *.xls *.docx *.jpg *.jpeg *.png)"


def show_privacy_notice_once(parent) -> bool:
    """
    首次使用 AI 导入功能时提示用户数据将发送至云端。
    返回 True 表示用户已知悉并继续（后续同一次运行不再重复提示）；
    返回 False 表示用户在提示框中取消。
    """
    global _notice_shown_this_session
    if _notice_shown_this_session:
        return True
    reply = QMessageBox.question(
        parent, "AI 导入提示",
        "此功能会将您选择的文件内容发送至阿里云百炼（Qwen）云端 API 进行识别，需要联网。\n"
        "本软件其余功能均为纯本地运行，仅此 AI 导入功能涉及网络传输。\n\n"
        "是否继续？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
    )
    if reply == QMessageBox.StandardButton.Yes:
        _notice_shown_this_session = True
        return True
    return False


def pick_import_file(parent) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, "选择要导入的文件", "", FILE_FILTER)
    return path


def get_ai_config() -> dict:
    return storage.load_company()


def run_ai_extraction(parent, extractor_fn, path: str):
    """
    在忙碌光标下执行提取函数，统一处理 AIImportError / AIClientError，
    成功返回提取结果，失败返回 None（已弹窗提示错误）。
    """
    from core.ai_import import AIImportError
    from core.ai_client import AIClientError

    config = get_ai_config()
    # 在后台线程中调用 AI（最长可能需要 1~2 分钟），界面显示进度窗口而不是"未响应"
    worker = _ExtractionWorker(extractor_fn, path, config)
    progress = QProgressDialog("AI 正在识别文件内容，请稍候…\n（多页文件可能需要 1~2 分钟）", None, 0, 0, parent)
    progress.setWindowTitle("AI 导入")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setCancelButton(None)
    progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    # 兜底轮询：若线程在进入事件循环前就已结束（错过 finished 信号），也能正常退出
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if worker.isFinished() else None)
    poll.start(200)
    worker.start()
    progress.show()
    loop.exec()
    poll.stop()
    worker.wait()
    progress.close()

    error = worker.error
    if error is None:
        return worker.result
    if isinstance(error, (AIImportError, AIClientError)):
        QMessageBox.warning(parent, "AI 导入失败", str(error))
    else:
        QMessageBox.critical(parent, "AI 导入失败", f"发生未预期的错误：{error}")
    return None


class _ExtractionWorker(QThread):
    def __init__(self, fn, path, config):
        super().__init__()
        self.fn, self.path, self.config = fn, path, config
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.fn(self.path, self.config)
        except Exception as e:  # 在主线程中统一弹窗提示
            self.error = e


def _display(value) -> str:
    """数字去掉多余的 0（4.0 -> 4），0 显示为空白，方便一眼看出哪些字段没有识别到。"""
    if isinstance(value, float):
        if not value:
            return ""
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


# 审核表中需要较宽显示的列及其最大宽度（像素）
WIDE_REVIEW_COLUMNS = {"name_en": 280, "name_cn": 200, "address_en": 320, "model_no": 160, "remark": 220}


class ImportReviewDialog(QDialog):
    """
    通用的 AI 提取结果审核对话框：以表格形式展示每一条提取到的记录，
    每行带勾选框（默认勾选），单元格可直接编辑修正 AI 识别错误的字段。
    确认后仅返回勾选的行（含用户编辑后的最新值）。
    """

    def __init__(self, parent, title: str, columns: list, rows: list):
        """
        columns: [(key, label), ...]
        rows: [dict, ...] 每个 dict 的 key 需与 columns 中的 key 对应
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(1000, 560)
        self.columns = columns
        self.original_rows = rows

        layout = QVBoxLayout(self)
        hint = QLabel("请核对 AI 识别结果，可直接双击单元格修正内容，取消勾选可排除该行。")
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        self.table = QTableWidget(len(rows), len(columns) + 1)
        self.table.setHorizontalHeaderLabels(["选择"] + [c[1] for c in columns])
        self.table.setWordWrap(True)

        for r, row_data in enumerate(rows):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self.table.setCellWidget(r, 0, checkbox)
            for c, (key, _label) in enumerate(columns, start=1):
                self.table.setItem(r, c, QTableWidgetItem(_display(row_data.get(key, ""))))

        # 按内容自适应列宽后再设上下限：短字段（单位/数量）不再占用和品名一样的宽度
        header = self.table.horizontalHeader()
        self.table.resizeColumnsToContents()
        for c, (key, _label) in enumerate(columns, start=1):
            limit = WIDE_REVIEW_COLUMNS.get(key, 140)
            self.table.setColumnWidth(c, max(60, min(self.table.columnWidth(c), limit)))
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认导入勾选项")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_confirmed_rows(self) -> list:
        """返回勾选行，字段值取自表格当前内容（包含用户手动编辑的修正）"""
        result = []
        for r, original in enumerate(self.original_rows):
            checkbox = self.table.cellWidget(r, 0)
            if checkbox is None or not checkbox.isChecked():
                continue
            row_copy = dict(original)
            for c, (key, _label) in enumerate(self.columns, start=1):
                item = self.table.item(r, c)
                row_copy[key] = item.text() if item else ""
            result.append(row_copy)
        return result
