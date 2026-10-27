import pytest

from study_lock.domain_rules import domain_allowed, normalize_domain


def test_domain_allowed_matches_exact_host_and_subdomains_only():
    assert domain_allowed("chatgpt.com", {"chatgpt.com"}) is True
    assert domain_allowed("sub.chatgpt.com", {"chatgpt.com"}) is True
    assert domain_allowed("notchatgpt.com", {"chatgpt.com"}) is False
    assert domain_allowed("chatgpt.com.evil.test", {"chatgpt.com"}) is False


def test_normalize_domain_rejects_urls_and_paths():
    assert normalize_domain("  ChatGPT.com. ") == "chatgpt.com"
    with pytest.raises(ValueError):
        normalize_domain("https://chatgpt.com/login")
    with pytest.raises(ValueError):
        normalize_domain("")
