from notes import hooks


def test_save_and_autosave():
    d = hooks.save("a", "hello  ")
    assert d["text"] == "hello\n" and d["saves"] == 1
    assert hooks.autosave("a")["saves"] == 2
    assert hooks.autosave("missing") is None
