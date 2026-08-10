import datetime as dt
from pathlib import Path

import pytest

from ssg import tags
from ssg.posts import Post


def post(slug, day, *post_tags):
    return Post(
        slug=slug,
        title=slug.title(),
        date=dt.date(2026, 8, day),
        description="A summary.",
        tags=tuple(post_tags),
        body="Body.",
        source=Path(f"{slug}.md"),
    )


def test_a_tag_becomes_a_url_safe_slug():
    assert tags.slug("AI") == "ai"
    assert tags.slug("open source") == "open-source"
    assert tags.slug("Gödel") == "godel"


def test_punctuation_only_tags_are_refused_rather_than_becoming_empty_paths():
    # slugify("#") is "", which would write straight into _site/tags/.
    with pytest.raises(tags.TagError, match="#"):
        tags.index([post("a", 1, "#")])


def test_two_tags_that_slug_the_same_are_refused_by_name():
    # Verified: slugify("C#") and slugify("C++") are both "c". Merging them into
    # one page silently would be worse than failing the build.
    with pytest.raises(tags.TagError) as caught:
        tags.index([post("a", 1, "C#"), post("b", 2, "C++")])

    assert "C#" in str(caught.value) and "C++" in str(caught.value)


def test_tags_come_out_alphabetically_and_their_posts_newest_first():
    grouped = tags.index(
        [
            post("newest", 3, "web", "ai"),
            post("middle", 2, "ai"),
            post("oldest", 1, "web"),
        ]
    )

    assert [tag for _, tag, _ in grouped] == ["ai", "web"]
    assert [p.slug for p in grouped[0][2]] == ["newest", "middle"]
    assert [p.slug for p in grouped[1][2]] == ["newest", "oldest"]


def test_the_slug_travels_with_its_display_name():
    grouped = tags.index([post("a", 1, "Open Source")])

    slug, display, _ = grouped[0]
    assert slug == "open-source"
    assert display == "Open Source"


def test_untagged_posts_produce_nothing():
    assert tags.index([post("a", 1)]) == []
    assert tags.index([]) == []
