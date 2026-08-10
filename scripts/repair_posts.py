"""Repair digests that were published before the agent could do better.

    python scripts/repair_posts.py --retag  --dry-run
    python scripts/repair_posts.py --refill --dry-run
    python scripts/repair_posts.py --retag --refill      # actually writes

Two jobs, deliberately separate because they carry different risk.

--retag reads what a post already says and gives it topics from the configured
vocabulary. Nothing is invented: the words being classified are the words on the
site. Only the `tags:` block changes.

--refill rewrites a digest that went out as a bare list of links, by fetching
the articles *that post already links to* and summarising those. It never
re-runs the feeds: the collection window is twenty-six hours, so asking for an
old date would file today's news under a past one. The rewritten post says in
its own body that the summaries came later.

Needs GEMINI_API_KEY. There is a `Repair posts` workflow that runs this in CI,
where the key already lives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import article, digest, repair
from agent.llm import LLMError, from_environment
from ssg.posts import load_all
from ssg.site import ROOT, load_config

POSTS = ROOT / "content" / "posts"


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _ask(model, prompt: str) -> dict:
    answer = model.generate(prompt, system=digest.SYSTEM)
    return digest._json(answer, on_note=_warn)


def retag(model, settings, *, dry_run: bool) -> int:
    topics = settings.get("topics", [])
    limit = settings.get("max_topics", digest.MAX_TOPICS)
    changed = 0

    for post in load_all(POSTS, include_drafts=True):
        if digest.MARKER_TAG not in post.tags:
            continue
        prompt = (
            f"Below is a technology digest published on {post.date.isoformat()}.\n"
            f"Choose 1 to {limit} topics describing what it actually covers.\n"
            f"Choose only from this list, exactly as spelled: {', '.join(topics)}.\n"
            'Answer with JSON and nothing else: {"topics": ["..."]}\n\n'
            f"{post.body[:6000]}"
        )
        try:
            chosen = digest._topics(
                _ask(model, prompt).get("topics"),
                allowed=topics,
                limit=limit,
                on_note=_warn,
            )
        except LLMError as error:
            # The model is unreachable, not this post's problem. Saying so once
            # beats the same line repeated for every file.
            _warn(f"stopping: {error}")
            break
        except digest.DigestError as error:
            _warn(f"{post.source.name}: {error}")
            continue

        document = post.source.read_text(encoding="utf-8")
        updated = repair.retag(document, chosen)
        if updated == document:
            continue
        print(f"  {post.source.name}: {digest.MARKER_TAG} + {', '.join(chosen) or '(none)'}")
        if not dry_run:
            post.source.write_text(updated, encoding="utf-8", newline="\n")
        changed += 1

    return changed


def refill(model, *, dry_run: bool) -> int:
    changed = 0

    for post in load_all(POSTS, include_drafts=True):
        document = post.source.read_text(encoding="utf-8")
        if not repair.is_links_only(document):
            continue
        items = repair.reading_list(document)
        if not items:
            _warn(f"{post.source.name}: no reading list found")
            continue

        bodies = {}
        for index, item in enumerate(items):
            text = article.fetch(item.link)
            if len(text) >= article.USEFUL:
                bodies[index] = text[:3000]
        print(f"  {post.source.name}: read {len(bodies)} of {len(items)} articles")
        if not bodies:
            _warn(f"{post.source.name}: nothing could be read; leaving it alone")
            continue

        listing = "\n\n".join(
            f"[{i}] {items[i].title}\n    source: {items[i].source}\n    article: {bodies[i]}"
            for i in sorted(bodies)
        )
        prompt = (
            "Below are the articles a technology digest linked to. Write two or "
            "three sentences on each: what happened and why a working software "
            "engineer should care. Base every summary only on the text given; "
            "never invent details, numbers, quotes or names. No hype.\n\n"
            'Answer with JSON and nothing else, in this shape:\n'
            '{"intro": "one sentence on the shape of the day",\n'
            ' "summaries": [{"index": 0, "summary": "..."}]}\n\n'
            f"{listing}\n"
        )
        try:
            payload = _ask(model, prompt)
        except LLMError as error:
            _warn(f"stopping: {error}")
            break
        except digest.DigestError as error:
            _warn(f"{post.source.name}: {error}")
            continue

        summaries = {
            int(row["index"]): str(row.get("summary", "")).strip()
            for row in payload.get("summaries", [])
            if isinstance(row, dict) and str(row.get("index", "")).lstrip("-").isdigit()
        }
        intro = str(payload.get("intro", "")).strip()
        if not summaries or not intro:
            _warn(f"{post.source.name}: the model returned nothing usable")
            continue

        updated = repair.refill(document, items, summaries, intro=intro)
        if not dry_run:
            post.source.write_text(updated, encoding="utf-8", newline="\n")
        changed += 1

    return changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retag", action="store_true", help="give old digests real topics")
    parser.add_argument("--refill", action="store_true", help="summarise links-only digests")
    parser.add_argument("--dry-run", action="store_true", help="say what would change")
    args = parser.parse_args(argv)

    if not (args.retag or args.refill):
        parser.error("choose --retag, --refill, or both")

    settings = load_config().get("agent", {})
    try:
        model = from_environment(model=settings.get("model", ""))
    except LLMError as error:
        print(f"no model available: {error}", file=sys.stderr)
        return 1
    print(f"repairing with {model.name}{' (dry run)' if args.dry_run else ''}")

    total = 0
    if args.refill:
        print("refilling links-only digests:")
        total += refill(model, dry_run=args.dry_run)
    if args.retag:
        print("retagging:")
        total += retag(model, settings, dry_run=args.dry_run)

    print(f"{total} post(s) {'would change' if args.dry_run else 'changed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
