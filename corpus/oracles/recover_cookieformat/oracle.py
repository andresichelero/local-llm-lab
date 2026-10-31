import bottle


def test_private_contract():
    assert bottle.cookie_is_encoded(b'!a?b')
    assert not bottle.cookie_is_encoded(b'!abc')
    assert not bottle.cookie_is_encoded(b'!')
    assert not bottle.cookie_is_encoded(b' !a?')
    assert not bottle.cookie_is_encoded(b'abc')
