export async function openGames(){
  let dialog=document.getElementById('games-dialog');
  if(!dialog){
    dialog=document.createElement('dialog');dialog.id='games-dialog';
    dialog.innerHTML='<div class="dialog-head"><h2>Playnite 游戏库</h2><button id="games-close" aria-label="关闭">✕</button></div><p>ActivityWatch 记录前台活动时间，Playnite 提供游戏资料。启动器和游戏会分别识别。</p><p id="games-status" role="status"></p><p id="games-path"></p><button id="games-import" class="primary">读取最新游戏资料</button><p id="games-error" class="error" role="alert" hidden></p><div class="table-wrap"><table><thead><tr><th>游戏</th><th>安装状态</th><th>自动识别依据</th></tr></thead><tbody id="games-list"></tbody></table></div><p class="footnote">尚未接入时，需要安装本地连接扩展。已接入后，资料导出会在下一轮自动同步中读取。手动修改 Playnite 条目后，可从 Playnite 的 LeisureLog 菜单同步资料。</p>';
    document.body.append(dialog);document.getElementById('games-close').onclick=()=>dialog.close();
    document.getElementById('games-import').onclick=()=>load(true);
  }
  dialog.showModal();await load(false);
  async function load(importing){
    const button=document.getElementById('games-import'),error=document.getElementById('games-error');button.disabled=true;error.hidden=true;
    try{
      const response=await fetch('/api/games/playnite'+(importing?'/import':''),{method:importing?'POST':'GET'});
      const data=await response.json();if(!response.ok)throw new Error('未能读取导出文件。请先在 Playnite 中同步游戏资料，再重试。已有记录继续保留。');
      document.getElementById('games-status').textContent=data.connected?`已接入 ${data.total} 个条目，其中 ${data.installed} 个已安装、${data.recognizable} 个具备识别依据。最近导入：${new Date(data.imported_at).toLocaleString('zh-CN')}`:'尚未接入。游戏库条目不会自动产生游玩时长。';
      if(data.export_path)document.getElementById('games-path').textContent='本地资料文件：'+data.export_path;
      const body=document.getElementById('games-list');body.replaceChildren();
      const games=[...data.games].sort((a,b)=>Number(b.installed)-Number(a.installed)||Number(Boolean(b.matches.length))-Number(Boolean(a.matches.length))||a.name.localeCompare(b.name,'zh-CN'));
      for(const game of games){const row=document.createElement('tr');for(const text of [game.name,game.installed?'已安装':'未安装',game.matches.length?game.matches.map(([app,title])=>app+(title?' · 标题包含 '+title:'')).join('；'):'待补充游戏进程']){const cell=document.createElement('td');cell.textContent=text;row.append(cell);}body.append(row);}
      if(importing)document.dispatchEvent(new Event('leisurelog:changed'));
    }catch(e){error.textContent=e.message;error.hidden=false;}finally{button.disabled=false;}
  }
}
