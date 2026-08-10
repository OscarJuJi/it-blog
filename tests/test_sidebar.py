import datetime as dt
from pathlib import Path

from ssg.build import _cloud_step, _neighbours, _recent, _related, _tag_counts
from ssg.posts import Post


def post(slug, day, *tags):
    return Post(
        slug=slug,
        title=slug.replace("-", " ").title(),
        date=dt.date(2026, 8, day),
        description="A summary.",
        tags=tuple(tags),
        body="Body.",
        source=Path(f"{slug}.md"),
    )


# Newest first, the order load_all already returns.
POSTS = [
    post("fifth", 5, "digest", "news"),
    post("fourth", 4, "digest", "news"),
    post("third", 3, "digest"),
    post("second", 2, "meta"),
    post("first", 1),
]


def test_tag_counts_counts_every_appearance():
    assert dict(_tag_counts(POSTS)) == {"digest": 3, "meta": 1, "news": 2}


def test_tag_counts_is_alphabetical_so_the_build_is_reproducible():
    assert [tag for tag, _ in _tag_counts(POSTS)] == ["digest", "meta", "news"]


def test_tag_counts_of_nothing_is_nothing():
    assert _tag_counts([]) == []
    assert _tag_counts([post("untagged", 1)]) == []


def test_the_most_common_tag_is_the_largest_step_and_the_rarest_the_smallest():
    assert _cloud_step(3, smallest=1, largest=3) == 5
    assert _cloud_step(1, smallest=1, largest=3) == 1


def test_a_middling_tag_lands_in_between():
    step = _cloud_step(2, smallest=1, largest=3)
    assert 1 < step < 5


def test_tags_that_all_tie_get_the_same_middle_step():
    # The real blog's tags tie constantly, and a naive range would divide by zero.
    steps = {_cloud_step(4, smallest=4, largest=4) for _ in range(3)}

    assert steps == {3}


def test_recent_takes_the_newest_and_respects_the_limit():
    assert [p.slug for p in _recent(POSTS, limit=3)] == ["fifth", "fourth", "third"]


def test_recent_copes_with_fewer_posts_than_the_limit():
    assert _recent([], limit=5) == []
    assert len(_recent(POSTS[:2], limit=5)) == 2


def test_the_newest_post_has_nothing_newer_and_the_oldest_nothing_older():
    newer, older = _neighbours(POSTS, POSTS[0])
    assert newer is None and older.slug == "fourth"

    newer, older = _neighbours(POSTS, POSTS[-1])
    assert newer.slug == "second" and older is None


def test_a_post_in_the_middle_has_both():
    newer, older = _neighbours(POSTS, POSTS[2])

    assert newer.slug == "fourth"
    assert older.slug == "second"


def test_a_lone_post_has_neither():
    only = [post("only", 1)]

    assert _neighbours(only, only[0]) == (None, None)


def test_a_tag_almost_everything_carries_relates_nothing():
    # `digest` is on every agent post. Counting it would make "related" mean
    # "the newest posts", which the neighbours strip and the recent widget
    # already show.
    universal = [post(f"p{d}", d, "digest") for d in range(1, 6)]

    assert _related(universal, universal[0]) == []


def test_posts_are_related_by_the_tags_they_actually_share():
    library = [
        post("a", 5, "digest", "security"),
        post("b", 4, "digest", "security"),
        post("c", 3, "digest", "web"),
        post("d", 2, "digest"),
    ]

    related = _related(library, library[0])

    assert [p.slug for p in related] == ["b"]


def test_more_shared_tags_wins_over_being_newer():
    library = [
        post("subject", 5, "digest", "ai", "security"),
        post("newer-weak", 4, "digest", "ai"),
        post("older-strong", 1, "digest", "ai", "security"),
        post("filler-a", 3, "digest", "web"),
        post("filler-b", 2, "digest", "web"),
    ]

    related = _related(library, library[0])

    # digest is on all five and is ignored; ai and security still discriminate.
    assert [p.slug for p in related] == ["older-strong", "newer-weak"]


def test_a_post_is_never_related_to_itself():
    library = [post("a", 2, "x", "y"), post("b", 1, "x", "y")]

    assert library[0] not in _related(library, library[0])


def test_related_respects_its_limit():
    library = [post(f"ai{d}", d, "ai") for d in range(1, 7)]
    library += [post("other-a", 7, "web"), post("other-b", 8, "web")]

    # ai is on six of eight -- common, but not ubiquitous enough to ignore.
    assert len(_related(library, library[0], limit=2)) == 2
