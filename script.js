// script.js (client hydration)
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const JUDGMENT_KEYS = {
  'pct_complete_overall': { label: '% Complete', color: COMPLIANCE_COLORS.COMPLETE },
  'pct_evasive':          { label: '% Evasive',  color: COMPLIANCE_COLORS.EVASIVE },
  'pct_denial':           { label: '% Denial',   color: COMPLIANCE_COLORS.DENIAL },
  'pct_error':            { label: '% Error',    color: COMPLIANCE_COLORS.ERROR }
};
const HIGHLIGHT_COLORS = { fadedBackground: 'rgba(200,200,200,0.7)', fadedBorder: 'rgba(180,180,180,0.7)' };
const CORE_META_PATH = '/data/metadata-core.json?1';
function atPath(re){ try{ return re.test(window.location.pathname); }catch(e){ return false; } }
function safeName(t){ if(!t) return 'id'; const n=t.normalize('NFKD').replace(/[\u0300-\u036f]/g,''); let s=n.toLowerCase().replace(/[^\w\s-]/g,'-').replace(/[\s-]+/g,'-'); s=s.replace(/^-+|-+$/g,'').substring(0,100); return s||'id'; }
async function fetchJSON(path){ const r = await fetch(path,{cache:'no-store'}); if(!r.ok) throw new Error(`HTTP ${r.status} ${path}`); return await r.json(); }
(function(){
  // Ensure hash anchors (e.g., #model-...) land correctly after layout
  function reanchorIfNeeded(){
    try {
      if (!location.hash) return;
      // Only handle model anchors to avoid interfering with other pages
      if (!/^#model-/i.test(location.hash)) return;
      const id = decodeURIComponent(location.hash.slice(1));
      const el = document.getElementById(id);
      if (!el) return;
      const r = el.getBoundingClientRect();
      // If not near the top of the viewport, re-scroll to align
      const nearTopBand = 80; // px
      const isNearTop = r.top >= 0 && r.top <= nearTopBand;
      if (!isNearTop) {
        try { el.scrollIntoView({ block: 'start', behavior: 'auto' }); }
        catch (_) { el.scrollIntoView(true); }
      }
    } catch (e) { /* no-op */ }
  }

  function setupAnchorFix(){
    if (setupAnchorFix._done) return; // idempotent
    setupAnchorFix._done = true;
    // After full load (images/CSS/fonts), re-jump to correct for any layout shift
    window.addEventListener('load', () => {
      // Do a couple of passes to be safe against late layout shifts
      setTimeout(reanchorIfNeeded, 0);
      setTimeout(reanchorIfNeeded, 250);
    });
    // Also handle in-page TOC navigation
    window.addEventListener('hashchange', () => { setTimeout(reanchorIfNeeded, 0); });
  }

  // Matches a filter query against row text: /regex/ syntax, else
  // all whitespace-separated terms must appear as substrings.
  function makeRowMatcher(raw){
    const q = String(raw || '').trim();
    if (!q) return () => true;
    const m = q.match(/^\/(.+)\/([a-z]*)$/i);
    if (m) {
      try {
        const re = new RegExp(m[1], m[2] || 'i');
        return (text) => re.test(text);
      } catch (e) { /* fall through to substring search */ }
    }
    const parts = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!parts.length) return () => true;
    return (text) => { const t = text.toLowerCase(); return parts.every(p => t.includes(p)); };
  }

  function setupDataTable(block){
    if (block.dataset.wired === '1') return;
    block.dataset.wired = '1';
    const table = block.querySelector('table.sm-table');
    const tbody = table ? table.tBodies[0] : null;
    if (!tbody) return;

    const controls = Array.from(block.querySelectorAll('[data-sort-key]'));
    const sel = block.querySelector('select.table-sort');
    const dirBtn = block.querySelector('button.table-sort-dir');
    let cur = { key: null, type: 'num', dir: 'desc' };
    // Initialize from the prerendered sorted header, falling back to the select.
    const initTh = block.querySelector('th.sorted-asc, th.sorted-desc');
    if (initTh) {
      cur = {
        key: initTh.getAttribute('data-sort-key'),
        type: initTh.getAttribute('data-sort-type') || 'num',
        dir: initTh.classList.contains('sorted-asc') ? 'asc' : 'desc',
      };
    }

    function syncIndicators(){
      controls.forEach(c => {
        c.classList.toggle('sorted-asc', c.getAttribute('data-sort-key') === cur.key && cur.dir === 'asc');
        c.classList.toggle('sorted-desc', c.getAttribute('data-sort-key') === cur.key && cur.dir === 'desc');
        if (c.tagName === 'TH') {
          if (c.getAttribute('data-sort-key') === cur.key) {
            c.setAttribute('aria-sort', cur.dir === 'asc' ? 'ascending' : 'descending');
          } else {
            c.removeAttribute('aria-sort');
          }
        }
      });
      if (sel) {
        const want = Array.from(sel.options).find(o => o.value.split('|')[0] === cur.key);
        if (want) sel.value = want.value;
      }
      if (dirBtn) {
        dirBtn.dataset.dir = cur.dir;
        dirBtn.textContent = cur.dir === 'asc' ? '↑' : '↓';
      }
    }

    function applySort(key, type, dir){
      cur = { key, type, dir };
      const mul = dir === 'desc' ? -1 : 1;
      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {
        const va = a.getAttribute('data-s-' + key) || '';
        const vb = b.getAttribute('data-s-' + key) || '';
        if (type === 'num') return ((parseFloat(va) || 0) - (parseFloat(vb) || 0)) * mul;
        return va.localeCompare(vb) * mul;
      });
      rows.forEach(r => tbody.appendChild(r));
      syncIndicators();
    }

    controls.forEach(c => {
      c.addEventListener('click', () => {
        const key = c.getAttribute('data-sort-key');
        const type = c.getAttribute('data-sort-type') || 'num';
        const dir = (cur.key === key)
          ? (cur.dir === 'asc' ? 'desc' : 'asc')
          : (c.getAttribute('data-first-dir') || 'desc');
        applySort(key, type, dir);
      });
    });
    if (sel) {
      sel.addEventListener('change', () => {
        const [key, type, firstDir] = sel.value.split('|');
        applySort(key, type, cur.key === key ? cur.dir : (firstDir || 'desc'));
      });
    }
    if (dirBtn) {
      dirBtn.addEventListener('click', () => {
        if (cur.key) applySort(cur.key, cur.type, cur.dir === 'asc' ? 'desc' : 'asc');
      });
    }

    const filt = block.querySelector('input.table-filter');
    if (filt) {
      filt.addEventListener('input', () => {
        const match = makeRowMatcher(filt.value);
        Array.from(tbody.rows).forEach(tr => {
          tr.hidden = !match(tr.getAttribute('data-f') || tr.textContent || '');
        });
      });
    }
    syncIndicators();
  }

  function initDataTables(){
    document.querySelectorAll('.data-table-block').forEach(setupDataTable);
  }

  async function hydrateTimeline(){
    const cvs = document.getElementById('timeline-chart-canvas'); if (!cvs) return;
    try{
      const core = await fetchJSON(CORE_META_PATH);
      const modelMeta = core && core.model_metadata ? core.model_metadata : {};
      const modelSummary = core && Array.isArray(core.model_summary) ? core.model_summary : [];
      const labMeta = core && core.lab_metadata ? core.lab_metadata : {};
      const params = new URLSearchParams(window.location.search);
      let metric = params.get('metric') || 'pct_complete_overall';
      let creator = params.get('creator') || 'all';
      let highlight = params.get('highlight') || 'none';
      // Populate selects
      const selMetric = document.getElementById('timeline-metric-filter');
      const selCreator = document.getElementById('timeline-creator-filter');
      const selHighlight = document.getElementById('timeline-highlight-creator-filter');
      const creatorSet = new Set(['all']); for (const mid in modelMeta){ creatorSet.add(modelMeta[mid]?.creator || 'Unknown Creator'); }
      function setOptions(sel, arr, labelMap){ if(!sel) return; sel.innerHTML=''; arr.forEach(v=>{ const o=document.createElement('option'); o.value=v; o.textContent=labelMap?labelMap[v]:v; sel.appendChild(o); }); }
      function labLabel(lab){ const m = labMeta && lab ? labMeta[lab] : null; const n = m && typeof m.full_name === 'string' ? m.full_name.trim() : ''; return n || lab; }
      if (selMetric && !selMetric.dataset.wired){ const metricLabels={}; Object.keys(JUDGMENT_KEYS).forEach(k=>metricLabels[k]=JUDGMENT_KEYS[k].label); setOptions(selMetric, Object.keys(JUDGMENT_KEYS), metricLabels); selMetric.value=metric; selMetric.dataset.wired='1'; }
      if (selCreator && !selCreator.dataset.wired){ const creators = Array.from(creatorSet).filter(c=>c!=='all').sort(); const labels={ all:'all' }; creators.forEach(c=>labels[c]=labLabel(c)); setOptions(selCreator, ['all', ...creators], labels); selCreator.value=creator; selCreator.dataset.wired='1'; }
      if (selHighlight && !selHighlight.dataset.wired){ const creators = Array.from(creatorSet).filter(c=>c!=='all').sort(); const labels={ none:'none' }; creators.forEach(c=>labels[c]=labLabel(c)); setOptions(selHighlight, ['none', ...creators], labels); selHighlight.value=highlight; selHighlight.dataset.wired='1'; }
      function updateURL(){ const p=new URLSearchParams(); if (selCreator && selCreator.value!=='all') p.set('creator', selCreator.value); if (selMetric && selMetric.value!=='pct_complete_overall') p.set('metric', selMetric.value); if (selHighlight && selHighlight.value!=='none') p.set('highlight', selHighlight.value); history.replaceState(null,'',p.toString()?`?${p.toString()}`:location.pathname); }
      function wire(sel){ if(!sel||sel.dataset.changeWired==='1') return; sel.addEventListener('change',()=>{ updateURL(); hydrateTimeline(); }); sel.dataset.changeWired='1'; }
      wire(selMetric); wire(selCreator); wire(selHighlight);
      // Normalize
      metric = selMetric ? selMetric.value : metric;
      creator = selCreator ? selCreator.value : creator;
      highlight = selHighlight ? selHighlight.value : highlight;
      const ji = JUDGMENT_KEYS[metric] || JUDGMENT_KEYS['pct_complete_overall'];
      const points = [];
      for (const m of modelSummary){
        const mid = m && m.model ? String(m.model) : '';
        if (!mid) continue;
        const meta = modelMeta[mid] || {};
        const cr = meta && meta.creator ? meta.creator : 'Unknown Creator';
        if (creator !== 'all' && cr !== creator) continue;
        let rd = null; if (meta && meta.release_date){ const p = Date.parse(meta.release_date); if (!isNaN(p)) rd = new Date(p); }
        if (!rd) continue;
        const y = Number(m && m[metric]);
        if (!Number.isFinite(y)) continue;
        const isoDay = (meta && meta.release_date) ? String(meta.release_date) : (function(dt){
          const y = dt.getUTCFullYear();
          const m = String(dt.getUTCMonth() + 1).padStart(2, '0');
          const da = String(dt.getUTCDate()).padStart(2, '0');
          return `${y}-${m}-${da}`;
        })(rd);
        points.push({ x: rd, y, label: mid, creator: cr, dateStr: isoDay });
      }
      points.sort((a,b)=>a.x-b.x);
      if (window.__timelineChart) { try { window.__timelineChart.destroy(); } catch (e) {} }
      const ctx = cvs.getContext('2d');
      window.__timelineChart = new Chart(ctx, {
        type: 'scatter',
        data: { datasets: [{ label: 'Models', data: points,
          pointBackgroundColor: (ctx)=>{ const cr = ctx.raw?.creator; return (highlight==='none'||cr===highlight)? (ji.color||'#bdc3c7') : HIGHLIGHT_COLORS.fadedBackground; },
          pointBorderColor: (ctx)=>{ const cr = ctx.raw?.creator; return (highlight==='none'||cr===highlight)? (ji.color||'#bdc3c7') : HIGHLIGHT_COLORS.fadedBorder; },
          pointRadius: 5, pointHoverRadius: 7 }] },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          onClick: (e)=>{ const ch=e.chart; const els=ch.getElementsAtEventForMode(e,'point',{intersect:true},true); if(els&&els.length){ const p=ch.config.data.datasets[els[0].datasetIndex].data[els[0].index]; if(p&&p.label) location.assign(`/models/${safeName(p.label)}/`);} },
          scales: { x:{ type:'time', time:{unit:'month'}, title:{display:true,text:'Model Release Date'} }, y:{ title:{display:true,text: ji.label}, min:0,max:100, ticks:{ callback:(v)=>v+'%' } } },
          plugins: {
            legend: { display:false },
            tooltip: {
              callbacks: {
                // Hide the default title (which is the x-value)
                title: () => [],
                // Show: "Model Name (YYYY-MM-DD, 12.3%)"
                label: (ctx) => {
                  const raw = ctx.raw || {};
                  const name = raw.label || ctx.dataset?.label || 'Model';
                  const day = raw.dateStr || (function(ts){
                    const d = new Date(ts);
                    const y = d.getUTCFullYear();
                    const m = String(d.getUTCMonth() + 1).padStart(2, '0');
                    const dd = String(d.getUTCDate()).padStart(2, '0');
                    return `${y}-${m}-${dd}`;
                  })(ctx.parsed.x);
                  const yv = (typeof ctx.parsed?.y === 'number') ? `${ctx.parsed.y.toFixed(1)}%` : '';
                  return `${name} (${day}, ${yv})`;
                }
              }
            }
          }
        }
      });
    }catch(e){ console.error('Timeline hydrate failed:', e); }
  }
  window.speechmapHydrate = function(){
    // Set up anchor fix on all pages; it runs only when a model hash exists
    setupAnchorFix();
    initDataTables();
    if(atPath(/^\/timeline\/$/)) { hydrateTimeline(); return; }
  };
})();
