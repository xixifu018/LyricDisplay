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
			var lyric = typeof data?.lyric === "string" ? data.lyric : "";
			var translation = typeof data?.translation === "string" ? data.translation : "";
			var next = typeof data?.next === "string" ? data.next : "";

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
					react.createElement(
						"div",
						{ className: "dshWg_dockText" },
						data && data.lyric ? data.lyric : "鲸鱼娘歌词",
					),
					react.createElement("div", { className: "dshWg_dockDot" }),
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
			} catch (error) {
				console.error("[" + NS + "] 插槽注入失败", error);
			}
		}

		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
