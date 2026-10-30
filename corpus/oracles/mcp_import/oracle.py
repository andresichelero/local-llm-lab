import bottle


def test_private_contract():
    assert bottle.load('builtins:str("ABC")') == 'ABC'
    import string
    assert bottle.load('string:Formatter') is string.Formatter
