/* Shared Policy editor + Policy diff UI for the guide pages (needs live_server.py for the /api/policy endpoints).
 *
 *   const pt = PolicyTools.mount({
 *     polEl, diffEl,                 // containers to fill
 *     sandboxes: ['egress-demo'],     // sandboxes the tool may edit (the server enforces its own allow-list too)
 *     getLast: () => ({prompt, answer, events, version}) | null,   // last run of the page
 *     rerun: async (prompt) => {}    // re-run a prompt; must update what getLast() returns
 *   });
 *   pt.openEditor(); pt.openDiff();  // call when the tab is shown
 * The host page must define the CSS variables --panel --line --ink --sub --green --red --amber --okbg --nobg --warnbg --code --bg.
 */
(function () {
  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const H = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
  const api = async (path, body) => {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : undefined);
    let j = {}; try { j = await r.json(); } catch (e) { /* non-JSON error page */ }
    return j;
  };

  const CSS = `
.pt-btn{cursor:pointer;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:5px 12px;font:inherit}
.pt-btn.primary{background:var(--green);color:#111;border-color:var(--green);font-weight:600}
.pt input[type=text],.pt select,.pt textarea{width:100%;padding:5px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}
.pt .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}
.pt .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.pt .sub{color:var(--sub);font-size:.85rem}.pt h2{font-size:1.05rem;margin:0 0 6px}
.pt label{display:block;font-size:.78rem;color:var(--sub);margin-bottom:2px}.pt label.inl{display:inline-flex;gap:4px;align-items:center;font-size:.85rem;color:var(--ink)}
.pt code,.pt pre{background:var(--code);border-radius:6px;font:12.5px ui-monospace,monospace}.pt code{padding:1px 5px}.pt pre{padding:9px;overflow-x:auto;margin:6px 0;white-space:pre-wrap;word-break:break-word}
.pt .tag{display:inline-block;font-size:.72rem;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--sub)}
.pt .tag.chg{border-color:var(--amber);color:var(--amber)}
.pt .chip{display:inline-block;padding:2px 9px;border-radius:99px;font-size:.8rem;margin:2px 4px 2px 0;border:1px solid var(--line)}
.pt .chip.a{background:var(--okbg);border-color:var(--green)}.pt .chip.d{background:var(--nobg);border-color:var(--red)}.pt .chip.n{background:var(--warnbg);border-color:var(--amber)}
.pt .verdict{padding:9px 12px;border-radius:8px;font-weight:600;margin-top:8px}.pt .verdict.ok{background:var(--okbg);border:1px solid var(--green)}.pt .verdict.warn{background:var(--warnbg);border:1px solid var(--amber)}
.pt .ev{display:flex;gap:8px;padding:6px 8px;border-radius:8px;margin:4px 0;border:1px solid var(--line);font:12.5px ui-monospace,monospace;word-break:break-all}.pt .ev.a{background:var(--okbg);border-color:var(--green)}.pt .ev.d{background:var(--nobg);border-color:var(--red)}.pt .ev b{min-width:70px}
.pt .grid2{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-top:6px}.pt .col2{display:grid;gap:10px;grid-template-columns:1fr 1fr}@media(max-width:760px){.pt .col2{grid-template-columns:1fr}}
.pt table{border-collapse:collapse;width:100%}.pt th,.pt td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top;font-size:.88rem;word-break:break-word}.pt .scroll{overflow-x:auto}
.pt td:last-child{white-space:nowrap}.pt .rm{white-space:nowrap;padding:1px 8px;font-size:.78rem;margin:1px 0;cursor:pointer;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px}
.pt .y span{display:block;white-space:pre-wrap;word-break:break-all}.pt .y .add{background:var(--okbg);border-left:3px solid var(--green)}.pt .y .del{background:var(--nobg);border-left:3px solid var(--red)}.pt .y .gap{color:var(--sub);font-style:italic}
.pt .dl{margin:3px 0;padding:4px 8px;border-radius:6px;border:1px solid var(--line)}.pt .dl.add{background:var(--okbg);border-color:var(--green)}.pt .dl.del{background:var(--nobg);border-color:var(--red)}.pt .dl.chg{background:var(--warnbg);border-color:var(--amber)}.pt .dl small{color:var(--sub)}
`;

  function mount(cfg) {
    if (!document.getElementById('pt-style')) { const st = H('style'); st.id = 'pt-style'; st.textContent = CSS; document.head.append(st); }
    const sbs = cfg.sandboxes, opts = sbs.map(s => `<option>${esc(s)}</option>`).join('');
    cfg.polEl.classList.add('pt'); cfg.diffEl.classList.add('pt');
    cfg.polEl.innerHTML = `
<div class="card"><h2>Policy editor</h2>
<div class="verdict warn">This changes the <b>live</b> network policy of a running sandbox. Opening egress to a host can create an exfiltration path. <b>Reset to default</b> re-applies the snapshot taken when this server first saw the sandbox (before any edit). Every change is logged in <code>state/logs/policy_changes.log</code>.</div>
<div class="row" style="margin-top:8px"><div><label>Sandbox</label><select id="pt-sb">${opts}</select></div><span class="tag" id="pt-ver">...</span><span class="tag" id="pt-base"></span><button class="pt-btn" id="pt-refresh">Refresh</button><button class="pt-btn" id="pt-reset">Reset to default</button><span id="pt-conf" hidden><b>Re-apply the baseline?</b> <button class="pt-btn primary" id="pt-yes">Yes, reset</button><button class="pt-btn" id="pt-no">Cancel</button></span></div><div class="sub" id="pt-msg" style="margin-top:6px"></div></div>
<div class="card"><h2>Default policy <span class="tag" id="pt-dmeta"></span> <span class="tag" id="pt-dmatch"></span></h2>
<div class="sub">The YAML that <b>Reset to default</b> re-applies. It is the policy this server first saw for the sandbox. Change it here if that snapshot was not the policy you consider the default (for example it already had manual edits).</div>
<div class="row" style="margin-top:6px"><button class="pt-btn primary" id="pt-dreset">Reset live policy to this default</button><button class="pt-btn" id="pt-dsave">Save the current live policy as the default</button><button class="pt-btn" id="pt-dedit">Edit default YAML</button><button class="pt-btn" id="pt-dtoed">Load default into the editor below</button><span id="pt-dconf" hidden><b id="pt-dconft"></b> <button class="pt-btn primary" id="pt-dyes">Yes</button><button class="pt-btn" id="pt-dno">Cancel</button></span></div>
<details id="pt-dwrap"><summary class="sub">Show default YAML</summary><textarea id="pt-dyaml" rows="12" readonly style="font:12px ui-monospace,monospace"></textarea><div class="row" style="margin-top:6px" id="pt-dedrow" hidden><button class="pt-btn primary" id="pt-dsaveyaml">Save as default</button><button class="pt-btn" id="pt-dcancel">Cancel edit</button><span class="sub">Saving only changes the stored default; press Reset afterwards to apply it.</span></div></details></div>
<div class="card"><h2>Allow something that was blocked</h2><div class="sub">Blocked in the last run. Click one to prefill the form, or fill it in by hand. A tool can connect through <i>several</i> binaries (for example <code>git</code> and its helper <code>git-remote-http</code>): list each, comma separated.</div><div id="pt-den" style="margin:6px 0"></div>
<div class="grid2"><div><label>Host</label><input type="text" id="pt-h" placeholder="gitlab.com"></div><div><label>Port</label><input type="text" id="pt-p" value="443"></div>
<div><label>Binaries allowed to connect (comma separated, at least one)</label><input type="text" id="pt-b" value="/usr/bin/curl"></div><div><label>Rule name (optional)</label><input type="text" id="pt-n" placeholder="my_rule"></div></div>
<div class="row" style="margin-top:6px"><label class="inl"><input type="radio" name="pt-m" value="full" checked> Allow all methods and paths</label><label class="inl"><input type="radio" name="pt-m" value="rest"> REST allow-list:</label><span id="pt-meths" class="row"></span><input type="text" id="pt-path" value="/**" style="width:140px" title="path glob"></div>
<div class="sub" style="margin-top:6px">Command that will run:</div><pre id="pt-cmd"></pre>
<div class="row"><button class="pt-btn" id="pt-prev">Preview (dry run)</button><button class="pt-btn primary" id="pt-apply">Apply</button><button class="pt-btn primary" id="pt-re">Apply and re-run last prompt</button></div>
<details id="pt-out" hidden><summary class="sub">Preview / result output</summary><pre id="pt-pre"></pre></details></div>
<div class="card"><h2>Current network policy</h2><div class="scroll"><table id="pt-net"></table></div></div>
<div class="card" id="pt-cmpcard" hidden><h2>Before / after</h2><div id="pt-cmp"></div></div>
<details class="card"><summary><b>Advanced: edit the full policy YAML</b></summary><div class="sub" style="margin-top:6px">Applies with <code>openshell policy set --wait</code>. Filesystem, Landlock and process sections are normally fixed when a sandbox is created, so edit <code>network_policies</code>.</div><textarea id="pt-yaml" rows="14" style="font:12px ui-monospace,monospace"></textarea><div class="row" style="margin-top:6px"><button class="pt-btn primary" id="pt-setyaml">Apply YAML</button></div></details>
<div class="card"><h2>Revision history</h2><pre id="pt-hist"></pre></div>`;
    cfg.diffEl.innerHTML = `
<div class="card"><h2>Policy revisions: what changed</h2><div class="sub">Compare any two revisions of a sandbox's live policy (from <code>openshell policy list</code> / <code>policy get --rev N</code>). <span class="chip a">added</span> <span class="chip d">removed</span> <span class="chip n">changed</span></div>
<div class="row" style="margin-top:8px"><div><label>Sandbox</label><select id="pt-dsb">${opts}</select></div><div><label>From (older)</label><select id="pt-da"></select></div><div><label>To (newer)</label><select id="pt-db"></select></div><button class="pt-btn" id="pt-dswap">Swap</button><button class="pt-btn" id="pt-dprev">Previous → this</button><button class="pt-btn" id="pt-dref">Refresh list</button></div><div class="sub" id="pt-dmsg" style="margin-top:6px"></div></div>
<div class="card" id="pt-dsum" hidden></div>
<div class="card" id="pt-dstruct" hidden><h2>Structured changes</h2><div id="pt-dstructbody"></div></div>
<div class="card" id="pt-draw" hidden><h2>YAML line diff</h2><div class="sub">Unchanged stretches are collapsed.</div><pre class="y" id="pt-drawbody"></pre></div>`;
    const $ = s => (cfg.polEl.querySelector(s) || cfg.diffEl.querySelector(s));
    const psb = () => $('#pt-sb').value;

    // ---------------- editor
    ['GET', 'HEAD', 'POST', 'PUT', 'DELETE'].forEach(m => { const l = H('label', 'inl', `<input type="checkbox" value="${m}" ${m === 'GET' ? 'checked' : ''}> ${m}`); $('#pt-meths').append(l); });
    const formReq = mode => {
      const mm = cfg.polEl.querySelector('input[name=pt-m]:checked').value;
      return { sandbox: psb(), mode, endpoint: { host: $('#pt-h').value.trim(), port: +$('#pt-p').value || 0, mode: mm,
        methods: [...cfg.polEl.querySelectorAll('#pt-meths input:checked')].map(x => x.value), path: $('#pt-path').value.trim() || '/**',
        binaries: $('#pt-b').value.split(',').map(x => x.trim()).filter(Boolean), rule_name: $('#pt-n').value.trim() || undefined } };
    };
    const cmdText = () => {
      const r = formReq('preview'), e = r.endpoint, h = e.host || '<host>';
      let c = `openshell policy update ${r.sandbox} --add-endpoint ${h}:${e.port}` + (e.mode === 'rest' ? '::rest:enforce' : ':full');
      if (e.mode === 'rest') (e.methods.length ? e.methods : ['GET']).forEach(m => c += ` --add-allow ${h}:${e.port}:${m}:${e.path}`);
      e.binaries.forEach(b => c += ' --binary ' + b); if (e.rule_name) c += ' --rule-name ' + e.rule_name;
      return c + ' --wait';
    };
    const setCmd = () => { $('#pt-cmd').textContent = cmdText(); };
    ['pt-h', 'pt-p', 'pt-b', 'pt-n', 'pt-path'].forEach(i => $('#' + i).oninput = setCmd);
    cfg.polEl.querySelectorAll('input[name=pt-m],#pt-meths input').forEach(x => x.onchange = setCmd);
    $('#pt-sb').onchange = () => { loadPolicy(); setCmd(); };
    setCmd();

    function parseDenied(e) {
      const b = (e.text.match(/^(\/\S+?)\(\d+\)/) || [])[1] || ''; let host = '', port = '';
      const m = e.text.match(/->\s+(?:[A-Z]+\s+)?(https?:\/\/)?([A-Za-z0-9.*-]+)(?::(\d+))?/);
      if (m) { host = m[2]; port = m[3] || (m[1] === 'http://' ? '80' : '443'); }
      return { bin: b, host, port };
    }
    function renderDenied() {
      const box = $('#pt-den'); box.innerHTML = ''; const last = cfg.getLast && cfg.getLast();
      const ev = ((last && last.events) || []).filter(e => e.verdict === 'DENIED');
      if (!ev.length) { box.append(H('span', 'sub', 'Nothing was denied in the last run (or no run yet). Run a sample that gets blocked first.')); return; }
      const seen = new Set();
      ev.forEach(e => {
        const p = parseDenied(e); if (!p.host) return; const k = p.bin + p.host + p.port; if (seen.has(k)) return; seen.add(k);
        const b = H('button', 'chip d', `${esc(p.bin || 'binary?')} → ${esc(p.host)}:${esc(p.port)}  (use this)`); b.style.cursor = 'pointer';
        b.onclick = () => { $('#pt-h').value = p.host; $('#pt-p').value = p.port; if (p.bin) $('#pt-b').value = p.bin; setCmd(); };
        box.append(b);
      });
    }
    async function loadPolicy() {
      $('#pt-msg').textContent = 'Loading...'; const j = await api('/api/policy?sandbox=' + psb());
      if (!j.yaml) { $('#pt-msg').textContent = 'Could not read the policy: ' + (j.error || ''); return; }
      $('#pt-ver').textContent = 'version ' + j.version + ' · ' + j.status + ' · ' + j.hash; $('#pt-base').textContent = 'default snapshot: ' + (j.baseline || 'none');
      $('#pt-msg').textContent = ''; $('#pt-yaml').value = j.yaml;
      const rows = ['<tr><th>Rule</th><th>Endpoints</th><th>Binaries</th><th></th></tr>'];
      (j.blocks || []).forEach(b => rows.push(`<tr><td><b>${esc(b.name)}</b></td><td>${b.endpoints.map(e => `<code>${esc(e.host)}:${e.port}</code> ${e.access === 'full' ? '<span class="tag">full</span>' : esc((e.rules || []).slice(0, 3).join(', '))}${(e.rules || []).length > 3 ? ' …' : ''}`).join('<br>')}</td><td>${(b.binaries || []).map(x => '<code>' + esc(x) + '</code>').join(' ')}</td><td>${b.endpoints.map(e => `<button class="rm" data-hp="${esc(e.host)}:${e.port}" title="remove ${esc(e.host)}:${e.port} from the policy">remove</button>`).join('<br>')}</td></tr>`));
      $('#pt-net').innerHTML = rows.join('');
      cfg.polEl.querySelectorAll('.rm').forEach(btn => btn.onclick = async () => {
        if (!confirm('Remove endpoint ' + btn.dataset.hp + ' from ' + psb() + '?')) return;
        $('#pt-msg').textContent = 'Removing...'; const r = await api('/api/policy/update', { sandbox: psb(), mode: 'apply', remove: btn.dataset.hp });
        $('#pt-msg').textContent = r.ok ? 'Removed.' : 'Failed: ' + (r.error || r.output); loadPolicy();
      });
      const h = await api('/api/policy/history?sandbox=' + psb()); $('#pt-hist').textContent = h.history || '';
      await loadDefault(j.yaml);
    }
    let DEF = '';
    const norm = x => String(x || '').replace(/\r/g, '').trim();
    async function loadDefault(liveYaml) {
      const d = await api('/api/policy/default?sandbox=' + psb()); DEF = d.yaml || '';
      $('#pt-dyaml').value = DEF; $('#pt-dmeta').textContent = d.meta ? d.meta : 'no default saved';
      const same = liveYaml !== undefined && DEF && norm(liveYaml) === norm(DEF);
      $('#pt-dmatch').textContent = !DEF ? '' : same ? 'live policy matches the default' : 'live policy differs from the default';
      $('#pt-dmatch').className = 'tag' + (DEF && !same ? ' chg' : '');
    }
    let dAct = null;
    const dAsk = (act, txt) => { dAct = act; $('#pt-dconft').textContent = txt; $('#pt-dconf').hidden = false; };
    $('#pt-dno').onclick = () => { $('#pt-dconf').hidden = true; dAct = null; };
    $('#pt-dreset').onclick = () => dAsk('reset', 'Replace the live policy with the default?');
    $('#pt-dsave').onclick = () => dAsk('save', 'Make the current live policy the new default?');
    $('#pt-dyes').onclick = async () => {
      $('#pt-dconf').hidden = true; const a = dAct; dAct = null; if (!a) return;
      $('#pt-msg').textContent = a === 'reset' ? 'Re-applying the default...' : 'Saving the live policy as the default...';
      const r = await api(a === 'reset' ? '/api/policy/reset' : '/api/policy/save-default', { sandbox: psb() });
      $('#pt-msg').textContent = r.ok ? (a === 'reset' ? 'Reset done: the live policy is back to the default.' : 'Saved: Reset now returns to this policy.') : 'Failed: ' + (r.error || r.output); loadPolicy();
    };
    $('#pt-dedit').onclick = () => { $('#pt-dwrap').open = true; $('#pt-dyaml').readOnly = false; $('#pt-dedrow').hidden = false; };
    $('#pt-dcancel').onclick = () => { $('#pt-dyaml').value = DEF; $('#pt-dyaml').readOnly = true; $('#pt-dedrow').hidden = true; };
    $('#pt-dsaveyaml').onclick = async () => {
      const r = await api('/api/policy/set-default', { sandbox: psb(), yaml: $('#pt-dyaml').value });
      $('#pt-msg').textContent = r.ok ? 'Default saved. Press "Reset live policy to this default" to apply it.' : 'Not saved: ' + (r.error || r.output);
      $('#pt-dyaml').readOnly = true; $('#pt-dedrow').hidden = true; loadPolicy();
    };
    $('#pt-dtoed').onclick = () => { $('#pt-yaml').value = DEF; $('#pt-msg').textContent = 'Default YAML loaded into the editor below (not applied).'; };
    $('#pt-refresh').onclick = loadPolicy;
    $('#pt-reset').onclick = () => { $('#pt-conf').hidden = false; }; $('#pt-no').onclick = () => { $('#pt-conf').hidden = true; };
    $('#pt-yes').onclick = async () => {
      $('#pt-conf').hidden = true; $('#pt-msg').textContent = 'Re-applying the default snapshot...';
      const r = await api('/api/policy/reset', { sandbox: psb() });
      $('#pt-msg').textContent = r.ok ? 'Reset done: the policy is back to the default snapshot.' : 'Reset failed: ' + (r.error || r.output); loadPolicy();
    };
    async function applyForm(mode) { $('#pt-out').hidden = false; $('#pt-pre').textContent = 'Working...'; const r = await api('/api/policy/update', formReq(mode)); $('#pt-pre').textContent = (r.error || '') + (r.output || ''); return r; }
    $('#pt-prev').onclick = () => applyForm('preview');
    $('#pt-apply').onclick = async () => { const r = await applyForm('apply'); $('#pt-msg').textContent = r.ok ? 'Applied.' : 'Failed.'; loadPolicy(); };
    $('#pt-re').onclick = async () => {
      const before = cfg.getLast && cfg.getLast();
      if (!before) { $('#pt-msg').textContent = 'Run a prompt first, then come back.'; return; }
      const r = await applyForm('apply'); if (!r.ok) { $('#pt-msg').textContent = 'Apply failed, not re-running.'; return; }
      $('#pt-msg').textContent = 'Applied. Re-running the last prompt...'; await loadPolicy();
      try { await cfg.rerun(before.prompt, before); showCompare(before, cfg.getLast()); $('#pt-msg').textContent = 'Done: see Before / after below.'; }
      catch (e) { $('#pt-msg').textContent = 'Re-run failed: ' + e.message; }
    };
    $('#pt-setyaml').onclick = async () => {
      if (!confirm('Apply this YAML to ' + psb() + '?')) return; $('#pt-msg').textContent = 'Applying YAML...';
      const r = await api('/api/policy/set', { sandbox: psb(), yaml: $('#pt-yaml').value });
      $('#pt-msg').textContent = r.ok ? 'YAML applied.' : 'Rejected: ' + (r.error || r.output); loadPolicy();
    };
    const evChips = ev => ev.length ? ev.map(e => `<div class="ev ${e.verdict === 'ALLOWED' ? 'a' : 'd'}"><b>${e.verdict}</b><span>${esc(e.text.slice(0, 140))}</span></div>`).join('') : '<div class="sub">No network events.</div>';
    function showCompare(a, b) {
      $('#pt-cmpcard').hidden = false;
      const flipped = a.events.some(e => e.verdict === 'DENIED') && b.events.some(e => e.verdict === 'ALLOWED');
      $('#pt-cmp').innerHTML = (flipped ? '<div class="verdict ok">DENIED → ALLOWED after the policy change</div>' : '<div class="verdict warn">No DENIED → ALLOWED flip detected: check the events below.</div>') +
        `<div class="col2" style="margin-top:8px"><div><b>Before</b> <span class="tag">policy v${esc(a.version)}</span><pre>${esc((a.answer || '').slice(0, 700))}</pre>${evChips(a.events)}</div><div><b>After</b> <span class="tag">policy v${esc(b.version)}</span><pre>${esc((b.answer || '').slice(0, 700))}</pre>${evChips(b.events)}</div></div>`;
    }

    // ---------------- diff
    const REVC = {}; let REVS = [];
    const fmtT = ms => new Date(ms).toLocaleString();
    async function loadRevs() {
      $('#pt-dmsg').textContent = 'Loading revisions...'; const h = await api('/api/policy/history?sandbox=' + $('#pt-dsb').value); REVS = h.revisions || [];
      if (!REVS.length) { $('#pt-dmsg').textContent = 'No revisions found.'; return; }
      const opt = r => `<option value="${r.version}">v${r.version} · ${r.hash.slice(0, 12)} · ${r.status}${r.created_ms ? ' · ' + fmtT(r.created_ms) : ''}</option>`;
      $('#pt-da').innerHTML = REVS.map(opt).join(''); $('#pt-db').innerHTML = REVS.map(opt).join('');
      $('#pt-db').value = REVS[0].version; $('#pt-da').value = (REVS[1] || REVS[0]).version; $('#pt-dmsg').textContent = REVS.length + ' revisions'; runDiff();
    }
    async function getRev(sb, v) { const k = sb + ':' + v; if (!REVC[k]) { const j = await api(`/api/policy/rev?sandbox=${sb}&rev=${v}`); if (!j.yaml) throw new Error(j.error || 'could not read revision ' + v); REVC[k] = j; } return REVC[k]; }
    const epKey = e => e.host + ':' + e.port, epSig = e => JSON.stringify([e.access || '', e.protocol || '', (e.rules || []).slice().sort()]);
    const epLbl = e => `<code>${esc(e.host)}:${e.port}</code> ${e.access === 'full' ? '<span class="tag">full access</span>' : esc((e.rules || []).join(', ')) || '<small>(no rules)</small>'}`;
    const bl = a => (a || []).map(x => '<code>' + esc(x) + '</code>').join(' ');
    function diffStruct(A, B) {
      const out = [], am = Object.fromEntries((A.blocks || []).map(b => [b.name, b])), bm = Object.fromEntries((B.blocks || []).map(b => [b.name, b]));
      Object.keys(bm).filter(n => !am[n]).forEach(n => { const b = bm[n]; out.push(`<div class="dl add"><b>+ rule ${esc(n)}</b> added<br>${b.endpoints.map(e => '&nbsp;&nbsp;+ ' + epLbl(e)).join('<br>')}<br><small>binaries:</small> ${bl(b.binaries)}</div>`); });
      Object.keys(am).filter(n => !bm[n]).forEach(n => { const b = am[n]; out.push(`<div class="dl del"><b>− rule ${esc(n)}</b> removed<br>${b.endpoints.map(e => '&nbsp;&nbsp;− ' + epLbl(e)).join('<br>')}<br><small>binaries:</small> ${bl(b.binaries)}</div>`); });
      Object.keys(bm).filter(n => am[n]).forEach(n => {
        const a = am[n], b = bm[n], ae = Object.fromEntries(a.endpoints.map(e => [epKey(e), e])), be = Object.fromEntries(b.endpoints.map(e => [epKey(e), e])), L = [];
        Object.keys(be).filter(k => !ae[k]).forEach(k => L.push('<span style="color:var(--green)">+ endpoint</span> ' + epLbl(be[k])));
        Object.keys(ae).filter(k => !be[k]).forEach(k => L.push('<span style="color:var(--red)">− endpoint</span> ' + epLbl(ae[k])));
        Object.keys(be).filter(k => ae[k] && epSig(ae[k]) !== epSig(be[k])).forEach(k => L.push('<span style="color:var(--amber)">~ endpoint</span> ' + epLbl(ae[k]) + ' → ' + epLbl(be[k])));
        const ab = new Set(a.binaries || []), bb = new Set(b.binaries || []);
        [...bb].filter(x => !ab.has(x)).forEach(x => L.push('<span style="color:var(--green)">+ binary</span> <code>' + esc(x) + '</code>'));
        [...ab].filter(x => !bb.has(x)).forEach(x => L.push('<span style="color:var(--red)">− binary</span> <code>' + esc(x) + '</code>'));
        if (L.length) out.push(`<div class="dl chg"><b>~ rule ${esc(n)}</b> changed<br>${L.map(x => '&nbsp;&nbsp;' + x).join('<br>')}</div>`);
      });
      const fl = [];
      ['read_only', 'read_write'].forEach(k => {
        const a = new Set((A.fs || {})[k] || []), b = new Set((B.fs || {})[k] || []);
        [...b].filter(x => !a.has(x)).forEach(x => fl.push(`<div class="dl add">+ filesystem ${k}: <code>${esc(x)}</code></div>`));
        [...a].filter(x => !b.has(x)).forEach(x => fl.push(`<div class="dl del">− filesystem ${k}: <code>${esc(x)}</code></div>`));
      });
      if (JSON.stringify(A.process || {}) !== JSON.stringify(B.process || {})) fl.push(`<div class="dl chg">~ process: <code>${esc(JSON.stringify(A.process))}</code> → <code>${esc(JSON.stringify(B.process))}</code></div>`);
      if (JSON.stringify(A.landlock || {}) !== JSON.stringify(B.landlock || {})) fl.push(`<div class="dl chg">~ landlock: <code>${esc(JSON.stringify(A.landlock))}</code> → <code>${esc(JSON.stringify(B.landlock))}</code></div>`);
      return { net: out, fs: fl };
    }
    function lineDiff(a, b) {
      const n = a.length, m = b.length, dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
      for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      const ops = []; let i = 0, j = 0;
      while (i < n && j < m) { if (a[i] === b[j]) { ops.push([' ', a[i]]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push(['-', a[i++]]); else ops.push(['+', b[j++]]); }
      while (i < n) ops.push(['-', a[i++]]); while (j < m) ops.push(['+', b[j++]]); return ops;
    }
    function renderLineDiff(ops) {
      const keep = new Array(ops.length).fill(false); ops.forEach((o, i) => { if (o[0] !== ' ') for (let k = Math.max(0, i - 2); k <= Math.min(ops.length - 1, i + 2); k++) keep[k] = true; });
      let h = '', skip = 0; const gap = () => `<span class="gap">… ${skip} unchanged line${skip > 1 ? 's' : ''} …</span>`;
      ops.forEach((o, i) => { if (!keep[i]) { skip++; return; } if (skip) { h += gap(); skip = 0; } h += `<span class="${o[0] === '+' ? 'add' : o[0] === '-' ? 'del' : ''}">${o[0] === '+' ? '+ ' : o[0] === '-' ? '− ' : '  '}${esc(o[1])}</span>`; });
      if (skip) h += gap(); return h;
    }
    async function runDiff() {
      const sb = $('#pt-dsb').value, va = +$('#pt-da').value, vb = +$('#pt-db').value; if (!va || !vb) return; $('#pt-dmsg').textContent = 'Comparing...';
      try {
        const [A, B] = await Promise.all([getRev(sb, va), getRev(sb, vb)]); $('#pt-dmsg').textContent = '';
        const same = A.hash === B.hash, ds = diffStruct(A, B), ops = lineDiff(A.yaml.split('\n'), B.yaml.split('\n')), adds = ops.filter(o => o[0] === '+').length, dels = ops.filter(o => o[0] === '-').length;
        const nAdd = ds.net.filter(x => x.includes('dl add')).length, nDel = ds.net.filter(x => x.includes('dl del')).length, nChg = ds.net.filter(x => x.includes('dl chg')).length;
        $('#pt-dsum').hidden = false;
        $('#pt-dsum').innerHTML = `<div class="row"><b>v${va}</b><span class="tag">${esc(A.hash)}</span> → <b>v${vb}</b><span class="tag">${esc(B.hash)}</span></div>` +
          (same ? '<div class="verdict ok">Identical policy (same hash): nothing changed between these revisions.</div>' : `<div class="verdict warn">${nAdd} rule(s) added · ${nDel} removed · ${nChg} changed · ${ds.fs.length} filesystem/process change(s) · YAML: <span style="color:var(--green)">+${adds}</span> / <span style="color:var(--red)">−${dels}</span> lines</div>`);
        $('#pt-dstruct').hidden = same; $('#pt-draw').hidden = same; if (same) return;
        $('#pt-dstructbody').innerHTML = (ds.net.join('') || '<div class="sub">No network policy changes.</div>') + (ds.fs.length ? '<h2 style="margin-top:10px">Filesystem / process</h2>' + ds.fs.join('') : '');
        $('#pt-drawbody').innerHTML = renderLineDiff(ops);
      } catch (e) { $('#pt-dmsg').textContent = 'Error: ' + e.message; }
    }
    $('#pt-dsb').onchange = loadRevs; $('#pt-da').onchange = runDiff; $('#pt-db').onchange = runDiff;
    $('#pt-dref').onclick = () => { Object.keys(REVC).forEach(k => delete REVC[k]); loadRevs(); };
    $('#pt-dswap').onclick = () => { const a = $('#pt-da').value; $('#pt-da').value = $('#pt-db').value; $('#pt-db').value = a; runDiff(); };
    $('#pt-dprev').onclick = () => { const v = +$('#pt-db').value, i = REVS.findIndex(r => r.version === v), p = REVS[i + 1]; if (p) { $('#pt-da').value = p.version; runDiff(); } };

    return { openEditor() { renderDenied(); loadPolicy(); }, openDiff: loadRevs, renderDenied, api };
  }
  window.PolicyTools = { mount, api };
})();
