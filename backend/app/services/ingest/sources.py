"""默认源清单 —— 加一个源 = 加一段配置，不在代码里写死抓取逻辑。

五个源都尽量走 L0（RSS / 官方 JSON / 官方 API）：

    机器之心  L0  官方文章 JSON（列表 + 详情）
    量子位    L0  WordPress RSS + 文章页正文
    InfoQ     L0  RSS + 文章页正文
    新智元    L0  WordPress RSS + WP REST 正文接口（页面自己也是这么取的）
    GitHub    L0  官方 Search API（可选 GITHUB_TOKEN）

站点改版时先改 `config`：选择器、详情模板、查询词都在这里。
长期失效就 `enabled=False`，主链路不受影响。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestSource

DEFAULT_SOURCES: list[dict] = [
    {
        "key": "jiqizhixin",
        "name": "机器之心",
        "home_url": "https://www.jiqizhixin.com",
        "feed_url": "https://www.jiqizhixin.com/api/article_library/articles.json?sort=time&page=1&per={limit}",
        "kind": "json_api",
        "level": "L0",
        "category": "tech",
        "priority": 10,
        "max_items": 12,
        "config": {
            "list_key": "articles",
            "detail_url": "https://www.jiqizhixin.com/api/article_library/articles/{id}.json",
            "article_url": "https://www.jiqizhixin.com/articles/{id}",
            "id_field": "slug",
            "title_field": "title",
            "summary_field": "content",
            "published_field": "publishedAt",
            "topics_field": "tagList",
            "fetch_detail": True,
            "detail_content_field": "content",
            "content_selectors": [".article-content", ".rich-text", "article"],
        },
    },
    {
        "key": "qbitai",
        "name": "量子位",
        "home_url": "https://www.qbitai.com",
        "feed_url": "https://www.qbitai.com/feed",
        "kind": "rss",
        "level": "L0",
        "category": "tech",
        "priority": 9,
        "max_items": 12,
        "config": {
            "fetch_detail": True,
            "content_selectors": [".content", "article", ".entry-content"],
        },
    },
    {
        "key": "infoq",
        "name": "InfoQ",
        "home_url": "https://www.infoq.cn",
        "feed_url": "https://www.infoq.cn/feed",
        "kind": "rss",
        "level": "L0",
        "category": "tech",
        "priority": 8,
        "max_items": 12,
        "config": {
            "fetch_detail": True,
            "content_selectors": [".article-content", "article", ".content"],
        },
    },
    {
        "key": "aiera",
        "name": "新智元",
        "home_url": "https://aiera.com.cn",
        "feed_url": "https://aiera.com.cn/feed",
        "kind": "rss",
        "level": "L0",
        "category": "tech",
        "priority": 8,
        "max_items": 12,
        "config": {
            "fetch_detail": True,
            # 新智元正文是 JS 渲染的，但页面自己就是调 WP REST 取正文 ——
            # 直接走同一个接口，比 L2 真浏览器更快也更稳。
            "detail_api": "https://aiera.com.cn/wp-json/wp/v2/posts/{id}?_embed=1",
            "id_from_url": r"/(\d+)/",
            "detail_content_field": "content.rendered",
            "content_selectors": [".post", "article", ".entry-content"],
        },
    },
    {
        "key": "github",
        "name": "GitHub",
        "home_url": "https://github.com",
        "feed_url": "https://api.github.com/search/repositories",
        "kind": "github",
        "level": "L0",
        "category": "tech",
        "priority": 7,
        "max_items": 10,
        "config": {
            # GitHub Search 的 OR 和 created/stars 限定组合在一起会返回 0 条，
            # 所以每个 topic 单独查，合并后再按 stars 排序（在 crawler 里做）。
            "queries": ["topic:llm", "topic:ai-agents", "topic:generative-ai"],
            "sort": "stars",
            "order": "desc",
            "created_within_days": 45,
            "min_stars": 300,
        },
    },
]


async def ensure_seed(db: AsyncSession) -> None:
    """只在缺 key 时补一行 —— 不覆盖工作台里改过的配置。"""
    existing = set((await db.execute(select(IngestSource.key))).scalars().all())
    changed = False
    for item in DEFAULT_SOURCES:
        if item["key"] in existing:
            continue
        db.add(IngestSource(**item))
        changed = True
    if changed:
        await db.commit()
