"""模块 C：对局加载界面敌方 5 名英雄识别（头像比对优先 + OCR 英雄名兜底）。

性能设计：
- 优先使用 IconBank 矩阵向量比对 5 个敌方卡片头像（<2ms，不跑 OCR）；
- 遇到皮肤原画与默认头像差异过大时，才对该空槽位用单行 OCR 读英雄名兜底；
- 连续两帧确认（或单帧认齐 5 人）后立即冻结，整局不再重复扫描。
- 卡片比例坐标集中在 ENEMY_PORTRAITS / ENEMY_NAMES，拿到加载界面实机截图后可直接校准。
"""

from __future__ import annotations

import logging
from collections import Counter

from .portraits import IconBank

log = logging.getLogger(__name__)

REF_W, REF_H = 1920, 1080


def _r(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (x0 / REF_W, y0 / REF_H, x1 / REF_W, y1 / REF_H)


# 加载界面下半排 5 张敌方英雄卡片比例坐标（1920×1080 基准，待实机截图校准）
_CARD_XS = (180, 500, 820, 1140, 1460)
ENEMY_PORTRAITS: tuple[tuple[float, float, float, float], ...] = tuple(
    _r(x + 40, 595, x + 240, 795) for x in _CARD_XS
)
ENEMY_NAMES: tuple[tuple[float, float, float, float], ...] = tuple(
    _r(x + 20, 860, x + 260, 905) for x in _CARD_XS
)


def _crop(img, box: tuple[float, float, float, float]):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def read_enemies(
    img,
    bank: IconBank | None,
    name_reader=None,
    *,
    portrait_boxes: tuple[tuple[float, float, float, float], ...] = ENEMY_PORTRAITS,
    name_boxes: tuple[tuple[float, float, float, float], ...] = ENEMY_NAMES,
) -> list[str]:
    """从加载界面截图中识别敌方英雄 ID（最多 5 个，去重保序）。"""
    if img is None or getattr(img, "size", 0) == 0:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for idx in range(min(5, len(portrait_boxes))):
        hid = None
        if bank is not None:
            m = bank.classify(_crop(img, portrait_boxes[idx]))
            if m.sure:
                hid = m.hero_id
        if hid is None and name_reader is not None and idx < len(name_boxes):
            hid = name_reader(_crop(img, name_boxes[idx]))
        if hid and hid not in seen:
            seen.add(hid)
            found.append(str(hid))
    return found


class LoadingTracker:
    """对局初期追踪加载界面敌方 5 人；一旦稳定锁定或超过扫描预算即冻结，零后续开销。"""

    def __init__(self, confirm_frames: int = 2, min_heroes: int = 3, max_attempts: int = 10):
        self.confirm_frames = confirm_frames
        self.min_heroes = min_heroes
        self.max_attempts = max_attempts
        self._votes: list[Counter[str]] = [Counter() for _ in range(5)]
        self._hits = 0
        self._attempts = 0
        self._locked: list[str] | None = None

    def reset(self) -> None:
        self._votes = [Counter() for _ in range(5)]
        self._hits = 0
        self._attempts = 0
        self._locked = None

    @property
    def done(self) -> bool:
        return self._locked is not None or self._attempts >= self.max_attempts

    @property
    def heroes(self) -> list[str] | None:
        return list(self._locked) if self._locked is not None else None

    def observe(self, hero_ids: list[str]) -> list[str] | None:
        """记录一帧识别结果；确认锁定时返回最终敌方 ID 列表，否则返回 None。"""
        if self._locked is not None:
            return list(self._locked)
        self._attempts += 1
        clean = [str(h) for h in hero_ids if h][:5]
        if len(clean) < self.min_heroes:
            return None
        self._hits += 1
        for i, hid in enumerate(clean):
            self._votes[i][hid] += 1
        if len(clean) == 5 and self._hits >= 1 and self.confirm_frames <= 1:
            self._locked = clean
            return list(self._locked)
        if self._hits >= self.confirm_frames:
            picked: list[str] = []
            seen: set[str] = set()
            for bucket in self._votes:
                for hid, _ in bucket.most_common():
                    if hid not in seen:
                        seen.add(hid)
                        picked.append(hid)
                        break
            if len(picked) >= self.min_heroes:
                self._locked = picked
                log.info("加载界面识别到敌方阵容：%s", picked)
                return list(self._locked)
        return None
