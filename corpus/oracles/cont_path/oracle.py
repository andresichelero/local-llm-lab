import bottle


def test_private_contract():
    assert bottle.path_shift('/app', '/a/b/', 1) == ('/app/a', '/b/')
    assert bottle.path_shift('/app/x', '/b/', -1) == ('/app', '/x/b/')
    assert bottle.path_shift('/a', '/b/', 0) == ('/a', '/b/')
