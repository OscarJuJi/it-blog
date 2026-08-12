import datetime as dt
import json
from pathlib import Path

from ssg import postindex
from ssg.posts import Post
from ssg.site import Site

SITE = Site.from_config(
    {
        "site": {
            "title": "IT Brief",
            "description": "Daily tech news.",
            "url": "https://oscarjuji.github.io",
            "base_url": "/it-blog",
            "language": "en",
        }
    }
)

POSTS = [
    Post(
        slug="2026-08-01-daily-digest",
        title="Daily digest & more",
        date=dt.date(2026, 8, 1),
        description="Five stories.",
        tags=("digest", "news"),
        body="Body.",
        source=Path("a.md"),
    ),
    Post(
        slug="older-note",
        title="Older note",
        date=dt.date(2026, 7, 30),
        description="",
        tags=(),
        body="## Heading\n\nThe opening paragraph of the body.",
        source=Path("b.md"),
    ),
]


def load(posts=POSTS):
    return json.loads(postindex.build(SITE, posts))


def test_it_is_json_and_counts_what_it_holds():
    payload = load()

    assert payload["count"] == 2
    assert len(payload["posts"]) == 2


def test_it_keeps_the_order_it_was_given():
    assert [post["slug"] for post in load()["posts"]] == [
        "2026-08-01-daily-digest",
        "older-note",
    ]


def test_every_url_carries_the_base_prefix_and_a_trailing_slash():
    for post in load()["posts"]:
        assert post["url"] == f"/it-blog/posts/{post['slug']}/"


def test_a_post_without_tags_gets_an_empty_list_not_null():
    assert load()["posts"][1]["tags"] == []
    assert load()["posts"][0]["tags"] == ["digest", "news"]


def test_the_summary_falls_back_to_the_body_the_way_the_pages_do():
    # Post.summary skips the heading; the index must not reimplement that.
    assert load()["posts"][1]["summary"] == POSTS[1].summary
    assert "Heading" not in load()["posts"][1]["summary"]


def test_dates_are_machine_readable_and_human_readable():
    first = load()["posts"][0]

    assert first["date"] == "2026-08-01"
    assert first["display_date"] == "August 1, 2026"


def test_no_posts_still_makes_valid_json():
    assert load([]) == {"count": 0, "posts": []}


def test_awkward_characters_survive_the_round_trip():
    awkward = Post(
        slug="awkward",
        title='He said "hello" & left — abruptly </script>',
        date=dt.date(2026, 8, 1),
        description="Quotes \\ backslashes — and ünïcode.",
        tags=("c#",),
        body="Body.",
        source=Path("c.md"),
    )

    only = load([awkward])["posts"][0]

    assert only["title"] == awkward.title
    assert only["summary"] == awkward.description
    assert only["tags"] == ["c#"]
