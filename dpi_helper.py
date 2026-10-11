"""
Windows 高 DPI 清晰度适配模块
解决 Windows 缩放设置 (如 125%、150%、200%) 下 Tkinter 界面模糊、字体发虚的问题。
在创建 Tkinter 窗口前调用，通知 Windows 使用进程级原生 DPI 渲染。
"""

import ctypes
import os
import sys

def init_dpi_awareness() -> float:
    """
    初始化 Windows DPI 感知，返回当前主显示器的缩放比例因子 (如 1.0, 1.25, 1.5, 2.0)。
    必须在创建 tk.Tk() 之前调用！
    """
    if sys.platform != 'win32':
        return 1.0

    # 1. 尝试设置 DPI 感知 (Windows 8.1+ Per-Monitor V2, 或 Windows Vista+ System DPI)
    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # 1 = PROCESS_SYSTEM_DPI_AWARE
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    # 2. 查询当前屏幕物理 DPI
    scale = 1.0
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        # 88 = LOGPIXELSX
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        scale = max(1.0, dpi / 96.0)
    except Exception:
        scale = 1.0

    return scale


def apply_tk_scaling(root, scale: float):
    """通知 Tkinter 内部字体与度量引擎当前的 DPI 缩放比例"""
    try:
        root.tk.call('tk', 'scaling', scale)
    except Exception:
        pass


if __name__ == '__main__':
    scale = init_dpi_awareness()
    print(f"当前 Windows 屏幕 DPI 缩放倍率: {scale * 100:.0f}% (因子: {scale:.2f})")
