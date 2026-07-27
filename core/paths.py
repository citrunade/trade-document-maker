"""
路径管理模块
统一处理开发环境与 PyInstaller 打包后 EXE 的路径问题。
所有数据/资源路径必须通过本模块获取，禁止在其他地方硬编码路径。
"""
import os
import sys


def get_app_root() -> str:
    """
    获取程序根目录。
    - 开发环境下：返回项目根目录（本文件的上一级）
    - 打包为 EXE 后：返回 exe 所在目录（不是 PyInstaller 的临时解压目录 _MEIPASS），
      这样 data/ 目录才能持久化保存在用户看到的 exe 旁边。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后运行
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_dir() -> str:
    """获取 data/ 目录路径，如不存在则自动创建。"""
    path = os.path.join(get_app_root(), "data")
    os.makedirs(path, exist_ok=True)
    return path


def check_data_dir_writable() -> bool:
    """
    实际写入一个探测文件以确认 data/ 目录真正可写。
    背景：若 EXE 被放在「C:\\Program Files」等受保护目录下，Windows 可能会
    将写入操作悄悄重定向到 VirtualStore，导致程序看似保存成功，
    但下次读取（或换一个用户登录）时数据却不存在——现象类似"保存的内容消失了"。
    在启动时提前探测，比让用户遇到诡异的"数据丢失"更容易定位问题。
    """
    path = os.path.join(get_data_dir(), ".write_test")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(path)
        return True
    except OSError:
        return False


def get_data_path(*parts: str) -> str:
    """获取 data/ 目录下某个文件/子路径的完整路径。"""
    return os.path.join(get_data_dir(), *parts)


def get_docs_dir() -> str:
    """获取历史单据存储目录 data/documents/"""
    path = os.path.join(get_data_dir(), "documents")
    os.makedirs(path, exist_ok=True)
    return path


def get_exports_dir() -> str:
    """获取 PDF 导出目录 data/exports/"""
    path = os.path.join(get_data_dir(), "exports")
    os.makedirs(path, exist_ok=True)
    return path


def get_backups_dir() -> str:
    """获取备份目录 data/backups/"""
    path = os.path.join(get_data_dir(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def get_bundled_resource_path(*parts: str) -> str:
    """
    获取程序自带的静态资源（如内置字体文件等）路径。
    开发环境读取项目 assets/ 目录；打包后从 PyInstaller 的 _MEIPASS 临时目录读取
    （通过 --add-data 打包进 EXE 的只读资源）。
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "assets", *parts)
    return os.path.join(base, "assets", *parts)


def get_windows_font_path(filename: str) -> str:
    """
    获取 Windows 系统字体路径（如 msyh.ttc / simsun.ttc）。
    用于 PDF 中文渲染，避免乱码。
    """
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "Fonts", filename)
