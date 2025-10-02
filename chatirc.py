#!/usr/bin/env python3
"""ChatIRC - IRC-style CLI ChatGPT client

Features:
- Per-room conversations with persistent history
- Automatic OpenAI SDK detection (new vs legacy)
- Configurable via ~/.chatircrc
- Save/load chat logs with metadata
- ANSI color output
- Readline completion for slash commands
"""

from __future__ import annotations
import os
import json
import re
import glob
import importlib
import importlib.util
from importlib import metadata as importlib_metadata
from datetime import datetime
from typing import List, Dict, Optional
import readline
import atexit
import time
import curses
import signal
import textwrap
import webbrowser

# package version
__version__ = "0.1.0"
import threading
import queue
try:
    from wcwidth import wcswidth as _wcswidth, wcwidth as _wcwidth
except Exception:
    _wcswidth = None
    _wcwidth = None


def _display_width(s: str) -> int:
    """Return the terminal column width of a string, using wcwidth if available."""
    if s is None:
        return 0
    if _wcswidth:
        try:
            val = _wcswidth(s)
            if val >= 0:
                return val
        except Exception:
            pass
    # fallback: approximate by character count
    return len(s)


def _slice_to_display_width(s: str, maxw: int) -> str:
    """Return the longest prefix of s whose display width is <= maxw."""
    if not s or maxw <= 0:
        return ''
    if _wcwidth:
        acc = 0
        out_chars = []
        for ch in s:
            try:
                w = _wcwidth(ch)
            except Exception:
                w = 1
            if w < 0:
                w = 0
            if acc + w > maxw:
                break
            out_chars.append(ch)
            acc += w
        return ''.join(out_chars)
    # fallback simple slice
    return s[:maxw]

# ANSI colors
RESET = "\033[0m"
TIME_COLOR = "\033[90m"  # gray
SYS_COLOR = "\033[95m"   # magenta
BOT_COLOR = "\033[92m"   # green
USER_COLOR = "\033[94m"  # blue

# Regex for stripping ANSI
ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# Slash commands
SLASH_COMMANDS = ["/quit", "/clear", "/save", "/load", "/topic", "/help", "/room", "/rooms", "/nick", "/saveconfig"]

# Defaults
MAX_HISTORY = int(os.environ.get("CHATIRC_MAX_HISTORY", "20"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")


def human_system(msg: str) -> str:
    return f"{TIME_COLOR}[{datetime.now().strftime('%H:%M')}] {SYS_COLOR}* {msg}{RESET}"


class Room:
    def __init__(self, name: str, max_history: int = MAX_HISTORY):
        self.name = name
        self.topic = "Welcome to #chatgpt — type /help for commands"
        self.chat_log: List[str] = []
        self.max_history = max_history
        self.messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": "You are a helpful assistant speaking in short IRC-style lines. Keep replies concise and friendly.",
            }
        ]

    def append_print(self, line: str):
        self.chat_log.append(line)

    def append_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_history:
            # keep any system messages then the last (max_history-1) messages
            systems = [m for m in self.messages if m.get("role") == "system"]
            self.messages = systems + self.messages[-(self.max_history - len(systems)) :]


class ChatIRC:
    def __init__(self):
        # load API key from file or env
        api_key = None
        # prefer per-user config under ~/.chatirc/openapi_key, then project file, then env
        try:
            user_key_path = os.path.expanduser("~/.chatirc/openapi_key")
            if os.path.exists(user_key_path):
                with open(user_key_path, "r", encoding="utf-8") as f:
                    api_key = f.read().strip()
            else:
                # fallback to project-local file
                if os.path.exists("openapi_key"):
                    with open("openapi_key", "r", encoding="utf-8") as f:
                        api_key = f.read().strip()
                else:
                    api_key = os.environ.get("OPENAI_API_KEY")
        except Exception:
            api_key = os.environ.get("OPENAI_API_KEY")

        # load config
        self.config_path = os.path.expanduser("~/.chatircrc")
        self.config: Dict[str, object] = {}
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as cf:
                    self.config = json.load(cf)
        except Exception:
            self.config = {}

        self.max_history = int(str(self.config.get("max_history", MAX_HISTORY)))
        global MODEL
        MODEL = str(self.config.get("model", MODEL))
        self.nick = str(self.config.get("nick", "You"))
        self.theme = str(self.config.get("theme", "classic"))
        # how many input lines to show at most (can be tuned in ~/.chatircrc)
        try:
            self.input_max_lines = int(str(self.config.get("input_max_lines", 3)))
        except Exception:
            self.input_max_lines = 3

        # detect and configure OpenAI client
        self.client = None
        self.api_style = "none"
        self.detected_openai_version = None
        # redraw control
        self._dirty = True
        self.input_dirty = True
        try:
            spec = importlib.util.find_spec("openai")
            if spec:
                openai_mod = importlib.import_module("openai")
                # new-style: openai.OpenAI
                if hasattr(openai_mod, "OpenAI"):
                    try:
                        if api_key:
                            self.client = openai_mod.OpenAI(api_key=api_key)
                        else:
                            self.client = openai_mod.OpenAI()
                        self.api_style = "openai_new"
                    except Exception:
                        # fall back to leaving client None but mark style
                        self.client = None
                        self.api_style = "openai_new"
                else:
                    # legacy module usage
                    self.client = openai_mod
                    self.api_style = "openai_legacy"
                try:
                    self.detected_openai_version = importlib_metadata.version("openai")
                except Exception:
                    self.detected_openai_version = None
        except Exception:
            self.client = None
            self.api_style = "none"

        # rooms
        self.rooms: Dict[str, Room] = {}
        self.current_room = self._ensure_room("main")
        self.mode = "compact"
        # input history for readline-like navigation
        self.input_history: List[str] = []
        self._history_index: Optional[int] = None
        # history file
        self.history_path = os.path.expanduser("~/.chatirchistory")
        try:
            if os.path.exists(self.history_path):
                with open(self.history_path, "r", encoding="utf-8") as hf:
                    lines = [ln.rstrip('\n') for ln in hf.readlines() if ln.strip()]
                    self.input_history = lines[-200:]
        except Exception:
            pass

        # async API handling: a queue for results and a simple inflight flag
        self._api_queue: "queue.Queue[tuple]" = queue.Queue()
        self._api_inflight = False
        self._spinner_pos = 0
        self._spinner_states = ['|', '/', '-', '\\']

    def _ensure_room(self, name: str) -> Room:
        if name in self.rooms:
            return self.rooms[name]
        r = Room(name, max_history=self.max_history)
        self.rooms[name] = r
        return r

    def print_banner(self):
        print(f"{BOT_COLOR}=== CLI ChatGPT (IRC-style) ==={RESET}")
        print(human_system(f"Topic: {self.current_room.topic}"))
        print(human_system("Type 'exit' or use /quit to leave."))

    def strip_ansi(self, s: str) -> str:
        return ANSI_RE.sub("", s)

    def list_rooms(self) -> List[str]:
        files = sorted(glob.glob("chatlog-*.txt"))
        return list(self.rooms.keys()) + files

    def save_room(self, filename: Optional[str] = None) -> str:
        if not filename:
            filename = f"chatlog-{self.current_room.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        if os.path.exists(filename):
            base, ext = os.path.splitext(filename)
            filename = f"{base}-{int(time.time())}{ext}"
        cleaned = "\n".join(self.strip_ansi(line) for line in self.current_room.chat_log)
        meta = {
            "room": self.current_room.name,
            "topic": self.current_room.topic,
            "messages": self.current_room.messages,
            "saved_at": datetime.now().isoformat(),
        }
        with open(filename, "w", encoding="utf-8") as f:
            f.write("##CHATIRC-V1\n")
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            f.write("---\n")
            f.write(cleaned)
        return filename

    def load_room_from_file(self, filename: str) -> Room:
        if not os.path.exists(filename):
            raise FileNotFoundError(filename)
        with open(filename, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        room_name = os.path.splitext(os.path.basename(filename))[0]
        r = self._ensure_room(room_name)
        if len(lines) >= 3 and lines[0] == "##CHATIRC-V1" and lines[2] == "---":
            try:
                meta = json.loads(lines[1])
                r.topic = meta.get("topic", r.topic)
                r.messages = meta.get("messages", r.messages)
                r.chat_log.extend(lines[3:])
                return r
            except Exception:
                pass
        r.chat_log.extend(lines)
        return r

    def format_timestamp(self) -> str:
        return f"{TIME_COLOR}[{datetime.now().strftime('%H:%M')}] {RESET}"

    def log_and_print(self, text: str, color: str = BOT_COLOR, nick: str = "Chat"):
        entry = f"{self.format_timestamp()}{color}{nick}> {text}{RESET}"
        print(entry)
        self.current_room.append_print(entry)

    def log_system(self, text: str):
        line = human_system(text)
        print(line)
        self.current_room.append_print(line)

    def run_api_call(self, payload_messages: List[Dict[str, str]]):
        # Keep a synchronous API call path for non-UI usage
        if not self.client:
            raise RuntimeError("OpenAI client not configured (missing API key or library)")
        last_exc = None
        for attempt in range(3):
            try:
                if self.api_style == "openai_new":
                    resp = self.client.chat.completions.create(model=MODEL, messages=payload_messages)
                elif self.api_style == "openai_legacy":
                    resp = self.client.ChatCompletion.create(model=MODEL, messages=payload_messages)
                else:
                    raise RuntimeError("No supported OpenAI client available")
                return resp
            except Exception as e:
                last_exc = e
                time.sleep(1 + attempt * 2)
        if last_exc:
            raise last_exc
        raise RuntimeError("API call failed")

    def _run_api_call_thread(self, payload_messages: List[Dict[str, str]], user_input: str):
        """Worker thread target: run the API call and put (user_input, success, payload) into queue."""
        try:
            resp = self.run_api_call(payload_messages)
            reply = self._extract_reply_from_response(resp)
            self._api_queue.put((user_input, True, reply))
        except Exception as e:
            self._api_queue.put((user_input, False, str(e)))
        finally:
            self._api_inflight = False

    def start_api_call(self, payload_messages: List[Dict[str, str]], user_input: str):
        """Start background API call if none in flight; returns True if started."""
        if self._api_inflight:
            return False
        self._api_inflight = True
        t = threading.Thread(target=self._run_api_call_thread, args=(payload_messages, user_input), daemon=True)
        t.start()
        return True

    def _extract_reply_from_response(self, resp) -> str:
        # Try several shapes to extract assistant content robustly
        try:
            return resp.choices[0].message.content.strip()
        except Exception:
            pass
        try:
            return resp["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
        try:
            return resp.choices[0].text.strip()
        except Exception:
            pass
        try:
            return resp["choices"][0]["text"].strip()
        except Exception:
            pass
        raise RuntimeError("Could not extract reply from API response")

    def _init_curses_colors(self, stdscr):
        """Initialize curses color pairs based on current theme."""
        curses.start_color()
        curses.use_default_colors()
        try:
            if self.theme == "classic":
                curses.init_pair(1, curses.COLOR_RED, -1)
                curses.init_pair(2, curses.COLOR_GREEN, -1)
                curses.init_pair(3, curses.COLOR_BLUE, -1)
            elif self.theme == "neon":
                curses.init_pair(1, curses.COLOR_MAGENTA, -1)
                curses.init_pair(2, curses.COLOR_CYAN, -1)
                curses.init_pair(3, curses.COLOR_YELLOW, -1)
            elif self.theme == "mono":
                curses.init_pair(1, curses.COLOR_WHITE, -1)
                curses.init_pair(2, curses.COLOR_WHITE, -1)
                curses.init_pair(3, curses.COLOR_WHITE, -1)
            elif self.theme == "glow":
                curses.init_pair(1, curses.COLOR_BLUE, -1)
                curses.init_pair(2, curses.COLOR_YELLOW, -1)
                curses.init_pair(3, curses.COLOR_CYAN, -1)
                try:
                    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLUE)
                except Exception:
                    curses.init_pair(4, curses.COLOR_YELLOW, -1)
            else:
                curses.init_pair(1, curses.COLOR_RED, -1)
                curses.init_pair(2, curses.COLOR_GREEN, -1)
                curses.init_pair(3, curses.COLOR_BLUE, -1)
        except Exception:
            # If terminal doesn't support colors, ignore failures
            pass

    def get_completions(self, token: str) -> List[str]:
        """Return completion candidates for a token (slash commands or room names)."""
        if not token:
            return []
        if token.startswith('/'):
            return [c for c in SLASH_COMMANDS if c.startswith(token)]
        else:
            return [r for r in self.rooms.keys() if r.startswith(token)]

    def save_history_to_file(self):
        try:
            dirname = os.path.dirname(self.history_path)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
            # atomic write: write to temp then rename
            tmp = self.history_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as hf:
                for ln in self.input_history[-200:]:
                    hf.write(ln.replace('\n', ' ') + '\n')
            try:
                os.replace(tmp, self.history_path)
            except Exception:
                # fallback
                os.rename(tmp, self.history_path)
        except Exception:
            pass

    def _show_completion_popup(self, stdscr, candidates: List[str], w: int, h: int) -> Optional[str]:
        """Popup a small selection window for completions; return the chosen string or None if cancelled."""
        try:
            maxw = min(max(len(c) for c in candidates) + 2, w // 2)
            maxh = min(len(candidates), h - 6)
            # place the popup centered in lower half
            popup_y = max(1, h - maxh - 4)
            popup_x = max(1, (w - maxw) // 2)
            popup = stdscr.derwin(maxh + 2, maxw + 2, popup_y, popup_x)
            popup.box()
            idx = 0
            while True:
                for i in range(maxh):
                    try:
                        popup.addstr(1 + i, 1, ' ' * maxw)
                    except curses.error:
                        pass
                for i, cand in enumerate(candidates[:maxh]):
                    try:
                        if i == idx:
                            popup.attron(curses.A_REVERSE)
                        popup.addstr(1 + i, 1, cand[:maxw])
                        if i == idx:
                            popup.attroff(curses.A_REVERSE)
                    except curses.error:
                        pass
                popup.noutrefresh()
                curses.doupdate()
                ch = stdscr.getch()
                if ch in (10, 13):  # Enter
                    # return chosen completion
                    chosen = candidates[idx]
                    return chosen
                elif ch == curses.KEY_UP:
                    idx = max(0, idx - 1)
                elif ch == curses.KEY_DOWN:
                    idx = min(len(candidates) - 1, idx + 1)
                elif ch in (27,):  # ESC
                    return None
        except Exception:
            return None

    def interactive_loop(self):
        def curses_main(stdscr):
            # Initialize colors using helper so we can reapply on theme change
            self._init_curses_colors(stdscr)

            curses.curs_set(1)
            stdscr.keypad(True)

            resize_pending = False
            def resize_handler(sig, frame):
                nonlocal resize_pending
                resize_pending = True

            signal.signal(signal.SIGWINCH, resize_handler)

            h, w = stdscr.getmaxyx()

            input_buf = ''
            input_cursor = 0

            def draw_screen(h, w):
                h = int(h)
                w = int(w)
                left_border = 0
                chat_start = 1
                separator = w - 21
                rooms_start = w - 20
                right_border = w - 1
                chat_width = separator - chat_start  # w-21 -1 = w-22, but to fit, adjust
                rooms_width = 19  # fixed
                chat_width = w - 23  # to make total w-1

                # Draw borders
                top_border = '+' + '-' * chat_width + '+' + '-' * rooms_width + '+'
                stdscr.addstr(0, 0, top_border)
                for i in range(1, h-5):
                    stdscr.addstr(i, left_border, '|')
                    stdscr.addstr(i, separator, '|')
                    stdscr.addstr(i, right_border, '|')
                sep_border = '+' + '-' * chat_width + '+' + '-' * rooms_width + '+'
                stdscr.addstr(h-5, 0, sep_border)
                input_border = '|' + ' ' * (w-3) + '|'
                stdscr.addstr(h-4, 0, input_border)
                stdscr.addstr(h-3, 0, input_border)
                stdscr.addstr(h-2, 0, input_border)
                bottom_border = '+' + '-' * (w-3) + '+'
                stdscr.addstr(h-1, 0, bottom_border)

                # Use a subwindow for the chat area to avoid overwrites
                try:
                    chat_h = max(1, h - 6)
                    chat_win = stdscr.derwin(chat_h, chat_width, 1, chat_start)
                    chat_win.erase()
                    chat_lines = self.current_room.chat_log[-(chat_h):]
                    display_items = []
                    for line in chat_lines:
                        if line.startswith("[ASCII]"):
                            display_items.append((True, line[len("[ASCII]"):]))
                        else:
                            wrapped = self._wrap_text_for_display(line, chat_width)
                            for chunk in wrapped:
                                display_items.append((False, chunk))
                    for i, (is_ascii, text) in enumerate(display_items[-(chat_h):]):
                        if i >= chat_h:
                            break
                        row = i
                        if is_ascii:
                            art = text
                            # measure by display width and slice to fit
                            art_display_len = _display_width(art)
                            maxlen = min(art_display_len, chat_width)
                            # build a prefix that fits maxlen display columns
                            piece = _slice_to_display_width(art, maxlen)
                            piece_display = _display_width(piece)
                            art_x = max(0, (chat_width - piece_display) // 2)
                            # render each visible character while approximating color bands
                            acc = 0
                            for ch in piece:
                                wch = _wcwidth(ch) if _wcwidth else 1
                                if acc < piece_display // 3:
                                    chat_win.attron(curses.color_pair(3))
                                elif acc < 2 * piece_display // 3:
                                    chat_win.attron(curses.color_pair(2))
                                else:
                                    chat_win.attron(curses.color_pair(1))
                                try:
                                    chat_win.addstr(row, art_x + acc, ch)
                                except curses.error:
                                    pass
                                try:
                                    chat_win.attrset(0)
                                except Exception:
                                    pass
                                acc += (wch if wch and wch > 0 else 1)
                        else:
                            if '[*]' in text:
                                chat_win.attron(curses.color_pair(1))
                            elif '[Chat]' in text:
                                chat_win.attron(curses.color_pair(2))
                            else:
                                chat_win.attron(curses.color_pair(3))
                            # slice by display width
                            sliced = _slice_to_display_width(text, chat_width)
                            try:
                                chat_win.addstr(row, 0, sliced)
                            except curses.error:
                                pass
                            try:
                                chat_win.attrset(0)
                            except Exception:
                                pass
                    chat_win.noutrefresh()
                except Exception:
                    # fallback to previous drawing if subwin fails
                    pass

                # Draw rooms
                rooms = list(self.rooms.keys())
                for i, room in enumerate(rooms[:h-6]):
                    if room == self.current_room.name:
                        stdscr.attron(curses.A_BOLD)
                    stdscr.addstr(1+i, rooms_start, room[:rooms_width])
                    stdscr.attroff(curses.A_BOLD)

                # Draw status
                status = f"Room: {self.current_room.name} | Theme: {self.theme}"
                stdscr.addstr(h-1, 1, status[:w-2])

                # Draw input
                prompt = f"{self.current_room.name}> "
                wrapped_input = self._wrap_text_for_display(prompt + input_buf, w-2)
                max_input_lines = max(1, min(self.input_max_lines, h-6))
                # show last up to max_input_lines lines, bottom-aligned
                display_input_lines = wrapped_input[-max_input_lines:]
                actual_count = len(display_input_lines)
                start_row = h-2 - (actual_count - 1)
                # Use an input subwindow
                try:
                    input_h = actual_count
                    input_win = stdscr.derwin(input_h, w-2, start_row, 1)
                    input_win.erase()
                    for idx, line in enumerate(display_input_lines):
                        try:
                            input_win.addstr(idx, 0, line[:w-2])
                        except curses.error:
                            pass
                    input_win.noutrefresh()
                except Exception:
                    for idx, line in enumerate(display_input_lines):
                        row = start_row + idx
                        try:
                            stdscr.addstr(row, 1, line)
                        except curses.error:
                            pass
                # Cursor: determine which wrapped line contains the cursor (display-width aware)
                # compute display width of prompt and of input up to cursor
                prompt_disp = _display_width(prompt)
                left_part = (prompt + input_buf)[: _slice_to_display_width((prompt + input_buf), prompt_disp + input_cursor).__len__() ] if False else None
                # simpler: compute display width of input up to cursor
                left_disp = _display_width((prompt + input_buf)[:input_cursor + len(prompt)])
                cursor_global = left_disp
                cur_line_idx = 0
                cur_col = 0
                acc = 0
                for i, ln in enumerate(wrapped_input):
                    ln_w = _display_width(ln)
                    if acc + ln_w >= cursor_global:
                        cur_line_idx = i
                        cur_col = cursor_global - acc
                        break
                    acc += ln_w
                # If cursor beyond, place at end
                if wrapped_input:
                    last_w = _display_width(wrapped_input[-1])
                else:
                    last_w = 0
                if cursor_global > acc + last_w:
                    cur_line_idx = len(wrapped_input) - 1
                    cur_col = last_w
                # Map to displayed rows (only last max_input_lines are shown)
                display_start_idx = max(0, len(wrapped_input) - max_input_lines)
                if cur_line_idx >= display_start_idx:
                    cursor_row = start_row + (cur_line_idx - display_start_idx)
                    cursor_col = 1 + cur_col
                else:
                    # cursor is above visible area; place at top line end so user sees context
                    cursor_row = start_row
                    first_visible = display_input_lines[0] if display_input_lines else ''
                    cursor_col = 1 + len(first_visible)
                if cursor_col < w-1:
                    stdscr.move(cursor_row, cursor_col)
                # Visual indicator if there are hidden input lines above
                try:
                    if len(wrapped_input) > max_input_lines:
                        indicator_row = start_row
                        indicator_col = max(1, w-4)
                        # use color pair 4 if defined for a visible indicator
                        try:
                            stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                            stdscr.addstr(indicator_row, indicator_col, '↑')
                            stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                        except Exception:
                            stdscr.attron(curses.A_BOLD)
                            stdscr.addstr(indicator_row, indicator_col, '↑')
                            stdscr.attroff(curses.A_BOLD)
                except curses.error:
                    pass

            # Add welcome messages with animation.
            # The ASCII image lines are inserted with a special sentinel
            # prefix "[ASCII]" so the renderer can apply a left->right
            # gradient only to those lines. The human-readable description
            # and commands remain normal chat messages.
            # First the short preamble (centered above the ASCII art)
            self.current_room.chat_log.append("[ASCII]Welcome To")
            draw_screen(h, w)
            stdscr.refresh()
            time.sleep(0.3)

            art_lines = [
                r"  ____ _           _    _____ _____    ____  ",
                r" ╱ ___| |__   __ _| |_ |_   __|  _ \  / ___| ",
                r"| |   | '_ \ / _` | __|  | |  | | | || |    ",
                r"| |___| | | | (_| | |_  _| |_ | | </ | |____    ",
                r" ╲____|_| |_|\__,_|\__||_____||_| \_\ \____/ ",
            ]
            # Normalize art width so every line is the same length. This
            # ensures centering calculations are consistent and alignment
            # remains stable across lines.
            art_width = max(len(ln) for ln in art_lines)
            art_lines = [ln.ljust(art_width) for ln in art_lines]

            # Fade-in each art line left-to-right. Create one placeholder per
            # art line and update that placeholder in-place so multiple lines
            # are visible simultaneously. We'll insert top padding so the
            # art block is vertically centered within the chat area.
            chat_area_height = max(1, h - 4)
            art_block_height = len(art_lines)
            top_pad = max(0, (chat_area_height - art_block_height) // 2)
            for _ in range(top_pad):
                self.current_room.chat_log.append("")

            for ln in art_lines:
                placeholder_index = len(self.current_room.chat_log)
                # append an empty placeholder of the normalized width
                self.current_room.chat_log.append("[ASCII]" + " " * art_width)
                for k in range(1, art_width + 1):
                    partial = ln[:k].ljust(art_width)
                    self.current_room.chat_log[placeholder_index] = "[ASCII]" + partial
                    draw_screen(h, w)
                    stdscr.refresh()
                    time.sleep(0.03)

            # Then the normal description and commands (not gradiented)
            self.add_to_chat("A curses-based IRC client for ChatGPT.", 1, "*")
            draw_screen(h, w)
            stdscr.refresh()
            time.sleep(0.5)
            self.add_to_chat("Commands: /help /room <name> /quit /clear /save /load /nick /theme /saveconfig", 1, "*")
            draw_screen(h, w)
            stdscr.refresh()
            time.sleep(0.5)

            while True:
                h, w = stdscr.getmaxyx()
                if h < 10 or w < 40:
                    stdscr.clear()
                    stdscr.addstr(0, 0, "Terminal too small!")
                    stdscr.refresh()
                    stdscr.getch()
                    return

                if resize_pending:
                    resize_pending = False
                    h, w = stdscr.getmaxyx()
                    stdscr.clear()
                    continue

                # Draw screen
                draw_screen(h, w)

                stdscr.refresh()

                # Process any completed API results from background thread
                try:
                    while not self._api_queue.empty():
                        user_input, success, payload = self._api_queue.get_nowait()
                        if success:
                            reply = payload
                            # append assistant message and chat
                            self.current_room.append_message("assistant", reply)
                            self.add_to_chat(reply, 2, "Chat")
                        else:
                            err = self.parse_error(str(payload))
                            self.add_to_chat(f"Error: {err}", 1, "*")
                except Exception:
                    pass

                # Draw spinner if API call is inflight; place it after status and color by theme
                try:
                    # compute visible status width
                    status = f"Room: {self.current_room.name} | Theme: {self.theme}"
                    visible_status = status[:max(0, w-12)]
                    disp_status_w = _display_width(visible_status)
                    spinner_col = 1 + disp_status_w + 1
                    # choose color pair for spinner
                    if self.theme == 'glow':
                        spinner_pair = 4
                    else:
                        spinner_pair = 2
                    if self._api_inflight:
                        s = self._spinner_states[self._spinner_pos % len(self._spinner_states)]
                        self._spinner_pos += 1
                        try:
                            stdscr.attron(curses.color_pair(spinner_pair) | curses.A_BOLD)
                            stdscr.addstr(h-1, min(w-2, spinner_col), f" {s}")
                            stdscr.attroff(curses.color_pair(spinner_pair) | curses.A_BOLD)
                        except curses.error:
                            pass
                    else:
                        # clear spinner area (a couple of chars)
                        try:
                            stdscr.addstr(h-1, min(w-2, spinner_col), '   ')
                        except curses.error:
                            pass
                except Exception:
                    pass

                # Get input
                ch = stdscr.getch()
                if ch == curses.KEY_RESIZE:
                    resize_pending = True
                    continue
                if ch in (curses.KEY_ENTER, 10, 13):
                    user_input = input_buf.strip()
                    input_buf = ''
                    if not user_input:
                        continue
                    if user_input.lower() in ["/quit", "/exit"]:
                        break
                    if user_input.startswith("/"):
                        self.handle_command(user_input)
                    else:
                        # Save to history and persist immediately
                        try:
                            if not self.input_history or (self.input_history and self.input_history[-1] != user_input):
                                self.input_history.append(user_input)
                                # trim
                                if len(self.input_history) > 200:
                                    self.input_history = self.input_history[-200:]
                                self.save_history_to_file()
                        except Exception:
                            pass

                        # Post the user message immediately to chat and start an async API call
                        self.current_room.append_message("user", user_input)
                        self.add_to_chat(user_input, 3, self.nick)
                        # start background API call
                        started = self.start_api_call(self.current_room.messages, user_input)
                        if not started:
                            # if a call is already inflight, inform user
                            self.add_to_chat("Another request is in progress. Please wait...", 1, "*")
                    continue
                # Input editing: support cursor, backspace, delete, arrows
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    # backspace: delete before cursor
                    if input_cursor > 0:
                        input_buf = input_buf[:input_cursor-1] + input_buf[input_cursor:]
                        input_cursor -= 1
                        # reset history index when editing
                        self._history_index = None
                    continue
                if ch == curses.KEY_DC:
                    # delete at cursor
                    if input_cursor < len(input_buf):
                        input_buf = input_buf[:input_cursor] + input_buf[input_cursor+1:]
                        self._history_index = None
                    continue
                if ch == curses.KEY_UP:
                    # history backward
                    if self.input_history:
                        if self._history_index is None:
                            self._history_index = len(self.input_history) - 1
                        else:
                            self._history_index = max(0, self._history_index - 1)
                        input_buf = self.input_history[self._history_index]
                        input_cursor = len(input_buf)
                    continue
                if ch == curses.KEY_DOWN:
                    # history forward
                    if self.input_history and self._history_index is not None:
                        self._history_index += 1
                        if self._history_index >= len(self.input_history):
                            self._history_index = None
                            input_buf = ''
                        else:
                            input_buf = self.input_history[self._history_index]
                        input_cursor = len(input_buf)
                    continue
                if ch == curses.KEY_LEFT:
                    if input_cursor > 0:
                        input_cursor -= 1
                    continue
                if ch == curses.KEY_RIGHT:
                    if input_cursor < len(input_buf):
                        input_cursor += 1
                    continue
                if ch == 9:  # TAB for completion
                    # find current token (word before cursor)
                    left = input_buf[:input_cursor]
                    m = re.search(r"(\S+)$", left)
                    token = m.group(1) if m else ''
                    candidates = self.get_completions(token)
                    if candidates:
                        if len(candidates) == 1:
                            comp = candidates[0]
                            if m:
                                start = m.start(1)
                                input_buf = left[:start] + comp + input_buf[input_cursor:]
                                input_cursor = start + len(comp)
                            else:
                                input_buf = comp + input_buf[input_cursor:]
                                input_cursor = len(comp)
                        else:
                            # show popup selection near cursor and use returned completion
                            chosen = self._show_completion_popup(stdscr, candidates, w, h)
                            if chosen:
                                if m:
                                    start = m.start(1)
                                    input_buf = left[:start] + chosen + input_buf[input_cursor:]
                                    input_cursor = start + len(chosen)
                                else:
                                    input_buf = chosen + input_buf[input_cursor:]
                                    input_cursor = len(chosen)
                    # else: no candidates, do nothing
                    continue
                if 32 <= ch <= 126:
                    # insert printable char at cursor
                    input_buf = input_buf[:input_cursor] + chr(ch) + input_buf[input_cursor:]
                    input_cursor += 1
                    # reset history index when editing
                    self._history_index = None
                    continue

        curses.wrapper(curses_main)

    def parse_error(self, error_str: str) -> str:
        if ' - ' in error_str:
            json_part = error_str.split(' - ', 1)[-1]
            try:
                import json
                error_data = json.loads(json_part)
                return error_data.get('error', {}).get('message', error_str)
            except:
                pass
        return error_str

    def _wrap_text_for_display(self, text: str, width: int) -> List[str]:
        """Wrap text to fit 'width'. If words are longer than width, hyphenate them."""
        if not text:
            return [""]
        parts = []
        for paragraph in text.split('\n'):
            words = paragraph.split(' ')
            line = ''
            line_disp = 0
            for word in words:
                if line:
                    sep = ' '
                    sep_w = 1
                else:
                    sep = ''
                    sep_w = 0
                word_w = _display_width(word)
                if word_w > width:
                    # flush current line
                    if line:
                        parts.append(line)
                        line = ''
                        line_disp = 0
                    # hyphenate the long word by display width
                    start_idx = 0
                    buf = word
                    while buf:
                        # take up to width-1 display cols
                        take = max(1, width - 1)
                        chunk = _slice_to_display_width(buf, take)
                        if not chunk:
                            break
                        buf = buf[len(chunk):]
                        if buf:
                            parts.append(chunk + '-')
                        else:
                            line = chunk
                            line_disp = _display_width(line)
                else:
                    if line_disp + sep_w + word_w <= width:
                        if sep:
                            line += sep + word
                        else:
                            line = word
                        line_disp += sep_w + word_w
                    else:
                        parts.append(line)
                        line = word
                        line_disp = word_w
            parts.append(line)
        return parts



    def add_to_chat(self, text: str, color_pair: int, nick: str):
        timestamp = datetime.now().strftime('%H:%M')
        line = f"[{timestamp}] {nick}> {text}"
        self.current_room.chat_log.append(line)

    def handle_command(self, user_input: str):
        parts = user_input.split()
        cmd = parts[0].lower()
        if cmd == "/clear":
            self.current_room.chat_log.clear()
            self.add_to_chat("Chat log cleared.", 1, "*")
        elif cmd == "/save":
            fname = parts[1] if len(parts) > 1 else None
            saved = self.save_room(fname)
            self.add_to_chat(f"Saved to {saved}", 1, "*")
        elif cmd == "/load":
            if len(parts) < 2:
                self.add_to_chat("Usage: /load <filename>", 1, "*")
            else:
                fname = parts[1]
                self.load_room_from_file(fname)
                self.add_to_chat(f"Loaded {fname}", 1, "*")
        elif cmd == "/topic":
            if len(parts) < 2:
                self.add_to_chat(f"Topic: {self.current_room.topic}", 1, "*")
            else:
                self.current_room.topic = " ".join(parts[1:])
                self.add_to_chat(f"Topic set to: {self.current_room.topic}", 1, "*")
        elif cmd == "/help":
            self.add_to_chat("Commands: /quit /clear /save [file] /load <file> /topic [new] /help /room <name|num> /rooms /nick <name> /theme <name> /saveconfig", 1, "*")
        elif cmd == "/getkey":
            # open browser to OpenAI API key create page and show a help line
            try:
                webbrowser.open("https://platform.openai.com/account/api-keys")
                self.add_to_chat("Opened browser to OpenAI API keys page. Save your key into the local file named 'openapi_key' in the working directory.", 1, "*")
            except Exception:
                self.add_to_chat("Could not open browser. Visit: https://platform.openai.com/account/api-keys", 1, "*")
        elif cmd == "/invite":
            # simple invite: open mailto with prefilled body containing download link placeholder
            to_addr = parts[1] if len(parts) > 1 else ''
            subject = "Join my ChatIRC chat"
            body = "Hi,%0A%0AI've invited you to join a ChatIRC room. Download the client from: <REPLACE_WITH_GITHUB_RELEASE_URL>%0A%0AOnce installed, place your OpenAI API key in a file named 'openapi_key' in the working directory.%0A%0ARegards"
            mailto = f"mailto:{to_addr}?subject={subject}&body={body}"
            try:
                webbrowser.open(mailto)
                self.add_to_chat(f"Opened mail client to invite {to_addr}", 1, "*")
            except Exception:
                self.add_to_chat("Could not open mail client. Copy this invite link: <REPLACE_WITH_GITHUB_RELEASE_URL>", 1, "*")
        elif cmd == "/room":
            if len(parts) < 2:
                self.add_to_chat(f"Current room: {self.current_room.name}", 1, "*")
            else:
                room_arg = parts[1]
                rooms = self.list_rooms()
                if room_arg.isdigit():
                    idx = int(room_arg) - 1
                    if 0 <= idx < len(rooms):
                        room_name = rooms[idx]
                    else:
                        self.add_to_chat("Invalid room number", 1, "*")
                        return
                else:
                    room_name = room_arg
                self.current_room = self._ensure_room(room_name)
        elif cmd == "/rooms":
            rooms = self.list_rooms()
            self.add_to_chat(f"Rooms: {', '.join(rooms)}", 1, "*")
        elif cmd == "/nick":
            if len(parts) < 2:
                self.add_to_chat(f"Nick: {self.nick}", 1, "*")
            else:
                self.nick = parts[1]
                self.add_to_chat(f"Nick set to: {self.nick}", 1, "*")
        elif cmd == "/theme":
            if len(parts) < 2:
                self.add_to_chat(f"Current theme: {self.theme} (available: classic, neon, mono, glow)", 1, "*")
            else:
                new_theme = parts[1].lower()
                if new_theme in ["classic", "neon", "mono", "glow"]:
                    self.theme = new_theme
                    # re-init curses colors if running under curses
                    try:
                        self._init_curses_colors(None)
                    except Exception:
                        pass
                    self.add_to_chat(f"Theme set to: {self.theme}.", 1, "*")
                else:
                    self.add_to_chat("Invalid theme. Use: classic, neon, mono, glow", 1, "*")
        elif cmd == "/saveconfig":
            self.config["max_history"] = self.max_history
            self.config["model"] = MODEL
            self.config["nick"] = self.nick
            self.config["theme"] = self.theme
            with open(self.config_path, "w", encoding="utf-8") as cf:
                json.dump(self.config, cf, indent=2)
            self.add_to_chat(f"Config saved to {self.config_path}", 1, "*")
        else:
            self.add_to_chat(f"Unknown command: {cmd}", 1, "*")


def main():
    cli = ChatIRC()
    cli.interactive_loop()


if __name__ == "__main__":
    main()
