import bottle


def test_private_contract():
    assert bottle._hval('  value  ') == '  value  '
    for bad in ('a\nb', 'a\rb', 'a\0b'):
        try:
            bottle._hval(bad)
        except ValueError:
            pass
        else:
            assert False, 'control character accepted'
