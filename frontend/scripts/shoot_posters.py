import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(r"D:/project/hospital_medical_insurance_agent/frontend")
OUT = ROOT / "public/assets/images/posters/pages"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://localhost:5174"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        # 视口放大使 ppt-controller 的 updateViewportScale = 1.0（slide 1440x810 不被缩放）
        page = await browser.new_page(viewport={"width":1500,"height":880}, device_scale_factor=2)
        for n in range(1, 12):
            await page.goto(f"{BASE}/?page={n}", wait_until="networkidle")
            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass
            # 隐藏底部进度条，确保海报干净
            await page.add_style_tag(content=".progress-bar{display:none!important}")
            await page.wait_for_timeout(500)
            # slide 经缩放=1、flex 居中后位于 (30,35) 起（(1500-1440)/2=30, (880-810)/2=35）
            await page.screenshot(
                path=str(OUT / f"page-{n}.png"),
                clip={"x":30,"y":35,"width":1440,"height":810},
            )
            print(f"✅ page-{n}.png")
        await browser.close()
    print("ALL DONE")

asyncio.run(main())
