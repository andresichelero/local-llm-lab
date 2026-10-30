import bottle


def test_private_contract():
    import base64
    def header(value): return 'bAsIc ' + base64.b64encode(value).decode()
    assert bottle.parse_auth(header(b'u:p:q:r')) == ('u', 'p:q:r')
    assert bottle.parse_auth(header(b'u:')) == ('u', '')
    assert bottle.parse_auth(header(b'no-colon')) is None
    assert bottle.parse_auth('Bearer abc') is None
