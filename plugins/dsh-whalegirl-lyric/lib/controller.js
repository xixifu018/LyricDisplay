/**
 * 洛雪音乐（LX Music）播放状态控制器。
 *
 * 只在 Host 侧轮询，浏览器侧读缓存 —— 多个页面共享同一次轮询。
 * 歌词在切歌时抓取一次并解析成有序行，之后每帧只做二分查找。
 */

import { currentAndNext, parseLrc } from './lrc.js'

/** 默认轮询间隔（毫秒）；可被配置项 pollIntervalMs 覆盖。 */
const DEFAULT_POLL_INTERVAL_MS = 500
/** SSE 断线后的重连间隔（毫秒）。 */
const SSE_RETRY_MS = 2000
/** 状态里必须是数字的字段：SSE 可能把它们推成字符串，统一在此收敛类型。 */
const NUMERIC_FIELDS = new Set(['duration', 'progress', 'playbackRate'])

/**
 * 解析一个 SSE 事件块。
 * 支持 `data:` 与 `event:` 两个字段，忽略注释行（`:` 开头）。
 * 导出以便单测（无需连真实流就能覆盖边界）。
 * @param {string} block - 以空行分隔出的事件块。
 * @returns {{ event: string, data: string } | null} 解析结果；无 data 时返回 null。
 */
export function parseSseBlock(block) {
  let event = 'message'
  const dataLines = []

  for (const rawLine of block.split('\n')) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (line === '' || line.startsWith(':')) continue
    const colonAt = line.indexOf(':')
    const field = colonAt < 0 ? line : line.slice(0, colonAt)
    // 冒号后允许有一个空格，按规范去掉
    let value = colonAt < 0 ? '' : line.slice(colonAt + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

/**
 * 把 SSE 的 `data` 文本解析成对应字段的值。
 * 值通常是 JSON（字符串带引号、数字是裸数字），解析失败时退回原文本。
 * @param {string} event - 字段名。
 * @param {string} data - 原始 data 文本。
 * @returns {string | number | boolean} 归一化后的值。
 */
export function normalizeStatusField(event, data) {
  let value
  try {
    value = JSON.parse(data)
  } catch {
    value = data
  }

  if (NUMERIC_FIELDS.has(event)) {
    const num = Number(value)
    return Number.isFinite(num) ? num : 0
  }
  if (event === 'mute' || event === 'collect') return value === true || value === 'true'
  return typeof value === 'string' ? value : String(value)
}
/** HTTP 超时（毫秒）。 */
const TIMEOUT_MS = 2500
/** 轮询请求的字段白名单 —— 不含 lyric，整首歌词改由 /lyric 单独获取。 */
const STATUS_FILTER = 'status,name,singer,albumName,duration,progress,lyricLineText,picUrl'

/** 一次轮询的原始结果。 */
function emptyRaw() {
  return {
    status: 'stoped',
    name: '',
    singer: '',
    albumName: '',
    duration: 0,
    progress: 0,
    lyricLineText: '',
    picUrl: '',
  }
}

/**
 * 按时间戳把翻译歌词并进原文歌词。
 * @param {{ time: number, text: string }[]} lines - 原文歌词行。
 * @param {{ time: number, text: string }[]} trans - 翻译歌词行。
 * @returns {{ time: number, text: string, translation: string }[]} 合并后的歌词行。
 */
function mergeTranslation(lines, trans) {
  if (trans.length === 0) return lines.map(line => ({ ...line, translation: '' }))

  const byTime = new Map()
  for (const item of trans) {
    byTime.set(item.time.toFixed(2), item.text)
  }

  return lines.map(line => ({
    ...line,
    translation: byTime.get(line.time.toFixed(2)) ?? '',
  }))
}

export class PlayerController {
  /**
   * @param {{ host: string, port: number, lyrics: boolean, translation: boolean, pollIntervalMs?: number }} config - 插件配置。
   */
  constructor(config) {
    this.config = config
    this.raw = emptyRaw()
    this.lyricLines = []
    this.lyricName = ''
    this.lyricPending = false
    this.reachable = false
    this.lastError = ''
    this.localProgress = 0
    this.lastUpdate = Date.now()
    this.timer = null
    this.poller = null
  }

  /** 基础 URL。 */
  get baseUrl() {
    return `http://${this.config.host}:${this.config.port}`
  }

  /** 实际生效的轮询间隔（毫秒）：配置非法时回退默认值。 */
  get pollIntervalMs() {
    const value = Number(this.config.pollIntervalMs)
    if (!Number.isFinite(value) || value < 200 || value > 5000) return DEFAULT_POLL_INTERVAL_MS
    return Math.round(value)
  }

  /**
   * 开始：轮询提供进度基准 + SSE 提供即时状态变化。
   *
   * 两者分工不同、都要有：
   *  - 轮询（每 {@link pollIntervalMs} 一次）给出权威进度，供本地时间外推；
   *  - SSE 让切歌与播放/暂停**即时**反映，不用等下一个轮询周期。
   */
  start() {
    if (this.timer !== null) return
    this.poller = new AbortController()
    // 立即拉一次，避免首帧空白
    void this.poll()
    this.timer = setInterval(() => void this.poll(), this.pollIntervalMs)
    if (this.config.useSse !== false) void this.subscribe()
  }

  /** 停止轮询与 SSE 订阅。 */
  stop() {
    if (this.timer !== null) {
      clearInterval(this.timer)
      this.timer = null
    }
    // 先 abort 再置空：在途的 fetch 流会立刻结束，subscribe() 的循环据此退出
    this.poller?.abort()
    this.poller = null
  }

  /**
   * 估算当前播放进度（秒）：以最近一次服务端值为基准，按本地时间推进。
   * @returns {number} 进度秒数。
   */
  estimateProgress() {
    if (this.raw.status !== 'playing') return this.localProgress
    const elapsed = (Date.now() - this.lastUpdate) / 1000
    const next = this.localProgress + elapsed
    return this.raw.duration > 0 ? Math.min(next, this.raw.duration) : next
  }

  /**
   * 当前完整状态快照，供浏览器侧渲染。
   * @returns {object} 状态快照。
   */
  snapshot() {
    const progress = this.estimateProgress()
    const { current, next, index } = currentAndNext(this.lyricLines, progress)
    const line = index >= 0 ? this.lyricLines[index] : undefined
    const hasLyric = this.lyricLines.length > 0

    return {
      ok: true,
      reachable: this.reachable,
      error: this.lastError,
      status: this.raw.status,
      playing: this.raw.status === 'playing',
      name: this.raw.name,
      singer: this.raw.singer,
      albumName: this.raw.albumName,
      picUrl: this.raw.picUrl,
      progress,
      duration: this.raw.duration,
      lyricLineText: this.raw.lyricLineText,
      lyric: current,
      translation: line?.translation ?? '',
      next,
      lyricReady: hasLyric,
      lyricIndex: index,
      lyricCount: this.lyricLines.length,
      at: Date.now(),
    }
  }

  /**
   * 动作名 → 洛雪开放 API 端点。
   *
   * 注意端点命名并不统一：播放/暂停是 `/play` `/pause`，
   * 但切歌是 `/skip-next` `/skip-prev` —— 写成 `/next` `/prev` 会得到 401。
   * 参考 https://lxmusic.toside.cn/desktop/open-api
   */
  static CONTROL_ENDPOINTS = {
    play: '/play',
    pause: '/pause',
    next: '/skip-next',
    prev: '/skip-prev',
    stop: '/stop',
  }

  /**
   * 发送一条播放控制指令。
   * @param {string} action - play / pause / toggle / next / prev / stop。
   * @returns {Promise<{ ok: boolean, action: string, error?: string }>} 执行结果。
   */
  async control(action) {
    const endpoints = PlayerController.CONTROL_ENDPOINTS
    let verb = action
    if (action === 'toggle') {
      verb = this.raw.status === 'playing' ? 'pause' : 'play'
    }

    const path = endpoints[verb]
    if (path === undefined) return { ok: false, action, error: 'unknown action' }

    try {
      await this.request(path)
      // 立刻回读一次，让界面不等下一个轮询周期
      await this.poll()
      return { ok: true, action: verb }
    } catch (error) {
      this.lastError = String(error?.message ?? error)
      return { ok: false, action: verb, error: this.lastError }
    }
  }

  /**
   * 单次 HTTP 请求。
   * @param {string} path - 以 / 开头的路径（可含查询串）。
   * @param {number} [timeoutMs] - 超时毫秒数。
   * @returns {Promise<Response>} fetch 响应。
   */
  async request(path, timeoutMs = TIMEOUT_MS) {
    const timeout = AbortSignal.timeout(timeoutMs)
    // 停止轮询时立刻取消在途请求，而不是等它自己超时
    const signal = this.poller === null ? timeout : AbortSignal.any([this.poller.signal, timeout])
    const response = await fetch(`${this.baseUrl}${path}`, { signal })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response
  }

  /** 执行一次轮询。 */
  async poll() {
    try {
      const response = await this.request(`/status?filter=${encodeURIComponent(STATUS_FILTER)}`)
      const data = await response.json()
      this.applyStatus(data)
    } catch (error) {
      this.reachable = false
      this.lastError = String(error?.message ?? error)
      // 服务不可达时清掉播放态，界面回到「等待」
      if (this.raw.status !== 'stoped') {
        this.raw = { ...this.raw, status: 'stoped' }
      }
    }
  }

  /**
   * 应用一份状态数据（轮询与 SSE 共用，避免两处逻辑漂移）。
   *
   * 与轮询的差异：SSE 每帧只带**变化**的字段，因此这里用**合并**而不是整体替换，
   * 否则一次 `progress` 推送就会把歌名、时长等字段清空。
   * @param {object} data - `/status` 返回的完整对象，或 SSE 累计出的部分字段。
   */
  applyStatus(data) {
    this.raw = { ...this.raw, ...data }

    // 服务端进度是权威值：用它重新对齐本地推进基准
    if (Number.isFinite(this.raw.progress)) this.localProgress = this.raw.progress
    this.lastUpdate = Date.now()
    this.reachable = true
    this.lastError = ''

    if (this.raw.name !== '' && this.raw.name !== this.lyricName) {
      void this.loadLyric(this.raw.name)
    }
  }

  /**
   * 订阅 SSE 状态流：切歌与播放/暂停会被**即时**推送，不必等下一个轮询周期。
   *
   * 为什么不能只靠 SSE：它只在状态**变化**时推送，进度不会逐帧到达，
   * 因此进度仍需轮询提供基准（见 {@link poll} 与 {@link estimateProgress}）。
   *
   * 实测帧格式（字段名就在 `event:` 里，值在 `data:` 里且是 JSON）：
   * ```
   * event: status
   * data: "paused"
   * ```
   * @returns {Promise<void>} 直到被 {@link stop} 中止才返回。
   */
  async subscribe(onStatus) {
    const signal = this.poller === null ? undefined : this.poller.signal
    const query = `?filter=${encodeURIComponent(STATUS_FILTER)}`
    const handle = typeof onStatus === 'function' ? onStatus : data => this.applyStatus(data)

    while (signal === undefined || !signal.aborted) {
      try {
        const response = await fetch(`${this.baseUrl}/subscribe-player-status${query}`, {
          signal,
          headers: { accept: 'text/event-stream' },
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (response.body === null || response.body === undefined) {
          throw new Error('SSE 响应没有流式 body')
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        // SSE 逐字段推送，累计起来再统一应用
        const fields = {}

        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          let splitAt = buffer.indexOf('\n\n')
          while (splitAt >= 0) {
            const block = buffer.slice(0, splitAt)
            buffer = buffer.slice(splitAt + 2)
            const frame = parseSseBlock(block)
            if (frame !== null) {
              fields[frame.event] = normalizeStatusField(frame.event, frame.data)
              handle({ ...fields })
            }
            splitAt = buffer.indexOf('\n\n')
          }
        }
      } catch (error) {
        // 被 stop() 中止是正常路径，不记为错误、不重连
        if (signal !== undefined && signal.aborted) return
        this.lastError = String(error?.message ?? error)
      }

      if (signal !== undefined && signal.aborted) return
      // 断线重连：洛雪重启或连接被中断后自动恢复
      try {
        await new Promise(resolve => setTimeout(resolve, SSE_RETRY_MS))
      } catch {
        return
      }
    }
  }

  /**
   * 抓取并解析当前歌曲歌词（切歌时调用一次）。
   *
   * 端点差异（均已实测，与开放 API 文档的描述不完全一致）：
   *  - `/lyric`      → 200，**纯文本 LRC**（只有原文，不含翻译）
   *  - `/lyric-all`  → 200，JSON `{ lyric, tlyric, rlyric, lxlyric }`
   *  - `/tlyric` `/rlyric` `/lxlyric` → 401，**并不存在**
   *
   * 因此需要翻译时走 `/lyric-all` 一次拿全，不需要时走更轻的 `/lyric`。
   * @param {string} name - 歌曲名，用于防止乱序覆盖。
   */
  async loadLyric(name) {
    if (!this.config.lyrics || this.lyricPending) return
    this.lyricPending = true
    try {
      const wantTranslation = this.config.translation === true
      let text = ''
      let transText = ''

      if (wantTranslation) {
        const response = await this.request('/lyric-all')
        const payload = await response.json()
        text = typeof payload.lyric === 'string' ? payload.lyric : ''
        transText = typeof payload.tlyric === 'string' ? payload.tlyric : ''
        if (text === '') {
          // `/lyric-all` 没给原文时退回 `/lyric`，避免整首歌没歌词
          const fallback = await this.request('/lyric')
          text = (await fallback.text()).trim()
        }
      } else {
        const response = await this.request('/lyric')
        text = (await response.text()).trim()
      }

      if (this.raw.name !== name) return  // 期间又切歌了，丢弃

      const baseLines = parseLrc(text)
      const lines = transText.trim() === ''
        ? mergeTranslation(baseLines, [])
        : mergeTranslation(baseLines, parseLrc(transText))
      this.lyricLines = lines
      this.lyricName = name
    } catch (error) {
      this.lastError = String(error?.message ?? error)
    } finally {
      this.lyricPending = false
    }
  }
}
