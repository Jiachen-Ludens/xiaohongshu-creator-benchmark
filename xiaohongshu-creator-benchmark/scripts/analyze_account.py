#!/usr/bin/env python3
"""Offline statistics and evidence preparation for one Xiaohongshu account."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable


UTC = dt.timezone.utc
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
SCHEMA_VERSION = 1


class AnalysisError(ValueError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"{path}: JSON 解析失败：{exc.msg}") from exc
    except OSError as exc:
        raise AnalysisError(f"{path}: 无法读取：{exc}") from exc


def parse_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    multiplier = 1
    if text.lower().endswith("w") or text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.lower().endswith("k") or text.endswith("千"):
        multiplier = 1_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def nested_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def pick(value: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        found = nested_get(value, path)
        if found not in (None, ""):
            return found
    return None


def unwrap_data(payload: Any) -> Any:
    current = payload
    for _ in range(3):
        if isinstance(current, dict) and "data" in current:
            current = current["data"]
        else:
            break
    return current


def profile_data(payload: Any) -> dict[str, Any]:
    current = unwrap_data(payload)
    if not isinstance(current, dict):
        raise AnalysisError("主页响应中没有识别到 data object")
    return current


def posts_data(payload: Any) -> list[dict[str, Any]]:
    current = unwrap_data(payload)
    if isinstance(current, dict) and isinstance(current.get("notes"), list):
        return [item for item in current["notes"] if isinstance(item, dict)]
    raise AnalysisError("作品响应中没有识别到 notes 列表")


def find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = find_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_key(child, key)
            if found is not None:
                return found
    return None


def detail_data(payload: Any) -> dict[str, Any]:
    notes = find_key(payload, "note_list")
    if isinstance(notes, list) and notes and isinstance(notes[0], dict):
        return notes[0]
    current = unwrap_data(payload)
    if isinstance(current, dict) and any(
        key in current for key in ("id", "note_id", "title", "desc")
    ):
        return current
    raise AnalysisError("详情响应中没有识别到笔记")


def comments_data(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current = unwrap_data(payload)
    if not isinstance(current, dict) or not isinstance(current.get("comments"), list):
        raise AnalysisError("评论响应中没有识别到 comments 列表")
    rows = [item for item in current["comments"] if isinstance(item, dict)]
    return rows, current


def parse_as_of(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(UTC)
    text = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise AnalysisError("--as-of 必须是 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def timestamp_to_datetime(value: Any) -> dt.datetime | None:
    parsed = parse_count(value)
    if parsed is None:
        return None
    if parsed > 10_000_000_000:
        parsed //= 1000
    try:
        return dt.datetime.fromtimestamp(parsed, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def median(values: Iterable[int | float | None]) -> int | float | None:
    known = [value for value in values if value is not None]
    return statistics.median(known) if known else None


def percentile(values: Iterable[int | float | None], fraction: float) -> float | None:
    known = sorted(float(value) for value in values if value is not None)
    if not known:
        return None
    if len(known) == 1:
        return known[0]
    position = (len(known) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(known) - 1)
    weight = position - lower
    return known[lower] * (1 - weight) + known[upper] * weight


def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    interactions = raw.get("interactions") if isinstance(raw.get("interactions"), list) else []
    interaction_counts = {
        str(item.get("type")): parse_count(item.get("count"))
        for item in interactions
        if isinstance(item, dict)
    }
    stats = raw.get("note_num_stat") if isinstance(raw.get("note_num_stat"), dict) else {}
    return {
        "user_id": str(pick(raw, "userid", "user_id", "id") or ""),
        "red_id": str(pick(raw, "red_id", "redId") or ""),
        "nickname": str(pick(raw, "nickname", "name") or "未知账号"),
        "bio": str(pick(raw, "desc", "share_info.content") or ""),
        "fans": parse_count(pick(raw, "fans")) or interaction_counts.get("fans"),
        "posted": parse_count(pick(stats, "posted")) or parse_count(pick(raw, "ndiscovery")),
        "liked": parse_count(pick(stats, "liked")) or parse_count(pick(raw, "liked")),
        "collected": parse_count(pick(stats, "collected")) or parse_count(pick(raw, "collected")),
        "location": str(pick(raw, "ip_location", "location") or ""),
    }


def metric(raw: dict[str, Any], *paths: str) -> int:
    return int(parse_count(pick(raw, *paths)) or 0)


def normalize_post(
    raw: dict[str, Any],
    *,
    as_of: dt.datetime,
    immature_hours: int,
) -> dict[str, Any]:
    published = timestamp_to_datetime(
        pick(raw, "create_time", "time", "publish_time")
    )
    age_hours = None
    mature = False
    if published:
        age_hours = max(0.0, (as_of - published).total_seconds() / 3600)
        mature = age_hours >= immature_hours
    likes = metric(raw, "likes", "liked_count", "interact_info.liked_count")
    collects = metric(raw, "collected_count", "collects", "interact_info.collected_count")
    comments = metric(raw, "comments_count", "comment_count", "interact_info.comment_count")
    shares = metric(raw, "share_count", "shared_count", "interact_info.shared_count")
    images = raw.get("images_list") if isinstance(raw.get("images_list"), list) else []
    media_type = "video" if raw.get("type") == "video" or raw.get("video_info_v2") else "image"
    return {
        "note_id": str(pick(raw, "id", "note_id") or ""),
        "title": str(pick(raw, "title", "display_title") or "无标题"),
        "summary": str(pick(raw, "desc", "description") or ""),
        "published_at_utc": published.isoformat() if published else "",
        "published_date_china": published.astimezone(CHINA_TZ).date().isoformat() if published else "",
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "mature": mature,
        "media_type": media_type,
        "image_count": len(images),
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": shares,
        "engagement": likes + collects + comments + shares,
        "sticky": bool(raw.get("sticky")),
        "evidence_layer": "observable_content",
    }


def normalize_detail(raw: dict[str, Any]) -> dict[str, Any]:
    images = raw.get("images_list") if isinstance(raw.get("images_list"), list) else []
    return {
        "note_id": str(pick(raw, "id", "note_id") or ""),
        "title": str(pick(raw, "title", "display_title") or "无标题"),
        "body": str(pick(raw, "desc", "description") or ""),
        "media_type": "video" if raw.get("type") == "video" or raw.get("video_info_v2") else "image",
        "image_count": len(images),
        "likes": metric(raw, "likes", "liked_count"),
        "collects": metric(raw, "collected_count"),
        "comments": metric(raw, "comments_count", "comment_count"),
        "shares": metric(raw, "share_count", "shared_count"),
        "evidence_layer": "observable_content",
    }


def normalize_comment(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "evidence_id": f"comment-{index:03d}",
        "content": str(raw.get("content") or "").strip(),
        "likes": metric(raw, "like_count"),
        "sub_comment_count": metric(raw, "sub_comment_count"),
        "evidence_layer": "public_comment",
    }


def round_number(value: int | float | None, digits: int = 2) -> int | float | None:
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return round(float(value), digits)


def meta_for(path: Path) -> dict[str, Any] | None:
    meta_path = path.with_name(path.name + ".meta.json")
    if not meta_path.is_file():
        return None
    loaded = load_json(meta_path)
    return loaded if isinstance(loaded, dict) else None


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        identity = path.expanduser().resolve()
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def build_output(
    profile_path: Path,
    posts_path: Path,
    detail_paths: list[Path],
    comments_paths: list[Path],
    *,
    as_of: dt.datetime,
    immature_hours: int,
    extra_source_paths: list[Path] | None = None,
) -> dict[str, Any]:
    profile = normalize_profile(profile_data(load_json(profile_path)))
    posts = [
        normalize_post(raw, as_of=as_of, immature_hours=immature_hours)
        for raw in posts_data(load_json(posts_path))
    ]
    mature_posts = [post for post in posts if post["mature"]]
    ranked = sorted(
        mature_posts,
        key=lambda post: (post["engagement"], post["likes"], post["note_id"]),
        reverse=True,
    )
    high = ranked[:3]
    high_ids = {post["note_id"] for post in high}
    low = [
        post
        for post in sorted(
            mature_posts,
            key=lambda post: (post["engagement"], post["likes"], post["note_id"]),
        )
        if post["note_id"] not in high_ids
    ][:2]

    details = [
        normalize_detail(detail_data(load_json(path))) for path in detail_paths
    ]
    comments: list[dict[str, Any]] = []
    comment_pages: list[dict[str, Any]] = []
    for path in comments_paths:
        raw_comments, page = comments_data(load_json(path))
        offset = len(comments)
        comments.extend(
            normalize_comment(raw, offset + index + 1)
            for index, raw in enumerate(raw_comments)
        )
        comment_pages.append(
            {
                "returned": len(raw_comments),
                "reported_total": parse_count(page.get("comment_count")),
                "has_more": bool(page.get("has_more")),
                "sort_strategy": str(page.get("current_sort_strategy") or ""),
            }
        )

    engagement_values = [post["engagement"] for post in mature_posts]
    total_engagement = sum(engagement_values)
    top3_engagement = sum(
        post["engagement"]
        for post in sorted(mature_posts, key=lambda post: post["engagement"], reverse=True)[:3]
    )
    likes_sum = sum(post["likes"] for post in mature_posts)
    collects_sum = sum(post["collects"] for post in mature_posts)
    dates = sorted(
        {post["published_date_china"] for post in posts if post["published_date_china"]}
    )
    span_days = 0
    if dates:
        first = dt.date.fromisoformat(dates[0])
        last = dt.date.fromisoformat(dates[-1])
        span_days = (last - first).days + 1

    input_paths = unique_paths(
        [
            profile_path,
            posts_path,
            *detail_paths,
            *comments_paths,
            *(extra_source_paths or []),
        ]
    )
    metas = [meta for path in input_paths if (meta := meta_for(path))]
    api_calls = sum(int(meta.get("billable_api_calls") or 0) for meta in metas)
    used_cache = any(
        meta.get("tool") == "fetch-cache"
        or int(meta.get("billable_api_calls") or 0) == 0
        for meta in metas
    )

    metrics = {
        "sample_count": len(posts),
        "mature_count": len(mature_posts),
        "immature_count": len(posts) - len(mature_posts),
        "likes_median": round_number(median(post["likes"] for post in mature_posts)),
        "collects_median": round_number(median(post["collects"] for post in mature_posts)),
        "comments_median": round_number(median(post["comments"] for post in mature_posts)),
        "shares_median": round_number(median(post["shares"] for post in mature_posts)),
        "engagement_median": round_number(median(engagement_values)),
        "engagement_p90": round_number(percentile(engagement_values, 0.9)),
        "top3_concentration": round(top3_engagement / total_engagement, 4)
        if total_engagement
        else None,
        "collect_like_ratio": round(collects_sum / likes_sum, 4)
        if likes_sum
        else None,
        "active_days": len(dates),
        "date_first": dates[0] if dates else "",
        "date_last": dates[-1] if dates else "",
        "span_days": span_days,
        "posts_per_week": round(len(posts) / span_days * 7, 2)
        if span_days
        else None,
        "image_posts": sum(post["media_type"] == "image" for post in posts),
        "video_posts": sum(post["media_type"] == "video" for post in posts),
    }

    evidence = [
        {
            "evidence_id": "profile-public-data",
            "layer": "public_data",
            "supports": ["账号规模", "累计互动", "作品数量"],
        },
        {
            "evidence_id": "profile-bio-self-report",
            "layer": "creator_self_report",
            "content": profile["bio"],
            "warning": "简介属于创作者自述，未独立核验。",
        },
    ]
    evidence.extend(
        {
            "evidence_id": f"post-{index:03d}",
            "layer": "observable_content",
            "note_id": post["note_id"],
            "title": post["title"],
        }
        for index, post in enumerate(posts, 1)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": dt.datetime.now(UTC).isoformat(),
        "as_of_utc": as_of.isoformat(),
        "immature_hours": immature_hours,
        "profile": profile,
        "metrics": metrics,
        "posts": posts,
        "selected_samples": {"high": high, "low": low},
        "details": details,
        "comments": comments,
        "comment_pages": comment_pages,
        "evidence": evidence,
        "api_calls": api_calls,
        "used_cache": used_cache,
        "source_files": [str(path) for path in input_paths],
        "limitations": [
            "公开互动是采集时快照，不等于浏览、涨粉、购买或收入。",
            "创作者简介和正文中的履历、收入与账号结果按自述处理。",
            "脚本只计算描述性统计和选择样本，不证明成功原因。",
            "高低表现对照仍可能受到发布时间、选题热度和平台分发影响。",
        ],
    }


def display(value: Any) -> str:
    if value in (None, ""):
        return "未提供"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def display_percent(value: Any) -> str:
    if value in (None, ""):
        return "未提供"
    return f"{float(value) * 100:.1f}%"


def render_report(data: dict[str, Any]) -> str:
    profile = data["profile"]
    metrics = data["metrics"]
    lines = [
        f"# {profile['nickname']}（{profile['red_id'] or profile['user_id']}）账号对标分析骨架",
        "",
        "> 本文件由确定性脚本生成统计和证据索引。成功原因、内容机制和策略建议必须由 Agent 回读内容后补充。",
        "",
        "## 一、待 Agent 完成的一句话结论",
        "",
        "- 结论：待分析。",
        "- 证据层级：必须区分公开数据、内容观察、创作者自述、分析推断和策略建议。",
        "",
        "## 二、账号数据快照",
        "",
        "| 指标 | 数据 |",
        "|---|---:|",
        f"| 粉丝 | {display(profile['fans'])} |",
        f"| 主页作品数 | {display(profile['posted'])} |",
        f"| 累计获赞 | {display(profile['liked'])} |",
        f"| 累计收藏 | {display(profile['collected'])} |",
        f"| 近期样本 | {metrics['sample_count']} |",
        f"| 成熟 / 未成熟 | {metrics['mature_count']} / {metrics['immature_count']} |",
        f"| 互动中位数 | {display(metrics['engagement_median'])} |",
        f"| 互动 P90 | {display(metrics['engagement_p90'])} |",
        f"| Top 3 互动占比 | {display_percent(metrics['top3_concentration'])} |",
        f"| 收藏/点赞 | {display_percent(metrics['collect_like_ratio'])} |",
        f"| 活跃发布日 | {metrics['active_days']} |",
        f"| 折算周更 | {display(metrics['posts_per_week'])} |",
        "",
        "## 三、高低表现作品对照",
        "",
        "| 组别 | 标题 | 赞 | 藏 | 评 | 转 | 总互动 | 成熟 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for group in ("high", "low"):
        label = "高表现" if group == "high" else "低表现"
        for post in data["selected_samples"][group]:
            lines.append(
                f"| {label} | {post['title']} | {post['likes']} | "
                f"{post['collects']} | {post['comments']} | {post['shares']} | "
                f"{post['engagement']} | {'是' if post['mature'] else '否'} |"
            )
    lines.extend(
        [
            "",
            "待 Agent 对照：标题承诺、开头兑现、证据、具体场景、完整交付、广告转场和 CTA。",
            "",
            "## 四、作品详情证据",
            "",
        ]
    )
    if data["details"]:
        for detail in data["details"]:
            lines.extend(
                [
                    f"### {detail['title']}",
                    "",
                    f"- 笔记 ID：`{detail['note_id']}`",
                    f"- 类型：{detail['media_type']}；图片数：{detail['image_count']}",
                    f"- 数据：赞 {detail['likes']} / 藏 {detail['collects']} / "
                    f"评 {detail['comments']} / 转 {detail['shares']}",
                    f"- 正文：{detail['body'][:500] or '未提供'}",
                    "",
                ]
            )
    else:
        lines.append("- 未提供详情，不能分析正文、画面或字幕结构。")
    lines.extend(["", "## 五、评论证据", ""])
    if data["comments"]:
        for comment in data["comments"][:20]:
            lines.append(
                f"- `{comment['evidence_id']}`：{comment['content']} "
                f"（赞 {comment['likes']}，回复 {comment['sub_comment_count']}）"
            )
    else:
        lines.append("- 未提供评论，不能判断真实使用、痛点、传播或质疑。")
    lines.extend(
        [
            "",
            "待 Agent 分类：真实使用、场景痛点、传播信号、质疑反例、诱导式互动。",
            "",
            "## 六、待 Agent 完成的成功机制",
            "",
            "1. 注意力获取：待分析。",
            "2. 信任建立：待分析。",
            "3. 内容交付：待分析。",
            "4. 关注理由：待分析。",
            "5. 商业承接：待分析。",
            "",
            "## 七、可复制与不可复制",
            "",
            "- 可复制机制：待分析。",
            "- 身份、资源或能力壁垒：待分析。",
            "- 风险与适用边界：待分析。",
            "",
            "## 八、方法与边界",
            "",
            f"- 数据截止：{data['as_of_utc']}",
            f"- TikHub 计费调用：{data['api_calls']}",
            f"- 使用缓存：{'是' if data['used_cache'] else '否'}",
        ]
    )
    lines.extend(f"- 局限：{item}" for item in data["limitations"])
    lines.extend(["", "### 原始数据", ""])
    lines.extend(f"- `{path}`" for path in data["source_files"])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze one Xiaohongshu creator from saved TikHub JSON"
    )
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--posts", required=True, type=Path)
    parser.add_argument("--detail", action="append", default=[], type=Path)
    parser.add_argument("--comments", action="append", default=[], type=Path)
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        type=Path,
        help="其他参与本次研究的响应文件，用于完整统计调用数和来源",
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--as-of", help="ISO 8601；测试或历史数据建议显式提供")
    parser.add_argument("--immature-hours", type=int, default=24)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.immature_hours < 0:
            raise AnalysisError("--immature-hours 不能为负数")
        output = build_output(
            args.profile,
            args.posts,
            args.detail,
            args.comments,
            as_of=parse_as_of(args.as_of),
            immature_hours=args.immature_hours,
            extra_source_paths=args.source,
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        normalized_path = args.out_dir / "normalized.json"
        report_path = args.out_dir / "report-skeleton.md"
        normalized_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report_path.write_text(render_report(output), encoding="utf-8")
        print(
            json.dumps(
                {
                    "normalized": str(normalized_path.resolve()),
                    "report": str(report_path.resolve()),
                    "sample_count": output["metrics"]["sample_count"],
                    "mature_count": output["metrics"]["mature_count"],
                    "high_samples": len(output["selected_samples"]["high"]),
                    "low_samples": len(output["selected_samples"]["low"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except AnalysisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
