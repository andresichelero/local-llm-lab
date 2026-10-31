import bottle


def test_private_contract():
    assert bottle.http_date(0) == 'Thu, 01 Jan 1970 00:00:00 GMT'
    assert bottle.http_date(' raw ') == ' raw '
    assert bottle.http_date(86400) == 'Fri, 02 Jan 1970 00:00:00 GMT'
