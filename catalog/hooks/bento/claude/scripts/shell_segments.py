#!/usr/bin/env python3
"""Stdlib-only, best-effort POSIX-shell "simple command" segmenter.

`command_segments(command)` returns one argv list per simple command found
in `command`: quotes are removed, wrapper/env prefixes are NOT stripped here
(see `strip_wrapper_prefix` for that), and command substitutions ($(...) and
backticks) are recursively segmented too, since their bodies really run.

This is a character-level scanner, not a full shell grammar -- it is built to
never *invent* a command that is not really there (the failure mode of a
naive `re.split` + `shlex.split` pipeline, which matches text inside quotes
and heredoc bodies). Where real bash semantics would require tracking state
this scanner does not model, it raises `SegmentError` and the caller is
expected to fail open (never block), same trust model as before.

Known limits (can *hide* a real command, never invent one):

- The body of `bash -c '...'`, `eval "..."`, and a heredoc fed to a nested
  shell (`bash <<EOF ... EOF`) is not parsed -- only $(...), backticks and
  <(...)/>(...)  bodies are, since those are the constructs whose contents
  provably run as part of *this* command line.
- A `cd` in an earlier segment does not change how later paths are resolved.
- `${...}` (parameter expansion) and `$((...))` (arithmetic expansion) are
  treated as fully opaque text -- a command substitution nested inside one of
  them (e.g. `${v:-$(git merge x)}`) is not seen.
- `case ... esac` pattern tracking used while matching a `$(...)` span is a
  heuristic (keyword-boundary based), not a real shell parser; a variable
  literally named `case` or `esac` used as an ordinary word can confuse it.
"""

from __future__ import annotations

MAX_DEPTH = 8


class SegmentError(ValueError):
    """Raised when the scanner hits shell structure it does not model."""


_KEYWORD_CHARS = None  # placeholder for readability; see _WORD_BREAK below


def _is_word_break(ch: str) -> bool:
    return ch in " \t\r\n;&|()<>{}"


def _find_unescaped(s: str, start: int, target: str) -> int:
    """Find `target` (a single char) in s[start:], honoring backslash escapes.

    Does not descend into nested quotes/substitutions -- only used for
    contexts (backticks) where that is the correct, simple behavior.
    """
    i = start
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == target:
            return i
        i += 1
    return -1


class _Matcher:
    """Shared balanced-span matcher for $(...), ${...}, $((...)), (...), {...}.

    Given the index of an opening character, returns the index of the
    matching closing character, honoring quotes, nested substitutions, and
    (for parenthesis matching) `case ... esac` pattern-terminator `)`s that
    are not real nesting.
    """

    def __init__(self, s: str, depth: int) -> None:
        self.s = s
        self.n = len(s)
        self.depth = depth

    def _check_depth(self) -> None:
        if self.depth > MAX_DEPTH:
            raise SegmentError("substitution nesting too deep")

    def skip_single_quote(self, i: int) -> int:
        end = self.s.find("'", i + 1)
        if end == -1:
            raise SegmentError("unterminated single quote")
        return end + 1

    def skip_ansi_c_quote(self, i: int) -> int:
        # s[i] == "'" and s[i-1] == "$" (caller positions us at the quote).
        j = i + 1
        n = self.n
        while j < n:
            c = self.s[j]
            if c == "\\" and j + 1 < n:
                j += 2
                continue
            if c == "'":
                return j + 1
            j += 1
        raise SegmentError("unterminated $'...' quote")

    def skip_double_quote(self, i: int) -> int:
        j = i + 1
        n = self.n
        while j < n:
            c = self.s[j]
            if c == "\\" and j + 1 < n:
                j += 2
                continue
            if c == '"':
                return j + 1
            if c == "$" and j + 1 < n and self.s[j + 1] == "(":
                j = self.match_dollar_paren(j)
                continue
            if c == "`":
                j = self.skip_backtick(j)
                continue
            j += 1
        raise SegmentError("unterminated double quote")

    def skip_backtick(self, i: int) -> int:
        end = _find_unescaped(self.s, i + 1, "`")
        if end == -1:
            raise SegmentError("unterminated backtick")
        return end + 1

    def match_dollar_paren(self, dollar_idx: int) -> int:
        """s[dollar_idx:dollar_idx+2] == '$('. Returns index just past the
        matching ')' (handling the $((...)) arithmetic case too)."""
        self.depth += 1
        self._check_depth()
        if self.s[dollar_idx + 2 : dollar_idx + 3] == "(":
            end = self._match_parens(dollar_idx + 3, start_depth=2)
        else:
            end = self._match_parens(dollar_idx + 2, start_depth=1)
        self.depth -= 1
        return end

    def match_dollar_brace(self, dollar_idx: int) -> int:
        """s[dollar_idx:dollar_idx+2] == '${'. Returns index just past the
        matching '}'."""
        self.depth += 1
        self._check_depth()
        end = self._match_braces(dollar_idx + 2, start_depth=1)
        self.depth -= 1
        return end

    def _match_parens(self, i: int, start_depth: int) -> int:
        depth = start_depth
        case_pending: list[int] = []
        word_start = i
        n = self.n
        while i < n:
            c = self.s[i]
            if c == "\\" and i + 1 < n:
                i += 2
                word_start = i
                continue
            if c == "'":
                if i > 0 and self.s[i - 1] == "$":
                    i = self.skip_ansi_c_quote(i)
                else:
                    i = self.skip_single_quote(i)
                word_start = i
                continue
            if c == '"':
                i = self.skip_double_quote(i)
                word_start = i
                continue
            if c == "`":
                i = self.skip_backtick(i)
                word_start = i
                continue
            if c == "$" and i + 1 < n and self.s[i + 1] == "(":
                i = self.match_dollar_paren(i)
                word_start = i
                continue
            if c == "$" and i + 1 < n and self.s[i + 1] == "{":
                i = self.match_dollar_brace(i)
                word_start = i
                continue
            if _is_word_break(c) or c in "()":
                word = self.s[word_start:i]
                if word == "case":
                    case_pending.append(depth)
                elif word == "esac" and case_pending and case_pending[-1] == depth:
                    case_pending.pop()
                if c == "(":
                    depth += 1
                    i += 1
                    word_start = i
                    continue
                if c == ")":
                    if case_pending and case_pending[-1] == depth:
                        # a case-pattern terminator, not real nesting.
                        i += 1
                        word_start = i
                        continue
                    depth -= 1
                    i += 1
                    if depth <= 0:
                        return i
                    word_start = i
                    continue
                i += 1
                word_start = i
                continue
            i += 1
        raise SegmentError("unterminated parenthesis/substitution")

    def _match_braces(self, i: int, start_depth: int) -> int:
        depth = start_depth
        n = self.n
        while i < n:
            c = self.s[i]
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == "'":
                if i > 0 and self.s[i - 1] == "$":
                    i = self.skip_ansi_c_quote(i)
                else:
                    i = self.skip_single_quote(i)
                continue
            if c == '"':
                i = self.skip_double_quote(i)
                continue
            if c == "`":
                i = self.skip_backtick(i)
                continue
            if c == "$" and i + 1 < n and self.s[i + 1] == "(":
                i = self.match_dollar_paren(i)
                continue
            if c == "$" and i + 1 < n and self.s[i + 1] == "{":
                i = self.match_dollar_brace(i)
                continue
            if c == "{":
                depth += 1
                i += 1
                continue
            if c == "}":
                depth -= 1
                i += 1
                if depth <= 0:
                    return i
                continue
            i += 1
        raise SegmentError("unterminated ${...}")


def _segment(command: str, depth: int) -> tuple[list[list[str]], list[list[str]]]:
    """Returns (segments, extra_segments_from_substitutions)."""
    if depth > MAX_DEPTH:
        raise SegmentError("substitution nesting too deep")
    matcher = _Matcher(command, depth)
    s = command
    n = len(s)
    i = 0

    segments: list[list[str]] = []
    extra: list[list[str]] = []
    words: list[str] = []
    cur: list[str] | None = None
    pending_heredocs: list[tuple[str, bool]] = []  # (delimiter, strip_tabs)
    bracket_depth = 0  # count of open, unmatched '[[' words (a [[ ... ]] test)

    def start_word() -> None:
        nonlocal cur
        if cur is None:
            cur = []

    def append_lit(text: str) -> None:
        start_word()
        assert cur is not None
        cur.append(text)

    def end_word() -> None:
        nonlocal cur, bracket_depth
        if cur is not None:
            word = "".join(cur)
            words.append(word)
            cur = None
            # Inside [[ ... ]], '(' is extended-pattern/grouping syntax, not
            # a subshell -- nothing in it ever runs. Track nesting by whole
            # word so a bare "[[" or "]]" elsewhere in a word (e.g. inside a
            # quoted string, already opaque by the time we get here) never
            # trips this.
            if word == "[[":
                bracket_depth += 1
            elif word == "]]" and bracket_depth > 0:
                bracket_depth -= 1

    def end_segment() -> None:
        nonlocal words
        end_word()
        if words:
            segments.append(words)
        words = []

    def consume_heredocs_after_newline(i: int) -> int:
        # s[i-1] == '\n' logically; process queued heredoc bodies in order.
        nonlocal pending_heredocs
        for delim, strip_tabs in pending_heredocs:
            while True:
                nl = s.find("\n", i)
                line_end = nl if nl != -1 else n
                line = s[i:line_end]
                check = line.lstrip("\t") if strip_tabs else line
                if check == delim:
                    i = line_end + 1 if nl != -1 else n
                    break
                if nl == -1:
                    i = n
                    break
                i = nl + 1
        pending_heredocs = []
        return i

    while i < n:
        c = s[i]

        # 1. backslash + newline: line continuation.
        if c == "\\" and i + 1 < n and s[i + 1] == "\n":
            i += 2
            continue
        # 2. backslash + other char: literal.
        if c == "\\" and i + 1 < n:
            append_lit(s[i + 1])
            i += 2
            continue
        if c == "\\":
            append_lit(c)
            i += 1
            continue

        # 3. single quote.
        if c == "'":
            end = s.find("'", i + 1)
            if end == -1:
                raise SegmentError("unterminated single quote")
            append_lit(s[i + 1 : end])
            i = end + 1
            continue

        # ANSI-C quoting: $'...'. Kept verbatim (like ${...}), backslash
        # escapes only affect where the closing quote is found.
        if c == "$" and i + 1 < n and s[i + 1] == "'":
            j = i + 2
            while True:
                if j >= n:
                    raise SegmentError("unterminated $'...' quote")
                cj = s[j]
                if cj == "\\" and j + 1 < n:
                    j += 2
                    continue
                if cj == "'":
                    j += 1
                    break
                j += 1
            append_lit(s[i:j])
            i = j
            continue

        # 4. double quote.
        if c == '"':
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise SegmentError("unterminated double quote")
                cj = s[j]
                if cj == "\\" and j + 1 < n and s[j + 1] in ('"', "\\", "$", "`", "\n"):
                    if s[j + 1] == "\n":
                        j += 2
                        continue
                    buf.append(s[j + 1])
                    j += 2
                    continue
                if cj == '"':
                    j += 1
                    break
                if cj == "$" and j + 1 < n and s[j + 1] == "(":
                    end = matcher.match_dollar_paren(j)
                    text = s[j:end]
                    buf.append(text)
                    if text.startswith("$(") and not text.startswith("$(("):
                        sub_segs, sub_extra = _segment(text[2:-1], depth + 1)
                        extra.extend(sub_segs)
                        extra.extend(sub_extra)
                    elif text.startswith("$(("):
                        pass  # arithmetic: opaque
                    j = end
                    continue
                if cj == "$" and j + 1 < n and s[j + 1] == "{":
                    end = matcher.match_dollar_brace(j)
                    buf.append(s[j:end])
                    j = end
                    continue
                if cj == "`":
                    end = _find_unescaped(s, j + 1, "`")
                    if end == -1:
                        raise SegmentError("unterminated backtick")
                    text = s[j : end + 1]
                    buf.append(text)
                    inner = text[1:-1].replace("\\`", "`").replace('\\"', '"').replace("\\$", "$").replace("\\\\", "\\")
                    sub_segs, sub_extra = _segment(inner, depth + 1)
                    extra.extend(sub_segs)
                    extra.extend(sub_extra)
                    j = end + 1
                    continue
                buf.append(cj)
                j += 1
            append_lit("".join(buf))
            i = j
            continue

        # 12. Expansions (outside quotes).
        if c == "$" and i + 1 < n and s[i + 1] == "(":
            end = matcher.match_dollar_paren(i)
            text = s[i:end]
            append_lit(text)
            if text.startswith("$((") and text.endswith("))"):
                pass  # arithmetic: opaque
            else:
                sub_segs, sub_extra = _segment(text[2:-1], depth + 1)
                extra.extend(sub_segs)
                extra.extend(sub_extra)
            i = end
            continue
        if c == "$" and i + 1 < n and s[i + 1] == "{":
            end = matcher.match_dollar_brace(i)
            append_lit(s[i:end])
            i = end
            continue
        if c == "`":
            end = _find_unescaped(s, i + 1, "`")
            if end == -1:
                raise SegmentError("unterminated backtick")
            text = s[i : end + 1]
            append_lit(text)
            inner = text[1:-1].replace("\\`", "`").replace('\\"', '"').replace("\\$", "$").replace("\\\\", "\\")
            sub_segs, sub_extra = _segment(inner, depth + 1)
            extra.extend(sub_segs)
            extra.extend(sub_extra)
            i = end + 1
            continue

        # Array literal: name=( or name+=( opens opaque text to matching ).
        if c == "(" and cur is not None:
            word_so_far = "".join(cur)
            if word_so_far.endswith("=") and _is_assignment_prefix(word_so_far):
                close = matcher._match_parens(i + 1, start_depth=1)
                # drop the array literal entirely from the word (invents nothing,
                # matches corpus row 37: arr=(git merge x) -> word is dropped).
                cur = None
                i = close
                continue

        # 5. comment, only when no word is in progress.
        if c == "#" and cur is None:
            nl = s.find("\n", i)
            i = nl if nl != -1 else n
            continue

        # 6. space/tab/CR: end word.
        if c in " \t\r":
            end_word()
            i += 1
            continue

        # 7. newline: end word, emit separator, drop heredoc bodies.
        if c == "\n":
            end_segment()
            i += 1
            if pending_heredocs:
                i = consume_heredocs_after_newline(i)
            continue

        # 8. here-string <<<
        if c == "<" and s[i : i + 3] == "<<<":
            append_lit("<<<")
            i += 3
            continue

        # 9. heredoc << or <<-
        if c == "<" and s[i : i + 2] == "<<":
            strip_tabs = False
            j = i + 2
            if j < n and s[j] == "-":
                strip_tabs = True
                j += 1
            while j < n and s[j] in " \t":
                j += 1
            delim_start = j
            if j < n and s[j] == "'":
                end = s.find("'", j + 1)
                if end == -1:
                    raise SegmentError("unterminated heredoc delimiter quote")
                delim = s[j + 1 : end]
                j = end + 1
            elif j < n and s[j] == '"':
                end = s.find('"', j + 1)
                if end == -1:
                    raise SegmentError("unterminated heredoc delimiter quote")
                delim = s[j + 1 : end]
                j = end + 1
            else:
                dstart = j
                while j < n and not _is_word_break(s[j]):
                    if s[j] == "\\" and j + 1 < n:
                        j += 2
                    else:
                        j += 1
                delim = s[dstart:j].replace("\\", "")
            end_word()
            if delim:
                pending_heredocs.append((delim, strip_tabs))
            i = j
            continue

        # 10. & directly after > or <, or & followed by >: word char.
        if c == "&" and ((i > 0 and s[i - 1] in "><") or (i + 1 < n and s[i + 1] == ">")):
            append_lit(c)
            i += 1
            continue

        # 11. operators: &&, ||, ;;, |&, ;, &, |
        matched_op = None
        for op in ("&&", "||", ";;", "|&"):
            if s[i : i + len(op)] == op:
                matched_op = op
                break
        if matched_op is None and c in ";&|":
            matched_op = c
        if matched_op is not None:
            end_segment()
            i += len(matched_op)
            continue

        # 13. leftover ( or ): grouping operator -- except inside [[ ... ]],
        # where '(' is extended-pattern/grouping syntax (e.g. `(git merge)`
        # as an alternation pattern after ==/!=), never a subshell: nothing
        # inside a [[ ]] test ever executes as a command.
        if c == "(" and bracket_depth > 0:
            close = matcher._match_parens(i + 1, start_depth=1)
            append_lit(s[i:close])
            i = close
            continue
        if c == "(":
            end_segment()
            close = matcher._match_parens(i + 1, start_depth=1)
            inner = s[i + 1 : close - 1]
            if depth + 1 > MAX_DEPTH:
                raise SegmentError("substitution nesting too deep")
            sub_segs, sub_extra = _segment(inner, depth + 1)
            segments.extend(sub_segs)
            extra.extend(sub_extra)
            i = close
            continue
        if c == ")":
            end_segment()
            i += 1
            continue
        if c == "{":
            end_word()
            append_lit("{")
            i += 1
            continue
        if c == "}":
            end_word()
            append_lit("}")
            i += 1
            continue

        if c in "<>":
            append_lit(c)
            i += 1
            continue

        # 14. any other character.
        append_lit(c)
        i += 1

    end_segment()

    # Strip standalone leading '{'/'!' and trailing '}' reserved-word tokens.
    for seg in segments + extra:
        if seg and seg[0] in ("{", "!"):
            seg.pop(0)
        if seg and seg[-1] == "}":
            seg.pop()

    segments = [seg for seg in segments if seg]
    extra = [seg for seg in extra if seg]
    return segments, extra


def _is_assignment_prefix(word: str) -> bool:
    # word ends with '=' already (caller checked). Strip the trailing '=' and
    # an optional trailing '+' (for +=), then check it looks like NAME.
    body = word[:-1]
    if body.endswith("+"):
        body = body[:-1]
    return bool(body) and (body[0].isalpha() or body[0] == "_") and all(
        ch.isalnum() or ch == "_" for ch in body
    )


_ASSIGNMENT_RE_PREFIX_CHARS = set("=")


def _is_assignment_token(token: str) -> bool:
    eq = token.find("=")
    if eq <= 0:
        return False
    name = token[:eq]
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


def strip_wrapper_prefix(segment: list[str]) -> tuple[dict[str, str], list[str]]:
    """Repeatedly strip VAR=value, rtk, exec, command, and env prefixes.

    Returns (env_assignments, remaining_argv). env_assignments collects every
    VAR=value token stripped this way (from a bare leading run and from
    `env`'s own VAR=value arguments), keyed by name, last write wins.
    """
    tokens = list(segment)
    env: dict[str, str] = {}
    changed = True
    while changed and tokens:
        changed = False
        while tokens and _is_assignment_token(tokens[0]):
            name, _, value = tokens[0].partition("=")
            env[name] = value
            tokens.pop(0)
            changed = True
        if tokens and tokens[0] == "rtk":
            tokens.pop(0)
            changed = True
            continue
        if tokens and tokens[0] == "exec":
            tokens.pop(0)
            changed = True
            continue
        if tokens and tokens[0] == "command" and (len(tokens) < 2 or not tokens[1].startswith("-")):
            tokens.pop(0)
            changed = True
            continue
        if tokens and tokens[0] == "env":
            tokens.pop(0)
            changed = True
            while tokens and (
                _is_assignment_token(tokens[0]) or tokens[0] in ("-i",) or tokens[0] == "-u"
            ):
                if tokens[0] == "-u":
                    tokens.pop(0)
                    if tokens:
                        tokens.pop(0)
                    continue
                if _is_assignment_token(tokens[0]):
                    name, _, value = tokens[0].partition("=")
                    env[name] = value
                tokens.pop(0)
            continue
    return env, tokens


def command_segments_with_env(command: str) -> list[tuple[dict[str, str], list[str]]]:
    """Like command_segments, but each segment is paired with the
    VAR=value assignments stripped from its wrapper prefix."""
    segments, extra = _segment(command, depth=0)
    result = [strip_wrapper_prefix(seg) for seg in segments + extra]
    return [(env, argv) for env, argv in result if argv]


def command_segments(command: str) -> list[list[str]]:
    """Parse `command` into one argv list per simple command, with wrapper
    prefixes (VAR=value runs, `rtk`, `exec`, `command`, `env ...`) already
    stripped from the front of each one.

    Raises SegmentError on shell structure this scanner does not model; the
    caller should treat that as "fail open" (cannot rule out a hidden git
    invocation, but also invents nothing).
    """
    return [argv for _env, argv in command_segments_with_env(command)]
