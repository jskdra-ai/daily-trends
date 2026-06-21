import os
import re
import time
import json
import requests
import subprocess
from datetime import datetime
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import google.generativeai as genai
from pytrends.request import TrendReq

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

genai.configure(api_key=GEMINI_API_KEY)
MODEL_PRIORITY = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
]
model = genai.GenerativeModel(MODEL_PRIORITY[0])

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ──────────────────────────────────────────────
# 1. 트렌드 수집 (우선순위: TikTok → YouTube → Google Trends → RSS)
# ──────────────────────────────────────────────

def get_trending_from_tiktok():
    """TikTok 트렌딩 수집 시도 (로그인 없이는 차단됨 — 빠르게 스킵)"""
    # TikTok API는 로그인 쿠키 + 앱 서명 토큰 없이는 빈 응답 반환
    # 개발자 API 계정 없이는 접근 불가 → 즉시 다음 소스로 전환
    print("  → TikTok API: 인증 필요 (자동 스킵)")
    return []


def get_trending_from_youtube():
    """BBC Entertainment + Sport RSS — YouTube 직접 스크래핑 불가로 대체"""
    topics = []
    feeds = [
        ("BBC Entertainment", "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
        ("BBC Sport",         "http://feeds.bbci.co.uk/sport/rss.xml"),
    ]
    for name, url in feeds:
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.content, "xml")
            count = 0
            for item in soup.find_all("item"):
                title_el = item.find("title")
                if not title_el:
                    continue
                title = title_el.text.strip()
                if title and len(title) > 10 and title not in topics:
                    topics.append(title[:150])
                    count += 1
                if count >= 3:
                    break
            print(f"  → {name} {count}개 수집")
        except Exception as e:
            print(f"  [{name} 오류] {e}")
    return topics


def get_trending_from_reddit():
    """Reddit RSS 시도 → 차단 시 Hacker News Algolia API로 자동 대체"""
    # 1차: Reddit RSS
    try:
        res = requests.get("https://www.reddit.com/r/all/hot.rss", headers=HEADERS, timeout=10)
        ct = res.headers.get("Content-Type", "")
        if res.status_code == 200 and ("xml" in ct or "rss" in ct):
            soup = BeautifulSoup(res.content, "xml")
            topics, seen = [], set()
            for item in soup.find_all("item"):
                title_el = item.find("title")
                if not title_el:
                    continue
                title = title_el.text.strip()
                if len(title) >= 10 and title not in seen:
                    seen.add(title)
                    topics.append(title[:150])
                if len(topics) >= 10:
                    break
            if topics:
                print(f"  → Reddit {len(topics)}개 수집")
                return topics
    except Exception:
        pass

    # 2차 fallback: Hacker News Algolia (1회 호출, 인증 불필요)
    print("  Reddit 차단 → Hacker News로 대체")
    try:
        url = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=15"
        res = requests.get(url, headers=HEADERS, timeout=10)
        topics = []
        for hit in res.json().get("hits", []):
            title = hit.get("title", "").strip()
            if title and len(title) >= 10:
                topics.append(title[:150])
            if len(topics) >= 10:
                break
        print(f"  → HackerNews {len(topics)}개 수집")
        return topics
    except Exception as e:
        print(f"  [HackerNews 오류] {e}")
        return []


def get_trending_from_wikipedia():
    """Wikipedia Pageviews REST API — 최다 조회 문서 (어제 → 그저께 순으로 시도)"""
    skip = {
        "Main_Page", "Special:Search", "Wikipedia", "Special:Random",
        "Wikipedia:Featured_pictures", "Special:RecentChanges",
    }
    try:
        from datetime import timedelta
        articles = []
        for days_back in [1, 2, 3]:
            d = datetime.now() - timedelta(days=days_back)
            url = (
                f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top"
                f"/en.wikipedia/all-access"
                f"/{d.year}/{d.month:02d}/{d.day:02d}"
            )
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                articles = res.json().get("items", [{}])[0].get("articles", [])
                if articles:
                    break

        topics = []
        for art in articles:
            title = art.get("article", "").replace("_", " ").strip()
            raw = art.get("article", "")
            if (raw not in skip
                    and not raw.startswith("Special:")
                    and not raw.startswith("Wikipedia:")
                    and not raw.startswith("Portal:")
                    and title):
                topics.append(title)
                if len(topics) >= 10:
                    break
        print(f"  → Wikipedia {len(topics)}개 수집")
        return topics
    except Exception as e:
        print(f"  [Wikipedia 오류] {e}")
        return []


def get_trending_from_google_rss():
    """[5단계] Google Trends 실시간 RSS (신규 URL: /trending/rss)"""
    try:
        url = "https://trends.google.com/trending/rss?geo=US"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"  [Google Trends] HTTP {res.status_code}")
            return []
        soup = BeautifulSoup(res.content, "xml")
        topics = []
        for item in soup.find_all("item"):
            title_el = item.find("title")
            if not title_el:
                continue
            title = title_el.text.strip()
            if title and len(title) > 3:
                topics.append(title[:150])
            if len(topics) >= 10:
                break
        print(f"  → Google Trends {len(topics)}개 수집")
        return topics
    except Exception as e:
        print(f"  [Google Trends 오류] {e}")
        return []


def get_trending_from_naver():
    """[6단계] 네이버 인기기사 스크래핑 (네이버 DataLab 뉴스 검색 권한 없어 대체)"""
    try:
        headers = {**HEADERS, "Accept-Language": "ko-KR,ko;q=0.9"}
        res = requests.get(
            "https://news.naver.com/main/ranking/popularDay.naver",
            headers=headers, timeout=10
        )
        if res.status_code != 200:
            print(f"  [네이버] HTTP {res.status_code}")
            return []
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select("a.list_title")
        skip_pfx = ["[속보]", "[단독]", "[영상]", "[포토]", "[오피니언]"]
        topics, seen = [], set()
        for item in items:
            title = item.get_text().strip()
            for pfx in skip_pfx:
                title = title.replace(pfx, "").strip()
            if title and title not in seen and len(title) > 10:
                seen.add(title)
                topics.append(title[:150])
            if len(topics) >= 10:
                break
        print(f"  → 네이버 인기기사 {len(topics)}개 수집")
        return topics
    except Exception as e:
        print(f"  [네이버 오류] {e}")
        return []


def get_trending_from_google():
    """pytrends fallback (현재 환경에서 404 반환 — 거의 사용 안 됨)"""
    try:
        pytrends = TrendReq(hl="en-US", tz=0)
        df = pytrends.trending_searches(pn="worldwide")
        topics = df[0].tolist()[:10]
        print(f"  → pytrends {len(topics)}개 수집")
        return topics
    except Exception as e:
        print(f"  [pytrends 오류] {e}")
        return []


def get_trending_from_rss():
    """Google News RSS (최후 fallback)"""
    try:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")[:10]
        topics = []
        for item in items:
            title = item.find("title").text.strip() if item.find("title") else ""
            title = re.sub(r'\s*-\s*[^-]+$', '', title).strip()
            if title:
                topics.append(title)
        print(f"  → Google News RSS {len(topics)}개 수집")
        return topics
    except Exception as e:
        print(f"  [RSS 오류] {e}")
        return []


def get_trending_topics():
    """
    8단계 수집 파이프라인 (각 소스 최대 3개, 10개 달성 시 자동 종료)
    1.TikTok(스킵) 2.BBC 3.HackerNews 4.Wikipedia
    5.Google Trends 6.네이버인기기사 7.Keyword Planner(스킵) 8.Google News RSS(보충)
    """
    combined = []

    def _add(source_topics, limit=3):
        new = [t for t in source_topics if t not in combined][:limit]
        combined.extend(new)
        print(f"  → {len(new)}개 추가 (누계 {len(combined)}개)")

    print("[1단계] TikTok 트렌드 수집...")
    get_trending_from_tiktok()

    if len(combined) < 10:
        print("[2단계] 엔터·스포츠 트렌드 수집 (BBC Entertainment/Sport)...")
        _add(get_trending_from_youtube())

    if len(combined) < 10:
        print("[3단계] Reddit/HackerNews 수집...")
        _add(get_trending_from_reddit())

    if len(combined) < 10:
        print("[4단계] Wikipedia 최다 조회 수집...")
        _add(get_trending_from_wikipedia())

    if len(combined) < 10:
        print("[5단계] Google Trends 실시간 수집...")
        _add(get_trending_from_google_rss())

    if len(combined) < 10:
        print("[6단계] 네이버 인기기사 수집...")
        _add(get_trending_from_naver())

    print("[7단계] Google Keyword Planner → Google Ads OAuth 필요 (스킵)")

    if len(combined) < 10:
        needed = 10 - len(combined)
        print(f"[8단계] Google News RSS 경쟁사 분석으로 {needed}개 보충...")
        for t in get_trending_from_rss():
            if t not in combined:
                combined.append(t)
            if len(combined) >= 10:
                break
        print(f"  → 보충 후 누계 {len(combined)}개")
    else:
        print("[8단계] 10개 달성 (스킵)")

    print(f"\n  ✓ 수집 완료: 총 {min(len(combined), 10)}개")
    return combined[:10]


# ──────────────────────────────────────────────
# 2. 뉴스 및 이미지 수집
# ──────────────────────────────────────────────

def fetch_og_image(url):
    """기사 URL에서 og:image 메타태그 추출"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        soup = BeautifulSoup(res.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content", "").startswith("http"):
            return og["content"]
        # fallback: twitter:image
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content", "").startswith("http"):
            return tw["content"]
    except Exception:
        pass
    return ""


def get_news_data(topic):
    """주제별 뉴스 내용 + 이미지 2장 이상 + 출처 링크 수집 (24시간 이내)"""
    try:
        # when:1d = 24시간 이내 기사만 검색
        q = requests.utils.quote(f"{topic} when:1d")
        search_url = (
            f"https://news.google.com/rss/search"
            f"?q={q}&hl=en-US&gl=US&ceid=US:en"
        )
        res = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")[:10]

        # 24시간 결과가 없으면 시간 제한 없이 재시도
        if len(items) < 3:
            fallback_url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(topic)}&hl=en-US&gl=US&ceid=US:en"
            )
            res = requests.get(fallback_url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.content, "xml")
            items = soup.find_all("item")[:10]

        contents = []
        images = []
        links = []

        for item in items:
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")

            title = title_el.text.strip() if title_el else ""
            desc_raw = desc_el.text if desc_el else ""
            link = link_el.text.strip() if link_el else ""

            desc_text = BeautifulSoup(desc_raw, "html.parser").get_text()
            if title:
                contents.append(f"{title}. {desc_text}")

            # RSS description 안의 이미지
            desc_soup = BeautifulSoup(desc_raw, "html.parser")
            for img_tag in desc_soup.find_all("img", src=True):
                src = img_tag["src"]
                if src.startswith("http") and src not in images:
                    images.append(src)

            # media:content, media:thumbnail 태그에서 이미지 추출
            for tag_name in ["media:content", "media:thumbnail"]:
                media = item.find(tag_name)
                if media and media.get("url", "").startswith("http"):
                    src = media["url"]
                    if src not in images:
                        images.append(src)

            # 기사 본문 og:image 수집 (이미지가 2장 미만일 때)
            if len(images) < 2 and link:
                og_img = fetch_og_image(link)
                if og_img and og_img not in images:
                    images.append(og_img)

            if link and link not in links:
                links.append(link)

            # 이미지 2장, 링크 2개 확보되면 조기 종료
            if len(images) >= 2 and len(links) >= 2:
                break

        # 이미지가 2장 미만이면 남은 링크에서 추가 시도
        if len(images) < 2:
            for link in links[1:5]:
                og_img = fetch_og_image(link)
                if og_img and og_img not in images:
                    images.append(og_img)
                if len(images) >= 2:
                    break

        # 여전히 부족하면 Bing News 이미지 검색으로 보완
        if len(images) < 2:
            try:
                bing_url = f"https://www.bing.com/news/search?q={requests.utils.quote(topic)}&format=rss"
                bing_res = requests.get(bing_url, headers=HEADERS, timeout=8)
                bing_soup = BeautifulSoup(bing_res.content, "xml")
                for bing_item in bing_soup.find_all("item")[:5]:
                    desc_raw = bing_item.find("description")
                    if desc_raw:
                        d_soup = BeautifulSoup(desc_raw.text, "html.parser")
                        img = d_soup.find("img", src=True)
                        if img and img["src"].startswith("http") and img["src"] not in images:
                            images.append(img["src"])
                    if len(images) >= 2:
                        break
            except Exception:
                pass

        print(f"  → 이미지 {len(images)}장 확보")
        return {
            "content": " ".join(contents)[:2000],
            "images": images[:3],
            "links": links[:2],
        }
    except Exception as e:
        print(f"  [뉴스 수집 오류] {e}")
        return {"content": topic, "images": [], "links": []}


# ──────────────────────────────────────────────
# 3. Gemini 콘텐츠 생성 (topic당 API 1회 호출로 통합)
# ──────────────────────────────────────────────

def call_gemini_with_retry(prompt, max_retries=3):
    """Gemini API 호출 — 429 시 대기 후 재시도, 모든 모델 실패 시 None"""
    global model
    current_model_idx = MODEL_PRIORITY.index(model.model_name.split("/")[-1]) if hasattr(model, "model_name") else 0

    for attempt in range(max_retries):
        try:
            resp = model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                # 일일 한도 소진 여부 판단 (retry_delay가 60초 이상이면 daily 한도)
                match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', err_str)
                wait_sec = int(match.group(1)) + 5 if match else 65

                # 다음 모델로 전환 시도
                next_idx = current_model_idx + attempt + 1
                if next_idx < len(MODEL_PRIORITY):
                    next_model_name = MODEL_PRIORITY[next_idx]
                    current_name = MODEL_PRIORITY[current_model_idx + attempt] if (current_model_idx + attempt) < len(MODEL_PRIORITY) else "unknown"
                    print(f"  [모델 전환] {current_name} → {next_model_name} (10초 대기)")
                    time.sleep(10)
                    model = genai.GenerativeModel(next_model_name)
                else:
                    print(f"  [API 한도] {wait_sec}초 대기 후 재시도 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_sec)
            else:
                print(f"  [Gemini 오류] {e}")
                return None
    return None


def generate_all_for_topic(topic, news_content):
    """한글제목·분류·요약·의견·해시태그를 Gemini API 1회 호출로 생성 (JSON 응답)"""
    prompt = f"""다음 뉴스 주제와 내용을 분석해서 JSON 형식으로 5가지를 작성해줘.

주제: {topic}
뉴스 내용: {news_content[:1500]}

아래 JSON 형식으로만 응답해줘 (설명 없이 JSON만):
{{
  "title": "이 뉴스를 블로그 제목으로 쓸 수 있는 한국어 제목 (40자 이내, 흥미를 끄는 문체)",
  "category": "social_economic 또는 daily_life 중 하나",
  "summary": "1000자 이내 한국어 블로그 요약. 자연스러운 문체, 핵심 위주, 마크다운 헤더(##) 사용 금지",
  "opinion": "1000자 이내 한국인 블로거 시각의 자연스러운 의견. category가 social_economic이면 사회/경제에 미치는 영향 포함, daily_life이면 개인 감상과 일상 연관성 위주. 마크다운 헤더(##) 사용 금지",
  "hashtags": "#태그1, #태그2, #태그3, #태그4, #태그5, #태그6, #태그7, #태그8, #태그9, #태그10"
}}

category 분류 기준:
- social_economic: 정치, 경제, 사회, 국제관계, 재해, 사건사고, 환경
- daily_life: 연예, 스포츠, 라이프스타일, 건강, 여행, 음식, 문화
"""
    DEFAULT = {
        "title": topic,
        "category": "social_economic",
        "summary": f"{topic}에 관한 최신 소식입니다.",
        "opinion": f"{topic}에 대한 개인적인 생각입니다.",
        "hashtags": "#트렌드, #세계뉴스, #오늘의이슈, #핫이슈, #글로벌, #뉴스요약, #최신뉴스, #정보, #이슈, #데일리",
    }

    result_text = call_gemini_with_retry(prompt)
    if not result_text:
        return DEFAULT

    try:
        json_text = re.sub(r'```json?\s*|\s*```', '', result_text).strip()
        data = json.loads(json_text)
        # 리스트로 반환된 경우 첫 번째 요소 사용
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if not isinstance(data, dict):
            return DEFAULT
        # 필수 키 보정
        for key in DEFAULT:
            if key not in data or not data[key]:
                data[key] = DEFAULT[key]
        return data
    except (json.JSONDecodeError, IndexError):
        print(f"  [JSON 파싱 실패] 기본값 사용")
        return DEFAULT


# ──────────────────────────────────────────────
# 4. HTML 생성
# ──────────────────────────────────────────────

def generate_html(results, date_str, time_str):
    """모바일 반응형 데일리 리포트 HTML"""
    cards_html = ""
    for i, item in enumerate(results, 1):
        topic = item["topic"]
        title_ko = item.get("title", topic)   # 한글 제목
        summary = item["summary"].replace("\n", "<br>")
        opinion = item["opinion"].replace("\n", "<br>")
        hashtags = item.get("hashtags", "")
        images = item.get("images", [])
        links = item.get("links", [])

        # 이미지 갤러리 (2장 이상)
        img_html = ""
        for img_url in images[:3]:
            if img_url:
                img_html += (
                    f'<img src="{img_url}" alt="{title_ko}" class="topic-img" '
                    f'onerror="this.style.display=\'none\'">\n'
                )
        gallery_html = f'<div class="img-gallery">{img_html}</div>' if img_html else ""

        # 출처 링크
        source_html = ""
        if links:
            anchors = "".join(
                f'<a href="{link}" target="_blank" rel="noopener">📎 출처 {j}</a>'
                for j, link in enumerate(links[:2], 1)
            )
            source_html = f'<div class="source-links">{anchors}</div>'

        # 해시태그 박스
        hashtag_html = ""
        if hashtags:
            hashtag_html = (
                f'<div class="hashtag-box">'
                f'<span class="hashtag-label">🏷️ 해시태그</span>'
                f'<div class="hashtag-content">{hashtags}</div>'
                f'</div>'
            )

        cards_html += f"""
        <div class="card" id="topic-{i}">
            <div class="card-rank">#{i}</div>
            {gallery_html}
            <h2 class="card-title">{title_ko}</h2>
            <div class="section">
                <div class="section-label">📰 뉴스 요약</div>
                <div class="section-content">{summary}</div>
            </div>
            {source_html}
            <div class="section opinion-section">
                <div class="section-label">💬 의견</div>
                <div class="section-content">{opinion}</div>
            </div>
            {hashtag_html}
        </div>
"""

    toc_items = "".join(
        f'<li><a href="#topic-{i}"><span class="rank-badge">#{i}</span> {results[i-1].get("title", results[i-1]["topic"])}</a></li>'
        for i in range(1, len(results) + 1)
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🌍 오늘의 세계 트렌드 Top10 - {date_str}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Malgun Gothic', sans-serif;
            background: #f0f2f5;
            color: #222;
            line-height: 1.7;
        }}
        header {{
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            color: white;
            padding: 28px 20px;
            text-align: center;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 12px rgba(0,0,0,0.3);
        }}
        header h1 {{ font-size: 1.4rem; font-weight: 700; letter-spacing: -0.5px; }}
        header p {{ font-size: 0.8rem; color: #aab; margin-top: 6px; }}
        .toc {{
            background: white;
            margin: 16px;
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.07);
        }}
        .toc h3 {{ font-size: 0.9rem; color: #888; margin-bottom: 10px; }}
        .toc-list {{ list-style: none; }}
        .toc-list li {{ padding: 5px 0; border-bottom: 1px solid #f0f0f0; }}
        .toc-list li:last-child {{ border-bottom: none; }}
        .toc-list a {{
            text-decoration: none; color: #1a1a2e;
            font-size: 0.9rem; display: flex; align-items: center; gap: 8px;
        }}
        .toc-list a:hover {{ color: #4a90e2; }}
        .rank-badge {{
            background: #1a1a2e; color: white;
            font-size: 0.7rem; padding: 2px 7px;
            border-radius: 20px; font-weight: 700; flex-shrink: 0;
        }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 0 16px 40px; }}
        .card {{
            background: white;
            border-radius: 16px;
            margin-bottom: 24px;
            overflow: hidden;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        }}
        .card-rank {{
            background: linear-gradient(135deg, #1a1a2e, #4a90e2);
            color: white;
            font-size: 0.85rem;
            font-weight: 700;
            padding: 8px 16px;
        }}
        .img-gallery {{
            display: flex;
            gap: 3px;
            background: #000;
            max-height: 220px;
            overflow: hidden;
        }}
        .img-gallery .topic-img {{
            flex: 1;
            width: 0;
            min-width: 0;
            object-fit: cover;
            display: block;
        }}
        .card-title {{
            font-size: 1.1rem;
            font-weight: 700;
            padding: 16px 16px 8px;
            color: #1a1a2e;
            line-height: 1.4;
        }}
        .section {{ padding: 12px 16px; }}
        .opinion-section {{ background: #f8f9ff; border-top: 1px solid #eef; }}
        .section-label {{
            font-size: 0.75rem;
            font-weight: 700;
            color: #4a90e2;
            margin-bottom: 8px;
            letter-spacing: 0.5px;
        }}
        .section-content {{ font-size: 0.92rem; color: #333; line-height: 1.85; }}
        .source-links {{
            padding: 4px 16px 10px;
            display: flex;
            gap: 14px;
        }}
        .source-links a {{
            font-size: 0.78rem;
            color: #4a90e2;
            text-decoration: none;
        }}
        .source-links a:hover {{ text-decoration: underline; }}
        .hashtag-box {{
            background: #eef3ff;
            border-top: 1px solid #d8e4ff;
            padding: 12px 16px;
        }}
        .hashtag-label {{
            font-size: 0.73rem;
            font-weight: 700;
            color: #6c8ebf;
            display: block;
            margin-bottom: 6px;
        }}
        .hashtag-content {{
            font-size: 0.83rem;
            color: #3a5fa5;
            line-height: 1.7;
            word-break: break-word;
        }}
        footer {{
            text-align: center;
            padding: 24px;
            font-size: 0.78rem;
            color: #aaa;
        }}
        @media (max-width: 480px) {{
            header h1 {{ font-size: 1.1rem; }}
            .card-title {{ font-size: 0.97rem; }}
            .section-content {{ font-size: 0.87rem; }}
            .img-gallery {{ max-height: 160px; }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>🌍 오늘의 세계 트렌드 Top10</h1>
        <p>{date_str} {time_str} 수집 기준</p>
    </header>

    <div class="container">
        <div class="toc">
            <h3>📋 목차</h3>
            <ul class="toc-list">
                {toc_items}
            </ul>
        </div>

        {cards_html}
    </div>

    <footer>
        자동 수집 · Gemini AI 생성 콘텐츠 | {date_str}
    </footer>
</body>
</html>"""


# ──────────────────────────────────────────────
# 5. GitHub 업로드
# ──────────────────────────────────────────────

def push_to_github():
    """변경사항 커밋 및 GitHub Pages 푸시"""
    repo_dir = "C:/Users/skybi/daily-trends"
    try:
        # git 사용자 정보 설정 (없을 경우 자동 설정)
        subprocess.run(["git", "config", "user.email", "jskdra@gmail.com"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.name", "jskdra-ai"], cwd=repo_dir, check=True)
        subprocess.run(["git", "add", "docs/index.html"], cwd=repo_dir, check=True)
        commit_msg = f"Daily trends update: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)
        print("[GitHub 업로드 완료]")
    except subprocess.CalledProcessError as e:
        print(f"[GitHub 업로드 오류] {e}")


# ──────────────────────────────────────────────
# 6. 메인
# ──────────────────────────────────────────────

def main():
    now = datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")
    time_str = now.strftime("%H:%M")

    print(f"\n{'='*52}")
    print(f"  🌍 세계 트렌드 데일리 리포트")
    print(f"  수집 시작: {date_str} {time_str}")
    print(f"  사용 모델: {MODEL_PRIORITY[0]} (한도 초과 시 자동 전환)")
    print(f"{'='*52}\n")

    topics = get_trending_topics()
    if not topics:
        print("[오류] 트렌드 수집 실패. 종료합니다.")
        return

    print(f"\n수집된 주제 {len(topics)}개:")
    for i, t in enumerate(topics, 1):
        print(f"  {i}. {t}")

    results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n[{i}/{len(topics)}] 처리 중: {topic[:60]}...")

        news_data = get_news_data(topic)
        news_content = news_data["content"]
        images = news_data["images"]
        links = news_data["links"]
        print(f"  링크 {len(links)}개 수집")

        generated = generate_all_for_topic(topic, news_content)
        print(f"  제목: {generated.get('title', topic)}")
        print(f"  분류: {generated['category']}")

        results.append({
            "topic": topic,
            "title": generated.get("title", topic),
            "summary": generated["summary"],
            "opinion": generated["opinion"],
            "hashtags": generated["hashtags"],
            "images": images,
            "links": links,
        })
        # API 호출 간격 (무료 티어 RPM 제한 대응: 15초 간격)
        time.sleep(15)
        print(f"  ✓ 완료")

    output_path = "C:/Users/skybi/daily-trends/docs/index.html"
    html_content = generate_html(results, date_str, time_str)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\n[HTML 저장 완료] {output_path}")

    push_to_github()

    print(f"\n{'='*52}")
    print("  ✅ 모든 작업 완료!")
    print(f"{'='*52}\n")


if __name__ == "__main__":
    main()
