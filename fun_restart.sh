#!/bin/bash
set -a
[ -f "$HOME/.config/locus-lcd/env" ] && . "$HOME/.config/locus-lcd/env"
set +a
kill -9 $(pgrep -f fun.py) 2>/dev/null || true
rm -f "${LCD_PIDFILE:-$HOME/fun.pid}"
sleep 2
nohup python3 "$HOME/source1/locus-lcd/fun.py" > "$HOME/source1/locus-lcd/fun.log" 2>&1 &
echo done
