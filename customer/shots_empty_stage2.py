import sys, os, json, urllib.request
sys.argv = [sys.argv[0], sys.argv[1]]
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "journey_stage2_ui.py")).read().split("with sync_playwright()")[0]
exec(src)
f = fixture(); f["payments"] = []; f["requests"] = []; f["authorizations"] = []; api("POST", "/_test/reset", f)
with sync_playwright() as p:
    br = p.chromium.launch()
    for W, H, tag in ((1280, 900, "d"), (375, 800, "m")):
        ctx = br.new_context(viewport={"width": W, "height": H}); page = ctx.new_page(); login(page, "ada@example.com"); page.wait_for_timeout(500)
        chk(f"{tag} real empty-activity", cnt(page, "empty-activity") == 1); shot(page, f"{tag}-home-truly-empty")
        page.goto(B + "/requests"); page.wait_for_timeout(400); chk(f"{tag} empty-requests", cnt(page, "empty-requests") == 1)
        page.goto(B + "/authorizations"); page.wait_for_timeout(400); chk(f"{tag} empty-auth", cnt(page, "empty-authorizations") == 1); shot(page, f"{tag}-authorizations-truly-empty")
        ctx.close()
    br.close()
