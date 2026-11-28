"""Batch 2 端到端测试：E1 选人队友 ID、C 加载页敌方识别、B 商店装备框选与 ShopLayer 绘制。"""
from __future__ import annotations

import base64
import os
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lolhex.config import Settings
from lolhex.data.icons import bundled_icons
from lolhex.engine import Engine
from lolhex.vision import loading, portraits, shop, teammates
from lolhex.vision.ocr import TextLine


def _paste(canvas: np.ndarray, icon: np.ndarray, rel_box: tuple[float, float, float, float]) -> None:
    h, w = canvas.shape[:2]
    x0, y0, x1, y1 = [int(v * s) for v, s in zip(rel_box, (w, h, w, h))]
    canvas[y0:y1, x0:x1] = cv2.resize(icon, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)


# ==================== E1：选人聊天框队友 ID ====================


def test_teammates_parse_multiframe_vote_and_freeze(tmp_path):
    lines_f1 = [
        TextLine("暗影岛茶话会 # 5120 加入了房间", 0.96, (0, 0, 100, 20)),
        TextLine("[12:03] 大乱斗只玩软辅#8842 加入了大厅", 0.92, (0, 22, 100, 42)),
        TextLine("Il1O0易错名#2049 加入了房间", 0.74, (0, 44, 100, 64)),
        TextLine("PlayerFour#9999 joined the lobby", 0.91, (0, 66, 100, 86)),
        TextLine("暗影岛茶话会：这把打团", 0.98, (0, 88, 100, 108)),  # 普通聊天应忽略
    ]
    lines_f2 = [
        TextLine("暗影岛茶话会#5120 加入了房间", 0.97, (0, 0, 100, 20)),
        TextLine("大乱斗只玩软辅#8842 加入了大厅", 0.94, (0, 22, 100, 42)),
        TextLine("I1100易错名#2049 加入了房间", 0.78, (0, 44, 100, 64)),  # l/I/1 与 0/O 轻微抖动应归并
        TextLine("PlayerFour#9999 joined the lobby", 0.93, (0, 66, 100, 86)),
    ]

    eng = Engine(Settings(check_data_updates=False), home=tmp_path)
    img = np.zeros((1080, 1920, 3), np.uint8)
    calls = []

    def fake_detect(_crop):
        calls.append(1)
        return lines_f1 if len(calls) == 1 else lines_f2

    mates1, st1 = eng.scan_teammates(img, detect=fake_detect)
    assert st1 == "scanning" and len(mates1) == 4
    assert mates1[0]["raw_name"] == "暗影岛茶话会#5120"
    assert mates1[2]["uncertain"] is True
    assert all(m["rating"] is None for m in mates1)

    # 验证小字增强预处理：2× 放大与对比度拉伸
    raw_chat = np.full((60, 120, 3), 20, np.uint8)
    raw_chat[20:40, 20:100] = 180
    up = teammates.preprocess_chat(raw_chat, scale=2.0)
    assert up.shape == (120, 240, 3) and int(up.max()) == 255 and int(up.min()) == 0

    mates2, st2 = eng.scan_teammates(img, detect=fake_detect)
    assert st2 == "cached" and len(mates2) == 4 and len(calls) == 2

    # 冻结后继续调用：零 OCR 消耗
    mates3, st3 = eng.scan_teammates(img, detect=fake_detect)
    assert st3 == "cached" and mates3 == mates2 and len(calls) == 2

    # rescan_teammates 后重新扫描
    eng.rescan_teammates()
    _, st4 = eng.scan_teammates(img, detect=fake_detect)
    assert st4 == "scanning" and len(calls) == 3

    # 国服实机 OCR 容错：「聊大」错字与 WeGame 带 #编号 发言前缀
    assert teammates.parse_join_line("听过许多大道理#72642加入了队伍聊大") == "听过许多大道理#72642"
    assert teammates.parse_join_line("生气了吗没有啊#61717：101资料站-沃利贝尔海克斯") == "生气了吗没有啊#61717"
    assert teammates.parse_join_line("NWS、CRanZz1Y #67629：101资料站-韦鲁斯") == "NWS、CRanZz1Y#67629"
    assert teammates.parse_join_line("普通玩家：不带编号的闲聊") is None


# ==================== C：加载界面敌方 5 人识别 ====================


def test_loading_enemies_portrait_match_and_rule_activation(tmp_path):
    eng = Engine(Settings(check_data_updates=False), home=tmp_path)
    eng.set_hero("103")  # 阿狸
    bundled_h = portraits.hero_icons()
    # 3 AP + 1 Tank + 1 Marksman：拉克丝 99、布兰德 63、辛德拉 134、奥恩 516、凯特琳 51
    enemy_ids = ["99", "63", "134", "516", "51"]
    bank_icons = {}
    for hid in enemy_ids:
        alias = eng.store.heroes[hid]["alias"]
        img = cv2.imdecode(np.frombuffer(bundled_h[alias], np.uint8), cv2.IMREAD_COLOR)
        assert img is not None
        bank_icons[hid] = img
    eng._icon_bank = portraits.IconBank(bank_icons)

    frame = np.zeros((1080, 1920, 3), np.uint8)
    for hid, box in zip(enemy_ids, loading.ENEMY_PORTRAITS):
        _paste(frame, bank_icons[hid], box)

    # 第 1 帧记录投票，第 2 帧确认锁定并写入 enemies
    assert eng.scan_loading_enemies(frame) is None
    profile = eng.scan_loading_enemies(frame)
    assert profile is not None
    assert profile["source"] == "loading_ocr"
    assert [h["hero_id"] for h in profile["heroes"]] == enemy_ids
    assert profile["profile"]["ap_count"] == 3

    # 自动联动规则出装并显式带非统计声明
    rec = eng.shop_recommendations("103")
    assert rec and rec["rule_adjustments"]
    assert all(r["source"] == "rule" and "非统计" in r["disclaimer"] for r in rec["rule_adjustments"])


def test_loading_enemies_falls_back_to_name_reader():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    names = ["99", "63", "134", "516", "51"]
    it = iter(names)
    found = loading.read_enemies(frame, bank=None, name_reader=lambda _crop: next(it, None))
    assert found == names


# ==================== B：商店装备识别 + ShopLayer 绘制 ====================


def test_shop_item_bank_engine_scan_and_shoplayer_paint(tmp_path, monkeypatch):
    PySide6 = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtGui import QColor, QImage
    from lolhex.ui.overlay import ShopLayer
    from lolhex.vision import window

    eng = Engine(Settings(check_data_updates=False), home=tmp_path)
    eng.set_hero("103")  # 阿狸
    eng.set_enemies(["99", "63", "134", "516", "51"], source="loading_ocr")

    raw_items = bundled_icons().get("item") or {}
    # 黯炎火炬(2503)、影焰(4645)、灭世者的死亡之帽(3089)、女妖面纱(3102)
    target_ids = ["2503", "4645", "3089", "3102"]
    decoded = {}
    for iid in target_ids:
        assert iid in raw_items
        decoded[iid] = cv2.imdecode(np.frombuffer(base64.b64decode(raw_items[iid]), np.uint8), cv2.IMREAD_COLOR)

    # 合成 1920×1080 商店画面：前 4 格放这 4 件装备，底部装备栏放 2503（模拟已购第 1 件）
    frame = np.zeros((1080, 1920, 3), np.uint8)
    for iid, box in zip(target_ids, shop.DEFAULT_LAYOUT.grid_boxes):
        _paste(frame, decoded[iid], box)
    _paste(frame, decoded["2503"], shop.DEFAULT_LAYOUT.inventory_boxes[0])

    # 锚点识别返回非商店文字 → 判定关闭
    assert eng.scan_shop(frame, anchor_reader=lambda _c: ("战绩面板", 0.9)) is None
    assert eng.snapshot()["shop"] is None

    # 锚点识别返回「商店」→ 识别出 4 个格子 + 已购 2503，自动把下一件推进到 4645，并标出规则推荐 3102
    res = eng.scan_shop(frame, (0, 0), anchor_reader=lambda _c: ("装备商店", 0.95))
    assert res is not None and res["open"] is True
    assert "2503" in res["owned_items"]
    by_id = {s["item_id"]: s for s in res["slots"]}
    assert set(by_id) == set(target_ids)
    assert by_id["2503"]["owned"] is True
    assert by_id["4645"]["is_next"] is True
    assert by_id["3102"]["source"] == "rule"
    assert "非统计" in (by_id["3102"]["disclaimer"] or "")

    # 验证 ShopLayer 透明层能正确渲染绿框（下一件）与琥珀框（规则推荐），且不遮挡图标中心
    app = PySide6.QApplication.instance() or PySide6.QApplication([])
    layer = ShopLayer()
    published = []
    monkeypatch.setattr(window, "set_drawn", lambda key, rects: published.append((key, rects)))
    try:
        layer.update_from(eng.snapshot(), window.Rect(0, 0, 1920, 1080))
        app.processEvents()
        assert layer.isVisible()
        img = QImage(1920, 1080, QImage.Format_ARGB32)
        img.fill(0)
        layer.render(img)
        shop_masks = [rects for key, rects in published if key == "ShopLayer" and rects]
        assert shop_masks and len(shop_masks[-1]) >= 10
        # 4645 格子的上边框应出现绿色像素，3102 格子的上边框应出现琥珀色像素
        bx0, by0, bx1, _ = by_id["4645"]["box"]
        rx0, ry0, rx1, _ = by_id["3102"]["box"]
        c_next = img.pixelColor((bx0 + bx1) // 2, by0 - 2)
        c_rule = img.pixelColor((rx0 + rx1) // 2, ry0 - 2)
        assert c_next.green() > 180 and c_next.alpha() > 200
        assert c_rule.red() > 200 and c_rule.green() > 150 and c_rule.alpha() > 200
    finally:
        layer.close()
        app.processEvents()


def test_mainwindow_shows_and_copies_teammates(tmp_path, monkeypatch):
    PySide6 = pytest.importorskip("PySide6.QtWidgets")
    from lolhex.ui import mainwindow

    app = PySide6.QApplication.instance() or PySide6.QApplication([])
    monkeypatch.setattr(mainwindow.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    eng = Engine(Settings(check_data_updates=False), home=tmp_path)
    eng._set(
        phase="client",
        champ_select={
            "bench": [],
            "team": [],
            "teammates": [
                {"raw_name": "玩家甲#1001", "confidence": 0.95, "frames": 2, "uncertain": False, "rating": None},
                {"raw_name": "玩家乙#2002", "confidence": 0.72, "frames": 1, "uncertain": True, "rating": None},
            ],
            "teammates_status": "cached",
        },
    )
    w = mainwindow.MainWindow(eng, SimpleNamespace(set_visible=lambda *a: None))
    try:
        w.show()
        w.refresh()
        assert w.cs_label.isVisible()
        assert w.teammate_bar.isVisible()
        assert "玩家甲#1001" in w.cs_label.text()
        assert "玩家乙#2002(?)" in w.cs_label.text()
        assert w.copy_teammates() == 2
        assert PySide6.QApplication.clipboard().text() == "玩家甲#1001\n玩家乙#2002"
        # 手工改掉一个 OCR 错字后复制，应复制修正后的文本
        w.teammate_edit.setText("玩家甲#1001, 玩家乙修正#2002")
        assert w.copy_teammates() == 2
        assert PySide6.QApplication.clipboard().text() == "玩家甲#1001\n玩家乙修正#2002"
    finally:
        w.hide()
        w.deleteLater()
        eng.stop()
        app.processEvents()


def test_control_panel_shows_teammates_copy_and_enemy_rules(tmp_path):
    PySide6 = pytest.importorskip("PySide6.QtWidgets")
    from lolhex.ui.overlay import ControlPanel

    app = PySide6.QApplication.instance() or PySide6.QApplication([])
    eng = Engine(Settings(check_data_updates=False), home=tmp_path)
    eng.set_hero("103")
    eng.set_enemies(["99", "1", "63", "516", "51"], source="loading_ocr")
    eng._set(
        phase="client",
        champ_select={
            "bench": [],
            "team": [],
            "teammates": [
                {"raw_name": "听过许多大道理#72642", "confidence": 0.97, "frames": 2, "uncertain": False, "rating": None},
                {"raw_name": "二师兄威武#29987", "confidence": 0.99, "frames": 2, "uncertain": False, "rating": None},
            ],
            "teammates_status": "cached",
        },
    )
    panel = ControlPanel(eng)
    try:
        panel.expanded = True
        panel.update_from(eng.snapshot())
        assert not panel.mate_bar.isHidden()
        assert "听过许多大道理#72642" in panel.mate_label.text()
        assert "阵容提示（规则·非统计）" in panel.info.text()
        panel._copy_teammates()
        assert PySide6.QApplication.clipboard().text() == "听过许多大道理#72642\n二师兄威武#29987"
    finally:
        panel.close()
        panel.deleteLater()
        eng.stop()
        app.processEvents()
