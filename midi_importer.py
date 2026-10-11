"""
MIDI 文件导入与转谱模块 (MIDI Importer)
支持标准 MIDI 文件 (.mid, .midi)，将多轨 MIDI 音乐解析为口琴三八度及半音简谱，
并自动折叠音域到 C3~B5 (低音1. ~ 高音7')，智能合并和弦与节拍。
"""

import os
from typing import Dict, List, Tuple, Optional
import mido

# MIDI 音符 (0~127) 对应口琴简谱代码查找表
# C3(48) ~ B5(83) 为口琴有效三八度
PITCH_MAP_BASE_OCTAVE = {
    0: ("1", ""),      # C
    1: ("#1", ""),     # C#
    2: ("2", ""),      # D
    3: ("#2", ""),     # D#
    4: ("3", ""),      # E
    5: ("4", ""),      # F
    6: ("#4", ""),     # F#
    7: ("5", ""),      # G
    8: ("#5", ""),     # G#
    9: ("6", ""),      # A
    10: ("#6", ""),    # A#
    11: ("7", ""),     # B
}

def midi_note_to_pitch(note_num: int) -> str:
    """
    将任意 MIDI 音高代码 (0~127) 折叠映射至口琴有效音域 (低音 1.~7., 中音 1~7, 高音 1'~7')
    """
    # 将音高折叠至 [48, 83] 范围内 (C3 ~ B5)
    while note_num < 48:
        note_num += 12
    while note_num > 83:
        note_num -= 12

    octave_idx = (note_num // 12) - 4 # 48//12=4 -> 0 (低音 C3), 60//12=5 -> 1 (中音 C4), 72//12=6 -> 2 (高音 C5)
    semitone_idx = note_num % 12
    base_name, _ = PITCH_MAP_BASE_OCTAVE[semitone_idx]

    if octave_idx == 0:
        # 低音
        return base_name + "."
    elif octave_idx == 1:
        # 中音
        return base_name
    elif octave_idx >= 2:
        # 高音
        return base_name + "'"
    return base_name


class MidiImporter:
    def __init__(self):
        pass

    def import_midi(self, file_path: str) -> Tuple[str, float, int]:
        """
        解析 MIDI 文件，返回:
        (score_text, bpm, note_count)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到 MIDI 文件: {file_path}")

        mid = None
        # 兼容各类 DAW 及游戏导出的非标准 MIDI 文件 (允许数据字节超出 0..127 自动 clip，并尝试常见文本编码)
        for cs in ['latin1', 'utf-8', 'gbk', 'gb18030', 'cp1252']:
            try:
                mid = mido.MidiFile(file_path, clip=True, charset=cs)
                break
            except Exception:
                continue

        if mid is None:
            mid = mido.MidiFile(file_path, clip=True)

        # 1. 计算全局默认速度 BPM
        bpm = 120.0
        for track in mid.tracks:
            for msg in track:
                if msg.type == 'set_tempo':
                    bpm = round(mido.tempo2bpm(msg.tempo), 1)
                    break
            if bpm != 120.0:
                break

        # 2. 收集所有音符事件 (统一绝对时间秒数)
        # 过滤打击乐轨道 (channel 9)
        active_notes: Dict[Tuple[int, int], float] = {} # (channel, note) -> start_time
        note_events = [] # [(start_time, duration, pitch_str)]

        current_time = 0.0
        for msg in mid:
            current_time += msg.time
            # 忽略鼓点通道 9 (第10通道)
            if hasattr(msg, 'channel') and msg.channel == 9:
                continue

            if msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes[key] = current_time
            elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active_notes:
                    start_t = active_notes.pop(key)
                    dur = max(0.05, current_time - start_t)
                    pitch_str = midi_note_to_pitch(msg.note)
                    note_events.append((start_t, dur, pitch_str))

        # 收集曲终未正常发送 note_off 的残留音符
        for key, start_t in list(active_notes.items()):
            dur = max(0.08, current_time - start_t)
            pitch_str = midi_note_to_pitch(key[1])
            note_events.append((start_t, dur, pitch_str))
        active_notes.clear()

        if not note_events:
            return "# MIDI 文件未识别到有效旋律音符", bpm, 0

        # 按触发时间排序
        note_events.sort(key=lambda x: x[0])

        # 3. 将连续与重叠的音符合并为简谱时值 token
        # 每拍时长 (秒)
        beat_sec = 60.0 / bpm
        tokens = []
        last_end_time = 0.0
        i = 0
        n = len(note_events)

        chord_cluster_window = 0.035 # 35ms 内视作同时按下的和弦

        while i < n:
            start_t, dur, pitch = note_events[i]

            # 3.1 检查前导休止符
            rest_gap = start_t - last_end_time
            if rest_gap >= beat_sec * 0.4:
                rest_beats = round(rest_gap / beat_sec * 2) / 2 # 四舍五入到 0.5 拍
                if rest_beats >= 1.0:
                    whole_rests = int(rest_beats)
                    for _ in range(whole_rests):
                        tokens.append("0")
                    if rest_beats - whole_rests >= 0.5:
                        tokens.append("(0 0)") # 简谱半拍空休止
                elif rest_beats == 0.5:
                    tokens.append("(0 0)")

            # 3.2 聚合同一时窗内的音符为和弦
            cluster_pitches = [pitch]
            cluster_dur = dur
            j = i + 1
            while j < n and (note_events[j][0] - start_t) < chord_cluster_window:
                p_next = note_events[j][2]
                if p_next not in cluster_pitches:
                    cluster_pitches.append(p_next)
                cluster_dur = max(cluster_dur, note_events[j][1])
                j += 1

            i = j # 推进游标

            # 3.3 格式化音符或和弦
            beats = max(0.25, round((cluster_dur / beat_sec) * 4) / 4) # 量化到 0.25 拍
            if len(cluster_pitches) == 1:
                token_base = cluster_pitches[0]
            else:
                token_base = "[" + " ".join(cluster_pitches) + "]"

            # 根据拍数生成标记
            if beats >= 4.0:
                note_str = f"{token_base} - - -"
            elif beats >= 3.0:
                note_str = f"{token_base} - -"
            elif beats >= 2.0:
                note_str = f"{token_base} -"
            elif beats >= 1.5:
                note_str = f"{token_base}."
            elif beats >= 1.0:
                note_str = token_base
            elif beats == 0.75:
                note_str = f"{token_base}:0.75"
            elif beats == 0.5:
                note_str = f"{token_base}/2"
            elif beats <= 0.25:
                note_str = f"{token_base}/4"
            else:
                note_str = f"{token_base}:{beats}"

            tokens.append(note_str)
            last_end_time = start_t + cluster_dur

        # 4. 排版生成美观的简谱文本 (每 4~8 个 token 换行，小节排版)
        lines = [
            f"# 从 MIDI 自动转谱: {os.path.basename(file_path)}",
            f"# 识别速度 BPM: {bpm}，总计 {len(note_events)} 个音符",
            ""
        ]

        current_line = []
        bar_count = 0
        for idx, tk in enumerate(tokens, start=1):
            current_line.append(tk)
            if idx % 4 == 0:
                current_line.append("|")
                bar_count += 1
                if bar_count % 2 == 0:
                    lines.append(" ".join(current_line))
                    current_line = []

        if current_line:
            lines.append(" ".join(current_line))

        score_text = "\n".join(lines)
        return score_text, bpm, len(note_events)


if __name__ == '__main__':
    # 单元测试：生成测试 MIDI 并解析
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(100)))
    # 60=1, 62=2, 64=3, 72=1', 55=5.
    for note in [60, 62, 64, 72, 55]:
        track.append(mido.Message('note_on', note=note, velocity=64, time=0))
        track.append(mido.Message('note_off', note=note, velocity=64, time=480))
    mid.save('sample_test.mid')

    importer = MidiImporter()
    text, bpm, count = importer.import_midi('sample_test.mid')
    print("MIDI 解析测试成功:")
    print(text)
    os.remove('sample_test.mid')
