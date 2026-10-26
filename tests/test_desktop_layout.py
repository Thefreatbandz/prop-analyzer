"""Desktop layout regressions (2026-10-26 wide-viewport browser check).

A ~1920px browser check found three desktop layout failures, all in the
Home "Top edges right now" row and the page container:
  1. Content capped at 1100px left the right ~third of the screen empty.
  2. The 4-across card row overflowed: cards clipped at the right edge,
     "MODEL PROB" / "EDGE" text truncated mid-word, and the large green
     edge % bled across adjacent card boundaries.
  3. Player names in the Home cards rendered as vertical letter stacks
     (one letter per line) while the Builder rendered the same names
     normally — the Home card header row crushed the name element.

Root cause for 2+3: the card header row was photo (76px, no-shrink) +
name (flex) + edge box (no-shrink, ~130px of 2.1em hero text) in a
~260px column — the no-shrink edge box squeezed the name below one
word's width and pushed content past the card edge. The fix wraps the
row (edge box drops to its own line instead of crushing or overflowing)
and guarantees the name a 140px floor, so names wrap word-wise only.

CSS is asserted via source checks (same pattern as test_ui_pop.py).
"""

import re

SRC = open("app.py").read()


def _css():
    m = re.search(r"<style>(.*?)</style>", SRC, re.S)
    assert m, "theme <style> block missing"
    return m.group(1)


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} rule missing"
    return m.group(1)


def test_desktop_container_uses_the_screen():
    css = _css()
    rule = _rule(css, ".block-container")
    m = re.search(r"max-width:\s*(\d+)px", rule)
    assert m, "block-container needs a desktop max-width"
    assert int(m.group(1)) >= 1500, (
        f"container cap {m.group(1)}px still leaves a wide viewport empty")


def test_phone_container_padding_untouched():
    # The mobile rule must survive the desktop widening.
    css = _css()
    phone = css[css.index("@media (max-width: 640px)"):]
    assert ".block-container" in phone
    assert "padding-left: 0.9rem" in phone


def test_neon_idrow_wraps_instead_of_overflowing():
    css = _css()
    rule = _rule(css, ".neon-idrow")
    assert "flex-wrap: wrap" in rule


def test_neon_name_keeps_a_word_width_floor():
    # The name block must hold at least one name word before the row
    # wraps — otherwise long names crush into letter stacks again.
    css = _css()
    rule = _rule(css, ".neon-id")
    m = re.search(r"flex:\s*1\s+1\s+(\d+)px", rule)
    assert m, "neon-id needs a flex-basis floor"
    assert int(m.group(1)) >= 120


def test_neon_name_never_breaks_letters():
    css = _css()
    rule = _rule(css, ".neon-name")
    assert "word-break: normal" in rule
    assert "break-all" not in rule


def test_neon_edgebox_may_shrink_and_wrap():
    # The old flex-shrink: 0 on the edge box is what crushed the name
    # and pushed the hero text past the card edge.
    css = _css()
    rule = _rule(css, ".neon-edgebox")
    assert "flex-shrink: 0" not in rule
    assert "min-width: 0" in rule
