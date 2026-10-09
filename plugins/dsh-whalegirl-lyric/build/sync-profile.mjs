#!/usr/bin/env node
/**
 * 把本插件从仓库同步到 DSH profile 的 node_modules。
 *
 * 为什么需要它：插件**不能**用软链接安装。
 * Node 的 ESM 解析器默认会解析符号链接的 realpath，于是 `import 'schemastery'`
 * 会去**仓库所在目录**的 node_modules 链里找，而那里没有这个包（它由宿主提供）。
 * 报错信息里的路径会指向仓库而不是 profile，很容易误判为插件写错。
 * 因此必须复制实体目录 —— 这也与 profile 里其他插件（皆为实体目录）保持一致。
 *
 * 用法:
 *   node build/sync-profile.mjs                    # 同步到默认 profile（desktop）
 *   node build/sync-profile.mjs <profile 名称>      # 指定 profile
 *   node build/sync-profile.mjs --dry-run          # 只看会复制什么
 */
import { cpSync, existsSync, lstatSync, readdirSync, rmSync, statSync } from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PLUGIN_NAME = 'dsh-whalegirl-lyric'
const SRC = path.resolve(HERE, '..')

const args = process.argv.slice(2)
const dryRun = args.includes('--dry-run')
const profileName = args.find(a => !a.startsWith('--')) ?? 'desktop'

const dshHome = process.env.DSH_HOME ?? path.join(os.homedir(), '.dsh')
const profileDir = path.join(dshHome, 'profiles', profileName)
const dest = path.join(profileDir, 'node_modules', PLUGIN_NAME)

console.log(`源   : ${SRC}`)
console.log(`目标 : ${dest}`)
console.log(`模式 : ${dryRun ? '试运行（不写入）' : '写入'}`)

if (!existsSync(profileDir)) {
  console.error(`\n✗ profile 目录不存在: ${profileDir}`)
  console.error('  可用 profile 列表：')
  const profilesRoot = path.join(dshHome, 'profiles')
  if (existsSync(profilesRoot)) {
    for (const n of readdirSync(profilesRoot)) console.log(`    - ${n}`)
  }
  process.exit(1)
}

// 软链接必须拦下：它的症状很隐蔽（导入时找不到宿主依赖）。
// 注意用 lstatSync 而不是 statSync —— 后者会**跟随**链接，对实体目录也会误判。
if (existsSync(dest) && lstatSync(dest).isSymbolicLink()) {
  console.error('\n✗ 目标是符号链接，插件不能用链接安装（见文件头注释）。')
  console.error('  请先删除它，再重新运行本脚本。')
  process.exit(1)
}

// 收集源文件（相对路径），跳过无关目录
const SKIP = new Set(['node_modules', '.git'])
const files = []
;(function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue
    const full = path.join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) walk(full)
    else if (st.isFile()) files.push(path.relative(SRC, full))
  }
})(SRC)

console.log(`\n待同步 ${files.length} 个文件:`)
for (const f of files) console.log(`  ${f}`)

if (dryRun) {
  console.log('\n试运行结束，未做任何修改。')
  process.exit(0)
}

// 整体替换，避免源目录删掉的文件残留在目标里
rmSync(dest, { recursive: true, force: true })
for (const f of files) {
  const from = path.join(SRC, f)
  const to = path.join(dest, f)
  cpSync(from, to, { recursive: true })
}

console.log(`\n✓ 已同步 ${files.length} 个文件到 profile`)
console.log('  下一步：确认 profile 的 package.json 里')
console.log(`  - dsh.profile.bundles 含 "${PLUGIN_NAME}"（否则插件行不会插入 Loader 树）`)
console.log('  - 然后重启 DeepSeek Harness 并刷新页面')
