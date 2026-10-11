"""
Tkinter 现代化可视化图形界面
特性：
- 完美适配游戏口琴界面 (Z~M, 逗号高音1, 鼠标左键降调, 鼠标中键半音, 鼠标右键升调)
- 完美适配 Windows 高 DPI 缩放 (125%, 150%, 200%)，杜绝模糊与字体发虚
- 支持导入 MIDI 文件 (.mid, .midi) 自动转口琴简谱
- 支持导入 MP4 视频及音频文件 (.mp4, .m4a, .mp3, .wav) 智能分析旋律转谱
- 支持弹奏时同步播放 MP4 原声伴奏
- 支持后台全局热键 F8 / F9 / Esc
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
from typing import Optional, List

from dpi_helper import init_dpi_awareness, apply_tk_scaling
from direct_input import KeyboardController
from config_manager import KeyConfigManager
from music_parser import MusicParser
from player_engine import PlayerEngine, PlayerState
from hotkey_listener import GlobalHotkeyListener
from songs import SONGS_LIBRARY
from midi_importer import MidiImporter
from media_importer import MediaImporter

def format_action_name(k: str) -> str:
    """将按键/鼠标代码格式化为友好中文展示名称"""
    k_lower = k.lower().strip()
    mapping = {
        'mouse_left': '鼠标左键(降调)',
        'left_click': '鼠标左键(降调)',
        'mouse_right': '鼠标右键(升调)',
        'right_click': '鼠标右键(升调)',
        'mouse_middle': '鼠标中键(半音)',
        'middle_click': '鼠标中键(半音)',
        'shift': 'Shift',
        'ctrl': 'Ctrl',
        'alt': 'Alt',
        'space': 'Space',
        ',': ', (逗号)',
    }
    return mapping.get(k_lower, k.upper())

class KeySettingsDialog(tk.Toplevel):
    """键位与修饰键自定义配置窗口"""
    def __init__(self, parent, config_mgr: KeyConfigManager, scale: float, on_saved_callback):
        super().__init__(parent)
        self.scale = scale
        self.title("⚙ 游戏键位与升降调设置")
        w = int(540 * scale)
        h = int(480 * scale)
        self.geometry(f"{w}x{h}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.config_mgr = config_mgr
        self.on_saved = on_saved_callback

        self._build_ui()

    def _build_ui(self):
        pad_frame = ttk.Frame(self, padding="14")
        pad_frame.pack(fill=tk.BOTH, expand=True)

        # 0. 预设快捷切换
        scheme_frame = ttk.LabelFrame(pad_frame, text=" ⚡ 快速预设方案 ", padding="8")
        scheme_frame.pack(fill=tk.X, pady=(0, 10))

        btn_game_preset = ttk.Button(scheme_frame, text="🎮 恢复游戏原生模式 (鼠标升降调/半音 + 逗号高音1)", command=self._apply_game_preset)
        btn_game_preset.pack(side=tk.LEFT, padx=4)

        btn_kb_preset = ttk.Button(scheme_frame, text="⌨ 切换为纯键盘模式", command=self._apply_kb_preset)
        btn_kb_preset.pack(side=tk.LEFT, padx=4)

        # 1. 修饰动作设置
        mod_frame = ttk.LabelFrame(pad_frame, text=" 🎛 升降调与半音触发动作设置 ", padding="10")
        mod_frame.pack(fill=tk.X, pady=(0, 10))

        mod_options = [
            "mouse_right", "mouse_left", "mouse_middle",
            "shift", "ctrl", "alt", "space", "none"
        ]

        ttk.Label(mod_frame, text="升调动作 (高八度，如 2'):").grid(row=0, column=0, sticky="w", pady=4)
        self.high_mod_var = tk.StringVar(value=self.config_mgr.config["modifiers"].get("high_octave", "mouse_right"))
        self.high_combo = ttk.Combobox(mod_frame, textvariable=self.high_mod_var, values=mod_options, width=16)
        self.high_combo.grid(row=0, column=1, padx=8, pady=4)

        ttk.Label(mod_frame, text="降调动作 (低八度，如 1.):").grid(row=1, column=0, sticky="w", pady=4)
        self.low_mod_var = tk.StringVar(value=self.config_mgr.config["modifiers"].get("low_octave", "mouse_left"))
        self.low_combo = ttk.Combobox(mod_frame, textvariable=self.low_mod_var, values=mod_options, width=16)
        self.low_combo.grid(row=1, column=1, padx=8, pady=4)

        ttk.Label(mod_frame, text="半音动作 (升半音，如 #4):").grid(row=2, column=0, sticky="w", pady=4)
        self.semi_mod_var = tk.StringVar(value=self.config_mgr.config["modifiers"].get("semitone", "mouse_middle"))
        self.semi_combo = ttk.Combobox(mod_frame, textvariable=self.semi_mod_var, values=mod_options, width=16)
        self.semi_combo.grid(row=2, column=1, padx=8, pady=4)

        tip_lbl = ttk.Label(
            mod_frame,
            text="* 提示: mouse_right=鼠标右键, mouse_left=鼠标左键, mouse_middle=鼠标中键/滚轮",
            font=("Microsoft YaHei UI", 8),
            foreground="#64748b"
        )
        tip_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # 2. 基础 1~7 及高音 1 (逗号) 键位设置
        base_frame = ttk.LabelFrame(pad_frame, text=" 🎹 基础按键设置 (1~7 度及高音 1̇) ", padding="10")
        base_frame.pack(fill=tk.X, pady=(0, 10))

        self.base_entries = {}
        note_headers = [("1", "音 1"), ("2", "音 2"), ("3", "音 3"), ("4", "音 4"),
                        ("5", "音 5"), ("6", "音 6"), ("7", "音 7"), ("1'", "高音 1̇")]
        for col, (pitch_key, title) in enumerate(note_headers):
            f = ttk.Frame(base_frame)
            f.grid(row=0, column=col, padx=4)
            ttk.Label(f, text=title, font=("Microsoft YaHei UI", 8)).pack()
            e = ttk.Entry(f, width=4, justify="center")
            e.insert(0, self.config_mgr.config["base_keys"].get(pitch_key, ""))
            e.pack(pady=2)
            self.base_entries[pitch_key] = e

        # 3. 按钮栏
        btn_frame = ttk.Frame(pad_frame)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_reset = ttk.Button(btn_frame, text="恢复默认", command=self._apply_game_preset)
        btn_reset.pack(side=tk.LEFT)

        btn_cancel = ttk.Button(btn_frame, text="取消", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=4)

        btn_save = ttk.Button(btn_frame, text="✔ 保存设置", command=self._on_save)
        btn_save.pack(side=tk.RIGHT, padx=4)

    def _apply_game_preset(self):
        self.config_mgr.set_scheme("game_mouse")
        self._refresh_fields()

    def _apply_kb_preset(self):
        self.config_mgr.set_scheme("keyboard")
        self._refresh_fields()

    def _refresh_fields(self):
        self.high_mod_var.set(self.config_mgr.config["modifiers"]["high_octave"])
        self.low_mod_var.set(self.config_mgr.config["modifiers"]["low_octave"])
        self.semi_mod_var.set(self.config_mgr.config["modifiers"]["semitone"])
        for k, entry in self.base_entries.items():
            entry.delete(0, tk.END)
            entry.insert(0, self.config_mgr.config["base_keys"].get(k, ""))
        if self.on_saved:
            self.on_saved()

    def _on_save(self):
        self.config_mgr.config["modifiers"]["high_octave"] = self.high_mod_var.get().strip().lower()
        self.config_mgr.config["modifiers"]["low_octave"] = self.low_mod_var.get().strip().lower()
        self.config_mgr.config["modifiers"]["semitone"] = self.semi_mod_var.get().strip().lower()

        for k, entry in self.base_entries.items():
            val = entry.get().strip().lower()
            if val:
                self.config_mgr.config["base_keys"][k] = val

        # 确保高音 1 覆盖逻辑生效
        high_1_key = self.config_mgr.config["base_keys"].get("1'", ",")
        self.config_mgr.config["custom_overrides"]["1'"] = [high_1_key]
        semi_mod = self.config_mgr.config["modifiers"]["semitone"]
        self.config_mgr.config["custom_overrides"]["#1'"] = [semi_mod, high_1_key]

        self.config_mgr.save()
        if self.on_saved:
            self.on_saved()
        self.destroy()


class MusicPlayerGUI:
    def __init__(self, root: tk.Tk, scale: float = 1.0):
        self.root = root
        self.scale = scale
        self.root.title("口琴自动音乐弹奏助手 (永劫无间/多模式支持)")

        # 依据系统 DPI 比例设定精准窗口尺寸与最小尺寸
        win_w = int(880 * scale)
        win_h = int(800 * scale)
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(int(760 * scale), int(680 * scale))

        # 核心业务组件
        self.config_mgr = KeyConfigManager()
        self.kb = KeyboardController()
        self.parser = MusicParser(self.config_mgr)
        self.player = PlayerEngine(self.kb)
        self.hotkey = GlobalHotkeyListener()
        self.midi_importer = MidiImporter()
        self.media_importer = MediaImporter()

        # 伴奏控制变量
        self.sync_audio_var = tk.BooleanVar(value=False)
        self.loaded_media_file: Optional[str] = None

        # 绑定播放引擎回调
        self.player.on_state_change = self._on_player_state_change
        self.player.on_note_start = self._on_note_start
        self.player.on_countdown = self._on_countdown
        self.player.on_finished = self._on_finished
        self.player.on_error = self._on_player_error

        # 绑定全局热键回调
        self.hotkey.on_f8 = self._on_hotkey_toggle
        self.hotkey.on_f9 = self._on_hotkey_stop
        self.hotkey.on_esc = self._on_hotkey_stop

        # UI 构建
        self._setup_style()
        self._build_ui()

        # 启动热键监听
        self.hotkey.start()

        # 加载初始歌曲
        first_song = list(SONGS_LIBRARY.keys())[0]
        self.song_var.set(first_song)
        self._on_song_select(None)

        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use('vista')
        except Exception:
            pass

    def _build_ui(self):
        # 1. 顶部标题与热键指示栏
        top_frame = ttk.Frame(self.root, padding="12 10 12 4")
        top_frame.pack(fill=tk.X)

        title_lbl = ttk.Label(
            top_frame,
            text="🎵 口琴自动弹奏助手",
            font=("Microsoft YaHei UI", 15, "bold"),
            foreground="#0f172a"
        )
        title_lbl.pack(side=tk.LEFT)

        btn_settings = ttk.Button(top_frame, text="⚙ 键位设置", command=self._open_settings)
        btn_settings.pack(side=tk.LEFT, padx=10)

        hotkey_tag = ttk.Label(
            top_frame,
            text="全局热键：[F8] 开始/暂停  |  [F9] 停止  |  [Esc] 紧急中止",
            font=("Microsoft YaHei UI", 9, "bold"),
            foreground="#0369a1",
            background="#e0f2fe",
            padding="6 4"
        )
        hotkey_tag.pack(side=tk.RIGHT)

        # 2. 键位映射展示框 (完整匹配游戏口琴 1~7 及 1̇)
        self.keys_frame = ttk.LabelFrame(self.root, text=" 🎹 游戏口琴键位与升降调动作 ", padding="8 6")
        self.keys_frame.pack(fill=tk.X, padx=12, pady=4)
        self._render_key_map_banner()

        # 3. 曲谱选择与加载区
        select_frame = ttk.Frame(self.root, padding="12 4 12 4")
        select_frame.pack(fill=tk.X)

        ttk.Label(select_frame, text="内置曲谱：", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)

        self.song_var = tk.StringVar()
        self.song_combo = ttk.Combobox(
            select_frame,
            textvariable=self.song_var,
            values=list(SONGS_LIBRARY.keys()),
            state="readonly",
            width=26,
            font=("Microsoft YaHei UI", 9)
        )
        self.song_combo.pack(side=tk.LEFT, padx=4)
        self.song_combo.bind("<<ComboboxSelected>>", self._on_song_select)

        # 各种导入按钮
        btn_load_txt = ttk.Button(select_frame, text="📁 导入TXT", command=self._import_txt)
        btn_load_txt.pack(side=tk.LEFT, padx=3)

        btn_load_midi = ttk.Button(select_frame, text="🎹 导入MIDI", command=self._import_midi)
        btn_load_midi.pack(side=tk.LEFT, padx=3)

        btn_load_media = ttk.Button(select_frame, text="🎬 导入MP4转谱", command=self._import_media)
        btn_load_media.pack(side=tk.LEFT, padx=3)

        btn_save_file = ttk.Button(select_frame, text="💾 保存", command=self._export_file)
        btn_save_file.pack(side=tk.LEFT, padx=3)

        btn_clear = ttk.Button(select_frame, text="🗑 清空", command=self._clear_score)
        btn_clear.pack(side=tk.RIGHT, padx=4)

        # 4. 曲谱编辑区
        editor_frame = ttk.LabelFrame(self.root, text=" 📝 简谱文本编辑器 (1~7、高音 1'~7'、低音 1.~7.、半音 #4、和弦 [1 3 5]) ", padding="6")
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        self.score_text = tk.Text(
            editor_frame,
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg="#ffffff",
            fg="#1e293b",
            relief=tk.SOLID,
            borderwidth=1,
            undo=True
        )
        self.score_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(editor_frame, orient=tk.VERTICAL, command=self.score_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.score_text.config(yscrollcommand=scrollbar.set)

        # 5. 参数调节栏 (BPM, 延时, 倒计时, 伴奏同步)
        params_frame = ttk.Frame(self.root, padding="12 4")
        params_frame.pack(fill=tk.X)

        # 5.1 BPM 速度
        ttk.Label(params_frame, text="速度 (BPM):", font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w")
        self.bpm_scale = ttk.Scale(params_frame, from_=40, to=220, orient=tk.HORIZONTAL, length=130, command=self._on_bpm_change)
        self.bpm_lbl = ttk.Label(params_frame, text="100", width=4, font=("Consolas", 10, "bold"))
        self.bpm_scale.set(100)
        self.bpm_scale.grid(row=0, column=1, padx=6)
        self.bpm_lbl.grid(row=0, column=2, padx=4)

        # 5.2 两次发音间隔 (Gap ms，控制连贯度)
        ttk.Label(params_frame, text="发音间隔 (Gap):", font=("Microsoft YaHei UI", 9)).grid(row=0, column=3, padx=(12, 0), sticky="w")
        self.gap_scale = ttk.Scale(params_frame, from_=5, to=50, orient=tk.HORIZONTAL, length=90, command=self._on_gap_change)
        self.gap_lbl = ttk.Label(params_frame, text="18 ms", width=6, font=("Consolas", 10, "bold"))
        self.gap_scale.set(18)
        self.gap_scale.grid(row=0, column=4, padx=4)
        self.gap_lbl.grid(row=0, column=5, padx=2)

        # 5.3 启动倒计时 (秒)
        ttk.Label(params_frame, text="倒计时 (秒):", font=("Microsoft YaHei UI", 9)).grid(row=0, column=6, padx=(10, 0), sticky="w")
        self.countdown_spin = ttk.Spinbox(params_frame, from_=0, to=10, width=3)
        self.countdown_spin.set("3")
        self.countdown_spin.grid(row=0, column=7, padx=4)

        # 5.4 连音连贯模式与伴奏复选框
        self.legato_var = tk.BooleanVar(value=True)
        self.cb_legato = ttk.Checkbutton(
            params_frame,
            text="连音连贯模式",
            variable=self.legato_var
        )
        self.cb_legato.grid(row=0, column=8, padx=(10, 0))

        self.cb_sync = ttk.Checkbutton(
            params_frame,
            text="同步播放MP4伴奏",
            variable=self.sync_audio_var
        )
        self.cb_sync.grid(row=0, column=9, padx=(8, 0))

        # 6. 控制按钮栏与状态
        control_frame = ttk.Frame(self.root, padding="12 6")
        control_frame.pack(fill=tk.X)

        self.btn_play = tk.Button(
            control_frame,
            text="▶ 开始弹奏 (游戏内按键)",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg="#16a34a",
            fg="#ffffff",
            activebackground="#15803d",
            activeforeground="#ffffff",
            padx=14,
            pady=6,
            relief=tk.FLAT,
            command=self._start_game_play
        )
        self.btn_play.pack(side=tk.LEFT, padx=4)

        self.btn_pause = ttk.Button(control_frame, text="⏸ 暂停/继续", command=self._toggle_pause)
        self.btn_pause.pack(side=tk.LEFT, padx=4)

        self.btn_stop = ttk.Button(control_frame, text="⏹ 停止", command=self._stop_play)
        self.btn_stop.pack(side=tk.LEFT, padx=4)

        self.btn_preview = ttk.Button(control_frame, text="🔊 PC蜂鸣器试听", command=self._start_preview)
        self.btn_preview.pack(side=tk.LEFT, padx=8)

        # 状态标签
        self.status_lbl = ttk.Label(
            control_frame,
            text="● 状态: 空闲就绪",
            font=("Microsoft YaHei UI", 10, "bold"),
            foreground="#475569"
        )
        self.status_lbl.pack(side=tk.RIGHT, padx=6)

        # 7. 进度与实时音符显示
        progress_frame = ttk.Frame(self.root, padding="12 4 12 8")
        progress_frame.pack(fill=tk.X)

        self.progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=2)

        self.current_note_lbl = ttk.Label(
            progress_frame,
            text="提示: 点击开始后有 3 秒切屏时间，或在游戏中直接按 F8 随时开弹！",
            font=("Microsoft YaHei UI", 9),
            foreground="#64748b"
        )
        self.current_note_lbl.pack(anchor="w", pady=2)

    def _render_key_map_banner(self):
        """渲染键位和修饰动作横幅 (精确还原截图布局)"""
        for widget in self.keys_frame.winfo_children():
            widget.destroy()

        mods = self.config_mgr.config["modifiers"]
        low_mod = format_action_name(mods.get("low_octave", "mouse_left"))
        semi_mod = format_action_name(mods.get("semitone", "mouse_middle"))
        high_mod = format_action_name(mods.get("high_octave", "mouse_right"))

        # 上排：音符与按键卡片 (1~7 以及高音 1̇)
        cards_frame = ttk.Frame(self.keys_frame)
        cards_frame.pack(fill=tk.X, pady=(2, 6))

        note_definitions = [
            ("1", "1", "Z"),
            ("2", "2", "X"),
            ("3", "3", "C"),
            ("4", "4", "V"),
            ("5", "5", "B"),
            ("6", "6", "N"),
            ("7", "7", "M"),
            ("1'", "1̇", ","),
        ]

        for idx, (p_key, display_note, default_k) in enumerate(note_definitions):
            k_char = self.config_mgr.config["base_keys"].get(p_key, default_k).upper()
            box = ttk.Frame(cards_frame, padding="4 2")
            box.grid(row=0, column=idx, padx=8, sticky="ew")

            # 音符标记 (如 1, 2, ..., 1̇)
            n_lbl = ttk.Label(
                box,
                text=display_note,
                font=("Microsoft YaHei UI", 11, "bold"),
                foreground="#0f172a"
            )
            n_lbl.pack()

            # 按键外观
            k_lbl = ttk.Label(
                box,
                text=f" [ {k_char} ] ",
                font=("Consolas", 10, "bold"),
                foreground="#1e293b",
                background="#e2e8f0"
            )
            k_lbl.pack(pady=2)

        # 下排：降调 | 半音 | 升调 动作指示行 (匹配截图中的鼠标图标指示)
        mod_line = ttk.Frame(self.keys_frame)
        mod_line.pack(fill=tk.X, pady=(4, 2))

        ttk.Label(
            mod_line,
            text=f"🖱 降调: [{low_mod}]    |    🖱 半音: [{semi_mod}]    |    🖱 升调: [{high_mod}]",
            font=("Microsoft YaHei UI", 9, "bold"),
            foreground="#0369a1"
        ).pack(side=tk.LEFT)

    def _open_settings(self):
        KeySettingsDialog(self.root, self.config_mgr, scale=self.scale, on_saved_callback=self._on_settings_saved)

    def _on_settings_saved(self):
        self.parser.set_config_manager(self.config_mgr)
        self._render_key_map_banner()
        self.current_note_lbl.config(text="✔ 键位设置已更新并生效！", foreground="#16a34a")

    # ==========================
    # 交互与文件导入处理
    # ==========================
    def _on_bpm_change(self, val):
        bpm = int(float(val))
        if hasattr(self, 'bpm_lbl'):
            self.bpm_lbl.config(text=str(bpm))
        if hasattr(self, 'player'):
            self.player.bpm = float(bpm)

    def _on_gap_change(self, val):
        gap = int(float(val))
        if hasattr(self, 'gap_lbl'):
            self.gap_lbl.config(text=f"{gap} ms")
        if hasattr(self, 'player'):
            self.player.note_gap = gap / 1000.0

    def _on_song_select(self, _event):
        song_name = self.song_var.get()
        if song_name in SONGS_LIBRARY:
            data = SONGS_LIBRARY[song_name]
            self.score_text.delete("1.0", tk.END)
            self.score_text.insert(tk.END, data["score"])
            self.bpm_scale.set(data["bpm"])
            if hasattr(self, 'bpm_lbl'):
                self.bpm_lbl.config(text=str(data["bpm"]))
            self.current_note_lbl.config(
                text=f"已载入《{song_name}》: {data.get('description', '')}"
            )
            self.sync_audio_var.set(False)

    def _import_txt(self):
        file_path = filedialog.askopenfilename(
            title="选择简谱文本文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.score_text.delete("1.0", tk.END)
                self.score_text.insert(tk.END, content)
                self.current_note_lbl.config(text=f"已导入文本曲谱: {os.path.basename(file_path)}")
                self.sync_audio_var.set(False)
            except Exception as e:
                messagebox.showerror("导入错误", f"无法读取文本文件: {e}")

    def _import_midi(self):
        """导入 MIDI 文件 (.mid, .midi)"""
        file_path = filedialog.askopenfilename(
            title="选择 MIDI 音乐文件",
            filetypes=[("MIDI 音乐文件", "*.mid;*.midi"), ("所有文件", "*.*")]
        )
        if not file_path:
            return
        try:
            score_text, bpm, count = self.midi_importer.import_midi(file_path)
            self.score_text.delete("1.0", tk.END)
            self.score_text.insert(tk.END, score_text)
            self.bpm_scale.set(bpm)
            if hasattr(self, 'bpm_lbl'):
                self.bpm_lbl.config(text=str(int(bpm)))
            self.current_note_lbl.config(
                text=f"✔ 已导入 MIDI《{os.path.basename(file_path)}》: 共解析 {count} 个音符，速度 BPM {bpm}",
                foreground="#16a34a"
            )
            self.sync_audio_var.set(False)
        except Exception as e:
            messagebox.showerror("MIDI 导入失败", f"无法解析 MIDI 文件: {e}")

    def _import_media(self):
        """导入 MP4 视频或音频并智能识别旋律转谱"""
        file_path = filedialog.askopenfilename(
            title="选择 MP4 视频或音频文件进行转谱",
            filetypes=[
                ("媒体文件 (MP4/音频)", "*.mp4;*.m4a;*.mp3;*.wav;*.flac"),
                ("MP4 视频文件", "*.mp4"),
                ("音频文件", "*.mp3;*.wav;*.m4a;*.flac"),
                ("所有文件", "*.*")
            ]
        )
        if not file_path:
            return

        self.current_note_lbl.config(
            text=f"⏳ 正在分析媒体文件《{os.path.basename(file_path)}》提取旋律中，请稍候...",
            foreground="#d97706"
        )
        self.root.update()

        def do_transcribe():
            try:
                bpm = float(self.bpm_scale.get())
                score_text, bpm_out, count = self.media_importer.transcribe_audio_to_score(file_path, bpm=bpm)
                self.loaded_media_file = file_path

                def update_ui():
                    self.score_text.delete("1.0", tk.END)
                    self.score_text.insert(tk.END, score_text)
                    self.current_note_lbl.config(
                        text=f"✔ 已完成旋律转谱《{os.path.basename(file_path)}》: 识别 {count} 个音符 (已生成原声伴奏)",
                        foreground="#16a34a"
                    )
                    self.sync_audio_var.set(True)
                self.root.after(0, update_ui)
            except Exception as e:
                def show_err():
                    messagebox.showerror("转谱失败", f"无法从媒体中提取旋律: {e}")
                    self.current_note_lbl.config(text=f"❌ 转谱失败: {e}", foreground="#dc2626")
                self.root.after(0, show_err)

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _export_file(self):
        file_path = filedialog.asksaveasfilename(
            title="保存曲谱文件",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")]
        )
        if file_path:
            try:
                content = self.score_text.get("1.0", tk.END)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                messagebox.showinfo("成功", "曲谱保存成功！")
            except Exception as e:
                messagebox.showerror("保存失败", f"无法保存文件: {e}")

    def _clear_score(self):
        self.score_text.delete("1.0", tk.END)

    def _get_parsed_events(self):
        content = self.score_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("提示", "当前曲谱为空，请先输入或选择曲谱！")
            return None
        events = self.parser.parse(content)
        if not events:
            messagebox.showwarning("解析失败", "未识别到有效音符，请检查曲谱格式！")
            return None
        return events

    def _start_game_play(self):
        events = self._get_parsed_events()
        if not events:
            return

        try:
            countdown = int(self.countdown_spin.get())
        except ValueError:
            countdown = 3

        bpm = float(self.bpm_scale.get())
        gap_time = float(self.gap_scale.get()) / 1000.0
        legato = self.legato_var.get()

        self.progress_bar['maximum'] = len(events)
        self.progress_bar['value'] = 0

        self.player.start_play(
            events=events,
            bpm=bpm,
            note_gap=gap_time,
            legato_mode=legato,
            countdown_seconds=countdown,
            preview=False
        )

    def _start_preview(self):
        events = self._get_parsed_events()
        if not events:
            return

        bpm = float(self.bpm_scale.get())
        gap_time = float(self.gap_scale.get()) / 1000.0
        legato = self.legato_var.get()

        self.progress_bar['maximum'] = len(events)
        self.progress_bar['value'] = 0

        self.player.start_play(
            events=events,
            bpm=bpm,
            note_gap=gap_time,
            legato_mode=legato,
            countdown_seconds=0,
            preview=True
        )

    def _toggle_pause(self):
        self.player.toggle_pause()

    def _stop_play(self):
        self.player.stop()
        self.media_importer.stop_accompaniment()

    def _on_hotkey_toggle(self):
        if self.player.state == PlayerState.PLAYING:
            self.root.after(0, self.player.toggle_pause)
        elif self.player.state == PlayerState.PAUSED:
            self.root.after(0, self.player.toggle_pause)
        elif self.player.state in (PlayerState.STOPPED, None):
            self.root.after(0, self._hotkey_start_instant)

    def _hotkey_start_instant(self):
        events = self._get_parsed_events()
        if not events:
            return
        bpm = float(self.bpm_scale.get())
        gap_time = float(self.gap_scale.get()) / 1000.0
        legato = self.legato_var.get()

        self.progress_bar['maximum'] = len(events)
        self.progress_bar['value'] = 0

        self.player.start_play(
            events=events,
            bpm=bpm,
            note_gap=gap_time,
            legato_mode=legato,
            countdown_seconds=0,
            preview=False
        )

    def _on_hotkey_stop(self):
        self.root.after(0, self._stop_play)

    def _on_player_state_change(self, state: str):
        self.root.after(0, self._update_ui_state, state)

    def _update_ui_state(self, state: str):
        if state == PlayerState.COUNTDOWN:
            self.status_lbl.config(text="⏳ 倒计时切屏中...", foreground="#eab308")
            self.btn_play.config(state=tk.DISABLED)
        elif state == PlayerState.PLAYING:
            mode_str = " (试听)" if self.player.is_preview_mode else " (游戏中)"
            self.status_lbl.config(text=f"▶ 正在弹奏{mode_str}", foreground="#16a34a")
            self.btn_play.config(state=tk.DISABLED)
            if self.sync_audio_var.get() and self.media_importer._current_wav_path:
                self.media_importer.play_accompaniment(self.media_importer._current_wav_path)
        elif state == PlayerState.PAUSED:
            self.status_lbl.config(text="⏸ 已暂停 (按 F8 继续)", foreground="#f97316")
            self.btn_play.config(state=tk.DISABLED)
            self.media_importer.stop_accompaniment()
        elif state == PlayerState.STOPPED:
            self.status_lbl.config(text="● 状态: 空闲就绪", foreground="#475569")
            self.btn_play.config(state=tk.NORMAL)
            self.media_importer.stop_accompaniment()

    def _on_countdown(self, remaining: int):
        self.root.after(0, lambda: self.current_note_lbl.config(
            text=f"倒计时 {remaining} 秒！请切换至游戏窗口，准备口琴姿态...",
            foreground="#ca8a04"
        ))

    def _on_note_start(self, index: int, event):
        self.root.after(0, self._update_note_display, index, event)

    def _update_note_display(self, index: int, event):
        self.progress_bar['value'] = index + 1
        total = len(self.player.events)

        if event.is_rest:
            info = f"[{index+1}/{total}] 休止符 0 (暂停 {event.beats} 拍)"
        else:
            action_names = [format_action_name(k) for k in event.keys]
            keys_str = " + ".join(action_names)
            pitches_str = ",".join(event.pitch_names)
            info = f"[{index+1}/{total}] 音符 {pitches_str} -> 动作 [ {keys_str} ] ({event.beats} 拍)"

        self.current_note_lbl.config(text=info, foreground="#0f172a")

    def _on_player_error(self, err_msg: str):
        self.root.after(0, lambda: messagebox.showerror("播放错误", f"弹奏时发生异常:\n{err_msg}"))

    def _on_finished(self):
        self.media_importer.stop_accompaniment()
        self.root.after(0, lambda: self.current_note_lbl.config(
            text="✨ 弹奏完毕！按 F8 可重新播放，随时欢迎选择其他曲目。",
            foreground="#16a34a"
        ))

    def _on_close(self):
        self.hotkey.stop()
        self.player.stop()
        self.media_importer.stop_accompaniment()
        self.root.destroy()


def run_gui():
    scale = init_dpi_awareness()
    root = tk.Tk()
    apply_tk_scaling(root, scale)
    app = MusicPlayerGUI(root, scale=scale)
    root.mainloop()

if __name__ == '__main__':
    run_gui()
