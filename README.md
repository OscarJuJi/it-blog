# it-blog

A personal blog with two authors: an agent that publishes a technology news
digest twice a week, and me.

Live at <https://oscarjuji.github.io/it-blog/>.

Nothing here is a framework. The static site generator in [`ssg/`](ssg/) is
written from scratch — front matter parsing, templating, RSS, sitemap — with
[mistune](https://mistune.lepture.com/) as the only dependency, because getting
Markdown right is a long tail of edge cases. The agent in [`agent/`](agent/) is
written from scratch too, over `urllib` and `xml.etree`.

## Layout

| Path | What it is |
|---|---|
| `content/posts/*.md` | Every post. The source of truth for the whole site. |
| `ssg/` | The generator: `frontmatter` → `posts` → `markdown` → `render` → `build`, plus `feed`, `sitemap`, `robots`, `postindex` and `tags`. |
| `agent/` | The twice-weekly digest: `feeds` → `history` → `rank` → `article` → `llm` → `digest`, driven by `run`. `repair` refills a digest already published. |
| `templates/`, `static/` | Page templates, the stylesheet, and the CMS at `static/admin/`. |
| `scripts/` | Run by hand or by a workflow: `new_post`, `repair_posts`, `make_og_image`. |
| `config.toml` | Site settings and the agent's feed list. |
| `docs/DESIGN.md` | Why the pieces are shaped the way they are. This file says how to use them. |
| `tests/` | `pytest`. The build and the digest both have integration tests. |

## Running it locally

```bash
python -m venv .venv && .venv/Scripts/activate    # source .venv/bin/activate on Linux
pip install -r requirements.txt

python -m pytest -q                # the test suite
python -m ssg.build --serve        # build and preview on http://127.0.0.1:8000/it-blog/
```

`--serve` answers the `/it-blog/` prefix that the deployed pages use, so links
work locally exactly as they do in production.

## Writing a post

Either way ends up as a Markdown file in `content/posts/`, and any commit to
`main` rebuilds and redeploys the site.

**In the browser.** Go to [`/admin/`](https://oscarjuji.github.io/it-blog/admin/)
and press *Sign In with Token*. It wants a GitHub fine-grained personal access
token with read and write access to *Contents* on this repository. Saving a post
there commits it for you.

**From the terminal.**

```bash
python scripts/new_post.py "What I learned about CUDA" --tags cuda,notes
```

Then edit the file it prints and push it.

The front matter is `title` and `date` (required), plus `description` and `tags`.
Every tag gets a page of its own at `/tags/<tag>/`, alongside the browser-side
`?tag=` filter on the front page.

The slug is the **whole** filename stem, date prefix included, so
`2026-08-01-daily-digest.md` is served at `/posts/2026-08-01-daily-digest/`.
That is deliberate: every digest is called `daily-digest`, and dropping the date
would make the second one collide with the first. It did, once, in production —
`tests/test_posts.py::test_a_recurring_post_gets_one_url_per_day` is the
executable version of this paragraph.

## The agent

Every Tuesday and Friday [`digest.yml`](.github/workflows/digest.yml) reads the
feeds listed in `config.toml`, keeps what was published in the last day, drops
duplicates and non-English titles, and hands about twenty candidates to Gemini.

The model answers with JSON that points at candidates **by index** and never
writes a URL. Every link in the published post is copied from the feed it came
from, so a wrong summary is possible but an invented source is not.

Its prose is treated as untrusted all the same. Posts render with HTML escaped,
and every page carries a Content-Security-Policy that allows scripts only from
this origin — the agent summarizes pages nobody here controls, and this origin
is also the one serving the CMS. [`docs/DESIGN.md`](docs/DESIGN.md) has the
reasoning.

If the model is unreachable, or too few of its picks survive validation, the
agent publishes the reading list with no prose rather than skipping the day.

```bash
python -m agent.run --dry-run --llm none      # what the feeds have, no model
python -m agent.run --dry-run --llm ollama    # draft with a local model
python -m agent.run                           # write content/posts/<date>-weekly-digest.md
```

The run is idempotent: if the day's file exists it stops, unless given `--force`.

## Setting it up elsewhere

1. Point `config.toml` at your own `url` and `base_url`, and `static/admin/config.yml`
   at your own repository.
2. Repository *Settings → Pages → Source: GitHub Actions*.
3. Add a `GEMINI_API_KEY` secret ([free key from AI Studio](https://aistudio.google.com/apikey)).
   Without it the agent still runs, and still publishes links.
