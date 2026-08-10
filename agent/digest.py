"""Turning a shortlist of feed entries into the Markdown of the day's post.

The model never writes a URL. It answers with JSON that points at entries by
index, and the links in the published post are copied from the feeds themselves.
A model can therefore get a summary wrong -- it cannot invent a source.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Callable, Sequence

from agent.feeds import Entry
from agent.llm import LLM, LLMError
from ssg.posts import format_date

# Every agent-written post carries this, and nothing else does. It is what lets
# the history check tell a post the agent wrote from one a human did.
MARKER_TAG = "digest"
MIN_USABLE_STORIES = 3
MAX_TOPICS = 3
# How many times to ask before settling for a list of links. An answer that
# comes back unusable is usually unusable by chance -- the model was cut off, or
# wandered out of JSON -- and the same prompt at temperature asked twice rarely
# fails the same way twice. Transport failures are not retried here; the HTTP
# client has already done that by the time it raises.
ATTEMPTS = 3
DESCRIPTION_LIMIT = 200

SYSTEM = (
    "You write the daily technology digest for a working software engineer's blog. "
    "You are accurate before you are interesting, and you never pad."
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class DigestError(RuntimeError):
    """Raised when the model's answer cannot be turned into a digest."""


@dataclass(frozen=True)
class Story:
    """One item of the digest: the model's words over a real entry."""

    entry: Entry
    headline: str
    summary: str


def build(
    day: dt.date,
    entries: Sequence[Entry],
    *,
    llm: LLM | None = None,
    min_stories: int = 5,
    max_stories: int = 10,
    topics: Sequence[str] = (),
    max_topics: int = MAX_TOPICS,
    attempts: int = ATTEMPTS,
    on_error: Callable[[str], None] = print,
) -> str:
    """Return the Markdown file for *day*, falling back to links if need be."""
    if not entries:
        raise DigestError("no entries to write about")

    for attempt in range(1, attempts + 1) if llm is not None else ():
        try:
            intro, stories, chosen = write(
                llm,
                entries,
                day=day,
                min_stories=min_stories,
                max_stories=max_stories,
                topics=topics,
                max_topics=max_topics,
                on_note=on_error,
            )
            return render(day, intro, stories, chosen)
        except LLMError as error:
            # The model could not be reached. Asking again would only wait longer.
            on_error(f"writing links only: {error}")
            break
        except DigestError as error:
            on_error(f"attempt {attempt} of {attempts} came back unusable: {error}")

    return render_links(day, entries[:max_stories])


def write(
    llm: LLM,
    entries: Sequence[Entry],
    *,
    day: dt.date,
    min_stories: int,
    max_stories: int,
    topics: Sequence[str] = (),
    max_topics: int = MAX_TOPICS,
    on_note: Callable[[str], None] = lambda _: None,
) -> tuple[str, list[Story], tuple[str, ...]]:
    """Ask the model to choose and summarize, and check what comes back."""
    answer = llm.generate(
        prompt(
            entries,
            day=day,
            min_stories=min_stories,
            max_stories=max_stories,
            topics=topics,
            max_topics=max_topics,
        ),
        system=SYSTEM,
    )
    payload = _json(answer, on_note=on_note)

    intro = str(payload.get("intro", "")).strip()
    chosen = _topics(
        payload.get("topics"), allowed=topics, limit=max_topics, on_note=on_note
    )
    stories = _stories(payload.get("stories"), entries, limit=max_stories)
    # A digest of one or two items is not worth publishing -- unless that is all
    # the configuration ever asked for.
    floor = min(MIN_USABLE_STORIES, max_stories)
    if len(stories) < floor:
        raise DigestError(f"only {len(stories)} usable stories came back")
    return intro, stories, chosen


def prompt(
    entries: Sequence[Entry],
    *,
    day: dt.date,
    min_stories: int,
    max_stories: int,
    topics: Sequence[str] = (),
    max_topics: int = MAX_TOPICS,
) -> str:
    """The whole instruction, candidates included."""
    vocabulary = ", ".join(topics)
    topic_rule = (
        f"- Tag the digest with 1 to {max_topics} topics describing what it "
        f"actually covers. Choose only from this list, exactly as spelled: "
        f"{vocabulary}. If nothing fits, return an empty list.\n"
        if topics
        else ""
    )
    topic_field = '\n  "topics": ["..."],' if topics else ""
    candidates = "\n\n".join(
        f"[{number}] {entry.title}\n"
        f"    source: {entry.source}\n"
        f"    link: {entry.link}\n"
        f"    feed summary: {entry.summary or '(none)'}"
        for number, entry in enumerate(entries, start=1)
    )
    return f"""Today is {format_date(day)}. Below are {len(entries)} stories \
pulled from technology news feeds in the last day.

Choose the {min_stories} to {max_stories} that matter most to a working software \
engineer, and write the digest.

Rules:
- Base every summary only on the title and feed summary given. If they are thin, \
say only what the headline supports. Never invent details, numbers, quotes or names.
- Two or three sentences per story. Say what happened and why a developer should \
care. No hype, no filler openings like "In a move that".
- Prefer a spread of topics over five variations of the same story.
- Skip press releases, funding announcements without substance, and pure marketing.
- Rewrite each headline in plain language. Do not copy it word for word if it is \
clickbait.
- Do not write any URLs. Refer to a story by its index number.
{topic_rule}
Answer with JSON and nothing else, in this shape:

{{"intro": "one sentence on the shape of the day, no more",{topic_field}
  "stories": [{{"index": 1, "headline": "...", "summary": "..."}}]}}

The stories:

{candidates}
"""


def render(
    day: dt.date,
    intro: str,
    stories: Sequence[Story],
    topics: Sequence[str] = (),
) -> str:
    """Assemble the post from the model's words and our own links."""
    sections = "\n\n".join(
        f"## {_link(story.headline, story.entry.link)}\n\n"
        f"{story.summary}\n\n"
        f"*{story.entry.source}*"
        for story in stories
    )
    body = f"{intro}\n\n{sections}" if intro else sections
    return _document(
        day,
        description=intro or _first_headline(stories),
        body=body,
        footer="Selected and summarized automatically from the sources linked above.",
        topics=topics,
    )


def render_links(day: dt.date, entries: Sequence[Entry]) -> str:
    """The digest we publish when the model is unavailable: sources, no prose."""
    note = (
        "The summaries could not be generated today, so here is the reading list "
        "on its own."
    )
    links = "\n".join(
        f"- {_link(entry.title, entry.link)} - *{entry.source}*" for entry in entries
    )
    return _document(
        day,
        description=note,
        body=f"{note}\n\n{links}",
        footer="Selected automatically from the sources linked above.",
    )


def _topics(
    raw: object,
    *,
    allowed: Sequence[str],
    limit: int,
    on_note: Callable[[str], None] = lambda _: None,
) -> tuple[str, ...]:
    """The model's topics, kept only where they match the agreed vocabulary.

    A closed vocabulary rather than whatever the model feels like saying: free
    text invents a near-synonym most days, and a tag that appears once is a tag
    nobody can browse by. Rejections are reported rather than swallowed -- the
    log is how you find out which topic the list is missing.
    """
    if not isinstance(raw, list):
        return ()

    permitted = {topic.strip().lower() for topic in allowed}
    kept: list[str] = []
    for item in raw:
        topic = str(item).strip().lower()
        if not topic or topic in kept or topic == MARKER_TAG:
            continue
        if topic not in permitted:
            on_note(f"ignoring topic outside the vocabulary: {topic!r}")
            continue
        kept.append(topic)
        if len(kept) == limit:
            break
    return tuple(kept)


def _document(
    day: dt.date,
    *,
    description: str,
    body: str,
    footer: str,
    topics: Sequence[str] = (),
) -> str:
    title = f"Daily digest: {format_date(day)}"
    tags = "\n".join(f"  - {tag}" for tag in (MARKER_TAG, *topics))
    return (
        "---\n"
        f"title: {_quote(title)}\n"
        f"date: {day.isoformat()}\n"
        f"description: {_quote(_shorten(description))}\n"
        "tags:\n"
        f"{tags}\n"
        "---\n"
        "\n"
        f"{body}\n"
        "\n"
        f"*{footer}*\n"
    )


def _stories(raw: object, entries: Sequence[Entry], *, limit: int) -> list[Story]:
    """Keep the items that point at a real entry and actually say something."""
    if not isinstance(raw, list):
        raise DigestError("the answer has no list of stories")

    stories: list[Story] = []
    used: set[int] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", 0))
        except (TypeError, ValueError):
            continue
        if not 1 <= index <= len(entries) or index in used:
            continue

        entry = entries[index - 1]
        headline = " ".join(str(item.get("headline", "") or entry.title).split())
        summary = " ".join(str(item.get("summary", "")).split())
        if not summary:
            continue

        used.add(index)
        stories.append(Story(entry=entry, headline=headline, summary=summary))
        if len(stories) == limit:
            break

    return stories


def _json(
    answer: str, *, on_note: Callable[[str], None] = lambda _: None
) -> dict:
    """Read the JSON out of an answer that may be wrapped, fenced, or cut short.

    A model that stops mid-array leaves a block ending at the last story it
    finished -- valid up to that point, and missing only its closing brackets.
    Rather than lose the whole digest over the story that never arrived, close
    the brackets and keep what did.
    """
    match = _JSON_BLOCK.search(answer)
    if match is None:
        raise DigestError(f"no JSON in the answer: {answer[:200]!r}")

    block = match.group(0)
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as error:
        closed = _close(block)
        try:
            payload = json.loads(closed)
        except json.JSONDecodeError:
            raise DigestError(
                f"the answer is not valid JSON: {error}: {answer[:400]!r}"
            ) from error
        on_note(
            f"the answer arrived truncated at {len(block)} characters; "
            "salvaging the stories that did arrive"
        )

    if not isinstance(payload, dict):
        raise DigestError("the answer is not a JSON object")
    return payload


def _close(block: str) -> str:
    """Add the brackets an answer that stopped early never got to write.

    Returns *block* untouched when the cut landed inside a string, where there
    is nothing safe to guess.
    """
    stack: list[str] = []
    in_string = escaped = False

    for char in block:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack:
            stack.pop()

    if in_string:
        return block
    return block + "".join(reversed(stack))


def _link(text: str, url: str) -> str:
    """A Markdown link that survives brackets in the text and spaces in the URL."""
    label = text.replace("[", "\\[").replace("]", "\\]")
    target = f"<{url}>" if re.search(r"[\s()]", url) else url
    return f"[{label}]({target})"


def _quote(value: str) -> str:
    """Quote a front matter value. Our parser has no escapes, so neither do we."""
    return '"{}"'.format(" ".join(value.split()).replace('"', "'"))


def _shorten(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= DESCRIPTION_LIMIT:
        return collapsed
    return f"{collapsed[: DESCRIPTION_LIMIT - 3].rstrip()}..."


def _first_headline(stories: Sequence[Story]) -> str:
    return stories[0].headline if stories else "Today in technology."
