import bottle


def test_private_contract():
    try:
        replaced = bottle.touni(bytes([255]), err='replace')
        ignored = bottle.touni(bytes([255]), err='ignore')
    except UnicodeDecodeError:
        assert False, 'decode error policy was not honored'
    assert replaced == '\ufffd'
    assert ignored == ''
    assert bottle.touni(b'hello') == 'hello'
