import {categoryLabels} from "/static/correction.js?v=content1";

const $ = id => document.getElementById(id);
const names = {"chrome.exe":"Chrome","msedge.exe":"Microsoft Edge","ChatGPT.exe":"ChatGPT","explorer.exe":"文件管理器","QQ.exe":"QQ","Weixin.exe":"微信","LockApp.exe":"锁屏","WindowsTerminal.exe":"终端","claude.exe":"Claude","LeagueClientUx.exe":"英雄联盟客户端","Playnite.DesktopApp.exe":"Playnite","steamwebhelper.exe":"Steam","wegame.exe":"WeGame"};
// Categories where a content name (a game, a show…) is useful.
const named = new Set(["game","video","film","anime","reading","music","live"]);
const choices = Object.entries(categoryLabels).filter(([key]) => key !== "unknown");
let busy = false;

function node(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function duration(value) {
  const n = Math.round(value || 0);
  if (n < 60) return `${n} 秒`;
  const h = Math.floor(n / 3600), m = Math.floor(n % 3600 / 60);
  return h ? `${h} 小时 ${m} 分` : `${m} 分 ${n % 60} 秒`;
}
const day = value => value ? new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"numeric",day:"numeric"}).format(new Date(value.endsWith("Z")||value.includes("+")?value:value+"Z")) : "—";

function appCell(item) {
  const cell = node("td"), wrap = node("div", undefined, "uncl-app"), info = node("div");
  const label = names[item.app];
  const title = node("div", label || item.app, "app-name");
  if (label) title.append(node("small", item.app));
  info.append(title);
  if (item.sample_titles.length) {
    const samples = node("div", item.sample_titles.join("、"), "samples");
    samples.title = item.sample_titles.join("\n");
    info.append(samples);
  }
  wrap.append(node("span", undefined, "app-icon"), info);
  cell.append(wrap);
  return cell;
}

function assignForm(item, row) {
  const form = node("form", undefined, "assign");
  const select = node("select"), name = node("input"), save = node("button", "保存", "primary");
  select.setAttribute("aria-label", `${names[item.app] || item.app} 的分类`);
  select.append(Object.assign(node("option", "选择分类…"), {value: ""}));
  for (const [key, label] of choices) select.append(Object.assign(node("option", label), {value: key}));
  name.placeholder = "名称（可选）"; name.maxLength = 300; name.hidden = true;
  name.setAttribute("aria-label", "内容名称，例如游戏名");
  save.type = "submit"; save.disabled = true;
  select.onchange = () => {
    save.disabled = !select.value || busy;
    name.hidden = !named.has(select.value);
    row.className = select.value ? `cat-${select.value}` : "";
  };
  form.append(select, name, save);
  form.onsubmit = async event => {
    event.preventDefault();
    if (!select.value || busy) return;
    busy = true; save.textContent = "保存中…";
    document.querySelectorAll(".assign button, .assign select").forEach(el => { el.disabled = true; });
    $("error").hidden = true;
    try {
      const response = await fetch("/api/classification/app-rules", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({source: item.source, app: item.app, category: select.value, content: name.hidden ? null : name.value}),
      });
      if (!response.ok) throw new Error(response.status === 422 ? "这个应用不能整体分类，请按网站分类。" : "保存失败，请确认 LeisureLog 正在运行后重试。");
      const data = await response.json();
      $("notice").textContent = `已把「${names[item.app] || item.app}」归入「${categoryLabels[select.value] || select.value}」，以前和以后的记录都会按这个分类统计。`;
      $("notice").hidden = false;
      render(data);
    } catch (error) {
      $("error").textContent = error.message; $("error").hidden = false;
      save.textContent = "保存";
    } finally {
      busy = false;
      document.querySelectorAll(".assign select").forEach(el => { el.disabled = false; el.dispatchEvent(new Event("change")); });
    }
  };
  return form;
}

function appRow(item) {
  const row = node("tr");
  const action = node("td");
  action.append(assignForm(item, row));
  row.append(appCell(item), node("td", duration(item.active_seconds), "num"), node("td", String(item.session_count), "num"), node("td", day(item.last_seen), "num"), action);
  return row;
}

function browserRow(item) {
  const row = node("tr");
  const state = item.sessions_with_url
    ? node("span", `${item.sessions_with_url} / ${item.session_count} 个片段有网址`, "url-state")
    : node("span", "没有网页地址，需要先在活动记录页“数据与设置 → 浏览器接入”里安装扩展", "url-state missing");
  const cell = node("td"); cell.append(state);
  row.append(appCell(item), node("td", duration(item.active_seconds), "num"), node("td", String(item.session_count), "num"), cell);
  return row;
}

function render(data) {
  $("total").textContent = duration(data.total_active_seconds);
  $("app-count").textContent = String(data.app_count);
  $("browser-total").textContent = duration(data.browser_active_seconds);
  const apps = data.apps.filter(item => !item.browser), browsers = data.apps.filter(item => item.browser);
  const major = apps.filter(item => item.active_seconds >= 60), minor = apps.filter(item => item.active_seconds < 60);
  $("apps").replaceChildren(...major.map(appRow));
  $("minor-apps").replaceChildren(...minor.map(appRow));
  $("minor").hidden = !minor.length;
  $("minor-label").textContent = `还有 ${minor.length} 个只出现过不到 1 分钟的应用`;
  $("empty").hidden = apps.length > 0;
  $("browsers").replaceChildren(...browsers.map(browserRow));
  $("browsers-panel").hidden = !browsers.length;
}

async function load() {
  try {
    const response = await fetch("/api/unclassified");
    if (!response.ok) throw new Error();
    render(await response.json());
  } catch {
    $("error").textContent = "读取失败，请确认 LeisureLog 正在运行。"; $("error").hidden = false;
  }
}
load();
