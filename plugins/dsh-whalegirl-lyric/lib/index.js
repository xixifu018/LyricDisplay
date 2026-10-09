/**
 * 鲸鱼娘·洛雪歌词挂件 —— Host 半边。
 *
 * 职责：
 *  - 在 Node 侧按固定间隔轮询洛雪音乐开放 API，解析 LRC，对外只发当前/下一句歌词；
 *  - 通过命名空间根路径上的两条路由，把状态与控制指令暴露给浏览器。
 *
 * 为什么轮询必须在 Host 侧：洛雪音乐的开放 API 不返回 CORS 头，浏览器直接请求会被
 * 同源策略拦掉；同时放在 Host 侧意味着多个页面共享同一次轮询。
 *
 * 路由形状的约束（实测）：只有 `/api/<命名空间>/<名字>` 这一层能正常访问，
 * 任何多一层路径段（如 `/api/<ns>/assets/x.png`）都会返回 401。因此本插件不在
 * 路由上提供静态素材，图片由构建脚本内嵌进客户端 bundle。
 */

import Schema from 'schemastery'

import { PlayerController } from './controller.js'

/** 路由命名空间。 */
const NS = 'dsh-whalegirl-lyric'
/** API 路由前缀。 */
const API_PREFIX = `/api/${NS}`

/**
 * 插件配置。
 *
 * 这几个字段会由「设置 → 插件」页渲染成表单（Host 侧 Config schema 直接投影为
 * JSON Schema）。保存后 Loader 会用新配置重新挂载本条目，因此**不需要重启**：
 * 控制器跟着重建，轮询地址与间隔立即生效。
 */
export const Config = Schema.object({
  host: Schema.string()
    .default('127.0.0.1')
    .description('洛雪音乐开放 API 地址（默认本机；填远程地址前请确认对方已开启该服务）'),
  port: Schema.natural()
    .default(23330)
    .description('洛雪音乐开放 API 端口（见洛雪「设置 → 基本设置 → 开放 API」）'),
  lyrics: Schema.boolean().default(true).description('在气泡里显示歌词'),
  translation: Schema.boolean()
    .default(true)
    .description('同时显示翻译歌词（经 /lyric-all 获取；取不到时自动回退为只显原文）'),
  pollIntervalMs: Schema.natural()
    .default(500)
    .min(200)
    .max(5000)
    .description('状态轮询间隔（毫秒，200~5000；越短歌词越跟手，请求也越频繁）'),
  useSse: Schema.boolean()
    .default(true)
    .description('用 SSE 推送即时响应切歌与播放/暂停（官方推荐）；进度仍靠轮询外推'),
})

/** 硬依赖：Web 路由宿主。 */
export const inject = ['webServer']

/**
 * 写一个 JSON 响应。
 * @param {import('node:http').ServerResponse} res - 响应对象。
 * @param {number} status - HTTP 状态码。
 * @param {unknown} body - 要序列化的数据。
 */
function sendJson(res, status, body) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

/**
 * 读取请求体并解析为 JSON。
 * @param {import('node:http').IncomingMessage} req - 请求对象。
 * @returns {Promise<Record<string, unknown>>} 解析结果；空体或非法 JSON 得到空对象。
 */
async function readJsonBody(req) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > 64 * 1024) throw new Error('body too large')
    chunks.push(chunk)
  }
  if (chunks.length === 0) return {}
  try {
    const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    return parsed !== null && typeof parsed === 'object' ? parsed : {}
  } catch {
    throw new Error('invalid JSON body')
  }
}

/**
 * 判断一个 URL 是否是当前歌曲自己的封面地址。
 * 这是封面代理的准入条件：只允许回源到洛雪刚刚返回的那个 picUrl，
 * 避免把路由变成任意 URL 的开放代理。
 * @param {unknown} candidate - 请求里带来的地址。
 * @param {string} currentPicUrl - 当前歌曲的封面地址。
 * @returns {boolean} 是否放行。
 */
function isCurrentCoverUrl(candidate, currentPicUrl) {
  if (typeof candidate !== 'string' || candidate === '' || currentPicUrl === '') return false
  if (candidate !== currentPicUrl) return false
  try {
    const parsed = new URL(candidate)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

/**
 * 代理当前歌曲封面。
 *
 * 为什么要代理：洛雪的 picUrl 指向第三方图床，浏览器直接加载会带上本站 Referer，
 * 容易被防盗链拒绝。由 Host 侧中转后是同源请求，且 Host 不发送浏览器 Referer。
 * 封面字节在内存里按 URL 缓存，避免每帧重复回源。
 * @param {import('node:http').ServerResponse} res - 响应对象。
 * @param {string} target - 要代理的封面地址。
 * @param {Map<string, { body: Buffer, headers: Record<string, string> }>} coverCache - 封面字节缓存。
 */
async function serveCover(res, target, coverCache) {
  const cached = coverCache.get(target)
  if (cached !== undefined) {
    res.writeHead(200, { ...cached.headers, 'cache-control': 'no-cache' })
    res.end(cached.body)
    return
  }

  try {
    const upstream = await fetch(target, {
      signal: AbortSignal.timeout(5000),
      headers: { accept: 'image/*' },
    })
    if (!upstream.ok) {
      res.writeHead(502).end()
      return
    }
    const body = Buffer.from(await upstream.arrayBuffer())
    const entry = {
      body,
      headers: {
        'content-type': upstream.headers.get('content-type') ?? 'image/jpeg',
        'content-length': String(body.length),
      },
    }
    // 简单上限：只缓存一张封面
    coverCache.clear()
    coverCache.set(target, entry)
    res.writeHead(200, { ...entry.headers, 'cache-control': 'no-cache' })
    res.end(body)
  } catch {
    res.writeHead(502).end()
  }
}

/**
 * 注册路由。
 * @param {import('@deepseek-ai/cordis').Context} ctx - 已注入 webServer 的上下文。
 * @param {PlayerController} player - 播放状态控制器。
 */
function registerRoutes(ctx, player) {
  /** 封面字节缓存：同一首歌只回源一次。 */
  const coverCache = new Map()

  const offState = ctx.webServer.register({
    kind: 'exact',
    path: `${API_PREFIX}/state`,
    handler: (req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.writeHead(405).end()
        return
      }

      // 带 cover 参数时走同源封面代理（子路径路由会被 401 拦掉，因此用查询参数）
      const url = new URL(req.url ?? '/', 'http://127.0.0.1')
      const cover = url.searchParams.get('cover')
      if (cover !== null) {
        if (!isCurrentCoverUrl(cover, player.raw.picUrl)) {
          res.writeHead(404).end()
          return
        }
        void serveCover(res, cover, coverCache)
        return
      }

      sendJson(res, 200, player.snapshot())
    },
  })

  const offControl = ctx.webServer.register({
    kind: 'exact',
    path: `${API_PREFIX}/control`,
    handler: async (req, res) => {
      if (req.method !== 'POST') {
        res.writeHead(405).end()
        return
      }
      let action = ''
      try {
        const body = await readJsonBody(req)
        action = typeof body.action === 'string' ? body.action : ''
      } catch (error) {
        sendJson(res, 400, { ok: false, error: String(error?.message ?? error) })
        return
      }
      const result = await player.control(action)
      sendJson(res, result.ok ? 200 : 400, result)
    },
  })

  ctx.effect(
    () => () => {
      offState()
      offControl()
    },
    `${NS}: routes`,
  )
}

/**
 * 插件入口。
 * @param {import('@deepseek-ai/cordis').Context} ctx - 插件上下文。
 * @param {object} config - 已校验的插件配置。
 */
export function apply(ctx, config) {
  const player = new PlayerController({
    host: config.host,
    port: config.port,
    lyrics: config.lyrics,
    translation: config.translation,
    pollIntervalMs: config.pollIntervalMs,
    useSse: config.useSse,
  })

  ctx.effect(
    () => {
      player.start()
      return () => player.stop()
    },
    `${NS}: lx-music poller`,
  )

  registerRoutes(ctx, player)

  ctx.logger?.debug?.(`${NS}: 轮询 ${player.baseUrl}（每 ${player.pollIntervalMs}ms）`)
}
