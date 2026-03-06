#!/usr/bin/env python3
"""build.py — Static site generator for samus.dev
Generates multilingual HTML + PDF from YAML/Markdown content.
"""

import shutil
import yaml
import markdown
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("⚠  Pillow not installed — skipping image optimization")

try:
    from weasyprint import HTML as WeasyHTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    HAS_WEASYPRINT = False
    print("⚠  WeasyPrint not available — skipping PDF generation")


# ── Configuration ────────────────────────────────────────────

LANGUAGES    = ["ru", "uk", "en"]
DEFAULT_LANG = "ru"

SRC       = Path("src")
BUILD     = Path("_site")
CONTENT   = SRC / "content"
TEMPLATES = SRC / "_templates"
DATA_DIR  = SRC / "_data"
CSS_DIR   = SRC / "css"
JS_DIR    = SRC / "js"
ASSETS    = SRC / "assets"
ADMIN     = SRC / "admin"

COLLECTIONS = ["experience", "projects", "education", "certificates"]

THUMB_SIZES = {"small": 400, "medium": 800}
IMG_QUALITY = 85


# ── Helpers ──────────────────────────────────────────────────

def clean():
    """Remove and recreate the build directory."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)


def parse_frontmatter(filepath: Path) -> dict:
    """Parse YAML front-matter + Markdown body from a .md file."""
    text = filepath.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            meta["content"] = (
                markdown.markdown(body, extensions=["extra"]) if body else ""
            )
            return meta
    return {"content": markdown.markdown(text, extensions=["extra"])}


def load_yaml(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def load_profile(lang: str) -> dict:
    return load_yaml(CONTENT / "profile" / f"profile.{lang}.yaml")


def load_ui(lang: str) -> dict:
    data = load_yaml(DATA_DIR / "ui.yaml")
    return data.get(lang, data.get(DEFAULT_LANG, {}))


def load_collection(name: str, lang: str) -> list[dict]:
    """Load all Markdown entries in a collection for *lang*."""
    folder = CONTENT / name
    if not folder.exists():
        return []
    entries = []
    for f in sorted(folder.glob(f"*.{lang}.md")):
        entry = parse_frontmatter(f)
        entry["slug"] = f.stem.removesuffix(f".{lang}")
        entries.append(entry)
    entries.sort(key=lambda e: e.get("order", 999))
    return entries


# ── Jinja2 Filters ──────────────────────────────────────────

def thumb_filter(filename: str, size: str = "small", fmt: str = "webp") -> str:
    """Convert 'photo.jpg' → 'photo-small.webp'."""
    if not filename:
        return ""
    stem = Path(filename).stem
    return f"{stem}-{size}.{fmt}"


# ── Image Optimization ──────────────────────────────────────

def optimize_images():
    """Create optimized WebP + JPEG thumbnails of asset images."""
    if not HAS_PILLOW:
        return

    for subdir in ("certificates", "projects"):
        src_dir = BUILD / "assets" / subdir
        if not src_dir.exists():
            continue

        out_dir = BUILD / "img" / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        for img_path in src_dir.iterdir():
            if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            try:
                img = Image.open(img_path)
                for label, max_w in THUMB_SIZES.items():
                    ratio = min(1, max_w / img.width)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    resized = img.resize(new_size, Image.LANCZOS)

                    # WebP
                    resized.save(
                        out_dir / f"{img_path.stem}-{label}.webp",
                        "WebP",
                        quality=IMG_QUALITY,
                    )
                    # JPEG fallback
                    rgb = resized.convert("RGB") if resized.mode != "RGB" else resized
                    rgb.save(
                        out_dir / f"{img_path.stem}-{label}.jpg",
                        "JPEG",
                        quality=IMG_QUALITY,
                    )
                print(f"  ✓ {subdir}/{img_path.name}")
            except Exception as exc:
                print(f"  ✗ {subdir}/{img_path.name}: {exc}")


# ── Copy Static Files ───────────────────────────────────────

def copy_static():
    """Copy CSS, JS, assets, admin, CNAME into the build directory."""
    # CSS
    (BUILD / "css").mkdir(parents=True, exist_ok=True)
    for f in CSS_DIR.glob("*.css"):
        shutil.copy2(f, BUILD / "css")

    # JS
    if JS_DIR.exists():
        (BUILD / "js").mkdir(parents=True, exist_ok=True)
        for f in JS_DIR.glob("*.js"):
            shutil.copy2(f, BUILD / "js")

    # Assets (originals)
    if ASSETS.exists():
        shutil.copytree(ASSETS, BUILD / "assets", dirs_exist_ok=True)

    # Admin
    if ADMIN.exists():
        shutil.copytree(ADMIN, BUILD / "admin", dirs_exist_ok=True)

    # Root files
    for fname in ("CNAME", "LICENSE"):
        p = Path(fname)
        if p.exists():
            shutil.copy2(p, BUILD / fname)


# ── Build HTML ───────────────────────────────────────────────

def build_html():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=False,
    )
    env.filters["thumb"] = thumb_filter

    template = env.get_template("layout.html")

    for lang in LANGUAGES:
        profile = load_profile(lang)
        profile["ui"] = load_ui(lang)

        ctx = {
            "lang": lang,
            "languages": LANGUAGES,
            "default_lang": DEFAULT_LANG,
            "base_url": "." if lang == DEFAULT_LANG else "..",
            "profile": profile,
            "now": datetime.now(),
        }
        for col in COLLECTIONS:
            ctx[col] = load_collection(col, lang)

        html = template.render(**ctx)

        if lang == DEFAULT_LANG:
            out = BUILD / "index.html"
        else:
            (BUILD / lang).mkdir(parents=True, exist_ok=True)
            out = BUILD / lang / "index.html"

        out.write_text(html, encoding="utf-8")
        print(f"  ✓ {out.relative_to(BUILD)}")


# ── Build PDF ────────────────────────────────────────────────

def build_pdf():
    """Generate PDF résumés from the built HTML pages."""
    if not HAS_WEASYPRINT:
        return

    for lang in LANGUAGES:
        if lang == DEFAULT_LANG:
            html_path = BUILD / "index.html"
            pdf_name  = "resume.pdf"
        else:
            html_path = BUILD / lang / "index.html"
            pdf_name  = f"resume-{lang}.pdf"

        pdf_path = BUILD / pdf_name
        try:
            WeasyHTML(filename=str(html_path)).write_pdf(str(pdf_path))
            print(f"  ✓ {pdf_name}")
        except Exception as exc:
            print(f"  ✗ {pdf_name}: {exc}")


# ── Main ─────────────────────────────────────────────────────

def build():
    print("🧹 Cleaning…")
    clean()

    print("📁 Copying static files…")
    copy_static()

    print("🖼  Optimizing images…")
    optimize_images()

    print("🔨 Building HTML…")
    build_html()

    print("📄 Generating PDF…")
    build_pdf()

    print("\n✅ Done → _site/")


if __name__ == "__main__":
    build()
