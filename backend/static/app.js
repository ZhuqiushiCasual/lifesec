'use strict';

/* ============ 工具 ============ */
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const TYPE_ICONS = {
  dietary: '🍽️', sport: '🏃', health: '🩺', mood: '😊', social: '👥',
  work: '💼', invest: '📈', finance: '💰', sleep: '😴', event: '📌',
};
const TYPE_NAMES = {
  dietary: '饮食', sport: '运动', health: '健康', mood: '情绪', social: '社交',
  work: '工作', invest: '投资', finance: '财务', sleep: '睡眠', event: '事件',
};
const CAT_ICONS = { ai: '🤖', finance: '📈', industry: '🏭' };
const CAT_NAMES = { all: '全部', ai: 'AI', finance: '金融', industry: '行业' };
const TXN_ICONS = { income: '📈', expense: '🛒', asset: '🏦', liability: '🏠' };
const TXN_NAMES = { income: '收入', expense: '支出', asset: '资产', liability: '负债' };
const CHART_COLORS = {
  primary: 'var(--primary)', accentLavender: 'var(--lavender)',
  accentWheat: 'var(--wheat)', accentPeach: 'var(--peach)', accentSky: 'var(--sky)',
};
const MOOD_EMOJI = { positive: '😊', neutral: '😐', negative: '🙁' };

const WEEKDAY_CN = ['日', '一', '二', '三', '四', '五', '六'];

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, ms = 1800) {
  const el = $('#toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, ms);
}

function showErr(err) {
  if (err && err.message && err.message !== '需要访问令牌') toast(err.message, 2600);
  console.error(err);
}

function hhmm(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function fmtDateCN(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEKDAY_CN[d.getDay()]}`;
}

function timeAgo(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
  return new Date(iso).toISOString().slice(0, 10);
}

function fmtAmount(n) {
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

/* ============ API ============ */
let token = localStorage.getItem('ls_token') || '';

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body) headers['Content-Type'] = 'application/json';
  if (token) headers['X-API-Token'] = token;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    askToken();
    throw new Error('需要访问令牌');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `请求失败 (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

function askToken() {
  const dlg = $('#token-dialog');
  if (!dlg.open) dlg.showModal();
}

$('#token-form').addEventListener('submit', () => {
  token = $('#token-input').value.trim();
  if (token) localStorage.setItem('ls_token', token);
  refresh();
});

/* ============ 记录页 ============ */
const SUGGESTIONS = [
  { label: '🍳 早餐', text: '早餐吃了' },
  { label: '😴 睡眠', text: '昨晚睡了' },
  { label: '🏃 运动', text: '晚上健身' },
  { label: '😊 情绪', text: '今天心情' },
];

async function loadRecord() {
  const b = await api('/api/board/today');

  $('#greeting').textContent = `${b.greeting} 🌿`;
  $('#today-date').textContent = fmtDateCN(b.date + 'T00:00:00');

  const chips = [];
  chips.push(`<span class="status-chip ${b.sport_done ? 'ok' : ''}">${b.sport_done ? '运动 ✅' : '未运动'}</span>`);
  if (b.mood) {
    chips.push(`<span class="status-chip ok">心情 ${MOOD_EMOJI[b.mood] || '😐'}</span>`);
  }
  if (b.water_warning) chips.push('<span class="status-chip warn">喝水不足 ⚠️</span>');
  $('#status-chips').innerHTML = chips.join('');

  const tl = $('#timeline');
  tl.innerHTML = b.recent_events.length
    ? b.recent_events.map((e) => `
      <li>
        <span class="tl-time">${hhmm(e.recorded_at)}</span>
        <span class="tl-icon">${TYPE_ICONS[e.type] || '📌'}</span>
        <span class="tl-content">${esc(e.content)}<span class="tl-type">${TYPE_NAMES[e.type] || esc(e.type)}</span></span>
        <button class="tl-del" data-id="${e.id}" title="删除">×</button>
      </li>`).join('')
    : '<li class="empty">今天还没有记录，说点什么吧</li>';

  const mi = $('#mini-insights');
  mi.innerHTML = b.latest_insights.length
    ? b.latest_insights.map((i) => `
      <button class="mini-card" data-goto="insight">
        <div class="mini-cat">${CAT_ICONS[i.category] || '📌'} ${CAT_NAMES[i.category] || esc(i.category)}</div>
        <div class="mini-title">${esc(i.title)}</div>
        <div class="mini-summary">${esc(i.summary)}</div>
      </button>`).join('')
    : '<p class="empty" style="width:100%">暂无动态</p>';
}

function bindRecord() {
  const input = $('#input');
  const send = $('#send');

  const autosize = () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 96) + 'px';
  };
  input.addEventListener('input', () => {
    autosize();
    send.disabled = !input.value.trim();
  });

  const doSend = async () => {
    const content = input.value.trim();
    if (!content) return;
    send.classList.add('sending');
    try {
      await api('/api/events', { method: 'POST', body: JSON.stringify({ content }) });
      input.value = '';
      autosize();
      send.disabled = true;
      toast('已记录 ✅');
      loadRecord().catch(showErr);
    } catch (err) {
      showErr(err);
    } finally {
      send.classList.remove('sending');
    }
  };
  send.addEventListener('click', doSend);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  });

  $('#suggestions').innerHTML = SUGGESTIONS.map((s, i) =>
    `<button class="chip" data-i="${i}">${s.label}</button>`).join('');
  $('#suggestions').addEventListener('click', (e) => {
    const chip = e.target.closest('[data-i]');
    if (chip) {
      input.value = SUGGESTIONS[chip.dataset.i].text;
      input.focus();
      autosize();
      send.disabled = false;
    }
  });

  $('#timeline').addEventListener('click', async (e) => {
    const del = e.target.closest('.tl-del');
    if (!del) return;
    if (!confirm('删除这条记录？')) return;
    try {
      await api(`/api/events/${del.dataset.id}`, { method: 'DELETE' });
      toast('已删除');
      loadRecord().catch(showErr);
    } catch (err) {
      showErr(err);
    }
  });
}

/* ============ 秘书页 ============ */
async function loadSecretary() {
  $('#secretary-date').textContent = fmtDateCN(new Date());
  const [bR, wR, dR, sR, tR] = await Promise.allSettled([
    api('/api/board/today'),
    api('/api/memory/weekly'),
    api('/api/digests/latest'),
    api('/api/finance/summary'),
    api('/api/finance/txns?page=1&page_size=10'),
  ]);
  const b = bR.status === 'fulfilled' ? bR.value : null;
  const w = wR.status === 'fulfilled' ? wR.value : null;
  const digest = dR.status === 'fulfilled' ? dR.value : null;
  const summary = sR.status === 'fulfilled' ? sR.value : null;
  const txns = tR.status === 'fulfilled' ? tR.value : null;

  /* 今日 + 财务概览 */
  let boardHTML = '<p class="section-title">今日看板</p>';
  if (b) {
    boardHTML += `
      <div class="card">
        <div class="txn" style="border:none;padding:2px 0">
          <span class="txn-icon">📝</span>
          <div class="txn-main"><div class="txn-note">今日已记录 <b>${b.today_event_count}</b> 条</div>
          <div class="txn-meta">${b.sport_done ? '已运动 ✅' : '未运动'}${b.mood ? ` · 心情 ${MOOD_EMOJI[b.mood] || ''}` : ''}${b.water_warning ? ' · 喝水不足 ⚠️' : ''}</div></div>
        </div>
      </div>`;
  }
  if (summary) {
    const net = Number(summary.monthly_net);
    boardHTML += `
      <p class="section-title">本月财务</p>
      <div class="kpi-row">
        <div class="kpi"><div class="num plus">+${fmtAmount(summary.monthly_inflow)}</div><div class="label">流入</div></div>
        <div class="kpi"><div class="num minus">-${fmtAmount(summary.monthly_outflow)}</div><div class="label">流出</div></div>
        <div class="kpi"><div class="num ${net >= 0 ? 'plus' : 'minus'}">${net >= 0 ? '+' : '-'}${fmtAmount(Math.abs(net))}</div><div class="label">净额</div></div>
      </div>`;
  }
  $('#sec-board').innerHTML = boardHTML;

  /* 周趋势图表 */
  let chartsHTML = '<p class="section-title">本周趋势</p>';
  if (w && w.charts.length) {
    chartsHTML += w.charts.map((c) => chartHTML(c, w.day_labels)).join('');
  } else {
    chartsHTML += '<div class="card"><p class="empty">本周还没有可统计的记录</p></div>';
  }
  $('#sec-charts').innerHTML = chartsHTML;

  /* 本周健康/睡眠事件 */
  if (w && w.health_events.length) {
    $('#sec-health').innerHTML = `
      <p class="section-title">本周健康</p>
      <div class="card"><ul class="timeline">
        ${w.health_events.map((e) => `
          <li>
            <span class="tl-time">${timeAgo(e.recorded_at)}</span>
            <span class="tl-icon">${TYPE_ICONS[e.type] || '🩺'}</span>
            <span class="tl-content">${esc(e.content)}</span>
          </li>`).join('')}
      </ul></div>`;
  } else {
    $('#sec-health').innerHTML = '';
  }

  /* 最新日报 */
  if (digest) {
    const block = (title, obj) => {
      const items = obj && typeof obj === 'object' ? Object.values(obj) : [];
      return items.length
        ? `<div class="digest-block"><h4>${title}</h4><ul>${items.map((v) => `<li>${esc(v)}</li>`).join('')}</ul></div>`
        : '';
    };
    $('#sec-digest').innerHTML = `
      <p class="section-title">日报 · ${fmtDateCN(digest.date + 'T00:00:00')}</p>
      <div class="card">
        <div class="digest-score">
          <div class="score-num">${digest.score ?? '--'}<small> /100</small></div>
          <div class="sub">今日评分</div>
        </div>
        ${block('✨ 亮点', digest.highlights)}
        ${block('⚠️ 问题', digest.problems)}
        ${block('💡 建议', digest.suggestions)}
        ${block('📈 长期变化', digest.trends)}
      </div>`;
  } else {
    $('#sec-digest').innerHTML = '';
  }

  /* 最近交易 */
  if (txns && txns.items.length) {
    $('#sec-finance').innerHTML = `
      <p class="section-title">最近交易</p>
      <div class="card">
        ${txns.items.map((t) => {
          const plus = t.type === 'income';
          return `
          <div class="txn">
            <span class="txn-icon">${TXN_ICONS[t.type] || '💰'}</span>
            <div class="txn-main">
              <div class="txn-note">${esc(t.counterparty || t.note || TXN_NAMES[t.type] || t.type)}</div>
              <div class="txn-meta">${TYPE_NAMES[t.category] || esc(t.category)} · ${timeAgo(t.recorded_at)}</div>
            </div>
            <span class="txn-amount ${plus ? 'plus' : 'minus'}">${plus ? '+' : '-'}${t.currency === 'CNY' ? '¥' : t.currency + ' '}${fmtAmount(t.amount)}</span>
          </div>`;
        }).join('')}
      </div>`;
  } else {
    $('#sec-finance').innerHTML = '';
  }
}

function chartHTML(c, labels) {
  const max = Math.max(...c.data, c.target || 0, 1);
  const color = CHART_COLORS[c.color] || 'var(--primary)';
  const bars = c.data.map((v) => {
    const h = v > 0 ? Math.max((v / max) * 100, 4) : 0;
    return `
      <div class="bar-col">
        <div class="bar-track">
          ${c.target ? `<div class="target-line" style="bottom:${((c.target / max) * 100).toFixed(1)}%"></div>` : ''}
          ${v > 0 ? `<div class="bar" style="height:${h.toFixed(1)}%;background:${color}"></div>` : ''}
        </div>
        <span class="bar-value">${v ? Math.round(v * 10) / 10 : ''}</span>
      </div>`;
  }).join('');
  return `
    <div class="card">
      <div class="chart-title">${esc(c.title)}</div>
      <div class="chart-summary">${esc(c.summary)}</div>
      <div class="bars">${bars}</div>
      <div class="bar-labels">${labels.map((l) => `<span>${esc(l)}</span>`).join('')}</div>
    </div>`;
}

/* ============ 洞察页 ============ */
const state = { category: 'all', page: 1, items: [], total: 0 };

async function loadInsights(reset = false) {
  if (reset) {
    state.page = 1;
    state.items = [];
  }
  const q = state.category === 'all' ? '' : `category=${encodeURIComponent(state.category)}&`;
  const data = await api(`/api/insights?${q}page=${state.page}&page_size=10`);
  state.items = state.items.concat(data.items);
  state.total = data.total;

  $('#insight-list').innerHTML = state.items.length
    ? state.items.map((i) => `
      <article class="insight-card">
        <div class="insight-top">
          <span class="insight-cat">${CAT_ICONS[i.category] || '📌'} ${CAT_NAMES[i.category] || esc(i.category)}</span>
          ${(i.importance || 0) >= 4 ? '<span class="insight-imp">重要</span>' : ''}
        </div>
        <div class="insight-title">${esc(i.title)}</div>
        <div class="insight-summary">${esc(i.summary)}</div>
        ${i.impact ? `<div class="insight-impact">影响：${esc(i.impact)}</div>` : ''}
        ${i.topics && i.topics.length ? `<div class="topics">${i.topics.map((t) => `<span class="topic">${esc(t)}</span>`).join('')}</div>` : ''}
        <div class="insight-meta">
          ${i.source_url ? `<a href="${esc(i.source_url)}" target="_blank" rel="noopener">${esc(i.source_name || '来源')}</a>` : esc(i.source_name || '')}
          ${i.source_url ? ' · ' : ''}${timeAgo(i.published_at || i.created_at)}
        </div>
      </article>`).join('')
    : '<p class="empty">该分类下暂无洞察</p>';

  const more = $('#more-insights');
  const shown = state.page * 10;
  more.classList.toggle('hidden', shown >= state.total);
}

function bindInsights() {
  const filters = $('#insight-filters');
  filters.innerHTML = Object.entries(CAT_NAMES).map(([k, v]) =>
    `<button class="chip ${k === 'all' ? 'active' : ''}" data-cat="${k}">${v}</button>`).join('');
  filters.addEventListener('click', (e) => {
    const chip = e.target.closest('[data-cat]');
    if (!chip) return;
    $$('.chip', filters).forEach((c) => c.classList.toggle('active', c === chip));
    state.category = chip.dataset.cat;
    loadInsights(true).catch(showErr);
  });

  $('#more-insights').addEventListener('click', () => {
    state.page += 1;
    loadInsights().catch(showErr);
  });
}

/* ============ 路由 ============ */
const VIEWS = ['record', 'secretary', 'insight'];

function currentView() {
  const v = location.hash.replace('#', '');
  return VIEWS.includes(v) ? v : 'record';
}

function switchView(name) {
  VIEWS.forEach((v) => {
    $('#view-' + v).classList.toggle('active', v === name);
    $('#view-' + v).classList.toggle('hidden', v !== name);
  });
  $$('.tabbar button').forEach((b) => b.classList.toggle('active', b.dataset.view === name));

  if (name === 'record') loadRecord().catch(showErr);
  else if (name === 'secretary') loadSecretary().catch(showErr);
  else if (name === 'insight') loadInsights(true).catch(showErr);
}

function refresh() {
  switchView(currentView());
}

window.addEventListener('hashchange', refresh);
$$('.tabbar button').forEach((b) =>
  b.addEventListener('click', () => { location.hash = b.dataset.view; }));
document.addEventListener('click', (e) => {
  const goto = e.target.closest('[data-goto]');
  if (goto) location.hash = goto.dataset.goto;
});

/* ============ 启动 ============ */
bindRecord();
bindInsights();
switchView(currentView());

// Service Worker：仅在安全上下文（HTTPS 或 localhost）下注册
if ('serviceWorker' in navigator &&
    (location.protocol === 'https:' || location.hostname === 'localhost')) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
