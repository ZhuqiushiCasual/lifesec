"""记忆层 —— 本项目的技术核心。

四层，按「变化频率 / 成本」划分，对应架构图 ④ 的四个子模块：

  4.1 profile.py   长期画像（总结意识）  慢变 · 走 LLM · 定期/阈值触发
  4.2 stats.py     事实与统计            实时 · 纯 SQL · 每次对话都查
  4.3 insights.py  洞察记忆              外部驱动 · 读 events(source=hermes)
  4.4 session.py   会话短期              最近 N 轮 · 用于指代消解

  context.py       ③ Context 组装 —— 把上面四层拼成 Memory Block + history
"""
