"""Accessibility invariants, asserted against the real built HTML.

These were checked once by driving a headless browser over the running site and
reading the tab order out of the DOM. That check cannot run in CI, so what it
established is encoded here instead: every claim below was true when measured,
and these tests are what stop it quietly becoming false.
"""

import datetime as dt
import re

import pytest

from ssg import build as build_module

NOW = dt.datetime(2026, 8, 1, 13, 0, tzinfo=dt.timezone.utc)

FOCUSABLE = re.compile(r"<(a\s[^>]*href=|button\b|input\b|select\b|textarea\b)", re.I)


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    output = tmp_path_factory.mktemp("a11y") / "_site"
    posts = build_module.build(output=output, now=NOW)
    return {
        "index": (output / "index.html").read_text(encoding="utf-8"),
        "post": (output / posts[0].path / "index.html").read_text(encoding="utf-8"),
        "tag": (output / "tags" / "digest" / "index.html").read_text(encoding="utf-8"),
        "404": (output / "404.html").read_text(encoding="utf-8"),
    }


def every_page(pages):
    return pages.values()


def test_the_skip_link_is_the_first_thing_you_can_tab_to(pages):
    for html in every_page(pages):
        body = html[html.index("<body") :]
        first = FOCUSABLE.search(body)
        assert first is not None
        # The skip link must sit before any other focusable element.
        assert 'class="skip-link"' in body[: first.end() + 120]


def test_the_skip_link_points_at_something_that_can_hold_focus(pages):
    for html in every_page(pages):
        target = re.search(r'class="skip-link" href="#([^"]+)"', html)
        assert target, "skip link missing or has no fragment target"

        anchor = re.search(rf'id="{re.escape(target.group(1))}"[^>]*', html)
        assert anchor, f"nothing on the page has id={target.group(1)!r}"
        # A <main> is not focusable by default; without this the skip link
        # moves the viewport but not the keyboard.
        assert 'tabindex="-1"' in anchor.group(0)


def test_the_content_is_tabbed_before_the_sidebar(pages):
    # Source order is tab order. The grid puts the sidebar on the right, but a
    # keyboard user must not have to walk the widgets to reach the articles.
    for html in every_page(pages):
        assert html.index("<main") < html.index("<aside")


def test_every_page_declares_its_language(pages):
    for html in every_page(pages):
        assert re.search(r'<html lang="[a-z]{2}', html)


def test_every_page_has_exactly_one_first_level_heading(pages):
    for name, html in pages.items():
        assert html.count("<h1") == 1, f"{name} has {html.count('<h1')} h1 elements"


def test_headings_never_skip_a_level(pages):
    for name, html in pages.items():
        levels = [int(m) for m in re.findall(r"<h([1-6])\b", html)]
        for previous, current in zip(levels, levels[1:]):
            assert current <= previous + 1, f"{name}: h{previous} jumps to h{current}"


def test_the_search_box_has_a_real_label_not_just_a_placeholder(pages):
    index = pages["index"]
    field = re.search(r'<input[^>]*type="search"[^>]*id="([^"]+)"', index)

    assert field, "the search input is gone or has no id"
    assert f'<label for="{field.group(1)}"' in index


def test_the_live_region_announces_result_counts(pages):
    # Filtering happens without a page load, so the count has to be spoken.
    assert 'aria-live="polite"' in pages["index"]


def test_navigation_landmarks_are_named(pages):
    for name, html in pages.items():
        for nav in re.findall(r"<nav\b[^>]*>", html):
            assert "aria-label" in nav, f"{name}: unlabelled <nav>: {nav}"


def test_the_social_card_carries_alternative_text(pages):
    for html in every_page(pages):
        assert 'property="og:image:alt"' in html


def test_focus_is_never_removed_without_being_replaced():
    css = (build_module.ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert ":focus-visible" in css
    # `outline: none` is only defensible on the skip-link target, which receives
    # focus programmatically and would otherwise ring the whole page.
    for match in re.finditer(r"([^{}]+)\{[^{}]*outline:\s*none", css):
        assert "main:focus" in match.group(1), f"outline removed from {match.group(1).strip()!r}"


def test_motion_can_be_turned_off(pages):
    css = (build_module.ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert "prefers-reduced-motion" in css
