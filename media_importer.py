"""
MP4 视频与音频处理模块 (Media Importer)
功能：
1. 提取 MP4 / MP3 / WAV 文件的音频音轨
2. 智能音频转谱：通过时频与自相关基频检测，识别主旋律并自动转化为口琴简谱 (1~7、高低音、半音)
3. 原声音频伴奏：支持在脚本弹奏的同时，同步播放 MP4 的原声背景音乐
"""

import os
import math
import wave
import threading
import winsound
from typing import Tuple, List, Optional
import numpy as np
import av

from midi_importer import midi_note_to_pitch

class MediaImporter:
    def __init__(self):
        self._current_wav_path: Optional[str] = None
        self._is_playing_audio = False

    def extract_pcm_and_wav(self, media_path: str, target_sr: int = 22050) -> Tuple[np.ndarray, str]:
        """
        从 MP4 / 音频文件中解码 PCM 浮点音频数组，并在同目录下导出临时缓存 WAV 供伴奏播放
        """
        if not os.path.exists(media_path):
            raise FileNotFoundError(f"找不到媒体文件: {media_path}")

        container = av.open(media_path)
        audio_streams = [s for s in container.streams if s.type == 'audio']
        if not audio_streams:
            container.close()
            raise ValueError(f"文件 '{os.path.basename(media_path)}' 中未找到音频轨道！")

        resampler = av.AudioResampler(format='s16', layout='mono', rate=target_sr)
        chunks = []

        for frame in container.decode(audio=0):
            resampled = resampler.resample(frame)
            if resampled:
                frames_list = resampled if isinstance(resampled, list) else [resampled]
                for f in frames_list:
                    chunks.append(np.frombuffer(f.planes[0], dtype=np.int16))

        container.close()

        if not chunks:
            raise ValueError("未能从音频轨道读取到有效音频数据！")

        int16_samples = np.concatenate(chunks)
        float_samples = int16_samples.astype(np.float32) / 32768.0

        # 导出伴奏 WAV 文件至同目录缓存
        cache_dir = os.path.dirname(media_path)
        base_name = os.path.splitext(os.path.basename(media_path))[0]
        wav_path = os.path.join(cache_dir, f".{base_name}_audio.wav")

        try:
            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2) # 16-bit
                wf.setframerate(target_sr)
                wf.writeframes(int16_samples.tobytes())
            self._current_wav_path = wav_path
        except Exception as e:
            print(f"[Media] 写入伴奏 WAV 失败: {e}")
            wav_path = ""

        return float_samples, wav_path

    def transcribe_audio_to_score(self, media_path: str, bpm: float = 100.0) -> Tuple[str, float, int]:
        """
        从 MP4 / 音频中分析基频并转录为口琴简谱文本
        """
        sr = 22050
        samples, wav_path = self.extract_pcm_and_wav(media_path, target_sr=sr)

        # 参数配置
        frame_size = 2048 # ~93ms
        hop_size = 512   # ~23ms
        num_frames = (len(samples) - frame_size) // hop_size

        if num_frames <= 0:
            return "# 音频时长过短，无法分析旋律", bpm, 0

        # 基频检测范围：C3 (130 Hz) ~ B5 (1000 Hz)
        min_lag = int(sr / 1000)
        max_lag = int(sr / 125)

        raw_notes = [] # [(time_sec, pitch_str or None)]
        energy_threshold = 0.015 # 静音判定门限

        for f_idx in range(num_frames):
            start = f_idx * hop_size
            frame = samples[start:start + frame_size]
            t_sec = start / sr

            # RMS 能量
            rms = np.sqrt(np.mean(frame ** 2))
            if rms < energy_threshold:
                raw_notes.append((t_sec, None))
                continue

            # 加窗并计算自相关
            windowed = frame * np.hanning(frame_size)
            corr = np.correlate(windowed, windowed, mode='full')
            corr = corr[len(corr) // 2:]

            if max_lag >= len(corr):
                raw_notes.append((t_sec, None))
                continue

            # 寻峰
            search_window = corr[min_lag:max_lag]
            if len(search_window) == 0:
                raw_notes.append((t_sec, None))
                continue

            peak_rel = np.argmax(search_window)
            peak_lag = min_lag + peak_rel

            # 峰值置信度
            if corr[peak_lag] < 0.22 * corr[0]:
                raw_notes.append((t_sec, None))
                continue

            pitch_hz = sr / peak_lag
            if pitch_hz < 125 or pitch_hz > 1050:
                raw_notes.append((t_sec, None))
                continue

            # 转换为最近的 MIDI 音符编号
            # 69 = A4 (440Hz)
            midi_num = int(round(69 + 12 * math.log2(pitch_hz / 440.0)))
            pitch_code = midi_note_to_pitch(midi_num)
            raw_notes.append((t_sec, pitch_code))

        # 聚合并平滑连续音符 (滤波微小杂音)
        note_events = [] # [(start_time, dur, pitch_code)]
        current_pitch = None
        seg_start = 0.0

        for t_sec, p in raw_notes:
            if p != current_pitch:
                if current_pitch is not None:
                    dur = t_sec - seg_start
                    if dur >= 0.08: # 大于 80ms 算作有效音
                        note_events.append((seg_start, dur, current_pitch))
                current_pitch = p
                seg_start = t_sec

        if current_pitch is not None:
            dur = (num_frames * hop_size / sr) - seg_start
            if dur >= 0.08:
                note_events.append((seg_start, dur, current_pitch))

        if not note_events:
            return "# 未能从音频中提取到清晰的主旋律（可能伴奏声过大或音量过低）", bpm, 0

        # 生成简谱文本排版
        beat_sec = 60.0 / bpm
        tokens = []
        last_end = 0.0

        for start_t, dur, pitch in note_events:
            gap = start_t - last_end
            if gap >= beat_sec * 0.4:
                rest_beats = round(gap / beat_sec)
                for _ in range(max(1, rest_beats)):
                    tokens.append("0")

            beats = max(0.25, round((dur / beat_sec) * 4) / 4)
            if beats >= 4.0:
                s = f"{pitch} - - -"
            elif beats >= 2.0:
                s = f"{pitch} -"
            elif beats >= 1.5:
                s = f"{pitch}."
            elif beats >= 1.0:
                s = pitch
            elif beats == 0.5:
                s = f"{pitch}/2"
            else:
                s = f"{pitch}/4"

            tokens.append(s)
            last_end = start_t + dur

        lines = [
            f"# 从媒体文件智能识别转谱: {os.path.basename(media_path)}",
            f"# 识别音符总数: {len(note_events)}，设定 BPM: {bpm}",
            ""
        ]

        current_line = []
        for idx, tk in enumerate(tokens, start=1):
            current_line.append(tk)
            if idx % 4 == 0:
                current_line.append("|")
                if len(current_line) >= 9:
                    lines.append(" ".join(current_line))
                    current_line = []

        if current_line:
            lines.append(" ".join(current_line))

        return "\n".join(lines), bpm, len(note_events)

    def play_accompaniment(self, wav_path: str):
        """异步播放伴奏音频"""
        if not wav_path or not os.path.exists(wav_path):
            return
        try:
            self._is_playing_audio = True
            winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"[Media] 播放伴奏失败: {e}")

    def stop_accompaniment(self):
        """停止伴奏播放"""
        if self._is_playing_audio:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
            self._is_playing_audio = False
