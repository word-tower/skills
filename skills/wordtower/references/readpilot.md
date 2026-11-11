# ReadPilot 我的讲解

先读取调用协议，并用 `/_list` 检查个人讲解操作是否已开放。查看列表需要 `readpilot:read`。获取正文、大纲及讲稿还需要 `content:read`。保存需要 `readpilot:write` 和 `content:read`。用户可为此单独创建连接。

| 操作 | 参数 | 用途 |
| --- | --- | --- |
| `/readpilot/context` | `course_id`，可选 `start_offset`、`end_offset`、`content_version`、`limit` | 读取讨论范围内的原句和服务器给出的句子 ID。续读用 `next_start_offset` 和同一正文版本。 |
| `/readpilot/list` | `course_id` | 查本书各套讲解在当前章的状态。结合目录可展示逐章进度。 |
| `/readpilot/get` | `course_id`、`guide_id` | 读取当前 `revision_id`、`outline` 和可供编辑的 `cues`。 |
| `/readpilot/save` | `course_id`、新套系 `title` 或已有 `guide_id`、`expected_revision_id`、`content_version`、`idempotency_key`、`cues` | 原子发布或替换这一章。 |

讨论后先在聊天里展示「编号 / 讲解重点 / 触发原句」。讲解用适合用户水平的口语，先说原句是什么意思，再用一条短例句讲清用法。`speech_text` 会被朗读，使用纯文本。

用户明确要求保存后再调用 `/readpilot/save`。如果单独调用模型生成结构化讲稿，让它只返回 `{"cues":[...]}`。由 Agent 使用实际的课程 ID、正文版本和当前讲解版本组装保存请求。收到「把 3-02 改简单一点」时，先读取当前版本，让模型只改指定讲解点，再按原编号合回完整 `cues`。检查新口播中的标注短语，原样保留其他讲解点。

## 讲稿格式

```json
{
  "cue_id": "3-02",
  "title": "虚拟语气与过去未发生的条件",
  "trigger_sentence_id": "s120-178",
  "steps": [
    {
      "speech_text": "这里的虚拟语气表示过去没有实现的条件。我们再换个例句。",
      "annotations": [
        {
          "spoken_text": "虚拟语气",
          "source_anchors": [{"sentence_id": "s120-178", "quote": "would have"}],
          "intent": "term",
          "callout_text": "过去未实现"
        }
      ]
    }
  ]
}
```

提交前检查讲稿：

- 触发句 ID 逐字复制自 `/readpilot/context`，按原文的 `start_offset` 排序，每句一个讲解点。每章最多 100 个点，每点 1–5 步，每步口播最多 500 字符。引用句必须是触发句或更早的原句。
- `intent` 只允许 `quote`、`term`、`contrast`、`key_point`、`reference`、`context`。语法点用 `key_point`，词义或搭配用 `term`；不确定时省略，默认 `quote`。`emphasis` 可省略，填写时只能用 `subtle`、`normal`、`strong`。
- `spoken_text` 从当前步骤的 `speech_text` 中逐字截取，且只出现一次。原文 `quote` 同样按原大小写和标点逐字截取，且在该句中只出现一次。例如一句里有两处 `would have`，可以选唯一的 `would have caught`。需要标整句时可省略 `quote`。无法找到唯一的口播短语时，可省略这处动画。
- 讲稿只提交示例结构及接口定义允许的字段。触发和动画基于原文与口播锚点，播放时由词塔换算到音源和 TTS 时间线。

把生成的 `{"cues":[...]}` 保存为 `draft.json`，把读取的正文响应保存为 `context.json`，先做本地预检：

```sh
python3 scripts/readpilot_validate.py draft.json --context context.json
```

上下文分页时重复传 `--context`。局部改稿只预检本次改写的点，再合回当前讲稿。根据输出的字段路径定点修正并重跑预检，尤其是把在正文与例句中都出现的词换成唯一的完整短语，例如用 `Not until 放在句首` 代替两次出现的 `Not until`。预检通过后仍以服务端校验为准。

每本书（或独立课程）最多有一套有效的个人讲解。保存前先查 `/readpilot/list`；优先使用 `active: true` 的套系及其 `guide_id` 继续添加或更新章节。遇到 `READPILOT_GUIDE_LIMIT` 时，查看已有套系并在其中保存用户指定的章节。整套所有章节删完后，可以新建一套。

新章发送 `expected_revision_id: null`。替换或恢复已删除章时，使用刚读取的当前版本和已有 `guide_id`，后者包括删除后的版本号。若收到 422，按 `error.details` 修正指定字段或锚点。网络结果不明确时，用完全相同的请求和幂等键重试。收到 `REVISION_CONFLICT` 或 `CONTENT_CHANGED` 时重新读取并核对用户要求。章节删除在词塔 App 的 ReadPilot 讲解面板内操作，打开「设置 → 个人讲解管理」。

保存只提交最终讲稿，口播生成沿用 ReadPilot 的公开静态音频地址。通过原书的 ReadPilot 选择同名套系即可收听。
