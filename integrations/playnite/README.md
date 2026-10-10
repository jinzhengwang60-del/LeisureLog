# Playnite 本地游戏库连接

这份扩展适用于本机 Playnite 10 / SDK PowerShell 5.1 接口。扩展只读取游戏资料，通过官方 SDK 获取名称、安装状态、目录、类型与标签，以及启动动作中的文件路径，再原子写入 LeisureLog 的本地 JSON 文件。不修改 Playnite 游戏库，不执行游戏启动动作，不联网，不导出账号、凭据或浏览记录。Playnite 11 的新接口需要另外实现 Adapter。

## 当前接入状态

2026-10-02 用户已授权安装，扩展已在本机 Playnite 10.62 中运行。当前导出与 LeisureLog 中均有 251 个条目，12 个已安装；补齐进程配置后，10 款游戏具备识别依据，另两个安装条目是 OBS Studio 与 Wallpaper Engine，不参与游戏识别。数量会随 Playnite 库更新变化。ActivityWatch 自动同步正常。安装包按下方命令重新生成到 `dist/LeisureLog-Playnite.pext`，包内 settings.json 指向此项目的 `data/playnite-library.json`。旧打包产物已清理，已安装的扩展不受影响。

如需重新安装，打开包后由 Playnite 安装；确认提示并按 Playnite 要求重启。启动时会导出资料。也可在 Playnite 主菜单 → 扩展 → LeisureLog 点击“同步游戏资料到 LeisureLog”。在 LeisureLog 首页点击“Playnite 游戏库”查看结果，或者等待下一轮每分钟同步。手动修改条目后需执行菜单同步；库更新、程序启动和完整退出也会触发导出。关闭窗口至托盘不算退出。

真实联调已验证菜单导出、启动/退出导出、自动库更新后后台导入以及重复读取不新增快照；真实游戏运行记录尚未验证。SDK 调用环境要求将辅助函数一并导出，脚本已修正并重新打包。

## 重新打包

从项目根目录运行：

```powershell
.venv/Scripts/python.exe integrations/playnite/build_package.py
```

更换项目位置时，给打包命令添加 `--export-path` 指定绝对路径，并将 LeisureLog 的 `LEISURELOG_PLAYNITE_EXPORT_PATH` 设置为同一位置。源码只包含 SDK 的读取与文件导出操作；安装包内的脚本带 UTF-8 BOM，保证 Windows PowerShell 5.1 正确读取中文。

## 分类边界

游戏库本身不产生游玩时间，也不把 Playnite/Steam 的累计时间加进 ActivityWatch 时长，避免重复统计。只有前台进程匹配的记录进入游戏分类。默认只识别已安装游戏；没有明确的文件启动动作时，显示“待补充游戏进程”。相同进程匹配多款游戏时不猜测。

对于通过启动器进入或 SDK 没有提供文件启动动作的游戏，在 `config/playnite-processes.yaml` 配置真实游戏进程。已为绝区零、英雄联盟、Minecraft、丝之歌、杀戮尖塔2、你嫂子、边缘世界及鸣潮补充配置；原神和棕色尘埃2直接使用 SDK 文件路径。Minecraft 的 javaw.exe 要求标题含 Minecraft；鸣潮的 Client-Win64-Shipping.exe 要求标题含 Wuthering Waves 或鸣潮。通用进程不能只凭进程名认定是哪款游戏，无法满足条件时保持未识别。配置优先级低于人工覆盖、记住的规则和 YAML 分类规则。未安装条目可查看，但不用于识别。

补充的五个程序均已在各自实际安装目录核对；不遍历其他目录、不启动游戏、不修改 Playnite 条目。规则已导入正式数据库并在页面核对，但仍需正常游玩时的窗口记录验证实际标题与进程。将来新增游戏、安装版本改变或 Playnite 名称改变时，需要重新检查配置。

Playnite 库删除不会删除已保存的活动记录或源快照；下一次成功导入会更新当前匹配目录，并重建自动分类。人工纠错继续保留。名称变化也会使按游戏名称绑定的特殊进程需要同步修改。确认游戏平台来源需要对应专用字段，不能把公开 Steam 资料链接当成安装来源。

接口依据：[Playnite 脚本接口](https://api.playnite.link/docs/tutorials/extensions/scripting.html)、[游戏库接口](https://api.playnite.link/docs/tutorials/extensions/library.html)、[事件接口](https://api.playnite.link/docs/tutorials/extensions/events.html)。
