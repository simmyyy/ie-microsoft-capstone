# Landing Page

import textwrap
import base64
from pathlib import Path
import streamlit as st

def render_landing():
    # --- Logo as base64 (OK because it's small) ---
    logo_path = Path(__file__).parent / "assets" / "logo_white.png"
    logo_b64 = ""
    if logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")

    logos_strip_path = Path(__file__).parent / "assets" / "logos-strip.png"
    logos_strip_b64 = ""
    if logos_strip_path.exists():
        logos_strip_b64 = base64.b64encode(logos_strip_path.read_bytes()).decode("utf-8")

    about_bg_path = Path(__file__).parent / "assets" / "about-bg.jpg"
    about_bg_b64 = ""
    if about_bg_path.exists():
        about_bg_b64 = base64.b64encode(about_bg_path.read_bytes()).decode("utf-8")

    # --- Video URL (Cloudinary or local static) ---
    # Option A (Cloudinary):
    hero_video_url = "https://res.cloudinary.com/dnsgamlxf/video/upload/v1773021155/hero_video_3_ypf1uf.mp4"
    # Option B (local): put at streamlit/static/hero_video.mp4 and use:
    # hero_video_url = "/static/hero_video.mp4"

    html = textwrap.dedent(f"""
    <style>
    :root{{
      --bg0: #06121a;
      --card: rgba(255,255,255,0.06);
      --stroke: rgba(255,255,255,0.12);
      --text: rgba(255,255,255,0.92);
      --muted: rgba(255,255,255,0.72);
      --accent1: rgba(223, 135, 79, 0.7);
      --accent2: rgba(159, 196, 53, 0.6);
      --radius: 18px;
    }}

    header[data-testid="stHeader"] {{ display: none; }}
    .block-container {{ padding-top: 0rem; padding-bottom: 0rem; max-width: 100%; }}

    /* Navbar */
    .topnav {{
        position: fixed;
        top: 0; left: 0; right: 0;
        z-index: 10000;
        padding: 20px 22px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: rgba(8, 12, 20, 0.55);
        backdrop-filter: blur(10px);
        border-bottom: 1px solid rgba(255,255,255,0.10);
    }}

    .navlinks a {{
        color: var(--muted);
        text-decoration: none;
        font-size: 16px;
        padding: 4px 4px;
        border-radius: 10px;
    }}
    .navlinks a:hover {{
        background: rgba(255,255,255,0.06);
        color: var(--text);
    }}

    .brand {{
        display:flex; align-items:center; gap: 10px;
        color: var(--text); font-weight: 800; letter-spacing: -0.02em;
        font-size: 17px;
    }}

    .brand-logo {{
        height: 80px;
        width: auto;
        display:block;
        padding-left: 20px;
        padding-right: 15px;
    }}

    .navlinks {{ display:flex; gap: 18px; color: var(--muted); font-size: 18px; font-weight: 700; }}
    .navlinks span {{ cursor: default; }}

    .nav-actions {{ display:flex; gap: 10px; align-items:center; }}
    .btn {{
        padding: 9px 14px; border-radius: 999px;
        border: 1px solid var(--stroke);
        background: var(--card);
        color: var(--text);
        font-weight: 650;
        font-size: 18px;
    }}
    .btn-primary {{
        border: none;
        background: linear-gradient(90deg, var(--accent1), var(--accent2));
    }}

    /* Hero with video background */
    .hero {{
        padding-top: 10vh;
        height: 95vh;
        position: relative;
        display:flex;
        align-items:center;
        justify-content:center;
        overflow: hidden;
        background: radial-gradient(circle at 20% 20%, rgba(238, 140, 85, 0.22), rgba(11,18,32,1));
    }}

    .hero-video {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      z-index: 0;
    }}

    .hero-overlay {{
      position: absolute;
      inset: 0;
      background: rgba(0,0,0,0.35);
      z-index: 1;
    }}

    .inner {{
      position: relative;
      z-index: 2;
      max-width: 980px;
      text-align:center;
      padding: 0 7vw;
      margin-top: 40px;
    }}

    .pill {{
        display:inline-flex; gap:10px; align-items:center;
        padding: 8px 14px;
        border-radius: 999px;
        border: 1px solid var(--stroke);
        background: var(--card);
        color: var(--text);
        font-size: 13px;
    }}

    .title {{
        margin: 18px 0 0 0;
        font-size: clamp(44px, 5.2vw, 76px);
        line-height: 1.02;
        font-weight: 850;
        letter-spacing: -0.04em;
        color: var(--text);
    }}

    .sub {{
        margin-top: 16px;
        font-size: 18px;
        line-height: 1.5;
        color: var(--muted);
        max-width: 820px;
        margin-left:auto; margin-right:auto;
    }}

    /* ---- Landing CTA: position Streamlit button block ---- */
    div[data-testid="stHorizontalBlock"] {{
      position: absolute;
      top: calc(50vh + 185px);
      left: 50%;
      transform: translateX(-50%);
      width: min(420px, 84vw);
      z-index: 3;
      background: transparent;
    }}

    /* --- Services section--- */
    .services-hero {{
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 40px;
      align-items: center;
      padding: 46px 46px;
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.10);
      background:
        radial-gradient(1200px 700px at 10% 10%, rgba(223,135,79,0.16), rgba(50,50,50,0.15) 55%),
        radial-gradient(900px 600px at 90% 0%, rgba(159,196,53,0.14), rgba(0,0,0,0) 60%),
        rgba(255,255,255,0.02);
      box-shadow: 0 18px 60px rgba(0,0,0,0.40);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
    }}

    .services-title {{
      font-size: clamp(34px, 4.0vw, 56px);
      line-height: 1.08;
      letter-spacing: -0.03em;
      font-weight: 900;
      color: var(--text);
      margin: 0;
      max-width: 680px;
    }}

    .services-copy {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.6;
      max-width: 720px;
    }}

    /* --- Data section--- */                   
    .data-card-single {{
      padding: 64px 42px 54px 42px;
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.08);
      background: linear-gradient(
        180deg,
        #d8c3d4 0%,
        #e8e7ec 22%,
        #f3f3f3 55%,
        #f7f7f7 100%
      );
      box-shadow: 0 18px 50px rgba(0,0,0,0.14);
      text-align: center;
      overflow: hidden;
    }}

    .data-card-inner {{
      max-width: 940px;
      margin: 0 auto;
      text-align: center;
    }}

    .data-eyebrow {{
      margin: 0 0 14px 0 !important;
      font-size: 14px !important;
      font-weight: 700 !important;
      letter-spacing: 0.16em !important;
      text-transform: uppercase !important;
      color: rgba(35,35,35,0.55) !important;
      text-align: center !important;
    }}

    .data-main-title {{
      margin: 0 auto !important;
      max-width: 780px !important;
      font-size: clamp(34px, 4.5vw, 58px) !important;
      line-height: 1.05 !important;
      letter-spacing: -0.04em !important;
      font-weight: 900 !important;
      color: #2f2c33 !important;
      text-align: center !important;
    }}

    .data-main-copy {{
      margin: 22px auto 0 auto !important;
      max-width: 760px !important;
      font-size: 18px !important;
      line-height: 1.7 !important;
      color: rgba(40,40,40,0.74) !important;
      text-align: center !important;
    }}

    .data-logos-block {{
      margin-top: 42px;
      display: flex;
      justify-content: center;
      align-items: center;
    }}

    .data-logos-strip {{
      width: min(980px, 100%);
      height: auto;
      display: block;
      object-fit: contain;
      opacity: 0.95;
    }}

    @media (max-width: 768px) {{
      .data-card-single {{
        padding: 42px 22px 38px 22px;
      }}

      .data-main-copy {{
        font-size: 16px;
      }}

      .data-logos-block {{
        margin-top: 30px;
      }}
    }}
                           
        /* --- About section --- */
    .about-card {{
      position: relative;
      min-height: 560px;
      border-radius: 28px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.10);
      background-image:
        linear-gradient(90deg, rgba(7,12,20,0.68) 0%, rgba(7,12,20,0.46) 38%, rgba(7,12,20,0.22) 100%),
        url("data:image/jpeg;base64,{about_bg_b64}");
      background-size: cover;
      background-position: center center;
      background-repeat: no-repeat;
      box-shadow: 0 18px 60px rgba(0,0,0,0.40);
      display: flex;
      align-items: center;
    }}

    .about-card-inner {{
      width: 100%;
      max-width: 1150px;
      padding: 64px 56px;
    }}

    .about-title {{
      margin: 0;
      color: rgba(255,255,255,0.96);
      font-size: clamp(34px, 4.5vw, 58px);
      line-height: 0.95;
      font-weight: 800;
      letter-spacing: -0.04em;
      max-width: 520px;
    }}

    .about-copy {{
      margin-top: 34px;
      max-width: 1080px;
      color: rgba(255,255,255,0.92);
      font-size: clamp(24px, 2.2vw, 30px);
      line-height: 1.42;
      font-weight: 500;
    }}

    @media (max-width: 980px) {{
      .about-card {{
        min-height: 460px;
        background-position: center center;
      }}

      .about-card-inner {{
        padding: 42px 28px;
      }}

      .about-title {{
        font-size: clamp(44px, 10vw, 72px);
        max-width: 320px;
      }}

      .about-copy {{
        margin-top: 24px;
        font-size: 20px;
        line-height: 1.5;
      }}
    }}
    /* ----------- */

    /* ============= ADDED ============= */
    .services-hero.split-layout {{
      grid-template-columns: 0.95fr 1.05fr;
      gap: 28px;
      align-items: stretch;
    }}

    .services-left {{
      display: flex;
      flex-direction: column;
      justify-content: center;
      min-width: 0;
    }}

    .services-right {{
      display: flex;
      flex-direction: column;
      gap: 16px;
      min-width: 0;
    }}

    .tier-card {{
      display: grid;
      grid-template-columns: 150px 1fr;
      overflow: hidden;
      border-radius: 24px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(255,255,255,0.04);
      min-height: 132px;
    }}

    .tier-label {{
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 18px;
      font-size: 18px;
      font-weight: 850;
      line-height: 1.2;
      color: white;
      background: linear-gradient(180deg, rgba(223,135,79,0.95), rgba(159,196,53,0.92));
    }}

    .tier-body {{
      display: flex;
      align-items: center;
      padding: 22px 28px;

      background: linear-gradient(
        180deg,
        rgba(223,135,79,0.5),
        rgba(159,196,53,0.5)
      );

      font-size: 15px;
      line-height: 1.65;
      font-weight: 500;
      color: white;
      text-align: left;
    }}

    .tier-body ul {{
      margin: 0;
      padding-left: 18px;
    }}

    .tier-body li {{
      margin-bottom: 6px;
    }}
                           
    .tier-body.professional {{
      background: linear-gradient(
        180deg,
        rgba(223,135,79,0.5),
        rgba(159,196,53,0.5)
      );
    }}

    .services-mini {{
      margin-top: 16px;
      color: rgba(255,255,255,0.68);
      font-size: 14px;
      line-height: 1.55;
    }}

    @media (max-width: 980px) {{
      .services-hero {{
        grid-template-columns: 1fr;
        padding: 30px 26px;
      }}

      .services-hero.split-layout {{
        grid-template-columns: 1fr;
      }}

      .tier-card {{
        grid-template-columns: 1fr;
      }}

      .tier-label {{
        min-height: 78px;
      }}

      .tier-body {{
        text-align: left;
      }}
    }}
    </style>

    <div class="topnav">
      <div class="brand">
        <img class="brand-logo" src="data:image/png;base64,{logo_b64}" />
        <span>GBIF Biodiversity Explorer</span>
      </div>
      <div class="navlinks">
        <a href="#services">Services</a>
        <a href="#data">Data Sources</a>
        <a href="#about">About</a>
      </div>
      <div class="nav-actions">
        <div class="btn">Login</div>
        <div class="btn btn-primary">Start Analysis</div>
      </div>
    </div>

    <div class="hero">
      <video class="hero-video" autoplay muted loop playsinline preload="metadata">
        <source src="{hero_video_url}" type="video/mp4">
      </video>
      <div class="hero-overlay"></div>
      <div class="inner">
        <div class="pill">Spain • GBIF Biodiversity Explorer</div>
        <h1 class="title">Biodiversity intelligence for faster site screening</h1>
        <div class="sub">
          Explore H3-based biodiversity signals, protected area context, and infrastructure pressure —
          then generate a report with AI insights.
        </div>
      </div>
    </div>

    <div id="services" style="padding:120px 10vw;">
      <div class="services-hero split-layout">
        <div class="services-left">
          <h1>Our Services</h1>
          <h2 class="services-title">Flexible access for early-stage biodiversity screening</h2>
          <div class="services-copy">
            Designed to support different levels of environmental due diligence.
            Start with a lightweight screening experience for rapid map-based exploration, or move
            into a more advanced tier with temporal analytics, predictive modeling, monitoring capacity,
            and AI-assisted project-specific insights.
          </div>
          <div class="services-mini">
            Freemium SaaS • Hexagonal spatial intelligence • No GIS expertise required
          </div>
        </div>
        <div class="services-right">
          <div class="tier-card">
            <div class="tier-label">Free Tier</div>
            <div class="tier-body">
              <ul>
                <li>No subscription required</li>
                <li>Hexagonal map interface</li>
                <li>Species richness</li>
                <li>Shannon & Simpson diversity indices</li>
                <li>IUCN Red List threat status</li>
                <li>Proximity to protected areas (WDPA)</li>
                <li>ESA WorldCover land cover analysis</li>
                <li>OpenStreetMap infrastructure context</li>
              </ul>
            </div>
          </div>
          <div class="tier-card">
            <div class="tier-label">Professional Tier</div>
            <div class="tier-body professional">
              <ul>
                <li>Everything in the free tier</li>
                <li>Temporal analytics</li>
                <li>Invasive species acceleration scoring</li>
                <li>ML predictive occurrence modelling</li>
                <li>Area of Habitat (AoH) proxy maps</li>
                <li>Agentic AI project-specific risk insights</li>
                <li>Area monitoring for subscribed hexagons</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div id="data" style="padding:120px 10vw;">
      <div class="data-card-single">
        <div class="data-card-inner">
          <div class="data-main-title">Built on multiple trusted sources for stronger biodiversity screening</div>
          <div class="data-main-copy">We combine complementary biodiversity, conservation, land cover, and infrastructure datasets to create a more complete and interpretable site-screening experience. By integrating different sources into a single workflow, the platform helps users evaluate ecological context with more confidence during early-stage analysis.</div>
          <div class="data-logos-block">
            <img class="data-logos-strip" src="data:image/png;base64,{logos_strip_b64}" alt="Data source logos" />
          </div>
        </div>
      </div>
    </div>

    <div id="about" style="padding:120px 10vw;">
      <div class="about-card">
        <div class="about-card-inner">
          <div class="about-title">About</div>
          <div class="about-copy">
            GBIF Biodiversity Explorer provides an accessible way to interpret biodiversity context during
            early-stage site screening. By combining ecological occurrence data, conservation layers, land-cover
            information, and infrastructure context into one workflow, the platform helps users identify risk,
            strengthen prioritization, and support more informed environmental decision-making.
          </div>
        </div>
      </div>
    </div>
    """)

    st.markdown(html, unsafe_allow_html=True)

