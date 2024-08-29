from conva_ai import ConvaAI
from scraping import scrape_multiple
from utils import (
    do_custom_search,
    escape_braces,
    maybe_trim_context,
    get_md_normal_text,
    get_md_hyperlink,
    extract_citations,
)

import asyncio
import os
import streamlit as st

st.set_page_config(page_title="Perplexipedia - by Conva.AI")


# Hack to get playwright to work properly
os.system("playwright install")

if "status" not in st.session_state:
    st.session_state.status = "uninitialized"

if "sources" not in st.session_state:
    st.session_state.sources = {}

if "query_value" not in st.session_state:
    st.session_state.query_value = ""

if "response" not in st.session_state:
    st.session_state.response = None

if "answer" not in st.session_state:
    st.session_state.answer = ""


def execute_action(key):
    st.session_state.status = "processing"
    st.session_state.query_value = st.session_state[key]
    response = get_answer(st.session_state[key])
    handle_response(response)


def execute_action_btn(value):
    st.session_state.status = "processing"
    st.session_state.query_value = value
    response = get_answer(value)
    handle_response(response)


def reset():
    st.session_state.status = "uninitialized"
    st.session_state.query_value = ""


col1, col2 = st.columns([10, 2])
col1.title("Perplexipedia")
col1.caption("Perplexity, but for wikipedia")
col2.title("")
col2.image("conva.ai.svg", width=100)


with st.container(border=True):
    st.text_area("Type your question below", value=st.session_state.query_value, key="query")
    col1, col2, col3 = st.columns([2, 2, 4])
    col1.button("Get the answer", on_click=execute_action, args=["query"])
    col2.button("Reset", on_click=reset)

    pbph = col3.empty()
    rph = st.empty()

if st.session_state.status == "uninitialized":
    pbph.empty()
    rph.empty()


def get_answer(query):
    progress = 5
    pb = pbph.progress(progress, "Searching for relevant information...")

    source_items = do_custom_search(query)

    if len(source_items) > 7:
        source_items = {k: v for k, v in source_items.items() if int(v.id.split("cit")[1]) >= 7}

    st.session_state.sources = source_items

    progress += 50
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

    progress += 25
    pb.progress(progress, "Generating answer...")
    capability_context = {"question_answering_with_citations": maybe_trim_context(escape_braces(context).strip())}

    response = client.invoke_capability_name(
        query="Answer the user's query based on the provided context. User's query: ({})".format(query),
        capability_name="question_answering_with_citations",
        timeout=600,
        stream=False,
        capability_context=capability_context,
    )

    pb.progress(100, "Completed")
    st.session_state.status = "success"
    return response


def postprocess_response(response):
    sources = st.session_state.sources
    citations = extract_citations(response)

    final_sources = {k: v for k, v in sources.items() if k in citations}
    for index, fs in enumerate(final_sources.items()):
        fs[1].index = index

    for _, fs in final_sources.items():
        response = response.replace(fs.id, str(fs.index + 1))

    return final_sources, response


def handle_response(response):
    sources, answer = postprocess_response(response.parameters.get("answer_with_citations", "Unavailable"))
    st.session_state.response = response
    st.session_state.sources = sources
    st.session_state.answer = answer


if st.session_state.status == "success":
    sources = st.session_state.sources
    answer = st.session_state.answer
    response = st.session_state.response

    with rph.container(border=True):
        st.subheader("Answer")
        st.markdown(get_md_normal_text(answer), unsafe_allow_html=True)

        st.subheader("Sources")
        for _, s in sources.items():
            link = get_md_hyperlink(s.url)
            t = "{}. {} {}...".format(s.index + 1, link, s.snippet[:100])
            st.markdown(get_md_normal_text(t), unsafe_allow_html=True)

        st.divider()

        st.subheader("Related")
        for r in response.related_queries:  # noqa
            st.button(r, key=r, on_click=execute_action_btn, args=[r])
