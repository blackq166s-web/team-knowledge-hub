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
.\scripts\kb.ps1 reranker-download
.\scripts\kb.ps1 bm25-build
.\scripts\kb.ps1 vector-build
.\scripts\kb.ps1 vector-eval
.\scripts\kb.ps1 hybrid-eval
.\scripts\kb.ps1 rerank-eval
.\scripts\kb.ps1 decompose-eval
```

模型下载默认使用 ModelScope，只下载 BGE-M3 稠密检索所需文件。模型、虚拟环境和 Qdrant 本地库都能重新生成，因此不进入 Git。

## 当前检索链路

`脱敏 Markdown → 切块 → BM25S 关键词检索 + BGE-M3/Qdrant 语义检索 → RRF 合并 Top 10 → BGE Rerank 选 Top 5 → 15 道题评测`

当前 ACL 只是 PoC 夹具：六份语料统一为 `fde-core`，其他用户组在检索前被拦截。

当前混合召回使用等权 RRF：Top 10 为 13/15。BGE Rerank 重排后的 Top 5 为 12/15，本机 CPU 平均重排约 13.8 秒/题。加入 DeepSeek 复杂问题拆分、原范围继承和文档结构词增强后，种子集 Top 5 为 15/15；该结果仍需在新增盲测题上复验。

## DeepSeek 问题拆分测试

DeepSeek 只接收用户问题和允许识别的产品名，不接收知识库正文。无权限用户会在调用 API 前被拦截；简单问题不调用 API；接口失败、输出不合法或遗漏产品标识时自动回退到原问题。

在本机 PowerShell 临时设置密钥后运行评测（不要把密钥写入仓库）：

```powershell
$secureKey = Read-Host 'DeepSeek API Key' -AsSecureString
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
try {
    $env:DEEPSEEK_MODEL = 'deepseek-v4-flash'
    .\scripts\kb.ps1 decompose-eval
} finally {
    Remove-Item Env:\DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
    $secureKey.Dispose()
}
```

结果写入本机忽略文件 `reports/deepseek_decomposition_eval.json`。必须确认其中 `deepseek_success_count` 大于 0，才能称为完成了 DeepSeek 实测。当前 15 道种子题实测为 15/15，DeepSeek 平均拆分约 3.90 秒；这不是新增真实问题的业务验收结论。
