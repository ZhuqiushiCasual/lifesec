/* selfsec 前端 —— 一个窗口，零依赖零构建。 */

const $ = (s) => document.querySelector(s);
const stream = $('#stream');

let items = [];
let plans = [];

/* ---------- 工具 ---------- */
function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function hhmm(iso) {
  const d = new Date(String(iso).replace(' ', 'T'));
  if (isNaN(d)) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
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

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const tk = getToken();
  if (tk) headers['X-API-Token'] = tk;

  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    const input = prompt('服务端已开启鉴权，请输入 API Token（只需一次）');
    if (input) {
      localStorage.setItem('selfsec_token', input.trim());
      return api(path, opts);
    }
    throw new Error('未提供 Token');
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

/* ---------- 渲染 ---------- */
function cardHTML(card) {
  if (!card) return '';
  const kind = ['record', 'plan', 'greeting', 'insight'].includes(card.kind) ? card.kind : 'record';
  const title = esc(card.title || '');

  if (kind === 'plan' && card.meta && card.meta.plan_id) {
    const done = plans.find((p) => p.id === card.meta.plan_id)?.status === 'done';
    return `<div class="card plan">
      <h4>待办</h4>
      <div class="plan-row${done ? ' done' : ''}" data-plan="${esc(card.meta.plan_id)}">
        <div class="plan-box"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div>
        <div class="plan-title">${esc(card.title || '')}</div>
      </div>
    </div>`;
  }

  const lines = (card.lines || []).filter(Boolean).map((l) => `<li>${esc(l)}</li>`).join('');
  const url = card.meta && card.meta.source_url;
  const srcName = card.meta && card.meta.source_name;
  const src = url
    ? `<div class="src">来源：<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(srcName || url)}</a></div>`
    : '';

  return `<div class="card ${kind}">
    ${title ? `<h4>${title}</h4>` : ''}
    ${lines ? `<ul>${lines}</ul>` : ''}
    ${src}
  </div>`;
}

function rowHTML(m) {
  const mine = m.role === 'me';
  const quiet = !mine && !m.card && ['greeting'].includes(m.kind);
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

  // 先本地上屏，不等服务端
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
    await api('/api/chat', { method: 'POST', body: JSON.stringify({ content }) });
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

$('#plans-badge').addEventListener('click', async () => {
  const open = plans.filter((p) => p.status === 'open');
  toast(open.length ? open.map((p) => '· ' + p.title).join('   ') : '没有未完成的待办', 3200);
});

/* ---------- 启动 ---------- */
(function init() {
  const d = new Date();
  $('#today').textContent = `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
  loadAll().catch((e) => {
    stream.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  });
})();
