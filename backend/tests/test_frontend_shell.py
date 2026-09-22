"""The shell every screen is drawn into.

One stray closing tag in app.html made the browser shut the views container
early, so twenty-three screens fell outside it and each opened with the empty
container's padding as a void above its title. Every ERP screen looked
unfinished for weeks and no test noticed, because no test reads the HTML.
These do.
"""
import os
import re

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
        return f.read()


def test_every_div_that_opens_is_closed():
    h = read("app.html")
    opens = len(re.findall(r"<div\b[^>]*>", h))
    closes = len(re.findall(r"</div>", h))
    assert opens == closes, "app.html opens %d divs and closes %d" % (opens, closes)


def test_every_screen_sits_inside_the_views_container():
    """Static check of what the browser would do: walk the tags and make
    sure the container is still open when each view-section begins."""
    h = read("app.html")
    # Start on the container's own opening tag, not inside it.
    start = h.rfind("<div", 0, h.index('class="views-container"'))
    depth, i = 0, start
    tag = re.compile(r"<(/?)div\b[^>]*>")
    views_seen, views_inside = 0, 0
    end = h.index("</main>", start)
    # Keep walking to the end of <main> rather than stopping when the depth
    # first reaches zero - that point IS the bug when a stray close is
    # present, and stopping there would hide every screen that fell after it.
    for m in tag.finditer(h, start, end):
        if m.group(1):
            depth -= 1
        else:
            depth += 1
        seg = h[m.start():m.end()]
        if 'class="view-section' in seg:
            views_seen += 1
            # The container is depth 1; a view opening at depth >= 2 is inside
            # it. One opening at depth <= 1 has fallen out.
            if depth >= 2:
                views_inside += 1
    assert views_seen > 30, "expected the app's screens, found %d" % views_seen
    assert views_inside == views_seen, (
        "%d of %d screens sit outside .views-container" % (views_seen - views_inside, views_seen))


def test_every_nav_entry_opens_a_screen_that_exists():
    h = read("app.html")
    j = read("app.js")
    entries = re.findall(r'id="(nav-[a-z-]+)"[^>]*showView\(\'([a-z-]+)\'\)', h)
    assert entries, "no nav entries found"
    missing_view = [v for _, v in entries if 'id="%s"' % v not in h]
    missing_map = [(n, v) for n, v in entries if "'%s': '%s'" % (v, n) not in j]
    assert not missing_view, "nav points at screens that do not exist: %s" % missing_view
    assert not missing_map, "nav entries with no highlight mapping: %s" % missing_map


def test_every_script_the_shell_loads_is_present():
    h = read("app.html")
    for src in re.findall(r'<script src="([a-z-]+\.js)\?v=\d+"', h):
        assert os.path.exists(os.path.join(FRONTEND, src)), "%s is loaded but missing" % src


def test_the_front_door_is_the_sign_in():
    """A single company's ERP has no marketing page."""
    h = re.sub(r"<!--.*?-->", "", read("index.html"), flags=re.S)   # comments may quote the past
    assert "login.html" in h
    for leftover in ("Pricing", "Testimonials", "Invoicing Made"):
        assert leftover not in h, "the old landing page is back: %s" % leftover
    assert "Super Admin" not in read("login.html")


def test_no_button_sends_anybody_to_excel():
    """The app exists to replace the spreadsheets. A button that says Excel
    is the whole workflow's tell: it says the real work happens there.
    Downloads are outputs, like the print button, and are labelled as such."""
    for name in os.listdir(FRONTEND):
        if not name.endswith((".html", ".js")) or name in ("index.html", "login.html"):
            continue
        text = read(name)
        for label in re.findall(r">([^<>]{0,40}Excel[^<>]{0,40})<", text):
            assert False, "%s labels a control with Excel: %r" % (name, label)
        assert "(Excel)" not in text, name


def test_the_measurement_modal_is_a_dimension_sheet():
    """No x L x B x D, on the screen, not in a sheet beside it."""
    h = read("app.html")
    assert 'id="measure-dims"' in h and 'id="sub-measure-dims"' in h
    assert "mbdims.js" in h
    assert 'MB page reference' not in h, "the page reference implies the book lives elsewhere"


def test_the_suites_the_app_was_started_from_stay_hidden():
    """Quotes, recurring invoices, recruitment, goals, an assistant orb and a
    vendor badge: the invoicing and HR product this began as. A civil
    contractor's ERP shows none of it, whatever a stray link calls."""
    h = read("app.html")
    for view in ("quotes-view", "recurring-view", "recruitment-view", "goals-view",
                 "orgchart-view", "onboarding-hub-view", "sales-pipeline-view",
                 "reports-view", "viewer-view"):
        assert ('id="%s" data-legacy="1"' % view) in h, view + " is not marked legacy"
    css = read("styles.css")
    assert ".view-section[data-legacy]" in css and "display: none !important" in css
    assert 'class="ai-core"' not in h
    assert "Powered by Aniprotech" not in h
    assert 'id="nav-viewer"' not in h
    assert 'id="dash-erp"' in h


def test_the_front_door_says_what_this_is():
    h = read("login.html")
    assert "Civil contracting ERP" in h
    assert "Measurement book" in h and "RA bills" in h
    assert "/api/public/brand" in h
