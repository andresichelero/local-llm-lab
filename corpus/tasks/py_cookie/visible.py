import bottle

response = bottle.BaseResponse()
response.set_cookie('session', {'id': 3}, secret='key')
value = response._cookies['session'].value
request = bottle.BaseRequest({'HTTP_COOKIE': 'other=' + value})
assert request.get_cookie('other', default='no', secret='key') == 'no'
print('visible: PASS')
