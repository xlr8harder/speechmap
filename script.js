// script.js
// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const JUDGMENT_KEYS = { 'pct_complete_overall': { label: '% Complete', key: 'k', color: COMPLIANCE_COLORS.COMPLETE }, 'pct_evasive': { label: '% Evasive', key: 'e', color: COMPLIANCE_COLORS.EVASIVE }, 'pct_denial': { label: '% Denial', key: 'd', color: COMPLIANCE_COLORS.DENIAL }, 'pct_error': { label: '% Error', key: 'r', color: COMPLIANCE_COLORS.ERROR } };
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };
const THEME_DETAIL_DIR = 'theme_details'; const UNKNOWN_CREATOR = 'Unknown Creator'; const HIGHLIGHT_COLORS = { fadedBackground: 'rgba(200, 200, 200, 0.7)', fadedBorder: 'rgba(180, 180, 180, 0.7)' };

// --- Alpine.js Data Store ---
document.addEventListener('alpine:init', () => {
    Alpine.data('explorerData', () => ({
        // --- State Variables ---
        loadingMessage: 'Initializing...', errorMessage: null, modelSummaryData: [], rawQuestionThemeSummaryData: [], modelThemeSummaryData: {}, complianceOrder: [], modelMetadata: {}, stats: { models: 0, themes: 0, judgments: 0, complete: 0 }, isMetadataLoading: true, isMetadataLoaded: false, currentThemeDetailData: null, isThemeDetailLoading: false, themeDetailErrorMessage: null, currentView: 'about', selectedModel: null, selectedGroupingKey: null, currentLoadingThemeKey: null, currentThemeAnchor: null,
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

        // --- Computed Properties --- (Simplified for brevity)
        get modelSummary() { return this.modelSummaryData; },
        get questionThemeSummary() { if (!this.isMetadataLoaded || !this.modelMetadata || !this.modelThemeSummaryData) { return []; } const filter = this.questionThemeTimeFilter; const now = new Date(); let cutoffDate = null; if (filter !== 'all') { const m = { '3m': 3, '6m': 6, '12m': 12, '18m': 18, '24m': 24 }[filter]; if (m) { cutoffDate = new Date(now.getFullYear(), now.getMonth() - m, now.getDate()); } } const filteredIds = new Set(); for (const id in this.modelMetadata) { const m = this.modelMetadata[id]; if (!m) continue; if (filter === 'all') { filteredIds.add(id); continue; } if (cutoffDate && m.release_date) { try { const d = new Date(Date.parse(m.release_date)); if (!isNaN(d) && d >= cutoffDate) filteredIds.add(id); } catch (e) {} } } const aggStats = {}; for (const id in this.modelThemeSummaryData) { if (filteredIds.has(id)) { const themes = this.modelThemeSummaryData[id]; for (const key in themes) { const s = themes[key]; const dom = s.domain || 'Unknown'; if (!aggStats[key]) { aggStats[key] = {gk:key,d:dom,c:0,k:0,e:0,dn:0,r:0,m:new Set()}; } aggStats[key].c += (s.c||0); aggStats[key].k += (s.k||0); aggStats[key].e += (s.e||0); aggStats[key].dn += (s.d||0); aggStats[key].r += (s.r||0); aggStats[key].m.add(id); if(aggStats[key].d==='Unknown'&&dom!=='Unknown') aggStats[key].d=dom; }}} const summary = Object.values(aggStats).map(a => { const cnt = a.c; return { grouping_key: a.gk, domain: a.d, num_responses: cnt, num_models: a.m.size, pct_complete_overall: cnt>0?(a.k/cnt*100):0, pct_evasive: cnt>0?(a.e/cnt*100):0, pct_denial: cnt>0?(a.dn/cnt*100):0, pct_error: cnt>0?(a.r/cnt*100):0 }; }); summary.sort((a, b) => { const diff=a.pct_complete_overall-b.pct_complete_overall; return diff!==0?diff:a.grouping_key.localeCompare(b.grouping_key); }); return summary; },
        get selectedModelQuestionSummary() { if (!this.selectedModel || !this.isMetadataLoaded || !this.modelThemeSummaryData) return []; const d = this.modelThemeSummaryData[this.selectedModel]; if (!d) return []; const list = Object.entries(d).map(([k, s]) => { const c=s.c||0; return { grouping_key: k, domain: s.domain||'N/A', num_responses: c, pct_complete: c>0?((s.k||0)/c*100):0, pct_evasive: c>0?((s.e||0)/c*100):0, pct_denial: c>0?((s.d||0)/c*100):0, pct_error: c>0?((s.r||0)/c*100):0 }; }); const filtered = list.filter(i => this.activeModelDomainFilters.length === 0 || this.activeModelDomainFilters.includes(i.domain)); filtered.sort((a, b) => { const diff=a.pct_complete-b.pct_complete; return diff!==0?diff:a.grouping_key.localeCompare(b.grouping_key); }); return filtered; },
        get selectedModelData() { if (!this.selectedModel || !this.isMetadataLoaded) return null; return this.modelSummaryData.find(m => m.model === this.selectedModel) || null; },
        get selectedModelFullMetadata() { if (!this.selectedModel || !this.isMetadataLoaded || !this.modelMetadata) return null; return this.modelMetadata[this.selectedModel] || null; },
        get selectedQuestionThemeData() { if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null; const t = this.questionThemeSummary.find(t => t.grouping_key === this.selectedGroupingKey); if (!t && this.rawQuestionThemeSummaryData) { const r=this.rawQuestionThemeSummaryData.find(t=>t.grouping_key===this.selectedGroupingKey); if (r) return {grouping_key:this.selectedGroupingKey,domain:r.domain}; } return t ? {grouping_key:this.selectedGroupingKey,domain:t.domain} : {grouping_key:this.selectedGroupingKey,domain:'N/A'}; },
        get selectedQuestionThemeModelSummary() { if (!this.currentThemeDetailData || !this.currentThemeDetailData.records) return []; const s = {}; this.currentThemeDetailData.records.forEach(r=>{ if(!s[r.model]){s[r.model]={m:r.model,aid:r.anchor_id,c:0,cc:0};} s[r.model].c++; if(r.compliance==='COMPLETE')s[r.model].cc++; if(!s[r.model].aid)s[r.model].aid=r.anchor_id; }); return Object.values(s).map(i => ({model: i.m, anchor_id: i.aid, count: i.c, pct_complete: i.c>0?(i.cc/i.c*100):0})).sort((a, b) => a.model.localeCompare(b.model)); },
        get filteredOrDeniedPercentage() { if (!this.stats || this.stats.judgments === 0) return 'N/A'; const c=this.stats.complete||0; const t=this.stats.judgments; return ((1-(c/t))*100).toFixed(1); },
        getDomainForSelectedTheme() { if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null; const t = this.questionThemeSummary.find(t => t.grouping_key === this.selectedGroupingKey); if (t) return t.domain; const r = this.rawQuestionThemeSummaryData.find(t => t.grouping_key === this.selectedGroupingKey); return r ? r.domain : 'Unknown'; },
        get timelineChartData() { if (!this.isMetadataLoaded) return []; const ji=JUDGMENT_KEYS[this.timelineFilterJudgment]; if (!ji) {console.error("Inv judgment key:", this.timelineFilterJudgment); return [];} const jsk=ji.key; const pts=[]; for (const n in this.modelMetadata) { const m=this.modelMetadata[n]; const c=m.creator||UNKNOWN_CREATOR; const rds=m.release_date; if (this.timelineFilterCreator!=='all'&&c!==this.timelineFilterCreator) continue; let rd=null; if(rds){try{let p=Date.parse(rds); if(!isNaN(p))rd=new Date(p);}catch(e){}} if (!rd) continue; let ft=0; let fjc=0; const mtd=this.modelThemeSummaryData[n]; if (mtd) { for (const tk in mtd) { const s=mtd[tk]; if (this.timelineFilterDomain==='all'||s.domain===this.timelineFilterDomain){ ft+=(s.c||0); fjc+=(s[jsk]||0); }}} if (ft===0) continue; const yv=(ft>0)?(fjc/ft*100):0; pts.push({x:rd, y:yv, label:n, creator:c}); } pts.sort((a, b) => a.x - b.x); return pts; },

        formatJudgments(num) { /* Unchanged */ if (typeof num !== 'number' || isNaN(num)) return '0'; if (num >= 10000) return Math.floor(num / 1000) + 'K+'; return num.toLocaleString(); },
        formatModelMetaKey(key) { /* Unchanged */ if (!key) return ''; return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()); },
        formatModelMetaValue(value) { /* Unchanged */ if (typeof value === 'boolean') return value ? 'Yes' : 'No'; return value; },

        // --- Methods ---
        async initialize() {
            this.isMetadataLoading = true; this.loadingMessage = 'Loading metadata...'; /* ... */ this.internalNavigationInProgress = false;

            // 1. Parse hash immediately on load to set initial view target, even before data loads.
            this.parseHash();
            // 2. Setup watchers now, so they react to state changes from the final parseHash later.
            this.setupWatchers();

            // 3. Load metadata asynchronously.
            try { await this.loadMetadata(); this.isMetadataLoaded = true; this.isMetadataLoading = false; this.loadingMessage = ''; this.errorMessage = null;
            } catch (e) { console.error("Init error:", e); this.errorMessage = `Failed load: ${e.message}`; this.isMetadataLoading = false; this.loadingMessage = ''; }

            // 4. Setup the hashchange listener to handle subsequent back/forward navigation.
            window.addEventListener('hashchange', () => {
                // If internalNavigationInProgress is true, it means this event was triggered by our
                // own history.pushState/replaceState call in `navigate()` or `smoothScroll()`.
                // We ignore the event to prevent double-processing and reset the flag.
                if (this.internalNavigationInProgress) {
                    this.internalNavigationInProgress = false;
                    // console.log("[hashchange] Ignored internal navigation event."); // DEBUG
                    return;
                }
                // If the flag was false, this was a user action (back/forward), so parse the hash.
                // Pass `isFromHashChange = true` to ensure `parseHash` processes the update.
                // console.log("[hashchange] User navigation detected, parsing hash."); // DEBUG
                this.parseHash(false, true);
            });

            // 5. If metadata loaded successfully, parse the hash AGAIN, forcing an update.
            // This ensures the correct view/state is established based on the URL *after*
            // all necessary data (filters, etc.) is available. parseHash will handle UI init.
            if (this.isMetadataLoaded) {
                 this.parseHash(true);
            }
            // MAINTENANCE NOTE: The order is important: initial parse -> watchers -> load data -> hash listener -> final parse.
        },
        async loadMetadata() { /* Unchanged */ try{const r=await fetch('metadata.json?2',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();if(!d.complianceOrder||!d.model_metadata||!d.stats||!d.model_summary||!d.question_theme_summary||!d.model_theme_summary)throw new Error("Missing keys.");this.complianceOrder=d.complianceOrder;this.modelMetadata=d.model_metadata;this.stats=d.stats;this.modelSummaryData=d.model_summary;this.rawQuestionThemeSummaryData=d.question_theme_summary;this.modelThemeSummaryData=d.model_theme_summary;this.availableFilters.models=this.modelSummaryData.map(m=>m.model).sort();this.availableFilters.domains=[...new Set(this.rawQuestionThemeSummaryData.map(q=>q.domain))].sort();this.availableFilters.grouping_keys=this.rawQuestionThemeSummaryData.map(q=>q.grouping_key).sort();this.availableFilters.variations=['1','2','3','4'];const c=new Set();Object.values(this.modelMetadata).forEach(m=>{c.add(m.creator||UNKNOWN_CREATOR);});this.availableFilters.creators=[...c].sort();let e=null;Object.values(this.modelMetadata).forEach(m=>{if(m.release_date){try{const dt=new Date(Date.parse(m.release_date));if(!isNaN(dt))if(e===null||dt<e)e=dt;}catch(err){}}});const t=new Date();const mm=30*24*60*60*1000;if(e)this.minReleaseDate=new Date(e.getTime()-mm);else this.minReleaseDate=new Date(t.getTime()-6*mm);this.maxReleaseDate=new Date(t.getTime()+mm);}catch(e){console.error("Metadata load fail:",e);this.minReleaseDate=null;this.maxReleaseDate=null;throw new Error(`Meta Load Fail:${e.message}`);} },

        async loadThemeDetailData(groupingKey, anchor = null) {
             // Handles loading data for the question detail page. Scroll logic is handled elsewhere.
             const targetAnchor = anchor || this.currentThemeAnchor;
             if (!groupingKey) return;
             if (this.currentLoadingThemeKey === groupingKey) return;
             // Don't return early if key is same, anchor might need update via parseHash->attemptScroll
             // if (this.selectedGroupingKey === groupingKey && this.currentThemeDetailData) { return; }

             this.selectedGroupingKey = groupingKey; // State should already be set by parseHash
             this.isThemeDetailLoading = true;
             this.themeDetailErrorMessage = null;
             this.currentThemeDetailData = null;
             this.currentLoadingThemeKey = groupingKey;
             // this.currentThemeAnchor = targetAnchor; // Anchor state set by parseHash

             await this.$nextTick();
             try {
                 const safeFile = this.generateSafeIdForFilename(groupingKey);
                 const fPath = `${THEME_DETAIL_DIR}/${safeFile}.json.gz`;
                 const r = await fetch(fPath, { cache: 'no-store', headers: { 'Accept-Encoding': 'gzip' } });
                 if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${fPath}`);
                 const compData = await r.arrayBuffer();
                 const decompData = pako.inflate(new Uint8Array(compData), { to: 'string' });
                 const json = JSON.parse(decompData);
                 if (!json.records || !Array.isArray(json.records)) throw new Error(`Invalid data structure: ${fPath}`);
                 json.records.sort((a, b) => a.model.localeCompare(b.model) || parseInt(a.variation) - parseInt(b.variation));

                 if (this.currentLoadingThemeKey === groupingKey) { // Still relevant?
                    this.currentThemeDetailData = json; // Update data
                    // Scroll is now handled by attemptScrollToAnchor triggered from parseHash
                 }
             } catch (e) {
                 console.error(`Theme detail load fail: ${groupingKey}`, e);
                 if (this.currentLoadingThemeKey === groupingKey) {
                    this.themeDetailErrorMessage = `Failed load: ${e.message}`;
                    this.currentThemeDetailData = null;
                 }
             } finally {
                 if (this.currentLoadingThemeKey === groupingKey) {
                    this.isThemeDetailLoading = false;
                    this.currentLoadingThemeKey = null;
                 }
             }
        },

        /**
         * @function parseHash
         * @description The central function for handling application state based on the URL hash.
         * It reads the hash, updates the core Alpine state variables (currentView, selectedModel, etc.),
         * triggers data loading if necessary (for question_theme_detail), destroys existing UI components,
         * and schedules the initialization of new UI components in the next tick.
         * It also handles triggering the anchor scroll attempt for deep links.
         * @param {boolean} forceUpdate - If true, forces UI re-initialization even if state appears unchanged.
         * @param {boolean} isFromHashChange - If true, indicates the call originated from the browser's hashchange event (back/forward).
         * @returns {void}
         * MAINTENANCE NOTE: This function is the core navigation controller. Changes here affect
         * view rendering, data loading triggers, and UI lifecycle. Ensure state updates happen
         * before UI destruction/creation. The `shouldProceed` logic prevents unnecessary work.
         */
        parseHash(forceUpdate = false, isFromHashChange = false) {
            const previousView = this.currentView; const previousModel = this.selectedModel; const previousKey = this.selectedGroupingKey;
            const fullHash = location.hash.slice(1); const anchorMatch = fullHash.match(/#([^#]*)$/); const anchor = anchorMatch ? anchorMatch[1] : null; const pathAndQuery = anchorMatch ? fullHash.substring(0, anchorMatch.index) : fullHash; const pathParts = pathAndQuery.split('?'); const path = pathParts[0]; const query = pathParts[1] || ''; const cleanPathParts = path.split('/').filter(Boolean);
            let viewTarget = 'about', modelTarget = null, keyTarget = null, domainTarget = 'all', creatorTarget = 'all', metricTarget = 'pct_complete_overall', highlightTarget = 'none';

            if (cleanPathParts[0] === 'overview') { viewTarget = 'overview'; }
            else if (cleanPathParts[0] === 'model' && cleanPathParts[1]) { viewTarget = 'model_detail'; modelTarget = decodeURIComponent(cleanPathParts[1]); }
            else if (cleanPathParts[0] === 'questions') { viewTarget = cleanPathParts[1] ? 'question_theme_detail' : 'question_themes'; if (cleanPathParts[1]) keyTarget = decodeURIComponent(cleanPathParts[1]); }
            else if (cleanPathParts[0] === 'timeline') { viewTarget = 'model_timeline'; const p = new URLSearchParams(query); domainTarget = p.get('domain') || 'all'; creatorTarget = p.get('creator') || 'all'; metricTarget = p.get('metric') || 'pct_complete_overall'; highlightTarget = p.get('highlight') || 'none'; }
            else if (cleanPathParts[0] === 'acknowledgments') { viewTarget = 'acknowledgments'; }

            const viewChanged = viewTarget !== previousView; const modelChanged = modelTarget !== previousModel; const keyChanged = keyTarget !== previousKey;
            const coreChange = viewChanged || modelChanged || keyChanged;
            // Proceed if core state changed, or forced, or triggered by user back/forward.
            const shouldProceed = coreChange || forceUpdate || isFromHashChange;

            if (!shouldProceed && !this.isMetadataLoaded) { if (viewTarget !== this.currentView) this.currentView = viewTarget; return }
            if (!shouldProceed) { return; }

            // --- Update State ---
            this.currentView = viewTarget; this.selectedModel = modelTarget; this.selectedGroupingKey = keyTarget; this.currentThemeAnchor = anchor; // Set anchor state here
            if (viewTarget === 'model_timeline' && this.isMetadataLoaded) { const vDom=domainTarget==='all'||this.availableFilters.domains.includes(domainTarget); const vCre=creatorTarget==='all'||this.availableFilters.creators.includes(creatorTarget); const vMet=Object.keys(JUDGMENT_KEYS).includes(metricTarget); const vHi=highlightTarget==='none'||this.availableFilters.creators.includes(highlightTarget); this.timelineFilterDomain=vDom?domainTarget:'all'; this.timelineFilterCreator=vCre?creatorTarget:'all'; this.timelineFilterJudgment=vMet?metricTarget:'pct_complete_overall'; this.timelineHighlightCreator=vHi?highlightTarget:'none'; }

            // --- Trigger Data Load (if needed) ---
            // Load data for theme detail *before* scheduling UI init.
            if (this.currentView === 'question_theme_detail' && (keyChanged || forceUpdate || (isFromHashChange && viewChanged))) {
                 this.loadThemeDetailData(this.selectedGroupingKey, this.currentThemeAnchor);
            }

            // --- Destroy/Recreate UI ---
            // Destroy existing UI components relevant to the *previous* view.
            this.destroyAllUI();

            // Schedule UI initialization for the new view state in the next tick.
            // This allows Alpine's x-show directives to update the DOM first.
            this.$nextTick(() => {
                try {
                    // Initialize the UI components relevant to the *current* view.
                    if (this.currentView === 'overview') { this.initOverviewTable(); }
                    else if (this.currentView === 'question_themes') { this.initQuestionThemesTable(); }
                    else if (this.currentView === 'model_detail') { this.initModelDetailTable(); }
                    else if (this.currentView === 'model_timeline') { this.initOrUpdateTimelineChart(); }
                } catch (error) { console.error(`Error init UI ${this.currentView}:`, error); this.errorMessage = `Error render ${this.currentView}.`; }

                // Trigger scroll attempt *after* scheduling UI init. The polling handles timing.
                 if (this.currentView === 'question_theme_detail' && this.currentThemeAnchor) {
                    // console.log(`[parseHash $nextTick] Triggering scroll attempt for anchor: ${this.currentThemeAnchor}`); // DEBUG
                    this.attemptScrollToAnchor(this.currentThemeAnchor);
                }
            });

             // --- Validation --- (Run after state updates)
             if (this.isMetadataLoaded) { if (this.currentView === 'model_detail' && this.selectedModel && !this.availableFilters.models.includes(this.selectedModel)) { console.warn(`Model '${this.selectedModel}' invalid.`); this.navigate('about', true); return; } if (this.currentView === 'question_theme_detail' && this.selectedGroupingKey && !this.availableFilters.grouping_keys.includes(this.selectedGroupingKey)) { console.warn(`Key '${this.selectedGroupingKey}' invalid.`); this.navigate('question_themes', true); return; } }
        },

        /**
         * @function navigate
         * @description Handles programmatic navigation triggered by UI interactions (button clicks, etc.).
         * Updates the URL hash, sets a flag to prevent the hashchange listener from processing
         * this change, and calls parseHash() immediately to update the application state and UI.
         * @param {string} view - The target view name.
         * @param {boolean} replaceHistory - If true, use replaceState instead of pushState.
         * @param {string|null} selectionKey - Model name or grouping key for detail views.
         * @param {string|null} anchor - Optional anchor to append to the hash.
         * @returns {void}
         * MAINTENANCE NOTE: This function *must* set `internalNavigationInProgress = true` before
         * modifying history and call `parseHash()` itself to ensure the UI updates synchronously
         * with the user's action. The flag is reset asynchronously.
         */
        navigate(view, replaceHistory = false, selectionKey = null, anchor = null) {
            let basePath = '#/', queryParams = '';
            if (view === 'overview') { basePath += 'overview'; }
            else if (view === 'question_themes') { basePath += 'questions'; }
            else if (view === 'model_timeline') { basePath += 'timeline'; const p = new URLSearchParams(); if(this.timelineFilterDomain !== 'all') p.set('domain', this.timelineFilterDomain); if(this.timelineFilterCreator !== 'all') p.set('creator', this.timelineFilterCreator); if(this.timelineFilterJudgment !== 'pct_complete_overall') p.set('metric', this.timelineFilterJudgment); if(this.timelineHighlightCreator !== 'none') p.set('highlight', this.timelineHighlightCreator); queryParams = p.toString(); }
            else if (view === 'model_detail') { const m = selectionKey || this.selectedModel; if (m) basePath += `model/${encodeURIComponent(m)}`; else { console.warn("Missing model key"); return; } }
            else if (view === 'question_theme_detail') { const k = selectionKey || this.selectedGroupingKey; if (k) basePath += `questions/${encodeURIComponent(k)}`; else { console.warn("Missing theme key"); return; } }
            else if (view === 'about') { basePath += 'about'; } else if (view === 'acknowledgments') { basePath += 'acknowledgments'; }
            else { console.warn("Invalid view:", view); basePath += 'about'; }

            let pathAndQuery = basePath; if (queryParams) pathAndQuery += '?' + queryParams; let finalHash = pathAndQuery; if (anchor) { finalHash += '#' + anchor; }

            if (location.hash !== finalHash) {
                 this.internalNavigationInProgress = true; // Set flag *before* changing history
                 if (replaceHistory) { history.replaceState(null, '', finalHash); } else { history.pushState(null, '', finalHash); }
                 this.parseHash(); // Call parseHash immediately AFTER changing history and setting flag
                 // Reset the flag AFTER the current execution context finishes.
                 // This allows the immediate hashchange event (if it fires synchronously) to be ignored.
                 this.$nextTick(() => {
                     this.internalNavigationInProgress = false;
                 });
            } else {
                 // Handle navigating to the same hash (e.g., clicking current nav item, or same anchor)
                 if (view === 'question_theme_detail' && anchor && this.currentThemeAnchor !== anchor) {
                      // If only the anchor within the detail view changes, update state and scroll.
                      this.currentThemeAnchor = anchor;
                      this.attemptScrollToAnchor(anchor); // Use polling scroll
                 } else if (!['model_timeline', 'question_theme_detail', 'acknowledgments', 'about'].includes(view)) {
                     // Force re-parse/re-init for certain views if clicked again
                      this.parseHash(true);
                 }
             }
        },
        updateTimelineUrlParams() { /* Unchanged */ if(this.currentView!=='model_timeline'||!this.isMetadataLoaded)return;const p=new URLSearchParams();if(this.timelineFilterDomain!=='all')p.set('domain',this.timelineFilterDomain);if(this.timelineFilterCreator!=='all')p.set('creator',this.timelineFilterCreator);if(this.timelineFilterJudgment!=='pct_complete_overall')p.set('metric',this.timelineFilterJudgment);if(this.timelineHighlightCreator!=='none')p.set('highlight',this.timelineHighlightCreator);const qs=p.toString();const nh=qs?`#/timeline?${qs}`:'#/timeline';if(location.hash!==nh){this.internalNavigationInProgress=true;history.replaceState(null,'',nh);this.$nextTick(()=>{this.internalNavigationInProgress=false;});} },
        selectModel(modelName) { this.navigate('model_detail', false, modelName); },
        selectQuestionTheme(groupingKey, modelAnchorId = null) { this.navigate('question_theme_detail', false, groupingKey, modelAnchorId); },

        // --- UI Initialization Methods --- (Called by parseHash via $nextTick)
        initOverviewTable() { /* Unchanged */ const t=document.getElementById("overview-table"); if(!t||this.currentView!=='overview'||!this.isMetadataLoaded)return; this.overviewTable=new Tabulator(t,{ data:[...this.modelSummaryData], layout:"fitDataFill", height:"60vh", placeholder:"No models.", selectable:false, initialSort:[{column:"pct_complete_overall",dir:"asc"}], responsiveLayout:"collapse", columns: [{title:"Model",field:"model",widthGrow:2,frozen:true,headerFilter:"input",cellClick:(e,c)=>this.selectModel(c.getRow().getData().model),cssClass:"clickable-cell",responsive:0},{title:"Released",field:"release_date",width:110,sorter:dateSorterNullable,headerFilter:"input",hozAlign:"center",responsive:2},{title:"# Resp",field:"num_responses",width:90,hozAlign:"right",sorter:"number",responsive:3},{title:"% Comp",field:"pct_complete_overall",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.COMPLETE},responsive:0},{title:"% Evas",field:"pct_evasive",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.EVASIVE},responsive:1},{title:"% Deny",field:"pct_denial",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.DENIAL},responsive:1},{title:"% Err",field:"pct_error",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.ERROR},responsive:1}], }); },
        initQuestionThemesTable() { /* Unchanged */ const t=document.getElementById("question-themes-table"); if(!t||this.currentView!=='question_themes'||!this.isMetadataLoaded)return; const d=this.questionThemeSummary; this.questionThemesTable=new Tabulator(t,{ data:[...d], layout:"fitDataFill", height:"60vh", placeholder:"No themes matching filters.", selectable:false, initialSort:[{column:"pct_complete_overall",dir:"asc"}], responsiveLayout:"collapse", columns: [{title:"Grouping Key",field:"grouping_key",widthGrow:2,frozen:true,headerFilter:"input",cellClick:(e,c)=>this.selectQuestionTheme(c.getRow().getData().grouping_key),cssClass:"clickable-cell",responsive:0},{title:"Domain",field:"domain",width:150,headerFilter:"select",headerFilterParams:{values:["",...this.availableFilters.domains]},responsive:2},{title:"Models",field:"num_models",width:100,hozAlign:"right",sorter:"number",responsive:3},{title:"# Resp",field:"num_responses",width:90,hozAlign:"right",sorter:"number",responsive:3},{title:"% Complete",field:"pct_complete_overall",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.COMPLETE},responsive:0},{title:"% Evas",field:"pct_evasive",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.EVASIVE},responsive:1},{title:"% Deny",field:"pct_denial",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.DENIAL},responsive:1},{title:"% Err",field:"pct_error",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.ERROR},responsive:1}], }); },
        initModelDetailTable() { /* Unchanged */ const t=document.getElementById("model-detail-table"); if(!t||this.currentView!=='model_detail'||!this.selectedModel||!this.isMetadataLoaded)return; const d=this.selectedModelQuestionSummary; this.modelDetailTable=new Tabulator(t,{ data:[...d], layout:"fitDataFill", height:"60vh", placeholder:"No themes for model/filters.", selectable:false, initialSort:[{column:"pct_complete",dir:"asc"}], responsiveLayout:"collapse", columns: [{title:"Grouping Key",field:"grouping_key",widthGrow:2,frozen:true,headerFilter:"input",cellClick:(e,c)=>{const r=c.getRow().getData();const k=r.grouping_key;const a=`model-${this.generateAnchorId(this.selectedModel)}`;this.selectQuestionTheme(k,a);},cssClass:"clickable-cell",responsive:0},{title:"Domain",field:"domain",width:150,headerFilter:"select",headerFilterParams:{values:["",...this.availableFilters.domains.filter(dm=>d.some(q=>q.domain===dm))]},responsive:2},{title:"# Resp",field:"num_responses",width:90,hozAlign:"right",sorter:"number",responsive:3},{title:"% Complete",field:"pct_complete",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.COMPLETE},responsive:0},{title:"% Evas",field:"pct_evasive",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.EVASIVE},responsive:1},{title:"% Deny",field:"pct_denial",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.DENIAL},responsive:1},{title:"% Err",field:"pct_error",width:100,hozAlign:"right",sorter:"number",formatter:percentWithBgBarFormatter,formatterParams:{color:COMPLIANCE_COLORS.ERROR},responsive:1}], }); },
        initOrUpdateTimelineChart() { /* Unchanged */ if(this.currentView!=='model_timeline'||!this.isMetadataLoaded||!this.minReleaseDate||!this.maxReleaseDate)return;this.destroyChart(this.timelineChart);const cvs=document.getElementById('timeline-chart-canvas');if(!cvs){console.error("Canvas not found");return;}const ctx=cvs.getContext('2d');if(!ctx){console.error("Context not found");return;}this.currentChartInitId++;const iid=this.currentChartInitId;const pts=this.timelineChartData;const ji=JUDGMENT_KEYS[this.timelineFilterJudgment];const yl=ji?ji.label:'%';const hc=this.timelineHighlightCreator;try{if(this.currentView!=='model_timeline'||iid!==this.currentChartInitId){console.warn(`Chart init ${iid} abort`);return;}const ch=new Chart(ctx,{type:'scatter',data:{datasets:[{label:'Models',data:pts,pointBackgroundColor:c=>{const cr=c.raw?.creator||UNKNOWN_CREATOR;return(hc==='none'||cr===hc)?(ji?.color||'#bdc3c7'):HIGHLIGHT_COLORS.fadedBackground;},pointBorderColor:c=>{const cr=c.raw?.creator||UNKNOWN_CREATOR;return(hc==='none'||cr===hc)?(ji?.color||'#bdc3c7'):HIGHLIGHT_COLORS.fadedBorder;},pointRadius:5,pointHoverRadius:7}]},options:{responsive:true,maintainAspectRatio:false,onClick:(e)=>{const els=this.timelineChart?.getElementsAtEventForMode(e,'point',{intersect:true},true);if(els&&els.length>0){const{datasetIndex:di,index:idx}=els[0];const p=this.timelineChart.config.data.datasets[di].data[idx];if(p&&p.label)this.navigate('model_detail',false,p.label);}},scales:{x:{type:'time',min:this.minReleaseDate?.valueOf(),max:this.maxReleaseDate?.valueOf(),time:{unit:'month',tooltipFormat:'yyyy-MM-dd',displayFormats:{month:'yyyy-MM',year:'yyyy'}},title:{display:true,text:'Model Release Date'},ticks:{source:'auto',maxRotation:45,minRotation:0}},y:{title:{display:true,text:yl},min:0,max:100,ticks:{callback:v=>v+'%'}}},plugins:{tooltip:{callbacks:{label:c=>{const p=c.raw;let l=p.label||'';if(l)l+=': ';l+=`${p.y.toFixed(1)}%`;if(p.creator)l+=` (${p.creator})`;return l;}}},legend:{display:false}}}});if(iid===this.currentChartInitId)this.timelineChart=ch;else{ch.destroy();this.timelineChart=null;}}catch(error){console.error(`Chart init err (ID:${iid}):`,error);this.errorMessage="Chart render fail.";this.timelineChart=null;} },

        // --- UI Cleanup ---
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyChart(chartInstance) { if (chartInstance) { try { chartInstance.destroy(); } catch (e) {} } return null; },
        destroyAllUI() { this.overviewTable = this.destroyTable(this.overviewTable); this.questionThemesTable = this.destroyTable(this.questionThemesTable); this.modelDetailTable = this.destroyTable(this.modelDetailTable); this.timelineChart = this.destroyChart(this.timelineChart); this.overviewTable = null; this.questionThemesTable = null; this.modelDetailTable = null; this.timelineChart = null; },

        // --- Watchers --- (Only for filters now)
        setupWatchers() {
             // Watchers were removed as UI lifecycle is now primarily driven by parseHash
             // Keep filter watchers as they modify *existing* components, not views
             this.$watch('timelineFilterDomain', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('timelineFilterJudgment', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('timelineFilterCreator', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('timelineHighlightCreator', () => { if (this.currentView === 'model_timeline') { this.updateTimelineUrlParams(); this.initOrUpdateTimelineChart(); }});
             this.$watch('questionThemeTimeFilter', () => { if (this.currentView === 'question_themes' && this.isMetadataLoaded) { if (this.questionThemesTable) { try { this.questionThemesTable.setData(this.questionThemeSummary); } catch (e) { console.error("Err set QThemes data:", e); } } else { console.warn("QThemesTable null on filter update."); } } });
        },

        // --- Helper Methods ---
        getVariationDescription(v) { return VARIATION_MAP[String(v)] || `Type ${v||'N/A'}`; },
        renderMarkdown(t) { if (!t) return ''; try { return DOMPurify.sanitize(marked.parse(t),{USE_PROFILES:{html:true}}); } catch (e) { console.error("MD err:", e); return `<pre>Err:\n${sanitize(t)}</pre>`; } },

        /**
         * @function doSmoothScroll
         * @description Performs the actual smooth scroll action to a given selector.
         * @param {string} selector - The CSS selector (e.g., '#element-id') to scroll to.
         * @returns {void}
         */
        doSmoothScroll(selector) {
             const el = document.querySelector(selector);
             if(el){
                 // Use a minimal timeout to ensure smoother animation start
                 setTimeout(() => { el.scrollIntoView({behavior:'smooth',block:'start'}); }, 50);
             } else {
                 console.warn("[doSmoothScroll] Target element not found:", selector);
             }
        },
        /**
         * @function attemptScrollToAnchor
         * @description Tries to scroll to an element identified by anchorId, polling with retries.
         * This is used after view changes or data loads where the target element might not exist immediately.
         * It does NOT update browser history.
         * @param {string} anchorId - The element ID (without '#') to scroll to.
         * @param {number} retries - The number of remaining attempts.
         * @returns {void}
         */
        attemptScrollToAnchor(anchorId, retries = 10) {
             if (!anchorId || retries <= 0) {
                 // console.log(`[attemptScrollToAnchor] Giving up or no anchorId provided.`); // DEBUG
                 return;
            }
             const selector = anchorId.startsWith('#') ? anchorId : '#' + anchorId;
             const el = document.querySelector(selector);
             if (el) {
                // console.log(`[attemptScrollToAnchor] Element found: ${selector}. Scrolling.`); // DEBUG
                 this.doSmoothScroll(selector); // Call the actual scroll action
             } else {
                // console.log(`[attemptScrollToAnchor] Element not found: ${selector}. Retrying (${retries - 1} left).`); // DEBUG
                 setTimeout(() => this.attemptScrollToAnchor(anchorId, retries - 1), 150); // Retry after delay
             }
        },
        /**
         * @function smoothScroll
         * @description Handles click events for scrolling. If `updateHistory` is true (for internal page links like TOC),
         * it updates the browser history with the anchor AND scrolls. If `updateHistory` is false (used by polling),
         * it only performs the scroll action.
         * @param {string} selector - The element ID or selector (can start with # or not).
         * @param {boolean} updateHistory - Whether to update the browser history (pushState).
         * @returns {void}
         */
        smoothScroll(selector, updateHistory = false) {
             const idSelector = selector.startsWith('#') ? selector : '#' + selector;
             const anchorId = selector.startsWith('#') ? selector.substring(1) : selector;

            if (updateHistory) {
                // Case: Internal anchor link clicked (e.g., TOC item).
                // Update history *first* then scroll.
                // console.log(`[smoothScroll] Updating history for anchor: ${anchorId}`); // DEBUG
                const basePath = `#/questions/${encodeURIComponent(this.selectedGroupingKey)}`;
                const newHash = `${basePath}#${anchorId}`;
                if (location.hash !== newHash) {
                    this.internalNavigationInProgress = true; // Prevent hashchange listener
                    history.pushState(null, '', newHash); // Use pushState to allow 'back' to top
                    this.currentThemeAnchor = anchorId; // Update internal state
                    this.$nextTick(() => { this.internalNavigationInProgress = false; }); // Reset flag after sync ops
                    this.doSmoothScroll(idSelector); // Scroll immediately
                } else {
                     // Already at the correct hash, just ensure scroll
                      this.doSmoothScroll(idSelector);
                }
            } else {
                 // Case: Scrolling initiated by attemptScrollToAnchor (deep link / click-through)
                 // History is already correct, just scroll.
                 this.doSmoothScroll(idSelector);
            }
        },

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
