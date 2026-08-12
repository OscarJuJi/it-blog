import datetime as dt

import pytest

from agent import digest, history
from agent.feeds import Entry

DAY = dt.date(2026, 8, 10)


def entry(title, link, source="Hacker News"):
    return Entry(
        title=title,
        link=link,
        source=source,
        summary="A summary.",
        published=dt.datetime(2026, 8, 10, 9, tzinfo=dt.timezone.utc),
    )


def story(title, link):
    return digest.Story(entry=entry(title, link), headline=title, summary="Said thing.")


def write_digest(tmp_path, day, *pairs, marker=True):
    """Publish a real digest document, the way the agent does."""
    document = digest.render(
        day, "Intro.", [story(title, link) for title, link in pairs]
    )
    if not marker:
        document = document.replace(f"  - {digest.MARKER_TAG}\n", "  - meta\n")
    path = tmp_path / f"{day.isoformat()}-daily-digest.md"
    path.write_text(document, encoding="utf-8")
    return path


def test_recent_digests_hands_back_what_the_last_editions_said(tmp_path):
    # `seen` answers "have we covered this link". This answers "what did we
    # say", which is what lets the next digest notice a story continuing.
    write_digest(tmp_path, dt.date(2026, 8, 4), ("An older thing", "https://example.com/old"))
    write_digest(tmp_path, dt.date(2026, 8, 7), ("A thing", "https://example.com/a"))

    recent = history.recent_digests(
        tmp_path, before=dt.date(2026, 8, 11), limit=2, marker=digest.MARKER_TAG
    )

    assert [past.date for past in recent] == [dt.date(2026, 8, 7), dt.date(2026, 8, 4)]
    assert "A thing" in recent[0].headlines
    assert recent[0].description


def test_recent_digests_keeps_only_as_many_as_asked_for(tmp_path):
    for day in (1, 4, 7):
        write_digest(tmp_path, dt.date(2026, 8, day), (f"Thing {day}", f"https://example.com/{day}"))

    recent = history.recent_digests(
        tmp_path, before=dt.date(2026, 8, 11), limit=2, marker=digest.MARKER_TAG
    )

    assert [past.date for past in recent] == [dt.date(2026, 8, 7), dt.date(2026, 8, 4)]


def test_recent_digests_ignores_posts_a_person_wrote(tmp_path):
    write_digest(tmp_path, dt.date(2026, 8, 7), ("Mine", "https://example.com/mine"), marker=False)

    assert history.recent_digests(
        tmp_path, before=dt.date(2026, 8, 11), limit=2, marker=digest.MARKER_TAG
    ) == []


def test_it_finds_the_links_of_a_published_digest(tmp_path):
    write_digest(tmp_path, dt.date(2026, 8, 9), ("A thing", "https://example.com/a"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    assert history.was_seen(entry("A thing", "https://example.com/a"), seen)


def test_it_reads_the_angle_bracket_link_form_too(tmp_path):
    # _link() switches to <...> when the URL has spaces or parentheses.
    write_digest(tmp_path, dt.date(2026, 8, 9), ("Odd", "https://example.com/a(b)"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    assert history.was_seen(entry("Odd", "https://example.com/a(b)"), seen)


def test_tracking_parameters_do_not_hide_a_repeat(tmp_path):
    write_digest(tmp_path, dt.date(2026, 8, 9), ("A thing", "https://example.com/a"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    repeat = entry("A thing", "http://www.example.com/a/?utm_source=hn")
    assert history.was_seen(repeat, seen)


def test_the_same_story_from_another_outlet_is_caught_by_its_title(tmp_path):
    write_digest(tmp_path, dt.date(2026, 8, 9), ("Rust 2.0 Released!", "https://a.com/x"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    syndicated = entry("rust 2.0 released", "https://completely-different.com/y")
    assert history.was_seen(syndicated, seen)


def test_a_genuinely_new_story_survives(tmp_path):
    write_digest(tmp_path, dt.date(2026, 8, 9), ("Old news", "https://example.com/old"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    assert not history.was_seen(entry("Fresh", "https://example.com/new"), seen)


def test_posts_without_the_marker_are_ignored(tmp_path):
    # A hand-written post linking somewhere must not suppress a news story.
    write_digest(
        tmp_path, dt.date(2026, 8, 9), ("A thing", "https://example.com/a"), marker=False
    )

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    assert not history.was_seen(entry("A thing", "https://example.com/a"), seen)


def test_posts_older_than_the_window_are_ignored(tmp_path):
    write_digest(tmp_path, dt.date(2026, 7, 1), ("Ancient", "https://example.com/a"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    assert not history.was_seen(entry("Ancient", "https://example.com/a"), seen)


def test_the_day_being_rewritten_is_excluded(tmp_path):
    # --force --date X must not dedupe against the very file it is replacing.
    write_digest(tmp_path, DAY, ("Today", "https://example.com/today"))

    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)

    assert not history.was_seen(entry("Today", "https://example.com/today"), seen)


def test_a_missing_directory_is_simply_no_history(tmp_path):
    seen = history.seen(
        tmp_path / "nope", before=DAY, days=14, marker=digest.MARKER_TAG
    )

    assert not history.was_seen(entry("Anything", "https://example.com/a"), seen)


def test_unseen_drops_the_repeats(tmp_path):
    write_digest(tmp_path, dt.date(2026, 8, 9), ("Old", "https://example.com/old"))
    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)
    entries = [entry("Old", "https://example.com/old"), entry("New", "https://e.com/n")]

    kept = history.unseen(entries, seen, keep_at_least=1)

    assert [e.title for e in kept] == ["New"]


def test_unseen_gives_back_the_newest_repeats_rather_than_skip_the_day(tmp_path):
    write_digest(
        tmp_path,
        dt.date(2026, 8, 9),
        ("One", "https://e.com/1"),
        ("Two", "https://e.com/2"),
    )
    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)
    entries = [entry("One", "https://e.com/1"), entry("Two", "https://e.com/2")]

    notes = []
    kept = history.unseen(entries, seen, keep_at_least=2, on_note=notes.append)

    assert len(kept) == 2
    assert notes and "already covered" in notes[0]


def test_unseen_without_history_changes_nothing(tmp_path):
    seen = history.seen(tmp_path, before=DAY, days=14, marker=digest.MARKER_TAG)
    entries = [entry("A", "https://e.com/a"), entry("B", "https://e.com/b")]

    assert history.unseen(entries, seen, keep_at_least=5) == entries
