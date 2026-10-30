import bottle

def text_form():
    return bottle.FormsDict(name='café'.encode('utf8').decode('latin1'))
d = text_form(); d.append('other', b'\xc3\xa9'); decoded = d.decode()
assert d.getunicode('name') == 'café'
assert decoded['other'] == 'é'
