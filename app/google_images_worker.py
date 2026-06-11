from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from playwright.sync_api import sync_playwright
from PIL import Image


BAD_HOST_PARTS = ("google.", "gstatic.", "googleusercontent.com", "ytimg.com")
CAPTCHA_TEXT = ("our systems have detected unusual traffic", "not a robot", "recaptcha", "sorry")
BAD_PAGE_HOST_PARTS = (
    "youtube.com", "youtu.be", "dailymotion.com", "vimeo.com", "tiktok.com",
    "pinterest.", "facebook.com", "instagram.com",
)
BAD_TITLE_TERMS = (
    "thumbnail", "youtube", "highlights", "reaction", "watch live", "livestream",
    "preview", "prediction", "lineup", "line-up", "starting xi", "vs poster",
    "match poster", "wallpaper", "graphic", "template", "banner", "cover",
    "scorecard", "full match", "video", "stream", "replay",
    "tactical analysis", "analysis", "fox sports", "sportv", "maxresdefault",
    "hqdefault", "shorts", "live score",
)


def _safe_ext(url: str, content_type: str = "") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return ".jpg" if guessed in {None, ".jpe", ".jpeg"} else guessed


def _safe_stem(text: str, fallback: str = "google-image") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-._")
    text = re.sub(r"-{2,}", "-", text)
    return text[:150] or fallback


def _query_tokens(query: str) -> set[str]:
    ignored = {"the", "and", "for", "with", "from", "photo", "match", "action", "football", "soccer"}
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", str(query or ""))
        if len(token) > 2 and token.lower() not in ignored
    }


def _candidate_urls(page, query: str, previous_urls: set[str] | None = None) -> list[dict]:
    previous_urls = previous_urls or set()
    rows = page.evaluate(
        """() => Array.from(document.images).map(img => {
            const rect = img.getBoundingClientRect();
            const anchor = img.closest("a");
            const panel = img.closest('[role="dialog"], [data-hveid], div');
            const srcset = (img.getAttribute("srcset") || "")
                .split(",")
                .map(value => value.trim().split(/\\s+/)[0])
                .filter(value => value.startsWith("http"));
            return {
                src: srcset[srcset.length - 1] || img.currentSrc || img.src || "",
                w: img.naturalWidth || 0,
                h: img.naturalHeight || 0,
                renderedW: rect.width || 0,
                renderedH: rect.height || 0,
                x: rect.x || 0,
                visible: rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight,
                title: img.alt || img.title || (panel ? panel.innerText.slice(0, 500) : ""),
                page: (anchor || {}).href || location.href
            };
        })"""
    )
    query_words = _query_tokens(query)
    scored = []
    for row in rows:
        src = str(row.get("src") or "")
        if not src.startswith("http"):
            continue
        panel_score = 3 if float(row.get("x") or 0) > 620 else 0
        if src in previous_urls and not panel_score:
            continue
        host = urlparse(src).netloc.lower()
        if any(part in host for part in BAD_HOST_PARTS):
            continue
        width = int(row.get("w") or 0)
        height = int(row.get("h") or 0)
        rendered_width = float(row.get("renderedW") or 0)
        rendered_height = float(row.get("renderedH") or 0)
        if width < 900 or height < 480:
            continue
        if abs((width / max(1, height)) - (16 / 9)) > 0.04:
            continue
        if not row.get("visible") or rendered_width < 280 or rendered_height < 170:
            continue
        title = str(row.get("title") or "").strip()
        page_url = str(row.get("page") or "")
        page_host = urlparse(page_url).netloc.lower()
        lowered_meta = f"{title} {page_url}".lower()
        if any(part in page_host for part in BAD_PAGE_HOST_PARTS):
            continue
        if any(term in lowered_meta for term in BAD_TITLE_TERMS):
            continue
        metadata_tokens = _query_tokens(f"{title} {page_url}")
        keyword_score = len(query_words & metadata_tokens)
        if query_words and keyword_score < 1:
            continue
        scored.append(
            (
                panel_score,
                keyword_score,
                width * height,
                {
                    "url": src,
                    "title": title,
                    "page": page_url,
                    "width": width,
                    "height": height,
                },
            )
        )
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    result = []
    seen = set()
    for _panel_score, _keyword_score, _area, row in scored:
        if row["url"] not in seen:
            seen.add(row["url"])
            result.append(row)
    return result


def _download(candidate: dict, output_dir: Path, index: int) -> Path | None:
    url = str(candidate.get("url") or "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145 Safari/537.36",
        "Referer": "https://www.google.com/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=12, stream=True)
        if response.status_code != 200:
            return None
        data = response.content
        if len(data) < 2048:
            return None
        ext = _safe_ext(url, response.headers.get("content-type", ""))
        host = urlparse(str(candidate.get("page") or url)).netloc.replace("www.", "")
        stem = _safe_stem(" ".join(part for part in (candidate.get("title"), host) if part))
        path = output_dir / f"{index:06d}-{stem}{ext}"
        path.write_bytes(data)
        path.with_suffix(path.suffix + ".json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


def _embedded_candidates(page, query: str) -> list[dict]:
    source = html.unescape(page.content())
    source = source.replace("\\u003d", "=").replace("\\u0026", "&").replace("\\/", "/")
    urls = re.findall(
        r"https?://[^\"'<> ]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'<> ]*)?",
        source,
        flags=re.I,
    )
    results = []
    seen = set()
    for url in urls:
        url = url.rstrip("\\,)]}")
        if url in seen:
            continue
        seen.add(url)
        host = urlparse(url).netloc.lower()
        lowered = url.lower()
        if any(part in host for part in BAD_HOST_PARTS):
            continue
        if any(term in lowered for term in BAD_TITLE_TERMS):
            continue
        results.append(
            {
                "url": url,
                "title": Path(urlparse(url).path).stem.replace("-", " ").replace("_", " "),
                "page": url,
                "width": 0,
                "height": 0,
            }
        )
    return results


def _valid_download_shape(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            width, height = image.size
        return width >= 600 and height >= 330
    except Exception:
        return False


def _image_dhash(path: Path) -> int | None:
    try:
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        with Image.open(path) as image:
            pixels = list(image.convert("L").resize((9, 8), resampling).getdata())
        value = 0
        for row in range(8):
            offset = row * 9
            for column in range(8):
                value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
        return value
    except Exception:
        return None


def _is_captcha(page) -> bool:
    try:
        url = page.url.lower()
        if "/sorry/" in url or "captcha" in url:
            return True
        text = page.locator("body").inner_text(timeout=1500).lower()
        return any(token in text for token in CAPTCHA_TEXT)
    except Exception:
        return False


def download_google_images(
    query: str,
    output: Path,
    count: int = 1,
    profile: Path | None = None,
    *,
    headed: bool = False,
    excluded_urls: set[str] | None = None,
    excluded_dhashes: set[int] | None = None,
    skip_results: int = 0,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    downloaded = []
    seen = {str(value).strip() for value in excluded_urls or set() if str(value).strip()}
    rejected_dhashes = {int(value) for value in excluded_dhashes or set()}
    accepted_dhashes: set[int] = set()
    file_counter = {"value": 0}
    clicked = 0
    discovered = 0
    with sync_playwright() as p:
        browser = None
        context_options = {
            "viewport": {"width": 1365, "height": 900},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145 Safari/537.36",
            "locale": "en-US",
        }
        if profile:
            profile.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                str(profile),
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled"],
                **context_options,
            )
        else:
            browser = p.chromium.launch(
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(**context_options)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(
                f"https://www.google.com/search?tbm=isch&hl=en&q={quote_plus(query)}",
                wait_until="domcontentloaded",
                timeout=18000,
            )
        except Exception as exc:
            context.close()
            if browser:
                browser.close()
            return {
                "ok": False,
                "network_error": True,
                "message": str(exc),
                "downloaded": [],
            }
        page.wait_for_timeout(1400)
        if _is_captcha(page):
            context.close()
            if browser:
                browser.close()
            return {"ok": False, "captcha": True, "message": "Google captcha/unusual traffic", "downloaded": []}
        for candidate in _embedded_candidates(page, query):
            if len(downloaded) >= count:
                break
            url = str(candidate.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            file_counter["value"] += 1
            path = _download(candidate, output, file_counter["value"])
            if not path:
                continue
            if not _valid_download_shape(path):
                path.unlink(missing_ok=True)
                path.with_suffix(path.suffix + ".json").unlink(missing_ok=True)
                continue
            perceptual = _image_dhash(path)
            if perceptual is not None and any(
                (perceptual ^ old).bit_count() <= 6
                for old in rejected_dhashes | accepted_dhashes
            ):
                path.unlink(missing_ok=True)
                path.with_suffix(path.suffix + ".json").unlink(missing_ok=True)
                continue
            if perceptual is not None:
                accepted_dhashes.add(perceptual)
            downloaded.append(str(path))
        thumbnails = page.locator("img")
        max_clicks = min(thumbnails.count(), max(60, count * 10))
        eligible_seen = 0
        for i in range(max_clicks):
            if len(downloaded) >= count:
                break
            try:
                box = thumbnails.nth(i).bounding_box(timeout=500)
                if (
                    not box
                    or box["width"] < 120
                    or box["height"] < 90
                    or box["y"] < 140
                ):
                    continue
                eligible_seen += 1
                if eligible_seen <= max(0, int(skip_results)):
                    continue
                before_urls = set(
                    page.evaluate(
                        "() => Array.from(document.images).map(img => img.currentSrc || img.src || '').filter(Boolean)"
                    )
                )
                thumbnails.nth(i).click(timeout=900)
                clicked += 1
                page.wait_for_timeout(450)
                if _is_captcha(page):
                    context.close()
                    if browser:
                        browser.close()
                    return {"ok": False, "captcha": True, "message": "Google captcha/unusual traffic", "downloaded": downloaded}
            except Exception:
                continue
            candidates = _candidate_urls(page, query, before_urls)
            discovered += len(candidates)
            for candidate in candidates:
                url = str(candidate.get("url") or "")
                if url in seen:
                    continue
                seen.add(url)
                file_counter["value"] += 1
                path = _download(candidate, output, file_counter["value"])
                if not path:
                    continue
                perceptual = _image_dhash(path)
                if perceptual is not None and any(
                    (perceptual ^ old).bit_count() <= 6
                    for old in rejected_dhashes | accepted_dhashes
                ):
                    path.unlink(missing_ok=True)
                    path.with_suffix(path.suffix + ".json").unlink(missing_ok=True)
                    continue
                if perceptual is not None:
                    accepted_dhashes.add(perceptual)
                downloaded.append(str(path))
                break
            if len(downloaded) < count:
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(100)
                except Exception:
                    pass
        context.close()
        if browser:
            browser.close()
    return {
        "ok": bool(downloaded),
        "downloaded": downloaded,
        "clicked": clicked,
        "discovered": discovered,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--exclude-url", action="append", default=[])
    parser.add_argument("--exclude-dhash", action="append", default=[])
    parser.add_argument("--skip-results", type=int, default=0)
    parser.add_argument("--request-json", type=Path, default=None)
    args = parser.parse_args()
    if args.request_json:
        request = json.loads(args.request_json.read_text(encoding="utf-8"))
        args.query = str(request["query"])
        args.output = Path(request["output"])
        args.count = int(request.get("count") or 1)
        args.profile = Path(request["profile"]) if request.get("profile") else None
        args.headed = bool(request.get("headed", False))
        args.exclude_url = list(request.get("exclude_urls") or [])
        args.exclude_dhash = [str(value) for value in request.get("exclude_dhashes") or []]
        args.skip_results = int(request.get("skip_results") or 0)
    if not args.query or not args.output:
        parser.error("--query and --output are required unless --request-json is used")

    result = download_google_images(
        args.query,
        args.output,
        args.count,
        args.profile,
        headed=args.headed,
        excluded_urls=set(args.exclude_url),
        excluded_dhashes={int(value) for value in args.exclude_dhash},
        skip_results=args.skip_results,
    )
    print(json.dumps(result, ensure_ascii=False))
    if result.get("captcha"):
        return 3
    return 0 if result.get("downloaded") else 2


if __name__ == "__main__":
    raise SystemExit(main())
