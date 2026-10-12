import {createTiming} from "./timing.js?v=timing1";
import {openBrowserSetup} from "./browser.js";
import {openGames} from "./games.js";
import {openStorage} from "./storage.js?v=auto1";
import {openRules} from "./rule-manager.js?v=content1";
import {purposeLabels, fillSelect, contextBadges, createContextEditor, openContextRules} from "./activity-context.js?v=2";
import {renderRibbon, titleDay} from "./timeline.js?v=activity2";
"use strict";
import { createCorrection, categoryLabels } from "/static/correction.js?v=activity2";
const $ = id => document.getElementById(id);
$("games-setup").onclick=openGames;
document.addEventListener("leisurelog:changed",()=>{offset=0;compareCache.clear();load();});
const categories = categoryLabels;
const names = {"chrome.exe":"Chrome","msedge.exe":"Microsoft Edge","ChatGPT.exe":"ChatGPT","explorer.exe":"文件管理器","QQ.exe":"QQ","Weixin.exe":"微信","LockApp.exe":"锁屏","WindowsTerminal.exe":"终端","Code.exe":"Visual Studio Code","WINWORD.EXE":"Word","EXCEL.EXE":"Excel","POWERPNT.EXE":"PowerPoint"};
const dayText = date => new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(date);
const clock = value => new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(value));
function duration(value){let n=Math.round(value||0);if(n<60)return `${n} 秒`;let h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return h?`${h} 小时 ${m} 分`:`${m} 分 ${s} 秒`;}
// Whole-day activity facts stay independent of the list's filters.
const hm=value=>{const n=Math.round((value||0)/60);if(n<1)return value>=1?"不到 1 分钟":"0 分";const h=Math.floor(n/60),m=n%60;return h?(m?`${h} 小时 ${m} 分`:`${h} 小时`):`${m} 分`;};
const groupLabels=Object.entries(purposeLabels);
let projectOptions=[];
const compareCache=new Map();
function weekBefore(day){
  if(!compareCache.has(day)){
    const noon=new Date(`${day}T12:00:00+08:00`).getTime(),back=n=>dayText(new Date(noon-n*86400000));
    compareCache.set(day,request(`/api/statistics?${new URLSearchParams({start:back(7),end:back(1),granularity:"day"})}`)
      .then(d=>{const days=d.trend.filter(t=>t.has_records).length;return days?{avg:d.totals.active_seconds/days,days}:null;}).catch(()=>null));
  }
  return compareCache.get(day);
}
function renderToday(h,day,isToday){
  $("leisure-label").textContent=isToday?"今天的电脑活动":"这一天的电脑活动";
  $("leisure").textContent=hm(h.activity_seconds);
  const list=$("top-list");list.replaceChildren();
  if(!h.top_all_activities.length)list.append(node("li",isToday?"今天还没有活动记录":"这一天没有活动记录","top-empty"));
  for(const item of h.top_all_activities){const li=node("li",undefined,`cat-${item.category}`),app=names[item.app]||item.app.replace(/\.exe$/i,"");const label=node("b",item.content||app);label.append(node("small",[purposeLabels[item.purpose],projectOptions.find(p=>p.id===item.project_id)?.name].filter(Boolean).join(" · ")));li.append(node("i"),label,node("em",hm(item.active_seconds)));li.title=`${purposeLabels[item.purpose]} · ${categories[item.category]||item.category} · ${app}`;list.append(li);}
  const total=h.activity_seconds||1;$("split-bar").replaceChildren();$("split-legend").replaceChildren();
  for(const [key,label] of groupLabels){const value=h.purpose_seconds[key]||0,bar=node("span",undefined,`purpose-${key}`),li=node("li",undefined,`purpose-${key}`);bar.style.width=`${value/total*100}%`;bar.title=`${label} ${hm(value)}`;$("split-bar").append(bar);li.append(node("i"),node("span",label),node("b",hm(value)));li.tabIndex=0;li.title=`筛选${label}活动`;const pick=()=>{$("purpose").value=$("purpose").value===key?"":key;reset();};li.onclick=pick;li.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pick();}};$("split-legend").append(li);}
  const note=$("leisure-compare");note.className="";note.textContent="正在和前 7 天比较…";
  weekBefore(day).then(result=>{
    if($("day").value!==day)return;
    if(!result){note.textContent="前 7 天没有记录可以比较";return;}
    if(isToday){note.textContent=`前 7 天平均每天 ${hm(result.avg)}`;return;}
    const diff=h.activity_seconds-result.avg;
    if(Math.abs(diff)<300||Math.abs(diff)<result.avg*.1){note.textContent=`和前 7 天平均（${hm(result.avg)}）差不多`;note.className="even";}
    else{note.textContent=`比前 7 天平均${diff>0?"多":"少"} ${hm(Math.abs(diff))}（平均 ${hm(result.avg)}）`;note.className=diff>0?"more":"less";}
  });
}
function node(tag,text,cls){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(cls)element.className=cls;return element;}
async function request(url){const response=await fetch(url,{cache:"no-store"});if(!response.ok)throw new Error(response.status===404?"这条活动已重新合并，请刷新列表后再查看。":"读取失败，请检查 LeisureLog 是否正在运行。");return response.json();}
let offset=0,total=0,version=0,detailVersion=0,forceRibbon=false;
const expanded=new Set();
const selected=new Set();
let pageEntries=[];
const eventIds=item=>item.kind==="group"?[...new Set(item.sessions.flatMap(s=>s.event_ids))]:item.event_ids;
function updateSelection(){
  $("selection-count").textContent=selected.size?`已选择 ${selected.size} 条活动记录`:"未选择活动";
  $("batch-context").disabled=$("clear-selection").disabled=selected.size===0;
  const all=[...new Set(pageEntries.flatMap(eventIds))];
  $("select-page").checked=all.length>0&&all.every(id=>selected.has(id));
  $("select-page").indeterminate=selected.size>0&&!$("select-page").checked;
  $("rows").querySelectorAll(".record-selection").forEach(input=>{input.checked=input.eventIds.every(id=>selected.has(id));input.indeterminate=!input.checked&&input.eventIds.some(id=>selected.has(id));});
}
function clearSelection(){selected.clear();updateSelection();}
const pref=(key,fallback)=>{try{const v=localStorage.getItem(`leisurelog:${key}`);return v===null?fallback:v==="1";}catch{return fallback;}};
const savePref=(key,value)=>{try{localStorage.setItem(`leisurelog:${key}`,value?"1":"0");}catch{}};
$("grouped").checked=pref("grouped",true);$("show-short").checked=pref("show-short",false);
const shortClock = value => new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(value));
const pageSize=50;
const linkedDay = new URLSearchParams(location.search).get("day");
let linkedSession = new URLSearchParams(location.search).get("session");
let linkedProject = new URLSearchParams(location.search).get("project_id") || "";
$("day").value = linkedDay && /^\d{4}-\d{2}-\d{2}$/.test(linkedDay) ? linkedDay : dayText(new Date());
if (!$("day").value) $("day").value = dayText(new Date());
fillSelect($("purpose"),Object.entries(purposeLabels),"全部用途",new URLSearchParams(location.search).get("purpose")||"");
fillSelect($("project"),[],"全部项目");
function setOptions(id,values,label){const chosen=$(id).value;$(id).replaceChildren(node("option",label));$(id).firstChild.value="";for(const value of values){const option=node("option",id==="category"?(categories[value]||value):(names[value]||value));option.value=value;$(id).append(option);}$(id).value=values.includes(chosen)?chosen:"";}
async function load(){
  const ticket=++version;$("refresh").disabled=true;$("error").hidden=true;clearSelection();
  try{
    const params=new URLSearchParams({day:$("day").value,app:$("app").value,category:$("category").value,purpose:$("purpose").value,project_id:$("project").value||linkedProject,query:$("search").value,limit:pageSize,offset,view:$("grouped").checked?"grouped":"sessions",min_seconds:$("show-short").checked?0:60});
    const data=await request(`/api/dashboard?${params}`);if(ticket!==version)return;
    total=data.total;if(offset>0&&offset>=total){offset=Math.max(0,Math.floor((total-1)/pageSize)*pageSize);load();return;}setOptions("app",data.options.apps,"全部应用");setOptions("category",data.options.categories,"全部类型");
    projectOptions=data.options.projects;fillSelect($("project"),[["none","未关联项目"],...projectOptions.map(p=>[p.id,p.name+(p.archived?"（已归档）":"")])],"全部项目",$("project").value||linkedProject);linkedProject="";
    const sum=values=>Object.values(values).reduce((a,b)=>a+b,0);
    $("active").textContent=duration(sum(data.summary.active_seconds_by_category));$("recorded").textContent=duration(sum(data.summary.recorded_seconds_by_category));$("afk").textContent=duration(data.summary.afk_seconds);$("unverified").textContent=duration(data.summary.unverified_seconds);$("details-summary").textContent=`计入 ${hm(sum(data.summary.active_seconds_by_category))} · 待确认 ${hm(data.summary.unverified_seconds)}`;if(data.highlights)renderToday(data.highlights,$("day").value,$("day").value===dayText(new Date()));$("count").textContent=total;
    pageEntries=data.items;$("rows").replaceChildren();for(const item of data.items)renderEntry(item);updateSelection();
    const merged=data.view==="grouped"?"同一应用、内容、用途与项目的相邻片段合并，时长按片段相加。":"每个片段单独一行。";
    $("list-note").textContent=`北京时间，最近的在前。${merged}${data.hidden_short?`已收起 ${data.hidden_short} 条不到 1 分钟的零碎记录。`:""}`;
    const today=dayText(new Date());titleDay($("day").value,today);renderRibbon({day:$("day").value,app:$("app").value,category:$("category").value,purpose:$("purpose").value,project_id:$("project").value,query:$("search").value},data.summary,{force:forceRibbon,isToday:$("day").value===today,onPick:showDetail});forceRibbon=false;
    $("empty").hidden=total!==0;$("page-label").textContent=total?`${offset+1}–${Math.min(offset+pageSize,total)} 条 / 共 ${total} 条`:"共 0 条";$("prev-page").disabled=offset===0;$("next-page").disabled=offset+pageSize>=total;
    if(linkedSession){const id=linkedSession;linkedSession=null;showDetail({id,app:new URLSearchParams(location.search).get('app')||'活动记录'});}
  }catch(error){if(ticket===version){$("error").textContent=error.message;$("error").hidden=false;}}
  finally{if(ticket===version)$("refresh").disabled=false;}
}
function renderEntry(item){
  if(item.kind!=="group"){$("rows").append(renderRow(item));return;}
  if(item.session_count===1){$("rows").append(renderRow(item.sessions[0]));return;}
  const row=renderRow(item,{group:true});$("rows").append(row);
  if(expanded.has(item.id))toggleGroup(item,row);
}
function toggleGroup(item,row){
  const open=row.dataset.open==="1",button=row.querySelector(".detail-button");
  if(open){let next=row.nextElementSibling;while(next&&next.dataset.parent===item.id){const gone=next;next=next.nextElementSibling;gone.remove();}row.dataset.open="0";expanded.delete(item.id);button.textContent=`展开 ${item.session_count} 段`;button.setAttribute("aria-expanded","false");return;}
  let anchor=row;for(const session of item.sessions){const child=renderRow(session,{child:true});child.dataset.parent=item.id;anchor.after(child);anchor=child;}
  row.dataset.open="1";expanded.add(item.id);button.textContent="收起";button.setAttribute("aria-expanded","true");
}
function renderRow(item,{group=false,child=false}={}){
  const row=node("tr",undefined,`cat-${item.classification.category}${group?" group-row":""}${child?" child-row":""}`);
  const selectionCell=node("td",undefined,"selection-cell"),select=node("input",undefined,"record-selection");select.type="checkbox";select.eventIds=eventIds(item);select.setAttribute("aria-label",`选择 ${item.classification.content||item.title||item.app} 的活动`);select.checked=select.eventIds.every(id=>selected.has(id));select.onchange=()=>{select.eventIds.forEach(id=>select.checked?selected.add(id):selected.delete(id));updateSelection();};selectionCell.append(select);row.append(selectionCell);
  const fmt=child?clock:shortClock,when=node("td",`${fmt(item.start_time)} – ${fmt(item.end_time)}`,"time");
  if(group)when.append(node("small",`${item.session_count} 段合并`,"group-count"));row.append(when);
  const content=node("td",undefined,"content"),line=node("div",undefined,"app-line"),name=names[item.app]||item.app||"未知应用",icon=node("span",name.slice(0,1),"app-icon"),info=node("div");info.append(node("div",name,"app-name"));const title=node("div",item.classification.content||item.title||"无窗口标题","title");title.title=item.title;info.append(title);info.append(contextBadges(item.context,projectOptions));if(item.url && item.classification.content && item.title !== item.classification.content) info.append(node("div",item.title,"title"));line.append(icon,info);content.append(line);row.append(content);
  const cat=node("td"),badge=node("span",categories[item.classification.category]||item.classification.category,"badge");badge.title=item.classification.origin==="manual"?"人工覆盖":"自动分类";badge.classList.add(`cat-${item.classification.category}`);cat.append(badge);if(item.classification.origin==="manual")cat.append(node("small","人工","manual-label"));if(item.retained_afk_seconds)cat.append(node("small",`计时保留 ${duration(item.retained_afk_seconds)}`,"manual-label"));row.append(cat,node("td",duration(item.recorded_seconds),"num"),node("td",duration(item.active_seconds),"num active-time"));
  const timing=node("td"),bar=node("div",undefined,"bar"),den=item.recorded_seconds||1;const parts=[[Math.max(0,item.active_seconds-item.unverified_seconds),"confirmed"],[item.unverified_seconds,"uncertain"],[item.afk_seconds,"away"]];for(const [seconds,cls]of parts){const part=node("span",undefined,cls);part.style.width=`${seconds/den*100}%`;bar.append(part);}bar.title=`状态有记录 ${duration(parts[0][0])} · 待确认 ${duration(item.unverified_seconds)} · 离开 ${duration(item.afk_seconds)}`;timing.append(bar,node("div",item.afk_seconds?`离开 ${duration(item.afk_seconds)}`:item.unverified_seconds?"状态待确认":"状态已覆盖","bar-label"));row.append(timing);
  const action=node("td"),button=node("button",group?`展开 ${item.session_count} 段`:"查看","detail-button");
  if(group){button.setAttribute("aria-expanded","false");button.addEventListener("click",()=>toggleGroup(item,row));}else button.addEventListener("click",()=>showDetail(item));
  action.append(button);row.append(action);return row;
}
async function syncStatus(){try{const state=await request("/api/sync/status");$("sync-box").dataset.state=state.last_error?"error":state.enabled?"on":"off";$("sync-state").textContent=state.last_error?"同步暂时失败，将自动重试":state.running?"正在同步活动…":state.enabled?"自动同步运行中":"自动同步已关闭";$("sync-time").textContent=state.last_success_at?`最近成功 ${clock(state.last_success_at)}`:"尚无成功同步记录";}catch{ $("sync-box").dataset.state="error";$("sync-state").textContent="暂时无法连接后端";$("sync-time").textContent="";}}
function detailTable(headers,rows){const table=node("table"),head=node("tr");headers.forEach(h=>head.append(node("th",h)));const thead=node("thead");thead.append(head);table.append(thead);const body=node("tbody");rows.forEach(values=>{const row=node("tr");values.forEach(value=>row.append(node("td",value)));body.append(row);});table.append(body);const wrap=node("div",undefined,"table-wrap");wrap.append(table);return wrap;}
async function showDetail(item){
  const ticket=++detailVersion;$("detail-name").textContent=names[item.app]||item.app;$("detail-body").replaceChildren(node("p","正在读取记录依据…"));$("detail").showModal();
  try{const data=await request(`/api/sessions/${encodeURIComponent(item.id)}/details?day=${$("day").value}`);if(ticket!==detailVersion||!$("detail").open)return;
    const s=data.session,body=$("detail-body"),summary=node("div",undefined,"detail-summary");for(const [label,value]of[["原始记录",s.recorded_seconds],["实际扣除",s.afk_seconds],["计入时长",s.active_seconds]]){const part=node("div");part.append(node("small",label),node("strong",duration(value)));summary.append(part);}body.replaceChildren(summary);body.append(node("p",`检测到离开：${duration(s.detected_afk_seconds)} · 策略保留：${duration(s.retained_afk_seconds)} · 实际扣除：${duration(s.afk_seconds)}`));body.append(node("p",s.title||"无窗口标题","detail-title"));body.append(node("p",`设备：${s.device} · 状态待确认：${duration(s.unverified_seconds)} · 分类：${categories[s.classification.category]||s.classification.category}`));
    if (s.url) body.append(node("p", `网页地址：${s.url}`));
    if (data.browser_events?.length) body.append(node("p", `已关联 ${data.browser_events.length} 条网页来源记录；时长仍依据前台窗口。`));
    const contextEditor=await createContextEditor(data,async message=>{$("detail").close();$("notice").textContent=message;$("notice").hidden=false;compareCache.clear();offset=0;forceRibbon=true;await load();});if(ticket!==detailVersion||!$("detail").open)return;body.append(contextEditor);
    body.append(createTiming(data, async message => {$("detail").close();$("notice").textContent=message;$("notice").hidden=false;offset=0;await load();}));
    body.append(createCorrection(data, async message => {$("detail").close();$("notice").textContent=message;$("notice").hidden=false;offset=0;await load();}));
    body.append(node("h3",`组成这个片段的记录（${data.events.length} 条）`));body.append(detailTable(["开始 / 结束","标题","分类来源"],data.events.map(e=>[`${clock(e.start_time)} – ${clock(e.end_time)}`,e.title||"—",e.classification.origin==="manual"?"人工覆盖":e.classification.origin==="learned"?"记住的规则":e.classification.origin.startsWith("rule:")?"规则识别":e.classification.origin.startsWith("playnite:")?"游戏库识别":"未分类"])));
    if (data.browser_events?.length) {body.append(node("h3","网页记录依据"));body.append(detailTable(["开始 / 结束","页面标题","网址"],data.browser_events.map(e=>[`${clock(e.start_time)} – ${clock(e.end_time)}`, e.title, e.url])));}
    body.append(node("h3","相关的离开状态"));if(data.idle_events.length)body.append(detailTable(["开始 / 结束","状态"],data.idle_events.map(e=>[`${clock(e.start_time)} – ${clock(e.end_time)}`,e.status==="afk"?"离开":"有键鼠活动"])));else body.append(node("p","没有对应状态，时长保留并标为待确认。"));body.append(node("p","显示当天的窗口记录；状态区间可能超出当前片段，计算只扣除重叠部分。"));
  }catch(error){if(ticket===detailVersion)$("detail-body").replaceChildren(node("p",error.message));}
}
function reset(){offset=0;load();}
function changeDay(delta){const date=new Date(`${$("day").value}T12:00:00+08:00`);date.setTime(date.getTime()+delta*86400000);$("day").value=dayText(date);$("app").value="";$("category").value="";reset();}
$("previous-day").onclick=()=>changeDay(-1);$("next-day").onclick=()=>changeDay(1);$("today").onclick=()=>{$("day").value=dayText(new Date());$("app").value="";$("category").value="";reset();};
$("day").onchange=()=>{if(!$("day").value)$("day").value=dayText(new Date());$("app").value="";$("category").value="";reset();};$("app").onchange=reset;$("category").onchange=reset;
$("grouped").onchange=()=>{savePref("grouped",$("grouped").checked);reset();};$("show-short").onchange=()=>{savePref("show-short",$("show-short").checked);reset();};
document.addEventListener("leisurelog:category",event=>{const value=$("category").value===event.detail?"":event.detail;$("category").value=value;if($("category").value!==value){const option=node("option",categories[value]||value);option.value=value;$("category").append(option);$("category").value=value;}reset();});
let debounce;$("search").oninput=()=>{clearTimeout(debounce);debounce=setTimeout(reset,250);};$("refresh").onclick=()=>{forceRibbon=true;load();syncStatus();};$("prev-page").onclick=()=>{offset=Math.max(0,offset-pageSize);load();};$("next-page").onclick=()=>{offset+=pageSize;load();};$("close-detail").onclick=()=>$("detail").close();
$("detail").addEventListener("click",event=>{if(event.target===$("detail")){const rect=$("detail").getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)$("detail").close();}});
load();syncStatus();setInterval(()=>{if(!document.hidden){syncStatus();if(!$("detail").open&&!selected.size){forceRibbon=true;load();}}},60000);

$("select-page").onchange=()=>{const ids=[...new Set(pageEntries.flatMap(eventIds))];ids.forEach(id=>$("select-page").checked?selected.add(id):selected.delete(id));updateSelection();};
$("clear-selection").onclick=clearSelection;
$("batch-context").onclick=async()=>{
  const ticket=++detailVersion;const ids=[...selected];$("detail-name").textContent="批量修改活动归属";$("detail-body").replaceChildren(node("p","正在读取归属选项…"));$("detail").showModal();
  try{const editor=await createContextEditor({events:ids.map(id=>({id}))},async message=>{$("detail").close();$("notice").textContent=message;$("notice").hidden=false;compareCache.clear();offset=0;forceRibbon=true;await load();},{batch:true});if(ticket===detailVersion&&$("detail").open)$("detail-body").replaceChildren(editor);}
  catch(error){if(ticket===detailVersion)$("detail-body").replaceChildren(node("p",error.message));}
};

$("manage-rules").onclick=()=>openRules(async()=>{offset=0;await load();});
$("manage-context").onclick=openContextRules;
$("purpose").onchange=reset;$("project").onchange=reset;

$("storage").onclick=()=>openStorage();

document.getElementById("browser-setup").onclick = openBrowserSetup;

document.querySelectorAll(".tools-menu button").forEach(button=>button.addEventListener("click",()=>button.closest("details").open=false));
document.addEventListener("click",event=>{const menu=document.querySelector(".tools[open]");if(menu&&!menu.contains(event.target))menu.open=false;});

$("reload-rules").onclick=async()=>{
  $("error").hidden=true;$("notice").textContent="正在重新读取 rules.yaml，并按新规则重新处理全部历史…";$("notice").hidden=false;
  try{
    const response=await fetch("/api/classification/reload-rules",{method:"POST"});
    if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(response.status===422?`规则文件有错误，仍在使用原来的规则。${body.detail||""}`:"重新读取失败，请确认 LeisureLog 正在运行。");}
    const result=await response.json();
    $("notice").textContent=`已读取 ${result.rules} 条规则，全部历史已按新规则重新分类。`;
    forceRibbon=true;offset=0;await load();
  }catch(error){$("notice").hidden=true;$("error").textContent=error.message;$("error").hidden=false;}
};
