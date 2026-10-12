# Fix the pnpm store version mismatch in the DSH profile, then install
# dsh-whalegirl-lyric by package name.
#
# ---------------------------------------------------------------------------
# ASCII-ONLY ON PURPOSE
# Windows PowerShell 5.1 reads .ps1 files using the system ANSI codepage
# (GBK on a Chinese Windows), so a UTF-8 file without a BOM has its non-ASCII
# characters mangled -- quotes get mis-parsed and the whole script fails to
# load. Keeping this file pure ASCII makes it work on both Windows PowerShell
# 5.1 and PowerShell 7, with no BOM and no encoding assumptions.
# ---------------------------------------------------------------------------
#
# WHY YOU MUST RUN THIS WITH DSH CLOSED:
#   The profile's node_modules was installed by pnpm 10 (store/v10, JSON index)
#   while the bundled runtime ships pnpm 11 (store/v11, SQLite index). The two
#   formats are incompatible, so every pnpm-based install -- including the
#   plugin manager -- fails with ERR_PNPM_UNEXPECTED_STORE.
#
#   The fix is to rebuild node_modules with pnpm 11. But the rebuild starts by
#   deleting the whole directory, and while DSH is running the lightningcss
#   Windows native module (.node / DLL) is loaded and locked by the process.
#   Windows refuses to delete a loaded DLL, so the rebuild aborts with EPERM.
#   Hence step 0 below refuses to continue while DSH is running.
#
# USAGE (in a normal PowerShell window, with DeepSeek Harness fully closed):
#   powershell -ExecutionPolicy Bypass -File "<repo>\plugins\dsh-whalegirl-lyric\build\fix-profile-store.ps1"
#
#   The path above is the only thing you supply -- it is where this file lives.
#   Everything else (DSH home, profile, node, pnpm) is auto-detected, so this
#   script is not tied to one machine or user name. Override only if detection
#   picks the wrong thing:
#     -DshHome <dir>   -Profile <name>   -ProfileDir <dir>
#     -NodePath <exe>  -PnpmPath <cjs>

param(
  [string]$DshHome    = $env:DSH_HOME,
  [string]$Profile    = $env:DSH_PROFILE,
  [string]$ProfileDir = $env:DSH_PROFILE_DIR,
  [string]$NodePath   = "",
  [string]$PnpmPath   = ""
)

$ErrorActionPreference = 'Stop'

$PLUGIN     = "dsh-whalegirl-lyric"
$PLUGIN_VER = "1.0.0"

function Step($n, $t) { Write-Host ""; Write-Host "=== $n. $t ===" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  OK   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  !    $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  FAIL $m" -ForegroundColor Red; exit 1 }

# ---------- 0a. Detect DSH home / profile / runtime paths ----------
# Nothing below is hard-coded to a particular user name or install location.
# Detection order: explicit parameter, then the env var DSH exports, then a
# sensible default derived from $env:USERPROFILE.
Step "0a" "Detect DSH home, profile, node and pnpm"

if (-not $DshHome) { $DshHome = Join-Path $env:USERPROFILE ".dsh" }
if (-not (Test-Path $DshHome)) { Die "DSH home not found: $DshHome (pass -DshHome <dir>)" }
$DshHome = (Resolve-Path $DshHome).Path
Ok "DSH home : $DshHome"

# Prefer the profile DSH itself reports; otherwise use the only/first profile.
if (-not $Profile) {
  $profRoot = Join-Path $DshHome "profiles"
  if (Test-Path $profRoot) {
    $all = @(Get-ChildItem $profRoot -Directory -ErrorAction SilentlyContinue)
    if ($all.Count -eq 1) {
      $Profile = $all[0].Name
      Ok "profile  : $Profile (only one found)"
    } elseif ($all.Count -gt 1) {
      Die ("Several profiles exist (" + (($all | ForEach-Object { $_.Name }) -join ', ') +
           "). Pass -Profile <name>.")
    }
  }
}
if (-not $Profile) { $Profile = "desktop" }

if (-not $ProfileDir) { $ProfileDir = Join-Path $DshHome "profiles\$Profile" }
if (-not (Test-Path $ProfileDir)) {
  Die "Profile directory not found: $ProfileDir (pass -ProfileDir <dir>)"
}
$ProfileDir = (Resolve-Path $ProfileDir).Path
Ok "profile  : $Profile"
Ok "profile dir: $ProfileDir"

# node / pnpm live under the bundled runtime. Search instead of assuming the
# runtime folder name, so a renamed runtime still works.
if (-not $NodePath -or -not $PnpmPath) {
  $depsRoots = @(
    (Join-Path $DshHome "dsh-runtimes\*\dependencies"),
    (Join-Path $DshHome "dsh-runtimes\*\*\dependencies")
  )
}
if (-not $NodePath) {
  $hit = @(Get-ChildItem -Path $depsRoots -Recurse -Filter "node.exe" -ErrorAction SilentlyContinue |
           Select-Object -First 1)
  if ($hit.Count -eq 0) { Die "node.exe not found under $DshHome\dsh-runtimes (pass -NodePath <exe>)" }
  $NodePath = $hit[0].FullName
}
Ok "node     : $NodePath"

if (-not $PnpmPath) {
  # prefer the .cjs entry (works with plain 'node <file>'); fall back to .mjs
  $hit = @(Get-ChildItem -Path $depsRoots -Recurse -Filter "pnpm.cjs" -ErrorAction SilentlyContinue |
           Select-Object -First 1)
  if ($hit.Count -eq 0) {
    $hit = @(Get-ChildItem -Path $depsRoots -Recurse -Filter "pnpm.mjs" -ErrorAction SilentlyContinue |
             Select-Object -First 1)
  }
  if ($hit.Count -eq 0) { Die "pnpm entry not found under $DshHome\dsh-runtimes (pass -PnpmPath <cjs>)" }
  $PnpmPath = $hit[0].FullName
}
Ok "pnpm     : $PnpmPath"

# Backup goes next to the DSH home, not inside any specific user path
$BAKROOT = Join-Path $DshHome "_storefix"

# ---------- 0b. Precondition: DSH must be closed ----------
Step "0b" "Precondition: DeepSeek Harness must be fully closed"
$running = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue
if ($running) {
  $pids = ($running | ForEach-Object { $_.Id }) -join ', '
  Die "DeepSeek Harness is still running (PID: $pids). Close it completely and retry."
}
Ok "No running DeepSeek Harness process found"

if (-not (Test-Path $NodePath)) { Die "Runtime node not found: $NodePath" }
if (-not (Test-Path $PnpmPath)) { Die "Runtime pnpm not found: $PnpmPath" }
Ok "All paths verified"

# ---------- 1. Backup ----------
Step 1 "Back up the profile and node_modules"
$BAK = Join-Path $BAKROOT (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Path $BAK -Force | Out-Null
foreach ($f in @("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "cordis.yml", "cordis.patch.yml")) {
  if (Test-Path "$ProfileDir\$f") { Copy-Item "$ProfileDir\$f" "$BAK\$f" -Force }
}
$nm = "$ProfileDir\node_modules"
$baseEntries = (Get-ChildItem $nm -Force -ErrorAction SilentlyContinue | Measure-Object).Count
$baseFiles   = (Get-ChildItem $nm -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
@{ entries = $baseEntries; files = $baseFiles } | ConvertTo-Json | Set-Content "$BAK\baseline.json" -Encoding ASCII
Get-ChildItem $nm -Force | Select-Object -ExpandProperty Name | Sort-Object | Set-Content "$BAK\entries.txt" -Encoding ASCII
Write-Host "  Compressing node_modules..."
Compress-Archive -Path "$nm\*" -DestinationPath "$BAK\node_modules.zip" -CompressionLevel Optimal -Force
$zipMB = [math]::Round((Get-Item "$BAK\node_modules.zip").Length / 1MB, 1)
Ok "Backed up to $BAK ($baseEntries entries / $baseFiles files, $zipMB MB)"

# ---------- 2. Rebuild node_modules with pnpm 11 ----------
Step 2 "Rebuild node_modules with pnpm 11 (this empties it first)"
Push-Location $ProfileDir
$env:CI = "true"
$env:npm_config_confirm_modules_purge = "false"
Write-Host "  store: $(& $NodePath $PnpmPath store path 2>&1)"
Write-Host "  This may take a few minutes (55 packages, some with native modules)."
& $NodePath $PnpmPath install --frozen-lockfile --ignore-scripts --reporter=append-only
$code = $LASTEXITCODE
Remove-Item env:CI -ErrorAction SilentlyContinue
Remove-Item env:npm_config_confirm_modules_purge -ErrorAction SilentlyContinue
Pop-Location

if ($code -ne 0) {
  Warn "Rebuild failed (exit code $code). Rolling back..."
  Remove-Item $nm -Recurse -Force -ErrorAction SilentlyContinue
  Expand-Archive -Path "$BAK\node_modules.zip" -DestinationPath $nm -Force
  foreach ($f in @("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "cordis.yml", "cordis.patch.yml")) {
    if (Test-Path "$BAK\$f") { Copy-Item "$BAK\$f" "$ProfileDir\$f" -Force }
  }
  Die "Rolled back to the pre-run state. Please send me the output above."
}
Ok "node_modules rebuilt by pnpm 11"

$newEntries = (Get-ChildItem $nm -Force | Measure-Object).Count
$newFiles   = (Get-ChildItem $nm -Recurse -File -Force | Measure-Object).Count
Write-Host "  entries: $newEntries (was $baseEntries)"
Write-Host "  files  : $newFiles (was $baseFiles)"

# ---------- 3. Core dependencies present ----------
Step 3 "Verify core dependencies were not dropped"
$missing = @()
foreach ($k in @("@linxin666\dsh-web-all", "@deepseek-ai\schemastery", "ws", "zod", "yaml")) {
  if (-not (Test-Path "$nm\$k")) { $missing += $k }
}
if ($missing.Count -gt 0) {
  Die ("Missing dependencies: " + ($missing -join ', ') + " -- please send me the output above.")
}
Ok "Core dependencies all present"

# ---------- 4. Install the plugin by package name ----------
Step 4 "Install $PLUGIN@$PLUGIN_VER by package name"
Push-Location $ProfileDir
& $NodePath $PnpmPath add "$PLUGIN@$PLUGIN_VER" --reporter=append-only
$code2 = $LASTEXITCODE
Pop-Location
if ($code2 -ne 0) {
  Die "pnpm add failed (exit code $code2) -- please send me the output above."
}
Ok "Package installed"

if (-not (Test-Path "$nm\$PLUGIN")) { Die "After install, $nm\$PLUGIN still does not exist" }
Ok "Plugin directory present: $nm\$PLUGIN"

# ---------- 5. Register the bundle ----------
Step 5 "Add $PLUGIN to dsh.profile.bundles"
$pkg = Get-Content "$ProfileDir\package.json" -Raw | ConvertFrom-Json
$bundles = @($pkg.dsh.profile.bundles)
if ($bundles -notcontains $PLUGIN) {
  $pkg.dsh.profile.bundles = @($bundles + $PLUGIN)
  $pkg | ConvertTo-Json -Depth 10 | Set-Content "$ProfileDir\package.json" -Encoding UTF8
  Ok "Added (without this entry the plugin loads no routes and shows nothing)"
} else {
  Ok "Already listed"
}
Get-Content "$ProfileDir\package.json" | ForEach-Object { Write-Host "    $_" }

# ---------- 6. Every bundle must resolve ----------
Step 6 "Verify every bundle resolves"
Push-Location $ProfileDir
$bad = @()
foreach ($b in $pkg.dsh.profile.bundles) {
  $js = "import('" + $b + "').then(function(){console.log('OK')}).catch(function(){console.log('FAIL')})"
  $r = & $NodePath -e $js 2>&1
  if ($r -eq 'OK') { Ok $b } else { $bad += $b; Warn "$b does not resolve" }
}
Pop-Location
if ($bad.Count -gt 0) {
  Die ("These bundles failed to resolve: " + ($bad -join ', '))
}

# ---------- 7. Done ----------
Step 7 "Done"
Write-Host ""
Write-Host "  Start DeepSeek Harness now, then refresh the browser page." -ForegroundColor Green
Write-Host "  The widget should appear at the bottom-right of the GUI (collapsed by default)."
Write-Host ""
Write-Host "  If it does not appear:"
Write-Host "    1. Open DevTools (F12) and look for [dsh-whalegirl-lyric] errors in Console"
Write-Host "    2. Make sure localStorage has no hidden flag:"
Write-Host "         Object.keys(localStorage).filter(function(k){return k.indexOf('whalegirl')>=0})"
Write-Host ""
Write-Host "  Backup of this run: $BAK"
Write-Host "  To roll back manually:"
Write-Host "    Remove-Item `"$nm`" -Recurse -Force"
Write-Host "    Expand-Archive `"$BAK\node_modules.zip`" -DestinationPath `"$nm`""
Write-Host "    then restore the 5 config files from $BAK"
