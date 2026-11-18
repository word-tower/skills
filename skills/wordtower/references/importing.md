# 文本、EPUB 和 YouTube 导入

预览、上传和提交均需服务端开放对应操作及 Token 授权。文本及 YouTube 需要 imports:text，EPUB 需要 imports:epub，App 的「导入课程」统一授予这两项权限。查询状态需要 imports:read，创建导入连接时服务端同时授予状态权限。用户明确要求导入后，在每日次数和解析额度范围内自动提交。

## 导入到手动合集

文章、TXT/Markdown 和 YouTube 视频课程可以导入自己的未分享手动合集。先用 /_list（MCP 客户端也可查看实时工具 schema）确认当前连接开放 /imports/collections 和对应预览的目标字段。服务未开放该能力时，说明无法按指定合集导入，保留目标要求。

- **导入已有合集**。调用 /imports/collections，支持 query、limit 和 cursor。查完相关分页后匹配实际标题或用户指定的 ID。有多个同名项时让用户选；找不到时说明情况。每条预览填写返回的 collection_id（字符串）。
- **新建合集并导入**。仅第一条有效内容的预览填写 new_collection_title。第一条被服务端接受时，同时创建合集并在提交响应中返回 collection_id。剩余条目预览统一填写这个 ID，即使有同名合集也使用本次新建的 ID。
- collection_id 和 new_collection_title 只能二选一。预览的 destination 会回显目标；换目标须重新预览。提交仍只传 preview_id 与 idempotency_key。首条提交结果不明时，重放原请求取得原任务及合集 ID，再继续余下条目。

```json
{"api_name":"/imports/collections","query":"精读文章"}
```

```json
{"api_name":"/imports/preview","title":"An English article","text":"The user-selected passage.","collection_id":"123"}
```

本地文本或字幕文件可给 request.py 加 `--collection-id 123` 或 `--new-collection-title "英语视频"`。由 youtube_subtitles.py 生成的预览 JSON 可直接加入其中一个目标字段，再向网关或 MCP 提交预览。

多篇文章或多个视频按条分别预览、提交和查询状态，按用户给定顺序追加到合集目录。根据当天剩余次数、解析余额和并发限制推进；达到并发上限时先等已接受任务进入终态。汇报每条结果，区分成功、失败、处理中及未提交。目标失效时停止该合集的后续提交，重新核实目标。计划导入失败或部分完成时，由 App 管理需要调整的合集或课程。

EPUB 整书及选章导入沿用书籍合集流程。书籍、分享或图书馆导入的合集，以及正在分享的手动合集，均不可选作本功能的目标。合集删除、移出课程和移动已有课程仍在词塔 App 内操作。

## 文本或 TXT

直接文本使用 /imports/preview，参数 title、text、可选 source_url（只记来源，服务端不抓取）。TXT/Markdown 纯文本文件可用 `python3 scripts/request.py --text 文件路径 --title 标题`；文件必须是 UTF-8，脚本在本地读取并提交正文，不向服务器传本机路径。

```json
{"api_name":"/imports/preview","title":"My vocabulary story","text":"The user-selected passage."}
```

## YouTube 视频与带时间戳字幕

使用 imports:text 导入 YouTube 课程，查询任务使用 imports:read。用户提供视频链接与字幕，或授权 Agent 取得字幕后再导入。

### 只有视频链接时

使用包内脚本获取单视频自带字幕，不依赖第三方 Skill、yt-dlp、FFmpeg 或本地转录；运行需要 Python 3 和可访问 YouTube 的网络。

```sh
python3 scripts/youtube_subtitles.py "https://www.youtube.com/watch?v=aDblEBU41nA" --output ./youtube-lesson
```

脚本先读取视频页，再按需通过 InnerTube 获取原始字幕，默认英文。`--language en-US` 可指定原始语言，`--list` 仅查看可用语言。优先选自动字幕以保留 JSON3 真实词偏移；源字幕没有词时间时只保留段落时间。一次只处理所选视频，不批量处理播放列表。

输出包含 subtitle_file、preview_request、subtitle_count 和 word_timing_available。脚本仅下载字幕、生成本地预览请求，不读取词塔 Key，不提交课程或消耗词塔额度。读取 preview_request 指向的 JSON 后，普通 Skill 执行 `python3 scripts/request.py 实际预览请求路径` 获取服务端预览；MCP 客户端移除 api_name 后调用 `wordtower_imports_youtube_preview`，不向本地脚本传连接表单的 Key。随后按下文规则提交和查询状态。

无字幕、所选语言缺失、登录验证或限流时，说明实际错误，请用户提供已有字幕文件；不伪造字幕、不自动安装依赖或下载音视频。YouTube 接口可能变化，单次成功不代表所有视频均可获取。词塔仍支持直接读取用户已有字幕。

优先获取 YouTube 原始 JSON3 字幕（例如下载工具的 `json3` 字幕格式），保留 `events[].segs[].tOffsetMs`。本地 SRT、VTT、JSON 或 JSON3 字幕可运行：

```sh
python3 scripts/request.py --youtube "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --subtitles lesson.json3 --title "My YouTube lesson"
```

脚本读取 UTF-8 文件，输出预览。SRT/VTT 的时间转换为秒，去掉字幕排版标签。JSON 文件可为字幕数组（每项包含 text、start、duration），或包含 events 的原始 JSON3 对象。JSON3 会保留逐词 segs 的 utf8 和 tOffsetMs，避免先转 SRT/VTT 丢失词时间。用户仅提供 URL 时，先取得实际字幕内容再预览。

结构化请求：

```json
{"api_name":"/imports/youtube/preview","title":"My YouTube lesson","url":"https://youtu.be/dQw4w9WgXcQ","subtitles":[{"text":"Hello world.","start":1.25,"duration":2.0},{"text":"A new lesson.","start":4.0,"duration":2.5}]}
```

start 和 duration 均为秒，可用小数，duration 必须大于 0。字幕需按 start 非递减排列，可保留真实的重叠时间段。保持原视频时间轴，截取片段时仍使用原视频秒数。将每段字幕中的换行合并为空格后计算正文位置。字幕的文字和时间必须对应用户指定视频，缺失时间戳时应取得带时间戳字幕。逐段时间用于同步播放与跳转。只有源字幕带真实词偏移时才保留逐词同步，不按字数均分伪造词时间。结构化字幕可传 segs 数组，每项为 utf8 和 tOffsetMs（相对该字幕起点的毫秒数），拼接文字需与 text 一致，偏移非负、有序且小于 duration × 1000。

预览返回 media_type=youtube、规范化 source_url、subtitle_count、word_timing_count 和额度报价。word_timing_count 大于 0 表示生成了逐词边界；为 0 时明确告知只有字幕段落时间。继续使用 /imports/text，传 preview_id 和同一个 idempotency_key 提交，再通过 /imports/status 查询。kind=text 表示沿用文本导入的权限、限额和处理流程，课程会保留 YouTube 链接和字幕时间轴。每个视频课程计一次文件导入，解析费用按规范化字幕正文字符数计算。服务端记录链接和已提交字幕，不主动下载视频或抓取字幕。


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

导入前通过 /account/capabilities 的 import_usage 查询 limit、used、remaining、timezone 与 resets_at，并结合 agent_limits 和 text_parse 余额判断是否可提交。限额可能动态调整，每次以最新服务端回包为准。所有 Key、文本、EPUB 与 YouTube 共用账号导入次数，按回包中的 timezone 和 resets_at 展示重置时间。一次文本、EPUB 或 YouTube 任务计一次，章节数不影响次数。服务端接受的新任务（包括后续失败或取消的任务）均计数，同一幂等请求重放不重复计数。

提交前生成并保存随机 idempotency_key（例如 UUID），与 preview_id 一同请求：

```json
{"api_name":"/imports/text","preview_id":"实际预览ID","idempotency_key":"实际随机幂等键"}
```

EPUB 用 /imports/epub，参数相同。不再带正文/对象名。网络超时用原 preview_id/key 重放找回 job，不换键。同一预览不能消费两次。

## 状态

202 仅表示接受。用 /imports/status 的 job_id 查询，遵循 poll_after_seconds。本次最多等约 2 分钟，仍处理中则保留 job ID，不能编造完成百分比。

queued/running 为处理中，succeeded 才成功；failed/cancelled 是终态。EPUB 可能有部分章节成功，报告 completed_chapters、billed_chars 和具体状态，不把部分结果称为完整成功。服务端只结算已成功处理的部分，其余预留释放。

reader_link 只使用回包已有链接，未配置前端时可能为 null，此时报告课程/合集 ID，不自行拼链接。课程私人可见，默认不启用学习计划。失败后重放同键不会重新执行；用户明确要重做时重新预览再提交，并占用新的一次文件额度。
