/* The walkthrough.
 *
 * Plain ES modules-free JavaScript, no framework, no build step. The page is
 * a thin renderer: every number it shows arrives from /api/step/<id>, which
 * reads the live database. If the pipeline has not been built, the page says
 * so instead of drawing an empty but convincing shell.
 *
 * The narrative text lives here, beside the rendering, because the point of
 * each step IS the text: the data is the evidence for a design choice, and
 * the choice is what a reviewer is being asked to judge.
 */
'use strict';

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (n) => (n === null || n === undefined || n === '') ? '—'
  : Number(n).toLocaleString('en-GB');

const state = { steps: [], personas: [], i: 0, session: null, role: null, cache: {} };

async function api(path, body) {
  const opts = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: 'bad response' }));
  return { ok: res.ok, status: res.status, data };
}

/* ---------- small renderers ---------------------------------------- */

function table(rows, columns) {
  if (!rows || !rows.length) return '<p class="muted">No rows.</p>';
  const cols = columns || Object.keys(rows[0]);
  return `<div class="scroll"><table><thead><tr>${
    cols.map((c) => `<th>${esc(c)}</th>`).join('')
  }</tr></thead><tbody>${
    rows.map((r) => `<tr>${cols.map((c) => {
      let v = r[c];
      if (Array.isArray(v)) v = v.length ? v.join(', ') : '—';
      if (v === null || v === undefined || v === '') v = '—';
      if (v === true) v = 'yes'; if (v === false) v = 'no';
      return `<td>${esc(v)}</td>`;
    }).join('')}</tr>`).join('')
  }</tbody></table></div>`;
}

const why = (title, html) =>
  `<div class="card why"><h3>Design choice — ${esc(title)}</h3>${html}</div>`;
const assume = (html) =>
  `<div class="card assume"><h3>What this assumes</h3>${html}</div>`;
const stats = (items) => `<div class="stats">${
  items.map(([b, s]) => `<div class="stat"><b>${esc(b)}</b><span>${esc(s)}</span></div>`).join('')
}</div>`;
const sev = (s) => `<span class="tag ${esc(s)}">${esc(String(s).toUpperCase())}</span>`;

function change(from, to, note) {
  return `<div class="arrowrow">
    <div class="box from">${esc(from)}</div><div class="arw">→</div>
    <div class="box to">${esc(to)}</div>
    <div class="note">${note}</div></div>`;
}

/* ---------- the steps ----------------------------------------------- */

const RENDER = {

  bronze(d) {
    const c = d.records.client[0] || {}, a = d.records.account[0] || {}, l = d.records.loan[0] || {};
    return `
    <div class="card"><h3>The three lines this walkthrough follows</h3>
      <pre>client.asc   line ${esc(c._source_row)}   client_id=${esc(c.client_id)}   birth_number=${esc(c.birth_number)}   district_id=${esc(c.district_id)}
account.asc  line ${esc(a._source_row)}   account_id=${esc(a.account_id)}   frequency=${esc(a.frequency)}   date=${esc(a.date)}
loan.asc     line ${esc(l._source_row)}   loan_id=${esc(l.loan_id)}   amount=${esc(l.amount)}   duration=${esc(l.duration)}   status=${esc(l.status)}</pre>
      <p class="muted" style="margin-top:10px">Read that as a person and almost nothing is answerable.
      <code>805502</code> is not a date of birth. <code>POPLATEK MESICNE</code> is not something
      you can group a report by. <code>A</code> is not a loan outcome. Closing that gap is the whole job.</p>
    </div>
    ${why('land it exactly as it arrived, and prove you did', `
      <p>Bronze casts nothing, fixes nothing and drops nothing. Every field is text,
      every row carries the file and line it came from, and each file's SHA-256 is recorded.</p>
      <p>The temptation here is to be helpful — trim a space, parse a date. Don't: every repair
      at this stage is a defect you can no longer find, and a quality report that describes what
      survived the loader is not a quality report.</p>`)}
    ${assume(`<p>That the files are what they claim to be. Checked rather than trusted: the row
      count of every table is compared against the published reference, and the build stops if
      one disagrees. <span class="ref">A23 · DECISIONS D004</span></p>`)}
    <div class="card"><h3>The load audit, from this build</h3>
      ${table(d.audit, ['source_name', 'rows_loaded', 'rows_expected', 'counts_match', 'sha256_head'])}
      ${stats([[num(d.total_rows), 'rows landed, unchanged'], [d.audit.length, 'files, all matching']])}
    </div>`;
  },

  'silver-clean'(d) {
    const c = d.client[0] || {}, a = d.account[0] || {}, l = d.loan[0] || {};
    return `
    <div class="card"><h3>The same three records, after cleaning</h3>
      ${change(`birth_number = ${c.birth_number}`, `birth_date = ${c.birth_date}`,
        'Czech birth numbers are YYMMDD — but the month carries +50 for women, so 55 means May.')}
      ${change(`birth_number = ${c.birth_number}`, `gender = ${c.gender}`,
        'The same six digits again. This dataset has no gender column; it is <em>derived</em>.')}
      ${change(`frequency = ${a.frequency_code}`, `${a.frequency_label}`,
        'One decode map, checked against a published catalogue on every build.')}
      ${change(`status = ${l.status_code}`, `${l.status_label}`,
        `…and <code>is_problematic = ${l.is_problematic}</code>, the certified B-or-D definition, settled once.`)}
    </div>
    ${why('never repair a value', `
      <p>Cleaning here means <b>type, normalise, decode, derive</b> — never overwrite an
      observation. Of 21 cleaning steps exactly one removes a row, and it removed one.</p>
      <p>The original <code>birth_number</code> is still in the row next to the two columns derived
      from it, so the derivation can be checked rather than trusted. A repaired value is
      indistinguishable from a real one a week later.</p>`)}
    ${assume(`<p><b>A two-digit year is always 19xx.</b> Safe only because the dataset runs
      1993–1998, and a date outside that window stops the build. <span class="ref">A17</span></p>
      <p><b>Gender can be inferred from an identifier format.</b> It is an inference, not a
      self-reported attribute, and anything grouping by it inherits that. <span class="ref">A18 · D016</span></p>`)}
    <div class="card"><h3>The most valuable step: resolving the sign once</h3>
      <p class="muted">The source never says whether money went in or out. It says it in Czech,
      in a different column, using two different words for “out”. A query that gets this wrong
      doesn't crash — it returns a confident, plausible, wrong number.</p>
      ${table(d.postings, ['trans_date', 'trans_type_code', 'trans_type_label', 'direction', 'amount', 'signed_amount', 'balance_after'])}
      <p class="muted" style="margin-top:8px">Resolved once for all 1,056,320 postings, with the
      original amount and Czech code kept beside it. “Net flow” is now a sum. <span class="ref">D018</span></p>
    </div>`;
  },

  'silver-grade'(d) {
    const bySev = Object.fromEntries(d.summary.map((r) => [r.severity, r]));
    return `
    <div class="card"><h3>What the rules found in the whole dataset</h3>
      ${stats([
        [num((bySev.block || {}).rules || 0), 'block rules firing'],
        [num((bySev.warn || {}).rules || 0), 'warn rules firing'],
        [num((bySev.info || {}).rules || 0), 'info rules firing'],
        [num(d.quarantined), 'rows removed from the product'],
      ])}
      <div style="margin-top:12px">${table(
        d.fired.map((r) => ({ severity: r.severity, rule: r.rule_id, table: r.target_table,
          rows: num(r.violation_count), of: num(r.total_count) })),
        ['severity', 'rule', 'table', 'rows', 'of'])}</div>
    </div>
    ${why('grade the defect, do not just detect it', `
      <p>Finding a broken row is the easy half. Deciding what it <em>costs</em> is the hard half,
      and it is the half a rule engine cannot do for you.</p>
      <p>${sev('block')} the row is removed from the product, and the removal is counted and reversible.
      ${sev('warn')} the row stays, carrying a flag that travels all the way into the answer.
      ${sev('info')} standardised and logged; no reported number moves.</p>
      <p>Every rule carries its severity <em>and the reason for that severity</em>, written in terms of
      which of the ten questions it would move. The brief is explicit: a rule without a justified
      severity scores the same as no rule.</p>`)}
    ${assume(`<p><b>A zero-amount transaction is not an error.</b> It is interest that accrued
      nothing. Blocking those 14 rows would break 14 balance chains to fix nothing — so it is
      <code>info</code>. <b>A negative balance is not an error either:</b> overdraft is real
      banking, and clipping it at zero would bias the average closing balance upward.</p>`)}
    <div class="card"><h3>And about this one client</h3>
      ${d.this_client.length
        ? table(d.this_client.map((r) => ({ severity: r.severity, rule: r.rule_id, reason: r.reason })),
                ['severity', 'rule', 'reason'])
        : '<p class="muted">No flags.</p>'}
      <p class="muted" style="margin-top:8px">Her account was opened when she was 12. That is what the
      bank's own file says. It is flagged, not corrected — the useful output is a row somebody
      investigates, not a quietly plausible one nobody does.</p>
    </div>`;
  },

  gold(d) {
    const c = d.client[0] || {}, a = d.account[0] || {};
    return `
    <div class="card"><h3>The published model</h3>
      ${table(d.tables.map((r) => ({ table: 'core.' + r.table_name, rows: num(r.approx_rows) })),
              ['table', 'rows'])}
    </div>
    ${why('a star schema with a bridge, not one big table', `
      <p>The ten questions have four different grains — client, account, loan, posting. Flattening
      everything onto the transaction turns every count of clients, accounts and loans into a
      <code>count(distinct …)</code>, which is the single easiest thing for a generated query to
      get wrong.</p>
      <p>The client-to-account relationship is many-to-many and stays a <b>bridge</b>. Collapsing it
      into either side is exactly what makes “the account owner” ambiguous. <span class="ref">D007 · DDR 3</span></p>`)}
    <div class="card"><h3>The same client, published</h3>
      ${table([{ client_id: c.client_id, client_ref: c.client_ref, birth_date: c.birth_date,
                 gender: c.gender, flags: c._dq_flags }])}
      ${table([{ account_id: a.account_id, account_ref: a.account_ref, open_date: a.open_date,
                 statement_frequency: a.statement_frequency, flags: a._dq_flags }])}
      <p class="muted" style="margin-top:8px">Note the two new names. <code>client_ref</code> is opaque —
      unlike a row number it cannot be guessed, counted or correlated. <code>account_ref</code> is an
      IBAN with genuine check digits, so a typo fails the way a real one would. Join on the id;
      refer to people by the reference. <span class="ref">D025</span></p>
    </div>
    ${assume(`<p><b>Nothing was lost on the way here.</b> Not assumed — proved, on every build:
      <code>core = staging − quarantine</code>, checked on row counts <em>and</em> on money.</p>`)}
    <div class="card"><h3>The reconciliation, from this build</h3>
      ${table(d.reconciliation.map((r) => ({ entity: r.entity, metric: r.metric,
        staging: num(r.stg_value), quarantined: num(r.quarantined),
        core: num(r.core_value), balanced: r.is_balanced })))}
    </div>`;
  },

  access(d) {
    return `
    <div class="card"><h3>Who can reach client ${esc(d.subject)}, and why</h3>
      ${table(d.who.map((r) => ({ principal: r.db_role, kind: r.user_type, may: r.permission,
        because: r.grant_source, reason: r.reason, until: r.valid_to ? String(r.valid_to).slice(0, 10) : '—' })))}
    </div>
    ${why('four sources of access, one shape', `
      <p>Every right anyone holds says <b>who</b>, over <b>what</b>, which <b>permission</b>, from
      which <b>source</b>, granted by whom, and until when.</p>
      <p><b>ownership</b> — the principal is this client. <b>disposition</b> — authorised to operate
      an account they do not own. <b>portfolio</b> — staff, through a book, <em>view only</em>:
      being accountable for a client is not authority to move their money.
      <b>delegation</b> — a human decision, which is why it is the only one that carries a reason
      and an expiry.</p>
      <p>Three of the four are derived live from records the bank already keeps, so they cannot
      drift. An earlier version materialised them into a table and a test caught the consequence:
      granting a portfolio did nothing until the next rebuild. <span class="ref">D027</span></p>`)}
    ${assume(`<p><b>A disposition grants the account and nothing else</b> — not the owner's client
      record, not their other accounts. The lazy implementation grants the owning client and lets
      their accounts follow, which would mean authorising someone to pay a bill from your account
      lets them read <em>you</em>. <span class="ref">A40 · D024</span></p>`)}
    <div class="card"><h3>Every live grant in the system</h3>
      ${table(d.sources.map((r) => ({ source: r.grant_source, permission: r.permission, grants: num(r.n) })))}
    </div>`;
  },

  login() {
    return `
    <div class="card"><h3>1 · Choose who to be</h3>
      <div class="personas" id="personas"></div>
    </div>
    <div id="loginflow"></div>
    ${why('the filter is in the engine, not in the question', `
      <p>Identity comes from the authenticated database role, which no statement the caller — or a
      language model — can change. The entitlement is a <b>policy on the table</b>, so it applies
      inside the plan of every statement on that connection, whoever wrote the SQL.</p>
      <p>That is why the next step can let a model write a query and run it without inspecting
      whose data it asks for. The predicate is not in the query, so rewriting the query cannot
      remove it. <span class="ref">D009 · D026</span></p>`)}
    ${assume(`<p><b>The second factor is real; the phone is not.</b> The code below is generated
      server-side because a web page cannot hand you six phones. Everything else — the TOTP
      algorithm, single use, lockout, the session bound to one connection — is the production
      path. A system that shows you your own second factor has one factor, and it is the first
      thing a deployment removes. <span class="ref">A46</span></p>`)}`;
  },

  ask() {
    return `
    <div class="card"><h3>Ask the data a question</h3>
      <p class="muted">The model is given the semantic layer and your question. It never sees the
      database. Its SQL is parsed before it runs, then executed on a connection authenticated as
      the persona you chose — so the answer is narrowed to what <em>they</em> may see.</p>
      <div id="asker"></div>
    </div>
    ${why('treat the model as an untrusted query author', `
      <p>Three things stand between the question and the data, and they do different jobs.
      The <b>semantic layer</b> tells the model what the words mean, so it has no reason to guess.
      The <b>guard</b> parses the SQL and rejects anything that is not a single read-only
      <code>SELECT</code> against the published schema. The <b>policies</b> decide which rows come
      back, and they would do that even if the first two failed.</p>
      <p>Only the third is a security control. The guard is a shape filter; the low-privilege,
      policy-bound role is the actual boundary. <span class="ref">D011 · DDR 7</span></p>`)}
    ${assume(`<p><b>That a small model will sometimes be wrong.</b> It is not a defect of the
      governance that it is: the point is that a wrong query returns a wrong answer <em>about data
      this persona is allowed to see</em>, and never somebody else's. Every call is logged with its
      prompt, model and raw response.</p>`)}`;
  },
};

/* ---------- interactive bits ---------------------------------------- */

function renderPersonas() {
  const host = $('#personas'); if (!host) return;
  host.innerHTML = state.personas.map((p) => `
    <button class="persona" data-role="${esc(p.role)}" aria-pressed="${state.role === p.role}">
      <b>${esc(p.name)}</b><span>${esc(p.kind)} — ${esc(p.blurb)}</span></button>`).join('');
  host.querySelectorAll('.persona').forEach((b) =>
    b.addEventListener('click', () => startLogin(b.dataset.role)));
}

async function startLogin(role) {
  state.role = role; state.session = null; renderPersonas(); updateWho();
  const host = $('#loginflow');
  host.innerHTML = `<div class="card"><h3>2 · The password alone</h3>
    <p class="muted"><span class="spin"></span> Connecting as <code>${esc(role)}</code>…</p></div>`;

  const peek = await api('/api/peek', { role });
  if (!peek.ok) { host.innerHTML = `<div class="card"><p class="err">${esc(peek.data.error)}</p></div>`; return; }
  const r = peek.data.reach;
  host.innerHTML = `
    <div class="card"><h3>2 · The password alone</h3>
      <p>Connected as <code>${esc(role)}</code>. Correct password, no second factor yet.</p>
      ${stats([[num(r.clients), 'clients'], [num(r.accounts), 'accounts'],
               [num(r.loans), 'loans'], [num(r.transactions), 'transactions']])}
      <p class="muted" style="margin-top:10px">Not an error — the queries <em>ran</em>. The
      entitlement resolves only for a session that has passed both factors, so a stolen password
      is an empty database.</p>
    </div>
    <div class="card"><h3>3 · The second factor</h3>
      <div class="row">
        <button id="getcode" class="small">Show the code their phone would show</button>
        <span class="muted" id="codehint"></span>
      </div>
      <div class="row" style="margin-top:10px">
        <input type="text" class="code" id="code" maxlength="6" inputmode="numeric"
               placeholder="000000" autocomplete="off">
        <button id="dologin">Log in</button>
        <span id="loginmsg" class="muted"></span>
      </div>
      <p class="muted" style="margin-top:8px">Try a wrong code first — six digits that aren't the
      right ones — and watch it refuse.</p>
    </div>`;

  $('#getcode').addEventListener('click', async () => {
    $('#codehint').innerHTML = '<span class="spin"></span>';
    const res = await api('/api/code', { role });
    if (!res.ok) { $('#codehint').textContent = res.data.error || 'failed'; return; }
    if (!res.data.code) {
      /* A code works once. Count down rather than hanging the request. */
      let left = res.data.wait_seconds;
      $('#codehint').textContent = `${res.data.note} Next code in ${left}s…`;
      const tick = setInterval(() => {
        left -= 1;
        if (left > 0) { $('#codehint').textContent = `Code already used — next one in ${left}s…`; }
        else { clearInterval(tick); $('#codehint').textContent = 'Ready — press again.'; }
      }, 1000);
      return;
    }
    $('#code').value = res.data.code;
    $('#codehint').textContent = `valid for ${res.data.valid_for_seconds}s — demo only`;
  });
  $('#dologin').addEventListener('click', doLogin);
  $('#code').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
}

async function doLogin() {
  const code = $('#code').value.trim();
  const msg = $('#loginmsg');
  msg.className = 'muted'; msg.innerHTML = '<span class="spin"></span>';
  const res = await api('/api/login', { role: state.role, code });
  if (!res.ok) { msg.className = 'err'; msg.textContent = res.data.error || 'refused'; return; }
  state.session = res.data.session;
  updateWho();
  const r = res.data.reach;
  msg.className = 'muted'; msg.textContent = 'accepted';
  $('#loginflow').insertAdjacentHTML('beforeend', `
    <div class="card"><h3>4 · Now logged in</h3>
      <p>Entitled to <code>${esc(res.data.entitlement.portfolios)}</code>
         as a <code>${esc(res.data.entitlement.principal_type)}</code>.</p>
      ${stats([[num(r.clients), 'clients'], [num(r.accounts), 'accounts'],
               [num(r.loans), 'loans'], [num(r.transactions), 'transactions']])}
      <div style="margin-top:12px">${table(res.data.sample)}</div>
      <p class="muted" style="margin-top:8px">Same connection, same queries, one code apart.
      Now go to <b>Ask</b> and put a question to the model as this person.</p>
    </div>`);
}

async function renderAsker() {
  const host = $('#asker'); if (!host) return;
  if (!state.session) {
    host.innerHTML = `<p class="err">Log in as a persona on the previous step first.</p>`;
    return;
  }
  const qs = (await api('/api/questions')).data.questions || [];
  host.innerHTML = `
    <p class="muted">Asking as <code>${esc(state.role)}</code>. Pick one of the brief's ten, or write your own.</p>
    <div class="personas" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">
      ${qs.map((q) => `<button class="qbtn" data-q="${esc(q.question)}">${esc(q.id)} — ${esc(q.question)}</button>`).join('')}
    </div>
    <div class="row" style="margin-top:12px">
      <input type="text" id="q" placeholder="…or type a question" maxlength="300">
      <button id="send">Ask</button>
    </div>
    <div id="answer"></div>`;
  host.querySelectorAll('.qbtn').forEach((b) =>
    b.addEventListener('click', () => { $('#q').value = b.dataset.q; sendQuestion(); }));
  $('#send').addEventListener('click', sendQuestion);
  $('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendQuestion(); });
}

async function sendQuestion() {
  const question = $('#q').value.trim();
  const out = $('#answer');
  if (question.length < 3) { out.innerHTML = '<p class="err">Ask something longer.</p>'; return; }
  out.innerHTML = `<div class="card"><p class="muted"><span class="spin"></span>
    Asking the model, then guarding and running its SQL as <code>${esc(state.role)}</code>…
    <br>A small model on a small box can take a while.</p></div>`;
  const res = await api('/api/ask', { session: state.session, question });
  const d = res.data;
  if (!res.ok) { out.innerHTML = `<div class="card"><p class="err">${esc(d.error || 'failed')}</p></div>`; return; }

  const stageNote = {
    llm: 'The model could not be reached. The page says so rather than inventing an answer.',
    parse: 'The model replied, but not in the shape asked for. Common with very small models.',
    guard: 'The guard refused the SQL before it touched the database.',
    execute: 'The SQL was allowed but failed when it ran.',
    done: '',
  }[d.stage] || '';

  out.innerHTML = `
    <div class="card"><h3>What the model wrote</h3>
      <p class="muted">${esc(d.provider)} / ${esc(d.model)} · ${esc(d.elapsed_sec)}s</p>
      ${d.sql ? `<pre>${esc(d.sql)}</pre>` : `<p class="muted">No SQL was produced.</p>`}
      ${d.model_explanation ? `<p class="muted" style="margin-top:8px">${esc(d.model_explanation)}</p>` : ''}
    </div>
    <div class="card"><h3>The guard</h3>
      ${d.guard
        ? (d.guard.allowed
            ? `<p><span class="tag info">ALLOWED</span> single read-only SELECT against the published schema, with a row cap applied.</p>`
            : `<p><span class="tag block">REFUSED</span> ${esc((d.guard.violations || []).join('; '))}</p>`)
        : '<p class="muted">Not reached.</p>'}
    </div>
    ${d.stage === 'done'
      ? `<div class="card"><h3>The answer, as ${esc(state.role)}</h3>
           ${table(d.rows)}
           <p class="muted" style="margin-top:8px">${num(d.row_count)} row(s). Log in as a
           different persona and ask the same question — the SQL will be the same and the answer
           will not.</p></div>`
      : `<div class="card"><p class="err">${esc(d.error || 'no answer')}</p>
           <p class="muted">${esc(stageNote)}</p></div>`}`;
}

/* ---------- shell ---------------------------------------------------- */

function updateWho() {
  const el = $('#whoami');
  if (state.session && state.role) { el.textContent = `logged in: ${state.role}`; el.className = 'pill ok'; }
  else if (state.role) { el.textContent = `${state.role} — not verified`; el.className = 'pill bad'; }
  else { el.textContent = 'not logged in'; el.className = 'pill'; }
}

function renderRail() {
  $('#rail').innerHTML = state.steps.map((s, i) => `
    <button data-i="${i}" ${i === state.i ? 'aria-current="step"' : ''}
            class="${i < state.i ? 'done' : ''}">
      <span class="n">${i + 1}</span>${esc(s.short || s.title)}</button>`).join('');
  $('#rail').querySelectorAll('button').forEach((b) =>
    b.addEventListener('click', () => go(Number(b.dataset.i))));
}

const LEDE = {
  bronze: 'Eight files of plain text. This is everything the bank hands over, and on its own it answers nothing.',
  'silver-clean': 'Typing, normalising, decoding, deriving — without ever overwriting what the bank recorded.',
  'silver-grade': 'Cleaning makes a value usable. It does not make it true. Each defect gets a severity and a consequence.',
  gold: 'The business model: stated grains, resolved keys, caveats attached to the rows that carry them.',
  access: 'Every right anyone holds over this data, where it comes from, and how long it lasts.',
  login: 'Become someone, and watch what the password alone is worth.',
  ask: 'A real question, a real model, and the entitlement filter the model cannot see or affect.',
};

async function go(i) {
  state.i = Math.max(0, Math.min(state.steps.length - 1, i));
  const step = state.steps[state.i];
  renderRail();
  $('#kicker').textContent = `Step ${state.i + 1} of ${state.steps.length}`;
  $('#title').textContent = step.title;
  $('#lede').textContent = LEDE[step.id] || '';
  $('#counter').textContent = `${state.i + 1} / ${state.steps.length}`;
  $('#prev').disabled = state.i === 0;
  $('#next').disabled = state.i === state.steps.length - 1;
  window.scrollTo({ top: 0, behavior: 'smooth' });
  location.hash = step.id;

  if (step.id === 'login') { $('#content').innerHTML = RENDER.login(); renderPersonas(); updateWho(); return; }
  if (step.id === 'ask') { $('#content').innerHTML = RENDER.ask(); renderAsker(); return; }

  $('#content').innerHTML = '<div class="card"><p class="muted"><span class="spin"></span> Reading the database…</p></div>';
  if (!state.cache[step.id]) {
    const res = await api('/api/step/' + step.id);
    if (!res.ok) {
      $('#content').innerHTML = `<div class="card"><h3>Not available</h3>
        <p class="err">${esc(res.data.detail || res.data.error)}</p>
        <p class="muted">${esc(res.data.hint || '')}</p></div>`;
      return;
    }
    state.cache[step.id] = res.data.data;
  }
  if (state.steps[state.i].id !== step.id) return;  /* user moved on while loading */
  $('#content').innerHTML = RENDER[step.id](state.cache[step.id]);
}

async function boot() {
  const theme = localStorage.getItem('theme');
  if (theme) document.documentElement.dataset.theme = theme;
  $('#theme').addEventListener('click', () => {
    const now = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = now;
    try { localStorage.setItem('theme', now); } catch (e) { /* private window */ }
  });

  const health = await api('/api/health');
  const h = health.data;
  const el = $('#health');
  if (h.ok) { el.textContent = `${num(h.clients)} clients · ${h.llm_configured ? h.llm : 'no LLM'}`; el.className = 'pill ok'; }
  else { el.textContent = 'pipeline not built'; el.className = 'pill bad'; }

  const tour = await api('/api/tour');
  if (!tour.ok) { $('#title').textContent = 'Cannot reach the server'; return; }
  state.steps = tour.data.steps;
  state.personas = tour.data.personas;

  $('#prev').addEventListener('click', () => go(state.i - 1));
  $('#next').addEventListener('click', () => go(state.i + 1));
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'ArrowRight') go(state.i + 1);
    if (e.key === 'ArrowLeft') go(state.i - 1);
  });

  const want = state.steps.findIndex((s) => s.id === location.hash.slice(1));
  go(want >= 0 ? want : 0);
}

boot();
