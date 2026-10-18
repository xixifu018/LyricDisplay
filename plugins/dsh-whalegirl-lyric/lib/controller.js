/**
 * 洛雪音乐（LX Music）播放状态控制器。
 *
 * 只在 Host 侧轮询，浏览器侧读缓存 —— 多个页面共享同一次轮询。
 * 歌词在切歌时抓取一次并解析成有序行，之后每帧只做二分查找。
 */

import { currentAndNext, parseAwlrc, parseLrc } from './lrc.js'

/** 默认轮询间隔（毫秒）；可被配置项 pollIntervalMs 覆盖。 */
const DEFAULT_POLL_INTERVAL_MS = 500
/** SSE 断线后的重连间隔（毫秒）。 */
const SSE_RETRY_MS = 2000
/**
 * 空歌词的重试次数上限（约 10 秒，按 500ms 轮询算）。
 *
 * ⚠️ 洛雪切歌时 `/status` 先变、`/lyric-all` 后变，此时**连 `lyricLineText` 都是空的**，
 * 不能拿它当"这首歌没歌词"的依据 —— 曾经就是这么误判的（`empty && lyricLineText`
 * 才重试）：切歌后第一次取到空 → 被当成"这首没歌词"缓存 → 整首歌都没歌词。
 * 所以只要解析出 0 行就重试，直到上限。
 */
const LYRIC_RETRY_LIMIT = 20
/** 放弃后若洛雪又出现了"新的当前行"，隔多久再补救一次（毫秒）。 */
const LYRIC_RECHECK_MS = 6000
/** 补救次数上限（防止对真正无歌词的歌无限请求）。 */
const LYRIC_RECHECK_LIMIT = 10
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
    /** 当前这首歌已重试了几次（切歌时归零）。 */
    this.lyricAttempts = 0
    /** 正在重试的歌名（用来判断"换歌了要归零计数"）。 */
    this.attemptName = ''
    /** 上一次**成功接受**的歌词属于哪首歌，用来识别"取到上一首"的残留。 */
    this.acceptedName = ''
    this.acceptedText = ''
    /** 放弃时的 `lyricLineText`：用它判断"后来是不是真的换出了新行"。 */
    this.acceptedLineText = ''
    /** 放弃后的补救次数与上次时间。 */
    this.emptyRechecks = 0
    /** 最近一次取回的歌词原文长度（诊断：区分"取不到"和"解析不出"）。 */
    this.lyricRawLen = -1
    /** 当前歌词是否带字级时间（决定客户端能不能做逐字/气泡）。 */
    this.lyricWordLevel = false
    this.lastRecheckAt = 0
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
   * 取当前行的字级时间；没有音节信息时按字符均分。
   * @param {{ text: string, time: number, end: number, syllables?: {start:number,end:number,text:string}[] }|undefined} line - 当前行。
   * @returns {{ s: number, e: number, t: string }[]} 字/词时间列表。
   */
  /**
   * 两轨（plain LRC 与 AWLRC）是否指向同一份歌词。
   *
   * 判据：行数接近 + 前几行时间戳一致。切歌瞬间 /lyric-all 的
   * lyric 可能是新歌、lxlyric 还是上一首，此时时间戳必然对不上。
   * @param {{time:number}[]} plainLines - lyric 解析结果。
   * @param {{time:number}[]} awLines - lxlyric 解析结果。
   * @returns {boolean} 是否可以安全地用 lxlyric 当声源。
   */
  _sameTiming(plainLines, awLines) {
    if (plainLines.length === 0 || awLines.length === 0) return false;
    const tolerance = Math.max(3, Math.round(plainLines.length * 0.2));
    if (Math.abs(plainLines.length - awLines.length) > tolerance) return false;
    const n = Math.min(4, plainLines.length, awLines.length);
    for (let i = 0; i < n; i += 1) {
      if (Math.abs(plainLines[i].time - awLines[i].time) > 0.08) return false;
    }
    return true;
  }

  _wordsFor(line) {
    if (!line) return [];
    if (Array.isArray(line.syllables) && line.syllables.length > 0) {
      return line.syllables.map((s) => ({ s: s.start, e: s.end, t: s.text }));
    }
    const text = typeof line.text === 'string' ? line.text : '';
    const chars = Array.from(text);
    if (chars.length === 0) return [];
    const from = Number.isFinite(line.time) ? line.time : 0;
    const to = Number.isFinite(line.end) && line.end > from ? line.end : from + chars.length * 0.3;
    const step = (to - from) / chars.length;
    return chars.map((ch, i) => ({ s: from + step * i, e: from + step * (i + 1), t: ch }));
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
      // ---- 逐字歌词带用的字段 ----
      // 当前行的字级时间（绝对秒）：客户端据此在本地按帧插值，不必每帧问宿主。
      // 没有字级时间（普通 LRC）时退化为"按字符均分整行时长"，
      // 这样背景歌词带仍然能逐字亮起，只是节奏不如 AWLRC 准。
      words: this._wordsFor(line),
      lineStart: line?.time ?? 0,
      lineEnd: line?.end ?? 0,
      wordLevel: this.lyricWordLevel,
      // 气泡是否显示歌词（关掉时背景带仍然工作，两者独立）
      lyricsEnabled: this.config.lyrics !== false,
      band: {
        enabled: this.config.band !== false,
        opacity: Number.isFinite(this.config.bandOpacity) ? this.config.bandOpacity : 0.8,
      },
      // 诊断用：确认宿主跑的是哪一版取词逻辑（客户端会忽略未知字段）
      lyricRevision: 2,
      lyricAttempts: this.lyricAttempts,
      lyricName: this.lyricName,
      // 最近一次取回的原文长度：>0 但 lyricCount=0 说明是**解析**问题，
      // =0 说明是**取不到**（洛雪那边还没就绪）。
      lyricRawLen: this.lyricRawLen,
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
      // 换歌了：先清掉上一首的歌词，避免新歌词就绪前把旧的当成新歌显示
      this.lyricLines = []
      // 重试计数归零，然后尝试取歌词。
      // 失败（空/上一首）时 `loadLyric` 不会写 `lyricName`，
      // 于是下一轮轮询会再调一次 —— 这就是重试机制本身。
      if (this.attemptName !== this.raw.name) {
        this.attemptName = this.raw.name
        this.lyricAttempts = 0
        this.emptyRechecks = 0
        this.acceptedLineText = ''
      }
      void this.loadLyric(this.raw.name)
      return
    }

    // 晚到补救：已经判定"这首没歌词"，但洛雪后来又换出了**新的**当前行
    // （说明歌词其实到了），隔段时间再试一次。用 `acceptedLineText` 比对，
    // 真正的纯音乐（行文本一直是同一句，如"纯音乐，请欣赏"）不会触发。
    if (
      this.raw.name !== ''
      && this.lyricLines.length === 0
      && this.raw.lyricLineText.trim() !== ''
      && this.raw.lyricLineText !== this.acceptedLineText
      && this.emptyRechecks < LYRIC_RECHECK_LIMIT
      && Date.now() - this.lastRecheckAt >= LYRIC_RECHECK_MS
    ) {
      this.emptyRechecks += 1
      this.lastRecheckAt = Date.now()
      this.lyricAttempts = 0
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
    // ⚠️ 只要**任一**消费者需要歌词就要取：
    //   - `lyrics`  → 气泡里那句
    //   - `band`    → 标题栏背景歌词带（要逐字时间）
    // 以前只判断 `lyrics`，于是关掉"气泡里显示歌词"时背景带也跟着消失（踩过）。
    const wantBubble = this.config.lyrics !== false
    const wantBand = this.config.band !== false
    if ((!wantBubble && !wantBand) || this.lyricPending) return
    this.lyricPending = true
    try {
      const wantTranslation = this.config.translation === true
      let text = ''
      let transText = ''
      let awlrc = ''

      if (wantTranslation) {
        const response = await this.request('/lyric-all')
        const payload = await response.json()
        text = typeof payload.lyric === 'string' ? payload.lyric : ''
        transText = typeof payload.tlyric === 'string' ? payload.tlyric : ''
        // 逐字轨：有它才能做字级高亮/气泡
        awlrc = typeof payload.lxlyric === 'string' ? payload.lxlyric : ''
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

      this.lyricRawLen = text.length
      // 优先逐字轨：只有它能给出每个字的起止时间。
      //
      // ⚠️ **必须校验两轨是否属于同一首歌**。实测切歌瞬间 `/lyric-all` 的
      //    `lyric` 与 `lxlyric` 会短暂不同步：前者已是新歌、后者还是上一首。
      //    只拿 `lyric` 判归属的话，就会把**上一首的逐字轨**当成新歌的缓存下来
      //    —— 表现为"切歌后歌词还是上一首的"（真实踩过）。
      const plainLines = parseLrc(text)
      const awlrcLines = parseAwlrc(awlrc)
      const awUsable = awlrcLines.length > 0 && this._sameTiming(plainLines, awlrcLines)
      const inconsistent = awlrcLines.length > 0 && plainLines.length > 0 && !awUsable
      this.lyricWordLevel = awUsable
      const baseLines = awUsable ? awlrcLines : plainLines
      const lines = transText.trim() === ''
        ? mergeTranslation(baseLines, [])
        : mergeTranslation(baseLines, parseLrc(transText))
      if (awUsable) {
        // mergeTranslation 会复制对象，音节字段要保留
        for (let i = 0; i < lines.length; i += 1) lines[i].syllables = baseLines[i].syllables
      }

      // ⚠️ 三种"还不能用"的结果，都不能写 `lyricName`（写了就再也不重取）：
      //   - 解析出 0 行：切歌瞬间 `/lyric-all` 常常还是空的，
      //     **此时 `lyricLineText` 往往也是空的**，所以不能拿它当"没歌词"的依据
      //   - 取到的原文与上一次**成功接受**的那首一字不差（= 还是上一首的残留）
      //   - 两轨时间轴对不上（= `lxlyric` 还是上一首的）
      const empty = lines.length === 0
      const stale = !empty && text !== ''
        && text === this.acceptedText && name !== this.acceptedName
      if ((empty || stale || inconsistent) && this.lyricAttempts < LYRIC_RETRY_LIMIT) {
        this.lyricAttempts += 1
        return
      }
      if (empty || stale) {
        // 重试用尽：接受"没有歌词"（残留则丢掉，宁可没有也不显示错的）
        this.lyricLines = []
        this.lyricName = name
        this.acceptedLineText = this.raw.lyricLineText
        return
      }
      // 走这里有两种情况：完全正常；或"两轨对不上但重试用尽"——
      // 后者已经在上面退回 `plainLines`，所以显示的是正确的歌词，只是没有逐字时间。

      this.lyricLines = lines
      this.lyricName = name
      this.lyricAttempts = 0
      this.emptyRechecks = 0
      this.acceptedName = name
      this.acceptedText = text
      this.acceptedLineText = this.raw.lyricLineText
    } catch (error) {
      this.lastError = String(error?.message ?? error)
    } finally {
      this.lyricPending = false
    }
  }
}
