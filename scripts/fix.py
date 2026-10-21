#!/usr/bin/env python3
"""fix.py — rewrite AI-slop CSS toward human-crafted defaults (stdlib only).

Applies the inverse of each SLOP-00x detection rule:

    SLOP-001  border-radius > 24px        -> 10px
    SLOP-002  backdrop blur + translucent -> drop blur, solid background
    SLOP-003  colored glowing box-shadow  -> subtle neutral shadow
    SLOP-004  red-purple gradient         -> solid color (first usable stop)
    SLOP-005  dark-only page              -> append prefers-color-scheme: light block
    SLOP-006  oversized centered hero     -> 2.25rem, left-aligned
    SLOP-007  narrow single column        -> widen container to 72rem

Usage:
    python3 fix.py sloppy.html [--dry-run] [--in-place]
    python3 fix.py styles.css

By default writes <stem>.fixed.<ext> and keeps <stem>.bak.<ext>.
--in-place edits the file directly (still keeps .bak). --dry-run prints a diff.
No network, no dependencies, no LLM.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

# import detection helpers from sibling script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect import (  # noqa: E402
    extract_colors, is_purple_family, is_near_black, is_gray,
    px_values, font_size_px, strip_comments, strip_at_blocks,
    find_media_preludes,
)

NEUTRAL_SHADOW = "0 1px 2px rgba(0, 0, 0, 0.08)"
FALLBACK_SOLID = "#64748b"  # slate-500, neutral and readable on light/dark

CHANGES: list[str] = []


def note(msg: str):
    CHANGES.append(msg)


def _decl_repl(prop: str, func):
    """Build a regex sub that rewrites declarations of `prop` via func(value)->new."""
    pat = re.compile(r"(" + prop + r"\s*:\s*)([^;{}]+?)\s*(;)", re.IGNORECASE)

    def sub(m):
        old = m.group(2).strip()
        new = func(old)
        if new is None or new == old:
            return m.group(0)
        note(f"{prop}: '{old}' -> '{new}'")
        return m.group(1) + new + m.group(3)

    return pat, sub


def fix_radius(text: str) -> str:
    def fixval(v):
        big = [x for x in px_values(v) if x > 24]
        if not big:
            return None
        return "10px"
    for prop in ("border-radius", "border-top-left-radius", "border-top-right-radius",
                 "border-bottom-left-radius", "border-bottom-right-radius"):
        pat, sub = _decl_repl(prop, fixval)
        text = pat.sub(sub, text)
    return text


def fix_glass(text: str) -> str:
    # drop backdrop-filter blur
    pat = re.compile(r"backdrop-filter\s*:\s*[^;{}]*blur\([^;{}]*\)[^;{}]*;", re.IGNORECASE)

    def sub(m):
        note("removed backdrop-filter blur (glassmorphism)")
        return ""
    text = pat.sub(sub, text)

    # rgba low-alpha background -> solid: keep rgb channels, alpha -> 1
    def solidify(v):
        def repl(m):
            args = m.group(1)
            parts = [p.strip() for p in re.split(r"[,/\s]+", args)
                     if p.strip() and p.strip() != "/"]
            if len(parts) >= 4:
                try:
                    if float(parts[3]) < 0.5:
                        note(f"solidified translucent background '{m.group(0)}'")
                        return f"rgb({parts[0]}, {parts[1]}, {parts[2]})"
                except ValueError:
                    pass
            return m.group(0)
        return re.sub(r"rgba\(\s*([^)]+)\)", repl, v, flags=re.IGNORECASE)

    for prop in ("background", "background-color"):
        pat, sub2 = _decl_repl(prop, solidify)
        text = pat.sub(sub2, text)
    return text


def fix_glow(text: str) -> str:
    def fixval(v):
        if v.strip().lower() == "none":
            return None
        cols = extract_colors(v)
        if any(not is_gray(c) for c in cols):
            return NEUTRAL_SHADOW
        return None
    pat, sub = _decl_repl("box-shadow", fixval)
    return pat.sub(sub, text)


def fix_gradient(text: str) -> str:
    def fixval(v):
        if not re.search(r"(linear|radial|conic)-gradient", v, re.IGNORECASE):
            return None
        cols = extract_colors(v)
        if not any(is_purple_family(c) for c in cols):
            return None
        # prefer the first non-purple stop color as the solid replacement
        for m in re.finditer(
                r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)|\b[a-zA-Z]+\b)", v):
            tok = m.group(1)
            c = extract_colors(tok)
            if c and not is_purple_family(c[0]):
                return tok
        return FALLBACK_SOLID
    for prop in ("background", "background-image"):
        pat, sub = _decl_repl(prop, fixval)
        text = pat.sub(sub, text)
    return text


def _scope_hero_blocks(text: str):
    """Yield (start, end, selector, body) for rule blocks whose selector is hero/h1."""
    out = []
    for m in re.finditer(r"([^{}]+?)\{([^{}]*)\}", text):
        selector = m.group(1).strip()
        s = selector.lower()
        if "hero" in s or re.search(r"(?<![\w-])h1(?![\w-])", s):
            out.append((m.start(), m.end(), selector, m.group(2)))
    return out


def fix_hero(text: str) -> str:
    # font-size on hero/h1 rules -> 2.25rem when oversized
    def fixval(v):
        px = font_size_px(v)
        if px is not None and px >= 48:
            return "2.25rem"
        return None
    # apply only inside hero/h1 rule blocks
    blocks = _scope_hero_blocks(text)
    if not blocks:
        return text
    # rebuild from the end so offsets stay valid
    for start, end, selector, body in reversed(blocks):
        pat, sub = _decl_repl("font-size", fixval)
        new_body = pat.sub(sub, body)
        # text-align: center -> left inside hero/h1
        pat2 = re.compile(r"(text-align\s*:\s*)center(\s*;)", re.IGNORECASE)

        def sub2(m):
            note(f"{selector}: text-align center -> left")
            return m.group(1) + "left" + m.group(2)
        new_body = pat2.sub(sub2, new_body)
        if new_body != body:
            text = text[:start] + selector + " {" + new_body + "}" + text[end:]
    return text


def fix_container(text: str) -> str:
    def fixval(v):
        pxs = px_values(v)
        rems = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)rem", v)]
        width = max(pxs) if pxs else (max(rems) * 16 if rems else None)
        if width is not None and width < 720:
            return "72rem"
        return None
    pat, sub = _decl_repl("max-width", fixval)
    return pat.sub(sub, text)


LIGHT_BLOCK = """
/* de-slop-skill: light-mode override (SLOP-005 fix) */
@media (prefers-color-scheme: light) {
  body {
    background: #ffffff;
    color: #111827;
  }
}
"""


def fix_dark_only(text: str) -> str:
    preludes = find_media_preludes(text)
    if any("prefers-color-scheme" in p.lower() for p in preludes):
        return text  # already has a light path
    # only add if there is a near-black body/html background
    body_bg = re.compile(
        r"(?<![\w-])(body|html|:root)[^{]*\{[^{}]*"
        r"background(?:-color)?\s*:\s*([^;{}]+);", re.IGNORECASE)
    dark = False
    for m in body_bg.finditer(text):
        cols = extract_colors(m.group(2))
        if cols and all(is_near_black(c) for c in cols):
            dark = True
            break
    if not dark:
        return text
    note("appended prefers-color-scheme: light override block")
    text = text.rstrip() + "\n" + LIGHT_BLOCK
    return text


def fix_text(text: str) -> str:
    CHANGES.clear()
    text = fix_radius(text)
    text = fix_glass(text)
    text = fix_glow(text)
    text = fix_gradient(text)
    text = fix_hero(text)
    text = fix_container(text)
    text = fix_dark_only(text)
    return text


def process_file(path: Path, dry_run: bool, in_place: bool):
    original = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".css":
        fixed = fix_text(original)
    else:
        # rewrite inside <style> blocks and inline styles of HTML
        def style_block(m):
            inner = m.group(1)
            return m.group(0).replace(inner, fix_text(inner), 1)
        fixed = re.sub(r"(<style[^>]*>)(.*?)(</style>)",
                       lambda m: m.group(1) + fix_text(m.group(2)) + m.group(3),
                       original, flags=re.IGNORECASE | re.DOTALL)

        def inline_style(m):
            quote = m.group(2)
            return m.group(1) + fix_text(m.group(3)) + quote
        fixed = re.sub(r"""(style\s*=\s*)(['"])(.*?)\2""", inline_style,
                       fixed, flags=re.IGNORECASE | re.DOTALL)

    if fixed == original:
        print(f"{path}: no slop rewrites applied.")
        return False

    if dry_run:
        diff = difflib.unified_diff(original.splitlines(), fixed.splitlines(),
                                    fromfile=str(path), tofile=str(path) + " (fixed)",
                                    lineterm="")
        print("\n".join(diff))
    else:
        bak = path.with_name(path.stem + ".bak" + path.suffix)
        bak.write_text(original, encoding="utf-8")
        if in_place:
            out = path
        else:
            out = path.with_name(path.stem + ".fixed" + path.suffix)
        out.write_text(fixed, encoding="utf-8")
        print(f"{path}: wrote {out} (backup: {bak})")
    print(f"  changes ({len(CHANGES)}):")
    for c in CHANGES:
        print(f"   - {c}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rewrite AI-slop CSS toward human defaults.")
    ap.add_argument("paths", nargs="+", help="HTML and/or CSS files to fix")
    ap.add_argument("--dry-run", action="store_true", help="Print diff, change nothing")
    ap.add_argument("--in-place", action="store_true",
                    help="Edit files directly (default writes *.fixed.*)")
    args = ap.parse_args(argv)
    changed = False
    for p in args.paths:
        path = Path(p)
        if not path.is_file():
            print(f"warning: not found: {path}", file=sys.stderr)
            continue
        changed |= process_file(path, args.dry_run, args.in_place)
    return 0


if __name__ == "__main__":
    sys.exit(main())
