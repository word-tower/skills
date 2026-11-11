# 查询和正文读取

先读协议，以 /_list 和各操作 schema 为准。本页操作只读，不自动查词标记、调用 LLM、推进阅读进度或打卡。

| 操作 | 权限 / 参数 |
| --- | --- |
| /courses/list | courses:read；query?/limit?/cursor?，返回课程或合集条目 |
| /courses/get | courses:read；course_id，返回课程概要，不含全文 |
| /collections/toc | courses:read；collection_id/limit?/cursor?，按持久化书籍顺序返回章节 |
| /courses/words | courses:read + vocab:read；course_id/limit?/cursor? |
| /vocab/list | vocab:read；list=review 或 familiar，query?/limit?/cursor? |
| /content/read | content:read；course_id/start_offset?/max_chars?/content_version?，续读用 cursor |
| /reading/recent | courses:read；limit?/cursor?，每个书架条目的最新阅读章节 |
| /reading/position | courses:read；course_id?（省略则最近阅读章节）、include_text?、max_chars?（1—5000） |
| /reading/history | courses:read + statistics:read；start_time/end_time、timezone?、course_id?/collection_id?/limit?/cursor? |

课程 ID 从响应取得；合集不是章节，不能把 collection_id 当 course_id。标题可重名，不猜章节号。目录分页按服务器顺序，不用 ID 大小自行排序。

review 是当前复习集合，不是历史查词。课程 new 状态还要看 confirmed：默认生词与用户确认不同。not_studied 不等于用户不认识，unrecognized 表示未可靠识别，familiar 是记录状态不证明永久掌握。首版无“本周查过的全部词”事件接口。

正文仅支持服务端能确认来源的本人导入内容；共享、借阅、来源不明记录不可自动获得外部读取权限。CONTENT_NOT_AVAILABLE 时说明限制，不改走原文/共享源接口。

首次可从 start_offset=0 读 max_chars=2000，响应提供实际 start_offset/end_offset、total_chars、content_version、text、has_more 和 next_cursor。位置为 Unicode code point，非 UTF-8 字节/JS UTF-16/阅读器页码。

继续用 next_cursor，引用已知位置须带对应 content_version。正文修改返回 CONTENT_CHANGED，重新定位，不能拼接不同版本。请求整章可连续翻页，读取已存正文不扣解析/ReadPilot/TTS；单次大小限制不是阻止完整阅读的授权边界。

按用户需要取正文；只读片段不能声称读整本。解释当前章时不预取后文；普通正文接口不保证 ReadPilot 式自动防剧透。首版不提供整本文件导出、OCR、原 EPUB 下载或音频抽取。

生成短文/测验在外部 Agent 完成。用户仅要求生成时不自动导入；明确需要送回词塔且具备导入授权时，先预览报价再自动提交，见导入文档。

## 阅读位置与历史

“最近读什么”用 /reading/recent；它复用已有书架最近阅读时间和章节、课程进度，是当前快照，不能当作某个过去时间的停留位置。last_read_at 为已有阅读提交时间，position_observed_at 是位置采集时间，两者可能不同；不是实时在线状态。未有阅读记录返回空列表，不推断未读过。

“现在停在哪”用 /reading/position。返回章节名、合集名、chapter_number、progress_ratio（0—1）、段落 paragraph_key/paragraph_number 和原文偏移。paragraph_number 按原文换行分段（含空行），不是排版屏码；is_page_fragment=true 表示长段落被分页切开，不能声称是完整段落。locator 是阅读器视口锚点，不证明用户逐字读过，也不代表累计读完的字数。

需要展示段落时传 include_text=true，额外要求 content:read；正文仍受 /content/read 同样的本人导入来源约束。paragraph.text 最多 max_chars 字符，has_more=true 时披露截断，后续以返回的 content_version 和偏移通过 /content/read 获取。text_status=source_restricted/anchor_unavailable/content_changed 时只报告元数据或段落标识，不猜正文、不换内部接口绕过。旧进度没有版本时 anchor_status=unversioned，不保证原文可还原；部署后再次正常保存进度才产生带版本的位置。版本校验以保存时的服务端正文为基础；旧客户端未提供其打开页面时的版本，不能据此证明当时屏幕正文未发生变化。

“昨晚/上周某段时间看了什么”用 /reading/history。先按用户时区把自然语言换成明确的起止时刻；未指定具体钟点时说明采用的范围。start_time/end_time 必须是带 UTC 偏移的 ISO 8601 时间，区间为 [start_time,end_time)，最多 366 天；timezone 是展示时区，默认 Asia/Shanghai，不替代时间字符串中的偏移。支持按 course_id 或 collection_id 筛选，分页保持全部筛选。夏令时按实际偏移处理，不固定每个自然日为 24 小时。

```json
{"api_name":"/reading/recent","limit":10}
```

```json
{"api_name":"/reading/position","include_text":true,"max_chars":2000}
```

```json
{"api_name":"/reading/history","start_time":"2026-10-30T18:00:00+08:00","end_time":"2026-10-31T06:00:00+08:00","timezone":"Asia/Shanghai","limit":50}
```

历史包括两类已有表中的记录：reading_activity 是真实阅读提交的时段，reading_position 是现有保存进度流程追加的位置快照。App 在离开章节/进入后台等现有保存点产生快照，不额外逐段轮询；离线尚未同步、退出前未保存的位置可能缺失。查词事件和 Agent 获取正文不算用户阅读。仅 reading_position 的 position 能回答该记录时刻的段落；reading_activity.position 无锚点时不要拿当前段落补过去。

历史按事件时间倒序，同时间保留不同记录；游标固定本轮查询的数据上限，后来补交的离线记录须重新从第一页查询。历史中标题为当时快照，删除课程后仍可返回本人历史元数据，但 resource_available=false、reader_link=null；不能由此索取已删除正文。

time_basis=client_interval 是带起止时间的阅读时段，与查询范围有交集即返回；interval.overlap_* 只表达时间交集。reported_total_seconds/reported_valid_seconds 始终是整条原始记录的秒数（duration_scope=whole_record），partially_overlaps=true 时不能把整条时长计为查询范围内时长，也不能按比例猜有效时长。time_basis=server_received 的旧数据只知道收到时间，不能还原真实离线阅读时刻。client_observed 表示已有进度的客户端采集时间。不要把两次位置快照的间隔当成阅读耗时。

history_is_complete=false、basis=recorded_events_only：只展示实际已记录的数据，不把空结果说成“那时没阅读”，不补造上线前段落历史，也不声称包含全部阅读。已有活动时段即使早于本版仍可查询；位置历史从部署后的正常进度保存开始累积。不新增学习/听力统计，也不因查询推进阅读进度。
