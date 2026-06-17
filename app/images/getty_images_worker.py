from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlparse

import requests
from playwright.sync_api import sync_playwright


GETTY_HOST_PARTS = ("media.gettyimages.com",)
CAPTCHA_TEXT = ("access denied", "verify you are human", "captcha", "unusual traffic")


def _safe_ext(url: str, content_type: str = "") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return ".jpg" if guessed in {None, ".jpe", ".jpeg"} else guessed


def _safe_image_name(url: str, index: int, ext: str) -> str:
    stem = Path(unquote(urlparse(str(url or "")).path)).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    stem = re.sub(r"-{2,}", "-", stem)
    if len(stem) < 8 or stem.lower() in {"image", "photo", "asset", "media"}:
        stem = "getty-image"
    return f"{index:06d}-{stem[:120]}{ext}"


def _url_variants(url: str) -> list[str]:
    variants = []
    for size in ("2048x2048", "1024x1024", "612x612"):
        value = re.sub(r"([?&]s=)\d+x\d+", rf"\g<1>{size}", str(url or ""))
        value = re.sub(r"([?&]w=)\d+", r"\g<1>2048", value)
        if value not in variants:
            variants.append(value)
    if url not in variants:
        variants.append(url)
    return variants


def _is_getty_image_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    if not any(part in host for part in GETTY_HOST_PARTS):
        return False
    path = parsed.path.lower()
    return any(token in path for token in (".jpg", ".jpeg", ".png", ".webp", "/id/")) or "media.gettyimages.com" in host


def _save_response_image(response, output_dir: Path, index: int) -> Path | None:
    try:
        if int(response.status or 0) != 200:
            return None
        url = str(response.url or "")
        if not _is_getty_image_url(url):
            return None
        downloaded = _download(url, output_dir, index)
        if downloaded:
            return downloaded
        content_type = str(response.headers.get("content-type") or "").lower()
        if not content_type.startswith("image/"):
            return None
        data = response.body()
        if len(data) < 2048:
            return None
        ext = _safe_ext(url, content_type)
        path = output_dir / _safe_image_name(url, index, ext)
        path.write_bytes(data)
        return path
    except Exception:
        return None


def _download(url: str, output_dir: Path, index: int) -> Path | None:
    if not _is_getty_image_url(url):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145 Safari/537.36",
        "Referer": "https://www.gettyimages.com/editorial-images",
    }
    for candidate_url in _url_variants(url):
        try:
            response = requests.get(candidate_url, headers=headers, timeout=15)
            if response.status_code != 200:
                continue
            data = response.content
            if len(data) < 2048:
                continue
            ext = _safe_ext(candidate_url, response.headers.get("content-type", ""))
            path = output_dir / _safe_image_name(candidate_url, index, ext)
            path.write_bytes(data)
            return path
        except Exception:
            continue
    return None


def _candidate_urls(page) -> list[str]:
    rows = page.evaluate(
        """() => Array.from(document.images).map(img => ({
            src: img.currentSrc || img.src || "",
            w: img.naturalWidth || 0,
            h: img.naturalHeight || 0,
            parent: (img.closest('a') || {}).href || ""
        }))"""
    )
    scored = []
    for row in rows:
        src = str(row.get("src") or "")
        if not src.startswith("http") or not _is_getty_image_url(src):
            continue
        parent = str(row.get("parent") or "")
        if parent and "/detail/" not in parent and "/photos/" not in parent:
            continue
        width = int(row.get("w") or 0)
        height = int(row.get("h") or 0)
        if width < 120 or height < 80:
            continue
        scored.append((width * height, src))
    scored.sort(reverse=True)
    result = []
    for _score, src in scored:
        if src not in result:
            result.append(src)
    return result


def _is_blocked(page) -> bool:
    try:
        if "bot-wall" in page.url.lower():
            return True
        text = page.locator("body").inner_text(timeout=1500).lower()
        return any(token in text for token in CAPTCHA_TEXT)
    except Exception:
        return False


def _wait_for_manual_validation(page, seconds: int = 300) -> bool:
    deadline = time.time() + max(10, int(seconds))
    while time.time() < deadline:
        if not _is_blocked(page):
            return True
        page.wait_for_timeout(3000)
    return False


def _accept_cookies(page) -> None:
    labels = ("Accept", "I Accept", "Accept All", "Allow all")
    for label in labels:
        try:
            button = page.get_by_role("button", name=label)
            if button.count():
                button.first.click(timeout=1000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    profile = args.profile or Path(__file__).resolve().parents[1] / "chrome_getty_images_profile"
    profile.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    seen: set[str] = set()
    file_counter = {"value": 0}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile),
            headless=not args.headed,
            viewport={"width": 1365, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145 Safari/537.36",
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response):
            if len(downloaded) >= args.count:
                return
            url = str(response.url or "")
            if not url.startswith("http") or url in seen:
                return
            seen.add(url)
            file_counter["value"] += 1
            path = _save_response_image(response, args.output, file_counter["value"])
            if path:
                downloaded.append(str(path))

        context.on("response", on_response)
        search_url = f"https://www.gettyimages.com/search/2/image?family=editorial&phrase={quote_plus(args.query)}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(2500)
        _accept_cookies(page)
        if _is_blocked(page):
            print(json.dumps({"ok": False, "blocked": True, "message": "Getty captcha: waiting for manual validation in browser"}, ensure_ascii=False), flush=True)
            if not _wait_for_manual_validation(page):
                print(json.dumps({"ok": False, "blocked": True, "message": "Getty captcha not solved before timeout"}, ensure_ascii=False))
                context.close()
                return 3
            page.wait_for_timeout(1500)

        for _ in range(5):
            if len(downloaded) >= args.count:
                break
            try:
                page.mouse.wheel(0, 950)
            except Exception:
                pass
            page.wait_for_timeout(1200)
            if _is_blocked(page):
                print(json.dumps({"ok": False, "blocked": True, "message": "Getty captcha: waiting for manual validation in browser"}, ensure_ascii=False), flush=True)
                if not _wait_for_manual_validation(page):
                    print(json.dumps({"ok": False, "blocked": True, "message": "Getty captcha not solved before timeout"}, ensure_ascii=False))
                    context.close()
                    return 3
                page.wait_for_timeout(1500)

        for url in _candidate_urls(page):
            if len(downloaded) >= args.count:
                break
            if url in seen:
                continue
            seen.add(url)
            file_counter["value"] += 1
            path = _download(url, args.output, file_counter["value"])
            if path:
                downloaded.append(str(path))

        context.close()

    print(json.dumps({"ok": True, "downloaded": downloaded}, ensure_ascii=False))
    return 0 if downloaded else 2


if __name__ == "__main__":
    raise SystemExit(main())
