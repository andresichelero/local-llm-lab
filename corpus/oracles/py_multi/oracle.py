import bottle


def test_private_contract():
    d = bottle.MultiDict()
    for value in ('4', 'bad', '9'): d.append('n', value)
    assert d.get('n', type=int) == 9
    assert d.get('n', index=0, type=int) == 4
    assert d.get('n', index=1, type=int, default='fallback') == 'fallback'
    assert d.get('n', index=8, default='fallback') == 'fallback'
    assert d.get('absent', default='fallback') == 'fallback'
