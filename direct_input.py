"""
Windows 底层按键与鼠标模拟模块
基于 Windows API DirectInput 硬件扫描码 (Scan Code) 与 鼠标事件 (mouse_event)。
完美适配：
- 键盘音符按键: Z, X, C, V, B, N, M, 以及高音1键 ',' (逗号)
- 鼠标修饰键: 鼠标左键 (降调), 鼠标右键 (升调), 鼠标中键 (半音)
- 键盘修饰键: Shift, Ctrl, Alt, Space
时序保护机制：先按住修饰键/鼠标键 -> 触发音符键 -> 释放音符键 -> 释放修饰键/鼠标键。
"""

import ctypes
from ctypes import wintypes
import time
from typing import List, Set, Optional

user32 = ctypes.windll.user32

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# 鼠标事件标志
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

MOUSE_BUTTONS = {
    'mouse_left': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    'mouse_right': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    'mouse_middle': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    'left_click': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    'right_click': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    'middle_click': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# 硬件扫描码映射 (US 键盘布局)
DEFAULT_SCANCODES = {
    # 口琴基础音 1~7 及 高音 1 (逗号 ,)
    'z': 0x2C, # 1 Do
    'x': 0x2D, # 2 Re
    'c': 0x2E, # 3 Mi
    'v': 0x2F, # 4 Fa
    'b': 0x30, # 5 Sol
    'n': 0x31, # 6 La
    'm': 0x32, # 7 Ti
    ',': 0x33, # 高音 1 (1̇ 逗号键)
    '.': 0x34,
    '/': 0x35,
    # 键盘修饰键与功能键
    'shift': 0x2A,
    'lshift': 0x2A,
    'rshift': 0x36,
    'ctrl': 0x1D,
    'lctrl': 0x1D,
    'rctrl': 0x1D,
    'alt': 0x38,
    'lalt': 0x38,
    'space': 0x39,
    'tab': 0x0F,
    'caps': 0x3A,
    # 辅助字母键 (a~j, q~u)
    'a': 0x1E, 's': 0x1F, 'd': 0x20, 'f': 0x21, 'g': 0x22, 'h': 0x23, 'j': 0x24,
    'q': 0x10, 'w': 0x11, 'e': 0x12, 'r': 0x13, 't': 0x14, 'y': 0x15, 'u': 0x16,
}

MODIFIER_KEYS = {
    'shift', 'lshift', 'rshift', 'ctrl', 'lctrl', 'rctrl', 'alt', 'lalt', 'space',
    'mouse_left', 'mouse_right', 'mouse_middle', 'left_click', 'right_click', 'middle_click'
}

class KeyboardController:
    def __init__(self):
        self._pressed_keys: Set[str] = set()
        self._pressed_mouse: Set[str] = set()
        self._active_modifiers: Set[str] = set()
        self._active_notes: Set[str] = set()
        self._scancode_cache = dict(DEFAULT_SCANCODES)

    def get_scancode(self, key: str) -> int:
        """获取按键的硬件扫描码"""
        key_lower = key.lower().strip()
        if key_lower in self._scancode_cache:
            return self._scancode_cache[key_lower]

        if key_lower == ',':
            return 0x33

        if len(key_lower) == 1:
            vk = ord(key_lower.upper())
            scancode = user32.MapVirtualKeyW(vk, 0)
            if scancode:
                self._scancode_cache[key_lower] = scancode
                return scancode

        return 0

    def press(self, key: str):
        """按下按键或鼠标按钮 (不释放)"""
        k = key.lower().strip()
        if k in MOUSE_BUTTONS:
            down_flag = MOUSE_BUTTONS[k][0]
            user32.mouse_event(down_flag, 0, 0, 0, 0)
            self._pressed_mouse.add(k)
            return

        scan = self.get_scancode(k)
        if not scan:
            return
        user32.keybd_event(0, scan, KEYEVENTF_SCANCODE, 0)
        self._pressed_keys.add(k)

    def release(self, key: str):
        """释放按键或鼠标按钮"""
        k = key.lower().strip()
        if k in MOUSE_BUTTONS:
            up_flag = MOUSE_BUTTONS[k][1]
            user32.mouse_event(up_flag, 0, 0, 0, 0)
            self._pressed_mouse.discard(k)
            return

        scan = self.get_scancode(k)
        if not scan:
            return
        user32.keybd_event(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
        self._pressed_keys.discard(k)

    def set_modifiers(self, needed_modifiers: Set[str]):
        """
        智能维持当前激活的修饰键/鼠标按键 (升调/降调/半音)
        若下一音符与当前音符共享相同修饰键，则持续按住，避免重复抬起按下带来的发音断续和杂乱点击
        """
        needed = {m.lower().strip() for m in needed_modifiers if m}
        
        # 释放不再需要的修饰键
        to_release = self._active_modifiers - needed
        for m in to_release:
            self.release(m)
            self._active_modifiers.discard(m)

        # 按下新增加的修饰键
        to_press = needed - self._active_modifiers
        for m in to_press:
            self.press(m)
            self._active_modifiers.add(m)

        if to_press:
            time.sleep(0.005) # 新修饰键按下时微等待 5ms 供游戏识别

    def press_notes(self, keys: List[str]):
        """按下当前音符按键"""
        for k in keys:
            k_lower = k.lower().strip()
            self.press(k_lower)
            self._active_notes.add(k_lower)

    def release_notes(self, keys: Optional[List[str]] = None):
        """释放当前音符按键 (保持修饰键状态不变)"""
        target = list(keys) if keys is not None else list(self._active_notes)
        for k in target:
            k_lower = k.lower().strip()
            self.release(k_lower)
            self._active_notes.discard(k_lower)

    def play_combination(self, keys: List[str], hold_duration: float = 0.035):
        """
        传统点按模式：触发一个音符或组合键
        1. 划分修饰键 (鼠标左/中/右键, shift, ctrl) 与基础音符键 (z~m, ,)
        2. 先按下修饰键
        3. 再按下基础音符键
        4. 保持 hold_duration
        5. 释放基础音符键
        6. 释放修饰键
        """
        mods = [k for k in keys if k.lower().strip() in MODIFIER_KEYS]
        bases = [k for k in keys if k.lower().strip() not in MODIFIER_KEYS]

        # 1. 先按下修饰键 / 鼠标键
        for m in mods:
            self.press(m)

        if mods and bases:
            time.sleep(0.005) # 微等待确保游戏捕获到修饰状态

        # 2. 按下基础目标音符键 (如 z, x, c, v, b, n, m, ,)
        for b in bases:
            self.press(b)

        # 3. 保持按键时间
        if hold_duration > 0:
            time.sleep(hold_duration)

        # 4. 释放基础音符键
        for b in bases:
            self.release(b)

        if mods and bases:
            time.sleep(0.003)

        # 5. 释放修饰键 / 鼠标键
        for m in mods:
            self.release(m)

    def tap(self, key: str, hold_duration: float = 0.035):
        """轻按并释放单个按键"""
        self.play_combination([key], hold_duration)

    def chord(self, keys: List[str], hold_duration: float = 0.035):
        """和弦弹奏"""
        self.play_combination(keys, hold_duration)

    def release_all(self):
        """紧急释放所有可能残留按下的键盘键与鼠标按钮"""
        for k in list(self._pressed_keys):
            self.release(k)
        for m in list(self._pressed_mouse):
            self.release(m)

        # 兜底释放所有常见鼠标按键
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)

        # 兜底释放常见键盘按键
        for k in ['shift', 'ctrl', 'alt', 'space', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',']:
            scan = self.get_scancode(k)
            if scan:
                user32.keybd_event(0, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)

        self._pressed_keys.clear()
        self._pressed_mouse.clear()
        self._active_modifiers.clear()
        self._active_notes.clear()


if __name__ == '__main__':
    kb = KeyboardController()
    print("测试音符扫描码:")
    for note, k in [("1", "z"), ("2", "x"), ("3", "c"), ("4", "v"), ("5", "b"), ("6", "n"), ("7", "m"), ("1̇", ",")]:
        print(f"  音符 {note:<3} -> 键位 '{k}' -> 扫描码: {hex(kb.get_scancode(k))}")
    print("测试鼠标修饰键支持:")
    for m in ['mouse_left (降调)', 'mouse_middle (半音)', 'mouse_right (升调)']:
        btn = m.split()[0]
        print(f"  修饰键 '{btn}' -> 映射成功: {btn in MOUSE_BUTTONS}")
