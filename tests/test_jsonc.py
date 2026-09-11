import pytest

from ocbox import image, jsonc


def test_plain_json_passes_through() -> None:
    assert jsonc.loads('{"a": [1, 2], "b": null}') == {"a": [1, 2], "b": None}


def test_line_and_block_comments_are_removed() -> None:
    text = '{\n  // line comment\n  "a": 1, /* block\n comment */ "b": 2\n}'
    assert jsonc.loads(text) == {"a": 1, "b": 2}


def test_double_slash_inside_a_string_is_kept() -> None:
    """Every URL contains `//` - stripping it would break the baseURL."""
    assert jsonc.loads('{"url": "http://127.0.0.1:11434/v1"}') == {
        "url": "http://127.0.0.1:11434/v1"
    }


def test_comment_markers_and_escaped_quotes_inside_strings() -> None:
    text = r'{"s": "say \"/* not a comment */\" // still text"}'
    assert jsonc.loads(text) == {"s": 'say "/* not a comment */" // still text'}


def test_trailing_commas_are_removed() -> None:
    assert jsonc.loads('{"a": [1, 2,], "b": {"c": 3,},}') == {"a": [1, 2], "b": {"c": 3}}


def test_comma_inside_a_string_before_a_brace_is_kept() -> None:
    assert jsonc.loads('{"s": ",}"}') == {"s": ",}"}


def test_invalid_document_raises_jsonc_error() -> None:
    with pytest.raises(jsonc.JsoncError):
        jsonc.loads('{"a": }')


def test_unterminated_block_comment_raises() -> None:
    with pytest.raises(jsonc.JsoncError, match="unterminated"):
        jsonc.loads('{"a": 1 /* oops }')


def test_the_team_opencode_jsonc_parses() -> None:
    data = jsonc.load(image.repo_config_dir() / "opencode.jsonc")
    assert isinstance(data["provider"]["local"]["models"], dict)
