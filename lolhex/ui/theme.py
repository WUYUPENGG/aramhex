"""主界面的外观：Oil UI「海克斯精密仪」双主题（暖瓷白 / 墨石黑 / 跟随系统），Win10、Win11 渲染一致。

统一用 Qt 自带的 Fusion 打底，再用 token 驱动的样式表定颜色、圆角和间距，不依赖系统主题控件样式。

只管主窗口、对话框、托盘菜单和搜索下拉框：选择器都严格限定在 QMainWindow#main / QDialog / QMenu#tray / QListView#heroPopup，
游戏里的浮窗（overlay.py）有自己的深色绘制样式，这里一条都不能落到它身上。
"""

from __future__ import annotations

from importlib import resources

from PySide6.QtCore import Qt, QTranslator
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

# 有的 Win10（精简系统、英文系统）界面字体是宋体或没有中文的 Segoe UI，所以写死优先顺序
FONTS = (
    "Microsoft YaHei UI",
    "PingFang SC",
    "SF Pro Text",
    "Microsoft YaHei",
    "Microsoft JhengHei UI",
    "Segoe UI",
)

THEME_MODES = (
    ("system", "跟随系统"),
    ("light", "浅色（暖瓷白）"),
    ("dark", "深色（墨石黑）"),
)

# Oil UI「海克斯精密仪」双主题 Token（与 preview/index.html 严格对齐，所有文字对比度 ≥ 4.5:1）
THEMES: dict[str, dict[str, str]] = {
    "light": {
        "BG": "#F8F8F6",
        "RAIL": "#EFEFED",
        "CARD": "#FFFFFF",
        "SURFACE_HOVER": "#F2F3F0",
        "SURFACE_PRESSED": "#E6E8E4",
        "LINE": "#E2E3DF",
        "FIELD": "#CFD2CD",
        "FIELD_HOVER": "#9CA3AF",
        "TEXT": "#141518",
        "TEXT_2": "#3F444E",
        "MUTED": "#5A616E",
        "PLACEHOLDER": "#6B7280",
        "ACCENT": "#0060C7",
        "ACCENT_DARK": "#004B9E",
        "ACCENT_BG": "#E5EFFA",
        "ACCENT_INK": "#FFFFFF",
        "CHECK_BG": "#0060C7",
        "CHECK_BG_HOVER": "#004B9E",
        "GOOD": "#0E6830",
        "GOOD_BG": "#E6F4EB",
        "WARN": "#8F4200",
        "WARN_BG": "#FEF5E4",
        "WARN_BORDER": "#E6C27A",
        "BAD": "#C42525",
        "PRISM": "#7E22CE",
        "DISABLED_BG": "#F0F1EE",
        "DISABLED_TEXT": "#959CA8",
        "PRIMARY_DISABLED_BG": "#8DB6E2",
        "TRACK": "#E6E8E4",
        "TRACK_CHUNK": "#4CA3FF",
        "SCROLL": "#C8CCD2",
        "SCROLL_HOVER": "#A2A9B4",
        "TAB_HOVER": "#E7E8E4",
        "ITEM_HOVER": "#EEF2F7",
        "ITEM_SEL_BG": "#E2ECF9",
        "ITEM_SEL_TEXT": "#004B9E",
    },
    "dark": {
        "BG": "#0E1014",
        "RAIL": "#14171E",
        "CARD": "#181C24",
        "SURFACE_HOVER": "#202633",
        "SURFACE_PRESSED": "#272F3F",
        "LINE": "#252B36",
        "FIELD": "#343D4D",
        "FIELD_HOVER": "#4D596E",
        "TEXT": "#F3F4F6",
        "TEXT_2": "#C2C9D6",
        "MUTED": "#939DAC",
        "PLACEHOLDER": "#7D8798",
        "ACCENT": "#4CA3FF",
        "ACCENT_DARK": "#338CEB",
        "ACCENT_BG": "#1A2C44",
        "ACCENT_INK": "#071324",
        "CHECK_BG": "#1F75D8",
        "CHECK_BG_HOVER": "#3488E8",
        "GOOD": "#4ADE80",
        "GOOD_BG": "#142C1F",
        "WARN": "#FBBF24",
        "WARN_BG": "#2B2212",
        "WARN_BORDER": "#6E5018",
        "BAD": "#F87171",
        "PRISM": "#D8B4FE",
        "DISABLED_BG": "#141820",
        "DISABLED_TEXT": "#5F697B",
        "PRIMARY_DISABLED_BG": "#244266",
        "TRACK": "#1F2430",
        "TRACK_CHUNK": "#4CA3FF",
        "SCROLL": "#333B4B",
        "SCROLL_HOVER": "#4B566C",
        "TAB_HOVER": "#202633",
        "ITEM_HOVER": "#202838",
        "ITEM_SEL_BG": "#1B314E",
        "ITEM_SEL_TEXT": "#7EC0FF",
    },
}

_ACTIVE_MODE = "light"
_SYSTEM_SCHEME: Qt.ColorScheme | None = None

# 模块级颜色常量（随 apply() 同步到当前生效主题；初始为浅色默认，兼容旧引用）
BG = THEMES["light"]["BG"]
RAIL = THEMES["light"]["RAIL"]
CARD = THEMES["light"]["CARD"]
LINE = THEMES["light"]["LINE"]
FIELD = THEMES["light"]["FIELD"]
TEXT = THEMES["light"]["TEXT"]
TEXT_2 = THEMES["light"]["TEXT_2"]
MUTED = THEMES["light"]["MUTED"]
ACCENT = THEMES["light"]["ACCENT"]
ACCENT_DARK = THEMES["light"]["ACCENT_DARK"]
ACCENT_BG = THEMES["light"]["ACCENT_BG"]
GOOD = THEMES["light"]["GOOD"]
GOOD_BG = THEMES["light"]["GOOD_BG"]
WARN = THEMES["light"]["WARN"]
WARN_BG = THEMES["light"]["WARN_BG"]
BAD = THEMES["light"]["BAD"]
PRISM = THEMES["light"]["PRISM"]


def _sync_globals(mode: str) -> dict[str, str]:
    global _ACTIVE_MODE, BG, RAIL, CARD, LINE, FIELD, TEXT, TEXT_2, MUTED
    global ACCENT, ACCENT_DARK, ACCENT_BG, GOOD, GOOD_BG, WARN, WARN_BG, BAD, PRISM
    _ACTIVE_MODE = mode
    t = THEMES[mode]
    BG, RAIL, CARD, LINE, FIELD = t["BG"], t["RAIL"], t["CARD"], t["LINE"], t["FIELD"]
    TEXT, TEXT_2, MUTED = t["TEXT"], t["TEXT_2"], t["MUTED"]
    ACCENT, ACCENT_DARK, ACCENT_BG = t["ACCENT"], t["ACCENT_DARK"], t["ACCENT_BG"]
    GOOD, GOOD_BG, WARN, WARN_BG, BAD, PRISM = t["GOOD"], t["GOOD_BG"], t["WARN"], t["WARN_BG"], t["BAD"], t["PRISM"]
    return t


_QSS = """
QMainWindow#main, QDialog { background: %(BG)s; color: %(TEXT)s; }
QMainWindow#main QWidget, QDialog QWidget, QMenu#tray { font-family: %(FONTS)s; font-size: 13px; }
QMainWindow#main QWidget#page, QMainWindow#main QScrollArea, QMainWindow#main QWidget#qt_scrollarea_viewport { background: transparent; }
QMainWindow#main QLabel, QDialog QLabel, QMainWindow#main QCheckBox { color: %(TEXT)s; background: transparent; }
QMainWindow#main QLabel[muted="true"] { color: %(MUTED)s; }
QMainWindow#main QLabel[secondary="true"] { color: %(TEXT_2)s; }
QMainWindow#main QLabel[badge="accent"] { background: %(ACCENT_BG)s; color: %(ACCENT)s; border-radius: 9px; padding: 2px 9px; font-size: 12px; font-weight: 600; }
QMainWindow#main QLabel[badge="good"] { background: %(GOOD_BG)s; color: %(GOOD)s; border-radius: 9px; padding: 2px 9px; font-size: 12px; font-weight: 600; }
QMainWindow#main QLabel[badge="warn"] { background: %(WARN_BG)s; color: %(WARN)s; border-radius: 9px; padding: 2px 9px; font-size: 12px; font-weight: 600; }

QMainWindow#main QFrame#card { background: %(CARD)s; border: 1px solid %(LINE)s; border-radius: 12px; }
QMainWindow#main QFrame#card[best="true"] { background: %(CARD)s; border: 1px solid %(GOOD)s; border-radius: 12px; }
QMainWindow#main QFrame#rail { background: %(RAIL)s; border-right: 1px solid %(LINE)s; border-top: none; border-bottom: none; border-left: none; border-radius: 0px; }
QMainWindow#main QFrame#railSep { background: %(LINE)s; border: none; max-height: 1px; }
QMainWindow#main QFrame#workspaceCard { background: %(CARD)s; border: 1px solid %(LINE)s; border-radius: 12px; }
QMainWindow#main QFrame#footer { background: %(RAIL)s; border: 1px solid %(LINE)s; border-radius: 10px; }
QMainWindow#main QFrame#notice { background: %(WARN_BG)s; border: 1px solid %(WARN_BORDER)s; border-radius: 12px; }

QMainWindow#main QPushButton[nav="true"] {
    background: transparent; color: %(TEXT_2)s; border: none; border-radius: 9px;
    padding: 8px 12px; text-align: left; font-size: 13.5px; font-weight: 500; min-height: 20px; }
QMainWindow#main QPushButton[nav="true"]:hover {
    background: %(TAB_HOVER)s; color: %(TEXT)s; border: none; }
QMainWindow#main QPushButton[nav="true"][active="true"] {
    background: %(ACCENT_BG)s; color: %(ACCENT)s; font-weight: 600; border: none; }
QMainWindow#main QPushButton[nav="true"][active="true"]:hover {
    background: %(ACCENT_BG)s; color: %(ACCENT)s; border: none; }

QMainWindow#main QPushButton, QDialog QPushButton {
    background: %(CARD)s; color: %(TEXT)s; border: 1px solid %(FIELD)s; border-radius: 8px; padding: 4px 14px; min-height: 18px; }
QMainWindow#main QPushButton:hover, QDialog QPushButton:hover {
    background: %(SURFACE_HOVER)s; border-color: %(ACCENT)s; color: %(ACCENT)s; }
QMainWindow#main QPushButton:pressed, QDialog QPushButton:pressed { background: %(SURFACE_PRESSED)s; }
QMainWindow#main QPushButton:focus, QDialog QPushButton:focus { border-color: %(ACCENT)s; }
QMainWindow#main QPushButton:disabled, QDialog QPushButton:disabled {
    background: %(DISABLED_BG)s; color: %(DISABLED_TEXT)s; border-color: %(LINE)s; }
QMainWindow#main QPushButton[ghost="true"] {
    background: transparent; border-color: transparent; color: %(TEXT_2)s; padding: 4px 10px; }
QMainWindow#main QPushButton[ghost="true"]:hover {
    background: %(SURFACE_HOVER)s; border-color: transparent; color: %(TEXT)s; }
QMainWindow#main QPushButton[pill="true"] {
    background: %(RAIL)s; border: 1px solid %(LINE)s; border-radius: 8px; padding: 3px 10px; color: %(TEXT)s; }
QMainWindow#main QPushButton[pill="true"]:hover {
    background: %(ACCENT_BG)s; border-color: %(ACCENT)s; color: %(ACCENT)s; }
QMainWindow#main QPushButton[primary="true"], QDialog QPushButton:default {
    background: %(ACCENT)s; color: %(ACCENT_INK)s; border-color: %(ACCENT)s; font-weight: 600; }
QMainWindow#main QPushButton[primary="true"]:hover, QDialog QPushButton:default:hover {
    background: %(ACCENT_DARK)s; border-color: %(ACCENT_DARK)s; color: %(ACCENT_INK)s; }
QMainWindow#main QPushButton[primary="true"]:disabled {
    background: %(PRIMARY_DISABLED_BG)s; border-color: %(PRIMARY_DISABLED_BG)s; color: %(ACCENT_INK)s; }
QDialog QPushButton { min-width: 64px; }

QMainWindow#main QLineEdit, QMainWindow#main QComboBox, QDialog QLineEdit {
    background: %(CARD)s; color: %(TEXT)s; border: 1px solid %(FIELD)s; border-radius: 8px; padding: 3px 10px; min-height: 20px;
    selection-background-color: %(ACCENT)s; selection-color: %(ACCENT_INK)s; }
QMainWindow#main QLineEdit:hover, QMainWindow#main QComboBox:hover { border-color: %(FIELD_HOVER)s; }
QMainWindow#main QLineEdit:focus, QMainWindow#main QComboBox:focus, QMainWindow#main QComboBox:on, QDialog QLineEdit:focus {
    border-color: %(ACCENT)s; }
QMainWindow#main QLineEdit:disabled, QMainWindow#main QComboBox:disabled {
    background: %(DISABLED_BG)s; color: %(DISABLED_TEXT)s; }
QMainWindow#main QKeySequenceEdit { background: transparent; border: none; }
QMainWindow#main QComboBox { padding-right: 26px; combobox-popup: 0; }
QMainWindow#main QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: center right; width: 26px; border: none; }
QMainWindow#main QComboBox::down-arrow { image: url("%(CHEVRON)s"); width: 12px; height: 12px; }
QMainWindow#main QComboBox QAbstractItemView, QListView#heroPopup {
    background: %(CARD)s; color: %(TEXT)s; border: 1px solid %(FIELD)s; border-radius: 8px; padding: 4px; outline: none;
    font-family: %(FONTS)s; font-size: 13px; }
QMainWindow#main QComboBox QAbstractItemView::item, QListView#heroPopup::item {
    min-height: 26px; padding: 0 8px; border-radius: 5px; color: %(TEXT)s; }
QMainWindow#main QComboBox QAbstractItemView::item:hover, QListView#heroPopup::item:hover { background: %(ITEM_HOVER)s; }
QMainWindow#main QComboBox QAbstractItemView::item:selected, QListView#heroPopup::item:selected {
    background: %(ITEM_SEL_BG)s; color: %(ITEM_SEL_TEXT)s; }

QMainWindow#main QCheckBox { spacing: 8px; }
QMainWindow#main QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid %(FIELD_HOVER)s; border-radius: 4px; background: %(CARD)s; }
QMainWindow#main QCheckBox::indicator:hover { border-color: %(ACCENT)s; }
QMainWindow#main QCheckBox::indicator:checked {
    background: %(CHECK_BG)s; border-color: %(CHECK_BG)s; image: url("%(CHECK)s"); }
QMainWindow#main QCheckBox::indicator:checked:hover { background: %(CHECK_BG_HOVER)s; border-color: %(CHECK_BG_HOVER)s; }
QMainWindow#main QCheckBox::indicator:disabled { background: %(DISABLED_BG)s; border-color: %(LINE)s; }

QMainWindow#main QTabWidget::pane {
    border: 1px solid %(LINE)s; border-radius: 12px; background: %(CARD)s; top: 6px; margin-bottom: 6px; }
QMainWindow#main QTabWidget::tab-bar { left: 2px; }
QMainWindow#main QTabBar { background: transparent; qproperty-drawBase: 0; }
QMainWindow#main QTabBar::tab {
    background: transparent; color: %(MUTED)s; border: none; border-radius: 8px; padding: 6px 16px; margin-right: 4px; min-height: 18px; }
QMainWindow#main QTabBar::tab:hover { background: %(TAB_HOVER)s; color: %(TEXT)s; }
QMainWindow#main QTabBar::tab:selected { background: %(ACCENT)s; color: %(ACCENT_INK)s; font-weight: 600; }
QMainWindow#main QTabBar::tab:focus { border: 1px solid %(ACCENT_DARK)s; }

QMainWindow#main QProgressBar {
    background: %(TRACK)s; border: none; border-radius: 9px; color: %(TEXT)s; text-align: center; font-size: 12px; }
QMainWindow#main QProgressBar::chunk { background: %(TRACK_CHUNK)s; border-radius: 9px; }

QMainWindow#main QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QMainWindow#main QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QMainWindow#main QScrollBar::handle { background: %(SCROLL)s; border-radius: 3px; }
QMainWindow#main QScrollBar::handle:vertical { min-height: 28px; }
QMainWindow#main QScrollBar::handle:horizontal { min-width: 28px; }
QMainWindow#main QScrollBar::handle:hover { background: %(SCROLL_HOVER)s; }
QMainWindow#main QScrollBar::add-line, QMainWindow#main QScrollBar::sub-line { width: 0; height: 0; }
QMainWindow#main QScrollBar::add-page, QMainWindow#main QScrollBar::sub-page { background: transparent; }

QMainWindow#main QAbstractScrollArea::corner { background: transparent; }

QMenu#tray { background: %(CARD)s; color: %(TEXT)s; border: 1px solid %(FIELD)s; border-radius: 8px; padding: 5px; }
QMenu#tray::item { padding: 7px 26px 7px 30px; border-radius: 5px; }
QMenu#tray::item:selected { background: %(ITEM_SEL_BG)s; color: %(ITEM_SEL_TEXT)s; }
QMenu#tray::separator { height: 1px; background: %(LINE)s; margin: 5px 8px; }
QMenu#tray::indicator { width: 14px; height: 14px; left: 9px; border: 1px solid %(FIELD_HOVER)s; border-radius: 3px; background: %(CARD)s; }
QMenu#tray::indicator:checked { background: %(CHECK_BG)s; border-color: %(CHECK_BG)s; image: url("%(CHECK)s"); }
"""


def asset(name: str) -> str:
    return str(resources.files("lolhex.ui").joinpath(name)).replace("\\", "/")


def current_mode() -> str:
    """当前生效的外观模式（"light" 或 "dark"）。"""
    return _ACTIVE_MODE


def resolve_mode(mode: str | None = None, app: QApplication | None = None) -> str:
    """将 system / light / dark 解析为最终生效的 "light" 或 "dark"。"""
    if mode in THEMES:
        return mode
    if mode == "system":
        app = app or QApplication.instance()
        scheme = _SYSTEM_SCHEME
        if app is not None and hasattr(app, "styleHints"):
            hints = app.styleHints()
            if scheme is None:
                scheme = hints.colorScheme()
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"
    return _ACTIVE_MODE if mode is None else "light"


def tokens(mode: str | None = None, app: QApplication | None = None) -> dict[str, str]:
    """返回指定模式（默认当前生效模式）的完整颜色字典。"""
    return dict(THEMES[resolve_mode(mode, app)])


def stylesheet(mode: str | None = None, app: QApplication | None = None) -> str:
    t = THEMES[resolve_mode(mode, app)]
    return _QSS % {
        **t,
        "FONTS": ", ".join(f'"{f}"' for f in FONTS),
        "CHECK": asset("check.png"),
        "CHEVRON": asset("chevron.png"),
    }


def palette(mode: str | None = None, app: QApplication | None = None) -> QPalette:
    """样式表没管到的地方（链接、选中文字、占位字）也用同一套颜色，不跟系统的强调色走。"""
    t = THEMES[resolve_mode(mode, app)]
    p = QStyleFactory.create("Fusion").standardPalette()
    for role, color in (
        (QPalette.Window, t["BG"]),
        (QPalette.Base, t["CARD"]),
        (QPalette.AlternateBase, t["RAIL"]),
        (QPalette.Button, t["CARD"]),
        (QPalette.WindowText, t["TEXT"]),
        (QPalette.Text, t["TEXT"]),
        (QPalette.ButtonText, t["TEXT"]),
        (QPalette.ToolTipBase, t["CARD"]),
        (QPalette.ToolTipText, t["TEXT"]),
        (QPalette.Highlight, t["ACCENT"]),
        (QPalette.HighlightedText, t["ACCENT_INK"]),
        (QPalette.Accent, t["ACCENT"]),
        (QPalette.Link, t["ACCENT"]),
        (QPalette.LinkVisited, t["ACCENT"]),
        (QPalette.PlaceholderText, t["PLACEHOLDER"]),
    ):
        p.setColor(role, QColor(color))
    return p


# 安装包不带 Qt 的翻译文件：对话框按钮、输入框右键菜单本来是英文
_ZH = {"OK": "确定", "&OK": "确定", "Cancel": "取消", "&Cancel": "取消", "&Yes": "是", "&No": "否", "Close": "关闭", "&Close": "关闭",
       "&Undo": "撤销", "&Redo": "重做", "Cu&t": "剪切", "&Copy": "复制", "&Paste": "粘贴", "Delete": "删除", "Select All": "全选",
       "Copy &Link Location": "复制链接地址"}
_ZH_CONTEXTS = {"QPlatformTheme", "QDialogButtonBox", "QLineEdit", "QWidgetTextControl"}


class _Zh(QTranslator):
    def isEmpty(self) -> bool:
        return False

    def translate(self, context, text, disambiguation=None, n=-1):
        return _ZH.get(text) if context in _ZH_CONTEXTS else None


def apply(app: QApplication, mode: str | None = None) -> str:
    """应用外观主题；启动时或切换主题时均可调用，返回实际生效的 "light" 或 "dark"。"""
    global _SYSTEM_SCHEME
    if _SYSTEM_SCHEME is None and hasattr(app, "styleHints"):
        _SYSTEM_SCHEME = app.styleHints().colorScheme()
    eff = resolve_mode("light" if mode is None else mode, app)
    _sync_globals(eff)
    if hasattr(app, "styleHints"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if eff == "dark" else Qt.ColorScheme.Light)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(palette(eff, app))
    app.setStyleSheet(stylesheet(eff, app))
    old_zh = getattr(app, "_zh", None)
    if old_zh is not None:
        app.removeTranslator(old_zh)
    zh = _Zh(app)
    app.installTranslator(zh)
    app._zh = zh  # 保持引用
    return eff


def mark(widget: QWidget, **props) -> QWidget:
    """设样式表用的属性（primary、muted、ghost、pill、best 等），返回控件本身。"""
    for name, value in props.items():
        widget.setProperty(name, value)
    return widget
