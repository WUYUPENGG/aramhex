"""v2 前后端契约后端第一版测试：配置扩展、单件装备持有率、敌方阵容规则、Engine 联调接口。"""

from __future__ import annotations

import json
from pathlib import Path

from lolhex.config import Settings
from lolhex.data.public import PublicStore
from lolhex.engine import Engine
from lolhex import item_rules


def _real_engine(tmp_path: Path) -> Engine:
    settings = Settings()
    store = PublicStore(tmp_path / "data", check_updates=False)
    return Engine(settings, home=tmp_path, store=store)


def test_settings_v2_defaults_and_validation(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "theme_mode": "invalid",
        "ui_preset": "unknown",
        "shop_overlay": "not_bool",
        "overlay_opacity": 999,
        "overlay_scale": 0.1,
    }), encoding="utf-8")
    s = Settings.load(cfg)
    assert s.theme_mode == "system"
    assert s.ui_preset == "liquid"
    assert s.shop_overlay is True
    assert s.enemy_rules is True
    assert s.teammate_ocr is True
    assert s.overlay_opacity == 100
    assert s.overlay_scale == 0.8

    s.theme_mode = "dark"
    s.ui_preset = "esports"
    s.overlay_opacity = 72
    s.overlay_scale = 1.15
    assert s.save(cfg)
    s2 = Settings.load(cfg)
    assert (s2.theme_mode, s2.ui_preset, s2.overlay_opacity, s2.overlay_scale) == ("dark", "esports", 72, 1.15)


def test_public_shop_item_stats_computes_pick_and_core_order(tmp_path):
    eng = _real_engine(tmp_path)
    stats = eng.store.shop_item_stats("103")  # 阿狸
    assert stats is not None
    assert stats["hero_id"] == "103"
    assert stats["total_games"] > 100000
    assert len(stats["core_order"]) == 3
    assert set(stats["core_order"].values()) == {1, 2, 3}

    items = stats["items"]
    assert len(items) >= 8
    # 前三项应按 core_order 1, 2, 3 排在最前
    assert [it["order"] for it in items[:3]] == [1, 2, 3]
    for it in items[:5]:
        assert 0 < it["pick"] <= 1.0
        assert 0 < it["win"] < 1.0
        assert it["source"] == "stats"
        assert isinstance(it["types"], list)


def test_enemy_rules_ap_heavy_recommends_mr_with_explicit_disclaimer(tmp_path):
    eng = _real_engine(tmp_path)
    eng.set_hero("103")
    # 3 名纯法师（拉克丝 99、安妮 1、布兰德 63）+ 奥恩 516 + 凯特琳 51
    prof = eng.set_enemies(["99", "1", "63", "516", "51"], source="loading_ocr")
    assert prof is not None
    assert prof["source"] == "loading_ocr"
    assert prof["profile"]["ap_count"] == 3
    assert "高法伤" in prof["profile"]["tags"]
    assert abs(sum(prof["profile"]["ratios"].values()) - 1.0) < 0.02

    recs = eng.shop_recommendations("103")
    assert recs is not None
    rules = recs["rule_adjustments"]
    assert rules, "3 法师阵容应触发魔抗规则建议"
    for r in rules:
        assert r["source"] == "rule"
        assert r["disclaimer"] == item_rules.RULE_DISCLAIMER
        assert r["low_sample"] is False
        assert r["base_pick"] >= item_rules.MIN_PICK
        assert any(t in ("SpellBlock", "MagicResist") for t in r["matched_types"])

    # hero_panel 与 snapshot 均同步暴露
    panel = eng.hero_panel("103")
    assert panel is not None
    assert panel["rule_adjustments"] == rules
    assert panel["shop_stats"]["hero_id"] == "103"
    assert "3081" in panel["augment_item_hints"]

    snap = eng.snapshot()
    assert snap["enemies"]["profile"]["ap_count"] == 3
    assert snap["settings"]["theme_mode"] == "system"
    assert snap["settings"]["shop_overlay"] is True


def test_shop_recommendations_advances_next_item_when_owned(tmp_path):
    eng = _real_engine(tmp_path)
    recs0 = eng.shop_recommendations("103")
    assert recs0 is not None
    first_id = recs0["items"][0]["item_id"]
    second_id = recs0["items"][1]["item_id"]
    assert recs0["next_recommended_id"] == first_id

    recs1 = eng.shop_recommendations("103", owned_items=[first_id])
    assert recs1 is not None
    assert recs1["next_recommended_id"] == second_id
    assert recs1["items"][0]["owned"] is True
    assert recs1["items"][1]["owned"] is False


def test_enemy_rules_toggle_disables_rule_adjustments(tmp_path):
    eng = _real_engine(tmp_path)
    eng.set_hero("103")
    eng.set_enemies(["99", "1", "63", "54", "51"])
    assert eng.hero_panel("103")["rule_adjustments"]

    eng.settings.enemy_rules = False
    assert eng.hero_panel("103")["rule_adjustments"] == []
    assert eng.shop_recommendations("103")["rule_adjustments"] == []


def test_search_heroes_supports_chinese_pinyin_and_nicknames(tmp_path):
    eng = _real_engine(tmp_path)
    res_tm = eng.search_heroes("tm", limit=5)
    assert any(h["id"] == "17" and h["name"] == "提莫" for h in res_tm)

    res_ahri = eng.search_heroes("九尾", limit=5)
    assert res_ahri and res_ahri[0]["id"] == "103"

    res_top = eng.search_heroes("", limit=10)
    assert len(res_top) == 10
    assert res_top[0]["win"] >= res_top[-1]["win"]


def test_rescan_teammates_and_clear_selection(tmp_path):
    eng = _real_engine(tmp_path)
    eng.set_hero("103")
    eng.set_enemies(["99", "1", "63"])
    eng.state["champ_select"] = {"bench": [], "team": [], "teammates": [{"raw_name": "玩家A#1234"}], "teammates_status": "cached"}

    eng.rescan_teammates()
    assert eng.state["champ_select"]["teammates"] == []
    assert eng.state["champ_select"]["teammates_status"] == "scanning"

    eng._clear_selection()
    snap = eng.snapshot()
    assert snap["enemies"] is None
    assert snap["shop"] is None
    assert snap["picked_augments"] == []


def test_enemy_rules_excludes_non_shop_quest_items_like_golden_spatula(tmp_path):
    eng = _real_engine(tmp_path)
    eng.set_hero("157")  # 亚索常有海牛阿福金铲铲记录
    eng.set_enemies(["99", "1", "63", "516", "51"])
    recs = eng.shop_recommendations("157")
    assert recs is not None
    ids = {r["item_id"] for r in recs["rule_adjustments"]}
    assert "994403" not in ids
    assert "228002" not in ids
