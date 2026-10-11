"""
播放引擎模块 (升级连音 Legato 引擎)
支持：
- 连音连贯模式 (Legato)：极大缩短两次发音之间的间隔，音符饱满延长，告别断断续续的机械敲击感
- 智能修饰键保持：连续同八度/半音音符持续保持按住鼠标键或修饰键，消除杂乱重复点击
- 纳秒级精准节拍控制 (基于 time.perf_counter 壁钟锚定)
- 暂停/恢复、即时停止、实时播放进度回调
"""

import time
import threading
import winsound
from typing import List, Callable, Optional, Set
from direct_input import KeyboardController, MODIFIER_KEYS
from music_parser import NoteEvent, NOTE_FREQUENCIES

class PlayerState:
    STOPPED = "STOPPED"
    COUNTDOWN = "COUNTDOWN"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"

class PlayerEngine:
    def __init__(self, key_controller: Optional[KeyboardController] = None):
        self.kb = key_controller or KeyboardController()
        self.state = PlayerState.STOPPED

        # 播放参数
        self.bpm = 100.0
        self.key_hold_time = 0.04   # 点按模式按键时间
        self.note_gap = 0.018       # 连音模式抬键发音间隔 (默认 18ms，极短间隔，声音无缝衔接)
        self.legato_mode = True     # 是否开启连音连贯模式 (默认开启)
        self.events: List[NoteEvent] = []
        self.current_index = 0
        self.is_preview_mode = False # 蜂鸣器试听模式

        # 线程控制
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()

        # 回调函数
        self.on_state_change: Optional[Callable[[str], None]] = None
        self.on_note_start: Optional[Callable[[int, NoteEvent], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None
        self.on_countdown: Optional[Callable[[int], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def _set_state(self, new_state: str):
        self.state = new_state
        if self.on_state_change:
            try:
                self.on_state_change(new_state)
            except Exception:
                pass

    def start_play(self, events: List[NoteEvent], bpm: float = 100.0, key_hold_time: float = 0.04,
                   note_gap: float = 0.018, legato_mode: bool = True,
                   countdown_seconds: int = 0, preview: bool = False):
        """开始播放 (支持连音连贯控制与参数设定)"""
        self.stop()

        self.events = list(events)
        self.bpm = max(20.0, min(300.0, bpm))
        self.key_hold_time = max(0.01, min(0.3, key_hold_time))
        self.note_gap = max(0.005, min(0.06, note_gap))
        self.legato_mode = legato_mode
        self.current_index = 0
        self.is_preview_mode = preview

        self._stop_event.clear()
        self._pause_event.set()
        initial_state = PlayerState.COUNTDOWN if (countdown_seconds > 0 and not preview) else PlayerState.PLAYING
        self._set_state(initial_state)

        self._thread = threading.Thread(
            target=self._play_loop,
            args=(countdown_seconds,),
            daemon=True
        )
        self._thread.start()

    def toggle_pause(self):
        """切换 暂停 / 继续"""
        if self.state == PlayerState.PLAYING:
            self._pause_event.clear()
            self._set_state(PlayerState.PAUSED)
            self.kb.release_all()
        elif self.state == PlayerState.PAUSED:
            self._pause_event.set()
            self._set_state(PlayerState.PLAYING)

    def stop(self):
        """停止播放并重置所有按键"""
        self._stop_event.set()
        self._pause_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None
        self.kb.release_all()
        self._set_state(PlayerState.STOPPED)

    def _play_loop(self, countdown_seconds: int):
        # 1. 倒计时准备
        if countdown_seconds > 0 and not self.is_preview_mode:
            self._set_state(PlayerState.COUNTDOWN)
            for remaining in range(countdown_seconds, 0, -1):
                if self._stop_event.is_set():
                    self._set_state(PlayerState.STOPPED)
                    return
                if self.on_countdown:
                    try:
                        self.on_countdown(remaining)
                    except Exception:
                        pass
                try:
                    winsound.Beep(800, 100)
                except Exception:
                    pass
                time.sleep(0.9)

        if self._stop_event.is_set():
            self._set_state(PlayerState.STOPPED)
            return

        if not self.is_preview_mode:
            try:
                winsound.Beep(1200, 150)
            except Exception:
                pass

        self._set_state(PlayerState.PLAYING)
        n = len(self.events)

        try:
            while self.current_index < n:
                if self._stop_event.is_set():
                    break

                # 暂停等待
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                ev = self.events[self.current_index]
                total_duration = ev.get_duration(self.bpm)
                note_start_time = time.perf_counter()

                if self.on_note_start:
                    try:
                        self.on_note_start(self.current_index, ev)
                    except Exception:
                        pass

                # 执行按键或发音
                if ev.is_rest:
                    # 休止符：释放基础音符与修饰键
                    self.kb.release_notes()
                    self.kb.set_modifiers(set())
                    self._interruptible_sleep(total_duration)
                elif self.is_preview_mode:
                    # 蜂鸣器试听 (同样应用连音时值控制)
                    freq = 440
                    if ev.pitch_names:
                        freq = NOTE_FREQUENCIES.get(ev.pitch_names[0], 440)
                    effective_gap = min(self.note_gap, total_duration * 0.15)
                    tone_dur_ms = int(max(30, (total_duration - effective_gap) * 1000 * 0.95))
                    try:
                        winsound.Beep(freq, tone_dur_ms)
                    except Exception:
                        pass
                    rest_time = total_duration - (tone_dur_ms / 1000.0)
                    if rest_time > 0:
                        self._interruptible_sleep(rest_time)
                else:
                    # 游戏连贯连音 (Legato) 按键模拟
                    keys_to_play = getattr(ev, 'keys', None) or getattr(ev, 'notes', [])
                    mods = {k.lower().strip() for k in keys_to_play if k.lower().strip() in MODIFIER_KEYS}
                    bases = [k.lower().strip() for k in keys_to_play if k.lower().strip() not in MODIFIER_KEYS]

                    # 1. 智能维持修饰键状态 (同八度/半音持续按住，避免频繁抬起按下)
                    self.kb.set_modifiers(mods)

                    # 2. 按下当前基础音符按键
                    if bases:
                        self.kb.press_notes(bases)

                    # 3. 计算音符发音饱满保持时长
                    if self.legato_mode:
                        # 连音模式：发音占满绝大部分时值，两次发音间隔缩短至极小 (如 18ms)
                        effective_gap = min(self.note_gap, total_duration * 0.15)
                        hold_time = max(0.025, total_duration - effective_gap)
                    else:
                        hold_time = min(self.key_hold_time, total_duration * 0.8)

                    self._interruptible_sleep(hold_time)

                    # 4. 释放当前音符按键 (保持修饰键状态不变)
                    if bases:
                        self.kb.release_notes(bases)

                    # 5. 精确睡眠剩余间隔时间，无缝切入下一个音符
                    target_end = note_start_time + total_duration
                    remaining_time = target_end - time.perf_counter()
                    if remaining_time > 0:
                        self._interruptible_sleep(remaining_time)

                self.current_index += 1
        except Exception as e:
            print(f"[PlayerEngine] 弹奏过程发生异常: {e}")
            if hasattr(self, 'on_error') and self.on_error:
                try:
                    self.on_error(str(e))
                except Exception:
                    pass
        finally:
            self.kb.release_all()
            self._set_state(PlayerState.STOPPED)
            if not self._stop_event.is_set() and self.on_finished:
                try:
                    self.on_finished()
                except Exception:
                    pass

    def _interruptible_sleep(self, duration: float, step: float = 0.005):
        """高精度细颗粒度可中断睡眠 (毫秒级响应)"""
        end_time = time.perf_counter() + duration
        while time.perf_counter() < end_time:
            if self._stop_event.is_set():
                break
            if not self._pause_event.is_set():
                self._pause_event.wait()
            time.sleep(min(step, max(0.0005, end_time - time.perf_counter())))
