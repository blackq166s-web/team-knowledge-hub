param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('setup', 'model-download', 'reranker-download', 'bm25-build', 'bm25-eval', 'vector-build', 'vector-eval', 'hybrid-eval', 'rerank-eval', 'decompose-eval', 'web')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if ($Action -eq 'setup') {
    if (-not (Test-Path -LiteralPath $Python)) {
        py -3.13 --version *> $null
        $PythonVersion = if ($LASTEXITCODE -eq 0) { '-3.13' } else { '-3.12' }
        & py $PythonVersion -m venv (Join-Path $ProjectRoot '.venv')
        if ($LASTEXITCODE -ne 0) {
            throw '需要先安装 Python 3.12 或 3.13。'
        }
    }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install $ProjectRoot
    exit $LASTEXITCODE
}

if ($Action -eq 'model-download') {
    $ModelDir = Join-Path $ProjectRoot '.cache\modelscope\bge-m3'
    if (-not (Test-Path -LiteralPath (Join-Path $ModelDir '.git'))) {
        $env:GIT_LFS_SKIP_SMUDGE = '1'
        git clone --depth 1 https://www.modelscope.cn/BAAI/bge-m3.git $ModelDir
        Remove-Item Env:\GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue
    }
    git -C $ModelDir lfs pull --include='pytorch_model.bin,sentencepiece.bpe.model,tokenizer.json'
    exit $LASTEXITCODE
}

if ($Action -eq 'reranker-download') {
    $ModelDir = Join-Path $ProjectRoot '.cache\modelscope\bge-reranker-v2-m3'
    if (-not (Test-Path -LiteralPath (Join-Path $ModelDir '.git'))) {
        $env:GIT_LFS_SKIP_SMUDGE = '1'
        git clone --depth 1 https://www.modelscope.cn/AI-ModelScope/bge-reranker-v2-m3.git $ModelDir
        Remove-Item Env:\GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue
    }
    git -C $ModelDir lfs pull --include='model.safetensors,sentencepiece.bpe.model,tokenizer.json'
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw '尚未创建虚拟环境，请先运行：.\scripts\kb.ps1 setup'
}

switch ($Action) {
    'web' { & $Python -m streamlit run (Join-Path $ProjectRoot 'src\web_app.py') --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false }
    'bm25-build'   { & $Python (Join-Path $ProjectRoot 'src\bm25_baseline.py') $ProjectRoot build }
    'bm25-eval'    { & $Python (Join-Path $ProjectRoot 'src\bm25_baseline.py') $ProjectRoot evaluate --top-k 5 }
    'vector-build' { & $Python (Join-Path $ProjectRoot 'src\vector_baseline.py') $ProjectRoot build }
    'vector-eval'  { & $Python (Join-Path $ProjectRoot 'src\vector_baseline.py') $ProjectRoot evaluate --top-k 5 }
    'hybrid-eval'  { & $Python (Join-Path $ProjectRoot 'src\hybrid_baseline.py') $ProjectRoot evaluate --top-k 5 }
    'rerank-eval'  { & $Python (Join-Path $ProjectRoot 'src\rerank_baseline.py') $ProjectRoot evaluate --top-k 5 --hybrid-top-k 10 }
    'decompose-eval' { & $Python (Join-Path $ProjectRoot 'src\decomposed_hybrid_eval.py') $ProjectRoot evaluate --top-k 5 --per-query-k 10 }
}
exit $LASTEXITCODE
