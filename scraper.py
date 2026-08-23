import os
import re
import json
import ssl
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

TMDB_KEY = "051ccf72e026820cb53b8b8531b6a2ba"
BASE_URL = "https://moviesdatamil.co"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

def make_request(url, referer=BASE_URL + "/"):
    try:
        req = urllib.request.Request(url, headers={**HEADERS, "Referer": referer})
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=12) as res:
            return res.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

def extract_links(html, base):
    raw = re.findall(r'href=["\'](.*?)["\']', html)
    clean = []
    for l in raw:
        if l.startswith("javascript:") or l.startswith("#") or l in ["/", "/favicon.ico"]:
            continue
        clean.append(urllib.parse.urljoin(base, l))
    return list(dict.fromkeys(clean))

def get_real_mp4_url(download_file_url):
    """Deep resolver: moviespage -> downloadpage -> direct .mp4 link"""
    try:
        html1 = make_request(download_file_url)
        # 1. Look for downloadpage server links
        server_links = re.findall(r'href=["\'](https?://movies\.downloadpage\.xyz/download/page/[^"\']+)["\']', html1)
        target_page = server_links[0] if server_links else download_file_url

        # 2. Extract real mp4 from downloadpage
        html2 = make_request(target_page, referer=download_file_url)
        mp4_matches = re.findall(r'href=["\'](https?://[^"\']+\.(?:mp4|mkv)[^"\']*)["\']', html2, re.IGNORECASE)
        if mp4_matches:
            return mp4_matches[0]

        # 3. Fallback direct match in first page
        direct_matches = re.findall(r'href=["\'](https?://[^"\']+\.(?:mp4|mkv)[^"\']*)["\']', html1, re.IGNORECASE)
        if direct_matches:
            return direct_matches[0]

        return download_file_url
    except Exception:
        return download_file_url

def resolve_single_quality(qp, orig_url):
    html3 = make_request(qp, orig_url)
    links3 = extract_links(html3, qp)
    dl_pages = [l for l in links3 if "/download/" in l or "download" in l.lower()] or [qp]

    for dp in dl_pages[:2]:
        html4 = make_request(dp, qp)
        links4 = extract_links(html4, dp)
        server_links = [l for l in links4 if any(k in l.lower() for k in ["moviespage", "downloadpage", "file"])]
        for sp in server_links[:2]:
            real_video = get_real_mp4_url(sp)
            if any(ext in real_video.lower() for ext in [".mp4", ".mkv"]):
                return real_video
    return None

def resolve_all_streams(movie_url):
    html1 = make_request(movie_url)
    if not html1:
        return {}
    links1 = extract_links(html1, movie_url)
    orig_links = [l for l in links1 if "original" in l.lower() and BASE_URL in l] or [l for l in links1 if "-movie" in l and BASE_URL in l]
    if not orig_links:
        return {}

    streams = {}
    for op in orig_links[:1]:
        html2 = make_request(op, movie_url)
        links2 = extract_links(html2, op)
        quality_pages = [l for l in links2 if BASE_URL in l and "sample" not in l.lower()]
        for qp in quality_pages:
            q_label = "HD"
            if "1080p" in qp.lower():
                q_label = "1080p"
            elif "720p" in qp.lower():
                q_label = "720p"

            if q_label not in streams:
                link = resolve_single_quality(qp, op)
                if link:
                    streams[q_label] = link
    return streams

def clean_name(raw):
    name = re.sub(r"-tamil-movie|-movie|\.[a-zA-Z0-9]+$", "", raw, flags=re.I)
    year_match = re.search(r"\b(19\d\d|20\d\d)\b", name)
    year = year_match.group(0) if year_match else "2026"
    name = re.sub(r"\(?(19\d\d|20\d\d)\)?", "", name)
    name = re.sub(r"[\._\-\(\)]", " ", name)
    return re.sub(r"\s+", " ", name).strip().title(), year

def get_metadata(title, year):
    meta = {"title": title, "plot": "", "poster": "", "fanart": "", "clearlogo": "", "trailer": "", "rating": "", "year": year, "genre": []}
    try:
        q = urllib.parse.quote(title)
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_KEY}&query={q}&primary_release_year={year}"
        html = make_request(url)
        data = json.loads(html) if html else {}
        if data.get("results"):
            m = data["results"][0]
            meta["title"] = m.get("title", title)
            meta["plot"] = m.get("overview", "")
            meta["rating"] = str(round(m.get("vote_average", 0), 1)) if m.get("vote_average") else ""
            if m.get("poster_path"):
                meta["poster"] = f"https://image.tmdb.org/t/p/w500{m['poster_path']}"
            if m.get("backdrop_path"):
                meta["fanart"] = f"https://image.tmdb.org/t/p/original{m['backdrop_path']}"
    except Exception:
        pass
    return meta

def process_single_movie(m_url):
    slug = m_url.rstrip("/").split("/")[-1]
    title, year = clean_name(slug)
    streams = resolve_all_streams(m_url)
    if not streams:
        return None
    meta = get_metadata(title, year)
    meta["streams"] = streams
    meta["url"] = streams.get("1080p") or streams.get("720p") or list(streams.values())[0]
    return meta

def main():
    cat_url = "https://moviesdatamil.co/tamil-2026-movies/"
    html = make_request(cat_url)
    links = extract_links(html, cat_url)
    movie_links = [l for l in links if "-movie" in l and BASE_URL in l and "tamil-movies/" not in l]
    movie_links = list(dict.fromkeys(movie_links))

    # Test top 10 movies only (Runs in 1-2 minutes)
    test_10 = movie_links[:10]
    print(f"Scraping top {len(test_10)} test movies...")

    movies_list = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_single_movie, url): url for url in test_10}
        for future in as_completed(futures):
            res = future.result()
            if res:
                movies_list.append(res)

    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(movies_list, f, indent=2, ensure_ascii=False)

    print("Success! Top 10 movies updated with direct MP4 links.")

if __name__ == "__main__":
    main()
