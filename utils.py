import re

import requests
import streamlit as st
import tiktoken

BING_SEARCH_API_KEY = st.secrets.bing_api_key


def do_custom_search(query: str) -> dict:
    headers = {"Ocp-Apim-Subscription-Key": BING_SEARCH_API_KEY}
    params = {
        "q": query,
        "customConfig": "36e6b2e7-6b94-48f5-8281-b991cfbd1469",
        "count": 5,
    }
    response = requests.get(
        "https://api.bing.microsoft.com/v7.0/custom/search",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    search_results = response.json()

    urls = []
    source_items = {}
    for index, sr in enumerate(search_results["webPages"]["value"]):
        url = sr["url"]
        snippet = sr["snippet"]
        if url not in urls:
            urls.append(url)
            id = "cit{}".format(index)
            source_items[id] = SourceItem("cit{}".format(index), url, snippet)

    return source_items


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


def extract_citations(text):
    # Find all occurrences of strings within square brackets
    matches = re.findall(r"\[(.*?)\]", text)  # noqa
    # Split each match by comma and strip whitespace
    citations = [citation.strip() for match in matches for citation in match.split(",")]
    return citations
