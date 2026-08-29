"""
Real TV — Political & Interview Performance Report
--------------------------------------------------
A standalone, occasional-use report (heavy pull — kept OUT of the daily App 1).

It answers, from real public data, NEUTRALLY:
  • POLITICAL: which political topics/videos pull the best views & engagement,
    sliceable by keyword category (AP parties, Telangana parties, leaders,
    political terms) — so Real TV can see what political coverage lands.
  • INTERVIEWS: which interviews/formats/lengths perform best — so the team
    can decide who to interview and how.

Neutral by design: this measures AUDIENCE ATTENTION only (views, likes,
comments). It does NOT score sentiment, take sides, or rate parties/leaders.
Classification is by TITLE KEYWORDS (approximate, editable below), and matched
videos are shown so you can eyeball accuracy.

Password-gated. HTML export. API key in Secrets, not here.
"""

from datetime import datetime, timezone, timedelta
import re
import requests
import pandas as pd
import streamlit as st

IST = timezone(timedelta(hours=5, minutes=30))
API_BASE = "https://www.googleapis.com/youtube/v3"
MONTHS_BACK = 5
PER_CHANNEL_CAP = 120

# ─────────────────────────────────────────────────────────────────────────────
# CHANNELS — your 11 news channels + SumanTV + BigTV
# ─────────────────────────────────────────────────────────────────────────────
CHANNELS = [
    {"label": "Real TV (you)",  "handle": "@realtvtelugunews", "id": None},
    {"label": "TV9 Telugu",     "handle": "@tv9telugu",        "id": "UCPXTXMecYqnRKNdqdVOGSFg"},
    {"label": "NTV Telugu",     "handle": "@ntvteluguofficial","id": "UCumtYpCY26F6Jr3satUgMvA"},
    {"label": "TV5 News",       "handle": "@tv5newschannel",   "id": None},
    {"label": "V6 News",        "handle": "@V6News",           "id": None},
    {"label": "Sakshi TV",      "handle": "@SakshiTV",         "id": None},
    {"label": "ABN Telugu",     "handle": "@abntelugutv",      "id": None},
    {"label": "10TV",           "handle": "@10TVNewsTelugu",   "id": None},
    {"label": "Mahaa News",     "handle": "@mahaanews",        "id": "UCDKjhgRoPF1CQk7HluMz23A"},
    {"label": "ETV Andhra",     "handle": "@etvandhrapradesh", "id": None},
    {"label": "HMTV",           "handle": "@hmtvlive",         "id": "UCNZOrs1QBt8cJnv9ud96qRA"},
    {"label": "SumanTV",        "handle": "@SumanTVChannel",   "id": None},
    {"label": "BigTV Telugu Live","handle": "@BIGTVTeluguLive","id": None},
]

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORD TAXONOMY — neutral, for CLASSIFICATION and the FILTER column.
# Purpose is only to detect and group political / interview videos so their
# AUDIENCE PERFORMANCE can be compared. It does not rank or judge any party
# or person. Edit freely — add spellings/aliases (Telugu + English) as needed.
# Each entry: category -> list of match terms (lowercased match).
# ─────────────────────────────────────────────────────────────────────────────
KEYWORD_CATEGORIES = {
    # --- Andhra Pradesh parties ---
    "AP · TDP":        ["tdp", "telugu desam", "తెలుగుదేశం", "టిడిపి"],
    "AP · YSRCP":      ["ysrcp", "ysr congress", "వైసిపి", "వైఎస్సార్సిపి", "ysrc"],
    "AP · Jana Sena":  ["jana sena", "janasena", "జనసేన", "jsp"],
    "AP · BJP (AP)":   ["bjp ap", "bharatiya janata"],  # BJP national; AP context
    # --- Telangana parties ---
    "TG · BRS":        ["brs", "trs", "bharat rashtra", "భారత రాష్ట్ర సమితి", "బిఆర్ఎస్"],
    "TG · Congress":   ["congress", "కాంగ్రెస్", "inc", "revanth"],
    "TG · BJP (TG)":   ["bjp telangana", "bjp tg"],
    "TG · AIMIM":      ["aimim", "mim", "owaisi", "ఏఐఎంఐఎం"],
    # --- Leaders (public figures; neutral list for topic detection) ---
    "Leaders · AP":    ["chandrababu", "cbn", "jagan", "pawan kalyan", "lokesh",
                        "చంద్రబాబు", "జగన్", "పవన్", "లోకేష్"],
    "Leaders · TG":    ["kcr", "ktr", "revanth", "kavitha", "harish rao",
                        "కేసీఆర్", "కేటీఆర్", "రేవంత్"],
    "Leaders · National": ["modi", "rahul gandhi", "amit shah", "మోడీ", "మోదీ"],
    # --- Generic political terms ---
    "Political terms": ["assembly", "mla", "mp", "minister", "election", "elections",
                        "cabinet", "cm ", "chief minister", "parliament", "govt",
                        "government", "vote", "poll", "సభ", "అసెంబ్లీ", "ఎమ్మెల్యే",
                        "మంత్రి", "ఎన్నికలు", "ప్రభుత్వం", "రాజకీయ", "political"],
}

# Region grouping (for the AP vs Telangana filter)
REGION_MAP = {
    "AP · TDP": "Andhra Pradesh", "AP · YSRCP": "Andhra Pradesh",
    "AP · Jana Sena": "Andhra Pradesh", "AP · BJP (AP)": "Andhra Pradesh",
    "Leaders · AP": "Andhra Pradesh",
    "TG · BRS": "Telangana", "TG · Congress": "Telangana",
    "TG · BJP (TG)": "Telangana", "TG · AIMIM": "Telangana",
    "Leaders · TG": "Telangana",
    "Leaders · National": "National", "Political terms": "General",
}

# Interview detection
INTERVIEW_TERMS = ["interview", "exclusive interview", "special interview",
                   "ముఖాముఖి", "మ.ఖాముఖి", "muఖాముఖి", "face to face",
                   "special chat", "exclusive chat", "ఇంటర్వ్యూ", "interaction",
                   "conversation with", "in conversation"]

# ─────────────────────────────────────────────────────────────────────────────
def get_api_key():
    try:
        return st.secrets["YT_API_KEY"]
    except Exception:
        st.error('No API key. In Streamlit → Settings → Secrets add:  YT_API_KEY = "your-key"')
        st.stop()


# ── Password gate ────────────────────────────────────────────────────────────
def check_password():
    if st.session_state.get("_authed"):
        return
    try:
        expected = st.secrets["APP_PASSWORD"]
    except Exception:
        st.error('No app password set. In Streamlit → Settings → Secrets add:  '
                 'APP_PASSWORD = "choose-a-shared-password"')
        st.stop()
    st.title("🔒 Real TV — Team Access")
    pw = st.text_input("Password", type="password")
    if st.button("Enter"):
        if pw == expected:
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_channel(channel, api_key):
    params = {"part": "snippet,contentDetails,statistics", "key": api_key}
    if channel.get("id"):
        params["id"] = channel["id"]
    else:
        params["forHandle"] = channel["handle"].lstrip("@")
    r = requests.get(f"{API_BASE}/channels", params=params, timeout=20)
    if r.status_code != 200:
        return {"label": channel["label"], "error": r.json().get("error", {}).get("message", r.text)}
    items = r.json().get("items", [])
    if not items:
        hint = channel.get("id") or channel.get("handle")
        return {"label": channel["label"], "error": f"not found ({hint})"}
    c = items[0]
    return {"label": channel["label"],
            "uploads_playlist": c["contentDetails"]["relatedPlaylists"]["uploads"],
            "subs": int(c["statistics"].get("subscriberCount", 0)), "error": None}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_recent_uploads(uploads_playlist, api_key, max_items):
    ids, token = [], None
    while len(ids) < max_items:
        params = {"part": "contentDetails", "playlistId": uploads_playlist,
                  "maxResults": min(50, max_items - len(ids)), "key": api_key}
        if token:
            params["pageToken"] = token
        r = requests.get(f"{API_BASE}/playlistItems", params=params, timeout=20)
        if r.status_code != 200:
            break
        data = r.json()
        ids.extend(it["contentDetails"]["videoId"] for it in data.get("items", []))
        token = data.get("nextPageToken")
        if not token:
            break
    return ids[:max_items]


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_video_details(video_ids, api_key):
    out = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        r = requests.get(f"{API_BASE}/videos", params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk), "key": api_key}, timeout=20)
        if r.status_code == 200:
            out.extend(r.json().get("items", []))
    return out


def parse_duration(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return h*3600 + mn*60 + s


def humanize(n):
    n = int(n)
    if n >= 10_000_000: return f"{n/10_000_000:.1f}Cr"
    if n >= 100_000:    return f"{n/100_000:.1f}L"
    if n >= 1_000:      return f"{n/1_000:.1f}K"
    return str(n)


def classify(title):
    """Return (matched_categories:list, matched_regions:set, is_interview:bool)."""
    t = title.lower()
    cats = [cat for cat, terms in KEYWORD_CATEGORIES.items()
            if any(term in t for term in terms)]
    regions = {REGION_MAP.get(c, "General") for c in cats}
    is_interview = any(term in t for term in INTERVIEW_TERMS)
    return cats, regions, is_interview


@st.cache_data(ttl=86400, show_spinner=False)
def build(api_key, months_back, cap):
    now = datetime.now(IST)
    cutoff = now - timedelta(days=months_back*30)
    rows, errors = [], []
    for channel in CHANNELS:
        ch = resolve_channel(channel, api_key)
        if ch.get("error"):
            errors.append(f"{channel['label']}: {ch['error']}")
            continue
        vids = fetch_video_details(
            fetch_recent_uploads(ch["uploads_playlist"], api_key, cap), api_key)
        for v in vids:
            published = datetime.fromisoformat(
                v["snippet"]["publishedAt"].replace("Z", "+00:00")).astimezone(IST)
            if published < cutoff:
                continue
            title = v["snippet"]["title"]
            cats, regions, is_interview = classify(title)
            stats = v.get("statistics", {})
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            dur = parse_duration(v.get("contentDetails", {}).get("duration", ""))
            rows.append({
                "Channel": ch["label"], "Title": title, "Views": views,
                "Likes": likes, "Comments": comments,
                "Engagement %": round((likes+comments)/views*100, 2) if views else 0,
                "Type": "Short" if 0 < dur <= 60 else "Long",
                "Length_s": dur,
                "Categories": cats, "Regions": sorted(regions),
                "Is political": bool(cats),
                "Is interview": is_interview,
                "Month": published.strftime("%Y-%m"),
                "Link": f"https://youtu.be/{v['id']}",
            })
    return pd.DataFrame(rows), errors, now


# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Real TV — Political & Interview Report", layout="wide")
check_password()
st.title("Real TV — Political & Interview Performance Report")
st.caption("Neutral audience-attention analysis (views, likes, comments) of political "
           "and interview coverage across Telugu news channels. Measures what draws "
           "viewers — it does not score sentiment or take sides.")

with st.sidebar:
    st.header("Settings")
    months = st.slider("Months to look back", 3, 6, MONTHS_BACK)
    cap = st.slider("Max videos per channel", 40, 200, PER_CHANNEL_CAP, step=20)
    if st.button("Rebuild report", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Heavy pull — caches 24h. Keep this OUT of daily use to protect quota.")

api_key = get_api_key()
with st.spinner("Building report — pulling recent months across all channels…"):
    df, errors, now = build(api_key, months, cap)

st.caption(f"Built {now.strftime('%d %b %Y, %I:%M %p IST')} · {months}-month window")
if errors:
    with st.expander(f"⚠️ {len(errors)} channel(s) couldn't be read — fix handle/id"):
        for e in errors:
            st.write("•", e)
if df.empty:
    st.warning("No data resolved. Fix handles/IDs and rebuild.")
    st.stop()

df["Length band"] = df["Length_s"].apply(
    lambda s: "Short (≤1m)" if s <= 60 else "Mid (1–8m)" if s <= 480
    else "Long (8–20m)" if s <= 1200 else "XLong (20m+)")

tabs = st.tabs([
    "🏛️ Political performance",
    "🎙️ Interview performance",
    "📈 Trend (5-month)",
    "⬇️ Export",
])

# ── Political performance (with filter) ──
with tabs[0]:
    st.subheader("Political coverage — what draws viewers")
    pol = df[df["Is political"]].copy()
    if pol.empty:
        st.info("No political videos matched. Widen the keyword lists in the config.")
    else:
        # explode categories so one video can count under each matched category
        exploded = pol.explode("Categories")
        all_regions = sorted({r for rs in pol["Regions"] for r in rs})
        all_cats = sorted(exploded["Categories"].dropna().unique())

        c1, c2 = st.columns(2)
        with c1:
            region_pick = st.multiselect("Filter by region", all_regions, default=all_regions)
        with c2:
            cat_pick = st.multiselect("Filter by keyword category", all_cats, default=all_cats)

        # apply filters
        mask = pol["Regions"].apply(lambda rs: any(r in region_pick for r in rs))
        pol_f = pol[mask]
        exploded_f = exploded[exploded["Categories"].isin(cat_pick)]

        m1, m2, m3 = st.columns(3)
        m1.metric("Political videos", len(pol_f))
        m2.metric("Median views", humanize(int(pol_f["Views"].median())) if not pol_f.empty else "0")
        m3.metric("Avg engagement %", round(pol_f["Engagement %"].mean(), 2) if not pol_f.empty else 0)

        st.markdown("**Performance by keyword category** (median views — what topics land)")
        cat_perf = (exploded_f.groupby("Categories")
                    .agg(Videos=("Title", "size"),
                         **{"Median views": ("Views", "median"),
                            "Avg engagement %": ("Engagement %", "mean")})
                    .reset_index().sort_values("Median views", ascending=False))
        cat_perf["Median views"] = cat_perf["Median views"].round().astype(int).apply(humanize)
        cat_perf["Avg engagement %"] = cat_perf["Avg engagement %"].round(2)
        st.dataframe(cat_perf, use_container_width=True, hide_index=True)

        st.markdown("**Top political videos** (matched — eyeball classifier accuracy here)")
        top = pol_f.sort_values("Views", ascending=False).head(15)[
            ["Channel", "Title", "Views", "Engagement %", "Type", "Link"]].copy()
        top["Views"] = top["Views"].apply(humanize)
        st.dataframe(top, use_container_width=True, hide_index=True,
                     column_config={"Link": st.column_config.LinkColumn("Watch", display_text="▶")})

# ── Interview performance ──
with tabs[1]:
    st.subheader("Interviews — what formats and lengths perform")
    iv = df[df["Is interview"]].copy()
    if iv.empty:
        st.info("No interview videos matched. Widen INTERVIEW_TERMS in the config.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Interview videos", len(iv))
        m2.metric("Median views", humanize(int(iv["Views"].median())))
        m3.metric("Avg engagement %", round(iv["Engagement %"].mean(), 2))

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**By length band (median views)**")
            order = {"Short (≤1m)":0,"Mid (1–8m)":1,"Long (8–20m)":2,"XLong (20m+)":3}
            lb = (iv.groupby("Length band")["Views"].median().round().astype(int)
                  .reset_index().rename(columns={"Views": "Median views"}))
            lb["_o"] = lb["Length band"].map(order)
            lb = lb.sort_values("_o").drop(columns="_o")
            lb["Median views"] = lb["Median views"].apply(humanize)
            st.dataframe(lb, use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**By channel (who does interviews best)**")
            by_ch = (iv.groupby("Channel")
                     .agg(Videos=("Title", "size"), **{"Median views": ("Views", "median")})
                     .reset_index().sort_values("Median views", ascending=False))
            by_ch["Median views"] = by_ch["Median views"].round().astype(int).apply(humanize)
            st.dataframe(by_ch, use_container_width=True, hide_index=True)

        st.markdown("**Top interviews** (matched — eyeball accuracy; guest names visible in titles)")
        top = iv.sort_values("Views", ascending=False).head(15)[
            ["Channel", "Title", "Views", "Engagement %", "Length band", "Link"]].copy()
        top["Views"] = top["Views"].apply(humanize)
        st.dataframe(top, use_container_width=True, hide_index=True,
                     column_config={"Link": st.column_config.LinkColumn("Watch", display_text="▶")})

# ── Trend ──
with tabs[2]:
    st.subheader("How political & interview attention is moving (post-month cohorts)")
    st.caption("Median views by the month a video was posted. Rising = the theme is "
               "gaining traction. Cohort method, not per-video history.")
    pol = df[df["Is political"]]
    iv = df[df["Is interview"]]
    trend = pd.DataFrame({
        "Political": pol.groupby("Month")["Views"].median(),
        "Interviews": iv.groupby("Month")["Views"].median(),
    }).sort_index()
    if not trend.empty:
        st.line_chart(trend)
        st.caption("Median views per posted-month.")
        st.markdown("**Political performance by region over time (median views)**")
        pol_r = pol.explode("Regions")
        reg_trend = (pol_r.groupby(["Month", "Regions"])["Views"].median()
                     .reset_index().pivot(index="Month", columns="Regions", values="Views").sort_index())
        if not reg_trend.empty:
            st.line_chart(reg_trend)
    else:
        st.info("Not enough data to chart trend.")

# ── Export ──
with tabs[3]:
    st.subheader("Export report")
    pol = df[df["Is political"]]
    iv = df[df["Is interview"]]
    pol_ex = pol.explode("Categories")
    cat_perf = (pol_ex.groupby("Categories")
                .agg(v=("Title", "size"), med=("Views", "median"), eng=("Engagement %", "mean"))
                .reset_index().sort_values("med", ascending=False)) if not pol.empty else pd.DataFrame()

    cat_rows = "".join(
        f"<tr><td>{r.Categories}</td><td>{int(r.v)}</td>"
        f"<td>{humanize(int(r.med))}</td><td>{r.eng:.2f}%</td></tr>"
        for r in cat_perf.itertuples()) if not cat_perf.empty else ""

    iv_top = iv.sort_values("Views", ascending=False).head(12) if not iv.empty else pd.DataFrame()
    iv_rows = "".join(
        f"<tr><td>{row.Channel}</td><td>{row.Title[:70]}</td>"
        f"<td>{humanize(row.Views)}</td><td>{row['Engagement %']:.1f}%</td></tr>"
        for _, row in iv_top.iterrows()) if not iv_top.empty else ""

    pol_med = humanize(int(pol["Views"].median())) if not pol.empty else "—"
    iv_med = humanize(int(iv["Views"].median())) if not iv.empty else "—"

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Real TV — Political & Interview Report</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1a1a1a;line-height:1.5}}
h1{{border-bottom:3px solid #c00;padding-bottom:8px}} h2{{margin-top:32px;color:#c00}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left;font-size:14px}} th{{background:#f4f4f4}}
.box{{background:#f9f9f9;border-left:4px solid #c00;padding:12px 16px;margin:16px 0}}
.muted{{color:#666;font-size:13px}}
</style></head><body>
<h1>Real TV — Political & Interview Performance Report</h1>
<p class="muted">Generated {now.strftime('%d %b %Y')} · {months}-month window · {len(df)} videos ·
{df['Channel'].nunique()} channels · neutral audience-attention analysis, not sentiment.</p>
<div class="box">Political videos median <b>{pol_med}</b> views · Interview videos median
<b>{iv_med}</b> views. Details below.</div>
<h2>Political performance by keyword category</h2>
<table><tr><th>Category</th><th>Videos</th><th>Median views</th><th>Avg engagement</th></tr>
{cat_rows}</table>
<h2>Top interviews</h2>
<table><tr><th>Channel</th><th>Title</th><th>Views</th><th>Eng.</th></tr>{iv_rows}</table>
<p class="muted">Classification by title keywords (approximate). Measures attention only;
does not score sentiment or rate any party or person. Validate with Studio data once live.</p>
</body></html>"""

    st.download_button("⬇️ Download HTML report", data=html,
                       file_name=f"realtv_political_interview_{now.strftime('%Y%m%d')}.html",
                       mime="text/html", use_container_width=True)
    st.caption("Open the file → Print → Save as PDF to share.")
