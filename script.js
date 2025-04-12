// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };
const PROGRESS_COLORS_TABULATOR = ['#e74c3c', '#f1c40f', '#2ecc71'];

// --- Alpine.js Data Store ---
document.addEventListener('alpine:init', () => {
    Alpine.data('explorerData', () => ({
        // --- State Variables ---
        isLoading: true, errorMessage: null, allResponses: [], complianceOrder: [],
        currentView: 'about', availableFilters: { models: [], domains: [], variations: [], grouping_keys: [] },
        overviewSortKey: 'pct_complete_overall', selectedModel: null, modelDetailDomainFilter: '',
        modelDetailVariationFilter: '', modelDetailSortKey: 'pct_complete', questionThemeDomainFilter: '',
        questionThemeSortKey: 'pct_complete_overall', selectedGroupingKey: null,
        overviewTable: null, modelDetailTable: null, questionThemesTable: null,
        variationMap: VARIATION_MAP,

        // --- Computed Properties ---
        get modelSummary() { /* ... same ... */ if(this.allResponses.length===0)return[]; const s=this.allResponses.reduce((a,r)=>{if(!a[r.model])a[r.model]={m:r.model,c:0,k:0};a[r.model].c++;if(r.compliance==='COMPLETE')a[r.model].k++;return a;},{}); const res=Object.values(s).map(i=>({model:i.m,num_responses:i.c,pct_complete_overall:i.c>0?(i.k/i.c*100):0,})); res.sort((a,b)=>(this.overviewSortKey==='model'?a.model.localeCompare(b.model):Number(a.pct_complete_overall)-Number(b.pct_complete_overall))); return res; },
        get questionThemeSummary() { /* ... same ... */ if(this.allResponses.length===0)return[]; const f=this.allResponses.filter(r=>!this.questionThemeDomainFilter||r.domain===this.questionThemeDomainFilter); const s=f.reduce((a,r)=>{if(!a[r.grouping_key])a[r.grouping_key]={k:r.grouping_key,d:r.domain,c:0,p:0};a[r.grouping_key].c++;if(r.compliance==='COMPLETE')a[r.grouping_key].p++;a[r.grouping_key].d=r.domain;return a;},{}); const res=Object.values(s).map(i=>({grouping_key:i.k,domain:i.d,num_responses:i.c,pct_complete_overall:i.c>0?(i.p/i.c*100):0,})); res.sort((a,b)=>{if(this.questionThemeSortKey==='grouping_key')return a.grouping_key.localeCompare(b.grouping_key);if(this.questionThemeSortKey==='num_responses')return Number(b.num_responses)-Number(a.num_responses);return Number(a.pct_complete_overall)-Number(b.pct_complete_overall);}); return res; },
        get selectedModelQuestionSummary() { /* ... same ... */ if(!this.selectedModel||this.allResponses.length===0)return[]; const f=this.allResponses.filter(r=>r.model===this.selectedModel&&(!this.modelDetailDomainFilter||r.domain===this.modelDetailDomainFilter)&&(!this.modelDetailVariationFilter||r.variation===this.modelDetailVariationFilter)); const s=f.reduce((a,r)=>{if(!a[r.grouping_key])a[r.grouping_key]={k:r.grouping_key,d:r.domain,c:0,p:0};a[r.grouping_key].c++;if(r.compliance==='COMPLETE')a[r.grouping_key].p++;a[r.grouping_key].d=r.domain;return a;},{}); const res=Object.values(s).map(i=>({grouping_key:i.k,domain:i.d,num_responses:i.c,pct_complete:i.c>0?(i.p/i.c*100):0,})); res.sort((a,b)=>(this.modelDetailSortKey==='grouping_key'?a.grouping_key.localeCompare(b.grouping_key):Number(a.pct_complete)-Number(b.pct_complete))); return res; },
        get selectedModelData() { /* ... same ... */ if (!this.selectedModel) return null; return this.modelSummary.find(m => m.model === this.selectedModel) || null; },
        get selectedQuestionThemeData() { /* ... same ... */ if (!this.selectedGroupingKey) return null; const firstRecord = this.allResponses.find(r => r.grouping_key === this.selectedGroupingKey); if (!firstRecord) return null; const domain = firstRecord.domain; const responsesForTheme = this.allResponses .filter(r => r.grouping_key === this.selectedGroupingKey) .sort((a,b) => a.model.localeCompare(b.model) || parseInt(a.variation) - parseInt(b.variation)); return { grouping_key: this.selectedGroupingKey, domain: domain, responses: responsesForTheme }; },
        get selectedQuestionThemeModelSummary() { /* ... same ... */ if (!this.selectedQuestionThemeData || !this.selectedQuestionThemeData.responses) return []; const summary = this.selectedQuestionThemeData.responses.reduce((acc, r) => { if (!acc[r.model]) acc[r.model] = { model: r.model, anchor_id: r.anchor_id, count: 0, complete_count: 0 }; acc[r.model].count++; if (r.compliance === 'COMPLETE') acc[r.model].complete_count++; acc[r.model].anchor_id = r.anchor_id; return acc; }, {}); return Object.values(summary).map(s => ({ model: s.model, anchor_id: s.anchor_id, count: s.count, pct_complete: s.count > 0 ? (s.complete_count / s.count * 100) : 0, })).sort((a,b) => a.model.localeCompare(b.model)); },
        // Computed property for detailed model stats
        get selectedModelDetailedStats() {
            if (!this.selectedModel || this.allResponses.length === 0) { return { overall: { count: 0, complete_count: 0, pct_complete: 0, counts: {}, percentages: {} }, by_domain: [], by_variation: [], by_domain_sorted: [] }; }
            const modelResponses = this.allResponses.filter(r => r.model === this.selectedModel);
            const overall = { count: 0, complete_count: 0, counts: {}, percentages: {} }; const by_domain = {}; const by_variation = {};
            this.complianceOrder.forEach(level => { overall.counts[level] = 0; });
            this.availableFilters.domains.forEach(d => { by_domain[d] = { domain: d, count: 0, complete_count: 0 }; });
            this.availableFilters.variations.forEach(v => { by_variation[v] = { variation: v, count: 0, complete_count: 0 }; });
            for (const r of modelResponses) { overall.count++; overall.counts[r.compliance]++; if (r.compliance === 'COMPLETE') overall.complete_count++; if (!by_domain[r.domain]) by_domain[r.domain] = { domain: r.domain, count: 0, complete_count: 0 }; by_domain[r.domain].count++; if (r.compliance === 'COMPLETE') by_domain[r.domain].complete_count++; if (!by_variation[r.variation]) by_variation[r.variation] = { variation: r.variation, count: 0, complete_count: 0 }; by_variation[r.variation].count++; if (r.compliance === 'COMPLETE') by_variation[r.variation].complete_count++; }
            overall.pct_complete = overall.count > 0 ? (overall.complete_count / overall.count * 100) : 0; this.complianceOrder.forEach(level => { overall.percentages[level] = overall.count > 0 ? (overall.counts[level] / overall.count * 100) : 0; });
            const domain_results = Object.values(by_domain).map(d => ({ ...d, pct_complete: d.count > 0 ? (d.complete_count / d.count * 100) : 0 }));
            const variation_results = Object.values(by_variation).map(v => ({ ...v, pct_complete: v.count > 0 ? (v.complete_count / v.count * 100) : 0 })).sort((a,b) => parseInt(a.variation) - parseInt(b.variation));
            const domain_results_sorted = [...domain_results].sort((a,b) => Number(a.pct_complete) - Number(b.pct_complete));
            return { overall: overall, by_domain: domain_results, by_variation: variation_results, by_domain_sorted: domain_results_sorted };
        },

        // --- Methods ---
        async initialize() { /* ... */ console.log('Alpine initializing...'); this.isLoading = true; this.errorMessage = null; try { const r=await fetch('us_hard_data.json'); if (!r.ok) throw new Error(`HTTP ${r.status}`); const d=await r.json(); this.allResponses=d.records||[]; this.complianceOrder=d.complianceOrder||[]; if(this.allResponses.length===0) throw new Error("No records."); this.availableFilters.models=[...new Set(this.allResponses.map(r=>r.model))].sort(); this.availableFilters.domains=[...new Set(this.allResponses.map(r=>r.domain))].sort(); this.availableFilters.variations=[...new Set(this.allResponses.map(r=>r.variation))].sort((a,b)=>parseInt(a)-parseInt(b)); this.availableFilters.grouping_keys=[...new Set(this.allResponses.map(r=>r.grouping_key))].sort(); window.addEventListener('hashchange',()=>this.handleHashChange()); this.handleHashChange(); this.setupWatchers(); } catch(e) { console.error("Init error:",e); this.errorMessage=`Failed init: ${e.message}`; this.allResponses=[]; } finally { this.isLoading=false; console.log("Init complete."); } },
        handleHashChange() { /* ... */ console.log("Handling Hash Change:", location.hash); const h=location.hash.slice(1); const p=h.split('/').filter(Boolean); let v='about'; let m=null; let k=null; if(p[0]==='overview'){ v='overview'; } else if(p[0]==='model'&&p[1]){ const pM=decodeURIComponent(p[1]); if(this.availableFilters.models.includes(pM)){v='model_detail';m=pM;} else { console.warn(`Model '${pM}' invalid.`); this.navigate('about', true); return; } } else if(p[0]==='questions'){ if(p[1]){ const pK=decodeURIComponent(p[1]); if(this.availableFilters.grouping_keys.includes(pK)){v='question_theme_detail';k=pK;} else { console.warn(`Key '${pK}' invalid.`); this.navigate('question_themes', true); return; } } else { v='question_themes'; } }
            if (v !== this.currentView || m !== this.selectedModel || k !== this.selectedGroupingKey) {
                console.log(`Updating state: view=${v}, model=${m}, key=${k}`);
                 // Update state BEFORE triggering table init
                this.currentView=v; this.selectedModel=m; this.selectedGroupingKey=k;
                // Destroy tables BEFORE potential DOM changes
                this.destroyAllTables();
                // Use $nextTick to ensure DOM is updated for the new view
                this.$nextTick(() => {
                    console.log("DOM updated, initializing tables for view:", this.currentView);
                    if(this.currentView === 'overview') this.initOverviewTable();
                    if(this.currentView === 'question_themes') this.initQuestionThemesTable();
                    if(this.currentView === 'model_detail') this.initModelDetailTable();
                 });
             } else { console.log("State matches hash."); }
         },
        navigate(view, replaceHistory = false, selectionKey = null) { /* ... */ let h='#/about'; if (view === 'overview'){ h = '#/overview'; } else if (view === 'question_themes'){ h = '#/questions'; } else if (view === 'model_detail'){ const m = selectionKey || this.selectedModel; if(m) h = `#/model/${encodeURIComponent(m)}`; else { console.warn("Nav model_detail no model."); return; } } else if (view === 'question_theme_detail'){ const k = selectionKey || this.selectedGroupingKey; if(k) h = `#/questions/${encodeURIComponent(k)}`; else { console.warn("Nav question_detail no key."); return; } } else if (view !== 'about'){ console.warn("Invalid view:", view); return; }
            if (location.hash !== h){ console.log(`Updating URL: ${h} (repl:${replaceHistory})`); if(replaceHistory) history.replaceState(null,'',h); else history.pushState(null,'',h); this.handleHashChange(); }
            else if (replaceHistory) { // Only redraw if replacing history (filter/sort change on same view)
                console.log("Same hash nav (filter/sort), ensuring redraw.");
                this.$nextTick(()=>{ if(this.currentView==='overview')this.initOverviewTable(); if(this.currentView==='question_themes')this.initQuestionThemesTable(); if(this.currentView==='model_detail')this.initModelDetailTable(); });
            }
         },
        selectModel(modelName) { this.selectedModel = modelName; this.navigate('model_detail', false, modelName); },
        selectQuestionTheme(groupingKey) { this.selectedGroupingKey = groupingKey; this.navigate('question_theme_detail', false, groupingKey); },

        // --- Tabulator Initializers ---
        // ** Added sorter:"number" and removed initialSort **
        initOverviewTable() {
            const t = document.getElementById("overview-table"); if (!t || this.currentView !== 'overview') return; this.destroyTable(this.overviewTable); const d = this.modelSummary; console.log("Init Overview, #", d.length);
            this.overviewTable = new Tabulator(t, { data: [...d], layout: "fitDataFill",/* Changed layout */ height: "60vh", placeholder: "No models.",
                columns: [ { title: "Model", field: "model", widthGrow:2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectModel(c.getRow().getData().model) }, { title: "# Resp", field: "num_responses", width: 120, hozAlign: "right", sorter:"number" }, { title: "% Complete", field: "pct_complete_overall", width: 150, hozAlign: "right", sorter:"number", formatter: "progress", formatterParams: { min: 0, max: 100, color: PROGRESS_COLORS_TABULATOR, legend: (v) => (typeof v === 'number' && !isNaN(v)) ? `${v.toFixed(1)}%` : '' } } ],
                // initialSort removed - rely on computed property sort
             });
        },
        initQuestionThemesTable() {
            const t=document.getElementById("question-themes-table"); if(!t||this.currentView!=='question_themes')return; this.destroyTable(this.questionThemesTable); const d=this.questionThemeSummary; console.log("Init Q Themes, #", d.length);
            this.questionThemesTable = new Tabulator(t,{ data:[...d], layout:"fitDataFill", height:"60vh", placeholder:"No themes.",
                columns:[{title:"Grouping Key", field:"grouping_key", widthGrow:2, frozen:true, headerFilter:"input", cellClick:(e,c)=>this.selectQuestionTheme(c.getRow().getData().grouping_key)}, {title:"Domain", field:"domain", widthGrow:1.5, headerFilter:"select", headerFilterParams:{values:["", ...this.availableFilters.domains]}}, {title:"# Resp", field:"num_responses", width:120, hozAlign:"right", sorter:"number"}, {title:"% Complete", field:"pct_complete_overall", width:150, hozAlign:"right", sorter:"number", formatter:"progress", formatterParams:{min:0, max:100, color:PROGRESS_COLORS_TABULATOR, legend:(v)=>(typeof v==='number'&&!isNaN(v))?`${v.toFixed(1)}%`:''}}],
                // initialSort removed
            });
        },
        initModelDetailTable() {
             const t=document.getElementById("model-detail-table"); if(!t||this.currentView!=='model_detail'||!this.selectedModel)return; this.destroyTable(this.modelDetailTable); const d=this.selectedModelQuestionSummary; console.log(`Init Model Detail ${this.selectedModel}, #`, d.length);
             this.modelDetailTable = new Tabulator(t,{ data:[...d], layout:"fitDataFill", height:"60vh", placeholder:"No Qs.",
                columns:[{title:"Grouping Key", field:"grouping_key", widthGrow:2, frozen:true, headerFilter:"input", cellClick:(e,c)=>this.selectQuestionTheme(c.getRow().getData().grouping_key)}, {title:"Domain", field:"domain", widthGrow:1.5, headerFilter:"select", headerFilterParams:{values:["", ...this.availableFilters.domains.filter(dm=>d.some(q=>q.domain===dm))]}}, {title:"# Resp", field:"num_responses", width:120, hozAlign:"right", sorter:"number"}, {title:"% Complete", field:"pct_complete", width:150, hozAlign:"right", sorter:"number", formatter:"progress", formatterParams:{min:0, max:100, color:PROGRESS_COLORS_TABULATOR, legend:(v)=>(typeof v==='number'&&!isNaN(v))?`${v.toFixed(1)}%`:''}}],
                 // initialSort removed
             });
         },

        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyAllTables() { this.overviewTable = this.destroyTable(this.overviewTable); this.questionThemesTable = this.destroyTable(this.questionThemesTable); this.modelDetailTable = this.destroyTable(this.modelDetailTable); },

        // --- Watchers ---
        setupWatchers() {
             // Watch filters and trigger navigation (which handles table updates)
             // Using replace=true prevents polluting history for simple filter/sort changes
             this.$watch('overviewSortKey', () => { if (this.currentView === 'overview') this.navigate('overview', true) });
             this.$watch('questionThemeDomainFilter', () => { if (this.currentView === 'question_themes') this.navigate('question_themes', true)});
             this.$watch('questionThemeSortKey', () => { if (this.currentView === 'question_themes') this.navigate('question_themes', true) });
             this.$watch('modelDetailDomainFilter', () => { if (this.currentView === 'model_detail') this.navigate('model_detail', true)});
             this.$watch('modelDetailVariationFilter', () => { if (this.currentView === 'model_detail') this.navigate('model_detail', true)});
             this.$watch('modelDetailSortKey', () => { if (this.currentView === 'model_detail') this.navigate('model_detail', true)});
        },

        // --- Helper Methods ---
        getVariationDescription(variation) { return VARIATION_MAP[String(variation)] || `Type ${variation || 'N/A'}`; },
        renderMarkdown(text) { if (!text) return ''; try { const clean = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } }); return clean; } catch (e) { console.error("Markdown error:", e); return `<pre>Err:\n${sanitize(text)}</pre>`; } },
        smoothScroll(selector) { const el = document.querySelector(selector); if(el) el.scrollIntoView({behavior:'smooth', block:'start'}); else console.warn("Smooth scroll target not found:", selector); },
        getComplianceBoxStyle(percent) { let bgColor = COMPLIANCE_COLORS.UNKNOWN; if (typeof percent === 'number' && !isNaN(percent)) { bgColor = percent >= 90 ? COMPLIANCE_COLORS.COMPLETE : (percent >= 25 ? COMPLIANCE_COLORS.EVASIVE : COMPLIANCE_COLORS.DENIAL); } const textColor = (bgColor === COMPLIANCE_COLORS.EVASIVE || bgColor === COMPLIANCE_COLORS.UNKNOWN) ? '#333' : 'white'; return `background-color: ${bgColor}; color: ${textColor};`; },
         // ** NEW: Helper to group responses for detail page **
         groupResponsesByModel(responses) {
             if (!responses) return [];
             const grouped = responses.reduce((acc, r) => {
                 if (!acc[r.model]) {
                     acc[r.model] = { model: r.model, responses: [] };
                 }
                 acc[r.model].responses.push(r);
                 // Responses should already be sorted by variation from computed prop
                 return acc;
             }, {});
             // Return array sorted by model name
             return Object.values(grouped).sort((a,b) => a.model.localeCompare(b.model));
         },

        // --- Init ---
         init() { /* Now called from x-init="initialize()" */ }

    }));
});

// --- Standalone Helper Functions --- (Keep unchanged)
function complianceFormatter(cell, formatterParams, onRendered) { const value = cell.getValue(); if (value === null || value === undefined) return ""; const color = COMPLIANCE_COLORS[value] || COMPLIANCE_COLORS['UNKNOWN']; const textColor = (value === 'EVASIVE' || value === 'UNKNOWN') ? '#333' : 'white'; const span = document.createElement('span'); span.textContent = value; span.classList.add('compliance-label'); span.style.backgroundColor = color; span.style.color = textColor; return span; }
function truncateText(text, maxLength = 100) { if (!text) return ""; text = String(text); return text.length <= maxLength ? text : text.substring(0, maxLength) + "..."; }
function formatDate(dateString) { if (!dateString) return "N/A"; try { return new Date(dateString).toLocaleString('sv-SE'); } catch (e) { return dateString; } }
function sanitize(str) { if (str === null || str === undefined) return ''; const temp = document.createElement('div'); temp.textContent = String(str); return temp.innerHTML; }

