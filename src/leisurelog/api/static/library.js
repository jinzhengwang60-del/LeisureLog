import {categoryName} from "/static/category-labels.js?v=1";
const $ = id => document.getElementById(id);
const apps = {'msedge.exe':'Microsoft Edge','chrome.exe':'Chrome','GenshinImpact.exe':'原神'};
const appName = value => apps[value] || value;
let offset = 0, dayOffset = 0, current = null, busy = false, ticket = 0, detailTicket = 0;
let mergeCandidates = [];
const limit = 50;
function node(tag, text, className) {const element = document.createElement(tag); if(text !== undefined) element.textContent=text; if(className) element.className=className; return element;}
function duration(value) {const n=Math.round(value||0); if(n<60)return `${n} 秒`;if(n<3600)return `${Math.floor(n/60)} 分 ${n%60} 秒`;return `${Math.floor(n/3600)} 小时 ${Math.floor(n%3600/60)} 分`;}
function date(value) {return value ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value)) : '尚无记录';}
function datetime(value) {return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));}
function message(id,text) {$(id).textContent=text;$(id).hidden=!text;}
async function api(path,options={}) {const response=await fetch(path,options);const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'无法完成操作，请检查输入或刷新重试');return data;}
function params() {return new URLSearchParams({query:$('search').value,category:$('category').value,sort:$('sort').value,limit,offset});}
async function load() {
  const request=++ticket;
  try {
    const data=await api(`/api/library?${params()}`);if(request!==ticket)return;
    $('rows').replaceChildren();$('total').textContent=`${data.total} 项`;$('total-time').textContent=duration(data.active_seconds);
    const selected=$('category').value;$('category').replaceChildren(new Option('全部分类',''),...data.categories.map(c=>new Option(categoryName(c),c)));$('category').value=selected;
    for(const item of data.items){const row=node('tr');const title=node('td');const button=node('button',item.name,'library-title');button.addEventListener('click',()=>open(item.id));title.append(button,node('div',(item.apps||[]).map(appName).join('、'),'library-app'));const cat=node('td');cat.append(node('span',categoryName(item.category),`badge cat-${item.category}`));row.append(title,cat,node('td',duration(item.active_seconds),'num active-time'),node('td',`${item.days} 天`,'num'),node('td',date(item.last_seen)));const action=node('td');const view=node('button','查看','detail-button');view.setAttribute('aria-label',`查看 ${item.name}`);view.onclick=()=>open(item.id);action.append(view);row.append(action);$('rows').append(row);}
    renderCards(data.items);$('empty').hidden=data.items.length!==0;$('page-label').textContent=data.total?`第 ${offset+1}–${offset+data.items.length} 项，共 ${data.total} 项`:'暂无匹配内容';$('prev-page').disabled=offset===0;$('next-page').disabled=offset+limit>=data.total;
  }catch(error){if(request===ticket)message('error',error.message);}
}
// Card wall: real Playnite covers for games, generated art from the name for everything else.
const glyph=name=>{const clean=(name||'').replace(/^[\s【\[（(「『《"“'#]+/,'');return Array.from(clean)[0]||'?';};
function renderCards(items){
  const wall=$('cards');wall.replaceChildren();
  for(const item of items){
    const card=node('a',undefined,`cover-card cat-${item.category}`);card.href=`?item=${encodeURIComponent(item.id)}`;
    card.addEventListener('click',event=>{event.preventDefault();open(item.id);});
    const art=node('span',undefined,'cover-art');
    if(item.cover){const img=node('img');img.loading='lazy';img.alt='';img.src=item.cover;img.onerror=()=>{img.remove();art.classList.add('generated');art.prepend(node('span',glyph(item.name),'cover-glyph'));};art.append(img);}
    else{art.classList.add('generated');art.append(node('span',glyph(item.name),'cover-glyph'));}
    art.append(node('span',categoryName(item.category),'cover-tag'));
    card.append(art,node('span',item.name,'cover-name'),node('span',`${duration(item.active_seconds)} · ${item.days} 天`,'cover-meta'));
    card.title=`${item.name}
${(item.apps||[]).map(appName).join('、')}`;
    wall.append(card);
  }
  window.LeisureMotion?.reveal(wall, {key: params().toString()});
}
// Same-named items recorded from different programs (a game, its launcher, a mod tool…).
let dupGroups=[];
async function loadDuplicates(){
  try{
    const data=await api('/api/library/duplicates');dupGroups=data.groups;
    $('dups').hidden=!dupGroups.length;if(!dupGroups.length)return;
    const extra=dupGroups.reduce((n,g)=>n+g.items.length-1,0);
    $('dup-title').textContent=`发现 ${dupGroups.length} 组可以合并的条目`;
    $('dup-list').textContent=`同一个东西来自不同程序时会分成几张卡片：${dupGroups.slice(0,4).map(g=>`${g.name}（${g.items.length} 张）`).join('、')}${dupGroups.length>4?' 等':''}。合并后少 ${extra} 张卡片，时长和记录不变。`;
    $('dup-detail').replaceChildren(...dupGroups.map(g=>node('li',`${g.name} · ${categoryName(g.category)}：${g.items.map(i=>`${i.name}（${(i.apps||[]).map(appName).join('、')}）`).join(' + ')}`)));
  }catch{$('dups').hidden=true;}
}
$('dup-merge').onclick=async()=>{
  if(busy||!dupGroups.length)return;
  if(!window.confirm(`把 ${dupGroups.length} 组同名条目各自合并成一个？\n每组保留时长最多的那个名称。合并后仍可在详情里把名称拆分回去。`))return;
  busy=true;$('dup-merge').disabled=true;$('dup-merge').textContent='正在合并…';message('error','');
  try{
    const groups=dupGroups.map(g=>({target_id:g.target_id,source_ids:g.items.map(i=>i.id).filter(id=>id!==g.target_id)}));
    const data=await api('/api/library/duplicates/merge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({groups})});
    message('notice',`已合并 ${data.merged} 个重复条目。`);
  }catch(error){message('error',error.message);}
  finally{busy=false;$('dup-merge').disabled=false;$('dup-merge').textContent='全部合并';load();loadDuplicates();}
};
loadDuplicates();
function setView(view){
  try{localStorage.setItem('leisurelog:library-view',view);}catch{}
  document.querySelectorAll('.view-switch button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));
  $('cards').hidden=view!=='cards';$('list-view').hidden=view==='cards';
}
document.querySelectorAll('.view-switch button').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
setView((()=>{try{return localStorage.getItem('leisurelog:library-view')||'cards';}catch{return 'cards';}})());
function dayLink(day,text) {const link=node('a',text||day);link.href=`/?day=${encodeURIComponent(day)}`;return link;}
function renderDetail(data) {
  current=data;$('detail-name').textContent=data.item.name;document.title=`${data.item.name} · LeisureLog`;$('detail-category').textContent=`${categoryName(data.item.category)} · 详情`;
  $('seen').textContent=data.item.first_seen?`首次记录 ${datetime(data.item.first_seen)} · 最近记录 ${datetime(data.item.last_seen)}`:'这个名称尚无活动记录，遇到相应内容后会自动累计。';
  $('active').textContent=duration(data.item.active_seconds);$('recorded').textContent=duration(data.item.recorded_seconds);$('days-count').textContent=`${data.item.days} 天`;$('session-count').textContent=`${data.item.sessions} 个`;
  $('timing-note').textContent=`检测离开 ${duration(data.item.detected_afk_seconds)} · 策略保留 ${duration(data.item.retained_afk_seconds)} · 实际扣除 ${duration(data.item.afk_seconds)} · 状态待确认 ${duration(data.item.unverified_seconds)}。缺少记录的日期不代表没有使用；不同设备重叠活动尚未排重。`;
  $('name').value=data.item.name;$('notes').value=data.item.notes;
  $('months').replaceChildren();const max=Math.max(1,...data.months.map(m=>m.active_seconds));
  for(const month of data.months){const row=node('div',undefined,'month');const track=node('div',undefined,'month-track');const fill=node('div',undefined,'month-fill');fill.style.width=`${month.active_seconds/max*100}%`;track.append(fill);row.append(node('span',month.month),track,node('span',duration(month.active_seconds),'month-value'));$('months').append(row);}
  if(!data.months.length)$('months').append(node('p','还没有月份记录','no-data'));
  $('day-rows').replaceChildren();for(const day of data.days){const row=node('tr');const td=node('td');td.append(dayLink(day.day));row.append(td,node('td',duration(day.recorded_seconds),'num'),node('td',duration(day.active_seconds),'num active-time'),node('td',duration(day.afk_seconds),'num'));$('day-rows').append(row);}
  $('day-label').textContent=data.day_total?`第 ${dayOffset+1}–${dayOffset+data.days.length} 天，共 ${data.day_total} 天`:'暂无使用日期';$('previous-days').disabled=dayOffset===0;$('next-days').disabled=dayOffset+30>=data.day_total;
  $('recent').replaceChildren();for(const session of data.recent_sessions){const entry=node('div',undefined,'recent-entry');entry.append(dayLink(session.day,`${datetime(session.start_time)} · ${appName(session.app)} · ${duration(session.active_seconds)}`),node('p',`识别名称：${session.classification.content||'未命名'}；原始标题：${session.title||'无标题'}`));$('recent').append(entry);}if(!data.recent_sessions.length)$('recent').append(node('p','还没有活动记录','no-data'));
  $('aliases').replaceChildren();for(const alias of data.aliases){const row=node('div',undefined,'alias');const label=node('div');label.append(node('strong',alias.name),node('small',`${appName(alias.app)} · ${categoryName(alias.category)}`));const split=node('button','拆分');split.type='button';split.disabled=data.aliases.length<2;split.setAttribute('aria-label',`拆分名称 ${alias.name}`);split.onclick=()=>mutate(`/api/library/${data.item.id}/aliases/${alias.id}/split`,'POST',undefined,'已拆分为独立内容',true);row.append(label,split);$('aliases').append(row);}
  const appList=[...new Set(data.aliases.map(a=>a.app))];$('apps').replaceChildren(...appList.map(a=>new Option(appName(a),a)));$('alias-app').value=appList[0]||'';
  $('merge-source').replaceChildren(new Option('请先搜索',''));$('merge-query').value='';$('merge-preview').textContent='';$('merge-submit').disabled=true;mergeCandidates=[];
}
async function open(id,push=true) {
  const request=++detailTicket;message('error','');
  try{const data=await api(`/api/library/${encodeURIComponent(id)}?limit=30&offset=${dayOffset}`);if(request!==detailTicket)return;renderDetail(data);$('catalog').hidden=true;$('detail').hidden=false;if(push){const url=new URL(location.href);url.searchParams.set('item',id);history.pushState({},'',url);}window.scrollTo(0,0);}catch(error){if(request===detailTicket)message('error',error.message);}
}
async function mutate(path,method,body,success,navigate=false) {
  if(busy)return;busy=true;message('error','');message('notice','');const controls=[...$('detail').querySelectorAll('button')];const states=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);
  try{const data=await api(path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});dayOffset=0;renderDetail(data);if(navigate){const url=new URL(location.href);url.searchParams.set('item',data.item.id);history.replaceState({},'',url);}message('notice',success);await load();}
  catch(error){message('error',error.message);}
  finally{busy=false;controls.forEach((c,i)=>{if(c.isConnected)c.disabled=states[i];});$('merge-submit').disabled=!$('merge-source').value;$('previous-days').disabled=dayOffset===0;$('next-days').disabled=!current||dayOffset+30>=current.day_total;}
}
function back(push=true){if(busy)return;++detailTicket;current=null;dayOffset=0;$('catalog').hidden=false;$('detail').hidden=true;document.title='LeisureLog · 玩过看过';message('error','');if(push){const url=new URL(location.href);url.searchParams.delete('item');history.pushState({},'',url);}load();}
$('filters').onsubmit=e=>{e.preventDefault();offset=0;message('error','');load();};$('refresh').onclick=()=>{message('error','');load();};$('prev-page').onclick=()=>{offset=Math.max(0,offset-limit);load();};$('next-page').onclick=()=>{offset+=limit;load();};$('back').onclick=()=>back();
$('refresh-detail').onclick=()=>{if(current&&!busy)open(current.item.id,false);};
$('previous-days').onclick=()=>{dayOffset=Math.max(0,dayOffset-30);open(current.item.id,false);};$('next-days').onclick=()=>{dayOffset+=30;open(current.item.id,false);};
$('edit').onsubmit=e=>{e.preventDefault();mutate(`/api/library/${current.item.id}`,'PATCH',{name:$('name').value,notes:$('notes').value},'展示名称和备注已保存');};
$('add-alias').onsubmit=e=>{e.preventDefault();mutate(`/api/library/${current.item.id}/aliases`,'POST',{app:$('alias-app').value,name:$('alias-name').value},'已关联名称，之后的记录也会归入这里');};
$('merge-search').onsubmit=async e=>{e.preventDefault();const id=current.item.id;const query=$('merge-query').value;message('error','');try{const data=await api(`/api/library?${new URLSearchParams({category:current.item.category,query,limit:100})}`);if(!current||current.item.id!==id||$('merge-query').value!==query)return;mergeCandidates=data.items.filter(i=>i.id!==id);$('merge-source').replaceChildren(new Option(mergeCandidates.length?'选择一个内容条目':'没有可合并内容',''),...mergeCandidates.map(i=>new Option(`${i.name} · ${(i.apps||[]).map(appName).join('、')} · ${duration(i.active_seconds)}`,i.id)));$('merge-preview').textContent=data.total>100?'仅显示前 100 项，请输入更完整的名称缩小范围。':'';$('merge-submit').disabled=true;}catch(error){message('error',error.message);}};
$('merge-source').onchange=()=>{const source=mergeCandidates.find(i=>i.id===$('merge-source').value);$('merge-submit').disabled=!source;$('merge-preview').textContent=source?`“${source.name}” → “${current.item.name}”，合并后计入 ${duration(current.item.active_seconds+source.active_seconds)}。`:'';};
$('merge').onsubmit=e=>{e.preventDefault();if($('merge-source').value)mutate(`/api/library/${current.item.id}/merge`,'POST',{source_id:$('merge-source').value},'内容已合并；可在关联名称中拆分');};
window.addEventListener('popstate',()=>{const id=new URLSearchParams(location.search).get('item');dayOffset=0;if(id)open(id,false);else back(false);});
setInterval(()=>{if(!document.hidden&&!current&&!busy)load();},60000);
const initial=new URLSearchParams(location.search);$('search').value=initial.get('query')||'';await load();if(initial.get('item'))await open(initial.get('item'),false);
