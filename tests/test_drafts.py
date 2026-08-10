import pytest

from ssg import posts
from ssg.posts import PostError, load, load_all

TEMPLATE = """---
title: {title}
date: 2026-08-0{day}
{extra}---

Some body text with a [link](https://example.com/somewhere-quite-long) in it.
"""


def write(tmp_path, name, *, title="A post", day=1, extra=""):
    path = tmp_path / f"{name}.md"
    path.write_text(TEMPLATE.format(title=title, day=day, extra=extra), encoding="utf-8")
    return path


def test_a_post_marked_draft_false_is_published(tmp_path):
    # The trap: frontmatter yields strings, so `draft: false` arrives as the
    # string "false", and bool("false") is True. Getting this backwards would
    # hide a post its author explicitly marked as ready.
    write(tmp_path, "ready", extra="draft: false\n")

    assert len(load_all(tmp_path)) == 1


def test_a_post_marked_draft_true_is_held_back(tmp_path):
    write(tmp_path, "wip", extra="draft: true\n")
    write(tmp_path, "live", day=2)

    published = load_all(tmp_path)

    assert [p.slug for p in published] == ["live"]


def test_the_draft_is_still_there_when_asked_for(tmp_path):
    write(tmp_path, "wip", extra="draft: true\n")

    assert len(load_all(tmp_path, include_drafts=True)) == 1


def test_a_post_with_no_draft_key_is_published(tmp_path):
    write(tmp_path, "plain")

    assert len(load_all(tmp_path)) == 1


@pytest.mark.parametrize("value", ["true", "True", "yes", "on", "1"])
def test_the_usual_ways_of_writing_yes_all_mean_draft(tmp_path, value):
    write(tmp_path, "wip", extra=f"draft: {value}\n")

    assert load_all(tmp_path) == []


@pytest.mark.parametrize("value", ["false", "False", "no", "off", "0", ""])
def test_everything_else_means_publish(tmp_path, value):
    write(tmp_path, "ready", extra=f"draft: {value}\n")

    assert len(load_all(tmp_path)) == 1


def test_drafts_still_fight_for_their_slug(tmp_path):
    # A draft owns its filename, so a collision must be reported now rather
    # than on the day it is published.
    (tmp_path / "a").mkdir()
    write(tmp_path, "2026-08-01-note", extra="draft: true\n")
    other = tmp_path / "2026-08-01-note.markdown"
    other.write_text(
        TEMPLATE.format(title="Other", day=1, extra=""), encoding="utf-8"
    )
    # Same stem, different suffix -- only .md is globbed, so this must NOT clash.
    assert len(load_all(tmp_path, include_drafts=True)) == 1


def test_reading_time_is_at_least_a_minute(tmp_path):
    post = load(write(tmp_path, "short"))

    assert post.reading_time == 1


def test_reading_time_does_not_count_the_url_in_a_link(tmp_path):
    # Digests are mostly links; counting their targets as words would report a
    # twenty-minute read for a page you skim in two.
    path = tmp_path / "linky.md"
    words = " ".join(["word"] * 400)
    links = "\n".join(
        f"- [Headline {i}](https://example.com/a/very/long/path/number/{i}/indeed)"
        for i in range(60)
    )
    path.write_text(
        TEMPLATE.format(title="Linky", day=1, extra="") + f"\n{words}\n\n{links}\n",
        encoding="utf-8",
    )

    post = load(path)

    # 400 words plus the visible headline text -- nowhere near what the raw
    # character count would suggest.
    assert 2 <= post.reading_time <= 4
