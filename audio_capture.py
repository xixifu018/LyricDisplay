"""音频捕获 —— 优先 soundcard WASAPI loopback，回退 sounddevice"""

import threading
import numpy as np

from PyQt5.QtCore import QObject, pyqtSignal

SAMPLE_RATE = 44100
BLOCK_SIZE = 2048
BAR_COUNT = 48
FALL_SPEED = 0.10


def _build_bin_map():
    freqs = np.fft.rfftfreq(BLOCK_SIZE, 1.0 / SAMPLE_RATE)
    lo = np.log10(20)
    hi = np.log10(16000)
    edges = np.logspace(lo, hi, BAR_COUNT + 1)
    mapping = []
    for j in range(BAR_COUNT):
        lo_bin = int(np.searchsorted(freqs, edges[j]))
        hi_bin = int(np.searchsorted(freqs, edges[j + 1]))
        if hi_bin <= lo_bin:
            hi_bin = lo_bin + 1
        mapping.append((lo_bin, hi_bin))
    return mapping


BIN_MAP = _build_bin_map()


class AudioCapture(QObject):
    """后台捕获音频 → FFT → 频谱数据信号"""

    spectrum_data = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._thread = None
        self._bars = np.zeros(BAR_COUNT, dtype=np.float32)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._bars = np.zeros(BAR_COUNT, dtype=np.float32)
        self.spectrum_data.emit([0.0] * BAR_COUNT)

    # ============================================================
    #  捕获循环
    # ============================================================

    def _capture_loop(self):
        # 方法1：soundcard loopback（最可靠）
        if self._try_soundcard():
            return
        # 方法2：sounddevice（旧方案）
        if self._try_sounddevice():
            return
        # 失败
        print("[AudioCapture] 无法获取音频，频谱不可用")
        self._running = False

    # ============================================================
    #  soundcard 方案
    # ============================================================

    def _try_soundcard(self):
        try:
            import soundcard as sc
        except ImportError:
            return False

        try:
            # 获取默认扬声器的 loopback 设备
            speaker = sc.default_speaker()
            speaker_name = speaker.name

            # all_microphones(include_loopback=True) 包含 loopback 设备
            loopback_mics = sc.all_microphones(include_loopback=True)

            # 找到与默认扬声器匹配的 loopback
            mic = None
            for m in loopback_mics:
                if m.name == speaker_name:
                    mic = m
                    break

            # 找不到精确匹配就用第一个非麦克风的设备
            if mic is None:
                for m in loopback_mics:
                    name_lower = m.name.lower()
                    if not any(kw in name_lower for kw in
                               ['microphone', 'mic', '麦克风', '话筒']):
                        mic = m
                        break

            if mic is None and loopback_mics:
                mic = loopback_mics[0]

            if mic is None:
                print("[AudioCapture] soundcard: 未找到 loopback 设备")
                return False

            print(f"[AudioCapture] soundcard loopback: {mic.name}")

            with mic.recorder(samplerate=SAMPLE_RATE, channels=2) as rec:
                while self._running:
                    try:
                        data = rec.record(numframes=BLOCK_SIZE)
                        self._process_audio(data)
                    except Exception:
                        break
            return True

        except Exception as e:
            print(f"[AudioCapture] soundcard 失败: {e}")
            return False

    # ============================================================
    #  sounddevice 回退方案
    # ============================================================

    def _try_sounddevice(self):
        try:
            import sounddevice as sd
        except ImportError:
            return False

        device = self._find_sd_device(sd)
        if device is None:
            return False

        print(f"[AudioCapture] sounddevice: {sd.query_devices(device)['name']}")

        def callback(indata, frames, time_info, status):
            if self._running:
                self._process_audio(indata)

        try:
            with sd.InputStream(
                device=device, channels=2,
                samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                callback=callback, dtype=np.float32,
            ):
                while self._running:
                    sd.sleep(50)
                    bars_copy = self._bars.copy().tolist()
                    self.spectrum_data.emit(bars_copy)
            return True
        except Exception as e:
            print(f"[AudioCapture] sounddevice 失败: {e}")
            return False

    def _find_sd_device(self, sd):
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            name = (dev.get('name') or '').lower()
            if 'loopback' in name and dev['max_input_channels'] > 0:
                return i
        # 回退到默认输入
        try:
            return sd.default.device[0]
        except Exception:
            return None

    # ============================================================
    #  FFT 处理（共用）
    # ============================================================

    def _process_audio(self, indata):
        """处理音频块 → FFT → 更新 bars"""
        try:
            if indata.ndim == 2:
                mono = indata[:, 0]
            else:
                mono = indata

            windowed = mono * np.hanning(len(mono))
            fft = np.abs(np.fft.rfft(windowed))

            # 映射到 bars
            raw_bars = np.zeros(BAR_COUNT, dtype=np.float32)
            for j, (lo, hi) in enumerate(BIN_MAP):
                raw_bars[j] = np.mean(fft[lo:hi])

            # 对数压缩
            raw_bars = np.log1p(raw_bars)

            # 频率加权：补偿高频能量不足
            freq_weight = np.linspace(1.0, 5.0, BAR_COUNT)
            raw_bars *= freq_weight

            # 每帧做 min-max 归一化 → 保证 0~1 动态范围
            bmin = raw_bars.min()
            bmax = raw_bars.max()
            if bmax - bmin > 0.001:
                raw_bars = (raw_bars - bmin) / (bmax - bmin)
            else:
                raw_bars.fill(0.0)

            # 轻度指数映射让低值更低
            raw_bars = raw_bars ** 1.5

            new_bars = np.clip(raw_bars, 0.0, 1.0)

            # 平滑
            for j in range(BAR_COUNT):
                if new_bars[j] > self._bars[j]:
                    self._bars[j] += (new_bars[j] - self._bars[j]) * 0.75
                else:
                    self._bars[j] = max(self._bars[j] - FALL_SPEED, new_bars[j])

            self.spectrum_data.emit(self._bars.copy().tolist())

        except Exception:
            pass
