"""采集层服务：源配置 / 抓取 / 任务 / 消息回写。

代码放在 selfsec 仓库里，**执行方是 Hermes**：
Hermes 的 skill 在仓库里运行 `python -m app.ingest.runner`，
再通过 `/api/ingest/*` 把结果写回来。这样 selfsec 不常驻抓取进程，
但采集规则、解析器、源配置仍然可版本化、可测试。
"""
