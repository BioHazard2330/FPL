from fpl_agent.live.image_proxy import fetch_image


def test_only_official_image_hosts_are_proxied(tmp_path):
    assert fetch_image("https://evil.example.com/a.png", tmp_path) is None
    assert fetch_image("http://resources.premierleague.com/a.png", tmp_path) is None
    assert fetch_image("https://resources.premierleague.com/a.exe", tmp_path) is None


def test_a_cached_image_is_served_from_disk(tmp_path):
    import hashlib

    url = "https://resources.premierleague.com/premierleague25/photos/players/110x140/1.png"
    (tmp_path / (hashlib.sha1(url.encode()).hexdigest() + ".png")).write_bytes(b"PNGDATA")
    assert fetch_image(url, tmp_path) == (b"PNGDATA", "image/png")
