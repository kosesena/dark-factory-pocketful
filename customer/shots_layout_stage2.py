import sys, os
B = sys.argv[1]; OUTD = sys.argv[2]; os.makedirs(OUTD, exist_ok=True)
sys.argv = [sys.argv[0], B]
src = open("/Users/kosesena/Desktop/dark-factory/band-work/result/customer/journey_stage2_ui.py").read().split("with sync_playwright()")[0]
exec(src); OUT = OUTD
def states():
    yield "seeded", fixture()
    f = fixture(); f["payments"] = []; f["requests"] = []; f["authorizations"] = []; yield "empty", f
with sync_playwright() as p:
    br = p.chromium.launch()
    for nm, f in states():
        api("POST", "/_test/reset", f)
        for W in (1280, 900, 375):
            ctx = br.new_context(viewport={"width": W, "height": 900}); page = ctx.new_page(); login(page, "ada@example.com")
            for route in ("/", "/requests", "/split", "/authorizations"):
                page.goto(B + route); page.wait_for_timeout(500)
                if route == "/split": page.get_by_test_id("split-amount").fill("10"); page.get_by_test_id("split-handles").fill("ada,bob,cy"); page.wait_for_timeout(400)
                tag = route.strip("/") or "home"
                shot(page, f"{nm}-{W}-{tag}")
                chk(f"{nm} {W} {tag} no h-scroll", overflow(page) <= 0, overflow(page))
                # measure column void: lowest bottom of cards in left vs right halves
                v = page.evaluate("""()=>{const H=document.documentElement.scrollHeight;const cards=[...document.querySelectorAll('main *')].filter(e=>{const s=getComputedStyle(e);return s.boxShadow!=='none'&&e.getBoundingClientRect().width>200});const w=innerWidth/2;let L=0,R=0;cards.forEach(e=>{const r=e.getBoundingClientRect();const b=r.bottom+scrollY;if(r.left+r.width/2<w){L=Math.max(L,b)}else{R=Math.max(R,b)}});return [H,L,R]}""")
                print("   cols", nm, W, tag, "pageH/leftBottom/rightBottom", [round(x) for x in v])
            ctx.close()
    br.close()
print("done", n, fails)
