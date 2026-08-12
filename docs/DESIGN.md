# Design

Why the pieces are shaped the way they are. The README says how to use them.

## The generator is written by hand

The point of this blog is partly the blog and partly the building of it, so
everything that could reasonably be written from scratch was: the front matter
parser, the template engine, the RSS feed, the sitemap.

The exception is Markdown. Both the CMS and the agent emit ordinary Markdown, and
a hand-rolled subset parser would render some of it wrong — tables one day,
nested lists the next. `mistune` is small, pure Python, and removes that whole
class of failure. It is the only runtime dependency.

The front matter parser accepts a deliberately small subset of YAML: scalars,
flow lists, block lists. That is everything this blog writes. A small grammar
means a malformed post fails loudly at build time instead of rendering strangely.

The template engine has two features, `{{ value }}` and `{{ value | safe }}`, and
raises on an unknown name. Loops live in Python, where they are easy to test: the
build renders a fragment per post and passes the joined string through `| safe`.
A missing value is an error rather than an empty string, because a silently blank
page is the failure that is hardest to notice.

## Links are ours, prose is the model's

The agent hands the model a numbered list of candidates and asks for JSON that
refers to them **by index**. The model is told not to write URLs, and its answer
is validated: an index outside the list is dropped, a repeated index is dropped,
a story with no summary is dropped.

The published Markdown is then assembled from our own data. Every link is copied
from the feed entry it belongs to. The consequence is worth stating plainly: the
model can summarize a story badly, but it cannot invent a source, and it cannot
attach a real headline to a URL that does not exist.

The site says out loud that the digests are machine-written, and each one ends
with a line saying so.

## Twice a week, with a memory

The digest went out every morning until 2026-08-11 over a 26-hour window. Five
thin posts a week is what that produced: whatever happened to be in the feeds
that morning, a sentence or two each. It now goes out Tuesday and Friday over a
96-hour window, with fewer stories and several paragraphs on each.

Widening the window was not enough on its own, and this is the part worth
remembering. `rank.select` orders by recency and nothing else — there is no
notion of "important" anywhere in it — then keeps `per_feed_limit` per source
before truncating to `candidate_limit`. Over four days those two caps fill up
with the newest day and quietly discard everything older, so the model would
have been choosing "the best of yesterday" out of a wider net. The limits had to
rise with the window, and they are commented in `config.toml` as a pair for that
reason.

The other half is memory. `history.recent_digests` reads the last two published
editions and hands the model their headlines and descriptions, so a story that
has moved on since Tuesday is written as what changed rather than introduced
again to a reader who already read it here. It is deliberately a separate
function from `history.seen`: that one answers "have we covered this link" with
a set built to be tested against, this one answers "what did we say" with
ordered prose. Same files on disk, different questions.

Only headlines and descriptions travel, never the bodies. The prompt already
runs to roughly 11,000 tokens; two whole digests would add thousands more to say
what the headlines already say.

## The agent is an author nobody vetted

"Links are ours" bounds what a wrong answer can do to the *content*. It says
nothing about what an answer could do to the *reader*, and that gap stayed open
for a while because the first author here was a person, committing to a
repository nobody else could push to.

It is worth being precise about who is writing now. The agent summarizes feed
entries and, when a feed says too little, the body of the linked article — text
from the open web, chosen by whoever published it. A prompt injection on any of
those pages is an author of this blog. The origin it writes into is the same one
that serves `/admin/`, where the CMS keeps a GitHub token with write access to
this repository.

Hence three locks on one door, none of them trusting the others:

- `ssg/markdown.py` renders with `escape=True`, so raw HTML in a post comes out
  as text rather than as markup.
- `templates/base.html` carries a Content-Security-Policy, in a `<meta>` because
  GitHub Pages sends no headers we can set. `script-src 'self'` is the
  load-bearing part.
- `static/admin/index.html` pins the CMS to one version with an SRI hash.
  Unpinned, that page ran whatever the CDN served that morning.

The cost of escaping was measured rather than assumed: the rendered `<main>` of
every post that existed at the time came back byte-identical to what was already
published. It gives up an embed nobody has used yet.

The same policy is what keeps the stylesheet honest. `style-src 'self'` means no
inline `style=`, no `<style>` block and no web font from a CDN, so everything the
site looks like lives in `static/style.css` on system font stacks.

## Failure is expected, not exceptional

A feed being down, a rate limit, a model returning prose instead of JSON: each of
these happens eventually, and none should cost an edition.

- `feeds.collect` reports a dead source and carries on with the rest.
- `llm._post` retries the status codes that pass on their own (429, 5xx) and
  fails fast on the ones that do not (400). A socket that times out mid-read
  raises `TimeoutError` rather than `URLError`, so it is caught explicitly —
  uncaught it escaped the fallback below and killed the run outright.
- `digest.build` falls back to a plain reading list when the model is unreachable
  or its answer does not validate.

The one thing the agent will not do is publish an empty post: with no entries at
all it exits non-zero and leaves the day alone.

## Deploying

GitHub Pages serves this as a *project* site, so every internal URL carries the
`/it-blog` prefix. `Site.path()` is the only place that knows it, and
`build --serve` reproduces the prefix locally so a link that works in preview
works in production.

`build-deploy.yml` exists as a workflow of its own because of one GitHub rule:
**a push made with `GITHUB_TOKEN` does not trigger `on: push`**. If the agent
simply committed, the site would never rebuild. So `digest.yml` commits and then
calls `build-deploy.yml` through `workflow_call`, and skips the call when there
was nothing new to commit.

This generalises, and the generalisation was learned the expensive way:
**any workflow here that commits needs its own deploy job.** `repair-posts.yml`
shipped without one, rewrote nine published posts, went green, and left the site
serving the old copies. It now carries the same `committed` output and the same
call.

The build runs the test suite before it renders anything. A broken post or a
broken parser fails the deploy instead of publishing a broken page.

## Search and filtering, without a server

The front page can search and filter by tag, which on a static host normally
means either a server or shipping a search library. It does neither.

`ssg/postindex.py` writes `posts.json` beside the feed and the sitemap: one
record per post, with the URL **already carrying the `/it-blog` prefix**.
`static/app.js` fetches it and decides which of the post cards to show.

The part worth stating plainly is what the script does *not* do: it never builds
markup. Every card is already in `index.html`, rendered by the same templates as
always; the script only toggles `hidden`. That means there is no second copy of
the card markup to keep in sync, nothing to escape on the client, and the page
without JavaScript is not a fallback that had to be built and tested separately
— it is this same page with no filter applied. If the fetch fails, nothing
changes and the controls stay hidden, so a visitor never meets a dead button.

The matching rule follows from it: the script consumes URLs, never constructs
them. `?tag=` links come from Python, so the prefix survives; a hand-joined path
would quietly drop it.

It also means the script reads `data-*` attributes and never a visual class.
`data-posts-list`, `data-toolbar`, `data-search`, `data-slug` and
`.tag-cloud a[data-tag]` are the contract; everything else about how a card
looks can be redrawn without touching JavaScript, and was.

## A tag has two addresses

The browser filter is one way to see a tag. `/tags/<slug>/` is the other, and it
is a real page: linkable, indexable, and working with scripts off. `ssg/tags.py`
groups the posts, and the build renders each group through the same card
fragment the index uses — so there is still only one copy of the card markup.

The `?tag=` links in the sidebar deliberately keep pointing at the query string
rather than at the new pages. `app.js` matches them against the raw tags in
`posts.json`, and rewriting them as slugs would break that contract and every
already-published link for no gain.

The one thing the grouping will not do is guess. `slugify` is lossy — `C#` and
`C++` both reduce to `c` — so two tags can want one page, and quietly merging
two subjects is a worse outcome than a build that stops and names them.
`tags.index` raises. On a blog where tags come either from a person or from the
agent's closed vocabulary, a collision is a mistake to fix, not a case to handle.

## Everything is a window

The site used to be flat: hard rules, offset shadows, no rounded corner
anywhere. It is now the other 2008 — the one that was trying to look expensive
at the time — with gradients, bevels and a gloss across anything raised, pulled
through a rust and yellowed-paper palette so it reads as a machine left
somewhere damp rather than as a period revival.

Each post, widget and error page is a window: title bar, frame, inset body. The
three controls at the right of every bar are decoration and carry
`aria-hidden="true"`, because a screen reader announcing three buttons that
minimise nothing is worse than no buttons at all.

The texture is gradients, not images. A repeating background would have meant
either an asset to ship or a data URI to encode, and three very low-contrast
radial gradients read as staining just as well.

## What was left out

No pagination, no analytics, no comments. Pagination becomes worth it somewhere
north of a few hundred posts, since every card is rendered server-side today.
