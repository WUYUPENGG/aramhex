"""主界面组件化卡片模块（Oil UI「海克斯精密仪」原生 PySide6 组件）。

彻底替代原版单 QLabel 纯文本排版，直接把英雄头像、核心三件路线、商店单件选取率/已购进度、
敌方 5 人阵容分析与规则抗性建议、选人队友 ID 与海克斯分阶榜单以交互式卡片呈现在桌面端。
所有图标优先读本地缓存，缺失时秒级回退内置离线图标库（hero_icons.json / item_icons.json）。
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..data.icons import bundled_icons
from ..vision import portraits
from . import theme
from .herosearch import hero_completer

RARITY_CN = {"prismatic": "棱彩", "gold": "黄金", "silver": "白银"}

# 敌方阵容一键体验预设（真实英雄 ID，便于对局外随时预览规则抗性推荐）
ENEMY_PRESETS: tuple[tuple[str, list[str]], ...] = (
    ("多法伤", ["99", "63", "134", "1", "516"]),
    ("多物理", ["51", "222", "238", "157", "54"]),
    ("多坦克", ["516", "54", "31", "36", "89"]),
    ("多回血", ["16", "266", "36", "50", "141"]),
)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _clear_layout(lay) -> None:
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif it.layout() is not None:
            _clear_layout(it.layout())


def _round_pixmap(src: QPixmap, size: int, radius: int = 8) -> QPixmap:
    if src.isNull():
        return QPixmap()
    scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    cropped = scaled.copy(x, y, size, size)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, cropped)
    p.end()
    return out


@lru_cache(maxsize=512)
def _bundled_hero_bytes(alias: str) -> bytes | None:
    if not alias:
        return None
    icons = portraits.hero_icons()
    return icons.get(alias) or icons.get(alias.lower())


@lru_cache(maxsize=1024)
def _bundled_item_bytes(kind: str, key: str) -> bytes | None:
    if not key:
        return None
    bucket = bundled_icons().get(kind) or {}
    b64 = bucket.get(str(key))
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except (ValueError, TypeError):
        return None


def hero_pixmap(store, icons, hid: str | None, size: int = 44, radius: int = 10) -> QPixmap:
    if not hid:
        return QPixmap()
    hero = (getattr(store, "heroes", None) or {}).get(str(hid)) or {}
    alias = str(hero.get("alias") or "")
    pm = QPixmap()
    if alias:
        raw = _bundled_hero_bytes(alias)
        if raw:
            pm.loadFromData(raw)
    if pm.isNull() and icons is not None:
        path = icons.local("hero", str(hid), hero.get("icon"))
        if path:
            pm = QPixmap(path)
    return _round_pixmap(pm, size, radius) if not pm.isNull() else QPixmap()


def item_pixmap(icons, item_id: str | None, icon_url: str | None = None, size: int = 36, radius: int = 8) -> QPixmap:
    if not item_id:
        return QPixmap()
    pm = QPixmap()
    raw = _bundled_item_bytes("item", str(item_id))
    if raw:
        pm.loadFromData(raw)
    if pm.isNull() and icons is not None:
        path = icons.local("item", str(item_id), icon_url)
        if path:
            pm = QPixmap(path)
    return _round_pixmap(pm, size, radius) if not pm.isNull() else QPixmap()


def spell_pixmap(icons, spell_id: str | None, icon_url: str | None = None, size: int = 28, radius: int = 6) -> QPixmap:
    if not spell_id:
        return QPixmap()
    pm = QPixmap()
    raw = _bundled_item_bytes("spell", str(spell_id))
    if raw:
        pm.loadFromData(raw)
    if pm.isNull() and icons is not None:
        path = icons.local("spell", str(spell_id), icon_url)
        if path:
            pm = QPixmap(path)
    return _round_pixmap(pm, size, radius) if not pm.isNull() else QPixmap()


def _icon_label(pm: QPixmap, size: int, fallback: str = "", tooltip: str = "") -> QLabel:
    lab = QLabel()
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignCenter)
    if not pm.isNull():
        lab.setPixmap(pm)
    else:
        lab.setText(fallback[:2] or "?")
        theme.mark(lab, chip="muted")
    if tooltip:
        lab.setToolTip(tooltip)
    return lab


def _frame(name: str = "card", **props) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    if props:
        theme.mark(f, **props)
    return f


def _chip(text: str, kind: str = "muted") -> QLabel:
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    theme.mark(lab, chip=kind)
    return lab


class _ClickableTile(QFrame):
    clicked = Signal()

    def __init__(self, name: str = "itemTile", **props):
        super().__init__()
        self.setObjectName(name)
        self.setCursor(Qt.PointingHandCursor)
        if props:
            theme.mark(self, **props)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class BuildsBoard(QWidget):
    """「出装与加点」页的组件化卡片面板。

    - 未选英雄：欢迎能力卡片 + 8 个带真实头像的高胜率热门英雄快捷卡；
    - 已选英雄：核心三件路线卡 + 召唤师技能/加点/鞋/出门装卡 + 可点击模拟已购的商店单件推荐网；
    - 常驻下方：敌方 5 人阵容分析与规则抗性建议卡 + 选人队友 ID 卡片（确保新功能随时可见、可体验）。
    """

    hero_picked = Signal(str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._manual_owned: set[str] = set()
        self._enemy_completer_ready = False
        self._enemy_names: dict[str, str] = {}
        self._last_sig = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(12)

        # 1) 动态主区（未选英雄引导 / 已选英雄核心三件 + 技能/鞋/出门装 + 商店单件网）
        self._hero_zone = QWidget()
        self._hero_zone.setObjectName("page")
        self._hero_zone.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._hero_lay = QVBoxLayout(self._hero_zone)
        self._hero_lay.setContentsMargins(0, 0, 0, 0)
        self._hero_lay.setSpacing(12)
        root.addWidget(self._hero_zone)

        # 2) 常驻：敌方阵容分析 & 抗性建议交互卡
        self.enemy_card = _frame("card")
        ec_lay = QVBoxLayout(self.enemy_card)
        ec_lay.setContentsMargins(14, 12, 14, 12)
        ec_lay.setSpacing(10)

        ec_head = QHBoxLayout()
        ec_head.setSpacing(6)
        ec_title = QLabel("<b style='font-size:14px'>敌方阵容分析与抗性建议</b>")
        ec_title.setTextFormat(Qt.RichText)
        ec_head.addWidget(ec_title)
        ec_head.addWidget(_chip("规则推荐 · 非统计结论", "warn"))
        ec_head.addStretch(1)
        for preset_name, preset_ids in ENEMY_PRESETS:
            b = theme.mark(QPushButton(preset_name), filter=True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, ids=list(preset_ids): self._apply_enemy_preset(ids))
            ec_head.addWidget(b)
        self.btn_clear_enemies = theme.mark(QPushButton("清空"), ghost=True)
        self.btn_clear_enemies.clicked.connect(self._clear_enemies)
        ec_head.addWidget(self.btn_clear_enemies)
        ec_lay.addLayout(ec_head)

        # 敌方 5 槽位 + 快捷搜索添加框
        slots_row = QHBoxLayout()
        slots_row.setSpacing(8)
        self._enemy_slots_lay = QHBoxLayout()
        self._enemy_slots_lay.setSpacing(8)
        slots_row.addLayout(self._enemy_slots_lay)
        slots_row.addStretch(1)
        self.enemy_search = QLineEdit()
        self.enemy_search.setPlaceholderText("+ 添加敌方英雄（回车）")
        self.enemy_search.setFixedWidth(185)
        self.enemy_search.returnPressed.connect(self._add_enemy_from_search)
        slots_row.addWidget(self.enemy_search)
        ec_lay.addLayout(slots_row)

        self._enemy_summary = QLabel()
        self._enemy_summary.setTextFormat(Qt.RichText)
        self._enemy_summary.setWordWrap(True)
        ec_lay.addWidget(self._enemy_summary)

        self._enemy_rules_box = QWidget()
        self._enemy_rules_box.setObjectName("page")
        self._enemy_rules_lay = QHBoxLayout(self._enemy_rules_box)
        self._enemy_rules_lay.setContentsMargins(0, 0, 0, 0)
        self._enemy_rules_lay.setSpacing(8)
        ec_lay.addWidget(self._enemy_rules_box)
        root.addWidget(self.enemy_card)

        # 3) 常驻：选人队友 ID 识别卡（平时可见状态，进入选人界面自动填充，可微调并一键复制）
        self.mates_card = _frame("card")
        mc_lay = QVBoxLayout(self.mates_card)
        mc_lay.setContentsMargins(14, 10, 14, 10)
        mc_lay.setSpacing(8)
        mc_head = QHBoxLayout()
        mc_head.setSpacing(8)
        mc_head.addWidget(QLabel("<b style='font-size:14px'>选人队友 ID 识别</b>"))
        self._mates_status_chip = _chip("待机 · 进选人自动扫描", "muted")
        mc_head.addWidget(self._mates_status_chip)
        mc_head.addStretch(1)
        self.btn_mates_rescan = theme.mark(QPushButton("重扫"), ghost=True)
        self.btn_mates_rescan.clicked.connect(self.engine.rescan_teammates)
        self.btn_mates_copy = theme.mark(QPushButton("复制全部 ID"), pill=True)
        self.btn_mates_copy.clicked.connect(self._copy_mates)
        mc_head.addWidget(self.btn_mates_rescan)
        mc_head.addWidget(self.btn_mates_copy)
        mc_lay.addLayout(mc_head)
        self.mates_edit = QLineEdit()
        self.mates_edit.setPlaceholderText("进入大乱斗选人后自动读取左下角聊天框队友 ID（支持手动微调后一键复制）")
        mc_lay.addWidget(self.mates_edit)
        self._last_mates_tuple: tuple[str, ...] = ()
        root.addWidget(self.mates_card)

        root.addStretch(1)

    def _ensure_enemy_completer(self) -> None:
        if self._enemy_completer_ready or not getattr(self.engine.store, "heroes", None):
            return
        comp, self._enemy_names = hero_completer(self.engine.store, self)
        comp.activated.connect(self._add_enemy_text)
        comp.popup().setObjectName("heroPopup")
        self.enemy_search.setCompleter(comp)
        self._enemy_completer_ready = True

    def _add_enemy_text(self, text: str) -> None:
        hid = self._enemy_names.get(text) or self.engine.store.resolve_hero(text)
        self.enemy_search.clear()
        if not hid:
            return
        cur = [h["hero_id"] for h in ((self.engine.snapshot().get("enemies") or {}).get("heroes") or [])]
        if str(hid) not in cur:
            cur = (cur + [str(hid)])[:5]
            self.engine.set_enemies(cur, source="manual")
            self._last_sig = None
            self.refresh_from(self.engine.snapshot())

    def _add_enemy_from_search(self) -> None:
        t = self.enemy_search.text().strip()
        if t:
            self._add_enemy_text(t)

    def _remove_enemy(self, hid: str) -> None:
        cur = [h["hero_id"] for h in ((self.engine.snapshot().get("enemies") or {}).get("heroes") or []) if h["hero_id"] != hid]
        self.engine.set_enemies(cur or None, source="manual")
        self._last_sig = None
        self.refresh_from(self.engine.snapshot())

    def _apply_enemy_preset(self, ids: list[str]) -> None:
        self.engine.set_enemies(ids, source="manual")
        self._last_sig = None
        self.refresh_from(self.engine.snapshot())

    def _clear_enemies(self) -> None:
        self.engine.set_enemies(None)
        self._last_sig = None
        self.refresh_from(self.engine.snapshot())

    def _toggle_owned(self, item_id: str) -> None:
        sid = str(item_id)
        if sid in self._manual_owned:
            self._manual_owned.remove(sid)
        else:
            self._manual_owned.add(sid)
        self._last_sig = None
        self.refresh_from(self.engine.snapshot())

    def _clear_owned(self) -> None:
        self._manual_owned.clear()
        self._last_sig = None
        self.refresh_from(self.engine.snapshot())

    def _copy_mates(self) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        raw = self.mates_edit.text().strip()
        names = [p.strip() for p in raw.replace("、", ",").replace("，", ",").split(",") if p.strip()]
        if not names:
            return
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText("\n".join(names))
        self.btn_mates_copy.setText("已复制")
        QTimer.singleShot(1500, lambda: self.btn_mates_copy.setText("复制全部 ID"))

    def invalidate(self) -> None:
        self._last_sig = None

    def refresh_from(self, snap: dict, panel_data: dict | None = None) -> None:
        self._ensure_enemy_completer()
        # 实时更新队友 ID 卡片（独立于英雄缓存键，确保选人阶段实时刷新）
        cs = snap.get("champ_select") or {}
        mates = [m for m in (cs.get("teammates") or []) if m.get("raw_name")]
        m_tuple = tuple(m["raw_name"] for m in mates)
        if m_tuple:
            st = cs.get("teammates_status")
            self._mates_status_chip.setText(f"已识别 {len(m_tuple)} 人" + (" · 已缓存" if st == "cached" else " · 扫描中"))
            self._mates_status_chip.setProperty("chip", "good" if st == "cached" else "accent")
            if m_tuple != self._last_mates_tuple and not self.mates_edit.hasFocus():
                self._last_mates_tuple = m_tuple
                self.mates_edit.setText(", ".join(m_tuple))
            self.btn_mates_copy.setEnabled(True)
        else:
            self._mates_status_chip.setText("待机 · 进选人自动扫描" if snap.get("settings", {}).get("teammate_ocr", True) else "已在设置中关闭")
            self._mates_status_chip.setProperty("chip", "muted")
            self.btn_mates_copy.setEnabled(bool(self.mates_edit.text().strip()))
        if self._mates_status_chip.style():
            self._mates_status_chip.style().unpolish(self._mates_status_chip)
            self._mates_status_chip.style().polish(self._mates_status_chip)
        hid = snap.get("hero_id")
        show_win = snap.get("settings", {}).get("show_winrate", True)
        enemy_rules_on = snap.get("settings", {}).get("enemy_rules", True)
        if panel_data is None and hid:
            panel_data = self.engine.hero_panel(hid)
        enemies = snap.get("enemies")
        enemy_ids = tuple(h["hero_id"] for h in ((enemies or {}).get("heroes") or []))
        live_owned = tuple((snap.get("shop") or {}).get("owned_items") or ())
        dd = snap.get("data") or {}
        sig = (
            hid,
            (panel_data or {}).get("data_revision"),
            (panel_data or {}).get("official_revision"),
            self.engine.icons.version if getattr(self.engine, "icons", None) else 0,
            dd.get("band_effective"),
            show_win,
            enemy_rules_on,
            enemy_ids,
            live_owned,
            tuple(sorted(self._manual_owned)),
            theme.current_mode(),
        )
        if sig == self._last_sig:
            return
        self._last_sig = sig

        _clear_layout(self._hero_lay)
        if panel_data and hid:
            self._build_hero_cards(hid, panel_data, show_win, live_owned)
        else:
            self._build_empty_cards()
        self._render_enemy_card(enemies, panel_data, show_win, enemy_rules_on)
        self._hero_zone.adjustSize()
        self._hero_zone.updateGeometry()
        self.updateGeometry()
        self.adjustSize()

    def _build_empty_cards(self) -> None:
        hero_box = _frame("card")
        hl = QVBoxLayout(hero_box)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(10)
        head = QLabel(
            f"<b style='font-size:15px'>开始使用海克斯精密仪</b> "
            f"<span style='color:{theme.MUTED}'>· 选一个英雄立刻预览完整出装、单件选取率、海克斯榜单与敌方抗性规则</span>"
        )
        head.setTextFormat(Qt.RichText)
        head.setWordWrap(True)
        hl.addWidget(head)

        cap_row = QHBoxLayout()
        cap_row.setSpacing(8)
        for title, desc in (
            ("选人自动识别", "英雄胜率评级 + 聊天框队友 ID"),
            ("商店装备框选", "4K/1080p 动态定位 49 格 + 已购"),
            ("敌方抗性规则", "读条识别或下方点选实时计算"),
            ("海克斯三选一", "浮窗毫秒级标注首选与 Δ胜率"),
        ):
            sc = _frame("subcard")
            sl = QVBoxLayout(sc)
            sl.setContentsMargins(10, 8, 10, 8)
            sl.setSpacing(2)
            sl.addWidget(QLabel(f"<b>{title}</b>"))
            dlab = theme.mark(QLabel(desc), muted=True)
            dlab.setWordWrap(True)
            sl.addWidget(dlab)
            cap_row.addWidget(sc, 1)
        hl.addLayout(cap_row)

        if hasattr(self.engine, "search_heroes"):
            top = self.engine.search_heroes("", limit=8)
            if top:
                sub = theme.mark(QLabel("当前版本高胜率热门英雄（点击立即进入详情）"), muted=True)
                hl.addWidget(sub)
                grid = QGridLayout()
                grid.setSpacing(8)
                for idx, h in enumerate(top[:8]):
                    pm = hero_pixmap(self.engine.store, self.engine.icons, h["id"], size=34, radius=8)
                    grade = f"[{h['grade']}] " if h.get("grade") else ""
                    w_txt = f"  {_pct(h.get('win'))}" if h.get("win") is not None else ""
                    btn = theme.mark(QPushButton(f"{grade}{h['name']}{w_txt}"), heroTile=True)
                    if not pm.isNull():
                        btn.setIcon(QIcon(pm))
                        btn.setIconSize(pm.size())
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.clicked.connect(lambda _=False, cid=h["id"]: self.hero_picked.emit(str(cid)))
                    grid.addWidget(btn, idx // 4, idx % 4)
                hl.addLayout(grid)
        self._hero_lay.addWidget(hero_box)

    def _build_hero_cards(self, hid: str, d: dict, show_win: bool, live_owned: tuple[str, ...]) -> None:
        merged_owned = list(dict.fromkeys(list(live_owned) + sorted(self._manual_owned)))
        rec = self.engine.shop_recommendations(hid, owned_items=merged_owned) if hasattr(self.engine, "shop_recommendations") else None
        next_id = (rec or {}).get("next_recommended_id")
        owned_set = set(merged_owned)

        # ---- Row 1：左侧核心三件路线 + 右侧召唤师技能/加点/鞋/出门装 ----
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # 左卡：核心三件
        core_card = _frame("card")
        core_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        cl = QVBoxLayout(core_card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        ch = QHBoxLayout()
        ch.addWidget(QLabel("<b style='font-size:14px'>核心三件路线</b>"))
        if d.get("core_band"):
            ch.addWidget(_chip(str(d["core_band"]), "accent"))
        ch.addStretch(1)
        cl.addLayout(ch)

        cores = (d.get("builds") or {}).get("core") or []
        if cores:
            for idx, c in enumerate(cores[:3]):
                row_f = _frame("subcard")
                row_f.setMinimumHeight(48)
                rl = QHBoxLayout(row_f)
                rl.setContentsMargins(10, 7, 10, 7)
                rl.setSpacing(6)
                rl.addWidget(_chip(f"#{idx + 1}", "good" if idx == 0 else "muted"))
                sep = "→" if c.get("ordered") is True else "+"
                items = c.get("items") or []
                for j, it in enumerate(items):
                    if j > 0:
                        arr = theme.mark(QLabel(sep), muted=True)
                        rl.addWidget(arr)
                    pm = item_pixmap(self.engine.icons, it.get("id"), it.get("icon"), size=34, radius=7)
                    tip = it.get("name") or str(it.get("id") or "")
                    rl.addWidget(_icon_label(pm, 34, tip, tip))
                rl.addStretch(1)
                if show_win and c.get("win") is not None:
                    w_val = c["win"]
                    rl.addWidget(_chip(f"胜率 {_pct(w_val)}", "good" if w_val >= 0.53 else "accent"))
                cl.addWidget(row_f)
        else:
            cl.addWidget(theme.mark(QLabel("暂无核心三件统计"), muted=True))
        cl.addStretch(1)
        top_row.addWidget(core_card, 11)

        # 右卡：召唤师技能 + 加点 + 鞋子 + 出门装
        quick_card = _frame("card")
        quick_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        ql = QVBoxLayout(quick_card)
        ql.setContentsMargins(14, 12, 14, 12)
        ql.setSpacing(10)
        qtitle = QLabel("<b style='font-size:14px'>技能加点 · 召唤师技能 · 鞋与出门</b>")
        qtitle.setMinimumHeight(22)
        ql.addWidget(qtitle)

        # 技能加点徽章
        sk = d.get("skills") or []
        mx = [k for k in (sk[0].get("max") or []) if k in "QWE"] if sk else []
        if mx:
            all_keys = mx + [k for k in ("Q", "W", "E") if k not in mx]
            sk_wrap = QWidget()
            sk_wrap.setObjectName("page")
            sk_wrap.setMinimumHeight(30)
            sk_row = QHBoxLayout(sk_wrap)
            sk_row.setContentsMargins(0, 0, 0, 0)
            sk_row.setSpacing(6)
            sk_row.addWidget(theme.mark(QLabel("主副加点"), muted=True))
            for idx, k in enumerate(all_keys[:3]):
                if idx > 0:
                    sk_row.addWidget(theme.mark(QLabel(">"), muted=True))
                klab = QLabel(k)
                klab.setAlignment(Qt.AlignCenter)
                theme.mark(klab, skill="primary" if idx == 0 else "secondary" if idx == 1 else "normal")
                sk_row.addWidget(klab)
            if show_win and sk[0].get("win") is not None:
                sk_row.addWidget(_chip(f"胜率 {_pct(sk[0]['win'])}", "good"))
            sk_row.addStretch(1)
            ql.addWidget(sk_wrap)

        # 召唤师技能组合
        sums = (d.get("summoners") or [])[:2]
        if sums:
            for srow in sums:
                sr_wrap = QWidget()
                sr_wrap.setObjectName("page")
                sr_wrap.setMinimumHeight(30)
                sr = QHBoxLayout(sr_wrap)
                sr.setContentsMargins(0, 0, 0, 0)
                sr.setSpacing(6)
                for sp in srow.get("spells") or []:
                    pm = spell_pixmap(self.engine.icons, sp.get("id"), sp.get("icon"), size=26, radius=6)
                    sr.addWidget(_icon_label(pm, 26, sp.get("name", ""), sp.get("name", "")))
                stat = (f"胜率 {_pct(srow.get('win'))} · " if show_win else "") + f"出场 {_pct(srow.get('pick'))}"
                sr.addWidget(theme.mark(QLabel(stat), secondary=True))
                sr.addStretch(1)
                ql.addWidget(sr_wrap)

        # 鞋子 + 出门装
        b = d.get("builds") or {}
        bs_wrap = QWidget()
        bs_wrap.setObjectName("page")
        bs_wrap.setMinimumHeight(32)
        bs_row = QHBoxLayout(bs_wrap)
        bs_row.setContentsMargins(0, 0, 0, 0)
        bs_row.setSpacing(10)
        shoes = (b.get("shoes") or [])[:2]
        if shoes:
            sh_box = QHBoxLayout()
            sh_box.setSpacing(5)
            sh_box.addWidget(theme.mark(QLabel("鞋子"), muted=True))
            for sh in shoes:
                it = sh.get("item") or {}
                pm = item_pixmap(self.engine.icons, it.get("id"), it.get("icon"), size=28, radius=6)
                sh_box.addWidget(_icon_label(pm, 28, it.get("name", ""), it.get("name", "")))
                if show_win and sh.get("win") is not None:
                    sh_box.addWidget(theme.mark(QLabel(_pct(sh["win"])), muted=True))
            bs_row.addLayout(sh_box)
        starts = b.get("start") or []
        if starts:
            st_box = QHBoxLayout()
            st_box.setSpacing(5)
            st_box.addWidget(theme.mark(QLabel("出门"), muted=True))
            for it in (starts[0].get("items") or [])[:3]:
                pm = item_pixmap(self.engine.icons, it.get("id"), it.get("icon"), size=28, radius=6)
                st_box.addWidget(_icon_label(pm, 28, it.get("name", ""), it.get("name", "")))
            if show_win and starts[0].get("win") is not None:
                st_box.addWidget(theme.mark(QLabel(_pct(starts[0]["win"])), muted=True))
            bs_row.addLayout(st_box)
        bs_row.addStretch(1)
        ql.addWidget(bs_wrap)
        ql.addStretch(1)
        top_row.addWidget(quick_card, 10)
        self._hero_lay.addLayout(top_row)

        # ---- Row 2：商店单件推荐 & 已购进度互动卡 ----
        items_list = (rec or {}).get("items") or []
        if items_list:
            shop_card = _frame("card")
            shop_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            sl = QVBoxLayout(shop_card)
            sl.setContentsMargins(14, 12, 14, 12)
            sl.setSpacing(10)
            sh = QHBoxLayout()
            sh.setSpacing(8)
            sh.addWidget(QLabel("<b style='font-size:14px'>商店装备推荐与已购顺位</b>"))
            next_name = next((it.get("name") for it in items_list if str(it["item_id"]) == str(next_id)), None)
            if next_name:
                sh.addWidget(_chip(f"下一件推荐：{next_name}", "good"))
            if live_owned:
                sh.addWidget(_chip(f"局内已购 {len(live_owned)} 件", "accent"))
            else:
                sh.addWidget(theme.mark(QLabel("点击装备卡可模拟已购，局内开商店自动同步"), muted=True))
            sh.addStretch(1)
            if self._manual_owned:
                btn_rst = theme.mark(QPushButton("重置模拟已购"), ghost=True)
                btn_rst.clicked.connect(self._clear_owned)
                sh.addWidget(btn_rst)
            sl.addLayout(sh)

            grid = QGridLayout()
            grid.setSpacing(8)
            for idx, it in enumerate(items_list[:8]):
                iid = str(it["item_id"])
                is_owned = iid in owned_set or bool(it.get("owned"))
                is_next = bool(next_id and iid == str(next_id) and not is_owned)
                is_rule = it.get("source") == "rule" and not is_owned
                tile = _ClickableTile(
                    "itemTile",
                    owned=is_owned,
                    next=is_next,
                    rule=is_rule,
                )
                tile.setMinimumHeight(88)
                tile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                tile.clicked.connect(lambda cid=iid: self._toggle_owned(cid))
                tl = QVBoxLayout(tile)
                tl.setContentsMargins(9, 8, 9, 8)
                tl.setSpacing(5)

                top_t = QHBoxLayout()
                top_t.setSpacing(8)
                pm = item_pixmap(self.engine.icons, iid, it.get("icon"), size=34, radius=7)
                top_t.addWidget(_icon_label(pm, 34, it.get("name", ""), it.get("name", "")))
                meta_v = QVBoxLayout()
                meta_v.setSpacing(2)
                name_lab = QLabel(f"<b>{escape(it.get('name') or iid)}</b>")
                name_lab.setTextFormat(Qt.RichText)
                meta_v.addWidget(name_lab)
                badge_txt, badge_kind = (
                    ("✓ 已购", "accent") if is_owned else
                    (f"#{it['order']} 推荐" if it.get("order") else "推荐", "good") if is_next else
                    ("规则建议", "warn") if is_rule else
                    (f"核心 #{it['order']}", "accent") if it.get("order") else
                    ("常出", "muted")
                )
                meta_v.addWidget(_chip(badge_txt, badge_kind), 0, Qt.AlignLeft)
                top_t.addLayout(meta_v, 1)
                tl.addLayout(top_t)

                pick = float(it.get("pick") or 0.0)
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(min(100, int(round(pick * 100))))
                bar.setTextVisible(False)
                theme.mark(bar, thin=True)
                tl.addWidget(bar)

                stat_str = f"选取 {_pct(pick)}" + (f" · 胜率 {_pct(it.get('win'))}" if show_win and it.get("win") is not None else "")
                tl.addWidget(theme.mark(QLabel(stat_str), muted=True))
                grid.addWidget(tile, idx // 4, idx % 4)
            sl.addLayout(grid)
            self._hero_lay.addWidget(shop_card)

    def _render_enemy_card(self, enemies: dict | None, panel_data: dict | None, show_win: bool, rules_on: bool) -> None:
        _clear_layout(self._enemy_slots_lay)
        _clear_layout(self._enemy_rules_lay)
        heroes = (enemies or {}).get("heroes") or []
        for idx in range(5):
            slot = _frame("enemySlot", filled=(idx < len(heroes)))
            slot.setFixedSize(48, 48)
            sl = QVBoxLayout(slot)
            sl.setContentsMargins(3, 3, 3, 3)
            if idx < len(heroes):
                eh = heroes[idx]
                ehid = str(eh["hero_id"])
                ename = eh.get("name") or ehid
                pm = hero_pixmap(self.engine.store, self.engine.icons, ehid, size=40, radius=7)
                btn = QPushButton()
                btn.setFlat(True)
                btn.setFixedSize(42, 42)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(f"{ename}（点击移除）")
                if not pm.isNull():
                    btn.setIcon(QIcon(pm))
                    btn.setIconSize(pm.size())
                else:
                    btn.setText(ename[:2])
                btn.clicked.connect(lambda _=False, cid=ehid: self._remove_enemy(cid))
                sl.addWidget(btn)
            else:
                plus = theme.mark(QLabel("+"), muted=True)
                plus.setAlignment(Qt.AlignCenter)
                sl.addWidget(plus)
            self._enemy_slots_lay.addWidget(slot)

        self.btn_clear_enemies.setVisible(bool(heroes))
        if not heroes:
            self._enemy_summary.setText(
                f"<span style='color:{theme.MUTED}'>进对局读条时自动识别敌方 5 人；"
                f"现在也可以点右上角 <b>多法伤 / 多物理 / 多坦克 / 多回血</b> 预设或在右侧添加敌方英雄立刻体验规则推荐。</span>"
            )
            self._enemy_rules_box.hide()
            return

        prof = (enemies or {}).get("profile") or {}
        tags = prof.get("tags") or []
        names = "、".join(escape(h.get("name") or h["hero_id"]) for h in heroes)
        counts = f"法伤 {prof.get('ap_count', 0)} · 物理 {prof.get('ad_count', 0)} · 坦克 {prof.get('tank_count', 0)} · 回复 {prof.get('heal_count', 0)}"
        tag_html = " ".join(f"<b style='color:{theme.WARN}'>[{escape(t)}]</b>" for t in tags)
        self._enemy_summary.setText(f"<b>敌方阵容：</b>{names}　<span style='color:{theme.MUTED}'>{counts}</span> {tag_html}")

        rules = (panel_data or {}).get("rule_adjustments") or []
        if not rules_on:
            self._enemy_rules_box.show()
            self._enemy_rules_lay.addWidget(theme.mark(QLabel("已在设置中关闭「按敌方阵容规则提示抗性装备」"), muted=True))
            return
        if not panel_data:
            self._enemy_rules_box.show()
            self._enemy_rules_lay.addWidget(theme.mark(QLabel("选择我方英雄后，这里会结合该英雄常出装给出针对性抗性建议"), muted=True))
            return
        if not rules:
            self._enemy_rules_box.show()
            self._enemy_rules_lay.addWidget(theme.mark(QLabel("当前敌方伤害构成较均衡，按上方常规核心出装即可"), muted=True))
            return

        self._enemy_rules_box.show()
        for r in rules[:3]:
            rc = _frame("ruleCard")
            rl = QHBoxLayout(rc)
            rl.setContentsMargins(10, 8, 10, 8)
            rl.setSpacing(8)
            iid = str(r.get("item_id") or "")
            pm = item_pixmap(self.engine.icons, iid, r.get("icon"), size=34, radius=7)
            rl.addWidget(_icon_label(pm, 34, r.get("name", ""), r.get("name", "")))
            tv = QVBoxLayout()
            tv.setSpacing(2)
            tv.addWidget(QLabel(f"<b style='color:{theme.WARN}'>{escape(r.get('name') or iid)}</b>"))
            extra = f" · 胜率 {_pct(r.get('base_win'))}" if show_win and r.get("base_win") is not None else ""
            tv.addWidget(theme.mark(QLabel(f"持有 {_pct(r.get('base_pick'))}{extra}"), muted=True))
            reason = r.get("rule_reason") or ""
            if reason:
                rlab = theme.mark(QLabel(reason), secondary=True)
                rlab.setWordWrap(True)
                tv.addWidget(rlab)
            rl.addLayout(tv, 1)
            self._enemy_rules_lay.addWidget(rc, 1)


class AugmentsBoard(QWidget):
    """「海克斯选择」页下半部分：当前英雄按棱彩 / 黄金 / 白银筛选的推荐海克斯卡片榜。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rarity = "all"
        self._augments: list[dict] = []
        self._hero_name = ""
        self._show_win = True
        self._last_sig = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._title = QLabel("<b style='font-size:14px'>当前英雄推荐海克斯榜单</b>")
        self._title.setTextFormat(Qt.RichText)
        head.addWidget(self._title)
        head.addStretch(1)
        self._filter_btns: dict[str, QPushButton] = {}
        for code, text in (("all", "全部"), ("prismatic", "棱彩"), ("gold", "黄金"), ("silver", "白银")):
            btn = theme.mark(QPushButton(text), filter=True, active=(code == "all"))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, c=code: self._set_rarity(c))
            head.addWidget(btn)
            self._filter_btns[code] = btn
        lay.addLayout(head)

        self._grid_wrap = QWidget()
        self._grid_wrap.setObjectName("page")
        self._grid = QGridLayout(self._grid_wrap)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        lay.addWidget(self._grid_wrap)

    def _set_rarity(self, code: str) -> None:
        self._rarity = code
        for c, btn in self._filter_btns.items():
            btn.setProperty("active", c == code)
            if btn.style():
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        self._last_sig = None
        self._rebuild()

    def set_data(self, hero_name: str, augments: list[dict], show_win: bool) -> None:
        sig = (hero_name, len(augments), self._rarity, show_win, theme.current_mode(),
               tuple((a.get("name"), a.get("delta")) for a in augments[:6]))
        if sig == self._last_sig:
            return
        self._last_sig = sig
        self._hero_name = hero_name
        self._augments = list(augments)
        self._show_win = show_win
        self._rebuild()

    def _rebuild(self) -> None:
        _clear_layout(self._grid)
        if not self._augments:
            self._title.setText("<b style='font-size:14px'>英雄推荐海克斯榜单</b>")
            self._grid.addWidget(theme.mark(QLabel("选择英雄后，这里会展示该英雄各阶梯（棱彩 / 黄金 / 白银）高胜率增幅海克斯"), muted=True), 0, 0)
            return
        self._title.setText(f"<b style='font-size:14px'>{escape(self._hero_name)} · 推荐海克斯榜单</b>")
        rows = [
            a for a in self._augments
            if a.get("delta") is not None and a.get("sample") != "low"
            and (self._rarity == "all" or a.get("rarity") == self._rarity)
        ]
        rows.sort(key=lambda a: -float(a["delta"]))
        if not rows:
            self._grid.addWidget(theme.mark(QLabel("该稀有度暂无足够样本的推荐海克斯"), muted=True), 0, 0)
            return
        for idx, a in enumerate(rows[:10]):
            card = _frame("augCard")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            cl.setSpacing(8)
            rar = a.get("rarity") or ""
            r_kind = "prism" if rar == "prismatic" else "warn" if rar == "gold" else "muted"
            cl.addWidget(_chip(RARITY_CN.get(rar, "海克斯"), r_kind))
            nv = QVBoxLayout()
            nv.setSpacing(1)
            nv.addWidget(QLabel(f"<b>{escape(a.get('name') or '')}</b>"))
            sub = f"梯队 {a['tier']}" if a.get("tier") else ""
            if self._show_win and a.get("win") is not None:
                sub += (" · " if sub else "") + f"胜率 {_pct(a['win'])}"
            if sub:
                nv.addWidget(theme.mark(QLabel(sub), muted=True))
            cl.addLayout(nv, 1)
            delta = float(a["delta"])
            d_kind = "good" if delta >= 1.0 else "accent" if delta >= 0 else "bad"
            cl.addWidget(_chip(f"{delta:+.1f}%", d_kind))
            self._grid.addWidget(card, idx // 2, idx % 2)
