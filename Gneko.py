#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gneko Desktop Pet — v2
======================
一只住在桌面上的像素猫。

相比 v1 的改动：
  * 真正透明：色键透明（transparentcolor），不再有黑色方框
  * 高清像素：最近邻整数放大，支持 1x~6x 缩放，DPI 感知不糊
  * 八方向行走：复用 upleft/upright/dwleft/dwright 素材
  * 自适应刷新：走路 24ms，发呆/睡觉 55ms，省电
  * 位置用 Win32 SetWindowPos 精确摆放，避开任务栏
  * 鼠标按键状态轮询，窗口失焦也能感知点击
  * 新增「趴在鼠标上」「玩耍(jare)」两个行为
  * 右键菜单：缩放 / 速度 / 跟随开关 / 睡一会 / 回鼠标 / 重载素材
  * 配置、素材路径按脚本目录解析，双击运行不再找不到资源
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import random
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageTk

# 打包成 exe 后：素材被 PyInstaller 解压到临时目录（sys._MEIPASS），
# 而配置、日志这类需要写入的文件必须留在 exe 所在目录。
IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", APP_DIR)) if IS_FROZEN else APP_DIR
IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def _xdg_dir(env_var: str, fallback: str) -> Path:
    """Linux 按 XDG 规范放配置和日志，别往源码目录里写。"""
    base = os.environ.get(env_var)
    root = Path(base) if base else (Path.home() / fallback)
    return root / "gneko"


CONFIG_DIR = _xdg_dir("XDG_CONFIG_HOME", ".config") if IS_LINUX else APP_DIR
STATE_DIR = _xdg_dir("XDG_STATE_HOME", ".local/state") if IS_LINUX else APP_DIR
LOG_FILE = STATE_DIR / "Gneko.log"


def default_config_path() -> Path:
    return CONFIG_DIR / "Gneko_config.json"


# ---------------------------------------------------------------- 日志

def log(msg: str) -> None:
    """pythonw 下没有控制台，关键信息落盘，方便事后排查。"""
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 512 * 1024:
            LOG_FILE.write_text(line, encoding="utf-8")
        else:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def log_exception(where: str = "") -> None:
    try:
        import traceback
        log(f"[ERROR]{(' ' + where) if where else ''}\n{traceback.format_exc()}")
    except Exception:
        pass


def install_exception_hooks() -> None:
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        try:
            import traceback
            log("[FATAL]\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    sys.excepthook = _hook


def is_key_down(vk: int) -> bool:
    if IS_LINUX:
        s = x11()
        name = {0x11: "ctrl", 0x12: "alt", 0x1B: "esc", 0x47: "g"}.get(int(vk))
        return bool(s and name and s.key_down(name))
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


class _NullStream:
    def write(self, *args):
        return 0

    def flush(self):
        pass


def ensure_std_streams() -> None:
    """pythonw 双击启动时 stdout/stderr 是 None，print 会直接报错。"""
    if sys.stdout is None:
        sys.stdout = _NullStream()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NullStream()  # type: ignore[assignment]

# ---------------------------------------------------------------- 默认配置

DEFAULT_CONFIG: Dict[str, Any] = {
    # 素材与外观
    # SKIN: "classic" 用 SPRITE_FOLDER 里的原版素材；
    # 其他值去 SKINS_DIR/<SKIN>/ 里找素材，找不到就退回 classic
    "SKIN": "classic",
    "SKINS_DIR": "skins",
    "SPRITE_FOLDER": "Gneko_png",
    "PET_WIDTH": 32,
    "PET_HEIGHT": 32,
    "SCALE": 2,
    "KEY_COLOR": "#ff00ff",
    "AUTO_SCALE_HIDPI": False,
    "ALWAYS_ON_TOP": True,
    "FALLBACK_COLOR": "#4488ff",
    "CANVAS_BG_COLOR": "black",
    "BG_COLOR_PRESETS": [
        "black", "#222222", "#102040", "#201020",
        "#003322", "#552222", "white", "#dddddd"
    ],
    # 节奏
    "BASE_SPEED": 1.4,
    "SPD_VARIATION": 0.6,
    "STUCK_SPEED_THRESHOLD": 0.3,
    "ANIM_DELAY": 130,
    "ANIM_SPEED_MULT": 1.0,
    "LOOP_INTERVAL": 24,
    "LOOP_INTERVAL_IDLE": 55,
    "IDLE_TIME_MIN": 1600,
    "IDLE_TIME_MAX": 5200,
    "SCRATCH_DELAY": 1800,
    "GROOM_DURATION": 1600,
    "SLEEP_DURATION": 2800,
    "GROOM_CHANCE": 0.09,
    "SLEEP_CHANCE": 0.05,
    "PLAY_CHANCE": 0.06,
    "PLAY_DURATION": 900,
    "IDLE_START_WALK_CHANCE": 0.75,
    # 行为
    "EDGE_MARGIN": 12,
    "DIAGONAL_SPRITES": True,
    "CHASE_TRIGGER_DIST": 220,
    "ROAM_TRIGGER_DIST": 450,
    "CHASE_DIST_STOP": 40,
    "INTEREST_MAX": 100,
    "INTEREST_PER_CLICK": 18,
    "INTEREST_DECAY_PER_TICK": 0.25,
    # 只要你在附近，兴趣值不会掉到这条线以下 —— 猫会一直想追
    "INTEREST_FLOOR": 45,
    "INTEREST_FLOOR_HOLD_MS": 3000,
    "CHASE_BORED_INTEREST": 12,
    "CHASE_BORED_STILL_MS": 6000,
    "CHASE_TRIGGER_BOOST_MAX": 260,
    "SLEEP_SCARE_IDLE_TIME": 1400,
    "CHASE_SMOOTH_FACTOR": 0.18,
    "CHASE_SLOW_DOWN_DIST": 70,
    "CHASE_MIN_SPEED": 0.6,
    "CHASE_HYSTERESIS_GAP": 80,
    "CHASE_BRAKE_SCALE": 0.35,
    "ENERGY_MAX": 100.0,
    "ENERGY_DRAIN_PER_TICK": 0.12,
    "ENERGY_REGEN_IDLE": 0.07,
    "ENERGY_REGEN_SLEEP": 0.22,
    "ENERGY_TIRED_THRESHOLD": 30.0,
    "TIRED_SLEEP_BOOST": 0.25,
    "AVOID_TRIGGER_SPEED": 220,
    "AVOID_TRIGGER_MAX_DIST": 130,
    "AVOID_DURATION": 420,
    "AVOID_SPEED_MULT": 1.6,
    "SIT_ON_CURSOR_CHANCE": 0.10,
    "SIT_OFFSET_X": -12,
    "SIT_OFFSET_Y": -30,
    "SIT_BREAKAWAY_SPEED": 380,
    "SIT_MAX_DURATION": 12000,
    "SIT_MOVE_SPEED": 2.2,
    "IDLE_STATIC_SWAP_MIN": 700,
    "IDLE_STATIC_SWAP_MAX": 2400,
    "PROB_IDLE_STATIC": 0.60,
    "PROB_IDLE_LOOK": 0.40,
    "MEANDER_MODE": True,
    "MEANDER_MAX_TARGET_DIST": 180,
    "MEANDER_PAUSE_CHANCE": 0.22,
    "WALK_PAUSE_CHANCE": 0.08,
    "EDGE_SCRATCH_CHANCE": 0.65,
    "DRAG_AFTER_IDLE_TIME": 1200,
    # 甩出去：松手速度快就带惯性飞，撞边反弹
    "FLING_ENABLE": True,
    "FLING_MIN_SPEED": 900.0,
    "FLING_MAX_SPEED": 2600.0,
    "FLING_FRICTION": 0.94,
    "FLING_BOUNCE": 0.55,
    "FLING_STOP_SPEED": 260.0,
    "FLING_STUN_MS": 600.0,
    "CHASE_MODE_FOLLOW_DIST_MIN": 90,
    "CHASE_MODE_FOLLOW_DIST_MAX": 140,
    "CHASE_MODE_SHY_BACKOFF_DIST": 65,
    "CHASE_MODE_POUNCE_TRIGGER_INTEREST": 65,
    "CHASE_MODE_POUNCE_SPEED_MULT": 1.6,
    "CHASE_MODE_POUNCE_DURATION": 420,
    # —— 加强追逐：距离越大跑越快、能真正扑到脚边、子模式不再每帧乱跳
    "CHASE_MAX_SPEED_MULT": 2.6,
    "CHASE_SPEED_RAMP_DIST": 280,
    "CHASE_CATCH_DIST": 16,
    "CHASE_MODE_HOLD_MIN": 900,
    "CHASE_MODE_HOLD_MAX": 2600,
    "CHASE_MOUSE_VEL_TRIGGER_GAIN": 0.35,
    "CHASE_MOUSE_VEL_INTEREST_GAIN": 1.6,
    "CHASE_CATCH_COOLDOWN": 2200,
    "SPIN_ACTION_RADIUS": 45.0,
    "SPIN_ACTION_DURATION_SEC": 3.0,
    "SPIN_ACTION_ANGULAR_SPEED": 2.2,
    "SPIN_ACTION_RANDOM_CHANCE": 0.015,
    "SPIN_ACTION_COOLDOWN_MS": 8000,
    # 多猫联机
    "ENABLE_MULTICAT_NET": True,
    "MULTICAT_PORT": 58231,
    "MULTICAT_SEE_DIST": 180,
    "MULTICAT_INTEREST_DIST": 100,
    "MULTICAT_CHASE_ENABLE": True,
    "MULTICAT_FLEE_DIST": 60,
    # 界面
    "WORKAREA_AWARE": True,
    "SAVE_SETTINGS": True,
    "BUBBLE_ENABLE": True,
    "MOUSE_CURSOR_ENABLE": True,
    "MOUSE_CURSOR_SCALE": 2,
    "BUBBLE_DURATION": 1700,
    "BUBBLE_LINES": [
        "喵~", "别戳啦", "陪我玩", "困了…", "跟着你",
        "抓不到我", "饿…", "zZ", "今天也要好好干活"
    ],
    "PET_ON_HOVER": True,
    "REMEMBER_POSITION": True,
    "LAST_X": -1,
    "LAST_Y": -1,
    "CLICK_THROUGH": False,
    # 调试
    "DEBUG_MODE": False,
    "SHOW_DEST_MARKER": False,
}

STATE_WALK = "walk"
STATE_IDLE = "idle"
STATE_PET = "pet"
STATE_SCRATCH = "scratch"
STATE_GROOM = "groom"
STATE_SLEEP = "sleep"
STATE_PLAY = "play"
STATE_AVOID = "avoid"
STATE_SIT_ON_CURSOR = "sit_cursor"
STATE_SIT_APPROACH = "sit_approach"
STATE_SPIN_ACTION = "spin_action"
STATE_FLUNG = "flung"

IDLE_SUB_STATIC = "idle_static"
IDLE_SUB_LOOK = "idle_look"

CHASE_SUB_NORMAL = "chase_normal"
CHASE_SUB_FOLLOW = "chase_follow"
CHASE_SUB_SHY = "chase_shy"
CHASE_SUB_POUNCE = "chase_pounce"

DIR_DEAD_ZONE = 3.0
DIR8 = ["right", "dwright", "down", "dwleft", "left", "upleft", "up", "upright"]
DIR_FALLBACK = {
    "dwright": ["dwright", "right"],
    "dwleft": ["dwleft", "left"],
    "upleft": ["upleft", "left"],
    "upright": ["upright", "right"],
}
QUIET_STATES = (STATE_SLEEP, STATE_IDLE, STATE_PET, STATE_SCRATCH,
                STATE_GROOM, STATE_PLAY, STATE_SPIN_ACTION)


# ---------------------------------------------------------------- Win32 工具

class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


def enable_dpi_awareness() -> None:
    """让 Tk 在缩放显示器上按物理像素绘制，像素图才不会被糊掉。"""
    if not IS_WIN:
        return
    for attempt in ("shcore", "user32"):
        try:
            if attempt == "shcore":
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            else:
                ctypes.windll.user32.SetProcessDPIAware()
            return
        except Exception:
            continue


def get_cursor_pos() -> Tuple[int, int]:
    if IS_WIN:
        try:
            pt = wt.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return int(pt.x), int(pt.y)
        except Exception:
            pass
    if IS_LINUX:
        s = x11()
        if s is not None:
            ox, oy, _ = s.pointer()
            if ox or oy:
                return ox, oy
    try:
        return tk._default_root.winfo_pointerx(), tk._default_root.winfo_pointery()
    except Exception:
        return 0, 0


def is_left_button_down() -> bool:
    if IS_LINUX:
        s = x11()
        return bool(s and s.button1_down())
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
    except Exception:
        return False


def virtual_screen() -> Tuple[int, int, int, int]:
    """虚拟桌面原点与尺寸（支持多显示器）。"""
    if IS_WIN:
        try:
            u = ctypes.windll.user32
            return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
                    u.GetSystemMetrics(78), u.GetSystemMetrics(79))
        except Exception:
            pass
    try:
        r = tk._default_root
        if r is not None:
            return 0, 0, int(r.winfo_screenwidth()), int(r.winfo_screenheight())
    except Exception:
        pass
    return 0, 0, 1920, 1080


def primary_workarea() -> Tuple[int, int, int, int]:
    """主屏可用区域（不含任务栏）。"""
    if IS_WIN:
        try:
            r = RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
            if r.right > r.left and r.bottom > r.top:
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    # Linux 上不读 _NET_WORKAREA：各桌面环境差异大，直接用整块屏幕，
    # 猫会贴着屏幕底边走，个别 dock 会被蹭到，属于已知的小瑕疵。
    vx, vy, vw, vh = virtual_screen()
    return vx, vy, vx + vw, vy + vh


# ---------------------------------------------------------------- Linux / X11
#
# Windows 靠色键透明 + SetSystemCursor，这两样 Linux 都没有：
#   * 透明改成用 SHAPE 扩展把窗口裁成当前帧的轮廓；
#   * 系统光标无法替换（没有跨桌面环境的 API），退化成不换，只留日志说明。
# 全局鼠标按键、Ctrl+Alt+G、Esc 用 XQueryPointer / XQueryKeymap 直接读，
# 不需要抓键、也不会抢焦点。

class X11State:
    """libX11 的最小封装：指针/键盘状态 + SHAPE 裁剪。"""

    BUTTON1 = 1 << 8
    SHAPE_BOUNDING = 0
    SHAPE_INPUT = 2
    SHAPE_SET = 0

    def __init__(self) -> None:
        self.ok = False
        self.dpy = None          # type: Optional[int]
        self.root = 0
        self.keycodes: Dict[str, int] = {}
        if not IS_LINUX:
            return
        try:
            self.x11 = ctypes.CDLL("libX11.so.6")
            self.xext = ctypes.CDLL("libXext.so.6")

            self.x11.XOpenDisplay.restype = ctypes.c_void_p
            self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self.dpy = self.x11.XOpenDisplay(None)
            if not self.dpy:
                raise RuntimeError("XOpenDisplay 返回空（没有图形会话？）")

            self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self.root = int(self.x11.XDefaultRootWindow(ctypes.c_void_p(self.dpy)))

            self.x11.XKeysymToKeycode.restype = ctypes.c_ubyte
            self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            for name, sym in (("esc", 0xFF1B), ("ctrl", 0xFFE3), ("alt", 0xFFE9), ("g", 0x67)):
                self.keycodes[name] = int(self.x11.XKeysymToKeycode(ctypes.c_void_p(self.dpy), sym))

            ul = ctypes.c_ulong
            pi = ctypes.POINTER(ctypes.c_int)
            self.x11.XQueryPointer.restype = ctypes.c_int
            self.x11.XQueryPointer.argtypes = [ctypes.c_void_p, ul, ctypes.POINTER(ul),
                                               ctypes.POINTER(ul), pi, pi, pi, pi,
                                               ctypes.POINTER(ctypes.c_uint)]
            self.x11.XQueryKeymap.restype = ctypes.c_int
            self.x11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte)]

            self.x11.XQueryTree.restype = ctypes.c_int
            self.x11.XQueryTree.argtypes = [ctypes.c_void_p, ul, ctypes.POINTER(ul),
                                             ctypes.POINTER(ul),
                                             ctypes.POINTER(ctypes.POINTER(ul)),
                                             ctypes.POINTER(ctypes.c_uint)]
            self.x11.XCreateBitmapFromData.restype = ul
            self.x11.XCreateBitmapFromData.argtypes = [ctypes.c_void_p, ul, ctypes.c_char_p,
                                                       ctypes.c_uint, ctypes.c_uint]
            self.x11.XFreePixmap.argtypes = [ctypes.c_void_p, ul]
            self.x11.XFree.restype = ctypes.c_int
            self.x11.XFree.argtypes = [ctypes.c_void_p]
            self.x11.XFlush.argtypes = [ctypes.c_void_p]

            self.xext.XShapeCombineMask.restype = None
            self.xext.XShapeCombineMask.argtypes = [ctypes.c_void_p, ul, ctypes.c_int,
                                                    ctypes.c_int, ctypes.c_int, ul, ctypes.c_int]
            self.xext.XShapeCombineRectangles.restype = None
            self.xext.XShapeCombineRectangles.argtypes = [ctypes.c_void_p, ul, ctypes.c_int,
                                                          ctypes.c_int, ctypes.c_int,
                                                          ctypes.c_void_p, ctypes.c_int,
                                                          ctypes.c_int, ctypes.c_int]
            self.ok = True
            log("[Gneko] X11 已连接，SHAPE 与全局输入可用")
        except Exception as e:
            print(f"[WARN] X11 初始化失败，Linux 特性降级: {e}")

    # ---------- 输入 ----------
    def pointer(self) -> Tuple[int, int, int]:
        """返回 (屏幕坐标 x, y, 按钮掩码)。"""
        if not self.ok or not self.dpy:
            return 0, 0, 0
        rx, ry = ctypes.c_int(), ctypes.c_int()
        wx, wy = ctypes.c_int(), ctypes.c_int()
        ret_root, ret_child = ctypes.c_ulong(), ctypes.c_ulong()
        mask = ctypes.c_uint()
        try:
            self.x11.XQueryPointer(ctypes.c_void_p(self.dpy), ctypes.c_ulong(self.root),
                                   ctypes.byref(ret_root), ctypes.byref(ret_child),
                                   ctypes.byref(rx), ctypes.byref(ry),
                                   ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
            return int(rx.value), int(ry.value), int(mask.value)
        except Exception:
            return 0, 0, 0

    def button1_down(self) -> bool:
        return bool(self.pointer()[2] & self.BUTTON1)

    def key_down(self, name: str) -> bool:
        if not self.ok or not self.dpy:
            return False
        code = self.keycodes.get(name, 0)
        if not code:
            return False
        buf = (ctypes.c_ubyte * 32)()
        try:
            self.x11.XQueryKeymap(ctypes.c_void_p(self.dpy), buf)
        except Exception:
            return False
        return bool(buf[code // 8] & (1 << (code % 8)))

    def toplevel(self, win_id: int) -> int:
        """Tk 的 winfo_id 给的是内层窗口，真正被 X 看到的顶层窗口要往上翻。"""
        if not self.ok or not self.dpy or not win_id:
            return win_id
        w = int(win_id)
        try:
            for _ in range(8):
                ret_root, parent = ctypes.c_ulong(), ctypes.c_ulong()
                n = ctypes.c_uint()
                # Xlib 会无条件解引用 children_return，传 NULL 直接段错误
                children = ctypes.POINTER(ctypes.c_ulong)()
                ok = self.x11.XQueryTree(ctypes.c_void_p(self.dpy), ctypes.c_ulong(w),
                                         ctypes.byref(ret_root), ctypes.byref(parent),
                                         ctypes.byref(children), ctypes.byref(n))
                if children:
                    self.x11.XFree(children)
                if not ok:
                    break
                if not parent.value or int(parent.value) == self.root:
                    break
                w = int(parent.value)
        except Exception:
            return int(win_id)
        return w

    # ---------- SHAPE ----------
    def shape(self, win_id: int, data: bytes, w: int, h: int, click_through: bool) -> bool:
        """把窗口裁成 data（1 位掩码，1=可见）的形状；点空白处直接穿透。"""
        if not self.ok or not self.dpy or not win_id:
            return False
        win_id = self.toplevel(win_id)
        try:
            win = ctypes.c_ulong(int(win_id))
            need = ((int(w) + 7) // 8) * int(h)
            if len(data) != need:
                # 掩码按正方形帧生成，PET_HEIGHT 与 PET_WIDTH 不同时要补齐，
                # 否则 XCreateBitmapFromData 会越界读
                data = (data + b"\x00" * need)[:need]
            pix = self.x11.XCreateBitmapFromData(ctypes.c_void_p(self.dpy), win,
                                                 ctypes.c_char_p(data), int(w), int(h))
            if not pix:
                return False
            self.xext.XShapeCombineMask(ctypes.c_void_p(self.dpy), win, self.SHAPE_BOUNDING,
                                        0, 0, ctypes.c_ulong(pix), self.SHAPE_SET)
            if click_through:
                # 输入区域清空 = 整块窗口都不接收鼠标事件
                self.xext.XShapeCombineRectangles(ctypes.c_void_p(self.dpy), win, self.SHAPE_INPUT,
                                                  0, 0, None, 0, self.SHAPE_SET, 0)
            else:
                self.xext.XShapeCombineMask(ctypes.c_void_p(self.dpy), win, self.SHAPE_INPUT,
                                            0, 0, ctypes.c_ulong(pix), self.SHAPE_SET)
            self.x11.XFreePixmap(ctypes.c_void_p(self.dpy), ctypes.c_ulong(pix))
            self.x11.XFlush(ctypes.c_void_p(self.dpy))
            return True
        except Exception as e:
            print(f"[WARN] X11 SHAPE 失败: {e}")
            return False


_X11: Optional[X11State] = None


def x11() -> Optional[X11State]:
    """第一次真正需要时才连 X 服务器，--list-skins 之类的纯命令行用法不碰它。"""
    global _X11
    if not IS_LINUX:
        return None
    if _X11 is None:
        _X11 = X11State()
    return _X11 if _X11.ok else None


def setup_fonts() -> None:
    """Linux 上 Tk 默认字体常常没有中文，菜单和气泡会变成方块。"""
    if not IS_LINUX:
        return
    try:
        import tkinter.font as tkfont
        families = set(tkfont.families())
        for cand in ("Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
                     "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Droid Sans Fallback"):
            if cand in families:
                for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                    tkfont.nametofont(name).configure(family=cand)
                log(f"[Gneko] 界面字体: {cand}")
                return
        log("[Gneko] 没找到中文字体，菜单可能显示方块（装 fonts-noto-cjk 可解）")
    except Exception as e:
        log(f"[WARN] 字体设置失败: {e}")


# ---------------------------------------------------------------- 配置读写

def save_config(config_path: Path, cfg: Dict[str, Any]) -> None:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] 写入配置失败: {e}")


def migrate_legacy_names() -> None:
    """把老版本的小写文件名/目录名换成 Gneko 前缀的写法。"""
    pairs = [("neko_png", "Gneko_png"),
             ("gneko_config.json", "Gneko_config.json"),
             ("gneko.log", "Gneko.log")]
    for old, new in pairs:
        src, dst = APP_DIR / old, APP_DIR / new
        try:
            if src.exists() and not dst.exists():
                src.rename(dst)
        except Exception as e:
            print(f"[Gneko] 重命名 {old} 失败: {e}")


def load_or_create_config(config_path: Path) -> Dict[str, Any]:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    merged = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
    if not config_path.exists():
        print(f"[Config] 未发现配置文件，已生成默认模板: {config_path}")
        save_config(config_path, merged)
        return merged
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            user_cfg = json.load(f)
    except Exception as e:
        print(f"[WARN] 配置文件读取失败({e})，使用内置默认配置")
        return merged
    if not isinstance(user_cfg, dict):
        print("[WARN] 配置文件内容损坏（不是对象），使用内置默认配置")
        return merged
    unknown = []
    for k, v in user_cfg.items():
        if k in merged:
            merged[k] = v
        else:
            unknown.append(k)
    if unknown:
        print(f"[Config] 忽略未知配置项: {', '.join(unknown)}")
    return merged


SKIN_CLASSIC = "classic"
SKIN_CLASSIC_ALIASES = ("classic", "default", "base", "orig", "original", "原版")

# 预制皮肤的中文名，仅用于菜单和气泡提示
SKIN_LABELS = {
    "orange": "橘猫",
    "gray": "银灰",
    "pink": "粉猫",
    "mint": "薄荷",
    "sky": "天空",
    "lavender": "香芋",
    "coffee": "咖啡",
    "snow": "雪白",
    "black": "墨黑",
}


def skins_root(cfg: Dict[str, Any]) -> Path:
    folder = Path(str(cfg.get("SKINS_DIR") or "skins"))
    return folder if folder.is_absolute() else (ASSET_ROOT / folder)


def available_skins(cfg: Dict[str, Any]) -> List[str]:
    """列出 skins 目录下所有可用的皮肤（必须至少有一张 PNG）。"""
    root = skins_root(cfg)
    if not root.exists():
        return []
    out = []
    try:
        for p in sorted(root.iterdir()):
            if p.is_dir() and next(p.glob("*.png"), None) is not None:
                out.append(p.name)
    except Exception:
        pass
    return out


def skin_label(name: str) -> str:
    return SKIN_LABELS.get(name, name)


def resolve_asset_dir(cfg: Dict[str, Any]) -> Path:
    skin = str(cfg.get("SKIN") or SKIN_CLASSIC).strip()
    if skin and skin.lower() not in SKIN_CLASSIC_ALIASES:
        d = skins_root(cfg) / skin
        if d.exists() and next(d.glob("*.png"), None) is not None:
            return d
        print(f"[WARN] 皮肤 {skin} 不存在或缺素材，回退到原版")

    folder = Path(str(cfg.get("SPRITE_FOLDER") or "Gneko_png"))
    if folder.name in ("neko_png", "Neko_png"):
        folder = folder.with_name("Gneko_png")
    return folder if folder.is_absolute() else (ASSET_ROOT / folder)


# ---------------------------------------------------------------- 素材库

class SpriteBank:
    """一次性加载、缩放、抠透明并缓存所有帧，运行时零解码开销。"""

    NAME_RE = re.compile(r"^(.*?)(\d*)$")

    def __init__(self, folder: Path, scale: int, key_color: str, cell: int = 32):
        self.folder = folder
        self.scale = max(1, int(scale))
        self.cell = cell
        self.key_rgb = tuple(int(key_color[i:i + 2], 16) for i in (1, 3, 5))
        self.walk: Dict[str, List[ImageTk.PhotoImage]] = {}
        self.togi: Dict[str, ImageTk.PhotoImage] = {}
        self.sleep: List[ImageTk.PhotoImage] = []
        self.groom: List[ImageTk.PhotoImage] = []
        self.play: List[ImageTk.PhotoImage] = []
        self.extra_idle: List[ImageTk.PhotoImage] = []
        self.special: Dict[str, ImageTk.PhotoImage] = {}
        self.masks: Dict[int, bytes] = {}   # PhotoImage id -> 1 位轮廓掩码（Linux SHAPE 用）
        self.count = 0
        self._load()

    # ---------- 内部 ----------
    @staticmethod
    def _fix_white_backdrop(im: Image.Image) -> Image.Image:
        """原版 mati / pet 是「白底」，而猫身上也是白的：只把连到边缘的白底抠掉，
        里面的白肚子保留，不然整只猫会被挖空、或者发呆时露出一块白方块。"""
        if im.getpixel((0, 0))[3] < 250:
            return im
        rgb = im.convert("RGB")
        if rgb.getpixel((0, 0)) != (255, 255, 255):
            return im
        w, h = im.size
        marker = (255, 0, 255, 0)
        work = im.copy()
        # 从四个角往里灌，只有和边缘连通的白才是最外层的底
        for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if work.getpixel(xy) == (255, 255, 255, 255):
                ImageDraw.floodfill(work, xy, marker, thresh=0)
        px = work.load()
        for y in range(h):
            for x in range(w):
                if px[x, y] == marker:
                    px[x, y] = (0, 0, 0, 0)
        return work

    def _prepare(self, im: Image.Image) -> ImageTk.PhotoImage:
        w = self.cell * self.scale
        im = im.resize((w, w), Image.NEAREST)
        alpha = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        bg = Image.new("RGBA", im.size, self.key_rgb + (255,))
        bg.paste(im, (0, 0), alpha)
        photo = ImageTk.PhotoImage(bg.convert("RGB"))
        # 轮廓留一份：Linux 用它把整块窗口裁成猫的形状（1 位掩码，1=可见）
        self.masks[id(photo)] = alpha.convert("1").tobytes()
        return photo

    def mask_of(self, photo: Optional[ImageTk.PhotoImage]) -> Optional[bytes]:
        return self.masks.get(id(photo)) if photo is not None else None

    def _load(self) -> None:
        if not self.folder.exists():
            print(f"[WARN] 素材目录不存在: {self.folder}")
            return
        files = sorted(self.folder.glob("*.png"))
        raw: Dict[str, List[Tuple[int, Image.Image]]] = {}
        for png in files:
            name = png.stem.lower().strip()
            base, idx = self.NAME_RE.match(name).groups()
            try:
                im = Image.open(png).convert("RGBA")
            except Exception as e:
                print(f"[WARN] 素材加载失败 {png.name}: {e}")
                continue
            im = self._fix_white_backdrop(im)
            raw.setdefault(base, []).append((int(idx or 0), im))
        for key in raw:
            raw[key].sort(key=lambda t: t[0])

        for base, items in raw.items():
            if base in ("text", "no", "mouse"):
                continue          # 光标包用的图标，不当成猫的动作帧
            frames = [self._prepare(im) for _, im in items]
            if not frames:
                continue
            if base == "awake":
                self.special["awake"] = frames[0]
            elif base == "pet":
                self.special["pet"] = frames[0]          # pet / pet副本 归一
            elif base.startswith("mati"):
                self.special.setdefault("mati", frames[0])
                if len(frames) > 1:
                    self.extra_idle.extend(frames[1:])
            elif base.startswith("kaki"):
                self.groom.extend(frames)
            elif base.startswith("sleep"):
                self.sleep.extend(frames)
            elif base.startswith("jare"):
                self.play.extend(frames)
            elif base.endswith("togi"):
                short = base[:-4]
                d = {"u": "up", "d": "down", "l": "left", "r": "right"}.get(short)
                if d:
                    self.togi[d] = frames[0]
            elif base in DIR8:
                self.walk[base] = frames
            self.count += len(frames)

    def walk_frames(self, direction: str) -> List[ImageTk.PhotoImage]:
        for cand in DIR_FALLBACK.get(direction, [direction]):
            if cand in self.walk:
                return self.walk[cand]
        if "right" in self.walk:
            return self.walk["right"]
        return next(iter(self.walk.values()), [])

    def togi_frame(self, direction: str) -> Optional[ImageTk.PhotoImage]:
        for cand in DIR_FALLBACK.get(direction, [direction]):
            if cand in self.togi:
                return self.togi[cand]
        if self.togi:
            return next(iter(self.togi.values()))
        return None


# ---------------------------------------------------------------- 多猫联机

class MultiCatNet:
    """局域网 UDP 广播彼此的坐标，多开时猫会互相追逐。"""

    PEER_TTL = 2.5  # 秒：超过这么久没收到广播，就认为那只猫已经关了

    def __init__(self, port: int):
        self.port = port
        self.running = False
        self.peers: Dict[int, Tuple[float, float, float]] = {}
        self.my_id = random.getrandbits(31)
        self.sock: Optional[socket.socket] = None
        self._last_send = 0.0
        self._lock = threading.Lock()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", self.port))
            s.settimeout(0.25)
            self.sock = s
            self.running = True
            threading.Thread(target=self._recv_loop, daemon=True,
                             name="GnekoMultiCatRecv").start()
        except Exception as e:
            print(f"[WARN][MultiCat] 网络初始化失败({e})，多猫功能关闭")

    def _recv_loop(self) -> None:
        while self.running and self.sock is not None:
            try:
                data, _ = self.sock.recvfrom(1024)
                msg = json.loads(data.decode("utf-8"))
                pid = int(msg["id"])
                if pid == self.my_id:
                    continue
                with self._lock:
                    self.peers[pid] = (float(msg["x"]), float(msg["y"]), time.monotonic())
            except socket.timeout:
                continue
            except Exception:
                continue

    def send(self, x: float, y: float) -> None:
        if not self.running or self.sock is None:
            return
        now = time.monotonic()
        if now - self._last_send < 0.1:
            return
        self._last_send = now
        try:
            payload = json.dumps({"id": self.my_id, "x": round(x, 1),
                                  "y": round(y, 1)}).encode("utf-8")
            self.sock.sendto(payload, ("127.255.255.255", self.port))
        except Exception:
            pass

    def peers_list(self) -> List[Tuple[float, float]]:
        now = time.monotonic()
        with self._lock:
            # 顺手清掉已经消失的猫，不然会一直躲一个不存在的影子
            dead = [pid for pid, v in self.peers.items() if now - v[2] > self.PEER_TTL]
            for pid in dead:
                self.peers.pop(pid, None)
            return [(v[0], v[1]) for v in self.peers.values()]

    def close(self) -> None:
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        with self._lock:
            self.peers.clear()


# ---------------------------------------------------------------- 对话气泡

class Bubble:
    """猫头上偶尔冒一句台词的小气泡。"""

    def __init__(self, root: tk.Tk, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#2b2b2b")
        self.label = tk.Label(
            self.win, text="", bg="#fffbe6", fg="#333333",
            font=("Microsoft YaHei UI", 9), padx=8, pady=3,
            justify="center", bd=0,
        )
        self.label.pack(padx=1, pady=1)
        self.win.withdraw()
        self._hide_at = 0.0
        self.visible = False

    def show(self, text: str, pet_x: int, pet_y: int, pet_size: int) -> None:
        if not self.cfg.get("BUBBLE_ENABLE", True) or not text:
            return
        self.label.config(text=text)
        self.win.update_idletasks()
        bw = max(self.win.winfo_reqwidth(), 40)
        bh = self.win.winfo_reqheight()
        vx, vy, vw, vh = virtual_screen()
        bx = int(pet_x + pet_size / 2 - bw / 2)
        by = int(pet_y - bh - 4)
        bx = max(vx + 4, min(bx, vx + vw - bw - 4))
        if by < vy + 4:
            by = int(pet_y + pet_size + 4)
        self.win.geometry(f"+{bx}+{by}")
        self.win.deiconify()
        self.win.lift()
        self.visible = True
        self._hide_at = time.monotonic() + max(0.4, self.cfg.get("BUBBLE_DURATION", 1700) / 1000.0)

    def tick(self) -> None:
        if self.visible and time.monotonic() >= self._hide_at:
            self.win.withdraw()
            self.visible = False

    def move_with(self, pet_x: int, pet_y: int, pet_size: int) -> None:
        if not self.visible:
            return
        bw = self.win.winfo_width()
        bh = self.win.winfo_height()
        self.win.geometry(f"+{int(pet_x + pet_size / 2 - bw / 2)}+{int(pet_y - bh - 4)}")

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 老鼠光标

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


class MouseCursor:
    """被猫追捕时，把系统光标换成 oneko 原版的小老鼠图标。"""

    HOTSPOT = (8, 7)  # oneko mouse_cursor 的 x_hot / y_hot
    IDC_ARROW = 32512
    SPI_SETCURSORS = 0x0057

    def __init__(self, png_path: Path, scale: int = 2):
        self.path = Path(png_path)
        self.scale = max(1, int(scale))
        self.hcursor = 0
        self.active = False
        self.ok = self._build()
        if self.ok:
            atexit.register(MouseCursor.restore_system)

    # ---- 生成 HCURSOR ----
    def _build(self) -> bool:
        if not IS_WIN or not self.path.exists():
            return False
        try:
            u = ctypes.windll.user32
            g = ctypes.windll.gdi32
            g.CreateDIBSection.restype = wt.HBITMAP
            g.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.DWORD,
                                           ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                           wt.DWORD]
            g.DeleteObject.argtypes = [wt.HANDLE]
            g.CreateBitmap.restype = wt.HBITMAP
            u.GetDC.restype = wt.HDC
            u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
            u.CreateIconIndirect.restype = wt.HANDLE
            u.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]

            im = Image.open(self.path).convert("RGBA")
            im = im.resize((im.width * self.scale, im.height * self.scale), Image.NEAREST)
            w, h = im.size
            bgra = im.tobytes("raw", "BGRA")
            alpha = im.getchannel("A").tobytes()

            hdr = BITMAPINFOHEADER()
            hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            hdr.biWidth = w
            hdr.biHeight = -h        # 顶朝下
            hdr.biPlanes = 1
            hdr.biBitCount = 32
            hdr.biCompression = 0    # BI_RGB
            bmi = BITMAPINFO()
            bmi.bmiHeader = hdr

            bits = ctypes.c_void_p()
            hdc = u.GetDC(0)
            hbm_color = g.CreateDIBSection(hdc, ctypes.byref(bmi), 0,
                                           ctypes.byref(bits), None, 0)
            if not hbm_color:
                raise RuntimeError("CreateDIBSection 失败")
            ctypes.memmove(bits, bgra, len(bgra))

            # 1bpp 掩码：透明处填 1，行按 4 字节对齐、自底向上
            stride = ((w + 31) // 32) * 4
            buf = bytearray(stride * h)
            for row in range(h):
                y = h - 1 - row
                base = row * stride
                for x in range(w):
                    if alpha[y * w + x] == 0:
                        buf[base + (x // 8)] |= 1 << (x % 8)
            hbm_mask = g.CreateBitmap(w, h, 1, 1, ctypes.c_char_p(bytes(buf)))

            info = ICONINFO(0, self.HOTSPOT[0] * self.scale, self.HOTSPOT[1] * self.scale,
                            hbm_mask, hbm_color)
            self.hcursor = int(u.CreateIconIndirect(ctypes.byref(info)) or 0)
            g.DeleteObject(hbm_color)
            g.DeleteObject(hbm_mask)
            u.ReleaseDC(0, hdc)
            return bool(self.hcursor)
        except Exception as e:
            log(f"[WARN] 老鼠光标创建失败: {e}")
            return False

    # ---- 换光标：直接替换系统箭头，全桌面有效 ----
    @staticmethod
    def restore_system() -> None:
        """把系统光标恢复成 Windows 默认。"""
        if not IS_WIN:
            return
        try:
            ctypes.windll.user32.SystemParametersInfoW(MouseCursor.SPI_SETCURSORS, 0, None, 0)
        except Exception:
            pass

    def _apply(self) -> bool:
        try:
            u = ctypes.windll.user32
            u.CopyIcon.restype = wt.HANDLE
            u.SetSystemCursor.argtypes = [wt.HANDLE, wt.DWORD]
            h = u.CopyIcon(self.hcursor)
            if not h:
                return False
            # SetSystemCursor 成功后会接管并销毁传入的句柄
            return bool(u.SetSystemCursor(h, self.IDC_ARROW))
        except Exception as e:
            log(f"[WARN] 替换系统光标失败: {e}")
            return False

    # ---- 对外 ----
    def set_active(self, on: bool) -> None:
        on = bool(on) and self.ok
        if on == self.active:
            return
        if on and self._apply():
            self.active = True
        elif not on:
            self.active = False
            self.restore_system()


# ---------------------------------------------------------------- 主角色

class GnekoPet:
    def __init__(self, root: tk.Tk, cfg: Dict[str, Any], config_path: Path):
        self.cfg = cfg
        self.root = root
        self.config_path = config_path
        self.asset_dir = resolve_asset_dir(cfg)

        # 窗口
        self.pet_w = int(cfg["PET_WIDTH"])
        self.pet_h = int(cfg["PET_HEIGHT"])
        self.root.overrideredirect(True)
        self.root.configure(bg=cfg["KEY_COLOR"])
        self.key_color = cfg["KEY_COLOR"]
        if cfg["ALWAYS_ON_TOP"]:
            self.root.attributes("-topmost", True)
        self.transparent_ok = self._setup_transparency()
        self._last_mask: Optional[bytes] = None   # Linux SHAPE 用的当前轮廓
        self._shape_win = 0

        # DPI 与缩放
        self.dpi_factor = 1.0
        try:
            self.dpi_factor = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self.dpi_factor = 1.0
        self._resolve_scale(int(cfg["SCALE"]))

        self.bank = SpriteBank(self.asset_dir, self.scale, self.key_color, self.pet_w)
        self.mouse_cursor: Optional[MouseCursor] = None
        if cfg.get("MOUSE_CURSOR_ENABLE", True):
            png = self.asset_dir / "mouse.png"
            if png.exists():
                self.mouse_cursor = MouseCursor(png, int(cfg.get("MOUSE_CURSOR_SCALE", 2)))
                if not self.mouse_cursor.ok:
                    log("[Gneko] 老鼠光标不可用，跳过该功能")
        self.canvas = tk.Canvas(root, width=self.pet_w, height=self.pet_h,
                                bg=self.key_color, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.image_item = self.canvas.create_image(0, 0, anchor=tk.NW)
        self.fallback_rect: Optional[int] = None
        self.target_box: Optional[int] = None
        self._last_img: Optional[ImageTk.PhotoImage] = None

        # 屏幕范围
        self.bounds = self._compute_bounds()
        if cfg.get("REMEMBER_POSITION", True) and int(cfg.get("LAST_X", -1)) >= 0:
            self.x = float(cfg["LAST_X"])
            self.y = float(cfg["LAST_Y"])
        else:
            self.x = float(random.randint(self.bounds[0],
                                          max(self.bounds[0], self.bounds[2] - self.pet_w)))
            self.y = float(random.randint(self.bounds[1],
                                          max(self.bounds[1], self.bounds[3] - self.pet_h)))
        self.clamp_position()
        self._last_win_pos: Optional[Tuple[int, int]] = None
        # 先让 Tk 真正创建窗口，才能拿到顶层句柄
        self.root.update_idletasks()
        self.hwnd = self._get_hwnd()
        self._apply_window_flags()
        if IS_LINUX:
            self._apply_shape()   # 先裁成整块，避免第一帧出现前闪出方框
        if bool(self.cfg.get("CLICK_THROUGH", False)):
            self.set_click_through(True, silent=True)

        # 运动状态
        self.target_x = self.x
        self.target_y = self.y
        self.vx = 0.0
        self.vy = 0.0
        self.spd_now = float(cfg["BASE_SPEED"])
        self.walk_dir = "right"
        self.frame_idx = 0
        self.anim_tick = 0.0
        self.k = 1.0
        self.dt = float(cfg["LOOP_INTERVAL"])

        # 行为状态
        self.state = STATE_IDLE
        self.idle_sub_state = IDLE_SUB_STATIC
        self.idle_timer = self._rand_idle()
        self.idle_static_timer = 0.0
        self.idle_static_swap = random.randint(cfg["IDLE_STATIC_SWAP_MIN"], cfg["IDLE_STATIC_SWAP_MAX"])
        self.idle_use_awake = True
        self.scratch_timer = 0.0
        self.groom_timer = 0.0
        self.sleep_timer = 0.0
        self.play_timer = 0.0
        self.energy = float(cfg["ENERGY_MAX"])
        self.chase_interest = float(cfg["INTEREST_FLOOR"])
        self.is_chase_mode = False
        self.chase_sub_mode = CHASE_SUB_NORMAL
        self.chase_mode_timer = 0.0
        self.mouse_vel = 0.0
        self.mouse_still = 0.0
        self.catch_cooldown = 0.0
        self.catch_count = 0
        self._dbg_dist = 0.0
        self.pounce_timer = 0.0
        self.avoid_timer = 0.0
        self.avoid_dir_x = 0.0
        self.avoid_dir_y = 0.0
        self.sit_timer = 0.0
        self.last_mx, self.last_my = get_cursor_pos()

        # 旋转动作
        self.spin_cx = 0.0
        self.spin_cy = 0.0
        self.spin_angle = 0.0
        self.spin_timer = 0.0
        self.spin_cooldown = 0.0

        # 拖动
        self.is_dragging = False
        self.drag_after_timer = 0.0
        self.drag_start = (0, 0)
        self.win_start = (0.0, 0.0)
        self.fling_vx = 0.0
        self.fling_vy = 0.0
        self.stun_timer = 0.0
        self._bounds_timer = 0.0
        self._drag_samples: List[Tuple[float, float, float]] = []

        # 点击检测
        self._left_prev = False
        self._last_say = 0.0
        self._hotkey_prev = False
        self._esc_prev = False
        self.click_through = bool(cfg.get("CLICK_THROUGH", False))

        # 多猫
        self.net = MultiCatNet(int(cfg["MULTICAT_PORT"])) if cfg["ENABLE_MULTICAT_NET"] else None

        # 气泡与菜单
        self.bubble = Bubble(root, cfg)
        self._build_menu()
        self._bind_events()

        self._last_tick = time.perf_counter()
        self._last_err_log = 0.0
        self._after_id: Optional[str] = None
        self._alive = True
        self._t0 = time.monotonic()
        root.after(1, self._tick)

    # ---------------- 尺寸 ----------------
    def _resolve_scale(self, base: int) -> None:
        s = max(1, base)
        if self.cfg.get("AUTO_SCALE_HIDPI", True):
            s = max(1, int(round(base * self.dpi_factor)))
        self.scale = s
        self.cell = int(self.cfg["PET_WIDTH"])
        self.pet_w = self.cell * s
        self.pet_h = int(self.cfg["PET_HEIGHT"]) * s

    # ---------------- 窗口 ----------------
    def _setup_transparency(self) -> bool:
        if IS_LINUX:
            # Linux 没有色键透明，改成每帧用 SHAPE 把窗口裁成猫的轮廓，
            # 真正生效要等第一帧渲染出来（见 _apply_shape）。
            if x11() is None:
                print("[WARN] 没有 X11/SHAPE，窗口会是实心方块")
                return False
            return True
        if not IS_WIN:
            return False
        try:
            self.root.attributes("-transparentcolor", self.key_color)
            return True
        except Exception:
            print("[WARN] 色键透明不可用，退回普通窗口")
            return False

    def _apply_shape(self, mask: Optional[bytes] = None) -> None:
        """Linux：按 1 位掩码裁剪窗口；穿透模式下把输入区域整个清空。"""
        if not IS_LINUX:
            return
        s = x11()
        if s is None:
            return
        if mask:
            self._last_mask = mask
        data = self._last_mask
        if not data:
            # 还没渲染过就先裁成整块，保证窗口能显示
            data = b"\xff" * (((self.pet_w + 7) // 8) * self.pet_h)
        win = int(self.root.winfo_id())
        if s.shape(win, data, self.pet_w, self.pet_h, bool(getattr(self, "click_through", False))):
            self.transparent_ok = True
            self._shape_win = win

    def _get_hwnd(self) -> int:
        if not IS_WIN:
            return 0
        try:
            u = ctypes.windll.user32
            u.GetParent.argtypes = [wt.HWND]
            u.GetParent.restype = wt.HWND
            u.GetDesktopWindow.restype = wt.HWND
            h = u.GetParent(self.root.winfo_id())
            desktop = u.GetDesktopWindow()
            for _ in range(8):
                parent = u.GetParent(h) if h else None
                if not parent or parent == desktop:
                    break
                h = parent
            return int(h or 0) or int(self.root.winfo_id())
        except Exception:
            return 0

    def _apply_window_flags(self) -> None:
        """色键透明 + 工具窗口 + 置顶，直接操作真正的顶层句柄。"""
        if not self.hwnd:
            return
        u = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TOOLWINDOW = 0x00000080
        LWA_COLORKEY = 0x00000001
        try:
            ex = u.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            u.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
            r = int(self.key_color[1:3], 16)
            g = int(self.key_color[3:5], 16)
            b = int(self.key_color[5:7], 16)
            colorref = (b << 16) | (g << 8) | r
            ok = bool(u.SetLayeredWindowAttributes(self.hwnd, colorref, 0, LWA_COLORKEY))
            self.transparent_ok = ok
        except Exception as e:
            print(f"[WARN] 窗口透明设置失败: {e}")
            self.transparent_ok = False
        self._force_topmost()

    def _force_topmost(self) -> None:
        if not self.hwnd:
            return
        try:
            # HWND_TOPMOST=-1, NOSIZE|NOMOVE|NOACTIVATE
            ctypes.windll.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0,
                                              0x0001 | 0x0002 | 0x0010)
        except Exception:
            pass

    def _compute_bounds(self) -> Tuple[int, int, int, int]:
        vx, vy, vw, vh = virtual_screen()
        x0, y0, x1, y1 = vx, vy, vx + vw, vy + vh
        if self.cfg.get("WORKAREA_AWARE", True):
            wx0, wy0, wx1, wy1 = primary_workarea()
            margin = int(self.cfg["EDGE_MARGIN"])
            # 只有主屏占满虚拟桌面时才用工作区，避免多屏误裁
            if wx0 <= x0 + margin and wx1 >= x1 - margin:
                y1 = min(y1, wy1)
        return x0, y0, x1, y1

    def _set_win_pos(self, x: int, y: int) -> None:
        """位置交给 Tk 自己维护，避免和 Tk 的几何管理器打架。"""
        self.root.geometry(f"+{int(x)}+{int(y)}")

    def _apply_window_size(self) -> None:
        self.canvas.config(width=self.pet_w, height=self.pet_h)
        self.root.geometry(f"{self.pet_w}x{self.pet_h}+{int(self.x)}+{int(self.y)}")
        self._last_win_pos = None

    # ---------------- 菜单 ----------------
    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=0)

        scale_menu = tk.Menu(self.menu, tearoff=0)
        for s in (1, 2, 3, 4, 5, 6):
            scale_menu.add_command(label=f"{s}x", command=lambda v=s: self.set_scale(v))
        self.menu.add_cascade(label="大小", menu=scale_menu)

        speed_menu = tk.Menu(self.menu, tearoff=0)
        for label, mult in (("慢悠悠 0.7x", 0.7), ("标准 1.0x", 1.0), ("轻快 1.4x", 1.4)):
            speed_menu.add_command(label=label, command=lambda m=mult: self.set_speed(m))
        self.menu.add_cascade(label="速度", menu=speed_menu)

        self.follow_var = tk.BooleanVar(value=bool(self.cfg["MULTICAT_CHASE_ENABLE"]))
        self.menu.add_checkbutton(label="跟随鼠标", variable=self.follow_var,
                                  command=self._toggle_follow)
        self.bubble_var = tk.BooleanVar(value=bool(self.cfg.get("BUBBLE_ENABLE", True)))
        self.menu.add_checkbutton(label="说说话", variable=self.bubble_var,
                                  command=lambda: self._toggle_bubble(self.bubble_var.get()))
        self.remember_var = tk.BooleanVar(value=bool(self.cfg.get("REMEMBER_POSITION", True)))
        self.menu.add_checkbutton(label="记住上次位置", variable=self.remember_var,
                                  command=self._toggle_remember)
        self.through_var = tk.BooleanVar(value=self.click_through)
        self.menu.add_checkbutton(label="穿透点击 (Ctrl+Alt+G)", variable=self.through_var,
                                  command=lambda: self.set_click_through(self.through_var.get()))
        self.mouse_var = tk.BooleanVar(value=self.mouse_cursor is not None)
        self.menu.add_checkbutton(label="被追时变老鼠", variable=self.mouse_var,
                                  command=self._toggle_mouse_cursor)
        self.menu.add_separator()
        self.menu.add_command(label="睡一会儿", command=self.go_sleep)
        self.menu.add_command(label="叫醒它", command=self.wake_up)
        self.menu.add_command(label="回到鼠标处", command=self.jump_to_cursor)
        self.menu.add_command(label="转个圈", command=self.trigger_spin_action)
        self.menu.add_separator()
        # 皮肤：预制素材包 + 原版
        skin_menu = tk.Menu(self.menu, tearoff=0)
        cur_skin = str(self.cfg.get("SKIN") or SKIN_CLASSIC).strip()
        if cur_skin.lower() in SKIN_CLASSIC_ALIASES:
            cur_skin = SKIN_CLASSIC
        self.skin_var = tk.StringVar(value=cur_skin)
        skin_menu.add_radiobutton(label="原版（黑白）", value=SKIN_CLASSIC,
                                  variable=self.skin_var,
                                  command=lambda: self.set_skin(SKIN_CLASSIC))
        names = available_skins(self.cfg)
        if names:
            skin_menu.add_separator()
        for name in names:
            skin_menu.add_radiobutton(label=f"{skin_label(name)}（{name}）", value=name,
                                      variable=self.skin_var,
                                      command=lambda n=name: self.set_skin(n))
        self.menu.add_cascade(label="皮肤", menu=skin_menu)
        self.menu.add_command(label="重载素材", command=self.reload_sprites)
        self.menu.add_command(label="打开素材文件夹", command=self.open_asset_folder)
        bg_menu = tk.Menu(self.menu, tearoff=0)
        for c in self.cfg["BG_COLOR_PRESETS"]:
            bg_menu.add_command(label=c, command=lambda v=c: self.set_bg_color(v))
        self.menu.add_cascade(label="背景色（调试用）", menu=bg_menu)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_end)
        self.canvas.bind("<Double-Button-1>", lambda _: self.trigger_spin_action())
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Enter>", self.on_pointer_enter)
        self.canvas.bind("<Leave>", self.on_pointer_leave)
        self.root.bind("<Escape>", lambda _: self.quit())

    # ---------------- 设置项 ----------------
    def set_scale(self, new_scale: int) -> None:
        self.cfg["SCALE"] = int(new_scale)
        self.cfg["AUTO_SCALE_HIDPI"] = False
        self._resolve_scale(int(new_scale))
        self.bank = SpriteBank(self.asset_dir, self.scale, self.key_color, self.cell)
        self.bounds = self._compute_bounds()
        self._apply_window_size()
        self._last_img = None
        self.clamp_position()
        self.save()

    def set_speed(self, mult: float) -> None:
        self.cfg["BASE_SPEED"] = round(1.4 * mult, 3)
        self.save()

    def _toggle_follow(self) -> None:
        self.cfg["MULTICAT_CHASE_ENABLE"] = bool(self.follow_var.get())
        if not self.follow_var.get():
            self.is_chase_mode = False
        self.save()

    def _toggle_bubble(self, on: bool) -> None:
        self.cfg["BUBBLE_ENABLE"] = bool(on)
        if not on:
            self.bubble.win.withdraw()
            self.bubble.visible = False
        self.save()

    def _toggle_remember(self) -> None:
        self.cfg["REMEMBER_POSITION"] = bool(self.remember_var.get())
        if self.remember_var.get():
            self.cfg["LAST_X"] = int(self.x)
            self.cfg["LAST_Y"] = int(self.y)
        self.save()

    def _toggle_mouse_cursor(self) -> None:
        on = bool(self.mouse_var.get())
        if on and self.mouse_cursor is None:
            png = self.asset_dir / "mouse.png"
            if png.exists():
                self.mouse_cursor = MouseCursor(png, int(self.cfg.get("MOUSE_CURSOR_SCALE", 2)))
            if self.mouse_cursor is None or not self.mouse_cursor.ok:
                self.mouse_var.set(False)
                self.say("没有老鼠图标")
                return
        if self.mouse_cursor is not None:
            self.mouse_cursor.set_active(False)
        self.cfg["MOUSE_CURSOR_ENABLE"] = on
        self.save()

    def _update_mouse_cursor(self) -> None:
        if self.mouse_cursor is None:
            return
        # 只在真的在追、而且已经逼近时换老鼠光标，避免日常一直换来换去
        chase = (self.is_chase_mode and not self.is_dragging
                 and self.state == STATE_WALK and self._dbg_dist < 300)
        self.mouse_cursor.set_active(chase)

    def set_bg_color(self, color: str) -> None:
        """仅在不支持色键透明时生效，用于排查显示问题。"""
        self.cfg["CANVAS_BG_COLOR"] = color
        if not self.transparent_ok:
            self.canvas.config(bg=color)
            self.root.configure(bg=color)
        self.save()

    def reload_sprites(self) -> None:
        self.bank = SpriteBank(self.asset_dir, self.scale, self.key_color, self.cell)
        self._last_img = None
        self.say("换新衣服")

    def set_skin(self, name: str) -> None:
        """切换皮肤：换素材目录 + 重建帧缓存 + 同步老鼠光标。"""
        name = str(name or SKIN_CLASSIC).strip() or SKIN_CLASSIC
        if name.lower() in SKIN_CLASSIC_ALIASES:
            name = SKIN_CLASSIC
        if name != SKIN_CLASSIC:
            cand = skins_root(self.cfg) / name
            if not cand.exists() or next(cand.glob("*.png"), None) is None:
                name = SKIN_CLASSIC      # 目录不存在就当原版，别在配置里留个死名字
        self.cfg["SKIN"] = name
        self.asset_dir = resolve_asset_dir(self.cfg)
        self.bank = SpriteBank(self.asset_dir, self.scale, self.key_color, self.cell)
        self._last_img = None
        if self.bank.count == 0:
            # 素材全废了也退回原版，别让猫变成隐形
            self.cfg["SKIN"] = SKIN_CLASSIC
            self.asset_dir = resolve_asset_dir(self.cfg)
            self.bank = SpriteBank(self.asset_dir, self.scale, self.key_color, self.cell)
            self.say("这套没素材呀")
        else:
            self.say(f"换上{skin_label(name)}")
        if hasattr(self, "skin_var"):
            self.skin_var.set(str(self.cfg.get("SKIN") or SKIN_CLASSIC))
        # 老鼠光标跟着皮肤目录走
        if self.mouse_cursor is not None:
            self.mouse_cursor.set_active(False)
            self.mouse_cursor = None
        if self.cfg.get("MOUSE_CURSOR_ENABLE", True):
            png = self.asset_dir / "mouse.png"
            if png.exists():
                mc = MouseCursor(png, int(self.cfg.get("MOUSE_CURSOR_SCALE", 2)))
                self.mouse_cursor = mc if mc.ok else None
        self.save()

    def set_click_through(self, on: bool, silent: bool = False) -> None:
        """穿透点击：猫不再挡住底下的窗口，Ctrl+Alt+G 随时切回来。"""
        if IS_LINUX:
            self.click_through = bool(on)
            self.cfg["CLICK_THROUGH"] = self.click_through
            if hasattr(self, "through_var"):
                self.through_var.set(self.click_through)
            self._apply_shape()
            if on:
                self.state = STATE_IDLE
                self.is_chase_mode = False
                if not silent:
                    self.say("透过去啦")
            elif not silent:
                self.say("我回来啦")
            self.save()
            return
        if not self.hwnd:
            return
        u = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        try:
            ex = u.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
            u.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex)
            u.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception as e:
            log(f"[WARN] 切换穿透失败: {e}")
            return
        self.click_through = bool(on)
        self.cfg["CLICK_THROUGH"] = self.click_through
        if hasattr(self, "through_var"):
            self.through_var.set(self.click_through)
        if on:
            self.state = STATE_IDLE
            self.is_chase_mode = False
            if not silent:
                self.say("透过去啦")
        elif not silent:
            self.say("我回来啦")
        self.save()

    def _poll_hotkey(self) -> None:
        # Ctrl + Alt + G 切换穿透（穿透状态下唯一的入口）
        combo = is_key_down(0x11) and is_key_down(0x12) and is_key_down(0x47)
        if combo and not self._hotkey_prev:
            self.set_click_through(not self.click_through)
        self._hotkey_prev = combo
        if IS_LINUX:
            # 无边框窗口基本拿不到焦点，Esc 只能靠全局读键，顺带按住 Ctrl+Q 也能退
            esc = is_key_down(0x1B)
            if esc and not self._esc_prev:
                self.quit()
            self._esc_prev = esc

    def open_asset_folder(self) -> None:
        try:
            if IS_LINUX:
                subprocess.Popen(["xdg-open", str(self.asset_dir)])
            else:
                os.startfile(str(self.asset_dir))  # type: ignore[attr-defined]
        except Exception as e:
            print(f"[WARN] 无法打开素材目录: {e}")

    def jump_to_cursor(self) -> None:
        mx, my = get_cursor_pos()
        self.x = float(mx - self.pet_w / 2)
        self.y = float(my - self.pet_h / 2)
        self.target_x, self.target_y = self.x, self.y
        self.clamp_position()
        self.state = STATE_IDLE
        self.idle_sub_state = IDLE_SUB_LOOK
        self.idle_timer = 900
        self.is_chase_mode = False

    def save(self) -> None:
        if self.cfg.get("SAVE_SETTINGS", True):
            save_config(self.config_path, self.cfg)

    # ---------------- 交互 ----------------
    def on_pointer_enter(self, _event=None) -> None:
        if not self.cfg.get("PET_ON_HOVER", True) or self.is_dragging:
            return
        if self.state in (STATE_WALK, STATE_IDLE):
            self.state = STATE_PET
            self.say("别戳啦")

    def on_pointer_leave(self, _event=None) -> None:
        if self.state == STATE_PET and not self.is_dragging:
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_LOOK
            self.idle_timer = random.randint(600, 1400)

    def on_drag_start(self, event) -> None:
        self.is_dragging = True
        self.state = STATE_PET
        self.drag_start = (event.x_root, event.y_root)
        self.win_start = (self.x, self.y)
        self.target_x, self.target_y = self.x, self.y
        self.spin_cooldown = float(self.cfg["SPIN_ACTION_COOLDOWN_MS"])
        self._drag_samples = [(time.perf_counter(), event.x_root, event.y_root)]

    def on_drag_move(self, event) -> None:
        if not self.is_dragging:
            return
        dx = event.x_root - self.drag_start[0]
        dy = event.y_root - self.drag_start[1]
        self.x = self.win_start[0] + dx
        self.y = self.win_start[1] + dy
        self.clamp_position()
        self.target_x, self.target_y = self.x, self.y
        now = time.perf_counter()
        self._drag_samples.append((now, event.x_root, event.y_root))
        # 只留最近 0.3s 的采样，够算出手速
        self._drag_samples = [s for s in self._drag_samples if now - s[0] < 0.3][-8:]

    def _drag_velocity(self) -> Tuple[float, float]:
        """根据最近几个采样点算出松手时的速度（像素/秒）。"""
        samples = getattr(self, "_drag_samples", None)
        if not samples or len(samples) < 2:
            return 0.0, 0.0
        t0, x0, y0 = samples[0]
        t1, x1, y1 = samples[-1]
        dt = t1 - t0
        if dt <= 0.001:
            return 0.0, 0.0
        return (x1 - x0) / dt, (y1 - y0) / dt

    def on_drag_end(self, _event=None) -> None:
        self.is_dragging = False
        self.drag_after_timer = float(self.cfg["DRAG_AFTER_IDLE_TIME"])
        vx, vy = self._drag_velocity()
        speed = math.hypot(vx, vy)
        if self.cfg.get("FLING_ENABLE", True) and speed >= self.cfg["FLING_MIN_SPEED"]:
            # 甩出去：带着惯性飞一段，撞屏幕边缘会弹
            limit = float(self.cfg["FLING_MAX_SPEED"])
            if speed > limit:
                vx, vy = vx / speed * limit, vy / speed * limit
            self.fling_vx, self.fling_vy = vx, vy
            self.state = STATE_FLUNG
            self.say("哇——")
            return
        edge = self.edge_direction()
        if edge and random.random() < self.cfg["EDGE_SCRATCH_CHANCE"]:
            self.state = STATE_SCRATCH
            self.scratch_timer = float(self.cfg["SCRATCH_DELAY"])
        else:
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_LOOK
            self.idle_timer = random.randint(600, 1400)

    def _update_fling(self) -> None:
        """惯性飞行：摩擦减速 + 边缘反弹，速度小了就爬起来。"""
        dt_s = self.dt / 1000.0
        self.x += self.fling_vx * dt_s
        self.y += self.fling_vy * dt_s
        # 摩擦：按实际帧间隔做指数衰减
        decay = self.cfg["FLING_FRICTION"] ** (self.dt / 24.0)
        self.fling_vx *= decay
        self.fling_vy *= decay

        x0, y0, x1, y1 = self.bounds
        bounce = self.cfg["FLING_BOUNCE"]
        if self.x < x0:
            self.x = x0
            self.fling_vx = abs(self.fling_vx) * bounce
        elif self.x > x1 - self.pet_w:
            self.x = x1 - self.pet_w
            self.fling_vx = -abs(self.fling_vx) * bounce
        if self.y < y0:
            self.y = y0
            self.fling_vy = abs(self.fling_vy) * bounce
        elif self.y > y1 - self.pet_h:
            self.y = y1 - self.pet_h
            self.fling_vy = -abs(self.fling_vy) * bounce

        self._face(self.fling_vx, self.fling_vy)
        if math.hypot(self.fling_vx, self.fling_vy) < self.cfg["FLING_STOP_SPEED"]:
            self.fling_vx = self.fling_vy = 0.0
            # 落地摔懵一下，再爬起来
            self.state = STATE_PET
            self.stun_timer = float(self.cfg["FLING_STUN_MS"])
            self.say("哎哟")

    def on_right_click(self, event) -> None:
        if not self._alive:
            return
        if self.state in (STATE_SIT_ON_CURSOR, STATE_SIT_APPROACH):
            self.state = STATE_IDLE
            self.idle_timer = 800
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            pass
        finally:
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass

    def say(self, text: Optional[str] = None) -> None:
        now = time.monotonic()
        if now - self._last_say < 3.0:
            return
        lines = self.cfg.get("BUBBLE_LINES") or []
        if text is None and lines:
            text = random.choice(lines)
        if text:
            self._last_say = now
            self.bubble.show(text, int(self.x), int(self.y), self.pet_w)

    # ---------------- 行为 ----------------
    def _rand_idle(self) -> float:
        return float(random.randint(self.cfg["IDLE_TIME_MIN"], self.cfg["IDLE_TIME_MAX"]))

    def go_sleep(self) -> None:
        if not self.bank.sleep:
            return
        self.state = STATE_SLEEP
        self.sleep_timer = float(self.cfg["SLEEP_DURATION"])
        self.say("zZ")

    def wake_up(self) -> None:
        if self.state != STATE_SLEEP:
            return
        self.state = STATE_IDLE
        self.idle_sub_state = IDLE_SUB_LOOK
        self.idle_timer = float(self.cfg["SLEEP_SCARE_IDLE_TIME"])
        self.idle_static_timer = 0.0
        self.say("喵")

    def trigger_spin_action(self) -> None:
        if self.state == STATE_SPIN_ACTION:
            return
        self.spin_cx, self.spin_cy = self.x, self.y
        self.spin_angle = 0.0
        self.spin_timer = float(self.cfg["SPIN_ACTION_DURATION_SEC"]) * 1000.0
        self.state = STATE_SPIN_ACTION
        self.say("转圈圈")

    def clamp_position(self) -> None:
        x0, y0, x1, y1 = self.bounds
        self.x = max(x0, min(self.x, x1 - self.pet_w))
        self.y = max(y0, min(self.y, y1 - self.pet_h))

    def edge_direction(self) -> Optional[str]:
        x0, y0, x1, y1 = self.bounds
        em = float(self.cfg["EDGE_MARGIN"])
        near_l = self.x <= x0 + em
        near_r = self.x + self.pet_w >= x1 - em
        near_t = self.y <= y0 + em
        near_b = self.y + self.pet_h >= y1 - em
        if near_l and near_t:
            return "upleft"
        if near_l and near_b:
            return "dwleft"
        if near_r and near_t:
            return "upright"
        if near_r and near_b:
            return "dwright"
        if near_l:
            return "left"
        if near_r:
            return "right"
        if near_t:
            return "up"
        if near_b:
            return "down"
        return None

    def _face(self, dx: float, dy: float) -> None:
        if abs(dx) < DIR_DEAD_ZONE and abs(dy) < DIR_DEAD_ZONE:
            return
        ang = math.degrees(math.atan2(dy, dx))  # 屏幕坐标：y 向下
        sector = int(((ang + 22.5) % 360) // 45)
        cand = DIR8[sector]
        if not self.cfg.get("DIAGONAL_SPRITES", True):
            cand = {"dwright": "right", "dwleft": "left",
                    "upleft": "left", "upright": "right"}.get(cand, cand)
        if self.bank.walk_frames(cand):
            self.walk_dir = cand

    # ---------------- 主循环 ----------------
    def _tick(self) -> None:
        if not self._alive:
            return
        try:
            self._step()
        except Exception:
            now = time.monotonic()
            if now - self._last_err_log > 5:
                self._last_err_log = now
                log_exception("tick")
        if not self._alive:
            return
        try:
            self._after_id = self.root.after(self._next_interval(), self._tick)
        except Exception:
            pass

    def _step(self) -> None:
        now = time.perf_counter()
        dt = (now - self._last_tick) * 1000.0
        self._last_tick = now
        self.dt = max(1.0, min(dt, 140.0))
        self.k = self.dt / 30.0

        # 分辨率/任务栏变了也要跟上，别把猫困在屏幕外
        self._bounds_timer += self.dt
        if self._bounds_timer >= 2000:
            self._bounds_timer = 0.0
            try:
                nb = self._compute_bounds()
                if nb != self.bounds:
                    self.bounds = nb
                    self.clamp_position()
            except Exception:
                pass

        if self.spin_cooldown > 0:
            self.spin_cooldown = max(0.0, self.spin_cooldown - self.dt)

        mx, my = get_cursor_pos()
        if self.last_mx is not None:
            moved = math.hypot(mx - self.last_mx, my - self.last_my)
            # 鼠标瞬时速度（px/秒），追捕强度会参考它
            self.mouse_vel = moved * 1000.0 / max(1.0, self.dt)
            # 鼠标停住多久了：停久了猫就慢慢失去兴趣
            self.mouse_still = 0.0 if moved > 2 else self.mouse_still + self.dt
        self._dbg_dist = math.hypot(mx - self.x, my - self.y)
        self._poll_clicks()
        self._poll_hotkey()
        if self.net:
            self.net.send(self.x, self.y)
        self.bubble.tick()

        if self.state == STATE_SPIN_ACTION:
            self._update_spin()
        elif self.state == STATE_FLUNG:
            self._update_fling()
        else:
            self._update_energy()
            self.chase_interest = max(0.0, self.chase_interest - self.cfg["INTEREST_DECAY_PER_TICK"] * self.k)
            # 你在附近时兴趣有保底，猫不会追两下就失去兴趣
            if (self._dbg_dist < self.cfg["ROAM_TRIGGER_DIST"]
                    and self.energy > self.cfg["ENERGY_TIRED_THRESHOLD"]
                    and self.mouse_still < self.cfg["INTEREST_FLOOR_HOLD_MS"]):
                self.chase_interest = max(self.chase_interest,
                                          float(self.cfg["INTEREST_FLOOR"]))
            self._update_avoid(mx, my)
            self._update_sit(mx, my)
            self._check_mouse_nearby(mx, my)
            self._update_state_timers()
            if self.state == STATE_WALK:
                self._update_physics(mx, my)

        self._advance_animation()
        self._update_mouse_cursor()
        if self.drag_after_timer > 0:
            self.drag_after_timer = max(0.0, self.drag_after_timer - self.dt)

        self._render()
        if self.cfg["DEBUG_MODE"]:
            try:
                chase_tag = self.chase_sub_mode if self.is_chase_mode else "none"
                print(f"[Gneko] state={self.state}/{self.idle_sub_state} chase={chase_tag} "
                      f"d={self._dbg_dist:.0f} mvel={self.mouse_vel:.0f} still={self.mouse_still:.0f} catch={self.catch_count} "
                      f"interest={self.chase_interest:.0f} energy={self.energy:.0f} "
                      f"pos=({self.x:.0f},{self.y:.0f}) scale={self.scale}x fps~{1000 / max(self.dt, 1):.0f}")
            except Exception:
                pass
        self.last_mx, self.last_my = mx, my

    def _next_interval(self) -> int:
        if self.state in QUIET_STATES and not self.is_dragging:
            return int(self.cfg["LOOP_INTERVAL_IDLE"])
        return int(self.cfg["LOOP_INTERVAL"])

    def _poll_clicks(self) -> None:
        down = is_left_button_down()
        if down and not self._left_prev:
            self._on_click()
        self._left_prev = down

    def _on_click(self) -> None:
        if self.state == STATE_SLEEP:
            self.wake_up()
            return
        if not self.is_dragging:
            self.chase_interest = min(self.cfg["INTEREST_MAX"],
                                      self.chase_interest + self.cfg["INTEREST_PER_CLICK"])

    def _update_energy(self) -> None:
        if self.state == STATE_WALK and self.is_chase_mode:
            drain = self.cfg["ENERGY_DRAIN_PER_TICK"] * (2.2 if self.chase_sub_mode == CHASE_SUB_POUNCE else 1.0)
            self.energy -= drain * self.k
        elif self.state == STATE_SLEEP:
            self.energy += self.cfg["ENERGY_REGEN_SLEEP"] * self.k
        else:
            self.energy += self.cfg["ENERGY_REGEN_IDLE"] * self.k
        self.energy = max(0.0, min(float(self.cfg["ENERGY_MAX"]), self.energy))

    def _update_spin(self) -> None:
        self.spin_timer -= self.dt
        self.spin_angle += self.cfg["SPIN_ACTION_ANGULAR_SPEED"] * (self.dt / 1000.0)
        r = float(self.cfg["SPIN_ACTION_RADIUS"])
        self.x = self.spin_cx + r * math.cos(self.spin_angle)
        self.y = self.spin_cy + r * math.sin(self.spin_angle)
        self.clamp_position()
        self._face(-math.sin(self.spin_angle), math.cos(self.spin_angle))
        if self.spin_timer <= 0:
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_STATIC
            self.idle_timer = self._rand_idle()
            self.spin_cooldown = float(self.cfg["SPIN_ACTION_COOLDOWN_MS"])

    def _update_avoid(self, mx: int, my: int) -> None:
        if self.state in (STATE_SLEEP, STATE_PET, STATE_SCRATCH, STATE_AVOID,
                          STATE_SIT_ON_CURSOR, STATE_SIT_APPROACH, STATE_SPIN_ACTION,
                          STATE_PLAY) or self.is_dragging:
            return
        d = math.hypot(mx - self.x, my - self.y)
        if d > self.cfg["AVOID_TRIGGER_MAX_DIST"]:
            return
        speed = math.hypot(mx - self.last_mx, my - self.last_my)
        if speed < self.cfg["AVOID_TRIGGER_SPEED"]:
            return
        nx, ny = -(my - self.y), (mx - self.x)
        ln = math.hypot(nx, ny)
        if ln < 0.01:
            nx, ny = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        else:
            nx, ny = nx / ln, ny / ln
        if random.random() > 0.5:
            nx, ny = -nx, -ny
        self.state = STATE_AVOID
        self.avoid_timer = float(self.cfg["AVOID_DURATION"])
        self.avoid_dir_x, self.avoid_dir_y = nx, ny

    def _update_sit(self, mx: int, my: int) -> None:
        tx = mx + self.cfg["SIT_OFFSET_X"]
        ty = my + self.cfg["SIT_OFFSET_Y"]
        if self.state == STATE_SIT_APPROACH:
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            self._face(dx, dy)
            if dist < 6.0:
                self.state = STATE_SIT_ON_CURSOR
                self.sit_timer = float(self.cfg["SIT_MAX_DURATION"])
                self.say("趴一下")
            elif dist > 0.1:
                step = float(self.cfg["SIT_MOVE_SPEED"]) * self.k
                self.x += dx / dist * step
                self.y += dy / dist * step
                self.clamp_position()
        elif self.state == STATE_SIT_ON_CURSOR:
            self.sit_timer -= self.dt
            cursor_speed = math.hypot(mx - self.last_mx, my - self.last_my)
            if cursor_speed > self.cfg["SIT_BREAKAWAY_SPEED"] or self.sit_timer <= 0:
                self.state = STATE_IDLE
                self.idle_sub_state = IDLE_SUB_LOOK
                self.idle_timer = random.randint(800, 1600)
            else:
                self.x = float(tx)
                self.y = float(ty)
                self.clamp_position()
        elif self.state == STATE_AVOID:
            self.avoid_timer -= self.dt
            spd = self.cfg["BASE_SPEED"] * self.cfg["AVOID_SPEED_MULT"] * self.k
            self.x += self.avoid_dir_x * spd
            self.y += self.avoid_dir_y * spd
            self._face(self.avoid_dir_x, self.avoid_dir_y)
            self.clamp_position()
            if self.avoid_timer <= 0:
                self.state = STATE_IDLE
                self.idle_sub_state = IDLE_SUB_LOOK
                self.idle_timer = random.randint(700, 1400)

    def _check_mouse_nearby(self, mx: int, my: int) -> None:
        if self.state in (STATE_SLEEP, STATE_PET, STATE_SCRATCH, STATE_AVOID,
                          STATE_SIT_ON_CURSOR, STATE_SIT_APPROACH, STATE_SPIN_ACTION,
                          STATE_PLAY, STATE_FLUNG) or self.is_dragging:
            self.is_chase_mode = False
            return
        if not self.cfg["MULTICAT_CHASE_ENABLE"]:
            self.is_chase_mode = False
            return
        if self.catch_cooldown > 0:
            self.catch_cooldown = max(0.0, self.catch_cooldown - self.dt)

        dist = math.hypot(mx - self.x, my - self.y)
        ratio = self.chase_interest / max(1, self.cfg["INTEREST_MAX"])
        trigger = self.cfg["CHASE_TRIGGER_DIST"] + ratio * self.cfg["CHASE_TRIGGER_BOOST_MAX"]
        # 鼠标猛地从身边划过时，猫会更想追（有上限，不会无限涨）
        vel_gain = min(self.mouse_vel / 1200.0, 1.0) * self.cfg["CHASE_MOUSE_VEL_TRIGGER_GAIN"]
        trigger *= 1.0 + vel_gain
        if dist < self.cfg["ROAM_TRIGGER_DIST"] and self.mouse_vel > 400:
            self.chase_interest = min(
                float(self.cfg["INTEREST_MAX"]),
                self.chase_interest + self.cfg["CHASE_MOUSE_VEL_INTEREST_GAIN"] * self.k)
        exit_dist = trigger + self.cfg["CHASE_HYSTERESIS_GAP"]
        if self.energy <= self.cfg["ENERGY_TIRED_THRESHOLD"]:
            self.is_chase_mode = False
            return
        if not self.is_chase_mode and dist < trigger:
            self.is_chase_mode = True
            self.state = STATE_WALK
            self.chase_sub_mode = self._select_chase_sub()
            self.chase_mode_timer = random.randint(self.cfg["CHASE_MODE_HOLD_MIN"],
                                                   self.cfg["CHASE_MODE_HOLD_MAX"])
            if self.chase_sub_mode == CHASE_SUB_POUNCE:
                self.pounce_timer = float(self.cfg["CHASE_MODE_POUNCE_DURATION"])
        elif self.is_chase_mode and dist > exit_dist:
            # 追不到就盯着看一会儿，而不是直接转头走开
            self.is_chase_mode = False
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_LOOK
            self.idle_timer = random.randint(500, 1100)
        elif (self.is_chase_mode
              and self.chase_interest < self.cfg["CHASE_BORED_INTEREST"]
              and self.mouse_still > self.cfg["CHASE_BORED_STILL_MS"]):
            # 鼠标一直不动、兴趣也没了，就别死盯着了
            self.is_chase_mode = False
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_STATIC
            self.idle_timer = self._rand_idle()
            self._pick_dest()

    def _select_chase_sub(self) -> str:
        # 刚抓到过 / 有点累，才会矜持地保持距离
        if self.catch_cooldown > 0 or self.energy < self.cfg["ENERGY_TIRED_THRESHOLD"] * 1.8:
            return CHASE_SUB_SHY
        interest = self.chase_interest
        if interest >= self.cfg["CHASE_MODE_POUNCE_TRIGGER_INTEREST"]:
            roll = random.random()
            return CHASE_SUB_POUNCE if roll < 0.35 else (CHASE_SUB_NORMAL if roll < 0.65 else CHASE_SUB_FOLLOW)
        if interest >= 35:
            return CHASE_SUB_NORMAL if random.random() < 0.5 else CHASE_SUB_FOLLOW
        return CHASE_SUB_SHY

    def _on_catch(self) -> None:
        """追到光标跟前，撒欢一下。"""
        self.catch_cooldown = float(self.cfg["CHASE_CATCH_COOLDOWN"])
        self.catch_count += 1
        self.chase_interest = min(self.chase_interest,
                                  float(self.cfg["INTEREST_MAX"]) * 0.55)
        self.chase_mode_timer = 0.0
        if self.bank.play:
            self.state = STATE_PLAY
            self.play_timer = 620.0
        else:
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_STATIC
            self.idle_timer = 600
        self.say("抓到啦")

    def _update_state_timers(self) -> None:
        if self.state == STATE_PET and self.stun_timer > 0:
            self.stun_timer -= self.dt
            if self.stun_timer <= 0:
                self.stun_timer = 0.0
                self.state = STATE_IDLE
                self.idle_sub_state = IDLE_SUB_LOOK
                self.idle_timer = self._rand_idle()
        if self.state == STATE_IDLE:
            self._tick_idle()
        elif self.state == STATE_GROOM:
            self.groom_timer -= self.dt
            if self.groom_timer <= 0:
                self.state = STATE_IDLE
                self.idle_sub_state = IDLE_SUB_STATIC
                self.idle_timer = self._rand_idle()
        elif self.state == STATE_SLEEP:
            self.sleep_timer -= self.dt
            if self.sleep_timer <= 0:
                self.state = STATE_IDLE
                self.idle_sub_state = IDLE_SUB_STATIC
                self.idle_timer = self._rand_idle()
        elif self.state == STATE_PLAY:
            self.play_timer -= self.dt
            if self.play_timer <= 0:
                self.state = STATE_IDLE
                self.idle_sub_state = IDLE_SUB_LOOK
                self.idle_timer = random.randint(800, 1600)
        elif self.state == STATE_SCRATCH:
            self.scratch_timer -= self.dt
            if self.scratch_timer <= 0:
                self.state = STATE_WALK
                if not self.is_chase_mode:
                    self._pick_dest()

    def _tick_idle(self) -> None:
        # 发呆时在 awake / mati 之间切换，偶尔换 mati3
        if self.idle_sub_state in (IDLE_SUB_STATIC, IDLE_SUB_LOOK):
            self.idle_static_timer += self.dt
            if self.idle_static_timer >= self.idle_static_swap:
                self.idle_static_timer = 0.0
                self.idle_use_awake = not self.idle_use_awake
                self.idle_static_swap = random.randint(self.cfg["IDLE_STATIC_SWAP_MIN"],
                                                       self.cfg["IDLE_STATIC_SWAP_MAX"])
        self.idle_timer -= self.dt
        if self.idle_timer > 0:
            return

        roll = random.random()
        sleep_bonus = self.cfg["TIRED_SLEEP_BOOST"] if self.energy <= self.cfg["ENERGY_TIRED_THRESHOLD"] else 0.0
        if self.bank.groom and roll < self.cfg["GROOM_CHANCE"]:
            self.state = STATE_GROOM
            self.groom_timer = float(self.cfg["GROOM_DURATION"])
            return
        if self.bank.sleep and roll < self.cfg["GROOM_CHANCE"] + self.cfg["SLEEP_CHANCE"] + sleep_bonus:
            self.state = STATE_SLEEP
            self.sleep_timer = float(self.cfg["SLEEP_DURATION"])
            self.say("zZ")
            return
        if self.bank.play and random.random() < self.cfg["PLAY_CHANCE"]:
            self.state = STATE_PLAY
            self.play_timer = float(self.cfg["PLAY_DURATION"])
            self.say("抓不到我")
            return
        if self.spin_cooldown <= 0 and random.random() < self.cfg["SPIN_ACTION_RANDOM_CHANCE"]:
            self.trigger_spin_action()
            return

        mx, my = get_cursor_pos()
        dist = math.hypot(mx - self.x, my - self.y)
        if dist < 240 and random.random() < self.cfg["SIT_ON_CURSOR_CHANCE"]:
            self.state = STATE_SIT_APPROACH
            return

        self.idle_sub_state = IDLE_SUB_STATIC if random.random() < self.cfg["PROB_IDLE_STATIC"] else IDLE_SUB_LOOK
        self.idle_timer = self._rand_idle()
        self._pick_dest()
        if random.random() < float(self.cfg["IDLE_START_WALK_CHANCE"]):
            self.state = STATE_WALK

    def _pick_dest(self) -> None:
        x0, y0, x1, y1 = self.bounds
        if self.cfg.get("MEANDER_MODE", True):
            md = int(self.cfg["MEANDER_MAX_TARGET_DIST"])
            tx = self.x + random.randint(-md, md)
            ty = self.y + random.randint(-md, md)
        else:
            tx = random.randint(x0, max(x0, x1 - self.pet_w))
            ty = random.randint(y0, max(y0, y1 - self.pet_h))
        self.target_x = float(max(x0, min(tx, x1 - self.pet_w)))
        self.target_y = float(max(y0, min(ty, y1 - self.pet_h)))

    # ---------------- 移动 ----------------
    def _update_physics(self, mx: int, my: int) -> None:
        k = self.k
        if self._avoid_peer_cat():
            return

        if self.is_chase_mode:
            self._erase_dest_marker()
            dist_m = math.hypot(mx - self.x, my - self.y)
            # 子模式有粘性：隔一段时间才重掷，避免每帧乱跳导致走位抽搐
            self.chase_mode_timer -= self.dt
            if self.chase_mode_timer <= 0:
                self.chase_sub_mode = self._select_chase_sub()
                self.chase_mode_timer = random.randint(self.cfg["CHASE_MODE_HOLD_MIN"],
                                                       self.cfg["CHASE_MODE_HOLD_MAX"])
                if self.chase_sub_mode == CHASE_SUB_POUNCE:
                    self.pounce_timer = float(self.cfg["CHASE_MODE_POUNCE_DURATION"])
            # 距离驱动速度：离得越远追得越猛
            ramp = max(1.0, float(self.cfg["CHASE_SPEED_RAMP_DIST"]))
            speed_mult = 1.0 + min(dist_m / ramp, 1.0) * (self.cfg["CHASE_MAX_SPEED_MULT"] - 1.0)
            if self.chase_sub_mode == CHASE_SUB_POUNCE:
                self.pounce_timer -= self.dt
                speed_mult = min(self.cfg["CHASE_MAX_SPEED_MULT"] * 1.2, speed_mult * 1.25)
                self.target_x, self.target_y = float(mx), float(my)
                if self.pounce_timer <= 0:
                    self.chase_sub_mode = CHASE_SUB_NORMAL
            elif self.chase_sub_mode == CHASE_SUB_FOLLOW:
                min_d = self.cfg["CHASE_MODE_FOLLOW_DIST_MIN"]
                max_d = self.cfg["CHASE_MODE_FOLLOW_DIST_MAX"]
                if dist_m > 0.1:
                    if min_d < dist_m < max_d:
                        self.target_x = mx - (mx - self.x) / dist_m * 22
                        self.target_y = my - (my - self.y) / dist_m * 22
                    elif dist_m >= max_d:
                        self.target_x, self.target_y = float(mx), float(my)
                    else:
                        self.target_x = self.x + (mx - self.x) / dist_m * 30
                        self.target_y = self.y + (my - self.y) / dist_m * 30
                speed_mult *= 0.85
            elif self.chase_sub_mode == CHASE_SUB_SHY:
                shy = self.cfg["CHASE_MODE_SHY_BACKOFF_DIST"]
                if 0.1 < dist_m < shy:
                    self.target_x = self.x + (self.x - mx) / dist_m * 45
                    self.target_y = self.y + (self.y - my) / dist_m * 45
                else:
                    self.target_x, self.target_y = float(mx), float(my)
                speed_mult *= 0.7
            else:
                self.target_x += (mx - self.target_x) * self.cfg["CHASE_SMOOTH_FACTOR"]
                self.target_y += (my - self.target_y) * self.cfg["CHASE_SMOOTH_FACTOR"]

            dist = math.hypot(self.target_x - self.x, self.target_y - self.y)
            slow = max(0.05, dist / self.cfg["CHASE_SLOW_DOWN_DIST"]) if dist < self.cfg["CHASE_SLOW_DOWN_DIST"] else 1.0
            # 扑到脚边：贴到光标跟前就“抓住”，短暂撒欢后再追
            if (self.chase_sub_mode != CHASE_SUB_SHY and self.catch_cooldown <= 0
                    and dist_m <= self.cfg["CHASE_CATCH_DIST"]):
                self._on_catch()
                return
        else:
            self._draw_dest_marker()
            slow = 1.0
            speed_mult = 1.0

        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = math.hypot(dx, dy)
        self._face(dx, dy)

        if dist > 2.0:
            base = self.cfg["BASE_SPEED"] + random.uniform(-self.cfg["SPD_VARIATION"], self.cfg["SPD_VARIATION"])
            base = max(self.cfg["CHASE_MIN_SPEED"], min(base, 3.2))
            self.spd_now = base * slow * speed_mult * k
            self.x += dx / dist * self.spd_now
            self.y += dy / dist * self.spd_now
            if not self.is_chase_mode:
                if random.random() < self.cfg["MEANDER_PAUSE_CHANCE"]:
                    if random.random() < 0.45:
                        self.state = STATE_IDLE
                        self.idle_timer = random.randint(500, 1300)
                        self.idle_sub_state = IDLE_SUB_LOOK
                    else:
                        self._pick_dest()
                elif random.random() < self.cfg["WALK_PAUSE_CHANCE"]:
                    self.state = STATE_IDLE
                    self.idle_timer = random.randint(600, 1400)
                    self.idle_sub_state = IDLE_SUB_LOOK
        else:
            self.state = STATE_IDLE
            self.idle_sub_state = IDLE_SUB_STATIC
            self.idle_timer = self._rand_idle()

        self.clamp_position()
        edge = self.edge_direction()
        if edge and random.random() < self.cfg["EDGE_SCRATCH_CHANCE"] * 0.02 * k:
            self.state = STATE_SCRATCH
            self.scratch_timer = float(self.cfg["SCRATCH_DELAY"])

    def _avoid_peer_cat(self) -> bool:
        """返回 True 表示已被别的猫接管目标，本帧跳过常规寻路。"""
        if not self.net or not self.cfg["MULTICAT_CHASE_ENABLE"]:
            return False
        peers = self.net.peers_list()
        if not peers:
            return False
        best, best_d = None, float("inf")
        for ox, oy in peers:
            d = math.hypot(ox - self.x, oy - self.y)
            if d < best_d:
                best_d, best = d, (ox, oy)
        if best is None or best_d > self.cfg["MULTICAT_SEE_DIST"]:
            return False
        ox, oy = best
        if 0.1 < best_d < self.cfg["MULTICAT_FLEE_DIST"]:
            self.target_x = self.x + (self.x - ox) / best_d * 70
            self.target_y = self.y + (self.y - oy) / best_d * 70
            self._face(self.target_x - self.x, self.target_y - self.y)
            return True
        if best_d < self.cfg["MULTICAT_INTEREST_DIST"]:
            if best_d < 35:
                self.state = STATE_IDLE
                self.idle_timer = random.randint(self.cfg["IDLE_TIME_MIN"] // 2,
                                                 self.cfg["IDLE_TIME_MAX"] // 2)
                self.idle_sub_state = IDLE_SUB_STATIC
                self._erase_dest_marker()
                return True
            self.target_x, self.target_y = ox, oy
            self._face(ox - self.x, oy - self.y)
            return True
        return False

    # ---------------- 调试标记 ----------------
    def _draw_dest_marker(self) -> None:
        if not self.cfg.get("SHOW_DEST_MARKER") or self.target_box is not None:
            return
        size = 14
        x1 = (self.pet_w - size) / 2
        y1 = (self.pet_h - size) / 2
        self.target_box = self.canvas.create_rectangle(x1, y1, x1 + size, y1 + size,
                                                       outline="#ff3333", width=1, dash=(3, 3))

    def _erase_dest_marker(self) -> None:
        if self.target_box is not None:
            self.canvas.delete(self.target_box)
            self.target_box = None

    # ---------------- 渲染 ----------------
    def _advance_animation(self) -> None:
        self.anim_tick += self.dt
        interval = max(30.0, float(self.cfg["ANIM_DELAY"]) / max(0.1, self.cfg["ANIM_SPEED_MULT"]))
        if self.anim_tick >= interval:
            self.anim_tick = 0.0
            self.frame_idx = (self.frame_idx + 1) % 32

    def _select_frame(self) -> Optional[ImageTk.PhotoImage]:
        if self.state == STATE_PET:
            return self.bank.special.get("pet") or self._walk_frame()
        if self.state == STATE_SPIN_ACTION:
            return self._walk_frame()
        if self.state in (STATE_IDLE, STATE_SIT_ON_CURSOR, STATE_SIT_APPROACH):
            awake = self.bank.special.get("awake")
            mati = self.bank.special.get("mati")
            if awake and mati:
                return awake if self.idle_use_awake else mati
            return awake or self._walk_frame()
        if self.state == STATE_GROOM and self.bank.groom:
            return self.bank.groom[self.frame_idx % len(self.bank.groom)]
        if self.state == STATE_SLEEP and self.bank.sleep:
            return self.bank.sleep[self.frame_idx % len(self.bank.sleep)]
        if self.state == STATE_PLAY and self.bank.play:
            return self.bank.play[self.frame_idx % len(self.bank.play)]
        if self.state == STATE_SCRATCH:
            edge = self.edge_direction()
            if edge:
                frame = self.bank.togi_frame(edge)
                if frame:
                    return frame
        return self._walk_frame()

    def _walk_frame(self) -> Optional[ImageTk.PhotoImage]:
        frames = self.bank.walk_frames(self.walk_dir)
        if not frames:
            return None
        return frames[self.frame_idx % len(frames)]

    def _render(self) -> None:
        img = self._select_frame()
        if img is not None:
            if self.fallback_rect is not None:
                self.canvas.delete(self.fallback_rect)
                self.fallback_rect = None
            if img is not self._last_img:
                self.canvas.itemconfig(self.image_item, image=img)
                self._last_img = img
                if IS_LINUX:
                    # 换帧就跟着换轮廓，像素猫在 Linux 上也是"一个形状"而不是方块
                    self._apply_shape(self.bank.mask_of(img))
        elif self.fallback_rect is None:
            self.fallback_rect = self.canvas.create_rectangle(
                1, 1, self.pet_w - 2, self.pet_h - 2, fill=self.cfg["FALLBACK_COLOR"])
        pos = (int(round(self.x)), int(round(self.y)))
        if pos != self._last_win_pos:
            self._set_win_pos(*pos)
            self._last_win_pos = pos
        if self.bubble.visible:
            self.bubble.move_with(pos[0], pos[1], self.pet_w)

    # ---------------- 收尾 ----------------
    def shutdown(self) -> None:
        if getattr(self, "_shut", False):
            return
        self._shut = True
        self._alive = False
        if self.mouse_cursor is not None:
            self.mouse_cursor.set_active(False)
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.cfg.get("REMEMBER_POSITION", True):
            self.cfg["LAST_X"] = int(self.x)
            self.cfg["LAST_Y"] = int(self.y)
        self.save()
        log("[Gneko] 退出")
        if self.net:
            self.net.close()
        self.bubble.destroy()
        try:
            self.root.destroy()
        except Exception:
            pass

    def quit(self) -> None:
        self.shutdown()
        raise SystemExit(0)


# ---------------------------------------------------------------- 入口

def main() -> None:
    ensure_std_streams()
    enable_dpi_awareness()
    install_exception_hooks()
    migrate_legacy_names()
    parser = argparse.ArgumentParser(description="Gneko 桌面猫")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径")
    parser.add_argument("--scale", "-s", type=int, default=None, help="临时指定缩放倍数")
    parser.add_argument("--skin", default=None, help="临时指定皮肤（classic 或 skins 下的目录名）")
    parser.add_argument("--list-skins", action="store_true", help="列出所有可用皮肤后退出")
    parser.add_argument("--selftest", type=float, default=0, help="自检运行秒数后自动退出")
    parser.add_argument("--debug", action="store_true", help="打印状态日志")
    parser.add_argument("--restore-cursor", action="store_true",
                        help="只把系统光标恢复成默认箭头，然后退出")
    args = parser.parse_args()

    if args.restore_cursor:
        MouseCursor.restore_system()
        print("系统光标已恢复默认。")
        return

    config_path = Path(args.config) if args.config else default_config_path()
    cfg = load_or_create_config(config_path)

    if args.list_skins:
        names = available_skins(cfg)
        print(f"可用皮肤（{skins_root(cfg)}）：")
        print(f"  classic  原版（黑白）")
        for n in names:
            print(f"  {n:9s}{skin_label(n)}")
        return

    if args.skin:
        cfg["SKIN"] = args.skin
    if args.scale:
        cfg["SCALE"] = args.scale
        cfg["AUTO_SCALE_HIDPI"] = False
    if args.debug:
        cfg["DEBUG_MODE"] = True
    save_config(config_path, cfg)

    print("==== Gneko 桌宠 v2 启动 ====")
    print(f"[Gneko] 配置: {config_path}")
    print(f"[Gneko] 素材: {resolve_asset_dir(cfg)}（皮肤 {cfg.get('SKIN') or SKIN_CLASSIC}）")

    root = tk.Tk()
    setup_fonts()
    root.report_callback_exception = lambda *_: log_exception("tk-callback")
    app = GnekoPet(root, cfg, config_path)
    log(f"[Gneko] 启动：{app.scale}x {app.pet_w}x{app.pet_h} 透明={app.transparent_ok} "
        f"帧={app.bank.count} 位置=({app.x:.0f},{app.y:.0f})")
    print(f"[Gneko] 素材帧 {app.bank.count} 张，缩放 {app.scale}x，"
          f"窗口 {app.pet_w}x{app.pet_h}，透明={'开' if app.transparent_ok else '关'}")

    if args.selftest > 0:
        def _auto_quit():
            print(f"[Selftest] 运行 {args.selftest}s 后退出，末状态={app.state} "
                  f"位置=({app.x:.0f},{app.y:.0f})")
            app.shutdown()
            root.quit()
        root.after(int(args.selftest * 1000), _auto_quit)

    try:
        root.mainloop()
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
