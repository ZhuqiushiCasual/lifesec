# 小红书抓图：给 `/date` 每家餐厅配 6 张实拍图

`/date` 的卡片封面和图集来自小红书笔记。这里的三个脚本是一条流水线，
**依赖装在独立的 venv 里**（Playwright + Pillow，不要装进 backend 的依赖）：

```bash
python -m venv <venv>
<venv>/Scripts/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple playwright pillow
# 用本机已装的 Edge，不再下 Chromium：脚本里 channel="msedge"
```

## 顺序

1. **登录**（一次性；登录态存在 `scripts/xhs_photos/profile/`，已被 gitignore）
   打开有头浏览器停在小红书登录页，人工扫码。`web_session` 之类的 cookie 存在 profile 里。
2. `python scrape.py [编号...]`
   按 `menu.json` 的顺序逐家搜 → 点开笔记 → 从 `__INITIAL_STATE__` 取 `imageList` →
   下 6 张到 `backend/static/date_photos/rNN/`，清单写 `out/rNN.json`（已存在就跳过，可断点续抓）。
3. `python compress.py` 最长边 960 / WebP q74，把 30 MB 压到 15 MB 左右。
4. `python import_photos.py <base_url> <date_admin_password>`
   走 `POST /api/date/items/{id}/photos` 整组写入（按店名对齐菜单 id），写完回读核对张数。

## 为什么要这么绕

- **不能直接开笔记 URL**：`goto /explore/<id>` 会被 `300031 当前笔记暂时无法浏览` 挡住。
  必须先在搜索结果里渲染出卡片，再 `click()` 卡片走 SPA 内部路由 —— 弹层才正常加载。
- **图集从 `__INITIAL_STATE__.note.noteDetailMap[noteId].note.imageList` 取**，
  不要扫 DOM：弹层只挂当前视口附近那几张。
- **标题里不带店名的笔记要剔掉**：小红书搜「XX 杭州」会混进同商圈别的店。
  `import_photos.py` 的规则是：标题带店名的够 3 张，就把不带的丢掉。
- 图不入仓库（`backend/static/date_photos/` 已 gitignore），线上靠 scp 传；
  数据库里只存路径 + 宽高 + 来源笔记链接。
