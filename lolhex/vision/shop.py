"""模块 B：局内装备商店识别与已购装备检测（离线 ItemIconBank 矩阵比对）。

性能与防干扰设计：
- 装备识别完全基于内置 item_icons.json 的 20×20 归一化 RGB 特征矩阵点乘（毫秒级，不调用 OCR）；
- 仅在商店锚点确认打开、且当前未出现海克斯三选一时扫描，避免与海克斯文字识别互相干扰；
- 商店网格与底部装备栏比例坐标集中在 ShopLayout，拿到不同分辨率/界面缩放实机截图后只需校准参数。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..data.icons import bundled_icons

log = logging.getLogger(__name__)

REF_W, REF_H = 1920, 1080
SIDE = 20
SHIFTS = (-0.04, 0.0, 0.04)
MIN_SCORE = 0.78
MIN_MARGIN = 0.07
MIN_TEXTURE = 9.0


def _r(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (x0 / REF_W, y0 / REF_H, x1 / REF_W, y1 / REF_H)


@dataclass(frozen=True)
class ShopLayout:
    """商店与底部 6 格装备栏的窗口比例坐标（1920×1080 基准，支持后续校准替换）。"""

    anchor_box: tuple[float, float, float, float]
    grid_boxes: tuple[tuple[float, float, float, float], ...]
    inventory_boxes: tuple[tuple[float, float, float, float], ...]


def default_layout() -> ShopLayout:
    """默认 1920×1080 商店推荐/成装网格与底部装备栏比例布局（待实机截图校准）。"""
    # 商店面板左上角「商店 / 装备」标题锚点区
    anchor = _r(175, 118, 330, 162)
    # 商店主展示区 4×3 常用装备格子（每格 48×48，间距 68×74）
    grid = tuple(
        _r(280 + col * 72, 260 + row * 78, 328 + col * 72, 308 + row * 78)
        for row in range(3)
        for col in range(4)
    )
    # 底部 HUD 6 格已购装备栏（2×3）
    inv = tuple(
        _r(1118 + col * 36, 978 + row * 36, 1150 + col * 36, 1010 + row * 36)
        for row in range(2)
        for col in range(3)
    )
    return ShopLayout(anchor_box=anchor, grid_boxes=grid, inventory_boxes=inv)


DEFAULT_LAYOUT = default_layout()
SHOP_MARKERS = ("商店", "装备", "所有装备", "推荐", "shop", "items")


def _square_feature(img: np.ndarray, inner: float = 0.78) -> np.ndarray | None:
    """方形装备图标 → 归一化 RGB 特征向量（裁去外圈金边/边框与冷却遮罩边缘）。"""
    if img is None or img.size == 0 or min(img.shape[:2]) < 8:
        return None
    h, w = img.shape[:2]
    s = min(h, w) * inner
    x0, y0 = int(round((w - s) / 2)), int(round((h - s) / 2))
    crop = img[y0:y0 + int(s), x0:x0 + int(s)]
    small = cv2.resize(crop, (SIDE, SIDE), interpolation=cv2.INTER_AREA).astype(np.float32)
    v = small.reshape(-1, 3)
    v = v - v.mean(axis=0, keepdims=True)
    v = v.ravel()
    norm = float(np.linalg.norm(v))
    if norm < 1e-3:
        return None
    return v / norm


def _flat(crop: np.ndarray) -> bool:
    if crop is None or crop.size == 0:
        return True
    h, w = crop.shape[:2]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
    return g.size == 0 or float(g.std()) < MIN_TEXTURE


@dataclass
class ItemMatch:
    item_id: str | None
    score: float
    second: float

    @property
    def sure(self) -> bool:
        return self.item_id is not None


class ItemIconBank:
    """离线装备图标向量库：毫秒级识别商店格子与底部装备栏里的装备 ID。"""

    def __init__(self, icons: dict[str, np.ndarray], *, min_score: float = MIN_SCORE, min_margin: float = MIN_MARGIN):
        ids: list[str] = []
        feats: list[np.ndarray] = []
        # 优先保留较短的标准装备 ID（如 2503），去掉与标准图标完全一致的斗魂/乱斗变体重复 ID（如 222503）
        ordered = sorted(icons.items(), key=lambda kv: (len(str(kv[0])), str(kv[0])))
        for iid, img in ordered:
            f = _square_feature(img)
            if f is None:
                continue
            if feats and float(np.max(np.stack(feats) @ f)) >= 0.995:
                continue
            ids.append(str(iid))
            feats.append(f)
        self.ids = ids
        self.min_score = min_score
        self.min_margin = min_margin
        self.mat = np.stack(feats) if feats else np.zeros((0, SIDE * SIDE * 3), np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    def classify(self, crop: np.ndarray) -> ItemMatch:
        if not self.ids or _flat(crop):
            return ItemMatch(None, 0.0, 0.0)
        h, w = crop.shape[:2]
        variants = []
        base = _square_feature(crop)
        if base is not None:
            variants.append(base)
        s = int(round(min(h, w) * 0.78))
        step_x = max(1, int(round(w * 0.04)))
        step_y = max(1, int(round(h * 0.04)))
        cx0, cy0 = (w - s) // 2, (h - s) // 2
        for dy in (-step_y, 0, step_y):
            for dx in (-step_x, 0, step_x):
                x0, y0 = cx0 + dx, cy0 + dy
                x1, y1 = x0 + s, y0 + s
                if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                    continue
                f = _square_feature(crop[y0:y1, x0:x1], inner=1.0)
                if f is not None:
                    variants.append(f)
        if not variants:
            return ItemMatch(None, 0.0, 0.0)
        sims = (np.stack(variants) @ self.mat.T).max(axis=0)
        order = np.argsort(-sims)
        best = float(sims[order[0]])
        second = float(sims[order[1]]) if len(order) > 1 else 0.0
        iid = self.ids[order[0]] if best >= self.min_score and best - second >= self.min_margin else None
        return ItemMatch(iid, best, second)

    @classmethod
    def from_bundled(cls, cache_dir: Path | None = None, allowed_ids: set[str] | None = None) -> "ItemIconBank":
        """从内置 item_icons.json（优先叠加本地缓存目录）构建装备图标库，完全离线。"""
        icons: dict[str, np.ndarray] = {}
        raw_items = bundled_icons().get("item") or {}
        for iid, b64 in raw_items.items():
            sid = str(iid)
            if allowed_ids is not None and sid not in allowed_ids:
                continue
            try:
                img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
            except (ValueError, TypeError):
                img = None
            if img is not None:
                icons[sid] = img
        if cache_dir is not None and cache_dir.is_dir():
            for p in cache_dir.glob("*.png"):
                sid = p.stem
                if allowed_ids is not None and sid not in allowed_ids:
                    continue
                img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    icons[sid] = img
        return cls(icons)


def _crop(img, box: tuple[float, float, float, float]):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _pixel_box(box: tuple[float, float, float, float], w: int, h: int, origin: tuple[int, int]) -> tuple[int, int, int, int]:
    ox, oy = origin
    x0, y0, x1, y1 = box
    return (int(x0 * w) + ox, int(y0 * h) + oy, int(x1 * w) + ox, int(y1 * h) + oy)


def is_shop_open(img, anchor_reader=None, layout: ShopLayout = DEFAULT_LAYOUT) -> bool:
    """判断商店窗口是否打开：有 anchor_reader 时用单行文字校验（约 10ms），否则交由格子命中数判断。"""
    if img is None or getattr(img, "size", 0) == 0:
        return False
    if anchor_reader is None:
        return True
    txt, score = anchor_reader(_crop(img, layout.anchor_box))
    low = (txt or "").strip().lower()
    return float(score or 0.0) >= 0.55 and any(k in low for k in SHOP_MARKERS)


def read_shop(
    img,
    bank: ItemIconBank,
    origin: tuple[int, int] = (0, 0),
    *,
    layout: ShopLayout = DEFAULT_LAYOUT,
    anchor_reader=None,
    memo=None,
    min_slots_without_anchor: int = 3,
) -> dict:
    """截取游戏客户区 → {"open": bool, "slots": [...], "owned_items": [...]}。

    slots 每项：{"slot": int, "item_id": str, "score": float, "box": (x0, y0, x1, y1)}（屏幕物理像素坐标）。
    """
    if img is None or getattr(img, "size", 0) == 0 or not len(bank):
        return {"open": False, "slots": [], "owned_items": []}
    if anchor_reader is not None and not is_shop_open(img, anchor_reader, layout):
        return {"open": False, "slots": [], "owned_items": []}

    h, w = img.shape[:2]
    classify = (lambda key, crop: memo(key, crop, bank.classify, lambda m: m.sure)) if memo is not None else (lambda _k, crop: bank.classify(crop))

    slots: list[dict] = []
    for idx, rel in enumerate(layout.grid_boxes):
        m = classify(("shop_grid", idx), _crop(img, rel))
        if m.sure:
            slots.append({
                "slot": idx,
                "item_id": m.item_id,
                "score": round(float(m.score), 3),
                "box": _pixel_box(rel, w, h, origin),
            })

    if anchor_reader is None and len(slots) < min_slots_without_anchor:
        return {"open": False, "slots": [], "owned_items": []}

    owned: list[str] = []
    seen_owned: set[str] = set()
    for idx, rel in enumerate(layout.inventory_boxes):
        m = classify(("shop_inv", idx), _crop(img, rel))
        if m.sure and m.item_id not in seen_owned:
            seen_owned.add(m.item_id)
            owned.append(m.item_id)

    return {"open": True, "slots": slots, "owned_items": owned}
