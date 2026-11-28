"""基于敌方阵容的规则式出装调整（模块 C）。

约束（见 docs/ROADMAP.md 与 docs/API_CONTRACT.md）：
1. 内置统计数据不包含「对阵某敌方阵容时的装备胜率」，因此本模块完全基于英雄定位与装备属性规则。
2. 所有输出必须携带 `source="rule"` 与 `disclaimer="规则推荐 · 非统计结论"`，界面必须显式区分。
3. 只从该英雄自身已有足够样本的常出成装池中挑选（`low_sample=False` 且 `pick >= MIN_PICK`），
   绝不推荐该英雄几乎不出的冷门装备。
"""

from __future__ import annotations

RULE_DISCLAIMER = "规则推荐 · 非统计结论"
MIN_PICK = 0.015  # 至少 1.5% 持有率才进入规则推荐候选池
# 非商店直接购买的特殊/海克斯赠予装备（如金铲铲、沃格勒特的巫师帽等），不参与商店出装规则
NON_SHOP_ITEMS = {"994403", "223069", "226668", "228002"}

ROLE_CN = {
    "mage": "法师",
    "marksman": "射手",
    "assassin": "刺客",
    "fighter": "战士",
    "tank": "坦克",
    "support": "辅助",
}


def enemy_profile(store, enemy_ids: list[str] | None, source: str = "manual") -> dict | None:
    """将最多 5 个敌方英雄整理为定位画像与伤害/坦度占比，供前端可视化和规则引擎消费。"""
    if not enemy_ids:
        return None
    heroes: list[dict] = []
    seen: set[str] = set()
    for raw in enemy_ids:
        if not raw:
            continue
        hid = store.resolve_hero(raw) if hasattr(store, "resolve_hero") else str(raw)
        if not hid or hid in seen:
            continue
        seen.add(hid)
        h = (getattr(store, "heroes", None) or {}).get(hid) or {"id": hid, "name": hid, "roles": []}
        roles = [str(r) for r in (h.get("roles") or []) if r]
        heroes.append({
            "hero_id": hid,
            "name": h.get("name") or hid,
            "nick": h.get("nick") or "",
            "roles": roles,
        })
        if len(heroes) >= 5:
            break
    if not heroes:
        return None

    counts = {k: 0 for k in ROLE_CN}
    ap_heroes: list[str] = []
    ad_heroes: list[str] = []
    tank_heroes: list[str] = []
    support_heroes: list[str] = []

    for h in heroes:
        rset = set(h["roles"])
        for r in rset:
            if r in counts:
                counts[r] += 1
        if "mage" in rset:
            ap_heroes.append(h["name"])
        if rset & {"marksman", "assassin"} or ("fighter" in rset and "mage" not in rset):
            ad_heroes.append(h["name"])
        if "tank" in rset:
            tank_heroes.append(h["name"])
        if "support" in rset:
            support_heroes.append(h["name"])

    ap_w = len(ap_heroes)
    ad_w = len(ad_heroes)
    tank_w = len(tank_heroes)
    sup_w = len(support_heroes)
    total_w = max(1, ap_w + ad_w + tank_w + sup_w)

    tags: list[str] = []
    if ap_w >= 3:
        tags.append("高法伤")
    if ad_w >= 3:
        tags.append("高物理爆发")
    if tank_w >= 2:
        tags.append("高坦度")
    if sup_w >= 2:
        tags.append("多辅助/回复")

    return {
        "source": source,
        "heroes": heroes,
        "profile": {
            **counts,
            "ap_count": ap_w,
            "ad_count": ad_w,
            "tank_count": tank_w,
            "support_count": sup_w,
            "ap_heroes": ap_heroes,
            "ad_heroes": ad_heroes,
            "tank_heroes": tank_heroes,
            "ratios": {
                "ap": round(ap_w / total_w, 3),
                "ad": round(ad_w / total_w, 3),
                "tank": round(tank_w / total_w, 3),
                "support": round(sup_w / total_w, 3),
            },
            "tags": tags,
        },
    }


def _hero_damage_bias(hero_roles: list[str]) -> str:
    rset = set(hero_roles or [])
    if "mage" in rset and not (rset & {"marksman", "fighter"}):
        return "ap"
    if rset & {"marksman", "fighter", "assassin"} and "mage" not in rset:
        return "ad"
    return "both"


def recommend_rule_items(
    shop_stats: dict | None,
    enemies: dict | None,
    *,
    hero_roles: list[str] | None = None,
    owned_items: set[str] | None = None,
    limit: int = 3,
) -> list[dict]:
    """根据敌方阵容画像，在英雄自身常出成装中筛出针对性规则建议。"""
    if not shop_stats or not enemies:
        return []
    prof = enemies.get("profile") or {}
    items = shop_stats.get("items") or []
    owned = {str(x) for x in (owned_items or ())}
    bias = _hero_damage_bias(hero_roles or [])

    rules: list[tuple[str, tuple[str, ...], str]] = []
    if prof.get("ap_count", 0) >= 3:
        names = "、".join((prof.get("ap_heroes") or [])[:4])
        rules.append((
            "enemy_ap_heavy",
            ("SpellBlock", "MagicResist"),
            f"敌方法师定位 {prof['ap_count']} 人（{names}），建议在常出装备中提前考虑魔抗",
        ))
    if prof.get("ad_count", 0) >= 3:
        names = "、".join((prof.get("ad_heroes") or [])[:4])
        rules.append((
            "enemy_ad_heavy",
            ("Armor",),
            f"敌方物理输出 {prof['ad_count']} 人（{names}），建议在常出装备中提前考虑护甲/保命",
        ))
    if prof.get("tank_count", 0) >= 2:
        names = "、".join((prof.get("tank_heroes") or [])[:4])
        pen_types = (
            ("MagicPenetration",) if bias == "ap"
            else ("ArmorPenetration",) if bias == "ad"
            else ("MagicPenetration", "ArmorPenetration")
        )
        rules.append((
            "enemy_tank_heavy",
            pen_types,
            f"敌方坦克定位 {prof['tank_count']} 人（{names}），建议提前补出穿透装备",
        ))

    if not rules:
        return []

    eligible = [
        it for it in items
        if not it.get("low_sample")
        and (it.get("pick") or 0) >= MIN_PICK
        and str(it.get("item_id") or "") not in owned
        and str(it.get("item_id") or "") not in NON_SHOP_ITEMS
        and len(it.get("types") or []) < 8
        and it.get("category") == "complete_equipment"
    ]

    picked: list[dict] = []
    seen_ids: set[str] = set()
    for rule_id, target_types, reason in rules:
        matches = [
            it for it in eligible
            if str(it["item_id"]) not in seen_ids
            and any(t in (it.get("types") or []) for t in target_types)
        ]
        matches.sort(key=lambda x: (-(x.get("win") or 0.0), -(x.get("pick") or 0.0)))
        for it in matches[:2]:
            iid = str(it["item_id"])
            seen_ids.add(iid)
            picked.append({
                "item_id": iid,
                "name": it.get("name") or iid,
                "icon": it.get("icon"),
                "source": "rule",
                "disclaimer": RULE_DISCLAIMER,
                "rule_id": rule_id,
                "rule_reason": reason,
                "matched_types": [t for t in (it.get("types") or []) if t in target_types],
                "base_pick": it.get("pick"),
                "base_win": it.get("win"),
                "base_games": it.get("games"),
                "low_sample": bool(it.get("low_sample")),
            })
            if len(picked) >= limit:
                return picked
    return picked
