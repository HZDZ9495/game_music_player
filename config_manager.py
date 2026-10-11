"""
键位配置管理模块 (Config Manager)
完美适配游戏口琴界面 (Z~M, 逗号高音1, 鼠标左键降调, 鼠标中键半音, 鼠标右键升调)。
配置自动持久化到 key_config.json。
"""

import json
import os
from typing import Dict, List, Optional

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "key_config.json")

# 默认游戏配置 (匹配游戏口琴原生键位与鼠标修饰键)
DEFAULT_CONFIG = {
    # 修饰键配置:
    # 升调 (高八度): 鼠标右键 (mouse_right)
    # 降调 (低八度): 鼠标左键 (mouse_left)
    # 半音 (推键): 鼠标中键 (mouse_middle)
    "modifiers": {
        "high_octave": "mouse_right",
        "low_octave": "mouse_left",
        "semitone": "mouse_middle"
    },
    # 基础音符键位:
    # 1~7 对应 Z~M，高音 1 对应逗号 ','
    "base_keys": {
        "1": "z",
        "2": "x",
        "3": "c",
        "4": "v",
        "5": "b",
        "6": "n",
        "7": "m",
        "1'": ","
    },
    # 特殊单个音符自定义覆盖
    "custom_overrides": {
        "1'": [","],                  # 高音 1 专属逗号按键
        "#1'": ["mouse_middle", ","]  # 高音升 1: 鼠标中键 + 逗号
    }
}

class KeyConfigManager:
    def __init__(self, config_path: str = CONFIG_FILE):
        self.config_path = config_path
        self.config = {
            "modifiers": dict(DEFAULT_CONFIG["modifiers"]),
            "base_keys": dict(DEFAULT_CONFIG["base_keys"]),
            "custom_overrides": dict(DEFAULT_CONFIG["custom_overrides"])
        }
        self.load()

    def load(self):
        """从 JSON 加载配置，若不存在则保存默认配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "modifiers" in data:
                        self.config["modifiers"].update(data["modifiers"])
                    if "base_keys" in data:
                        self.config["base_keys"].update(data["base_keys"])
                    if "custom_overrides" in data:
                        self.config["custom_overrides"] = data["custom_overrides"]
            except Exception as e:
                print(f"[Config] 加载配置文件失败，使用默认配置: {e}")
        else:
            self.save()

    def save(self):
        """保存当前配置至 JSON 文件"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] 保存配置文件失败: {e}")

    def reset_to_default(self):
        """重置为游戏原生配置 (鼠标右键升调, 鼠标左键降调, 鼠标中键半音, 逗号高音1)"""
        self.config = {
            "modifiers": dict(DEFAULT_CONFIG["modifiers"]),
            "base_keys": dict(DEFAULT_CONFIG["base_keys"]),
            "custom_overrides": dict(DEFAULT_CONFIG["custom_overrides"])
        }
        self.save()

    def set_scheme(self, scheme_name: str):
        """快捷切换按键预设方案"""
        if scheme_name == "game_mouse":
            # 游戏原生鼠标方案
            self.reset_to_default()
        elif scheme_name == "keyboard":
            # 纯键盘方案
            self.config["modifiers"] = {
                "high_octave": "shift",
                "low_octave": "ctrl",
                "semitone": "space"
            }
            self.config["base_keys"] = {
                "1": "z", "2": "x", "3": "c", "4": "v", "5": "b", "6": "n", "7": "m", "1'": ","
            }
            self.config["custom_overrides"] = {
                "1'": [","]
            }
            self.save()

    def get_keys_for_note(self, pitch_code: str) -> List[str]:
        """
        根据音符代码计算对应的按键与修饰动作
        """
        # 1. 优先检查自定义覆盖 (例如 1' -> [','])
        if pitch_code in self.config.get("custom_overrides", {}):
            val = self.config["custom_overrides"][pitch_code]
            if isinstance(val, list):
                return val
            elif isinstance(val, str):
                return [k.strip() for k in val.split("+") if k.strip()]

        # 2. 解析音符特征
        is_sharp = pitch_code.startswith("#")
        core = pitch_code[1:] if is_sharp else pitch_code

        # 判断八度
        octave = 0 # 0=中音, 1=高音, -1=低音
        if core.endswith("'") or core.endswith("^"):
            octave = 1
            digit = core.rstrip("'^")
        elif core.endswith(".") or core.endswith(","):
            octave = -1
            digit = core.rstrip(".,")
        else:
            digit = core

        base_key = self.config["base_keys"].get(digit, "z")

        keys = []
        mods = self.config["modifiers"]

        # 八度修饰动作 (升调/降调)
        if octave == 1:
            high_mod = mods.get("high_octave", "").strip()
            if high_mod and high_mod.lower() != "none":
                keys.append(high_mod.lower())
        elif octave == -1:
            low_mod = mods.get("low_octave", "").strip()
            if low_mod and low_mod.lower() != "none":
                keys.append(low_mod.lower())

        # 半音修饰动作 (推键)
        if is_sharp:
            semi_mod = mods.get("semitone", "").strip()
            if semi_mod and semi_mod.lower() != "none":
                keys.append(semi_mod.lower())

        # 基础音符按键
        keys.append(base_key.lower())

        return keys


if __name__ == '__main__':
    mgr = KeyConfigManager()
    mgr.reset_to_default() # 强制写入最新游戏默认设置
    test_pitches = [
        "1", "2", "7",
        "1'", "2'", "3'",
        "1.", "2.", "5.",
        "#1", "#4",
        "#1'", "#4'",
        "#1.", "#5."
    ]
    print("游戏原生键位计算测试 (根据截图修改):")
    for p in test_pitches:
        print(f"  音符 {p:<5} -> 触发组合: {mgr.get_keys_for_note(p)}")
