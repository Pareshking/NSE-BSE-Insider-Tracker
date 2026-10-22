"""In-app links that stay in the session (audit 22 Oct).

A plain link (a company name in a table, "Every filing ->") reloaded the whole app in its frame: a new
session, a cold load, the address bar unchanged (on streamlit.app the app runs in a frame that may not
navigate the top window), so no company had an address to keep or share. A click on a link the pages draw
to one of the site's pages is caught here and sent to Python, which switches page with st.switch_page:
the same session, the page's own address in the bar. Streamlit's menu, a link that opens a new tab and a
ctrl/cmd-click are left alone.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlsplit

import streamlit as st

JS = """
export default function (component) {
  const { setTriggerValue, data } = component;
  window.__insidersGo = setTriggerValue;
  window.__insidersPaths = new Set((data && data.paths) || []);
  if (window.__insidersNav) return;
  window.__insidersNav = true;
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest('a[href]');
    if (!a || !a.closest('[data-testid="stHtml"]') || (a.target && a.target !== '_self')) return;
    const href = a.getAttribute('href') || '';
    if (!href.startsWith('/') || href.startsWith('//')) return;
    const path = href.split(/[?#]/)[0].replace(/^\\/+|\\/+$/g, '');
    if (!window.__insidersPaths.has(path)) return;
    e.preventDefault();
    window.__insidersGo('go', href.split('#')[0] + '#' + Date.now());   // the fragment is the click's own id
  }, true);
}
"""

_nav = st.components.v2.component('insiders_nav', js=JS, isolate_styles=False)


def target(href: str, pages: dict) -> tuple | None:
    """(page, query params) for an in-app link, or None when it is not one of the site's pages."""
    if not isinstance(href, str) or not href.startswith('/'):
        return None
    parts = urlsplit(href)
    page = pages.get(parts.path.strip('/'))
    return (page, dict(parse_qsl(parts.query))) if page is not None else None


def links(pages: dict) -> None:
    """Mount once per run, before the page runs. `pages` maps a url path ('' for the default page) to its
    st.Page. A click arrives as a trigger; st.switch_page interrupts the run before Streamlit clears it, so
    it can come back once more: each click carries its own id and is acted on once."""
    if os.environ.get('INSIDERS_NO_INAPP_LINKS'):   # streamlit.testing has no browser to mount it in (it waits)
        return
    with st.container(key='navhook'):
        res = _nav(key='insiders_nav', data={'paths': sorted(pages)}, on_go_change=lambda: None)
    got = getattr(res, 'go', None)
    if not isinstance(got, str) or got == st.session_state.get('_nav_done'):
        return
    st.session_state['_nav_done'] = got
    hit = target(got, pages)
    if hit:
        # The query is set on the new page's own run (apply_query), not passed to switch_page: the frame's URL
        # then changes from none to ?symbol=..., which is what streamlit.app copies into the address bar.
        st.session_state['_nav_query'] = hit[1]
        st.switch_page(hit[0])


def apply_query() -> None:
    """At the top of every run: the query of the link that led here (see links())."""
    q = st.session_state.pop('_nav_query', None)
    if q:
        st.query_params.from_dict(q)
