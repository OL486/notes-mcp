# 《Designing Data-Intensive Applications》读书笔记

## 第三章：存储与检索

LSM-Tree 与 B-Tree 的取舍：写入吞吐 vs 读取延迟。
LSM 把随机写变成顺序写，代价是读的时候可能要查多个 SSTable，
所以需要 compaction 和布隆过滤器兜底。

这一章对 notes-mcp 的直接启发：如果笔记涨到十万篇，
"每次全量扫描"就等价于把 LSM 退化成每次全表扫——必须有倒排索引。

## 第四章：编码与演化

向后兼容 / 向前兼容的区别，以及为什么 JSON 的"可选字段"策略
在长期演进里会变成负担。

#reading #storage
