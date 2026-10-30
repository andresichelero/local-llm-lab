import bottle
import pytest

def text_form():
    return bottle.FormsDict(name='café'.encode('utf8').decode('latin1'))
def test_contract():
    d=text_form(); d.append('other', b'\xc3\xa9'); d.append('other', b'\xc3\xb1')
    decoded=d.decode()
    assert d.getunicode('name') == 'café'
    assert d.getunicode('absent', 'fallback') == 'fallback'
    assert bottle.FormsDict(name='\xff').getunicode('name', 'fallback') == 'fallback'
    assert decoded.getall('other') == ['é', 'ñ']
    assert decoded['name'] == 'café'
    assert bottle.FormsDict(key=b'\xe9').decode('latin1')['key'] == 'é'
    latin1_text = bottle.FormsDict(key='é')
    try:
        decoded_latin1 = latin1_text.decode('latin1')
    except UnicodeError:
        pytest.fail('WSGI text must use the requested encoding')
    assert decoded_latin1['key'] == 'é'
    encoded = bottle.FormsDict()
    encoded.append(b'\xc3\xa9', b'\xc3\xb1')
    encoded.append('café'.encode('utf8').decode('latin1'), b'\xc3\xa9')
    assert encoded.decode()['é'] == 'ñ'
    assert encoded.decode()['café'] == 'é'

def test_getunicode_wsgi_text_with_alternative_encoding():
    assert bottle.FormsDict(key='é').getunicode('key', 'fallback', encoding='latin1') == 'é'
