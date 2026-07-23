from etl.domains import reverse_domain, normalize_domain

def test_reverse_domain():
    assert reverse_domain("omni.co") == "co.omni"
    assert reverse_domain("co.omni") == "omni.co"          # symmetric
    assert reverse_domain("sigmacomputing.com") == "com.sigmacomputing"

def test_normalize_domain():
    assert normalize_domain("  WWW.Example.COM. ") == "example.com"
    assert normalize_domain("hex.tech") == "hex.tech"
