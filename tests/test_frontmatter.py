import pytest

from ssg import frontmatter


def test_reads_scalars_and_body():
    metadata, body = frontmatter.split(
        "---\ntitle: Hello world\ndate: 2026-08-01\n---\n\nThe body.\n"
    )
    assert metadata == {"title": "Hello world", "date": "2026-08-01"}
    assert body == "The body."


def test_strips_one_layer_of_quotes():
    metadata, _ = frontmatter.split("---\ntitle: \"Quoted: it works\"\n---\n")
    assert metadata["title"] == "Quoted: it works"


# `quote` lives here rather than beside its callers because it is the inverse of
# `_scalar`: whoever changes how a value is read has to see how it is written.


@pytest.mark.parametrize(
    "value",
    [
        'He said "hi"',
        "Line one\ntags: injected\nmore",
        "trailing backslash \\",
        "  padded  and    spaced  ",
        "Kubernetes: the hard way",
        "[bracketed] and #hashed",
    ],
)
def test_a_quoted_value_reads_back_on_one_line(value):
    metadata, _ = frontmatter.split(
        f"---\ntitle: {frontmatter.quote(value)}\ndate: 2026-08-01\n---\n\nbody\n"
    )

    assert list(metadata) == ["title", "date"]
    assert "\n" not in metadata["title"]
    assert metadata["date"] == "2026-08-01"


@pytest.mark.parametrize(
    "value",
    ['ends with a backslash \\', r"a path C:\Users\PC", 'both "quoted" and \\ slashed'],
)
def test_a_quoted_value_carries_nothing_another_parser_would_read_as_an_escape(value):
    """This parser is not the only one that reads these files.

    Sveltia parses the front matter as real YAML, where a backslash opens an
    escape sequence: `description: "a \\"` never finds its closing quote, and
    `"C:\\Users"` is an unknown escape. Either one makes the CMS unable to open
    a post that this generator renders perfectly well -- the same split that
    once turned `*dev.to*` into `_dev.to_`. So the written value carries no
    character any reader could take as an escape.
    """
    written = frontmatter.quote(value)

    assert "\\" not in written
    assert written.count('"') == 2
    assert written.startswith('"') and written.endswith('"')


def test_quoting_keeps_the_words_even_when_it_cannot_keep_the_punctuation():
    written = frontmatter.quote('The day AI ate "everything" at once')

    metadata, _ = frontmatter.split(f"---\ntitle: {written}\n---\n\nbody\n")

    assert metadata["title"] == "The day AI ate 'everything' at once"


def test_keeps_a_hash_inside_a_value():
    metadata, _ = frontmatter.split("---\ntitle: C# in 2026\n---\n")
    assert metadata["title"] == "C# in 2026"


def test_reads_a_flow_list():
    metadata, _ = frontmatter.split("---\ntags: [python, web dev, ai]\n---\n")
    assert metadata["tags"] == ["python", "web dev", "ai"]


def test_reads_an_indented_block_list():
    metadata, _ = frontmatter.split("---\ntags:\n  - python\n  - notes\ntitle: T\n---\n")
    assert metadata["tags"] == ["python", "notes"]
    assert metadata["title"] == "T"


def test_an_empty_value_is_an_empty_string():
    metadata, _ = frontmatter.split("---\ntitle: T\ndescription:\n---\n")
    assert metadata["description"] == ""


def test_ignores_comment_lines():
    metadata, _ = frontmatter.split("---\n# a comment\ntitle: T\n---\n")
    assert metadata == {"title": "T"}


def test_handles_windows_line_endings():
    metadata, body = frontmatter.split("---\r\ntitle: T\r\n---\r\n\r\nBody line.\r\n")
    assert metadata == {"title": "T"}
    assert body == "Body line."


def test_a_horizontal_rule_in_the_body_is_left_alone():
    _, body = frontmatter.split("---\ntitle: T\n---\n\nBefore.\n\n---\n\nAfter.\n")
    assert body == "Before.\n\n---\n\nAfter."


def test_rejects_a_document_without_a_block():
    with pytest.raises(frontmatter.FrontmatterError, match="does not open"):
        frontmatter.split("Just a body.\n")


def test_rejects_an_unclosed_block():
    with pytest.raises(frontmatter.FrontmatterError, match="never closed"):
        frontmatter.split("---\ntitle: T\n\nBody.\n")


def test_rejects_a_duplicate_key():
    with pytest.raises(frontmatter.FrontmatterError, match="duplicate key"):
        frontmatter.split("---\ntitle: One\ntitle: Two\n---\n")


def test_rejects_a_line_that_is_not_a_pair():
    with pytest.raises(frontmatter.FrontmatterError, match="not a 'key: value' pair"):
        frontmatter.split("---\ntitle: T\nnonsense\n---\n")
