from __future__ import annotations

import argparse
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from playwright.sync_api import sync_playwright


BAD_HOST_PARTS = ("bing.com", "msn.com", "microsoft.com")


def _safe_ext(url: str, content_type: str = "") -> str:
    suffix = Path(urlparse(str(url or "")).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return ".jpg" if guessed in {None, ".jpe", ".jpeg"} else guessed


def _safe_stem(text: str, fallback: str = "bing-image") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip("-._")
    text = re.sub(r"-{2,}", "-", text)
    return (text[:150] or fallback)


def _candidate_urls(page) -> list[dict]:
    rows = page.evaluate(
        """() => {
            const urls = [];
            for (const node of document.querySelectorAll('a.iusc')) {
                try {
                    const meta = JSON.parse(node.getAttribute('m') || '{}');
                    if (meta.murl) urls.push({
                        src: meta.murl,
                        title: meta.t || node.getAttribute('aria-label') || '',
                        page: meta.purl || '',
                        desc: meta.desc || ''
                    });
                } catch (e) {}
            }
            for (const img of document.images) {
                urls.push({
                    src: img.currentSrc || img.src || "",
                    title: img.alt || img.title || '',
                    page: location.href,
                    desc: ''
                });
            }
            return urls;
        }"""
    )
    result = []
    seen = set()
    for row in rows:
        src = str(row.get("src") or "")
        if not src.startswith("http"):
            continue
        host = urlparse(src).netloc.lower()
        if any(part in host for part in BAD_HOST_PARTS):
            continue
        if src in seen:
            continue
        seen.add(src)
        result.append(
            {
                "url": src,
                "title": str(row.get("title") or ""),
                "page": str(row.get("page") or ""),
                "desc": str(row.get("desc") or ""),
            }
        )
    return result


def _download(candidate: dict, output_dir: Path, index: int) -> Path | None:
    url = str(candidate.get("url") or "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145 Safari/537.36",
        "Referer": "https://www.bing.com/images/search",
    }
    try:
        response = requests.get(url, headers=headers, timeout=18)
        if response.status_code != 200:
            return None
        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.lower().startswith("image/"):
            return None
        data = response.content
        if len(data) < 2048:
            return None
        ext = _safe_ext(url, content_type)
        host = urlparse(str(candidate.get("page") or url)).netloc.replace("www.", "")
        title = " ".join(part for part in (candidate.get("title"), candidate.get("desc"), host) if part)
        path = output_dir / f"{index:06d}-{_safe_stem(title)}{ext}"
        path.write_bytes(data)
        return path
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--profile", type=Path, default=None)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    profile = args.profile or Path(__file__).resolve().parents[1] / "chrome_bing_images_profile"
    profile.mkdir(parents=True, exist_ok=True)
    downloaded = []
    seen = set()
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
        url = f"https://www.bing.com/images/search?q={quote_plus(args.query)}&form=HDRSC2&first=1"
        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(2200)
        for _ in range(4):
            for candidate in _candidate_urls(page):
                if len(downloaded) >= args.count:
                    break
                candidate_url = str(candidate.get("url") or "")
                if candidate_url in seen:
                    continue
                seen.add(candidate_url)
                path = _download(candidate, args.output, len(downloaded) + 1)
                if path:
                    downloaded.append(str(path))
            if len(downloaded) >= args.count:
                break
            try:
                page.mouse.wheel(0, 1100)
            except Exception:
                pass
            page.wait_for_timeout(900)
        context.close()
    print(json.dumps({"ok": True, "downloaded": downloaded}, ensure_ascii=False))
    return 0 if downloaded else 2


if __name__ == "__main__":
    raise SystemExit(main())
