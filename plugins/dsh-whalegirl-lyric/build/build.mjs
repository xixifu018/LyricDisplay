/**
 * 构建脚本：把鲸鱼娘素材生成为内嵌 data URL 的客户端 bundle。
 *
 * 为什么内嵌而不是让浏览器去取图片：
 * DSH 对 `/api/<命名空间>/<子路径>` 形式的请求会返回 401（实测 `/state`、`/control`
 * 这类命名空间根路径正常，但任何多一层路径段的路由都取不到），因此插件不依赖
 * 任何子路径素材路由，直接把图片作为 data URL 编进 bundle，插件完全自包含。
 *
 * 用法: node build.mjs
 */

import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const run = promisify(execFile)

const here = dirname(fileURLToPath(import.meta.url))
const SOURCE_IMAGE = resolve(here, '..', '..', '..', 'whalegirl.png')
const TEMPLATE = join(here, 'client.template.js')
const OUTPUT = join(here, '..', 'lib', 'client.js')

/** 生成后的目标宽度（显示尺寸约 204px，2 倍图足够清晰）。 */
const TARGET_WIDTH = 400

/**
 * 裁掉透明留白并缩放到目标宽度，返回 PNG Buffer。
 * 使用项目自带的 Python + Pillow，避免给插件引入依赖。
 * @param {string} source - 源图片绝对路径。
 * @returns {Promise<Buffer>} 处理后的 PNG 数据。
 */
async function renderImage(source) {
  const script = [
    'import io, sys, base64',
    'from PIL import Image',
    `im = Image.open(r"${source}").convert("RGBA")`,
    'bbox = im.getchannel("A").getbbox()',
    'im = im.crop(bbox)',
    `w = ${TARGET_WIDTH}`,
    'h = round(im.height * w / im.width)',
    'im = im.resize((w, h), Image.LANCZOS)',
    'buf = io.BytesIO()',
    'im.save(buf, "PNG", optimize=True)',
    'sys.stdout.write(base64.b64encode(buf.getvalue()).decode("ascii"))',
  ].join('\n')

  const { stdout } = await run('python', ['-c', script], { maxBuffer: 64 * 1024 * 1024 })
  return Buffer.from(stdout.trim(), 'base64')
}

const png = await renderImage(SOURCE_IMAGE)
const dataUrl = `data:image/png;base64,${png.toString('base64')}`

const template = await readFile(TEMPLATE, 'utf8')
if (!template.includes('__WHALEGIRL_DATA_URL__')) {
  throw new Error('模板里找不到 __WHALEGIRL_DATA_URL__ 占位符')
}

await mkdir(dirname(OUTPUT), { recursive: true })
await writeFile(OUTPUT, template.replaceAll('__WHALEGIRL_DATA_URL__', dataUrl), 'utf8')

console.log(`素材: ${SOURCE_IMAGE}`)
console.log(`内嵌 PNG: ${(png.length / 1024).toFixed(0)} KB → base64 ${(dataUrl.length / 1024).toFixed(0)} KB`)
console.log(`已生成: ${OUTPUT} (${((await readFile(OUTPUT)).length / 1024).toFixed(0)} KB)`)
