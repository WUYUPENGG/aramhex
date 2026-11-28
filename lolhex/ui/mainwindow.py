"""主界面与系统托盘。

- 主窗口：数据状态、当前英雄（识别结果/候选/搜索手动选）、英雄评级与出装加点、当前三选一推荐、设置。
- 关闭主窗口只是隐藏到托盘；退出要在托盘菜单里点「退出」。
- 托盘：双击打开主界面；右键菜单。
"""

from __future__ import annotations

import logging
import os
import random
import threading
import webbrowser
from html import escape
from importlib import resources

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QScrollArea,
                               QPushButton, QSizePolicy, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__, cloud, cloudsettings, i18n, logupload, official, patch, rank, recommend, update
from ..config import is_portable
from ..data.public import BANDS, norm_band
from . import autostart, buildview, theme, workers as _workers
from .badgepos import POSITIONS as BADGE_POSITIONS, BadgePosPreview
from .data_status import data_status_html
from .herosearch import hero_completer
from .workers import QUIT_TIMEOUT_S, RankWorker, UpdateWorker, about_html, hard_exit_later, show_progress

RARITY_CN = {"silver": "白银", "gold": "黄金", "prismatic": "棱彩"}
# 云控强制设置时提示用的名字
SETTING_NAMES = {"idle_ocr_guard": "空闲时减少识别开销", "overlay_on_demand": "对局中按需显示浮窗按钮", "show_winrate": "显示胜率数字", "overlay": "显示游戏内浮窗", "overlay_corner": "浮窗位置",
                 "badge_position": "三选一标签", "speed": "识别频率",
                 "check_data_updates": "自动获取最新海克斯数据", "game_lang": "游戏语言", "data_band": "参考分数段"}
VERDICT_CN = {"best": ("首选", "#2e9d5b"), "ok": ("可选", "#3b7dd8"), "reroll": ("可考虑刷新", "#d0533f"),
              "unknown": ("未知", "#888"), "nodata": ("无数据", "#888")}
PHASE_CN = {None: "未检测到英雄联盟", "client": "客户端（选英雄界面会自动识别英雄）", "ingame": "对局中"}
VISION_CN = {"idle": "待机", "paused": "游戏不在前台，暂停", "scanning": "扫描中"}
SAVED_TEXT = "<span style='color:#2e9d5b'>已保存</span>"


def _verdict_info(verdict: str) -> tuple[str, str]:
    """按当前生效主题（深色/浅色）返回三选一结论文字与高对比色。"""
    label = VERDICT_CN.get(verdict, VERDICT_CN["unknown"])[0]
    colors = {"best": theme.GOOD, "ok": theme.ACCENT, "reroll": theme.BAD,
              "unknown": theme.MUTED, "nodata": theme.MUTED}
    return label, colors.get(verdict, theme.MUTED)


def _saved_html() -> str:
    return f"<span style='color:{theme.GOOD}'>已保存</span>"


def app_icon() -> QIcon:
    data = resources.files("lolhex.ui").joinpath("icon.png").read_bytes()
    pm = QPixmap()
    pm.loadFromData(data)
    return QIcon(pm)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _set_checked_quietly(widget, on: bool) -> None:
    """改勾选状态但不触发 toggled（两处「开机自动启动」互相同步时用）。"""
    old = widget.blockSignals(True)
    widget.setChecked(on)
    widget.blockSignals(old)


def _progress_bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setTextVisible(True)
    bar.setMaximumHeight(18)
    bar.hide()
    return bar


def _card(name: str = "card") -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


def _page() -> QWidget:
    """透明底的容器页：底色由外面的窗口或标签页决定。"""
    w = QWidget()
    w.setObjectName("page")
    return w


def _card_layout(card: QFrame) -> QVBoxLayout:
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(6)
    return lay


def quit_app(engine) -> None:
    """托盘「退出」和浮窗「退出」：转调 workers.quit_app，并保留本模块 hard_exit_later 便于测试拦截。"""
    _workers.quit_app(engine, hard_exit=hard_exit_later)


BAND_CHOICES = [("", "全体")] + [(c, BANDS[c]) for c in BANDS]
NAV_LABELS = ("出装与加点", "海克斯选择", "设置")


class _NavStack(QStackedWidget):
    """右侧页面栈：对外保持与 QTabWidget 相同的 setCurrentIndex / widget / count 接口，同时同步左侧导航高亮。"""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self.currentChanged.connect(self._on_change)

    def addTab(self, widget: QWidget, _label: str = "") -> int:
        return self.addWidget(widget)


class MainWindow(QMainWindow):
    def __init__(self, engine, overlay):
        super().__init__()
        self.engine = engine
        self.overlay = overlay
        self._names: dict[str, str] = {}
        self._cand_ids: list = []
        self._panel_hero = None
        self._hint_shown = False
        self._compact = False
        self.setObjectName("main")  # 样式表（theme.py）只认它里面的控件，不影响浮窗
        self.setWindowTitle(f"海克斯大乱斗助手 v{__version__}")
        self.setWindowIcon(app_icon())
        self.resize(860, 740)
        self.setMinimumSize(360, 260)

        root = _page()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # ---- 左侧导航栏（Oil UI Navigation Rail）----
        self._rail = _card("rail")
        self._rail.setFixedWidth(182)
        rail_lay = QVBoxLayout(self._rail)
        rail_lay.setContentsMargins(12, 16, 12, 14)
        rail_lay.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        logo = self._logo = QLabel()
        logo.setPixmap(app_icon().pixmap(30, 30))
        self._title_label = QLabel()
        self._title_label.setTextFormat(Qt.RichText)
        brand_row.addWidget(logo, 0, Qt.AlignTop)
        brand_row.addWidget(self._title_label, 1)
        rail_lay.addLayout(brand_row)
        rail_lay.addSpacing(4)

        self._nav_buttons: list[QPushButton] = []
        for idx, text in enumerate(NAV_LABELS):
            btn = theme.mark(QPushButton(text), nav=True, active=(idx == 0))
            btn.clicked.connect(lambda _=False, i=idx: self.tabs.setCurrentIndex(i))
            rail_lay.addWidget(btn)
            self._nav_buttons.append(btn)

        rail_lay.addStretch(1)
        sep = _card("railSep")
        sep.setFixedHeight(1)
        rail_lay.addWidget(sep)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        rail_lay.addWidget(self.status)
        self.data_progress = _progress_bar()  # 下载统计数据时显示
        rail_lay.addWidget(self.data_progress)
        shell.addWidget(self._rail)

        # ---- 右侧主工作区 ----
        ws = _page()
        lay = QVBoxLayout(ws)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(10)
        shell.addWidget(ws, 1)

        # 顶部工具条
        head = QHBoxLayout()
        head.setSpacing(8)
        self._section_title = QLabel(f"<b style='font-size:15px'>{NAV_LABELS[0]}</b>")
        self._section_title.setTextFormat(Qt.RichText)
        head.addWidget(self._section_title, 1)
        self.btn_comm = theme.mark(QPushButton(), pill=True)  # 云控里标了 primary 的社区入口（比如 QQ 群），没有就不显示
        self.btn_comm.clicked.connect(self._open_primary)
        self.btn_comm.hide()
        head.addWidget(self.btn_comm)
        self.btn_theme = theme.mark(QPushButton(), ghost=True)
        self.btn_theme.setToolTip("在浅色（暖瓷白）与深色（墨石黑）之间切换")
        self.btn_theme.clicked.connect(self._toggle_theme)
        head.addWidget(self.btn_theme)
        self.btn_dash = theme.mark(QPushButton("帮助"), ghost=True)
        self.btn_dash.clicked.connect(lambda: webbrowser.open(cloud.help_page()))
        head.addWidget(self.btn_dash)
        self._show_primary()
        lay.addLayout(head)

        # 有新版本时才显示
        self.update_bar = _card("notice")
        ubv = _card_layout(self.update_bar)
        ub = QHBoxLayout()
        ubv.addLayout(ub)
        self.update_text = QLabel()
        self.update_text.setWordWrap(True)
        self.btn_update = theme.mark(QPushButton("立即更新"), primary=True)
        self.btn_update.clicked.connect(self._start_update)
        ub.addWidget(self.update_text, 1)
        ub.addWidget(self.btn_update)
        self.update_progress = _progress_bar()  # 更新时显示：在做什么、下了多少
        ubv.addWidget(self.update_progress)
        self.update_bar.hide()
        lay.addWidget(self.update_bar)
        self._update_info = None
        self._worker = None
        # 助手常驻托盘，可能好几天不重启：平时也定时查更新
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self.check_update)
        self._update_timer.start(self._check_interval_ms())
        # 提示和弹窗都不在对局中出现（会抢游戏的焦点）：对局中先攒着，回到游戏外再出
        self._deferred_cloud: dict | None = None
        self._popup_open = False  # 有提醒类弹窗开着（不叠第二个）
        self._deferred_toast: str | None = None
        self._shown_note = None
        self._asked_offers: set = set()
        self._notify_timer = QTimer(self)
        self._notify_timer.timeout.connect(self._notify_tick)
        self._notify_timer.start(3000)

        # 英雄锚点区（全页共享：英雄评级/胜率、选人队友 ID、快速搜索与分段切换）
        hc = _card()
        hl = _card_layout(hc)
        self.hero_label = QLabel()
        self.hero_label.setTextFormat(Qt.RichText)
        hl.addWidget(self.hero_label)
        self.cs_label = QLabel()  # 选人界面：待选栏按胜率排序的汇总
        self.cs_label.setTextFormat(Qt.RichText)
        self.cs_label.setWordWrap(True)
        self.cs_label.hide()
        hl.addWidget(self.cs_label)
        # 选人界面队友 ID 可编辑复制栏（仅识别到队友时显示，默认隐藏不影响布局高度）
        self.teammate_bar = QWidget()
        tml = QHBoxLayout(self.teammate_bar)
        tml.setContentsMargins(0, 0, 0, 0)
        tml.setSpacing(6)
        self.teammate_edit = QLineEdit()
        self.teammate_edit.setPlaceholderText("队友 ID（逗号或换行分隔，可微调错字后复制）")
        self._last_mates_key: tuple[str, ...] = ()
        self.btn_copy_mates = theme.mark(QPushButton("复制ID"), pill=True)
        self.btn_copy_mates.clicked.connect(self._copy_teammates_clicked)
        self.btn_rescan_mates = theme.mark(QPushButton("重扫"), ghost=True)
        self.btn_rescan_mates.clicked.connect(self.engine.rescan_teammates)
        tml.addWidget(self.teammate_edit, 1)
        tml.addWidget(self.btn_copy_mates)
        tml.addWidget(self.btn_rescan_mates)
        self.teammate_bar.hide()
        hl.addWidget(self.teammate_bar)
        self.cands = QHBoxLayout()
        hl.addLayout(self.cands)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索英雄（Ctrl+K，支持拼音与别名）")
        self.search.returnPressed.connect(self._search_pick)
        self._shortcut_search = QShortcut(QKeySequence("Ctrl+K"), self)
        self._shortcut_search.activated.connect(self._focus_search)
        btn_clear = theme.mark(QPushButton("清除"), ghost=True)
        btn_clear.clicked.connect(lambda: self.engine.set_hero(None))
        row.addWidget(self.search, 1)
        row.addWidget(btn_clear)
        # 分段和搜索放一行：设置页要在默认窗口里一屏放下
        row.addSpacing(8)
        row.addWidget(QLabel("分段"))
        self.band_box = QComboBox()
        for code, label in BAND_CHOICES:
            self.band_box.addItem(label, code)
        self.band_box.setCurrentIndex(max(0, self.band_box.findData(engine.settings.data_band or "")))
        self.band_box.currentIndexChanged.connect(lambda i: self.engine.set_band(self.band_box.itemData(i) or None))
        row.addWidget(self.band_box)
        hl.addLayout(row)
        self.my_rank_label = theme.mark(QLabel(), muted=True)
        self.my_rank_label.hide()  # 查过分才有这一行
        hl.addWidget(self.my_rank_label)
        lay.addWidget(hc)

        # 主工作区页面栈（由左侧导航栏切换，保持 self.tabs 接口向后兼容）
        ws_card = _card("workspaceCard")
        ws_card_lay = QVBoxLayout(ws_card)
        ws_card_lay.setContentsMargins(0, 0, 0, 0)
        ws_card_lay.setSpacing(0)
        self.tabs = _NavStack(self._on_nav_changed)
        ws_card_lay.addWidget(self.tabs)
        self.tab_hero = QLabel()
        self.tab_hero.setTextFormat(Qt.RichText)
        self.tab_hero.setWordWrap(True)
        self.tab_hero.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.tab_hero.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # 未选英雄时的快捷英雄入口（热门/高胜率英雄一键预览出装与海克斯）
        self.quick_heroes_box = QWidget()
        qh_outer = QVBoxLayout(self.quick_heroes_box)
        qh_outer.setContentsMargins(0, 8, 0, 0)
        qh_outer.setSpacing(8)
        self._quick_heroes_title = theme.mark(QLabel("快捷查看热门英雄出装（或按 Ctrl+K 搜索任意英雄）"), muted=True)
        qh_outer.addWidget(self._quick_heroes_title)
        self._quick_heroes_grid = QGridLayout()
        self._quick_heroes_grid.setSpacing(8)
        qh_outer.addLayout(self._quick_heroes_grid)
        self._quick_heroes_loaded = False
        w1 = _page()
        l1 = QVBoxLayout(w1)
        l1.setContentsMargins(16, 14, 16, 14)
        l1.addWidget(self.tab_hero)
        l1.addWidget(self.quick_heroes_box)
        l1.addStretch(1)
        # 出装、加点很长：放进滚动区，不然页面按最高的一页定高度，选了英雄后设置页的「检查更新」被挤出窗口
        w1_scroll = QScrollArea()
        w1_scroll.setWidget(w1)
        w1_scroll.setWidgetResizable(True)
        w1_scroll.setFrameShape(QFrame.NoFrame)
        w1_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.tabs.addTab(w1_scroll, "出装与加点")

        w2 = _page()
        l2 = QVBoxLayout(w2)
        l2.setContentsMargins(16, 14, 16, 14)
        l2.setSpacing(10)
        self.offer_advice = QLabel("未在选海克斯")
        self.offer_advice.setWordWrap(True)
        l2.addWidget(self.offer_advice)
        grid = QGridLayout()
        self.offer_cards, self.offer_frames = [], []
        for i in range(4):  # 第 4 格只在四选一时显示
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignTop)
            lab.setMinimumWidth(110)
            fr = _card()
            _card_layout(fr).addWidget(lab)
            grid.addWidget(fr, 0, i)
            fr.setVisible(i < 3)
            self.offer_cards.append(lab)
            self.offer_frames.append(fr)
        l2.addLayout(grid)
        btns = QHBoxLayout()
        b1 = QPushButton("重新识别")
        b1.clicked.connect(self.engine.rescan)
        b2 = QPushButton("重新校准卡片位置")
        b2.clicked.connect(self._recalibrate)
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addStretch(1)
        l2.addLayout(btns)
        l2.addStretch(1)
        self.tabs.addTab(w2, "海克斯选择")

        self.tabs.addTab(self._settings_tab(), "设置")
        self._refresh_theme_visuals()
        lay.addWidget(ws_card, 1)
        # 小屏或高缩放时保留完整内容，允许滚动，不让底部操作落到屏幕外。
        root.setMinimumWidth(640)
        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        viewport.setFrameShape(QScrollArea.NoFrame)
        viewport.setWidget(root)
        self.setCentralWidget(viewport)
        self._root_layout, self._card_layouts = lay, [hl, ubv]
        self._rail_layout = rail_lay

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    # ---------- 设置 ----------

    def _settings_tab(self) -> QWidget:
        """设置页：一屏放下，不用滚动；改了马上生效，没有「保存」按钮。"""
        s = self.engine.settings
        w = _page()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(14, 10, 14, 8)
        outer.setSpacing(8)
        g = QGridLayout()
        g.setVerticalSpacing(5)
        g.setHorizontalSpacing(10)
        g.setColumnStretch(1, 1)
        outer.addLayout(g)

        def label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return lab

        # 外服：游戏客户端的语言
        self.set_lang = QComboBox()
        for code, name in i18n.LANGS:
            self.set_lang.addItem(name, code)
        self.set_lang.setCurrentIndex(max(0, self.set_lang.findData(i18n.normalize_lang(s.game_lang))))
        self.set_lang.setToolTip("国服选简体中文；外服按游戏客户端的语言选")
        # 外观模式（暖瓷白 / 墨石黑 / 跟随系统）
        self.set_theme = QComboBox()
        for code, name in theme.THEME_MODES:
            self.set_theme.addItem(name, code)
        self.set_theme.setCurrentIndex(max(0, self.set_theme.findData(getattr(s, "theme_mode", "system"))))
        self.set_theme.setToolTip("切换主界面的浅色（暖瓷白）、深色（墨石黑）或跟随系统外观")
        self.set_corner = QComboBox()
        self.set_corner.addItems(["右上角", "左上角"])
        self.set_corner.setCurrentIndex(0 if s.overlay_corner == "top-right" else 1)
        self.set_corner.setToolTip("对局中收起详情后按钮隐藏，鼠标移到原位置附近再出现，点击可展开。\n"
                                   "选英雄、三选一推荐标签和未识别英雄的提示照常显示。")
        # 详情的背景只在详情里点「背景」按钮换，设置页没有这一项：存设置、马上生效
        panel = getattr(self.overlay, "panel", None)
        if hasattr(panel, "bg_picked"):
            panel.bg_picked.connect(self._bg_picked)
        # 1.2.0：不再有详情快捷键（不好按），只靠鼠标唤出，这里写明怎么唤出
        self.corner_hint = QLabel("按钮游戏内隐藏，鼠标移过去浮现")
        self.corner_hint.setWordWrap(True)
        theme.mark(self.corner_hint, muted=True)
        self.set_hotkey = QKeySequenceEdit(QKeySequence(s.overlay_hotkey))
        self.set_hotkey.setMaximumSequenceLength(1)
        self.set_hotkey.setClearButtonEnabled(True)
        edit = self.set_hotkey.findChild(QLineEdit)
        if edit is not None:  # Qt 默认的占位字是英文「Press shortcut」
            edit.setPlaceholderText("点这里按下快捷键")
        self.set_hotkey.setToolTip("点击后按下组合键，包含 Ctrl 或 Alt，可再加 Shift；支持字母、数字、F1～F11。\n"
                                   "默认不绑定：点击浮窗或把鼠标移到按钮位置也能看详情；海克斯推荐自动出现，选完自动收起。\n"
                                   "只在游戏或选英雄在前台时启用。建议避开 F 键和游戏、聊天、录屏软件已用的键位。")
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.set_hotkey, 1)
        clear_hotkey = QPushButton("清空")
        clear_hotkey.setToolTip("不绑定快捷键（默认）；仍可点击浮窗查看详情。")
        clear_hotkey.clicked.connect(self.set_hotkey.clear)
        hotkey_row.addWidget(clear_hotkey)
        hotkey_service = getattr(self.overlay, "hotkey", None)
        self.hotkey_status = QLabel(hotkey_service.status if hotkey_service else "游戏或选英雄在前台时启用。")
        self.hotkey_status.setWordWrap(True)
        theme.mark(self.hotkey_status, muted=True)
        if hotkey_service:
            hotkey_service.status_changed.connect(self.hotkey_status.setText)
        # 快捷键一行连同状态说明放一起，云控 features.overlay_hotkey 关着（默认）时整块不显示
        self.hotkey_box = QWidget()
        hotkey_lay = QVBoxLayout(self.hotkey_box)
        hotkey_lay.setContentsMargins(0, 0, 0, 0)
        hotkey_lay.addLayout(hotkey_row)
        hotkey_lay.addWidget(self.hotkey_status)
        self.hotkey_label = label("详情快捷键")
        # 三选一标签放卡片上方还是下方，右边的示意图跟着选项变
        self.set_badge = QComboBox()
        for code, name in BADGE_POSITIONS:
            self.set_badge.addItem(name, code)
        self.set_badge.setCurrentIndex(max(0, self.set_badge.findData(s.badge_position)))
        self.badge_preview = BadgePosPreview(s.badge_position)
        self.set_badge.currentIndexChanged.connect(
            lambda i: self.badge_preview.set_position(self.set_badge.itemData(i)))
        self.set_shop_overlay = QCheckBox("商店界面框选推荐装备")
        self.set_shop_overlay.setChecked(getattr(s, "shop_overlay", True))
        self.set_shop_overlay.setToolTip("局内打开商店时在常出与核心装备上标注顺位与选取率")
        self.set_enemy_rules = QCheckBox("按敌方阵容规则提示抗性装备")
        self.set_enemy_rules.setChecked(getattr(s, "enemy_rules", True))
        self.set_enemy_rules.setToolTip("基于敌方英雄定位给出规则建议，界面显式标注非统计结论")
        self.set_teammate_ocr = QCheckBox("选人时识别聊天框队友 ID")
        self.set_teammate_ocr.setChecked(getattr(s, "teammate_ocr", True))
        self.set_teammate_ocr.setToolTip("只截屏读取选人左下角聊天框并提供一键复制，不连接游戏客户端")
        self.set_auto = QCheckBox("开机自动启动")
        self.set_auto.setChecked(autostart.is_enabled())
        self.set_data = QCheckBox("自动获取最新海克斯数据（建议开启）")
        self.set_data.setChecked(s.check_data_updates)
        self.set_usage = QCheckBox("帮助改善软件（匿名）")
        self.set_usage.setChecked(s.send_usage)
        self.set_usage.setToolTip("开着时：联网时带一个随机编号（和账号、硬件无关），用来统计有多少人在用；\n"
                                  "排查问题时开发者可能请这台电脑上传运行日志，上传前去掉游戏账号名和电脑用户名。\n"
                                  "关掉就都不发。")

        g.addWidget(label("游戏语言"), 0, 0)
        g.addWidget(self.set_lang, 0, 1, 1, 2)
        g.addWidget(label("外观模式"), 1, 0)
        g.addWidget(self.set_theme, 1, 1, 1, 2)
        g.addWidget(label("浮窗位置"), 2, 0)
        g.addWidget(self.set_corner, 2, 1, 1, 2)
        g.addWidget(self.corner_hint, 3, 1, 1, 2)
        g.addWidget(self.hotkey_label, 4, 0)
        g.addWidget(self.hotkey_box, 4, 1, 1, 2)
        self._show_hotkey_row()
        # 示意图比下拉框高：左边下拉框下面接着放功能开关与基础开关，示意图在右边对齐
        g.addWidget(label("三选一标签"), 5, 0)
        g.addWidget(self.set_badge, 5, 1)
        g.addWidget(self.set_shop_overlay, 6, 1)
        g.addWidget(self.set_enemy_rules, 7, 1)
        g.addWidget(self.set_teammate_ocr, 8, 1)
        g.addWidget(self.set_auto, 9, 1)
        g.addWidget(self.set_data, 10, 1)
        g.addWidget(self.set_usage, 11, 1)
        g.addWidget(self.badge_preview, 5, 2, 6, 1, Qt.AlignTop | Qt.AlignRight)

        # 改了就生效、马上写进设置文件
        for combo in (self.set_lang, self.set_corner, self.set_badge):
            combo.currentIndexChanged.connect(self._settings_edited)
        self.set_theme.currentIndexChanged.connect(self._theme_edited)
        for box in (self.set_shop_overlay, self.set_enemy_rules, self.set_teammate_ocr, self.set_data, self.set_usage):
            box.toggled.connect(self._settings_edited)
        self.set_auto.toggled.connect(self._autostart_edited)
        self.set_hotkey.keySequenceChanged.connect(self._hotkey_edited)

        # 我的水平：和上面的设置项排成一样的一行
        rrow = QHBoxLayout()
        rrow.setSpacing(8)
        self.rank_input = QLineEdit(s.riot_id)
        self.rank_input.setPlaceholderText("名字#编号")
        self.rank_input.returnPressed.connect(self._query_rank)
        self.btn_rank = QPushButton("查询")
        self.btn_rank.setMinimumWidth(84)
        self.btn_rank.clicked.connect(self._query_rank)
        rrow.addWidget(self.rank_input, 1)
        rrow.addWidget(self.btn_rank)
        g.addWidget(label("我的水平"), 12, 0)
        g.addLayout(rrow, 12, 1, 1, 2)
        self.rank_result = QLabel()
        self.rank_result.setWordWrap(True)
        g.addWidget(self.rank_result, 13, 1, 1, 2)
        self._show_rank(s.my_rank)
        self._rank_worker = None
        outer.addStretch(1)
        # 版本和检查更新固定在页底，设置项较多时只滚动上面的表单。
        card = _card("footer")
        about_row = QHBoxLayout(card)
        about_row.setContentsMargins(14, 7, 14, 7)
        cv = QVBoxLayout()
        cv.setSpacing(3)
        about_row.addLayout(cv, 1)
        about = QLabel(about_html())
        about.setTextFormat(Qt.RichText)
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        self.about_label = about
        cv.addWidget(about)
        self.about_note = theme.mark(
            QLabel("非官方非商用工具 · 海克斯大乱斗统计数据（github.com/czgreat/aramhex-data），CC BY-NC 4.0"),
            muted=True,
        )
        self.about_note.setWordWrap(True)
        cv.addWidget(self.about_note)
        self.about_data = QLabel()
        theme.mark(self.about_data, muted=True)
        self.about_data.setWordWrap(True)
        cv.addWidget(self.about_data)
        self.btn_check = QPushButton("检查更新")
        self.btn_check.setMinimumWidth(120)
        self.btn_check.setMinimumHeight(32)
        self.btn_check.clicked.connect(lambda: self.check_update(manual=True))
        # 没有「保存」按钮：改完在检查更新下面短暂显示绿色「已保存」，平时空着。
        # 右边这一栏本来比左边的说明矮，放这里页底不变高，设置项仍一屏放下
        self.save_hint = QLabel()
        self.save_hint.setAlignment(Qt.AlignCenter)
        self.save_hint.setMinimumHeight(self.save_hint.fontMetrics().height())  # 空着也占一行：出现、消失时按钮不跳
        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.timeout.connect(self.save_hint.clear)
        side = QVBoxLayout()
        side.setSpacing(4)
        side.addStretch(1)
        side.addWidget(self.btn_check)
        side.addWidget(self.save_hint)
        side.addStretch(1)
        about_row.addLayout(side)
        # 设置项越来越多：放进可滚动区域，窗口矮的时候不会被压扁
        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 表单的建议高度不能撑大整页，否则外层滚动区仍会把页底按钮推到屏幕外。
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        tab = _page()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(1, 1, 1, 10)
        tab_layout.addWidget(scroll, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 0, 14, 0)
        foot.addWidget(card)
        tab_layout.addLayout(foot)
        return tab

    # ---------- 主题与快捷搜索 ----------

    def _focus_search(self) -> None:
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def _on_nav_changed(self, idx: int) -> None:
        for i, btn in enumerate(getattr(self, "_nav_buttons", ())):
            btn.setProperty("active", i == idx)
            if btn.style():
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        if hasattr(self, "_section_title") and 0 <= idx < len(NAV_LABELS):
            self._section_title.setText(f"<b style='font-size:15px'>{NAV_LABELS[idx]}</b>")

    def _refresh_theme_visuals(self) -> None:
        """同步标题、顶部快捷切换按钮和富文本说明到当前生效主题（深色/浅色）。"""
        if hasattr(self, "_title_label"):
            self._title_label.setText(
                f"<b style='font-size:13.5px'>海克斯助手</b><br>"
                f"<span style='font-size:11.5px;color:{theme.MUTED}'>v{__version__}</span>"
            )
        if hasattr(self, "btn_theme"):
            self.btn_theme.setText("切浅色" if theme.current_mode() == "dark" else "切深色")
        if hasattr(self, "about_label"):
            self.about_label.setText(about_html())
        if hasattr(self, "rank_result") and hasattr(self, "engine"):
            self._show_rank(self.engine.settings.my_rank)

    def _set_theme_mode(self, mode: str, *, save: bool = True) -> None:
        if mode not in ("system", "light", "dark"):
            mode = "system"
        s = self.engine.settings
        s.set_by_user("theme_mode", mode)
        app = QApplication.instance()
        if app is not None:
            theme.apply(app, mode)
        if hasattr(self, "set_theme"):
            old = self.set_theme.blockSignals(True)
            try:
                idx = self.set_theme.findData(mode)
                if idx >= 0:
                    self.set_theme.setCurrentIndex(idx)
            finally:
                self.set_theme.blockSignals(old)
        self._refresh_theme_visuals()
        self._panel_hero = None
        if self.isVisible():
            self.refresh()
        if save:
            self._write_settings()

    def _theme_edited(self, *_):
        mode = self.set_theme.currentData() or "system"
        if mode != self.engine.settings.theme_mode:
            self._set_theme_mode(mode)

    def copy_teammates(self) -> int:
        """一键复制选人聊天框识别到的队友召唤师 ID 到剪贴板（优先使用编辑框内手工修正后的内容），返回复制人数。"""
        edited = self.teammate_edit.text().strip() if hasattr(self, "teammate_edit") else ""
        if edited:
            names = [part.strip() for part in edited.replace("、", ",").replace("，", ",").split(",") if part.strip()]
        else:
            cs = self.engine.snapshot().get("champ_select") or {}
            names = [t.get("raw_name") for t in (cs.get("teammates") or ()) if t.get("raw_name")]
        if not names:
            return 0
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText("\n".join(names))
        return len(names)

    def _copy_teammates_clicked(self) -> None:
        if self.copy_teammates() and hasattr(self, "btn_copy_mates"):
            self.btn_copy_mates.setText("已复制")
            QTimer.singleShot(1500, lambda: self.btn_copy_mates.setText("复制ID") if hasattr(self, "btn_copy_mates") else None)

    def _toggle_theme(self) -> None:
        self._set_theme_mode("light" if theme.current_mode() == "dark" else "dark")

    # ---------- 查我的水平 ----------

    def _show_rank(self, res: dict):
        text = rank.describe(res)
        self.rank_result.setText(
            text or f"<span style='color:{theme.MUTED}'>填自己的「名字#编号」，查区内排名，自动选对应分段</span>"
        )
        r = (res or {}).get("results") or []
        if hasattr(self, "my_rank_label"):
            self.my_rank_label.setText(f"你：{r[0]['band_name']}（前 {rank.top_pct(r[0]['top'])}）" if r else "")
            self.my_rank_label.setVisible(bool(r))

    def _retire_when_done(self, attr: str, worker) -> None:
        """查询/更新线程跑完就删掉：父对象是主窗口，不删的话每查一次留一个 QThread（助手常驻托盘好几天）。"""
        def done():
            if getattr(self, attr) is worker:
                setattr(self, attr, None)
            worker.deleteLater()
        worker.finished.connect(done)

    def _query_rank(self, silent: bool = False):
        if self._rank_worker and self._rank_worker.isRunning():
            return
        rid = self.rank_input.text().strip()
        if not silent:
            self.btn_rank.setEnabled(False)
            self.btn_rank.setText("查询中…")
        self._rank_worker = RankWorker(rid, self)
        self._rank_worker.done.connect(lambda res: self._rank_done(rid, res, silent))
        self._rank_worker.failed.connect(lambda msg: self._rank_failed(msg, silent))
        self._rank_worker.finished.connect(lambda: (self.btn_rank.setEnabled(True), self.btn_rank.setText("查询")))
        self._retire_when_done("_rank_worker", self._rank_worker)
        self._rank_worker.start()

    def _rank_done(self, rid: str, res: dict, silent: bool):
        import time
        s = self.engine.settings
        old = (s.my_rank or {}).get("results") or []
        old_band = norm_band(old[0]["band"]) if old else ""
        s.riot_id, s.my_rank = rid, {**res, "queried_at": time.time()}
        pending = getattr(self, "_recheck_pending", None)
        if silent and pending:  # 查分库更新后的自动重查成功了：这个日期不再查
            s.extra["rank_rechecked"] = pending
            self._recheck_pending = None
        s.save()
        self._show_rank(s.my_rank)
        band = norm_band(res["results"][0]["band"])
        if silent and old and band != old_band and band in BANDS:
            # 查分库更新后自动重查，分段变了：告诉玩家；参考分段原来跟着查分选的，就跟着换
            self._toast(f"查分数据更新了：你现在是{BANDS[band]}（前 {rank.top_pct(res['results'][0]['top'])}），"
                        f"原来是{BANDS.get(old_band, old_band)}")
            if (s.data_band or "") == old_band:
                silent = False
        if not silent and band in BANDS:
            i = self.band_box.findData(band)
            if i >= 0:
                self.band_box.setCurrentIndex(i)  # 触发 engine.set_band，记住选择

    def _rank_failed(self, msg: str, silent: bool):
        if silent:
            logging.getLogger(__name__).info("自动查分失败：%s", msg)
            return
        self.rank_result.setText(f"<span style='color:{theme.BAD}'>{escape(msg)}</span>")

    def refresh_rank_if_stale(self):
        """启动时：上次查分超过 7 天就悄悄再查一次（不改你选的分段）。"""
        import time
        s = self.engine.settings
        if s.riot_id and time.time() - float((s.my_rank or {}).get("queried_at") or 0) > 7 * 86400:
            self._query_rank(silent=True)

    def recheck_rank_if_newer(self, cfg: dict) -> bool:
        """云控 rank.as_of（查分库最新数据日期）比本机上次查到的新：悄悄重查一次。
        同一个 as_of 查成功一次就不再查（查分库还没换完时不反复查）；查失败、对局中、选英雄中，下次刷新云控再试。"""
        s = self.engine.settings
        latest = str(((cfg or {}).get("rank") or {}).get("as_of") or "")
        mine = str((s.my_rank or {}).get("as_of") or "")
        if not (s.riot_id and latest and latest > mine and s.extra.get("rank_rechecked") != latest):
            return False
        if self._busy():  # 分段变了会弹提示：别在对局、选英雄时弹
            return False
        self._recheck_pending = latest
        if self.rank_input.text().strip() != s.riot_id:
            self.rank_input.setText(s.riot_id)
        logging.getLogger(__name__).info("查分库更新到 %s（本机上次 %s），自动重查", latest, mine or "无")
        self._query_rank(silent=True)
        return True

    # ---------- 云控 ----------

    def _show_primary(self):
        p = cloud.primary_link()
        if p:
            self.btn_comm.setText(p["name"])
            self.btn_comm.setToolTip(p.get("text") or "")
        self.btn_comm.setVisible(bool(p))

    def _open_primary(self):
        p = cloud.primary_link()
        if p:
            webbrowser.open(p["url"])

    def _in_game(self) -> bool:
        return self.engine.snapshot().get("phase") == "ingame"

    def _busy(self) -> bool:
        """对局中或正在选英雄：这时不弹窗（会抢游戏或客户端的焦点）。"""
        snap = self.engine.snapshot()
        return snap.get("phase") == "ingame" or bool(snap.get("champ_select"))

    def _modal_open(self) -> bool:
        """有弹窗开着（提醒类，或设置已保存、检查更新这类别的对话框）：不再叠一个。"""
        return self._popup_open or QApplication.activeModalWidget() is not None

    def _toast(self, text: str) -> None:
        tray = getattr(self, "tray", None)
        if tray:
            tray.showMessage("海克斯大乱斗助手", text, app_icon(), 6000)

    def _notify_tick(self):
        """游戏外才出：攒下的公告/新版本提示、数据已更新的提示、关了自动更新时的「是否更新」。
        弹窗还要避开选英雄；已经有弹窗开着时不再叠一个（计时器在弹窗打开期间也会跑）。"""
        if self._in_game() or self._modal_open():
            return
        if self._deferred_cloud is not None and not self._busy():
            cfg, self._deferred_cloud = self._deferred_cloud, None
            self._apply_cloud(cfg)
        if self._deferred_toast:
            text, self._deferred_toast = self._deferred_toast, None
            self._toast(text)
        dd = self.engine.snapshot().get("data") or {}
        note = dd.get("data_note")
        if note and note.get("id") != self._shown_note:
            self._shown_note = note["id"]
            logging.getLogger(__name__).info("右下角提示：%s", note["text"])
            self._toast(note["text"])
        offer = dd.get("data_offer")
        if offer and offer.get("id") not in self._asked_offers and not self._busy() and not self._modal_open():
            self._asked_offers.add(offer["id"])  # 每份新数据只问一次；点了「稍后」下次启动再问
            self._popup_open = True
            try:
                ask = QMessageBox.question(self, "统计数据", f"检测到新数据（{offer['text']}），现在更新吗？")
            finally:
                self._popup_open = False
            if ask == QMessageBox.Yes:
                st = self.engine.store
                threading.Thread(target=lambda: st.sync_data(force=True, manual=True), daemon=True).start()

    @staticmethod
    def _check_interval_ms() -> int:
        """定时检查的间隔：云控 update.check_minutes，每台电脑随机错开 ±10%，免得同一时刻一起请求。"""
        return int(cloud.check_minutes() * 60_000 * random.uniform(0.9, 1.1))

    def _upload_logs(self, cfg: dict) -> None:
        try:
            logupload.maybe_upload(self.engine.settings, cfg)
        except Exception:
            logging.getLogger(__name__).exception("上传日志出错")

    def _apply_cloud_settings(self, cfg: dict) -> None:
        """云控设置（cloudsettings.py）：改了值的马上生效，设置页跟着变；强制的原因每条规则提示一次。"""
        s = self.engine.settings
        res = cloudsettings.apply(s, cfg, __version__)
        changed = set(res["changed"])
        if changed:
            s.save()
            if "data_band" in changed:
                self.engine.set_band(s.data_band or None, by_user=False)
            if "game_lang" in changed:
                self.engine.set_game_lang(s.game_lang)
            if "check_data_updates" in changed and hasattr(self.engine.store, "check_updates"):
                self.engine.store.check_updates = s.check_data_updates
            if "overlay_bg" in changed and hasattr(self, "overlay"):
                self.overlay.apply_bg()
            if changed & {"overlay", "overlay_corner"} and hasattr(self, "overlay"):
                self.overlay.set_visible(s.overlay)
                self.overlay.panel.corner = s.overlay_corner
            self._sync_settings_form()
        seen = s.extra.get("seen_force") if isinstance(s.extra.get("seen_force"), list) else []
        for rid, reason in res["reasons"]:
            if rid not in seen:
                seen.append(rid)
                s.extra["seen_force"] = seen[-20:]
                s.save()
                if self._busy():  # 1.1.8：对局中、选英雄时先攒着，回到游戏外再提示（1.1.7 会在对局里弹）
                    logging.getLogger(__name__).info("对局中或选英雄中，云控设置提示推迟到打完")
                    self._deferred_toast = reason
                else:
                    self._toast(reason)

    def _sync_settings_form(self) -> None:
        """设置页的控件按当前设置重新显示（云控改了值以后），不触发各自的处理函数。"""
        s = self.engine.settings
        if not hasattr(self, "set_data"):
            return
        pairs = [(self.set_data, lambda w: w.setChecked(s.check_data_updates)),
                 (self.set_corner, lambda w: w.setCurrentIndex(0 if s.overlay_corner == "top-right" else 1)),
                 (self.set_badge, lambda w: w.setCurrentIndex(max(0, w.findData(s.badge_position)))),
                 (self.set_lang, lambda w: w.setCurrentIndex(max(0, w.findData(s.game_lang)))),
                 (self.band_box, lambda w: w.setCurrentIndex(max(0, w.findData(s.data_band or ""))))]
        if hasattr(self, "set_theme"):
            pairs.append((self.set_theme, lambda w: w.setCurrentIndex(max(0, w.findData(getattr(s, "theme_mode", "system"))))))
        if hasattr(self, "set_shop_overlay"):
            pairs.append((self.set_shop_overlay, lambda w: w.setChecked(getattr(s, "shop_overlay", True))))
        if hasattr(self, "set_enemy_rules"):
            pairs.append((self.set_enemy_rules, lambda w: w.setChecked(getattr(s, "enemy_rules", True))))
        if hasattr(self, "set_teammate_ocr"):
            pairs.append((self.set_teammate_ocr, lambda w: w.setChecked(getattr(s, "teammate_ocr", True))))
        for w, fn in pairs:
            old = w.blockSignals(True)
            try:
                fn(w)
            finally:
                w.blockSignals(old)
        self.badge_preview.set_position(s.badge_position)

    def _show_hotkey_row(self) -> None:
        """1.2.0 起设置页不显示「详情快捷键」，「浮窗位置」下面写怎么用鼠标唤出；
        云控 features.overlay_hotkey=true 退回 1.1.9（快捷键一行显示，说明不显示）。"""
        on = cloud.feature("overlay_hotkey", False)
        self.hotkey_label.setVisible(on)
        self.hotkey_box.setVisible(on)
        self.corner_hint.setVisible(not on)

    def _apply_cloud(self, cfg: dict):
        if hasattr(self.engine, "cloud_changed"):
            self.engine.cloud_changed()
        if hasattr(self, "hotkey_box"):
            self._show_hotkey_row()  # 云控 features.overlay_hotkey 开关变了：设置页跟着变
        try:
            self._apply_cloud_settings(cfg)
        except Exception:
            logging.getLogger(__name__).exception("云控设置出错")
        if hasattr(self, "overlay"):
            self.overlay.apply_bg()  # 云控 features.overlay_bg 开关变了：详情的背景、按钮跟着变
        try:
            logupload.apply_verbose(self.engine.settings, cfg)
        except Exception:
            logging.getLogger(__name__).exception("远程详细日志出错")
        try:
            self.recheck_rank_if_newer(cfg)
            threading.Thread(target=self._upload_logs, args=(cfg,), daemon=True).start()
        except Exception:
            logging.getLogger(__name__).exception("自动重查、上传日志出错")
        if hasattr(self, "_update_timer"):
            self._update_timer.setInterval(self._check_interval_ms())
        if hasattr(self, "about_label"):
            self.about_label.setText(about_html())
        if hasattr(self, "btn_comm"):
            self._show_primary()
        busy = self._busy()
        if busy or self._modal_open():  # 公告、版本太旧都是弹窗：打完这局、选完英雄再弹；已有弹窗时也等一等
            if self._deferred_cloud is None:
                why = ("对局中" if self._in_game() else "选英雄中") if busy else "已有弹窗开着"
                logging.getLogger(__name__).info("%s，云控公告/版本检查推迟", why)
            self._deferred_cloud = cfg
            return
        self._popup_open = True
        try:
            self._cloud_popups(cfg)
        finally:
            self._popup_open = False

    def _cloud_popups(self, cfg: dict):
        s = self.engine.settings
        notice = cfg.get("notice") or {}
        if notice.get("id") and notice.get("text") and notice["id"] != s.seen_notice:
            s.seen_notice = notice["id"]
            s.save()
            box = QMessageBox(QMessageBox.Information, "公告", notice["text"], parent=self)
            b_open = box.addButton("查看", QMessageBox.AcceptRole) if notice.get("url") else None
            box.addButton("知道了", QMessageBox.RejectRole)
            box.exec()
            if b_open is not None and box.clickedButton() is b_open:
                webbrowser.open(notice["url"])
        minv = cfg.get("min_version") or ""
        if minv and update.is_newer(minv, __version__) and not getattr(self, "_min_warned", False):
            self._min_warned = True
            box = QMessageBox(QMessageBox.Warning, "需要更新", f"当前版本 {__version__} 太旧，请更新到最新版本。", parent=self)
            b_up = box.addButton("立即更新", QMessageBox.AcceptRole)
            box.addButton("稍后", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b_up:
                self._update_info = self._update_info or getattr(self, "_held_update", None)
                if self._update_info:
                    self._start_update()
                else:
                    self._offer_manual("", update.pan_links())

    def _hotkey_edited(self, seq) -> None:
        """录完一个组合键（或点了清空）马上生效。不能用的键（单按、被占用）不改原来的设置，下面一行说明原因。"""
        from .hotkey import parse_shortcut
        s = self.engine.settings
        text = seq.toString(QKeySequence.PortableText)
        try:
            parse_shortcut(text)
        except ValueError as exc:
            self.hotkey_status.setText(f"<span style='color:{theme.BAD}'>{escape(str(exc))}</span>")
            return
        hotkey_service = getattr(self.overlay, "hotkey", None)
        error = hotkey_service.validate(text) if hotkey_service else ""
        if error:
            self.hotkey_status.setText(f"<span style='color:{theme.BAD}'>{escape(error)}</span>")
            return
        if text == s.overlay_hotkey:
            return
        s.set_by_user("overlay_hotkey", text)
        self._write_settings()

    def _bg_picked(self, code: str) -> None:
        """详情里点了「背景」按钮：记成玩家选的（以后云控改默认值不碰），马上生效并写进设置文件。"""
        self.engine.settings.set_by_user("overlay_bg", code)
        self.overlay.apply_bg()
        self._write_settings()

    def _autostart_edited(self, on: bool) -> None:
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.sync_autostart()
            QMessageBox.warning(self, "开机自启", f"设置失败：{e}")
        else:
            self._flash_saved()
        tray = getattr(self, "tray", None)
        if tray is not None:  # 托盘菜单的勾跟着变
            tray.sync_autostart()

    def sync_autostart(self) -> None:
        """设置页「开机自动启动」按注册表的实际状态重新显示（托盘改了、写失败时）。"""
        if hasattr(self, "set_auto"):
            _set_checked_quietly(self.set_auto, autostart.is_enabled())

    def _settings_edited(self, *_):
        """设置页任意一项改了：马上生效并写进设置文件（没有「保存」按钮）。"""
        s = self.engine.settings
        before = {k: getattr(s, k) for k in cloudsettings.SPEC}
        s.check_data_updates = self.set_data.isChecked()
        usage_changed = s.send_usage != self.set_usage.isChecked()
        s.send_usage = self.set_usage.isChecked()
        rules_changed = False
        if hasattr(self, "set_shop_overlay"):
            s.set_by_user("shop_overlay", self.set_shop_overlay.isChecked())
        if hasattr(self, "set_enemy_rules"):
            rules_changed = s.enemy_rules != self.set_enemy_rules.isChecked()
            s.set_by_user("enemy_rules", self.set_enemy_rules.isChecked())
        if hasattr(self, "set_teammate_ocr"):
            s.set_by_user("teammate_ocr", self.set_teammate_ocr.isChecked())
        if rules_changed:
            self._panel_hero = None
            if self.isVisible():
                self.refresh()
        cloud.set_install_id(s.install_id if s.send_usage else None)
        try:
            logupload.apply_verbose(s, cloud.get())  # 关了「帮助改善软件」，远程详细日志马上停
        except Exception:
            logging.getLogger(__name__).exception("远程详细日志出错")
        if hasattr(self.engine.store, "check_updates"):
            self.engine.store.check_updates = s.check_data_updates  # 马上生效，不用重开
        s.overlay_corner = "top-right" if self.set_corner.currentIndex() == 0 else "top-left"
        s.badge_position = self.set_badge.currentData() or "top"
        lang = self.set_lang.currentData() or "zh_CN"
        if lang != s.game_lang:
            self.engine.set_game_lang(lang)
        mine = [k for k, v in before.items() if getattr(s, k) != v]
        s.mark_user(*mine)  # 玩家自己改的：以后云控改默认值不碰
        held = [k for k in mine if k in s.forced]
        for k in held:  # 云控正在强制的项：记下玩家要的值，云控撤掉后用它
            s.forced[k] = getattr(s, k)
        if held or usage_changed:
            # 改回强制值，并让语言、数据更新等跟着生效；开关使用统计会换掉匿名编号，
            # 按编号挑的规则（ids、percent 分组）要马上重算，关了统计就马上撤掉（1.1.9）
            try:
                self._apply_cloud_settings(cloud.get())
            except Exception:
                logging.getLogger(__name__).exception("云控设置出错")
        if held:
            QMessageBox.information(self, "设置", "这几项现在按官方临时设置，撤掉后会改回你选的："
                                    + "、".join(SETTING_NAMES.get(k, k) for k in held))
        self.overlay.panel.corner = s.overlay_corner
        self._write_settings()

    def _write_settings(self) -> None:
        """写设置文件；写不进去只提醒一次，免得每改一项弹一次。"""
        if self.engine.settings.save():
            self._save_warned = False
            self._flash_saved()
        elif not getattr(self, "_save_warned", False):
            self._save_warned = True
            QMessageBox.warning(self, "设置", "设置文件写不进去，改动关掉助手后会丢失。")

    def _flash_saved(self) -> None:
        """设置页没有「保存」按钮：改完在页底短暂显示「已保存」，玩家知道改动已经写进去了。"""
        hint = getattr(self, "save_hint", None)
        if hint is None:
            return
        hint.setText(_saved_html())
        self._saved_timer.start(2000)

    def _recalibrate(self):
        self.engine.reset_calibration()
        QMessageBox.information(self, "重新校准", "已清除卡片位置，下次出现海克斯三选一时会重新校准。")

    # ---------- 更新 ----------

    def check_update(self, manual: bool = False):
        """启动、再次打开助手时各查一次，平时按云控 update.check_minutes 查（默认 3 小时）；
        只提示，用户点了「立即更新」才下载安装。正在查或正在下载时跳过。
        manual=True 是设置页「检查更新」按钮：结果（最新 / 有新版本 / 失败）都弹窗告诉用户。"""
        if self._worker and self._worker.isRunning():
            if manual:
                QMessageBox.information(self, "检查更新", "正在检查或下载更新，请稍候。")
            return
        self._data_msg = ""
        self._worker = UpdateWorker("check", parent=self, strict=manual,
                                    data_sync=self._sync_data_now if manual else None)
        self._worker.found.connect(lambda info: self._update_found(info, manual))
        self._worker.cloud.connect(self._apply_cloud)
        if manual:
            self.btn_check.setEnabled(False)
            self.btn_check.setText("检查中…")
            self._worker.data_done.connect(lambda m: setattr(self, "_data_msg", m))
            self._worker.uptodate.connect(lambda: QMessageBox.information(
                self, "检查更新", f"软件已是最新版本（{__version__}）。" + self._data_line()))
            self._worker.failed.connect(self._check_failed)
            self._worker.finished.connect(lambda: (self.btn_check.setEnabled(True),
                                                   self.btn_check.setText("检查更新")))
        self._retire_when_done("_worker", self._worker)
        self._worker.start()

    def _sync_data_now(self) -> str:
        """「检查更新」按钮：马上查统计数据（不管自动更新开关）和官方资料，返回结果。"""
        st = self.engine.store
        changed = st.sync_data(force=True, manual=True)
        if changed:  # 结果在「检查更新」的对话框里说了，右下角不再提示一遍
            self._shown_note = (getattr(st, "data_note", None) or {}).get("id")
        ds = st.dataset
        tail = f"（{ds.patch} 版本，截至 {str(ds.snapshot_at)[5:10]}）" if ds else ""
        if changed:
            msg = f"统计数据已更新{tail}。"
        elif st.sync_error:
            msg = "统计数据这次没连上，稍后会自动再试。"
        else:
            msg = f"统计数据已是最新{tail}。"
        # 官方资料（英雄、海克斯、装备、召唤师技能）平时按云控间隔查（可能 30 天一次），按钮上也马上查一次。
        # 只在换上新一版时多说一句；没变化、连不上都不提，免得多一行看不懂的话
        if hasattr(st, "sync_official"):
            try:
                if st.sync_official(force=True):
                    rev = st.official.status().get("official_revision")
                    msg += f"\n官方资料已更新（第 {rev} 版）。"
            except Exception:
                logging.getLogger(__name__).exception("检查官方资料出错")
        return msg

    def _data_line(self) -> str:
        msg = getattr(self, "_data_msg", "")
        return f"\n{msg}" if msg else ""

    def _check_failed(self, msg: str):
        logging.getLogger(__name__).warning("检查更新失败：%s", msg)
        own_build = not official.updatable()  # 自己打的包不自动更新，不是失败
        box = QMessageBox(QMessageBox.Information if own_build else QMessageBox.Warning, "检查更新",
                          ("这不是官方安装包，不会自动更新。" if own_build else "检查更新失败，请稍后再试。")
                          + self._data_line(), parent=self)
        b_site = box.addButton("官网下载" if official.available() else "下载页", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_site:
            webbrowser.open(update.download_page())

    def _update_found(self, info: dict, manual: bool = False):
        known = (self._update_info or {}).get("version")
        minv = cloud.get().get("min_version") or ""
        if not manual and not (minv and update.is_newer(minv, __version__)) \
                and not cloud.offer_update(info["version"], getattr(self.engine.settings, "install_id", None)):
            # 分批推送还没轮到这台电脑（或暂停了）：先不提示；手动「检查更新」和「最低版本」照常
            self._held_update = info
            logging.getLogger(__name__).info("有新版本 %s，分批推送还没轮到本机，先不提示", info["version"])
            return
        self._update_info = info
        notes = f"<br><span style='color:{theme.MUTED}'>{escape(info['notes'][:200])}</span>" if info.get("notes") else ""
        # 打包后的程序都能先试增量更新；源码运行时只有带安装包地址的才能直接装
        direct = patch.install_root() is not None or (bool(info.get("url")) and not is_portable())
        self.update_text.setText(f"<b>有新版本 {info['version']}</b>（当前 {__version__}）{notes}")
        self.btn_update.setText("立即更新" if direct else "去下载")
        self.update_bar.show()
        tray = getattr(self, "tray", None)
        if manual:
            ask = QMessageBox.question(self, "检查更新", f"有新版本 {info['version']}（当前 {__version__}）。"
                                       + (f"\n\n{info['notes']}" if info.get("notes") else "")
                                       + (f"\n\n{self._data_msg}" if getattr(self, "_data_msg", "") else "")
                                       + "\n\n现在更新吗？")
            if ask == QMessageBox.Yes:
                if self._worker:
                    self._worker.wait(3000)  # 检查线程发完信号就结束，等它收尾再开始下载
                self._start_update()
        elif tray and known != info["version"]:  # 同一个版本只弹一次通知；对局中先攒着
            text = f"有新版本 {info['version']}，打开主界面点「立即更新」。"
            if self._in_game():
                logging.getLogger(__name__).info("对局中，新版本提示推迟到打完")
                self._deferred_toast = text
            else:
                self._toast(text)

    def _start_update(self):
        if not self._update_info or (self._worker and self._worker.isRunning()):
            return
        # 源码运行、又没有安装包地址：只能打开下载页
        if patch.install_root() is None and (is_portable() or not self._update_info.get("url")):
            webbrowser.open(cloud.site())
            return
        if self._busy():
            # 选英雄时也不更新：重启那几十秒正好错过选英雄界面，这局就认不出英雄（10-29 日志：1.1.2→1.1.3 更新后 48 局）
            QMessageBox.information(self, "更新", "正在选英雄或对局中，打完这局再更新。")
            return
        self.btn_update.setEnabled(False)
        self.btn_update.setText("更新中…")
        self._update_stage = "准备更新…"
        show_progress(self.update_progress, self._update_stage)
        self._worker = UpdateWorker("download", info=self._update_info, parent=self)
        self._worker.phase.connect(self._update_phase)
        self._worker.progress.connect(
            lambda done, total: show_progress(self.update_progress, self._update_stage.rstrip("…"), done, total))
        self._worker.ready.connect(self._install)
        self._worker.patched.connect(self._apply_patch)
        self._worker.manual.connect(self._offer_manual)
        self._worker.failed.connect(self._update_failed)
        self._retire_when_done("_worker", self._worker)
        self._worker.start()

    def _update_phase(self, text: str):
        self._update_stage = text
        show_progress(self.update_progress, text)

    def _apply_patch(self, changed: list, stale: list):
        show_progress(self.update_progress, "下载完成，正在重启助手…", 1, 1)
        root = patch.install_root()
        try:
            patch.launch_apply(root, changed, stale, self._update_info["version"], relaunch=str(root / "AramHex.exe"))
        except OSError as e:
            return self._update_failed(str(e))
        self.tray.quit()  # 退出让出文件；替换完自动重新打开
        hard_exit_later()

    def _offer_manual(self, reason: str, links: dict | None = None):
        """更新没能在软件里完成：提示原因，按钮直接打开网盘下载（链接从官网读，每次发版会换）或官网下载区。"""
        self.update_progress.hide()
        self.btn_update.setEnabled(True)
        self.btn_update.setText("重试更新")
        links = links or {}
        pan = links.get("portable" if is_portable() else "setup")
        instructions = ("请下载便携版，解压到新目录；退出旧助手后，将旧目录的 userdata 文件夹复制到新目录以保留设置。"
                        if is_portable() else "请下载新版本，直接覆盖安装，设置会保留。")
        box = QMessageBox(QMessageBox.Information, "更新", f"{reason}\n{instructions}", parent=self)
        b_pan = box.addButton("网盘下载", QMessageBox.AcceptRole)
        b_site = box.addButton("官网下载", QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_pan)
        box.exec()
        if box.clickedButton() is b_pan:
            webbrowser.open(pan or update.download_page())
        elif box.clickedButton() is b_site:
            webbrowser.open(update.download_page())

    def _install(self, path: str):
        show_progress(self.update_progress, "下载完成，正在启动安装程序…", 1, 1)
        try:
            update.launch_installer(path)
        except OSError as e:
            return self._update_failed(str(e))
        self.tray.quit()  # 退出让安装程序替换文件；装完会自动重新打开
        hard_exit_later()

    def _update_failed(self, msg: str):
        logging.getLogger(__name__).warning("更新失败：%s", msg)
        self._offer_manual("更新失败。")

    def _ensure_completer(self):
        heroes = self.engine.store.heroes
        if self._names or not heroes:
            return
        comp, self._names = hero_completer(self.engine.store, self)
        comp.activated.connect(lambda text: (self.engine.set_hero(self._names.get(text, text)), self.search.clear()))
        comp.popup().setObjectName("heroPopup")
        self.search.setCompleter(comp)

    def _search_pick(self):
        t = self.search.text().strip()
        if t:
            self.engine.set_hero(self._names.get(t, t))
            self.search.clear()

    def _set_candidates(self, cands):
        ids = [c.get("id") for c in cands]
        if ids == self._cand_ids:
            return
        self._cand_ids = ids
        while self.cands.count():
            it = self.cands.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if cands:
            self.cands.addWidget(QLabel("候选："))
        for c in cands[:6]:
            b = theme.mark(QPushButton(c.get("name") or c.get("id")), pill=True)
            b.clicked.connect(lambda _=False, hid=c.get("id"): self.engine.set_hero(hid))
            self.cands.addWidget(b)
        self.cands.addStretch(1)

    # ---------- 刷新 ----------

    def refresh(self):
        if not self.isVisible():
            return
        snap = self.engine.snapshot()
        self._ensure_completer()
        dd = snap.get("data", {})
        v = snap.get("vision", {})
        self.status.setText(
            f"<b>状态：</b>{PHASE_CN.get(snap.get('phase'), snap.get('phase'))}<br>"
            f"<b>海克斯识别：</b>{VISION_CN.get(v.get('status'), v.get('status'))}"
            f"{f' · <span style=\"color:{theme.BAD}\">游戏可能是全屏模式，无法识别。请在游戏内设置-窗口模式中选择无边框/窗口。</span>' if v.get('blank') else ''}<br>"
            f"<b>数据：</b>{BANDS.get(dd.get('band_effective'), '全体')} · {data_status_html(dd)}")
        if hasattr(self, "about_data"):
            self.about_data.setText("统计数据：" + data_status_html(dd))
        dp = dd.get("data_progress")
        if dp:
            show_progress(self.data_progress, "统计数据更新中", dp.get("done"), dp.get("total"))
        else:
            self.data_progress.hide()

        h, hid = snap.get("hero"), snap.get("hero_id")
        show_win = snap.get("settings", {}).get("show_winrate", True)
        d = self.engine.hero_panel(hid) if hid else None
        if h:
            r = (d or {}).get("rank") or {}
            b = self.engine.hero_brief(hid)
            rating = []
            if b.get("grade"):
                g_col = theme.GOOD if b["grade"] in ("S", "A") else theme.ACCENT if b["grade"] == "B" else theme.MUTED
                rating.append(f"<b style='color:{g_col}'>评级 {b['grade']}</b>")
            if b.get("rank"):
                rating.append(f"胜率排名 {b['rank']}/{b.get('total') or '?'}")
            if show_win and r.get("win") is not None:
                w_col = theme.GOOD if r["win"] >= 0.52 else theme.ACCENT if r["win"] >= 0.495 else theme.BAD
                rating.append(f"<b style='color:{w_col}'>胜率 {_pct(r['win'])}</b>")
            if r.get("pick") is not None:
                rating.append(f"出场率 {_pct(r['pick'])}")
            self.hero_label.setText(
                f"<span style='font-size:20px'><b>{escape(h['name'])}</b></span> "
                f"<span style='color:{theme.MUTED}'>{escape(h['nick'])}</span><br>"
                f"<span style='color:{theme.TEXT_2}'>{' · '.join(rating)}</span>")
        else:
            self.hero_label.setText("<b>未识别到英雄，请手动选择</b>")
        cs = snap.get("champ_select")
        if cs and (cs.get("bench") or cs.get("cards") or cs.get("teammates")):
            from .overlay import champ_select_summary
            parts = []
            if cs.get("bench") or cs.get("cards"):
                parts.append(champ_select_summary(cs, show_win))
            mates = cs.get("teammates") or []
            if mates:
                m_txt = "、".join(
                    f"{escape(m['raw_name'])}" + ("(?)" if m.get("uncertain") else "")
                    for m in mates if m.get("raw_name")
                )
                parts.append(f"<span style='color:{theme.MUTED}'>队友 ID（仅截屏）：</span>{m_txt}")
                raw_names = tuple(m["raw_name"] for m in mates if m.get("raw_name"))
                if hasattr(self, "teammate_edit") and raw_names != self._last_mates_key:
                    self._last_mates_key = raw_names
                    if not self.teammate_edit.hasFocus():
                        self.teammate_edit.setText(", ".join(raw_names))
                if hasattr(self, "teammate_bar"):
                    self.teammate_bar.show()
            elif hasattr(self, "teammate_bar"):
                self._last_mates_key = ()
                self.teammate_bar.hide()
            self.cs_label.setText("<br>".join(parts))
            self.cs_label.show()
        else:
            self.cs_label.hide()
            if hasattr(self, "teammate_bar"):
                self._last_mates_key = ()
                self.teammate_bar.hide()
        self._set_candidates(snap.get("candidates") or [])

        rule_sig = tuple(item.get("item_id") for item in ((d or {}).get("rule_adjustments") or ()))
        key = (hid, d.get("date"), d.get("data_revision"), d.get("official_revision"),
               d.get("official_origin"), self.engine.icons.version, dd.get("band_effective"), show_win,
               theme.current_mode(), rule_sig) if d else None
        if d and self._panel_hero != key:
            self._panel_hero = key
            self.tab_hero.setText(self._hero_html(d, show_win))
            if hasattr(self, "quick_heroes_box"):
                self.quick_heroes_box.hide()
        elif not d:
            self._panel_hero = None
            self.tab_hero.setText(self._empty_hero_html())
            self._ensure_quick_heroes()
            if hasattr(self, "quick_heroes_box"):
                self.quick_heroes_box.show()
        self._render_offer(snap.get("evaluation"), show_win,
                           (snap.get("offer") or {}).get("pending_columns"))

    def _empty_hero_html(self) -> str:
        return (
            f"<div style='padding:4px 0 8px 0'>"
            f"<div style='font-size:16px;font-weight:700;color:{theme.TEXT};margin-bottom:6px'>还没有选英雄</div>"
            f"<div style='color:{theme.TEXT_2};line-height:1.65'>"
            f"· 进入大乱斗<b>选人界面</b>后会自动识别当前英雄、待选栏与聊天框队友 ID<br>"
            f"· 对局中打开<b>商店（P）</b>会自动在「所有物品」页框选核心与常出装备<br>"
            f"· 出现<b>海克斯三选一</b>时会在卡片旁实时标注首选与胜率增幅<br>"
            f"· 若中途启动助手，可在上方搜索框（<code style='color:{theme.ACCENT}'>Ctrl+K</code>）或下方点选英雄立即查看"
            f"</div></div>"
        )

    def _ensure_quick_heroes(self) -> None:
        if getattr(self, "_quick_heroes_loaded", False) or not hasattr(self, "_quick_heroes_grid"):
            return
        if not hasattr(self.engine, "search_heroes"):
            return
        try:
            top = self.engine.search_heroes("", limit=8)
        except Exception:
            return
        if not top:
            return
        self._quick_heroes_loaded = True
        for idx, h in enumerate(top[:8]):
            win_str = f" {_pct(h.get('win'))}" if h.get("win") is not None else ""
            grade = f"{h.get('grade')} · " if h.get("grade") else ""
            btn = theme.mark(QPushButton(f"{grade}{h['name']}{win_str}"), pill=True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, hid=h["id"]: self.engine.set_hero(hid))
            self._quick_heroes_grid.addWidget(btn, idx // 4, idx % 4)

    def _hero_html(self, d, show_win) -> str:
        out = buildview.lines(d, self.engine.icons, show_win, size=28, muted=theme.MUTED)
        sk = buildview.skills_line(d, show_win, muted=theme.MUTED)
        if sk:
            out.append(sk)
        rules = d.get("rule_adjustments") or []
        if rules and getattr(self.engine.settings, "enemy_rules", True):
            rule_rows = []
            for r in rules:
                extra = f" · 胜率 {_pct(r.get('base_win'))}" if show_win and r.get("base_win") is not None else ""
                rule_rows.append(
                    f"<br><b style='color:{theme.WARN}'>{escape(r.get('name') or r.get('item_id', ''))}</b>"
                    f"<span style='color:{theme.MUTED}'>（持有 {_pct(r.get('base_pick'))}{extra}）</span>"
                )
            out.append(
                f"<div style='margin-top:6px;padding:8px 10px;border-radius:8px;"
                f"background:{theme.WARN_BG};border:1px solid {theme.LINE}'>"
                f"<b style='color:{theme.WARN}'>敌方阵容提示</b> "
                f"<span style='color:{theme.WARN}'>（规则推荐 · 非统计结论）</span>"
                + (f"<br><span style='color:{theme.TEXT_2}'>{escape(rules[0]['rule_reason'])}</span>" if rules[0].get("rule_reason") else "")
                + "".join(rule_rows)
                + "</div>"
            )
        top = [a for a in d.get("augments", []) if a.get("delta") is not None and a.get("sample") != "low"]
        top.sort(key=lambda a: -a["delta"])
        if top:
            out.append(f"<div style='margin-top:8px;padding-top:8px;border-top:1px solid {theme.LINE}'><b>推荐海克斯</b></div>")
            for a in top[:8]:
                d_col = theme.GOOD if a["delta"] >= 0 else theme.BAD
                rar = RARITY_CN.get(a.get("rarity"), "")
                r_col = theme.PRISM if a.get("rarity") == "prismatic" else theme.WARN if a.get("rarity") == "gold" else theme.MUTED
                out.append(
                    f"　<b>{escape(a['name'])}</b> "
                    f"<span style='color:{r_col}'>{rar}</span> "
                    f"<span style='color:{theme.MUTED}'>{a.get('tier') or ''}</span> "
                    f"<b style='color:{d_col}'>{a['delta']:+.1f}</b>"
                )
        # 每行一段、留点间距：图标行直接换行会上下贴在一起
        return "".join(f"<div style='margin:0 0 7px 0'>{line}</div>" for line in out)

    def _render_offer(self, ev, show_win, pending=None):
        frames = getattr(self, "offer_frames", ())
        if not ev:
            self.offer_advice.setText(f"<span style='color:{theme.MUTED}'>未在选海克斯</span>")
            for lab in self.offer_cards:
                lab.setText("")
            for fr in frames:
                if hasattr(fr, "setProperty"):
                    fr.setProperty("best", False)
                    if fr.style():
                        fr.style().unpolish(fr)
                        fr.style().polish(fr)
            return
        waiting = any(pending or ())
        pk = recommend.pentakill_text(ev.get("pentakill")) if not waiting else ""
        advice = "卡片更新中，等待识别确认" if waiting else ev['advice']
        self.offer_advice.setText(f"<b style='font-size:15px'>{advice}</b>"
                                  + (f"<br><span style='color:{theme.PRISM}'>{escape(pk)}</span>" if pk else ""))
        for i, fr in enumerate(frames):
            fr.setVisible(i < max(3, len(ev["slots"])))
        for idx, (lab, r) in enumerate(zip(self.offer_cards, ev["slots"])):
            is_best = r.get("verdict") == "best" and not (pending and r["index"] < len(pending) and pending[r["index"]])
            if idx < len(frames) and hasattr(frames[idx], "setProperty"):
                frames[idx].setProperty("best", is_best)
                if frames[idx].style():
                    frames[idx].style().unpolish(frames[idx])
                    frames[idx].style().polish(frames[idx])
            if pending and r["index"] < len(pending) and pending[r["index"]]:
                lab.setText("<span style='color:#777'>识别中…</span>")
                continue
            v, col = _verdict_info(r["verdict"])
            if r["verdict"] == "best" and r.get("sample_warning"):
                v = "相对较好，仅供参考"
            lines = [f"<b style='color:{col}'>{v}</b>", f"<b>{r.get('name') or '未识别'}</b>"]
            meta = [RARITY_CN.get(r.get("rarity"), "")]
            if r.get("tier"):
                meta.append(f"{r['tier']}级")
            lines.append(f"<span style='color:{theme.MUTED}'>" + " ".join(m for m in meta if m) + "</span>")
            if r["verdict"] == "nodata":
                note = recommend.NEW_NOTE if r.get("basis") == "new" else recommend.NODATA_NOTE
                lines.append(f"<span style='color:{theme.MUTED}'>{note}</span>")
            if r.get("basis") == "pbe":
                pbe = f"测试服 {r['pbe_games']} 局 · 胜率 {_pct(r['pbe_win'])}，" if r.get("pbe_games") else ""
                lines.append(f"<span style='color:{theme.MUTED}'>{pbe}{recommend.PBE_NOTE}</span>")
            if r.get("score") is not None:
                s = f"{r['score']:+.1f}"
                if show_win and recommend.win_text(r):
                    s += " · " + recommend.win_text(r)
                if r.get("thin") or r.get("sample_warning"):
                    warn = "⚠ 样本太少" if r.get("thin") == "too_few" else "样本偏少"
                    s += f" · <span style='color:{theme.BAD}'>{warn}</span>"
                lines.append(s)
            lab.setText("<br>".join(lines))

    # ---------- 窗口行为 ----------

    COMPACT_HEIGHT = 560  # 比这矮（小屏、高缩放）就收紧间距，把地方留给工作区里的内容
    NARROW_WIDTH = 720    # 窄窗口时自动收紧左侧导航栏宽度

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_rail"):
            want_w = 142 if self.width() < self.NARROW_WIDTH else 182
            if self._rail.width() != want_w:
                self._rail.setFixedWidth(want_w)
        compact = self.height() < self.COMPACT_HEIGHT
        if compact == self._compact:
            return
        self._compact = compact
        hm = 12 if self.width() < self.NARROW_WIDTH else 18
        self._root_layout.setContentsMargins(*((hm, 6, hm, 6) if compact else (hm, 12, hm, 12)))
        self._root_layout.setSpacing(5 if compact else 10)
        for lay in self._card_layouts:
            lay.setContentsMargins(*((12, 5, 12, 5) if compact else (14, 10, 14, 10)))
            lay.setSpacing(4 if compact else 6)
        size = 24 if compact else 30
        self._logo.setPixmap(app_icon().pixmap(size, size))
        self.about_data.setVisible(not compact)  # 左侧栏状态里有同样的内容
        self.about_note.setVisible(not compact)

    def show_and_raise(self):
        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(self.width(), max(360, available.width() - 16)),
                        min(self.height(), max(260, available.height() - 48)))
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.refresh()

    def closeEvent(self, e):
        if QApplication.instance().property("quitting"):
            e.accept()
            return
        e.ignore()
        self.hide()
        if not self._hint_shown and QSystemTrayIcon.isSystemTrayAvailable():
            self._hint_shown = True
            tray = getattr(self, "tray", None)
            if tray:
                tray.showMessage("海克斯大乱斗助手", "助手仍在后台运行，右下角托盘图标可以重新打开或退出。",
                                 app_icon(), 4000)


class Tray(QSystemTrayIcon):
    def __init__(self, engine, window: MainWindow, overlay):
        super().__init__(app_icon())
        self.engine, self.window, self.overlay = engine, window, overlay
        self.setToolTip(f"海克斯大乱斗助手 v{__version__}")
        m = QMenu()
        m.setObjectName("tray")
        m.addAction("打开主界面", window.show_and_raise)
        m.addAction("重新识别", engine.rescan)
        m.addAction("检查更新", lambda: (window.show_and_raise(), window.check_update(manual=True)))
        self.messageClicked.connect(window.show_and_raise)
        self.act_auto = QAction("开机自动启动", m, checkable=True)
        self.act_auto.setChecked(autostart.is_enabled())
        self.act_auto.toggled.connect(self._toggle_auto)
        m.addAction(self.act_auto)
        m.aboutToShow.connect(self.sync_autostart)  # 设置页、别的程序改过注册表：打开菜单时按实际状态显示
        m.addSeparator()
        m.addAction("退出", self.quit)
        self.setContextMenu(m)
        self._menu = m
        self.activated.connect(self._activated)
        self.timer = QTimer()
        self.timer.timeout.connect(self._tooltip)
        self.timer.start(3000)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.window.show_and_raise()

    def sync_autostart(self) -> None:
        _set_checked_quietly(self.act_auto, autostart.is_enabled())

    def _toggle_auto(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.sync_autostart()  # 没写进去：勾改回实际状态（1.1.9 以前勾变了、实际没写，玩家不知道）
            self.showMessage("开机自动启动", f"设置失败：{e}", app_icon(), 6000)
        self.window.sync_autostart()

    def _tooltip(self):
        s = self.engine.snapshot()
        h = s.get("hero")
        self.setToolTip(f"海克斯大乱斗助手 v{__version__}\n" + PHASE_CN.get(s.get("phase"), "") +
                        (f"\n英雄：{h['name']}" if h else ""))

    def quit(self):
        self.hide()
        quit_app(self.engine)
