"""Check that every API call in the Flutter apps has a matching backend route.

    python scripts/check_contract.py ../../Brainbox-Mobile/BrAInBox_Mobile
    python scripts/check_contract.py <frontend repo> --verbose     # also list matched calls

1. Loads the backend routes from `app.openapi()` (only `/api/v1/...`; the apps' base URL
   already ends in `/api/v1`).
2. Scans apps/mobile/lib, apps/admin/lib and packages/brainbox_core/lib in the frontend repo
   for `api.get/post/put/patch/delete('<path>')` calls (`upload` / `uploadBytes` count as
   POST). Skips *.g.dart and *.freezed.dart, and ignores comments.
   - `static const _base = '/learn'` (any `static const` string) is resolved inside the file.
   - `$var` / `${expr}` inside a path is a path parameter: it matches `{param}` in a route.
   - A private helper that passes its `String path` argument straight to `api.get(path)` (e.g.
     `_cached(path)`, `_list(path)`) is followed: the calls to that helper are checked instead.
   - A `switch` / `?:` that picks between path literals checks every literal.
3. Prints every call with no matching route and exits 1 if there are any (0 if none, 2 if the
   folder is wrong).

Paths built at runtime that can't match a `{param}` route go in ALLOWED_UNMATCHED below,
each with a comment explaining why the call is fine.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

API_PREFIX = "/api/v1"
SCAN_DIRS = ("apps/mobile/lib", "apps/admin/lib", "packages/brainbox_core/lib")
SKIP_SUFFIXES = (".g.dart", ".freezed.dart")
# ApiClient method -> HTTP method (packages/brainbox_core/lib/api/api_client.dart)
CLIENT_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "upload": "POST",
    "uploadBytes": "POST",
}
PARAM = "{}"  # how a $var / ${...} segment is shown in normalised paths

# (METHOD, normalised path as the script prints it) -> why it is fine.
ALLOWED_UNMATCHED: dict[tuple[str, str], str] = {
    # apps/admin/lib/features/analytics/data/analytics_repository.dart: `_get(part)` is only
    # called with 'overview', 'performance' and 'ai-usage', which are three fixed routes
    # (GET /admin/analytics/overview|performance|ai-usage), not one `{param}` route.
    ("GET", "/admin/analytics/{}"): "analytics part is overview|performance|ai-usage",
    # apps/admin/lib/features/content_review/data/content_review_repository.dart:
    # '/admin/content/$id/${approve ? 'approve' : 'reject'}' -> POST .../{item_id}/approve
    # and POST .../{item_id}/reject both exist.
    ("POST", "/admin/content/{}/{}"): "last segment is approve|reject",
    # apps/admin/lib/features/syllabus_manager/data/syllabus_manager_repository.dart:
    # '$_base/${kind.name}s/$id' with NodeKind {unit, topic, concept} -> PATCH
    # /admin/syllabus/units|topics|concepts/{id} all exist.
    ("PATCH", "/admin/syllabus/{}/{}"): "kind is units|topics|concepts",
}


# --------------------------------------------------------------------------- Dart scanning


@dataclass(frozen=True)
class DartString:
    """A string literal: `parts` are ("text", s) or ("interp", name-or-expression)."""

    start: int
    end: int  # index just after the closing quote
    parts: tuple[tuple[str, str], ...]


def _read_string(src: str, i: int) -> DartString:
    """Read the string literal starting at src[i] (a quote, or `r` before one)."""
    start = i
    raw = src[i] == "r"
    if raw:
        i += 1
    quote = src[i : i + 3] if src[i : i + 3] in ("'''", '"""') else src[i]
    i += len(quote)
    parts: list[tuple[str, str]] = []
    text: list[str] = []
    n = len(src)
    while i < n:
        if src.startswith(quote, i):
            i += len(quote)
            break
        ch = src[i]
        if ch == "\\" and not raw:
            text.append(src[i : i + 2])
            i += 2
        elif ch == "$" and not raw and i + 1 < n and src[i + 1] == "{":
            end = _skip_balanced(src, i + 1)  # index after the matching "}"
            if text:
                parts.append(("text", "".join(text)))
                text = []
            parts.append(("interp", src[i + 2 : end - 1].strip()))
            i = end
        elif ch == "$" and not raw and i + 1 < n and (src[i + 1].isalpha() or src[i + 1] == "_"):
            m = re.match(r"[A-Za-z_]\w*", src[i + 1 :])
            assert m
            if text:
                parts.append(("text", "".join(text)))
                text = []
            parts.append(("interp", m.group(0)))
            i += 1 + len(m.group(0))
        else:
            if ch == "\n" and len(quote) == 1:  # unterminated: stop at the end of the line
                break
            text.append(ch)
            i += 1
    if text:
        parts.append(("text", "".join(text)))
    return DartString(start, i, tuple(parts))


def _is_string_start(src: str, i: int) -> bool:
    if src[i] in "'\"":
        return True
    # r'raw' (but not the end of an identifier like `bar'`)
    return (
        src[i] == "r"
        and i + 1 < len(src)
        and src[i + 1] in "'\""
        and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_"))
    )


def _skip_balanced(src: str, i: int) -> int:
    """src[i] is ( [ or {; return the index after its partner (strings/comments aware)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[src[i]]]
    i += 1
    n = len(src)
    while i < n and stack:
        ch = src[i]
        if _is_string_start(src, i):
            i = _read_string(src, i).end
            continue
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i == -1 else i
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch == stack[-1]:
            stack.pop()
        i += 1
    return i


def blank_comments(src: str) -> str:
    """Replace comments with spaces (newlines kept, so offsets and line numbers still match)."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        if _is_string_start(src, i):
            i = _read_string(src, i).end
            continue
        if src.startswith("//", i):
            end = src.find("\n", i)
            end = n if end == -1 else end
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end == -1 else end + 2
        else:
            i += 1
            continue
        for k in range(i, end):
            if out[k] != "\n":
                out[k] = " "
        i = end
    return "".join(out)


def blank_strings(src: str) -> str:
    """Replace string bodies with spaces (quotes and offsets kept): code-only text to search."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        if _is_string_start(src, i):
            s = _read_string(src, i)
            for k in range(i + 1, s.end - 1):
                if out[k] != "\n":
                    out[k] = " "
            i = s.end
        else:
            i += 1
    return "".join(out)


def _strings_in(src: str, start: int, end: int) -> list[DartString]:
    """Every string literal in src[start:end], also inside brackets (a switch or a ?:)."""
    found, i = [], start
    while i < end:
        if _is_string_start(src, i):
            s = _read_string(src, i)
            found.append(s)
            i = s.end
        else:
            i += 1
    return found


def _first_argument(src: str, open_paren: int) -> tuple[int, int]:
    """(start, end) of the first argument of the call whose "(" is at open_paren."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    i = open_paren + 1
    n = len(src)
    while i < n:
        ch = src[i]
        if _is_string_start(src, i):
            i = _read_string(src, i).end
        elif ch in pairs:
            i = _skip_balanced(src, i)
        elif ch in ",)":
            return open_paren + 1, i
        else:
            i += 1
    return open_paren + 1, n


_GENERIC = r"(?:<(?:[^<>()]|<(?:[^<>()]|<[^<>()]*>)*>)*>)?"
_CONST_RE = re.compile(r"\bstatic\s+const\s+(?:String\s+)?([A-Za-z_]\w*)\s*=\s*")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


@dataclass
class Call:
    method: str
    path: str  # normalised, e.g. "/learn/topics/{}/notes"
    source: str  # the path as written in Dart
    file: str
    line: int


class _DartFile:
    def __init__(self, path: Path, rel: str):
        self.rel = rel
        self.src = blank_comments(path.read_text(encoding="utf-8"))
        # Same offsets, string bodies blanked too: regexes search this, so "api.get(" written
        # inside a string is not taken for a call.
        self.code = blank_strings(self.src)
        # (offset, name, value) of `static const name = '...'` strings in this file
        self.consts: list[tuple[int, str, DartString]] = []
        for m in _CONST_RE.finditer(self.code):
            if _is_string_start(self.src, m.end()):
                self.consts.append((m.start(), m.group(1), _read_string(self.src, m.end())))

    def line_of(self, offset: int) -> int:
        return self.src.count("\n", 0, offset) + 1

    def const(self, name: str, at: int) -> DartString | None:
        """The `static const name` nearest before `at` (else the first one after it)."""
        before = [c for c in self.consts if c[1] == name and c[0] <= at]
        if before:
            return before[-1][2]
        after = [c for c in self.consts if c[1] == name]
        return after[0][2] if after else None

    def render(self, s: DartString, at: int, depth: int = 0) -> str:
        """The literal as a URL path: consts filled in, every other $var / ${...} -> {}."""
        out = []
        for kind, value in s.parts:
            if kind == "text":
                out.append(value)
                continue
            const = self.const(value, at) if _IDENT_RE.fullmatch(value) else None
            out.append(self.render(const, at, depth + 1) if const and depth < 5 else "\x00")
        return "".join(out)

    def calls_of(self, name_re: str) -> list[tuple[int, int, int]]:
        """(call offset, first-arg start, first-arg end) for every call matching name_re."""
        found = []
        for m in re.finditer(rf"(?<![\w.]){name_re}\s*{_GENERIC}\s*\(", self.code):
            start, end = _first_argument(self.src, m.end() - 1)
            found.append((m.start(), start, end))
        return found

    def enclosing_function(self, param: str, at: int) -> str | None:
        """Name of the nearest function before `at` whose FIRST parameter is `String param`."""
        pattern = (
            rf"([A-Za-z_]\w*)\s*{_GENERIC}\s*\(\s*[\[{{]?\s*(?:required\s+)?String\??\s+{param}\b"
        )
        matches = list(re.finditer(pattern, self.code[:at]))
        return matches[-1].group(1) if matches else None


def _normalise(path: str) -> str:
    path = path.split("?", 1)[0].split("#", 1)[0]
    segments = [s for s in path.split("/") if s]
    return "/" + "/".join(PARAM if "\x00" in s else s for s in segments)


def _scan_file(dart: _DartFile) -> list[Call]:
    calls: list[Call] = []
    # Work list of (callee regex, HTTP method); helpers that forward `path` are added on the way.
    work = [(rf"api\s*\.\s*{name}", method) for name, method in CLIENT_METHODS.items()]
    seen: set[tuple[str, str]] = set()
    while work:
        callee, method = work.pop()
        if (callee, method) in seen:
            continue
        seen.add((callee, method))
        for at, start, end in dart.calls_of(callee):
            arg = dart.src[start:end].strip()
            line = dart.line_of(at)
            if not arg or re.fullmatch(r"(?:required\s+)?[\w<>?, ]+\s+\w+", arg):
                continue  # the helper's own definition (`_list<T>(String path, ...)`)
            strings = _strings_in(dart.src, start, end)
            if _IDENT_RE.fullmatch(arg):
                const = dart.const(arg, at)
                if const is not None:
                    strings = [const]
                else:
                    helper = dart.enclosing_function(arg, at)
                    if helper:
                        work.append((rf"{re.escape(helper)}", method))
                        continue
                    calls.append(Call(method, f"<unresolved: {arg}>", arg, dart.rel, line))
                    continue
            elif not strings:
                calls.append(Call(method, f"<unresolved: {arg}>", arg, dart.rel, line))
                continue
            # One literal (or adjacent 'a' 'b' literals) = one path; a switch/ternary = several.
            is_switch = not re.fullmatch(r"(?:\s|r?'[^']*'|r?\"[^\"]*\"|\+)*", _mask(arg))
            pieces = (
                [s for s in strings if dart.render(s, at).startswith("/")] if is_switch else [None]
            )
            for piece in pieces:
                rendered = (
                    dart.render(piece, at)
                    if piece is not None
                    else "".join(dart.render(s, at) for s in strings)
                )
                source = (
                    dart.src[piece.start : piece.end]
                    if piece is not None
                    else " ".join(dart.src[s.start : s.end] for s in strings)
                )
                calls.append(Call(method, _normalise(rendered), source, dart.rel, line))
    return calls


def _mask(arg: str) -> str:
    """The argument with each string literal's body replaced by x (so quotes inside vanish)."""
    out, i = [], 0
    while i < len(arg):
        if _is_string_start(arg, i):
            s = _read_string(arg, i)
            out.append("'x'")
            i = s.end
        else:
            out.append(arg[i])
            i += 1
    return "".join(out)


def scan_frontend(root: Path) -> list[Call]:
    calls: list[Call] = []
    for folder in SCAN_DIRS:
        for path in sorted((root / folder).rglob("*.dart")):
            if path.name.endswith(SKIP_SUFFIXES):
                continue
            rel = path.relative_to(root).as_posix()
            calls.extend(_scan_file(_DartFile(path, rel)))
    calls.sort(key=lambda c: (c.file, c.line, c.method, c.path))
    return calls


# --------------------------------------------------------------------------- matching


@dataclass(frozen=True)
class Route:
    path: str  # without /api/v1
    methods: frozenset[str]

    def matches(self, path: str) -> bool:
        want = [s for s in path.split("/") if s]
        have = [s for s in self.path.split("/") if s]
        for i, seg in enumerate(have):
            if seg.startswith("{") and seg.endswith(":path}"):
                return len(want) > i  # {name:path} takes the rest (one segment or more)
            if i >= len(want):
                return False
            if seg.startswith("{") and seg.endswith("}"):
                continue  # a route parameter matches a literal or a $var
            if want[i] != seg:
                return False
        return len(want) == len(have)


def load_routes(openapi: dict) -> list[Route]:
    routes = []
    for path, operations in openapi.get("paths", {}).items():
        if not (path == API_PREFIX or path.startswith(API_PREFIX + "/")):
            continue  # e.g. the legacy /exam/* routes; the apps always use /api/v1
        methods = frozenset(m.upper() for m in operations if m.lower() in _HTTP_METHODS)
        routes.append(Route(path[len(API_PREFIX) :] or "/", methods))
    return routes


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass
class Result:
    call: Call
    status: str  # "ok", "allowed", "missing", "wrong-method", "unresolved"
    note: str = ""


def check(
    calls: list[Call],
    routes: list[Route],
    allowed: dict[tuple[str, str], str] | None = None,
) -> list[Result]:
    allowed = ALLOWED_UNMATCHED if allowed is None else allowed
    results = []
    for call in calls:
        same_path = [r for r in routes if r.matches(call.path)]
        if any(call.method in r.methods for r in same_path):
            results.append(Result(call, "ok"))
        elif (call.method, call.path) in allowed:
            results.append(Result(call, "allowed", allowed[(call.method, call.path)]))
        elif call.path.startswith("<unresolved"):
            results.append(Result(call, "unresolved", "path is not a literal; add to allow-list"))
        elif same_path:
            has = sorted({m for r in same_path for m in r.methods})
            results.append(Result(call, "wrong-method", "route has " + ", ".join(has)))
        else:
            results.append(Result(call, "missing", "no route"))
    return results


def stale_allow_list(
    results: list[Result], allowed: dict[tuple[str, str], str] | None = None
) -> list[tuple[str, str]]:
    allowed = ALLOWED_UNMATCHED if allowed is None else allowed
    used = {(r.call.method, r.call.path) for r in results if r.status == "allowed"}
    return [key for key in allowed if key not in used]


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("frontend", type=Path, help="folder of the Flutter frontend repo")
    parser.add_argument("-v", "--verbose", action="store_true", help="also list matched calls")
    args = parser.parse_args(argv)

    root: Path = args.frontend.resolve()
    if not root.is_dir() or not any((root / d).is_dir() for d in SCAN_DIRS):
        print(f"error: {root} has none of {', '.join(SCAN_DIRS)}", file=sys.stderr)
        return 2

    from api.main import create_app

    routes = load_routes(create_app().openapi())
    calls = scan_frontend(root)
    results = check(calls, routes)
    bad = [r for r in results if r.status not in ("ok", "allowed")]

    for r in results:
        if r.status == "ok" and not args.verbose:
            continue
        mark = {"ok": "ok     ", "allowed": "ALLOWED"}.get(r.status, "MISSING")
        c = r.call
        note = f"  ({r.status}: {r.note})" if r.status != "ok" else ""
        print(f"{mark} {c.method:<6} {c.path:<55} {c.file}:{c.line}{note}")
    for method, path in stale_allow_list(results):
        print(f"note: allow-list entry {method} {path} is not used any more; remove it")

    counts = {s: sum(r.status == s for r in results) for s in ("ok", "allowed")}
    print(
        f"\n{len(results)} calls checked against {len(routes)} routes: "
        f"{counts['ok']} match, {counts['allowed']} allow-listed, {len(bad)} without a route."
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
