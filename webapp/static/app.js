// ============================================================
// State
// ============================================================
let projectId = null;
let questions = [];
let agentMeta = [];

// Conversational discovery flow state
let dfAnswers = {};       // question_id -> answer text
let dfSkipped = {};       // question_id -> true, for questions explicitly skipped
let dfIndex = 0;          // index of the question currently on screen
let dfShowingReview = false;
let dfReturnToReview = false; // true when we jumped here via "Edit" from the review screen
const OTHER_LABEL = 'Something else';
const ADDITIONAL_INFO_ID = 'additional_information';

// Agent-run state. runState drives the "Run AI Agents" button so it can never be
// double-clicked: idle -> running -> done, or running -> error (re-enabled to retry).
let runState = 'idle';          // 'idle' | 'running' | 'done' | 'error'
let nextAgentIndex = 0;         // where a retry after an error resumes
let hasGeneratedBefore = false; // this project already has a generated package (reopened / re-run)
let lastHandoffStatus = null;

const NODE_X_START = 70;
const NODE_X_GAP = 150;
const NODE_Y = 70;
const NODE_R = 26;

// ============================================================
// Helpers
// ============================================================
function $(sel) { return document.querySelector(sel); }
function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) e.appendChild(c);
  return e;
}
function unlock(panelId) { $(panelId).classList.remove('is-locked'); }

async function api(path, opts = {}) {
  const data = await rawApi(path, opts);
  // Live-mode steps run as background jobs (they make many LLM calls and can
  // take minutes): the POST answers with a job id and we poll until it's done,
  // then hand back exactly what the synchronous endpoint would have returned.
  if (data && data.job_id) return pollJob(data.job_id);
  return data;
}

function showJobProgress(lines) {
  const log = $('#agent-log');
  let box = $('#job-progress');
  if (!lines) { if (box) box.remove(); return; }
  if (!box) box = log.appendChild(el('div', { id: 'job-progress', class: 'log-progress' }));
  box.textContent = lines.slice(-3).map((l) => '   ⋯ ' + l).join('\n');
  box.style.whiteSpace = 'pre-wrap';
  log.scrollTop = log.scrollHeight;
}

async function pollJob(jobId) {
  const started = Date.now();
  let failures = 0;
  try {
    while (Date.now() - started < 30 * 60 * 1000) {
      await new Promise((r) => setTimeout(r, 2000));
      let snap;
      try {
        snap = await rawApi(`/api/job/${jobId}`);
        failures = 0;
      } catch (e) {
        if (/unknown or expired job/.test(e.message)) {
          throw new Error('The server restarted while generating — please try again.');
        }
        if (++failures >= 5) throw e;   // tolerate a few network blips
        continue;
      }
      if (snap.status === 'error') throw new Error(snap.error || 'generation failed');
      if (snap.status === 'done') return snap.result;
      showJobProgress(snap.progress && snap.progress.length ? snap.progress : ['working…']);
    }
    throw new Error('Generation is taking unusually long (over 30 minutes) — please try again.');
  } finally {
    showJobProgress(null);
  }
}

async function rawApi(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let data;
  try {
    data = await res.json();
  } catch (parseErr) {
    // The response wasn't JSON at all — almost always means a proxy/host
    // timed the request out (or crashed) and served its own HTML error
    // page before our Flask app's JSON error handler ever got to run.
    // Surface something actionable instead of the raw parse error.
    throw new Error(
      res.ok
        ? 'The server sent back an unexpected response. It may have timed out — please try again.'
        : `Request failed (HTTP ${res.status}). The server may have timed out — please try again.`
    );
  }
  if (!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function downloadMarkdown(filename, content) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Status strings like "READY FOR DESIGN AGENT" have spaces, which can't
// be used directly as CSS classes — slugify for styling, keep the raw
// text for display.
function statusSlug(status) {
  if (!status) return 'unknown';
  const s = status.toUpperCase();
  if (s.includes('NOT READY')) return 'status-not-ready';
  if (s.includes('WARNING')) return 'status-warnings';
  if (s.includes('READY')) return 'status-ready';
  return 'status-unknown';
}

// ============================================================
// Title block
// ============================================================
function setTitleBlock({ projectId, domain }) {
  $('#tb-project').textContent = projectId ? projectId.slice(0, 8) : '—';
  $('#tb-domain').textContent = domain || '—';
  $('#tb-date').textContent = new Date().toISOString().slice(0, 10);
}

async function refreshDomainCount() {
  try {
    const data = await api('/api/knowledge/domains');
    $('#tb-domains').textContent = `${data.domains.length} domains`;
  } catch (e) { /* non-critical */ }
}

async function checkMode() {
  const elm = $('#tb-mode');
  try {
    const data = await api('/api/mode');
    elm.textContent = data.mode === 'live' ? `LIVE · ${data.provider.toUpperCase()}` : 'MOCK · offline';
  } catch (e) {
    elm.textContent = 'unknown';
  }
}
checkMode();

// ============================================================
// View switching: dashboard <-> pipeline
// ============================================================
$('#btn-go-dashboard').addEventListener('click', goToDashboard);
$('#btn-pipeline-back').addEventListener('click', goToDashboard);
$('#btn-open-new-project').addEventListener('click', () => {
  sessionStorage.setItem('poc_view', 'pipeline');
  history.replaceState(null, '', location.pathname);
  location.reload();
});

function goToDashboard() {
  if (runState === 'running' &&
      !confirm('The AI agents are still running. If you leave now this run is lost (your answers stay saved as a draft). Leave anyway?')) return;
  runState = 'idle';   // let the unload guard below stand down
  sessionStorage.removeItem('poc_view');
  history.replaceState(null, '', location.pathname);
  location.reload();
}

// Guards against closing the tab in the middle of an agent run. Answers are autosaved
// server-side after every question, so nothing else is ever lost by closing the tab.
window.addEventListener('beforeunload', (e) => {
  if (runState === 'running') { e.preventDefault(); e.returnValue = ''; }
});

function showPipelineView() {
  $('#dashboard-view').hidden = true;
  $('#pipeline-view').hidden = false;
}

function showDashboardList() {
  $('#pipeline-view').hidden = true;
  $('#dashboard-view').hidden = false;
  loadDashboard();
}

function openProject(id) {
  location.hash = 'project=' + id;
  location.reload();
}

// ============================================================
// Dashboard: project list (table) — drafts can be resumed, finished projects reopened
// ============================================================
async function loadDashboard() {
  $('#dash-loading-msg').hidden = false;
  $('#dash-empty-msg').hidden = true;
  $('#dash-table').hidden = true;
  try {
    const data = await api('/api/history');
    renderDashboardTable(data.projects);
  } catch (e) {
    $('#dash-loading-msg').textContent = 'Could not load projects: ' + e.message;
  }
}

function renderDashboardTable(projects) {
  const loadingMsg = $('#dash-loading-msg');
  const emptyMsg = $('#dash-empty-msg');
  const table = $('#dash-table');
  const body = $('#dash-table-body');
  body.innerHTML = '';
  loadingMsg.hidden = true;

  if (!projects.length) {
    emptyMsg.hidden = false; table.hidden = true; return;
  }
  emptyMsg.hidden = true; table.hidden = false;

  projects.forEach(p => {
    const isDraft = p.status === 'draft';
    const stamp = p.updated_at || p.created_at;
    const date = stamp ? new Date(stamp).toLocaleString() : 'unknown';
    const statusBadge = isDraft
      ? el('span', { class: 'history-badge status-draft', text: p.question_count ? `DRAFT · ${p.answered_count}/${p.question_count} answered` : 'DRAFT' })
      : el('span', { class: 'history-badge status-ready', text: 'COMPLETE' });
    const handoff = isDraft
      ? el('span', { class: 'dash-muted', text: '—' })
      : el('span', { class: `history-badge ${statusSlug(p.handoff_status)}`, text: p.handoff_status || 'unknown' });

    const actions = el('td', { class: 'dash-actions-cell' });
    const openBtn = el('button', { type: 'button', class: 'btn btn-small', text: isDraft ? 'Resume →' : 'Open →' });
    openBtn.addEventListener('click', (ev) => { ev.stopPropagation(); openProject(p.id); });
    actions.appendChild(openBtn);
    if (isDraft) {
      const delBtn = el('button', { type: 'button', class: 'btn btn-small btn-ghost', text: 'Discard' });
      delBtn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        if (!confirm('Discard this unfinished draft? Its answers will be deleted.')) return;
        try {
          await api(`/api/project/${p.id}`, { method: 'DELETE' });
          loadDashboard();
        } catch (e) { alert('Could not discard: ' + e.message); }
      });
      actions.appendChild(delBtn);
    }

    const row = el('tr', {}, [
      el('td', { class: 'dash-idea-cell', text: p.business_idea }),
      el('td', { class: 'dash-domain-cell', text: p.domain || 'unclassified' }),
      el('td', {}, [statusBadge]),
      el('td', { text: String(p.artefact_count) }),
      el('td', {}, [handoff]),
      el('td', { class: 'dash-date-cell', text: date }),
      actions,
    ]);
    row.addEventListener('click', () => openProject(p.id));
    body.appendChild(row);
  });
}

// Turns ```mermaid code blocks into rendered diagrams, each on its own light "canvas" card with a
// small notation legend so separate diagrams are easy to tell apart. Purely progressive: if the
// mermaid library didn't load or a diagram is invalid, the readable source stays.
const DIAGRAM_LEGEND = '<span class="lg lg-term"></span>Start / End<span class="lg lg-proc"></span>Process step<span class="lg lg-dec"></span>Decision';

function renderMermaidBlocks(viewer) {
  if (!window.mermaid) return;
  try {
    const blocks = viewer.querySelectorAll('pre > code.language-mermaid');
    blocks.forEach((code) => {
      const src = code.textContent;
      const card = document.createElement('div');
      card.className = 'diagram-card';
      if (/^\s*(flowchart|graph)/i.test(src)) {
        const legend = document.createElement('div');
        legend.className = 'diagram-legend';
        legend.innerHTML = DIAGRAM_LEGEND;
        card.appendChild(legend);
      }
      const div = document.createElement('div');
      div.className = 'mermaid';
      div.textContent = src;
      card.appendChild(div);
      code.parentElement.replaceWith(card);
    });
    if (blocks.length) {
      window.mermaid.run({ nodes: viewer.querySelectorAll('.mermaid'), suppressErrors: true })
        .then(() => viewer.querySelectorAll('.diagram-card svg').forEach(routeFlowchart))
        .catch(() => {});
    }
  } catch (e) { /* keep the source visible */ }
}

// ------------------------------------------------------------------------------------------
// Standard flowchart connector routing.
// Mermaid clips every connector to the slanted edge of a diamond, so lines appear to start
// mid-side and arrowheads float off the borders. After rendering, each connector is re-drawn
// from the node geometry using the usual flowchart conventions:
//   - only horizontal / vertical segments (right angles), one arrowhead at the target
//   - a decision leaves from its left, right or bottom corner point
//   - other shapes leave from the bottom centre and enter the target's top centre
//   - a line that goes back up (a retry loop) leaves from the side and re-enters from the side
// Any edge that cannot be routed cleanly (it would cross another shape) keeps Mermaid's own line.
// ------------------------------------------------------------------------------------------
function routeFlowchart(svg) {
  try {
    const nodeEls = [...svg.querySelectorAll('g.node')];
    const paths = [...svg.querySelectorAll('path.flowchart-link')];
    if (!nodeEls.length || !paths.length) return;

    const boxes = {};
    nodeEls.forEach((g) => {
      const m = /flowchart-(.+)-\d+$/.exec(g.id || '');
      if (!m) return;
      const t = /translate\(\s*([-\d.]+)[ ,]+([-\d.]+)/.exec(g.getAttribute('transform') || '');
      if (!t) return;
      const b = g.getBBox();                       // whole node, in the node's own (centred) coordinates
      const w = b.width, h = b.height, cx = +t[1] + b.x + w / 2, cy = +t[2] + b.y + h / 2;
      const isDecision = g.querySelector('polygon') !== null;
      boxes[m[1]] = { id: m[1], cx, cy, w, h, l: cx - w / 2, r: cx + w / 2, t: cy - h / 2, b: cy + h / 2, dec: isDecision };
    });

    const labels = [...svg.querySelectorAll('g.edgeLabels > g.edgeLabel')];
    const used = {};                               // decision exits already taken: id -> {left,right,bottom}
    const routed = [];
    const channels = [];                           // x positions already used by loop-back lines

    const hits = (pts, skip) => {
      for (let i = 0; i < pts.length - 1; i++) {
        const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
        const minx = Math.min(x1, x2), maxx = Math.max(x1, x2), miny = Math.min(y1, y2), maxy = Math.max(y1, y2);
        for (const k in boxes) {
          if (skip.includes(k)) continue;
          const n = boxes[k];
          if (maxx > n.l + 1 && minx < n.r - 1 && maxy > n.t + 1 && miny < n.b - 1) return true;
        }
      }
      return false;
    };

    // Distance the arrow tip sits beyond the path end, so the tip can touch the shape border.
    let tip = 4;
    const mk = svg.querySelector('marker');
    if (mk) {
      const vb = (mk.getAttribute('viewBox') || '0 0 10 10').split(/[ ,]+/).map(Number);
      const refX = parseFloat(mk.getAttribute('refX') || '5'), mw = parseFloat(mk.getAttribute('markerWidth') || vb[2]);
      if (vb[2] > 0 && mw > 0 && !isNaN(refX)) tip = Math.max(0, (vb[2] - refX) * (mw / vb[2]));
    }

    const edges = [];
    paths.forEach((path, idx) => {
      // which shapes does this line join? Newer Mermaid puts it in the id (L_A_B_0 / L-A-B-0),
      // older versions also add LS-A / LE-B classes.
      const cls = path.getAttribute('class') || '';
      let s = (/LS-(\S+)/.exec(cls) || [])[1], e = (/LE-(\S+)/.exec(cls) || [])[1];
      if (!s || !e) {
        const ids = Object.keys(boxes), esc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        outer: for (const a of ids) for (const b of ids) {
          if (new RegExp('(^|[-_])L[-_]' + esc(a) + '[-_]' + esc(b) + '[-_]\\d+$').test(path.id || '')) { s = a; e = b; break outer; }
        }
      }
      const S = boxes[s], T = boxes[e];
      if (S && T && S !== T) edges.push({ path, idx, S, T });
    });
    // loop-back lines first, so they reserve their corner points before forward lines choose theirs
    const isBack = (E) => !(E.T.t > E.S.b + 6);
    edges.sort((x, y) => (isBack(y) ? 1 : 0) - (isBack(x) ? 1 : 0));

    edges.forEach(({ path, idx, S, T }) => {
      const dx = T.cx - S.cx;
      const usedS = (used[S.id] = used[S.id] || {}), usedT = (used[T.id] = used[T.id] || {});
      const cands = [];                                           // candidate routes, best first

      if (T.t > S.b + 6) {                                         // forward: target is below
        const side = dx < 0 ? 'left' : 'right', sideX = dx < 0 ? S.l : S.r;
        const sideRoute = () => [[sideX, S.cy], [T.cx, S.cy], [T.cx, T.t]];
        const zRoute = (f) => { const my = S.b + (T.t - S.b) * f; return [[S.cx, S.b], [S.cx, my], [T.cx, my], [T.cx, T.t]]; };
        // leave the side, run past the target, come back into the target's facing side
        const wrapRoute = () => {
          const inX = dx < 0 ? T.r : T.l, x = dx < 0 ? T.r + 26 : T.l - 26;
          return [[sideX, S.cy], [x, S.cy], [x, T.cy], [inX, T.cy]];
        };
        const canSide = Math.abs(dx) > S.w / 2 + 8 && !usedS[side];
        const nb = usedS.bottomCount || 0;                          // lines already forking off the bottom point
        const canBottom = nb < 3;
        if (Math.abs(dx) < 3 && nb === 0) {
          const x = (S.cx + T.cx) / 2;                             // centres differ only by rounding
          cands.push({ pts: [[x, S.b], [x, T.t]], exit: 'bottom' });
        } else {
          const fr = [[0.5, 0.3, 0.7], [0.75, 0.25, 0.88], [0.9, 0.12, 0.6]][nb] || [];   // each fork gets its own level
          const z = canBottom ? fr.map((f) => ({ pts: zRoute(f), exit: 'bottom', seg: S.dec ? 1 : 0 })) : [];
          if (S.dec) {
            if (canSide) cands.push({ pts: sideRoute(), exit: side });
            cands.push(...z);
          } else {
            cands.push(...z);
            if (canSide) cands.push({ pts: sideRoute(), exit: side });
          }
          const enter = dx < 0 ? 'right' : 'left';
          if (canSide && !usedT[enter]) cands.push({ pts: wrapRoute(), exit: side, enter });
        }
      } else {                                                      // backward / same level: loop round a side
        const first = T.cx <= S.cx ? 'left' : 'right';
        [first, first === 'left' ? 'right' : 'left'].forEach((sd) => {
          if (usedS[sd] || usedT[sd]) return;
          let out = sd === 'left' ? Math.min(S.l, T.l) - 34 : Math.max(S.r, T.r) + 34;
          while (channels.some((c) => Math.abs(c - out) < 14)) out += sd === 'left' ? -16 : 16;   // keep loops apart
          cands.push({ pts: [[sd === 'left' ? S.l : S.r, S.cy], [out, S.cy], [out, T.cy], [sd === 'left' ? T.l : T.r, T.cy]], exit: sd, enter: sd, channel: out });
        });
      }
      const pick = cands.find((c) => !hits(c.pts, [S.id, T.id]));
      if (!pick) return;                                           // keep Mermaid's own line
      usedS[pick.exit] = true;
      if (pick.exit === 'bottom') usedS.bottomCount = (usedS.bottomCount || 0) + 1;
      if (pick.enter) usedT[pick.enter] = true;                    // a corner point carries one line only
      if (pick.channel !== undefined) channels.push(pick.channel);
      const pts = pick.pts, labelSeg = pick.seg || 0;

      // pull the last point back so the arrow TIP (not its base) lands on the border
      const n = pts.length, [px, py] = pts[n - 2], last = pts[n - 1];
      const len = Math.hypot(last[0] - px, last[1] - py) || 1;
      pts[n - 1] = [last[0] - ((last[0] - px) / len) * tip, last[1] - ((last[1] - py) / len) * tip];

      path.setAttribute('d', 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L'));
      routed.push({ idx, pts, labelSeg });
    });

    // put each label on the first segment leaving its decision, on a white plate over the line
    routed.forEach(({ idx, pts, labelSeg }) => {
      const lab = labels[idx];
      if (!lab || !(lab.textContent || '').trim()) return;
      let a = pts[labelSeg], b = pts[labelSeg + 1];
      if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 34 && pts[labelSeg + 2]) { a = pts[labelSeg + 1]; b = pts[labelSeg + 2]; }
      lab.setAttribute('transform', `translate(${((a[0] + b[0]) / 2).toFixed(1)}, ${((a[1] + b[1]) / 2).toFixed(1)})`);
    });

    // loop-back lines can run outside the box Mermaid measured — widen the drawing to include them
    const bb = svg.querySelector('g').getBBox();
    const pad = 12, vb = [bb.x - pad, bb.y - pad, bb.width + pad * 2, bb.height + pad * 2];
    svg.setAttribute('viewBox', vb.map((v) => v.toFixed(1)).join(' '));
    svg.style.maxWidth = vb[2].toFixed(0) + 'px';
  } catch (err) { /* leave Mermaid's own rendering untouched */ }
}

// Puts every table in a horizontally scrollable wrapper so wide tables use the full width
// available and scroll inside themselves instead of squeezing or overflowing the page.
function wrapTables(viewer) {
  viewer.querySelectorAll('table').forEach((t) => {
    if (t.parentElement && t.parentElement.classList.contains('table-wrap')) return;
    const wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    t.replaceWith(wrap);
    wrap.appendChild(t);
  });
}

// ============================================================
// SHEET 01 — Intake
// ============================================================
const IDEA_DRAFT_KEY = 'poc_idea_draft';

// The idea text is kept locally as it's typed, so a closed tab before "Run discovery" loses nothing.
function restoreIdeaDraft() {
  try {
    const saved = localStorage.getItem(IDEA_DRAFT_KEY);
    if (saved && !$('#idea-input').value) $('#idea-input').value = saved;
  } catch (e) { /* storage unavailable */ }
}
$('#idea-input').addEventListener('input', () => {
  try { localStorage.setItem(IDEA_DRAFT_KEY, $('#idea-input').value); } catch (e) { /* ignore */ }
});

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    $('#idea-input').value = chip.dataset.idea;
    try { localStorage.setItem(IDEA_DRAFT_KEY, chip.dataset.idea); } catch (e) { /* ignore */ }
  });
});

$('#btn-submit-idea').addEventListener('click', async () => {
  const idea = $('#idea-input').value.trim();
  if (!idea) return;
  const btn = $('#btn-submit-idea');
  btn.disabled = true; btn.textContent = 'Running discovery…';

  try {
    const data = await api('/api/project', { method: 'POST', body: JSON.stringify({ idea }) });
    projectId = data.project_id;
    questions = data.questions;
    history.replaceState(null, '', '#project=' + projectId);   // refresh / reopened tab resumes this project
    try { localStorage.removeItem(IDEA_DRAFT_KEY); } catch (e) { /* ignore */ }
    setTitleBlock({ projectId, domain: `${data.domain} (${Math.round(data.confidence * 100)}%)` });
    await refreshDomainCount();
    if (data.learned_new_domain) $('#learned-banner').hidden = false;
    lockIntake();

    dfAnswers = {};
    dfSkipped = {};
    dfIndex = 0;
    dfShowingReview = false;
    dfReturnToReview = false;
    unlock('#panel-discovery');
    showDiscoveryQuestion(0);
  } catch (e) {
    alert('Something went wrong: ' + e.message);
    btn.disabled = false; btn.textContent = 'Run discovery →';
  }
});

// Once a project exists its idea is fixed (changing it would mean a different project).
function lockIntake() {
  $('#idea-input').readOnly = true;
  document.querySelector('.idea-examples').hidden = true;
  $('#btn-submit-idea').hidden = true;
  $('#draft-note').hidden = false;
}

// ============================================================
// SHEET 02 — Discovery: sequential, conversational question flow
// ============================================================
const DF_MICROCOPY = {
  first: "Let's shape your idea into a plan.",
  penultimate: 'A few more details.',
  last: 'Almost there — last question.',
};

function microcopyFor(i, total) {
  if (total <= 1) return DF_MICROCOPY.first;
  if (i === 0) return DF_MICROCOPY.first;
  if (i === total - 1) return DF_MICROCOPY.last;
  if (i === total - 2) return DF_MICROCOPY.penultimate;
  if (i > 0 && i % 3 === 0) return "Let's narrow this down.";
  return '';
}

function humanizeCategory(cat) {
  return (cat || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function updateDiscoveryStatus() {
  const answeredCount = questions.filter(q => dfAnswers[q.id]).length;
  const skippedCount = questions.filter(q => dfSkipped[q.id]).length;
  const doneCount = answeredCount + skippedCount;
  if (dfShowingReview) { $('#discovery-status').textContent = 'reviewing'; return; }
  if (doneCount >= questions.length) {
    $('#discovery-status').textContent = skippedCount > 0 ? `complete (${skippedCount} skipped)` : 'complete';
  } else {
    $('#discovery-status').textContent = skippedCount > 0
      ? `${answeredCount} answered, ${skippedCount} skipped / ${questions.length}`
      : `${answeredCount} / ${questions.length} answered`;
  }
}

function showDiscoveryQuestion(index) {
  dfIndex = Math.max(0, Math.min(index, questions.length - 1));
  dfShowingReview = false;
  $('#discovery-review').hidden = true;
  $('#discovery-flow').hidden = false;
  renderCurrentQuestion();
  updateDiscoveryStatus();
}

// Jump to a specific question from the review screen. Continuing from here
// returns straight to the review instead of marching through every
// remaining question, and answering it doesn't touch any other answer.
function editFromReview(index) {
  dfReturnToReview = true;
  showDiscoveryQuestion(index);
}

function renderCurrentQuestion() {
  const q = questions[dfIndex];
  const total = questions.length;

  // Progress
  $('#df-progress-fill').style.width = `${((dfIndex) / total) * 100 + (100 / total) * 0.15}%`;
  $('#df-progress-label').textContent = `Question ${dfIndex + 1} of ${total}`;

  // Copy
  const microcopyEl = $('#df-microcopy');
  const microcopyText = microcopyFor(dfIndex, total);
  microcopyEl.textContent = microcopyText;
  microcopyEl.hidden = !microcopyText;
  $('#df-category').textContent = humanizeCategory(q.category);
  $('#df-select-hint').hidden = !q.multi_select;
  $('#df-question').textContent = q.text;
  $('#df-skipped-note').hidden = !dfSkipped[q.id];

  // Nav
  $('#df-btn-back').hidden = dfIndex === 0;
  $('#df-btn-to-review').hidden = !dfReturnToReview;
  $('#df-btn-continue').textContent = dfReturnToReview ? 'Save & return to review →' : 'Continue →';

  const isExtra = q.id === ADDITIONAL_INFO_ID;
  $('#df-btn-skip').textContent = isExtra ? 'Nothing more to add — skip →' : 'Not sure / skip this question →';
  $('#df-freetext-input').placeholder = isExtra
    ? 'Optional — e.g. specific requirements, constraints, integrations, reference apps, data you already have…'
    : 'Type your answer…';
  $('#df-freetext-input').rows = isExtra ? 6 : 3;

  const existingAnswer = dfAnswers[q.id] || '';
  const optionsWrap = $('#df-options');
  const freetextWrap = $('#df-freetext');
  const freetextInput = $('#df-freetext-input');
  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');
  const continueBtn = $('#df-btn-continue');

  optionsWrap.innerHTML = '';
  optionsWrap.setAttribute('role', q.multi_select ? 'group' : 'radiogroup');
  otherWrap.hidden = true;
  otherInput.value = '';

  if (q.options && q.options.length) {
    freetextWrap.hidden = true;

    if (q.multi_select) {
      // ---- Checkbox mode: several options may apply at once ----
      const parts = existingAnswer ? existingAnswer.split(' | ').map(p => p.trim()).filter(Boolean) : [];
      const selected = new Set(parts.filter(p => q.options.includes(p)));
      const otherText = parts.find(p => !q.options.includes(p)) || '';
      if (otherText) selected.add(OTHER_LABEL);

      const allOptions = q.options.includes(OTHER_LABEL) ? q.options : [...q.options, OTHER_LABEL];
      allOptions.forEach(opt => {
        const isSelected = selected.has(opt);
        const card = buildOptionCard(opt, isSelected, 'checkbox', opt === OTHER_LABEL);
        card.addEventListener('click', () => toggleMultiOption(q, opt, card));
        optionsWrap.appendChild(card);
      });

      if (selected.has(OTHER_LABEL)) {
        otherWrap.hidden = false;
        otherInput.value = otherText;
      }

      continueBtn.hidden = selected.size === 0;
      continueBtn.disabled = selected.has(OTHER_LABEL) && !otherInput.value.trim();
    } else {
      // ---- Radio mode: exactly one option applies ----
      const allOptions = q.options.includes(OTHER_LABEL) ? q.options : [...q.options, OTHER_LABEL];
      const matchedOption = allOptions.includes(existingAnswer) ? existingAnswer : (existingAnswer ? OTHER_LABEL : '');

      allOptions.forEach(opt => {
        const card = buildOptionCard(opt, opt === matchedOption, 'radio', opt === OTHER_LABEL);
        card.addEventListener('click', () => selectSingleOption(q, opt, card));
        optionsWrap.appendChild(card);
      });

      if (matchedOption === OTHER_LABEL) {
        otherWrap.hidden = false;
        otherInput.value = existingAnswer;
      }

      // Continue is only shown when landing on an already-answered question
      // (i.e. via Back / Edit) so the user can confirm without re-tapping.
      // A fresh tap always advances straight away — see selectSingleOption.
      continueBtn.hidden = !matchedOption;
      continueBtn.disabled = matchedOption === OTHER_LABEL && !existingAnswer.trim();
    }
  } else {
    freetextWrap.hidden = false;
    freetextInput.value = existingAnswer;
    continueBtn.hidden = false;
    continueBtn.disabled = !existingAnswer.trim();
    setTimeout(() => freetextInput.focus(), 50);
  }

  otherInput.oninput = () => {
    continueBtn.hidden = false;
    continueBtn.disabled = !otherInput.value.trim();
  };
  freetextInput.oninput = () => {
    continueBtn.disabled = !freetextInput.value.trim();
  };
}

// Builds one tappable choice card with a radio dot or checkbox indicator.
function buildOptionCard(label, isSelected, kind, isOther) {
  const card = el('button', {
    type: 'button',
    class: 'df-option' + (isSelected ? ' selected' : ''),
    role: kind,
    'aria-checked': isSelected ? 'true' : 'false',
  }, [
    el('span', { class: `df-option-indicator df-option-indicator-${kind}` }),
    el('span', { class: 'df-option-text' }, [
      el('span', { class: 'df-option-label', text: label }),
      ...(isOther ? [el('span', { class: 'df-option-hint', text: 'Write your own answer' })] : []),
    ]),
  ]);
  return card;
}

async function selectSingleOption(q, optionLabel, cardEl) {
  document.querySelectorAll('#df-options .df-option').forEach(c => {
    c.classList.remove('selected'); c.setAttribute('aria-checked', 'false');
  });
  cardEl.classList.add('selected');
  cardEl.setAttribute('aria-checked', 'true');

  const continueBtn = $('#df-btn-continue');
  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');

  if (optionLabel === OTHER_LABEL) {
    otherWrap.hidden = false;
    otherInput.value = dfAnswers[q.id] && !q.options.includes(dfAnswers[q.id]) ? dfAnswers[q.id] : '';
    continueBtn.hidden = false;
    continueBtn.disabled = !otherInput.value.trim();
    otherInput.focus();
    return;
  }

  // A direct tap always advances on its own — no intermediate Continue flash.
  otherWrap.hidden = true;
  continueBtn.hidden = true;
  await saveAnswer(q.id, optionLabel);
  setTimeout(() => { if (dfAnswers[q.id] === optionLabel) goToNextQuestion(); }, 320);
}

function toggleMultiOption(q, optionLabel, cardEl) {
  const isSelected = cardEl.classList.toggle('selected');
  cardEl.setAttribute('aria-checked', isSelected ? 'true' : 'false');

  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');
  const continueBtn = $('#df-btn-continue');

  if (optionLabel === OTHER_LABEL) {
    otherWrap.hidden = !isSelected;
    if (isSelected) otherInput.focus(); else otherInput.value = '';
  }

  const anySelected = document.querySelectorAll('#df-options .df-option.selected').length > 0;
  continueBtn.hidden = !anySelected;
  continueBtn.disabled = !otherWrap.hidden && !otherInput.value.trim();
}

async function saveAnswer(questionId, answerText) {
  answerText = (answerText || '').trim();
  if (!answerText) return;
  dfAnswers[questionId] = answerText;
  delete dfSkipped[questionId];
  updateDiscoveryStatus();
  onAnswersChanged();
  try {
    await api(`/api/project/${projectId}/answer`, { method: 'POST', body: JSON.stringify({ question_id: questionId, answer: answerText }) });
  } catch (e) {
    alert('Could not save answer: ' + e.message);
  }
}

async function skipCurrentQuestion() {
  const q = questions[dfIndex];
  delete dfAnswers[q.id];
  dfSkipped[q.id] = true;
  updateDiscoveryStatus();
  onAnswersChanged();
  try {
    await api(`/api/project/${projectId}/skip`, { method: 'POST', body: JSON.stringify({ question_id: q.id }) });
  } catch (e) {
    alert('Could not skip question: ' + e.message);
    return;
  }
  goToNextQuestion();
}

async function confirmCurrentAnswerAndAdvance() {
  const q = questions[dfIndex];
  if (q.options && q.options.length) {
    if (q.multi_select) {
      const selectedCards = [...document.querySelectorAll('#df-options .df-option.selected')];
      if (!selectedCards.length) return;
      const otherWrap = $('#df-other-wrap');
      const parts = [];
      selectedCards.forEach(card => {
        const label = card.querySelector('.df-option-label').textContent;
        if (label === OTHER_LABEL) {
          const val = $('#df-other-input').value.trim();
          if (val) parts.push(val);
        } else {
          parts.push(label);
        }
      });
      if (!parts.length) return;
      await saveAnswer(q.id, parts.join(' | '));
    } else {
      const otherWrap = $('#df-other-wrap');
      if (!otherWrap.hidden) {
        const val = $('#df-other-input').value.trim();
        if (!val) return;
        await saveAnswer(q.id, val);
      } else if (!dfAnswers[q.id]) {
        return; // nothing selected yet
      }
    }
  } else {
    const val = $('#df-freetext-input').value.trim();
    if (!val) return;
    await saveAnswer(q.id, val);
  }
  goToNextQuestion();
}

function goToNextQuestion() {
  if (dfReturnToReview) {
    dfReturnToReview = false;
    showDiscoveryReview();
    return;
  }
  if (dfIndex < questions.length - 1) {
    showDiscoveryQuestion(dfIndex + 1);
  } else {
    showDiscoveryReview();
  }
}

$('#df-btn-continue').addEventListener('click', confirmCurrentAnswerAndAdvance);
$('#df-freetext-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) confirmCurrentAnswerAndAdvance();
});
$('#df-other-input').addEventListener('keydown', e => { if (e.key === 'Enter') confirmCurrentAnswerAndAdvance(); });
$('#df-btn-back').addEventListener('click', () => {
  if (dfIndex > 0) showDiscoveryQuestion(dfIndex - 1);
});
$('#df-btn-to-review').addEventListener('click', () => {
  dfReturnToReview = false;
  showDiscoveryReview();
});
$('#df-btn-skip').addEventListener('click', skipCurrentQuestion);

// ---- Review / confirmation screen ----
function showDiscoveryReview() {
  dfShowingReview = true;
  dfReturnToReview = false;
  $('#discovery-flow').hidden = true;
  $('#discovery-review').hidden = false;
  $('#reopen-note').hidden = !hasGeneratedBefore;
  updateDiscoveryStatus();
  renderReview();
  updateRunButton();
}

function renderReview() {
  const container = $('#df-review-groups');
  container.innerHTML = '';

  const seenCategories = [];
  const byCategory = {};
  questions.forEach(q => {
    if (!byCategory[q.category]) { byCategory[q.category] = []; seenCategories.push(q.category); }
    byCategory[q.category].push(q);
  });

  seenCategories.forEach(cat => {
    const section = el('div', { class: 'df-review-section' }, [
      el('div', { class: 'df-review-section-title', text: humanizeCategory(cat) }),
    ]);
    byCategory[cat].forEach(q => {
      const idx = questions.indexOf(q);
      const isSkipped = !!dfSkipped[q.id];
      const rawAnswer = dfAnswers[q.id] || (isSkipped ? (q.id === ADDITIONAL_INFO_ID ? 'Nothing added' : 'Skipped') : '(not answered)');
      const answer = rawAnswer.includes(' | ') ? rawAnswer.split(' | ').join(', ') : rawAnswer;
      const editBtn = el('button', { type: 'button', class: 'df-review-edit', text: isSkipped ? 'Answer' : 'Edit' });
      editBtn.addEventListener('click', () => editFromReview(idx));
      section.appendChild(el('div', { class: 'df-review-item' }, [
        el('div', { class: 'df-review-item-body' }, [
          el('p', { class: 'df-review-q', text: q.text }),
          el('p', { class: 'df-review-a' + (isSkipped ? ' df-review-a-skipped' : ''), text: answer }),
        ]),
        editBtn,
      ]));
    });
    container.appendChild(section);
  });
}

$('#df-btn-review-back').addEventListener('click', () => showDiscoveryQuestion(questions.length - 1));

// ============================================================
// Run AI Agents — the button locks the moment it is clicked (no double runs) and only
// unlocks again if the agent process fails, so the person can retry.
// ============================================================
const RUN_LABELS = {
  idle: () => (hasGeneratedBefore ? 'Re-run AI Agents →' : 'Run AI Agents →'),
  running: () => 'Running AI Agents…',
  done: () => 'AI Agents completed ✓',
  error: () => 'Retry AI Agents →',
  external: () => 'AI Agents running on the server…',
};
let pipelineRanThisSession = false;   // agent outputs exist in server memory -> resolve/export are possible

function updateRunButton() {
  const btn = $('#btn-run-agents');
  btn.textContent = RUN_LABELS[runState]();
  btn.disabled = runState === 'running' || runState === 'done' || runState === 'external';
  // while agents work, the answers must not change underneath them
  $('#discovery-review').classList.toggle('is-busy', runState === 'running' || runState === 'external');
  $('#df-btn-review-back').disabled = runState === 'running' || runState === 'external';
}

// Any change to an answer means the last package no longer matches -> allow a fresh run.
function onAnswersChanged() {
  nextAgentIndex = 0;
  if (runState === 'done' || runState === 'error') runState = 'idle';
  updateRunButton();
}

function resetAgentPanel() {
  $('#agent-log').innerHTML = '';
  $('#qa-verdict').hidden = true;
  $('#agent-note').hidden = true;
  $('#btn-export').hidden = true;
  lastHandoffStatus = null;
  updateResolveButton();
}

$('#btn-run-agents').addEventListener('click', async () => {
  if (runState === 'running' || runState === 'external') return;   // hard guard against multi-click
  const allHandled = questions.every(q => dfAnswers[q.id] || dfSkipped[q.id]);
  if (!allHandled) { alert('A few questions still need an answer or a skip.'); return; }

  runState = 'running';
  updateRunButton();                 // disabled synchronously, before any await
  try {
    unlock('#panel-agents');
    if (!agentMeta.length) await loadAgentMeta();
    if (nextAgentIndex === 0) {
      resetAgentPanel();
      drawSchematic();
    } else {
      logLine(`↻ Retrying from ${agentMeta[nextAgentIndex].label}…`);
    }
    const ok = await runAgentPipeline(nextAgentIndex);
    if (ok) hasGeneratedBefore = true;
    runState = ok ? 'done' : 'error';
  } catch (e) {
    logLine(`✗ Agent run failed: ${e.message}`);
    $('#agents-status').textContent = 'error';
    runState = 'error';
  }
  updateRunButton();
  updateResolveButton();   // the run has fully finished (incl. auto-resolution) — only now may Resolve show
});

// ============================================================
// SHEET 03 — Agent assembly (schematic)
// ============================================================
async function loadAgentMeta() {
  const data = await api(`/api/project/${projectId}/agents`);
  agentMeta = data.agents;
}

function nodeX(i) { return NODE_X_START + i * NODE_X_GAP; }

// Process-flow notation: nodes are joined by straight, single-direction, right-angle (horizontal)
// connectors with arrowheads.
function drawSchematic() {
  const svg = $('#schematic');
  svg.innerHTML = '';
  const ns = 'http://www.w3.org/2000/svg';

  const totalWidth = NODE_X_START * 2 + Math.max(0, agentMeta.length - 1) * NODE_X_GAP;
  svg.setAttribute('viewBox', `0 0 ${totalWidth} 160`);

  for (let i = 0; i < agentMeta.length - 1; i++) {
    const x1 = nodeX(i) + NODE_R, x2 = nodeX(i + 1) - NODE_R;
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', x1);
    line.setAttribute('y1', NODE_Y);
    line.setAttribute('x2', x2 - 9);
    line.setAttribute('y2', NODE_Y);
    line.setAttribute('class', 'trace-line');
    line.setAttribute('id', `trace-${i}`);
    svg.appendChild(line);

    const arrow = document.createElementNS(ns, 'polygon');
    arrow.setAttribute('points', `${x2},${NODE_Y} ${x2 - 10},${NODE_Y - 5} ${x2 - 10},${NODE_Y + 5}`);
    arrow.setAttribute('class', 'trace-arrow');
    arrow.setAttribute('id', `arrow-${i}`);
    svg.appendChild(arrow);
  }

  agentMeta.forEach((agent, i) => {
    const g = document.createElementNS(ns, 'g');
    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('cx', nodeX(i)); circle.setAttribute('cy', NODE_Y); circle.setAttribute('r', NODE_R);
    circle.setAttribute('class', 'node-circle'); circle.setAttribute('id', `node-${i}`);
    g.appendChild(circle);

    const check = document.createElementNS(ns, 'text');
    check.setAttribute('x', nodeX(i)); check.setAttribute('y', NODE_Y + 6);
    check.setAttribute('text-anchor', 'middle'); check.setAttribute('class', 'node-check'); check.setAttribute('id', `check-${i}`);
    check.textContent = '✓';
    g.appendChild(check);

    const idx = document.createElementNS(ns, 'text');
    idx.setAttribute('x', nodeX(i)); idx.setAttribute('y', NODE_Y + 5);
    idx.setAttribute('text-anchor', 'middle'); idx.setAttribute('id', `idx-${i}`);
    idx.setAttribute('class', 'node-index');
    idx.textContent = `0${i + 1}`;
    g.appendChild(idx);

    const label1 = document.createElementNS(ns, 'text');
    label1.setAttribute('x', nodeX(i)); label1.setAttribute('y', NODE_Y + NODE_R + 22);
    label1.setAttribute('text-anchor', 'middle'); label1.setAttribute('class', 'node-label'); label1.setAttribute('id', `label-${i}`);
    label1.textContent = agent.label;
    g.appendChild(label1);

    const label2 = document.createElementNS(ns, 'text');
    label2.setAttribute('x', nodeX(i)); label2.setAttribute('y', NODE_Y + NODE_R + 36);
    label2.setAttribute('text-anchor', 'middle'); label2.setAttribute('class', 'node-label node-sublabel');
    label2.textContent = agent.note;
    g.appendChild(label2);

    svg.appendChild(g);
  });
}

function setNodeState(i, state) {
  const circle = $(`#node-${i}`), label = $(`#label-${i}`), check = $(`#check-${i}`), idx = $(`#idx-${i}`);
  if (!circle) return;
  circle.classList.remove('active', 'done', 'error'); label.classList.remove('active', 'done', 'error');
  if (state === 'active') {
    circle.classList.add('active'); label.classList.add('active');
  } else if (state === 'error') {
    circle.classList.add('error'); label.classList.add('error');
  } else if (state === 'done') {
    circle.classList.add('done'); label.classList.add('done'); check.classList.add('show');
    idx.style.display = 'none';
    const trace = $(`#trace-${i}`), arrow = $(`#arrow-${i}`);
    if (trace) trace.classList.add('charged');
    if (arrow) arrow.classList.add('charged');
  }
}

function logLine(text, done = false) {
  const log = $('#agent-log');
  log.appendChild(el('div', { text, class: done ? 'log-done' : '' }));
  log.scrollTop = log.scrollHeight;
}

// Returns true when all agents ran; false if one failed (the run button then re-enables to retry
// from the agent that failed, without redoing the ones that already succeeded).
async function runAgentPipeline(startIndex = 0) {
  $('#agents-status').textContent = 'running…';
  $('#btn-resolve-issues').hidden = true;

  for (let i = startIndex; i < agentMeta.length; i++) {
    setNodeState(i, 'active');
    logLine(`⏳ ${agentMeta[i].label} reading project context…`);
    try {
      const data = await api(`/api/project/${projectId}/agent/${i}`, { method: 'POST' });
      setNodeState(i, 'done');
      logLine(`✓ ${agentMeta[i].label} — ${data.summary}`, true);
      if (agentMeta[i].role === 'ai_handoff_validation') showQaVerdict(data);
    } catch (e) {
      setNodeState(i, 'error');
      logLine(`✗ ${agentMeta[i].label} failed: ${e.message}`);
      $('#agents-status').textContent = 'error';
      nextAgentIndex = i;
      return false;
    }
  }
  nextAgentIndex = 0;
  pipelineRanThisSession = true;

  // The 5 documents existing isn't the same as the package being complete — automatically
  // run a short chain of "resolve" passes (each its own quick request, so no single call
  // risks a host/proxy timeout) until validation comes back clean or a small round cap is
  // hit. This never requires the person to notice a gap and click anything.
  await autoResolveGaps();

  $('#agents-status').textContent = `complete — ${agentMeta.length}/${agentMeta.length}`;
  $('#btn-export').hidden = false;
  // Only now that auto-resolution has finished can the manual "Resolve issues" fallback appear.
  updateResolveButton();
  return true;
}

const MAX_AUTO_RESOLVE_ROUNDS = 4;

async function autoResolveGaps() {
  for (let round = 1; round <= MAX_AUTO_RESOLVE_ROUNDS; round++) {
    let data;
    try {
      data = await api(`/api/project/${projectId}/resolve`, { method: 'POST' });
    } catch (e) {
      logLine(`⚠ Auto-resolve round ${round} failed: ${e.message} — you can retry with "Resolve issues" below.`);
      return;
    }
    if (!data.resolved) {
      // Nothing left to fix (or nothing was flagged in the first place).
      return;
    }
    logLine(`↻ Auto-resolve round ${round}: fixed ${data.issues_addressed} issue(s) — re-ran: ${data.agents_rerun.join(', ')}`, true);
    showQaVerdict({ output: data.validation_output, consistency_notes: data.consistency_notes });
    if (data.artefacts && data.artefacts.length) {
      unlock('#panel-artefacts');
      renderArtefacts(data.artefacts);
    }
    const status = data.validation_output && data.validation_output.final_handoff_status;
    const clean = status === 'READY FOR DESIGN AGENT'
      && !(data.validation_output.conflicts_found || []).length
      && !(data.validation_output.missing_information || []).length;
    if (clean) return;
  }
  logLine(`⚠ Reached the auto-resolve round limit (${MAX_AUTO_RESOLVE_ROUNDS}) with some items still flagged — review below, or click "Resolve issues" to try another round.`);
}

function showQaVerdict(data) {
  const status = (data.output && data.output.final_handoff_status) || 'unknown';
  lastHandoffStatus = status;
  const box = $('#qa-verdict');
  box.hidden = false;
  box.className = `qa-verdict ${statusSlug(status)}`;

  const notes = data.consistency_notes || [];
  const notesHtml = notes.length ? '<ul>' + notes.map(n => `<li>${escapeHtml(n)}</li>`).join('') + '</ul>' : '';
  box.innerHTML = `HANDOFF STATUS: ${escapeHtml(status)}` + notesHtml;
  // NOTE: deliberately does not touch the Resolve button — see updateResolveButton().
}

// "Resolve issues" is a manual fallback, offered ONLY once the automatic resolution has finished
// (never while the agents or the auto-resolve rounds are still running) and only if issues remain.
function updateResolveButton() {
  const stillIssues = !!lastHandoffStatus && lastHandoffStatus !== 'READY FOR DESIGN AGENT';
  $('#btn-resolve-issues').hidden = !(pipelineRanThisSession && stillIssues && runState !== 'running');
}

// ============================================================
// SHEET 04 — Artefacts (5-document package)
// ============================================================
let currentArtefacts = [];
let activeArtefactIndex = 0;

$('#btn-export').addEventListener('click', async () => {
  unlock('#panel-artefacts');
  const btn = $('#btn-export');
  btn.disabled = true; btn.textContent = 'Exporting…';
  try {
    const data = await api(`/api/project/${projectId}/export`, { method: 'POST' });
    renderArtefacts(data.artefacts);
  } catch (e) {
    alert('Export failed: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Export 5-document package →';
  }
});

$('#btn-resolve-issues').addEventListener('click', async () => {
  const btn = $('#btn-resolve-issues');
  btn.disabled = true; btn.textContent = 'Resolving…';
  try {
    const data = await api(`/api/project/${projectId}/resolve`, { method: 'POST' });
    if (!data.resolved) {
      alert(data.reason || 'Nothing to resolve.');
      return;
    }
    logLine(`↻ Resolved ${data.issues_addressed} issue(s) — re-ran: ${data.agents_rerun.join(', ')}`, true);
    showQaVerdict({ output: data.validation_output, consistency_notes: data.consistency_notes });
    if (data.agents) {
      data.agents.forEach((a, i) => { if (agentMeta[i]) logLine(`✓ ${agentMeta[i].label} — ${a.summary}`); });
    }
    if (data.artefacts && data.artefacts.length) {
      unlock('#panel-artefacts');
      renderArtefacts(data.artefacts);
    }
  } catch (e) {
    alert('Could not resolve issues: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '⚙ Resolve issues →';
    updateResolveButton();
  }
});

function renderArtefacts(artefacts) {
  currentArtefacts = artefacts;
  activeArtefactIndex = 0;

  const tabs = $('#artefact-tabs');
  tabs.innerHTML = '';
  tabs.hidden = false;
  $('#artefact-controls').hidden = false;

  artefacts.forEach((a, i) => {
    const tab = el('button', { class: 'tab-btn' + (i === 0 ? ' active' : ''), text: a.title.split('—')[0].trim() || a.type });
    tab.addEventListener('click', () => {
      activeArtefactIndex = i;
      document.querySelectorAll('#artefact-tabs .tab-btn').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      renderDoc(a.content_markdown);
    });
    tabs.appendChild(tab);
  });

  if (artefacts.length) renderDoc(artefacts[0].content_markdown);
}

function renderDoc(markdown) {
  const viewer = $('#doc-viewer');
  viewer.innerHTML = window.marked ? marked.parse(markdown, { breaks: true, gfm: true }) : markdown;
  wrapTables(viewer);
  renderMermaidBlocks(viewer);
  // Switching artifacts replaces this element's content but not the
  // element itself, so the browser keeps whatever scroll position was
  // left over from the PREVIOUS document — on a shorter new document
  // that can even leave the viewer scrolled past its own content.
  // Always land at the top of the newly-selected document.
  viewer.scrollTop = 0;
}

$('#btn-download-current').addEventListener('click', () => {
  const a = currentArtefacts[activeArtefactIndex];
  if (a) downloadMarkdown(`${a.type}.md`, a.content_markdown);
});

// "Download all" -> ONE .zip containing every document (no repeated browser download prompts).
$('#btn-download-all').addEventListener('click', () => {
  if (!currentArtefacts.length) return;
  const files = currentArtefacts.map(a => ({ name: `${a.type}.md`, content: a.content_markdown }));
  const stamp = projectId ? projectId.slice(0, 8) : 'package';
  downloadBlob(`specification-package-${stamp}.zip`, buildZip(files));
});

// ============================================================
// Minimal ZIP writer (store / no compression — the documents are small text files), so the
// download works with no extra library and no network. Produces a standard .zip.
// ============================================================
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

function buildZip(files) {
  const enc = new TextEncoder();
  const now = new Date();
  const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
  const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  const chunks = [], central = [];
  let offset = 0;

  files.forEach(f => {
    const name = enc.encode(f.name), data = enc.encode(f.content), crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true); // UTF-8 names
    local.setUint16(8, 0, true); local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
    local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true); local.setUint16(28, 0, true);
    chunks.push(new Uint8Array(local.buffer), name, data);

    const cen = new DataView(new ArrayBuffer(46));
    cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
    cen.setUint16(10, 0, true); cen.setUint16(12, dosTime, true); cen.setUint16(14, dosDate, true);
    cen.setUint32(16, crc, true); cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
    cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
    central.push(new Uint8Array(cen.buffer), name);

    offset += 30 + name.length + data.length;
  });

  const centralSize = central.reduce((n, c) => n + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, centralSize, true); end.setUint32(16, offset, true);
  return new Blob([...chunks, ...central, new Uint8Array(end.buffer)], { type: 'application/zip' });
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ============================================================
// Resume / reopen — restores the WHOLE process for a saved project: the idea, every question
// with its answer (editable), the agent run, and the generated documents.
// ============================================================
async function resumeProject(id) {
  let data;
  try {
    data = await api(`/api/project/${id}/session`);
  } catch (e) {
    alert('Could not open this project: ' + e.message);
    history.replaceState(null, '', location.pathname);
    location.reload();
    return;
  }
  projectId = data.project_id;
  questions = data.questions || [];
  dfAnswers = {}; dfSkipped = {};
  questions.forEach(q => {
    if (q.status === 'answered' && q.answer) dfAnswers[q.id] = q.answer;
    else if (q.status === 'skipped') dfSkipped[q.id] = true;
  });
  const conf = data.confidence != null ? ` (${Math.round(data.confidence * 100)}%)` : '';
  setTitleBlock({ projectId, domain: data.domain ? data.domain + conf : null });
  refreshDomainCount();
  $('#idea-input').value = data.business_idea || '';
  lockIntake();

  const artefacts = data.artefacts || [];
  hasGeneratedBefore = artefacts.length > 0;
  pipelineRanThisSession = false;
  if (data.agents_running) runState = 'external';

  if (questions.length) {
    unlock('#panel-discovery');
    const firstOpen = questions.findIndex(q => !dfAnswers[q.id] && !dfSkipped[q.id]);
    if (firstOpen >= 0 && !hasGeneratedBefore) showDiscoveryQuestion(firstOpen);   // carry on where they stopped
    else showDiscoveryReview();
  } else if (hasGeneratedBefore) {
    logLine('ℹ This project was saved before questions and answers were recorded, so only its documents can be shown.');
  }

  if (hasGeneratedBefore) await restoreGeneratedView(data, artefacts);
  if (data.agents_running) {
    unlock('#panel-agents');
    const note = $('#agent-note');
    note.textContent = 'The AI agents are still working on this project on the server. Reopen it in a few minutes to see the result.';
    note.hidden = false;
  }
  updateRunButton();
}

async function restoreGeneratedView(data, artefacts) {
  unlock('#panel-agents');
  await loadAgentMeta();
  drawSchematic();
  const log = data.agent_log || [];
  const finished = new Set(log.map(a => a.agent));
  agentMeta.forEach((m, i) => { if (finished.has(m.role) || !log.length) setNodeState(i, 'done'); });
  log.forEach(a => logLine(`✓ ${a.label || a.agent} — ${a.summary}`, true));
  if (!log.length) logLine('✓ Package generated in an earlier session.', true);
  $('#agents-status').textContent = `complete — ${agentMeta.length}/${agentMeta.length}`;
  if (data.handoff_status) {
    showQaVerdict({ output: { final_handoff_status: data.handoff_status }, consistency_notes: data.consistency_notes || [] });
  }
  unlock('#panel-artefacts');
  renderArtefacts(artefacts);
}

// ============================================================
// Startup — runs last, once every function and constant above exists.
// The URL carries the open project (#project=<id>), so a refresh, a browser "reopen closed tab"
// or a bookmarked link lands back on the same project instead of an empty form.
// ============================================================
(function bootstrapView() {
  const hashProjectId = (location.hash.match(/project=([\w-]+)/) || [])[1];
  if (hashProjectId) {
    showPipelineView();
    resumeProject(hashProjectId);
  } else if (sessionStorage.getItem('poc_view') === 'pipeline') {
    sessionStorage.removeItem('poc_view');
    showPipelineView();
    restoreIdeaDraft();
  } else {
    loadDashboard();
  }
})();
