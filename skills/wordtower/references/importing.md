# 文本、EPUB 和 YouTube 导入

预览、上传和提交需要 Pro 或 Ultra。文本需要 imports:text，EPUB 需要 imports:epub。查询状态需要 imports:read，创建导入连接时服务端同时授予状态权限，降级后仍可查询已提交任务。用户明确要求导入后，在权限、文件数和解析额度范围内自动提交，无需账户批准或确认页。

## 文本或 TXT

直接文本使用 /imports/preview，参数 title、text、可选 source_url（只记来源，服务端不抓取）。TXT/Markdown 纯文本文件可用 `python3 scripts/request.py --text 文件路径 --title 标题`；文件必须是 UTF-8，脚本在本地读取并提交正文，不向服务器传本机路径。

```json
{"api_name":"/imports/preview","title":"My vocabulary story","text":"The user-selected passage."}
```

## YouTube 视频与带时间戳字幕

Pro 或 Ultra 使用 imports:text 导入 YouTube 课程，查询任务使用 imports:read。用户提供视频链接与字幕，或授权 Agent 取得字幕后再导入。

本地 SRT、VTT 或 JSON 字幕可运行：

```sh
python3 scripts/request.py --youtube "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --subtitles lesson.vtt --title "My YouTube lesson"
```

脚本读取 UTF-8 文件，输出预览。SRT/VTT 的时间转换为秒，去掉字幕排版标签。JSON 文件为字幕数组，每项包含 text、start、duration。用户仅提供 URL 时，先取得实际字幕内容再预览。

结构化请求：

```json
{"api_name":"/imports/youtube/preview","title":"My YouTube lesson","url":"https://youtu.be/dQw4w9WgXcQ","subtitles":[{"text":"Hello world.","start":1.25,"duration":2.0},{"text":"A new lesson.","start":4.0,"duration":2.5}]}
```

start 和 duration 均为秒，可用小数，duration 必须大于 0。字幕需按 start 非递减排列，可保留真实的重叠时间段。保持原视频时间轴，截取片段时仍使用原视频秒数。将每段字幕中的换行合并为空格后计算正文位置。字幕的文字和时间必须对应用户指定视频，缺失时间戳时应取得带时间戳字幕。逐段时间用于同步播放与跳转，不能声称包含逐词对齐。

预览返回 media_type=youtube、规范化 source_url、subtitle_count 和额度报价。继续使用 /imports/text，传 preview_id 和同一个 idempotency_key 提交，再通过 /imports/status 查询。kind=text 表示沿用文本导入的权限、限额和处理流程，课程会保留 YouTube 链接和字幕时间轴。每个视频课程计一次文件导入，解析费用按规范化字幕正文字符数计算。服务端记录链接和已提交字幕，不主动下载视频或抓取字幕。


## EPUB 文件

用户只要某些章节或某类题材时，先按 [EPUB 选章](epub-selection.md) 在本地生成选章版，再上传选章版文件；不得把原整本先上传/导入后删除不需要的章节。

运行 `python3 scripts/request.py --epub 文件路径 --title 标题`。脚本计算 SHA-256/大小，调用 /imports/upload-url，将文件 PUT 到回包中的 COS 单对象地址，再用 upload_id 调 /imports/epub/preview，最后只输出预览。PUT 不带 Words Key，不跟随重定向。

手动接口顺序：

1. /imports/upload-url：file_name（.epub）、size_bytes、sha256（小写）。
2. 按 method/headers 上传到 upload_url；不能自行换对象名。签名有效 10 分钟，文件上限 20 MiB。
3. /imports/epub/preview：upload_id、可选 title。

服务端验证、冻结文件并按章节解析。正文总量按当前 epub_chars 限制和共用额度执行。压缩包加密/异常条目/路径/实体会被拒绝；不能改扩展名绕过。不支持服务器下载任意 EPUB URL。

## 自动提交与次数

先读取服务端预览的标题、章节数、normalized_chars、quote 和 quota，简要说明实际导入内容与预计解析额度。字符不是英文单词或 LLM token；费用以服务端预览为准。confirmation_required=false、confirmation_url=null 表示无需确认页面；approved 是旧版显式批准的兼容字段，即使为 false 也不影响新版自动提交。不要调用账户批准接口，也不要向用户索取登录 JWT。

用户要求“导入”就继续提交，不再重复询问是否确认。用户只要求预览、分析、比较或筛选方案时停在预览；只有范围不清、额度不足或需要改变内容/范围时说明问题。改正文/标题/来源必须新建预览；预览 15 分钟有效，跨月失效。只生成预览不建课、不占解析额度、不占每日文件次数。

首次使用 /account/capabilities 的 import_usage 查看 limit、used、remaining、timezone 与 resets_at；agent_limits.daily_imports 是当前套餐的上限。所有 Key、文本与 EPUB 共用账号每日计数，当前三档默认均为 10，可由服务端分别调整。按 Asia/Shanghai 自然日重置，resets_at 是 UTC 时间。一次文本提交或一个 EPUB 任务计 1 个文件，章节数不影响次数。服务端接受的新任务（包括后续失败/取消的任务）均占 1 次；同一幂等请求重放不重复计数。不能通过换 Key、拆分任务或更换幂等键绕过限制。

提交前生成并保存随机 idempotency_key（例如 UUID），与 preview_id 一同请求：

```json
{"api_name":"/imports/text","preview_id":"实际预览ID","idempotency_key":"实际随机幂等键"}
```

EPUB 用 /imports/epub，参数相同。不再带正文/对象名。网络超时用原 preview_id/key 重放找回 job，不换键。同一预览不能消费两次。

## 状态

202 仅表示接受。用 /imports/status 的 job_id 查询，遵循 poll_after_seconds。本次最多等约 2 分钟，仍处理中则保留 job ID，不能编造完成百分比。

queued/running 为处理中，succeeded 才成功；failed/cancelled 是终态。EPUB 可能有部分章节成功，报告 completed_chapters、billed_chars 和具体状态，不把部分结果称为完整成功。服务端只结算已成功处理的部分，其余预留释放。

reader_link 只使用回包已有链接，未配置前端时可能为 null，此时报告课程/合集 ID，不自行拼链接。课程私人可见，默认不启用学习计划。失败后重放同键不会重新执行；用户明确要重做时重新预览再提交，并占用新的一次文件额度。
