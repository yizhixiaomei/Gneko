#!/usr/bin/env sh
# 卸掉 linux/install.sh 装的东西（不删仓库源码，也不删你的配置）
set -eu

BIN="${HOME}/.local/bin/gneko"
DESKTOP="${HOME}/.local/share/applications/gneko.desktop"
AUTOSTART="${HOME}/.config/autostart/gneko.desktop"

# 先把还开着的猫关掉，否则文件被占用也无所谓，但会留个孤儿进程
pkill -f "Gneko.py" 2>/dev/null || true

for f in "$BIN" "$DESKTOP" "$AUTOSTART"; do
    if [ -e "$f" ]; then
        rm -f "$f"
        printf '[Gneko] 已删除 %s\n' "$f"
    fi
done

cat <<'EOF'
[Gneko] 卸载完成。
配置文件还留着：
  ~/.config/gneko/Gneko_config.json
  ~/.local/state/gneko/Gneko.log
想彻底清掉就手动删这两个目录。
EOF
