import bottle


def test_private_contract():
    t = bottle.SimpleTemplate('{{name}}|{{!name}}')
    assert t.render({'name': 'old'}, {'name': 'middle'}, name='<b>') == '&lt;b&gt;|<b>'
    assert t.render({'name': 'one'}, {'name': 'two'}) == 'two|two'
