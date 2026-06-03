"""调试入口：在 PC（Windows/macOS/Linux 桌面）上调试 tiny_scraper.scraper。

使用方法：
    1) 在下方【调试参数区】填好你要的参数。
    2) 在 IDE 里直接 Run / F5 即可，无需命令行。

设计说明：
- 不导入 main / app / graphic / input，避免掌机硬件依赖（/dev/fb0、/dev/input/event1、fcntl 等）。
- 只复用纯逻辑：Scraper、systems。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PKG_DIR = PROJECT_ROOT / "tiny_scraper"
sys.path.insert(0, str(PKG_DIR))

from scraper import Scraper  # noqa: E402
from systems import get_system_id, get_system_extension, systems  # noqa: E402


# ============================================================
# 【调试参数区】改这里就好，不要传命令行
# ============================================================

# 可选模式： "crc" / "scrape" / "scan"
#   crc    -> 只计算 ROM_PATH 的 CRC32
#   scrape -> 抓取 ROM_PATH 单个 ROM 的媒体，存到 OUT_DIR
#   scan   -> 扫描 ROMS_ROOT/SYSTEM 下所有缺图 ROM，可选 DOWNLOAD 批量下载
MODE: str = "scrape"

# screenscraper.fr 账号配置文件（必填用户/密码）
CONFIG_PATH: Path = PKG_DIR / "config.json"

# 单 ROM 调试（MODE=crc 或 scrape 时使用）
# 支持两种值：
#   1) 单个 ROM 文件： Path(r"D:\roms\GBA\Pokemon.gba")
#   2) 一个文件夹：    Path(r"D:\roms\GBA")  会按 SYSTEM 的扩展名过滤后逐个处理
ROM_PATH: Path = Path(r"F:/RG556/gba/运动游戏")

# 系统名（必须在 tiny_scraper/systems.py 中存在），常用值：
#   GBA / GBC / GB / FC / SFC / MD / N64 / PS / PSP / NDS / SMS / GG / ...
SYSTEM: str = "GBA"

# scrape 模式输出目录
OUT_DIR: Path = PROJECT_ROOT / "out"

# scan 模式：ROM 根目录（其下应有 <SYSTEM>/ 子目录）
ROMS_ROOT: Path = Path(r"F:/RG556/gba/运动游戏")

# scan 模式：列出 / 下载的最大条数，0 表示不限
LIMIT: int = 5

# scan 模式：是否实际下载到 <ROMS_ROOT>/<SYSTEM>/Imgs/
DOWNLOAD: bool = False

# ============================================================


def _build_scraper(config_path: Path) -> Scraper:
    s = Scraper()
    ok = s.load_config_from_json(str(config_path))
    if not ok:
        print(f"[WARN] 未找到配置文件 {config_path}，将使用空账号（可能 401）")
    print(f"[INFO] user={s.user!r}  media_type={s.media_type!r}  region={s.region!r}")
    return s


def _collect_roms(path: Path, system: str) -> list[Path]:
    """根据 ROM_PATH 收集要处理的 ROM 文件列表。
    - 文件：直接返回 [path]
    - 目录：按 system 的扩展名过滤，跳过隐藏文件
    """
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []

    exts = {e.lower() for e in get_system_extension(system)}
    if not exts:
        print(f"[WARN] 系统 {system} 未在 systems.py 中定义扩展名，将列出目录内所有文件")
        return [p for p in sorted(path.iterdir()) if p.is_file() and not p.name.startswith((".", "-"))]

    roms: list[Path] = []
    for p in sorted(path.iterdir()):
        if not p.is_file() or p.name.startswith((".", "-")):
            continue
        if p.suffix.lower().lstrip(".") in exts:
            roms.append(p)
    return roms


def do_crc() -> int:
    if not ROM_PATH.exists():
        print(f"[ERR] 路径不存在：{ROM_PATH}")
        return 2
    targets = _collect_roms(ROM_PATH, SYSTEM)
    if not targets:
        print(f"[ERR] 没有找到任何匹配的 ROM 文件：{ROM_PATH}")
        return 2

    s = Scraper()
    print(f"[INFO] 共 {len(targets)} 个 ROM 待计算 CRC32")
    for i, rom in enumerate(targets, 1):
        try:
            crc = s.get_crc32_from_file(rom)
            print(f"[{i}/{len(targets)}] {crc}  {rom.name}")
        except Exception as exc:
            print(f"[{i}/{len(targets)}] [EXC] {rom.name}: {exc}")
    return 0


def do_scrape() -> int:
    if not ROM_PATH.exists():
        print(f"[ERR] 路径不存在：{ROM_PATH}")
        return 2

    system_id = get_system_id(SYSTEM)
    if system_id <= 0:
        valid = ", ".join(sorted({sys_["name"] for sys_ in systems}))
        print(f"[ERR] 未知或不可抓取的系统：{SYSTEM}\n可用：{valid}")
        return 2

    targets = _collect_roms(ROM_PATH, SYSTEM)
    if not targets:
        print(f"[ERR] 没有找到任何匹配的 ROM 文件：{ROM_PATH}")
        return 2

    s = _build_scraper(CONFIG_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] system={SYSTEM}(id={system_id}) 待抓取 {len(targets)} 个 ROM")

    success = fail = 0
    for i, rom in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {rom.name}")
        try:
            crc = s.get_crc32_from_file(rom)
            img = s.scrape_screenshot(
                crc=crc,
                game_name=rom.name,
                system_id=system_id,
            )
        except Exception as exc:
            print(f"    [EXC] {exc}")
            fail += 1
            continue
        if not img:
            print("    [FAIL] 没有抓到任何媒体")
            fail += 1
            continue
        out_file = OUT_DIR / f"{rom.stem}.png"
        out_file.write_bytes(img)
        print(f"    [OK] {len(img)} 字节 -> {out_file}")
        success += 1

    print(f"[DONE] 成功 {success}，失败 {fail}")
    return 0 if fail == 0 else 1


def do_scan() -> int:
    if not ROMS_ROOT.is_dir():
        print(f"[ERR] ROM 根目录不存在：{ROMS_ROOT}")
        return 2

    system_id = get_system_id(SYSTEM)
    if system_id <= 0:
        print(f"[WARN] 系统 {SYSTEM} 没有有效的 screenscraper id，只能列出缺图，不能抓取")

    if not get_system_extension(SYSTEM):
        print(f"[ERR] 系统 {SYSTEM} 未在 systems.py 中定义扩展名")
        return 2

    s = _build_scraper(CONFIG_PATH)
    roms = s.get_roms(str(ROMS_ROOT), SYSTEM)
    if not roms:
        print(f"[INFO] {ROMS_ROOT / SYSTEM} 下没有发现任何 ROM")
        return 0

    imgs_folder = ROMS_ROOT / SYSTEM / "Imgs"
    if imgs_folder.exists():
        existing = set(s.get_image_files_without_extension(imgs_folder))
    else:
        existing = set()

    missing = [r for r in roms if r.name not in existing]
    missing.sort(key=lambda r: r.name)

    print(f"[INFO] 共 {len(roms)} 个 ROM，缺图 {len(missing)} 个")
    preview = missing[:LIMIT] if LIMIT else missing
    for r in preview:
        print(f"  - {r.filename}")
    if LIMIT and len(missing) > LIMIT:
        print(f"  ...（仅显示前 {LIMIT} 个，共 {len(missing)}）")

    if not DOWNLOAD:
        return 0
    if system_id <= 0:
        print("[ERR] 无法下载：系统 id 无效")
        return 1

    imgs_folder.mkdir(parents=True, exist_ok=True)
    success = fail = 0
    system_path = ROMS_ROOT / SYSTEM
    for i, rom in enumerate(preview, 1):
        print(f"[{i}/{len(preview)}] {rom.filename}")
        try:
            rom.set_crc(s.get_crc32_from_file(system_path / rom.filename))
            img = s.scrape_screenshot(
                crc=rom.crc, game_name=rom.name, system_id=system_id
            )
        except Exception as exc:
            print(f"    [EXC] {exc}")
            fail += 1
            continue
        if img:
            out_file = imgs_folder / f"{rom.name}.png"
            out_file.write_bytes(img)
            print(f"    [OK] -> {out_file}")
            success += 1
        else:
            print("    [MISS] 未抓到媒体")
            fail += 1
    print(f"[DONE] 成功 {success}，失败 {fail}")
    return 0


DISPATCH = {
    "crc": do_crc,
    "scrape": do_scrape,
    "scan": do_scan,
}


def main() -> int:
    func = DISPATCH.get(MODE)
    if func is None:
        print(f"[ERR] 未知 MODE：{MODE!r}，可选：{list(DISPATCH)}")
        return 2
    print(f"[INFO] MODE = {MODE}")
    return func()


if __name__ == "__main__":
    raise SystemExit(main())
