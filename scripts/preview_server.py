"""本地前后端联调预览服务：让 preview/index.html 直连真实的 Python Engine 与 16.23 内置数据。

用法：
    .venv/bin/python scripts/preview_server.py
    # 默认监听 http://127.0.0.1:8765 ，浏览器打开即可实时搜索全部 173 英雄、测试分段与敌方规则出装。

说明：
- 仅监听 127.0.0.1，不联网、不连接游戏客户端、不改动真实用户配置目录（使用临时目录）。
- preview/index.html 直接用 file:// 打开时会自动回退到内置离线数据，不依赖本脚本。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lolhex.config import Settings, THEME_MODES, UI_PRESETS
from lolhex.data.public import BANDS, PublicStore
from lolhex.engine import Engine
from lolhex import recommend


def create_preview_engine(home: Path) -> Engine:
    settings = Settings(check_data_updates=False)
    store = PublicStore(home / "data", check_updates=False)
    eng = Engine(settings, home=home, store=store)
    eng.set_hero("103")
    eng.set_enemies(["99", "63", "134", "54", "51"], source="loading_ocr")
    return eng


def _serialize_hero_bundle(engine: Engine, hero_id: str, owned: list[str]) -> dict:
    hid = engine.store.resolve_hero(hero_id) or "103"
    engine.set_hero(hid)
    panel = engine.hero_panel(hid) or {}
    brief = engine.hero_brief(hid)
    shop = engine.shop_recommendations(hid, owned_items=owned) or {}
    snap = engine.snapshot()

    # 选出该英雄 Top 海克斯用于界面展示与三选一模拟
    augs = [a for a in (panel.get("augments") or []) if a.get("delta") is not None]
    augs.sort(key=lambda a: (a.get("sample") == "low", -(a.get("delta") or -999)))

    # 用真实 recommend.evaluate 算一组三选一与四选一
    prismatic = [a["id"] for a in augs if a.get("rarity") == "prismatic" and a.get("sample") == "high"]
    sample_three = [prismatic[0], prismatic[min(3, len(prismatic) - 1)], prismatic[-1]] if len(prismatic) >= 3 else [a["id"] for a in augs[:3]]
    low_aug = next((a["id"] for a in augs if a.get("sample") == "low"), None)
    sample_four = (sample_three[:2] + ([low_aug] if low_aug else []) + sample_three[2:3])[:4]
    destiny_slots = [recommend.WEAPON_OF_DESTINY] + sample_three[1:3]

    return {
        "connected": True,
        "patch": snap["data"].get("dataset_patch"),
        "matches": snap["data"].get("dataset_matches"),
        "snapshot_at": snap["data"].get("dataset_snapshot"),
        "hero_count": len(engine.store.heroes),
        "brief": brief,
        "hero": panel.get("hero"),
        "rank": panel.get("rank"),
        "skills": panel.get("skills") or [],
        "summoners": panel.get("summoners") or [],
        "builds": panel.get("builds") or {},
        "core_band": panel.get("core_band"),
        "augments": augs[:36],
        "augment_item_hints": panel.get("augment_item_hints") or {},
        "shop": shop,
        "enemies": snap.get("enemies"),
        "settings": snap.get("settings"),
        "band": engine.settings.data_band or "",
        "bands": BANDS,
        "offers": {
            "standard": recommend.evaluate(engine.store, hid, sample_three),
            "four": recommend.evaluate(engine.store, hid, sample_four),
            "destiny": recommend.evaluate(engine.store, hid, destiny_slots),
        },
        "snapshot": snap,
    }


def make_handler(engine: Engine, preview_html: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send_json(self, data: dict, status: int = 200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path in ("/", "/index.html"):
                body = preview_html.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/health":
                st = engine.store.status()
                self._send_json({
                    "ok": True,
                    "patch": st.get("dataset_patch"),
                    "matches": st.get("dataset_matches"),
                    "heroes": len(engine.store.heroes),
                })
                return
            if parsed.path == "/api/heroes":
                q = (qs.get("q") or [""])[0]
                limit = int((qs.get("limit") or ["18"])[0])
                self._send_json({"heroes": engine.search_heroes(q, limit=limit)})
                return
            if parsed.path == "/api/state":
                hid = (qs.get("hero") or [engine.state.get("hero_id") or "103"])[0]
                owned = [x for x in (qs.get("owned") or [""])[0].split(",") if x]
                self._send_json(_serialize_hero_bundle(engine, hid, owned))
                return
            self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            parsed = urlparse(self.path)
            body = self._read_json()
            if parsed.path == "/api/band":
                engine.set_band(body.get("band") or None)
                hid = body.get("hero_id") or engine.state.get("hero_id") or "103"
                self._send_json(_serialize_hero_bundle(engine, hid, body.get("owned") or []))
                return
            if parsed.path == "/api/enemies":
                ids = body.get("hero_ids") or []
                engine.set_enemies(ids, source=body.get("source") or "manual")
                hid = body.get("hero_id") or engine.state.get("hero_id") or "103"
                self._send_json(_serialize_hero_bundle(engine, hid, body.get("owned") or []))
                return
            if parsed.path == "/api/settings":
                s = engine.settings
                if body.get("theme_mode") in THEME_MODES:
                    s.theme_mode = body["theme_mode"]
                if body.get("ui_preset") in UI_PRESETS:
                    s.ui_preset = body["ui_preset"]
                for k in ("shop_overlay", "enemy_rules", "teammate_ocr", "check_data_updates"):
                    if k in body and isinstance(body[k], bool):
                        setattr(s, k, body[k])
                if "overlay_opacity" in body:
                    s.overlay_opacity = max(30, min(100, int(body["overlay_opacity"])))
                if "overlay_scale" in body:
                    s.overlay_scale = round(max(0.8, min(1.25, float(body["overlay_scale"]))), 2)
                engine._panel_cache = (None, None)
                hid = body.get("hero_id") or engine.state.get("hero_id") or "103"
                self._send_json(_serialize_hero_bundle(engine, hid, body.get("owned") or []))
                return
            self._send_json({"error": "not found"}, 404)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="AramHex 本地前后端联调预览服务")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="aramhex-preview-") as tmp:
        eng = create_preview_engine(Path(tmp))
        srv = ThreadingHTTPServer((args.host, args.port), make_handler(eng, ROOT / "preview" / "index.html"))
        print(f"AramHex 联调预览已启动：http://{args.host}:{args.port} （已加载 {len(eng.store.heroes)} 位英雄 · 16.23 内置数据）")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
