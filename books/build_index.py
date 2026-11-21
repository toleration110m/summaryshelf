#!/usr/bin/env python3
"""
build_index.py — ساخت books.json از پوشه‌های books/<slug>/<slug>.md

هر بار کتابی را اضافه یا ویرایش کردی (مثلاً عوض شدن date_updated)، قبل از commit:

    python3 books/build_index.py

صفحه‌ی اصلی فقط همین فایل کوچک را می‌خواند، نه همه‌ی فایل‌های Markdown را.
فایل‌هایی که اسمشان با «_» شروع شود (مثلاً _draft.md) نادیده گرفته می‌شوند.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "books.json"

FM = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n?", re.S)
LINE = re.compile(r"^([a-zA-Z_]+):\s*(.*)$")


def parse_frontmatter(raw: str) -> dict:
    # همان منطق parseFrontmatter در app.js: BOM و CRLF را تحمل می‌کند
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    m = FM.match(raw)
    meta = {}
    if not m:
        return meta
    for line in m.group(1).split("\n"):
        lm = LINE.match(line)
        if not lm:
            continue
        key, value = lm.group(1).strip(), lm.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            value = [x.strip() for x in value[1:-1].split(",") if x.strip()]
        meta[key] = value
    return meta


def main() -> int:
    if not ROOT.is_dir():
        print("پوشه‌ی books پیدا نشد.", file=sys.stderr)
        return 1

    books = []
    dirs = sorted((path for path in ROOT.iterdir() if path.is_dir()), key=lambda path: path.name)
    for book_dir in dirs:
        if book_dir.name.startswith("_"):
            continue
        path = book_dir / f"{book_dir.name}.md"
        if not path.is_file():
            continue
        meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not meta.get("title"):
            print(f"هشدار: {path.name} فیلد title ندارد.", file=sys.stderr)
        meta.pop("cover", None)
        books.append({"slug": path.stem, **meta})

    new_text = json.dumps(books, ensure_ascii=False, indent=2) + "\n"

    # فایل فعلی را با تبدیل CRLF به LF می‌خوانیم تا مقایسه دقیق باشد
    old_text = None
    if OUT.exists():
        old_text = OUT.read_bytes().decode("utf-8").replace("\r\n", "\n")

    if old_text == new_text:
        print(f"{len(books)} کتاب؛ {OUT.name} تغییری نداشت و دست نخورد.")
        return 0

    # newline="\n": روی ویندوز هم همیشه LF بنویس (با eol=lf در .gitattributes هماهنگ)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    print(f"{len(books)} کتاب در {OUT.name} نوشته شد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())