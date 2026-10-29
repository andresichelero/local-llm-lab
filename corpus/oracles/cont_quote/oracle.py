import bottle


def test_private_contract():
    assert bottle.html_quote('<\t&\n\r') == '"&lt;&#9;&amp;&#10;&#13;"'
    assert bottle.html_quote('x') == '"x"'
