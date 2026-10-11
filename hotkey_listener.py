"""
全局热键监听模块 (基于 Windows GetAsyncKeyState)
无需聚焦当前窗口，无需依赖外部 C 扩展库，在全屏游戏、无边框窗口模式下均可全局生效。
- F8: 启动 / 暂停 (Toggle Play / Pause)
- F9: 停止播放 (Stop)
- Esc: 紧急停止 (Emergency Stop)
"""

import ctypes
import threading
import time
from typing import Callable, Optional

user32 = ctypes.windll.user32

VK_F8 = 0x77
VK_F9 = 0x78
VK_ESCAPE = 0x1B

class GlobalHotkeyListener:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._key_states = {
            VK_F8: False,
            VK_F9: False,
            VK_ESCAPE: False
        }

        # 回调列表
        self.on_f8: Optional[Callable[[], None]] = None
        self.on_f9: Optional[Callable[[], None]] = None
        self.on_esc: Optional[Callable[[], None]] = None

    def start(self):
        """启动后台全局热键监听"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止监听"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.2)
        self._thread = None

    def _listen_loop(self):
        while self._running:
            for vk in (VK_F8, VK_F9, VK_ESCAPE):
                # 检查最高位是否为 1 (代表键当前处于按下状态)
                is_pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                was_pressed = self._key_states[vk]

                # 边沿触发：由 未按下 -> 按下 时触发一次
                if is_pressed and not was_pressed:
                    self._dispatch_hotkey(vk)

                self._key_states[vk] = is_pressed

            time.sleep(0.025) # 25ms 轮询间隔，极低 CPU 占用且按键响应延迟仅 1/40 秒

    def _dispatch_hotkey(self, vk: int):
        try:
            if vk == VK_F8 and self.on_f8:
                self.on_f8()
            elif vk == VK_F9 and self.on_f9:
                self.on_f9()
            elif vk == VK_ESCAPE and self.on_esc:
                self.on_esc()
        except Exception as e:
            print(f"[Hotkey Error] {e}")


if __name__ == '__main__':
    listener = GlobalHotkeyListener()
    listener.on_f8 = lambda: print("[Hotkey Triggered] F8 (开始/暂停)")
    listener.on_f9 = lambda: print("[Hotkey Triggered] F9 (停止)")
    listener.on_esc = lambda: print("[Hotkey Triggered] ESC (紧急停止)")
    listener.start()
    print("热键监听已启动 (按 F8, F9, ESC 测试，Ctrl+C 退出)...")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        listener.stop()
