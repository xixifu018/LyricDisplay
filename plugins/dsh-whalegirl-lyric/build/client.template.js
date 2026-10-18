window.__ModuleLoader__.load({
	id: "dsh-whalegirl-lyric",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react = require("react");
		// 显式解构用到的 hook，避免依赖 require 返回对象的形状
		var useState = react.useState;
		var useEffect = react.useEffect;
		var useRef = react.useRef;

		//#region 常量
		/** 路由命名空间，与 Host 半边保持一致。 */
		var NS = "dsh-whalegirl-lyric";
		/** 状态接口。 */
		var STATE_API = "/api/" + NS + "/state";
		/** 控制接口。 */
		var CONTROL_API = "/api/" + NS + "/control";
		/** 配置读写接口（设置页用）。 */
		var CONFIG_API = "/api/" + NS + "/config";
		/** 轮询间隔：略快于 Host 的 500ms，让进度条更顺。 */
		var POLL_MS = 300;
		/** 隐藏状态在 localStorage 中的键。 */
		var HIDE_KEY = NS + ":hidden";
		/** 控制区折叠状态在 localStorage 中的键。 */
		var COMPACT_KEY = NS + ":compact";
		/** 拖动位置在 localStorage 中的键。 */
		var POS_KEY = NS + ":pos";
		/** 挂件与视口边缘的默认间距（CSS 里也用这个值）。 */
		var EDGE_GAP = 12;
		/**
		 * 鲸鱼娘素材。构建脚本把真实的 PNG data URL 注入到这个占位符位置。
		 * 内嵌而非走 HTTP 子路径路由：DSH 对 `/api/<ns>/<子路径>` 会返回 401，
		 * 内嵌同时让插件自包含，不依赖任何外部文件。
		 */
		var FIGURE_URL = "__WHALEGIRL_DATA_URL__";

		//#region 小工具
		/**
		 * 秒数格式化为 mm:ss。
		 * @param {number} seconds - 秒数。
		 * @returns {string} 时间文本。
		 */
		function formatTime(seconds) {
			if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
			var total = Math.floor(seconds);
			var minutes = Math.floor(total / 60);
			var rest = total % 60;
			return minutes + ":" + (rest < 10 ? "0" : "") + rest;
		}

		/**
		 * 注入全局关键帧动画，返回清理函数。
		 * @returns {() => void} 清理函数。
		 */
		function installGlobalStyles() {
			var style = document.createElement("style");
			style.textContent = [
				"@keyframes dshWgRise{from{opacity:0;transform:translateY(9px) scale(.97)}to{opacity:1;transform:none}}",
				"@keyframes dshWgPulse{0%,100%{opacity:.35;transform:translateY(0)}50%{opacity:1;transform:translateY(-3px)}}",
				"@keyframes dshWgFloat{0%,100%{transform:translateY(0) rotate(-1.2deg)}50%{transform:translateY(-6px) rotate(1.2deg)}}",
				// 歌曲名超长时来回滚动；距离由组件按实际溢出量写入 --dshWgMarqueeDx
				"@keyframes dshWgMarquee{0%{transform:translateX(0)}100%{transform:translateX(var(--dshWgMarqueeDx,0))}}",
			].join("");
			document.head.appendChild(style);
			return function () {
				style.remove();
			};
		}

		/**
		 * 读取持久化的显示状态。
		 * @returns {boolean} true 表示挂件被收起。
		 */
		function readHidden() {
			try {
				return window.localStorage.getItem(HIDE_KEY) === "1";
			} catch (error) {
				return false;
			}
		}

		/**
		 * 读取拖动后的位置偏移。
		 * @returns {{ dx: number, dy: number }} 相对默认右下角的偏移（像素）。
		 */
		function readPos() {
			try {
				var raw = window.localStorage.getItem(POS_KEY);
				if (raw === null) return { dx: 0, dy: 0 };
				var parsed = JSON.parse(raw);
				var dx = Number(parsed && parsed.dx);
				var dy = Number(parsed && parsed.dy);
				return {
					dx: Number.isFinite(dx) ? dx : 0,
					dy: Number.isFinite(dy) ? dy : 0,
				};
			} catch (error) {
				return { dx: 0, dy: 0 };
			}
		}

		/**
		 * 写入拖动后的位置偏移。
		 * @param {{ dx: number, dy: number }} pos - 偏移量。
		 */
		function writePos(pos) {
			try {
				window.localStorage.setItem(POS_KEY, JSON.stringify(pos));
			} catch (error) {
				/* 隐私模式下忽略 */
			}
		}

		/**
		 * 把位置偏移转成内联样式（两个 CSS 变量）。
		 * @param {{ dx: number, dy: number }} pos - 偏移量。
		 * @returns {Record<string, string>} React style 对象。
		 */
		function posStyle(pos) {
			return {
				"--dshWgRight": pos.dx + "px",
				"--dshWgBottom": pos.dy + "px",
			};
		}

		/**
		 * 写入持久化的显示状态。
		 * @param {boolean} value - 是否收起。
		 */
		function writeHidden(value) {
			try {
				window.localStorage.setItem(HIDE_KEY, value ? "1" : "0");
			} catch (error) {
				/* 隐私模式下忽略 */
			}
		}

		/**
		 * 读取控制区折叠状态。默认收起：只显示鲸鱼娘，左侧控制区整列收掉。
		 * 用户一旦手动展开过，就尊重那次选择。
		 * @returns {boolean} true 表示控制区已折叠。
		 */
		function readCompact() {
			try {
				return window.localStorage.getItem(COMPACT_KEY) !== "0";
			} catch (error) {
				return true;
			}
		}

		/**
		 * 写入控制区折叠状态。
		 * @param {boolean} value - 是否折叠。
		 */
		function writeCompact(value) {
			try {
				window.localStorage.setItem(COMPACT_KEY, value ? "1" : "0");
			} catch (error) {
				/* 隐私模式下忽略 */
			}
		}

		/**
		 * 构造同源封面代理地址。
		 * 洛雪的 picUrl 指向第三方图床，直接加载容易被防盗链拒绝，因此经 Host 中转。
		 * @param {string} picUrl - 洛雪返回的封面地址。
		 * @returns {string} 同源代理地址。
		 */
		function coverSrc(picUrl) {
			return STATE_API + "?cover=" + encodeURIComponent(picUrl);
		}

		/**
		 * 取字符串首字符（用于无封面时的占位字），不依赖代码点语义。
		 * @param {string} text - 源文本。
		 * @returns {string} 首字符，空串输入返回空串。
		 */
		function firstChar(text) {
			if (typeof text !== "string" || text.length === 0) return "";
			return text[0] === undefined ? "" : text[0];
		}

		//#region 样式
		/**
		 * 组件样式表。
		 * 说明：`shell.overlay` 整层是点击穿透的，因此交互元素必须自己开 pointer-events。
		 * 明暗主题都读 --dsw-* 设计令牌，不写死颜色。
		 */
		var CSS = [
			// 整体尺寸刻意压小：默认态只有 214×202，展开控制区也才 372×202，
			// 避免浮窗挡住会话内容。
			// 位置由两种方式共同决定：CSS 里的默认右下角间距 12px，
			// 加上拖动后写入的 --dshWgRight / --dshWgBottom 偏移（默认 0）。
			// 用 calc 而不是直接改 right，是为了让「默认位置」在 CSS 里保持可读、可断言。
			".dshWg_root{position:fixed;right:calc(var(--dshWgRight,0px) + 12px);bottom:calc(var(--dshWgBottom,0px) + 12px);z-index:40;pointer-events:auto;font-family:inherit;user-select:none;-webkit-user-select:none;cursor:grab;touch-action:none}",
			".dshWg_root[data-dragging='true']{cursor:grabbing}",
			// 控制区在左、鲸鱼娘在右；两者底部对齐
			".dshWg_card{position:relative;display:flex;align-items:flex-end;gap:8px;padding:8px;border-radius:13px;border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-overlay);box-shadow:0 6px 20px rgba(0,0,0,.3);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}",
			".dshWg_hide{position:absolute;top:-6px;right:-6px;width:16px;height:16px;border:1px solid var(--dsw-alias-border-l1);border-radius:50%;background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-secondary);font-size:11px;line-height:1;cursor:pointer;opacity:0;transition:opacity .18s;pointer-events:auto;padding:0}",
			".dshWg_card:hover .dshWg_hide{opacity:1}",
			".dshWg_hide:hover{color:var(--dsw-alias-state-error-primary)}",
			".dshWg_stage{position:relative;flex:none;width:160px;height:170px}",
			// 折叠 = 左侧控制区整列真正收掉，卡片只剩鲸鱼娘那部分的宽度。
			// 宽度账：
			//   展开 8 + 160 + 8 + 170 + 8 = 354…（含折叠开关列后为 372）
			//   折叠 8 + 14 - 5 + 8 + 170 + 8 = 203…（含折叠开关列后为 214）
			// 卡片锚定右下角，因此折叠时只是左边收回来，鲸鱼娘在屏幕上的位置不变。
			".dshWg_card.dshWg_compact .dshWg_bar{visibility:hidden;width:0;overflow:hidden}",
			// 折叠开关：负外边距抵消卡片内边距，贴在左边缘；折叠后自己成为最左列
			".dshWg_collapse{flex:none;align-self:flex-start;width:14px;height:14px;margin:1px 0 0 -5px;display:flex;align-items:center;justify-content:center;border:none;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer;padding:0;opacity:.5;transition:opacity .15s,color .15s;pointer-events:auto}",
			".dshWg_card:hover .dshWg_collapse{opacity:1}",
			// 收起态下必须常显：否则用户看不出这里能展开
			".dshWg_card[data-compact='true'] .dshWg_collapse{opacity:.85}",
			".dshWg_collapse:hover{color:var(--dsw-alias-brand-primary)}",
			".dshWg_figure{position:absolute;left:0;right:0;bottom:0;top:20px;background-repeat:no-repeat;background-size:contain;background-position:center bottom;animation:dshWgFloat 5.2s ease-in-out infinite;transform-origin:50% 88%}",
			".dshWg_card[data-playing='false'] .dshWg_figure{animation-play-state:paused;filter:saturate(.7) brightness(.92)}",
			// 气泡钉在右上角（与鲸鱼娘头部同侧），尾巴朝下指向她的头
			".dshWg_bubble{position:absolute;right:0;top:0;z-index:2;width:148px;box-sizing:border-box;padding:6px 8px;border-radius:10px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);box-shadow:0 4px 12px rgba(0,0,0,.2)}",
			".dshWg_bubble:after{content:'';position:absolute;left:22px;bottom:-5px;width:9px;height:9px;background:inherit;border-right:1px solid var(--dsw-alias-border-l2);border-bottom:1px solid var(--dsw-alias-border-l2);transform:rotate(45deg);border-bottom-right-radius:2px}",
			".dshWg_line{font-size:11px;font-weight:600;line-height:1.35;color:var(--dsw-alias-label-primary);word-break:break-word;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}",
			".dshWg_trans{margin-top:2px;font-size:9.5px;line-height:1.3;color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
			".dshWg_next{margin-top:3px;font-size:9.5px;line-height:1.3;color:var(--dsw-alias-label-secondary);opacity:.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
			".dshWg_rise{animation:dshWgRise .34s cubic-bezier(.22,1,.36,1)}",
			".dshWg_dots{display:flex;align-items:center;gap:3px;height:15px}",
			".dshWg_dots i{width:4px;height:4px;border-radius:50%;background:var(--dsw-alias-brand-primary);animation:dshWgPulse 1.25s ease-in-out infinite}",
			".dshWg_dots i:nth-child(2){animation-delay:.16s}",
			".dshWg_dots i:nth-child(3){animation-delay:.32s}",
			".dshWg_idle{font-size:10px;color:var(--dsw-alias-label-secondary);height:15px;line-height:15px}",
			// 控制区：封面在上，轨道信息与按钮贴底
			// 左列内容整体居中（封面、歌曲名、进度区、按钮都居中）
			".dshWg_bar{flex:none;width:126px;height:170px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;padding-bottom:0}",
			".dshWg_cover{width:90px;max-width:100%;aspect-ratio:1/1;flex:none;display:flex;align-items:center;justify-content:center;border-radius:9px;overflow:hidden;border:1px solid var(--dsw-alias-border-l1);background:linear-gradient(150deg,var(--dsw-alias-bg-layer-2),var(--dsw-alias-bg-layer-1))}",
			".dshWg_coverImg{width:100%;height:100%;object-fit:cover;display:block}",
			".dshWg_coverNote{font-size:26px;font-weight:600;color:var(--dsw-alias-label-secondary);opacity:.5;line-height:1}",
			".dshWg_buttons{display:flex;align-items:center;justify-content:center;gap:5px}",
			".dshWg_btn{flex:none;width:21px;height:21px;display:flex;align-items:center;justify-content:center;border:1px solid var(--dsw-alias-border-l1);border-radius:7px;background:transparent;color:var(--dsw-alias-label-primary);cursor:pointer;padding:0;transition:background .15s,color .15s}",
			".dshWg_btn:hover{background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-brand-primary)}",
			".dshWg_btn:disabled{opacity:.42;cursor:default}",
			".dshWg_play{width:26px;height:26px;border-radius:50%;background:var(--dsw-alias-brand-primary);color:#fff;border-color:transparent}",
			".dshWg_play:hover{background:var(--dsw-alias-brand-primary);color:#fff;filter:brightness(1.12)}",
			".dshWg_rail{display:flex;flex-direction:column;align-items:center;min-width:0}",
			// 歌曲名锁定行宽；超长时由内层滚动显示（滚动距离与时长由组件按实际溢出量注入）
			".dshWg_track{width:110px;font-size:9.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;margin-bottom:3px}",
			".dshWg_trackScroll{display:inline-block;white-space:nowrap;will-change:transform}",
			".dshWg_trackScroll[data-scroll='true']{animation:dshWgMarquee var(--dshWgMarqueeDur,14s) linear infinite alternate}",
			".dshWg_track:hover .dshWg_trackScroll[data-scroll='true']{animation-play-state:paused}",
			".dshWg_track b{color:var(--dsw-alias-label-primary);font-weight:600}",
			// 进度区：上排「已播时间 —— 总时长」，下排通栏进度条。
			// 注意：不要把时间放在进度条左右两侧 —— 两个时间标签就占约 46px，
			// 加上进度条会超出控制列内宽，行溢出后视觉上会盖住鲸鱼娘。
			".dshWg_progressRow{display:flex;flex-direction:column;align-items:center;gap:3px}",
			".dshWg_timeRow{display:flex;align-items:center;justify-content:space-between;width:110px}",
			".dshWg_time{flex:none;font-size:8.5px;color:var(--dsw-alias-label-secondary);font-variant-numeric:tabular-nums;line-height:1}",
			// 进度条锁定 110 宽，不参与弹性伸缩：内部百分比填充的基准一旦漂移就会漫出列外
			".dshWg_progress{position:relative;flex:none;width:110px;height:3px;border-radius:2px;background:var(--dsw-alias-border-l1);overflow:hidden}",
			".dshWg_fill{position:absolute;left:0;top:0;bottom:0;border-radius:2px;background:var(--dsw-alias-brand-primary);transition:width .3s linear}",
			// 收起态：文字在左、圆形头像在右，与展开态的左右关系保持一致
			".dshWg_dock{position:fixed;right:calc(var(--dshWgRight,0px) + 12px);bottom:calc(var(--dshWgBottom,0px) + 12px);z-index:40;pointer-events:auto;display:flex;align-items:center;gap:6px;padding:4px 4px 4px 9px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-overlay);box-shadow:0 5px 16px rgba(0,0,0,.26);cursor:grab;color:var(--dsw-alias-label-primary);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);user-select:none;-webkit-user-select:none;touch-action:none}",
			".dshWg_dock[data-dragging='true']{cursor:grabbing}",
			".dshWg_dock:hover{border-color:var(--dsw-alias-brand-primary)}",
			".dshWg_dockFace{width:22px;height:22px;border-radius:50%;flex:none;background-repeat:no-repeat;background-size:cover;background-position:center 18%;border:1px solid var(--dsw-alias-border-l2)}",
			".dshWg_dockText{font-size:10px;max-width:88px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
			".dshWg_dockDot{width:5px;height:5px;border-radius:50%;flex:none;background:var(--dsw-alias-state-idle-primary)}",
			".dshWg_dock[data-playing='true'] .dshWg_dockDot{background:var(--dsw-alias-state-success-primary)}",

			// ---- 背景歌词带（会话标题栏）----
			// 关键：root 加 isolation:isolate 建独立层叠上下文，
			// 否则 z-index:-1 会跑到 root 的不透明背景后面，歌词整条看不见。
			"[data-dsh-lyric-host]{isolation:isolate}",
			// 只加定位：overflow 交给带子自己裁，免得把宿主标题栏里的弹层/焦点框剪掉
			"[data-dsh-lyric-band]{position:relative !important}",
			".dshLyricBand{position:absolute;inset:0;z-index:-1;pointer-events:none;display:flex;align-items:center;justify-content:center;padding:0 24px;overflow:hidden;"
				+ "-webkit-mask-image:linear-gradient(90deg,transparent 0,#000 5%,#000 95%,transparent 100%);"
				+ "mask-image:linear-gradient(90deg,transparent 0,#000 5%,#000 95%,transparent 100%)}",
			// 字号不宜过大：长句要能在"标题与按钮之间"放得下（23px 时 ~30 字仍可容纳）。
			// ⚠️ 两个都不能少：
			//   - line-height:1.5 —— 默认 1.2 时 g/y 这类下伸部会被裁掉（真实踩过）
			//   - 不要 overflow:hidden —— 那会按行盒裁字，下伸部同样被切
			// 长句由 `fitBandLine()` 自动缩字号，所以不靠裁切来兜底
			".dshLyricBand__line{position:relative;max-width:64%;white-space:nowrap;"
				+ "font-size:23px;font-weight:800;letter-spacing:.04em;line-height:1.5;padding-bottom:6px;"
				+ "color:var(--dsw-alias-label-primary,#e8e8e8)}",
			// 颜色由 JS 逐字写（每个字一种糖果色），这里只保留排版属性
			".dshLyricBand__ch{display:inline-block;will-change:color}",
			// 悬浮播放控制：挂在 shell.overlay 层（和挂件按钮同一层，可点击），
			// 用 fixed 定位贴到歌词文字右侧。**不要放进标题栏** ——
			// 那里是 Electron 的窗口拖拽区（-webkit-app-region: drag），
			// 落在里面的按钮收不到点击（真实踩过两次）。
			".dshWg_transport{position:fixed;z-index:41;display:flex;align-items:center;gap:4px;"
				+ "padding:4px 6px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);"
				+ "background:var(--dsw-alias-bg-overlay);box-shadow:0 4px 14px rgba(0,0,0,.28);"
				+ "backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);"
				+ "-webkit-app-region:no-drag;user-select:none}",
			".dshWg_transportBtn{width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;"
				+ "border:none;border-radius:50%;padding:0;cursor:pointer;font-size:12px;line-height:1;"
				+ "background:transparent;color:var(--dsw-alias-label-primary)}",
			".dshWg_transportBtn:hover{background:var(--dsw-alias-bg-layer-2)}",
			".dshWg_transportBtn:disabled{opacity:.5;cursor:default}",

			// 光标横条：只在"当前正在唱的那个字"下方，像终端里的输入光标
			".dshLyricBand__caret{position:absolute;bottom:2px;left:0;width:0;height:3px;border-radius:2px;"
				+ "background:currentColor;opacity:.95;display:none;will-change:left,width,color;"
				+ "animation:dshLyricCaret 1.1s ease-in-out infinite}",
			"@keyframes dshLyricCaret{0%,100%{opacity:.95}50%{opacity:.55}}",

			// ---- 设置页（设置 → 鲸鱼娘歌词）----
			".dshWgSet{display:flex;flex-direction:column;gap:16px;max-width:560px;padding:4px 2px 24px;"
				+ "color:var(--dsw-alias-label-primary);font-size:13px}",
			".dshWgSet_row{display:flex;flex-direction:column;gap:6px}",
			".dshWgSet_label{font-size:13px;font-weight:600}",
			".dshWgSet_hint{font-size:11px;color:var(--dsw-alias-label-tertiary);line-height:1.5}",
			".dshWgSet_input{width:100%;box-sizing:border-box;padding:6px 9px;border-radius:6px;"
				+ "border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);"
				+ "color:var(--dsw-alias-label-primary);font:inherit}",
			".dshWgSet_input:focus{outline:none;border-color:var(--dsw-alias-brand-primary)}",
			".dshWgSet_check{display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer}",
			".dshWgSet_actions{display:flex;align-items:center;gap:12px;margin-top:4px}",
			".dshWgSet_btn{border:none;border-radius:6px;padding:7px 16px;font:inherit;cursor:pointer;"
				+ "background:var(--dsw-alias-brand-primary);color:#fff}",
			".dshWgSet_btn:disabled{opacity:.55;cursor:default}",
			".dshWgSet_note{font-size:12px;color:var(--dsw-alias-label-secondary)}",
			".dshWgSet_note[data-error='true']{color:var(--dsw-alias-state-error-primary)}",
		].join("");

		//#region 图标
		/**
		 * 绘制一个线性图标。
		 * @param {{ size?: number, children: unknown }} props - 尺寸与路径。
		 * @returns {unknown} React 元素。
		 */
		function IconGlyph(props) {
			var size = props.size === undefined ? 12 : props.size;
			return react.createElement(
				"svg",
				{
					viewBox: "0 0 24 24",
					width: size,
					height: size,
					fill: "none",
					stroke: "currentColor",
					strokeWidth: 2,
					strokeLinecap: "round",
					strokeLinejoin: "round",
					"aria-hidden": "true",
				},
				props.children,
			);
		}

		/** @returns {unknown} 上一首图标。 */
		function IconPrev() {
			return react.createElement(
				IconGlyph,
				null,
				react.createElement("path", { key: "a", d: "M18 5v14L8 12z" }),
				react.createElement("path", { key: "b", d: "M6 5v14" }),
			);
		}

		/** @returns {unknown} 下一首图标。 */
		function IconNext() {
			return react.createElement(
				IconGlyph,
				null,
				react.createElement("path", { key: "a", d: "M6 5v14l10-7z" }),
				react.createElement("path", { key: "b", d: "M18 5v14" }),
			);
		}

		/** @returns {unknown} 播放图标。 */
		function IconPlay() {
			return react.createElement(
				IconGlyph,
				{ size: 13 },
				react.createElement("path", { key: "a", d: "M7 4.5v15l12-7.5z" }),
			);
		}

		/** @returns {unknown} 暂停图标。 */
		function IconPause() {
			return react.createElement(
				IconGlyph,
				{ size: 13 },
				react.createElement("path", { key: "a", d: "M8.5 4.5v15" }),
				react.createElement("path", { key: "b", d: "M15.5 4.5v15" }),
			);
		}

		/** @returns {unknown} 折叠/展开控制区的指示箭头。 */
		function IconChevron(props) {
			return react.createElement(
				IconGlyph,
				{ size: 12 },
				react.createElement("path", {
					key: "a",
					d: props.pointing === "right" ? "M9 6l6 6-6 6" : "M15 6l-6 6 6 6",
				}),
			);
		}

		//#region 子组件
		/**
		 * 歌词气泡：钉在挂件左上角，切句时重放升起动画。
		 * @param {{ data: object | undefined, error: string }} props - 状态与错误。
		 * @returns {unknown} React 元素。
		 */
		function LyricBubble(props) {
			var data = props.data;
			// 设置里关掉「气泡里显示歌词」时，气泡只显示歌名（背景歌词带仍然独立工作）
			var showLyric = data?.lyricsEnabled !== false;
			var lyric = showLyric && typeof data?.lyric === "string" ? data.lyric : "";
			var translation = showLyric && typeof data?.translation === "string" ? data.translation : "";
			var next = showLyric && typeof data?.next === "string" ? data.next : "";

			var body;
			if (lyric !== "") {
				body = [
					react.createElement("div", { key: "l", className: "dshWg_line" }, lyric),
					translation !== ""
						? react.createElement("div", { key: "t", className: "dshWg_trans" }, translation)
						: null,
					next !== ""
						? react.createElement("div", { key: "n", className: "dshWg_next" }, next)
						: null,
				];
			} else if (props.error !== "") {
				body = react.createElement("div", { className: "dshWg_idle" }, "未连接到洛雪音乐");
			} else if (data === undefined) {
				body = react.createElement("div", { className: "dshWg_idle" }, "连接中…");
			} else if (data.name !== "") {
				body = react.createElement(
					"div",
					{ className: "dshWg_line" },
					data.name,
					data.singer !== "" ? " — " + data.singer : "",
				);
			} else {
				body = react.createElement(
					"div",
					{ className: "dshWg_dots" },
					react.createElement("i", { key: "1" }),
					react.createElement("i", { key: "2" }),
					react.createElement("i", { key: "3" }),
				);
			}

			return react.createElement(
				"div",
				{ className: "dshWg_bubble" },
				react.createElement(
					"div",
					// key 变化驱动重挂载，从而重放切入动画
					{ key: lyric === "" ? "__empty" : lyric, className: "dshWg_rise" },
					body,
				),
			);
		}

		/**
		 * 歌曲封面。放在控制区上方，把原本空着的左上角利用起来。
		 * 加载失败或没有封面时退化为一块带占位文字的渐变方块，布局不塌。
		 * @param {{ picUrl: string, name: string }} props - 封面地址与歌名。
		 * @returns {unknown} React 元素。
		 */
		function CoverArt(props) {
			var failed = react.useState(false);
			var broken = failed[0];
			var setBroken = failed[1];

			// 换歌时重置错误状态，否则上一张的失败会一直沿用
			react.useEffect(
				function () {
					setBroken(false);
				},
				[props.picUrl],
			);

			var showImage = props.picUrl !== "" && !broken;
			var children = showImage
				? [
						react.createElement("img", {
							key: "img",
							className: "dshWg_coverImg",
							src: coverSrc(props.picUrl),
							alt: "",
							draggable: false,
							onError: function () {
								setBroken(true);
							},
						}),
					]
				: [
						react.createElement(
							"span",
							{ key: "ph", className: "dshWg_coverNote" },
							firstChar(props.name) || "♪",
						),
					];

			return react.createElement("div", { className: "dshWg_cover" }, children);
		}

		/**
		 * 播放控制条。
		 * @param {{ playing: boolean, disabled: boolean, onControl: (action: string) => void, name: string, singer: string, progress: number, duration: number, picUrl: string }} props - 控制面。
		 * @returns {unknown} React 元素。
		 */
		function ControlBar(props) {
			var ratio = props.duration > 0 ? Math.max(0, Math.min(1, props.progress / props.duration)) : 0;

			// 歌曲名超出可视宽度时来回滚动。距离按内层实际宽度与容器宽度之差计算，
			// 因此中文/英文、粗体与否都能算准；歌名变化后重新测量。
			var trackRef = useRef(null);
			var dxState = useState(0);
			var marqueeDx = dxState[0];
			var setMarqueeDx = dxState[1];

			useEffect(
				function () {
					var el = trackRef.current;
					if (el === null || el === undefined) return;
					var overflow = el.scrollWidth - el.clientWidth;
					// 1px 容差，避免刚好贴边时抖动
					setMarqueeDx(overflow > 1 ? overflow : 0);
				},
				[props.name, props.singer],
			);

			var scrolling = marqueeDx > 0;
			// 约 26px/s，最少 10s，避免长标题滚得太快
			var durationSec = Math.max(10, Math.round(marqueeDx / 26) * 2);

			return react.createElement(
				"div",
				{ className: "dshWg_bar" },
				react.createElement(CoverArt, { picUrl: props.picUrl, name: props.name }),
				react.createElement(
					"div",
					{ className: "dshWg_rail" },
					react.createElement(
						"div",
						{ className: "dshWg_track", ref: trackRef },
						react.createElement(
							"span",
							{
								className: "dshWg_trackScroll",
								"data-scroll": String(scrolling),
								style: {
									"--dshWgMarqueeDx": (scrolling ? -marqueeDx : 0) + "px",
									"--dshWgMarqueeDur": durationSec + "s",
								},
							},
							props.name === ""
								? "洛雪音乐未在播放"
								: react.createElement(
										"span",
										null,
										react.createElement("b", null, props.name),
										props.singer !== "" ? " · " + props.singer : "",
									),
						),
					),
					react.createElement(
						"div",
						{ className: "dshWg_progressRow" },
						react.createElement(
							"div",
							{ className: "dshWg_timeRow" },
							react.createElement("div", { className: "dshWg_time" }, formatTime(props.progress)),
							react.createElement("div", { className: "dshWg_time" }, formatTime(props.duration)),
						),
						react.createElement(
							"div",
							{ className: "dshWg_progress" },
							react.createElement("div", {
								className: "dshWg_fill",
								style: { width: (ratio * 100).toFixed(2) + "%" },
							}),
						),
					),
				),
				react.createElement(
					"div",
					{ className: "dshWg_buttons" },
					react.createElement(
						"button",
						{
							type: "button",
							className: "dshWg_btn",
							title: "上一首",
							disabled: props.disabled,
							onClick: function () {
								props.onControl("prev");
							},
						},
						react.createElement(IconPrev, null),
					),
					react.createElement(
						"button",
						{
							type: "button",
							className: "dshWg_btn dshWg_play",
							title: props.playing ? "暂停" : "播放",
							disabled: props.disabled,
							onClick: function () {
								props.onControl("toggle");
							},
						},
						props.playing ? react.createElement(IconPause, null) : react.createElement(IconPlay, null),
					),
					react.createElement(
						"button",
						{
							type: "button",
							className: "dshWg_btn",
							title: "下一首",
							disabled: props.disabled,
							onClick: function () {
								props.onControl("next");
							},
						},
						react.createElement(IconNext, null),
					),
				),
			);
		}

		/**
		 * 控制条的折叠开关。用负外边距抵消卡片内边距，让它贴在卡片左边缘。
		 *
		 * 提示文字刻意写成「控制区」而不是「播放控制」：这个开关只管封面/进度/按钮那一列，
		 * 和右上角「收起成胶囊」是两件不同的事，措辞上必须区分开。
		 * @param {{ compact: boolean, onToggle: () => void }} props - 当前状态与切换回调。
		 * @returns {unknown} React 元素。
		 */
		function CollapseToggle(props) {
			return react.createElement(
				"button",
				{
					type: "button",
					className: "dshWg_collapse",
					title: props.compact ? "展开控制区（封面 / 进度 / 播放按钮）" : "收起控制区",
					"aria-label": props.compact ? "展开控制区" : "收起控制区",
					"aria-expanded": String(!props.compact),
					onClick: props.onToggle,
				},
				react.createElement(IconChevron, { pointing: props.compact ? "right" : "left" }),
			);
		}

		//#region 背景歌词带
		/**
		 * 会话标题栏背景里的逐字歌词带。
		 *
		 * 为什么直接操作 DOM 而不是注册插槽：DSH 没有"会话内容下方"的插槽，
		 * `conversation.session.header` 是 single（注册会顶掉真标题）。
		 * 所以用锚点定位 + 注入节点：
		 *   - 锚点用 `data-conversation-tabs` / `data-conversation-header-corner`
		 *     （不是哈希类名，宿主升级也能命中）
		 *   - 层叠靠 `[data-dsh-lyric-host]{isolation:isolate}` + 子节点 `z-index:-1`
		 *
		 * 渲染用 rAF + 直接写样式：宿主每 300ms 推一次快照，
		 * 若用 React state 驱动动画，每次推送都会把动画打断。
		 */
		// 糖果色板：逐字循环取色（每个字一种颜色）
		var BAND_PALETTE = [
			[255, 92, 138],   // 草莓粉
			[255, 176, 58],   // 芒果橙
			[255, 225, 77],   // 柠檬黄
			[107, 227, 140],  // 青苹果
			[79, 216, 216],   // 薄荷
			[91, 184, 255],   // 汽水蓝
			[155, 140, 255],  // 葡萄紫
			[255, 123, 213],  // 泡泡糖
		];
		/** 未唱的字保留的透明度（颜色不变，只压暗）。 */
		var BAND_DIM_ALPHA = 0.33;

		var bandState = { data: null };
		var bandEls = null;
		var bandRaf = 0;
		var bandLastTry = 0;

		/**
		 * 找主面板里的会话标题栏（排除右侧会话副本）。
		 *
		 * ⚠️ 两条踩过的坑：
		 *  1. **不能取 `tabs.parentElement`** —— `<header>` 与页签行之间隔着一层
		 *     「插槽容器」，它可能是 `display:contents`（不生成盒子），
		 *     对它设 `position:relative` 无效，`inset:0` 会按更外层的定位祖先生效，
		 *     于是歌词带跑到**整块会话正文中间**（真实发生过）。
		 *     → 用 `closest("header")` 直接拿语义标签，与插槽结构无关。
		 *  2. `data-conversation-header-corner` 在 `titleRow` 里面，同理用 closest。
		 */
		function findBandHeader() {
			var tabs = document.querySelectorAll("[data-conversation-tabs]");
			for (var i = 0; i < tabs.length; i += 1) {
				if (tabs[i].closest("[data-sidebar-right-session]") !== null) continue;
				var owner = tabs[i].closest("header");
				if (owner !== null) return owner;
			}
			var corner = document.querySelector("[data-conversation-header-corner]");
			if (corner !== null) {
				var owner2 = corner.closest("header");
				if (owner2 !== null) return owner2;
			}
			// 回退：往上找最近的 grid 且高度合理（≤200px）的容器
			var el = tabs.length > 0 ? tabs[0].parentElement : null;
			while (el !== null && el !== document.body) {
				var rect = el.getBoundingClientRect();
				if (window.getComputedStyle(el).display === "grid" && rect.height > 0 && rect.height <= 200) return el;
				el = el.parentElement;
			}
			return null;
		}

		/**
		 * 找"带不透明背景的那一层"——必须把 isolation 加在它身上。
		 *
		 * ⚠️ 层叠顺序：同一 stacking context 内，负 z-index 子节点（第 2 步）**先**画，
		 * 不带定位的块背景（第 3 步）、文本（第 5 步）**后**画。
		 * 所以 isolation 若加在更外层的 wrapper 上，歌词会落在会话根的背景**下面** → 看不见。
		 * 只有加在"背景就在它身上"的那个元素上，负 z-index 才叠在背景之上、内容之下。
		 */
		function findBandRoot(header) {
			var el = header.parentElement;
			while (el !== null && el !== document.body) {
				var bg = window.getComputedStyle(el).backgroundColor;
				if (bg && bg !== "transparent" && bg !== "rgba(0, 0, 0, 0)") return el;
				el = el.parentElement;
			}
			return header.parentElement;
		}

		/** 确保节点已注入；标题栏被 React 重建时自动补回。 */
		function ensureBand() {
			var header = findBandHeader();
			if (header === null) return null;
			// 护栏：
			//  - 高度必须在 ~20~220px 之间（真 header 约 76px）
			//  - display 不能是 contents（那种元素不生成盒子，position:relative 无效，
			//    带子会按更外层定位 → 跑到会话正文中间）
			var hrect = header.getBoundingClientRect();
			if (hrect.height < 20 || hrect.height > 220) return null;
			if (window.getComputedStyle(header).display === "contents") return null;

			var root = findBandRoot(header);
			if (root === null) return null;

			if (bandEls !== null && bandEls.header === header && header.isConnected) return bandEls;

			root.setAttribute("data-dsh-lyric-host", "");
			header.setAttribute("data-dsh-lyric-band", "");

			// 清掉可能残留的旧节点，避免重复叠加
			var stale = header.querySelectorAll(":scope > .dshLyricBand");
			for (var s = 0; s < stale.length; s += 1) stale[s].remove();

			var band = document.createElement("div");
			band.className = "dshLyricBand";
			var line = document.createElement("div");
			line.className = "dshLyricBand__line";
			band.appendChild(line);
			// 光标横条：像终端输入光标一样，贴在"当前正在唱的那个字"下方
			var caret = document.createElement("div");
			caret.className = "dshLyricBand__caret";
			band.appendChild(caret);
			header.appendChild(band);

			bandEls = {
				root: root,
				header: header,
				band: band,
				line: line,
				caret: caret,
				spans: [],
				sig: "",
				lastQ: [],
				lastCaret: -1,
			};
			return bandEls;
		}

		/**
		 * 把光标横条移到第 `index` 个字下方；`index < 0` 时隐藏。
		 *
		 * ⚠️ 只在"当前字变了"时才调用：这里要读 offsetLeft/offsetWidth，
		 * 每帧调用会持续触发布局计算。
		 */
		function placeCaret(els, index) {
			if (els.caret === null) return;
			if (index < 0 || index >= els.spans.length) {
				els.caret.style.display = "none";
				return;
			}
			var span = els.spans[index];
			var rgb = BAND_PALETTE[index % BAND_PALETTE.length];
			// 注意：这里必须是 "block"。CSS 里默认 display:none，
			// 写空字符串只是删掉内联样式，仍然会回落到 none（踩过）。
			els.caret.style.display = "block";
			// 偏移都相对于各自的 offsetParent：span 在 line 内，line 在 band 内
			els.caret.style.left = (els.line.offsetLeft + span.offsetLeft) + "px";
			els.caret.style.width = span.offsetWidth + "px";
			els.caret.style.color = "rgba(" + rgb.join(",") + ",0.95)";
		}

		/** 换行时重建字符 span（只在文本变化时做）。 */
		function rebuildBandLine(els, words) {
			els.line.textContent = "";
			els.spans = [];
			els.lastQ = [];
			els.lastCaret = -1;
			for (var i = 0; i < words.length; i += 1) {
				var span = document.createElement("span");
				span.className = "dshLyricBand__ch";
				// AWLRC 的拉丁文音节常带词尾空格（"There "），直接塞进 inline-block
				// 会被当成行尾空白折叠掉 → 单词全连在一起（踩过）。用 NBSP 保留。
				span.textContent = String(words[i].t).replace(/ /g, "\u00A0");
				els.line.appendChild(span);
				els.spans.push(span);
				els.lastQ.push(-1);
			}
		}

		/**
		 * 长句自适应：内容超出可用宽度时按比例缩小字号，保证整句不裁字。
		 *
		 * 只在换行时执行一次（会触发一次布局），不进每帧循环。
		 * 基准字号 23px 与 CSS 里 `.dshLyricBand__line` 保持一致。
		 */
		function fitBandLine(els) {
			els.line.style.fontSize = "";
			var max = els.line.clientWidth;
			var need = els.line.scrollWidth;
			if (max > 0 && need > max) {
				var size = Math.max(13, 23 * (max / need));
				els.line.style.fontSize = size.toFixed(2) + "px";
			}
			// 字号变了，光标位置要重算
			placeCaret(els, els.lastCaret);
		}

		/**
		 * 画一帧。`now` 是外推后的播放位置（秒）。
		 *
		 * 只在"进度跨过一个量化档"时才写颜色；当前字只把颜色走到不透明，
		 * **不加任何背景/光晕**（大字号下会发虚），进度靠下方的光标横条表示。
		 */
		function paintBand(els, data, now) {
			var words = data.words;
			var active = -1;
			var lastSung = -1;
			for (var i = 0; i < words.length; i += 1) {
				var word = words[i];
				var span2 = word.e - word.s;
				var p = span2 > 0 ? (now - word.s) / span2 : (now >= word.s ? 1 : 0);
				p = Math.max(0, Math.min(1, p));
				// 量化到 1/24，避免每帧都写样式（60fps × 30 字 = 不必要的重排）
				var q = Math.round(p * 24) / 24;
				if (q !== els.lastQ[i]) {
					els.lastQ[i] = q;
					var rgb = BAND_PALETTE[i % BAND_PALETTE.length];
					// 未唱压到 33% 透明度、已唱全亮 —— 每个字保留自己的糖果色
					els.spans[i].style.color =
						"rgba(" + rgb.join(",") + "," + (BAND_DIM_ALPHA + (1 - BAND_DIM_ALPHA) * q).toFixed(3) + ")";
				}
				// 当前字 = 已经开始唱、且还没唱完的那一个；
				// 整行都唱完时停在最后一个字上（别跳回句首）
				if (p > 0 && p < 1) active = i;
				if (p >= 1) lastSung = i;
			}

			if (active < 0) active = lastSung;
			if (active !== els.lastCaret) {
				els.lastCaret = active;
				placeCaret(els, active);
			}
		}

		function bandFrame() {
			bandRaf = 0;
			var data = bandState.data;
			if (data === null) return;

			if (bandEls === null || !bandEls.header.isConnected) {
				if (Date.now() - bandLastTry < 800) return;
				bandLastTry = Date.now();
				bandEls = ensureBand();
			}
			if (bandEls === null) return;

			// 该不该显示
			var band = data.band || {};
			var words = Array.isArray(data.words) ? data.words : [];
			var on = band.enabled !== false && data.playing === true && words.length > 0;
			bandEls.band.style.visibility = on ? "visible" : "hidden";
			bandEls.band.style.opacity = String(typeof band.opacity === "number" ? band.opacity : 0.8);
			if (!on) {
				// 不强行收起：纯音乐/暂停时 band 虽然隐藏，但悬浮仍应能控制播放
				if (data.playing === true) bandRaf = window.requestAnimationFrame(bandFrame);
				return;
			}

			var sig = data.lineStart + "|" + words.length;
			for (var si = 0; si < words.length; si += 1) sig += words[si].t;
			if (sig !== bandEls.sig) {
				bandEls.sig = sig;
				rebuildBandLine(bandEls, words);
				fitBandLine(bandEls);
			}

			var at = typeof data.at === "number" ? data.at : Date.now();
			var now = data.progress + (Date.now() - at) / 1000;
			paintBand(bandEls, data, now);

			if (data.playing === true) bandRaf = window.requestAnimationFrame(bandFrame);
		}

		/** 收到新快照：存起来并（必要时）启动渲染循环。 */
		function pushBandState(data) {
			bandState.data = data;
			if (bandEls !== null) bandEls.header.setAttribute("data-dsh-lyric-band", "");
			if (bandRaf === 0) bandRaf = window.requestAnimationFrame(bandFrame);
		}

		/** 卸载：停循环、摘节点、清标记。 */
		function disposeBand() {
			if (bandRaf !== 0) {
				window.cancelAnimationFrame(bandRaf);
				bandRaf = 0;
			}
			if (bandEls !== null) {
				if (bandEls.band.parentElement !== null) bandEls.band.parentElement.removeChild(bandEls.band);
				bandEls.header.removeAttribute("data-dsh-lyric-band");
				bandEls.root.removeAttribute("data-dsh-lyric-host");
				bandEls = null;
			}
			bandState.data = null;
		}

		//#region 设置页
		/**
		 * 「设置 → 鲸鱼娘歌词」这一页。
		 *
		 * 字段列表由宿主 `/config` 接口给出（`fields`），前端只负责按 `type`
		 * 渲染控件并回写，所以以后加配置项只改宿主那一处。
		 *
		 * 保存后宿主会立刻重建轮询器，不需要重启 DSH。
		 * @returns {unknown} React 元素。
		 */
		function WhalegirlSettings() {
			var loadedState = react.useState(null);
			var loaded = loadedState[0];
			var setLoaded = loadedState[1];

			var draftState = react.useState({});
			var draft = draftState[0];
			var setDraft = draftState[1];

			var noteState = react.useState("");
			var note = noteState[0];
			var setNote = noteState[1];

			var errorState = react.useState(false);
			var isError = errorState[0];
			var setIsError = errorState[1];

			var busyState = react.useState(false);
			var busy = busyState[0];
			var setBusy = busyState[1];

			react.useEffect(function () {
				var alive = true;
				fetch(CONFIG_API, { cache: "no-store" })
					.then(function (response) {
						if (!response.ok) throw new Error("HTTP " + response.status);
						return response.json();
					})
					.then(function (next) {
						if (!alive) return;
						setLoaded(next);
						setDraft(next.values === undefined ? {} : next.values);
					})
					.catch(function (cause) {
						if (alive) {
							setIsError(true);
							setNote("读取配置失败：" + String(cause && cause.message ? cause.message : cause));
						}
					});
				return function () {
					alive = false;
				};
			}, []);

			function edit(key, value) {
				var next = Object.assign({}, draft);
				next[key] = value;
				setDraft(next);
			}

			function save() {
				setBusy(true);
				setIsError(false);
				setNote("保存中…");
				fetch(CONFIG_API, {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify({ values: draft }),
				})
					.then(function (response) {
						return response.json().then(function (body) {
							return { ok: response.ok, body };
						});
					})
					.then(function (result) {
						if (!result.ok || result.body.ok !== true) {
							throw new Error(result.body.error || "保存失败");
						}
						setLoaded({ values: result.body.values, fields: loaded ? loaded.fields : [] });
						setDraft(result.body.values);
						setNote("已保存，立即生效");
					})
					.catch(function (cause) {
						setIsError(true);
						setNote("保存失败：" + String(cause && cause.message ? cause.message : cause));
					})
					.then(function () {
						setBusy(false);
					});
			}

			if (loaded === null) {
				return react.createElement(
					"div",
					{ className: "dshWgSet" },
					react.createElement("div", { className: "dshWgSet_note" }, note || "读取配置中…"),
				);
			}

			var fields = Array.isArray(loaded.fields) ? loaded.fields : [];
			var rows = fields.map(function (field) {
				var value = draft[field.key];

				if (field.type === "bool") {
					return react.createElement(
						"label",
						{ key: field.key, className: "dshWgSet_check" },
						react.createElement("input", {
							type: "checkbox",
							checked: value === true,
							onChange: function (event) {
								edit(field.key, event.target.checked);
							},
						}),
						react.createElement("span", null, field.label),
					);
				}

				var inputProps =
					field.type === "number"
						? {
								type: "number",
								min: field.min,
								max: field.max,
								step: field.step,
								value: value === undefined ? "" : value,
								onChange: function (event) {
									var raw = event.target.value;
									edit(field.key, raw === "" ? "" : Number(raw));
								},
						  }
						: {
								type: "text",
								value: value === undefined ? "" : value,
								onChange: function (event) {
									edit(field.key, event.target.value);
								},
						  };

				return react.createElement(
					"label",
					{ key: field.key, className: "dshWgSet_row" },
					react.createElement("span", { className: "dshWgSet_label" }, field.label),
					react.createElement(
						"input",
						Object.assign({ className: "dshWgSet_input" }, inputProps),
					),
					field.hint
						? react.createElement("span", { className: "dshWgSet_hint" }, field.hint)
						: null,
				);
			});

			return react.createElement(
				"div",
				{ className: "dshWgSet" },
				rows,
				react.createElement(
					"div",
					{ className: "dshWgSet_actions" },
					react.createElement(
						"button",
						{ className: "dshWgSet_btn", disabled: busy, onClick: save },
						busy ? "保存中…" : "保存",
					),
					note
						? react.createElement(
								"span",
								{ className: "dshWgSet_note", "data-error": String(isError) },
								note,
						  )
						: null,
				),
			);
		}

		//#region 主组件
		/**
		 * 鲸鱼娘歌词挂件。
		 * 收起态是一枚圆形头像胶囊，点击展开；展开态是鲸鱼娘 + 左上角气泡歌词 + 播放控制。
		 * @returns {unknown} React 元素。
		 */
		function WhalegirlLyric() {
			var state = react.useState(undefined);
			var data = state[0];
			var setData = state[1];

			var hiddenState = react.useState(readHidden);
			var collapsed = hiddenState[0];
			var setCollapsed = hiddenState[1];

			var errorState = react.useState("");
			var error = errorState[0];
			var setError = errorState[1];

			var busyState = react.useState(false);
			var busy = busyState[0];
			var setBusy = busyState[1];

			// 控制区折叠状态（与「完全收起成胶囊」是两件事）
			var compactState = react.useState(readCompact);
			var compact = compactState[0];
			var setCompact = compactState[1];

			// 拖动位置（相对默认右下角的偏移）
			var posState = react.useState(readPos);
			var pos = posState[0];
			var setPos = posState[1];

			var rootRef = useRef(null);
			var dragState = react.useState(null);
			var drag = dragState[0];
			var setDrag = dragState[1];

			// 歌词关掉后，播放控制浮在标题栏歌词带上方。
			// 用 ref 拿最新快照，避免 mousemove 监听随每次轮询重绑。
			var dataRef = react.useRef(null);
			dataRef.current = data;
			var transportState = react.useState({ shown: false, left: 0, top: 0 });
			var transport = transportState[0];
			var setTransport = transportState[1];

			// 轮询 Host 状态。静态包，浏览器全局可用，因此直接用 fetch。
			react.useEffect(
				function () {
					var alive = true;
					var timer = 0;

					function tick() {
						fetch(STATE_API, { cache: "no-store" })
							.then(function (response) {
								if (!response.ok) throw new Error("HTTP " + response.status);
								return response.json();
							})
							.then(function (next) {
								if (!alive) return;
								setData(next);
								setError(next.reachable === false ? String(next.error ?? "unreachable") : "");
							})
							.catch(function (cause) {
								if (alive) setError(String(cause && cause.message ? cause.message : cause));
							})
							.then(function () {
								if (alive) timer = window.setTimeout(tick, POLL_MS);
							});
					}

					tick();
					return function () {
						alive = false;
						window.clearTimeout(timer);
					};
				},
				[],
			);

			// 背景歌词带：每次拿到新快照就推给它（它自己和 rAF 配合，不会打断动画）
			react.useEffect(
				function () {
					if (data === undefined) return undefined;
					pushBandState(data);
					return undefined;
				},
				[data],
			);

			// 组件卸载时把注入的节点摘掉，别在宿主里留垃圾
			react.useEffect(function () {
				return function () {
					disposeBand();
				};
			}, []);

			// 悬浮播放控制：鼠标在标题栏歌词带范围内时，把控制条浮到
			// 歌词文字右侧。位置每次都用 rect 现算，窗口宽度变了也不会错位。
			react.useEffect(function () {
				function hide(prev) {
					return prev.shown ? { shown: false, left: prev.left, top: prev.top } : prev;
				}

				function onMove(event) {
					var payload = dataRef.current;
					// 气泡歌词还开着时，挂件自己有控制条，不重复出现
					if (!payload || payload.lyricsEnabled !== false) {
						setTransport(hide);
						return;
					}
					var band = document.querySelector(".dshLyricBand");
					if (band === null) {
						setTransport(hide);
						return;
					}
					var rect = band.getBoundingClientRect();
					if (rect.width <= 0) {
						setTransport(hide);
						return;
					}
					var inside =
						event.clientX >= rect.left &&
						event.clientX <= rect.right &&
						event.clientY >= rect.top - 6 &&
						event.clientY <= rect.bottom + 6;
					if (!inside) {
						setTransport(hide);
						return;
					}
					// 贴着歌词文字右侧；放不下就贴右，并给宿主右上角按钮留出余量
					var width = 118;
					var maxLeft = rect.right - width - 12;
					var left = maxLeft;
					var line = band.querySelector(".dshLyricBand__line");
					if (line !== null) left = line.getBoundingClientRect().right + 10;
					if (left > maxLeft) left = maxLeft;
					if (left < rect.left + 12) left = rect.left + 12;
					var top = rect.top + rect.height / 2 - 17;
					setTransport(function (prev) {
						if (
							prev.shown &&
							Math.abs(prev.left - left) < 1 &&
							Math.abs(prev.top - top) < 1
						) {
							return prev;
						}
						return { shown: true, left: left, top: top };
					});
				}

				document.addEventListener("mousemove", onMove, { passive: true });
				return function () {
					document.removeEventListener("mousemove", onMove);
				};
			}, []);

			// 多窗口同步收起/折叠/位置
			react.useEffect(function () {
				function onStorage(event) {
					if (event.key === HIDE_KEY) setCollapsed(readHidden());
					if (event.key === COMPACT_KEY) setCompact(readCompact());
					if (event.key === POS_KEY) setPos(readPos());
				}
				window.addEventListener("storage", onStorage);
				return function () {
					window.removeEventListener("storage", onStorage);
				};
			}, []);

			/**
			 * 开始拖动。只在卡片空白/图片上按下时生效，按钮与链接保持原有点击行为。
			 * @param {Event} event - mousedown 事件。
			 */
			function onDragStart(event) {
				if (event.button !== 0) return;
				var target = event.target;
				if (target !== null && target !== undefined) {
					var tag = String(target.tagName ?? "").toUpperCase();
					if (tag === "BUTTON" || tag === "A" || tag === "INPUT" || tag === "IMG") return;
					if (target.closest !== undefined && target.closest("button, a, input, img") !== null) return;
				}
				var rect =
					rootRef.current !== null && rootRef.current.getBoundingClientRect !== undefined
						? rootRef.current.getBoundingClientRect()
						: null;
				setDrag({
					startX: event.clientX,
					startY: event.clientY,
					dx: pos.dx,
					dy: pos.dy,
					w: rect === null ? 0 : rect.width,
					h: rect === null ? 0 : rect.height,
					viewW: window.innerWidth,
					viewH: window.innerHeight,
				});
				event.preventDefault();
			}

			// 拖动期间用 document 监听移动与抬起，松手时把最终位置落盘。
			// 位移直接写 CSS 变量、不触发重渲染，避免拖动时每帧重算整棵子树。
			react.useEffect(
				function () {
					if (drag === null) return undefined;

					var maxRight = Math.max(0, drag.viewW - drag.w - EDGE_GAP);
					var maxBottom = Math.max(0, drag.viewH - drag.h - EDGE_GAP);
					// 最近一次落点；松手时用它落盘，因此不必在渲染期把状态写进 ref
					var lastRight = drag.dx;
					var lastBottom = drag.dy;

					function clamp(value, min, max) {
						if (!Number.isFinite(value)) return min;
						if (value < min) return min;
						if (value > max) return max;
						return value;
					}

					function onMove(event) {
						// 偏移量是「离右下角的距离」，因此与鼠标位移方向相反：
						// 鼠标向左/上移动（clientX / clientY 减小）→ 偏移量增大。
						lastRight = clamp(drag.dx - (event.clientX - drag.startX), 0, maxRight);
						lastBottom = clamp(drag.dy - (event.clientY - drag.startY), 0, maxBottom);
						var el = rootRef.current;
						if (el !== null && el !== undefined && el.style !== undefined) {
							el.style.setProperty("--dshWgRight", lastRight + "px");
							el.style.setProperty("--dshWgBottom", lastBottom + "px");
						}
					}

					function onUp() {
						var settled = { dx: lastRight, dy: lastBottom };
						writePos(settled);
						setPos(settled);
						setDrag(null);
					}

					document.addEventListener("mousemove", onMove);
					document.addEventListener("mouseup", onUp);
					return function () {
						document.removeEventListener("mousemove", onMove);
						document.removeEventListener("mouseup", onUp);
					};
				},
				[drag],
			);

			/**
			 * 发送控制指令。
			 * @param {string} action - 动作名。
			 */
			function onControl(action) {
				if (busy) return;
				setBusy(true);
				fetch(CONTROL_API, {
					method: "POST",
					headers: { "content-type": "application/json" },
					body: JSON.stringify({ action: action }),
				})
					.catch(function () {
						/* 失败时靠下一轮轮询自愈 */
					})
					.then(function () {
						setBusy(false);
					});
			}

			/** 收起挂件。 */
			function collapse() {
				writeHidden(true);
				setCollapsed(true);
			}

			/** 展开挂件。 */
			function expand() {
				writeHidden(false);
				setCollapsed(false);
			}

			// 关掉「气泡里显示歌词」→ 整个挂件不显示；
			// 播放控制浮到标题栏歌词带上方（走 overlay 层，可点击）。
			// 例外：背景带也关了的话就没有任何控制入口了，此时保留挂件本体。
			var bandOn = !(data && data.band && data.band.enabled === false);
			if (data && data.lyricsEnabled === false && bandOn) {
				if (!transport.shown) return null;
				var transportButton = function (key, title, icon, action) {
					return react.createElement(
						"button",
						{
							key: key,
							className: "dshWg_transportBtn",
							title: title,
							"aria-label": title,
							disabled: busy,
							onMouseDown: function (event) {
								event.stopPropagation();
							},
							onClick: function (event) {
								event.stopPropagation();
								onControl(action);
							},
						},
						icon,
					);
				};
				return react.createElement(
					"div",
					{
						className: "dshWg_transport",
						style: { left: transport.left + "px", top: transport.top + "px" },
					},
					transportButton("prev", "上一曲", react.createElement(IconPrev), "prev"),
					transportButton(
						"toggle",
						data.playing ? "暂停" : "播放",
						data.playing ? react.createElement(IconPause) : react.createElement(IconPlay),
						"toggle",
					),
					transportButton("next", "下一曲", react.createElement(IconNext), "next"),
				);
			}

			if (collapsed) {
				return react.createElement(
					"div",
					{
						className: "dshWg_dock",
						ref: rootRef,
						style: posStyle(pos),
						role: "button",
						tabIndex: 0,
						title: "点击展开 · 按住拖动",
						"data-playing": String(Boolean(data && data.playing)),
						"data-dragging": String(drag !== null),
						onMouseDown: onDragStart,
						onClick: expand,
						onKeyDown: function (event) {
							if (event.key === "Enter" || event.key === " ") {
								event.preventDefault();
								expand();
							}
						},
					},
					// 歌词关闭时，隐藏态只留头像，不再显示占位文字
					data && data.lyricsEnabled !== false
						? react.createElement(
								"div",
								{ className: "dshWg_dockText" },
								data.lyric ? data.lyric : "鲸鱼娘歌词",
						  )
						: null,
					data && data.lyricsEnabled !== false
						? react.createElement("div", { className: "dshWg_dockDot" })
						: null,
					// 与展开态保持一致：文字在左，头像在右
					react.createElement("div", {
						className: "dshWg_dockFace",
						style: { backgroundImage: "url(" + FIGURE_URL + ")" },
					}),
				);
			}

			return react.createElement(
				"div",
				{
					className: "dshWg_root",
					ref: rootRef,
					style: posStyle(pos),
					"data-dragging": String(drag !== null),
					onMouseDown: onDragStart,
				},
				react.createElement(
					"div",
					{
						className: "dshWg_card" + (compact ? " dshWg_compact" : ""),
						"data-playing": String(Boolean(data && data.playing)),
						"data-compact": String(compact),
					},
					react.createElement(CollapseToggle, {
						compact: compact,
						onToggle: function () {
							var next = !compact;
							writeCompact(next);
							setCompact(next);
						},
					}),
					react.createElement(
						"button",
						{
							type: "button",
							className: "dshWg_hide",
							title: "收起",
							onClick: collapse,
						},
						"×",
					),
					// 折叠后本元素隐藏，它占的 196px 让给舞台区
					react.createElement(ControlBar, {
						playing: Boolean(data && data.playing),
						disabled: Boolean(data && data.reachable === false),
						onControl: onControl,
						name: data && data.name ? data.name : "",
						singer: data && data.singer ? data.singer : "",
						progress: data && Number.isFinite(data.progress) ? data.progress : 0,
						duration: data && Number.isFinite(data.duration) ? data.duration : 0,
						picUrl: data && data.picUrl ? data.picUrl : "",
					}),
					react.createElement(
						"div",
						{ className: "dshWg_stage" },
						react.createElement("div", {
							className: "dshWg_figure",
							style: { backgroundImage: "url(" + FIGURE_URL + ")" },
						}),
						react.createElement(LyricBubble, { data: data, error: error }),
					),
				),
			);
		}

		//#region 注册
		/** 挂到 shell.overlay 的格子 id。 */
		var SLOT_ID = "whalegirl-lyric";
		/** 排序：靠后，避免与官方浮层抢位置。 */
		var SLOT_ORDER = 60;

		/**
		 * 给列表插槽的子元素补一个 React key。
		 * @param {unknown} Component - 被包装的组件。
		 * @returns {unknown} 带 key 的包装组件。
		 */
		function withSlotKey(Component) {
			return function Slotted() {
				return react.createElement(Component, { key: SLOT_ID });
			};
		}

		/** 硬依赖：插槽注册表。 */
		var inject = ["slots"];

		/**
		 * 插件入口。
		 * @param {import('@deepseek-ai/cordis').Context} ctx - 客户端根上下文。
		 */
		function apply(ctx) {
			var disposers = [];

			// 样式与本 fiber 同生命周期，插件卸载时自动回收
			ctx.effect(function () {
				var style = document.createElement("style");
				style.textContent = CSS;
				document.head.appendChild(style);
				return function () {
					style.remove();
				};
			}, NS + ": styles");

			ctx.effect(installGlobalStyles, NS + ": keyframes");

			ctx.effect(function () {
				return function () {
					for (var i = 0; i < disposers.length; i += 1) disposers[i]();
					disposers = [];
				};
			}, NS + ": slots");

			try {
				disposers.push(
					ctx.slots.inject("shell.overlay", function () {
						try {
							return ctx.slots.register(
								{
									name: "shell.overlay",
									id: SLOT_ID,
									order: SLOT_ORDER,
									label: "鲸鱼娘歌词",
								},
								withSlotKey(WhalegirlLyric),
							);
						} catch (error) {
							// 外壳不提供该座位时安静降级，绝不把整个 GUI 拖下水
							console.error("[" + NS + "] shell.overlay 注册失败", error);
							return function () {};
						}
					}),
				);

				// 设置 → 鲸鱼娘歌词：把宿主的配置项做成表单
				disposers.push(
					ctx.slots.inject("settings.section", function () {
						try {
							return ctx.slots.register(
								{
									name: "settings.section",
									id: NS,
									order: 80,
									label: "鲸鱼娘歌词",
								},
								withSlotKey(WhalegirlSettings),
							);
						} catch (error) {
							console.error("[" + NS + "] settings.section 注册失败", error);
							return function () {};
						}
					}),
				);
			} catch (error) {
				console.error("[" + NS + "] 插槽注入失败", error);
			}
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
