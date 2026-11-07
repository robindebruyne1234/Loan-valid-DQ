/* The playground page. Plain JavaScript, no framework, no build step.
 *
 * A thin client over /api/play/*: every answer comes from the live pipeline
 * (src/playground.py), and every value shown is escaped before it reaches
 * the DOM — including Claude's SQL and rows, which are untrusted text.
 */
'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') return v.toLocaleString('en-GB', { maximumFractionDigits: 4 });
  return String(v);
};
const usd = (n) => `USD ${Number(n || 0).toFixed(4)}`;
const json = (o) => JSON.stringify(o, null, 2);

const S = { setup: null, last: null, job: null, poll: null, openRow: null };

async function api(path, body) {
  const opts = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) } : {};
  try {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({ error: 'bad response' }));
    return { ok: res.ok, status: res.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: { error: 'the server is not reachable — is `make play` still running?' } };
  }
}

function table(rows, cols, max = 50) {
  if (!rows || !rows.length) return '<p class="muted">No rows.</p>';
  const columns = cols || Object.keys(rows[0]);
  return `<div class="scroll"><table><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${
    rows.slice(0, max).map((r) => `<tr>${columns.map((c) => `<td${typeof r[c] === 'number' ? ' class="num"' : ''}>${esc(fmt(r[c]))}</td>`).join('')}</tr>`).join('')
  }</tbody></table></div>`;
}

function card(title, body, cls = '') {
  return `<div class="card ${cls}"><h3>${esc(title)}</h3>${body}</div>`;
}

/* ---------- header, tabs, setup ------------------------------------- */

function banner(html, bad) {
  $('#banner').innerHTML = html ? `<div class="banner${bad ? ' bad' : ''}">${html}</div>` : '';
}

async function loadHealth() {
  const { ok, status, data } = await api('/api/play/health');
  if (status === 404) {
    banner('The playground is off on this server. Start it with <code>make play</code> '
      + '(or <code>python -m src.webapp --playground</code>) and reload.', true);
    $('#health').textContent = 'playground off';
    $('#health').className = 'pill bad';
    return false;
  }
  if (!ok || !data.database) {
    banner(`The pipeline is not built in this database: ${esc(data.detail || data.error || '')}. `
      + 'Run <code>make build</code>, then reload.', true);
    $('#health').textContent = 'database: not built';
    $('#health').className = 'pill bad';
    return false;
  }
  $('#health').textContent = `${fmt(data.clients)} clients · ${fmt(data.loans)} loans · ${data.policies} RLS policies`;
  $('#health').className = 'pill ok';
  $('#cli').textContent = data.claude_cli ? `claude ${data.claude_cli.split(' ')[0]}` : 'claude CLI not found';
  $('#cli').className = `pill ${data.claude_cli ? 'ok' : 'bad'}`;
  if (!data.claude_cli) {
    banner('The <code>claude</code> CLI is not on PATH, so the Claude models cannot be asked. '
      + 'Install Claude Code and log in (<code>claude</code>), or set <code>LLM_API_KEY</code>. '
      + 'The guard lab works without a model.');
  }
  return true;
}

function fillSelects() {
  const { personas, models, default_model: def } = S.setup;
  const personaOpts = personas.map((p) => `<option value="${esc(p.role)}">${esc(p.name)} · ${esc(p.kind)} (${esc(p.role)})</option>`).join('');
  $('#role').innerHTML = personaOpts;
  $('#grole').innerHTML = personaOpts;
  const modelOpts = models.map((m) => `<option value="${esc(m.key)}"${m.key === def ? ' selected' : ''}${m.available ? '' : ' disabled'}>${esc(m.label)}${m.available ? '' : ' — not available'}</option>`).join('');
  $$('.modelsel').forEach((el) => { el.innerHTML = modelOpts; });
}

function fillExamples() {
  const groups = Object.entries(S.setup.examples).map(([name, qs]) =>
    `<div class="chips"><span class="grp">${esc(name)}</span>${qs.map((q) =>
      `<button class="chip${name === 'Attacks' ? ' attack' : ''}" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div>`);
  const brief = `<div class="chips"><span class="grp">The brief</span>${S.setup.suites.core.map((q) =>
    `<button class="chip" data-q="${esc(q.question)}" title="${esc(q.question)}">${esc(q.id)}</button>`).join('')}</div>`;
  $('#examples').innerHTML = brief + groups.join('');
  $$('#examples .chip').forEach((b) => b.addEventListener('click', () => { $('#q').value = b.dataset.q; $('#q').focus(); }));

  $('#presets').innerHTML = `<details open><summary>Start from a preset</summary>${S.setup.guard_presets.map((p, i) =>
    `<div class="preset"><button class="chip${/refuse/i.test(p.expect) ? ' attack' : ''}" data-i="${i}">${esc(p.label)}</button>`
    + `<span class="muted">${esc(p.expect)}</span></div>`).join('')}</details>`;
  $$('#presets .chip').forEach((b) => b.addEventListener('click', () => {
    $('#sql').value = S.setup.guard_presets[Number(b.dataset.i)].sql;
  }));
}

function switchTab(name) {
  $$('.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  $$('.tab').forEach((t) => { t.hidden = t.id !== `tab-${name}`; });
  if (name === 'test') renderTests();
  if (name === 'pack') loadPack();
}

/* ---------- ask ------------------------------------------------------ */

// Order of the checks inside the pipeline, and how the page names them.
const STAGES = [
  ['llm', 'Claude', 'answered'], ['parse', 'Reply', 'one JSON object'],
  ['guard', 'Guard', 'shape: one read-only SELECT on ai'], ['ir', 'Intent', 'the IR is well formed'],
  ['sql', 'Meaning', 'SQL matches the IR (D029)'], ['plan', 'Plan', 'no fan-out joins'],
  ['execute', 'Rows', 'run as the persona, under RLS'], ['recompute', 'Recompute', 'metric re-derived from the IR'],
  ['done', 'Answer', 'shown'],
];

function stageStrip(stage) {
  const at = STAGES.findIndex(([id]) => id === stage);
  return `<div class="stages">${STAGES.map(([id, name, what], i) => {
    let cls = 'skip';
    if (stage === 'done' || i < at) cls = 'pass';
    else if (i === at) cls = 'fail';
    return `<div class="stage ${cls}"><b>${esc(name)}</b>${esc(what)}</div>`;
  }).join('')}</div>`;
}

function personaName(role) {
  const p = (S.setup.personas || []).find((x) => x.role === role);
  return p ? `${p.name} (${role})` : role;
}

function renderAnswer(r) {
  const u = r.usage || {};
  const meta = `<div class="meta"><span>as <b>${esc(personaName(r.as_role))}</b></span>`
    + `<span>model <b>${esc(r.model)}</b></span><span><b>${esc(r.elapsed_sec)}</b> s</span>`
    + `<span><b>${esc(usd(u.cost_usd))}</b></span>`
    + `<span><b>${fmt(u.input_tokens)}</b> tokens in · <b>${fmt(u.output_tokens)}</b> out</span>`
    + `<span>attempts <b>${(r.attempts || []).length}</b></span></div>`;
  const tries = (r.attempts || []).length > 1
    ? `<p class="muted">Attempt 1 was refused (${esc(r.attempts[0].stage)}: ${esc(r.attempts[0].error)}); the reason went back to Claude, which corrected itself.</p>` : '';

  let html = stageStrip(r.stage) + meta + tries;
  if (r.stage === 'done') {
    html += card(`Answer as ${personaName(r.as_role)} — ${fmt(r.row_count)} row(s)`, table(r.rows), 'answer');
  } else {
    html += card(`Refused at "${r.stage}"`, `<p>${esc(r.error)}</p><p class="muted">Nothing invented: a refused answer shows no rows.</p>`, 'refused');
  }
  if (r.sql) {
    const rewritten = r.guard && r.guard.rewritten_sql && r.guard.rewritten_sql !== r.sql
      ? `<p class="muted">As executed (the guard's rewrite):</p><pre class="sql">${esc(r.guard.rewritten_sql)}</pre>` : '';
    html += `<div class="grid2">${card('SQL Claude wrote', `<pre class="sql">${esc(r.sql)}</pre>${rewritten}`)}`
      + `${card('What Claude says it computes (IR)', `<pre class="sql">${esc(json(r.ir))}</pre>`)}</div>`;
    html += `<div class="row"><button id="everyBtn" class="ghost">Run this SQL as every persona</button>`
      + `<span class="muted">One statement, eight logins: watch the policies decide.</span></div><div id="everyOut"></div>`;
  }
  const v = r.verification || {};
  html += `<details><summary>Verification details (${(v.checks || []).length} checks passed${(v.findings || []).length ? `, ${v.findings.length} finding(s)` : ''})</summary>`
    + `${(v.findings || []).length ? `<p class="err">${v.findings.map(esc).join('<br>')}</p>` : ''}`
    + `<ul>${(v.checks || []).map((c) => `<li class="muted">${esc(c)}</li>`).join('')}</ul></details>`;
  if (r.model_explanation) html += `<details><summary>Claude's explanation</summary><p>${esc(r.model_explanation)}</p></details>`;
  html += `<details><summary>Raw reply</summary><pre class="sql">${esc(r.raw_response)}</pre></details>`;
  $('#askOut').innerHTML = html;
  const every = $('#everyBtn');
  if (every) every.addEventListener('click', () => runEveryone(r.sql, r.ir, r.question, '#everyOut', every));
}

async function ask() {
  const question = $('#q').value.trim();
  if (question.length < 3) { $('#askState').textContent = 'Type a question first.'; return; }
  $('#askBtn').disabled = true;
  $('#askState').innerHTML = '<span class="spin"></span> Claude is thinking — usually 10–40 s…';
  $('#askOut').innerHTML = '';
  const { ok, data } = await api('/api/play/ask', { question, role: $('#role').value, model: $('#model').value });
  $('#askBtn').disabled = false;
  $('#askState').textContent = '';
  if (!ok) { $('#askOut').innerHTML = card('Error', `<p class="err">${esc(data.error)} ${esc(data.detail || '')}</p>`, 'refused'); return; }
  S.last = data;
  renderAnswer(data);
}

async function runEveryone(sql, ir, question, target, btn) {
  if (btn) btn.disabled = true;
  $(target).innerHTML = '<p class="muted"><span class="spin"></span> Logging in as each persona…</p>';
  const { ok, data } = await api('/api/play/everyone', { sql, ir, question });
  if (btn) btn.disabled = false;
  if (!ok) { $(target).innerHTML = `<p class="err">${esc(data.error)}</p>`; return; }
  if (!data.guard.allowed) { $(target).innerHTML = card('Refused by the guard', `<p>${esc(data.guard.reason)}</p>`, 'refused'); return; }
  const rows = data.runs.map((r) => ({
    persona: `${r.name} · ${r.kind}`, role: r.role,
    result: r.ok ? `${r.row_count} row(s)` : `refused at ${r.stage}`,
    'first row': r.ok ? (r.rows[0] ? Object.entries(r.rows[0]).map(([k, v]) => `${k}=${fmt(v)}`).join(' · ') : '—') : r.error,
  }));
  $(target).innerHTML = card('Same SQL, every persona', table(rows));
}

/* ---------- test the questions --------------------------------------- */

function renderTests() {
  const suite = $('#suite').value;
  const qs = S.setup.suites[suite] || [];
  const byId = {};
  const job = S.job && S.job.suite === suite ? S.job : null;
  if (job) job.results.forEach((r) => { byId[r.id] = r; });
  const running = job && job.status === 'running';
  const rows = qs.map((q) => {
    const r = byId[q.id];
    const v = r ? r.verdict : (running && job.current === q.id ? 'running' : '');
    return `<tr data-id="${esc(q.id)}" class="${S.openRow === q.id ? 'open' : ''}"><td><b>${esc(q.id)}</b></td><td>${esc(q.question)}</td>`
      + `<td>${v ? `<span class="verdict ${esc(v)}">${esc(v)}</span>` : ''}</td>`
      + `<td class="num">${r && r.expected !== undefined ? `${r.matched}/${r.expected}` : ''}</td>`
      + `<td class="num">${r && r.attempts ? r.attempts : ''}</td><td class="num">${r && r.seconds ? r.seconds : ''}</td>`
      + `<td class="num">${r && r.cost_usd !== undefined ? Number(r.cost_usd).toFixed(4) : ''}</td>`
      + `<td><button class="small ghost runone" data-id="${esc(q.id)}"${running ? ' disabled' : ''}>Run</button></td></tr>`
      + (S.openRow === q.id && r ? `<tr class="open"><td></td><td colspan="7">${testDetail(r)}</td></tr>` : '');
  }).join('');
  $('#testTable').innerHTML = `<div class="card"><div class="scroll"><table class="tests"><colgroup><col class="c-q"><col><col class="c-v"><col class="c-n"><col class="c-n"><col class="c-n"><col class="c-usd"><col class="c-run"></colgroup><thead><tr><th>Q</th><th>Question</th><th>Verdict</th>`
    + `<th class="num">Values</th><th class="num">Tries</th><th class="num">s</th><th class="num">USD</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
    + '<p class="muted">Click a scored row to compare Claude\'s rows with the reference.</p></div>';
  $$('#testTable .runone').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); runSuite([b.dataset.id]); }));
  $$('#testTable tr[data-id]').forEach((tr) => tr.addEventListener('click', () => {
    S.openRow = S.openRow === tr.dataset.id ? null : tr.dataset.id; renderTests();
  }));
  $('#runAll').disabled = !!running;
  if (job) {
    const t = job.tally || {};
    $('#tally').innerHTML = [['match', 'match'], ['partial', 'partial'], ['mismatch', 'mismatch'], ['not_executed', 'not executed'], ['error', 'error']]
      .filter(([k]) => t[k]).map(([k, label]) => `<div class="stat"><b>${t[k]}</b><span>${esc(label)}</span></div>`).join('')
      + `<div class="stat"><b>${job.done}/${job.total}</b><span>done · ${esc(job.model)}</span></div>`
      + `<div class="stat"><b>${esc(job.elapsed)} s</b><span>elapsed</span></div>`
      + `<div class="stat"><b>${Number(job.cost_usd || 0).toFixed(3)}</b><span>USD so far</span></div>`;
  } else {
    $('#tally').innerHTML = '';
  }
}

function testDetail(r) {
  if (r.verdict === 'error' || r.verdict === 'not_executed') return `<p class="err">${esc(r.error || r.note || r.status)}</p>`;
  const missing = (r.missing || []).length
    ? `<p class="err">Missing values: ${r.missing.map((m) => `${esc(m.key ?? '')} ${esc(m.measure)}=${esc(fmt(m.value))}`).join('; ')}</p>` : '';
  return `${r.note ? `<p class="muted">${esc(r.note)}</p>` : ''}${missing}`
    + `<pre class="sql">${esc(r.sql)}</pre><div class="grid2">`
    + `${card(`Claude (${fmt(r.row_count)} rows)`, table(r.rows, null, 12))}`
    + `${card(`Reference (${fmt(r.reference_row_count)} rows)`, table(r.reference_rows, null, 12))}</div>`;
}

async function runSuite(ids) {
  const { ok, data } = await api('/api/play/suite', { suite: $('#suite').value, ids: ids || null, model: $('#tmodel').value });
  if (!ok) { $('#testState').innerHTML = `<span class="err">${esc(data.error)}</span>`; return; }
  S.job = data;
  $('#testState').innerHTML = '<span class="spin"></span> running — Claude answers one question at a time';
  renderTests();
  clearInterval(S.poll);
  S.poll = setInterval(async () => {
    const res = await api(`/api/play/job/${S.job.id}`);
    if (!res.ok) return;
    S.job = res.data;
    renderTests();
    if (S.job.status !== 'running') {
      clearInterval(S.poll);
      const m = (S.job.tally || {}).match || 0;
      $('#testState').textContent = `finished: ${m}/${S.job.total} match · ${S.job.elapsed} s · ${usd(S.job.cost_usd)}`;
    }
  }, 1500);
}

/* ---------- guard lab ------------------------------------------------ */

async function guardRun(mode) {
  const sql = $('#sql').value.trim();
  $('#gState').innerHTML = '<span class="spin"></span>';
  if (mode === 'all') {
    $('#guardOut').innerHTML = '<div id="gEvery"></div>';
    await runEveryone(sql, null, '', '#gEvery', $('#gAll'));
    $('#gState').textContent = '';
    return;
  }
  const { ok, data } = await api('/api/play/guard', { sql, role: mode === 'run' ? $('#grole').value : null });
  $('#gState').textContent = '';
  if (!ok) { $('#guardOut').innerHTML = `<p class="err">${esc(data.error)}</p>`; return; }
  const g = data.guard;
  let html = card(g.allowed ? 'Allowed by the guard' : 'Refused by the guard',
    `<p><span class="verdict ${g.allowed ? 'allowed' : 'refused'}">${g.allowed ? 'allowed' : 'refused'}</span> ${esc(g.reason)}</p>`
    + (g.rewritten_sql && g.rewritten_sql !== sql ? `<p class="muted">Rewritten to:</p><pre class="sql">${esc(g.rewritten_sql)}</pre>` : ''),
    g.allowed ? 'answer' : 'refused');
  if (mode === 'run' && g.allowed) {
    html += data.error ? card('The database refused it', `<p class="err">${esc(data.error)}</p>`, 'refused')
      : card(`Rows as ${personaName(data.role)} — ${fmt(data.row_count)} row(s)`, table(data.rows));
  }
  $('#guardOut').innerHTML = html;
}

/* ---------- pack ----------------------------------------------------- */

async function loadPack() {
  if ($('#pack').dataset.loaded) return;
  const { ok, data } = await api('/api/play/pack');
  if (!ok) { $('#pack').textContent = data.error || 'not available'; return; }
  $('#pack').textContent = data.text;
  $('#pack').dataset.loaded = '1';
  $('#packMeta').textContent = `${fmt(data.chars)} characters (about ${fmt(Math.round(data.chars / 4))} tokens), sent with every question.`;
}

/* ---------- start ---------------------------------------------------- */

async function start() {
  const theme = (() => { try { return localStorage.getItem('theme'); } catch (e) { return null; } })();
  if (theme) document.documentElement.dataset.theme = theme;
  $('#theme').addEventListener('click', () => {
    const now = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = now;
    try { localStorage.setItem('theme', now); } catch (e) { /* private window */ }
  });
  $$('.tabs button').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  if (!(await loadHealth())) return;
  const { ok, data } = await api('/api/play/setup');
  if (!ok) { banner(esc(data.error || 'could not load the playground'), true); return; }
  S.setup = data;
  fillSelects();
  fillExamples();
  $('#askBtn').addEventListener('click', ask);
  $('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) ask(); });
  $('#runAll').addEventListener('click', () => runSuite(null));
  $('#suite').addEventListener('change', renderTests);
  $('#gCheck').addEventListener('click', () => guardRun('check'));
  $('#gRun').addEventListener('click', () => guardRun('run'));
  $('#gAll').addEventListener('click', () => guardRun('all'));
}

start();
