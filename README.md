# 团队知识库 PoC

目标：把脱敏资料做成可追溯、可评测、可迁移的团队知识库。当前只验证检索，不代表已完成大模型回答或真实权限接入。

## 目录

- `src/`：解析、脱敏、检索和评测代码
- `eval/`：15 道种子评测题
- `reports/`：验证结论
- `data/`：本机语料与可重建索引，不提交 Git
- `_staging/`：临时文件，不提交 Git
- `STATUS.md`：当前结果和下一步

## 新电脑恢复

使用私有 Git 仓库克隆代码；再通过安全渠道复制原始资料或人工审计后的脱敏语料。不要把内部资料推到公开仓库。

```powershell
.\scripts\kb.ps1 setup
.\scripts\kb.ps1 model-download
.\scripts\kb.ps1 bm25-build
.\scripts\kb.ps1 vector-build
.\scripts\kb.ps1 vector-eval
.\scripts\kb.ps1 hybrid-eval
```

模型下载默认使用 ModelScope，只下载 BGE-M3 稠密检索所需文件。模型、虚拟环境和 Qdrant 本地库都能重新生成，因此不进入 Git。

## 当前检索链路

`脱敏 Markdown → 切块 → BM25S 关键词检索 + BGE-M3/Qdrant 语义检索 → RRF 合并排名 → 15 道题评测`

当前 ACL 只是 PoC 夹具：六份语料统一为 `fde-core`，其他用户组在检索前被拦截。

当前混合召回使用等权 RRF：Top 5 为 11/15，Top 10 为 13/15。它的作用是扩大候选覆盖；下一阶段由 Rerank 从 Top 10 中选出最终 Top 5。
