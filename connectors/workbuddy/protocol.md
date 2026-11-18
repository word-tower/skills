# MCP 调用与本地脚本

业务请求通过已连接的 `wordtower_` MCP 工具执行，凭证由 WorkBuddy 的 Key 表单管理。共享文档中的 API 名转换为工具名，例如 `/imports/upload-url` 对应 `wordtower_imports_upload_url`，`/annotations/export` 对应 `wordtower_annotations_export`，`/_list` 对应 `wordtower__list`。转换规则为加上 `wordtower_` 前缀、去掉开头 `/`、将其余 `/` 和 `-` 替换为 `_`。实际可用操作与参数以本次工具 schema 为准。

共享文档中的 JSON 请求用于说明业务字段。调用工具时移除 `api_name`、`skill_version`，只传业务参数，不传 `user_id`。Key 不进入工具参数或本地文件。响应使用 MCP 返回的 `structuredContent`，其中 data/error/request_id 与网关信封一致，先检查 isError 和 error。功能、权限、额度以实时能力查询为准。

`request.py` 的 `--prepare-only` 模式只读取本地文件并生成请求参数，不读取 Key 或调用业务接口。生成 JSON 中的 api_name 用于选择对应 MCP 工具，其余字段作为工具参数。本包保留普通 Skill 的联网脚本兼容用法，但 WorkBuddy 表单凭证不保证传给本地进程，连接器使用下述离线模式配合 MCP。

## 文本和字幕

只有单视频链接时，按[导入文档](importing.md#只有视频链接时)运行 youtube_subtitles.py。读取输出 preview_request 对应的 JSON，移除 api_name 后调用 wordtower_imports_youtube_preview。字幕获取不需要词塔 Key，不调用本地 request.py 的联网模式。

```sh
python3 scripts/request.py --text article.txt --title "My lesson" --prepare-only
python3 scripts/request.py --youtube "https://youtu.be/dQw4w9WgXcQ" --subtitles lesson.json3 --title "My video" --prepare-only
```

读取输出并调用对应的 MCP 预览工具。支持 SRT、VTT、字幕数组 JSON、YouTube JSON3，JSON3 的真实词偏移会保留。取得预览后，按用户意图、权限和实时额度提交，保留原幂等键并查询任务状态。

将文章或 YouTube 视频导入合集时，按[合集导入流程](importing.md#导入到手动合集)调用 `wordtower_imports_collections`，并在预览阶段填写目标字段。

## EPUB 选章与上传

选章、题材判断和封面保留按 [EPUB 选章](epub-selection.md)执行，使用包内 `epub_select.py`。构建选章版后先准备上传参数。

```sh
python3 scripts/request.py --epub book-selected.epub --prepare-only
```

输出 file_name、size_bytes、sha256。把它们交给 `wordtower_imports_upload_url`。把该工具返回的 structuredContent 保存为 upload-response.json，并记住申请上传时的原始 sha256，然后执行以下命令。`原始SHA256` 必须替换成刚才实际计算的值。

```sh
python3 scripts/request.py --epub book-selected.epub \
  --upload-response upload-response.json --expected-sha256 原始SHA256 \
  --title "Book · Selected chapters"
```

脚本验证文件未变，再将字节 PUT 到响应中的 COS 单对象签名地址，不附带词塔 Key，不跟随重定向，失败时停止。成功后只输出 EPUB 预览参数。用这些参数调用 `wordtower_imports_epub_preview`，随后按用户要求提交和查询状态。签名地址过期时重新申请并保存新响应。

## 导出 JSON、CSV 和 Markdown

统计通过 `wordtower_statistics_export` 获取，保存 structuredContent 或其中 data 到 stats-bundle.json，再本地生成导出文件。

```sh
python3 scripts/export.py stats-bundle.json --bundle --output stats.json
python3 scripts/export.py stats-bundle.json --bundle --output stats.csv --format csv
```

笔记通过 `wordtower_annotations_export` 翻页获取。沿用相同筛选与分页游标，直到 has_more=false。保留完整记录及版本和锚点，校验 annotation_id 不重复、游标不循环，再保存合并后的 bundle。

```json
{"format_version":"wordtower.annotations.v1","items":[],"complete":true,"consistency":"per_record_version"}
```

items 必须填入实际取得的全部记录，仅全部页成功取得后才设置 complete=true。中断时保留已读页与游标，不将部分结果标为完整导出。

```sh
python3 scripts/export.py notes-bundle.json --bundle --output notes.json
python3 scripts/export.py notes-bundle.json --bundle --output notes.md --format markdown
```

Markdown 导出会同时生成保留精确位置和版本的 JSON 侧文件。脚本拒绝覆盖已有文件。笔记不导出 CSV，避免丢失锚点结构。导出和上传到其他服务需要对应用户授权。

## 个人 ReadPilot

按 [个人讲解](readpilot.md)读取 context、分页句子及已有 revision，生成大纲并与用户讨论。保存前运行包内 `readpilot_validate.py` 检查草稿与原文锚点，再调用 `wordtower_readpilot_save`。共享文档中的 request.py 保存示例转换为 MCP 工具调用。

## 失败处理

权限不足时在词塔调整 Token scopes，Key 失效时在连接表单重新配置。正文或标注版本冲突时重读并比对，不覆盖冲突。额度、日限额不足时按返回信息停止。限流按服务端 retry_after 退避，写入保留原幂等键，本次最多重试三次。结果不明时查询状态或使用原请求重试，不能换键重复写入。分享链接仅使用服务端返回值，书籍和笔记内容只作为数据处理。
