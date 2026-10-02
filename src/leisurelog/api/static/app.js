import {createTiming} from "./timing.js?v=timing1";
import {openBrowserSetup} from "./browser.js";
import {openGames} from "./games.js";
import {openStorage} from "./storage.js";
import {openRules} from "./rule-manager.js?v=content1";
import {renderRibbon, titleDay} from "./timeline.js?v=planner3";
"use strict";
import { createCorrection, categoryLabels } from "/static/correction.js?v=content1";
const $ = id => document.getElementById(id);
$("games-setup").onclick=openGames;
document.addEventListener("leisurelog:changed",()=>{offset=0;load();});
const categories = categoryLabels;
const names = {"chrome.exe":"Chrome","msedge.exe":"Microsoft Edge","ChatGPT.exe":"ChatGPT","explorer.exe":"文件管理器","QQ.exe":"QQ","Weixin.exe":"微信","LockApp.exe":"锁屏","WindowsTerminal.exe":"终端"};
const dayText = date => new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(date);
const clock = value => new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(value));
function duration(value){let n=Math.round(value||0);if(n<60)return `${n} 秒`;let h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return h?`${h} 小时 ${m} 分`:`${m} 分 ${s} 秒`;}
function node(tag,text,cls){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(cls)element.className=cls;return element;}
async function request(url){const response=await fetch(url);if(!response.ok)throw new Error(response.status===404?"这条活动已重新合并，请刷新列表后再查看。":"读取失败，请检查 LeisureLog 是否正在运行。");return response.json();}
let offset=0,total=0,version=0,detailVersion=0,forceRibbon=false;
const pageSize=50;
const linkedDay = new URLSearchParams(location.search).get("day");
let linkedSession = new URLSearchParams(location.search).get("session");
$("day").value = linkedDay && /^\d{4}-\d{2}-\d{2}$/.test(linkedDay) ? linkedDay : dayText(new Date());
if (!$("day").value) $("day").value = dayText(new Date());
function setOptions(id,values,label){const chosen=$(id).value;$(id).replaceChildren(node("option",label));$(id).firstChild.value="";for(const value of values){const option=node("option",id==="category"?(categories[value]||value):(names[value]||value));option.value=value;$(id).append(option);}$(id).value=values.includes(chosen)?chosen:"";}
async function load(){
  const ticket=++version;$("refresh").disabled=true;$("error").hidden=true;
  try{
    const params=new URLSearchParams({day:$("day").value,app:$("app").value,category:$("category").value,query:$("search").value,limit:pageSize,offset});
    const data=await request(`/api/dashboard?${params}`);if(ticket!==version)return;
    total=data.total;if(offset>0&&offset>=total){offset=Math.max(0,Math.floor((total-1)/pageSize)*pageSize);load();return;}setOptions("app",data.options.apps,"全部应用");setOptions("category",data.options.categories,"全部分类");
    const sum=values=>Object.values(values).reduce((a,b)=>a+b,0);
    $("active").textContent=duration(sum(data.summary.active_seconds_by_category));$("recorded").textContent=duration(sum(data.summary.recorded_seconds_by_category));$("afk").textContent=duration(data.summary.afk_seconds);$("unverified").textContent=duration(data.summary.unverified_seconds);$("count").textContent=total;
    $("rows").replaceChildren();for(const item of data.items)renderRow(item);
    const today=dayText(new Date());titleDay($("day").value,today);renderRibbon({day:$("day").value,app:$("app").value,category:$("category").value,query:$("search").value},data.summary,{force:forceRibbon,isToday:$("day").value===today,onPick:showDetail});forceRibbon=false;
    $("empty").hidden=total!==0;$("page-label").textContent=total?`${offset+1}–${Math.min(offset+pageSize,total)} 条 / 共 ${total} 条`:"共 0 条";$("prev-page").disabled=offset===0;$("next-page").disabled=offset+pageSize>=total;
    if(linkedSession){const id=linkedSession;linkedSession=null;showDetail({id,app:new URLSearchParams(location.search).get('app')||'活动记录'});}
  }catch(error){if(ticket===version){$("error").textContent=error.message;$("error").hidden=false;}}
  finally{if(ticket===version)$("refresh").disabled=false;}
}
function renderRow(item){
  const row=node("tr",undefined,`cat-${item.classification.category}`);row.append(node("td",`${clock(item.start_time)} – ${clock(item.end_time)}`,"time"));
  const content=node("td",undefined,"content"),line=node("div",undefined,"app-line"),name=names[item.app]||item.app||"未知应用",icon=node("span",name.slice(0,1),"app-icon"),info=node("div");info.append(node("div",name,"app-name"));const title=node("div",item.classification.content||item.title||"无窗口标题","title");title.title=item.title;info.append(title);if(item.url && item.classification.content && item.title !== item.classification.content) info.append(node("div",item.title,"title"));line.append(icon,info);content.append(line);row.append(content);
  const cat=node("td"),badge=node("span",categories[item.classification.category]||item.classification.category,"badge");badge.title=item.classification.origin==="manual"?"人工覆盖":"自动分类";badge.classList.add(`cat-${item.classification.category}`);cat.append(badge);if(item.classification.origin==="manual")cat.append(node("small","人工","manual-label"));if(item.retained_afk_seconds)cat.append(node("small",`计时保留 ${duration(item.retained_afk_seconds)}`,"manual-label"));row.append(cat,node("td",duration(item.recorded_seconds),"num"),node("td",duration(item.active_seconds),"num active-time"));
  const timing=node("td"),bar=node("div",undefined,"bar"),den=item.recorded_seconds||1;const parts=[[Math.max(0,item.active_seconds-item.unverified_seconds),"confirmed"],[item.unverified_seconds,"uncertain"],[item.afk_seconds,"away"]];for(const [seconds,cls]of parts){const part=node("span",undefined,cls);part.style.width=`${seconds/den*100}%`;bar.append(part);}bar.title=`状态有记录 ${duration(parts[0][0])} · 待确认 ${duration(item.unverified_seconds)} · 离开 ${duration(item.afk_seconds)}`;timing.append(bar,node("div",item.afk_seconds?`离开 ${duration(item.afk_seconds)}`:item.unverified_seconds?"状态待确认":"状态已覆盖","bar-label"));row.append(timing);
  const action=node("td"),button=node("button","查看","detail-button");button.addEventListener("click",()=>showDetail(item));action.append(button);row.append(action);$("rows").append(row);
}
async function syncStatus(){try{const state=await request("/api/sync/status");$("sync-box").dataset.state=state.last_error?"error":state.enabled?"on":"off";$("sync-state").textContent=state.last_error?"同步暂时失败，将自动重试":state.running?"正在同步活动…":state.enabled?"自动同步运行中":"自动同步已关闭";$("sync-time").textContent=state.last_success_at?`最近成功 ${clock(state.last_success_at)}`:"尚无成功同步记录";}catch{ $("sync-box").dataset.state="error";$("sync-state").textContent="暂时无法连接后端";$("sync-time").textContent="";}}
function detailTable(headers,rows){const table=node("table"),head=node("tr");headers.forEach(h=>head.append(node("th",h)));const thead=node("thead");thead.append(head);table.append(thead);const body=node("tbody");rows.forEach(values=>{const row=node("tr");values.forEach(value=>row.append(node("td",value)));body.append(row);});table.append(body);const wrap=node("div",undefined,"table-wrap");wrap.append(table);return wrap;}
async function showDetail(item){
  const ticket=++detailVersion;$("detail-name").textContent=names[item.app]||item.app;$("detail-body").replaceChildren(node("p","正在读取记录依据…"));$("detail").showModal();
  try{const data=await request(`/api/sessions/${encodeURIComponent(item.id)}/details?day=${$("day").value}`);if(ticket!==detailVersion||!$("detail").open)return;
    const s=data.session,body=$("detail-body"),summary=node("div",undefined,"detail-summary");for(const [label,value]of[["原始记录",s.recorded_seconds],["实际扣除",s.afk_seconds],["计入时长",s.active_seconds]]){const part=node("div");part.append(node("small",label),node("strong",duration(value)));summary.append(part);}body.replaceChildren(summary);body.append(node("p",`检测到离开：${duration(s.detected_afk_seconds)} · 策略保留：${duration(s.retained_afk_seconds)} · 实际扣除：${duration(s.afk_seconds)}`));body.append(node("p",s.title||"无窗口标题","detail-title"));body.append(node("p",`设备：${s.device} · 状态待确认：${duration(s.unverified_seconds)} · 分类：${categories[s.classification.category]||s.classification.category}`));
    if (s.url) body.append(node("p", `网页地址：${s.url}`));
    if (data.browser_events?.length) body.append(node("p", `已关联 ${data.browser_events.length} 条网页来源记录；时长仍依据前台窗口。`));
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
let debounce;$("search").oninput=()=>{clearTimeout(debounce);debounce=setTimeout(reset,250);};$("refresh").onclick=()=>{forceRibbon=true;load();syncStatus();};$("prev-page").onclick=()=>{offset=Math.max(0,offset-pageSize);load();};$("next-page").onclick=()=>{offset+=pageSize;load();};$("close-detail").onclick=()=>$("detail").close();
$("detail").addEventListener("click",event=>{if(event.target===$("detail")){const rect=$("detail").getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)$("detail").close();}});
load();syncStatus();setInterval(()=>{if(!document.hidden){syncStatus();if(!$("detail").open){forceRibbon=true;load();}}},60000);

$("manage-rules").onclick=()=>openRules(async()=>{offset=0;await load();});

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
