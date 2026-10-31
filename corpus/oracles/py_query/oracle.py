import bottle


def test_private_contract():
    assert bottle._parse_qsl('x=a+b&x=%2B&empty=') == [('x', 'a b'), ('x', '+'), ('empty', '')]
    assert bottle._parse_qsl('a=1&&b') == [('a', '1'), ('b', '')]
