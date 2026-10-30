import bottle

r = bottle.Router()
r.add('/item/<item:int>', 'GET', 'x', name='item')
assert r.build('item', item=7, q='red blue') == '/item/7?q=red+blue'
print('visible: PASS')
