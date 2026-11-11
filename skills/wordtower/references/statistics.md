# 阅读统计导出

需要 statistics:read。调用 /statistics/export，参数 start_date、end_date 为 YYYY-MM-DD，均包含，最多 366 个自然日；timezone 使用 IANA 时区，如 Asia/Shanghai 或 America/New_York，默认 Asia/Shanghai。长时间范围分段导出，各段不要重叠。先按用户所在时区解释“本周/月/年”，不要静默改成 UTC。

返回 totals、days（补齐无记录日期）、day_count、reading_days、average_daily_valid_reading_seconds、timezone 和 limitations。

- reading_total_seconds：记录的阅读总耗时；reading_valid_seconds：已有系统判定的有效阅读耗时，不是总耗时或在线时长。
- study_seconds：词卡学习耗时；answered_cards 为已答词卡次数，new_words 为学习记录的新词数，不代表词汇量增长或本周查词事件。
- listening_seconds、foreground_listening_seconds、background_listening_seconds：主音频播放时长，底层毫秒先汇总再除以 1000，可含小数秒。所有导出时长单位均为秒。
- reading_days：有效阅读时长大于 0 的自然日数；average_daily_valid_reading_seconds 按包含零记录的全部自然日平均，不是按有阅读的天数平均。

按现有 study_record.record_timestamp 归入指定时区；已有记录是汇总数据，不能重新拆分跨时区、跨午夜的历史汇总或还原每次阅读事件。阅读、听力和词卡时间可能重叠，不要相加为“总学习时长”。不要从统计推断读完了哪本书、阅读页数或长期词汇增长。

导出读取不新增学习记录、不打卡、不消耗解析或 AI 额度。数据来自本人，不包括他人/图书馆运营统计。

请求示例：

```json
{"api_name":"/statistics/export","start_date":"2026-10-01","end_date":"2026-10-22","timezone":"Asia/Shanghai"}
```

将请求写入本地 stats-request.json 后，可保存原始 JSON 或每日明细 CSV：

```sh
python3 scripts/export.py stats-request.json --output stats.json
python3 scripts/export.py stats-request.json --output stats.csv --format csv
```

CSV 每行保留日期与时区；合计、口径和限制见 JSON。文件不会覆盖已有内容。上传第三方服务仍需用户授权。
