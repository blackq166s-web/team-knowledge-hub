"""Shared light/dark styling, including native Streamlit theme variables."""
import streamlit as st


def apply_theme(dark):
    bg, panel, text, muted, border = (
        ("#10151f", "#192231", "#e8eef8", "#a6b4c8", "#334155") if dark else
        ("#f5f7fb", "#ffffff", "#17243b", "#5e6d82", "#dce3ed"))
    st.html(f"""<style>
    :root, .stApp, [data-testid="stSidebar"] {{
      --background-color:{bg}; --secondary-background-color:{panel};
      --text-color:{text}; --border-color:{border};
      color-scheme:{'dark' if dark else 'light'};
    }}
    .stApp, [data-testid="stHeader"] {{background:{bg}; color:{text};}}
    [data-testid="stSidebar"] {{background:{panel}; border-right:1px solid {border};}}
    [data-testid="stSidebar"] [role="radiogroup"] {{gap:12px;}}
    [data-testid="stSidebar"] [role="radiogroup"] > div {{width:100%;}}
    [data-testid="stSidebar"] label:has(input:checked) {{background:{'#223754' if dark else '#eaf1ff'}; border-color:#2563eb;}}
    [data-testid="stSidebar"] [role="radiogroup"] label {{padding:12px; border-radius:10px; border:1px solid {border}; width:100%; min-width:220px; box-sizing:border-box;}}
    h1,h2,h3,h4,p,label, [data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] {{color:{text};}}
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{color:{muted}!important;opacity:1!important;}}
    [data-testid="stFileUploaderDropzone"] small {{color:{muted}!important;}}
    input::placeholder,textarea::placeholder {{color:{muted}!important;opacity:1;}}
    [data-testid="stMainBlockContainer"] {{max-width:1450px; padding-top:4.5rem;}}
    [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] > div {{border-color:{border};}}
    input,textarea,[data-baseweb="input"],[data-baseweb="textarea"],
    [data-baseweb="select"] > div, [data-baseweb="popover"], [role="listbox"], [role="option"],
    [data-testid="stExpander"] details, [data-testid="stExpander"] summary,
    [data-testid="stFileUploaderDropzone"], [data-testid="stCode"], pre {{background:{panel}!important; color:{text}!important;}}
    button[kind="secondary"],button[kind="secondaryFormSubmit"],button[kind="tertiary"] {{background:{panel};color:{text};border-color:{border};}}
    button[kind="primary"],button[kind="primaryFormSubmit"] {{background:#2563eb;color:white;border-color:#2563eb;}}
    button[kind="primary"] p,button[kind="primaryFormSubmit"] p {{color:white;}}
    [data-testid="stTable"] {{background:{panel};color:{text};}}
    [data-testid="stDataFrame"] {{filter:{'invert(.9) hue-rotate(180deg)' if dark else 'none'};}}
    hr {{border-color:{border};}}
    .st-key-final_answer {{background:{panel}; border:1px solid #2563eb; border-left:5px solid #2563eb; border-radius:14px; padding:20px;}}
    .answer-claim {{font-size:1.15rem;line-height:1.9;white-space:pre-wrap;}}
    .answer-citations {{color:{'#93baff' if dark else '#1d4ed8'};font-weight:600;}}
    </style>""")
