/* selfsec 前端 —— 一个窗口 + 一个回溯弹层。零依赖零构建。 */

const $ = (s) => document.querySelector(s);
const stream = $('#stream');

let items = [];
let plans = [];

/* ---------- 工具 ---------- */
function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function toDate(iso) {
  return new Date(String(iso).replace(' ', 'T'));
}

function hhmm(iso) {
  const d = toDate(iso);
  return isNaN(d) ? '' : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function dayLabel(iso) {
  const d = toDate(iso);
  if (isNaN(d)) return '';
  const key = (x) => `${x.getFullYear()}-${x.getMonth() + 1}-${x.getDate()}`;
  const now = new Date();
  const yest = new Date(Date.now() - 864e5);
  if (key(d) === key(now)) return '今天';
  if (key(d) === key(yest)) return '昨天';
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}

let toastTimer;
function toast(msg, ms = 1800) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), ms);
}

/* ---------- API ---------- */
function getToken() {
  return localStorage.getItem('selfsec_token') || '';
}

// 并发请求可能同时收到 401（loadAll 一次发两个请求），共用一个输入过程，只问一次
let askingToken = null;

function askToken() {
  if (!askingToken) {
    askingToken = Promise.resolve(prompt('服务端已开启鉴权，请输入 API Token（只需一次）'))
      .then((input) => {
        if (!input || !input.trim()) throw new Error('未提供 Token');
        localStorage.setItem('selfsec_token', input.trim());
      })
      .finally(() => {
        askingToken = null;
      });
  }
  return askingToken;
}

async function api(path, opts = {}, retried = false) {
  const used = getToken();                       // 这次请求实际用的 token
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (used) headers['X-API-Token'] = used;

  const res = await fetch(path, { ...opts, headers });

  if (res.status === 401) {
    if (retried) throw new Error('API Token 无效');
    // 另一个并发请求刚把新 token 写进去了 —— 直接用它重试，不再多问一次
    if (getToken() !== used) return api(path, opts, true);
    await askToken();
    return api(path, opts, true);
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

/* ---------- 主窗口渲染 ---------- */
function tagChips(tags) {
  const list = (tags || []).filter(Boolean);
  if (!list.length) return '';
  return `<div class="tags">${list.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>`;
}

function cardHTML(card) {
  if (!card) return '';
  const kind = ['record', 'plan', 'greeting', 'insight'].includes(card.kind) ? card.kind : 'record';
  const meta = card.meta || {};
  const title = esc(card.title || '');

  if (kind === 'plan' && meta.plan_id) {
    const done = plans.find((p) => p.id === meta.plan_id)?.status === 'done';
    return `<div class="card plan">
      <h4>待办</h4>
      <div class="plan-row${done ? ' done' : ''}" data-plan="${esc(meta.plan_id)}">
        <div class="plan-box"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div>
        <div class="plan-title">${esc(card.title || '')}</div>
      </div>
      ${tagChips(meta.tags)}
    </div>`;
  }

  const lines = (card.lines || []).filter(Boolean).map((l) => `<li>${esc(l)}</li>`).join('');
  const url = meta.source_url;
  const src = url
    ? `<div class="src">来源：<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(meta.source_name || url)}</a></div>`
    : '';
  const merged = meta.merged
    ? `<div class="merged">同一件事，第 ${esc(String(meta.merged_count || 2))} 次补充</div>`
    : '';

  return `<div class="card ${kind}">
    ${title ? `<h4>${title}</h4>` : ''}
    ${lines ? `<ul>${lines}</ul>` : ''}
    ${tagChips(meta.tags)}
    ${merged}
    ${src}
  </div>`;
}

function rowHTML(m) {
  const mine = m.role === 'me';
  const quiet = !mine && !m.card && m.kind === 'greeting';
  return `<div class="row ${mine ? 'me' : 'sec'}">
    <div class="bubble${quiet ? ' quiet' : ''}">${esc(m.content)}</div>
    ${mine ? '' : cardHTML(m.card)}
    <div class="when">${hhmm(m.created_at)}</div>
  </div>`;
}

function render() {
  if (!items.length) {
    stream.innerHTML = `<div class="empty">还没有任何内容。<br>随便说一句，从这里开始。</div>`;
    return;
  }
  stream.innerHTML = items.map(rowHTML).join('');
  stream.scrollTop = stream.scrollHeight;
}

function renderBadge() {
  const open = plans.filter((p) => p.status === 'open').length;
  const b = $('#plans-badge');
  b.hidden = open === 0;
  b.textContent = `${open} 个待办`;
}

/* ---------- 回溯弹层 ---------- */
const D = { filter: 'all', items: [], cursor: null, done: false, loading: false };
const PAGE = 30;

function hitemHTML(m) {
  // role=event 是「合并后的事件」，role=me/secretary 是窗口里的原话与回应
  let cls = 'record';
  let label = '我说';
  if (m.role === 'event') {
    label = m.kind === 'plan' ? '待办' : '事件';
  } else if (m.role === 'secretary') {
    if (m.kind === 'insight') { cls = 'insight'; label = '洞察'; }
    else if (m.kind === 'greeting') label = '问候';
    else label = '回应';
  }
  if (m.kind === 'feeling') cls = 'feeling';

  const card = m.card || {};
  const lines = card.lines || [];
  const text = m.kind === 'insight'
    ? [m.content, ...lines.slice(1)].filter(Boolean).join('\n')
    : m.content;
  const url = card.meta && card.meta.source_url;
  const link = url
    ? `<div class="hlink">来源：<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(card.meta.source_name || url)}</a></div>`
    : '';
  const count = m.merged_count > 1 ? `<span class="hcount">合了 ${m.merged_count} 条消息</span>` : '';

  return `<div class="hitem ${cls}">
    <div class="htime">${hhmm(m.created_at)}</div>
    <div class="hbody"><span class="hkind">${label}</span>${count}<div class="htext">${esc(text)}</div>${tagChips(m.tags)}${link}</div>
  </div>`;
}

function renderDrawer() {
  const body = $('#drawer-body');
  if (!D.items.length) {
    body.innerHTML = `<div class="drawer-empty">这里还没有内容。</div>`;
    return;
  }
  let html = '';
  let lastDay = '';
  for (const m of D.items) {
    const day = dayLabel(m.created_at);
    if (day !== lastDay) {
      html += `<div class="daysep">${day}</div>`;
      lastDay = day;
    }
    html += hitemHTML(m);
  }
  body.innerHTML = html;
}

async function loadDrawer(reset) {
  if (D.loading) return;
  D.loading = true;
  if (reset) {
    D.items = [];
    D.cursor = null;
    D.done = false;
    $('#drawer-body').innerHTML = `<div class="drawer-empty">加载中…</div>`;
  }
  let url = `/api/messages?filter=${D.filter}&order=desc&limit=${PAGE}`;
  if (D.cursor) url += `&before=${encodeURIComponent(D.cursor)}`;
  try {
    const rows = await api(url);
    if (rows.length < PAGE) D.done = true;
    if (rows.length) D.cursor = rows[rows.length - 1].created_at;
    D.items = D.items.concat(rows);
    renderDrawer();
    $('#drawer-more').hidden = D.done || !D.items.length;
  } catch (e) {
    $('#drawer-body').innerHTML = `<div class="drawer-empty">加载失败：${esc(e.message)}</div>`;
  } finally {
    D.loading = false;
  }
}

function openDrawer() {
  $('#drawer').hidden = false;
  loadDrawer(true);
}

function closeDrawer() {
  $('#drawer').hidden = true;
}

/* ---------- 加载 ---------- */
async function loadAll() {
  const [msgs, pl] = await Promise.all([api('/api/messages?limit=60'), api('/api/plans')]);
  items = msgs;
  plans = pl;
  render();
  renderBadge();
}

/* ---------- 发送 ---------- */
async function send() {
  const input = $('#input');
  const content = input.value.trim();
  if (!content) return;

  const btn = $('#send');
  btn.disabled = true;
  input.disabled = true;

  items.push({ id: 'local', role: 'me', kind: 'user', content, card: null, created_at: new Date().toISOString() });
  input.value = '';
  autosize();
  render();
  stream.insertAdjacentHTML(
    'beforeend',
    `<div class="row sec" id="pending"><div class="bubble quiet thinking"><i></i><i></i><i></i></div></div>`
  );
  stream.scrollTop = stream.scrollHeight;

  try {
    const res = await api('/api/chat', { method: 'POST', body: JSON.stringify({ content }) });
    if (res && res.merged) toast('并入了今天已有的一件事');
    await loadAll();
  } catch (e) {
    toast('发送失败：' + e.message);
    items = items.filter((m) => m.id !== 'local');
    render();
  } finally {
    $('#pending')?.remove();
    input.disabled = false;
    input.focus();
    btn.disabled = !input.value.trim();
  }
}

/* ---------- 待办勾选 ---------- */
async function togglePlan(id) {
  const p = plans.find((x) => x.id === id);
  if (!p) return;
  const next = p.status === 'done' ? 'open' : 'done';
  try {
    await api(`/api/plans/${id}`, { method: 'PATCH', body: JSON.stringify({ status: next }) });
    p.status = next;
    render();
    renderBadge();
  } catch (e) {
    toast('更新失败：' + e.message);
  }
}

/* ---------- 自适应高度 ---------- */
function autosize() {
  const t = $('#input');
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 150) + 'px';
}

/* ---------- 事件绑定 ---------- */
$('#input').addEventListener('input', () => {
  autosize();
  $('#send').disabled = !$('#input').value.trim();
});
$('#input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
$('#send').addEventListener('click', send);

stream.addEventListener('click', (e) => {
  const row = e.target.closest('[data-plan]');
  if (row) togglePlan(row.dataset.plan);
});

$('#plans-badge').addEventListener('click', () => {
  const open = plans.filter((p) => p.status === 'open');
  toast(open.length ? open.map((p) => '· ' + p.title).join('   ') : '没有未完成的待办', 3200);
});

/* 回溯 */
$('#open-history').addEventListener('click', openDrawer);
$('#drawer-close').addEventListener('click', closeDrawer);
$('#drawer-more').addEventListener('click', () => loadDrawer(false));
$('#drawer').addEventListener('click', (e) => {
  if (e.target.id === 'drawer') closeDrawer();   // 点遮罩关闭
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('#drawer').hidden) closeDrawer();
});
$('#drawer-tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-f]');
  if (!b) return;
  D.filter = b.dataset.f;
  [...$('#drawer-tabs').children].forEach((x) => x.classList.toggle('on', x === b));
  loadDrawer(true);
});

/* ---------- 启动 ---------- */
(function init() {
  const d = new Date();
  $('#today').textContent = `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
  loadAll().catch((e) => {
    stream.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  });
})();
