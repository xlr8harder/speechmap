// script.js (timeline only)
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const JUDGMENT_KEYS = {
  'pct_complete_overall': { label: '% Complete', key: 'k', color: COMPLIANCE_COLORS.COMPLETE },
  'pct_evasive':          { label: '% Evasive',   key: 'e', color: COMPLIANCE_COLORS.EVASIVE },
  'pct_denial':           { label: '% Denial',    key: 'd', color: COMPLIANCE_COLORS.DENIAL },
  'pct_error':            { label: '% Error',     key: 'r', color: COMPLIANCE_COLORS.ERROR }
};
const HIGHLIGHT_COLORS = { fadedBackground: 'rgba(200,200,200,0.7)', fadedBorder: 'rgba(180,180,180,0.7)' };
const CORE_META_PATH = '/data/metadata-core.json?1';
const MODEL_DOMAIN_SUMMARY_PATH = '/data/model-domain-summary.json?1';
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

  function percentWithBgBarFormatter(cell){
    const v = parseFloat(cell.getValue());
    const pct = isNaN(v) ? 0 : v;
    const field = cell.getColumn().getField();
    let color = COMPLIANCE_COLORS.COMPLETE;
    if (field === 'pct_evasive') color = COMPLIANCE_COLORS.EVASIVE;
    else if (field === 'pct_denial') color = COMPLIANCE_COLORS.DENIAL;
    else if (field === 'pct_error') color = COMPLIANCE_COLORS.ERROR;
    const w = Math.max(0, Math.min(100, pct));
    return `
      <div class="percent-bar-container">
        <div class="percent-bar-bg" style="width:${w}%; background-color:${color}"></div>
        <span class="percent-bar-text">${pct.toFixed(1)}%</span>
      </div>`;
  }

  function hydrateModelsIndex(){
    const container = document.getElementById('overview-table');
    const fallback = document.querySelector('#static-fallback-overview table.simple-table');
    if (!container || !fallback) return;
    if (container.dataset.hydrated === '1') return; // prevent duplicate init
    // Parse rows
    const rows = [];
    fallback.querySelectorAll('tbody tr').forEach(tr => {
      const tds = tr.querySelectorAll('td');
      if (tds.length < 7) return;
      const a = tds[0].querySelector('a');
      const model = a ? a.textContent.trim() : tds[0].textContent.trim();
      rows.push({
        model,
        release_date: tds[1].textContent.trim() || '',
        num_responses: parseInt((tds[2].textContent||'0').replace(/[^\d]/g,'')) || 0,
        pct_complete_overall: parseFloat((tds[3].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_evasive: parseFloat((tds[4].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_denial: parseFloat((tds[5].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_error: parseFloat((tds[6].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
      });
    });
    // Build Tabulator
    const table = new Tabulator(container, {
      data: rows,
      layout: 'fitDataFill',
      height: '65vh',
      placeholder: 'No models.',
      initialSort: [{column:'pct_complete_overall', dir:'asc'}],
      columns: [
        { title:'Model', field:'model', widthGrow:2, headerFilter:'input', headerFilterPlaceholder:'Filter models… (supports /regex/)', headerFilterFunc:(headerValue, rowValue)=>{
            if (!headerValue) return true;
            const v = String(rowValue || '');
            const raw = String(headerValue).trim();
            const m = raw.match(/^\/(.+)\/([a-z]*)$/i);
            if (m) {
              try {
                const re = new RegExp(m[1], m[2] || 'i');
                return re.test(v);
              } catch (e) {
                // Fall through to substring search on regex errors
              }
            }
            const parts = raw.toLowerCase().split(/\s+/).filter(Boolean);
            if (!parts.length) return true;
            const lower = v.toLowerCase();
            return parts.every(p => lower.includes(p));
          }, formatter:(cell)=>{
            const name = cell.getValue();
            const link = `/models/${safeName(name)}/`;
            return `<a href="${link}">${name}</a>`;
          }
        },
        { title:'Released', field:'release_date', width:120, hozAlign:'center' },
        { title:'# Resp', field:'num_responses', width:90, hozAlign:'right', sorter:'number' },
        { title:'% Comp', field:'pct_complete_overall', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Evas', field:'pct_evasive', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Deny', field:'pct_denial', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Err', field:'pct_error', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
      ],
    });
    // Hide static fallback after hydration
    const fbWrap = document.getElementById('static-fallback-overview');
    if (fbWrap) fbWrap.style.display = 'none';
    container.dataset.hydrated = '1';
  }

  function hydrateModelDetail(){
    const container = document.getElementById('model-detail-table');
    const fallback = document.querySelector('#static-fallback-model-detail table.simple-table');
    if (!container || !fallback) return;
    if (container.dataset.hydrated === '1') return;
    // Parse static rows
    const rows = [];
    fallback.querySelectorAll('tbody tr').forEach(tr => {
      const tds = tr.querySelectorAll('td');
      if (tds.length < 7) return;
      const a = tds[0].querySelector('a');
      const theme = a ? a.textContent.trim() : tds[0].textContent.trim();
      const href = a ? a.getAttribute('href') : `/themes/${safeName(theme)}/`;
      rows.push({
        theme, href,
        domain: tds[1].textContent.trim() || '',
        num_responses: parseInt((tds[2].textContent||'0').replace(/[^\d]/g,'')) || 0,
        pct_complete_overall: parseFloat((tds[3].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_evasive: parseFloat((tds[4].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_denial: parseFloat((tds[5].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_error: parseFloat((tds[6].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
      });
    });
    // Build Tabulator table
    new Tabulator(container, {
      data: rows,
      layout: 'fitDataFill',
      height: '65vh',
      placeholder: 'No themes.',
      initialSort: [{column:'pct_complete_overall', dir:'asc'}],
      columns: [
        { title:'Theme', field:'theme', widthGrow:2, formatter:(cell)=>{
            const r = cell.getRow().getData();
            const name = r.theme;
            const link = r.href || `/themes/${safeName(name)}/`;
            return `<a href="${link}">${name}</a>`;
          }
        },
        { title:'Domain', field:'domain', width:220 },
        { title:'# Resp', field:'num_responses', width:90, hozAlign:'right', sorter:'number' },
        { title:'% Comp', field:'pct_complete_overall', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Evas', field:'pct_evasive', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Deny', field:'pct_denial', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Err', field:'pct_error', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
      ],
    });
    const fbWrap = document.getElementById('static-fallback-model-detail');
    if (fbWrap) fbWrap.style.display = 'none';
    container.dataset.hydrated = '1';
  }

  function hydrateThemesIndex(){
    const container = document.getElementById('question-themes-table');
    const fallback = document.querySelector('#static-fallback-themes table.simple-table');
    if (!container || !fallback) return;
    if (container.dataset.hydrated === '1') return; // prevent duplicate init
    const rows = [];
    fallback.querySelectorAll('tbody tr').forEach(tr => {
      const tds = tr.querySelectorAll('td');
      if (tds.length < 8) return;
      const a = tds[0].querySelector('a');
      const theme = a ? a.textContent.trim() : tds[0].textContent.trim();
      rows.push({
        grouping_key: theme,
        domain: tds[1].textContent.trim() || '',
        num_models: parseInt((tds[2].textContent||'0').replace(/[^\d]/g,'')) || 0,
        num_responses: parseInt((tds[3].textContent||'0').replace(/[^\d]/g,'')) || 0,
        pct_complete_overall: parseFloat((tds[4].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_evasive: parseFloat((tds[5].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_denial: parseFloat((tds[6].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
        pct_error: parseFloat((tds[7].textContent||'0').replace(/[^\d\.]/g,'')) || 0,
      });
    });
    new Tabulator(container, {
      data: rows,
      layout: 'fitDataFill',
      height: '65vh',
      placeholder: 'No themes.',
      initialSort: [{column:'pct_complete_overall', dir:'asc'}],
      columns: [
        { title:'Theme', field:'grouping_key', widthGrow:2, formatter:(cell)=>{
            const key = cell.getValue(); const link = `/themes/${safeName(key)}/`;
            return `<a href="${link}">${key}</a>`;
          }
        },
        { title:'Domain', field:'domain', width:180 },
        { title:'Models', field:'num_models', width:90, hozAlign:'right', sorter:'number' },
        { title:'# Resp', field:'num_responses', width:90, hozAlign:'right', sorter:'number' },
        { title:'% Complete', field:'pct_complete_overall', width:120, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Evas', field:'pct_evasive', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Deny', field:'pct_denial', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
        { title:'% Err', field:'pct_error', width:110, hozAlign:'right', sorter:'number', formatter:percentWithBgBarFormatter },
      ],
    });
    // Hide static fallback after hydration
    const fbWrap = document.getElementById('static-fallback-themes');
    if (fbWrap) fbWrap.style.display = 'none';
    container.dataset.hydrated = '1';
  }

  async function hydrateTimeline(){
    const cvs = document.getElementById('timeline-chart-canvas'); if (!cvs) return;
    try{
      const [core, domainSummary] = await Promise.all([ fetchJSON(CORE_META_PATH), fetchJSON(MODEL_DOMAIN_SUMMARY_PATH) ]);
      const modelMeta = core && core.model_metadata ? core.model_metadata : {};
      const params = new URLSearchParams(window.location.search);
      let domain = params.get('domain') || 'all';
      let metric = params.get('metric') || 'pct_complete_overall';
      let creator = params.get('creator') || 'all';
      let highlight = params.get('highlight') || 'none';
      // Populate selects
      const selDomain = document.getElementById('timeline-domain-filter');
      const selMetric = document.getElementById('timeline-metric-filter');
      const selCreator = document.getElementById('timeline-creator-filter');
      const selHighlight = document.getElementById('timeline-highlight-creator-filter');
      const domainSet = new Set(); for (const mid in domainSummary){ Object.keys(domainSummary[mid]||{}).forEach(d=>domainSet.add(d)); }
      const creatorSet = new Set(['all']); for (const mid in modelMeta){ creatorSet.add(modelMeta[mid]?.creator || 'Unknown Creator'); }
      function setOptions(sel, arr){ if(!sel) return; sel.innerHTML=''; arr.forEach(v=>{ const o=document.createElement('option'); o.value=v; o.textContent=v; sel.appendChild(o); }); }
      if (selDomain && !selDomain.dataset.wired){ setOptions(selDomain, ['all', ...Array.from(domainSet).sort()]); selDomain.value=domain; selDomain.dataset.wired='1'; }
      if (selMetric && !selMetric.dataset.wired){ setOptions(selMetric, Object.keys(JUDGMENT_KEYS)); selMetric.value=metric; selMetric.dataset.wired='1'; }
      if (selCreator && !selCreator.dataset.wired){ setOptions(selCreator, Array.from(creatorSet).sort()); selCreator.value=creator; selCreator.dataset.wired='1'; }
      if (selHighlight && !selHighlight.dataset.wired){ setOptions(selHighlight, ['none', ...Array.from(creatorSet).sort().filter(c=>c!=='all')]); selHighlight.value=highlight; selHighlight.dataset.wired='1'; }
      function updateURL(){ const p=new URLSearchParams(); if (selDomain && selDomain.value!=='all') p.set('domain', selDomain.value); if (selCreator && selCreator.value!=='all') p.set('creator', selCreator.value); if (selMetric && selMetric.value!=='pct_complete_overall') p.set('metric', selMetric.value); if (selHighlight && selHighlight.value!=='none') p.set('highlight', selHighlight.value); history.replaceState(null,'',p.toString()?`?${p.toString()}`:location.pathname); }
      function wire(sel){ if(!sel||sel.dataset.changeWired==='1') return; sel.addEventListener('change',()=>{ updateURL(); hydrateTimeline(); }); sel.dataset.changeWired='1'; }
      wire(selDomain); wire(selMetric); wire(selCreator); wire(selHighlight);
      // Normalize
      domain = selDomain ? selDomain.value : domain;
      metric = selMetric ? selMetric.value : metric;
      creator = selCreator ? selCreator.value : creator;
      highlight = selHighlight ? selHighlight.value : highlight;
      const ji = JUDGMENT_KEYS[metric] || JUDGMENT_KEYS['pct_complete_overall'];
      const jsk = ji.key;
      const points = [];
      for (const mid in modelMeta){
        const meta = modelMeta[mid];
        const cr = meta && meta.creator ? meta.creator : 'Unknown Creator';
        if (creator !== 'all' && cr !== creator) continue;
        let rd = null; if (meta && meta.release_date){ const p = Date.parse(meta.release_date); if (!isNaN(p)) rd = new Date(p); }
        if (!rd) continue;
        const perDom = domainSummary[mid] || {};
        let c = 0, ycount = 0;
        if (domain === 'all'){ for (const d in perDom){ const s = perDom[d]; c += (s.c||0); ycount += (s[jsk]||0); } }
        else { const s = perDom[domain] || {}; c += (s.c||0); ycount += (s[jsk]||0); }
        if (c === 0) continue;
        const isoDay = (meta && meta.release_date) ? String(meta.release_date) : (function(dt){
          const y = dt.getUTCFullYear();
          const m = String(dt.getUTCMonth() + 1).padStart(2, '0');
          const da = String(dt.getUTCDate()).padStart(2, '0');
          return `${y}-${m}-${da}`;
        })(rd);
        points.push({ x: rd, y: (ycount / c) * 100.0, label: mid, creator: cr, dateStr: isoDay });
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
    if(atPath(/^\/models\/$/)) { hydrateModelsIndex(); return; }
    if(atPath(/^\/models\/[^/]+\/?$/)) { hydrateModelDetail(); return; }
    if(atPath(/^\/themes\/$/)) { hydrateThemesIndex(); return; }
    if(atPath(/^\/timeline\/$/)) { hydrateTimeline(); return; }
  };
})();
