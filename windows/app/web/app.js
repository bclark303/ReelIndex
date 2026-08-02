(() => {
  'use strict';
  const API = '/api';
  const main = document.getElementById('main');
  const overlay = document.getElementById('overlay-root');
  const scanPanel = document.getElementById('scan-panel');
  const globalError = document.getElementById('global-error');
  const state = {
    page: (location.hash.replace('#','') || 'library'), sources: [], scans: [], view: localStorage.getItem('reelindex-view') || 'grid',
    query: {sort:'title', direction:'asc', page:1, page_size:100}, failureQuery:{page:1,page_size:50}, searchDraft:'', failureSearchDraft:'', movies:null, probeFailures:null, stats:null, diagnostics:null, loading:false,
    sourceModal:null, selectedMovie:null, pollTimer:null, lastActiveRefresh:0,
    scanLog:{runId:null,cursor:0,events:[],tailLoaded:false,autoScroll:true,error:null,pinned:false}
  };

  const icons = {
    grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    list:'<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3" cy="6" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="18" r="1"/>',
    search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>', refresh:'<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    film:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M17 8h4M3 16h4M17 16h4"/>',
    server:'<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>',
    activity:'<path d="M3 12h4l2-7 4 14 2-7h6"/>', x:'<path d="m6 6 12 12M18 6 6 18"/>', warning:'<path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    check:'<path d="m5 12 4 4L19 6"/>', trash:'<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v5M14 11v5"/>',
    download:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>', folder:'<path d="M3 6h6l2 2h10v11H3z"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>', edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/>', plus:'<path d="M12 5v14M5 12h14"/>'
  };
  function icon(name,size=20,cls=''){ return `<svg class="${cls}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.info}</svg>`; }
  document.getElementById('brand-icon').innerHTML = icon('film',22);
  document.querySelectorAll('[data-icon]').forEach(n => n.innerHTML = icon(n.dataset.icon,18));

  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const fmtBytes = bytes => { if(!bytes) return '—'; const u=['B','KB','MB','GB','TB','PB']; const p=Math.min(Math.floor(Math.log(bytes)/Math.log(1024)),u.length-1); const v=bytes/Math.pow(1024,p); return `${v.toFixed(v>=10||p===0?0:1)} ${u[p]}`; };
  const fmtRuntime = seconds => { if(!seconds) return '—'; const h=Math.floor(seconds/3600), m=Math.round((seconds%3600)/60); return h?`${h}h ${m}m`:`${m}m`; };
  const fmtDate = value => value ? new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)) : 'Never';
  const fmtBitrate = value => value ? `${(value/1000000).toFixed(1)} Mbps` : '—';
  function toast(message,type='success'){ const node=document.createElement('div'); node.className=`toast ${type}`; node.textContent=message; document.body.appendChild(node); setTimeout(()=>node.remove(),3500); }
  function showError(message){ globalError.innerHTML=message?`<div class="global-error">${icon('warning',16)}<span>${esc(message)}</span></div>`:''; }
  async function request(path,init={}){
    const isForm=typeof FormData!=='undefined'&&init.body instanceof FormData;
    const headers={...(isForm?{}:{'Content-Type':'application/json'}),...(init.headers||{})};
    const response=await fetch(API+path,{cache:'no-store',...init,headers});
    if(!response.ok){ let payload={}; try{payload=await response.json();}catch{} throw new Error(payload.detail||response.statusText||'Request failed'); }
    return response.status===204?null:response.json();
  }
  const api={
    movies:q=>{const p=new URLSearchParams();Object.entries(q).forEach(([k,v])=>{if(v!==undefined&&v!==''&&v!==false)p.set(k,String(v));});return request('/movies?'+p)}, movie:id=>request('/movies/'+encodeURIComponent(id)), stats:()=>request('/stats'),
    sources:()=>request('/sources'), createSource:p=>request('/sources',{method:'POST',body:JSON.stringify(p)}), updateSource:(id,p)=>request('/sources/'+id,{method:'PUT',body:JSON.stringify(p)}), deleteSource:id=>request('/sources/'+id,{method:'DELETE'}), testSource:p=>request('/sources/test',{method:'POST',body:JSON.stringify(p)}),
    scans:()=>request('/scans'), startScan:(id,mode='quick',scope='incomplete')=>request('/scans/'+id+'?mode='+encodeURIComponent(mode)+'&scope='+encodeURIComponent(scope),{method:'POST'}), resumeScan:id=>request('/scans/'+id+'/resume',{method:'POST'}), cancelScan:id=>request('/scans/'+id+'/cancel',{method:'POST'}), scanEvents:(id,cursor=0,tail=false)=>request(`/scans/${id}/events?cursor=${cursor}&limit=400&tail=${tail?'true':'false'}`), diagnostics:()=>request('/diagnostics'),
    loggingSettings:p=>request('/settings/logging',{method:'PUT',body:JSON.stringify(p)}),
    clearInventory:confirmation=>request('/maintenance/clear-inventory',{method:'POST',body:JSON.stringify({confirmation})}),
    factoryReset:confirmation=>request('/maintenance/factory-reset',{method:'POST',body:JSON.stringify({confirmation})}),
    posterSearch:(id,q,year,includeTv=true)=>{const p=new URLSearchParams({q,include_tv:String(includeTv),limit:'24'});if(year)p.set('year',String(year));return request(`/movies/${encodeURIComponent(id)}/poster/search?${p}`)},
    selectPoster:(id,tmdbId,mediaType)=>request(`/movies/${encodeURIComponent(id)}/poster/tmdb`,{method:'POST',body:JSON.stringify({tmdb_id:tmdbId,media_type:mediaType})}),
    uploadPoster:(id,file)=>{const form=new FormData();form.append('poster',file);return request(`/movies/${encodeURIComponent(id)}/poster/upload`,{method:'POST',body:form})},
    clearPoster:id=>request(`/movies/${encodeURIComponent(id)}/poster`,{method:'DELETE'}),
    probeFailures:q=>{const p=new URLSearchParams();Object.entries(q||{}).forEach(([k,v])=>{if(v!==undefined&&v!==''&&v!==false)p.set(k,String(v));});return request('/probe-failures?'+p)},
    retryProbe:(id,strategy='auto')=>request(`/media-files/${encodeURIComponent(id)}/probe/retry`,{method:'POST',body:JSON.stringify({strategy})}),
    health:()=>request('/health')
  };
  function loading(label='Loading'){ return `<div class="loading"><span class="spinner"></span><span>${esc(label)}</span></div>`; }
  function empty(title,message,action=''){ return `<div class="empty-state">${icon('film',42)}<h2>${esc(title)}</h2><p>${esc(message)}</p>${action}</div>`; }
  function placeholder(title,compact=false){ return `<div class="poster-placeholder ${compact?'compact':''}">${icon('film',compact?18:36)}<span>${esc((title||'?').slice(0,1).toUpperCase())}</span></div>`; }
  function badges(values,solid=false){ return (values||[]).slice(0,3).map(v=>`<span class="badge ${solid?'badge-solid':''}">${esc(v)}</span>`).join(''); }

  function setPage(page){ state.page=page; location.hash=page; document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page)); renderPage(); }
  document.getElementById('brand').addEventListener('click',()=>setPage('library'));
  document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));
  window.addEventListener('hashchange',()=>{const p=location.hash.replace('#','')||'library'; if(p!==state.page){state.page=p;renderPage();}});

  async function loadSources(){ try{state.sources=await api.sources();showError('');}catch(e){showError(e.message);} }
  async function loadScans(){ try{state.scans=await api.scans(); renderScanPanel();}catch(e){state.scans=[];scanPanel.innerHTML=`<div class="scan-state-error">${icon('warning',17)}<span>Scan controls unavailable: ${esc(e.message)}</span></div>`;console.error('Could not load scan state',e);} }
  function renderScanPanel(){
    const active=state.scans.filter(s=>['queued','running','cancelling'].includes(s.status));
    if(!active.length){scanPanel.innerHTML='';return;}
    scanPanel.innerHTML=`<div class="scan-panel">${active.map(s=>{const total=Math.max(s.queue_total||s.discovered_count||0,1);const done=s.queue_total?Math.max(0,s.queue_total-(s.queue_remaining||0)):((s.analyzed_count||0)+(s.cached_count||0)+(s.error_count||0));const pct=Math.min(100,Math.round(done/total*100));const cancelling=s.status==='cancelling';return `<div class="scan-row"><div class="scan-icon">${icon('refresh',20,'spin')}</div><div class="scan-content"><div class="scan-copy"><strong>${esc(s.source_name||'Library scan')}</strong><span>${esc(s.current_item||s.status)}</span></div><div class="progress-track"><span style="width:${pct}%"></span></div><div class="scan-counts"><span>${s.discovered_count} files found</span><span>${s.analyzed_count} analyzed · ${s.cached_count} cached · ${s.error_count} errors</span></div></div><button class="button danger small scan-cancel" data-cancel-scan="${s.id}" ${cancelling?'disabled':''}>${cancelling?'Cancelling…':'Cancel scan'}</button></div>`}).join('')}</div>`;
    scanPanel.querySelectorAll('[data-cancel-scan]').forEach(button=>button.onclick=async()=>{button.disabled=true;button.textContent='Cancelling…';try{await api.cancelScan(button.dataset.cancelScan);toast('Scan cancellation requested');await loadScans();schedulePoll();}catch(e){toast(e.message,'error');await loadScans();}});
  }
  function schedulePoll(){ clearTimeout(state.pollTimer); const active=state.scans.some(s=>['queued','running','cancelling'].includes(s.status)); state.pollTimer=setTimeout(async()=>{const before=state.scans.map(s=>s.id+':'+s.status).join('|');await loadScans();const after=state.scans.map(s=>s.id+':'+s.status).join('|');const stillActive=state.scans.some(s=>['queued','running','cancelling'].includes(s.status));const statusChanged=before!==after;const now=Date.now();const refreshActive=stillActive&&now-state.lastActiveRefresh>=5000;if(state.page==='sources')await loadLiveScanEvents();if((statusChanged||refreshActive)&&state.page==='library'){state.lastActiveRefresh=now;loadLibrary();}if((statusChanged||refreshActive)&&state.page==='sources'){state.lastActiveRefresh=now;await loadSources();renderSources();}else if(state.page==='sources'){renderLiveScanConsole();}schedulePoll();},active?1000:5000); }

  async function renderPage(){
    document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===state.page));
    overlay.innerHTML='';
    if(state.page==='sources') return renderSources(true);
    if(state.page==='diagnostics') return renderDiagnostics(true);
    if(state.page==='failures') return renderProbeFailures(true);
    return renderLibrary(true);
  }


  async function loadProbeFailures(){
    state.loading=true;renderProbeFailures(false);
    try{state.probeFailures=await api.probeFailures(state.failureQuery);showError('');}
    catch(e){showError(e.message);state.probeFailures=null;}
    state.loading=false;renderProbeFailures(false);
  }
  function categoryLabel(value){return ({timeout:'Timeout',missing_path:'Path unavailable',permission:'Permission',analyzer_missing:'Analyzer missing',container_parse:'Container parse',incomplete:'Incomplete metadata',network_io:'Network / storage',interrupted:'Interrupted',unknown:'Other'})[value]||String(value||'Other').replaceAll('_',' ');}
  function failureActionLabel(value){return ({retry_auto:'Retry native',retry_extended:'Extended retry',retry_ffprobe:'ffprobe retry',check_source:'Check source',check_permissions:'Check permissions',repair_install:'Repair install'})[value]||'Review';}
  function renderProbeFailures(initial=false){
    if(initial&&!state.probeFailures&&!state.loading){main.innerHTML=loading('Loading probe failures');loadProbeFailures();return;}
    const d=state.probeFailures;
    const q=state.failureQuery;
    const summary=d?.summary||{total:0,by_category:{},by_container:{}};
    const categories=Object.entries(summary.by_category||{}).sort((a,b)=>b[1]-a[1]);
    const containers=Object.entries(summary.by_container||{}).sort((a,b)=>b[1]-a[1]);
    main.innerHTML=`<section class="page-heading split-heading"><div><span class="eyebrow">Technical analysis remediation</span><h1>Probe failures</h1><p>See which files failed, why they failed, and retry them one at a time without rescanning the entire library.</p></div><button class="button secondary" id="refresh-failures">${icon('refresh',17)}Refresh</button></section>
    <div class="failure-summary"><article><strong>${summary.total||0}</strong><span>Current failures</span></article>${categories.slice(0,4).map(([key,count])=>`<article><strong>${count}</strong><span>${esc(categoryLabel(key))}</span></article>`).join('')}</div>
    <section class="toolbar-card failure-toolbar"><div class="search-box">${icon('search')}<input id="failure-search" value="${esc(state.failureSearchDraft)}" placeholder="Search title, filename, path, or error…"/><button class="clear-search ${state.failureSearchDraft?'':'hidden'}" id="clear-failure-search">${icon('x',16)}</button></div><div class="toolbar-actions"><select id="failure-source"><option value="">All sources</option>${state.sources.map(source=>`<option value="${source.id}" ${q.source_id===source.id?'selected':''}>${esc(source.name)}</option>`).join('')}</select><select id="failure-category"><option value="">All causes</option>${categories.map(([key,count])=>`<option value="${esc(key)}" ${q.category===key?'selected':''}>${esc(categoryLabel(key))} (${count})</option>`).join('')}</select><select id="failure-container"><option value="">All containers</option>${containers.map(([key,count])=>`<option value="${esc(key)}" ${q.container===key?'selected':''}>${esc(key.toUpperCase())} (${count})</option>`).join('')}</select></div></section>
    ${state.loading?loading('Loading probe failures'):renderFailureResults()}`;
    bindProbeFailures();
  }
  function renderFailureResults(){
    const d=state.probeFailures;if(!d)return `<div class="error-panel">${icon('warning')}<div><strong>Could not load probe failures</strong><p>Check Diagnostics or restart ReelIndex.</p></div></div>`;
    if(!d.items.length)return empty('No matching probe failures','Every indexed file in this view currently has usable technical metadata.');
    const pages=Math.max(1,Math.ceil(d.total/d.page_size));
    return `<div class="failure-list">${d.items.map(failureCard).join('')}</div>${pages>1?`<div class="pagination"><button class="button secondary small" id="prev-failure-page" ${d.page<=1?'disabled':''}>Previous</button><span>Page ${d.page} of ${pages}</span><button class="button secondary small" id="next-failure-page" ${d.page>=pages?'disabled':''}>Next</button></div>`:''}`;
  }
  function failureCard(item){
    const suggested=item.suggestions?.[0]||item.diagnosis_summary;
    const retryable=item.retryable;
    return `<article class="failure-card severity-${esc(item.severity)}"><div class="failure-card-head"><div><span class="failure-category">${esc(categoryLabel(item.category))}</span><h2>${esc(item.movie_title)}${item.movie_year?` <small>(${item.movie_year})</small>`:''}</h2><p>${esc(item.filename)}</p></div><div class="failure-attempts"><strong>${item.deep_attempt_count||item.attempt_count||0}</strong><span>attempts</span></div></div><div class="failure-diagnosis"><div class="failure-icon">${icon('warning',20)}</div><div><strong>${esc(item.diagnosis_title)}</strong><p>${esc(item.diagnosis_summary)}</p></div></div><div class="failure-error"><code>${esc(item.error)}</code></div><div class="failure-meta"><span>${esc((item.container||'unknown').toUpperCase())}</span><span>${fmtBytes(item.size_bytes)}</span><span>${esc(item.source_name)}</span><span>${item.attempted_at?fmtDate(item.attempted_at):fmtDate(item.updated_at)}</span></div><div class="path-box">${icon('folder',15)}<code>${esc(item.path)}</code></div><div class="failure-remedy"><span>${icon('info',16)}${esc(suggested)}</span><div class="failure-actions"><button class="button ghost small" data-open-failure-movie="${item.movie_id}">Open movie</button>${retryable?`<button class="button secondary small" data-retry-probe="${item.file_id}" data-strategy="auto">Retry native</button><button class="button secondary small" data-retry-probe="${item.file_id}" data-strategy="extended">Extended</button><button class="button secondary small" data-retry-probe="${item.file_id}" data-strategy="ffprobe">ffprobe</button>`:`<span class="status-pill warning">${esc(failureActionLabel(item.recommended_action))}</span>`}</div></div></article>`;
  }
  function bindProbeFailures(){
    document.getElementById('refresh-failures')?.addEventListener('click',loadProbeFailures);
    const search=document.getElementById('failure-search');let timer;search?.addEventListener('input',e=>{state.failureSearchDraft=e.target.value;document.getElementById('clear-failure-search').classList.toggle('hidden',!state.failureSearchDraft);clearTimeout(timer);timer=setTimeout(()=>{state.failureQuery.search=state.failureSearchDraft||undefined;state.failureQuery.page=1;loadProbeFailures();},240);});
    document.getElementById('clear-failure-search')?.addEventListener('click',()=>{state.failureSearchDraft='';state.failureQuery.search=undefined;state.failureQuery.page=1;loadProbeFailures();});
    [['failure-source','source_id'],['failure-category','category'],['failure-container','container']].forEach(([id,key])=>document.getElementById(id)?.addEventListener('change',e=>{state.failureQuery[key]=e.target.value||undefined;state.failureQuery.page=1;loadProbeFailures();}));
    document.querySelectorAll('[data-open-failure-movie]').forEach(button=>button.onclick=()=>openMovie(button.dataset.openFailureMovie));
    document.querySelectorAll('[data-retry-probe]').forEach(button=>button.onclick=async()=>{const original=button.textContent;button.disabled=true;button.textContent='Probing…';try{const result=await api.retryProbe(button.dataset.retryProbe,button.dataset.strategy);toast(result.resolved?'Probe failure resolved':(result.error||result.message),result.resolved?'success':'error');state.movies=null;state.stats=null;await loadProbeFailures();}catch(error){toast(error.message,'error');button.disabled=false;button.textContent=original;}});
    document.getElementById('prev-failure-page')?.addEventListener('click',()=>{state.failureQuery.page=Math.max(1,(state.failureQuery.page||1)-1);loadProbeFailures();scrollTo(0,0);});
    document.getElementById('next-failure-page')?.addEventListener('click',()=>{state.failureQuery.page=(state.failureQuery.page||1)+1;loadProbeFailures();scrollTo(0,0);});
  }

  async function loadLibrary(){
    state.loading=true; renderLibrary(false);
    try{const [movies,stats]=await Promise.all([api.movies(state.query),api.stats()]);state.movies=movies;state.stats=stats;showError('');}
    catch(e){showError(e.message);state.movies=null;}
    state.loading=false; renderLibrary(false);
  }
  function libraryHeading(){const s=state.stats;return `<section class="page-heading library-heading"><div><span class="eyebrow">Read-only media inventory</span><h1>Your movie library</h1><p>Search, inspect, and compare every indexed media file.</p></div>${s?`<div class="stats-strip"><div><strong>${s.movies.toLocaleString()}</strong><span>Movies</span></div><div><strong>${s.files.toLocaleString()}</strong><span>Files</span></div><div><strong>${fmtBytes(s.total_size_bytes)}</strong><span>Storage</span></div><div><strong>${s.resolutions['4K']||0}</strong><span>4K files</span></div></div>`:''}</section>`;}
  function renderLibrary(initial=false){
    if(initial&&!state.movies&&!state.loading){main.innerHTML=loading('Loading movie inventory');loadLibrary();return;}
    const d=state.movies, q=state.query, active=['source_id','resolution','codec','container','missing_poster','multiple_versions','probe_errors'].filter(k=>q[k]).length;
    const facet=(key,label)=>`<select data-filter="${key}" aria-label="${label}"><option value="">${label}</option>${((d&&d.facets[key==='codec'?'codecs':key==='container'?'containers':'resolutions'])||[]).map(v=>`<option ${q[key]===v?'selected':''}>${esc(v)}</option>`).join('')}</select>`;
    main.innerHTML=libraryHeading()+`<section class="toolbar-card"><div class="search-box">${icon('search')}<input id="movie-search" value="${esc(state.searchDraft)}" placeholder="Search by movie title…" aria-label="Search movies by title"/><button class="clear-search ${state.searchDraft?'':'hidden'}" id="clear-search">${icon('x',16)}</button></div><div class="toolbar-actions"><select id="sort"><option value="title:asc">Title A–Z</option><option value="title:desc">Title Z–A</option><option value="year:desc">Newest first</option><option value="year:asc">Oldest first</option><option value="size:desc">Largest first</option><option value="updated:desc">Recently indexed</option></select><div class="segmented"><button data-view="grid" class="${state.view==='grid'?'active':''}">${icon('grid')}</button><button data-view="list" class="${state.view==='list'?'active':''}">${icon('list')}</button></div></div></section>
    <section class="filter-bar"><select data-filter="source_id"><option value="">All sources</option>${state.sources.map(s=>`<option value="${s.id}" ${q.source_id===s.id?'selected':''}>${esc(s.name)}</option>`).join('')}</select>${facet('resolution','All resolutions')}${facet('codec','All codecs')}${facet('container','All containers')}${[['multiple_versions','Multiple versions'],['missing_poster','Missing posters'],['probe_errors','Probe errors']].map(([k,l])=>`<label class="filter-toggle ${q[k]?'active':''}"><input type="checkbox" data-toggle="${k}" ${q[k]?'checked':''}/>${l}</label>`).join('')}${active?`<button class="text-button" id="clear-filters">Clear ${active} filter${active===1?'':'s'}</button>`:''}</section>
    <div class="result-summary"><span>${d?`${d.total.toLocaleString()} ${d.total===1?'movie':'movies'}`:'Loading collection'}</span>${state.stats&&state.stats.probe_errors?`<span class="warning-copy">${icon('warning',15)}${state.stats.probe_errors} file analysis warning${state.stats.probe_errors===1?'':'s'}</span>`:''}</div>
    ${state.loading?loading('Loading movie inventory'):renderMovieResults()}`;
    bindLibrary();
  }
  function renderMovieResults(){const d=state.movies;if(!d)return `<div class="error-panel">${icon('warning')}<div><strong>Could not load the library</strong><p>Check Diagnostics or restart ReelIndex.</p></div></div>`;if(!d.items.length)return empty(state.sources.length?'No matching movies':'Connect your first library',state.sources.length?'Try clearing filters or start a new scan.':'Add a filesystem, Plex, Jellyfin, or Emby source to create the inventory.',state.sources.length?'':'<button class="button primary" id="go-sources">Add a source</button>');const content=state.view==='grid'?`<div class="movie-grid">${d.items.map(movieCard).join('')}</div>`:`<div class="table-wrap"><table class="movie-table"><thead><tr><th>Movie</th><th>Year</th><th>Version</th><th>Resolution</th><th>Codec</th><th>Container</th><th>Size</th><th>Runtime</th></tr></thead><tbody>${d.items.map(movieRow).join('')}</tbody></table></div>`;const pages=Math.max(1,Math.ceil(d.total/d.page_size));return content+(pages>1?`<div class="pagination"><button class="button secondary small" id="prev-page" ${d.page<=1?'disabled':''}>Previous</button><span>Page ${d.page} of ${pages}</span><button class="button secondary small" id="next-page" ${d.page>=pages?'disabled':''}>Next</button></div>`:'');}
  function movieCard(m){return `<button class="movie-card" data-movie="${m.id}"><div class="movie-poster-wrap">${m.poster_url?`<img class="movie-poster" src="${m.poster_url}" alt="${esc(m.title)} poster" loading="lazy"/>`:placeholder(m.title)}<span class="poster-source">${esc(m.source_type)}</span>${m.has_probe_error?`<span class="poster-warning">${icon('warning',15)}</span>`:''}<div class="poster-badges">${badges(m.resolutions,true)}${m.file_count>1?`<span class="badge">${m.file_count} files</span>`:''}</div></div><div class="movie-card-copy"><h2 title="${esc(m.title)}">${esc(m.title)}</h2><div class="movie-card-meta"><span>${m.year||'—'}</span><span>${fmtRuntime(m.runtime_seconds)}</span></div></div></button>`;}
  function movieRow(m){return `<tr data-movie="${m.id}"><td><div class="movie-title-cell">${m.poster_url?`<img class="table-poster" src="${m.poster_url}" alt="" loading="lazy"/>`:placeholder(m.title,true)}<div><strong>${esc(m.title)}</strong><div class="muted">${esc(m.source_name)}</div></div></div></td><td>${m.year||'—'}</td><td>${m.file_count}</td><td>${esc(m.resolutions.join(', ')||'—')}</td><td>${esc(m.video_codecs.join(', ')||'—')}</td><td>${esc(m.containers.join(', ')||'—')}</td><td>${fmtBytes(m.total_size_bytes)}</td><td>${fmtRuntime(m.runtime_seconds)}</td></tr>`;}
  function bindLibrary(){
    const search=document.getElementById('movie-search');let timer;search&&search.addEventListener('input',e=>{state.searchDraft=e.target.value;document.getElementById('clear-search').classList.toggle('hidden',!state.searchDraft);clearTimeout(timer);timer=setTimeout(()=>{state.query.search=state.searchDraft||undefined;state.query.page=1;loadLibrary();},240);});
    document.getElementById('clear-search')?.addEventListener('click',()=>{state.searchDraft='';state.query.search=undefined;state.query.page=1;loadLibrary();});
    const sort=document.getElementById('sort');if(sort){sort.value=`${state.query.sort}:${state.query.direction}`;sort.addEventListener('change',e=>{[state.query.sort,state.query.direction]=e.target.value.split(':');loadLibrary();});}
    document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{state.view=b.dataset.view;localStorage.setItem('reelindex-view',state.view);renderLibrary(false);}));
    document.querySelectorAll('[data-filter]').forEach(el=>el.addEventListener('change',()=>{state.query[el.dataset.filter]=el.value||undefined;state.query.page=1;loadLibrary();}));
    document.querySelectorAll('[data-toggle]').forEach(el=>el.addEventListener('change',()=>{state.query[el.dataset.toggle]=el.checked||undefined;state.query.page=1;loadLibrary();}));
    document.getElementById('clear-filters')?.addEventListener('click',()=>{const keep={sort:state.query.sort,direction:state.query.direction,page_size:100,search:state.query.search};state.query=keep;loadLibrary();});
    document.querySelectorAll('[data-movie]').forEach(el=>el.addEventListener('click',()=>openMovie(el.dataset.movie)));
    document.getElementById('go-sources')?.addEventListener('click',()=>setPage('sources'));
    document.getElementById('prev-page')?.addEventListener('click',()=>{state.query.page=Math.max(1,(state.query.page||1)-1);loadLibrary();scrollTo(0,0);});document.getElementById('next-page')?.addEventListener('click',()=>{state.query.page=(state.query.page||1)+1;loadLibrary();scrollTo(0,0);});
  }
  async function openMovie(id){
    state.selectedMovie=id;
    overlay.innerHTML=`<div class="drawer-backdrop"><aside class="detail-drawer"><button class="icon-button drawer-close" data-close>${icon('x')}</button>${loading('Loading movie details')}</aside></div>`;
    overlay.querySelector('[data-close]').onclick=()=>overlay.innerHTML='';
    overlay.querySelector('.drawer-backdrop').addEventListener('click',e=>{if(e.target.classList.contains('drawer-backdrop'))overlay.innerHTML='';});
    try{
      const m=await api.movie(id);
      state.selectedMovie=m;
      const posterSource=m.metadata&&m.metadata.poster_source?String(m.metadata.poster_source).replaceAll('-',' '):'';
      overlay.querySelector('.detail-drawer').innerHTML=`<button class="icon-button drawer-close" data-close>${icon('x')}</button><div class="detail-hero"><div class="detail-poster-wrap">${m.poster_url?`<img class="detail-poster" src="${m.poster_url}" alt="${esc(m.title)} poster"/>`:`<div class="detail-poster">${placeholder(m.title)}</div>`}<button class="button secondary small poster-manage" id="manage-poster">${icon('edit',15)}Manage poster</button>${posterSource?`<span class="poster-source-label">${esc(posterSource)}</span>`:''}</div><div class="detail-heading"><span class="eyebrow">${esc(m.source_name)}</span><h1>${esc(m.title)}</h1><div class="detail-heading-meta"><span>${m.year||'Unknown year'}</span><span>${fmtRuntime(m.runtime_seconds)}</span><span>${m.file_count} file${m.file_count===1?'':'s'}</span></div><div class="badge-list">${badges(m.resolutions,true)}${badges(m.video_codecs)}${badges(m.containers)}</div></div></div>${m.overview?`<p class="overview">${esc(m.overview)}</p>`:''}<div class="detail-summary-grid"><div class="detail-item"><span>Total size</span><strong>${fmtBytes(m.total_size_bytes)}</strong></div><div class="detail-item"><span>Source</span><strong>${esc(m.source_type)}</strong></div><div class="detail-item"><span>Files</span><strong>${m.file_count}</strong></div><div class="detail-item"><span>Updated</span><strong>${fmtDate(m.updated_at)}</strong></div></div><section class="detail-section"><div class="section-heading"><div><span class="eyebrow">Technical inventory</span><h2>Media files</h2></div>${icon('database')}</div><div class="file-stack">${m.files.map((f,i)=>fileCard(f,i)).join('')}</div></section>`;
      overlay.querySelector('[data-close]').onclick=()=>overlay.innerHTML='';
      overlay.querySelector('#manage-poster').onclick=()=>openPosterManager(m);
      overlay.querySelectorAll('[data-file-retry]').forEach(button=>button.onclick=async()=>{const original=button.textContent;button.disabled=true;button.textContent='Probing…';try{const result=await api.retryProbe(button.dataset.fileRetry,button.dataset.strategy);toast(result.resolved?'Probe failure resolved':(result.error||result.message),result.resolved?'success':'error');state.movies=null;state.stats=null;if(state.page==='failures')await loadProbeFailures();else await loadLibrary();openMovie(m.id);}catch(error){toast(error.message,'error');button.disabled=false;button.textContent=original;}});
    }catch(e){
      overlay.querySelector('.detail-drawer').innerHTML=`<button class="icon-button drawer-close" data-close>${icon('x')}</button><div class="error-panel">${icon('warning')}<p>${esc(e.message)}</p></div>`;
      overlay.querySelector('[data-close]').onclick=()=>overlay.innerHTML='';
    }
  }

  function posterResultCard(result,movie){
    const titleMeta=[result.year,result.media_type==='tv'?'TV':'Movie'].filter(Boolean).join(' · ');
    return `<article class="poster-result-card">${result.poster_url?`<img src="${result.poster_url}" alt="${esc(result.title)} poster" loading="lazy"/>`:`<div class="poster-result-empty">${placeholder(result.title,true)}</div>`}<div class="poster-result-copy"><strong>${esc(result.title)}</strong><span>${esc(titleMeta||'TMDB')}</span>${result.original_title?`<small>${esc(result.original_title)}</small>`:''}<p>${esc((result.overview||'No description available.').slice(0,180))}</p></div><button class="button primary small" data-use-poster="${result.tmdb_id}" data-media-type="${esc(result.media_type)}" ${result.poster_url?'':'disabled'}>${result.poster_url?'Use poster':'No poster'}</button></article>`;
  }

  async function openPosterManager(movie,results=null,status=''){
    const defaultQuery=(movie.metadata&&movie.metadata.imdb_id)||movie.title;
    overlay.innerHTML=`<div class="modal-backdrop"><div class="source-modal poster-manager-modal"><div class="modal-header"><div><span class="eyebrow">Poster management</span><h2>${esc(movie.title)}</h2></div><button class="icon-button" data-close>${icon('x')}</button></div><div class="poster-manager-current">${movie.poster_url?`<img src="${movie.poster_url}" alt="Current poster"/>`:`<div class="poster-current-empty">${placeholder(movie.title,true)}</div>`}<div><strong>${movie.poster_url?'Current poster':'No poster selected'}</strong><p>Search TMDB by title or IMDb ID, or upload a JPEG, PNG, or WebP image. Manual choices are kept during future scans.</p>${movie.poster_url?`<button class="button danger small" id="remove-poster">Remove current poster</button>`:''}</div></div><form id="poster-search-form" class="poster-search-form"><label><span>Title or IMDb ID</span><input id="poster-query" value="${esc(defaultQuery)}" placeholder="Movie title or tt1234567"/></label><label class="poster-year-field"><span>Year</span><input id="poster-year" type="number" min="1870" max="2200" value="${movie.year||''}"/></label><label class="check-row poster-tv-check"><input id="poster-include-tv" type="checkbox" checked/><span>Include TV results</span></label><button class="button primary" type="submit">${icon('search',16)}Search</button></form><div id="poster-manager-status">${status?`<div class="connection-status ${status.startsWith('Error:')?'error':'success'}">${esc(status)}</div>`:''}</div><div id="poster-results">${results===null?'<div class="poster-search-hint">Search using the cleaned title, alternate title, IMDb ID, or a simpler phrase.</div>':results.length?`<div class="poster-result-grid">${results.map(r=>posterResultCard(r,movie)).join('')}</div>`:`<div class="poster-search-hint">No matching posters were returned. Try a shorter title, remove release tags, include the year, or upload an image.</div>`}</div><div class="poster-upload-box"><div><strong>Upload your own poster</strong><p>The image is stored only in ReelIndex's local cache; media files remain read-only.</p></div><input id="poster-file" type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"/><button class="button secondary" id="upload-poster" type="button">${icon('plus',16)}Upload image</button></div><div class="modal-actions"><button class="button ghost" id="back-to-movie" type="button">Back to movie</button></div></div></div>`;
    overlay.querySelector('[data-close]').onclick=()=>overlay.innerHTML='';
    overlay.querySelector('#back-to-movie').onclick=()=>openMovie(movie.id);
    const form=overlay.querySelector('#poster-search-form');
    form.onsubmit=async e=>{
      e.preventDefault();
      const host=overlay.querySelector('#poster-results');
      const statusHost=overlay.querySelector('#poster-manager-status');
      const query=overlay.querySelector('#poster-query').value.trim();
      const year=Number(overlay.querySelector('#poster-year').value)||null;
      if(!query){statusHost.innerHTML='<div class="connection-status error">Enter a title or IMDb ID.</div>';return;}
      host.innerHTML=loading('Searching TMDB');statusHost.innerHTML='';
      try{
        const payload=await api.posterSearch(movie.id,query,year,overlay.querySelector('#poster-include-tv').checked);
        openPosterManager(movie,payload.results,`${payload.results.length} result${payload.results.length===1?'':'s'} for “${payload.query}”`);
      }catch(err){openPosterManager(movie,[],`Error: ${err.message}`);}
    };
    overlay.querySelectorAll('[data-use-poster]').forEach(button=>button.onclick=async()=>{
      button.disabled=true;button.textContent='Applying…';
      try{await api.selectPoster(movie.id,Number(button.dataset.usePoster),button.dataset.mediaType);toast('Poster updated');await loadLibrary();openMovie(movie.id);}catch(err){toast(err.message,'error');button.disabled=false;button.textContent='Use poster';}
    });
    const upload=overlay.querySelector('#upload-poster');
    upload.onclick=async()=>{
      const file=overlay.querySelector('#poster-file').files[0];
      if(!file){toast('Choose an image first','error');return;}
      upload.disabled=true;upload.textContent='Uploading…';
      try{await api.uploadPoster(movie.id,file);toast('Poster uploaded');await loadLibrary();openMovie(movie.id);}catch(err){toast(err.message,'error');upload.disabled=false;upload.textContent='Upload image';}
    };
    const remove=overlay.querySelector('#remove-poster');
    if(remove)remove.onclick=async()=>{
      if(!confirm('Remove this cached poster? The movie file and any sidecar artwork will not be changed.'))return;
      remove.disabled=true;
      try{await api.clearPoster(movie.id);toast('Poster removed');await loadLibrary();openMovie(movie.id);}catch(err){toast(err.message,'error');remove.disabled=false;}
    };
  }

  function fileCard(f,i){
    const failure=f.probe_error?`<div class="probe-failure-detail"><div class="probe-failure-heading">${icon('warning',18)}<div><strong>${esc(f.probe_failure_title||'Probe failed')}</strong><p>${esc(f.probe_failure_summary||f.probe_error)}</p></div></div><div class="inline-warning"><span>${esc(f.probe_error)}</span></div>${f.probe_failure_suggestions?.length?`<ul>${f.probe_failure_suggestions.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}<div class="failure-actions"><button class="button secondary small" data-file-retry="${f.id}" data-strategy="auto">Retry native</button><button class="button secondary small" data-file-retry="${f.id}" data-strategy="extended">Extended retry</button><button class="button secondary small" data-file-retry="${f.id}" data-strategy="ffprobe">ffprobe retry</button></div></div>`:'';
    return `<article class="file-card"><div class="file-card-header"><div><span class="file-index">File ${i+1}${f.edition?` · ${esc(f.edition)}`:''}</span><h3>${esc(f.filename)}</h3><p>${fmtBytes(f.size_bytes)} · ${fmtRuntime(f.duration_seconds)}</p></div><div class="badge-list">${f.resolution_label?`<span class="badge badge-solid">${esc(f.resolution_label)}</span>`:''}${f.container?`<span class="badge">${esc(f.container)}</span>`:''}</div></div>${failure}<div class="technical-grid">${[['Video codec',f.video_codec],['Dimensions',f.width&&f.height?`${f.width}×${f.height}`:null],['Video bitrate',fmtBitrate(f.video_bitrate)],['Audio codec',f.audio_codec],['Audio channels',f.audio_channels],['Audio language',f.audio_languages],['Container',f.container],['Runtime',fmtRuntime(f.duration_seconds)]].map(([k,v])=>`<div class="detail-item"><span>${k}</span><strong>${esc(v||'—')}</strong></div>`).join('')}</div><div class="path-box">${icon('folder',15)}<code>${esc(f.path)}</code></div><details class="raw-details"><summary>Raw analyzer information</summary><pre>${esc(JSON.stringify(f.probe,null,2))}</pre></details></article>`;
  }

  function preferredLiveRun(){
    const current=state.scans.find(scan=>scan.id===state.scanLog.runId);
    const active=state.scans.find(scan=>['queued','running','cancelling'].includes(scan.status));
    if(state.scanLog.pinned&&current)return current;
    return active||current||state.scans[0]||null;
  }
  function resetLiveRun(runId,pinned=false){state.scanLog={runId,cursor:0,events:[],tailLoaded:false,autoScroll:state.scanLog.autoScroll,error:null,pinned};}
  async function loadLiveScanEvents(runId=null){
    const selected=runId?state.scans.find(scan=>scan.id===runId):preferredLiveRun();
    if(!selected){if(state.scanLog.runId)resetLiveRun(null);renderLiveScanConsole();return;}
    if(state.scanLog.runId!==selected.id)resetLiveRun(selected.id,Boolean(runId));
    try{
      const payload=await api.scanEvents(selected.id,state.scanLog.cursor,!state.scanLog.tailLoaded);
      state.scanLog.tailLoaded=true;
      state.scanLog.cursor=payload.next_cursor;
      if(payload.events?.length){state.scanLog.events.push(...payload.events);if(state.scanLog.events.length>1200)state.scanLog.events.splice(0,state.scanLog.events.length-1200);}
      state.scanLog.error=null;
      if(payload.has_more)setTimeout(()=>loadLiveScanEvents(selected.id),0);
    }catch(error){state.scanLog.error=error.message;}
    renderLiveScanConsole();
  }
  function scanEventDetails(event){const details=event.details||{};const parts=[];if(details.location)parts.push(details.location);if(details.mode)parts.push(`mode=${details.mode}`);if(details.files!==undefined)parts.push(`${details.files} file${details.files===1?'':'s'}`);if(details.elapsed_ms!==undefined)parts.push(`${Number(details.elapsed_ms).toLocaleString()} ms`);if(details.files_per_second!==undefined)parts.push(`${details.files_per_second} files/s`);if(details.jobs_per_second!==undefined)parts.push(`${details.jobs_per_second} jobs/s`);if(details.workers!==undefined)parts.push(`${details.workers} workers`);if(details.scope)parts.push(`scope=${details.scope}`);if(details.remaining!==undefined)parts.push(`${Number(details.remaining).toLocaleString()} remaining`);if(details.eta_seconds!==undefined)parts.push(`ETA ${Math.floor(details.eta_seconds/60)}m ${String(details.eta_seconds%60).padStart(2,'0')}s`);if(details.average_ms!==undefined)parts.push(`${Number(details.average_ms).toLocaleString()} ms avg`);return parts.length?`<span class="scan-event-details">${esc(parts.join(' · '))}</span>`:'';}
  function liveScanConsoleMarkup(){
    const run=state.scans.find(scan=>scan.id===state.scanLog.runId)||preferredLiveRun();
    const events=state.scanLog.events;
    return `<section class="live-scan-card"><div class="live-scan-header"><div><span class="eyebrow">Live activity</span><h2>Scan output</h2><p>${run?`${esc(run.source_name||'Media source')} · ${esc(run.status)}`:'Start a scan to see each stage as it happens.'}</p></div><div class="live-scan-controls"><select id="scan-log-run" aria-label="Scan run">${state.scans.length?state.scans.slice(0,20).map(scan=>`<option value="${scan.id}" ${scan.id===run?.id?'selected':''}>${esc(scan.source_name||'Source')} · ${esc(scan.status)} · ${fmtDate(scan.started_at)}</option>`).join(''):'<option>No scan runs</option>'}</select><label class="scan-autoscroll"><input id="scan-log-autoscroll" type="checkbox" ${state.scanLog.autoScroll?'checked':''}/><span>Auto-scroll</span></label><button class="button secondary small" id="copy-scan-log" ${events.length?'':'disabled'}>Copy</button>${run?`<a class="button secondary small" href="/api/scans/${run.id}/events/export" download>${icon('download',15)}Download log</a>`:''}<button class="button ghost small" id="clear-scan-log" ${events.length?'':'disabled'}>Clear view</button></div></div><div class="scan-console" id="scan-console" role="log" aria-live="polite">${state.scanLog.error?`<div class="scan-event error"><span class="scan-event-time">—</span><span class="scan-event-stage">API</span><span class="scan-event-message">${esc(state.scanLog.error)}</span></div>`:events.length?events.map(event=>`<div class="scan-event ${esc(event.level||'info')}"><span class="scan-event-time">${event.timestamp?new Date(event.timestamp).toLocaleTimeString():''}</span><span class="scan-event-stage">${esc(event.stage||'scan')}</span><span class="scan-event-message">${esc(event.message)}${scanEventDetails(event)}</span></div>`).join(''):`<div class="scan-console-empty">${run?'Waiting for scan output…':'No scan output yet.'}</div>`}</div><div class="live-scan-footer"><span>${events.length.toLocaleString()} visible event${events.length===1?'':'s'}${events.length>=1200?' · oldest events hidden':''}</span><span>Credentials are never written to this output; movie names and paths may be included.</span></div></section>`;
  }
  function renderLiveScanConsole(){const host=document.getElementById('live-scan-console-host');if(!host)return;host.innerHTML=liveScanConsoleMarkup();bindLiveScanConsole();}
  function bindLiveScanConsole(){
    const select=document.getElementById('scan-log-run');if(select&&state.scans.length)select.onchange=()=>{resetLiveRun(select.value,true);loadLiveScanEvents(select.value);};
    const auto=document.getElementById('scan-log-autoscroll');if(auto)auto.onchange=()=>{state.scanLog.autoScroll=auto.checked;if(auto.checked){const consoleNode=document.getElementById('scan-console');if(consoleNode)consoleNode.scrollTop=consoleNode.scrollHeight;}};
    const clear=document.getElementById('clear-scan-log');if(clear)clear.onclick=()=>{state.scanLog.events=[];renderLiveScanConsole();};
    const copy=document.getElementById('copy-scan-log');if(copy)copy.onclick=async()=>{const text=state.scanLog.events.map(event=>`${event.timestamp||''} [${String(event.level||'info').toUpperCase()}] [${event.stage||'scan'}] ${event.message}`).join('\n');try{await navigator.clipboard.writeText(text);toast('Scan output copied');}catch{toast('Could not copy scan output','error');}};
    const consoleNode=document.getElementById('scan-console');if(consoleNode&&state.scanLog.autoScroll)requestAnimationFrame(()=>{consoleNode.scrollTop=consoleNode.scrollHeight;});
  }
  async function renderSources(initial=false){if(initial){main.innerHTML=loading('Loading source configuration');await loadSources();await loadLiveScanEvents();}main.innerHTML=`<section class="page-heading split-heading"><div><span class="eyebrow">Portable configuration</span><h1>Media sources</h1><p>Connect filesystems and read-only media-server APIs. Server details remain outside application code.</p></div><button class="button primary" id="add-source">${icon('plus',17)}Add source</button></section><div class="notice-card">${icon('info')}<div><strong>Quick scan builds the inventory. Poster refresh is independent of Deep Scan.</strong><p>Posters are resolved immediately after indexing. Deep analysis remains resumable and uses native container parsers with bounded ffprobe fallback.</p></div></div><div id="live-scan-console-host">${liveScanConsoleMarkup()}</div><section class="source-grid">${state.sources.length?state.sources.map(sourceCard).join(''):`<div class="source-empty">${empty('No sources configured','Add a filesystem, Plex, Jellyfin, or Emby source to begin.')}</div>`}</section>`;bindSources();bindLiveScanConsole();}
  function sourceCard(s){const active=state.scans.find(scan=>scan.source_id===s.id&&['queued','running','cancelling'].includes(scan.status));const resumable=state.scans.find(scan=>scan.source_id===s.id&&scan.resumable&&!['queued','running','cancelling'].includes(scan.status));return `<article class="source-card"><div class="source-card-top"><div class="source-icon">${icon(s.type==='filesystem'?'folder':'server')}</div><div><span class="eyebrow">${esc(s.type)}</span><h2>${esc(s.name)}</h2><p class="source-location" title="${esc(s.url_or_path)}">${esc(s.url_or_path)}</p></div><span class="status-pill ${esc(active?.status||s.last_scan_status||'')}">${esc(active?.status||s.last_scan_status||'not scanned')}</span></div><div class="source-metrics"><div><strong>${s.movie_count.toLocaleString()}</strong><span>Movies</span></div><div><strong>${fmtDate(s.last_scan_at)}</strong><span>Last scan</span></div><div><strong>${resumable?`${resumable.queue_remaining.toLocaleString()} left`:(s.schedule_enabled?`${s.schedule_minutes} min`:'Manual')}</strong><span>${resumable?'Deep queue':'Schedule'}</span></div></div><div class="source-card-actions">${active?`<button class="button danger small" data-cancel-source="${active.id}" ${active.status==='cancelling'?'disabled':''}>${active.status==='cancelling'?'Cancelling…':'Cancel scan'}</button>`:`<button class="button primary small" data-scan="${s.id}" data-scan-mode="quick" title="Fast inventory and local metadata scan">${icon('refresh',15)}Quick scan</button><button class="button secondary small" data-scan="${s.id}" data-scan-mode="posters" title="Fetch missing or changed local, server, embedded, and TMDB artwork">${icon('film',15)}Posters</button><button class="button secondary small" data-deep-scan="${s.id}" title="Choose a targeted, resumable deep-analysis scope">${icon('database',15)}Deep scan</button>${resumable?`<button class="button secondary small resume-deep" data-resume-scan="${resumable.id}" title="Continue ${resumable.queue_remaining} pending files">${icon('refresh',15)}Resume deep</button>`:''}`}<button class="button secondary small" data-edit="${s.id}">${icon('edit',15)}Edit</button><button class="icon-button danger" data-delete="${s.id}" aria-label="Delete source">${icon('trash',17)}</button></div></article>`;}
  function bindSources(){document.getElementById('add-source').onclick=()=>openSourceModal();document.querySelectorAll('[data-scan]').forEach(b=>b.onclick=async()=>{const mode=b.dataset.scanMode||'quick';try{const run=await api.startScan(b.dataset.scan,mode);resetLiveRun(run.id,false);toast(mode==='posters'?'Poster refresh started':`${mode[0].toUpperCase()+mode.slice(1)} scan started`);await loadScans();await loadLiveScanEvents(run.id);renderSources();schedulePoll();}catch(e){toast(e.message,'error');}});document.querySelectorAll('[data-deep-scan]').forEach(b=>b.onclick=()=>openDeepScanModal(state.sources.find(source=>source.id===b.dataset.deepScan)));document.querySelectorAll('[data-resume-scan]').forEach(b=>b.onclick=async()=>{b.disabled=true;b.textContent='Resuming…';try{const run=await api.resumeScan(b.dataset.resumeScan);resetLiveRun(run.id,false);toast('Deep analysis resumed');await loadScans();await loadLiveScanEvents(run.id);renderSources();schedulePoll();}catch(e){toast(e.message,'error');await loadScans();renderSources();}});document.querySelectorAll('[data-cancel-source]').forEach(b=>b.onclick=async()=>{b.disabled=true;b.textContent='Cancelling…';try{await api.cancelScan(b.dataset.cancelSource);toast('Scan cancellation requested');await loadScans();await loadLiveScanEvents(b.dataset.cancelSource);renderSources();schedulePoll();}catch(e){toast(e.message,'error');await loadScans();renderSources();}});document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>openSourceModal(state.sources.find(s=>s.id===b.dataset.edit)));document.querySelectorAll('[data-delete]').forEach(b=>b.onclick=async()=>{const source=state.sources.find(x=>x.id===b.dataset.delete);if(!confirm(`Delete source "${source?.name}" and its cached inventory? Media files will not be changed.`))return;try{await api.deleteSource(b.dataset.delete);await loadSources();renderSources();toast('Source deleted');}catch(e){toast(e.message,'error');}});}
  function openDeepScanModal(source){if(!source)return;const scopes=[['incomplete','Incomplete or changed','Analyze new, changed, failed, deferred, or technically incomplete files.'],['failed','Retry failed','Retry only files that previously failed or timed out.'],['missing','Missing fields','Analyze files missing codec, resolution, runtime, or audio information.'],['4k','4K / HDR candidates','Target files already marked 4K or named 2160p, 4K, HDR10, or Dolby Vision.'],['all','All files','Force a fresh deep analysis of every active media file.']];overlay.innerHTML=`<div class="modal-backdrop"><div class="source-modal deep-scan-modal"><div class="modal-header"><div><span class="eyebrow">Resumable background work</span><h2>Deep scan · ${esc(source.name)}</h2></div><button class="icon-button" data-close>${icon('x')}</button></div><form id="deep-scan-form"><p class="modal-intro">The inventory becomes available before deep analysis finishes. You can cancel and resume the remaining queue later.</p><div class="deep-scope-list">${scopes.map(([value,title,description],index)=>`<label class="deep-scope-option"><input type="radio" name="scope" value="${value}" ${index===0?'checked':''}/><span><strong>${title}</strong><small>${description}</small></span></label>`).join('')}</div><div class="warning-callout deep-warning">${icon('info',18)}<p>Standard probes are bounded to short reads. A timeout is deferred rather than followed by a longer retry. Extended probing runs only when a standard probe succeeds but leaves core fields missing.</p></div><div class="modal-actions"><div class="action-spacer"></div><button type="button" class="button ghost" data-close>Cancel</button><button type="submit" class="button primary">Start deep scan</button></div></form></div></div>`;const close=()=>overlay.innerHTML='';overlay.querySelectorAll('[data-close]').forEach(button=>button.onclick=close);document.getElementById('deep-scan-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;button.textContent='Starting…';const scope=new FormData(event.currentTarget).get('scope')||'incomplete';try{const run=await api.startScan(source.id,'deep',String(scope));overlay.innerHTML='';resetLiveRun(run.id,false);toast(`Deep scan started · ${scope}`);await loadScans();await loadLiveScanEvents(run.id);renderSources();schedulePoll();}catch(error){button.disabled=false;button.textContent='Start deep scan';toast(error.message,'error');}};}
  function openSourceModal(source=null){const c=source?.config||{};const mapping=(c.path_mappings||[])[0]||{};const f={name:source?.name||'',type:source?.type||'filesystem',url_or_path:source?.url_or_path||'',library_id:source?.library_id||'',token:c.token||'',user_id:c.user_id||'',verify_ssl:c.verify_ssl!==false,tmdb_token:c.tmdb_token||'',remote_path:mapping.remote||'',local_path:mapping.local||'',schedule_enabled:source?.schedule_enabled||false,schedule_minutes:source?.schedule_minutes||360};state.sourceModal={source,form:f,libraries:[]};renderSourceModal();}
  function renderSourceModal(status=''){const m=state.sourceModal,f=m.form;overlay.innerHTML=`<div class="modal-backdrop"><div class="source-modal"><div class="modal-header"><div><span class="eyebrow">${m.source?'Update connection':'New connection'}</span><h2>${m.source?'Edit source':'Add a media source'}</h2></div><button class="icon-button" data-close>${icon('x')}</button></div><div class="type-tabs">${['filesystem','plex','jellyfin','emby'].map(t=>`<button data-type="${t}" class="${f.type===t?'active':''}">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}</div><form id="source-form"><label><span>Display name</span><input name="name" value="${esc(f.name)}" required placeholder="Main movie library"/></label><label><span>${f.type==='filesystem'?'Movie folder path':'Server URL'}</span><input name="url_or_path" value="${esc(f.url_or_path)}" required placeholder="${f.type==='filesystem'?'D:\\Movies':'http://192.168.1.20:32400'}"/><small>${f.type==='filesystem'?'Use a local, mapped-drive, or UNC path.':'Use the base address of the media server.'}</small></label>${f.type!=='filesystem'?`<div class="form-grid two"><label><span>Read-only API token</span><input name="token" type="password" value="${esc(f.token)}" placeholder="API token"/></label>${f.type!=='plex'?`<label><span>User ID (optional)</span><input name="user_id" value="${esc(f.user_id)}"/></label>`:''}</div>`:''}${m.libraries.length?`<label><span>Movie library</span><select name="library_id" required><option value="">Select a library</option>${m.libraries.map(l=>`<option value="${esc(l.id)}" ${f.library_id===l.id?'selected':''}>${esc(l.name)}</option>`).join('')}</select></label>`:''}${f.type!=='filesystem'?`<details class="advanced"><summary>Path mapping and network options</summary><div class="form-grid two"><label><span>Server path prefix</span><input name="remote_path" value="${esc(f.remote_path)}" placeholder="D:\\Movies"/></label><label><span>Local accessible prefix</span><input name="local_path" value="${esc(f.local_path)}" placeholder="M:\\Movies"/></label></div><label class="check-row"><input type="checkbox" name="verify_ssl" ${f.verify_ssl?'checked':''}/><span>Verify TLS certificates</span></label></details>`:''}<details class="advanced"><summary>Metadata and schedule</summary><label><span>TMDB API read token (optional)</span><input type="password" name="tmdb_token" value="${esc(f.tmdb_token)}"/></label><div class="schedule-row"><label class="check-row"><input type="checkbox" name="schedule_enabled" ${f.schedule_enabled?'checked':''}/><span>Enable automatic rescans</span></label><label><span>Every</span><select name="schedule_minutes">${[[60,'1 hour'],[360,'6 hours'],[720,'12 hours'],[1440,'24 hours'],[10080,'Weekly']].map(([v,l])=>`<option value="${v}" ${Number(f.schedule_minutes)===v?'selected':''}>${l}</option>`).join('')}</select></label></div></details><div id="connection-status">${status}</div><div class="modal-actions"><button type="button" class="button secondary" id="test-source">Test connection</button><div class="action-spacer"></div><button type="button" class="button ghost" data-close>Cancel</button><button type="submit" class="button primary">${m.source?'Save changes':'Add source'}</button></div></form></div></div>`;bindSourceModal();}
  function readSourceForm(){const form=document.getElementById('source-form'),fd=new FormData(form),f=state.sourceModal.form;for(const key of ['name','url_or_path','library_id','token','user_id','remote_path','local_path','tmdb_token'])f[key]=String(fd.get(key)||'');f.verify_ssl=form.elements.verify_ssl?form.elements.verify_ssl.checked:true;f.schedule_enabled=form.elements.schedule_enabled.checked;f.schedule_minutes=Number(fd.get('schedule_minutes'));return f;}
  function sourcePayload(f){const config={};if(f.token)config.token=f.token;if(f.user_id)config.user_id=f.user_id;config.verify_ssl=f.verify_ssl;if(f.tmdb_token)config.tmdb_token=f.tmdb_token;if(f.remote_path&&f.local_path)config.path_mappings=[{remote:f.remote_path,local:f.local_path}];return {name:f.name,type:f.type,url_or_path:f.url_or_path,library_id:f.library_id||null,config,schedule_enabled:f.schedule_enabled,schedule_minutes:f.schedule_minutes,enabled:true};}
  function bindSourceModal(){overlay.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>{overlay.innerHTML='';state.sourceModal=null;});overlay.querySelectorAll('[data-type]').forEach(b=>b.onclick=()=>{readSourceForm();state.sourceModal.form.type=b.dataset.type;state.sourceModal.libraries=[];renderSourceModal();});document.getElementById('test-source').onclick=async()=>{const f=readSourceForm();renderSourceModal(`<div class="connection-status loading">${icon('refresh',18,'spin')}<span>Testing connection…</span></div>`);try{const r=await api.testSource({type:f.type,url_or_path:f.url_or_path,library_id:f.library_id||null,config:sourcePayload(f).config});state.sourceModal.libraries=r.libraries||[];if(!f.library_id&&state.sourceModal.libraries.length===1)f.library_id=state.sourceModal.libraries[0].id;renderSourceModal(`<div class="connection-status ${r.ok?'success':'error'}">${icon(r.ok?'check':'warning',18)}<span>${esc(r.message)}</span></div>`);}catch(e){renderSourceModal(`<div class="connection-status error">${icon('warning',18)}<span>${esc(e.message)}</span></div>`);}};document.getElementById('source-form').onsubmit=async e=>{e.preventDefault();const f=readSourceForm();const payload=sourcePayload(f);const submit=e.submitter;submit.disabled=true;submit.textContent='Saving…';try{if(state.sourceModal.source)await api.updateSource(state.sourceModal.source.id,payload);else await api.createSource(payload);overlay.innerHTML='';state.sourceModal=null;await loadSources();renderSources();toast('Source saved');}catch(err){submit.disabled=false;submit.textContent=state.sourceModal.source?'Save changes':'Add source';document.getElementById('connection-status').innerHTML=`<div class="connection-status error">${icon('warning',18)}<span>${esc(err.message)}</span></div>`;}};}

  async function renderDiagnostics(initial=false){
    if(initial){
      main.innerHTML=loading('Collecting diagnostics');
      try{state.diagnostics=await api.diagnostics();showError('');}
      catch(e){showError(e.message);state.diagnostics=null;}
    }
    const d=state.diagnostics;
    if(!d){
      main.innerHTML=`<section class="page-heading"><div><span class="eyebrow">Troubleshooting</span><h1>Diagnostics</h1></div></section><div class="error-panel">${icon('warning')}<p>Diagnostics could not be loaded.</p></div>`;
      return;
    }
    const activeScan=state.scans.some(scan=>['queued','running','cancelling'].includes(scan.status));
    const blocked=activeScan?'disabled':'';
    main.innerHTML=`<section class="page-heading split-heading"><div><span class="eyebrow">Troubleshooting and disclosure</span><h1>Diagnostics</h1><p>Review system capability, source configuration, and recent inventory runs.</p></div><a class="button secondary" href="/api/diagnostics/export" download>${icon('download',17)}Export JSON</a></section><div class="diagnostics-stack"><section class="diagnostic-card"><div class="section-heading"><div><span class="eyebrow">Runtime</span><h2>System</h2></div>${icon('activity')}</div>${valueGrid(d.system)}</section><section class="diagnostic-card"><div class="section-heading"><div><span class="eyebrow">Persistent cache</span><h2>Database</h2></div>${icon('database')}</div>${valueGrid(d.database)}</section><section class="diagnostic-card full logging-card"><div class="section-heading"><div><span class="eyebrow">Performance tracing</span><h2>Verbose scan logging</h2></div>${icon('activity')}</div><div class="logging-setting"><div><h3>Record per-file and per-stage timings</h3><p>Includes MediaInfo, ffprobe, cache, indexing, discovery, and poster timings in Scan output. This adds a small amount of logging overhead and should be disabled after troubleshooting.</p></div><label class="switch-row"><input id="verbose-scan-logging" type="checkbox" ${d.logging?.verbose_scan_logging?'checked':''}/><span>${d.logging?.verbose_scan_logging?'Enabled':'Disabled'}</span></label></div><div class="maintenance-warning privacy-note">${icon('info',17)}<span>Downloaded scan logs do not contain API tokens, but they can contain movie titles and filesystem paths.</span></div></section><section class="diagnostic-card full"><div class="section-heading"><div><span class="eyebrow">Recent activity</span><h2>Scan history</h2></div>${icon('clock')}</div><div class="scan-history">${d.recent_scans.length?d.recent_scans.map(scan=>`<div class="history-row"><span class="status-dot ${esc(scan.status)}"></span><div><strong>${esc(scan.status)}</strong><span>${esc(scan.started_at)}</span></div><div class="history-counts"><span>${scan.discovered} found</span><span>${scan.cached} cached</span><span>${scan.errors} errors</span></div></div>`).join(''):'<p style="padding:12px">No scans have run yet.</p>'}</div></section><section class="diagnostic-card full maintenance-card"><div class="section-heading"><div><span class="eyebrow">Destructive actions</span><h2>Maintenance</h2></div>${icon('trash')}</div>${activeScan?`<div class="maintenance-warning">${icon('warning',17)}<span>Cancel the active scan before clearing application data.</span></div>`:''}<div class="maintenance-grid"><article class="maintenance-action"><div><h3>Clear inventory cache</h3><p>Remove indexed movies, technical metadata, scan history, and downloaded posters. Source connections and credentials are retained.</p></div><button class="button secondary" id="clear-inventory" ${blocked}>Clear cache</button></article><article class="maintenance-action danger-zone"><div><h3>Factory reset ReelIndex</h3><p>Delete every source connection, stored credential, movie record, scan record, and cached poster. The installed application remains.</p></div><button class="button danger" id="factory-reset" ${blocked}>Reset everything</button></article></div></section></div>`;
    const verboseToggle=document.getElementById('verbose-scan-logging');
    verboseToggle.onchange=async()=>{verboseToggle.disabled=true;try{const result=await api.loggingSettings({verbose_scan_logging:verboseToggle.checked});d.logging=result;toast(`Verbose scan logging ${result.verbose_scan_logging?'enabled':'disabled'}`);renderDiagnostics(false);}catch(error){verboseToggle.checked=!verboseToggle.checked;toast(error.message,'error');verboseToggle.disabled=false;}};
    document.getElementById('clear-inventory').onclick=()=>openMaintenanceModal('cache');
    document.getElementById('factory-reset').onclick=()=>openMaintenanceModal('factory');
  }

  function openMaintenanceModal(mode){
    const factory=mode==='factory';
    const phrase=factory?'RESET REELINDEX':'CLEAR CACHE';
    const title=factory?'Factory reset ReelIndex':'Clear inventory cache';
    const description=factory
      ?'This permanently removes all ReelIndex database content, including source connections and encrypted credentials. Your movie files are never changed.'
      :'This removes the generated inventory, technical metadata, scan history, and poster cache. Your configured source connections are retained.';
    overlay.innerHTML=`<div class="modal-backdrop"><div class="source-modal maintenance-modal"><div class="modal-header"><div><span class="eyebrow">Confirmation required</span><h2>${title}</h2></div><button class="icon-button" data-close>${icon('x')}</button></div><div class="maintenance-confirmation"><div class="warning-callout">${icon('warning',20)}<p>${esc(description)}</p></div><label><span>Type <strong>${phrase}</strong> to continue</span><input id="maintenance-phrase" autocomplete="off" spellcheck="false" placeholder="${phrase}" /></label><div id="maintenance-status"></div><div class="modal-actions"><div class="action-spacer"></div><button type="button" class="button ghost" data-close>Cancel</button><button type="button" class="button danger" id="confirm-maintenance" disabled>${factory?'Reset everything':'Clear cache'}</button></div></div></div></div>`;
    const input=document.getElementById('maintenance-phrase');
    const confirmButton=document.getElementById('confirm-maintenance');
    const close=()=>{overlay.innerHTML='';};
    overlay.querySelectorAll('[data-close]').forEach(button=>button.onclick=close);
    input.oninput=()=>{confirmButton.disabled=input.value.trim()!==phrase;};
    input.onkeydown=event=>{if(event.key==='Enter'&&!confirmButton.disabled)confirmButton.click();};
    confirmButton.onclick=async()=>{
      confirmButton.disabled=true;
      input.disabled=true;
      confirmButton.textContent=factory?'Resetting…':'Clearing…';
      document.getElementById('maintenance-status').innerHTML=`<div class="connection-status loading">${icon('refresh',18,'spin')}<span>Please keep ReelIndex open while local data is removed.</span></div>`;
      try{
        const result=factory?await api.factoryReset(phrase):await api.clearInventory(phrase);
        toast(result.message||'Maintenance completed');
        if(factory)localStorage.removeItem('reelindex-view');
        overlay.innerHTML='';
        state.movies=null;state.stats=null;state.diagnostics=null;state.query={sort:'title',direction:'asc',page:1,page_size:100};
        await Promise.all([loadSources(),loadScans()]);
        state.page=factory?'sources':'library';
        location.hash=state.page;
        await renderPage();
      }catch(error){
        input.disabled=false;
        confirmButton.disabled=input.value.trim()!==phrase;
        confirmButton.textContent=factory?'Reset everything':'Clear cache';
        document.getElementById('maintenance-status').innerHTML=`<div class="connection-status error">${icon('warning',18)}<span>${esc(error.message)}</span></div>`;
      }
    };
    setTimeout(()=>input.focus(),0);
  }

  function valueGrid(data){return `<div class="diagnostic-grid">${Object.entries(data).map(([k,v])=>`<div class="diagnostic-value"><span>${esc(k.replaceAll('_',' '))}</span><strong>${esc(typeof v==='number'&&k.includes('disk')?fmtBytes(v):String(v??'—'))}</strong></div>`).join('')}</div>`;}

  async function loadReleaseIdentity(){try{const health=await api.health();const release=document.getElementById('release-label');const edition=document.getElementById('edition-label');if(release)release.textContent=`ReelIndex ${health.version||'1.4.5'}`;if(edition)edition.textContent=`${health.edition||'Local'} edition · AI-assisted, read-only inventory`;}catch(error){console.warn('Could not load release identity',error);}}

  (async function init(){await loadReleaseIdentity();await loadSources();await loadScans();renderPage();schedulePoll();})();
})();
