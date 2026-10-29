/* 工作台 —— 消息推送后台。零依赖零构建。 */

const $ = (s) => document.querySelector(s);

const S = {
  pwd: sessionStorage.getItem('selfsec_wb_pwd') || '',
  tab: 'overview',
  sources: [],
  messages: [],
  selected: new Set(),
  timer: null,
  overview: null,
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function dt(v) {
  if (!v) return '—';
  const d = new Date(String(v).replace(' ', 'T'));
  if (isNaN(d)) return String(v);
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(
    2,
    '0'
  )}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function clip(s, n = 150) {
  const t = String(s || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
}

let toastTimer;
function toast(msg, ms = 2200) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

/* ---------- 鉴权 / 请求 ---------- */
function showGate(msg = '') {
  $('#gate').hidden = false;
  $('#gate-msg').textContent = msg;
  setTimeout(() => $('#gate-pwd')?.focus(), 30);
}

async function wb(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (S.pwd) headers['X-Workbench-Password'] = S.pwd;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    S.pwd = '';
    sessionStorage.removeItem('selfsec_wb_pwd');
    showGate('密码不正确，再试一次');
    throw new Error('需要工作台密码');
  }
  if (res.status === 503) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch {}
    showGate(detail);
    throw new Error(detail);
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

/* ---------- 概览 ---------- */
function statCard(k, v, d, cls = '') {
  return `<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${esc(v)}</div><div class="d">${esc(d)}</div></div>`;
}

function renderOverview(d) {
  S.overview = d;
  const t = d.tasks || {};
  const m = d.messages || {};
  const s = d.sources || {};
  $('#stat-cards').innerHTML = [
    statCard('排队中', t.queued || 0, '等 Hermes 领取'),
    statCard('运行中', t.running || 0, '正在执行'),
    statCard('失败', t.failed || 0, `成功 ${t.succeeded || 0} / 部分 ${t.partial || 0}`, t.failed ? 'warn' : ''),
    statCard('近 24h 消息', m.last_24h || 0, `累计 ${m.total || 0} 条`),
    statCard('源异常', s.error || 0, `${s.enabled || 0}/${s.total || 0} 个启用`, s.error ? 'warn' : 'ok'),
  ].join('');

  const cfg = d.config || {};
  const sch = cfg.schedule || {};
  const disp = cfg.dispatch || {};
  $('#config-box').innerHTML = `
    <div class="config-item"><b>每日采集</b>${
      sch.enabled ? `每天 ${String(sch.hour).padStart(2, '0')}:${String(sch.minute).padStart(2, '0')}` : '已关闭'
    }</div>
    <div class="config-item"><b>回看窗口</b>最近 ${esc(sch.lookback_hours ?? '—')} 小时 · 每源最多 ${esc(sch.max_items ?? '—')} 条</div>
    <div class="config-item"><b>下发方式</b>${
      disp.configured
        ? `<span class="ok">已配置 push</span> · ${esc(disp.url || '')}`
        : '<span class="bad">未配置 push</span> · Hermes 走 pull'
    }</div>`;

  $('#recent-tasks').innerHTML = (d.recent_tasks || []).length
    ? `<div class="list">${d.recent_tasks.map(taskRow).join('')}</div>`
    : `<div class="empty">还没有任务。去「任务」里手动下发一次。</div>`;

  $('#recent-runs').innerHTML = (d.recent_runs || []).length
    ? `<div class="list">${d.recent_runs.slice(0, 10).map(runRow).join('')}</div>`
    : `<div class="empty">还没有执行记录。</div>`;
}

function statsLine(t) {
  const s = t.stats || {};
  const bits = [];
  if (s.sources !== undefined) bits.push(`${s.sources} 个源`);
  if (s.new !== undefined) bits.push(`新增 ${s.new}`);
  if (s.updated !== undefined) bits.push(`更新 ${s.updated}`);
  if (s.failed) bits.push(`失败 ${s.failed}`);
  return bits.join(' · ');
}

function taskRow(t) {
  const stuck = t.status === 'queued' && t.dispatched_at;
  const actions = [
    `<button class="ghost small" data-action="task-detail" data-id="${esc(t.id)}">详情</button>`,
    ['queued', 'dispatched'].includes(t.status)
      ? `<button class="ghost small" data-action="task-dispatch" data-id="${esc(t.id)}">再推一次</button>`
      : '',
    ['queued', 'dispatched', 'running'].includes(t.status)
      ? `<button class="ghost small danger" data-action="task-cancel" data-id="${esc(t.id)}">取消</button>`
      : `<button class="ghost small" data-action="task-retry" data-id="${esc(t.id)}">重跑</button>`,
  ].join('');
  return `<div class="item">
    <div class="grow">
      <div class="title"><span class="badge ${esc(t.status)}">${statusLabel(t.status)}</span>
        <span class="badge ${esc(t.trigger)}">${t.trigger === 'schedule' ? '定时' : '手动'}</span>
        <span class="muted" style="font-weight:400"> ${esc(t.source_keys && t.source_keys.length ? t.source_keys.join(' / ') : '全部启用源')}</span>
      </div>
      <div class="meta-line">
        <span>创建 ${dt(t.created_at)}</span>
        ${t.started_at ? `<span>开始 ${dt(t.started_at)}</span>` : ''}
        ${statsLine(t) ? `<span>${esc(statsLine(t))}</span>` : ''}
        ${stuck ? '<span>已推送</span>' : ''}
      </div>
      ${t.error ? `<div class="desc" style="color:var(--red)">${esc(clip(t.error, 180))}</div>` : ''}
    </div>
    <div class="item-actions">${actions}</div>
  </div>`;
}

function statusLabel(s) {
  return (
    {
      queued: '排队',
      dispatched: '已推送',
      running: '运行中',
      succeeded: '成功',
      partial: '部分成功',
      failed: '失败',
      cancelled: '已取消',
      skipped: '跳过',
      new: '新消息',
      read: '已读',
      hidden: '已隐藏',
    }[s] || s
  );
}

function runRow(r) {
  const counts = [`找到 ${r.items_found}`];
  if (r.items_new) counts.push(`新增 ${r.items_new}`);
  if (r.items_updated) counts.push(`更新 ${r.items_updated}`);
  const elapsed = r.detail && r.detail.elapsed_ms ? ` · ${(r.detail.elapsed_ms / 1000).toFixed(1)}s` : '';
  return `<div class="item">
    <div class="grow">
      <div class="title"><span class="badge ${esc(r.status)}">${statusLabel(r.status)}</span>
        ${esc(r.source_name || r.source_key)} <span class="muted" style="font-weight:400">${esc(r.fetch_level || '')}</span></div>
      <div class="meta-line"><span>${counts.join(' · ')}${elapsed}</span><span>${dt(r.started_at)}</span></div>
      ${r.error ? `<div class="desc" style="color:var(--red)">${esc(clip(r.error, 200))}</div>` : ''}
    </div>
  </div>`;
}

/* ---------- 任务 ---------- */
async function loadTasks() {
  await ensureSources();
  renderTaskPicker();
  const rows = await wb('/api/workbench/tasks?limit=60');
  $('#task-count').textContent = `${rows.length} 个任务`;
  $('#task-list').innerHTML = rows.length
    ? `<div class="list">${rows.map(taskRow).join('')}</div>`
    : `<div class="empty">还没有任务。</div>`;
  const cfg = S.overview?.config?.dispatch;
  $('#dispatch-hint').textContent = cfg
    ? cfg.configured
      ? '已配置 push：创建后会直接喊 Hermes'
      : '未配置 push：创建后等 Hermes pull'
    : '';
}

function renderTaskPicker() {
  const enabled = S.sources.filter((s) => s.enabled);
  $('#task-sources').innerHTML = enabled.length
    ? enabled
        .map(
          (s) =>
            `<label class="pick"><input type="checkbox" value="${esc(s.key)}"> ${esc(s.name)}<span class="muted">${esc(
              s.key
            )}</span></label>`
        )
        .join('')
    : `<span class="muted">没有启用的源——先去「源」里打开几个。</span>`;
}

async function createTask() {
  const keys = [...$('#task-sources').querySelectorAll('input:checked')].map((i) => i.value);
  const btn = $('#create-task');
  btn.disabled = true;
  try {
    const task = await wb('/api/workbench/tasks', {
      method: 'POST',
      body: JSON.stringify({ source_keys: keys, trigger: 'manual' }),
    });
    const configured = S.overview?.config?.dispatch?.configured;
    toast(configured ? `任务已创建并推送：${task.id.slice(0, 8)}` : `任务已入队：${task.id.slice(0, 8)}（等 Hermes pull）`, 3000);
    $('#task-sources').querySelectorAll('input').forEach((i) => (i.checked = false));
    await loadTasks();
  } catch (e) {
    toast('下发失败：' + e.message, 3200);
  } finally {
    btn.disabled = false;
  }
}

async function showTaskDetail(id) {
  try {
    const d = await wb(`/api/workbench/tasks/${encodeURIComponent(id)}`);
    const t = d.task || {};
    const runs = d.runs || [];
    openModal(
      `任务 ${t.id}`,
      `<div class="field"><label>状态</label>
        <span class="badge ${esc(t.status)}">${statusLabel(t.status)}</span>
        <span class="badge ${esc(t.trigger)}">${t.trigger === 'schedule' ? '定时' : '手动'}</span>
        <span class="muted">创建 ${dt(t.created_at)} · 开始 ${dt(t.started_at)} · 结束 ${dt(t.finished_at)}</span>
      </div>
      <div class="field"><label>源</label><div>${esc((t.source_keys || []).join(' / ') || '全部启用源')}</div></div>
      <div class="field"><label>汇总</label><div>${esc(statsLine(t) || '—')}</div></div>
      ${t.error ? `<div class="field"><label>错误</label><div class="desc" style="color:var(--red)">${esc(t.error)}</div></div>` : ''}
      <div class="field"><label>每个源的执行记录</label>
        ${runs.length ? runs.map(runRow).join('') : '<div class="empty">还没有运行记录。</div>'}
      </div>`,
      [{ label: '关闭', cls: 'ghost', onClick: closeModal }]
    );
  } catch (e) {
    toast('取不到任务：' + e.message);
  }
}

/* ---------- 源 ---------- */
async function ensureSources(force = false) {
  if (S.sources.length && !force) return S.sources;
  S.sources = await wb('/api/workbench/sources');
  return S.sources;
}

async function loadSources() {
  await ensureSources(true);
  $('#source-list').innerHTML = S.sources.length
    ? `<div class="list">${S.sources.map(sourceRow).join('')}</div>`
    : `<div class="empty">还没有源。点「补回内置源」。</div>`;
}

function sourceRow(s) {
  const status = s.last_status
    ? `<span class="badge ${esc(s.last_status)}">${statusLabel(s.last_status)}</span>`
    : '<span class="muted">从未运行</span>';
  return `<div class="item ${s.last_status === 'failed' ? 'error' : ''}">
    <div class="grow">
      <div class="title">${esc(s.name)} <span class="muted" style="font-weight:400">${esc(s.key)}</span>
        <span class="badge">${esc(s.kind)} · ${esc(s.level)}</span>
        ${s.enabled ? '' : '<span class="badge cancelled">已停用</span>'}
      </div>
      <div class="meta-line">
        <span>${esc(s.feed_url || s.home_url || '')}</span>
        <span>${esc(s.category)} · 每源 ${s.max_items} 条 · 优先级 ${s.priority}</span>
      </div>
      <div class="meta-line"><span>${status}</span><span>${s.last_run_at ? '上次 ' + dt(s.last_run_at) : ''}</span></div>
      ${s.last_error ? `<div class="desc" style="color:var(--red)">${esc(clip(s.last_error, 180))}</div>` : ''}
    </div>
    <div class="item-actions">
      <button class="ghost small" data-action="source-toggle" data-id="${esc(s.id)}">${s.enabled ? '停用' : '启用'}</button>
      <button class="ghost small" data-action="source-run" data-id="${esc(s.id)}">试跑</button>
      <button class="ghost small" data-action="source-edit" data-id="${esc(s.id)}">编辑</button>
      <button class="ghost small danger" data-action="source-delete" data-id="${esc(s.id)}">删除</button>
    </div>
  </div>`;
}

function sourceModal(s) {
  const isNew = !s;
  const src = s || {
    key: '',
    name: '',
    home_url: '',
    feed_url: '',
    kind: 'rss',
    level: 'L0',
    category: 'tech',
    enabled: true,
    priority: 5,
    max_items: 12,
    interval_minutes: 1440,
    config: {},
  };
  const kindOpts = ['rss', 'json_api', 'html', 'github']
    .map((k) => `<option value="${k}" ${src.kind === k ? 'selected' : ''}>${k}</option>`)
    .join('');
  const levelOpts = ['L0', 'L1', 'L1.5', 'L2', 'L3']
    .map((k) => `<option value="${k}" ${src.level === k ? 'selected' : ''}>${k}</option>`)
    .join('');
  const catOpts = ['tech', 'finance', 'other']
    .map((k) => `<option value="${k}" ${src.category === k ? 'selected' : ''}>${k}</option>`)
    .join('');

  openModal(
    isNew ? '加一个源' : `编辑 ${src.name}`,
    `<div class="grid2">
      <div class="field"><label>key（稳定标识）</label><input id="f-key" type="text" value="${esc(src.key)}" ${
      isNew ? '' : 'disabled'
    } placeholder="qbitai"></div>
      <div class="field"><label>名称</label><input id="f-name" type="text" value="${esc(src.name)}" placeholder="量子位"></div>
    </div>
    <div class="field"><label>首页</label><input id="f-home" type="url" value="${esc(src.home_url)}" placeholder="https://example.com"></div>
    <div class="field"><label>RSS / API / 列表页</label><input id="f-feed" type="url" value="${esc(
      src.feed_url || ''
    )}" placeholder="https://example.com/feed">
      <div class="hint">json_api 的列表 URL 可用 <code>{limit}</code> 占位。</div></div>
    <div class="grid3">
      <div class="field"><label>类型</label><select id="f-kind" class="select">${kindOpts}</select></div>
      <div class="field"><label>起点</label><select id="f-level" class="select">${levelOpts}</select></div>
      <div class="field"><label>分类</label><select id="f-cat" class="select">${catOpts}</select></div>
    </div>
    <div class="grid3">
      <div class="field"><label>优先级</label><input id="f-priority" type="text" value="${esc(src.priority)}"></div>
      <div class="field"><label>每源条数</label><input id="f-max" type="text" value="${esc(src.max_items)}"></div>
      <div class="field"><label>启用</label><label class="check"><input id="f-enabled" type="checkbox" ${
      src.enabled ? 'checked' : ''
    }> 参与采集</label></div>
    </div>
    <div class="field"><label>config（JSON）</label><textarea id="f-config" rows="7">${esc(
      JSON.stringify(src.config || {}, null, 2)
    )}</textarea><div class="hint">解析细节：content_selectors / fetch_detail / query / min_stars …</div></div>`,
    [
      { label: '取消', cls: 'ghost', onClick: closeModal },
      {
        label: '保存',
        cls: 'primary',
        onClick: async (btn) => {
          let config;
          try {
            config = JSON.parse($('#f-config').value || '{}');
          } catch (e) {
            toast('config 不是合法 JSON');
            return;
          }
          const payload = {
            name: $('#f-name').value.trim(),
            home_url: $('#f-home').value.trim(),
            feed_url: $('#f-feed').value.trim() || null,
            kind: $('#f-kind').value,
            level: $('#f-level').value,
            category: $('#f-cat').value,
            enabled: $('#f-enabled').checked,
            priority: Number($('#f-priority').value) || 5,
            max_items: Number($('#f-max').value) || 12,
            interval_minutes: src.interval_minutes || 1440,
            config,
          };
          if (!payload.name || !payload.home_url) {
            toast('名称和首页必填');
            return;
          }
          btn.disabled = true;
          try {
            if (isNew) {
              payload.key = $('#f-key').value.trim();
              if (!payload.key) throw new Error('key 必填');
              await wb('/api/workbench/sources', { method: 'POST', body: JSON.stringify(payload) });
            } else {
              await wb(`/api/workbench/sources/${encodeURIComponent(src.id)}`, {
                method: 'PATCH',
                body: JSON.stringify(payload),
              });
            }
            closeModal();
            toast('已保存');
            await loadSources();
          } catch (e) {
            toast('保存失败：' + e.message, 3200);
          } finally {
            btn.disabled = false;
          }
        },
      },
    ]
  );
}

/* ---------- 消息 ---------- */
function messageRow(m) {
  const selected = S.selected.has(m.event_id);
  return `<div class="item" data-msg="${esc(m.event_id)}">
    <label class="check" style="padding-top:3px"><input type="checkbox" data-msg-check="${esc(
      m.event_id
    )}" ${selected ? 'checked' : ''}></label>
    <div class="grow">
      <div class="title">${esc(m.title)}
        <span class="badge ${esc(m.status)}">${statusLabel(m.status)}</span>
        ${Number(m.importance || 3) >= 4 ? '<span class="badge partial">重点</span>' : ''}
      </div>
      <div class="desc">${esc(clip(m.summary, 220))}</div>
      <div class="meta-line">
        <span>${esc(m.source_name || m.source_key || '—')}</span>
        ${m.category ? `<span>${esc(m.category)}</span>` : ''}
        ${m.published_at ? `<span>发布 ${dt(m.published_at)}</span>` : ''}
        <span>入库 ${dt(m.created_at)}</span>
        ${(m.tags || []).length ? `<span>${esc(m.tags.join(' · '))}</span>` : ''}
      </div>
    </div>
    <div class="item-actions">
      <button class="ghost small" data-action="msg-detail" data-id="${esc(m.event_id)}">详情 / 编辑</button>
      <button class="ghost small" data-action="msg-hide" data-id="${esc(m.event_id)}">${
        m.status === 'hidden' ? '恢复' : '隐藏'
      }</button>
      ${m.source_url ? `<a class="ghost small" href="${esc(m.source_url)}" target="_blank" rel="noreferrer">原文</a>` : ''}
      <button class="ghost small danger" data-action="msg-delete" data-id="${esc(m.event_id)}">删除</button>
    </div>
  </div>`;
}

async function loadMessages() {
  await ensureSources();
  const sel = $('#msg-source');
  const current = sel.value;
  const opts = ['<option value="">全部来源</option>']
    .concat(S.sources.map((s) => `<option value="${esc(s.key)}">${esc(s.name)}</option>`))
    .join('');
  sel.innerHTML = opts;
  sel.value = current;

  const q = new URLSearchParams({ limit: '200', include_hidden: $('#msg-hidden').checked ? 'true' : 'false' });
  if (sel.value) q.set('source_key', sel.value);
  const rows = await wb(`/api/workbench/messages?${q.toString()}`);
  S.messages = rows;
  S.selected.clear();
  renderMergeBar();
  $('#message-list').innerHTML = rows.length
    ? `<div class="list">${rows.map(messageRow).join('')}</div>`
    : `<div class="empty">还没有推送消息。</div>`;
}

function renderMergeBar() {
  const n = S.selected.size;
  $('#merge-bar').hidden = n < 2;
  $('#merge-count').textContent = n;
}

function messageById(id) {
  return S.messages.find((m) => m.event_id === id);
}

function showMessageDetail(id) {
  const m = messageById(id);
  if (!m) return;
  openModal(
    '消息详情',
    `<div class="field"><label>标题</label><input id="m-title" type="text" value="${esc(m.title)}"></div>
    <div class="field"><label>总结（卡面显示）</label><textarea id="m-summary" rows="3">${esc(m.summary || '')}</textarea></div>
    <div class="field"><label>影响</label><input id="m-impact" type="text" value="${esc(m.impact || '')}"></div>
    <div class="field"><label>详情（弹层显示）</label><textarea id="m-detail" rows="8">${esc(m.detail || '')}</textarea></div>
    <div class="grid2">
      <div class="field"><label>分类</label><input id="m-category" type="text" value="${esc(m.category || '')}"></div>
      <div class="field"><label>状态</label><select id="m-status" class="select">
        <option value="new" ${m.status === 'new' ? 'selected' : ''}>新消息</option>
        <option value="read" ${m.status === 'read' ? 'selected' : ''}>已读</option>
        <option value="hidden" ${m.status === 'hidden' ? 'selected' : ''}>已隐藏</option>
      </select></div>
    </div>
    <div class="field"><label>Topics（逗号分隔）</label><input id="m-topics" type="text" value="${esc(
      (m.topics || []).join(', ')
    )}"></div>
    <div class="field"><label>原文链接</label><input id="m-url" type="text" value="${esc(m.source_url || '')}"></div>
    ${m.source_url ? `<div class="field"><a href="${esc(m.source_url)}" target="_blank" rel="noreferrer">打开原文 ↗</a></div>` : ''}`,
    [
      { label: '取消', cls: 'ghost', onClick: closeModal },
      {
        label: '保存修改',
        cls: 'primary',
        onClick: async (btn) => {
          btn.disabled = true;
          try {
            await wb(`/api/workbench/messages/${encodeURIComponent(id)}`, {
              method: 'PATCH',
              body: JSON.stringify({
                title: $('#m-title').value.trim(),
                summary: $('#m-summary').value,
                impact: $('#m-impact').value,
                detail: $('#m-detail').value,
                category: $('#m-category').value.trim() || null,
                status: $('#m-status').value,
                topics: $('#m-topics')
                  .value.split(',')
                  .map((x) => x.trim())
                  .filter(Boolean),
                source_url: $('#m-url').value.trim() || null,
              }),
            });
            closeModal();
            toast('已保存，前台同步更新');
            await loadMessages();
          } catch (e) {
            toast('保存失败：' + e.message, 3200);
          } finally {
            btn.disabled = false;
          }
        },
      },
    ]
  );
}

async function toggleMessageHidden(id) {
  const m = messageById(id);
  if (!m) return;
  const next = m.status === 'hidden' ? 'new' : 'hidden';
  try {
    await wb(`/api/workbench/messages/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: next }),
    });
    toast(next === 'hidden' ? '已从前台隐藏' : '已恢复显示');
    await loadMessages();
  } catch (e) {
    toast('操作失败：' + e.message);
  }
}

async function deleteMessage(id) {
  const m = messageById(id);
  if (!m) return;
  if (!confirm(`删除这条消息？\n\n${m.title}\n\n（前台那张卡也会一起消失）`)) return;
  try {
    await wb(`/api/workbench/messages/${encodeURIComponent(id)}`, { method: 'DELETE' });
    toast('已删除');
    await loadMessages();
  } catch (e) {
    toast('删除失败：' + e.message);
  }
}

async function mergeSelected() {
  const ids = [...S.selected];
  if (ids.length < 2) return;
  const [primary, ...dups] = ids;
  if (!confirm(`把选中的 ${ids.length} 条合并成一条？\n\n主消息：${messageById(primary)?.title || primary}`)) return;
  try {
    await wb('/api/workbench/messages/merge', {
      method: 'POST',
      body: JSON.stringify({ primary_id: primary, duplicate_ids: dups }),
    });
    toast('已合并');
    await loadMessages();
  } catch (e) {
    toast('合并失败：' + e.message, 3200);
  }
}

/* ---------- 通用弹层 ---------- */
function openModal(title, bodyHTML, actions = []) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHTML;
  const foot = $('#modal-foot');
  foot.innerHTML = '';
  for (const a of actions) {
    const b = document.createElement('button');
    b.className = a.cls || 'ghost';
    b.textContent = a.label;
    b.addEventListener('click', () => a.onClick(b));
    foot.appendChild(b);
  }
  $('#modal').hidden = false;
}

function closeModal() {
  $('#modal').hidden = true;
}

/* ---------- 刷新 / 启动 ---------- */
async function refreshCurrent() {
  try {
    if (S.tab === 'overview') {
      const d = await wb('/api/workbench/overview');
      renderOverview(d);
    } else if (S.tab === 'tasks') {
      if (!S.overview) S.overview = await wb('/api/workbench/overview');
      await loadTasks();
    } else if (S.tab === 'sources') {
      await loadSources();
    } else {
      await loadMessages();
    }
    $('#refresh-at').textContent = `刷新于 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`;
  } catch (e) {
    if (e.message !== '需要工作台密码') toast('加载失败：' + e.message, 3200);
  }
}

function switchTab(tab) {
  S.tab = tab;
  [...$('#tabs').children].forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  document.querySelectorAll('.view').forEach((v) => (v.hidden = v.id !== `view-${tab}`));
  refreshCurrent();
}

function startTimer() {
  if (S.timer) clearInterval(S.timer);
  S.timer = setInterval(() => {
    if (document.hidden) return;
    if (!$('#modal').hidden || !$('#gate').hidden) return;
    refreshCurrent();
  }, 30000);
}

async function boot() {
  $('#gate').hidden = true;
  startTimer();
  await refreshCurrent();
}

/* ---------- 事件 ---------- */
$('#tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (b) switchTab(b.dataset.tab);
});

document.addEventListener('click', async (e) => {
  const a = e.target.closest('[data-goto]');
  if (a) {
    e.preventDefault();
    switchTab(a.dataset.goto);
    return;
  }

  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const { action, id } = btn.dataset;
  try {
    if (action === 'task-detail') await showTaskDetail(id);
    else if (action === 'task-dispatch') {
      const r = await wb(`/api/workbench/tasks/${encodeURIComponent(id)}/dispatch`, { method: 'POST' });
      toast(r.dispatched ? '已推送给 Hermes' : `没推出去：${r.detail}`, 3200);
      await refreshCurrent();
    } else if (action === 'task-retry') {
      await wb(`/api/workbench/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST' });
      toast('已创建重跑任务');
      await refreshCurrent();
    } else if (action === 'task-cancel') {
      if (!confirm('取消这个任务？已经开始的源可能还在跑。')) return;
      await wb(`/api/workbench/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
      toast('已取消');
      await refreshCurrent();
    } else if (action === 'source-toggle') {
      const s = S.sources.find((x) => x.id === id);
      if (!s) return;
      await wb(`/api/workbench/sources/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: !s.enabled }),
      });
      await loadSources();
    } else if (action === 'source-run') {
      const t = await wb(`/api/workbench/sources/${encodeURIComponent(id)}/run`, { method: 'POST' });
      toast(`已创建试跑任务：${t.id.slice(0, 8)}`);
      await loadSources();
    } else if (action === 'source-edit') {
      sourceModal(S.sources.find((x) => x.id === id));
    } else if (action === 'source-delete') {
      const s = S.sources.find((x) => x.id === id);
      if (!s || !confirm(`删除源「${s.name}」？\n（历史消息不受影响）`)) return;
      await wb(`/api/workbench/sources/${encodeURIComponent(id)}`, { method: 'DELETE' });
      toast('已删除');
      await loadSources();
    } else if (action === 'msg-detail') {
      showMessageDetail(id);
    } else if (action === 'msg-hide') {
      await toggleMessageHidden(id);
    } else if (action === 'msg-delete') {
      await deleteMessage(id);
    }
  } catch (err) {
    if (err.message !== '需要工作台密码') toast('操作失败：' + err.message, 3200);
  }
});

$('#message-list').addEventListener('change', (e) => {
  const cb = e.target.closest('[data-msg-check]');
  if (!cb) return;
  const id = cb.dataset.msgCheck;
  if (cb.checked) S.selected.add(id);
  else S.selected.delete(id);
  renderMergeBar();
});

$('#create-task').addEventListener('click', createTask);
$('#add-source').addEventListener('click', () => sourceModal(null));
$('#seed-sources').addEventListener('click', async () => {
  try {
    const r = await wb('/api/workbench/sources/seed', { method: 'POST' });
    toast(r.added && r.added.length ? `补回：${r.added.join('、')}` : '没有缺的源');
    await loadSources();
  } catch (e) {
    toast('操作失败：' + e.message);
  }
});
$('#reload-messages').addEventListener('click', loadMessages);
$('#msg-hidden').addEventListener('change', loadMessages);
$('#msg-source').addEventListener('change', loadMessages);
$('#merge-clear').addEventListener('click', () => {
  S.selected.clear();
  document.querySelectorAll('[data-msg-check]').forEach((c) => (c.checked = false));
  renderMergeBar();
});
$('#merge-go').addEventListener('click', mergeSelected);
$('#refresh').addEventListener('click', refreshCurrent);
$('#modal-close').addEventListener('click', closeModal);
$('#modal').addEventListener('click', (e) => {
  if (e.target.id === 'modal') closeModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#modal').hidden) closeModal();
});

$('#gate-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pwd = $('#gate-pwd').value.trim();
  if (!pwd) return;
  S.pwd = pwd;
  try {
    await wb('/api/workbench/check');
    sessionStorage.setItem('selfsec_wb_pwd', pwd);
    $('#gate-msg').textContent = '';
    await boot();
  } catch (err) {
    S.pwd = '';
    $('#gate-msg').textContent = err.message;
  }
});

/* ---------- 启动 ---------- */
(async function init() {
  if (!S.pwd) {
    showGate();
    return;
  }
  try {
    await wb('/api/workbench/check');
    await boot();
  } catch (e) {
    if (e.message !== '需要工作台密码') showGate(e.message);
  }
})();
