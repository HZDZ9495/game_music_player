"""
简谱解析器与音符事件模型 (升级版)
完整支持：
- 三个八度：低音 (1.~7. 或 -1~-7), 中音 (1~7), 高音 (1'~7' 或 +1~+7)
- 变音记号 / 半音：升半音 (#1, #2, #4, #5, #6), 降半音 (b2, b3, b5, b6, b7)
- 增时线 (-), 附点 (.), 连音分组 ((1 2)), 显式时值 (1/2, 1:0.5)
- 和弦 ([1 3 5 1'])
- 与 KeyConfigManager 联动，动态解析出每个音符对应的按键组合 (如 ['shift', 'space', 'v'])
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from config_manager import KeyConfigManager

# 3 个八度全半音阶频率表 (Hz)
NOTE_FREQUENCIES = {
    # 低音
    "1.": 131, "#1.": 139, "2.": 147, "#2.": 156, "3.": 165,
    "4.": 175, "#4.": 185, "5.": 196, "#5.": 208, "6.": 220, "#6.": 233, "7.": 247,
    # 中音
    "1": 262, "#1": 277, "2": 294, "#2": 311, "3": 330,
    "4": 349, "#4": 370, "5": 392, "#5": 415, "6": 440, "#6": 466, "7": 494,
    # 高音
    "1'": 523, "#1'": 554, "2'": 587, "#2'": 622, "3'": 659,
    "4'": 698, "#4'": 740, "5'": 784, "#5'": 831, "6'": 880, "#6'": 932, "7'": 988,
}

# 降半音到升半音等音映射 (b2 -> #1, b3 -> #2 等)
FLAT_TO_SHARP_MAP = {
    "b2": "#1",
    "b3": "#2",
    "b5": "#4",
    "b6": "#5",
    "b7": "#6",
    "b1": "7.",
    "b4": "3",
}

@dataclass
class NoteEvent:
    """一个弹奏事件"""
    keys: List[str]                  # 需要触发的按键序列 (如 ['shift', 'z'])
    beats: float                      # 持续拍数 (例如 1.0, 0.5, 2.0)
    raw_text: str                     # 原始标记 (如 "1'", "#4.", "[1 3 5]")
    is_rest: bool = False             # 是否为休止符 (0)
    pitch_names: List[str] = field(default_factory=list) # 规范音符名列表 (如 ["#4'"])

    @property
    def notes(self) -> List[str]:
        return self.keys

    def get_duration(self, bpm: float) -> float:
        """根据 BPM 计算实际持续时间 (秒)"""
        beat_seconds = 60.0 / bpm
        return self.beats * beat_seconds


class MusicParser:
    def __init__(self, config_mgr: Optional[KeyConfigManager] = None):
        self.config_mgr = config_mgr or KeyConfigManager()

    def set_config_manager(self, mgr: KeyConfigManager):
        self.config_mgr = mgr

    def _normalize_pitch(self, token: str) -> Optional[str]:
        """
        将单音 token 解析为标准音高代码:
        - 中音: '1', '2', '3', '4', '5', '6', '7'
        - 高音: "1'", "2'", "3'", "4'", "5'", "6'", "7'"
        - 低音: "1.", "2.", "3.", "4.", "5.", "6.", "7."
        - 升音: "#1", "#4'", "#5." 等
        """
        t = token.strip()
        # 排除休止符
        if '0' in t:
            return None

        # 1. 检查降半音 (如 b3, b7', -b3 等)
        flat_match = re.search(r'b([1-7])', t)
        is_flat = bool(flat_match)

        # 2. 检查升半音 (如 #1, 1#, +#4 等)
        is_sharp = '#' in t

        # 3. 提取数字 1-7
        digit_m = re.search(r'[1-7]', t)
        if not digit_m:
            return None
        digit = digit_m.group(0)

        # 4. 判断八度
        # 高音判定: 含有 '+', ''', '^', 或者顶部点
        # 低音判定: 含有 '-', '.', (如果在数字后面或前面有点/减号且不为增时线), ','
        octave = 0
        if any(h in t for h in ["'", "^", "+", "̇"]):
            octave = 1
        elif any(l in t for l in [",", "v"]):
            octave = -1
        elif t.startswith("-") and not t.endswith("-"):
            # 例如 -1 代表低音 1
            octave = -1
        elif "." in t:
            # 注意区分附点与低音点：若形如 1. 且没有其他附点语义，或者纯低音下点
            # 常见写法: 1. 表示下加点，若有附点写为 1.. 或带时值
            # 这里如果有明确低音或两个点：我们优先把 1. 作为低音，1.. 作为低音带附点
            # 也可以支持 1, 作为低音
            octave = -1

        # 5. 等音转换 (降半音转升半音)
        if is_flat:
            flat_key = f"b{digit}"
            if flat_key in FLAT_TO_SHARP_MAP:
                equiv = FLAT_TO_SHARP_MAP[flat_key]
                if equiv.startswith("#"):
                    is_sharp = True
                    digit = equiv[1:]
                else:
                    is_sharp = False
                    digit = equiv

        # 6. 构造标准音高代码
        res = f"#{digit}" if is_sharp else digit
        if octave == 1:
            res += "'"
        elif octave == -1:
            res += "."

        return res

    def parse(self, score_text: str) -> List[NoteEvent]:
        """解析简谱文本为 NoteEvent 序列"""
        events: List[NoteEvent] = []

        # 1. 过滤注释并合并为单行有效文本 (区分注释 # 与升半音 #1, #4)
        cleaned_lines = []
        comment_pattern = r'(\/\/.*$|(?<!\S)#(?![1-7\+\-b]).*$)'
        for line in score_text.splitlines():
            line = re.sub(comment_pattern, '', line).strip()
            if line:
                cleaned_lines.append(line)
        content = " ".join(cleaned_lines)

        if not content:
            return []

        # 2. 词法切分
        tokens = self._tokenize(content)

        i = 0
        n = len(tokens)
        while i < n:
            token = tokens[i]

            # 小节线跳过
            if token == '|':
                i += 1
                continue

            # 增时线 '-' (若单独出现，延长前一个音 1 拍)
            if token == '-':
                if events:
                    events[-1].beats += 1.0
                    events[-1].raw_text += ' -'
                i += 1
                continue

            # 处理连音分组 (1 2 3) 或 (5' 6') 或 (1 2)/2
            if token.startswith('(') and ')' in token:
                paren_end = token.rfind(')')
                inner = token[1:paren_end].strip()
                suffix = token[paren_end + 1:].strip()
                sub_tokens = self._tokenize(inner)
                sub_tokens = [st for st in sub_tokens if st != '|']
                if sub_tokens:
                    base_group_beat = 1.0
                    if suffix.startswith(':'):
                        try:
                            base_group_beat = float(suffix[1:])
                        except ValueError:
                            pass
                    elif suffix.startswith('/'):
                        try:
                            base_group_beat = 1.0 / float(suffix[1:])
                        except ValueError:
                            pass
                    elif '-' in suffix:
                        base_group_beat += suffix.count('-') * 1.0

                    each_beat = base_group_beat / len(sub_tokens)
                    for st in sub_tokens:
                        ev = self._parse_single_token(st, base_beat=each_beat)
                        if ev:
                            events.append(ev)
                i += 1
                continue

            # 处理和弦 [1 3 5] 或 [1 3 5 1']/2
            if token.startswith('[') and ']' in token:
                ev = self._parse_chord_token(token)
                if ev:
                    events.append(ev)
                i += 1
                continue

            # 普通单音 / 休止符
            ev = self._parse_single_token(token, base_beat=1.0)
            if ev:
                events.append(ev)

            i += 1

        return events

    def _tokenize(self, s: str) -> List[str]:
        tokens = []
        current = []
        in_paren = 0
        in_bracket = 0

        for char in s:
            if char == '(':
                if in_paren == 0 and in_bracket == 0 and current:
                    tokens.append("".join(current).strip())
                    current = []
                in_paren += 1
                current.append(char)
            elif char == ')':
                in_paren = max(0, in_paren - 1)
                current.append(char)
            elif char == '[':
                if in_paren == 0 and in_bracket == 0 and current:
                    tokens.append("".join(current).strip())
                    current = []
                in_bracket += 1
                current.append(char)
            elif char == ']':
                in_bracket = max(0, in_bracket - 1)
                current.append(char)
            elif char.isspace() and in_paren == 0 and in_bracket == 0:
                if current:
                    tokens.append("".join(current).strip())
                    current = []
            elif char == '|' and in_paren == 0 and in_bracket == 0:
                if current:
                    tokens.append("".join(current).strip())
                    current = []
                tokens.append('|')
            else:
                current.append(char)

        if current:
            tokens.append("".join(current).strip())

        return [t for t in tokens if t]

    def _parse_chord_token(self, token: str) -> Optional[NoteEvent]:
        """解析和弦 token，如 '[1 3 5 1']' 或 '[#4 6 1']' 或 '[6. 6]/2'"""
        bracket_end = token.rfind(']')
        if bracket_end == -1:
            return None
        inner = token[1:bracket_end].strip()
        suffix = token[bracket_end + 1:].strip()

        beats = 1.0

        # 从后缀解析时值 (例如 /2, /4, :0.5, -, .)
        if suffix.startswith(':'):
            try:
                beats = float(suffix[1:])
            except ValueError:
                pass
        elif suffix.startswith('/'):
            try:
                beats = 1.0 / float(suffix[1:])
            except ValueError:
                pass
        else:
            if '-' in suffix:
                beats += suffix.count('-') * 1.0
            if '.' in suffix:
                beats *= (1.5 ** suffix.count('.'))

        # 内部如果有 : 也支持 (例如 [1 3 5:0.5])
        if ':' in inner:
            inner, beat_str = inner.split(':', 1)
            try:
                beats = float(beat_str)
            except ValueError:
                pass

        # 提取各个子音符
        sub_tokens = self._tokenize(inner)
        all_keys = []
        all_pitches = []

        for st in sub_tokens:
            pitch = self._normalize_pitch(st)
            if pitch:
                all_pitches.append(pitch)
                keys = self.config_mgr.get_keys_for_note(pitch)
                for k in keys:
                    if k not in all_keys:
                        all_keys.append(k)

        if not all_pitches:
            return None

        return NoteEvent(
            keys=all_keys,
            beats=beats,
            raw_text=token,
            is_rest=False,
            pitch_names=all_pitches
        )

    def _parse_single_token(self, token: str, base_beat: float = 1.0) -> Optional[NoteEvent]:
        """解析单个音符或休止符 token"""
        t = token.strip()
        if not t:
            return None

        # 1. 休止符 0
        if t == '0' or t.startswith('0'):
            beats = base_beat
            if ':' in t:
                try:
                    beats = float(t.split(':', 1)[1])
                except ValueError:
                    pass
            elif '/' in t:
                try:
                    beats = base_beat / float(t.split('/', 1)[1])
                except ValueError:
                    pass
            else:
                dash_count = t.count('-')
                beats += dash_count * 1.0
                if '.' in t:
                    beats *= 1.5
            return NoteEvent(keys=[], beats=beats, raw_text=token, is_rest=True, pitch_names=['0'])

        # 2. 分离音符部分与时值后缀
        beats = base_beat
        pitch_part = t

        # 2.1 冒号显式时值 1:0.5, 1':1.5
        if ':' in t:
            parts = t.split(':', 1)
            pitch_part = parts[0]
            try:
                beats = float(parts[1])
            except ValueError:
                pass
        # 2.2 分数时值 1/2, 1/4, 1./2
        elif '/' in t:
            parts = t.split('/', 1)
            pitch_part = parts[0]
            try:
                beats = base_beat / float(parts[1])
            except ValueError:
                pass
        else:
            # 2.3 减时线下划线 _1
            if pitch_part.startswith('_') or pitch_part.endswith('_'):
                beats = 0.5
                pitch_part = pitch_part.strip('_')

            # 2.4 增时线 '-'
            dash_count = pitch_part.count('-')
            # 如果 token 形如 '-1' (低音)，负号不算增时线
            if pitch_part.startswith('-') and not pitch_part.endswith('-') and dash_count == 1:
                dash_count = 0
            elif dash_count > 0:
                pitch_part = pitch_part.replace('-', '')
            beats += dash_count * 1.0

        # 3. 提取标准音高代码
        pitch = self._normalize_pitch(pitch_part)
        if not pitch:
            return None

        keys = self.config_mgr.get_keys_for_note(pitch)

        # 4. 附点 '.' 处理 (仅在未显式指定 : 或 / 时计算)
        if ':' not in t and '/' not in t:
            dot_count = pitch_part.count('.')
            if pitch.endswith('.'):
                # 其中 1 个点用作低音标记
                dot_count = max(0, dot_count - 1)

            if dot_count == 1:
                beats *= 1.5
            elif dot_count >= 2:
                beats *= 1.75

        return NoteEvent(keys=keys, beats=beats, raw_text=token, is_rest=False, pitch_names=[pitch])


if __name__ == '__main__':
    parser = MusicParser()
    test_score = "1 1' 1. #4 #5' (b3 5) | [1 3 5 1'] - | 0"
    events = parser.parse(test_score)
    print(f"解析成功，总计 {len(events)} 个音符事件:")
    for ev in events:
        keys_str = "+".join(ev.keys) if ev.keys else "休止"
        pitches_str = ",".join(ev.pitch_names)
        print(f"  标记: {ev.raw_text:<10} 音符代码: {pitches_str:<8} 按键组合: {keys_str:<18} 拍数: {ev.beats} 拍")
