"""采集 runner 的稳定入口（`python -m app.ingest.runner`）。

实现放在 `app.services.ingest`，这里只做一层薄壳，
让 Hermes skill 不必关心内部目录调整。
"""
