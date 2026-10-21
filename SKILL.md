---
name: design-slop-skill
description: Detect and fix "AI slop" web design — the visual fingerprint AI-generated pages share (giant border-radius, glassmorphism, glowing borders, red-purple gradients, dark-mode-only, oversized centered hero, single long column). Run scripts/detect.py after generating any HTML/CSS, then scripts/fix.py to rewrite toward human-crafted defaults. Bilingual rules (English + 中文).
---

# design-slop-skill

AI-generated web pages all look the same. This skill gives you a deterministic,
no-LLM detector plus an auto-fixer so the pages you generate don't smell like AI.

## When to use

Invoke this skill **every time you generate or significantly restyle a web page**
(HTML/CSS), right after the code is written and before you hand it to the user:

1. Run the detector: `python3 scripts/detect.py <file.html> [more files...]`
2. Read the findings (rule id, file, line, bilingual explanation).
3. Run the fixer: `python3 scripts/fix.py <file.html> --dry-run` first, review,
   then without `--dry-run` to write `<name>.fixed.html` (+ `.bak` backup).
4. Re-run the detector on the fixed file; confirm the score dropped.
5. Anything the fixer can't do automatically (noted below) — fix by hand.

The scripts are stdlib-only Python. No network, no API keys, no dependencies.

## The 7 slop rules (bilingual)

Each rule has an id, an English and a 中文 description, and a human-crafted default.

### SLOP-001 · Giant border-radius · 巨大圆角
- **EN:** `border-radius` over 24px on cards, buttons, badges. The AI default.
- **中文:** 卡片/按钮/徽章的圆角超过 24px。这是 AI 的默认审美。
- **Human default:** 6–12px radius (8px is a safe default). Circles (`50%`) are fine.
- **Fix:** clamp to `10px`.

### SLOP-002 · Glassmorphism · 毛玻璃
- **EN:** `backdrop-filter: blur()` combined with a translucent background
  (frosted-glass cards floating over gradients).
- **中文:** 毛玻璃卡片：`backdrop-filter` 模糊 + 半透明背景。
- **Human default:** solid surface colors; blur only for real overlays (modals).
- **Fix:** drop the blur; convert translucent `rgba()` backgrounds to solid.

### SLOP-003 · Glowing border / shadow · 发光边框
- **EN:** Colored glowing `box-shadow` (neon halo around cards/buttons).
- **中文:** 发光边框/阴影：带颜色的 `box-shadow` 光晕。
- **Human default:** subtle neutral shadow (`0 1px 2px rgba(0,0,0,.08)`) or a plain 1px border.
- **Fix:** replace with the neutral shadow.

### SLOP-004 · Red-purple gradient · 红紫渐变
- **EN:** `linear-gradient` with violet/magenta/purple stops —
  the signature AI palette (`#8b5cf6 → #ec4899` and friends).
- **中文:** 红紫渐变：渐变里出现紫/品红/红紫色 —— AI 网页的招牌配色。
- **Human default:** a solid brand color, or a muted single-hue gradient.
- **Fix:** replace with a solid color (first non-purple stop, else slate).

### SLOP-005 · Dark-mode-only · 只有暗黑模式
- **EN:** Pure/near-black body background with no light-mode path —
  no `prefers-color-scheme`, no theme toggle. Most users don't want forced dark.
- **中文:** 纯黑/近黑背景，却没有亮色模式：没有 `prefers-color-scheme`，
  也没有主题切换开关。大多数用户并不想要被强制的暗黑模式。
- **Human default:** respect the OS theme; offer an explicit toggle.
- **Fix:** appends a `prefers-color-scheme: light` override block.
  **You still need to add a real toggle button by hand** if the page is dark-first.

### SLOP-006 · Oversized centered hero · 特大居中标题
- **EN:** Hero/H1 title ≥ 48px (3rem) **and** centered — the default AI landing layout.
- **中文:** 特大居中标题：Hero/H1 字号 ≥ 48px 且居中 —— AI 落地页的默认版式。
- **Human default:** ~2–2.5rem, left-aligned on desktop.
- **Fix:** `font-size: 2.25rem`, `text-align: left` within hero/H1 rules.

### SLOP-007 · Single long column · 一个长单栏
- **EN:** One narrow `max-width` container (< 720px), no grid or multi-column
  sections anywhere — a single endless column of sections.
- **中文:** 一个长单栏：容器 `max-width` 很窄，且全站没有任何 grid/多栏布局。
- **Human default:** wider measure (~72rem) with grid/columns for content sections.
- **Fix:** widens the container to `72rem`.
  **Grid layout is a design decision — restructure by hand** when the fixer flags
  "no display:grid / multi-column found".

## Slop score

Each rule has a weight (SLOP-004 and SLOP-005: 20; others: 10). The score is the
sum of weights of triggered rules, capped at 100. Exit code is 1 when slop is
found, 0 when clean. Use `--json` for machine-readable output and
`--fail-under N` to fail CI only above a threshold.

## Verification checklist

After fixing, confirm:
- [ ] `detect.py` on the fixed file shows a lower score (0 is ideal).
- [ ] No `backdrop-filter` blur remains on non-overlay elements.
- [ ] No purple/magenta gradient remains.
- [ ] Page is readable with the OS in light mode.
- [ ] Hero title ≤ 2.5rem and not centered on desktop widths.
- [ ] Content sections use more than one column where appropriate.

## Limitations

- Regex-based CSS parsing: conservative by design. False negatives are possible
  (heavily minified or CSS-in-JS may be missed); false positives are treated as
  bugs — report them.
- `fix.py` is a mechanical rewrite, not a redesign. Tasteful layout (grid
  structure, real theme toggle, color system) still needs a human or a
  design-aware pass after the fixer runs.
- Inline `style=""` attributes are scanned; `<style>` blocks and relative
  linked stylesheets are followed. Remote stylesheets are skipped.
