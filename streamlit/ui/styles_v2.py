import streamlit as st

def inject_css():
    st.markdown(
        """
        <style>
        .block-container { max-width: 1300px; padding-top: 2.5rem; padding-bottom: 2.5rem; }
        section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }

        .card {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 14px 16px;
            background: rgba(255,255,255,0.03);
            box-shadow: 0 10px 28px rgba(0,0,0,0.35);
        }
        .muted { color: rgba(230,234,242,0.72); font-size: 0.92rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )