
import curses
import textwrap
from datetime import datetime
import time

# =========================
# APP STATE
# =========================

MAX_MESSAGE_LENGTH = 100
MAX_INPUT_LINES = 4


class AppState:
    def __init__(self, contacts, chats):
        # Persistent data (shared with main)
        self.contacts = contacts        # {user_id: {contact_id: name}}
        self.chats = chats              # {user_id: {contact_id: [(dir, msg), ...]}}

        # Runtime state
        self.client_id = None
        self.active_contact = None
        self.unread_counts = {}

        # Focus + scrolling
        self.focus_mode = "contacts"     # "contacts" or "chat"
        self.chat_scroll_offset = 0
        self.contact_scroll_offset = 0

        # Input editing
        self.input_buffer = ""
        self.cursor_pos = 0

        # Connection state
        self.sending = False
        self.connection_status = "Disconnected"

        # UI state
        self.modal = None   # None or dict describing modal
        self.status_message = None
        self.error_message = None

        self.running = True

    # =========================
    # USER INITIALIZATION
    # =========================

    def initialize_user(self, client_id):
        self.client_id = client_id

        self.contacts.setdefault(client_id, {})
        self.chats.setdefault(client_id, {})

        # Always ensure self contact exists
        self.contacts[client_id].setdefault(client_id, "You")
        self.chats[client_id].setdefault(client_id, [])

        # Initialize unread counts
        for cid in self.contacts[client_id]:
            self.unread_counts.setdefault(cid, 0)

        self.active_contact = client_id
        self.chat_scroll_offset = 0
        self.contact_scroll_offset = 0

    # =========================
    # CONTACT MANAGEMENT
    # =========================

    def ensure_contact(self, contact_id, default_name=None):
        user_contacts = self.contacts[self.client_id]
        user_chats = self.chats[self.client_id]

        if contact_id not in user_contacts:
            user_contacts[contact_id] = default_name or f"PersonID{contact_id}"

        user_chats.setdefault(contact_id, [])
        self.unread_counts.setdefault(contact_id, 0)

    def rename_contact(self, contact_id, new_name):
        self.ensure_contact(contact_id)
        self.contacts[self.client_id][contact_id] = new_name

    # =========================
    # MESSAGE MANAGEMENT
    # =========================

    def append_message(self, contact_id, direction, message):
        self.ensure_contact(contact_id)
        ts = time.time()
        self.chats[self.client_id][contact_id].append((direction, message, ts))

    # =========================
    # INPUT MANAGEMENT
    # =========================

    def can_insert_char(self):
        return len(self.input_buffer) < MAX_MESSAGE_LENGTH

    def insert_char(self, ch):
        if not self.can_insert_char():
            self.status_message = "Maximum character limit reached"
            return False

        self.input_buffer = (
            self.input_buffer[:self.cursor_pos] +
            ch +
            self.input_buffer[self.cursor_pos:]
        )
        self.cursor_pos += 1
        self.status_message = None
        return True

    def insert_newline(self):
        if not self.can_insert_char():
            self.status_message = "Maximum character limit reached"
            return False

        self.insert_char("\n")
        return True

    def backspace(self):
        if self.cursor_pos == 0:
            return

        self.input_buffer = (
            self.input_buffer[:self.cursor_pos - 1] +
            self.input_buffer[self.cursor_pos:]
        )
        self.cursor_pos -= 1

    def delete(self):
        if self.cursor_pos >= len(self.input_buffer):
            return

        self.input_buffer = (
            self.input_buffer[:self.cursor_pos] +
            self.input_buffer[self.cursor_pos + 1:]
        )

    def move_cursor_left(self):
        if self.cursor_pos > 0:
            self.cursor_pos -= 1

    def move_cursor_right(self):
        if self.cursor_pos < len(self.input_buffer):
            self.cursor_pos += 1

    def clear_input(self):
        self.input_buffer = ""
        self.cursor_pos = 0
        self.status_message = None

    # =========================
    # SCROLL MANAGEMENT
    # =========================

    def scroll_chat_up(self):
        self.chat_scroll_offset += 1

    def scroll_chat_down(self):
        self.chat_scroll_offset = max(0, self.chat_scroll_offset - 1)

    def scroll_contacts_up(self):
        self.contact_scroll_offset += 1

    def scroll_contacts_down(self):
        self.contact_scroll_offset = max(0, self.contact_scroll_offset - 1)

    # =========================
    # FOCUS
    # =========================

    def toggle_focus(self):
        self.focus_mode = (
            "chat" if self.focus_mode == "contacts" else "contacts"
        )

    # =========================
    # MODALS
    # =========================

    def open_modal(self, modal_type, data=None):
        self.modal = {
            "type": modal_type,
            "buffer": "",
            "cursor": 0,
            "data": data,
        }

    def close_modal(self):
        self.modal = None

    def show_error(self, message):
        self.open_modal("error", {"message": message})


# =========================
# RENDERER
# =========================

MIN_WIDTH = 60
MIN_HEIGHT = 16
SIDEBAR_WIDTH = 25


class Renderer:
    def __init__(self, stdscr, state):
        self.stdscr = stdscr
        self.state = state
        self._init_colors()

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()

        curses.init_pair(1, curses.COLOR_GREEN, -1)    # Typing
        curses.init_pair(2, curses.COLOR_CYAN, -1)     # Pending / Connected
        curses.init_pair(3, curses.COLOR_YELLOW, -1)   # Active / Reconnecting
        curses.init_pair(4, curses.COLOR_RED, -1)      # Failed / Disconnected
        curses.init_pair(5, curses.COLOR_WHITE, -1)    # Normal
        curses.init_pair(6, curses.COLOR_CYAN, -1)     # Sent
        curses.init_pair(7, curses.COLOR_WHITE, -1)    # Received
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_WHITE)

    def _format_time(self, ts):
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%H:%M")
    
    def _format_date(self, ts):
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%d %b %Y")

    # =========================
    # PUBLIC DRAW ENTRY
    # =========================

    def draw(self):
        self.stdscr.erase()

        h, w = self.stdscr.getmaxyx()

        if h < MIN_HEIGHT or w < MIN_WIDTH:
            self._draw_too_small(h, w)
            self.stdscr.refresh()
            return

        layout = self._compute_layout(h, w)

        self._draw_border(layout)
        self._draw_top_bar(layout)
        self._draw_contacts(layout)
        self._draw_chat(layout)
        self._draw_separator(layout)
        self._draw_status_bar(layout)
        self._draw_input(layout)

        if self.state.modal:
            self._draw_modal(layout)

        self.stdscr.refresh()

    # =========================
    # LAYOUT
    # =========================

    def _compute_layout(self, h, w):
        top_bar_y = 0
        status_bar_y = h - 1
        input_bottom = h - 2
        separator_y = h - 6
        chat_top = 1
        chat_bottom = separator_y - 1

        return {
            "h": h,
            "w": w,
            "top_bar_y": top_bar_y,
            "status_bar_y": status_bar_y,
            "input_bottom": input_bottom,
            "separator_y": separator_y,
            "chat_top": chat_top,
            "chat_bottom": chat_bottom,
            "chat_left": SIDEBAR_WIDTH + 1,
            "chat_right": w - 2,
        }

    # =========================
    # TOO SMALL
    # =========================

    def _draw_too_small(self, h, w):
        msg = f"Terminal too small ({w}x{h}). Resize."
        self.stdscr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg)

    # =========================
    # BORDER
    # =========================

    def _draw_border(self, layout):
        self.stdscr.box()
            
        for y in range(1, layout["chat_bottom"] + 1):
            self.stdscr.addch(
                y,
                SIDEBAR_WIDTH,
                curses.ACS_VLINE,
                curses.color_pair(2)
            )

    # =========================
    # TOP BAR
    # =========================

    def _draw_top_bar(self, layout):
        status_text = f"[{self.state.connection_status}]"

        if self.state.connection_status == "Connected":
            status_color = curses.color_pair(2)
        elif self.state.connection_status == "Reconnecting...":
            status_color = curses.color_pair(3)
        else:
            status_color = curses.color_pair(4)

        title_part = " RETRO MESSENGER "
        title_text = f"{title_part}{status_text} "

        bar_attr = status_color | curses.A_REVERSE | curses.A_BOLD
        self.stdscr.hline(0, 1, ord(" "), layout["w"] - 2, bar_attr)
        start_x = (layout["w"] - len(title_text)) // 2
        self.stdscr.addstr(
            0,
            start_x,
            title_part,
            bar_attr
        )
        self.stdscr.addstr(
            0,
            start_x + len(title_part),
            status_text,
            bar_attr
        )
        self.stdscr.attroff(bar_attr)

    # =========================
    # CONTACTS
    # =========================

    def _draw_contacts(self, layout):
        user_contacts = self.state.contacts.get(self.state.client_id, {})
        keys = sorted(user_contacts.keys())

        visible_height = layout["chat_bottom"] - 3
        offset = self.state.contact_scroll_offset

        # Auto adjust to keep active visible
        active_idx = keys.index(self.state.active_contact)
        if active_idx < offset:
            self.state.contact_scroll_offset = active_idx
        elif active_idx >= offset + visible_height:
            self.state.contact_scroll_offset = active_idx - visible_height + 1

        offset = self.state.contact_scroll_offset
        visible = keys[offset: offset + visible_height]

        self.stdscr.addstr(2, 2, " CONTACTS ", curses.A_BOLD)

        for i, cid in enumerate(visible):
            row = 4 + i
            name = user_contacts[cid]
            unread = self.state.unread_counts.get(cid, 0)

            label = f"[{cid}] {name}"
            if unread > 0:
                label += f" ({unread})"

            if cid == self.state.active_contact:
                self.stdscr.addstr(row, 2,
                                label[:SIDEBAR_WIDTH - 3],
                                curses.color_pair(3) | curses.A_BOLD)
            else:
                self.stdscr.addstr(row, 2,
                                label[:SIDEBAR_WIDTH - 3],
                                curses.color_pair(5))

    # =========================
    # CHAT
    # =========================

    def _wrap_text(self, text, width):
        lines = []

        wrapper = textwrap.TextWrapper(
            width=width,
            expand_tabs=False,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False
        )

        for raw in text.replace("\r", "").split("\n"):
            wrapped = wrapper.wrap(raw)
            if not wrapped:
                lines.append("")
            else:
                lines.extend(wrapped)

        return lines
    
    def _draw_chat(self, layout):
        chat_top = layout["chat_top"] + 1
        chat_bottom = layout["chat_bottom"]
        chat_left = layout["chat_left"]
        chat_right = layout["chat_right"] - 1

        chat_width = chat_right - chat_left + 1
        chat_height = chat_bottom - chat_top + 1

        messages = self.state.chats[self.state.client_id].get(
            self.state.active_contact, []
        )

        # =========================
        # BUILD BLOCKS
        # =========================
        blocks = []
        last_date = None

        for message in messages:
            if len(message) == 2:
                direction, msg = message
                ts = 0
            else:
                direction, msg, ts = message

            date_str = self._format_date(ts)

            if date_str != last_date:
                blocks.append(("date", date_str))
                last_date = date_str

            wrapped = self._wrap_text(msg, chat_width // 2)
            blocks.append(("msg", direction, wrapped, ts))

        # =========================
        # FLATTEN
        # =========================
        rendered = []

        for block in blocks:
            if block[0] == "date":
                rendered.append(("date", block[1]))
            else:
                _, direction, lines, ts = block

                time_str = self._format_time(ts)
                if lines:
                    lines = lines.copy()
                    lines[-1] = f"{lines[-1]}  {time_str}"

                rendered.append(("bubble", direction, lines))

        # =========================
        # SCROLL
        # =========================
        total_height = 0

        for item in rendered:
            if item[0] == "date":
                total_height += 1
            else:
                _, _, lines = item
                total_height += 2 + len(lines)
        
        max_scroll = max(0, total_height - chat_height)

        self.state.chat_scroll_offset = max(
            0,
            min(self.state.chat_scroll_offset, max_scroll)
        )

        visible = []
        row_budget = chat_height
        skip_rows = self.state.chat_scroll_offset

        # Traverse from bottom upward
        for item in reversed(rendered):

            if item[0] == "date":
                item_height = 1
            else:
                _, _, lines = item
                item_height = 2 + len(lines)

            # First consume scroll offset rows
            if skip_rows >= item_height:
                skip_rows -= item_height
                continue

            # If partially skipped (rare but safe)
            if skip_rows > 0:
                skip_rows = 0
                continue

            # Add item if it fits
            if item_height <= row_budget:
                visible.insert(0, item)
                row_budget -= item_height
            else:
                break
        
        # =========================
        # DRAW
        # =========================
        row = chat_top

        for item in visible:
            if row > chat_bottom:
                break

            # -------- DATE --------
            if item[0] == "date":
                date_text = f"────────  {item[1]}  ────────"
                x = chat_left + (chat_width - len(date_text)) // 2
                self.stdscr.addstr(row, x, date_text, curses.A_DIM)
                row += 1
                continue

            _, direction, lines = item

            max_bubble_width = chat_width // 2 + 2
            content_width = max(len(l) for l in lines)
            bubble_width = min(content_width + 2, max_bubble_width)

            # -------- COLOR LOGIC --------
            if direction == "out":
                color = curses.color_pair(6) | curses.A_ITALIC
            elif direction == "out_pending":
                color = curses.color_pair(2)
            elif direction == "out_failed":
                color = curses.color_pair(4) | curses.A_BOLD
            else:  # "in"
                color = curses.color_pair(7) | curses.A_ITALIC

            # -------- SIDE SWAP --------
            if direction.startswith("out"):
                x_start = chat_right - bubble_width + 1
            else:
                x_start = chat_left + 1

            # -------- DRAW BUBBLE --------
            # Top border
            self.stdscr.addstr(
                row,
                x_start,
                "┌" + "─" * (bubble_width - 2) + "┐",
                color
            )
            row += 1

            # Content
            for i, line in enumerate(lines):

                padded = line.ljust(bubble_width - 2)

                # Dim timestamp (only on last line)
                if i == len(lines) - 1:
                    # Split timestamp from message
                    parts = line.rsplit("  ", 1)

                    if len(parts) == 2:
                        msg_part, time_part = parts
                    else:
                        msg_part = line
                        time_part = ""

                    msg_part = msg_part.ljust(bubble_width - 2 - len(time_part) - 2)

                    # Left border
                    self.stdscr.addstr(row, x_start, "│", color)

                    # Message text (normal brightness)
                    self.stdscr.addstr(row, x_start + 1, msg_part, color)

                    # Timestamp (dimmed)
                    if time_part:
                        self.stdscr.addstr(
                            row,
                            x_start + 1 + len(msg_part),
                            "  " + time_part,
                            curses.A_DIM
                        )

                    # Right border
                    self.stdscr.addstr(
                        row,
                        x_start + bubble_width - 1,
                        "│",
                        color
                    )

                else:
                    padded = line.ljust(bubble_width - 2)
                    self.stdscr.addstr(
                        row,
                        x_start,
                        f"│{padded}│",
                        color
                    )
                row += 1

            # Bottom border
            self.stdscr.addstr(
                row,
                x_start,
                "└" + "─" * (bubble_width - 2) + "┘",
                color
            )
            row += 1
            
    # =========================
    # SEPARATOR
    # =========================

    def _draw_separator(self, layout):
        y = layout["separator_y"]
        self.stdscr.hline(y, 1, curses.ACS_HLINE, layout["w"] - 2)

    # =========================
    # INPUT (MULTILINE)
    # =========================
    def _draw_input(self, layout):
        input_top = layout["separator_y"] + 1

        left_margin = 2
        right_margin = 2  # border + padding

        usable_width = layout["w"] - left_margin - right_margin

        prefix_width = 2  # "> "
        interior_width = usable_width - prefix_width

        buffer = self.state.input_buffer

        # Wrap using interior width ONLY
        wrapped = self._wrap_text(buffer, interior_width)

        # Only last N lines visible
        visible = wrapped[-MAX_INPUT_LINES:]

        # Clear area
        for i in range(MAX_INPUT_LINES):
            self.stdscr.addstr(
                input_top + i,
                left_margin,
                " " * usable_width
            )

        # Draw
        for i, line in enumerate(visible):
            prefix = "> " if i == 0 else "  "
            self.stdscr.addstr(
                input_top + i,
                left_margin,
                prefix + line.ljust(interior_width),
                curses.color_pair(1)
            )

        # ---- Cursor ----
        before_cursor = buffer[:self.state.cursor_pos]
        cursor_wrapped = self._wrap_text(before_cursor, interior_width)
        cursor_visible = cursor_wrapped[-MAX_INPUT_LINES:]

        cursor_row = input_top + len(cursor_visible) - 1
        cursor_col = left_margin + prefix_width + len(cursor_visible[-1])

        # Hard clamp
        max_col = left_margin + usable_width - 1
        cursor_col = min(cursor_col, max_col)

        self.stdscr.move(cursor_row, cursor_col)

    # =========================
    # STATUS BAR
    # =========================

    def _draw_status_bar(self, layout):
        msg = None

        if self.state.error_message:
            msg = " ERROR! Press any key to dismiss "
        elif self.state.status_message:
            msg = f" {self.state.status_message} "
        else:
            msg = " Ctrl+? Help | Ctrl+R Rename | Ctrl+X Quit | Tab Switch "

        y = layout["status_bar_y"]
        w = layout["w"]

        self.stdscr.attron(curses.A_REVERSE | curses.color_pair(5))
        self.stdscr.hline(y, 1, ord(" "), w - 2)
        self.stdscr.addstr(y, max(1, (w - len(msg)) // 2), msg[:w-2])
        self.stdscr.attroff(curses.A_REVERSE | curses.color_pair(5))

    # =========================
    # MODAL
    # =========================
    def _draw_modal(self, layout):
        h = layout["h"]
        w = layout["w"]

        box_w = 60
        box_h = 11

        sy = (h - box_h) // 2
        sx = (w - box_w) // 2

        modal_type = self.state.modal["type"]

        # Colors    
        if modal_type == "help":
            modal_border = curses.color_pair(2) | curses.A_BOLD   # Cyan
        elif modal_type == "rename":
            modal_border = curses.color_pair(1) | curses.A_BOLD   # Green
        elif modal_type == "confirm_quit":
            modal_border = curses.color_pair(3) | curses.A_BOLD   # Yellow
        elif modal_type == "error":
            modal_border = curses.color_pair(4) | curses.A_BOLD   # Red
        else:
            modal_border = curses.color_pair(5) | curses.A_BOLD   # Default white
        

        modal_fill = curses.color_pair(8)

        # Fill modal background
        for i in range(box_h):
            self.stdscr.addstr(
                sy + i,
                sx,
                " " * box_w,
                modal_fill
            )

        # Rounded border
        self.stdscr.addstr(
            sy, sx,
            "╭" + "─" * (box_w - 2) + "╮",
            modal_border
        )
        self.stdscr.addstr(
            sy + box_h - 1, sx,
            "╰" + "─" * (box_w - 2) + "╯",
            modal_border
        )

        for i in range(1, box_h - 1):
            self.stdscr.addstr(sy + i, sx, "│", modal_border)
            self.stdscr.addstr(sy + i, sx + box_w - 1, "│", modal_border)

        if modal_type == "help":
            title = " HELP "
            self.stdscr.addstr(
                sy + 1,
                sx + (box_w - len(title)) // 2,
                title,
                modal_border | curses.A_REVERSE | curses.A_BOLD
            )

            lines = [
                "Ctrl+?    - Open Help",
                "Ctrl+R    - Add or Rename Contact",
                "Ctrl+X    - Quit",
                "Tab       - Toggle Focus",
                "Enter     - Send Message",
                "Ctrl+N    - New Line",
            ]

            for i, line in enumerate(lines):
                self.stdscr.addstr(
                    sy + 3 + i,
                    sx + 4,
                    line,
                    modal_fill
                )

            footer = "Press any key to close"
            self.stdscr.addstr(
                sy + box_h - 2,
                sx + (box_w - len(footer)) // 2,
                footer,
                modal_fill | curses.A_DIM
            )

        elif modal_type == "confirm_quit":
            title = " CONFIRM EXIT "
            self.stdscr.addstr(
                sy + 2,
                sx + (box_w - len(title)) // 2,
                title,
                modal_border | curses.A_REVERSE | curses.A_BOLD
            )

            msg = "Are you sure you want to quit? (y/n)"
            self.stdscr.addstr(
                sy + 5,
                sx + (box_w - len(msg)) // 2,
                msg,
                modal_fill
            )

        elif modal_type == "rename":
            title = " ADD OR RENAME CONTACT "
            self.stdscr.addstr(
                sy + 1,
                sx + (box_w - len(title)) // 2,
                title,
                modal_border | curses.A_REVERSE | curses.A_BOLD
            )

            prompt = "Enter: <id> <name>"
            self.stdscr.addstr(
                sy + 3,
                sx + 4,
                prompt,
                modal_fill
            )

            buffer = self.state.modal["buffer"]
            self.stdscr.addstr(
                sy + 6,
                sx + 4,
                buffer,
                modal_fill
            )

            cursor_x = sx + 4 + self.state.modal["cursor"]
            cursor_y = sy + 6
            self.stdscr.move(cursor_y, cursor_x)

        elif modal_type == "error":
            message = self.state.modal["data"]["message"]
            lines = message.split("\n")

            title = " ERROR "
            self.stdscr.addstr(
                sy + 1,
                sx + (box_w - len(title)) // 2,
                title,
                modal_border | curses.A_REVERSE | curses.A_BOLD
            )

            for i, line in enumerate(lines):
                if sy + 3 + i >= sy + box_h - 2:
                    break
                self.stdscr.addstr(
                    sy + 3 + i,
                    sx + 4,
                    line[:box_w - 8],
                    modal_fill
                )

            footer = "Press any key to close"
            self.stdscr.addstr(
                sy + box_h - 2,
                sx + (box_w - len(footer)) // 2,
                footer,
                curses.A_DIM
            )

# =========================
# INPUT CONTROLLER
# =========================

class InputController:
    def __init__(self, state, send_callback):
        self.state = state
        self.send_callback = send_callback  # function(contact_id, message)

    # =========================
    # ENTRY
    # =========================

    def handle(self, ch):
        # If modal active → route to modal handler
        if self.state.modal:
            self._handle_modal(ch)
            return

        # -------------------------
        # Global shortcuts
        # -------------------------

        if ch == 31:
            self.state.open_modal("help")
            return

        if ch == 24:  # Ctrl+X
            self.state.open_modal("confirm_quit")
            return

        if ch == 18:  # Ctrl+R
            self.state.open_modal("rename")
            return

        if ch == 9:  # Tab
            self._toggle_focus()
            return

        # -------------------------
        # Navigation / scrolling
        # -------------------------

        if ch == curses.KEY_UP:
            self._handle_up()
            return

        if ch == curses.KEY_DOWN:
            self._handle_down()
            return

        # -------------------------
        # Editing keys
        # -------------------------

        if ch in (curses.KEY_LEFT,):
            self.state.move_cursor_left()
            return

        if ch in (curses.KEY_RIGHT,):
            self.state.move_cursor_right()
            return

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self.state.backspace()
            return

        if ch == curses.KEY_DC:
            self.state.delete()
            return
        
        if ch == 10:  # Enter
            self._send_message()
            return
        
        # -------------------------
        # Character input
        # -------------------------

        if 32 <= ch <= 126:
            self.state.insert_char(chr(ch))
        elif ch == 14:
            self.state.insert_char('\n')

    # =========================
    # FOCUS
    # =========================

    def _toggle_focus(self):
        # Clear failed messages if leaving chat
        if self.state.focus_mode == "chat":
            self._cleanup_failed(self.state.active_contact)

        self.state.toggle_focus()

    # =========================
    # UP/DOWN HANDLING
    # =========================

    def _handle_up(self):
        if self.state.focus_mode == "contacts":
            self._select_previous_contact()
        else:
            self.state.scroll_chat_up()

    def _handle_down(self):
        if self.state.focus_mode == "contacts":
            self._select_next_contact()
        else:
            self.state.scroll_chat_down()

    # =========================
    # CONTACT SWITCH
    # =========================

    def _select_previous_contact(self):
        contacts = sorted(self.state.contacts[self.state.client_id].keys())
        idx = contacts.index(self.state.active_contact)

        if idx > 0:
            self._cleanup_failed(self.state.active_contact)
            self.state.active_contact = contacts[idx - 1]
            self.state.chat_scroll_offset = 0
            self.state.unread_counts[self.state.active_contact] = 0

    def _select_next_contact(self):
        contacts = sorted(self.state.contacts[self.state.client_id].keys())
        idx = contacts.index(self.state.active_contact)

        if idx < len(contacts) - 1:
            self._cleanup_failed(self.state.active_contact)
            self.state.active_contact = contacts[idx + 1]
            self.state.chat_scroll_offset = 0
            self.state.unread_counts[self.state.active_contact] = 0

    # =========================
    # SEND
    # =========================

    def _send_message(self):
        message = self.state.input_buffer.strip()
        if not message:
            return

        contact = self.state.active_contact

        if self.state.connection_status != "Connected":
            self.state.show_error("Not connected to server.")
            return
        
        # Append pending
        self.state.append_message(contact, "out_pending", message)

        # Reset scroll to bottom
        self.state.chat_scroll_offset = 0

        # Clear input
        self.state.clear_input()

        # Trigger async send
        self.send_callback(contact, message)

    # =========================
    # MODAL HANDLING
    # =========================

    def _handle_modal(self, ch):
        modal_type = self.state.modal["type"]

        # Escape closes modal
        if ch == 27:
            self.state.close_modal()
            return

        if modal_type == "help":
            # Any key closes help
            self.state.close_modal()
            return

        if modal_type == "confirm_quit":
            if ch in (ord('y'), ord('Y')):
                self.state.running = False
            else:
                self.state.close_modal()
            return

        if modal_type == "rename":
            self._handle_rename_modal(ch)

        if modal_type == "error":
            self.state.close_modal()
            return

    def _handle_rename_modal(self, ch):
        buffer = self.state.modal["buffer"]
        cursor = self.state.modal["cursor"]

        if ch == 10:  # Enter → confirm
            parts = buffer.strip().split(" ", 1)
            if len(parts) == 2:
                try:
                    cid = int(parts[0])
                    name = parts[1]
                    self.state.rename_contact(cid, name)
                except ValueError:
                    self.state.show_error("Invalid contact ID.")
                    pass
            self.state.close_modal()
            return

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                buffer = buffer[:cursor-1] + buffer[cursor:]
                cursor -= 1

        elif ch == curses.KEY_LEFT:
            if cursor > 0:
                cursor -= 1

        elif ch == curses.KEY_RIGHT:
            if cursor < len(buffer):
                cursor += 1

        elif 32 <= ch <= 126:
            buffer = buffer[:cursor] + chr(ch) + buffer[cursor:]
            cursor += 1

        self.state.modal["buffer"] = buffer
        self.state.modal["cursor"] = cursor

    # =========================
    # FAILED CLEANUP
    # =========================

    def _cleanup_failed(self, contact_id):
        messages = self.state.chats[self.state.client_id].get(contact_id, [])
        self.state.chats[self.state.client_id][contact_id] = [
            m for m in messages if m[0] != "out_failed"
        ]

# =========================
# NETWORK WORKER
# =========================

import threading
import time

class NetworkWorker:
    def __init__(self, state, app_factory):
        self.state = state
        self.app_factory = app_factory
        self.app = None
        self.lock = threading.RLock()
        self.thread = None

    # =========================
    # START
    # =========================

    def start(self):
        self.app = self.app_factory(self.state.client_id)

        try:
            self.app.associate()
            self.state.connection_status = "Connected"
        except Exception as e:
            self.state.connection_status = "Disconnected"
            self.state.show_error(f"Association failed:\n{e}")

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

    # =========================
    # MAIN LOOP
    # =========================

    def _run(self):
        while self.state.running:
            try:
                self._poll_messages()
                time.sleep(0.2)

            except Exception:
                self._handle_reconnect()

    # =========================
    # POLL
    # =========================

    def _poll_messages(self):
        while True:
            msg = self.app.get_message()
            if not msg:
                break

            sender = msg.get("id2")
            content = msg.get("payload", "")

            content = content.replace("\r", "")

            with self.lock:
                self.state.ensure_contact(sender)
                self.state.append_message(sender, "in", content)

                # Unread logic
                if sender != self.state.active_contact:
                    self.state.unread_counts[sender] = \
                        self.state.unread_counts.get(sender, 0) + 1

            self.state.connection_status = "Connected"

    # =========================
    # SEND
    # =========================

    def send(self, contact_id, message):
        def _send_async():
            self.state.sending = True

            try:
                success = self.app.push_message(contact_id, message)

                with self.lock:
                    messages = self.state.chats[
                        self.state.client_id
                    ][contact_id]

                    # Find last pending message
                    for i in reversed(range(len(messages))):
                        if messages[i][0] == "out_pending":
                            if success:
                                messages[i] = ("out", messages[i][1], messages[i][2])
                            else:
                                messages[i] = ("out_failed", messages[i][1], messages[i][2])
                                self.state.show_error("Recipient buffer is full.")
                            break

            except Exception as e:
                with self.lock:
                    messages = self.state.chats[
                        self.state.client_id
                    ][contact_id]

                    for i in reversed(range(len(messages))):
                        if messages[i][0] == "out_pending":
                            messages[i] = ("out_failed", messages[i][1], messages[i][2])
                            break

                    self.state.show_error(f"Send failed:\n{e}")

            self.state.sending = False

        threading.Thread(target=_send_async, daemon=True).start()

    # =========================
    # RECONNECT
    # =========================

    def _handle_reconnect(self):
        self.state.connection_status = "Reconnecting..."

        time.sleep(1)

        try:
            self.app = self.app_factory(self.state.client_id)
            self.app.associate()
            self.state.connection_status = "Connected"
        except Exception as e:
            self.state.connection_status = "Disconnected"
            self.state.show_error(f"Reconnect failed:\n{e}")

# =========================
# RETRO MESSENGER UI
# =========================

WELCOME_BANNER = [
    "  ██████  ███████ ████████ ██████   ██████ ",
    "  ██   ██ ██         ██    ██   ██ ██    ██",
    "  ██████  █████      ██    ██████  ██    ██",
    "  ██   ██ ██         ██    ██   ██ ██    ██",
    "  ██   ██ ███████    ██    ██   ██  ██████ ",
    "",
    "        RETRO TERMINAL MESSENGER v1.0",
]


class RetroMessengerUI:
    def __init__(self, state, app_factory,
                 save_contacts, save_chats):

        self.state = state
        self.app_factory = app_factory
        self.save_contacts = save_contacts
        self.save_chats = save_chats

        self.network = None
        self.renderer = None
        self.input_controller = None

    # =========================
    # START
    # =========================

    def start(self):
        try:
            curses.wrapper(self._main)
        except KeyboardInterrupt:
            pass
        finally:
            self._persist_clean_data()
    # =========================
    # MAIN
    # =========================

    def _main(self, stdscr):
        curses.curs_set(1)
        stdscr.keypad(True)

        # Old Welcome Screen
        client_id = self._welcome_screen(stdscr)
        self.state.initialize_user(client_id)

        stdscr.nodelay(True)
        stdscr.timeout(100)

        # Setup Components
        self.renderer = Renderer(stdscr, self.state)

        self.network = NetworkWorker(
            self.state,
            self.app_factory
        )
        self.network.start()

        self.input_controller = InputController(
            self.state,
            self.network.send
        )

        # Main Loop
        last_redraw = time.time()

        while self.state.running:
            now = time.time()

            # Periodic redraw
            if now - last_redraw >= 0.5:
                self.renderer.draw()
                last_redraw = now

            ch = stdscr.getch()
            if ch != -1:
                self.input_controller.handle(ch)
                self.renderer.draw()

        # Clean shutdown
        self._persist_clean_data()

    # =========================
    # WELCOME SCREEN
    # =========================

    def _welcome_screen(self, stdscr):
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        box_width = min(80, w - 4)
        box_height = 18
        sy = (h - box_height) // 2
        sx = (w - box_width) // 2

        # Border (cyan like old version)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(5, curses.COLOR_WHITE, -1)
        curses.init_pair(1, curses.COLOR_GREEN, -1)

        stdscr.attron(curses.color_pair(2))
        stdscr.addstr(sy, sx, "+" + "-"*(box_width-2) + "+")
        for i in range(1, box_height-1):
            stdscr.addstr(sy+i, sx, "|")
            stdscr.addstr(sy+i, sx+box_width-1, "|")
        stdscr.addstr(sy+box_height-1, sx,
                      "+" + "-"*(box_width-2) + "+")
        stdscr.attroff(curses.color_pair(2))

        # Banner
        for i, line in enumerate(WELCOME_BANNER):
            stdscr.addstr(sy+2+i,
                          sx + (box_width - len(line))//2,
                          line,
                          curses.color_pair(2) | curses.A_BOLD)

        # Intro text (exact original vibe)
        intro = [
            "",
            "Hi! This is Navin's implementation of the client side",
            "of the messenger app made in lieu of EE5150.",
            "",
            "A note: the terminal UI has been made using ncurses",
            "(and a painful amount of AI prompting)",
        ]

        banner_start = sy + 2
        banner_end = banner_start + len(WELCOME_BANNER)
        intro_start = banner_end + 1

        for i, line in enumerate(intro):
            stdscr.addstr(intro_start + i,
                          sx + (box_width - len(line)) // 2,
                          line,
                          curses.color_pair(5))

        # Prompt
        prompt = "Enter Client ID [1 to 1000]: "
        prompt_y = intro_start + len(intro) + 1

        stdscr.addstr(prompt_y,
                      sx + (box_width - len(prompt)) // 2,
                      prompt,
                      curses.color_pair(1) | curses.A_BOLD)

        curses.echo()
        stdscr.refresh()

        cid_str = stdscr.getstr().decode().strip()
        curses.noecho()

        try:
            cid = int(cid_str)
        except ValueError:
            self.state.show_error("Invalid contact ID. Starting as user 1.")
            cid = 1

        stdscr.clear()
        stdscr.refresh()

        return cid

    # =========================
    # PERSISTENCE (FILTERED)
    # =========================

    def _persist_clean_data(self):
        # Remove unsent before saving
        for user_id, conversations in self.state.chats.items():
            for contact_id in conversations:
                conversations[contact_id] = [
                    msg for msg in conversations[contact_id]
                    if msg[0] in ("in", "out")
                ]

        self.save_contacts()
        self.save_chats()