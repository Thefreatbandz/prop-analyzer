"""UI pop overhaul (v6): floating tab nav, branded banners, glowing heroes,
mini trading-card suggestions. CSS is asserted via source checks (same
pattern as the dev-mode gate test); card HTML is asserted directly."""

import re

from ui import cards

SRC = open("app.py").read()


def _css():
    m = re.search(r"<style>(.*?)</style>", SRC, re.S)
    assert m, "theme <style> block missing"
    return m.group(1)


# ---------- Floating tab nav ----------


def test_floating_tablist_css_present():
    css = _css()
    assert '[data-testid="stTabs"] [role="tablist"]' in css
    assert "position: sticky" in css
    assert "backdrop-filter: blur" in css


def test_phone_bottom_tab_bar_css_present():
    css = _css()
    assert "@media (max-width: 640px)" in css
    phone = css[css.index("@media (max-width: 640px)"):]
    assert "position: fixed" in phone
    assert "bottom: 0" in phone
    assert "env(safe-area-inset-bottom)" in phone


def test_active_tab_is_gold_pill():
    css = _css()
    assert 'div[data-testid="stTab"][aria-selected="true"]' in css
    # gold gradient pill, dark text
    assert "#E8C84A" in css


def test_dead_tab_selectors_removed():
    # Streamlit 1.65 renders div[data-testid="stTab"], not buttons —
    # the old selectors never matched anything.
    assert 'button[data-baseweb="tab"]' not in SRC


# ---------- Branded banners (no default blue) ----------


def test_alert_kinds_all_branded():
    css = _css()
    for kind in ("Info", "Warning", "Success", "Error"):
        assert f'stAlertContent{kind}' in css, kind
    # info banners get the gold treatment, not Streamlit blue
    assert "border-left: 3px solid var(--gold)" in css


def test_no_default_blue_alert_background():
    css = _css()
    # the alert surfaces are forced onto charcoal
    assert "background: #17171a !important" in css


# ---------- Glow / depth ----------


def test_hero_numbers_glow():
    css = _css()
    assert ".ev-hero" in css and "text-shadow" in css
    assert ".prob-num" in css


def test_section_headers_get_gold_underline():
    css = _css()
    assert "h2::after" in css and "linear-gradient(90deg, var(--gold)" in css


def test_primary_button_glows_gold():
    css = _css()
    assert "box-shadow: 0 0 18px rgba(201,162,39,.35)" in css


# ---------- Suggestion mini trading cards ----------


def _sug(**kw):
    d = {"name": "Josh Allen", "team": "Buffalo Bills",
         "reason": "Top +EV prop this week: Pass Yds over 267.5 (+4.2%)"}
    d.update(kw)
    return d


def test_suggestion_card_renders_mini_trading_card():
    html = cards.suggestion_card_html(
        _sug(), photo_b64="data:image/jpeg;base64,AAA", position="QB")
    assert "sug-mini" in html
    assert "Josh Allen" in html
    assert "QB" in html
    assert "Buffalo Bills" in html
    assert "Top +EV prop this week" in html
    assert "data:image/jpeg;base64,AAA" in html
    # Bills royal-blue accent edge
    assert "#00338D" in html


def test_suggestion_card_initials_fallback():
    html = cards.suggestion_card_html(_sug())
    assert "sug-mini-initials" in html
    assert ">JA<" in html


def test_suggestion_card_escapes_markup():
    html = cards.suggestion_card_html(
        _sug(name='<script>alert(1)</script>',
             reason='<img src=x onerror=alert(2)>'))
    assert "<script>" not in html
    # the raw tag must not survive; the escaped text form is harmless
    assert "<img src=x" not in html


def test_suggestion_card_unknown_team_no_accent():
    html = cards.suggestion_card_html(_sug(team="Springfield Atoms"))
    assert "sug-mini" in html
    assert "box-shadow:0 0 14px" not in html


def test_scan_uses_mini_cards():
    assert "ui_cards.suggestion_card_html(" in SRC
    assert "Worth a look this week" in SRC


# ---------- Friendlier copy ----------


def test_track_record_gate_copy_is_encouraging():
    assert "Every pick makes the record stronger" in SRC


def test_track_record_empty_copy_is_warmer():
    assert "Nothing hidden, nothing cherry-picked" in SRC
