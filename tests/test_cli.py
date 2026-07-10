import pytest

from card_renderer import build_parser


def test_text_with_value():
    args = build_parser().parse_args(["123456", "--text", "hello world"])
    assert args.url_or_id == "123456"
    assert args.text == "hello world"


def test_text_as_last_arg_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["123456", "--text"])
    assert exc.value.code == 2


def test_only_text_given_errors(capsys):
    # Regression for #11: this used to raise IndexError instead of a clean usage error.
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--text", "hello"])
    assert exc.value.code == 2


def test_no_args_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([])
    assert exc.value.code == 2


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_output_positional_is_optional():
    args = build_parser().parse_args(["123456"])
    assert args.output is None


def test_output_positional_given():
    args = build_parser().parse_args(["123456", "out.png"])
    assert args.output == "out.png"


def test_force_and_local_flags_default_false():
    args = build_parser().parse_args(["123456"])
    assert args.force is False
    assert args.local is False


def test_force_and_local_flags_set():
    args = build_parser().parse_args(["123456", "--force", "--local"])
    assert args.force is True
    assert args.local is True
