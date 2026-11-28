"""主窗口后台工作线程与通用界面辅助（从 mainwindow.py 拆分）。

包含：
- RankWorker：后台查分线程；
- UpdateWorker：后台检查/下载/增量更新线程；
- hard_exit_later / quit_app：安全退出与兜底强退；
- show_progress / about_html：进度条与关于链接格式化。
"""

from __future__ import annotations

import logging
import os
import threading
from html import escape

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QProgressBar

from .. import DATA_HOMEPAGE, HOMEPAGE, __version__, cloud, official, patch, rank, update
from ..config import is_portable
from . import theme

QUIT_TIMEOUT_S = 3.0


def show_progress(bar: QProgressBar, label: str, done: int | None = None, total: int | None = None) -> None:
    """进度条上写"<在做什么> 已下载 / 总共 MB"；不知道总量时只写文字。"""
    if total:
        bar.setRange(0, 1000)
        bar.setValue(int(1000 * min(done or 0, total) / total))
        bar.setFormat(f"{label} {(done or 0) / 1e6:.1f} / {total / 1e6:.1f} MB")
    else:
        bar.setRange(0, 1)
        bar.setValue(0)
        bar.setFormat(label)
    bar.show()


def hard_exit_later(seconds: float = 5.0, reason: str = "退出超时，强制结束以便更新") -> None:
    """更新要替换文件：正常退出卡住（后台线程、网络请求没结束）时，几秒后强制结束本进程。
    1.0.9 之前出现过：旧助手没退出，文件被占用，更新被还原。"""
    def go():
        logging.getLogger(__name__).warning(reason)
        logging.shutdown()
        os._exit(0)
    t = threading.Timer(seconds, go)
    t.daemon = True
    t.start()


def quit_app(engine, *, hard_exit=None) -> None:
    """托盘「退出」和浮窗「退出」：停后台线程、结束事件循环；几秒内没退干净就强制结束进程。"""
    logging.getLogger(__name__).info("退出")
    app = QApplication.instance()
    if app is not None:
        app.setProperty("quitting", True)  # 主窗口的关闭不再改成缩到托盘
    engine.stop()
    (hard_exit or hard_exit_later)(QUIT_TIMEOUT_S, "退出超时，强制结束")
    QApplication.exit(0)


def about_html() -> str:
    style = f"color:{theme.ACCENT};text-decoration:none"
    links = [f"<a style='{style}' href='{cloud.site()}'>官网</a>"] if official.available() else []
    links += [f"<a style='{style}' href='{HOMEPAGE}'>GitHub</a>", f"<a style='{style}' href='{DATA_HOMEPAGE}'>统计数据</a>"]
    for c in cloud.community():  # 云控：QQ 群、B 站、赞助……
        label = escape(c["name"] + (" " + c["text"] if c.get("text") else ""))
        links.append(f"<a style='{style}' href='{escape(c['url'])}'>{label}</a>" if c.get("url") else label)
    return (f"<b>AramHex 海克斯大乱斗助手</b> {__version__}{'（便携版）' if is_portable() else ''}<br>" + " · ".join(links))


class RankWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, riot_id: str, parent=None):
        super().__init__(parent)
        self.riot_id = riot_id

    def run(self):
        try:
            self.done.emit(rank.lookup(self.riot_id))
        except rank.RankError as e:
            self.failed.emit(str(e))
        except Exception as e:
            logging.getLogger(__name__).warning("查分出错：%s", e)
            self.failed.emit("查询出错，请稍后再试")


class UpdateWorker(QThread):
    """后台线程：mode=check 查有没有新版本（手动检查时先同步统计数据，结果发 data_done）；
    mode=download 先试增量更新（只下变了的文件，官网优先），不行再从 GitHub 下完整安装包；
    增量失败、安装包下不了或太慢、便携版要整包，都发 manual（原因, 网盘链接）让用户去网盘下载。
    strict=True（手动检查）时连不上会发 failed，没有新版本发 uptodate。"""
    found = Signal(dict)
    uptodate = Signal()
    progress = Signal(int, int)
    ready = Signal(str)
    patched = Signal(list, list)
    phase = Signal(str)  # 当前在做什么（检查更新文件 / 比对本机文件 / 下载更新 / 下载安装包）
    failed = Signal(str)
    data_done = Signal(str)
    manual = Signal(str, dict)
    cloud = Signal(dict)

    def __init__(self, mode: str, info: dict | None = None, parent=None, strict: bool = False, data_sync=None):
        super().__init__(parent)
        self.mode, self.info, self.strict, self.data_sync = mode, info, strict, data_sync

    def run(self):
        try:
            if self.mode == "check":
                self.cloud.emit(cloud.refresh())
                if self.data_sync:
                    try:
                        self.data_done.emit(self.data_sync())
                    except Exception as e:
                        logging.getLogger(__name__).warning("手动同步统计数据失败：%s", e)
                        self.data_done.emit("统计数据这次没连上，稍后会自动再试。")
                info = update.check(__version__, strict=self.strict)
                if info:
                    self.found.emit(info)
                else:
                    self.uptodate.emit()
            else:
                log = logging.getLogger(__name__)
                try:
                    changed, stale = patch.prepare(self.info["version"], self.progress.emit, phase=self.phase.emit)
                    self.patched.emit(changed, stale)
                    return
                except patch.NotWritable as e:
                    log.info("软件所在的文件夹不能写入：%s", e)
                    self.manual.emit("软件所在的文件夹不能写入（比如装在 Program Files），这次需要手动下载安装。",
                                     update.pan_links())
                    return
                except patch.NeedFullInstall as e:
                    log.info("要整包更新：%s", e)
                    reason = str(e) if isinstance(e, patch.IncompleteRollback) else "这次更新需要重新下载安装包。"
                except Exception as e:
                    log.warning("增量更新失败：%s", e)
                    self.manual.emit("更新文件下载失败。", update.pan_links())
                    return
                if not self.info.get("url") or is_portable():
                    self.manual.emit(reason, update.pan_links())
                    return
                self.phase.emit("从 GitHub 下载安装包…")
                try:
                    self.ready.emit(str(update.download(self.info, self.progress.emit)))
                except update.SlowDownload as e:
                    log.info("GitHub %s", e)
                    self.manual.emit("从 GitHub 下载太慢。", update.pan_links())
                except Exception as e:
                    log.warning("从 GitHub 下载安装包失败：%s", e)
                    self.manual.emit("从 GitHub 下载安装包失败。", update.pan_links())
        except Exception as e:  # 更新失败不能影响助手本身
            self.failed.emit(str(e))
