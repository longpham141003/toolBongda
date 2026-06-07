from __future__ import annotations

import argparse
import json
from pathlib import Path

from icrawler.builtin import BaiduImageCrawler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    crawler = BaiduImageCrawler(
        feeder_threads=1,
        parser_threads=1,
        downloader_threads=3,
        storage={"root_dir": str(args.output)},
    )
    crawler.crawl(
        keyword=args.query,
        offset=max(0, args.offset),
        max_num=max(3, args.count),
        file_idx_offset="auto",
        max_idle_time=20,
    )
    print(json.dumps({"ok": True, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
