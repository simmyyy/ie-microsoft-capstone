import streamlit as st

def header(title: str, subtitle: str, right_html: str | None = None):
    c1, c2 = st.columns([0.72, 0.28], vertical_alignment="center")
    with c1:
        st.markdown(f"## {title}")
        st.markdown(f"<div class='muted'>{subtitle}</div>", unsafe_allow_html=True)
    with c2:
        if right_html:
            st.markdown(f"<div class='card card-tight'>{right_html}</div>", unsafe_allow_html=True)
    st.divider()

def kpi(label: str, value: str, hint: str | None = None):
    hint_html = f"<div class='muted' style='margin-top:4px;'>{hint}</div>" if hint else ""
    st.markdown(
        f"<div class='card'>"
        f"<div class='label'>{label}</div>"
        f"<div class='value'>{value}</div>"
        f"{hint_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

def empty_state(title: str, body: str):
    st.markdown(
        f"<div class='card'>"
        f"<div style='font-weight:750; font-size:1.05rem;'>{title}</div>"
        f"<div class='muted' style='margin-top:6px;'>{body}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

def chips(items: list[str]):
    if not items:
        st.markdown("<span class='chip'>No hexes selected</span>", unsafe_allow_html=True)
        return
    html = " ".join([f"<span class='chip'>📍 <code>{h}</code></span>" for h in items])
    st.markdown(html, unsafe_allow_html=True)