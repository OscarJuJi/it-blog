import datetime as dt

import pytest

from agent import repair
from ssg import frontmatter

LINKS_ONLY = """---
title: "Daily digest: August 1, 2026"
date: 2026-08-01
description: "The summaries could not be generated today, so here is the reading list on its own."
tags:
  - digest
  - news
---

The summaries could not be generated today, so here is the reading list on its own.

- [First story headline](https://example.com/one) - *Hacker News*
- [Second with (parens)](<https://example.com/two(x)>) - *Ars Technica*

*Selected automatically from the sources linked above.*
"""

WRITTEN = """---
title: "Daily digest: August 3, 2026"
date: 2026-08-03
description: "A quiet day."
tags:
  - digest
  - news
---

A quiet day.

## [A headline](https://example.com/a)

Something happened and here is why it matters.

*Hacker News*

*Selected and summarized automatically from the sources linked above.*
"""


def test_it_recognises_a_digest_that_never_got_its_summaries():
    assert repair.is_links_only(LINKS_ONLY)
    assert not repair.is_links_only(WRITTEN)


def test_it_reads_back_the_reading_list():
    items = repair.reading_list(LINKS_ONLY)

    assert [i.title for i in items] == ["First story headline", "Second with (parens)"]
    assert [i.link for i in items] == [
        "https://example.com/one",
        "https://example.com/two(x)",
    ]
    assert [i.source for i in items] == ["Hacker News", "Ars Technica"]


def test_it_reads_a_post_the_cms_has_rewritten():
    # Sveltia normalises emphasis on save, so a post edited in the browser comes
    # back with _underscores_ where the agent wrote *asterisks*. 2026-08-02 is
    # the real post this was found on.
    cms_style = LINKS_ONLY.replace("*Hacker News*", "_Hacker News_")

    items = repair.reading_list(cms_style)

    assert [i.source for i in items] == ["Hacker News", "Ars Technica"]


def test_a_written_digest_has_no_reading_list_to_read():
    assert repair.reading_list(WRITTEN) == []


def test_retagging_replaces_only_the_tags():
    out = repair.retag(WRITTEN, ["ai", "security"])

    assert "  - digest\n  - ai\n  - security\n" in out
    assert "  - news" not in out
    # Everything else must survive byte for byte.
    assert out.split("---\n", 2)[2] == WRITTEN.split("---\n", 2)[2]
    assert 'title: "Daily digest: August 3, 2026"' in out
    assert "date: 2026-08-03" in out


def test_retagging_always_keeps_the_marker_first():
    out = repair.retag(WRITTEN, ["security"])

    tags = [line for line in out.splitlines() if line.startswith("  - ")]
    assert tags == ["  - digest", "  - security"]


def test_retagging_with_nothing_leaves_just_the_marker():
    out = repair.retag(WRITTEN, [])

    assert [line for line in out.splitlines() if line.startswith("  - ")] == ["  - digest"]


def test_retagging_refuses_a_file_with_no_tags_block():
    with pytest.raises(repair.RepairError, match="tags"):
        repair.retag("---\ntitle: x\ndate: 2026-08-01\n---\n\nBody.\n", ["ai"])


def test_it_rebuilds_the_body_from_written_summaries():
    items = repair.reading_list(LINKS_ONLY)
    summaries = {0: "The first thing, explained.", 1: "The second thing, explained."}

    out = repair.refill(LINKS_ONLY, items, summaries, intro="Two things happened.")

    assert "## [First story headline](https://example.com/one)" in out
    assert "The first thing, explained." in out
    assert "*Hacker News*" in out
    # The apology is gone from both the body and the description.
    assert "could not be generated" not in out
    assert "Two things happened." in out


def test_refilling_keeps_the_stories_it_has_no_summary_for_as_links():
    items = repair.reading_list(LINKS_ONLY)

    out = repair.refill(LINKS_ONLY, items, {0: "Only the first."}, intro="One thing.")

    assert "## [First story headline]" in out
    # The second is not dropped and not invented -- it stays a bare link.
    assert "https://example.com/two(x)" in out


def test_refilling_says_the_post_was_written_after_the_fact():
    items = repair.reading_list(LINKS_ONLY)

    out = repair.refill(LINKS_ONLY, items, {0: "A summary."}, intro="Intro.")

    assert "written later" in out.lower()


def test_refilling_refuses_a_post_that_already_has_prose():
    with pytest.raises(repair.RepairError, match="already"):
        repair.refill(WRITTEN, [], {}, intro="x")


# The intro is the model's sentence, written from articles nobody here controls,
# and it goes straight into front matter that has no escape syntax at all. Both
# tests below round-trip through the real parser rather than reading the string.


def test_an_intro_with_quotes_survives_the_front_matter():
    items = repair.reading_list(LINKS_ONLY)

    out = repair.refill(
        LINKS_ONLY, items, {0: "A summary."}, intro='The day AI ate "everything"'
    )

    metadata, _ = frontmatter.split(out)
    assert "\\" not in metadata["description"]
    assert "everything" in metadata["description"]


def test_an_intro_carrying_a_newline_cannot_break_the_build():
    items = repair.reading_list(LINKS_ONLY)

    out = repair.refill(
        LINKS_ONLY,
        items,
        {0: "A summary."},
        intro="Line one\ntags: injected\nmore",
    )

    metadata, _ = frontmatter.split(out)
    # The injected line is text inside the description, not a key of its own,
    # and the post's real tags are untouched.
    assert metadata["tags"] == frontmatter.split(LINKS_ONLY)[0]["tags"]
    assert "injected" in metadata["description"]
    assert "\n" not in metadata["description"]
