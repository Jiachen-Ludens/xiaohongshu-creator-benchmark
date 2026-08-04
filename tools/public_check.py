#!/usr/bin/env python3
"""Fail a release when committed files contain private or off-scope material."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


IGNORED_DIRS = {".git", ".venv", "__pycache__"}
IGNORED_NAMES = {"PROGRESS.md", "BLOCKED.md"}
TEXT_SUFFIXES = {
    "",
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
}
SECRET_PATTERNS = [
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"),
]
SIGNED_CACHE_PATTERN = re.compile(
    r"https://cache\.tikhub\.io/api/v1/cache/public/[A-Za-z0-9?&=_-]+"
)
HARD_CALL_CAP_PATTERNS = (
    re.compile(r"默认最多\s*\d+\s*次"),
    re.compile(r"研究.{0,20}最多使用\s*\d+\s*次"),
)
PERSONAL_PATH_MARKERS = (
    "/" + "Users" + "/",
    "/" + "home" + "/",
)
OTHER_PLATFORM_MARKERS = (
    "dou" + "yin",
    "wechat",
    "reddit",
    "tiktok",
    "instagram",
    "youtube",
    "bilibili",
    "weibo",
    "zhihu",
)
REAL_CREATOR_MARKERS = (
    "xiao" + "gaifun",
    "小" + "盖",
    "6720" + "c690000000001c01b883",
    "6a61" + "f751000000001101a9b2",
)


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.name in IGNORED_NAMES:
            continue
        yield path, relative


def read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def check_repository(root: Path) -> list[str]:
    errors: list[str] = []
    readme = root / "README.md"
    if not readme.is_file():
        errors.append("README.md 缺失")
    else:
        readme_text = readme.read_text(encoding="utf-8")
        required = [
            "https://user.tikhub.io/register?ref=Gqosvz0l",
            "https://user.tikhub.io/register",
            "少量佣金",
            "不使用邀请码",
        ]
        for marker in required:
            if marker not in readme_text:
                errors.append(f"README 缺少透明邀请说明：{marker}")

    for path, relative in iter_files(root):
        lowered_relative = str(relative).lower()
        for marker in REAL_CREATOR_MARKERS:
            if marker.lower() in lowered_relative:
                errors.append(f"案例文件名包含真实博主标识：{relative}")
        if path.suffix.lower() in {".pyc", ".pyo"}:
            errors.append(f"编译产物不应发布：{relative}")
            continue
        text = read_text(path)
        if text is None:
            continue
        lowered_text = text.lower()
        for marker in REAL_CREATOR_MARKERS:
            if marker.lower() in lowered_text:
                errors.append(f"公开文件包含真实博主标识：{relative}")
        for marker in PERSONAL_PATH_MARKERS:
            if marker in text:
                errors.append(f"包含个人绝对路径：{relative}")
        if SIGNED_CACHE_PATTERN.search(text):
            errors.append(f"包含真实 TikHub 缓存 URL：{relative}")
        for pattern in HARD_CALL_CAP_PATTERNS:
            if pattern.search(text):
                errors.append(f"包含 TikHub 调用次数硬上限：{relative}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"包含疑似密钥：{relative}")
        if relative.parts[:2] == ("xiaohongshu-creator-benchmark", "scripts"):
            lowered = text.lower()
            for marker in OTHER_PLATFORM_MARKERS:
                if marker in lowered:
                    errors.append(f"运行脚本出现其他平台能力 {marker}：{relative}")
            endpoint_literals = re.findall(r'"/api/v1/([^"]+)"', text)
            for endpoint in endpoint_literals:
                if not endpoint.startswith("xiaohongshu/"):
                    errors.append(f"出现非小红书 API 端点：{relative} -> {endpoint}")

    fixtures = root / "tests" / "fixtures"
    if fixtures.is_dir():
        for path in fixtures.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            forbidden = ("request_id", "debug_info", "cache_message", "xsec_token")
            for marker in forbidden:
                if marker in text:
                    errors.append(f"fixture 疑似真实响应字段 {marker}：{path.name}")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check public release hygiene")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = check_repository(root)
    if errors:
        print("PUBLIC CHECK FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PUBLIC CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
