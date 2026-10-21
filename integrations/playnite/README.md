# Playnite 本地游戏库连接

这份扩展适用于本机 Playnite 10 / SDK PowerShell 5.1 接口。扩展只读取游戏资料，通过官方 SDK 获取名称、安装状态、目录、类型与标签，以及启动动作中的文件路径，再原子写入 LeisureLog 的本地 JSON 文件。不修改 Playnite 游戏库，不执行游戏启动动作，不联网，不导出账号、凭据或浏览记录。Playnite 11 的新接口需要另外实现 Adapter。

## 安装与使用

安装包按下方命令生成到 `dist/LeisureLog-Playnite.pext`，包内 settings.json 指定本地 JSON 导出位置。默认使用项目的 `data/playnite-library.json`；使用其他位置时，需要同时调整 LeisureLog 的导入路径。导入的条目数和可识别游戏数取决于使用者自己的游戏库、安装状态和进程配置，公开源码不包含游戏库导出或个人进程绑定。

如需重新安装，打开包后由 Playnite 安装；确认提示并按 Playnite 要求重启。启动时会导出资料。也可在 Playnite 主菜单 → 扩展 → LeisureLog 点击“同步游戏资料到 LeisureLog”。在 LeisureLog 首页点击“Playnite 游戏库”查看结果，或者等待下一轮每分钟同步。手动修改条目后需执行菜单同步；库更新、程序启动和完整退出也会触发导出。关闭窗口至托盘不算退出。

扩展支持菜单导出、程序启动与退出导出、游戏库更新后导出；LeisureLog 在后续同步中读取完整文件。重复读取相同资料不应新增源快照。接入后请在自己的环境中核对导出路径、导入状态和识别依据；库中存在条目或进程绑定，不代表已经采集到实际游玩记录。SDK 调用环境需要能够访问脚本提供的辅助函数。

## 重新打包

从项目根目录运行：

```powershell
.venv/Scripts/python.exe integrations/playnite/build_package.py
```

更换项目位置时，给打包命令添加 `--export-path` 指定绝对路径，并将 LeisureLog 的 `LEISURELOG_PLAYNITE_EXPORT_PATH` 设置为同一位置。源码只包含 SDK 的读取与文件导出操作；安装包内的脚本带 UTF-8 BOM，保证 Windows PowerShell 5.1 正确读取中文。

## 分类边界

游戏库本身不产生游玩时间，也不把 Playnite/Steam 的累计时间加进 ActivityWatch 时长，避免重复统计。只有前台进程匹配的记录进入游戏分类。默认只识别已安装游戏；没有明确的文件启动动作时，显示“待补充游戏进程”。相同进程匹配多款游戏时不猜测。

对于通过启动器进入或 SDK 没有提供文件启动动作的游戏，在 `config/playnite-processes.yaml` 配置真实游戏进程。公开源码提供空绑定模板，请根据自己的实际安装与前台窗口添加配置；能够直接取得 SDK 文件路径的游戏无需重复补充。共享的 javaw.exe、Shipping 等进程需要附加能区分游戏的窗口标题条件，不能只凭通用进程名认定是哪款游戏，无法满足条件时保持未识别。配置优先级低于人工覆盖、记住的规则和 YAML 分类规则。未安装条目可查看，但不用于识别。

新增游戏、安装版本改变或 Playnite 名称改变时，需要重新检查配置。进程绑定本身不代表已经验证真实游玩，应结合自己的前台窗口记录核对实际标题与进程；修改绑定不会启动游戏或修改 Playnite 条目。

Playnite 库删除不会删除已保存的活动记录或源快照；下一次成功导入会更新当前匹配目录，并重建自动分类。人工纠错继续保留。名称变化也会使按游戏名称绑定的特殊进程需要同步修改。确认游戏平台来源需要对应专用字段，不能把公开 Steam 资料链接当成安装来源。

接口依据：[Playnite 脚本接口](https://api.playnite.link/docs/tutorials/extensions/scripting.html)、[游戏库接口](https://api.playnite.link/docs/tutorials/extensions/library.html)、[事件接口](https://api.playnite.link/docs/tutorials/extensions/events.html)。
