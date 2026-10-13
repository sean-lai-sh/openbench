from svc import api
import importlib

def test_m00_0():
    m = importlib.import_module('svc.m00')
    assert m.job_0() == 'body:https://example.test/m00/0:5'

def test_m00_1():
    m = importlib.import_module('svc.m00')
    assert m.job_1() == 'body:https://example.test/m00/1:9'

def test_m00_2():
    m = importlib.import_module('svc.m00')
    assert m.job_2() == 'body:https://example.test/m00/2:5'

def test_m00_3():
    m = importlib.import_module('svc.m00')
    assert m.job_3() == 'body:https://example.test/m00/3:9'

def test_m00_4():
    m = importlib.import_module('svc.m00')
    assert m.job_4() == 'body:https://example.test/m00/4:5'

def test_m00_5():
    m = importlib.import_module('svc.m00')
    assert m.job_5() == 'body:https://example.test/m00/5:9'

def test_m01_0():
    m = importlib.import_module('svc.m01')
    assert m.job_0() == 'body:https://example.test/m01/0:5'

def test_m01_1():
    m = importlib.import_module('svc.m01')
    assert m.job_1() == 'body:https://example.test/m01/1:9'

def test_m01_2():
    m = importlib.import_module('svc.m01')
    assert m.job_2() == 'body:https://example.test/m01/2:5'

def test_m01_3():
    m = importlib.import_module('svc.m01')
    assert m.job_3() == 'body:https://example.test/m01/3:9'

def test_m01_4():
    m = importlib.import_module('svc.m01')
    assert m.job_4() == 'body:https://example.test/m01/4:5'

def test_m02_0():
    m = importlib.import_module('svc.m02')
    assert m.job_0() == 'body:https://example.test/m02/0:5'

def test_m02_1():
    m = importlib.import_module('svc.m02')
    assert m.job_1() == 'body:https://example.test/m02/1:9'

def test_m02_2():
    m = importlib.import_module('svc.m02')
    assert m.job_2() == 'body:https://example.test/m02/2:5'

def test_m02_3():
    m = importlib.import_module('svc.m02')
    assert m.job_3() == 'body:https://example.test/m02/3:9'

def test_m03_0():
    m = importlib.import_module('svc.m03')
    assert m.job_0() == 'body:https://example.test/m03/0:5'

def test_m03_1():
    m = importlib.import_module('svc.m03')
    assert m.job_1() == 'body:https://example.test/m03/1:9'

def test_m03_2():
    m = importlib.import_module('svc.m03')
    assert m.job_2() == 'body:https://example.test/m03/2:5'

def test_m03_3():
    m = importlib.import_module('svc.m03')
    assert m.job_3() == 'body:https://example.test/m03/3:9'

def test_m04_0():
    m = importlib.import_module('svc.m04')
    assert m.job_0() == 'body:https://example.test/m04/0:5'

def test_m04_1():
    m = importlib.import_module('svc.m04')
    assert m.job_1() == 'body:https://example.test/m04/1:9'

def test_m04_2():
    m = importlib.import_module('svc.m04')
    assert m.job_2() == 'body:https://example.test/m04/2:5'

def test_m05_0():
    m = importlib.import_module('svc.m05')
    assert m.job_0() == 'body:https://example.test/m05/0:5'

def test_m05_1():
    m = importlib.import_module('svc.m05')
    assert m.job_1() == 'body:https://example.test/m05/1:9'

def test_m05_2():
    m = importlib.import_module('svc.m05')
    assert m.job_2() == 'body:https://example.test/m05/2:5'

def test_m06_0():
    m = importlib.import_module('svc.m06')
    assert m.job_0() == 'body:https://example.test/m06/0:5'

def test_m06_1():
    m = importlib.import_module('svc.m06')
    assert m.job_1() == 'body:https://example.test/m06/1:9'

def test_m06_2():
    m = importlib.import_module('svc.m06')
    assert m.job_2() == 'body:https://example.test/m06/2:5'

def test_m07_0():
    m = importlib.import_module('svc.m07')
    assert m.job_0() == 'body:https://example.test/m07/0:5'

def test_m07_1():
    m = importlib.import_module('svc.m07')
    assert m.job_1() == 'body:https://example.test/m07/1:9'

def test_m08_0():
    m = importlib.import_module('svc.m08')
    assert m.job_0() == 'body:https://example.test/m08/0:5'

def test_m08_1():
    m = importlib.import_module('svc.m08')
    assert m.job_1() == 'body:https://example.test/m08/1:9'

def test_m09_0():
    m = importlib.import_module('svc.m09')
    assert m.job_0() == 'body:https://example.test/m09/0:5'

def test_m10_0():
    m = importlib.import_module('svc.m10')
    assert m.job_0() == 'body:https://example.test/m10/0:5'

def test_m11_0():
    m = importlib.import_module('svc.m11')
    assert m.job_0() == 'body:https://example.test/m11/0:5'


def test_v2_exists():
    assert api.fetch_v2('u') == 'body:u:5'
