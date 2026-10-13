# Windows 本地安装版

0.4.0b1 是首次面向其他用户的 Windows x64 试用安装版。记录与分析模块继续使用模块化单体；`desktop/` 负责启动、用户路径、数据库准备、单实例、本机访问保护、首次引导和系统托盘。数据库结构保持 0013。

## 普通用户怎么使用

1. 运行 `LeisureLog-0.4.0b1-Windows-x64-Setup.exe`，按向导安装。
2. 从桌面或开始菜单打开 LeisureLog。程序自动准备个人数据库并打开浏览器。
3. 按引导安装并启动官方 [ActivityWatch](https://docs.activitywatch.net/en/latest/getting-started.html)。已有安装会直接检测；尚未就绪也可完成设置，后台稍后重试。
4. 阅读本机信息说明，选择首次导入最近 1 小时或 24 小时，确认后开启同步。确认前自动同步关闭，手动导入接口也不能绕过引导。
5. 通过系统托盘打开活动记录、本机设置、停止/开启自动同步、打开个人数据目录或退出程序。关闭网页不等于退出后台。

浏览器 Web Watcher 与 Playnite 10 均为可选项。首次设置页生成的 Playnite 扩展使用当前用户自己的导出路径；不会包含开发者的游戏资料。不支持 Playnite 11 SDK。

停止自动同步控制 LeisureLog 的导入，不停止独立运行的 ActivityWatch。删除 LeisureLog 的数据库也不会删除 ActivityWatch 的原始记录。

本版本默认不配置开机启动。当前开发版已有的启动脚本和启动项保持原样。

## 数据位置与升级

- 默认程序目录：`%LOCALAPPDATA%\Programs\LeisureLog`。
- 默认个人数据目录：`%LOCALAPPDATA%\LeisureLog`，其中 `data/` 保存 SQLite 和本机导出，`config/` 保存用户规则与桌面设置，`backups/` 保存备份，`logs/` 保存运行日志。
- 桌面入口不读取工作目录 `.env` 或继承的开发环境配置。每个 Windows 用户有独立数据库。
- 默认使用 8001；被占用时保留其他程序并选择可用的本机端口，记住该端口以便后续启动。重复点击桌面图标打开已有实例，不重复启动采集任务。
- 默认分类文件只在首次使用时复制，不覆盖用户修改。
- 数据库结构升级前使用 SQLite 在线备份，验证完整性后执行 Alembic 迁移；失败时恢复旧库。遇到未知/更高的数据库版本停止启动，不能偷偷降级。
- 安装、升级和卸载会检查后台是否退出。更新时先在托盘选择“退出 LeisureLog”，再运行安装程序。
- 卸载只处理安装目录内的程序文件，保留独立的个人数据目录。历史记录没有自动到期删除机制；每周最多保留四份自动备份的策略不等于删除活动历史。

源码运行目录中的 `data/` 记录不会自动复制到安装版。若首次打开看到空记录，应先核对数据位置；原记录仍在旧目录。历史数据搬迁应独立备份后再进行。

## 独立文件夹版本

另提供 `LeisureLog-0.4.0b1-Windows-x64-Standalone.zip`。完整解压后双击其中的 `LeisureLog.exe`，必须保留旁边的 `_internal/` 文件夹。它仍使用上述个人数据目录，不默认把个人记录放在解压位置。

测试时可指定隔离目录：

```powershell
.\LeisureLog.exe --data-dir 'D:\LeisureLog-Test' --no-browser --no-tray
.\LeisureLog.exe --data-dir 'D:\LeisureLog-Test' --stop
```

`--port` 可指定端口，0 表示选择空闲端口。`--activitywatch-url` 仅接受本机 HTTP 地址。以上开关主要用于诊断；普通用户使用桌面图标即可。

## 开发者构建

需要 Windows x64、Python 3.11+，以及制作安装包时使用的 Inno Setup 6.5+。构建环境与正式运行环境应分开；当前验证构建使用 Python 3.13.9、PyInstaller 6.22.3、pystray 0.19.5、Pillow 12.3.0、Inno Setup 6.7.3。

```powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -e '.[desktop,packaging,dev]'
.\.build-venv\Scripts\python.exe scripts/build_desktop.py --iscc 'C:\Path\To\Inno Setup\ISCC.exe'
```

`requirements-lock.txt` 是现有业务依赖的已验证精确版本；`packaging/requirements-build.txt` 记录本次额外打包依赖。先安装这些锁定版本，再用 `--no-deps` 安装项目，可重建本次依赖组合。

构建脚本显式收集网页、皮肤、通用默认规则、迁移文件和 Playnite 扩展源码。不会收集 `.env`、数据库、游戏资料、运行日志、测试用户设置和历史截图；默认 Playnite 进程绑定为空。产物附带依赖许可说明、文件清单和 SHA256 校验文件。

中文安装翻译来自 [Inno Setup 官方翻译页面](https://jrsoftware.org/files/istrans/) 指向的 [ChineseSimplified.isl](https://github.com/jrsoftware/issrc/blob/main/Files/Languages/ChineseSimplified.isl)，保留原作者信息。本次文件 Git blob 为 `d0d44258f51aa3127fc0d1167a7c8be328a9bdcf`。Inno Setup 的下载和适用许可按其官方规定处理。

## 验证方法与发布边界

`tests/test_desktop.py` 验证隔离路径、中文/空格/百分号目录、规则保留、旧库升级、迁移失败恢复、未知版本拒绝、单实例、端口冲突、授权引导与请求来源保护。

`scripts/smoke_desktop.py` 启动真正的打包 exe，通过合成 ActivityWatch HTTP 服务验证页面资源、数据导入、人工纠错、重复启动、重启和正常退出。测试子进程 PATH 只包含 Windows 系统目录，并使用不同于安装目录的工作目录及个人数据目录。

```powershell
python scripts/smoke_desktop.py --exe 'dist\LeisureLog\LeisureLog.exe' --workspace 'outputs\desktop-check-unique'
```

首次使用界面还需通过浏览器验证勾选控制、连接提示和桌面/窄屏布局。安装程序需验证实际安装、重新安装、卸载及数据保留，不能仅以编译成功作为发布依据。

当前为本机验证的试用版本，尚未完成独立干净 Windows 10/11 机器、普通用户账户和不同显示设置的兼容性验证。尚无发布者代码签名、自动更新、自动安装 ActivityWatch 或账号/云端同步。正式发布前仍需补齐实机试用、项目发布许可与来源说明核对、签名和 GitHub Release。
