import bottle


def test_private_contract():
    assert list(bottle.parse_range_header('bytes=0-0,5-99,-2', 8)) == [(0, 1), (5, 8), (6, 8)]
    assert list(bottle.parse_range_header('bytes=9-12', 8)) == []
