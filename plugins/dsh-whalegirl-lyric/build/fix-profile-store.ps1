# 修复 profile 的 pnpm store 版本错配，并按包名安装 dsh-whalegirl-lyric
#
# 为什么必须由你在 DSH 关闭后运行：
#   profile 的 node_modules 由 pnpm 10 安装（store/v10，JSON 索引），
#   而运行时自带 pnpm 11（store/v11，SQLite 索引），两者格式不兼容。
#   修复 = 用 pnpm 11 重建 node_modules。但重建会先删除整个目录，
#   其中 lightningcss 的 Windows 原生模块 (.node / DLL) 在 DSH 运行时
#   被进程加载并锁定，Windows 不允许删除 → EPERM，重建中止。
#   因此必须先完全退出 DeepSeek Harness。
#
# 用法（在 DSH 关闭后，用普通 PowerShell 运行）：
#   powershell -ExecutionPolicy Bypass -File D:\MyProject\lyric_display\plugins\dsh-whalegirl-lyric\build\fix-profile-store.ps1

$ErrorActionPreference = 'Stop'

$PROF = "C:\Users\lys13\.dsh\profiles\desktop"
$NODE = "C:\Users\lys13\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
$PNPM = "C:\Users\lys13\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.cjs"
$PLUGIN = "dsh-whalegirl-lyric"
$PLUGIN_VER = "1.0.0"

function Step($n, $t) { Write-Host "`n=== $n. $t ===" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  OK   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  !    $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  FAIL $m" -ForegroundColor Red; exit 1 }

# ---------- 0. 前置检查：DSH 必须已关闭 ----------
Step 0 "前置检查：确认 DeepSeek Harness 已完全退出"
$running = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue
if ($running) {
  Die "DeepSeek Harness 仍在运行（PID: $($running.Id -join ', ')）。请完全退出后重试。"
}
Ok "未发现运行中的 DeepSeek Harness"

if (-not (Test-Path $PROF))          { Die "profile 目录不存在: $PROF" }
if (-not (Test-Path $PNPM))          { Die "找不到运行时 pnpm: $PNPM" }
Ok "路径检查通过"

# ---------- 1. 备份 ----------
Step 1 "备份当前 profile 与 node_modules"
$BAK = "C:\Users\lys13\.dsh\_storefix_" + (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Path $BAK -Force | Out-Null
foreach ($f in @("package.json","pnpm-lock.yaml","pnpm-workspace.yaml","cordis.yml","cordis.patch.yml")) {
  if (Test-Path "$PROF\$f") { Copy-Item "$PROF\$f" "$BAK\$f" -Force }
}
$nm = "$PROF\node_modules"
$baseEntries = (Get-ChildItem $nm -Force -ErrorAction SilentlyContinue | Measure-Object).Count
$baseFiles   = (Get-ChildItem $nm -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
@{ entries = $baseEntries; files = $baseFiles } | ConvertTo-Json | Set-Content "$BAK\baseline.json" -Encoding UTF8
Get-ChildItem $nm -Force | Select-Object -ExpandProperty Name | Sort-Object | Set-Content "$BAK\entries.txt" -Encoding UTF8
Compress-Archive -Path "$nm\*" -DestinationPath "$BAK\node_modules.zip" -CompressionLevel Optimal -Force
Ok "备份到 $BAK（$baseEntries 条目 / $baseFiles 文件）"

# ---------- 2. 用 pnpm 11 重建 node_modules ----------
Step 2 "用 pnpm 11 重建 node_modules（会先清空）"
Push-Location $PROF
$env:CI = "true"                              # 非交互环境也必须允许清空重建
$env:npm_config_confirm_modules_purge = "false"
Write-Host "  store: $(& $NODE $PNPM store path 2>&1)"
& $NODE $PNPM install --frozen-lockfile --ignore-scripts --reporter=append-only
$code = $LASTEXITCODE
Remove-Item env:CI -ErrorAction SilentlyContinue
Remove-Item env:npm_config_confirm_modules_purge -ErrorAction SilentlyContinue
Pop-Location

if ($code -ne 0) {
  Warn "重建失败（退出码 $code）。执行回滚…"
  Remove-Item "$nm" -Recurse -Force -ErrorAction SilentlyContinue
  Expand-Archive -Path "$BAK\node_modules.zip" -DestinationPath $nm -Force
  foreach ($f in @("package.json","pnpm-lock.yaml","pnpm-workspace.yaml","cordis.yml","cordis.patch.yml")) {
    if (Test-Path "$BAK\$f") { Copy-Item "$BAK\$f" "$PROF\$f" -Force }
  }
  Die "已回滚到操作前状态。请把上面的输出发给我。"
}
Ok "node_modules 已由 pnpm 11 重建"

$newEntries = (Get-ChildItem $nm -Force | Measure-Object).Count
$newFiles   = (Get-ChildItem $nm -Recurse -File -Force | Measure-Object).Count
Write-Host "  条目数: $newEntries（原 $baseEntries）"
Write-Host "  文件数: $newFiles（原 $baseFiles）"

# ---------- 3. 确认核心依赖完好 ----------
Step 3 "确认核心依赖未被漏装"
$missing = @()
foreach ($k in @("@linxin666\dsh-web-all","@deepseek-ai\schemastery","ws","zod","yaml")) {
  if (-not (Test-Path "$nm\$k")) { $missing += $k }
}
if ($missing.Count -gt 0) { Die "缺少依赖: $($missing -join ', ')。请把输出发给我。" }
Ok "核心依赖齐全"

# ---------- 4. 按包名安装插件 ----------
Step 4 "按包名安装 $PLUGIN@$PLUGIN_VER"
Push-Location $PROF
& $NODE $PNPM add "$PLUGIN@$PLUGIN_VER" --reporter=append-only
$code2 = $LASTEXITCODE
Pop-Location
if ($code2 -ne 0) { Die "pnpm add 失败（退出码 $code2）。请把输出发给我。" }
Ok "包已安装"

if (-not (Test-Path "$nm\$PLUGIN")) { Die "装完后 $nm\$PLUGIN 仍不存在" }
Ok "插件目录存在: $nm\$PLUGIN"

# ---------- 5. 把插件加入 bundle 列表 ----------
Step 5 "把 $PLUGIN 加入 dsh.profile.bundles"
$pkg = Get-Content "$PROF\package.json" -Raw | ConvertFrom-Json
$bundles = @($pkg.dsh.profile.bundles)
if ($bundles -notcontains $PLUGIN) {
  $pkg.dsh.profile.bundles = @($bundles + $PLUGIN)
  $pkg | ConvertTo-Json -Depth 10 | Set-Content "$PROF\package.json" -Encoding UTF8
  Ok "已加入（缺这一项会导致插件不生效）"
} else {
  Ok "已在列表中"
}
Get-Content "$PROF\package.json" | ForEach-Object { Write-Host "    $_" }

# ---------- 6. 逐项校验 ----------
Step 6 "校验 bundles 全部可解析"
Push-Location $PROF
$bad = @()
foreach ($b in $pkg.dsh.profile.bundles) {
  $r = & $NODE -e "import('$b').then(()=>console.log('OK')).catch(()=>console.log('FAIL'))" 2>&1
  if ($r -eq 'OK') { Ok $b } else { $bad += $b; Warn "$b 无法解析" }
}
Pop-Location
if ($bad.Count -gt 0) { Die "以下 bundle 解析失败: $($bad -join ', ')" }

# ---------- 7. 收尾 ----------
Step 7 "完成"
Write-Host @"

  请现在启动 DeepSeek Harness，然后刷新浏览器页面。
  挂件应出现在 GUI 右下角（默认收起态：只显示鲸鱼娘那块）。

  若没出现：
    1. 浏览器 F12 → Console 看有无 [dsh-whalegirl-lyric] 报错
    2. 确认 localStorage 里没有 dsh-whalegirl-lyric:hidden
       Object.keys(localStorage).filter(k=>k.includes('whalegirl'))

  本次备份: $BAK
  若 GUI 起不来，回滚：
    Remove-Item "$nm" -Recurse -Force
    Expand-Archive "$BAK\node_modules.zip" -DestinationPath "$nm"
    并从 `$BAK 还原那 5 个配置文件
"@ -ForegroundColor Green
