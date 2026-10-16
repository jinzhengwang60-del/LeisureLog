import {gameAccess, gameRequest, readGameAccess, gameLink as permittedGameLink} from './game-access.js';

const $=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const duration=value=>{const n=Math.round(value||0);return n<60?`${n} 秒`:n<3600?`${Math.floor(n/60)} 分 ${n%60} 秒`:`${Math.floor(n/3600)} 小时 ${Math.floor(n%3600/60)} 分`;};
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const palette=['#4f5bd5','#1a9c8c','#e0457b','#f2913d','#2e9bd6','#a9479c','#9db33a','#e5b524'];
let version=0,report=null,colors={};
let access=gameAccess(null);
function color(id){return id==='unknown'?'#c3c8d1':colors[id]||'#6d89ab';}
function gameLink(item){return permittedGameLink(document,item,access,{start:report.start,end:report.end});}
function gameRows(){const filter=$('type-filter').value;const rows=report.games.filter(g=>!filter||g.game_type.primary===filter);$('games').replaceChildren();for(const game of rows){const row=node('tr'),name=node('td');name.append(gameLink(game));row.append(name,node('td',game.game_type.label+(game.game_type.source==='manual'?' · 人工':' · 自动')),node('td',game.game_type.tags.join('、')||'暂无补充标签'),node('td',duration(game.active_seconds),'num'));$('games').append(row);}$('no-filter').hidden=rows.length!==0;}
function render(data){report=data;history.replaceState(null,"","/game-preferences?"+new URLSearchParams({start:data.start,end:data.end}));$("year").value=data.start.slice(0,4);$('total').textContent=data.coverage.game_days?duration(data.totals.active_seconds):'暂无记录';$('game-count').textContent=data.recorded_games;$('unknown').textContent=duration(data.untyped_seconds);$('timing').textContent=`原始 ${duration(data.totals.recorded_seconds)} · 扣除离开 ${duration(data.totals.afk_seconds)}`;$('days').textContent=`${data.coverage.game_days} 个有游戏记录日期`;$('unnamed').textContent=`其中未命名游戏 ${duration(data.unnamed_seconds)}`;
$('coverage').textContent=data.coverage.game_days?`所选范围 ${data.start} 至 ${data.end} · 实际游戏记录 ${data.coverage.first_game_day} 至 ${data.coverage.last_game_day} · 状态待确认 ${duration(data.totals.unverified_seconds)}`:`所选范围 ${data.start} 至 ${data.end} · 暂无游戏记录`;$('scope').textContent=data.scope;$('empty').hidden=data.coverage.game_days!==0;
$('types').replaceChildren();$('type-filter').replaceChildren(node('option','全部类型'));$('type-filter').firstChild.value='';
for(const type of data.types){const row=node('div'),heading=node('div',undefined,'type-row-heading'),button=node('button',type.label),track=node('div',undefined,'type-track'),fill=node('div',undefined,'type-fill');button.type='button';button.onclick=()=>{$('type-filter').value=type.primary;gameRows();};fill.style.width=`${(type.share||0)*100}%`;fill.style.background=color(type.primary);track.append(fill);heading.append(button,node('span',`${duration(type.active_seconds)} · ${type.share===null?'占比无可计入时长':(type.share*100).toFixed(1)+'%'} · ${type.game_count} 款已命名游戏`));row.append(heading,track);$('types').append(row);const option=node('option',type.label);option.value=type.primary;$('type-filter').append(option);}
$('trend').replaceChildren();const max=Math.max(...data.trend.map(m=>m.active_seconds),1);for(const month of data.trend){const row=node('tr'),chart=node('td',undefined,'trend-chart'),stack=node('div',undefined,'month-stack');stack.style.width=`${month.active_seconds/max*100}%`;const parts=[];for(const type of month.types){const segment=node('div',undefined,'month-segment');segment.style.width=`${(type.share||0)*100}%`;segment.style.background=color(type.primary);segment.title=`${type.label}：${duration(type.active_seconds)}`;stack.append(segment);parts.push(`${type.label} ${type.share===null?'0 秒':(type.share*100).toFixed(1)+'%'}`);}stack.setAttribute('role','img');stack.setAttribute('aria-label',`${month.month} ${parts.join('，')||'暂无游戏记录'}`);chart.append(stack);row.append(node('td',month.month),chart,node('td',month.has_game_records?duration(month.active_seconds):'—','num'),node('td',month.has_game_records?(parts.join(' · ')||'有游戏记录，计入为零'):month.has_activity_records?'有活动记录，未采集到游戏':'暂无活动记录'));$('trend').append(row);}gameRows();$('results').hidden=false;}
async function load(){
  const ticket=++version;
  $('loading').hidden=false; $('error').hidden=true; $('results').hidden=true;
  try {
    const next=await readGameAccess();
    if(ticket!==version)return;
    access=next;
    $('game-access-message').textContent=access.message;
    $('game-access-note').hidden=!access.message;
    $('games-overview').textContent=access.edit?'管理游戏类型':'查看游戏统计';
    $('game-list-description').textContent=access.details
      ? access.edit?'点击游戏修改主类型或查看游玩依据。':'点击游戏查看游玩明细；当前未开放类型修改。'
      : '查看每款游戏的累计时间；授权读取活动详情后可查看游玩明细。';
    if(access.known&&!access.available)return;
    const data=await gameRequest('/api/game-preferences?'+new URLSearchParams({
      start:$('start').value,end:$('end').value,
    }));
    if(ticket===version)render(data);
  } catch(error){
    if(ticket===version){$('error').textContent=error.message;$('error').hidden=false;}
  } finally{if(ticket===version)$('loading').hidden=true;}
}
function yearRange(year){$('start').value=String(year).padStart(4,'0')+'-01-01';$('end').value=String(year).padStart(4,'0')+'-12-31';load();}
$('range').onsubmit=e=>{e.preventDefault();load();};$('refresh').onclick=load;$('type-filter').onchange=gameRows;$('choose-year').onclick=()=>{const year=Number($('year').value);if(Number.isInteger(year)&&year>=1&&year<=9998)yearRange(year);else{$('error').textContent='请输入 1 至 9998 的年份。';$('error').hidden=false;}};
for(const button of document.querySelectorAll('[data-range]'))button.onclick=()=>{const end=today();const year=Number(end.slice(0,4));if(button.dataset.range==='last-year'){yearRange(year-1);return;}$('start').value=button.dataset.range==='month'?end.slice(0,7)+'-01':end.slice(0,4)+'-01-01';$('end').value=end;load();};
try{const response=await fetch('/api/game-types');if(!response.ok)throw new Error('类型选项读取失败');const options=await response.json();options.types.forEach((type,index)=>{colors[type.id]=palette[index%palette.length];});}catch{/* Report remains usable with fallback colors. */}
const now=today(),initial=new URLSearchParams(location.search),valid=/^\d{4}-\d{2}-\d{2}$/;$('start').value=valid.test(initial.get('start')||'')?initial.get('start'):now.slice(0,4)+'-01-01';$('end').value=valid.test(initial.get('end')||'')?initial.get('end'):now;$('year').value=$('start').value.slice(0,4);load();
