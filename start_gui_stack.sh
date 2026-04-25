#!/bin/bash
# start_gui_stack.sh — boot Xvfb + fluxbox + x11vnc + noVNC on DISPLAY :1.
# Called once by job_server.sh at container startup. All processes are
# daemonised; if one dies we let the container fail its health check.
set -u

DISPLAY_NUM="${DISPLAY:-:1}"
VNC_PORT="${VNC_PORT:-5901}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
RESOLUTION="${RESOLUTION:-1680x1050x24}"
GUI_LOG_DIR="/shared/gui_logs"

mkdir -p "$GUI_LOG_DIR"

if pgrep -x Xvfb >/dev/null 2>&1; then
    echo "[gui] Xvfb already running"
    exit 0
fi

echo "[gui] starting Xvfb on $DISPLAY_NUM at $RESOLUTION"
Xvfb "$DISPLAY_NUM" -screen 0 "$RESOLUTION" -ac +extension GLX +render -noreset \
    >"$GUI_LOG_DIR/xvfb.log" 2>&1 &

# Wait for X to come up
for _ in 1 2 3 4 5 6 7 8; do
    if DISPLAY="$DISPLAY_NUM" xdpyinfo >/dev/null 2>&1; then break; fi
    sleep 0.5
done

echo "[gui] starting fluxbox"
DISPLAY="$DISPLAY_NUM" fluxbox >"$GUI_LOG_DIR/fluxbox.log" 2>&1 &

echo "[gui] starting x11vnc on $VNC_PORT"
x11vnc -display "$DISPLAY_NUM" -forever -shared -nopw -rfbport "$VNC_PORT" \
    -quiet -bg -o "$GUI_LOG_DIR/x11vnc.log"

echo "[gui] starting noVNC (websockify) on $NOVNC_PORT → $VNC_PORT"
websockify --web=/usr/share/novnc "$NOVNC_PORT" "localhost:$VNC_PORT" \
    >"$GUI_LOG_DIR/novnc.log" 2>&1 &

echo "[gui] GUI stack started"
