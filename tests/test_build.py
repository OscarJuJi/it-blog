"""Integration: build the real site, with the real templates, into a temp folder."""

import datetime as dt
from xml.etree import ElementTree

import pytest

from ssg import build as build_module
from ssg.site import ROOT

NOW = dt.datetime(2026, 8, 1, 13, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def site_dir(tmp_path_factory):
    output = tmp_path_factory.mktemp("build") / "_site"
    build_module.build(output=output, now=NOW)
    return output


def read(path):
    return path.read_text(encoding="utf-8")


def test_writes_an_index_listing_every_post(site_dir):
    posts = build_module.load_all(ROOT / "content" / "posts")
    index = read(site_dir / "index.html")

    assert "<!doctype html>" in index
    for post in posts:
        assert post.title in index
        assert f'href="/ti-blog/{post.path}"' in index


def test_writes_a_page_per_post_with_rendered_markdown(site_dir):
    page = read(site_dir / "posts" / "2026-08-01-how-this-blog-works" / "index.html")

    assert "<h1>How this blog works</h1>" in page
    assert "<h2>The generator</h2>" in page
    assert "<code>frontmatter.py</code>" in page
    assert 'href="https://mistune.lepture.com/"' in page


def test_writes_the_json_index_the_browser_fetches(site_dir):
    import json

    payload = json.loads(read(site_dir / "posts.json"))
    posts = build_module.load_all(ROOT / "content" / "posts")

    assert payload["count"] == len(posts)
    assert payload["posts"][0]["url"].startswith("/ti-blog/posts/")


def test_the_page_tells_the_script_where_the_index_lives(site_dir):
    index = read(site_dir / "index.html")

    assert 'data-posts-url="/ti-blog/posts.json"' in index
    assert 'src="/ti-blog/app.js"' in index
    assert (site_dir / "app.js").exists()


def test_every_card_is_addressable_by_slug(site_dir):
    index = read(site_dir / "index.html")

    for post in build_module.load_all(ROOT / "content" / "posts"):
        assert f'data-slug="{post.slug}"' in index


def test_the_enhanced_controls_are_hidden_in_the_served_html(site_dir):
    # The no-JS contract: a visitor without scripts sees no dead controls.
    index = read(site_dir / "index.html")

    assert "<div class=\"toolbar\" data-toolbar hidden>" in index
    assert "data-load-more hidden" in index


def test_the_sidebar_rides_along_on_every_kind_of_page(site_dir):
    for path in (
        site_dir / "index.html",
        site_dir / "posts" / "2026-08-01-how-this-blog-works" / "index.html",
        site_dir / "404.html",
    ):
        page = read(path)
        assert 'class="tag-cloud"' in page
        assert "Recent entries" in page


def test_the_tag_cloud_lists_each_tag_once_and_links_it_home(site_dir):
    index = read(site_dir / "index.html")
    posts = build_module.load_all(ROOT / "content" / "posts")
    tags = {tag for post in posts for tag in post.tags}

    for tag in tags:
        assert index.count(f'data-tag="{tag}"') == 1
        assert f'href="/ti-blog/?tag={tag}"' in index


def test_the_recent_widget_is_capped_and_newest_first(site_dir):
    import re

    index = read(site_dir / "index.html")
    widget = re.search(r'<ul class="recent">(.*?)</ul>', index, re.DOTALL).group(1)
    posts = build_module.load_all(ROOT / "content" / "posts")

    assert widget.count("<li>") <= 5
    assert posts[0].title in widget


def test_a_post_links_to_its_neighbours_and_the_ends_only_have_one(site_dir):
    posts = build_module.load_all(ROOT / "content" / "posts")
    newest = read(site_dir / posts[0].path / "index.html")
    oldest = read(site_dir / posts[-1].path / "index.html")

    assert 'rel="prev"' in newest and 'rel="next"' not in newest
    assert 'rel="next"' in oldest and 'rel="prev"' not in oldest


def test_a_tag_gets_a_page_of_its_own(site_dir):
    page = read(site_dir / "tags" / "digest" / "index.html")
    posts = build_module.load_all(ROOT / "content" / "posts")
    tagged = [p for p in posts if "digest" in p.tags]

    assert page.count('class="post-item"') == len(tagged)
    for post in posts:
        if "digest" not in post.tags:
            assert post.title not in page


def test_a_tag_with_one_post_says_entry_not_entries(site_dir):
    # The templates cannot branch, so the whole label is built in Python -- and
    # the template must not append the noun itself.
    page = read(site_dir / "tags" / "python" / "index.html")

    assert '<p class="index-count">1 entry</p>' in page
    assert "entry entries" not in page


def test_a_tag_page_leaves_the_script_asleep(site_dir):
    # app.js starts only when both hooks are present. If it woke up here its
    # click handler would preventDefault the sidebar chips and they would stop
    # navigating -- the one way a tag page can silently break.
    page = read(site_dir / "tags" / "digest" / "index.html")

    assert "data-toolbar" not in page
    assert "data-posts-list" not in page


def test_tag_pages_are_in_the_sitemap(site_dir):
    assert "/ti-blog/tags/digest/" in read(site_dir / "sitemap.xml")


def test_robots_points_at_the_sitemap_by_absolute_url(site_dir):
    robots = read(site_dir / "robots.txt")

    assert "User-agent: *" in robots
    assert "Sitemap: https://oscarjuji.github.io/ti-blog/sitemap.xml" in robots


def test_the_social_card_is_absolute_and_actually_exists(site_dir):
    index = read(site_dir / "index.html")

    assert 'content="https://oscarjuji.github.io/ti-blog/og.png"' in index
    # A card pointing at a 404 is worse than no card at all.
    assert (site_dir / "og.png").exists()


def test_a_post_declares_itself_an_article_and_the_index_a_website(site_dir):
    posts = build_module.load_all(ROOT / "content" / "posts")

    assert '<meta property="og:type" content="website">' in read(site_dir / "index.html")
    assert '<meta property="og:type" content="article">' in read(
        site_dir / posts[0].path / "index.html"
    )


def test_internal_links_carry_the_project_prefix(site_dir):
    page = read(site_dir / "posts" / "2026-08-01-how-this-blog-works" / "index.html")

    assert 'href="/ti-blog/style.css"' in page
    assert 'href="/ti-blog/feed.xml"' in page
    assert 'href="/ti-blog/admin/"' in page


def test_copies_static_files_and_the_admin_panel(site_dir):
    assert (site_dir / "style.css").is_file()
    assert (site_dir / "admin" / "index.html").is_file()
    assert (site_dir / "admin" / "config.yml").is_file()


def test_writes_the_feed_the_sitemap_and_the_marker(site_dir):
    feed_root = ElementTree.fromstring(read(site_dir / "feed.xml"))
    assert feed_root.find("channel").findall("item")

    sitemap_root = ElementTree.fromstring(read(site_dir / "sitemap.xml"))
    assert len(sitemap_root) >= 2

    assert (site_dir / ".nojekyll").is_file()
    assert (site_dir / "404.html").is_file()


def test_no_placeholder_survives_in_the_output(site_dir):
    for page in site_dir.rglob("*.html"):
        assert "{{" not in read(page), f"unrendered placeholder in {page}"


def test_rebuilding_over_a_previous_build_is_fine(tmp_path):
    output = tmp_path / "_site"
    build_module.build(output=output, now=NOW)
    build_module.build(output=output, now=NOW)
    assert (output / "index.html").is_file()


def test_refuses_to_erase_a_directory_it_did_not_build(tmp_path):
    output = tmp_path / "not-a-build"
    output.mkdir()
    (output / "important.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(build_module.BuildError, match="refusing to erase"):
        build_module.build(output=output, now=NOW)

    assert (output / "important.txt").is_file()
