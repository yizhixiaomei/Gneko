#!/usr/bin/env sh
# Gneko Linux 一键安装：依赖检查 + 启动器 + 桌面菜单项 + 可选开机自启
#   ./linux/install.sh              装到 ~/.local（当前用户）
#   ./linux/install.sh --autostart  同时写进登录自启
set -eu

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
APP_DIR=$(cd "$SELF_DIR/.." && pwd)
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${HOME}/.local/share/applications"
AUTOSTART_DIR="${HOME}/.config/autostart"
AUTOSTART=0

for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}/  /'; exit 0 ;;
        *) echo "未知参数: $arg" >&2; exit 1 ;;
    esac
done

say()  { printf '\033[1;36m[Gneko]\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[Gneko]\033[0m %s\n' "$1"; }

PY=python3
command -v "$PY" >/dev/null 2>&1 || { warn "没有 python3，先装：sudo apt install python3"; exit 1; }

# 1. 依赖检查（tkinter / Pillow）
DEPS=$("$PY" -c "
mods = []
for m in ('tkinter', 'PIL'):
    try:
        __import__(m)
    except Exception:
        mods.append(m)
print(','.join(mods))
" 2>/dev/null || echo "tkinter,PIL")

if [ -n "$DEPS" ]; then
    warn "缺依赖：$DEPS"
    echo "       Debian/Ubuntu： sudo apt install python3-tk python3-pil"
    echo "       Fedora：        sudo dnf install python3-tkinter python3-pillow"
    echo "       Arch：          sudo pacman -S tk python-pillow"
    exit 1
fi
say "依赖检查通过"

# 2. 中文字体（只提示，不阻塞）
FONT=$("$PY" -c "
import tkinter, tkinter.font
r = tkinter.Tk()
try:
    fams = set(tkinter.font.families())
    want = ('Noto Sans CJK SC', 'Noto Sans SC', 'Source Han Sans SC', 'WenQuanYi Micro Hei')
    print('ok' if any(f in fams for f in want) else 'none')
finally:
    r.destroy()
" 2>/dev/null || echo none)
if [ "$FONT" != "ok" ]; then
    warn "没找到中文字体，菜单可能显示方块：sudo apt install fonts-noto-cjk"
fi

# 3. 装启动器
mkdir -p "$BIN_DIR"
install -m 755 "$SELF_DIR/gneko" "$BIN_DIR/gneko"
say "启动器 -> $BIN_DIR/gneko"

# 4. 菜单项
mkdir -p "$DESKTOP_DIR"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@BIN@|$BIN_DIR/gneko|g" \
    "$SELF_DIR/gneko.desktop" > "$DESKTOP_DIR/gneko.desktop"
say "菜单项 -> $DESKTOP_DIR/gneko.desktop（应用列表里搜 Gneko）"

# 5. 登录自启（可选）
if [ "$AUTOSTART" = "1" ]; then
    mkdir -p "$AUTOSTART_DIR"
    cp "$DESKTOP_DIR/gneko.desktop" "$AUTOSTART_DIR/gneko.desktop"
    say "已加入登录自启 -> $AUTOSTART_DIR/gneko.desktop"
fi

cat <<EOF

装好了。常用命令：
  gneko                    前台运行（有报错直接看得到）
  gneko --skin mint        换皮肤
  gneko --list-skins       列出所有皮肤
  gneko --selftest 5       跑 5 秒自检后自动退出

配置与日志（XDG 规范）：
  \${XDG_CONFIG_HOME:-\$HOME/.config}/gneko/Gneko_config.json
  \${XDG_STATE_HOME:-\$HOME/.local/state}/gneko/Gneko.log

退出：右键菜单「退出」，或直接按 Esc（全局读键，不用先切窗口）。
EOF

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "PATH 里还没有 $BIN_DIR，把它加进 ~/.profile 或直接用绝对路径" ;;
esac
