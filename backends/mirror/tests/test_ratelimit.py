from starlette.requests import Request

from app.ratelimit import client_address


def request(headers):
    return Request({"type": "http", "headers": [(key.encode(), value.encode()) for key, value in headers],
                    "client": ("10.0.0.5", 1234)})


def test_client_cannot_spoof_forwarding_headers():
    spoofed = request([("x-forwarded-for", "1.2.3.4"), ("cf-connecting-ip", "5.6.7.8")])
    assert client_address(spoofed) == "10.0.0.5"
    assert client_address(request([("x-real-ip", "192.0.2.1")])) == "192.0.2.1"
