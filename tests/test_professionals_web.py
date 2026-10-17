"""Website reading: extraction, politeness (robots, limits), blocked sites. No network: httpx.MockTransport."""

import httpx
import pytest

from server.professionals.web import (
    SiteFetcher,
    clean_email,
    email_is_generic,
    extract_page,
    find_emails,
    find_phones,
    looks_blocked,
    normalize_phone,
    probe_site,
)

HOME = """<html><head><title>Dr. Asha Rao | Clinical Psychologist</title>
<meta name="description" content="Therapy for anxiety in Bangalore">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Physician","name":"Asha Rao",
"telephone":"+91 98450 12345","email":"asha@raoclinic.in"}</script></head>
<body><nav><a href="/about">About</a><a href="/contact-us">Contact</a></nav>
<p>RCI Licensed. Follow <a href="https://www.instagram.com/asha.rao.psych/">Instagram</a> and
<a href="https://in.linkedin.com/in/Asha-Rao-12ab">LinkedIn</a>.</p>
<a href="https://wa.me/919845012345">WhatsApp</a><script>var x="ignored@tracker.example.com"</script></body></html>"""

CONTACT = """<html><body><h1>Contact</h1>
<a href="mailto:info@raoclinic.in?subject=Hi">info@raoclinic.in</a> <a href="tel:+918023456789">Call</a>
<p>Landline 080 2345 6789 - mobile 98450 12345 - write to noreply@raoclinic.in</p>
<form><input type="text" name="name"><input type="email" name="email"><textarea name="message"></textarea></form>
</body></html>"""


# ---- pure helpers ---------------------------------------------------------------------------
def test_phone_normalisation():
    assert normalize_phone("98450 12345") == "+919845012345"
    assert normalize_phone("+91-98450-12345") == "+919845012345"
    assert normalize_phone("09845012345") == "+919845012345"
    assert normalize_phone("080 2345 6789") == "+918023456789"   # Bangalore landline = +91 80 2345 6789
    assert normalize_phone("011 2345 6789") == "+911123456789"
    assert normalize_phone("+44 20 7946 0958") == "+442079460958"
    assert normalize_phone("12345") is None and normalize_phone("20240513") is None


def test_phones_found_in_text_but_not_in_numbers_that_are_not_phones():
    found = find_phones("Call 98450 12345 or +91 80 2345 6789, 080 2345 6789. Order 1234567890123, price 1234.56789")
    assert "+919845012345" in found and found.count("+918023456789") == 1  # both spellings of the landline collapse to one
    assert not any("1234567890123" in p for p in found)


def test_emails_deobfuscated_and_junk_removed():
    assert find_emails("write to rao [at] clinic [dot] in") == ["rao@clinic.in"]
    assert find_emails("logo@2x.png noreply@clinic.in privacy@clinic.in me@example.com hello@clinic.in") == ["hello@clinic.in"]
    assert clean_email("  Dr.Rao@Clinic.IN. ") == "dr.rao@clinic.in"
    assert email_is_generic("info@clinic.in") and not email_is_generic("asha.rao@clinic.in")


def test_bot_check_pages_are_recognised_but_big_normal_pages_are_not():
    assert looks_blocked("<title>Just a moment...</title>" + "x" * 500)
    assert not looks_blocked("<html>" + "normal page with a reCAPTCHA form " * 1000 + "</html>")


# ---- extraction -------------------------------------------------------------------------------
def test_extract_home_page():
    p = extract_page(HOME, "https://raoclinic.in/")
    assert ("asha@raoclinic.in", "jsonld") in p.emails
    assert ("+919845012345", "jsonld") in p.phones
    assert p.whatsapp == ["+919845012345"]
    assert p.social == {"instagram": "https://www.instagram.com/asha.rao.psych/", "linkedin": "https://www.linkedin.com/in/asha-rao-12ab"}
    assert p.contact_link == "https://raoclinic.in/contact-us"
    assert p.title.startswith("Dr. Asha Rao") and "anxiety" in p.description
    assert "tracker.example.com" not in " ".join(e for e, _ in p.emails)  # script contents are not page text


def test_extract_contact_page_detects_form_and_ignores_noreply():
    p = extract_page(CONTACT, "https://raoclinic.in/contact-us")
    emails = [e for e, _ in p.emails]
    assert emails == ["info@raoclinic.in"] and p.has_form
    assert "+918023456789" in [x for x, _ in p.phones]
    assert ("+918023456789", "tel") in p.phones


def test_search_and_newsletter_forms_are_not_contact_forms():
    html = '<form role="search"><input type="search" name="q"></form><form><input type="email" name="email"></form>'
    assert not extract_page(html, "https://x.in/").has_form


# ---- fetching -----------------------------------------------------------------------------------
async def public_dns(host):
    return ["93.184.216.34"]            # every test hostname "resolves" to a public address


def fetcher(handler, resolver=public_dns, **kw):
    return SiteFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True),
                       delay=0, resolver=resolver, **kw)


def site(routes, robots="User-agent: *\nAllow: /", log=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots) if robots is not None else httpx.Response(404)
        body = routes.get(request.url.path)
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"}) if body else httpx.Response(404)
    return handler


@pytest.mark.asyncio
async def test_probe_reads_home_and_contact_page_only_and_keeps_provenance():
    log = []
    routes = {"/": HOME, "/contact-us": CONTACT, "/about": "<html>should never be fetched</html>"}
    probe = await probe_site(fetcher(site(routes, log=log)), "https://raoclinic.in/")
    assert probe.status == "ok" and len(probe.pages) == 2
    assert [u for u in log if not u.endswith("robots.txt")] == ["https://raoclinic.in/", "https://raoclinic.in/contact-us"]
    by = {(c.kind, c.value): c for c in probe.channels}
    assert by[("email", "asha@raoclinic.in")].source_url == "https://raoclinic.in/" and not by[("email", "asha@raoclinic.in")].is_generic
    assert by[("email", "info@raoclinic.in")].is_generic and by[("email", "info@raoclinic.in")].source_url.endswith("/contact-us")
    assert by[("contact_form", "https://raoclinic.in/contact-us")].found_via == "form"
    assert ("whatsapp", "+919845012345") in by and ("phone", "+919845012345") in by
    assert len([c for c in probe.channels if (c.kind, c.value) == ("phone", "+919845012345")]) == 1  # de-duplicated
    assert probe.social["instagram"].endswith("asha.rao.psych/")
    assert "RCI Licensed" in probe.text


@pytest.mark.asyncio
async def test_robots_disallow_is_respected_and_nothing_else_is_requested():
    log = []
    probe = await probe_site(fetcher(site({"/": HOME}, robots="User-agent: *\nDisallow: /", log=log)), "https://raoclinic.in/")
    assert probe.status == "robots" and probe.channels == []
    assert log == ["https://raoclinic.in/robots.txt"]


@pytest.mark.asyncio
async def test_unreadable_robots_means_skip_but_missing_robots_means_allowed():
    def server_error(request):
        return httpx.Response(500)

    assert (await probe_site(fetcher(server_error), "https://a.in/")).status == "robots_unavailable"
    forbidden = lambda r: httpx.Response(403)
    assert (await probe_site(fetcher(forbidden), "https://a.in/")).status == "robots"  # robots.txt itself forbidden
    ok = await probe_site(fetcher(site({"/": HOME}, robots=None)), "https://raoclinic.in/")
    assert ok.status == "ok"


@pytest.mark.asyncio
async def test_blocked_sites_are_recorded_not_fought():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403, text="forbidden")

    probe = await probe_site(fetcher(handler), "https://apollo.example/")
    assert probe.status == "blocked" and probe.reason == "HTTP 403" and probe.channels == []

    def challenge(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<title>Just a moment...</title>", headers={"content-type": "text/html"})

    assert (await probe_site(fetcher(challenge), "https://cf.example/")).status == "blocked"


@pytest.mark.asyncio
async def test_non_html_and_oversized_responses():
    def pdf(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    assert (await probe_site(fetcher(pdf), "https://a.in/cv.pdf")).status == "http_error"

    big = "<html><body>" + ("<p>filler text</p>" * 200000) + "<a href='mailto:late@a.in'>x</a></body></html>"

    def huge(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=big, headers={"content-type": "text/html"})

    probe = await probe_site(fetcher(huge), "https://a.in/")
    assert probe.status == "ok" and len(probe.text) <= 6000  # read is capped, nothing explodes
    assert not any(c.value == "late@a.in" for c in probe.channels)  # beyond the byte cap


@pytest.mark.asyncio
async def test_non_http_urls_are_refused():
    assert (await fetcher(site({})).fetch("file:///etc/passwd")).status == "error"
    assert (await fetcher(site({})).fetch("javascript:alert(1)")).status == "error"


# ---- only public addresses (URLs come from strangers' bios) ----------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin", "http://localhost:8080/", "http://169.254.169.254/latest/meta-data/",      # loopback, cloud metadata
    "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.9/", "http://[::1]/", "http://0.0.0.0/",
    "http://intranet/", "http://printer.local/", "http://db.internal/",
])
async def test_private_and_internal_addresses_are_never_requested(url):
    log = []

    def handler(request):
        log.append(str(request.url))
        return httpx.Response(200, text="<html>secret internal page</html>", headers={"content-type": "text/html"})

    result = await fetcher(handler).fetch(url)
    assert result.status == "error" and "public" in result.reason and log == []


@pytest.mark.asyncio
async def test_a_public_looking_name_that_resolves_to_a_private_address_is_refused():
    async def rebinding(host):
        return ["93.184.216.34", "10.1.2.3"]     # one bad answer is enough

    log = []
    result = await fetcher(lambda r: log.append(1) or httpx.Response(200, text="x"), resolver=rebinding).fetch("https://innocent.example/")
    assert result.status == "error" and log == []
    async def broken(host):
        raise OSError("dns failure")

    assert (await fetcher(lambda r: httpx.Response(200, text="x"), resolver=broken).fetch("https://nxdomain.example/")).status == "error"


@pytest.mark.asyncio
async def test_a_redirect_into_the_private_network_is_stopped_before_the_request_is_made():
    log = []

    def handler(request):
        log.append(request.url.host)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "clinic.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return httpx.Response(200, text="<html>internal</html>", headers={"content-type": "text/html"})

    result = await fetcher(handler).fetch("https://clinic.example/")
    assert result.status == "error" and "127.0.0.1" not in log
