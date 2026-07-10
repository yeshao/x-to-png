from card_renderer import compute_token


def test_returns_nonempty_string():
    tok = compute_token("1445078208190291973")
    assert isinstance(tok, str) and tok


def test_deterministic():
    assert compute_token("1445078208190291973") == compute_token("1445078208190291973")


def test_different_ids_usually_differ():
    assert compute_token("1445078208190291973") != compute_token("20")


def test_handles_bad_input_without_raising():
    assert compute_token("not-an-id") == "0"
