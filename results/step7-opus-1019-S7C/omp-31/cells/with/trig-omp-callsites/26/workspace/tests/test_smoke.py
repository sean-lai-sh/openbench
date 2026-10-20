from svc import api


def test_v2():
    assert api.fetch_v2('u') == 'body:u:5'
