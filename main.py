"""
口琴自动音乐弹奏脚本 - 主入口
支持 GUI 图形化界面 与 CLI 命令行模式。
支持 TXT 简谱、MIDI 文件 (.mid) 及 MP4 视频/音频智能转谱播放。
"""

import sys
import os
import argparse
import time

from dpi_helper import init_dpi_awareness
from direct_input import KeyboardController
from music_parser import MusicParser
from player_engine import PlayerEngine, PlayerState
from songs import SONGS_LIBRARY
from midi_importer import MidiImporter
from media_importer import MediaImporter

def run_cli_play(song_name: str, bpm: float = 0, gap: float = 18.0, preview: bool = False, countdown: int = 3):
    score_text = ""
    target_bpm = 100

    # 兼容相对路径 (当前工作目录或脚本所在目录)
    if not os.path.exists(song_name):
        alt = os.path.join(os.path.dirname(__file__), song_name)
        if os.path.exists(alt):
            song_name = alt

    # 1. 判断是否为 MIDI 文件
    if song_name.lower().endswith(('.mid', '.midi')):
        try:
            print(f"[*] 正在解析 MIDI 文件: {song_name} ...")
            importer = MidiImporter()
            score_text, m_bpm, count = importer.import_midi(song_name)
            target_bpm = m_bpm
            print(f"[*] MIDI 解析完成，识别 {count} 个音符，默认 BPM: {target_bpm}")
        except Exception as e:
            print(f"[!] 解析 MIDI 文件失败: {e}")
            return
    # 2. 判断是否为 MP4 视频或音频文件
    elif song_name.lower().endswith(('.mp4', '.m4a', '.mp3', '.wav', '.flac')):
        try:
            print(f"[*] 正在从媒体文件中提取音频并进行智能旋律转谱: {song_name} ...")
            importer = MediaImporter()
            score_text, m_bpm, count = importer.transcribe_audio_to_score(song_name, bpm=bpm or 100.0)
            target_bpm = m_bpm
            print(f"[*] MP4 智能转谱完成，识别 {count} 个音符，设定 BPM: {target_bpm}")
        except Exception as e:
            print(f"[!] 媒体转谱失败: {e}")
            return
    else:
        # 3. 查找内置曲库或普通 txt 文件
        found_key = None
        for name in SONGS_LIBRARY:
            if song_name.lower() in name.lower():
                found_key = name
                break

        if found_key:
            score_text = SONGS_LIBRARY[found_key]["score"]
            target_bpm = SONGS_LIBRARY[found_key]["bpm"]
            print(f"[*] 载入内置歌曲: 《{found_key}》")
        else:
            try:
                with open(song_name, "r", encoding="utf-8") as f:
                    score_text = f.read()
                print(f"[*] 从文件读取曲谱: {song_name}")
            except Exception as e:
                print(f"[!] 无法找到歌曲或文件: {song_name} ({e})")
                return

    if bpm > 0:
        target_bpm = bpm

    parser = MusicParser()
    events = parser.parse(score_text)
    if not events:
        print("[!] 曲谱中未识别到有效音符！")
        return

    print(f"[*] 解析成功，共 {len(events)} 个音符事件，速度 BPM: {target_bpm}")
    print("[*] 全局控制: 运行中可在窗口按 Ctrl+C 中止。")

    kb = KeyboardController()
    engine = PlayerEngine(kb)

    def on_note(idx, ev):
        if ev.is_rest:
            print(f"  [{idx+1}/{len(events)}] 休止符 0 ({ev.beats} 拍)")
        else:
            keys_str = "+".join(ev.keys or ev.notes).upper()
            pitches_str = ",".join(ev.pitch_names)
            print(f"  [{idx+1}/{len(events)}] 音符 {pitches_str} -> 按键组合 [ {keys_str} ] ({ev.beats} 拍)")

    engine.on_note_start = on_note

    print(f"[*] 准备启动... 倒计时 {countdown} 秒后开始弹奏，请切到游戏窗口！")
    engine.start_play(
        events=events,
        bpm=target_bpm,
        note_gap=gap / 1000.0 if 'gap' in locals() and gap else 0.018,
        legato_mode=True,
        countdown_seconds=countdown,
        preview=preview
    )

    try:
        while engine.state != PlayerState.STOPPED:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[!] 收到中断信号，紧急停止！")
        engine.stop()

    print("[*] 弹奏结束。")


def main():
    # 提前开启高 DPI 清晰度感知
    init_dpi_awareness()

    parser = argparse.ArgumentParser(description="游戏口琴自动弹奏脚本 (支持三八度·半音·MIDI·MP4)")
    parser.add_argument("--cli", action="store_true", help="强制以命令行 CLI 模式运行")
    parser.add_argument("--list", action="store_true", help="列出所有内置曲目")
    parser.add_argument("--play", type=str, help="直接播放指定曲目、TXT文件、MIDI文件(.mid)或MP4视频(.mp4)")
    parser.add_argument("--bpm", type=float, default=0, help="自定义播放速度 BPM")
    parser.add_argument("--gap", type=float, default=18, help="两次发音之间的间隔毫秒 (默认 18ms，极连贯)")
    parser.add_argument("--preview", action="store_true", help="使用 PC 蜂鸣器试听而非游戏按键")
    parser.add_argument("--countdown", type=int, default=3, help="切屏倒计时秒数 (默认 3)")

    args = parser.parse_args()

    if args.list:
        print("=== 内置口琴曲库列表 ===")
        for idx, (title, info) in enumerate(SONGS_LIBRARY.items(), start=1):
            print(f"{idx}. {title} (默认 BPM: {info['bpm']}) - {info['description']}")
        return

    if args.play:
        run_cli_play(args.play, bpm=args.bpm, gap=args.gap, preview=args.preview, countdown=args.countdown)
        return

    # 默认启动 GUI 模式
    if not args.cli:
        try:
            from gui import run_gui
            run_gui()
            return
        except Exception as e:
            print(f"[!] 启动图形界面失败: {e}，正在切换至命令行模式...")

    # CLI 交互模式
    print("=" * 55)
    print("      口琴自动弹奏脚本 (命令行交互模式)")
    print("  音符 1~7 对应键盘底部按键: Z X C V B N M")
    print("  支持高低八度 (Shift/Ctrl) 及半音推键 (Space)")
    print("  支持导入 .mid MIDI音乐与 .mp4 媒体文件")
    print("=" * 55)
    print("内置曲库:")
    names = list(SONGS_LIBRARY.keys())
    for idx, name in enumerate(names, start=1):
        print(f"  [{idx}] {name}")
    print()

    try:
        choice = input(f"请输入歌曲序号 (1~{len(names)})、本地文件名 (如 test.mid) 或直接回车选 1: ").strip()
        idx = 1
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            song_target = names[int(choice) - 1]
        elif choice:
            song_target = choice
        else:
            song_target = names[0]

        mode_choice = input("是否仅试听 (PC蜂鸣器)？(y/N, 默认游戏按键): ").strip().lower()
        is_preview = mode_choice == 'y'

        run_cli_play(song_target, preview=is_preview, countdown=3)
    except (KeyboardInterrupt, EOFError):
        print("\n已退出。")

if __name__ == '__main__':
    main()
