// script.js (client hydration)
const JUDGMENT_KEYS = {
  'pct_complete_overall': { label: '% Complete' },
  'pct_evasive':          { label: '% Evasive' },
  'pct_denial':           { label: '% Denial' },
  'pct_error':            { label: '% Error' }
};
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

  // Matches a filter query against row text. A leading slash switches to
  // regex mode immediately — the closing slash is optional, so `/poolside`
  // works while it's still being typed. Anything else: all whitespace-
  // separated terms must appear as substrings.
  function makeRowMatcher(raw){
    const q = String(raw || '').trim();
    if (!q) return () => true;
    if (q.startsWith('/')) {
      const closed = q.match(/^\/(.*)\/([a-z]*)$/);
      const body = closed ? closed[1] : q.slice(1);
      const flags = (closed && closed[2]) || 'i';
      try {
        const re = new RegExp(body, flags);
        return (text) => re.test(text);
      } catch (e) {
        return () => true; // in-progress/invalid regex: don't filter yet
      }
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
      const applyFilter = () => {
        const match = makeRowMatcher(filt.value);
        Array.from(tbody.rows).forEach(tr => {
          tr.hidden = !match(tr.getAttribute('data-f') || tr.textContent || '');
        });
      };
      filt.addEventListener('input', applyFilter);
      // Deep links can prefill the filter: /models/?filter=mistralai/
      const preset = new URLSearchParams(window.location.search).get('filter');
      if (preset) { filt.value = preset; applyFilter(); }
    }
    syncIndicators();
  }

  function initDataTables(){
    document.querySelectorAll('.data-table-block').forEach(setupDataTable);
  }

  const TL_OTHER_COLOR = '#b0b7c3';
  const TL_FADED = 'rgba(203,208,215,0.4)';
  function hexToRgba(hex, a){
    const h = hex.replace('#','');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    const n = parseInt(full, 16);
    return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`;
  }

  // Highlight state survives re-hydration (metric/creator changes rebuild the chart).
  let tlPinned = null;   // Set of creator keys; null until first URL parse
  let tlHovered = null;
  // For labs added ad hoc (no reserved tier color). Validated against each
  // other and against the nearest tier hues; cycles when exhausted.
  const TL_FALLBACK_COLORS = ['#a12a52', '#6d28d9', '#067a52'];
  const tlFallbackAssigned = new Map();

  async function hydrateTimeline(){
    const cvs = document.getElementById('timeline-chart-canvas'); if (!cvs) return;
    try{
      const core = await fetchJSON(CORE_META_PATH);
      const modelMeta = core && core.model_metadata ? core.model_metadata : {};
      const modelSummary = core && Array.isArray(core.model_summary) ? core.model_summary : [];
      const labMeta = core && core.lab_metadata ? core.lab_metadata : {};
      // Color tier comes from the prerendered legend chips (static-first).
      const legend = document.getElementById('timeline-legend');
      const chipsWrap = legend ? legend.querySelector('.tl-chips-wrap') : legend;
      const labColors = {};
      if (legend) legend.querySelectorAll('.tl-chip[data-lab]:not(.tl-chip-temp)').forEach(ch => { labColors[ch.dataset.lab] = ch.dataset.color; });
      const params = new URLSearchParams(window.location.search);
      let metric = params.get('metric') || 'pct_complete_overall';
      let creator = params.get('creator') || 'all';
      if (tlPinned === null) {
        tlPinned = new Set((params.get('highlight') || '').split(',').map(s => s.trim()).filter(s => s && s !== 'none'));
      }
      // Populate selects
      const selMetric = document.getElementById('timeline-metric-filter');
      const selCreator = document.getElementById('timeline-creator-filter');
      const selHighlight = document.getElementById('timeline-highlight-creator-filter');
      const creatorSet = new Set(['all']); for (const mid in modelMeta){ creatorSet.add(modelMeta[mid]?.creator || 'Unknown Creator'); }
      function setOptions(sel, arr, labelMap){ if(!sel) return; sel.innerHTML=''; arr.forEach(v=>{ const o=document.createElement('option'); o.value=v; o.textContent=labelMap?labelMap[v]:v; sel.appendChild(o); }); }
      function labLabel(lab){ const m = labMeta && lab ? labMeta[lab] : null; const n = m && typeof m.full_name === 'string' ? m.full_name.trim() : ''; return n || lab; }
      if (selMetric && !selMetric.dataset.wired){ const metricLabels={}; Object.keys(JUDGMENT_KEYS).forEach(k=>metricLabels[k]=JUDGMENT_KEYS[k].label); setOptions(selMetric, Object.keys(JUDGMENT_KEYS), metricLabels); selMetric.value=metric; selMetric.dataset.wired='1'; }
      if (selCreator && !selCreator.dataset.wired){ const creators = Array.from(creatorSet).filter(c=>c!=='all').sort(); const labels={ all:'all' }; creators.forEach(c=>labels[c]=labLabel(c)); setOptions(selCreator, ['all', ...creators], labels); selCreator.value=creator; selCreator.dataset.wired='1'; }
      if (selHighlight && !selHighlight.dataset.wired){ const creators = Array.from(creatorSet).filter(c=>c!=='all').sort(); const labels={ none:'add a lab…' }; creators.forEach(c=>labels[c]=labLabel(c)); setOptions(selHighlight, ['none', ...creators], labels); selHighlight.value='none'; selHighlight.dataset.wired='1'; }
      function updateURL(){ const p=new URLSearchParams(); if (selCreator && selCreator.value!=='all') p.set('creator', selCreator.value); if (selMetric && selMetric.value!=='pct_complete_overall') p.set('metric', selMetric.value); if (tlPinned && tlPinned.size) p.set('highlight', Array.from(tlPinned).join(',')); history.replaceState(null,'',p.toString()?`?${p.toString()}`:location.pathname); }
      function wire(sel){ if(!sel||sel.dataset.changeWired==='1') return; sel.addEventListener('change',()=>{ updateURL(); hydrateTimeline(); }); sel.dataset.changeWired='1'; }
      wire(selMetric); wire(selCreator);
      // The highlight select ADDS a lab to the pinned set (covers labs
      // without legend chips), then snaps back to its placeholder.
      if (selHighlight && selHighlight.dataset.changeWired !== '1'){
        selHighlight.dataset.changeWired = '1';
        selHighlight.addEventListener('change', () => {
          const v = selHighlight.value;
          selHighlight.value = 'none';
          if (v && v !== 'none') window.__timelineTogglePin?.(v, true);
        });
      }
      // Normalize
      metric = selMetric ? selMetric.value : metric;
      creator = selCreator ? selCreator.value : creator;
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
        const isoDay = (meta && meta.release_date) ? String(meta.release_date) : rd.toISOString().slice(0, 10);
        points.push({ x: rd, y, label: mid, creator: cr, dateStr: isoDay });
      }
      // Draw order: gray pool first, colored tier on top; chronological within each.
      points.sort((a,b)=>{ const ta = labColors[a.creator]?1:0, tb = labColors[b.creator]?1:0; return (ta-tb) || (a.x-b.x); });

      // Trend lines use the lab-standings methodology on the displayed
      // metric: monthly-average buckets smoothed by a gap-aware EMA with a
      // 3-month half-life (same weighting as the Free Speech Index, but
      // computed on whatever metric is on the Y axis).
      function emaSeries(pts, halfLifeMonths){
        const hl = halfLifeMonths || 3;
        const decay = Math.pow(0.5, 1 / hl); // per-month weight retention
        const byMonth = new Map();
        for (const p of pts){ const k = p.dateStr.slice(0,7); if(!byMonth.has(k)) byMonth.set(k, []); byMonth.get(k).push(p.y); }
        const months = Array.from(byMonth.keys()).sort();
        const out = [];
        let ema = null, prev = null;
        for (const mon of months){
          const vals = byMonth.get(mon);
          const avg = vals.reduce((s,v)=>s+v,0) / vals.length;
          if (ema === null) {
            ema = avg;
          } else {
            const gap = Math.max(1,
              (parseInt(mon.slice(0,4),10) - parseInt(prev.slice(0,4),10)) * 12
              + (parseInt(mon.slice(5,7),10) - parseInt(prev.slice(5,7),10)));
            const alphaGap = Math.min(1, Math.max(0, 1 - Math.pow(decay, gap)));
            ema = ema * (1 - alphaGap) + avg * alphaGap;
          }
          prev = mon;
          out.push({ x: new Date(mon + '-15T00:00:00Z'), y: ema });
        }
        return out;
      }
      const trendData = emaSeries(points);

      function fallbackColor(cr){
        if (!tlFallbackAssigned.has(cr)) tlFallbackAssigned.set(cr, TL_FALLBACK_COLORS[tlFallbackAssigned.size % TL_FALLBACK_COLORS.length]);
        return tlFallbackAssigned.get(cr);
      }
      function labColorFor(cr){ return labColors[cr] || fallbackColor(cr); }
      function activeSet(){ const s = new Set(tlPinned); if (tlHovered) s.add(tlHovered); return s; }
      function pointColor(ctx){
        const cr = ctx.raw?.creator;
        const act = activeSet();
        if (!act.size) return hexToRgba(labColors[cr] || TL_OTHER_COLOR, 0.8);
        return act.has(cr) ? hexToRgba(labColorFor(cr), 0.85) : TL_FADED;
      }

      if (window.__timelineChart) { try { window.__timelineChart.destroy(); } catch (e) {} }
      const scatterDs = { label: 'Models', data: points, order: 3,
        pointBackgroundColor: pointColor, pointBorderColor: pointColor,
        pointRadius: 4.5, pointHoverRadius: 7 };
      const trendDs = { label: 'Overall trend', type: 'line', data: trendData, order: 1,
        hidden: activeSet().size > 0,
        borderColor: '#64748b', borderWidth: 2, borderDash: [6,4],
        pointRadius: 0, pointHitRadius: 0, tension: 0.3, fill: false };
      const ctx = cvs.getContext('2d');
      const chart = new Chart(ctx, {
        type: 'scatter',
        data: { datasets: [scatterDs, trendDs] },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          onClick: (e)=>{ const ch=e.chart; const els=ch.getElementsAtEventForMode(e,'point',{intersect:true},true); if(els&&els.length){ const el=els[0]; if(el.datasetIndex!==0) return; const p=ch.config.data.datasets[el.datasetIndex].data[el.index]; if(p&&p.label) location.assign(`/models/${safeName(p.label)}/`);} },
          onHover: (e, els)=>{
            // Hovering a point spotlights its lab (same as hovering the chip).
            const el = els && els.length && els[0].datasetIndex === 0 ? els[0] : null;
            const cr = el ? (points[el.index] && points[el.index].creator) : null;
            if (cr !== tlHovered) { tlHovered = cr; window.__timelineApplyHighlights?.(); }
          },
          scales: { x:{ type:'time', time:{unit:'month'}, title:{display:true,text:'Model Release Date'}, ticks:{ maxRotation:0, autoSkip:true, maxTicksLimit:12 }, grid:{color:'rgba(148,163,184,0.15)'} }, y:{ title:{display:true,text: ji.label}, min:0,max:100, ticks:{ callback:(v)=>v+'%' }, grid:{color:'rgba(148,163,184,0.25)'} } },
          plugins: {
            legend: { display:false },
            tooltip: {
              filter: (item) => item.datasetIndex === 0,
              callbacks: {
                title: () => [],
                label: (c) => {
                  const raw = c.raw || {};
                  const name = raw.label || 'Model';
                  const day = raw.dateStr || '';
                  const yv = (typeof c.parsed?.y === 'number') ? `${c.parsed.y.toFixed(1)}%` : '';
                  const lab = raw.creator ? labLabel(raw.creator) : '';
                  return `${name}${lab ? ' — ' + lab : ''} (${day}, ${yv})`;
                }
              }
            }
          }
        }
      });
      window.__timelineChart = chart;

      function applyHighlights(){
        const act = activeSet();
        // The global trend competes with spotlighted trajectories (and
        // clutters screenshots) — show one or the other.
        trendDs.hidden = act.size > 0;
        const trajs = Array.from(act).map(cr => ({
          label: 'trend:' + cr, type: 'line', order: 2,
          data: emaSeries(points.filter(p => p.creator === cr)),
          borderColor: labColorFor(cr), borderWidth: 2,
          pointRadius: 0, pointHitRadius: 0, tension: 0.15, fill: false,
        }));
        chart.data.datasets = [scatterDs, trendDs, ...trajs];
        if (legend) legend.querySelectorAll('.tl-chip[data-lab]').forEach(ch => ch.classList.toggle('pinned', tlPinned.has(ch.dataset.lab)));
        const clearBtn = document.getElementById('timeline-clear-highlights');
        if (clearBtn) clearBtn.hidden = tlPinned.size === 0;
        chart.update('none');
      }
      window.__timelineApplyHighlights = applyHighlights;

      // Labs without a legend chip (added via the highlight select or a
      // shared URL) get a temporary, removable chip in a fallback color.
      function ensureTempChip(cr){
        if (!chipsWrap || labColors[cr]) return;
        if (chipsWrap.querySelector(`.tl-chip-temp[data-lab="${CSS.escape(cr)}"]`)) return;
        const btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'tl-chip tl-chip-temp';
        btn.dataset.lab = cr; btn.dataset.color = fallbackColor(cr);
        const dot = document.createElement('i'); dot.className = 'dot'; dot.style.background = fallbackColor(cr);
        btn.appendChild(dot); btn.appendChild(document.createTextNode(labLabel(cr)));
        chipsWrap.insertBefore(btn, document.getElementById('timeline-clear-highlights'));
        wireChip(btn);
      }
      function removeTempChip(cr){ const el = chipsWrap && chipsWrap.querySelector(`.tl-chip-temp[data-lab="${CSS.escape(cr)}"]`); if (el) el.remove(); }
      function togglePin(cr, on){
        const want = on === undefined ? !tlPinned.has(cr) : on;
        if (want) { tlPinned.add(cr); ensureTempChip(cr); }
        else { tlPinned.delete(cr); if (!labColors[cr]) removeTempChip(cr); }
        updateURL();
        applyHighlights();
      }
      window.__timelineTogglePin = togglePin;
      window.__timelineClear = function(){
        Array.from(tlPinned).forEach(cr => { if (!labColors[cr]) removeTempChip(cr); });
        tlPinned.clear(); tlHovered = null;
        updateURL();
        applyHighlights();
      };
      window.__timelinePinned = () => Array.from(tlPinned);

      function wireChip(ch){
        if (ch.dataset.wired === '1') return;
        ch.dataset.wired = '1';
        const lab = ch.dataset.lab;
        ch.addEventListener('mouseenter', () => { tlHovered = lab; window.__timelineApplyHighlights?.(); });
        ch.addEventListener('mouseleave', () => { tlHovered = null; window.__timelineApplyHighlights?.(); });
        ch.addEventListener('click', () => { window.__timelineTogglePin?.(lab); });
      }
      if (legend) legend.querySelectorAll('button.tl-chip[data-lab]').forEach(wireChip);
      const clearBtn = document.getElementById('timeline-clear-highlights');
      if (clearBtn && clearBtn.dataset.wired !== '1'){ clearBtn.dataset.wired = '1'; clearBtn.addEventListener('click', () => { window.__timelineClear?.(); }); }
      // Restore chips for URL-supplied pins and paint the initial state.
      tlPinned.forEach(cr => ensureTempChip(cr));
      applyHighlights();
    }catch(e){ console.error('Timeline hydrate failed:', e); }
  }
  window.speechmapHydrate = function(){
    // Set up anchor fix on all pages; it runs only when a model hash exists
    setupAnchorFix();
    initDataTables();
    if(atPath(/^\/timeline\/$/)) { hydrateTimeline(); return; }
  };
})();
