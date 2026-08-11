"""What a post is allowed to put on the page.

The generator used to pass raw HTML straight through, on the reasoning that
every post arrives as a commit and its author is therefore trusted. That was
true when the only author was Oscar. It stopped being true the day the agent
started writing summaries out of feed entries and article bodies it fetches from
the open web: a prompt injection in any linked page is now an author.
"""

from ssg.markdown import to_html


def test_a_script_in_a_post_is_shown_not_run():
    html = to_html("A summary <script>steal()</script> and more.")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_an_event_handler_smuggled_through_an_image_is_shown_not_run():
    html = to_html('Look <img src=x onerror="fetch(evil)"> here.')

    assert "<img" not in html
    assert "onerror" not in html.replace("&lt;img src=x onerror=&quot;fetch(evil)&quot;&gt;", "")


def test_a_javascript_url_does_not_survive_as_a_link():
    html = to_html("[click](javascript:alert(1))")

    assert "javascript:" not in html


def test_ordinary_markdown_still_renders():
    html = to_html("# Title\n\nA [link](https://example.com) and `code`.\n")

    assert "<h1>Title</h1>" in html
    assert '<a href="https://example.com">link</a>' in html
    assert "<code>code</code>" in html


def test_the_plugins_the_blog_relies_on_are_still_on():
    table = to_html("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in table
    assert "<del>gone</del>" in to_html("~~gone~~")
