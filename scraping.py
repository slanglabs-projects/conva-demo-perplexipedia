from bs4 import BeautifulSoup
from cacheout import lru_memoize
from fake_useragent import UserAgent
from playwright.async_api import async_playwright

import asyncio
import streamlit as st


@lru_memoize()
async def scrape(url: str, id: str, sources: dict):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            user_agent = UserAgent().chrome
            context = await browser.new_context(
                user_agent=user_agent,
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_selector("body")

            previous_height = await page.evaluate("document.body.scrollHeight")
            while True:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                await page.wait_for_timeout(1000)  # Wait to load the page

                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    break
                previous_height = new_height
            content = await page.content()
            await context.close()

            soup = BeautifulSoup(content, "html.parser")
            for data in soup(["header", "footer", "nav", "script", "style"]):
                data.decompose()
            content = soup.get_text(strip=True)
            sources[id].content = content
    except (Exception,):
        sources[id].content = ""


async def scrape_multiple():
    sources = st.session_state.sources
    tasks = [scrape(si.url, si.id, sources) for _, si in sources.items()]
    await asyncio.gather(*tasks)
    st.session_state.sources = sources
