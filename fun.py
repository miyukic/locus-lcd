# -*- coding: utf-8 -*-
import smbus2, time, datetime, subprocess, os, sys

PIDFILE = os.path.expanduser(os.environ.get('LCD_PIDFILE', '~/fun.pid'))
MSGFILE = os.path.expanduser(os.environ.get('LCD_MSGFILE', '~/lcd_msg.txt'))   # 外部からの優先メッセージ。1行目=上段, 2行目=下段
MSG_TTL = 120                        # メッセージ表示の有効秒数（更新から120秒で自動消滅）
WEATHER_LOCATION = os.environ.get('LCD_WEATHER_LOCATION', '').strip()
DB_HOST = os.environ.get('LCD_DB_HOST', '').strip()
DB_USER = os.environ.get('LCD_DB_USER', 'postgres').strip()
DB_NAME = os.environ.get('LCD_DB_NAME', '').strip()

# PID check
if os.path.exists(PIDFILE):
    try:
        with open(PIDFILE) as f:
            old_pid = int(f.read().strip())
        if os.path.exists(f'/proc/{old_pid}'):
            print(f"Already running (PID {old_pid}), exiting.")
            sys.exit(1)
    except (ValueError, IOError):
        pass

with open(PIDFILE, 'w') as f:
    f.write(str(os.getpid()))

import atexit
atexit.register(lambda: os.path.exists(PIDFILE) and os.unlink(PIDFILE))

LCD_ADDR = 0x27
BL = 0x08
EN = 0b00000100
E_PULSE = 0.0005

def lcd_byte(bus, bits, mode):
    high = mode | (bits & 0xF0) | BL
    low  = mode | ((bits << 4) & 0xF0) | BL
    for b in [high, high|EN, high, low, low|EN, low]:
        bus.write_byte(LCD_ADDR, b)
        time.sleep(E_PULSE)

CHARS = [
    [0x1F,0x1F,0x1F,0x1F,0x1F,0x1F,0x1F,0x1F],
    [0x00,0x0A,0x1F,0x1F,0x0E,0x04,0x00,0x00],
    [0x0E,0x1F,0x15,0x1F,0x0E,0x0E,0x00,0x00],
    [0x04,0x0A,0x0A,0x0E,0x0E,0x1F,0x1F,0x0E],
    [0x01,0x03,0x05,0x09,0x0B,0x1B,0x18,0x00],
    [0x11,0x0A,0x04,0x00,0x04,0x0A,0x11,0x00],
    [0x00,0x10,0x18,0x1C,0x18,0x10,0x00,0x00],
    [0x18,0x18,0x18,0x18,0x18,0x18,0x18,0x18],
]

BLOCK = chr(0); HEART = chr(1); SKULL = chr(2)
THERM = chr(3); NOTE  = chr(4); XMARK = chr(5)
ARROW = chr(6); HALF  = chr(7)

def lcd_init_and_chars(bus):
    for cmd in [0x33,0x32,0x06,0x0C,0x28,0x01]:
        lcd_byte(bus, cmd, 0)
    time.sleep(0.005)
    for i, ch in enumerate(CHARS):
        lcd_byte(bus, 0x40 | (i * 8), 0)
        for b in ch:
            lcd_byte(bus, b, 1)
    lcd_byte(bus, 0x80, 0)

def lcd_show(bus, line1, line2):
    lcd_byte(bus, 0x80, 0)
    for c in line1.ljust(16)[:16]: lcd_byte(bus, ord(c), 1)
    lcd_byte(bus, 0xC0, 0)
    for c in line2.ljust(16)[:16]: lcd_byte(bus, ord(c), 1)

def get_message():
    """外部メッセージを返す (line1, line2)。無効/期限切れなら None。"""
    try:
        if os.path.exists(MSGFILE):
            if time.time() - os.path.getmtime(MSGFILE) > MSG_TTL:
                return None
            with open(MSGFILE) as f:
                lines = f.read().rstrip('\n').split('\n')
            l1 = lines[0][:16] if len(lines) > 0 else ''
            l2 = lines[1][:16] if len(lines) > 1 else ''
            if l1 == '' and l2 == '':
                return None
            return (l1, l2)
    except:
        pass
    return None

def get_cpu_temp():
    try:
        with open('/sys/devices/virtual/thermal/thermal_zone0/temp') as f:
            return int(f.read()) // 1000
    except:
        return -1

def get_mem_percent():
    try:
        r = subprocess.run(['free','-m'], capture_output=True, text=True)
        for line in r.stdout.split('\n'):
            if line.startswith('Mem:'):
                p = line.split(); return int(int(p[2])*100//int(p[1]))
    except: pass
    return -1

def get_uptime():
    try:
        with open('/proc/uptime') as f:
            s = float(f.read().split()[0])
        d,h,m = int(s//86400), int(s%86400//3600), int(s%3600//60)
        return f"{d}d {h:02d}:{m:02d}"
    except: return "???"

_weather_cache = (None, 0)

def get_weather():
    global _weather_cache
    if not WEATHER_LOCATION:
        return None
    now = time.time()
    if _weather_cache[0] is not None and now - _weather_cache[1] < 300:
        return _weather_cache[0]
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '4', f'wttr.in/{WEATHER_LOCATION}?format=%t|%C'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=5
        )
        parts = r.stdout.strip().split('|')
        temp = parts[0].replace('\xb0', '').strip() if parts else 'N/A'
        cond = parts[1].strip().upper()[:16] if len(parts) > 1 else 'N/A'
        result = (temp, cond)
        _weather_cache = (result, now)
        return result
    except:
        return _weather_cache[0] or ('N/A', 'N/A')

_weight_cache = (None, 0)

def get_weight_latest():
    """Return (weight_kg_str, 'MM/DD') latest from weight_logs."""
    global _weight_cache
    if not (DB_HOST and DB_NAME):
        return None
    now = time.time()
    if _weight_cache[0] is not None and now - _weight_cache[1] < 60:
        return _weight_cache[0]
    try:
        sql = "SELECT weight_kg::text, to_char(logged_at AT TIME ZONE 'Asia/Tokyo','MM/DD') FROM weight_logs ORDER BY logged_at DESC LIMIT 1"
        env = os.environ.copy()
        env['PGCONNECT_TIMEOUT'] = '3'
        r = subprocess.run(
            ['psql', '-h', DB_HOST, '-U', DB_USER, '-d', DB_NAME, '-tA', '-c', sql],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=5, universal_newlines=True
        )
        if r.returncode == 0:
            parts = r.stdout.strip().split('|')
            if len(parts) == 2:
                result = (parts[0], parts[1])
                _weight_cache = (result, now)
                return result
    except Exception as e:
        print(f"weight err: {e}")
    return _weight_cache[0]

_cal_cache = (None, 0)

def get_cal_today():
    """Return (total_kcal, count) for today. password via ~/.pgpass."""
    global _cal_cache
    if not (DB_HOST and DB_NAME):
        return None
    now = time.time()
    if _cal_cache[0] is not None and now - _cal_cache[1] < 60:
        return _cal_cache[0]
    try:
        sql = "SELECT COALESCE(SUM(estimated_kcal),0)::int, COUNT(*) FROM calorie_logs WHERE eaten_at::date = CURRENT_DATE"
        env = os.environ.copy()
        env['PGCONNECT_TIMEOUT'] = '3'
        r = subprocess.run(
            ['psql', '-h', DB_HOST, '-U', DB_USER, '-d', DB_NAME, '-tA', '-c', sql],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=5, universal_newlines=True
        )
        if r.returncode == 0:
            parts = r.stdout.strip().split('|')
            if len(parts) == 2:
                result = (int(parts[0]), int(parts[1]))
                _cal_cache = (result, now)
                return result
    except Exception as e:
        print(f"cal err: {e}")
    return _cal_cache[0]

# ---- BOOT ----
bus = smbus2.SMBus(1)
lcd_init_and_chars(bus)
print(f"fun.py start PID={os.getpid()}")

lcd_show(bus, "LOCUS CORP v1.0 ", "[              ]")
time.sleep(0.4)
for i in range(1, 13):
    bar = BLOCK * i + " " * (12 - i)
    pct = int(i * 100 / 12)
    lcd_show(bus, "LOCUS CORP v1.0 ", f"[{bar}]{pct:3d}%")
    time.sleep(0.12)
time.sleep(0.5)
lcd_show(bus, f"{HEART} SYSTEM ONLINE {HEART}", f"  LOCUS LAB SV1 ")
time.sleep(2.5)

# ---- メインループ ----
QUOTES = [
    # --- classic ---
    ("WAKE UP, NEO... ", f"THE MATRIX{SKULL}HAS U"),
    (f"{NOTE}SUDO MAKE ME A ", f"  SANDWICH{NOTE}     "),
    ("HELLO,COMPUTER  ", "COMPUTER: HELLO "),
    ("I AM  INEVITABLE", f"{SKULL}  JARVIS{SKULL} LOL  "),
    ("ACCESSING LOCUS ", "DATABASE...OK   "),
    (f"{HEART}LAB NODE ONLINE{HEART}", "SYSTEMS  READY "),
    ("KA! KA! KA!     ", f"{SKULL}YAMETE KUDASAI "),
    ("LOCUS VIDEO STU", "DIO  RECORDING "),
    # --- 2026-05-21 fresh ---
    ("HOT TIME DAY 21 ", f"EXP UP {ARROW}HUNT NOW"),
    ("FFMPEG  97% DONE", "  G:DRIVE  CLEAN"),
    ("TIMESTAMPTZ FIX ", f"+09:00 JST{HEART}OK   "),
    (f"{HEART}HUMAN + AI     ", "= LOCUS SYSTEM  "),
    ("IMPORTANT TXT   ", f"  GUARD: {NOTE}ARMED{NOTE}"),
    ("CODEX MEETS CC  ", " RESCUE PROTOCOL"),
    ("ZUNDAMON  PREPS ", "    EP.2 SCRIPT "),
    ("SPRING MODE     ", " LAB  HARU READY"),
    ("LOCUSLAB  BUILT ", " BRICK BY BRICK "),
    (f"OPEN SOURCE {ARROW}OR", " DIE TRYING.    "),
    # --- 2026-05-23 fresh ---
    ("DISCORD WEIGHT  ", f"AUTO LOGGED OK{HEART} "),
    ("N8N WF2 REVIVED ", " FROM THE DEAD  "),
    ("WEIGHT_LOGS LIVE", " UNIQUE  ARMED  "),
    (f"CENTURY {ARROW}HATCH ", " SEDAN COSPLAY  "),
    ("ROLEX X RIOT GMS", " 30YR LATER...  "),
    (f"L: REMOUNTED {HEART}  ", " WORK2 ALIVE    "),
]
q_idx = 0
SPIN = "|/-\\"

prev_phase = -1
last_init  = time.time()

while True:
    try:
        now   = datetime.datetime.now()

        # 優先メッセージ: lcd_msg.txt があればローテーションより優先表示
        msg = get_message()
        if msg is not None:
            lcd_show(bus, msg[0].ljust(16), msg[1].ljust(16))
            if (time.time() - last_init) >= 300:
                lcd_init_and_chars(bus)
                last_init = time.time()
            time.sleep(1)
            continue

        temp  = get_cpu_temp()
        mem   = get_mem_percent()
        up    = get_uptime()
        phase = (int(time.time()) // 8) % 7
        phase_changed = (phase != prev_phase)
        if phase_changed and phase == 3:
            q_idx += 1
        prev_phase = phase

        if (time.time() - last_init) >= 300:
            lcd_init_and_chars(bus)
            last_init = time.time()

        if phase == 0:
            lcd_show(bus,
                now.strftime("%Y/%m/%d %a  "),
                now.strftime("%H:%M:%S") + f"  {HEART}     ")
        elif phase == 1:
            t_str = f"{temp}C" if temp >= 0 else "--"
            m_str = f"{mem}%" if mem >= 0 else "--"
            lcd_show(bus,
                f"{THERM}{t_str} MEM:{m_str}      ",
                f"UP: {up}        ")
        elif phase == 2:
            weather = get_weather()
            if weather:
                w_temp, w_cond = weather
                lcd_show(bus,
                    f"WEATHER {w_temp}     "[:16],
                    w_cond[:16].ljust(16))
            else:
                lcd_show(bus,
                    "WEATHER         ",
                    f"  NO CONFIG{XMARK}    ")
        elif phase == 3:
            q = QUOTES[q_idx % len(QUOTES)]
            lcd_show(bus, q[0], q[1])
        elif phase == 4:
            sp = SPIN[int(time.time() * 2) % 4]
            lcd_show(bus,
                f"LOCUS LAB  {sp}    ",
                f"{BLOCK*3} ONLINE {BLOCK*3}  ")
        elif phase == 5:
            cal = get_cal_today()
            if cal and cal[0] is not None:
                total, cnt = cal
                line1 = f"TODAY {total} KCAL"
                line2 = f"  {cnt} MEALS{HEART}"
            else:
                line1 = "TODAY  --- KCAL "
                line2 = f"  DB OFFLINE{XMARK}  "
            lcd_show(bus, line1, line2)
        elif phase == 6:
            w = get_weight_latest()
            if w and w[0] is not None:
                wkg, wdate = w
                line1 = f"WEIGHT {wkg} KG"[:16]
                line2 = f"  {wdate}{HEART} LOG OK "[:16]
            else:
                line1 = "WEIGHT  -- KG   "
                line2 = f"  NO DATA{XMARK}     "
            lcd_show(bus, line1, line2)

        time.sleep(1)
    except Exception as e:
        print(f"Err: {e}")
        try:
            try: bus.close()
            except: pass
            bus = smbus2.SMBus(1)
            lcd_init_and_chars(bus)
            last_init = time.time()
        except: pass
        time.sleep(2)
