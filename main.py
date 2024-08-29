from bs4 import BeautifulSoup
from cacheout import lru_memoize
from conva_ai import ConvaAI
from fake_useragent import UserAgent
from playwright.async_api import async_playwright
import asyncio
import os
import re
import requests
import streamlit as st
import tiktoken

st.set_page_config(page_title="Perplexipedia - by Conva.AI")

# Hack to get playwright to work properly
os.system("playwright install")

BING_SEARCH_API_KEY = st.secrets.bing_api_key

hide_default_format = """
       <style>
       #MainMenu {visibility: hidden; }
       footer {visibility: hidden;}
       </style>
       """
st.markdown(hide_default_format, unsafe_allow_html=True)


class SourceItem:
    def __init__(self, id, url, snippet, content=None, index=-1):
        self.id = id
        self.url = url
        self.snippet = snippet
        self.content = content
        self.index = index


def num_tokens_from_string(string: str, model_name: str) -> int:
    encoding = tiktoken.encoding_for_model(model_name)
    num_tokens = len(encoding.encode(string))
    print("num tokens = {}".format(num_tokens))
    return num_tokens


def escape_braces(text: str) -> str:
    text = re.sub(r"(?<!\{)\{(?!\{)", r"{{", text)  # noqa
    text = re.sub(r"(?<!\})\}(?!\})", r"}}", text)  # noqa
    return text


def maybe_trim_context(context: str) -> str:
    length = len(context)
    tokens = num_tokens_from_string(context, "gpt-4o-mini")
    start = 0
    finish = length
    while tokens > 120 * 1000:
        finish = int(finish - 0.1 * finish)
        context = context[start:finish]
        tokens = num_tokens_from_string(context, "gpt-4o-mini")
    return context


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


def get_md_normal_text(text):
    return "<p> {} </p>".format(text)


def get_md_hyperlink(text):
    return "<a href={}>{}</a>".format(text, text)


def get_md_list(arr):
    lis = ""
    for elem in arr:
        if "$" in elem:
            elem = elem.replace("$", "\\$")
        lis += "<li> {} </li>".format(elem)
    return "<list> {} </list>".format(lis)


if "ready" not in st.session_state:
    st.session_state.ready = False

if "success" not in st.session_state:
    st.session_state.success = False

if "reset" not in st.session_state:
    st.session_state.reset = True

if "sources" not in st.session_state:
    st.session_state.sources = {}

col1, col2 = st.columns([10, 2])
col1.title("Perplexipedia")
col1.caption("Perplexity, but for wikipedia")
col2.title("")
col2.image("conva.ai.svg", width=100)

with st.container(border=True):
    st.text_area("Type your question below", key="query")
    col1, col2, col3 = st.columns([2, 2, 4])
    st.session_state.ready = col1.button("Get the answer")
    st.session_state.reset = col2.button("Reset")
    pbph = col3.empty()

rph = st.empty()
response = None

if st.session_state.reset:
    pbph.empty()
    rph.empty()
    st.session_state.ready = False
    st.session_state.success = False

if st.session_state.ready and st.session_state.query:
    progress = 5
    pb = pbph.progress(progress, "Searching for relevant information...")

    urls = []
    source_items = {}

    headers = {"Ocp-Apim-Subscription-Key": BING_SEARCH_API_KEY}
    params = {
        "q": st.session_state.query,
        "customConfig": "7469e414-57a0-4289-898c-bf9f1fbfd380",
        "count": 5,
    }
    response = requests.get(
        "https://api.bing.microsoft.com/v7.0/custom/search",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    search_results = response.json()

    for index, sr in enumerate(search_results["webPages"]["value"]):
        url = sr["url"]
        snippet = sr["snippet"]
        if url not in urls:
            urls.append(url)
            id = "cit{}".format(index)
            source_items[id] = SourceItem("cit{}".format(index), url, snippet)

    if len(source_items) > 5:
        source_items = {k: v for k, v in source_items.items() if int(v.id.split("cit")[1]) >= 5}

    st.session_state.sources = source_items

    progress += 5
    pb.progress(progress, "Processing search results...")

    asyncio.run(scrape_multiple())
    pb.progress(progress, "Reading results...")

    context = ""
    for id, item in st.session_state.sources.items():
        context += "Result ID: {} URL: {}\nContents: {}\n\n".format(
            id,
            item.url,
            item.content,
        )

    client = ConvaAI(
        assistant_id=st.secrets.conva_assistant_id,
        api_key=st.secrets.conva_api_key,
        assistant_version="7.0.0",
    )

    progress += 5
    pb.progress(progress, "Generating answer...")
    capability_context = {"question_answering_with_citations": maybe_trim_context(escape_braces(context).strip())}

    response = client.invoke_capability_name(
        query="Answer the user's query based on the provided context. User's query: ({})".format(
            st.session_state.query,
        ),
        capability_name="question_answering_with_citations",
        timeout=600,
        stream=False,
        capability_context=capability_context,
    )

    pb.progress(100, "Completed")
    st.session_state.success = True


def extract_citations(text):
    # Find all occurrences of strings within square brackets
    matches = re.findall(r"\[(.*?)\]", text)  # noqa
    # Split each match by comma and strip whitespace
    citations = [citation.strip() for match in matches for citation in match.split(",")]
    return citations


def postprocess_response(response):
    sources = st.session_state.sources
    citations = extract_citations(response)

    final_sources = {k: v for k, v in sources.items() if k in citations}
    for index, fs in enumerate(final_sources.items()):
        fs[1].index = index

    for _, fs in final_sources.items():
        response = response.replace(fs.id, str(fs.index + 1))

    return final_sources, response


if st.session_state.success:
    with rph.container(border=True):
        sources, answer = postprocess_response(response.parameters.get("answer_with_citations", "Unavailable"))

        st.subheader("Answer")
        st.markdown(get_md_normal_text(answer), unsafe_allow_html=True)

        st.subheader("Sources")
        for _, s in sources.items():
            link = get_md_hyperlink(s.url)
            t = "{}. {} {}...".format(s.index + 1, link, s.snippet[:100])
            st.markdown(get_md_normal_text(t), unsafe_allow_html=True)

        st.divider()

        st.subheader("Related")
        for r in response.related_queries:
            st.button(r)
