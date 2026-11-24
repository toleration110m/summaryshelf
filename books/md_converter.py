import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import re
import sys
import os
import json
import html
import datetime
import shutil
import tempfile
from urllib.parse import quote, unquote

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:  # Pillow نصب نیست
    PIL_AVAILABLE = False


APP_NAME = "MdConverter"
APP_VERSION = "2026-11-24-e"  # برای اطمینان از اینکه نسخه‌ی درست اجرا می‌شود

# پیشوند آدرس تصاویر داخل فایل md: books/نام-کتاب/01.webp
# ساختار روی دیسک: <پوشه‌ی برنامه>/نام-کتاب/{نام-کتاب.md, 01.webp, ...}
LINK_PREFIX = "books"

# سرعت مطالعه (کلمه در دقیقه) برای محاسبه‌ی read_minutes
READING_WPM = 200

# تبدیل تصاویر به WebP (کیفیت 1 تا 100؛ ۸۵ تعادل خوبی بین حجم و کیفیت است)
WEBP_QUALITY = 85
WEBP_CONVERTIBLE = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif"}


# ==================================================
# مسیر config بر اساس سیستم‌عامل
# ==================================================
def get_config_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / APP_NAME


CONFIG_FILE = get_config_dir() / "config.json"


# ==================================================
# توابع config
# ==================================================
def load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data):
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def load_last_open_dir():
    return load_config().get("last_open_dir", "")


def save_last_open_dir(path):
    config = load_config()
    config["last_open_dir"] = str(path)
    save_config(config)


def make_output_name(input_path):
    """نام فایل ورودی، حروف کوچک، و فاصله‌ها به dash: 'My Book.docx' -> 'my-book.md'"""
    stem = re.sub(r'\s+', '-', input_path.stem.strip()).lower()
    return stem + ".md"


# ==================================================
# مسیر اسکریپت
# ==================================================
def get_script_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


# ==================================================
# پاک‌سازی markdown
# ==================================================
def remove_direction_spans(text):
    text = re.sub(
        r'<span\s+dir=["\'](?:rtl|ltr)["\']\s*>',
        '', text, flags=re.IGNORECASE
    )
    text = re.sub(r'</span>', '', text, flags=re.IGNORECASE)
    return text


def clean_list_spacing(text):
    lines = text.splitlines()
    result = []

    for line in lines:
        line = re.sub(r'^(\s*[-*+])\s+', r'\1 ', line)
        line = re.sub(r'^(\s*\d+[.)])\s+', r'\1 ', line)
        result.append(line)

    cleaned = []
    i = 0
    while i < len(result):
        current = result[i]
        if (
            i + 2 < len(result)
            and current.strip()
            and result[i + 1].strip() == ""
            and result[i + 2].strip()
        ):
            current_is_list = re.match(
                r'^\s*(?:[-*+]|\d+[.)])\s+', current
            )
            next_is_list = re.match(
                r'^\s*(?:[-*+]|\d+[.)])\s+', result[i + 2]
            )
            if current_is_list and next_is_list:
                cleaned.append(current)
                i += 2
                continue
        cleaned.append(current)
        i += 1

    return "\n".join(cleaned)


# ==================================================
# استخراج بلوک META
# ==================================================
def extract_meta_block(text):
    pattern = re.compile(
        r'\\?\[\s*META\s*\\?\]'
        r'(.*?)'
        r'\\?\[\s*/\s*META\s*\\?\]',
        re.DOTALL | re.IGNORECASE
    )

    match = pattern.search(text)
    if not match:
        return None, text

    meta_content = match.group(1)

    text_without_meta = text[:match.start()] + text[match.end():]
    text_without_meta = text_without_meta.lstrip("\n")

    meta = {}
    for line in meta_content.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+)$', line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            # حذف backslash های escape pandoc
            value = re.sub(r'\\([\[\]\(\)\*_`~])', r'\1', value)
            meta[key] = value

    return meta, text_without_meta


# ==================================================
# تخمین زمان مطالعه
# ==================================================
def estimate_read_minutes(text, wpm=READING_WPM):
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', text)        # تصاویر
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)     # لینک: فقط متن
    text = re.sub(r'<[^>]+>', ' ', text)                       # تگ‌های HTML
    text = re.sub(r'https?://\S+', ' ', text)                  # آدرس‌ها
    text = text.replace("\u200c", "")                          # نیم‌فاصله
    words = re.findall(r'[^\W_]+', text)
    return max(1, round(len(words) / wpm))


def format_read_time(minutes):
    """کمتر از ۶۰: «X دقیقه». از ۶۰ به بالا: «X ساعت و Y دقیقه»."""
    if minutes < 60:
        return f"{minutes} دقیقه"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours} ساعت"
    return f"{hours} ساعت و {mins} دقیقه"


# ==================================================
# تاریخ شمسی امروز (بدون نیاز به کتابخانه‌ی خارجی)
# ==================================================
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100
        + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def today_jalali():
    t = datetime.date.today()
    jy, jm, jd = gregorian_to_jalali(t.year, t.month, t.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


# ==================================================
# ساخت front matter
# ==================================================
def build_front_matter(meta):
    if not meta:
        return ""

    field_order = [
        "title", "author", "category", "year_publish",
        "date_updated", "read_minutes", "rating",
        "tags", "quote", "cover"
    ]

    lines = ["---"]

    for key in field_order:
        if key in meta:
            value = meta[key]
            if key == "tags" and not value.startswith("["):
                value = f"[{value}]"
            lines.append(f"{key}: {value}")

    for key, value in meta.items():
        if key not in field_order:
            lines.append(f"{key}: {value}")

    lines.append("---")
    lines.append("")
    lines.append("")

    return "\n".join(lines)


# ==================================================
# سازماندهی تصاویر: <پوشه‌ی خروجی>/<نام کتاب>/01.webp, 02.webp, ...
# ==================================================
IMG_PATTERN = re.compile(
    r'!\[(?P<md_alt>(?:[^\]\\]|\\.)*)\]'
    r'\(\s*<?(?P<md_src>[^)\s>]+)>?'
    r'(?:\s+"(?P<md_title>(?:[^"\\]|\\.)*)")?\s*\)'
    r'|(?P<html><img\b[^>]*>)',
    re.IGNORECASE | re.DOTALL
)
IMAGE_SUFFIXES = {
    ".webp", ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".tif", ".tiff", ".emf", ".wmf", ".svg"
}
# فایل‌هایی که هنگام پاک‌سازی تصاویر قبلی هرگز حذف نمی‌شوند (cover.webp و ...)
PROTECTED_STEMS = {"cover"}
ATTR_PATTERN = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def parse_image(m):
    """از یک match، (alt, src, title) را برمی‌گرداند."""
    if m.group("html"):
        attrs = {
            k.lower(): html.unescape(v)
            for k, v in ATTR_PATTERN.findall(m.group("html"))
        }
        return attrs.get("alt", ""), attrs.get("src", ""), attrs.get("title", "")
    unesc = lambda t: re.sub(r'\\(.)', r'\1', t or "")
    return unesc(m.group("md_alt")), m.group("md_src"), unesc(m.group("md_title"))


def format_image(alt, url, title):
    """خروجی یکدست: ![alt](url "title")"""
    alt = re.sub(r'\s+', ' ', alt).strip()
    alt = alt.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    title = re.sub(r'\s+', ' ', title).strip().replace('"', '\\"')
    if title:
        return f'![{alt}]({url} "{title}")'
    return f'![{alt}]({url})'


def save_as_webp(src, dst):
    with Image.open(src) as img:
        if getattr(img, "is_animated", False):
            raise ValueError("animated image")  # متحرک‌ها دست‌نخورده می‌مانند
        img = ImageOps.exif_transpose(img)
        has_alpha = (
            img.mode in ("RGBA", "LA")
            or (img.mode == "P" and "transparency" in img.info)
        )
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.save(dst, "WEBP", quality=WEBP_QUALITY, method=6)


def format_size(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def organize_images(text, extract_dir, output_dir, doc_name):
    """
    تصاویر استخراج‌شده توسط pandoc را به ترتیب ظهور در متن به
    output_dir/doc_name/01.ext, 02.ext, ... منتقل می‌کند و همه‌ی
    تصاویر را با فرمت ![alt](مسیر "title") می‌نویسد.
    متن Description در Alt Text ورد، هم alt و هم title می‌شود.
    تصاویر قابل‌تبدیل (png/jpg/bmp/tiff/gif ثابت) به WebP تبدیل می‌شوند.
    خروجی: (متن جدید، تعداد تصاویر، آمار حجم)
    """
    extract_dir = Path(extract_dir)

    def resolve(src):
        if re.match(r'^(?:[a-z][a-z0-9+.-]*:|//)', src, re.IGNORECASE):
            return None  # لینک اینترنتی یا data:
        path = extract_dir / unquote(src).replace("\\", "/")
        return path if path.is_file() else None

    # ترتیب یکتای تصاویر بر اساس اولین ظهور
    ordered = []
    for m in IMG_PATTERN.finditer(text):
        p = resolve(parse_image(m)[1])
        if p and p not in ordered:
            ordered.append(p)

    stats = {"orig": 0, "new": 0, "webp": 0, "pillow": PIL_AVAILABLE}
    if not ordered:
        return text, 0, stats

    width = max(2, len(str(len(ordered))))
    target_dir = Path(output_dir) / doc_name

    # پاک‌سازی تصاویر تبدیل قبلی همین کتاب (فقط فایل‌های تصویری، نه کل پوشه)
    if target_dir.is_dir():
        for old_file in target_dir.iterdir():
            if (
                old_file.is_file()
                and old_file.suffix.lower() in IMAGE_SUFFIXES
                and old_file.stem.lower() not in PROTECTED_STEMS
            ):
                old_file.unlink()
    target_dir.mkdir(parents=True, exist_ok=True)

    new_names = {}
    for i, p in enumerate(ordered, start=1):
        stem = f"{i:0{width}d}"
        name = None

        if PIL_AVAILABLE and p.suffix.lower() in WEBP_CONVERTIBLE:
            candidate = target_dir / f"{stem}.webp"
            try:
                save_as_webp(p, candidate)
                name = candidate.name
                stats["webp"] += 1
            except Exception:
                candidate.unlink(missing_ok=True)

        if name is None:  # تبدیل نشد: فایل اصلی کپی می‌شود
            name = f"{stem}{p.suffix.lower()}"
            shutil.copy2(p, target_dir / name)

        new_names[p] = name
        stats["orig"] += p.stat().st_size
        stats["new"] += (target_dir / name).stat().st_size

    base = quote(doc_name)
    if LINK_PREFIX:
        base = f"{LINK_PREFIX.rstrip('/')}/{base}"

    def replace(m):
        alt, src, title = parse_image(m)
        p = resolve(src)
        if p is None:
            return m.group(0)
        # فقط Description وجود دارد؛ همان را هم alt و هم title می‌کنیم
        caption = alt or title
        return format_image(caption, f"{base}/{new_names[p]}", caption)

    return IMG_PATTERN.sub(replace, text), len(ordered), stats


# ==================================================
# اجرای build_index.py (یک پوشه عقب‌تر از پوشه‌ی خروجی md)
# ==================================================
def run_build_index(md_dir):
    """
    خروجی: (status, detail) که status یکی از "ok" / "missing" / "error" است.
    خطای این مرحله هیچ‌وقت تبدیل فایل را خراب نمی‌کند.
    """
    script = Path(md_dir).resolve().parent / "build_index.py"
    if not script.is_file():
        return "missing", str(script)

    if getattr(sys, "frozen", False):
        # در حالت exe، sys.executable خود برنامه است نه پایتون
        python = shutil.which("python") or shutil.which("python3") or shutil.which("py")
    else:
        python = sys.executable
    if not python:
        return "error", "Python was not found in PATH."

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [python, str(script)],
            cwd=str(script.parent), env=env,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120, **kwargs
        )
    except subprocess.TimeoutExpired:
        return "error", "build_index.py timed out after 120 seconds."
    except Exception as e:
        return "error", str(e)

    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-600:]
        return "error", f"Exit code {result.returncode}\n{tail}"
    return "ok", str(script)


# ==================================================
# تابع اصلی
# ==================================================
def convert_word_to_markdown():
    root = tk.Tk()
    root.withdraw()

    script_dir = get_script_dir()
    last_open_dir = load_last_open_dir()

    # پنجره‌ی انتخاب فایل: آخرین پوشه‌ای که ازش فایل انتخاب شده
    if last_open_dir and Path(last_open_dir).is_dir():
        initial_open_dir = last_open_dir
    else:
        initial_open_dir = str(script_dir)

    input_file = filedialog.askopenfilename(
        title="Select Word File",
        initialdir=initial_open_dir,
        filetypes=[
            ("Word Documents", "*.docx"),
            ("All Files", "*.*")
        ]
    )
    if not input_file:
        root.destroy()
        return

    input_path = Path(input_file)

    # ذخیره‌ی پوشه برای دفعه‌ی بعد
    save_last_open_dir(input_path.parent)

    # خروجی: کنار فایل برنامه، بدون سوال؛ اگر وجود داشته باشد جایگزین می‌شود
    # هر کتاب یک پوشه‌ی مخصوص دارد: <پوشه‌ی برنامه>/<نام-کتاب>/<نام-کتاب>.md
    book_name = Path(make_output_name(input_path)).stem
    book_dir = script_dir / book_name
    book_dir.mkdir(parents=True, exist_ok=True)
    output_path = book_dir / f"{book_name}.md"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            temp_md = tmp_path / "out.md"

            # pandoc داخل پوشه‌ی موقت اجرا می‌شود تا لینک‌ها نسبی باشند
            command = [
                "pandoc",
                str(input_path.resolve()),
                "-f", "docx",
                "-t", "gfm",
                "--wrap=none",
                "--extract-media=.",
                "-o", str(temp_md)
            ]

            subprocess.run(
                command, check=True, cwd=tmp,
                capture_output=True, text=True
            )

            markdown_text = temp_md.read_text(encoding="utf-8")
            markdown_text = remove_direction_spans(markdown_text)

            meta, markdown_text = extract_meta_block(markdown_text)

            markdown_text = clean_list_spacing(markdown_text)

            markdown_text, image_count, img_stats = organize_images(
                markdown_text, tmp_path, script_dir, book_name
            )

        # تخمین زمان مطالعه (اگر در META دستی نوشته شده باشد، همان می‌ماند)
        meta_found = bool(meta)
        meta_count = len(meta or {})
        meta = meta or {}
        if "read_minutes" not in meta:
            meta["read_minutes"] = format_read_time(
                estimate_read_minutes(markdown_text)
            )

        # اگر date_updated خالی بود، تاریخ امروز (شمسی) نوشته می‌شود
        if not meta.get("date_updated"):
            meta["date_updated"] = today_jalali()

        front_matter = build_front_matter(meta)

        final_text = front_matter + markdown_text

        output_path.write_text(final_text, encoding="utf-8")

        # اجرای build_index.py بعد از ذخیره‌ی فایل md
        index_status, index_detail = run_build_index(script_dir)

        info = f"Conversion completed successfully!\n\nOutput:\n{output_path}"
        info += f"\n\nImages: {image_count}"
        if image_count:
            info += (
                f" ({img_stats['webp']} converted to WebP, "
                f"{format_size(img_stats['orig'])} -> "
                f"{format_size(img_stats['new'])})"
            )
            if not img_stats["pillow"]:
                info += "\nPillow is not installed, so images were not converted. Run: pip install Pillow"
        info += f"\nRead time: {meta['read_minutes']}"
        info += f"\nDate updated: {meta['date_updated']}"
        if meta_found:
            info += f"\n\nMetadata fields found: {meta_count}"
        else:
            info += "\n\nWarning: No [META] block found!"

        info += f"\n\n(v{APP_VERSION})"

        if index_status == "ok":
            info += "\n\nbuild_index.py: executed successfully"
        elif index_status == "missing":
            info += f"\n\nbuild_index.py: not found at\n{index_detail}"
        else:
            info += f"\n\nbuild_index.py FAILED:\n{index_detail}"

        if index_status == "error":
            messagebox.showwarning("Done with warnings", info)
        else:
            messagebox.showinfo("Success", info)

    except FileNotFoundError:
        messagebox.showerror(
            "Pandoc Not Found",
            "Pandoc is not installed or is not available in PATH."
        )
    except subprocess.CalledProcessError as e:
        messagebox.showerror(
            "Conversion Error",
            f"Pandoc conversion failed.\n\n{e.stderr}"
        )
    except Exception as e:
        messagebox.showerror("Error", str(e))
    finally:
        root.destroy()


if __name__ == "__main__":
    convert_word_to_markdown()