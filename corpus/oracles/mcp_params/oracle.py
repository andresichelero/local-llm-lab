import bottle


def test_private_contract():
    assert bottle._parse_http_header('text/html; Q=0.5,application/json; LEVEL=1') == [('text/html', {'q': '0.5'}), ('application/json', {'level': '1'})]
    assert bottle._parse_http_header('text/plain') == [('text/plain', {})]
