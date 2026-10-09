/**
 * LRC 歌词解析（移植自项目中已验证的 Python 实现）。
 *
 * 关键点：时间标签的小数位允许 1~3 位，分隔符允许 `.` 或 `:`。
 * 只接受 2~3 位小数的实现会静默丢弃 `[00:42.6]` 这类行，表现为歌词卡住不动。
 */

/** 时间标签：[mm:ss] / [mm:ss.x] / [mm:ss.xx] / [mm:ss.xxx]，分隔符 . 或 : */
const TIME_TAG_RE = /\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g
/** 元数据标签：[ar:xxx] [ti:xxx] [offset:xxx] 等 */
const META_TAG_RE = /^\[([a-zA-Z]+):(.+)\]$/

/**
 * 解析 LRC 文本。
 * @param {string} text - 原始 LRC 歌词。
 * @returns {{ time: number, text: string }[]} 按时间升序排列的歌词行。
 */
export function parseLrc(text) {
  const lines = []
  if (typeof text !== 'string' || text === '') return lines

  let offset = 0

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (line === '') continue

    const meta = META_TAG_RE.exec(line)
    if (meta !== null) {
      if (meta[1].toLowerCase() === 'offset') {
        const parsed = Number.parseInt(meta[2], 10)
        // 洛雪/酷狗 的 offset 单位是毫秒
        if (Number.isFinite(parsed)) offset = parsed / 1000
      }
      continue
    }

    TIME_TAG_RE.lastIndex = 0
    const tags = [...line.matchAll(TIME_TAG_RE)]
    if (tags.length === 0) continue

    for (let i = 0; i < tags.length; i += 1) {
      const tag = tags[i]
      const from = tag.index + tag[0].length
      // 一个时间标签的作用域直到下一个标签为止；最后一个标签直接取到行尾。
      // 这样 [t1][t2]共享正文 与 [t1]正文A[t2]正文B 两种写法都能正确解析。
      const to = i + 1 < tags.length ? tags[i + 1].index : line.length
      const body = line.slice(from, to).trim()

      const minutes = Number.parseInt(tag[1], 10)
      const seconds = Number.parseInt(tag[2], 10)
      const fracStr = tag[3] ?? '0'
      // 1 位=十分之一，2 位=百分之一，3 位=千分之一
      const frac = Number.parseInt(fracStr, 10) / 10 ** fracStr.length
      lines.push({ time: minutes * 60 + seconds + frac + offset, text: body })
    }
  }

  lines.sort((a, b) => a.time - b.time)
  return lines
}

/**
 * 二分查找：返回时间戳 <= progress 的最后一行下标；没有则返回 -1。
 * @param {{ time: number }[]} lines - 升序歌词行。
 * @param {number} progress - 播放进度（秒）。
 * @returns {number} 命中的下标或 -1。
 */
export function indexAt(lines, progress) {
  if (lines.length === 0 || !(progress >= 0)) return -1

  let lo = 0
  let hi = lines.length - 1
  let found = -1

  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid].time <= progress) {
      found = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }

  return found
}

/**
 * 取当前句与下一句。
 * @param {{ time: number, text: string }[]} lines - 升序歌词行。
 * @param {number} progress - 播放进度（秒）。
 * @returns {{ current: string, next: string, index: number }} 当前句、下一句与当前行下标。
 */
export function currentAndNext(lines, progress) {
  const index = indexAt(lines, progress)
  if (index < 0) {
    // 还没到第一句：网易云习惯先显示第一句作为提示
    return { current: '', next: lines.length > 0 ? lines[0].text : '', index: -1 }
  }
  return {
    current: lines[index].text,
    next: index + 1 < lines.length ? lines[index + 1].text : '',
    index,
  }
}
