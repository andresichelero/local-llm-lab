import bottle


def test_private_contract():
    assert bottle._re_flatten('(abc)') == '(?:abc)'
    assert bottle._re_flatten('(?P<n>a)') == '(?:a)'
    assert bottle._re_flatten(r'\(a\)') == r'\(a\)'
