# 前后端接口对齐契约（v2 界面重构与新功能）

更新于 2026-11-28，分支 `feat/apple-ui-contract-preview`（源自 `main` @ `4b93f69`）。

本文档定义**Apple Sequoia Liquid Glass × Linear/Raycast 风格重构（A）**及本期新增功能**商店装备框选（B）**、**按敌方阵容规则优化出装（C）**、**选人识别队友 ID（E1）**，以及预留项**按海克斯出装（D）**与**战绩评级（E2）**的前后端数据结构、方法签名与动效状态契约。

- 交互式原型：[`preview/index.html`](../preview/index.html)（支持离线演示 + 自动连接本地实时引擎）
- 本地实时联调桥接：[`scripts/preview_server.py`](../scripts/preview_server.py)（直连真实 `Engine` + 173 英雄内置数据）

---

## 1. 架构边界与硬约束

本项目无远程业务后端，采用**进程内单向数据流**：

```
后端（Engine / PublicStore / item_rules / Vision）
   │  只读输出：Engine.snapshot() / hero_panel() / shop_recommendations() / search_heroes()
   ▼
前端（MainWindow / Overlay / Tray / ⌘K Spotlight）
   │  用户操作：set_hero() / set_band() / set_enemies() / rescan*() / Settings.save()
   ▼
持久化配置（config.json）
```

不变约束（来自 [`AGENTS.md`](../AGENTS.md) 与 [`docs/ROADMAP.md`](ROADMAP.md)）：
1. **不碰游戏客户端**：不连 LCU、不走 2999 端口、不读内存、不注入、不模拟按键，只截屏识别与透明层显示。
2. **规则与统计严格分离**：规则引擎产出的建议必须带 `"source": "rule"` 与 `"disclaimer": "规则推荐 · 非统计结论"`，前端强制分层标注，禁止混入统计结论。
3. **非商用与署名**：界面保留 `海克斯大乱斗统计数据（github.com/czgreat/aramhex-data），CC BY-NC 4.0`。

---

## 2. 配置契约（`lolhex/config.py` → `Settings`，已实现）

### 2.1 新增字段

| 字段名 | 类型 | 默认值 | 校验规则 | 对应模块 |
|---|---|---|---|---|
| `theme_mode` | `str` | `"system"` | `("system", "light", "dark")` | A 外观 |
| `ui_preset` | `str` | `"liquid"` | `("liquid", "apple", "esports")` | A 视觉预设 |
| `shop_overlay` | `bool` | `True` | 布尔值 | B 商店框选 |
| `enemy_rules` | `bool` | `True` | 布尔值 | C 敌方规则 |
| `teammate_ocr` | `bool` | `True` | 布尔值 | E1 队友 ID |
| `overlay_opacity` | `int` | `85` | `30..100` | A/B 浮窗不透明度 |
| `overlay_scale` | `float` | `1.0` | `0.8..1.25` | A/B 浮窗缩放倍率 |

### 2.2 `Engine.snapshot()["settings"]`

```json
"settings": {
  "show_winrate": true,
  "badge_position": "top",
  "overlay_on_demand": true,
  "theme_mode": "system",
  "ui_preset": "liquid",
  "shop_overlay": true,
  "enemy_rules": true,
  "teammate_ocr": true,
  "overlay_opacity": 85,
  "overlay_scale": 1.0
}
```

---

## 3. 设计语言与 Token 映射（Liquid Glass × Linear Surface Ladder）

针对深色电竞场景与浅色 macOS 桌面场景，采用 **4 阶表面层级（Surface Ladder）+ 顶部 1px 高光边（Specular Edge）**，摒弃扁平单色卡片：

| 层级 Token | 深色模式（Obsidian） | 浅色模式（Porcelain） | 用途 |
|---|---|---|---|
| `BG_CANVAS` | `#08090C` | `#F3F5F9` | 窗口底层画布 |
| `BG_SIDEBAR` | `#0D0F14` | `#EBEEF5` | 左侧固定导航栏 |
| `SURFACE_CARD` | `#12151C` | `#FFFFFF` | 主信息卡片（带顶边 1px 高光） |
| `SURFACE_TILE` | `#181C26` | `#F6F8FC` | 卡片内装备/海克斯子单元 |
| `BORDER_HAIRLINE` | `rgba(255,255,255,0.07)` | `rgba(15,23,42,0.08)` | 精致 1px 细描边 |
| `ACCENT` | `#0A84FF` | `#007AFF` | Apple 强调色 / 焦点环 / 选中胶囊 |
| `GOOD` | `#30D158` | `#1B9E4B` | 首选 / 胜率正差值 |
| `WARN` | `#FF9F0A` | `#D97706` | 规则推荐 / 样本偏少提醒 |
| `BAD` | `#FF453A` | `#DC2626` | 可考虑刷新 / 胜率负差值 |

动效规范（前端已按此实现，迁移至 PySide6 时使用 `QPropertyAnimation` + `QEasingCurve.OutCubic` / `OutExpo`）：
- **侧边栏滑动指示胶囊**：220ms 弹簧曲线平滑滑动；
- **页面与卡片交错入场**：35ms 间隔轻柔上浮淡入；
- **数据可视化过渡**：胜率圆环仪表盘、Δ 胜率双向对比条、敌方伤害构成堆叠条平滑插值；
- **快捷命令面板（`⌘K`）**：160ms 弹性弹出，全键盘上下选择。

---

## 4. 后端新增接口清单（Batch 1 已实现并纳入单测）

### 4.1 英雄模糊检索（支撑 `⌘K` 全局命令面板与敌方阵容选择器）

```python
# Engine.search_heroes (lolhex/engine.py)
def search_heroes(self, query: str = "", limit: int = 12) -> list[dict]:
    """按中文名、称号、外号、英文、拼音/首字母检索全部 173 英雄；空查询按胜率倒序。"""
```

返回项：`{"id", "name", "nick", "roles", "win", "rank", "total", "grade"}`。

### 4.2 商店单件统计与顺位（模块 B，`lolhex/data/public.py`）

```python
# PublicStore.shop_item_stats (lolhex/data/public.py)
def shop_item_stats(self, hero_id: str) -> dict | None:
    """合并 core_builds.json（前三件 order=1/2/3）、
    hero_item_holdings.json / equipment_heroes.json（单件持有率 pick / win / delta / low_sample）
    与 item_metadata.json（category / types / price）。"""
```

### 4.3 敌方阵容画像与规则出装（模块 C，`lolhex/item_rules.py`）

```python
def enemy_profile(store, enemy_ids: list[str] | None, source: str = "manual") -> dict | None
def recommend_rule_items(shop_stats, enemies, *, hero_roles=None, owned_items=None, limit=3) -> list[dict]
```

- `enemy_profile()` 输出：`heroes`、`profile`（含各定位计数、`ap_count`/`ad_count`/`tank_count`/`support_count`、`ratios` 供堆叠条渲染、`tags`）。
- `recommend_rule_items()` 强约束：仅从 `low_sample == False` 且 `pick >= 0.015` 的英雄常出成装中筛选，每条必带 `"source": "rule"` 与 `"disclaimer": "规则推荐 · 非统计结论"`。

### 4.4 引擎整合查询与控制接口（`lolhex/engine.py` & `lolhex/panel.py`）

```python
Engine.set_enemies(hero_ids: list[str] | None, source: str = "manual") -> dict | None
Engine.rescan_teammates() -> None
Engine.shop_recommendations(hero_id=None, enemies=None, owned_items=None) -> dict | None
```

- `shop_recommendations()` 支持传入 `owned_items`（已购买装备 ID 集合），自动计算 `next_recommended_id`（下一件应买的核心装备），便于局内商店动态推进高亮框与原型点击模拟购买。
- `Engine.hero_panel(hero_id)` 在保留所有旧字段不变的前提下，新增 `shop_stats`、`rule_adjustments`、`augment_item_hints`（模块 D 预留）。
- `Engine.snapshot()` 新增顶层字段：`enemies`、`shop`、`picked_augments`（模块 D 预留），`champ_select` 兼容 `teammates` 与 `teammates_status`（模块 E1，单条保留 `rating: null` 作为 E2 预留）。

---

## 5. 联调与后续开发进度

| 批次 | 内容 | 状态 | 备注 |
|---|---|---|---|
| **Batch 1** | `Settings` 扩展 + `shop_item_stats()` + `item_rules.py` + `Engine`/`panel` 新接口 + 单测 | **已完成** | 见 `tests/test_shop_and_rules.py` |
| **本地联调桥** | `scripts/preview_server.py` + `preview/index.html` 实时对接 173 英雄 | **已完成** | 支持离线与实时双模式 |
| **Batch 2（视觉识别）** | 商店格子定位（B）、加载页敌方识别（C）、聊天框队友 ID OCR（E1） | **待实机截图** | 截图到齐直接写入对应 `snapshot` 字段即可接通 |
| **PySide6 落地** | `theme.py` 深浅色 Token → `mainwindow.py` 侧边栏拆分 → `overlay.py` `ShopLayer` | **待原型定型** | 原型验收定稿后按契约迁移 |
