from __future__ import annotations

import json
import os
from pickle import FALSE
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen

ADDRESS = "https://thumbnails.libretro.com"
DEF_SCORE = 90
MAX_SCORE = 100
THUMB_DIRS = ["Named_Boxarts", "Named_Titles", "Named_Snaps", "Named_Logos"]

# 直接修改这些变量即可运行脚本示例
FILENAME = "Super Mario Bros. 3"
SYSTEM = "Nintendo - Nintendo Entertainment System"
MIN_SCORE = DEF_SCORE
LIMIT = 5
NO_META = True
HACK = False
BEFORE = None
REQUEST_TIMEOUT = 15
READ_CHUNK_SIZE = 64 * 1024
MAX_DIRECTORY_BYTES = 20 * 1024 * 1024
SHOW_PROGRESS = True
THUMBNAIL_JSON_DIR = "thumbnail_json"
BUILD_ALL_PLATFORM_JSON = False
BUILD_JSON_IF_SYSTEM_MISSING = True
SKIP_EXISTING_PLATFORM_JSON = True

forbidden = re.compile(
    r"[\u0022\u003c\u003e\u007c\u0000\u0001\u0002\u0003\u0004\u0005\u0006\u0007\u0008"
    + r"\u0009\u000a\u000b\u000c\u000d\u000e\u000f\u0010\u0011\u0012\u0013\u0014\u0015"
    + r"\u0016\u0017\u0018\u0019\u001a\u001b\u001c\u001d\u001e\u001f\u003a\u002a\u003f\u005c\u002f\u0026]"
)
camelcase_pattern = re.compile(
    r"((?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[0-9])(?=[A-Z][a-z])|(?<=[a-zA-Z])(?=[0-9]))"
)
zero_lead_pattern = re.compile(r"([^\d])0+([1-9])")
almost_symbols_pattern = re.compile(r"[^\w\s,']")
roman_bounded_numeral = re.compile(r"\b[IVXLCDM]+\b")
roman_numerals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


@dataclass(frozen=True)
class Match:
    name: str
    score: float
    urls: dict[str, str]


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


def text_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() * 100


def extdigits(input_str: str) -> str:
    result = ""
    for ch in input_str:
        if ch.isdigit():
            result += ch
    return result


def removeparenthesis(input_str: str, open_p: str = "(", close_p: str = ")") -> str:
    result = ""
    remainder = ""
    paren_level = 0
    for ch in input_str:
        if ch == open_p:
            if paren_level < 0:
                paren_level = 1
            else:
                paren_level += 1
        elif ch == close_p:
            paren_level -= 1
            remainder = ""
        elif paren_level <= 0:
            result += ch
        else:
            remainder += ch
    return result + remainder


def extractbefore(before: str | None, name: str) -> str:
    if before:
        name_without_meta = re.search(r"(^[^\[({]*)", name)
        if name_without_meta:
            before_index = name_without_meta.group(1).find(before)
            if before_index != -1:
                return name[0:before_index]
    return name


def replacemany(our_str: str, to_be_replaced: str, replace_with: str) -> str:
    for nextchar in to_be_replaced:
        our_str = our_str.replace(nextchar, replace_with)
    return our_str


def removefirst(name: str, suf: str) -> str:
    return name.replace(suf, "", 1)


def removeprefix(name: str, pre: str) -> str:
    if name.startswith(pre):
        return name[len(pre) :]
    return name


def from_roman(num: str) -> int:
    result = 0
    for i, c in enumerate(num):
        if (i + 1) == len(num) or roman_numerals[c] >= roman_numerals[num[i + 1]]:
            result += roman_numerals[c]
        else:
            result -= roman_numerals[c]
    return result


def replace_roman(source: str) -> str:
    return roman_bounded_numeral.sub(lambda m: str(from_roman(m.group())), source)


def normalize_game_name(name: str, *, no_meta: bool = False, hack: bool = False) -> tuple[str, str, list[str], str]:
    if no_meta:
        name = removeparenthesis(name, "(", ")")
    if not hack:
        name = removeparenthesis(name, "[", "]")

    name = name.replace("_", " ")
    name = re.sub(zero_lead_pattern, r"\g<1>\g<2>", name)
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))

    subtitles = name.split(" - ")
    if len(subtitles) == 1:
        subtitles = name.split(": ")

    subtitles_no_space = [""] * len(subtitles)
    for i, subtitle in enumerate(subtitles):
        stripped_symbols = re.sub(almost_symbols_pattern, "", subtitle)
        if stripped_symbols:
            subtitle = stripped_symbols

        subtitle = " ".join(part for token in re.split(camelcase_pattern, subtitle) if token and (part := token.strip()))
        subtitle = replace_roman(subtitle)
        subtitle = subtitle.replace("Center", "Centre")
        subtitle = subtitle.lower()
        subtitle = subtitle.replace("1rst", "1st")
        subtitle = subtitle.replace("first", "1st")
        subtitle = subtitle.replace("second", "2nd")
        subtitle = subtitle.replace("third", "3rd")
        subtitle = subtitle.replace("fourth", "4th")
        subtitle = subtitle.replace("fifth", "5th")
        subtitle = subtitle.replace("sixth", "6th")
        subtitle = subtitle.replace("seventh", "7th")
        subtitle = subtitle.replace("eighth", "8th")
        subtitle = subtitle.replace("ninth", "9th")
        subtitle = subtitle.replace("tenth", "10th")

        for suffix, prefix in [
            (", the", "the "),
            (", los", "los "),
            (", las", "las "),
            (", les", "les "),
            (", le", "le "),
            (", la", "la "),
            (", l'", "l'"),
            (", der", "der "),
            (", die", "die "),
            (", das", "das "),
            (", el", "el "),
            (", os", "os "),
            (", as", "as "),
            (", o", "o "),
            (", a", "a "),
        ]:
            subtitle = removefirst(subtitle, suffix)
            subtitle = removeprefix(subtitle, prefix)

        subtitle = replacemany(subtitle, ",'", "")
        subtitle = subtitle.replace(" and ", " ")
        subtitle = subtitle.replace(" the ", " ")
        words = subtitle.strip().split()
        subtitles[i] = " ".join(words)
        subtitles_no_space[i] = "".join(words)

    no_space_name = "".join(subtitles_no_space)
    return " ".join(subtitles), no_space_name, subtitles_no_space, extdigits(no_space_name)


def normalize_local_name(name: str, *, no_meta: bool = False, hack: bool = False, before: str | None = None):
    safe_name = re.sub(forbidden, "_", extractbefore(before, name))
    return name, normalize_game_name(safe_name, no_meta=no_meta, hack=hack)


def normalize_remote_name(name: str, *, no_meta: bool = False, hack: bool = False):
    return name, normalize_game_name(name, no_meta=no_meta, hack=hack)


class TitleScorer:
    def __init__(self, local_norms: dict, remote_norms: dict, hack: bool = False):
        self.local_norms = local_norms
        self.remote_norms = remote_norms
        self.hack = hack

    def __call__(self, name, other):
        name, name_ns, name_ns_subs, digits = self.local_norms[name]
        other, other_ns, other_ns_subs, other_digits = self.remote_norms[other]
        if name == other or name_ns == other_ns:
            return MAX_SCORE
        if not name_ns:
            return 0

        remaining = MAX_SCORE - DEF_SCORE
        if not self.hack and other in self.local_norms:
            remaining -= remaining * 0.65

        rest_of_score = text_ratio(digits, other_digits) * 0.01 * 0.03 * remaining
        heuristic = remaining * 0.97
        ratio = text_ratio(name, other) * 0.01

        if not name_ns.isdigit():
            sum_ns = ""
            for sub_ns in other_ns_subs:
                if name_ns == sub_ns or name_ns == (sum_ns := sum_ns + sub_ns):
                    rest_of_score += heuristic * ratio
                    return DEF_SCORE + rest_of_score
        if not other_ns.isdigit():
            sum_ns = ""
            for sub_ns in name_ns_subs:
                if other_ns == sub_ns or other_ns == (sum_ns := sum_ns + sub_ns):
                    rest_of_score += heuristic * ratio
                    return DEF_SCORE + rest_of_score

        common = len(os.path.commonprefix([name_ns, other_ns])) / len(name_ns)
        parity = min(len(name_ns), len(other_ns)) / max(len(name_ns), len(other_ns))
        rest_of_score += (heuristic * common * 0.80) + (heuristic * parity * 0.20)
        return rest_of_score + DEF_SCORE * ratio


def read_url_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "thumbnail-matcher/1.0"})
    chunks = []
    total = 0
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        while True:
            chunk = response.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if SHOW_PROGRESS:
                print(f"  read {total // 1024} KB", end="\r")
            if total > MAX_DIRECTORY_BYTES:
                raise RuntimeError(f"Directory response is too large: {url}")
    if SHOW_PROGRESS and total:
        print(f"  read {total // 1024} KB")
    return b"".join(chunks).decode("utf-8", errors="replace")


def scan_thumbnail_directory(
    system: str,
    *,
    address: str = ADDRESS,
    thumb_dirs: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    thumb_dirs = thumb_dirs or THUMB_DIRS
    base_url = address.rstrip("/") + "/" + quote(system)
    result = {}

    for thumb_dir in thumb_dirs:
        directory_url = f"{base_url}/{thumb_dir}/"
        if SHOW_PROGRESS:
            print(f"Scanning {directory_url}")
        try:
            html = read_url_text(directory_url)
        except HTTPError as exc:
            if exc.code in (400, 404):
                result[thumb_dir] = {}
                continue
            raise RuntimeError(f"Could not scan thumbnail directory {directory_url}: {exc}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not scan thumbnail directory {directory_url}: {exc}") from exc

        parser = LinkParser()
        parser.feed(html)
        result[thumb_dir] = {
            unquote(Path(href).name[:-4]): directory_url + href
            for href in parser.hrefs
            if href.endswith(".png")
        }
        if SHOW_PROGRESS:
            print(f"  found {len(result[thumb_dir])} png files")

    return result


def list_thumbnail_systems(address: str = ADDRESS) -> list[str]:
    root_url = address.rstrip("/") + "/"
    if SHOW_PROGRESS:
        print(f"Scanning systems from {root_url}")
    html = read_url_text(root_url)
    parser = LinkParser()
    parser.feed(html)

    systems = []
    for href in parser.hrefs:
        if not href.endswith("/"):
            continue
        name = unquote(href.strip("/"))
        if name and not name.startswith(("?", "/")):
            systems.append(name)
    return sorted(set(systems))


def safe_json_filename(system: str) -> str:
    safe_name = re.sub(forbidden, "_", system).strip(" .")
    return f"{safe_name or 'unknown'}.json"


def system_json_path(system: str, json_dir: str | Path = THUMBNAIL_JSON_DIR) -> Path:
    return Path(json_dir, safe_json_filename(system))


def build_system_thumbnails_json(
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    address: str = ADDRESS,
    thumb_dirs: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    thumbnail_index = scan_thumbnail_directory(system, address=address, thumb_dirs=thumb_dirs)
    json_dir = Path(json_dir)
    json_dir.mkdir(parents=True, exist_ok=True)
    output_path = system_json_path(system, json_dir)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(thumbnail_index, file, ensure_ascii=False, indent=2)
    return thumbnail_index


def build_all_system_thumbnail_json_files(
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    address: str = ADDRESS,
    thumb_dirs: list[str] | None = None,
    skip_existing: bool = True,
) -> list[str]:
    json_dir = Path(json_dir)
    json_dir.mkdir(parents=True, exist_ok=True)
    systems = list_thumbnail_systems(address)
    for index, system in enumerate(systems, 1):
        output_path = system_json_path(system, json_dir)
        if skip_existing and output_path.exists():
            if SHOW_PROGRESS:
                print(f"[{index}/{len(systems)}] exists: {output_path.name}")
            continue
        if SHOW_PROGRESS:
            print(f"[{index}/{len(systems)}] {system}")
        try:
            build_system_thumbnails_json(system, json_dir, address=address, thumb_dirs=thumb_dirs)
        except RuntimeError as exc:
            print(f"  skipped: {exc}")
    return systems


def load_system_thumbnails_json(
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
) -> dict[str, dict[str, str]]:
    with system_json_path(system, json_dir).open("r", encoding="utf-8") as file:
        return json.load(file)


def find_image_for_filename_from_json(
    filename: str,
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    thumbnail_index = load_system_thumbnails_json(system, json_dir)
    return find_best_thumbnails(
        filename,
        thumbnail_index,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def find_image_for_filename_from_json_or_build(
    filename: str,
    system: str,
    json_dir: str | Path = THUMBNAIL_JSON_DIR,
    *,
    address: str = ADDRESS,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    path = system_json_path(system, json_dir)
    if not path.exists():
        build_system_thumbnails_json(system, json_dir, address=address)

    thumbnail_index = load_system_thumbnails_json(system, json_dir)
    if not thumbnail_index:
        build_system_thumbnails_json(system, json_dir, address=address)
        thumbnail_index = load_system_thumbnails_json(system, json_dir)

    return find_best_thumbnails(
        filename,
        thumbnail_index,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def build_remote_names(thumbnail_index: dict[str, dict[str, str]]) -> set[str]:
    remote_names = set()
    for images in thumbnail_index.values():
        remote_names.update(images.keys())
    return remote_names


def game_name_from_filename(filename: str) -> str:
    path = Path(filename)
    if path.suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,7}", path.suffix):
        return path.stem
    return filename


def find_best_thumbnails(
    filename: str,
    thumbnail_index: dict[str, dict[str, str]],
    *,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    game_name = game_name_from_filename(filename)
    remote_names = build_remote_names(thumbnail_index)
    if not remote_names:
        return []

    local_norms = dict([normalize_local_name(game_name, no_meta=no_meta, hack=hack, before=before)])
    remote_norms = dict(normalize_remote_name(name, no_meta=no_meta, hack=hack) for name in remote_names)
    scorer = TitleScorer(local_norms, remote_norms, hack=hack)

    scored = sorted(
        ((remote_name, scorer(game_name, remote_name)) for remote_name in remote_names),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]

    matches = []
    for remote_name, score in scored:
        if score < min_score:
            continue
        urls = {
            thumb_type: images[remote_name]
            for thumb_type, images in thumbnail_index.items()
            if remote_name in images
        }
        matches.append(Match(name=remote_name, score=score, urls=urls))
    return matches


def find_image_for_filename(
    filename: str,
    system: str,
    *,
    address: str = ADDRESS,
    min_score: int = DEF_SCORE,
    limit: int = 5,
    no_meta: bool = False,
    hack: bool = False,
    before: str | None = None,
) -> list[Match]:
    thumbnail_index = scan_thumbnail_directory(system, address=address)
    return find_best_thumbnails(
        filename,
        thumbnail_index,
        min_score=min_score,
        limit=limit,
        no_meta=no_meta,
        hack=hack,
        before=before,
    )


def run_example():
    if BUILD_ALL_PLATFORM_JSON:
        systems = build_all_system_thumbnail_json_files(
            THUMBNAIL_JSON_DIR,
            address=ADDRESS,
            skip_existing=SKIP_EXISTING_PLATFORM_JSON,
        )
        print(f"Checked {len(systems)} platform JSON files in {THUMBNAIL_JSON_DIR}")

    if BUILD_JSON_IF_SYSTEM_MISSING:
        matches = find_image_for_filename_from_json_or_build(
            FILENAME,
            SYSTEM,
            THUMBNAIL_JSON_DIR,
            address=ADDRESS,
            min_score=MIN_SCORE,
            limit=LIMIT,
            no_meta=NO_META,
            hack=HACK,
            before=BEFORE,
        )
    else:
        matches = find_image_for_filename_from_json(
            FILENAME,
            SYSTEM,
            THUMBNAIL_JSON_DIR,
            min_score=MIN_SCORE,
            limit=LIMIT,
            no_meta=NO_META,
            hack=HACK,
            before=BEFORE,
        )

    if not matches:
        print("No match found")
        return

    for match in matches:
        print(f"{match.score:.1f} {match.name}")
        for thumb_type, url in match.urls.items():
            print(f"  {thumb_type}: {url}")


def main():
    run_example()


if __name__ == "__main__":
    main()
