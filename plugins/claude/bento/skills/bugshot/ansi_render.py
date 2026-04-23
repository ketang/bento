"""Convert text with ANSI escape sequences to styled HTML.

Supports SGR attributes (bold, dim, italic, underline, strikethrough,
inverse), 8/16 colors, 256-color, and 24-bit truecolor. Non-SGR
sequences (cursor movement, screen control, etc.) are stripped.
"""

import html
import re

# Standard 8-color palette (normal intensity)
COLORS_16 = [
    "#000000",  # 0 black
    "#c91b00",  # 1 red
    "#00c200",  # 2 green
    "#c7c400",  # 3 yellow
    "#0225c7",  # 4 blue
    "#c930c7",  # 5 magenta
    "#00c5c7",  # 6 cyan
    "#c7c7c7",  # 7 white
    "#686868",  # 8 bright black
    "#ff6e67",  # 9 bright red
    "#5ffa68",  # 10 bright green
    "#fffc67",  # 11 bright yellow
    "#6871ff",  # 12 bright blue
    "#ff77ff",  # 13 bright magenta
    "#60fdff",  # 14 bright cyan
    "#ffffff",  # 15 bright white
]

DEFAULT_FG = "#e0e0e0"
DEFAULT_BG = "#1a1a1a"

# Regex matching any ANSI escape sequence (CSI, OSC, etc.)
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;]*[A-Za-z]|\][^\x07]*\x07|\[[\x20-\x2f]*[\x40-\x7e])"
)

# Regex matching only SGR sequences: ESC [ <params> m
_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _color_256(n):
    """Return a hex color string for a 256-color palette index."""
    if n < 16:
        return COLORS_16[n]
    if n < 232:
        # 6x6x6 color cube
        n -= 16
        b = (n % 6) * 51
        n //= 6
        g = (n % 6) * 51
        r = (n // 6) * 51
        return f"#{r:02x}{g:02x}{b:02x}"
    # Grayscale ramp
    v = 8 + (n - 232) * 10
    return f"#{v:02x}{v:02x}{v:02x}"


class _State:
    """Tracks the current SGR state."""

    __slots__ = ("bold", "dim", "italic", "underline", "strikethrough",
                 "inverse", "fg", "bg")

    def __init__(self):
        self.reset()

    def reset(self):
        self.bold = False
        self.dim = False
        self.italic = False
        self.underline = False
        self.strikethrough = False
        self.inverse = False
        self.fg = None  # None means default
        self.bg = None

    def to_style(self):
        """Return a CSS style string for the current state, or empty string."""
        parts = []
        fg = self.fg or DEFAULT_FG
        bg = self.bg or DEFAULT_BG
        if self.inverse:
            fg, bg = bg, fg

        if fg != DEFAULT_FG:
            parts.append(f"color:{fg}")
        if bg != DEFAULT_BG:
            parts.append(f"background-color:{bg}")
        if self.bold:
            parts.append("font-weight:bold")
        if self.dim:
            parts.append("opacity:0.5")
        if self.italic:
            parts.append("font-style:italic")

        decorations = []
        if self.underline:
            decorations.append("underline")
        if self.strikethrough:
            decorations.append("line-through")
        if decorations:
            parts.append(f"text-decoration:{' '.join(decorations)}")

        return ";".join(parts)

    def __eq__(self, other):
        if not isinstance(other, _State):
            return NotImplemented
        return all(
            getattr(self, attr) == getattr(other, attr)
            for attr in self.__slots__
        )

    def copy(self):
        new = _State.__new__(_State)
        for attr in self.__slots__:
            setattr(new, attr, getattr(self, attr))
        return new


def _parse_sgr(params_str, state):
    """Apply SGR parameter string to state."""
    if not params_str:
        state.reset()
        return

    params = [int(p) if p else 0 for p in params_str.split(";")]
    i = 0
    while i < len(params):
        p = params[i]
        if p == 0:
            state.reset()
        elif p == 1:
            state.bold = True
        elif p == 2:
            state.dim = True
        elif p == 3:
            state.italic = True
        elif p == 4:
            state.underline = True
        elif p == 9:
            state.strikethrough = True
        elif p == 7:
            state.inverse = True
        elif p == 22:
            state.bold = False
            state.dim = False
        elif p == 23:
            state.italic = False
        elif p == 24:
            state.underline = False
        elif p == 27:
            state.inverse = False
        elif p == 29:
            state.strikethrough = False
        elif 30 <= p <= 37:
            state.fg = COLORS_16[p - 30]
        elif p == 38:
            # Extended foreground
            if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                state.fg = _color_256(params[i + 2])
                i += 2
            elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                r, g, b = params[i + 2], params[i + 3], params[i + 4]
                state.fg = f"#{r:02x}{g:02x}{b:02x}"
                i += 4
        elif p == 39:
            state.fg = None
        elif 40 <= p <= 47:
            state.bg = COLORS_16[p - 40]
        elif p == 48:
            # Extended background
            if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                state.bg = _color_256(params[i + 2])
                i += 2
            elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                r, g, b = params[i + 2], params[i + 3], params[i + 4]
                state.bg = f"#{r:02x}{g:02x}{b:02x}"
                i += 4
        elif p == 49:
            state.bg = None
        elif 90 <= p <= 97:
            state.fg = COLORS_16[p - 90 + 8]
        elif 100 <= p <= 107:
            state.bg = COLORS_16[p - 100 + 8]
        i += 1


def ansi_to_html(text):
    """Convert text with ANSI escape sequences to styled HTML.

    Returns a string of HTML with <span> elements carrying inline
    styles for colors and attributes. Intended to be placed inside
    a <pre> block.
    """
    if not text:
        return ""

    state = _State()
    prev_style = ""
    output = []
    in_span = False

    pos = 0
    for match in _ANSI_RE.finditer(text):
        start, end = match.span()

        # Emit text before this escape
        if start > pos:
            chunk = html.escape(text[pos:start])
            style = state.to_style()
            if style != prev_style:
                if in_span:
                    output.append("</span>")
                if style:
                    output.append(f'<span style="{style}">')
                    in_span = True
                else:
                    in_span = False
                prev_style = style
            output.append(chunk)

        # Process SGR sequences, strip everything else
        sgr_match = _SGR_RE.fullmatch(match.group())
        if sgr_match:
            _parse_sgr(sgr_match.group(1), state)

        pos = end

    # Emit remaining text
    if pos < len(text):
        chunk = html.escape(text[pos:])
        style = state.to_style()
        if style != prev_style:
            if in_span:
                output.append("</span>")
            if style:
                output.append(f'<span style="{style}">')
                in_span = True
            else:
                in_span = False
        output.append(chunk)

    if in_span:
        output.append("</span>")

    return "".join(output)
