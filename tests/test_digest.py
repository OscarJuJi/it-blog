import datetime as dt
import json

import pytest

from agent import digest
from agent.feeds import Entry
from agent.llm import LLMError
from ssg import posts

DAY = dt.date(2026, 8, 1)

ENTRIES = [
    Entry(
        title="Rust 2.0 ships",
        link="https://example.com/rust-2",
        summary="The release lands today.",
        published=None,
        source="Ars Technica",
    ),
    Entry(
        title="A database rewrite",
        link="https://example.com/db?utm_source=rss",
        summary="",
        published=None,
        source="Hacker News",
    ),
    Entry(
        title="Third story",
        link="https://example.com/third",
        summary="",
        published=None,
        source="The Verge",
    ),
    Entry(
        title="Fourth story",
        link="https://example.com/fourth",
        summary="",
        published=None,
        source="dev.to",
    ),
]


class FakeLLM:
    """Answers with whatever the test decided, and remembers what it was asked."""

    name = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.prompt = None
        self.system = None

    def generate(self, prompt, *, system=""):
        self.prompt, self.system = prompt, system
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def answer(*indices, intro="A quiet day.", topics=None, description=None):
    payload = {
        "intro": intro,
        "stories": [
            {
                "index": index,
                "headline": f"Headline {index}",
                "summary": f"Summary of story {index}.",
            }
            for index in indices
        ],
    }
    if topics is not None:
        payload["topics"] = topics
    if description is not None:
        payload["description"] = description
    return json.dumps(payload)


ALLOWED = ("ai", "security", "web", "databases")


def tags_of(document, tmp_path, name="2026-08-01-daily-digest.md"):
    path = tmp_path / name
    path.write_text(document, encoding="utf-8")
    return posts.load(path).tags


def test_the_marker_tag_is_always_there_and_comes_first(tmp_path):
    document = digest.build(
        DAY,
        ENTRIES,
        llm=FakeLLM(answer(1, 2, 3, topics=["security", "ai"])),
        topics=ALLOWED,
    )

    assert tags_of(document, tmp_path) == (digest.MARKER_TAG, "security", "ai")


def test_a_topic_outside_the_vocabulary_is_dropped_and_reported(tmp_path):
    notes = []
    document = digest.build(
        DAY,
        ENTRIES,
        llm=FakeLLM(answer(1, 2, 3, topics=["ai", "cryptozoology"])),
        topics=ALLOWED,
        on_error=notes.append,
    )

    assert tags_of(document, tmp_path) == (digest.MARKER_TAG, "ai")
    assert any("cryptozoology" in note for note in notes)


def test_topics_are_capped(tmp_path):
    document = digest.build(
        DAY,
        ENTRIES,
        llm=FakeLLM(answer(1, 2, 3, topics=["ai", "security", "web", "databases"])),
        topics=ALLOWED,
        max_topics=2,
    )

    assert tags_of(document, tmp_path) == (digest.MARKER_TAG, "ai", "security")


def test_duplicates_and_stray_capitals_collapse(tmp_path):
    document = digest.build(
        DAY,
        ENTRIES,
        llm=FakeLLM(answer(1, 2, 3, topics=["AI", "ai", " Security "])),
        topics=ALLOWED,
    )

    assert tags_of(document, tmp_path) == (digest.MARKER_TAG, "ai", "security")


def test_an_answer_with_no_topics_still_publishes(tmp_path):
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3)), topics=ALLOWED)

    assert tags_of(document, tmp_path) == (digest.MARKER_TAG,)


def test_the_links_only_fallback_claims_no_topics(tmp_path):
    # Nobody classified that day, so saying otherwise would be a lie.
    document = digest.build(DAY, ENTRIES, llm=None, topics=ALLOWED)

    assert tags_of(document, tmp_path) == (digest.MARKER_TAG,)


def test_the_prompt_lists_the_vocabulary_it_will_accept():
    text = digest.prompt(
        ENTRIES, day=DAY, min_stories=3, max_stories=5, topics=ALLOWED, max_topics=3
    )

    for topic in ALLOWED:
        assert topic in text


def test_the_configured_vocabulary_is_safe_in_hand_built_frontmatter():
    # _document writes YAML by hand and frontmatter.py has no escapes, so a topic
    # carrying a colon, a leading bracket or a newline would corrupt every post.
    from ssg.site import load_config

    for topic in load_config().get("agent", {}).get("topics", []):
        assert topic == topic.strip().lower()
        assert not any(ch in topic for ch in ':[]{}#,"\'\n')


class FlakyLLM:
    """Answers differently each call, so a retry can be told from a repeat."""

    name = "flaky"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def generate(self, prompt, *, system=""):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_an_unusable_answer_is_asked_for_again():
    model = FlakyLLM("I would rather not.", answer(1, 2, 3))

    document = digest.build(DAY, ENTRIES, llm=model, on_error=lambda _: None)

    assert model.calls == 2
    assert "summaries could not be generated" not in document
    assert "Headline 1" in document


def test_it_stops_asking_after_the_last_attempt():
    model = FlakyLLM(*["I would rather not."] * digest.ATTEMPTS)

    document = digest.build(DAY, ENTRIES, llm=model, on_error=lambda _: None)

    assert model.calls == digest.ATTEMPTS
    assert "summaries could not be generated" in document


def test_an_unreachable_model_is_not_asked_again():
    # The HTTP client already exhausted its own retries before raising, so
    # asking again here would only multiply the wait.
    model = FlakyLLM(LLMError("503"), answer(1, 2, 3))

    document = digest.build(DAY, ENTRIES, llm=model, on_error=lambda _: None)

    assert model.calls == 1
    assert "summaries could not be generated" in document


def test_every_attempt_says_which_one_it_was():
    problems = []
    digest.build(
        DAY, ENTRIES, llm=FlakyLLM(*["nope"] * digest.ATTEMPTS), on_error=problems.append
    )

    assert len(problems) == digest.ATTEMPTS
    assert "1" in problems[0] and "nope" in problems[0]


def cut_short(*indices, intro="A quiet day."):
    """A pretty-printed answer that stops partway through its last story.

    This is the shape that reached production: the model stopped mid-array, and
    what survived ended at the closing brace of the last story it finished.
    """
    full = json.dumps(
        {
            "intro": intro,
            "stories": [
                {
                    "index": index,
                    "headline": f"Headline {index}",
                    "summary": f"Summary of story {index}.",
                }
                for index in indices
            ],
        },
        indent=2,
    )
    return full[: full.rindex('"summary"')]


def test_a_truncated_answer_still_publishes_the_stories_that_arrived():
    document = digest.build(
        DAY, ENTRIES, llm=FakeLLM(cut_short(1, 2, 3, 4)), on_error=lambda _: None
    )

    assert "summaries could not be generated" not in document
    assert document.count("## [") == 3
    assert "Headline 4" not in document


def test_a_truncated_answer_that_arrived_too_short_still_falls_back():
    document = digest.build(
        DAY, ENTRIES, llm=FakeLLM(cut_short(1, 2)), on_error=lambda _: None
    )
    assert "summaries could not be generated" in document


def test_salvaging_a_truncated_answer_says_so():
    problems = []
    digest.build(DAY, ENTRIES, llm=FakeLLM(cut_short(1, 2, 3, 4)), on_error=problems.append)

    assert problems and "truncated" in problems[0]


def test_the_error_repeats_what_the_model_actually_answered():
    problems = []
    digest.build(
        DAY, ENTRIES, llm=FakeLLM('{"stories": [oh no]}'), on_error=problems.append
    )

    assert problems and "oh no" in problems[0]


def test_the_post_it_writes_is_a_post_the_generator_can_load(tmp_path):
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3)))

    path = tmp_path / "2026-08-01-daily-digest.md"
    path.write_text(document, encoding="utf-8")
    post = posts.load(path)

    # Not "Daily digest" any more: it goes out Tuesdays and Fridays, and the
    # title is the one piece of this a reader actually sees.
    assert post.title == "Digest: August 1, 2026"
    assert post.date == DAY
    assert post.tags == (digest.MARKER_TAG,)
    assert post.description == "A quiet day."
    assert post.slug == "2026-08-01-daily-digest"


def test_the_description_is_not_the_body_repeated(tmp_path):
    # The card, the <meta> and the post itself used to open with the same
    # sentence, because `intro` was serving as both.
    document = digest.build(
        DAY,
        ENTRIES,
        llm=FakeLLM(
            answer(1, 2, 3, intro="A quiet day.", description="Rust 2.0 and a rewrite.")
        ),
    )

    path = tmp_path / "2026-08-01-daily-digest.md"
    path.write_text(document, encoding="utf-8")
    post = posts.load(path)

    assert post.description == "Rust 2.0 and a rewrite."
    assert post.body.lstrip().startswith("A quiet day.")


def test_a_model_that_writes_no_description_still_gets_one(tmp_path):
    # Every answer before this field existed is this case, and the intro is a
    # better description than nothing.
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3, intro="A quiet day.")))

    path = tmp_path / "2026-08-01-daily-digest.md"
    path.write_text(document, encoding="utf-8")

    assert posts.load(path).description == "A quiet day."


def test_a_blank_description_falls_back_to_the_intro(tmp_path):
    document = digest.build(
        DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3, intro="A quiet day.", description="   "))
    )

    path = tmp_path / "2026-08-01-daily-digest.md"
    path.write_text(document, encoding="utf-8")

    assert posts.load(path).description == "A quiet day."


def test_the_prompt_asks_for_a_description_that_is_not_the_intro():
    text = digest.prompt(ENTRIES, day=DAY, min_stories=3, max_stories=5)

    assert '"description"' in text
    # The whole point is that the two differ, so the instruction has to say so.
    assert "description" in text and "intro" in text


def test_links_come_from_the_feeds_not_from_the_model():
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3)))

    assert "(https://example.com/rust-2)" in document
    assert "## [Headline 1](https://example.com/rust-2)" in document
    assert "*Ars Technica*" in document


def test_a_story_pointing_at_no_entry_is_dropped():
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 99, 2, 3)))

    assert document.count("## [") == 3
    assert "Headline 99" not in document


def test_the_same_entry_twice_is_only_published_once():
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 1, 2, 3)))
    assert document.count("## [") == 3


def test_json_wrapped_in_a_code_fence_is_still_read():
    fenced = f"Here you go:\n\n```json\n{answer(1, 2, 3)}\n```\n"
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(fenced))
    assert "Headline 1" in document


def test_more_stories_than_asked_for_are_cut():
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3, 4)), max_stories=2)
    assert document.count("## [") == 2


def test_falls_back_to_links_when_the_model_is_unreachable():
    problems = []
    document = digest.build(
        DAY, ENTRIES, llm=FakeLLM(LLMError("503")), on_error=problems.append
    )

    assert "summaries could not be generated" in document
    assert "- [Rust 2.0 ships](https://example.com/rust-2)" in document
    assert problems and "503" in problems[0]


def test_falls_back_when_too_few_stories_survive():
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1)), on_error=lambda _: None)
    assert "summaries could not be generated" in document


def test_falls_back_when_the_answer_is_not_json():
    document = digest.build(
        DAY, ENTRIES, llm=FakeLLM("I would rather not."), on_error=lambda _: None
    )
    assert "summaries could not be generated" in document


def test_the_links_only_post_also_loads(tmp_path):
    path = tmp_path / "2026-08-01-daily-digest.md"
    path.write_text(digest.render_links(DAY, ENTRIES), encoding="utf-8")
    assert posts.load(path).tags == (digest.MARKER_TAG,)


def test_quotes_in_a_summary_cannot_break_the_front_matter(tmp_path):
    reply = json.dumps(
        {
            "intro": 'He said "hello"\nand left',
            "stories": [
                {"index": index, "headline": f"H{index}", "summary": "S."}
                for index in (1, 2, 3)
            ],
        }
    )
    path = tmp_path / "2026-08-01-daily-digest.md"
    path.write_text(digest.build(DAY, ENTRIES, llm=FakeLLM(reply)), encoding="utf-8")

    assert posts.load(path).description == "He said 'hello' and left"


def test_brackets_in_a_headline_do_not_break_the_link():
    reply = json.dumps(
        {
            "intro": "",
            "stories": [
                {"index": 1, "headline": "A [bracketed] headline", "summary": "S."},
                {"index": 2, "headline": "H2", "summary": "S."},
                {"index": 3, "headline": "H3", "summary": "S."},
            ],
        }
    )
    document = digest.build(DAY, ENTRIES, llm=FakeLLM(reply))
    assert "## [A \\[bracketed\\] headline](https://example.com/rust-2)" in document


def test_without_a_model_it_publishes_the_links():
    document = digest.build(DAY, ENTRIES, llm=None)
    assert "summaries could not be generated" in document


def test_the_footer_does_not_claim_summaries_nobody_wrote():
    written = digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3)))
    links_only = digest.build(DAY, ENTRIES, llm=None)

    assert written.rstrip().endswith("*Selected and summarized automatically from the sources linked above.*")
    assert links_only.rstrip().endswith("*Selected automatically from the sources linked above.*")


def test_no_entries_is_an_error():
    with pytest.raises(digest.DigestError, match="no entries"):
        digest.build(DAY, [], llm=None)


def test_the_prompt_carries_what_the_last_editions_covered():
    from agent.history import PastDigest

    previously = [
        PastDigest(
            date=dt.date(2026, 8, 7),
            description="Rust and a database rewrite.",
            headlines=("Rust 2.0 reaches beta", "A database rewrite"),
        )
    ]

    text = digest.prompt(
        ENTRIES, day=DAY, min_stories=3, max_stories=5, previously=previously
    )

    assert "Rust 2.0 reaches beta" in text
    assert "August 7, 2026" in text
    # Knowing what ran is useless unless the model is told what to do about it.
    assert "continu" in text.lower()


def test_the_prompt_says_nothing_about_past_editions_when_there_are_none():
    text = digest.prompt(ENTRIES, day=DAY, min_stories=3, max_stories=5)

    assert "previous edition" not in text.lower()


def test_summaries_that_come_back_short_are_reported(tmp_path):
    # qwen3:8b answered a real prompt with 2-3 sentences per story where the
    # rule asks for four to six, and nothing anywhere said so: the digest
    # published, green, just thinner than intended. Length is the whole point of
    # the twice-weekly edition, so falling short has to be visible in the log.
    notes = []
    digest.build(DAY, ENTRIES, llm=FakeLLM(answer(1, 2, 3)), on_error=notes.append)

    assert any("shorter" in note for note in notes)


def test_summaries_of_the_length_asked_for_are_not_complained_about():
    long_enough = "This is what happened, at the length the rules ask for. " * 10
    reply = json.dumps(
        {
            "intro": "A quiet day.",
            "stories": [
                {"index": index, "headline": f"H{index}", "summary": long_enough}
                for index in (1, 2, 3)
            ],
        }
    )
    notes = []
    digest.build(DAY, ENTRIES, llm=FakeLLM(reply), on_error=notes.append)

    assert not any("shorter" in note for note in notes)


def test_the_prompt_asks_for_summaries_worth_the_wait():
    text = digest.prompt(ENTRIES, day=DAY, min_stories=3, max_stories=5)

    # Twice-weekly means each story has to carry more than a sentence.
    assert "Two or three sentences" not in text
    assert "four to six sentences" in text.lower()


def test_the_prompt_carries_every_candidate_and_forbids_urls():
    model = FakeLLM(answer(1, 2, 3))
    digest.build(DAY, ENTRIES, llm=model, min_stories=5, max_stories=10)

    assert "[1] Rust 2.0 ships" in model.prompt
    assert "[4] Fourth story" in model.prompt
    assert "Do not write any URLs" in model.prompt
    assert "5 to 10" in model.prompt
    assert model.system == digest.SYSTEM
