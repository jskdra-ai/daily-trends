import os
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
model = genai.GenerativeModel("gemini-2.5-flash")


def get_trending_topics():
    """Google Trends에서 전세계 실시간 인기 검색어 Top10 수집"""
    try:
        pytrends = TrendReq(hl="en-US", tz=0)
        df = pytrends.trending_searches(pn="worldwide")
        topics = df[0].tolist()[:10]
        print(f"[트렌드 수집 완료] {len(topics)}개")
        return topics
    except Exception as e:
        print(f"[트렌드 수집 오류] {e}")
        return get_trending_from_rss()


def get_trending_from_rss():
    """Google News RSS에서 트렌드 수집 (fallback)"""
    try:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")[:10]
        topics = [item.find("title").text.strip() for item in items]
        print(f"[RSS 트렌드 수집] {len(topics)}개")
        return topics
    except Exception as e:
        print(f"[RSS 수집 오류] {e}")
        return []


def get_news_content(topic):
    """주제별 최신 뉴스 내용 수집"""
    try:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(topic)}&hl=en-US&gl=US&ceid=US:en"
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")[:3]
        contents = []
        for item in items:
            title = item.find("title").text if item.find("title") else ""
            desc = item.find("description").text if item.find("description") else ""
            desc_clean = BeautifulSoup(desc, "html.parser").get_text()
            contents.append(f"{title}. {desc_clean}")
        return " ".join(contents)[:2000]
    except Exception as e:
        print(f"[뉴스 수집 오류] {topic}: {e}")
        return topic


def get_news_image(topic):
    """구글 뉴스에서 이미지 URL 수집"""
    try:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(topic)}&hl=en-US&gl=US&ceid=US:en"
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.content, "xml")
        item = soup.find("item")
        if item:
            desc = item.find("description").text if item.find("description") else ""
            img_soup = BeautifulSoup(desc, "html.parser")
            img = img_soup.find("img")
            if img and img.get("src"):
                return img["src"]
    except Exception as e:
        print(f"[이미지 수집 오류] {topic}: {e}")
    return ""


def generate_summary(topic, news_content):
    """Gemini API로 1000자 이내 뉴스 요약 생성"""
    prompt = f"""
다음 주제와 뉴스 내용을 바탕으로 한국어 블로그용 요약글을 작성해줘.

조건:
- 1000자 이내
- 자연스러운 블로그 문체
- 핵심 내용 위주로 간결하게
- 독자가 이해하기 쉽게 풀어서 설명

주제: {topic}
뉴스 내용: {news_content}
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[요약 생성 오류] {topic}: {e}")
        return f"{topic}에 관한 내용입니다."


def generate_opinion(topic, news_content):
    """Gemini API로 1000자 이내 자연스러운 의견 생성"""
    prompt = f"""
다음 주제에 대해 한국인 블로거의 시각으로 개인 의견을 작성해줘.

조건:
- 1000자 이내
- 일상적이고 자연스러운 말투
- 주제가 일상/엔터테인먼트라면 개인적 감상과 느낌 위주로
- 주제가 사회/경제라면 사회에 미치는 영향과 개인적 견해 포함
- 독자가 공감할 수 있는 내용으로

주제: {topic}
뉴스 내용: {news_content}
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[의견 생성 오류] {topic}: {e}")
        return f"{topic}에 대한 개인적인 생각입니다."


def generate_html(results, date_str, time_str):
    """모바일 반응형 HTML 페이지 생성"""
    cards_html = ""
    for i, item in enumerate(results, 1):
        topic = item["topic"]
        summary = item["summary"].replace("\n", "<br>")
        opinion = item["opinion"].replace("\n", "<br>")
        image_url = item.get("image", "")
        img_tag = f'<img src="{image_url}" alt="{topic}" class="topic-img">' if image_url else ""

        cards_html += f"""
        <div class="card" id="topic-{i}">
            <div class="card-rank">#{i}</div>
            {img_tag}
            <h2 class="card-title">{topic}</h2>
            <div class="section">
                <div class="section-label">📰 뉴스 요약</div>
                <div class="section-content">{summary}</div>
            </div>
            <div class="section opinion-section">
                <div class="section-label">💬 의견</div>
                <div class="section-content">{opinion}</div>
            </div>
        </div>
"""

    html = f"""<!DOCTYPE html>
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
        .toc-list a {{ text-decoration: none; color: #1a1a2e; font-size: 0.9rem; display: flex; align-items: center; gap: 8px; }}
        .toc-list a:hover {{ color: #4a90e2; }}
        .rank-badge {{ background: #1a1a2e; color: white; font-size: 0.7rem; padding: 2px 7px; border-radius: 20px; font-weight: 700; }}
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
        .topic-img {{
            width: 100%;
            max-height: 220px;
            object-fit: cover;
            display: block;
        }}
        .card-title {{
            font-size: 1.15rem;
            font-weight: 700;
            padding: 16px 16px 8px;
            color: #1a1a2e;
            line-height: 1.4;
        }}
        .section {{ padding: 12px 16px; }}
        .opinion-section {{ background: #f8f9ff; border-top: 1px solid #eef; }}
        .section-label {{
            font-size: 0.78rem;
            font-weight: 700;
            color: #4a90e2;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .section-content {{ font-size: 0.92rem; color: #333; line-height: 1.8; }}
        footer {{
            text-align: center;
            padding: 20px;
            font-size: 0.78rem;
            color: #aaa;
        }}
        @media (max-width: 480px) {{
            header h1 {{ font-size: 1.15rem; }}
            .card-title {{ font-size: 1rem; }}
            .section-content {{ font-size: 0.88rem; }}
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
                {"".join(f'<li><a href="#topic-{i}"><span class="rank-badge">#{i}</span> {results[i-1]["topic"]}</a></li>' for i in range(1, len(results)+1))}
            </ul>
        </div>

        {cards_html}
    </div>

    <footer>
        자동 수집 · 생성된 콘텐츠입니다 | {date_str}
    </footer>
</body>
</html>"""
    return html


def push_to_github():
    """GitHub에 변경사항 커밋 및 푸시"""
    try:
        subprocess.run(["git", "add", "docs/index.html"], cwd="C:/Users/skybi/daily-trends", check=True)
        commit_msg = f"Daily trends update: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd="C:/Users/skybi/daily-trends", check=True)
        subprocess.run(["git", "push"], cwd="C:/Users/skybi/daily-trends", check=True)
        print("[GitHub 업로드 완료]")
    except subprocess.CalledProcessError as e:
        print(f"[GitHub 업로드 오류] {e}")


def main():
    now = datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일")
    time_str = now.strftime("%H:%M")

    print(f"\n{'='*50}")
    print(f"  세계 트렌드 수집 시작: {date_str} {time_str}")
    print(f"{'='*50}\n")

    topics = get_trending_topics()
    if not topics:
        print("[오류] 트렌드 수집 실패. 종료합니다.")
        return

    results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n[{i}/10] {topic} 처리 중...")
        news_content = get_news_content(topic)
        image_url = get_news_image(topic)
        summary = generate_summary(topic, news_content)
        time.sleep(1)
        opinion = generate_opinion(topic, news_content)
        time.sleep(1)

        results.append({
            "topic": topic,
            "summary": summary,
            "opinion": opinion,
            "image": image_url
        })
        print(f"  ✓ 완료")

    html_content = generate_html(results, date_str, time_str)
    output_path = "C:/Users/skybi/daily-trends/docs/index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\n[HTML 저장 완료] {output_path}")

    push_to_github()

    print(f"\n{'='*50}")
    print("  모든 작업 완료!")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
