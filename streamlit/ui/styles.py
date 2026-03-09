import streamlit as st

def inject_css():
    st.markdown(
        """
        <style>
        /* Global container width + breathing room */
        .block-container { max-width: 1300px; padding-top: 1.2rem; padding-bottom: 2.5rem; }

        /* Sidebar padding */
        section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }

        /* Cards */
        .card {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 14px 16px;
            background: rgba(255,255,255,0.03);
            box-shadow: 0 10px 28px rgba(0,0,0,0.35);
        }
        .card-tight { padding: 10px 12px; border-radius: 16px; }
        .muted { color: rgba(230,234,242,0.72); font-size: 0.92rem; }
        .label { color: rgba(230,234,242,0.72); font-size: 0.80rem; letter-spacing: 0.02em; text-transform: uppercase; }
        .value { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.02em; }
        .chip {
            display:inline-flex; align-items:center; gap:8px;
            padding: 6px 10px; border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.10);
            background: rgba(255,255,255,0.03);
            font-size: 0.92rem;
        }

        /* Tabs spacing (más “producto”) */
        button[data-baseweb="tab"] { padding-top: 10px; padding-bottom: 10px; }
        </style>
        """,
        unsafe_allow_html=True,
    )