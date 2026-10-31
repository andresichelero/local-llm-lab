import bottle


def test_private_contract():
    assert bottle.parse_date('Sun, 06 Nov 1994 08:49:37 GMT') == bottle.parse_date('Sun, 06 Nov 1994 09:49:37 +0100')
    assert bottle.parse_date('not a date') is None
