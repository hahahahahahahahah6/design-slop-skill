#!/usr/bin/env python3
"""detect.py — deterministic AI-slop web design detector (stdlib only).

Scans HTML/CSS for the visual fingerprint of AI-generated pages:
giant border-radius, glassmorphism, glowing borders, red-purple gradients,
dark-mode-only, oversized centered hero titles, single long column.

Usage:
    python3 detect.py index.html [--json] [--fail-under SCORE]
    python3 detect.py styles.css page.html

Exit code 0 = clean, 1 = slop found.
No network, no dependencies, no LLM.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
from pathlib import Path

RULES = {
    "SLOP-001": {
        "name": "Giant border-radius",
        "weight": 10,
        "en": "border-radius over 24px on cards/buttons. AI default; humans use 6-12px.",
        "zh": "卡片/按钮圆角超过 24px。AI 的默认审美；人类手工设计一般用 6–12px。",
        "fix": "Clamp border-radius to 10px.",
    },
    "SLOP-002": {
        "name": "Glassmorphism",
        "weight": 10,
        "en": "backdrop-filter blur + translucent background (frosted glass card).",
        "zh": "毛玻璃卡片：backdrop-filter 模糊 + 半透明背景。",
        "fix": "Drop the blur; use a solid surface color.",
    },
    "SLOP-003": {
        "name": "Glowing border/shadow",
        "weight": 10,
        "en": "Colored glowing box-shadow (neon glow around cards/buttons).",
        "zh": "发光边框/阴影：带颜色的 box-shadow 光晕。",
        "fix": "Replace with a subtle neutral shadow or a plain 1px border.",
    },
    "SLOP-004": {
        "name": "Red-purple gradient",
        "weight": 20,
        "en": "linear-gradient with violet/magenta/purple stops — the signature AI palette.",
        "zh": "红紫渐变：linear-gradient 里出现紫/品红/红紫色 —— AI 网页的招牌配色。",
        "fix": "Replace with a solid color.",
    },
    "SLOP-005": {
        "name": "Dark-mode-only",
        "weight": 20,
        "en": "Pure/near-black body background with no light-mode path "
              "(no prefers-color-scheme, no theme toggle).",
        "zh": "纯黑/近黑背景却没有亮色模式（没有 prefers-color-scheme，也没有主题切换开关）。",
        "fix": "Add a prefers-color-scheme: light override and/or a theme toggle.",
    },
    "SLOP-006": {
        "name": "Oversized centered hero",
        "weight": 10,
        "en": "Hero/H1 title >= 48px and centered — the default AI landing layout.",
        "zh": "特大居中标题：Hero/H1 字号 ≥ 48px 且居中 —— AI 落地页的默认版式。",
        "fix": "Reduce to ~2.25rem and left-align on desktop.",
    },
    "SLOP-007": {
        "name": "Single long column",
        "weight": 10,
        "en": "One narrow max-width container, no grid or multi-column sections.",
        "zh": "一个长单栏：容器 max-width 很窄，且全站没有 grid/多栏布局。",
        "fix": "Widen the container and use grid/columns for content sections.",
    },
}

# ---------------------------------------------------------------- colors

NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255),
    "purple": (128, 0, 128), "violet": (238, 130, 238),
    "magenta": (255, 0, 255), "fuchsia": (255, 0, 255),
    "plum": (221, 160, 221), "orchid": (218, 112, 214),
    "mediumorchid": (186, 85, 211), "darkviolet": (148, 0, 211),
    "blueviolet": (138, 43, 226), "rebeccapurple": (102, 51, 153),
    "indigo": (75, 0, 130), "pink": (255, 192, 203),
    "hotpink": (255, 105, 180), "deeppink": (255, 20, 147),
}

HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
RGB_RE = re.compile(r"rgba?\(\s*([^)]+)\)", re.IGNORECASE)
WORD_RE = re.compile(r"\b([a-zA-Z]+)\b")


def _hex_to_rgb(h: str):
    h = h.lower()
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    h = h[:6]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _parse_rgb_args(args: str):
    parts = [p.strip() for p in re.split(r"[,/\s]+", args) if p.strip() and p.strip() != "/"]
    if len(parts) < 3:
        return None
    rgb = []
    for p in parts[:3]:
        if p.endswith("%"):
            try:
                rgb.append(round(float(p[:-1]) * 2.55))
            except ValueError:
                return None
        else:
            try:
                rgb.append(int(float(p)))
            except ValueError:
                return None
    return tuple(rgb)


def extract_colors(value: str):
    """Return list of (r, g, b) tuples found in a CSS value."""
    colors = []
    for m in HEX_RE.finditer(value):
        try:
            colors.append(_hex_to_rgb(m.group(1)))
        except ValueError:
            pass
    for m in RGB_RE.finditer(value):
        rgb = _parse_rgb_args(m.group(1))
        if rgb:
            colors.append(rgb)
    for m in WORD_RE.finditer(value):
        name = m.group(1).lower()
        if name in NAMED_COLORS:
            colors.append(NAMED_COLORS[name])
    return colors


def is_gray(rgb, tol=12):
    r, g, b = rgb
    return abs(r - g) <= tol and abs(g - b) <= tol and abs(r - b) <= tol


def is_purple_family(rgb):
    r, g, b = rgb
    if is_gray(rgb, tol=30):
        return False
    h, _l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    hue = h * 360
    return (265 <= hue <= 345) and s > 0.25


def is_near_black(rgb):
    return all(c <= 26 for c in rgb)


def has_low_alpha(value: str) -> bool:
    """rgba() with alpha < 0.5, 8/4-digit hex with low alpha, or 'transparent'."""
    for m in re.finditer(r"rgba\(\s*[^)]+\)", value, re.IGNORECASE):
        args = m.group(0)[5:-1]
        parts = [p.strip() for p in re.split(r"[,/\s]+", args) if p.strip() and p.strip() != "/"]
        if len(parts) >= 4:
            try:
                if float(parts[3]) < 0.5:
                    return True
            except ValueError:
                pass
    for m in HEX_RE.finditer(value):
        h = m.group(1).lower()
        if len(h) == 8:
            try:
                if int(h[6:8], 16) < 0x80:
                    return True
            except ValueError:
                pass
        elif len(h) == 4:
            try:
                if int(h[3] * 2, 16) < 0x80:
                    return True
            except ValueError:
                pass
    if re.search(r"\btransparent\b", value, re.IGNORECASE):
        return True
    return False


def px_values(value: str):
    return [float(n) for n in re.findall(r"(-?\d+(?:\.\d+)?)px", value)]


def font_size_px(value: str):
    """Best-effort conversion of a font-size value to px. None if unknown."""
    v = value.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)px", v)
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)rem", v)
    if m:
        return float(m.group(1)) * 16
    m = re.fullmatch(r"(\d+(?:\.\d+)?)em", v)
    if m:
        return float(m.group(1)) * 16
    m = re.fullmatch(r"(\d+(?:\.\d+)?)%", v)
    if m:
        return float(m.group(1)) / 100 * 16
    return None


# ---------------------------------------------------------------- parsing

MEDIA_BLOCK_RE = re.compile(r"@media\b[^{}]*\{", re.IGNORECASE)
AT_BLOCK_RE = re.compile(r"@(media|keyframes|supports|font-face|import)\b", re.IGNORECASE)


def strip_at_blocks(text: str):
    """Remove @media/@keyframes/etc blocks (balanced braces). Return (text, preludes)."""
    preludes = []
    out = []
    i = 0
    n = len(text)
    while i < n:
        m = AT_BLOCK_RE.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i:m.start()])
        # find opening brace
        j = text.find("{", m.start())
        semi = text.find(";", m.start())
        if j == -1 or (semi != -1 and semi < j):
            # e.g. @import ...; — no block
            out.append(text[m.start():semi + 1] if semi != -1 else text[m.start():])
            i = (semi + 1) if semi != -1 else n
            continue
        preludes.append(text[m.start():j].strip())
        depth = 0
        k = j
        while k < n:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        i = k + 1
    return "".join(out), preludes


def strip_comments(text: str):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


RULE_RE = re.compile(r"([^{}]+?)\{([^{}]*)\}")


def parse_rules(text: str, filename: str):
    """Parse a stylesheet into (selector, [(prop, value, line)], rule_line)."""
    text = strip_comments(text)
    text, _ = strip_at_blocks(text)
    rules = []
    for m in RULE_RE.finditer(text):
        selector = m.group(1).strip()
        if not selector or selector.startswith("<"):
            continue
        block = m.group(2)
        base_line = text.count("\n", 0, m.start()) + 1
        # offset of declarations measured from the start of the whole match,
        # so newlines inside the selector part are counted too
        decl_base = len(m.group(1)) + 1  # selector + '{'
        full = m.group(0)
        decls = []
        for dm in re.finditer(r"([a-zA-Z-]+)\s*:\s*([^;{}]+?)\s*(?:;|$)", block):
            prop = dm.group(1).strip().lower()
            val = dm.group(2).strip()
            line = base_line + full.count("\n", 0, decl_base + dm.start())
            decls.append((prop, val, line))
        if decls:
            rules.append((selector, decls, base_line))
    return rules


def find_media_preludes(text: str):
    _, preludes = strip_at_blocks(strip_comments(text))
    return preludes


def extract_css_sources(path: Path):
    """Return list of (kind, filename, text, line_offset)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    sources = []
    if path.suffix.lower() == ".css":
        sources.append(("css", str(path), raw, 0))
        return sources
    # HTML: <style> blocks
    for m in re.finditer(r"<style[^>]*>(.*?)</style>", raw, re.IGNORECASE | re.DOTALL):
        start_line = raw.count("\n", 0, m.start(1)) + 1
        sources.append(("style", str(path), m.group(1), start_line - 1))
    # HTML: inline style="..."
    for m in re.finditer(r"""<([a-zA-Z][a-zA-Z0-9-]*)\b[^<>]*?\sstyle\s*=\s*(['"])(.*?)\2""",
                         raw, re.IGNORECASE | re.DOTALL):
        line = raw.count("\n", 0, m.start()) + 1
        sources.append(("inline", str(path), m.group(3), line - 1,
                        f"<{m.group(1)} style=...>"))
    # HTML: linked stylesheets (relative)
    for m in re.finditer(
            r"""<link\b[^<>]*?rel\s*=\s*(['"])stylesheet\1[^<>]*?href\s*=\s*(['"])(.*?)\2""",
            raw, re.IGNORECASE):
        href = m.group(3)
        if href.startswith(("http://", "https://", "//", "data:")):
            continue
        css_path = (path.parent / href.split("?")[0].split("#")[0])
        if css_path.is_file():
            sources.append(("css", str(css_path),
                            css_path.read_text(encoding="utf-8", errors="replace"), 0))
    return sources


# ---------------------------------------------------------------- detection

class Finding:
    def __init__(self, rule_id, filename, line, snippet):
        self.rule_id = rule_id
        self.filename = filename
        self.line = line
        self.snippet = snippet.strip()[:120]

    def to_dict(self):
        r = RULES[self.rule_id]
        return {
            "rule_id": self.rule_id,
            "rule": r["name"],
            "file": self.filename,
            "line": self.line,
            "snippet": self.snippet,
            "suggestion_en": r["en"],
            "suggestion_zh": r["zh"],
        }


def _is_hero_selector(selector: str):
    s = selector.lower()
    return ("hero" in s or re.search(r"(?<![\w-])h1(?![\w-])", s) is not None)


def _is_container_selector(selector: str):
    s = selector.lower()
    return any(k in s for k in ("container", "wrapper", "content", "main", "page", "layout"))


def _is_body_selector(selector: str):
    s = selector.lower()
    return any(re.search(p, s) for p in
               (r"(?<![\w-])body(?![\w-])", r"(?<![\w-])html(?![\w-])", r":root"))


def detect_paths(paths):
    findings = []
    css_texts = []          # (filename, text) for global checks
    html_texts = []         # (filename, text) for toggle detection
    has_grid = False
    has_light_path = False

    for path in paths:
        path = Path(path)
        if not path.is_file():
            print(f"warning: not found: {path}", file=sys.stderr)
            continue
        for src in extract_css_sources(path):
            kind = src[0]
            filename, text, offset = src[1], src[2], src[3]
            inline_label = src[4] if len(src) > 4 else None
            css_texts.append((filename, text))
            if kind == "inline":
                decls = []
                for dm in re.finditer(r"([a-zA-Z-]+)\s*:\s*([^;{}]+?)\s*(?:;|$)", text):
                    decls.append((dm.group(1).strip().lower(), dm.group(2).strip(), offset + 1))
                rules = [(inline_label, decls, offset + 1)]
            else:
                rules = [(sel, [(p, v, l + offset) for p, v, l in decls], ln + offset)
                         for sel, decls, ln in parse_rules(text, filename)]
            for selector, decls, _rule_line in rules:
                props = {p: (v, ln) for p, v, ln in decls}

                # SLOP-001 giant border-radius
                for prop in ("border-radius", "border-top-left-radius",
                             "border-top-right-radius", "border-bottom-left-radius",
                             "border-bottom-right-radius"):
                    if prop in props:
                        v, ln = props[prop]
                        big = [x for x in px_values(v) if x > 24]
                        if big:
                            findings.append(Finding("SLOP-001", filename, ln,
                                                    f"{selector} {{ {prop}: {v} }}"))

                # SLOP-002 glassmorphism
                if "backdrop-filter" in props and "blur(" in props["backdrop-filter"][0].lower():
                    v, ln = props["backdrop-filter"]
                    bg = props.get("background", ("", 0))[0]
                    bgc = props.get("background-color", ("", 0))[0]
                    if has_low_alpha(bg) or has_low_alpha(bgc):
                        findings.append(Finding("SLOP-002", filename, ln,
                                                f"{selector} {{ backdrop-filter: {v}; "
                                                f"background: {bg or bgc} }}"))

                # SLOP-003 glowing shadow
                if "box-shadow" in props:
                    v, ln = props["box-shadow"]
                    if v.strip().lower() != "none":
                        cols = extract_colors(v)
                        colorful = [c for c in cols if not is_gray(c)]
                        if colorful and re.search(r"\d", v):
                            findings.append(Finding("SLOP-003", filename, ln,
                                                    f"{selector} {{ box-shadow: {v} }}"))

                # SLOP-004 red-purple gradient
                for prop in ("background", "background-image"):
                    if prop in props:
                        v, ln = props[prop]
                        if re.search(r"(linear|radial|conic)-gradient", v, re.IGNORECASE):
                            if any(is_purple_family(c) for c in extract_colors(v)):
                                findings.append(Finding("SLOP-004", filename, ln,
                                                        f"{selector} {{ {prop}: {v} }}"))

                # SLOP-005 dark body background (light-path check is global, below)
                if _is_body_selector(selector):
                    for prop in ("background", "background-color"):
                        if prop in props:
                            v, ln = props[prop]
                            cols = extract_colors(v)
                            if cols and all(is_near_black(c) for c in cols):
                                findings.append(Finding("SLOP-005", filename, ln,
                                                        f"{selector} {{ {prop}: {v} }} "
                                                        f"[dark bg]"))

                # SLOP-006 oversized centered hero
                if _is_hero_selector(selector):
                    size = None
                    centered = False
                    size_ln = None
                    if "font-size" in props:
                        size = font_size_px(props["font-size"][0])
                        size_ln = props["font-size"][1]
                    if props.get("text-align", ("", 0))[0].strip().lower() == "center":
                        centered = True
                    if size is not None and ((size >= 48 and centered) or size >= 64):
                        findings.append(Finding("SLOP-006", filename, size_ln,
                                                f"{selector} {{ font-size: "
                                                f"{props['font-size'][0]}; "
                                                f"{'text-align: center; ' if centered else ''}}}"))

                # SLOP-007 narrow container
                if _is_container_selector(selector) and "max-width" in props:
                    v, ln = props["max-width"]
                    pxs = px_values(v)
                    rems = [float(n) for n in re.findall(r"(\d+(?:\.\d+)?)rem", v)]
                    width_px = max(pxs) if pxs else (max(rems) * 16 if rems else None)
                    if width_px is not None and width_px < 720:
                        findings.append(Finding("SLOP-007", filename, ln,
                                                f"{selector} {{ max-width: {v} }} "
                                                f"[single narrow column]"))

                # global: any grid / multi-column usage?
                dv = props.get("display", ("", 0))[0].strip().lower()
                if dv == "grid" or "column-count" in props or "columns" in props:
                    has_grid = True

    # ---- global checks ----
    all_css = "\n".join(t for _, t in css_texts)
    for _fn, text in css_texts:
        for pre in find_media_preludes(text):
            if "prefers-color-scheme" in pre.lower():
                has_light_path = True
    for fn in {f for f, _ in css_texts}:
        if fn.endswith((".html", ".htm")):
            try:
                html = Path(fn).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            html_texts.append((fn, html))
    for _fn, html in html_texts:
        if re.search(r"data-theme|theme[-_]toggle|light[-_ ]?mode|切换主题|明暗|深色模式",
                     html, re.IGNORECASE):
            has_light_path = True

    # SLOP-005: dark bg without light path — drop if a light path exists
    dark_bg = [f for f in findings if f.rule_id == "SLOP-005"]
    if dark_bg and not has_light_path:
        pass  # keep: genuinely dark-only
    elif dark_bg and has_light_path:
        findings = [f for f in findings if f.rule_id != "SLOP-005"]

    # SLOP-007b: no grid/multi-column layout anywhere
    if not has_grid:
        anchor = None
        for f in findings:
            if f.rule_id == "SLOP-007":
                anchor = f
                break
        if anchor:
            findings.append(Finding("SLOP-007", anchor.filename, anchor.line,
                                    "[no display:grid / multi-column found in any stylesheet]"))
        elif any("container" in t.lower() for _, t in css_texts):
            f0, _t0 = css_texts[0]
            findings.append(Finding("SLOP-007", f0, 1,
                                    "[no display:grid / multi-column found in any stylesheet]"))

    # ---- score ----
    seen = sorted({f.rule_id for f in findings})
    score = min(100, sum(RULES[r]["weight"] for r in seen))
    return findings, score, seen


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Detect AI-slop web design (deterministic).")
    ap.add_argument("paths", nargs="+", help="HTML and/or CSS files to scan")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--fail-under", type=int, default=0,
                    help="Exit 1 if score >= N (default: exit 1 on any slop)")
    args = ap.parse_args(argv)

    findings, score, seen = detect_paths(args.paths)

    if args.json:
        print(json.dumps({
            "score": score,
            "rules": seen,
            "findings": [f.to_dict() for f in findings],
        }, indent=2, ensure_ascii=False))
    else:
        if not findings:
            print("Clean — no AI-slop design features detected. 看起来是人类手写的设计。")
        else:
            print(f"Slop score: {score}/100  ({len(findings)} findings, "
                  f"{len(seen)} rules)\n")
            for f in findings:
                r = RULES[f.rule_id]
                print(f"[{f.rule_id}] {r['name']} — {f.filename}:{f.line}")
                print(f"    {f.snippet}")
                print(f"    EN: {r['en']}")
                print(f"    中文: {r['zh']}\n")

    threshold = args.fail_under if args.fail_under > 0 else 1
    return 1 if score >= threshold else 0


if __name__ == "__main__":
    sys.exit(main())
