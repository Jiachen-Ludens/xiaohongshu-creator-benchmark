#!/usr/bin/env python3
"""Minimal TikHub client for Xiaohongshu creator benchmarking."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import ssl
import stat
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("TIKHUB_BASE_URL", "https://api.tikhub.io").rstrip("/")
TOKEN_FILE = Path(
    "~/.config/xiaohongshu-creator-benchmark/tikhub-token"
).expanduser()
USER_AGENT = "xiaohongshu-creator-benchmark/1.0"

AFFILIATE_REGISTER_URL = "https://user.tikhub.io/register?ref=Gqosvz0l"
PLAIN_REGISTER_URL = "https://user.tikhub.io/register"


def tool(
    path: str,
    allowed: list[str],
    *,
    required: list[str] | None = None,
    one_of: list[str] | None = None,
    defaults: dict[str, Any] | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        "method": "GET",
        "path": path,
        "allowed": allowed,
        "required": required or [],
        "one_of": one_of or [],
        "defaults": defaults or {},
        "note": note,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "xhs_search_users": tool(
        "/api/v1/xiaohongshu/app_v2/search_users",
        ["keyword", "page", "search_id", "source"],
        required=["keyword"],
        defaults={"page": 1},
        note="按昵称或小红书号搜索用户。",
    ),
    "xhs_get_user_info": tool(
        "/api/v1/xiaohongshu/app_v2/get_user_info",
        ["user_id", "share_text"],
        one_of=["user_id", "share_text"],
        note="获取公开主页信息。",
    ),
    "xhs_get_user_posted_notes": tool(
        "/api/v1/xiaohongshu/app_v2/get_user_posted_notes",
        ["user_id", "share_text", "cursor"],
        one_of=["user_id", "share_text"],
        defaults={"cursor": ""},
        note="获取账号近期作品；默认只取第一页。",
    ),
    "xhs_get_image_note_detail": tool(
        "/api/v1/xiaohongshu/app_v2/get_image_note_detail",
        ["note_id", "share_text"],
        one_of=["note_id", "share_text"],
        note="获取已知图文笔记详情。",
    ),
    "xhs_get_video_note_detail": tool(
        "/api/v1/xiaohongshu/app_v2/get_video_note_detail",
        ["note_id", "share_text"],
        one_of=["note_id", "share_text"],
        note="获取已知视频笔记详情。",
    ),
    "xhs_get_note_comments": tool(
        "/api/v1/xiaohongshu/app_v2/get_note_comments",
        [
            "note_id",
            "share_text",
            "cursor",
            "index",
            "pageArea",
            "sort_strategy",
        ],
        one_of=["note_id", "share_text"],
        defaults={"cursor": "", "index": 0},
        note="获取一级评论；默认只取一页。",
    ),
}


class CliError(ValueError):
    pass


def json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def collect_args(raw_json: str | None, pairs: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise CliError(f"--args 不是有效 JSON：{exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise CliError("--args 必须是 JSON object")
        values.update(parsed)
    for pair in pairs:
        if "=" not in pair:
            raise CliError(f"--arg 必须使用 key=value：{pair}")
        key, value = pair.split("=", 1)
        if not key:
            raise CliError("--arg 的 key 不能为空")
        values[key] = json_value(value)
    return values


def validate(tool_name: str, values: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS[tool_name]
    unknown = sorted(set(values) - set(spec["allowed"]))
    if unknown:
        raise CliError(
            f"{tool_name} 不支持参数：{', '.join(unknown)}；"
            f"允许：{', '.join(spec['allowed'])}"
        )
    merged = {**spec["defaults"], **values}
    missing = [key for key in spec["required"] if merged.get(key) in (None, "")]
    if missing:
        raise CliError(f"{tool_name} 缺少必填参数：{', '.join(missing)}")
    if spec["one_of"] and not any(
        merged.get(key) not in (None, "") for key in spec["one_of"]
    ):
        raise CliError(f"{tool_name} 至少需要一个参数：{', '.join(spec['one_of'])}")
    return merged


def tls_context() -> ssl.SSLContext:
    configured = os.environ.get("TIKHUB_CA_BUNDLE") or os.environ.get(
        "SSL_CERT_FILE"
    )
    if configured:
        ca_path = Path(configured).expanduser()
        if not ca_path.is_file():
            raise CliError(f"CA 文件不存在：{ca_path}")
        context = ssl.create_default_context(cafile=str(ca_path))
    elif sys.platform == "darwin" and Path("/etc/ssl/cert.pem").is_file():
        context = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    else:
        context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise CliError("TLS context 未启用证书与主机名校验")
    return context


def token_source() -> tuple[str | None, str]:
    env_token = os.environ.get("TIKHUB_API_KEY", "").strip()
    if env_token:
        return env_token, "environment"
    if TOKEN_FILE.is_file():
        mode = stat.S_IMODE(TOKEN_FILE.stat().st_mode)
        if mode & 0o077:
            raise CliError(f"Token 文件权限必须为 0600，当前为 {mode:04o}")
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token, str(TOKEN_FILE)
    return None, "not configured"


def require_token() -> str:
    token, source = token_source()
    if not token:
        raise CliError(
            "TikHub 是本 Skill 的必选数据源，但尚未配置 Token。"
            "这是作者的邀请码；通过该链接注册，作者会获得少量佣金："
            f"{AFFILIATE_REGISTER_URL}。不想使用邀请码时，请使用："
            f"{PLAIN_REGISTER_URL}。"
            "注册后设置 TIKHUB_API_KEY，或写入 "
            f"{TOKEN_FILE} 并 chmod 600。"
        )
    if len(token) < 20:
        raise CliError(f"{source} 中的 TikHub Token 长度异常")
    return token


def find_cache_url(value: Any) -> str | None:
    if isinstance(value, dict):
        direct = value.get("cache_url")
        if isinstance(direct, str) and direct:
            return direct
        for child in value.values():
            found = find_cache_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_cache_url(child)
            if found:
                return found
    return None


def write_result(body: bytes, *, out_path: str | None, meta: dict[str, Any]) -> None:
    if not out_path:
        try:
            payload = json.loads(body)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        except (json.JSONDecodeError, UnicodeDecodeError):
            sys.stdout.buffer.write(body)
            if not body.endswith(b"\n"):
                sys.stdout.write("\n")
        return

    target = Path(out_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    meta_path = target.with_name(target.name + ".meta.json")
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "saved_to": str(target),
                "metadata": str(meta_path),
                "http_status": meta["http_status"],
                "bytes": len(body),
                "billable_api_calls": meta["billable_api_calls"],
                "cache_available": bool(meta.get("cache_url")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def execute_call(
    name: str,
    values: dict[str, Any],
    *,
    out_path: str | None,
    timeout: float,
) -> None:
    spec = TOOLS[name]
    token = require_token()
    url = BASE_URL + spec["path"] + "?" + urlencode(values, doseq=True)
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        with urlopen(request, timeout=timeout, context=tls_context()) as response:
            response_body = response.read()
            status_code = response.status
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CliError(
            f"TikHub 返回 HTTP {exc.code}；本次请求可能已计费。"
            f"响应：{detail[:2000]}"
        ) from exc
    except URLError as exc:
        raise CliError(f"TikHub 请求失败：{exc}") from exc

    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    meta = {
        "tool": name,
        "method": "GET",
        "endpoint": spec["path"],
        "arguments": values,
        "fetched_at_utc": fetched_at,
        "http_status": status_code,
        "bytes": len(response_body),
        "cache_url": find_cache_url(payload),
        "billable_api_calls": 1,
    }
    write_result(response_body, out_path=out_path, meta=meta)


def fetch_cache(url: str, *, out_path: str | None, timeout: float) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cache.tikhub.io":
        raise CliError("只允许读取 https://cache.tikhub.io/ 下的缓存 URL")
    request = Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    try:
        with urlopen(request, timeout=timeout, context=tls_context()) as response:
            body = response.read()
            status_code = response.status
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CliError(f"缓存 URL 返回 HTTP {exc.code}：{detail[:2000]}") from exc
    except URLError as exc:
        raise CliError(f"缓存 URL 请求失败：{exc}") from exc
    meta = {
        "tool": "fetch-cache",
        "method": "GET",
        "endpoint": "TikHub public cache",
        "arguments": {},
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "http_status": status_code,
        "bytes": len(body),
        "cache_url": url,
        "billable_api_calls": 0,
    }
    write_result(body, out_path=out_path, meta=meta)


def print_list() -> None:
    for name, spec in TOOLS.items():
        print(f"{name:34} GET  {spec['path']}")


def print_description(name: str) -> None:
    spec = TOOLS[name]
    print(
        json.dumps(
            {
                "name": name,
                "method": "GET",
                "path": spec["path"],
                "required": spec["required"],
                "one_of": spec["one_of"],
                "allowed": spec["allowed"],
                "defaults": spec["defaults"],
                "note": spec["note"],
                "billable_when": "call is used with --execute",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TikHub client for Xiaohongshu creator benchmarking"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="列出允许的小红书端点，不调用 API")

    describe = subparsers.add_parser("describe", help="查看端点参数")
    describe.add_argument("tool", choices=sorted(TOOLS))

    call = subparsers.add_parser("call", help="预览或执行一次 TikHub 请求")
    call.add_argument("tool", choices=sorted(TOOLS))
    call.add_argument("--args", help="JSON object 参数")
    call.add_argument("--arg", action="append", default=[], help="key=value，可重复")
    call.add_argument("--execute", action="store_true", help="真正发出一次付费请求")
    call.add_argument("--out", help="保存响应；同时生成 .meta.json")
    call.add_argument("--timeout", type=float, default=45.0)

    cache = subparsers.add_parser("fetch-cache", help="读取 TikHub 24 小时缓存")
    cache.add_argument("url")
    cache.add_argument("--out")
    cache.add_argument("--timeout", type=float, default=45.0)

    subparsers.add_parser("token-status", help="显示 Token 来源，不显示 Token")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "list":
            print_list()
        elif args.command == "describe":
            print_description(args.tool)
        elif args.command == "token-status":
            token, source = token_source()
            print(
                json.dumps(
                    {"configured": bool(token), "source": source},
                    ensure_ascii=False,
                )
            )
        elif args.command == "fetch-cache":
            fetch_cache(args.url, out_path=args.out, timeout=args.timeout)
        elif args.command == "call":
            values = validate(args.tool, collect_args(args.args, args.arg))
            spec = TOOLS[args.tool]
            if not args.execute:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "tool": args.tool,
                            "method": "GET",
                            "url": BASE_URL + spec["path"],
                            "arguments": values,
                            "would_issue_tikhub_api_calls": 1,
                            "hint": "确认参数后加 --execute，并使用 --out 落盘。",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                execute_call(
                    args.tool,
                    values,
                    out_path=args.out,
                    timeout=args.timeout,
                )
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
