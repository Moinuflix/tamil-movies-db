import os
import re
import time
import json
import ssl
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

TMDB_KEY = "051ccf72e026820cb53b8b8531b6a2ba"
BASE_URL = "https://moviesdatamil.co"

# SSL verification bypass
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# Quick 2026 test categories
YEAR_CATEGORIES = [
    "https://moviesdatamil.co/tamil-2026-movies/"
]

def make_request(url, referer=BASE_URL + "/"):
    try:
        req = urllib.request.Request(
            url, 
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": referer,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
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

def get_final_mp4_redirect(target_url, referer_url):
    """HTML download page ko follow karke actual .mp4 / .mkv stream link resolve karta hai"""
    try:
        req = urllib.request.Request(
            target_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": referer_url
            }
        )
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            final_url = resp.geturl()
            if any(ext in final_url.lower() for ext in [".mp4", ".mkv"]):
                return final_url
            
            # Agar intermediate download page hai to direct mp4 link regex search
            content = resp.read().decode("utf-8", errors="ignore")
            mp4_matches = re.findall(r'href=["\'](https?://[^"\']+\.(?:mp4|mkv)[^"\']*)["\']', content, re.IGNORECASE)
            if mp4_matches:
                return mp4_matches[0]
            
            return final_url
    except Exception:
        return target_url

def resolve_single_quality(qp, orig_url):
    html3 = make_request(qp, orig_url)
    links3 = extract_links(html3, qp)
    dl_pages = [l for l in links3 if "/download/" in l or "download" in l.lower()] or [qp]

    for dp in dl_pages[:2]:
        html4 = make_request(dp, qp)
        links4 = extract_links(html4, dp)
        
        # Direct server download links
        server_candidates = [l for l in links4 if any(k in l.lower() for k in ["moviespage", "downloadpage", "hotshare", "server", "file"])]
        for sp in server_candidates[:2]:
            final_stream = get_final_mp4_redirect(sp, dp)
            if final_stream and not final_stream.endswith((".css", ".js", ".html")):
                return final_stream
                
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
    for op in orig_links[:2]:
        html2 = make_request(op, movie_url)
        links2 = extract_links(html2, op)
        quality_pages = [l for l in links2 if BASE_URL in l and "sample" not in l.lower()]
        for qp in quality_pages:
            q_label = "HD"
            if "1080p" in qp.lower():
                q_label = "1080p"
            elif "720p" in qp.lower():
                q_label = "720p"
            elif "480p" in qp.lower() or "640x360" in qp.lower():
                q_label = "480p"

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
    meta = {
        "title": title, "plot": "", "poster": "", "fanart": "",
        "clearlogo": "", "trailer": "", "rating": "", "year": year, "genre": []
    }
    try:
        q = urllib.parse.quote(title)
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_KEY}&query={q}&primary_release_year={year}"
        html = make_request(url)
        data = json.loads(html) if html else {}
        if not data.get("results"):
            url_no_yr = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_KEY}&query={q}"
            html2 = make_request(url_no_yr)
            data = json.loads(html2) if html2 else {}

        if data.get("results"):
            m = data["results"][0]
            m_id = m["id"]
            meta["title"] = m.get("title", title)
            meta["plot"] = m.get("overview", "")
            meta["rating"] = str(round(m.get("vote_average", 0), 1)) if m.get("vote_average") else ""
            meta["year"] = m.get("release_date", "").split("-")[0] or year
            if m.get("poster_path"):
                meta["poster"] = f"https://image.tmdb.org/t/p/w500{m['poster_path']}"
            if m.get("backdrop_path"):
                meta["fanart"] = f"https://image.tmdb.org/t/p/original{m['backdrop_path']}"

            det_url = f"https://api.themoviedb.org/3/movie/{m_id}?api_key={TMDB_KEY}&append_to_response=images,videos&include_image_language=en,null,ta"
            det_html = make_request(det_url)
            if det_html:
                det = json.loads(det_html)
                meta["genre"] = [g["name"] for g in det.get("genres", [])]
                
                logos = det.get("images", {}).get("logos", [])
                if logos:
                    meta["clearlogo"] = f"https://image.tmdb.org/t/p/original{logos[0]['file_path']}"
                
                videos = det.get("videos", {}).get("results", [])
                trailers = [v for v in videos if v.get("site") == "YouTube" and v.get("type") in ["Trailer", "Teaser"]]
                if trailers:
                    meta["trailer"] = f"https://www.youtube.com/watch?v={trailers[0]['key']}"
    except Exception:
        pass
    return meta

def get_all_movie_links(cat_url):
    all_movies = []
    current_page = cat_url
    visited = set()
    while current_page and current_page not in visited:
        visited.add(current_page)
        html = make_request(current_page)
        if not html:
            break
        links = extract_links(html, current_page)
        all_movies.extend([l for l in links if "-movie" in l and BASE_URL in l and "tamil-movies/" not in l])
        next_pages = [l for l in links if "page" in l.lower() and BASE_URL in l and l not in visited]
        current_page = next_pages[0] if next_pages else None
    return list(dict.fromkeys(all_movies))

def process_single_movie(m_url):
    slug = m_url.rstrip("/").split("/")[-1]
    title, year = clean_name(slug)
    streams = resolve_all_streams(m_url)
    if not streams:
        return None
    meta = get_metadata(title, year)
    meta["original_filename"] = f"{title} ({year}).strm"
    meta["streams"] = streams
    meta["url"] = streams.get("1080p") or streams.get("720p") or list(streams.values())[0]
    return meta

def main():
    total_movie_links = []
    for cat in YEAR_CATEGORIES:
        links = get_all_movie_links(cat)
        if links:
            total_movie_links.extend(links)
    total_movie_links = list(dict.fromkeys(total_movie_links))

    # Fast test run on first 3 movies
    test_links = total_movie_links[:3]
    print(f"Scraping {len(test_links)} test movies...")

    movies_list = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_single_movie, url): url for url in test_links}
        for future in as_completed(futures):
            res = future.result()
            if res:
                movies_list.append(res)

    with open("movies.json", "w", encoding="utf-8") as f:
        json.dump(movies_list, f, indent=2, ensure_ascii=False)
    
    print("Done! Check movies.json for direct stream URLs.")

if __name__ == "__main__":
    main()
