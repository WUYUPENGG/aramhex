"""模块 E1：选人界面左下角聊天框队友召唤师 ID 识别（只截屏 OCR，不连 LCU）。

性能与稳定性设计：
- 仅在已确认处于选人界面（in_cs）时扫描左下角聊天框小区域，不扫全屏；
- 解析系统进场消息（如「xxx#1234 加入了房间」/「xxx joined the lobby」）；
- 多帧多数表决纠错，凑齐 4 位队友后自动冻结缓存，后续帧零 OCR 开销；
- 聊天框比例坐标集中定义在 CHAT_BOX，拿到实机截图后只需校准这一处。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
from rapidfuzz import fuzz

log = logging.getLogger(__name__)

# 以 1920×1080 客户端客户区为基准的比例坐标（待国服实机截图最终微调）
REF_W, REF_H = 1920, 1080


def _r(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (x0 / REF_W, y0 / REF_H, x1 / REF_W, y1 / REF_H)


CHAT_BOX = _r(24, 750, 495, 1020)

# 常见进场系统提示：中/繁/英客户端兼容
_JOIN_PATTERNS = (
    re.compile(r"^\s*(?:\[[^\]]+\]\s*)?(.+?)\s*(?:加入了(?:房间|大厅|队伍聊天|聊天室)|已加入(?:房间|大厅|队伍))\s*[。!！.]*$"),
    re.compile(r"^\s*(?:\[[^\]]+\]\s*)?(.+?)\s+joined\s+the\s+(?:lobby|room|team\s+chat)\s*[.!]*$", re.IGNORECASE),
)
_NOISE_PREFIX = re.compile(r"^[\s\[\(（·•\-—:>]+")
_NOISE_SUFFIX = re.compile(r"[\s\]\)）·•\-—:,，。!！]+$")

MIN_CONFIDENCE = 0.65
UNCERTAIN_CONFIDENCE = 0.85
MAX_TEAMMATES = 4


def crop_chat(img, box: tuple[float, float, float, float] = CHAT_BOX):
    """按窗口比例裁出左下角聊天框区域。"""
    if img is None or getattr(img, "size", 0) == 0:
        return img
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def preprocess_chat(crop: np.ndarray, *, scale: float = 2.0) -> np.ndarray:
    """聊天框小字增强：对暗底浅字做对比度拉伸 + 2× 双三次放大，改善 l/I/1 与复杂汉字识别。"""
    if crop is None or getattr(crop, "size", 0) == 0:
        return crop
    img = crop
    if scale and scale > 1.0:
        h, w = img.shape[:2]
        if h > 0 and w > 0 and max(h, w) <= 1200:
            img = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_CUBIC)
    # 轻微对比度拉伸（保留文字色彩，避免把纯黑空图拉出噪点）
    lo, hi = float(np.percentile(img, 5)), float(np.percentile(img, 99))
    if hi - lo >= 25.0:
        stretched = np.clip((img.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        return stretched
    return img


def parse_join_line(text: str) -> str | None:
    """从单行聊天 OCR 文本提取召唤师 ID；非进场系统消息返回 None。"""
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    for pat in _JOIN_PATTERNS:
        m = pat.match(cleaned)
        if not m:
            continue
        raw = m.group(1).strip()
        raw = _NOISE_PREFIX.sub("", raw)
        raw = _NOISE_SUFFIX.sub("", raw)
        # 保留 #编号（若中间被 OCR 拆出空格则合拢）
        raw = re.sub(r"\s*#\s*", "#", raw)
        if len(raw) >= 2 and not raw.startswith("系统"):
            return raw
    return None


def parse_join_lines(lines) -> list[tuple[str, float]]:
    """OCR TextLine 列表（或 (text, score) 元组）→ [(raw_name, score)]。"""
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for item in lines or ():
        if hasattr(item, "text") and hasattr(item, "score"):
            text, score = item.text, float(item.score)
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            text, score = str(item[0]), float(item[1])
        else:
            continue
        if score < MIN_CONFIDENCE:
            continue
        name = parse_join_line(text)
        if name and name not in seen:
            seen.add(name)
            out.append((name, score))
    return out


def _canon(name: str) -> str:
    """用于归并多帧里 l/I/1、0/O 等轻微错字的归一化键。"""
    s = name.lower().replace(" ", "")
    return s.translate(str.maketrans({"i": "1", "l": "1", "o": "0"}))


@dataclass
class _Entry:
    votes: dict[str, int] = field(default_factory=dict)
    max_score: float = 0.0
    frames: int = 0

    def add(self, raw_name: str, score: float) -> None:
        self.votes[raw_name] = self.votes.get(raw_name, 0) + 1
        self.max_score = max(self.max_score, float(score))
        self.frames += 1

    def best_name(self) -> str:
        return max(self.votes.items(), key=lambda kv: (kv[1], len(kv[0])))[0]

    def to_dict(self) -> dict:
        return {
            "raw_name": self.best_name(),
            "confidence": round(self.max_score, 3),
            "frames": self.frames,
            "uncertain": self.max_score < UNCERTAIN_CONFIDENCE or self.frames < 2,
            "rating": None,  # 模块 E2 预留，不连 LCU 时恒为 None
        }


class TeammateTracker:
    """跨帧累积并冻结选人聊天框队友 ID，凑齐后停止重复 OCR。"""

    def __init__(self, max_teammates: int = MAX_TEAMMATES, freeze_frames: int = 2, max_scans: int = 12):
        self.max_teammates = max_teammates
        self.freeze_frames = freeze_frames
        self.max_scans = max_scans
        self._entries: list[_Entry] = []
        self._scans = 0
        self._frozen = False

    def reset(self) -> None:
        self._entries.clear()
        self._scans = 0
        self._frozen = False

    @property
    def done(self) -> bool:
        return self._frozen

    @property
    def status(self) -> str:
        if self._frozen:
            return "cached"
        return "scanning"

    def snapshot(self) -> list[dict]:
        return [e.to_dict() for e in self._entries[: self.max_teammates]]

    def _find_entry(self, raw_name: str) -> _Entry | None:
        key = _canon(raw_name)
        for entry in self._entries:
            ek = _canon(entry.best_name())
            if ek == key or (len(key) >= 4 and fuzz.ratio(ek, key) >= 85):
                return entry
        return None

    def observe(self, lines) -> list[dict]:
        """吸收一帧 OCR 文本行，返回当前累计的队友列表。已冻结时直接返回缓存。"""
        if self._frozen:
            return self.snapshot()
        self._scans += 1
        for raw_name, score in parse_join_lines(lines):
            entry = self._find_entry(raw_name)
            if entry is None:
                if len(self._entries) >= self.max_teammates:
                    continue
                entry = _Entry()
                self._entries.append(entry)
            entry.add(raw_name, score)
        if (
            len(self._entries) >= self.max_teammates
            and all(e.frames >= self.freeze_frames for e in self._entries[: self.max_teammates])
        ) or (self._scans >= self.max_scans and self._entries):
            self._frozen = True
            log.info("选人队友 ID 已缓存：%d 人", len(self._entries))
        return self.snapshot()


def read_chat(
    img,
    detect,
    tracker: TeammateTracker | None = None,
    memo=None,
    box: tuple[float, float, float, float] = CHAT_BOX,
    *,
    enhance: bool = True,
) -> tuple[list[dict], str]:
    """从客户端截图读取左下角聊天框队友 ID。已缓存时零 OCR 消耗。"""
    if tracker is not None and tracker.done:
        return tracker.snapshot(), tracker.status
    crop = crop_chat(img, box)
    if crop is None or getattr(crop, "size", 0) == 0:
        return (tracker.snapshot() if tracker else []), (tracker.status if tracker else "scanning")
    run = (lambda c: detect(preprocess_chat(c))) if enhance else detect
    lines = memo("cs_chat", crop, run, bool) if memo is not None else run(crop)
    if tracker is None:
        tmp = TeammateTracker()
        return tmp.observe(lines), tmp.status
    return tracker.observe(lines), tracker.status
