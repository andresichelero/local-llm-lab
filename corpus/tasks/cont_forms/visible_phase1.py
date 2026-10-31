import bottle

def text_form():
    return bottle.FormsDict(name='café'.encode('utf8').decode('latin1'))
assert text_form().getunicode('name') == 'café'
