# 小红书博主对标分析 Skill

输入一个小红书博主，这个 Codex Skill 会用公开数据告诉你：**他为什么成功、哪些能学、哪些学不了。**

它只做一件事：研究单个小红书账号。它不会搜索全网热点，不做抖音、公众号或其他平台，也不会承诺照着做就能爆。

## 它会交付什么

- 账号和近期作品的数据基线；
- 点赞、收藏、评论、分享的中位数与分布；
- 高表现与低表现作品的账号内对照；
- 内容支柱、标题承诺、正文兑现和视觉/视频结构；
- 评论区中的真实使用、痛点、传播与质疑信号；
- 注意力、信任、内容交付、关注理由和商业承接链路；
- 可复制机制、不可复制壁垒、风险和样本边界。

查看完整示例：[某AI博主账号拆解](examples/ai-creator-report.md)。

## 安装

```bash
git clone https://github.com/Jiachen-Ludens/xiaohongshu-creator-benchmark.git
cp -R xiaohongshu-creator-benchmark/xiaohongshu-creator-benchmark ~/.codex/skills/
```

重新打开 Codex 后，使用 `$xiaohongshu-creator-benchmark`，或直接说：

```text
研究一下这个小红书博主：<主页链接>
分析其为什么能成功，并把报告写入 ./creator-benchmark-report.md。
```

## 注册 TikHub

这个 Skill 使用 TikHub 获取小红书公开数据，因此需要你准备自己的 TikHub API Key。TikHub 是付费服务，不是本项目提供的免费接口。

- [使用我的邀请链接注册 TikHub](https://user.tikhub.io/register?ref=Gqosvz0l)
- [不使用邀请码注册 TikHub](https://user.tikhub.io/register)

### 利益关系说明

第一个链接包含我的邀请码。如果你通过它注册，我会获得少量佣金。如果你不希望使用我的邀请码，直接选择第二个链接即可，也可以手动删除邀请链接中的 `?ref=Gqosvz0l`。

我真心推荐 TikHub。以我自己的使用体验，它比自行维护小红书抓取方案稳定、省心。虽然需要付费，但少量充值通常可以使用较长时间；实际费用取决于调用次数和 TikHub 当时的接口定价。时间也是成本，是否使用请根据自己的需求判断。

注册和配置：

1. 打开上方任一链接，按页面提示完成注册并登录 TikHub。
2. 在 TikHub 控制台创建或复制自己的 API Key；如需调用付费接口，按自己的使用量充值。
3. 在本机通过环境变量或权限受限的配置文件保存 API Key。

使用环境变量：

```bash
export TIKHUB_API_KEY="your-token"
```

也可以写入配置文件：

```bash
mkdir -p ~/.config/xiaohongshu-creator-benchmark
touch ~/.config/xiaohongshu-creator-benchmark/tikhub-token
chmod 600 ~/.config/xiaohongshu-creator-benchmark/tikhub-token
${EDITOR:-vi} ~/.config/xiaohongshu-creator-benchmark/tikhub-token
```

不要把 Token 发给 Codex、写进提示词或提交到 GitHub。

## 默认报告目录

可以为最终 Markdown 报告设置一个默认根目录：

```bash
mkdir -p ~/.config/xiaohongshu-creator-benchmark
printf '%s\n' "/absolute/path/to/report-root" \
  > ~/.config/xiaohongshu-creator-benchmark/report-root
```

未在提示词中指定文件路径时，Skill 会查看根目录中的现有分类，选择最合适的子目录；没有合适分类时会新建。TikHub 原始数据和统计中间文件仍保存在任务工作区，不会写进笔记库。

## 默认数据流程

一轮基础研究通常先覆盖以下 6 类 TikHub API 调用：

1. 按小红书号搜索用户；
2. 获取主页信息；
3. 获取近期作品；
4. 获取一条高表现作品详情；
5. 获取一条低表现作品详情；
6. 获取代表作一级评论。

上面只是基础流程。实际分析时，可以继续获取更多作品、笔记详情和评论，不限制调用次数。以数据足以支撑结论为准，同时留意 API 费用。

每次请求默认只预览，不计费。只有显式增加 `--execute` 才会发出请求。24 小时内优先复用已保存的响应或 TikHub 缓存。

## 手动运行脚本

预览一次账号搜索：

```bash
python3 xiaohongshu-creator-benchmark/scripts/tikhub_xhs.py call xhs_search_users \
  --arg keyword=creator_keyword
```

执行并保存响应：

```bash
python3 xiaohongshu-creator-benchmark/scripts/tikhub_xhs.py call xhs_search_users \
  --arg keyword=creator_keyword --execute \
  --out research-data/users.json
```

生成确定性统计和报告骨架：

```bash
python3 xiaohongshu-creator-benchmark/scripts/analyze_account.py \
  --profile research-data/profile.json \
  --posts research-data/posts.json \
  --source research-data/users.json \
  --detail research-data/high-note.json \
  --detail research-data/low-note.json \
  --comments research-data/comments.json \
  --out-dir research-output
```

脚本只计算数据和选择样本，不会自动编造“成功原因”。最终判断由 Codex 根据正文、画面、字幕、评论和证据边界完成。

## 方法边界

- 只处理公开页面，不绕过登录、访问控制或平台限制。
- 公开互动不等于真实购买、收入或粉丝增长。
- 创作者履历、收入和账号矩阵等说法按“创作者自述”处理。
- 样本相关性不等于因果；报告必须说明采集日期和样本量。
- 新发布不足 24 小时的作品会标为未成熟，不轻率参与表现判断。
- TikHub 的接口、价格和可见字段可能变化，请以其当前服务为准。

## 开发验证

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 tools/public_check.py .
.venv/bin/python ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  xiaohongshu-creator-benchmark
```

## English

This repository contains a focused Codex skill for evidence-based benchmarking of one Xiaohongshu creator. TikHub is required as the public-data API. The skill compares account-level baselines, high- and low-performing posts, content delivery, audience signals, and replication limits.
