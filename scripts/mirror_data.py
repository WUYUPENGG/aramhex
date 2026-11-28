#!/usr/bin/env python3
"""将上游统计数据仓库（czgreat/aramhex-data）同步为静态镜像目录，并生成 .pack.xz 压缩包。

支持三种用法：
1. 直接在 Mac（走本机 Clash 代理）拉取并生成镜像，再推到 NAS 静态目录：
   .venv/bin/python scripts/mirror_data.py --out build/data-mirror --proxy http://127.0.0.1:7897
   .venv/bin/python scripts/mirror_data.py --out build/data-mirror --proxy http://127.0.0.1:7897 --rsync user@192.168.31.159:/volume1/web/aramhex-data

2. 直接在 NAS / 云主机上定时执行（cron 每 2–6 小时跑一次，无更新自动跳过）：
   python3 scripts/mirror_data.py --out /var/www/aramhex-data

3. 从本地目录（如 lolhex/data/bundled 或本地 aramhex-data 克隆）构建镜像：
   .venv/bin/python scripts/mirror_data.py --from lolhex/data/bundled --out build/data-mirror

镜像目录结构（直接交给 Nginx / Caddy / NAS Web Station 静态托管即可）：
  <out>/
    latest.json
    index.json                      （上游存在时同步）
    patches/<patch>/<mode>/*.json   （逐文件回退用）
    patches/<patch>/<mode>.pack.xz  （客户端优先下载的单文件压缩包，体积缩小约 80%）

客户端接入方式：
  - 临时测试：设置环境变量 ARAMHEX_DATA_MIRROR=http://<地址>/aramhex-data
  - 长期内置：把镜像 URL 加到 lolhex/data/public.py 的 DATA_SOURCES 首位
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lolhex.data.public import (  # noqa: E402
    DATA_SOURCES,
    Dataset,
    DatasetError,
    _dataset_file,
    check_manifest,
    make_pack,
    unpack,
)

DEFAULT_SOURCE = DATA_SOURCES[0]


def _make_session(proxy: str | None = None):
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = "aramhex-mirror/1.0"
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def _fetch_bytes(session, url: str, timeout: float = 60.0) -> bytes:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def _manifest_sig(manifest: dict) -> tuple:
    files_sig = json.dumps(manifest.get("files") or {}, sort_keys=True)
    return (
        str(manifest.get("patch") or ""),
        str(manifest.get("mode") or ""),
        str(manifest.get("snapshot_at") or ""),
        int(manifest.get("seq") or 0),
        hashlib.sha256(files_sig.encode("utf-8")).hexdigest(),
    )


def _read_json_if_exists(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _sync_one_dataset(
    manifest: dict,
    out_root: Path,
    *,
    read_file,
    build_pack: bool = True,
    force: bool = False,
) -> dict:
    """将单份由 manifest 描述的数据集原子同步到 out_root/<path>，可选生成 <path>.pack.xz。"""
    check_manifest(manifest)
    rel_path = str(manifest.get("path") or "").strip("/")
    if not rel_path or ".." in rel_path.split("/"):
        raise DatasetError(f"数据清单 path 不合法：{rel_path!r}")

    target_dir = out_root / rel_path
    pack_path = out_root / f"{rel_path}.pack.xz"
    existing_manifest = _read_json_if_exists(target_dir / "latest.json")
    if (
        not force
        and existing_manifest is not None
        and _manifest_sig(existing_manifest) == _manifest_sig(manifest)
        and (not build_pack or pack_path.is_file())
    ):
        try:
            Dataset(target_dir, "mirror")
            raw_bytes = sum(int(f.get("size") or 0) for f in manifest["files"].values())
            return {
                "path": rel_path,
                "patch": manifest.get("patch"),
                "seq": manifest.get("seq"),
                "updated": False,
                "raw_bytes": raw_bytes,
                "pack_bytes": pack_path.stat().st_size if pack_path.is_file() else 0,
            }
        except (DatasetError, OSError, ValueError):
            pass

    staging = target_dir.with_name(target_dir.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    raw_bytes = 0
    try:
        for name, meta in manifest["files"].items():
            body = read_file(rel_path, name)
            if hashlib.sha256(body).hexdigest() != meta["sha256"]:
                raise DatasetError(f"{rel_path}/{name} SHA-256 校验失败")
            if "size" in meta and len(body) != meta["size"]:
                raise DatasetError(f"{rel_path}/{name} 文件大小校验失败（{len(body)} != {meta['size']}）")
            dest_file = _dataset_file(staging, name)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(body)
            raw_bytes += len(body)
        (staging / "latest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # 完整校验结构与全部文件哈希
        Dataset(staging, "mirror")

        pack_bytes = 0
        tmp_pack = None
        if build_pack:
            blob = make_pack(staging, manifest)
            # 自检：解包后逐个文件核对 SHA-256，确保客户端可无损还原
            unpacked = unpack(blob)
            for name, meta in manifest["files"].items():
                if name not in unpacked or hashlib.sha256(unpacked[name]).hexdigest() != meta["sha256"]:
                    raise DatasetError(f"{rel_path}.pack.xz 自检失败：{name} 还原后 SHA-256 不一致")
            tmp_pack = pack_path.with_name(pack_path.name + ".tmp")
            tmp_pack.parent.mkdir(parents=True, exist_ok=True)
            tmp_pack.write_bytes(blob)
            pack_bytes = len(blob)

        old = target_dir.with_name(target_dir.name + ".old")
        if target_dir.exists():
            shutil.rmtree(old, ignore_errors=True)
            target_dir.rename(old)
        try:
            staging.rename(target_dir)
            if tmp_pack is not None:
                tmp_pack.replace(pack_path)
        except OSError:
            if not target_dir.exists() and old.exists():
                old.rename(target_dir)
            raise
        shutil.rmtree(old, ignore_errors=True)
        return {
            "path": rel_path,
            "patch": manifest.get("patch"),
            "seq": manifest.get("seq"),
            "updated": True,
            "raw_bytes": raw_bytes,
            "pack_bytes": pack_bytes,
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def sync_mirror(
    out_root: Path,
    *,
    source_url: str = DEFAULT_SOURCE,
    local_from: Path | None = None,
    proxy: str | None = None,
    build_pack: bool = True,
    include_events: bool = False,
    force: bool = False,
    timeout: float = 60.0,
) -> dict:
    """同步最新统计数据（及可选活动模式数据）到静态镜像目录 out_root。"""
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    if local_from is not None:
        src = Path(local_from)
        manifest = json.loads((src / "latest.json").read_text(encoding="utf-8"))
        # 兼容 lolhex/data/bundled（平铺目录）和 aramhex-data 仓库根（含 patches/<patch>/<mode>）
        def read_local(rel_path: str, name: str) -> bytes:
            nested = src / rel_path / name
            if nested.is_file():
                return nested.read_bytes()
            return (src / name).read_bytes()
        read_fn = read_local
        index_data = _read_json_if_exists(src / "index.json")
    else:
        base = source_url.rstrip("/")
        session = _make_session(proxy)
        manifest = json.loads(_fetch_bytes(session, f"{base}/latest.json", timeout=timeout).decode("utf-8"))
        def read_remote(rel_path: str, name: str) -> bytes:
            return _fetch_bytes(session, f"{base}/{rel_path}/{name}", timeout=timeout)
        read_fn = read_remote
        index_data = None
        try:
            index_data = json.loads(_fetch_bytes(session, f"{base}/index.json", timeout=timeout).decode("utf-8"))
        except Exception:
            index_data = None

    results = [_sync_one_dataset(manifest, out_root, read_file=read_fn, build_pack=build_pack, force=force)]

    # 写根目录 latest.json（原子替换）
    latest_tmp = out_root / "latest.json.tmp"
    latest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    latest_tmp.replace(out_root / "latest.json")

    # 可选同步 index.json 与最新活动规则（如首次必棱彩）
    if isinstance(index_data, dict):
        if include_events:
            datasets = index_data.get("datasets") or []
            seen_modes: set[str] = {str(manifest.get("mode") or "normal")}
            for ds_entry in sorted(
                (d for d in datasets if isinstance(d, dict) and d.get("files") and d.get("path")),
                key=lambda d: (str(d.get("snapshot_at") or ""), int(d.get("seq") or 0)),
                reverse=True,
            ):
                mode = str(ds_entry.get("mode") or "")
                if not mode or mode in seen_modes:
                    continue
                seen_modes.add(mode)
                ev_manifest = {**ds_entry, "schema_version": ds_entry.get("schema_version", 1)}
                try:
                    results.append(_sync_one_dataset(ev_manifest, out_root, read_file=read_fn, build_pack=build_pack, force=force))
                except Exception as exc:
                    print(f"[跳过活动数据 {mode}] {exc}", file=sys.stderr)
        idx_tmp = out_root / "index.json.tmp"
        idx_tmp.write_text(json.dumps(index_data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        idx_tmp.replace(out_root / "index.json")

    return {
        "out": str(out_root),
        "updated": any(r["updated"] for r in results),
        "datasets": results,
    }


def _rsync_to_nas(out_root: Path, target: str) -> None:
    cmd = ["rsync", "-az", "--delete", f"{out_root.resolve()}/", target.rstrip("/") + "/"]
    print("同步到 NAS：", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _serve_dir(out_root: Path, host: str, port: int) -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(out_root.resolve()))
    srv = ThreadingHTTPServer((host, port), handler)
    print(f"静态镜像服务已启动：http://{host}:{port}/latest.json  （Ctrl+C 退出）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步 czgreat/aramhex-data 到本地/NAS 静态镜像目录并生成 .pack.xz")
    ap.add_argument("--out", required=True, type=Path, help="镜像输出目录（如 /volume1/web/aramhex-data）")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help=f"上游静态源 URL（默认 {DEFAULT_SOURCE}）")
    ap.add_argument("--from", dest="local_from", type=Path, default=None, help="改为从本地目录构建（如 lolhex/data/bundled 或本地克隆）")
    ap.add_argument("--proxy", default=None, help="HTTP 代理地址（如 http://127.0.0.1:7897）")
    ap.add_argument("--no-pack", action="store_true", help="不生成 .pack.xz 压缩包")
    ap.add_argument("--include-events", action="store_true", help="同时同步 index.json 中最新的活动模式数据")
    ap.add_argument("--force", action="store_true", help="即使版本未变也强制重新同步和重新打包")
    ap.add_argument("--rsync", default=None, help="同步完成后 rsync 推送目标（如 user@192.168.31.159:/volume1/web/aramhex-data）")
    ap.add_argument("--serve", type=int, default=0, help="同步完成后在指定端口起一个临时 HTTP 服务验证")
    ap.add_argument("--host", default="127.0.0.1", help="--serve 监听地址（默认 127.0.0.1）")
    args = ap.parse_args(argv)

    res = sync_mirror(
        args.out,
        source_url=args.source,
        local_from=args.local_from,
        proxy=args.proxy,
        build_pack=not args.no_pack,
        include_events=args.include_events,
        force=args.force,
    )
    for d in res["datasets"]:
        status = "已更新" if d["updated"] else "已是最新（跳过）"
        pack_info = f"，pack.xz {d['pack_bytes']/1e6:.2f} MB（原 {d['raw_bytes']/1e6:.2f} MB）" if d["pack_bytes"] else ""
        print(f"[{status}] {d['path']} (patch={d['patch']} seq={d['seq']}{pack_info})")

    if args.rsync:
        _rsync_to_nas(args.out, args.rsync)
    if args.serve:
        _serve_dir(args.out, args.host, args.serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
