# design-slop-skill

A **Claude Code skill** that detects and fixes "AI slop" web design — the visual
fingerprint AI-generated pages share:

- 🫧 Giant border-radius on everything (SLOP-001)
- 🪟 Glassmorphism / frosted-glass cards (SLOP-002)
- ✨ Glowing colored borders and shadows (SLOP-003)
- 🟣 Red-purple gradients, the signature AI palette (SLOP-004)
- 🌑 Dark-mode-only pages with no light-mode path (SLOP-005)
- 📢 Oversized centered hero titles (SLOP-006)
- 📜 One long single column, no grid (SLOP-007)

All rules are **bilingual (English + 中文)**. Detection is deterministic —
stdlib-only Python, no LLM, no network, no dependencies.

## Quick start

```bash
# 1. scan the page you just generated
python3 scripts/detect.py index.html

# 2. preview the automatic rewrites
python3 scripts/fix.py index.html --dry-run

# 3. apply them (writes index.fixed.html + index.bak.html)
python3 scripts/fix.py index.html

# 4. verify the slop score dropped
python3 scripts/detect.py index.fixed.html
```

Example report:

```
Slop score: 90/100  (8 findings, 7 rules)

[SLOP-004] Red-purple gradient — index.html:42
    .hero-banner { background: linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%) }
    EN: linear-gradient with violet/magenta/purple stops — the signature AI palette.
    中文: 红紫渐变：linear-gradient 里出现紫/品红/红紫色 —— AI 网页的招牌配色。
```

## How it works

`scripts/detect.py` parses `<style>` blocks, inline `style=""` attributes, and
relative linked stylesheets, then checks 7 rules. Each finding carries a rule id,
file, line number, code snippet, and a bilingual suggestion. Rules are weighted
(SLOP-004/SLOP-005: 20, others: 10) into a 0–100 slop score. Exit code 1 = slop
found, 0 = clean. `--json` emits machine-readable output for CI.

`scripts/fix.py` rewrites the offending CSS toward human-crafted defaults:
radius clamped to 10px, blur dropped and translucent backgrounds solidified,
glow shadows neutralized, purple gradients flattened to solid colors, a
`prefers-color-scheme: light` block appended for dark-only pages, hero titles
tamed to 2.25rem left-aligned, narrow containers widened to 72rem.

Two things still need a human (or a design-aware pass) after the fixer runs:
adding a real theme-toggle button, and restructuring single-column layouts into
grids. The skill tells the agent exactly that.

## Use as a Claude Code skill

Copy this repo (or just `SKILL.md` + `scripts/`) into your project's
`.claude/skills/design-slop-skill/` — or install it as a user skill. Then tell
the agent: *"after generating any page, run the design-slop-skill check."*
See `SKILL.md` for the full agent-facing instructions.

## Tests

```bash
python3 -m unittest tests.test_detect
```

23 tests: one fixture per slop rule, a clean human-crafted negative that must
stay silent, a max-slop mixed fixture, JSON output, score weighting, and
fix-verification (re-detection score must drop after fixing).

## How this differs

- **vs. CLI auditors** (e.g. my own
  [css-slop-detector](https://github.com/hahahahahahahahah6/css-slop-detector)):
  those are tools you run *after the fact*. This is the **agent-native skill
  form** — the coding agent invokes it *during* generation, with bilingual
  rules and an auto-fixer wired into the workflow.
- **vs. text de-AI tools** (e.g. MrGeDiao/shuorenhua): those remove AI
  *writing* tics. This removes AI *design* tics — CSS, layout, color.
  Complementary, not overlapping.

## License

MIT — see [LICENSE](LICENSE).
