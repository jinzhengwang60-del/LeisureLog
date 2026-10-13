# 存储、备份与恢复

[返回项目首页](../README.md)

## 本地存储与备份

主页“存储与备份”查看全部日期的数据数量、最早/最新记录时间、数据库绝对路径、主数据库/WAL/SHM 的逻辑文件大小及备份目录占用。WAL 是尚未回收的写入日志，主文件大小不能单独代表当前占用；占用会随写入和 checkpoint 改变，不是逐日增长测量。全部日期的活动历史继续保留；可手动整理已被更新版本替代的原始快照，不按日期删除活动，未设置历史保留年限或容量上限；自动备份默认每 7 天创建一份，只保留最近 4 份自动备份。

点击“创建本地备份”使用 SQLite online backup 生成一致快照，无须停止自动同步。随后将快照恢复到独立临时数据库，检查 integrity_check、foreign_key_check、schema、数据库迁移版本和全部业务表的行数与内容哈希。只有验证成功才发布备份文件。失败不会替换或修改运行数据库，未完成输出会清理；同一应用进程内重复备份返回 409。当前仍使用单个 worker。

默认备份位置为数据库旁的 `backups/`。可用 `LEISURELOG_BACKUP_DIR` 指定其他位置。每份保存 `.db` 快照、`.rules.yaml` 配置副本、`.json` 验证报告和包含三者的 `.zip`；不保存账号凭据或整个环境配置。页面下载完整 ZIP，包含：

- `leisurelog.db`：原始快照、ActivityEvent/IdleEvent/Session、人工分类、用户识别规则、同步进度和迁移版本。
- `config/rules.yaml`：配置分类器规则。用户通过页面保存的规则已经在数据库内。
- `verification.json`：恢复验证记录和表数据摘要。

备份覆盖 LeisureLog 已导入的数据，不包含 ActivityWatch 自己的数据库或 LeisureLog 项目程序。备份增加硬盘占用；自动备份按配置轮换，手动备份不会被自动删除。默认同盘副本不能应对整块硬盘损坏，可将 ZIP 复制到其他磁盘。界面不会覆盖当前数据库，暂未提供一键原地恢复。

### 恢复到独立位置

1. 将完整 ZIP 解压到一个新的目录，例如 `D:/LeisureLogRestore/2026-09-30/`，避免覆盖现有数据。
2. 使用当前版本的 LeisureLog，在项目目录设置 `LEISURELOG_DATABASE_URL=sqlite:///D:/LeisureLogRestore/2026-09-30/leisurelog.db`，`LEISURELOG_RULES_PATH=D:/LeisureLogRestore/2026-09-30/config/rules.yaml`，先设置 `LEISURELOG_AUTO_SYNC_ENABLED=false`。
3. 在该配置下执行 `alembic upgrade head`，再用空闲端口启动服务。确认健康检查、活动记录、人工分类和识别规则；使用不同数据库路径，不复制到正在运行的主库旁，也不带入旧库 WAL/SHM 文件。
4. 恢复核对成功后再决定切换主服务和开启同步；恢复后的同步进度以备份时刻为准，之后会补取 ActivityWatch 仍保留的活动。

新增 API：`GET /api/storage` 查看占用与备份列表，`POST /api/storage/backups` 创建并验证，`GET /api/storage/backups/{name}/archive` 下载完整 ZIP，`GET /api/storage/backups/{name}/download` 下载单独数据库。下载名严格限定为服务生成的文件名。

实现边界：StorageService 依赖纯 domain 的 StorageStore 接口；SQLiteStorage 负责数据库和本地文件，API 负责入口及下载响应。没有数据库结构变更。本地存储仍是当前主存储，云端同步未实现。

## 原始更新快照整理与空间回收

“存储与备份”页面显示可整理的原始更新快照数，并提供“备份并整理旧快照”。仅移除属于仍存在活动、且不被任何 ActivityEvent/IdleEvent 当前引用的原始版本。每个活动的最新原始记录、所有日期的统一活动与 Session、人工分类、识别规则、同步进度保持不变；孤立原始数据保守保留。不按日期设置期限，不删除往年的活动。

执行顺序：创建完整备份并独立恢复验证 → 从该备份取得可整理 ID → 获取 SQLite 写锁，重新检查引用并在单事务中删除 → 尝试 VACUUM 和 WAL checkpoint 回收空间。仅删除存在于已验证备份的候选版本，备份后新产生的旧版本留到下次。备份失败不开始删除；删除失败整体回滚。VACUUM 在删除提交后独立执行，失败时保留整理结果并提示空间回收延后，不能把整理完成与空间回收完成混为一谈。

整理后的自动同步仍保存更新快照，用户可以按需再次整理，尚未定时自动整理。整理移除了运行库的部分原始更新历史，无法在运行库中逐版本回放这些旧修订；这些版本仍保存在整理前备份中。导入数据源若回到旧版本，Adapter/Repository 会重新保存对应快照。

每次整理会增加一份完整备份；原库变小不代表本地总占用一定减少。页面分别显示运行库与备份目录占用；整理产生的手动备份不会被自动轮换删除。VACUUM 可能短暂阻塞写入，且需要额外临时空间，适用于当前本地小数据量；备份操作与整理在单进程内互斥。新增 `POST /api/storage/compact`，返回整理数量、备份、操作前后文件大小及回收状态。没有待整理版本时不创建新备份。

## 自动备份配置

`LEISURELOG_AUTO_BACKUP_DAYS` 默认 7，设为 0 时关闭自动备份；
`LEISURELOG_AUTO_BACKUP_KEEP` 默认 4，只限制自动备份的数量。
`LEISURELOG_AUTO_BACKUP_CHECK_SECONDS` 默认 3600，控制检查间隔，允许 60–86400 秒。
最新的手动或自动备份达到配置间隔后才会创建新自动备份，因此新手动备份也会推迟下一次自动备份。

v0.3 使用独立的备份任务，启动时检查一次，此后默认每小时检查；关闭同步或 ActivityWatch 离线不影响备份检查。LeisureLog 未运行时不会执行任务，下次启动时检查是否到期。页面展示实际配置、最近检查时间和备份任务错误。备份失败独立重试，不阻断活动同步，也不删除正式历史记录。
