from ai_scraper.redaction import redact_text, redact_url


def test_url_and_secret_redaction():
    assert (
        redact_url("https://user:pass@example.com/path?token=secret#x")
        == "https://example.com/path"
    )
    value = redact_text("Authorization: Bearer abc.def token=secret")
    assert "abc.def" not in value
    assert "secret" not in value
