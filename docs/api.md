# 基础接口索引

[返回项目首页](../README.md)

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /health | 数据库迁移状态及应用版本，当前 0012 / 0.2.0 |
| POST | /api/sync/activitywatch | 拉取指定时间窗口并处理 |
| GET | /api/sync/status | 自动同步运行状态及最近结果 |
| GET | /api/events | 统一事件，limit / offset 分页 |
| GET | /api/idle-events | AFK 状态记录，limit / offset 分页 |
| GET | /api/sessions | 合并结果，limit / offset 分页 |
| PUT / DELETE | /api/events/{id}/override | 设置 / 删除人工分类 |
| PUT / DELETE | /api/events/overrides | 批量设置 / 删除人工分类；event_ids，PUT 另含 category / content / tags，可选 remember_scope |
| GET | /api/classification/rules | 查看已记住的规则 |
| DELETE | /api/classification/rules/{id} | 删除规则并重建自动分类 |
| POST | /api/reprocess | 对所有统一事件重新分类、合并 |
| GET | /api/games/playnite | 游戏库接入状态、游戏列表和自动识别依据 |
| POST | /api/games/playnite/import | 导入配置的本地 SDK 导出文件，事务内更新目录并重新分类 |
| GET | /api/stats/summary | 基础分类记录时长汇总，附统计口径 |
| GET | /api/dashboard | 北京时间 day、app、category、purpose、project_id、query 筛选；limit / offset；返回当天汇总和列表 |
| GET | /api/dashboard/ribbon | 与首页列表一致的筛选，时间带 |
| GET | /api/statistics | start/end/granularity，支持 purpose/project_id；全部活动的日期、类型、用途、项目汇总 |
| GET | /api/statistics/hours | 相同范围及用途/项目筛选的小时分布，最多展示最近 31 天 |
| GET | /api/statistics/export | 当前范围和筛选的每日/月度 CSV，UTF-8 BOM，不含窗口标题 |
| GET | /api/activity-context/options | 用途字典与项目元数据（包括归档） |
| PUT / DELETE | /api/events/context | 独立用途与项目的批量人工设置/恢复，1–1000 个 event_ids |
| GET | /api/activity-context/rules | 已记住的归属规则 |
| DELETE | /api/activity-context/rules/{id} | 删除归属规则并重处理，人工归属保留 |
| GET | /api/activity-context/pending | 日期范围内的用途待确认分组，支持搜索与分页 |
| GET | /api/activity-context/pending/events | 指定来源、应用及网站分组的来源记录，分页最多 1000 条 |
| POST | /api/activity-context/preview | 只读规则影响预览、样例与预览令牌 |
| GET | /api/events/{id}/context/explanation | 用途/项目来源与匹配规则 |
| GET | /api/activity-context/changes | 分页读取 v0.3 开始保存的可撤销修改 |
| POST | /api/activity-context/changes/{id}/undo | 撤销归属或规则操作，过期/冲突返回 409 |
| GET / POST | /api/projects | 查询日期范围项目报告 / 新建项目 |
| GET / PUT | /api/projects/{id} | start/end 必填的项目详情 / 修改名称、说明、颜色、归档状态 |
| GET | /api/sessions/{id}/details | 必填 day，查看当天活动片段的窗口与 AFK 状态依据 |

输入错误返回 422；不存在的覆盖目标返回 404；过期的规则预览、冲突或已完成的撤销返回 409；上游不可达、无效响应或无效 bucket 返回 502；未迁移的健康检查返回 503。事件/Session 响应含 classification 与时间字段，Swagger 展示输入结构。

v0.2 的事件/Session 还包含独立 `context`，字段是 `purpose`、`project_id`、`purpose_origin`、`project_origin`。归属 PUT 只修改请求中明确出现的字段；省略字段保持原值，`purpose: null` 恢复自动用途，`project_id: null` 人工指定未关联。可选 `remember_scope` 为 app/title/title_contains/url/domain；title_contains 另需 `match_text`。不同应用的批量选择可以修改本次归属，记为一个规则时必须满足同一匹配条件。

用途筛选允许 work/study/create/communication/leisure/system/other/unknown，空值表示全部。项目筛选使用项目 ID，`none` 表示未关联，空值表示全部。项目 PUT 必须包含名称，其余未发送字段保持原值；可选 `goal_seconds` 为正数或 `null`。没有 DELETE 项目接口。详情及范围查询最多 3660 天。

v0.3 网页保存自动归属规则时先预览，再通过归属 PUT 携带 `preview_token`。令牌匹配当前影响结果后才开始写入。成功的归属、恢复及删除规则操作返回可撤销的 `change_id`，没有实际变更时为 `null`；旧 API 客户端仍可以省略预览令牌。项目报告同时包含当前范围活动时间、全部历史投入和可选目标进度，说明见 [待确认与项目目标](confirmation.md)。

## 完整接口文档

服务启动后打开 [本机交互接口文档](http://127.0.0.1:8001/docs)。它由当前代码生成，包含每周回顾、重复条目合并、存储与备份等全部接口。
具体功能的接口与参数也记录在 [功能说明](features.md) 和 [存储说明](storage.md) 中。
