"""NAS 静态数据镜像脚本（scripts/mirror_data.py）与 ARAMHEX_DATA_MIRROR 接入测试。"""
from __future__ import annotations

import hashlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lolhex.data.public import BUNDLED_DIR, Dataset, PublicStore, unpack
from scripts.mirror_data import sync_mirror


def _mini_dataset(folder: Path, *, patch: str = "16.99", seq: int = 99) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"patch": patch, "mode": "normal", "mode_label": "常规"}
    heroes = {"103": {"games": 10000, "wins": 5200, "win_rate": 0.52}}
    augs = {"103": {"1156": {"games": 1000, "wins": 560, "win_rate": 0.56, "low_sample": False}}}
    files = {}
    for name, obj in (("meta.json", meta), ("heroes.json", heroes), ("hero_augments.json", augs)):
        body = (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
        (folder / name).write_bytes(body)
        files[name] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
    manifest = {
        "schema_version": 1,
        "patch": patch,
        "mode": "normal",
        "mode_label": "常规",
        "path": f"patches/{patch}/normal",
        "seq": seq,
        "snapshot_at": "2026-12-01T09:00:00+08:00",
        "bands": False,
        "files": files,
    }
    (folder / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return folder


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


def test_mirror_sync_pack_idempotent_and_publicstore_download(tmp_path, monkeypatch):
    src = _mini_dataset(tmp_path / "src", patch="16.99", seq=99)
    mirror_dir = tmp_path / "mirror"

    # 第一次同步：应写出 latest.json、原始 JSON 与 .pack.xz 并通过自检
    r1 = sync_mirror(mirror_dir, local_from=src, build_pack=True)
    assert r1["updated"] is True
    ds_info = r1["datasets"][0]
    assert ds_info["patch"] == "16.99" and ds_info["pack_bytes"] > 0
    pack_path = mirror_dir / "patches/16.99/normal.pack.xz"
    assert pack_path.is_file()
    assert set(unpack(pack_path.read_bytes())) == {"meta.json", "heroes.json", "hero_augments.json"}
    assert Dataset(mirror_dir / "patches/16.99/normal", "mirror").seq == 99

    # 第二次同步（上游未变）：幂等跳过，不重复写入
    r2 = sync_mirror(mirror_dir, local_from=src, build_pack=True)
    assert r2["updated"] is False and r2["datasets"][0]["updated"] is False

    # 用本地静态 HTTP 服务挂载 mirror_dir，通过 ARAMHEX_DATA_MIRROR 让 PublicStore 拉取
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(mirror_dir)))
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        mirror_url = f"http://127.0.0.1:{port}"
        monkeypatch.setenv("ARAMHEX_DATA_MIRROR", mirror_url)
        client_root = tmp_path / "client"
        store = PublicStore(client_root, bundled=BUNDLED_DIR, check_updates=True)
        assert store.base_urls[0] == mirror_url
        assert store.sync_data(force=True) is True
        assert store.dataset is not None
        assert store.dataset.patch == "16.99" and store.dataset.seq == 99
        assert store.data_source == mirror_url
    finally:
        server.shutdown()
        server.server_close()
