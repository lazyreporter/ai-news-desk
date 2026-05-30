import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import email.utils
import time
import streamlit as st
import streamlit.components.v1 as components 

# 브라우저 자체 저장을 위한 라이브러리
from streamlit_cookies_manager import EncryptedCookieManager

from google import genai
from google.genai import types

st.set_page_config(page_title="통합 AI 데스크", page_icon="📝", layout="wide")

# ==========================================
# --- 브라우저 쿠키 매니저 설정 ---
# ==========================================
cookies = EncryptedCookieManager(prefix="kbcdesk", password="kbc_newsroom_master_password_2026")
if not cookies.ready():
    st.stop()

# ==========================================
# --- 세션 및 기본값 초기화 (원본 규칙 100% 복구) ---
# ==========================================
default_rules = {
    "report": "🚨 [필수 준수 규칙]\n발제하는 아이템에 맞춰서 방송용 리포트 기사를 작성합니다. 감정적인 요소를 최대한 절제하고 객관적인 문장을 사용합니다. 방송 기사는 구어체, 존댓말을 기반으로 작성합니다. KBC 광주방송이나 SBS 8시 뉴스에 송출되는 기사들의 양식을 따릅니다. 일반적으로 앵커멘트 2문장과 기사 본문 7~8문장, 인터뷰나 싱크 2개로 작성됩니다. 기사 전체 길이는 2분 안팎에 머물러야 합니다. 주로 기사 초반부에 현장의 문제점이나 사례 등을 보여주고 이후 해당 사안에 대한 분석을 담는 포맷을 선호합니다. 기사에 들어가는 정보는 직접 취재를 해서 제공되기도 하지만 인터넷에 기 보도된 다른 언론사의 기사들을 참고해도 좋습니다.",
    "briefing": "🚨 [필수 준수 규칙]\n각종 보도자료나 통신매체에 있는 기사를 방송용 단신 기사로 바꾸는 작업을 수행합니다. 제공된 자료를 살펴보고 핵심적인 내용을 3줄로 뽑아서 작성합니다. 첫번째 문장은 리드문장으로 중요한 정보를 간략하게 작성합니다. 두번째 문장은 본문으로, 리드문장에 들어간 정보를 제공한 기관명을 시작으로 육하원칙에 맞게 세부적인 내용을 작성합니다. 세번째 문장은 부가 문장으로 리드와 본문에 담지 못한 추가적인 내용을 담습니다. KBC8뉴스에 나온 단신 기사의 포맷을 참고하면 좋습니다. 14글자 안팎의 방송용 자막, 제목도 함께 제안합니다.",
    "portal": "🚨 [필수 준수 규칙]\n제공되는 기사를 방송용 포털기사로 다시 작성합니다. 기사의 방식은 전형적인 역피라미드 형태입니다. 첫 리드 문장에 기사 전체의 핵심 내용을 간략하게 담습니다. 방송기사와 같이 구어체로 존댓말을 사용합니다. 기존의 KBC 인터넷용 기사를 참고해서 규칙을 적용하면 좋습니다. 날짜는 오늘, 내일 대신 명시된 날짜를 사용합니다. 날짜는 현재 시점의 경우 일자만 적고 연도와 월은 생략합니다. 다가올 미래 시제일 경우 '오는 00일'로 표기합니다. 매 문장마다 문단을 바꿉니다. 시간을 표시할때 정확하지 않은 경우 뒤에 '쯤'을 붙입니다. 월, 일, 오전, 오후 뒤에는 붙이지 않습니다. 나이는 '마흔아홉살'이 아닌 '49살' 처럼 숫자로 작성합니다. 문장 어미에 '데요'를 쓰지 않습니다. 문장 첫 단어로 '이는'을 쓰지 않습니다. 기존 기사보다 최대한 깔끔하게 표현을 바꿉니다. 감정적인 표현은 최대한 배제합니다. 기사 내 언급된 인물이 직접 한 말은 큰따옴표로 처리합니다. 관련된 기사를 검색해서 추가적인 정보도 추가합니다. 검색해서 정보를 추가한 부분은 볼드체로 표기합니다. 검색했던 근거도 링크로 함께 보여줍니다. 사람들이 많이 클릭하게 할만한 기사의 제목도 2~3개씩 함께 제안합니다."
}

if "api_keys" not in st.session_state:
    st.session_state.api_keys = {
        "naver_id": cookies.get("naver_id", ""),
        "naver_secret": cookies.get("naver_secret", ""),
        "gemini": cookies.get("gemini", "")
    }

if "rules" not in st.session_state:
    st.session_state.rules = {
        "report": cookies.get("rule_report", default_rules["report"]) or default_rules["report"],
        "briefing": cookies.get("rule_briefing", default_rules["briefing"]) or default_rules["briefing"],
        "portal": cookies.get("rule_portal", default_rules["portal"]) or default_rules["portal"]
    }

if "keywords" not in st.session_state:
    st.session_state.keywords = {
        "local": cookies.get("kw_local", "광주, 전남") or "광주, 전남",
        "national": cookies.get("kw_national", "정치, 사고, 사건, 속보") or "정치, 사고, 사건, 속보"
    }

if "news_states" not in st.session_state:
    st.session_state.news_states = {}

# --- 원클릭 복사 버튼 ---
def create_copy_button(text_to_copy):
    js_safe_text = json.dumps(text_to_copy).replace("<", "\\u003c")
    html_code = f"""
    <button id="copy-btn" style="width: 100%; background-color: #4CAF50; color: white; padding: 12px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: bold;" 
    onclick='copyToClipboard()'>📋 텍스트 복사하기</button>
    <script>
    function copyToClipboard() {{
        const text = {js_safe_text};
        navigator.clipboard.writeText(text).then(function() {{ alert("텍스트가 복사되었습니다!"); }});
    }}
    </script>
    """
    components.html(html_code, height=70)

# --- 기능 함수 모음 ---
def get_article_full_text(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            body = soup.find('div', id='dic_area') or soup.find('div', id='newsct_article')
            return body.get_text(separator=' ', strip=True) if body else "ERROR_NOT_NAVER"
        return "ERROR_CONNECTION"
    except Exception as e: return f"ERROR: {e}"

def fetch_news(keyword, client_id, client_secret, hours=3):
    enc_text = urllib.parse.quote(keyword)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=100&sort=sim"
    try:
        response = requests.get(url, headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret})
        if response.status_code == 200:
            news_data = response.json()
            filtered_news = []
            limit = datetime.now(timezone(timedelta(hours=9))) - timedelta(hours=hours)
            for item in news_data.get("items", []):
                pub_date = email.utils.parsedate_to_datetime(item["pubDate"])
                if pub_date >= limit and "naver.com" in item["link"]:
                    filtered_news.append({
                        "title": item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"'),
                        "description": item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"'),
                        "time": pub_date.strftime("%Y-%m-%d %H:%M"), "link": item["link"]
                    })
            return filtered_news
        return []
    except: return []

# [복구] gemini-3.1-flash-lite 모델 지정 및 JSON 강제 포맷 적용
def evaluate_top_news(api_key, news_list):
    if not news_list: return []
    try:
        client = genai.Client(api_key=api_key)
        target = news_list[:30]
        prompt_list = "\n".join([f"[{i}] 제목: {n['title']} | 요약: {n['description']}" for i, n in enumerate(target)])
        
        prompt = f"""당신은 날카로운 편집 데스크입니다. 아래 제공된 기사들의 '뉴스 가치(News Value)'를 총점 100점 만점으로 평가하여 가장 점수가 높은 5개의 기사를 선정하세요.
        
        🚨 [평가 기준]
        1. 지역 밀착성 및 파급력: 지역민의 실생활과 경제에 직접적인 영향을 미치는 이슈인가?
        2. 전국적 대중성 및 화제성: 폭발적인 흥미를 갖고 클릭할 만한 기사인가?
        
        반드시 아래 JSON 배열 형식으로만 답변하고, 점수가 높은 순서대로 5개만 담아주세요.
        [
          {{"index": 0, "score": 95, "reason": "폭발적인 조회수 예상"}},
          {{"index": 3, "score": 88, "reason": "지역 현안이면서 전국적 관심 집중"}}
        ]
        
        [오늘의 기사 목록]
        {prompt_list}"""
        
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
        )
        
        # 마크다운 코드 블록 제거 처리 (안전장치)
        raw_text = response.text.strip()
        if raw_text.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
