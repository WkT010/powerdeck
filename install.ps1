# ============================================================
#  多链私钥扫描器 - Windows 一键安装脚本 (PowerShell)
#  用法:
#    右键此文件 -> 用 PowerShell 运行
#    或在 PowerShell 中执行:  .\install.ps1
#  可选环境变量:
#    $env:PORT="8080"              web 查看器端口
#    $env:SCAN_INTERVAL="0.3"      扫描间隔秒数
#    $env:ALCHEMY_API_KEY="xxx"    启用 Alchemy 全量代币扫描
# ============================================================

# 强制以管理员权限运行（安装 Python 时可能需要）
if (-Not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[INFO] 需要管理员权限，正在重启脚本..." -ForegroundColor Blue
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$ErrorActionPreference = "Stop"

function Info($m)  { Write-Host "[INFO]  $m" -ForegroundColor Blue }
function Ok($m)    { Write-Host "[OK]    $m" -ForegroundColor Green }
function Warn($m)  { Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Fail($m)  { Write-Host "[FAIL]  $m" -ForegroundColor Red; exit 1 }

# ---------- 变量 ----------
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { Join-Path $env:USERPROFILE "eth-scanner" }
$Port       = if ($env:PORT)          { $env:PORT }          else { "8080" }
$ScanInt    = if ($env:SCAN_INTERVAL) { $env:SCAN_INTERVAL } else { "0.3" }

Info "多链私钥扫描器 - Windows 一键安装"
Info "安装目录: $InstallDir"
Info "Web 端口: $Port  扫描间隔: ${ScanInt}s"
Write-Host ""

# ---------- 1. 检测 Python ----------
Info "检查 Python..."
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python (3\.\d+)") {
            $pythonCmd = $cmd
            Ok "检测到 $ver ($cmd)"
            break
        }
    } catch { }
}
if (-Not $pythonCmd) {
    Info "未检测到 Python 3，正在通过 winget 安装..."
    try {
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
        $pythonCmd = "python"
        Ok "Python 安装完成"
    } catch {
        Fail "Python 安装失败，请手动安装 Python 3: https://www.python.org/downloads/"
    }
}

# 刷新 PATH（刚装的 Python 可能不在当前会话 PATH）
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# ---------- 2. 创建安装目录 ----------
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "output") | Out-Null
Set-Location $InstallDir

# ---------- 3. 复制服务文件 ----------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Info "复制服务文件到 $InstallDir ..."

$files = @("scanner.py", "web_log_viewer.py", "run.sh", "start_viewer.sh", "requirements.txt")
foreach ($f in $files) {
    $src = Join-Path $ScriptDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $InstallDir $f)
        Ok "  $f"
    } else {
        Warn "  $f 源文件不存在，跳过"
    }
}
if (-Not (Test-Path (Join-Path $InstallDir "scanner.py"))) {
    Fail "找不到 scanner.py，请把 install.ps1 与服务文件放在同一目录后重试。"
}
Ok "服务文件就位"

# ---------- 4. 安装 Python 依赖 ----------
Info "安装 Python 依赖..."
& $pythonCmd -m pip install -q -r requirements.txt 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    Warn "pip 安装失败，尝试 --user"
    & $pythonCmd -m pip install --user -q -r requirements.txt 2>&1 | Select-Object -Last 5
    if ($LASTEXITCODE -ne 0) { Fail "Python 依赖安装失败" }
}
Ok "Python 依赖就绪"

# ---------- 5. 启动 scanner ----------
Info "启动 scanner..."
$env:SCAN_INTERVAL = $ScanInt
# Windows 没有 nohup，用 Start-Process 后台启动 + 重定向输出
$scannerLog = Join-Path $InstallDir "output\scanner.stdout.log"
$scannerProc = Start-Process -FilePath $pythonCmd -ArgumentList "-u", "scanner.py" `
    -WorkingDirectory $InstallDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $scannerLog -RedirectStandardError $scannerLog
$scannerProc.Id | Out-File (Join-Path $InstallDir ".scanner.pid") -Encoding ASCII
Start-Sleep -Seconds 6
if (-Not $scannerProc.HasExited) {
    Ok "scanner 已启动, PID=$($scannerProc.Id)"
} else {
    Warn "scanner 启动失败，查看 $scannerLog"
}

# ---------- 6. 启动 viewer ----------
Info "启动 web 查看器 (端口 $Port)..."
$env:PORT = $Port
$viewerLog = Join-Path $InstallDir "output\viewer.log"
$viewerProc = Start-Process -FilePath $pythonCmd -ArgumentList "-u", "web_log_viewer.py" `
    -WorkingDirectory $InstallDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $viewerLog -RedirectStandardError $viewerLog
$viewerProc.Id | Out-File (Join-Path $InstallDir ".viewer.pid") -Encoding ASCII
Start-Sleep -Seconds 2
if (-Not $viewerProc.HasExited) {
    Ok "viewer 已启动, PID=$($viewerProc.Id)"
} else {
    Warn "viewer 启动失败，查看 $viewerLog"
}

# ---------- 7. 验证 HTTP ----------
Info "验证 web 查看器..."
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -eq 200) {
        Ok "Web 查看器响应正常 (HTTP 200)"
    } else {
        Warn "Web 查看器响应码: $($resp.StatusCode)"
    }
} catch {
    Warn "Web 查看器未响应（可能还在启动中，稍等片刻再访问）"
}

# ---------- 8. 完成 ----------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  安装目录:  $InstallDir"
$scannerPid = if (Test-Path (Join-Path $InstallDir ".scanner.pid")) { Get-Content (Join-Path $InstallDir ".scanner.pid") } else { "-" }
$viewerPid  = if (Test-Path (Join-Path $InstallDir ".viewer.pid"))  { Get-Content (Join-Path $InstallDir ".viewer.pid")  } else { "-" }
Write-Host "  Scanner:   运行中 PID=$scannerPid"
Write-Host "  Viewer:    运行中 PID=$viewerPid"
Write-Host ""
Write-Host "  访问地址:  http://localhost:$Port/"
if ($env:ALCHEMY_API_KEY) {
    Write-Host "  Alchemy:   已启用全量代币扫描"
} else {
    Write-Host "  Alchemy:   未启用（可选 `$env:ALCHEMY_API_KEY='xxx' 增强）"
}
Write-Host ""
Write-Host "  常用命令 (PowerShell):"
Write-Host "    cd $InstallDir"
Write-Host "    Stop-Process -Id $scannerPid        # 停止 scanner"
Write-Host "    Stop-Process -Id $viewerPid         # 停止 viewer"
Write-Host "    Get-Content output\scanner.log -Wait  # 实时看日志"
Write-Host ""
Write-Host "  注意: 私钥空间 2^256，碰撞概率≈0，仅供学习/演示。" -ForegroundColor Yellow
Write-Host ""
Write-Host "  按任意键打开浏览器访问..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Start-Process "http://localhost:$Port/"
