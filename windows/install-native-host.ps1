param (
    [switch]$Uninstall
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$HostName = 'com.llm_project.llama_launcher'
$NativeDir = Join-Path $PSScriptRoot 'native_host'
$CsFile = Join-Path $NativeDir 'LlamaLauncher.cs'
$ExeFile = Join-Path $NativeDir 'llama_launcher.exe'
$ManifestFile = Join-Path $NativeDir "$HostName.json"
$ExtensionId = 'mbhjmenbcbbdhknajlellaokildpknam'

$RegRoots = @(
    "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\$HostName",
    "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
)

if ($Uninstall) {
    foreach ($reg in $RegRoots) {
        if (Test-Path -LiteralPath $reg) {
            Remove-Item -LiteralPath $reg -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "[OK] 已移除 Native Host 註冊 ($HostName)。" -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $NativeDir)) {
    New-Item -ItemType Directory -Path $NativeDir -Force | Out-Null
}

$Csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $Csc)) {
    $Csc = 'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $Csc)) {
    throw "找不到 csc.exe，無法編譯 Native Host。"
}

& $Csc /nologo /optimize+ /target:exe "/out:$ExeFile" "$CsFile"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ExeFile)) {
    throw "編譯 llama_launcher.exe 失敗 (exit=$LASTEXITCODE)。"
}

$Manifest = [ordered]@{
    name = $HostName
    description = 'LLM Watchdog Native Launcher for Shinkansen'
    path = $ExeFile
    type = 'stdio'
    allowed_origins = @(
        "chrome-extension://$ExtensionId/"
    )
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($ManifestFile, $ManifestJson, (New-Object System.Text.UTF8Encoding($false)))

foreach ($reg in $RegRoots) {
    $parent = Split-Path -Parent $reg
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -Path $parent -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $reg)) {
        New-Item -Path $reg -Force | Out-Null
    }
    Set-ItemProperty -LiteralPath $reg -Name '(Default)' -Value $ManifestFile
}

Write-Host "[OK] Native Host 已編譯並註冊完成：" -ForegroundColor Green
Write-Host "  • 執行檔：$ExeFile"
Write-Host "  • Manifest：$ManifestFile"
Write-Host "  • Allowed Origin：chrome-extension://$ExtensionId/"
