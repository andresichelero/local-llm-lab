import bottle


def test_private_contract():
    c = bottle.ConfigDict()
    c.load_dict({'a': {'b': {'c': 1}, 'd': 2}, 'x': 3}, namespace='root')
    assert dict(c) == {'root.a.b.c': 1, 'root.a.d': 2, 'root.x': 3}
