# D:\demo 垃圾清理脚本 —— 在普通 PowerShell 或 cmd 中运行：
#   powershell -NoProfile -ExecutionPolicy Bypass -File D:\demo\cleanup.ps1
# 只删无争议垃圾；数据库备份滚动由程序自动管理，不在此处理。

$ErrorActionPreference = 'Continue'
Set-Location 'D:\demo'
$freed = 0

function Remove-Junk([string]$path) {
    if (Test-Path $path) {
        $size = (Get-ChildItem $path -Recurse -Force -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum
        Remove-Item -LiteralPath $path -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
        if (-not (Test-Path $path)) {
            $script:freed += [math]::Round(($size ?? 0) / 1MB, 1)
            Write-Host "已删除: $path"
        } else {
            Write-Host "删除失败(可能被占用): $path"
        }
    }
}

# 1. pytest 测试残留目录
Get-ChildItem 'D:\demo' -Directory -Filter 'pytest-tmp*' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Junk $_.FullName }

# 2. Python 字节码缓存（会自动重建）
Get-ChildItem 'D:\demo\backend' -Directory -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Junk $_.FullName }

# 3. 旧备份快照（数据库 .db 备份不在删除范围内）
Remove-Junk 'D:\demo\backups\pre-sync-20260831-161336'
Remove-Junk 'D:\demo\backups\review-status-20260912-131454'
Remove-Junk 'D:\demo\backups\data-recovery-20260831-164027'

# 4. 前端构建产物（可随时 pnpm build 重建，dev 模式用不到）
# 如需保留 dist 请注释掉下面这行
Remove-Junk 'D:\demo\frontend\dist'

Write-Host ""
Write-Host "清理完成，共释放约 $freed MB"
