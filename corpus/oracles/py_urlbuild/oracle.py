import bottle


def test_private_contract():
    r = bottle.Router()
    r.add('/item/<item:int>', 'GET', 'x', name='item')
    r.add('/file/<:int>', 'GET', 'x', name='file')
    assert r.build('item', item='03') == '/item/3'
    assert r.build('item', item=4, tag='a b') == '/item/4?tag=a+b'
    assert r.build('file', 9, mode='raw') == '/file/9?mode=raw'
