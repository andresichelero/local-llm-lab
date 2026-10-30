import bottle


def test_private_contract():
    assert bottle.template("{{! '<b>' }}") == '<b>'
    assert bottle.template("{{ '<b>' }}") == '&lt;b&gt;'
