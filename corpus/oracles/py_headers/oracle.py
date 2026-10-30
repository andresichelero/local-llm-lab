import bottle


def test_private_contract():
    h = bottle.HeaderDict()
    h.append('X-Test', 'one')
    h.append('x-test', 'two')
    assert h.get('X-TEST') == 'two'
    assert h.get('x-test', index=0) == 'one'
    assert h.get('missing', default='none') == 'none'
