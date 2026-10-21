# 日常使用与维护

[返回首页](../README.md) · [存储与备份](storage.md) · [本轮收尾](stability.md)

## 平时怎么用

在项目目录双击 `start-leisurelog.bat`，打开活动首页。ActivityWatch 需要独立运行；要记录网页明细，浏览器里的 ActivityWatch 扩展也要保持启用。
关闭网页只是关掉查看窗口，后台仍会同步。需要暂停整个服务时用 `stop-leisurelog.bat`，代码更新后用 `restart-leisurelog.bat`。现有登录启动设置不会因这次更新改变。

活动时间来自前台窗口，网页用于补充窗口内容，Playnite 用于游戏资料和识别。网页与游戏资料不会另外添加一份活动时间。
自动识别不确定时保留“未知/待确认”；在活动详情中纠正，并按需要记住规则。用途和项目分别设置，人工选择优先于自动分类。

“插件”页管理随程序提供的两个官方功能。关闭 Playnite 接入或游戏分析会影响游戏识别或相关页面，活动采集、原始历史和人工修正继续保留。当前没有第三方插件安装市场。

## 偶尔看一下什么

- 首页同步状态：最近成功时间是否持续更新。默认每 60 秒尝试一次；电脑休眠、关机和服务退出期间不会执行。
- “存储与备份”：自动备份是否启用、最近检查是否成功、磁盘是否还有空间。
- 重要整理前创建完整备份，把下载的 ZIP 再复制到其他磁盘。默认每 7 天自动备份、保留最近 4 份；手动备份不自动删除。

活动历史按全部年份保存，不按 90 天删除。长期占用仍会增长；原始更新快照可在创建验证备份后按需整理。日志采用轮换，活动数据库本身没有容量上限。不要直接删除正在使用的 `.db-wal` 或 `.db-shm`。

## 没有新记录或网页打不开

| 现象 | 处理 |
|---|---|
| 首页打不开 | 重新运行启动文件，确认 8001 没有被其他服务占用。查看 `data/logs/server.log`，启动失败时再看 `server.err.log`。 |
| ActivityWatch 暂时离线 | 恢复 ActivityWatch 后，LeisureLog 在下次同步重试，从上次成功进度补取来源仍保存的数据。独立备份任务仍可工作。 |
| 有应用、没有网页明细 | 检查浏览器扩展及其与 ActivityWatch 的连接。网页匹配还需要同一设备上的前台浏览器窗口。 |
| 数据库或备份写入失败 | 检查剩余空间和目录权限。写事务失败会回滚，不会把失败批次报告为已保存；恢复空间后等待下次检查或手动重试。 |
| 一份备份显示异常 | 页面会提示并保留文件，自动轮换跳过该文件。先创建新备份，不要把异常文件直接覆盖到主库。 |
| 插件失败或停用 | 在插件页查看原因，检查 Playnite 导出是否有效。核心活动记录不依赖游戏功能成功。 |

脚本部署的 `server.log` 每份约 2 MB，最多保留当前文件和 3 份旧日志，总量通常约 8 MB；单条特别大的日志可能超过阈值。
启动输出 `server.out.log`、`server.err.log` 每次启动覆盖。直接自行运行 Uvicorn 时，需指定 `--log-config config/logging.json` 并先创建 `data/logs/` 才能使用轮换。
桌面安装版仍使用自己的数据路径和已有轮换日志，本轮没有重新制作安装包。

## 从完整备份恢复

工具先校验 ZIP 路径与文件清单、SQLite 完整性/外键、全部表的数据摘要，以及新备份的文件校验和和分类规则。
它只写尚不存在的新目录，不会停服务或替换当前数据库。校验失败不发布恢复目录，源 ZIP 保留。校验和用于发现损坏，不证明来源可信；只恢复自己保管的备份。

在项目目录打开 PowerShell，替换下面两处路径。目标父目录需已存在，`LeisureLog-Recovered` 本身必须不存在：

```powershell
.\.venv\Scripts\python.exe -m leisurelog.recovery "D:\Backups\leisurelog-backup.zip" --destination "D:\LeisureLog-Recovered"
```

结果包含 `data/leisurelog.db`、`config/rules.yaml`、`verification.json`；有插件选择时保存为 `data/plugin-state.json`。
旧包缺少文件校验和时仍核对数据库表摘要；没有插件选择的旧包需另行核对选择。结构不是当前 `0013` 的备份会被拒绝，应先用对应兼容版本在隔离位置迁移。
损坏但原样备份的插件选择仍会保留，运行管理器会拒绝无效配置，需检查后再启用。

先关闭同步，用另一个空闲端口检查恢复结果：

```powershell
$env:LEISURELOG_DATABASE_URL='sqlite:///D:/LeisureLog-Recovered/data/leisurelog.db'
$env:LEISURELOG_RULES_PATH='D:/LeisureLog-Recovered/config/rules.yaml'
$env:LEISURELOG_PLUGIN_STATE_PATH='D:/LeisureLog-Recovered/data/plugin-state.json'
$env:LEISURELOG_AUTO_SYNC_ENABLED='false'
$env:LEISURELOG_AUTO_BACKUP_DAYS='0'
.\.venv\Scripts\python.exe -m uvicorn leisurelog.main:create_app --factory --host 127.0.0.1 --port 8012
```

打开 `http://127.0.0.1:8012/` 检查历史、人工修正、规则、项目和插件选择。按 Ctrl+C 结束检查，关闭这个终端清除临时环境变量。
正式切换前停止原服务并保存最新完整备份，再在项目 `.env` 中指定核对后的数据库、规则和插件选择路径，恢复同步配置后启动。
保留原数据目录；不要在原服务运行时覆盖数据库，也不要把旧 WAL/SHM 文件带到恢复库。
备份之后的记录按同步进度补取；来源已删除的记录无法凭旧备份重新生成。

完整备份不包含 ActivityWatch 数据库、Playnite 游戏库/封面、个人进程绑定、程序包、`.env` 或浏览器里的外观偏好。换电脑时还需单独保存或重新配置。

## 开发暂停期间

继续作为单用户本地应用运行，使用一个服务进程和一个 worker。不要把 8001 直接开放到互联网。
无需经常更新依赖；更新前先备份、阅读版本说明。程序回退与数据恢复是两件事：本轮保持 `0013`，回退程序时继续使用当前数据库，避免用旧备份抹掉后来记录。
本机保留更新前回退点及本轮验证记录，后续开发可以从这个边界开始。
