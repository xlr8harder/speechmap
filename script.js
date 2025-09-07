// script.js
// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const JUDGMENT_KEYS = { 'pct_complete_overall': { label: '% Complete', key: 'k', color: COMPLIANCE_COLORS.COMPLETE }, 'pct_evasive': { label: '% Evasive', key: 'e', color: COMPLIANCE_COLORS.EVASIVE }, 'pct_denial': { label: '% Denial', key: 'd', color: COMPLIANCE_COLORS.DENIAL }, 'pct_error': { label: '% Error', key: 'r', color: COMPLIANCE_COLORS.ERROR } };
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };
const THEME_DETAIL_DIR = 'theme_details'; const UNKNOWN_CREATOR = 'Unknown Creator'; const HIGHLIGHT_COLORS = { fadedBackground: 'rgba(200, 200, 200, 0.7)', fadedBorder: 'rgba(180, 180, 180, 0.7)' };
// Phase 1 data split paths
const CORE_META_PATH = 'data/metadata-core.json?1';
const QTHEME_SUMMARY_DIR = 'data/question-theme-summary';
const MODEL_THEMES_DIR = 'data/model-themes';
const MODEL_DOMAIN_SUMMARY_PATH = 'data/model-domain-summary.json?1';

// --- Alpine.js Data Store ---
document.addEventListener('alpine:init', () => {
    Alpine.data('explorerData', () => ({
        // --- State Variables ---
        loadingMessage: 'Initializing...', errorMessage: null, modelSummaryData: [],
        // rawQuestionThemeSummaryData holds the 'all' bin to populate filters
        rawQuestionThemeSummaryData: [],
        // modelThemeSummaryData is no longer loaded globally in Phase 1
        modelThemeSummaryData: {},
        // New split data caches
        questionThemeSummariesByBin: {}, // { binName: [...] }
        modelThemesCache: {},            // { modelId: { themeKey: stats } }
        modelDomainSummaryData: null,    // { modelId: { domain: {c,k,e,d,r} } }
        complianceOrder: [], modelMetadata: {}, stats: { models: 0, themes: 0, judgments: 0, complete: 0 }, isMetadataLoading: true, isMetadataLoaded: false, currentThemeDetailData: null, isThemeDetailLoading: false, themeDetailErrorMessage: null, currentView: 'about', selectedModel: null, selectedGroupingKey: null, currentLoadingThemeKey: null, currentThemeAnchor: null,
        availableFilters: { models: [], domains: [], variations: [], grouping_keys: [], creators: [] }, activeModelDomainFilters: [],
        /**
         * @property {boolean} internalNavigationInProgress - Flag to differentiate between navigation triggered
         *   programmatically (by clicking links/buttons via the `navigate` function) and navigation triggered
         *   by the user directly interacting with browser history (back/forward buttons, causing a `hashchange` event).
         *   - `navigate()` sets this to `true` *before* changing `location.hash`.
         *   - The `hashchange` listener checks this flag. If `true`, it means the event was caused by `navigate()`,
         *     so the listener ignores the event and resets the flag to `false`.
         *   - If the `hashchange` listener sees the flag is `false`, it means the user used back/forward,
         *     so it proceeds to call `parseHash()` to update the view accordingly.
         *   - `navigate()` also resets the flag to `false` in a `$nextTick` *after* its own `parseHash()` call completes,
         *     as a safety measure in case the `hashchange` event timing is unpredictable.
         *   **MAINTENANCE NOTE:** This flag is critical for preventing double-processing of navigation events.
         *   Be cautious when modifying `navigate` or the `hashchange` listener logic.
         */
        internalNavigationInProgress: false,
        timelineFilterDomain: 'all', timelineFilterJudgment: 'pct_complete_overall', timelineFilterCreator: 'all', timelineHighlightCreator: 'none', questionThemeTimeFilter: 'all', timelineChart: null, currentChartInitId: 0, timelineJudgmentOptions: Object.entries(JUDGMENT_KEYS).map(([value, {label}]) => ({value, label})), minReleaseDate: null, maxReleaseDate: null, overviewTable: null, modelDetailTable: null, questionThemesTable: null, variationMap: VARIATION_MAP,

        // --- Computed Properties --- (Simplified)
        get modelSummary() { return this.modelSummaryData; },
        get questionThemeSummary() {
            if (!this.isMetadataLoaded) return [];
            const bin = this.questionThemeTimeFilter || 'all';
            return this.questionThemeSummariesByBin[bin] || this.questionThemeSummariesByBin['all'] || [];
        },
        get selectedModelQuestionSummary() {
            if (!this.selectedModel || !this.isMetadataLoaded) return [];
            const d = this.modelThemesCache[this.selectedModel];
            if (!d) return [];
            const list = Object.entries(d).map(([k, s]) => {
                const c = s.c || 0;
                return {
                    grouping_key: k,
                    domain: s.domain || 'N/A',
                    num_responses: c,
                    pct_complete: c > 0 ? ((s.k || 0) / c * 100) : 0,
                    pct_evasive: c > 0 ? ((s.e || 0) / c * 100) : 0,
                    pct_denial: c > 0 ? ((s.d || 0) / c * 100) : 0,
                    pct_error: c > 0 ? ((s.r || 0) / c * 100) : 0
                };
            });
            const filtered = list.filter(i => this.activeModelDomainFilters.length === 0 || this.activeModelDomainFilters.includes(i.domain));
            filtered.sort((a, b) => { const diff = a.pct_complete - b.pct_complete; return diff !== 0 ? diff : a.grouping_key.localeCompare(b.grouping_key); });
            return filtered;
        },
        get selectedModelData() { if (!this.selectedModel || !this.isMetadataLoaded) return null; return this.modelSummaryData.find(m => m.model === this.selectedModel) || null; },
        get selectedModelFullMetadata() { if (!this.selectedModel || !this.isMetadataLoaded || !this.modelMetadata) return null; return this.modelMetadata[this.selectedModel] || null; },
        get selectedQuestionThemeData() { if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null; const t = this.questionThemeSummary.find(t => t.grouping_key === this.selectedGroupingKey); if (!t && this.rawQuestionThemeSummaryData) { const r=this.rawQuestionThemeSummaryData.find(t=>t.grouping_key===this.selectedGroupingKey); if (r) return {grouping_key:this.selectedGroupingKey,domain:r.domain}; } return t ? {grouping_key:this.selectedGroupingKey,domain:t.domain} : {grouping_key:this.selectedGroupingKey,domain:'N/A'}; },
        get selectedQuestionThemeModelSummary() { if (!this.currentThemeDetailData || !this.currentThemeDetailData.records) return []; const s = {}; this.currentThemeDetailData.records.forEach(r=>{ if(!s[r.model]){s[r.model]={m:r.model,aid:r.anchor_id,c:0,cc:0};} s[r.model].c++; if(r.compliance==='COMPLETE')s[r.model].cc++; if(!s[r.model].aid)s[r.model].aid=r.anchor_id; }); return Object.values(s).map(i => ({model: i.m, anchor_id: i.aid, count: i.c, pct_complete: i.c>0?(i.cc/i.c*100):0})).sort((a, b) => a.model.localeCompare(b.model)); },
        get filteredOrDeniedPercentage() { if (!this.stats || this.stats.judgments === 0) return 'N/A'; const c=this.stats.complete||0; const t=this.stats.judgments; return ((1-(c/t))*100).toFixed(1); },
        getDomainForSelectedTheme() { if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null; const t = this.questionThemeSummary.find(t => t.grouping_key === this.selectedGroupingKey); if (t) return t.domain; const r = this.rawQuestionThemeSummaryData.find(t => t.grouping_key === this.selectedGroupingKey); return r ? r.domain : 'Unknown'; },
        get timelineChartData() {
            if (!this.isMetadataLoaded || !this.modelDomainSummaryData) return [];
            const ji = JUDGMENT_KEYS[this.timelineFilterJudgment];
            if (!ji) { console.error("Inv judgment key:", this.timelineFilterJudgment); return []; }
            const jsk = ji.key;
            const pts = [];
            for (const n in this.modelMetadata) {
                const m = this.modelMetadata[n];
                const c = m.creator || UNKNOWN_CREATOR;
                const rds = m.release_date;
                if (this.timelineFilterCreator !== 'all' && c !== this.timelineFilterCreator) continue;
                let rd = null; if (rds) { try { const p = Date.parse(rds); if (!isNaN(p)) rd = new Date(p); } catch (e) {} }
                if (!rd) continue;
                const perDom = this.modelDomainSummaryData[n] || {};
                let ft = 0; let fjc = 0;
                if (this.timelineFilterDomain === 'all') {
                    for (const dom in perDom) { const s = perDom[dom] || {}; ft += (s.c || 0); fjc += (s[jsk] || 0); }
                } else {
                    const s = perDom[this.timelineFilterDomain] || {}; ft += (s.c || 0); fjc += (s[jsk] || 0);
                }
                if (ft === 0) continue;
                const yv = (ft > 0) ? (fjc / ft * 100) : 0;
                pts.push({ x: rd, y: yv, label: n, creator: c });
            }
            pts.sort((a, b) => a.x - b.x);
            return pts;
        },

        formatJudgments(num) { /* Unchanged */ if (typeof num !== 'number' || isNaN(num)) return '0'; if (num >= 10000) return Math.floor(num / 1000) + 'K+'; return num.toLocaleString(); },
        formatModelMetaKey(key) { /* Unchanged */ if (!key) return ''; return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()); },
        formatModelMetaValue(value) { /* Unchanged */ if (typeof value === 'boolean') return value ? 'Yes' : 'No'; return value; },

        // --- Methods ---
        async initialize() {
            this.isMetadataLoading = true; this.loadingMessage = 'Loading metadata...'; /* ... */ this.internalNavigationInProgress = false;

            this.parseHash(); // Initial parse on load (before metadata)
            this.setupWatchers(); // Setup watchers before loading data

            try { await this.loadMetadata(); this.isMetadataLoaded = true; this.isMetadataLoading = false; this.loadingMessage = ''; this.errorMessage = null;
            } catch (e) { console.error("Init error:", e); this.errorMessage = `Failed load: ${e.message}`; this.isMetadataLoading = false; this.loadingMessage = ''; }

            window.addEventListener('hashchange', () => { if (this.internalNavigationInProgress) { this.internalNavigationInProgress = false; return; } this.parseHash(false, true); });

            if (this.isMetadataLoaded) { this.parseHash(true); }
        },
        async loadMetadata() {
            try {
                // Load small core metadata
                const r = await fetch(CORE_META_PATH, { cache: 'no-store' });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const d = await r.json();
                if (!d.complianceOrder || !d.model_metadata || !d.stats || !d.model_summary) throw new Error("Missing keys.");
                this.complianceOrder = d.complianceOrder;
                this.modelMetadata = d.model_metadata;
                this.stats = d.stats;
                this.modelSummaryData = d.model_summary;

                // Load 'all' question theme summary to populate filters and initial table
                const all = await this.fetchQuestionThemeBin('all');
                this.rawQuestionThemeSummaryData = all;
                this.questionThemeSummariesByBin['all'] = all;

                // Populate available filters
                this.availableFilters.models = this.modelSummaryData.map(m => m.model).sort();
                this.availableFilters.domains = [...new Set(all.map(q => q.domain))].sort();
                this.availableFilters.grouping_keys = all.map(q => q.grouping_key).sort();
                this.availableFilters.variations = ['1', '2', '3', '4'];
                const c = new Set(); Object.values(this.modelMetadata).forEach(m => { c.add(m.creator || UNKNOWN_CREATOR); });
                this.availableFilters.creators = [...c].sort();

                // Compute min/max release dates
                let e = null; Object.values(this.modelMetadata).forEach(m => { if (m.release_date) { try { const dt = new Date(Date.parse(m.release_date)); if (!isNaN(dt)) if (e === null || dt < e) e = dt; } catch (err) {} } });
                const t = new Date(); const mm = 30 * 24 * 60 * 60 * 1000;
                if (e) this.minReleaseDate = new Date(e.getTime() - mm); else this.minReleaseDate = new Date(t.getTime() - 6 * mm);
                this.maxReleaseDate = new Date(t.getTime() + mm);
            } catch (e) {
                console.error("Metadata load fail:", e);
                this.minReleaseDate = null; this.maxReleaseDate = null;
                throw new Error(`Meta Load Fail:${e.message}`);
            }
        },
        async fetchQuestionThemeBin(bin) {
            if (this.questionThemeSummariesByBin[bin]) return this.questionThemeSummariesByBin[bin];
            const fp = `${QTHEME_SUMMARY_DIR}/${bin}.json`;
            const r = await fetch(fp, { cache: 'no-store' });
            if (!r.ok) throw new Error(`HTTP ${r.status} fetch ${fp}`);
            const d = await r.json();
            if (!Array.isArray(d)) throw new Error(`Invalid struct: ${fp}`);
            this.questionThemeSummariesByBin[bin] = d;
            return d;
        },
        async ensureModelThemesLoaded(model) {
            if (this.modelThemesCache[model]) return this.modelThemesCache[model];
            const safe = this.generateSafeIdForFilename(model);
            const fp = `${MODEL_THEMES_DIR}/${safe}.json`;
            const r = await fetch(fp, { cache: 'no-store' });
            if (!r.ok) throw new Error(`HTTP ${r.status} fetch ${fp}`);
            const d = await r.json();
            if (!d || typeof d !== 'object') throw new Error(`Invalid struct: ${fp}`);
            this.modelThemesCache[model] = d;
            return d;
        },
        async ensureModelDomainSummaryLoaded() {
            if (this.modelDomainSummaryData) return this.modelDomainSummaryData;
            const r = await fetch(MODEL_DOMAIN_SUMMARY_PATH, { cache: 'no-store' });
            if (!r.ok) throw new Error(`HTTP ${r.status} fetch model-domain-summary`);
            const d = await r.json();
            if (!d || typeof d !== 'object') throw new Error('Invalid model-domain-summary');
            this.modelDomainSummaryData = d; return d;
        },
        async loadThemeDetailData(groupingKey, anchor = null) { /* Unchanged */ const tA=anchor||this.currentThemeAnchor;if(!groupingKey)return;if(this.currentLoadingThemeKey===groupingKey)return;this.selectedGroupingKey=groupingKey;this.isThemeDetailLoading=true;this.themeDetailErrorMessage=null;this.currentThemeDetailData=null;this.currentLoadingThemeKey=groupingKey;this.currentThemeAnchor=tA;await this.$nextTick();try{const sf=this.generateSafeIdForFilename(groupingKey);const fp=`${THEME_DETAIL_DIR}/${sf}.json.gz`;const r=await fetch(fp,{cache:'no-store',headers:{'Accept-Encoding':'gzip'}});if(!r.ok)throw new Error(`HTTP ${r.status} fetch ${fp}`);const cd=await r.arrayBuffer();const dd=pako.inflate(new Uint8Array(cd),{to:'string'});const j=JSON.parse(dd);if(!j.records||!Array.isArray(j.records))throw new Error(`Invalid struct:${fp}`);j.records.sort((a,b)=>a.model.localeCompare(b.model)||parseInt(a.variation)-parseInt(b.variation));if(this.currentLoadingThemeKey===groupingKey){this.currentThemeDetailData=j;}}catch(e){console.error(`Theme load fail:${groupingKey}`,e);if(this.currentLoadingThemeKey===groupingKey){this.themeDetailErrorMessage=`Fail load:${e.message}`;this.currentThemeDetailData=null;}}finally{if(this.currentLoadingThemeKey===groupingKey){this.isThemeDetailLoading=false;this.currentLoadingThemeKey=null;}} },

        parseHash(forceUpdate = false, isFromHashChange = false) { /* Unchanged */ const previousView=this.currentView;const previousModel=this.selectedModel;const previousKey=this.selectedGroupingKey;const fullHash=location.hash.slice(1);const anchorMatch=fullHash.match(/#([^#]*)$/);const anchor=anchorMatch?anchorMatch[1]:null;const pathAndQuery=anchorMatch?fullHash.substring(0,anchorMatch.index):fullHash;const pathParts=pathAndQuery.split('?');const path=pathParts[0];const query=pathParts[1]||'';const cleanPathParts=path.split('/').filter(Boolean);let viewTarget='about',modelTarget=null,keyTarget=null,domainTarget='all',creatorTarget='all',metricTarget='pct_complete_overall',highlightTarget='none';if(cleanPathParts[0]==='overview'){viewTarget='overview';}else if(cleanPathParts[0]==='model'&&cleanPathParts[1]){viewTarget='model_detail';modelTarget=decodeURIComponent(cleanPathParts[1]);}else if(cleanPathParts[0]==='questions'){viewTarget=cleanPathParts[1]?'question_theme_detail':'question_themes';if(cleanPathParts[1])keyTarget=decodeURIComponent(cleanPathParts[1]);}else if(cleanPathParts[0]==='timeline'){viewTarget='model_timeline';const p=new URLSearchParams(query);domainTarget=p.get('domain')||'all';creatorTarget=p.get('creator')||'all';metricTarget=p.get('metric')||'pct_complete_overall';highlightTarget=p.get('highlight')||'none';}else if(cleanPathParts[0]==='acknowledgments'){viewTarget='acknowledgments';}const viewChanged=viewTarget!==previousView;const modelChanged=modelTarget!==previousModel;const keyChanged=keyTarget!==previousKey;const coreChange=viewChanged||modelChanged||keyChanged;const shouldProceed=coreChange||forceUpdate||isFromHashChange;if(!shouldProceed&&!this.isMetadataLoaded){if(viewTarget!==this.currentView)this.currentView=viewTarget;return}if(!shouldProceed){return;}this.currentView=viewTarget;this.selectedModel=modelTarget;this.selectedGroupingKey=keyTarget;this.currentThemeAnchor=anchor;if(viewTarget==='model_timeline'&&this.isMetadataLoaded){const vDom=domainTarget==='all'||this.availableFilters.domains.includes(domainTarget);const vCre=creatorTarget==='all'||this.availableFilters.creators.includes(creatorTarget);const vMet=Object.keys(JUDGMENT_KEYS).includes(metricTarget);const vHi=highlightTarget==='none'||this.availableFilters.creators.includes(highlightTarget);this.timelineFilterDomain=vDom?domainTarget:'all';this.timelineFilterCreator=vCre?creatorTarget:'all';this.timelineFilterJudgment=vMet?metricTarget:'pct_complete_overall';this.timelineHighlightCreator=vHi?highlightTarget:'none';}let loadTriggered=false;if(this.currentView==='question_theme_detail'&&(keyChanged||forceUpdate||(isFromHashChange&&viewChanged))){this.loadThemeDetailData(this.selectedGroupingKey,this.currentThemeAnchor);loadTriggered=true;}if(coreChange||forceUpdate||isFromHashChange){this.destroyAllUI();this.$nextTick(()=>{try{if(this.currentView==='overview'){this.initOverviewTable();}else if(this.currentView==='question_themes'){this.initQuestionThemesTable();}else if(this.currentView==='model_detail'){this.initModelDetailTable();}else if(this.currentView==='model_timeline'){this.initOrUpdateTimelineChart();}}catch(error){console.error(`Error init UI ${this.currentView}:`,error);this.errorMessage=`Error render ${this.currentView}.`;}if(this.currentView==='question_theme_detail'&&this.currentThemeAnchor){this.attemptScrollToAnchor(this.currentThemeAnchor);}});}if(this.isMetadataLoaded){if(this.currentView==='model_detail'&&this.selectedModel&&!this.availableFilters.models.includes(this.selectedModel)){console.warn(`Model '${this.selectedModel}' invalid.`);this.navigate('about',true);return;}if(this.currentView==='question_theme_detail'&&this.selectedGroupingKey&&!this.availableFilters.grouping_keys.includes(this.selectedGroupingKey)){console.warn(`Key '${this.selectedGroupingKey}' invalid.`);this.navigate('question_themes',true);return;}} },
        navigate(view, replaceHistory = false, selectionKey = null, anchor = null) { /* Unchanged */ let bp='#/',qp='';if(view==='overview'){bp+='overview';}else if(view==='question_themes'){bp+='questions';}else if(view==='model_timeline'){bp+='timeline';const p=new URLSearchParams();if(this.timelineFilterDomain!=='all')p.set('domain',this.timelineFilterDomain);if(this.timelineFilterCreator!=='all')p.set('creator',this.timelineFilterCreator);if(this.timelineFilterJudgment!=='pct_complete_overall')p.set('metric',this.timelineFilterJudgment);if(this.timelineHighlightCreator!=='none')p.set('highlight',this.timelineHighlightCreator);qp=p.toString();}else if(view==='model_detail'){const m=selectionKey||this.selectedModel;if(m)bp+=`model/${encodeURIComponent(m)}`;else{console.warn("Missing model key");return;}}else if(view==='question_theme_detail'){const k=selectionKey||this.selectedGroupingKey;if(k)bp+=`questions/${encodeURIComponent(k)}`;else{console.warn("Missing theme key");return;}}else if(view==='about'){bp+='about';}else if(view==='acknowledgments'){bp+='acknowledgments';}else{console.warn("Invalid view:",view);bp+='about';}let paq=bp;if(qp)paq+='?'+qp;let fh=paq;if(anchor){fh+='#'+anchor;}if(location.hash!==fh){this.internalNavigationInProgress=true;if(replaceHistory){history.replaceState(null,'',fh);}else{history.pushState(null,'',fh);}this.parseHash();this.$nextTick(()=>{this.internalNavigationInProgress=false;});}else{if(view==='question_theme_detail'&&anchor&&this.currentThemeAnchor!==anchor){this.currentThemeAnchor=anchor;this.attemptScrollToAnchor(anchor);}else if(!['model_timeline','question_theme_detail','acknowledgments','about'].includes(view)){this.parseHash(true);}} },
        updateTimelineUrlParams() { /* Unchanged */ if(this.currentView!=='model_timeline'||!this.isMetadataLoaded)return;const p=new URLSearchParams();if(this.timelineFilterDomain!=='all')p.set('domain',this.timelineFilterDomain);if(this.timelineFilterCreator!=='all')p.set('creator',this.timelineFilterCreator);if(this.timelineFilterJudgment!=='pct_complete_overall')p.set('metric',this.timelineFilterJudgment);if(this.timelineHighlightCreator!=='none')p.set('highlight',this.timelineHighlightCreator);const qs=p.toString();const nh=qs?`#/timeline?${qs}`:'#/timeline';if(location.hash!==nh){this.internalNavigationInProgress=true;history.replaceState(null,'',nh);this.$nextTick(()=>{this.internalNavigationInProgress=false;});} },
        selectModel(modelName) { this.navigate('model_detail', false, modelName); },
        selectQuestionTheme(groupingKey, modelAnchorId = null) { this.navigate('question_theme_detail', false, groupingKey, modelAnchorId); },

        // --- UI Initialization Methods ---
        initOverviewTable() { /* Unchanged */ const t=document.getElementById("overview-table"); if(!t||this.currentView!=='overview'||!this.isMetadataLoaded)return; this.overviewTable=new Tabulator(t,{ data:[...this.modelSummaryData], layout:"fitDataFill", height:"60vh", placeholder:"No models.", selectable:false, initialSort:[{column:"pct_complete_overall",dir:"asc"}], responsiveLayout:"collapse", columns: [{title:"Model",field:"model",widthGrow:2,frozen:true,headerFilter:"input",cellClick:(e,c)=>this.selectModel(c.getRow().getData().model),cssClass:"clickable-cell",responsive:0},{title:"Released",field:"release_date",width:110,sorter:dateSorterNullable,headerFilter:"input",hozAlign:"center",responsive:2},{title:"# Resp",field:"num_responses",width:90,hozAlign:"right",sorter:"number",responsive:3},{title:"% Comp",field:"pct_complete_overall",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.COMPLETE},responsive:0},{title:"% Evas",field:"pct_evasive",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.EVASIVE},responsive:1},{title:"% Deny",field:"pct_denial",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.DENIAL},responsive:1},{title:"% Err",field:"pct_error",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.ERROR},responsive:1}], }); },
        initQuestionThemesTable() { /* Unchanged */ const t=document.getElementById("question-themes-table"); if(!t||this.currentView!=='question_themes'||!this.isMetadataLoaded)return; const d=this.questionThemeSummary; this.questionThemesTable=new Tabulator(t,{ data:[...d], layout:"fitDataFill", height:"60vh", placeholder:"No themes matching filters.", selectable:false, initialSort:[{column:"pct_complete_overall",dir:"asc"}], responsiveLayout:"collapse", columns: [{title:"Grouping Key",field:"grouping_key",widthGrow:2,frozen:true,headerFilter:"input",cellClick:(e,c)=>this.selectQuestionTheme(c.getRow().getData().grouping_key),cssClass:"clickable-cell",responsive:0},{title:"Domain",field:"domain",width:150,headerFilter:"select",headerFilterParams:{values:["",...this.availableFilters.domains]},responsive:2},{title:"Models",field:"num_models",width:100,hozAlign:"right",sorter:"number",responsive:3},{title:"# Resp",field:"num_responses",width:90,hozAlign:"right",sorter:"number",responsive:3},{title:"% Complete",field:"pct_complete_overall",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.COMPLETE},responsive:0},{title:"% Evas",field:"pct_evasive",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.EVASIVE},responsive:1},{title:"% Deny",field:"pct_denial",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.DENIAL},responsive:1},{title:"% Err",field:"pct_error",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.ERROR},responsive:1}], }); },
        initModelDetailTable() { /* Modified for lazy model themes */ const t=document.getElementById("model-detail-table"); if(!t||this.currentView!=='model_detail'||!this.selectedModel||!this.isMetadataLoaded)return; const d=this.selectedModelQuestionSummary; this.modelDetailTable=new Tabulator(t,{ data:[...d], layout:"fitDataFill", height:"60vh", placeholder:"Loading model themes...", selectable:false, initialSort:[{column:"pct_complete",dir:"asc"}], responsiveLayout:"collapse", columns: [{title:"Grouping Key",field:"grouping_key",widthGrow:2,frozen:true,headerFilter:"input",cellClick:(e,c)=>{const r=c.getRow().getData();const k=r.grouping_key;const a=`model-${this.generateAnchorId(this.selectedModel)}`;this.selectQuestionTheme(k,a);},cssClass:"clickable-cell",responsive:0},{title:"Domain",field:"domain",width:150,headerFilter:"select",headerFilterParams:{values:["",...this.availableFilters.domains.filter(dm=>d.some(q=>q.domain===dm))]},responsive:2},{title:"# Resp",field:"num_responses",width:90,hozAlign:"right",sorter:"number",responsive:3},{title:"% Complete",field:"pct_complete",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.COMPLETE},responsive:0},{title:"% Evas",field:"pct_evasive",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.EVASIVE},responsive:1},{title:"% Deny",field:"pct_denial",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.DENIAL},responsive:1},{title:"% Err",field:"pct_error",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.ERROR},responsive:1}], }); this.ensureModelThemesLoaded(this.selectedModel).then(()=>{try{const nd=this.selectedModelQuestionSummary; if(this.modelDetailTable) this.modelDetailTable.setData(nd);}catch(e){console.error('Err set model detail data:',e);}}).catch(e=>{console.error('Load model themes fail:',e);}); },

        async initOrUpdateTimelineChart() {
            if (this.currentView !== 'model_timeline' || !this.isMetadataLoaded || !this.minReleaseDate || !this.maxReleaseDate) return;
            // Ensure domain summary loaded
            try { await this.ensureModelDomainSummaryLoaded(); } catch (e) { console.error('Domain summary load failed', e); return; }
            this.destroyChart(this.timelineChart);
            const cvs=document.getElementById('timeline-chart-canvas'); if (!cvs){console.error("Canvas not found");return;} const ctx=cvs.getContext('2d'); if(!ctx){console.error("Context not found");return;}
            this.currentChartInitId++; const iid=this.currentChartInitId; const pts=this.timelineChartData; const ji=JUDGMENT_KEYS[this.timelineFilterJudgment]; const yl=ji?ji.label:'%'; const hc=this.timelineHighlightCreator;
            try {
                if(this.currentView!=='model_timeline'||iid!==this.currentChartInitId){console.warn(`Chart init ${iid} abort`);return;}
                const ch=new Chart(ctx,{
                    type:'scatter',
                    data:{datasets:[{label:'Models',data:pts,pointBackgroundColor:c=>{const cr=c.raw?.creator||UNKNOWN_CREATOR;return(hc==='none'||cr===hc)?(ji?.color||'#bdc3c7'):HIGHLIGHT_COLORS.fadedBackground;},pointBorderColor:c=>{const cr=c.raw?.creator||UNKNOWN_CREATOR;return(hc==='none'||cr===hc)?(ji?.color||'#bdc3c7'):HIGHLIGHT_COLORS.fadedBorder;},pointRadius:5,pointHoverRadius:7}]},
                    options:{
                        responsive:true, maintainAspectRatio:false,
                        // Disable animations
                        animation: false, // ADDED THIS LINE
                        onClick:(e)=>{const els=this.timelineChart?.getElementsAtEventForMode(e,'point',{intersect:true},true);if(els&&els.length>0){const{datasetIndex:di,index:idx}=els[0];const p=this.timelineChart.config.data.datasets[di].data[idx];if(p&&p.label)this.navigate('model_detail',false,p.label);}},
                        scales:{x:{type:'time',min:this.minReleaseDate?.valueOf(),max:this.maxReleaseDate?.valueOf(),time:{unit:'month',tooltipFormat:'yyyy-MM-dd',displayFormats:{month:'yyyy-MM',year:'yyyy'}},title:{display:true,text:'Model Release Date'},ticks:{source:'auto',maxRotation:45,minRotation:0}},y:{title:{display:true,text:yl},min:0,max:100,ticks:{callback:v=>v+'%'}}},
                        plugins:{tooltip:{callbacks:{label:c=>{const p=c.raw;let l=p.label||'';if(l)l+=': ';l+=`${p.y.toFixed(1)}%`;if(p.creator)l+=` (${p.creator})`;return l;}}},legend:{display:false}}
                    }
                });
                if(iid===this.currentChartInitId)this.timelineChart=ch;else{ch.destroy();this.timelineChart=null;}
            } catch (error) { console.error(`Chart init err (ID:${iid}):`,error); this.errorMessage="Chart render fail."; this.timelineChart=null; }
        },

        // --- UI Cleanup ---
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyChart(chartInstance) { if (chartInstance) { try { chartInstance.destroy(); } catch (e) {} } return null; },
        destroyAllUI() { this.overviewTable = this.destroyTable(this.overviewTable); this.questionThemesTable = this.destroyTable(this.questionThemesTable); this.modelDetailTable = this.destroyTable(this.modelDetailTable); this.timelineChart = this.destroyChart(this.timelineChart); this.overviewTable = null; this.questionThemesTable = null; this.modelDetailTable = null; this.timelineChart = null; },

        // --- Watchers --- (Only for filters)
        setupWatchers() {
             this.$watch('timelineFilterDomain', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('timelineFilterJudgment', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('timelineFilterCreator', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('timelineHighlightCreator', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('questionThemeTimeFilter', () => { if (this.currentView === 'question_themes' && this.isMetadataLoaded) { this.fetchQuestionThemeBin(this.questionThemeTimeFilter).then(()=>{ if (this.questionThemesTable) { try { this.questionThemesTable.setData(this.questionThemeSummary); } catch (e) { console.error("Err set QThemes data:", e); } } }).catch(e=>{ console.error('QTheme bin load fail:', e); }); } });
        },

        // --- Helper Methods ---
        getVariationDescription(v) { return VARIATION_MAP[String(v)] || `Type ${v||'N/A'}`; },
        renderMarkdown(t) { if (!t) return ''; try { return DOMPurify.sanitize(marked.parse(t),{USE_PROFILES:{html:true}}); } catch (e) { console.error("MD err:", e); return `<pre>Err:\n${sanitize(t)}</pre>`; } },
        doSmoothScroll(selector) { const el = document.querySelector(selector); if(el){ setTimeout(() => { el.scrollIntoView({behavior:'smooth',block:'start'}); }, 50); } else { console.warn("[doSmoothScroll] Target element not found:", selector); } },
        attemptScrollToAnchor(anchorId, retries = 10) { if (!anchorId || retries <= 0) return; const selector = anchorId.startsWith('#') ? anchorId : '#' + anchorId; const el = document.querySelector(selector); if (el) { this.doSmoothScroll(selector); } else { setTimeout(() => this.attemptScrollToAnchor(anchorId, retries - 1), 150); } },
        smoothScroll(selector, updateHistory = false) { const idSelector = selector.startsWith('#') ? selector : '#' + selector; const anchorId = selector.startsWith('#') ? selector.substring(1) : selector; if (updateHistory) { const basePath = `#/questions/${encodeURIComponent(this.selectedGroupingKey)}`; const newHash = `${basePath}#${anchorId}`; if (location.hash !== newHash) { this.internalNavigationInProgress = true; history.pushState(null, '', newHash); this.currentThemeAnchor = anchorId; this.$nextTick(() => { this.internalNavigationInProgress = false; }); this.doSmoothScroll(idSelector); } else { this.doSmoothScroll(idSelector); } } else { this.doSmoothScroll(idSelector); } },
        getComplianceBoxStyle(p) { let c='#bdc3c7'; if(typeof p==='number'&&!isNaN(p)){c=p>=90?'#2ecc71':(p>=25?'#f1c40f':'#e74c3c');} const t=(c==='#f1c40f'||c==='#bdc3c7')?'#333':'white'; return `background-color:${c};color:${t};`; },
        groupResponsesByModel(r) { if (!r) return []; const g=r.reduce((a,c)=>{if(!a[c.model]){a[c.model]={model:c.model,responses:[]};}a[c.model].responses.push(c);return a;},{}); return Object.values(g).sort((a,b)=>a.model.localeCompare(b.model)); },
        generateOpenRouterLink(m,p) { const b="https://openrouter.ai/chat"; const mn=m||""; const mp=`${mn}`; const pm=encodeURIComponent(p||""); return `${b}?models=${mp}&message=${pm}`; },
        generateSafeIdForFilename(t) { if (!t) return 'id'; const n=t.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toString(); let s=n.toLowerCase().replace(/[^\w\s-]/g,'-').replace(/[\s-]+/g,'-'); s=s.replace(/^-+|-+$/g,'').substring(0,100); return s||"id"; },
        generateAnchorId(t) { if (!t) return 'id'; const n=t.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toString(); let s=n.toLowerCase().replace(/[^a-z0-9-]/g,'-').replace(/-+/g,'-'); s=s.replace(/^-+|-+$/g,'').substring(0,100); return s||"id"; },
        init() { /* Called from x-init, starts initialize() */ }

    }));
});

// --- Standalone Helper Functions --- (Simplified)
function complianceFormatter(c,p,o){ const v=c.getValue(); if(v==null)return""; const clr=COMPLIANCE_COLORS[v]||'#bdc3c7'; const tc=(v==='EVASIVE'||v==='UNKNOWN')?'#333':'white'; const s=document.createElement('span'); s.textContent=v; s.classList.add('compliance-label'); s.style.backgroundColor=clr; s.style.color=tc; return s; }
function truncateText(t,m=100){if(!t)return""; t=String(t); return t.length<=m?t:t.substring(0,m)+"...";}
function formatDate(d){if(!d)return"N/A";try{return new Date(d).toLocaleString('sv-SE');}catch(e){return d;}}
function sanitize(s){if(s==null)return'';const t=document.createElement('div');t.textContent=String(s);return t.innerHTML;}
function percentWithBgBarFormatter(c,p,o){ const v=c.getValue(); if(typeof v!=='number'||isNaN(v))return""; const clr=p.color||'#bdc3c7'; const ct=document.createElement('div'); ct.classList.add('percent-bar-container'); const b=document.createElement('div'); b.classList.add('percent-bar-bg'); b.style.width=`${v}%`; b.style.backgroundColor=clr; const tx=document.createElement('span'); tx.classList.add('percent-bar-text'); tx.textContent=v.toFixed(1)+'%'; ct.appendChild(b); ct.appendChild(tx); return ct; }
function dateSorterNullable(a,b,aR,bR,col,dir,sorterParams){ const an=a==null||a===undefined||a===''; const bn=b==null||b===undefined||b===''; if(an&&bn)return 0; if(an)return dir==="asc"?1:-1; if(bn)return dir==="asc"?-1:1; try{const dA=new Date(a);const dB=new Date(b);if(!isNaN(dA)&&!isNaN(dB))return dA-dB;}catch(e){} return String(a).localeCompare(String(b)); }
