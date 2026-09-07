param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedManifest = (Resolve-Path -LiteralPath $ManifestPath).Path
$stagingRoot = Join-Path $resolvedRoot '_staging\20260907_语料基线'
$conversionRoot = Join-Path $stagingRoot 'conversion'
$pdfRoot = Join-Path $stagingRoot 'pdf'
New-Item -ItemType Directory -Force -Path $conversionRoot, $pdfRoot | Out-Null

$manifest = Get-Content -Raw -LiteralPath $resolvedManifest | ConvertFrom-Json
$samples = @($manifest.documents | Where-Object { $_.sample_selected -eq $true })
if ($samples.Count -ne 6) {
    throw "抽检样本数量应为 6，实际为 $($samples.Count)"
}

$word = $null
$results = @()
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3

    foreach ($item in $samples) {
        $inputPath = Join-Path $resolvedRoot ($item.raw_relative_path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $inputPath -PathType Leaf)) {
            throw "样本文档不存在: $inputPath"
        }
        $normalizedPath = $inputPath
        $conversionStatus = '无需转换'
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($inputPath)
        if ([System.IO.Path]::GetExtension($inputPath).ToLowerInvariant() -eq '.doc') {
            $normalizedPath = Join-Path $conversionRoot ($baseName + '.docx')
            $document = $word.Documents.Open($inputPath, $false, $true)
            try {
                $document.SaveAs2($normalizedPath, 16)
                $conversionStatus = 'DOC 转 DOCX 成功'
            }
            finally {
                $document.Close($false)
            }
        }

        $pdfPath = Join-Path $pdfRoot ($baseName + '.pdf')
        $document = $word.Documents.Open($normalizedPath, $false, $true)
        try {
            $document.ExportAsFixedFormat($pdfPath, 17)
        }
        finally {
            $document.Close($false)
        }
        $results += [pscustomobject]@{
            source_id = $item.source_id
            source_relative_path = $item.raw_relative_path
            normalized_docx = [System.IO.Path]::GetRelativePath($resolvedRoot, $normalizedPath).Replace('\', '/')
            pdf = [System.IO.Path]::GetRelativePath($resolvedRoot, $pdfPath).Replace('\', '/')
            conversion_status = $conversionStatus
            pdf_status = if (Test-Path -LiteralPath $pdfPath) { '成功' } else { '失败' }
        }
    }
}
finally {
    if ($null -ne $word) {
        $word.Quit()
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$resultPath = Join-Path $stagingRoot 'word_preparation.json'
$results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resultPath -Encoding utf8
Write-Output $resultPath
