/* selfsec 前端 —— 一个聊天窗口 + 两个全屏视图（回看 / 安排）。
   零依赖零构建。视觉世界：城市导视 / 线路图。 */

const $ = (s) => document.querySelector(s);
// 绑事件前先确认元素存在：万一浏览器拿着"旧 HTML + 新脚本"（缓存错配），
// 不至于在这一行整脚本挂掉、连消息流都渲染不出来。
const on = (s, evt, fn) => {
  const el = $(s);
  if (el) el.addEventListener(evt, fn);
  else console.warn('[selfsec] 页面缺少元素', s, '—— 前端脚本与 HTML 版本不一致，强制刷新一次');
};
const stream = $('#stream');

let items = [];
let plans = [];
let planOptions = { workout: [], food: [], outing: [] };
let planTab = 'workout';
let pickedWorkout = new Map();
let pendingPlan = null;

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

function dayStamp(iso) {
  const d = toDate(iso);
  if (isNaN(d)) return '';
  return `${d.getMonth() + 1}.${String(d.getDate()).padStart(2, '0')}`;
}

function dateKey(iso) {
  const d = toDate(iso);
  if (isNaN(d)) return '';
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

function fmtStamp(v) {
  if (!v) return '';
  const d = toDate(v);
  if (isNaN(d)) return '';
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${String(d.getHours()).padStart(2, '0')}:${String(
    d.getMinutes()
  ).padStart(2, '0')}`;
}

// 聊天窗口里跨天的历史消息只显示时分会被误读成乱序，补一个日期
function whenLabel(iso) {
  const d = toDate(iso);
  if (isNaN(d)) return '';
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  return sameDay ? hhmm(iso) : `${d.getMonth() + 1}/${d.getDate()} ${hhmm(iso)}`;
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

/* 洞察：一条消息存三样东西 —— 总结（卡面）/ 详情（弹层）/ 原文（外链）。 */
const insightCards = new Map();

function insightMeta(card) {
  const src = card.meta || {};
  const lines = card.lines || [];
  const impactLine = lines.find((l) => String(l).startsWith('影响：')) || '';
  return {
    ...src,
    title: src.title || card.title || '',
    summary: src.summary || lines[0] || '',
    impact: src.impact || impactLine.replace(/^影响：/, ''),
    detail: src.detail || '',
  };
}

function rememberInsight(card, fallbackContent) {
  const meta = insightMeta(card);
  if (!meta.summary && fallbackContent) meta.summary = fallbackContent;
  if (meta.event_id) insightCards.set(meta.event_id, meta);
  return meta;
}

function cardHTML(card) {
  if (!card) return '';
  const kind = ['record', 'plan', 'greeting', 'insight', 'workout'].includes(card.kind) ? card.kind : 'record';
  const meta = card.meta || {};
  const title = esc(card.title || '');

  if (kind === 'insight') {
    const m = rememberInsight(card);
    const when = fmtStamp(m.published_at);
    const hot = Number(m.importance || 3) >= 4 ? '<span class="insight-hot">重点</span>' : '';
    const link = m.source_url
      ? `<a class="insight-link" href="${esc(m.source_url)}" target="_blank" rel="noreferrer">原文链接 ↗</a>`
      : '';
    return `<div class="card insight">
      <div class="insight-top">
        <span class="insight-src">${esc(m.source_name || '外部消息')}</span>
        ${when ? `<span class="insight-when">${esc(when)}</span>` : ''}
        ${hot}
      </div>
      ${card.title ? `<h4 class="insight-title">${esc(card.title)}</h4>` : ''}
      ${m.summary ? `<p class="insight-summary">${esc(m.summary)}</p>` : ''}
      ${m.impact ? `<p class="insight-impact"><b>影响</b>${esc(m.impact)}</p>` : ''}
      ${tagChips(m.tags)}
      <div class="insight-actions">
        <button class="insight-more" data-insight="${esc(m.event_id || '')}">详情</button>
        ${link}
      </div>
    </div>`;
  }

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

  if (kind === 'workout') {
    const lines = (card.lines || []).filter(Boolean).map((l) => `<li>${esc(l)}</li>`).join('');
    return `<div class="card workout">
      <h4>训练${card.title ? ' · ' + esc(card.title) : ''}</h4>
      ${lines ? `<ul>${lines}</ul>` : ''}
      ${tagChips(meta.tags)}
      ${meta.workout_id ? `<div class="insight-actions"><button class="insight-more" data-workout="${esc(meta.workout_id)}">查看训练</button></div>` : ''}
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
    <div class="when">${whenLabel(m.created_at)}</div>
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
  if (!b) return;
  b.hidden = open === 0;
  b.textContent = `${open} 个待办`;
}

/* ---------- 回看：时间轴 = 线路，经历 = 站点 ---------- */
const RV = { filter: 'all', items: [], loading: false, expanded: new Set(), search: '' };

function updateRecallSub() {
  const el = $('#recall-sub');
  if (el) el.textContent = '按日子翻，也按地方找';
}

function eventTone(kind) {
  if (kind === 'plan') return { c: 'var(--amber)', label: '计划' };
  if (kind === 'feeling') return { c: 'var(--red)', label: '心情' };
  if (kind === 'finance') return { c: 'var(--graphite)', label: '账目' };
  if (kind === 'insight') return { c: 'var(--green)', label: '洞察' };
  return { c: 'var(--graphite)', label: '事件' };
}

function eventStopHTML(e, major) {
  const t = eventTone(e.kind);
  const label = e.domain === 'workout' ? '训练' : e.domain === 'dining' ? '吃饭' : t.label;
  const tone = e.domain === 'workout' ? 'var(--olive)' : e.domain === 'dining' ? 'var(--brick)' : t.c;
  const where = [e.place, e.people].filter(Boolean).join(' · ');
  const merged = (e.merged_count || 1) > 1
    ? `<div class="stop-meta">合了 <em>${e.merged_count}</em> 条消息</div>`
    : '';
  return `<div class="stop${major ? ' major' : ''}" style="--c:${tone}" data-event="${esc(e.id)}">
    <div class="stamp"><b>${label}</b><span>${hhmm(e.created_at)}</span></div>
    <div class="stop-title">${esc(e.content)}</div>
    ${where ? `<div class="stop-meta"><em>${esc(where)}</em></div>` : ''}
    ${tagChips(e.tags)}
    ${merged}
  </div>`;
}

function insightStopHTML(m, major) {
  const meta = rememberInsight(m.card || {}, m.content);
  const when = fmtStamp(meta.published_at) || hhmm(m.created_at);
  const link = meta.source_url
    ? `<a class="insight-link" href="${esc(meta.source_url)}" target="_blank" rel="noreferrer">原文 ↗</a>`
    : '';
  const detail = meta.event_id
    ? `<button class="hlink-btn" data-insight="${esc(meta.event_id)}">详情</button>`
    : '';
  return `<div class="stop${major ? ' major' : ''}" style="--c:var(--green)">
    <div class="stamp"><b>洞察</b><span>${esc(when)}</span></div>
    <div class="stop-title">${esc(meta.title || m.content)}</div>
    ${meta.summary ? `<div class="stop-meta">${esc(meta.summary)}</div>` : ''}
    ${tagChips(meta.tags)}
    ${detail || link ? `<div style="margin-top:8px">${detail}${link}</div>` : ''}
  </div>`;
}

function insightRowHTML(m) {
  const meta = rememberInsight(m.card || {}, m.content);
  const detail = meta.event_id
    ? `<button class="hlink-btn" data-insight="${esc(meta.event_id)}">详情</button>`
    : '';
  const link = meta.source_url
    ? `<a class="insight-link" href="${esc(meta.source_url)}" target="_blank" rel="noreferrer">原文 ↗</a>`
    : '';
  const when = fmtStamp(meta.published_at) || hhmm(m.created_at);
  return `<div class="insight-row">
    <div class="insight-row-title">${esc(meta.title || m.content)}</div>
    <div class="insight-row-meta">${esc(meta.source_name || '外部消息')} · ${esc(when)}</div>
    ${detail || link ? `<div class="insight-row-actions">${detail}${link}</div>` : ''}
  </div>`;
}

function insightGroupHTML(dayKey, items) {
  const first = rememberInsight(items[0].card || {}, items[0].content);
  const expanded = RV.expanded.has(dayKey);
  const preview = first.title || items[0].content;
  return `<div class="stop insight-group" style="--c:var(--green)">
    <div class="stamp"><b>洞察</b><span>${items.length} 条</span></div>
    <div class="insight-preview">${esc(preview)}${items.length > 1 ? ` 等 ${items.length} 条` : ''}</div>
    <button class="insight-toggle" data-insight-day="${esc(dayKey)}">${expanded ? '收起' : '展开'}</button>
    <div class="insight-items" ${expanded ? '' : 'hidden'}>${items.map(insightRowHTML).join('')}</div>
  </div>`;
}

function renderRecall() {
  const body = $('#recall-body');
  if (!body) return;
  if (!RV.items.length) {
    body.innerHTML = RV.place
      ? `<div class="page-empty">这个地点还没有记录。</div>`
      : `<div class="page-empty">这里还没有站点。<br>回到聊天说一句，线就会从这里长出来。</div>`;
    return;
  }
  // 先按天分组：事件照常成为站点，洞察默认合并成当天的一组（不重要，点开再看）
  const groups = new Map();
  for (const it of RV.items) {
    const key = dateKey(it.created_at);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(it);
  }
  let html = RV.place
    ? `<div class="place-filter">只看 <b>${esc(RV.place)}</b><button class="insight-toggle" data-clear-place>清除</button></div>`
    : '';
  html += `<div class="legend">
    <span style="--c:var(--graphite)"><i></i>事件</span>
    <span style="--c:var(--amber)"><i></i>计划</span>
    <span style="--c:var(--red)"><i></i>心情</span>
    <span style="--c:var(--green)"><i></i>洞察</span>
  </div><div class="route">`;
  for (const [key, list] of groups) {
    const stampIso = list[0].created_at;
    html += `<div class="day-head"><b>${dayLabel(stampIso)}</b><span>${dayStamp(stampIso)}</span></div>`;
    const events = list.filter((x) => x._kind !== 'insight');
    const insights = list.filter((x) => x._kind === 'insight');
    let first = true;
    for (const it of events) {
      html += eventStopHTML(it, first);
      first = false;
    }
    if (insights.length) {
      if (RV.filter === 'insight') {
        // 用户主动筛洞察时不再折叠，直接看每一条
        for (const it of insights) {
          html += insightStopHTML(it, first);
          first = false;
        }
      } else {
        html += insightGroupHTML(key, insights);
      }
    }
  }
  html += '</div>';
  body.innerHTML = html;
}

async function loadRecall() {
  if (RV.filter === 'place' && !RV.place) {
    await loadPlaces();
    return;
  }
  if (RV.loading) return;
  RV.loading = true;
  const body = $('#recall-body');
  if (body) body.innerHTML = `<div class="page-empty">加载中…</div>`;
  try {
    let url = '/api/life/timeline?limit=200';
    if (RV.place) url += `&place=${encodeURIComponent(RV.place)}`;
    const items = await api(url);
    RV.items = items
      .filter((it) => RV.filter !== 'record' || it.item_kind === 'event')
      .filter((it) => RV.filter !== 'insight' || it.item_kind === 'insight')
      .map((it) => ({ ...it, _kind: it.item_kind }));
    renderRecall();
  } catch (e) {
    if (body) body.innerHTML = `<div class="page-empty">加载失败：${esc(e.message)}</div>`;
  } finally {
    RV.loading = false;
  }
}

async function loadPlaces() {
  const body = $('#recall-body');
  if (!body) return;
  body.innerHTML = `<div class="page-empty">加载中…</div>`;
  try {
    const list = await api('/api/life/places');
    if (!list.length) {
      body.innerHTML = `<div class="page-empty">还没有记过地点。<br>在聊天里说一次「去某家店吃了」，这里就会出现。</div>`;
      return;
    }
    body.innerHTML = `<div class="place-list">${list
      .map((p) => {
        const last = p.last_on ? String(p.last_on).slice(0, 10) : '—';
        return `<button class="place-item" data-place="${esc(p.name)}">
          <span class="place-name">${esc(p.name)}</span>
          <span class="place-meta">去过 ${p.count} 次 · 上次 ${esc(last)}${p.rating ? ` · ${p.rating} 分` : ''}</span>
          ${p.review ? `<span class="place-review">${esc(p.review)}</span>` : ''}
        </button>`;
      })
      .join('')}</div>`;
  } catch (e) {
    body.innerHTML = `<div class="page-empty">加载失败：${esc(e.message)}</div>`;
  }
}

async function runSearch() {
  const q = ($('#recall-search')?.value || '').trim();
  RV.search = q;
  if (!q) {
    loadRecall();
    return;
  }
  const body = $('#recall-body');
  if (body) body.innerHTML = `<div class="page-empty">搜索中…</div>`;
  try {
    const rows = await api('/api/life/search?q=' + encodeURIComponent(q));
    renderSearch(rows, q);
  } catch (e) {
    if (body) body.innerHTML = `<div class="page-empty">搜索失败：${esc(e.message)}</div>`;
  }
}

function renderSearch(rows, q) {
  const body = $('#recall-body');
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<div class="page-empty">没有找到「${esc(q)}」。</div>`;
    return;
  }
  const labels = { event: '事件', insight: '洞察', dining: '吃饭', workout: '训练', plan: '计划' };
  body.innerHTML = `<div class="search-head">找到 ${rows.length} 条 · “${esc(q)}”</div>
    <div class="search-result">${rows
      .map(
        (r) => `<button class="search-item" data-search-type="${esc(r.type)}" data-id="${esc(r.id)}"
          data-event-id="${esc(r.event_id || '')}" data-workout-id="${esc(r.workout_id || '')}" data-plan-id="${esc(r.plan_id || '')}">
          <span class="search-kind">${labels[r.type] || '记录'}</span>
          <span class="search-title">${esc(r.title)}</span>
          ${r.subtitle ? `<span class="search-sub">${esc(r.subtitle)}</span>` : ''}
        </button>`
      )
      .join('')}</div>`;
}

async function openExperience(kind, id) {
  try {
    const data = await api(`/api/life/experiences/${kind}/${id}`);
    const item = data.item || {};
    const raws = data.raw_messages || [];
    const visit = data.date_visit;
    const when = item.created_at ? fmtStamp(item.created_at) : '';
    const place = item.place || (visit ? [visit.restaurant_name, visit.branch].filter(Boolean).join(' · ') : '');
    $('#exp-kicker').textContent = item.item_kind === 'insight' ? '外部消息' : '生活记录';
    $('#exp-body').innerHTML = `
      <div class="exp-meta">${esc(when)}${place ? ` · ${esc(place)}` : ''}${item.people ? ` · ${esc(item.people)}` : ''}</div>
      <h2 class="exp-title">${esc(item.title || '')}</h2>
      ${tagChips(item.tags)}
      ${visit ? `<div class="exp-visit">${visit.rating ? `评分 ${visit.rating}` : ''}${visit.occasion ? ` · ${esc(visit.occasion)}` : ''}${visit.dishes && visit.dishes.length ? `<br>菜：${visit.dishes.map((d) => esc(d)).join('、')}` : ''}${visit.review ? `<br>${esc(visit.review)}` : ''}</div>` : ''}
      ${data.workout ? `<div class="insight-section-label">训练</div>${workoutDetailHTML(data.workout)}` : ''}
      <div class="insight-section-label">原话</div>
      ${raws.length
        ? raws.map((m) => `<div class="exp-raw">${esc(m.content)}<div class="when">${whenLabel(m.created_at)}</div></div>`).join('')
        : `<div class="exp-empty">这条记录没有留下原话。</div>`}
      ${item.summary && item.summary !== item.title ? `<div class="insight-section-label">摘要</div><div class="exp-raw">${esc(item.summary)}</div>` : ''}
    `;
    $('#experience').hidden = false;
    $('#exp-body').scrollTop = 0;
  } catch (e) {
    toast('打开失败：' + e.message);
  }
}

function closeExperience() {
  $('#experience').hidden = true;
}

function workoutDetailHTML(w) {
  const exercises = (w.exercises || [])
    .map((ex) => {
      const rows = (ex.sets || [])
        .map((s) => {
          const load = s.weight_kg != null ? `${s.weight_kg} kg` : '自重';
          const reps = s.reps != null ? s.reps : s.duration_sec != null ? `${s.duration_sec}s` : '—';
          return `<div>${s.set_index}</div><div>${load}</div><div>${reps}</div>`;
        })
        .join('');
      const media = ex.media_path
        ? `<img class="workout-anim" src="/media/${esc(ex.media_path)}" alt="${esc(ex.exercise_name)}">`
        : '';
      return `<div class="workout-ex">
        <div class="workout-ex-name">${esc(ex.exercise_name)}</div>
        ${media}
        <div class="sets"><div class="h">组</div><div class="h">重量</div><div class="h">次数</div>${rows}</div>
      </div>`;
    })
    .join('');
  const volume = w.total_volume == null ? 0 : w.total_volume;
  return `<div class="exp-visit">总容量 ${volume} kg · ${(w.exercises || []).length} 个动作</div>${exercises}`;
}

const PLAN_KIND_LABEL = { workout: '训练', meal: '吃饭', outing: '出门', travel: '出行', goal: '目标', todo: '待办' };

async function openPlanDetail(id) {
  try {
    const p = await api('/api/life/plans/' + id);
    const kind = PLAN_KIND_LABEL[p.kind] || '计划';
    const when = p.scheduled_on || p.due_date || '还没定日期';
    let blocks = '';

    if (p.exercises && p.exercises.length) {
      blocks += `<div class="insight-section-label">动作</div>` + p.exercises
        .map((ex) => {
          const media = ex.media_path
            ? `<img class="workout-anim" src="/media/${esc(ex.media_path)}" alt="${esc(ex.name)}">`
            : '';
          return `<div class="workout-ex">
            <div class="workout-ex-name">${esc(ex.name)}</div>
            ${media}
            <div class="option-meta">${esc([ex.body_part, ex.equipment, ex.target].filter(Boolean).join(' · '))}</div>
          </div>`;
        })
        .join('');
    }

    if (p.food) {
      const f = p.food;
      const thumb = f.photo
        ? `<img class="option-thumb" src="${esc(f.photo)}" alt="">`
        : `<span class="option-tile" style="background:${esc(f.accent_a || 'var(--panel)')}">${esc((f.name || '?').slice(0, 1))}</span>`;
      const facts = [f.dist_km ? `${f.dist_km} km` : '', f.price ? `¥${f.price}` : '', f.score ? `${f.score} 分` : '']
        .filter(Boolean)
        .join(' · ');
      blocks += `<div class="insight-section-label">餐厅</div>
        <div class="plan-ref-card">
          <div class="plan-ref-head">${thumb}<span><span class="option-name">${esc(f.name)}</span><span class="option-meta">${esc([f.cuisine, f.branch].filter(Boolean).join(' · '))}</span></span></div>
          ${f.reason ? `<div class="option-reason">${esc(f.reason)}</div>` : ''}
          ${facts ? `<div class="option-facts">${esc(facts)}</div>` : ''}
        </div>`;
    }

    if (p.outing) {
      const o = p.outing;
      blocks += `<div class="insight-section-label">出门</div>
        <div class="plan-ref-card">
          <div class="option-name">${esc(o.name)}</div>
          <div class="option-meta">${esc([o.kind, o.area].filter(Boolean).join(' · '))}</div>
          ${o.note ? `<div class="option-reason">${esc(o.note)}</div>` : ''}
          ${(o.tags || []).length ? `<div class="option-facts">${esc(o.tags.join(' / '))}</div>` : ''}
        </div>`;
    }

    $('#exp-kicker').textContent = p.kind === 'workout' ? '执行 · 训练' : `计划 · ${kind}`;
    const actionText = p.status === 'done'
      ? (p.kind === 'workout' ? '恢复训练' : '恢复未完成')
      : (p.kind === 'workout' ? '完成训练' : '标记完成');
    $('#exp-body').innerHTML = `
      <div class="exp-meta">${esc(String(when))}${p.place ? ` · ${esc(p.place)}` : ''}${p.status === 'done' ? ' · 已完成' : ''}</div>
      <h2 class="exp-title">${esc(p.title)}</h2>
      ${blocks || `<div class="exp-empty">这个计划没有更多详情。</div>`}
      ${p.exercises && p.exercises.length ? `<div class="option-hint">按动作顺序练，演示在上面。</div>` : ''}
      <div class="plan-actions">
        <button class="ob-primary" data-plan-status="${p.status === 'done' ? 'open' : 'done'}" data-plan-id="${esc(p.id)}">
          ${actionText}
        </button>
      </div>
    `;
    $('#experience').hidden = false;
    $('#exp-body').scrollTop = 0;
  } catch (e) {
    toast('打开失败：' + e.message);
  }
}

async function openWorkout(id) {
  try {
    const w = await api('/api/life/workouts/' + id);
    $('#exp-kicker').textContent = '训练';
    $('#exp-body').innerHTML = `
      <div class="exp-meta">${esc(String(w.performed_on || ''))}${w.place ? ` · ${esc(w.place)}` : ''}${w.duration_min ? ` · ${w.duration_min} 分钟` : ''}</div>
      <h2 class="exp-title">${esc(w.title || '训练')}</h2>
      ${workoutDetailHTML(w)}
      ${w.notes ? `<div class="insight-section-label">备注</div><div class="exp-raw">${esc(w.notes)}</div>` : ''}
    `;
    $('#experience').hidden = false;
    $('#exp-body').scrollTop = 0;
  } catch (e) {
    toast('打开失败：' + e.message);
  }
}

/* ---------- 安排：未来 14 天 ---------- */
function planGroups() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const groups = { overdue: [], today: [], week: [], later: [], someday: [], done: [] };
  for (const p of plans) {
    if (p.status === 'done') {
      groups.done.push(p);
      continue;
    }
    const when = p.scheduled_on || p.due_date;
    if (!when) {
      groups.someday.push(p);
      continue;
    }
    const d = new Date(`${String(when).slice(0, 10)}T00:00:00`);
    if (isNaN(d)) {
      groups.someday.push(p);
      continue;
    }
    const diff = Math.round((d - today) / 864e5);
    if (diff < 0) groups.overdue.push(p);
    else if (diff === 0) groups.today.push(p);
    else if (diff <= 7) groups.week.push(p);
    else groups.later.push(p);
  }
  const byDate = (a, b) =>
    String(a.scheduled_on || a.due_date || '9999').localeCompare(
      String(b.scheduled_on || b.due_date || '9999')
    );
  for (const k of Object.keys(groups)) groups[k].sort(byDate);
  groups.done = groups.done
    .sort((a, b) => toDate(b.created_at) - toDate(a.created_at))
    .slice(0, 10);
  return groups;
}

function planItemHTML(p) {
  const done = p.status === 'done';
  const kind = { workout: '训练', meal: '吃饭', outing: '出门', travel: '出行', goal: '目标', todo: '待办' }[p.kind] || '计划';
  const when = p.scheduled_on || p.due_date;
  const dateText = when ? `${String(when).slice(5, 7)} 月 ${String(when).slice(8, 10)} 日` : '还没定日期';
  const place = p.place ? ` · ${esc(p.place)}` : '';
  const hint =
    p.kind === 'workout' && p.meta && (p.meta.exercises || []).length
      ? ' · 点击看动作'
      : '';
  return `<div class="plan-item${done ? ' done' : ''}" data-plan-id="${esc(p.id)}">
    <button class="plan-box" data-plan-toggle="${esc(p.id)}" aria-label="标记完成">
      <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
    </button>
    <button class="plan-body plan-open">
      <span class="plan-title">${esc(p.title)}</span>
      <span class="plan-meta">${kind} · ${dateText}${place}${hint}</span>
    </button>
    <span class="plan-chev" aria-hidden="true">›</span>
  </div>`;
}

function renderPlan() {
  const body = $('#plan-body');
  if (!body) return;
  const groups = planGroups();
  const labels = { overdue: '逾期', today: '今天', week: '本周', later: '更远', someday: '想做，还没定日期', done: '已完成' };
  let html = '';
  for (const key of Object.keys(labels)) {
    const list = groups[key];
    if (!list.length) continue;
    html += `<div class="plan-group"><div class="day-head"><b>${labels[key]}</b><span>${list.length}</span></div>`;
    html += list.map(planItemHTML).join('');
    html += '</div>';
  }
  if (!html) html = `<div class="plan-empty-inline">还没有定下日期的计划。</div>`;
  html += `<div class="plan-tabs" id="plan-tabs">
    ${planTabHTML('workout', '可以练')}
    ${planTabHTML('food', '可以吃')}
    ${planTabHTML('outing', '可以玩')}
  </div><div id="plan-options">${optionListHTML(planTab)}</div>`;
  body.innerHTML = html;
}

function planTabHTML(kind, label) {
  const count = (planOptions[kind] || []).length;
  return `<button class="chip${planTab === kind ? ' on' : ''}" data-ptab="${kind}">${label}<span>${count}</span></button>`;
}

function optionItemHTML(o, kind) {
  if (kind === 'workout') {
    const picked = pickedWorkout.has(o.id);
    const media = o.meta && o.meta.media_path
      ? `<img class="option-thumb" src="/media/${esc(o.meta.media_path)}" alt="">`
      : `<span class="option-tile">${esc((o.name || '?').slice(0, 1))}</span>`;
    return `<div class="option-item option-pick${picked ? ' picked' : ''}" data-option-detail="workout" data-option-id="${esc(o.id)}">
      ${media}
      <span class="option-main">
        <span class="option-name">${esc(o.name)}</span>
        <span class="option-meta">${esc(o.subtitle || '')}</span>
        ${o.meta && o.meta.target ? `<span class="option-facts">${esc(o.meta.target)}</span>` : ''}
      </span>
      <button class="option-check" data-pick-exercise="${esc(o.id)}" data-pick-name="${esc(o.name)}">${picked ? '已选' : '选'}</button>
    </div>`;
  }

  const m = o.meta || {};
  const thumb = m.photo
    ? `<img class="option-thumb" src="${esc(m.photo)}" alt="">`
    : `<span class="option-tile" style="background:${esc(m.accent_a || 'var(--panel)')}">${esc((o.name || '?').slice(0, 1))}</span>`;
  const facts = kind === 'food'
    ? [m.dist_km ? `${m.dist_km} km` : '', m.price ? `¥${m.price}` : '', m.score ? `${m.score} 分` : '']
        .filter(Boolean)
        .join(' · ')
    : esc(m.note || '');
  return `<div class="option-item option-rich" data-option-detail="${kind}" data-option-id="${esc(o.id)}">
    ${thumb}
    <span class="option-main">
      <span class="option-name">${esc(o.name)}</span>
      <span class="option-meta">${esc(o.subtitle || '')}</span>
      ${m.reason ? `<span class="option-reason">${esc(m.reason)}</span>` : ''}
      ${facts ? `<span class="option-facts">${esc(facts)}</span>` : ''}
    </span>
    <button class="insight-more option-arrange" data-arrange="${kind === 'food' ? 'meal' : 'outing'}" data-id="${esc(o.id)}" data-name="${esc(o.name)}">安排</button>
  </div>`;
}

function optionListHTML(kind) {
  const items = planOptions[kind] || [];
  if (!items.length) return `<div class="page-empty">这一类还没有候选。</div>`;
  const meta = {
    workout: { hint: '动作库 · 选几个动作，组成一次训练', limit: 8 },
    food: { hint: '约会菜单 · 选一家安排到某天' },
    outing: { hint: '杭州 · 选一个安排到某天' },
  }[kind];
  const head = meta.limit ? items.slice(0, meta.limit) : items;
  const rest = meta.limit ? items.slice(meta.limit) : [];
  const pickedBar = kind === 'workout'
    ? `<div class="arrange-bar"><span>已选 ${pickedWorkout.size} 个动作</span><button class="insight-more" data-arrange-workout ${pickedWorkout.size ? '' : 'disabled'}>安排这次训练</button></div>`
    : '';
  return `<div class="option-hint">${meta.hint}</div>
    <div class="option-list">${head.map((o) => optionItemHTML(o, kind)).join('')}${rest.length ? `<div class="option-rest" hidden>${rest.map((o) => optionItemHTML(o, kind)).join('')}</div>` : ''}</div>
    ${rest.length ? `<button class="insight-toggle option-toggle" data-option-toggle data-option-count="${items.length}">展开全部 ${items.length} 个</button>` : ''}
    ${pickedBar}`;
}

function renderOptionList() {
  const el = $('#plan-options');
  if (el) el.innerHTML = optionListHTML(planTab);
}

function localDateISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function optionSchedulePayload(kind, option) {
  const meta = (option && option.meta) || {};
  if (kind === 'workout') {
    return {
      kind: 'workout',
      title: `训练：${option.name}`,
      meta: {
        exercises: [
          {
            id: option.id,
            name: option.name,
            body_part: meta.body_part,
            equipment: meta.equipment,
            media_path: meta.media_path,
          },
        ],
      },
      ref_type: null,
      ref_id: null,
      place: '',
    };
  }
  if (kind === 'food') {
    return {
      kind: 'meal',
      title: `去吃${option.name}`,
      ref_type: 'date_menu',
      ref_id: option.id,
      place: option.name,
      meta: {
        reason: meta.reason,
        photo: meta.photo,
        accent_a: meta.accent_a,
        cuisine: option.subtitle,
      },
    };
  }
  return {
    kind: 'outing',
    title: `去${option.name}`,
    ref_type: 'outing_spot',
    ref_id: option.id,
    place: option.name,
    meta: { area: meta.area, kind: meta.kind, note: meta.note },
  };
}

function openOptionDetail(kind, id) {
  const option = (planOptions[kind] || []).find((x) => x.id === id);
  if (!option) return;
  const meta = option.meta || {};

  if (kind === 'workout') {
    const picked = pickedWorkout.has(id);
    const media = meta.media_path
      ? `<img class="workout-anim" src="/media/${esc(meta.media_path)}" alt="${esc(option.name)}">`
      : '';
    $('#exp-kicker').textContent = '动作';
    $('#exp-body').innerHTML = `
      <div class="exp-meta">${esc(option.subtitle || '')}${meta.target ? ` · ${esc(meta.target)}` : ''}</div>
      <h2 class="exp-title">${esc(option.name)}</h2>
      ${media}
      <div class="option-facts">${esc([meta.body_part, meta.equipment, meta.target].filter(Boolean).join(' · '))}</div>
      <div class="plan-actions">
        <button class="ob-primary" data-detail-pick="${esc(id)}">${picked ? '移出本次训练' : '加入本次训练'}</button>
        <button class="insight-more" data-detail-arrange="workout" data-id="${esc(id)}">单独安排</button>
      </div>`;
  } else if (kind === 'food') {
    const thumb = meta.photo
      ? `<img class="option-thumb" src="${esc(meta.photo)}" alt="">`
      : `<span class="option-tile" style="background:${esc(meta.accent_a || 'var(--panel)')}">${esc((option.name || '?').slice(0, 1))}</span>`;
    const facts = [meta.dist_km ? `${meta.dist_km} km` : '', meta.price ? `¥${meta.price}` : '', meta.score ? `${meta.score} 分` : '']
      .filter(Boolean)
      .join(' · ');
    $('#exp-kicker').textContent = '餐厅';
    $('#exp-body').innerHTML = `
      <div class="plan-ref-head">${thumb}<span><span class="option-name">${esc(option.name)}</span><span class="option-meta">${esc(option.subtitle || '')}</span></span></div>
      ${meta.reason ? `<div class="option-reason">${esc(meta.reason)}</div>` : ''}
      ${facts ? `<div class="option-facts">${esc(facts)}</div>` : ''}
      <div class="plan-actions">
        <button class="ob-primary" data-detail-arrange="food" data-id="${esc(id)}">安排到某天</button>
      </div>`;
  } else {
    $('#exp-kicker').textContent = '出门';
    $('#exp-body').innerHTML = `
      <div class="exp-meta">${esc(option.subtitle || '')}</div>
      <h2 class="exp-title">${esc(option.name)}</h2>
      ${meta.note ? `<div class="option-reason">${esc(meta.note)}</div>` : ''}
      ${(meta.tags || []).length ? `<div class="option-facts">${esc(meta.tags.join(' / '))}</div>` : ''}
      <div class="plan-actions">
        <button class="ob-primary" data-detail-arrange="outing" data-id="${esc(id)}">安排到某天</button>
      </div>`;
  }

  $('#experience').hidden = false;
  $('#exp-body').scrollTop = 0;
}

function openSchedule(payload) {
  pendingPlan = payload;
  $('#schedule-title').textContent = payload.title || '安排到哪天？';
  const d = new Date();
  $('#schedule-date').value = localDateISO(d);
  $('#schedule').hidden = false;
}

function closeSchedule() {
  $('#schedule').hidden = true;
  pendingPlan = null;
}

async function confirmSchedule() {
  const date = $('#schedule-date').value;
  if (!pendingPlan) return;
  if (!date) return toast('先选一天');
  try {
    await api('/api/life/plans', {
      method: 'POST',
      body: JSON.stringify({ ...pendingPlan, scheduled_on: date, source: 'recall' }),
    });
    closeSchedule();
    pickedWorkout.clear();
    await loadPlan();
    toast('已安排');
  } catch (e) {
    toast('安排失败：' + e.message);
  }
}

async function loadPlan() {
  const body = $('#plan-body');
  try {
    plans = await api('/api/plans?include_done=true');
    renderBadge();
    try {
      const [workout, food, outing] = await Promise.all([
        api('/api/life/options?kind=workout'),
        api('/api/life/options?kind=food'),
        api('/api/life/options?kind=outing'),
      ]);
      planOptions = { workout, food, outing };
    } catch {
      planOptions = { workout: [], food: [], outing: [] };
    }
    renderPlan();
  } catch (e) {
    if (body) body.innerHTML = `<div class="page-empty">加载失败：${esc(e.message)}</div>`;
  }
}

/* ---------- 视图切换 ---------- */
function syncView() {
  const h = location.hash;
  const isRecall = h === '#/recall';
  const isPlan = h === '#/plan';
  const recall = $('#recall-view');
  const plan = $('#plan-view');
  if (recall) recall.hidden = !isRecall;
  if (plan) plan.hidden = !isPlan;
  if (isRecall) {
    updateRecallSub();
    loadRecall();
  }
  if (isPlan) loadPlan();
}

function closeView() {
  if (location.hash === '#/recall' || location.hash === '#/plan') {
    location.hash = '#/today';
  } else {
    syncView();
  }
}

/* ---------- 洞察详情（总结 / 详情 / 原文） ---------- */
function openInsight(id) {
  const m = insightCards.get(id);
  if (!m) {
    toast('这条消息没有详情');
    return;
  }
  $('#insight-title').textContent = m.title || '外部消息';
  const bits = [m.source_name, m.category === 'finance' ? '金融' : m.category === 'tech' ? '科技' : m.category, fmtStamp(m.published_at)].filter(Boolean);
  $('#insight-meta').textContent = bits.join(' · ');
  const detail = m.detail || '';
  $('#insight-summary').textContent = m.summary || detail || '（这条消息没有摘要）';
  const wrap = $('#insight-detail-wrap');
  wrap.hidden = !detail;
  $('#insight-detail').textContent = detail;
  $('#insight-tags').innerHTML = tagChips(m.tags);
  const a = $('#insight-link');
  if (m.source_url) {
    a.href = m.source_url;
    a.hidden = false;
  } else {
    a.hidden = true;
    a.removeAttribute('href');
  }
  $('#insight-modal').hidden = false;
  $('#insight-body').scrollTop = 0;
}

function closeInsight() {
  $('#insight-modal').hidden = true;
}

/* ---------- 加载 ---------- */
async function loadAll() {
  const [msgs, pl] = await Promise.all([
    api('/api/messages?limit=60'),
    api('/api/plans?include_done=true'),
  ]);
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
    `<div class="row sec" id="pending"><div class="bubble quiet thinking">正在想</div></div>`
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
    if (!$('#plan-view')?.hidden) renderPlan();
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

/* ---------- 画像初始化：10 题 → 可审阅预览 → 确认 ---------- */
const OB = { questions: [], answers: {}, choice: {}, step: 'form', sections: {} };

function obFilled() {
  const text = Object.keys(OB.answers).filter((k) => String(OB.answers[k] || '').trim()).length;
  const picked = Object.keys(OB.choice).filter((k) => OB.choice[k]).length;
  return text + picked;
}

function obFormHTML() {
  return OB.questions
    .map((q) => {
      const hint = q.hint ? `<div class="q-hint">${esc(q.hint)}</div>` : '';
      const choices = (q.choices || []).length
        ? `<div class="q-choices" data-q="${esc(q.id)}">${q.choices
            .map(
              (c) =>
                `<button type="button" class="q-choice${OB.choice[q.id] === c ? ' on' : ''}" data-c="${esc(c)}">${esc(c)}</button>`
            )
            .join('')}</div>`
        : '';
      const ta =
        q.kind === 'text' || q.kind === 'choice_text'
          ? `<textarea rows="2" data-t="${esc(q.id)}" placeholder="${
              q.kind === 'choice_text' ? '补一句：行业 / 在做的事' : '写一句就行'
            }">${esc(OB.answers[q.id] || '')}</textarea>`
          : '';
      return `<div class="q"><label>${esc(q.question)}</label>${hint}${choices}${ta}</div>`;
    })
    .join('');
}

function obPreviewHTML() {
  const labels = { identity: '身份', style: '沟通与风格', avoid: '回避项', current: '当前进行中', insight: '结论级洞察' };
  const cards = Object.keys(labels)
    .filter((k) => String(OB.sections[k] || '').trim())
    .map((k) => `<div class="ob-card"><b>${labels[k]}</b><p>${esc(OB.sections[k])}</p></div>`)
    .join('');
  return (cards || `<div class="ob-empty">还看不出什么 —— 回去多填两题？</div>`) +
    `<div class="ob-note">这是它现在对你的理解，之后每次对话都会带上它（画像 ≤1500 字，只挑关于「你是谁」的结论）。确认后它会随时间自己更新，你也能在「回看」里看到它推给你的变化。</div>`;
}

function obRender() {
  $('#ob-body').innerHTML = OB.step === 'form' ? obFormHTML() : obPreviewHTML();
  const filled = obFilled();
  if (OB.step === 'form') {
    $('#ob-progress').textContent = `已填 ${filled} / ${OB.questions.length}`;
    $('#ob-back').hidden = true;
    $('#ob-next').hidden = false;
    $('#ob-next').textContent = '看看它理解的你';
    $('#ob-next').disabled = filled === 0;
    $('#ob-sub').textContent = '10 个问题，答完它就一直记得';
  } else {
    $('#ob-progress').textContent = '确认之后，这一页就收起来了';
    $('#ob-back').hidden = false;
    $('#ob-next').hidden = false;
    $('#ob-next').textContent = '确认，就这样';
    $('#ob-next').disabled = false;
    $('#ob-sub').textContent = '这是它现在对你的理解';
  }
}

async function openOnboard() {
  try {
    const data = await api('/api/onboarding/questions');
    OB.questions = data.questions || [];
    OB.step = 'form';
    OB.sections = {};
    $('#onboard').hidden = false;
    obRender();
  } catch (e) {
    toast('拿不到问卷：' + e.message);
  }
}

function closeOnboard() {
  $('#onboard').hidden = true;
}

// 选择题 + 填空合成一份答案：choice_text 是「选项，补充」
function obComposeAnswers() {
  const out = {};
  for (const q of OB.questions) {
    const choice = OB.choice[q.id] || '';
    const text = String(OB.answers[q.id] || '').trim();
    if (q.kind === 'choice_text') {
      const merged = [choice, text].filter(Boolean).join('，');
      if (merged) out[q.id] = merged;
    } else if (q.kind === 'choice') {
      if (choice) out[q.id] = choice;
    } else if (text) {
      out[q.id] = text;
    }
  }
  return out;
}

async function obNext() {
  const btn = $('#ob-next');
  btn.disabled = true;

  if (OB.step === 'form') {
    try {
      const res = await api('/api/onboarding/preview', {
        method: 'POST',
        body: JSON.stringify({ answers: obComposeAnswers() }),
      });
      OB.sections = res.sections || {};
      OB.step = 'preview';
      obRender();
    } catch (e) {
      toast('预览失败：' + e.message);
      btn.disabled = false;
    }
    return;
  }

  try {
    await api('/api/onboarding/apply', {
      method: 'POST',
      body: JSON.stringify({ answers: obComposeAnswers() }),
    });
    closeOnboard();
    $('#profile-init').hidden = true; // 建过之后入口就消失
    toast('画像已建立，它现在认识你了', 2600);
  } catch (e) {
    toast('保存失败：' + e.message);
    btn.disabled = false;
  }
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
  location.hash = '#/plan';
});

/* 回看 / 安排 */
on('#open-recall', 'click', () => { location.hash = '#/recall'; });
on('#open-plan', 'click', () => { location.hash = '#/plan'; });
on('#recall-close', 'click', closeView);
on('#plan-close', 'click', closeView);
on('#recall-filters', 'click', (e) => {
  const b = e.target.closest('button[data-rf]');
  if (!b || b.disabled) return;
  RV.filter = b.dataset.rf;
  RV.place = '';
  RV.search = '';
  if ($('#recall-search')) $('#recall-search').value = '';
  RV.expanded.clear();
  [...$('#recall-filters').children].forEach((x) => x.classList.toggle('on', x === b));
  if (RV.filter === 'place') loadPlaces();
  else loadRecall();
});
on('#recall-search', 'keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    runSearch();
  }
  if (e.key === 'Escape') {
    e.target.value = '';
    RV.search = '';
    loadRecall();
  }
});
on('#recall-search', 'search', (e) => {
  if (!e.target.value.trim()) {
    RV.search = '';
    loadRecall();
  }
});
on('#recall-body', 'click', (e) => {
  const hit = e.target.closest('[data-search-type]');
  if (hit) {
    const type = hit.dataset.searchType;
    if (type === 'workout') {
      openWorkout(hit.dataset.workoutId);
      return;
    }
    if (type === 'plan') {
      location.hash = '#/plan';
      return;
    }
    if (hit.dataset.eventId) {
      openExperience(type === 'insight' ? 'insight' : 'event', hit.dataset.eventId);
      return;
    }
    return;
  }
  const clear = e.target.closest('[data-clear-place]');
  if (clear) {
    RV.place = '';
    RV.filter = 'all';
    [...$('#recall-filters').children].forEach((x) => x.classList.toggle('on', x.dataset.rf === 'all'));
    loadRecall();
    return;
  }
  const placeBtn = e.target.closest('[data-place]');
  if (placeBtn) {
    RV.place = placeBtn.dataset.place;
    RV.filter = 'place';
    loadRecall();
    return;
  }
  const btn = e.target.closest('[data-insight-day]');
  if (!btn) return;
  const group = btn.closest('.insight-group');
  const box = group?.querySelector('.insight-items');
  if (!box) return;
  box.hidden = !box.hidden;
  btn.textContent = box.hidden ? '展开' : '收起';
  const key = btn.dataset.insightDay;
  if (box.hidden) RV.expanded.delete(key);
  else RV.expanded.add(key);
});
on('#plan-body', 'click', (e) => {
  const tab = e.target.closest('[data-ptab]');
  if (tab) {
    planTab = tab.dataset.ptab;
    [...$('#plan-tabs').children].forEach((x) => x.classList.toggle('on', x === tab));
    renderOptionList();
    return;
  }
  const pick = e.target.closest('[data-pick-exercise]');
  if (pick) {
    const id = pick.dataset.pickExercise;
    if (pickedWorkout.has(id)) {
      pickedWorkout.delete(id);
    } else {
      const option =
        (planOptions.workout || []).find((x) => x.id === id) ||
        { id, name: pick.dataset.pickName, meta: {} };
      pickedWorkout.set(id, option);
    }
    renderOptionList();
    return;
  }
  const arrangeWorkout = e.target.closest('[data-arrange-workout]');
  if (arrangeWorkout) {
    if (!pickedWorkout.size) return;
    const options = [...pickedWorkout.values()];
    openSchedule({
      kind: 'workout',
      title: `训练：${options.map((o) => o.name).join('、')}`,
      meta: {
        exercises: options.map((o) => ({
          id: o.id,
          name: o.name,
          body_part: o.meta && o.meta.body_part,
          equipment: o.meta && o.meta.equipment,
          media_path: o.meta && o.meta.media_path,
        })),
      },
      ref_type: null,
      ref_id: null,
      place: '',
    });
    return;
  }
  const arrange = e.target.closest('[data-arrange]');
  if (arrange) {
    const kind = arrange.dataset.arrange === 'meal' ? 'food' : 'outing';
    const option = (planOptions[kind] || []).find((x) => x.id === arrange.dataset.id);
    if (option) openSchedule(optionSchedulePayload(kind, option));
    return;
  }
  const detail = e.target.closest('[data-option-detail]');
  if (detail) {
    openOptionDetail(detail.dataset.optionDetail, detail.dataset.optionId);
    return;
  }
  const planItem = e.target.closest('.plan-item[data-plan-id]');
  if (planItem) {
    if (e.target.closest('[data-plan-toggle]')) togglePlan(planItem.dataset.planId);
    else openPlanDetail(planItem.dataset.planId);
    return;
  }
  const toggle = e.target.closest('[data-option-toggle]');
  if (toggle) {
    // tab 改版后按钮的父容器是 #plan-options，不再有 .plan-group 包裹
    const rest =
      toggle.parentElement?.querySelector('.option-rest') ||
      toggle.closest('#plan-options')?.querySelector('.option-rest');
    if (!rest) return;
    rest.hidden = !rest.hidden;
    toggle.textContent = rest.hidden ? `展开全部 ${toggle.dataset.optionCount} 个` : '收起';
    return;
  }
  const row = e.target.closest('[data-plan]');
  if (row) togglePlan(row.dataset.plan);
});

// 详情按钮在窗口流和回看里都有，统一用事件委托
document.addEventListener('click', (e) => {
  const wbtn = e.target.closest('[data-workout]');
  if (wbtn && wbtn.dataset.workout) {
    e.preventDefault();
    openWorkout(wbtn.dataset.workout);
    return;
  }
  const ev = e.target.closest('[data-event]');
  if (ev && ev.dataset.event) {
    e.preventDefault();
    openExperience('event', ev.dataset.event);
    return;
  }
  const btn = e.target.closest('[data-insight]');
  if (!btn || !btn.dataset.insight) return;
  e.preventDefault();
  openInsight(btn.dataset.insight);
});
on('#insight-close', 'click', closeInsight);
on('#insight-modal', 'click', (e) => {
  if (e.target.id === 'insight-modal') closeInsight();
});
on('#exp-close', 'click', closeExperience);
on('#experience', 'click', (e) => {
  if (e.target.id === 'experience') closeExperience();
});
on('#exp-body', 'click', async (e) => {
  const pickBtn = e.target.closest('[data-detail-pick]');
  if (pickBtn) {
    const id = pickBtn.dataset.detailPick;
    if (pickedWorkout.has(id)) pickedWorkout.delete(id);
    else {
      const option = (planOptions.workout || []).find((x) => x.id === id);
      if (option) pickedWorkout.set(id, option);
    }
    renderOptionList();
    openOptionDetail('workout', id);
    return;
  }
  const arrangeBtn = e.target.closest('[data-detail-arrange]');
  if (arrangeBtn) {
    const kind = arrangeBtn.dataset.detailArrange;
    const pool = kind === 'food' ? planOptions.food : kind === 'outing' ? planOptions.outing : planOptions.workout;
    const option = (pool || []).find((x) => x.id === arrangeBtn.dataset.id);
    if (!option) return;
    closeExperience();
    openSchedule(optionSchedulePayload(kind, option));
    return;
  }

  const btn = e.target.closest('[data-plan-status]');
  if (!btn) return;
  try {
    await api('/api/life/plans/' + btn.dataset.planId, {
      method: 'PATCH',
      body: JSON.stringify({ status: btn.dataset.planStatus }),
    });
    closeExperience();
    await loadPlan();
    toast('计划已更新');
  } catch (err) {
    toast('更新失败：' + err.message);
  }
});
on('#schedule-close', 'click', closeSchedule);
on('#schedule-confirm', 'click', confirmSchedule);
on('#schedule', 'click', (e) => {
  if (e.target.id === 'schedule') closeSchedule();
});
on('#schedule-quick', 'click', (e) => {
  const btn = e.target.closest('[data-day-offset]');
  if (!btn) return;
  const d = new Date();
  d.setDate(d.getDate() + Number(btn.dataset.dayOffset));
  $('#schedule-date').value = localDateISO(d);
});

/* 画像初始化 */
on('#profile-init', 'click', openOnboard);
on('#ob-close', 'click', closeOnboard);
on('#ob-next', 'click', obNext);
on('#ob-back', 'click', () => {
  OB.step = 'form';
  obRender();
});
on('#onboard', 'click', (e) => {
  if (e.target.id === 'onboard') closeOnboard();
});
on('#ob-body', 'click', (e) => {
  const chip = e.target.closest('.q-choice');
  if (!chip) return;
  const qid = chip.parentElement.dataset.q;
  OB.choice[qid] = OB.choice[qid] === chip.dataset.c ? '' : chip.dataset.c; // 再点一次取消
  obRender();
});
on('#ob-body', 'input', (e) => {
  const ta = e.target.closest('textarea[data-t]');
  if (!ta) return;
  OB.answers[ta.dataset.t] = ta.value;
  if (OB.step !== 'form') return;
  $('#ob-progress').textContent = `已填 ${obFilled()} / ${OB.questions.length}`;
  $('#ob-next').disabled = obFilled() === 0;
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!$('#schedule').hidden) return closeSchedule();
  if (!$('#experience').hidden) return closeExperience();
  if (!$('#onboard').hidden) return closeOnboard();
  if (!$('#insight-modal').hidden) return closeInsight();
  if (!$('#recall-view').hidden || !$('#plan-view').hidden) closeView();
});

window.addEventListener('hashchange', syncView);

/* ---------- 启动 ---------- */
(function init() {
  const d = new Date();
  $('#today').textContent = `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
  loadAll().catch((e) => {
    stream.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  });
  // 画像还没建立时露出入口；建过之后这个按钮就消失了
  api('/api/onboarding/questions')
    .then((data) => {
      const btn = $('#profile-init');
      if (btn) btn.hidden = !!data.answered;
    })
    .catch((e) => console.warn('[selfsec] 取不到问卷状态，画像入口保持隐藏：', e.message));
  if (location.hash === '#/recall' || location.hash === '#/plan') syncView();
})();
