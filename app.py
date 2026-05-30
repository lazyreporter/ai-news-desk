import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import email.utils
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
# --- 세션 및 기본값 초기화 ---
# ==========================================
default_rules = {
    "report": "🚨 [필수 준수 규칙]\n방송용 리포트 기사를 작성합니다. 객관적인 문장과 구어체, 존댓말을 사용하세요. KBC 광주방송이나 SBS 8시 뉴스에 송출되는 기사들의 양식을 따릅니다. 주로 기사 초반부에 현장의 문제점이나 사례 등을 보여주고 이후 해당 사안에 대한 분석을 담는 포맷을 선호합니다.",
    "briefing": "🚨 [필수 준수 규칙]\n방송용 단신 기사로 바꿉니다. 제공된 자료를 살펴보고 핵심적인 내용을 3줄로 뽑아서 작성합니다. 육하원칙에 맞게 세부적인 내용을 작성하며, 14글자 안팎의 방송용 자막과 제목도 함께 제안합니다.",
    "portal": "🚨 [필수 준수 규칙]\n방송용 포털기사로 다시 작성합니다. 전형적인 역피라미드 형태이며, 날짜는 현재 시점의 경우 일자만 적고 연도와 월은 생략합니다. 다가올 미래 시제일 경우 '오는 00일'로 표기합니다. 사람들이 많이 클릭하게 할만한 기사의 제목도 2~3개씩 함께 제안합니다."
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

def evaluate_top_news(api_key, news_list):
    if not news_list: return []
    try:
        client = genai.Client(api_key=api_key)
        target = news_list[:30]
        prompt_list = "\n".join([f"[{i}] 제목: {n['title']} | 요약: {n['description']}" for i, n in enumerate(target)])
        prompt = f"당신은 편집 데스크입니다. 아래 기사들의 '뉴스 가치'를 평가해 가장 높은 5개를 선정하세요.\n[오늘의 기사 목록]\n{prompt_list}"
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
        )
        top_picks = []
        for item in json.loads(response.text):
            idx = item.get("index")
            if 0 <= idx < len(target):
                n = target[idx].copy()
                n.update({"ai_score": item.get("score", 0), "ai_reason": item.get("reason", "")})
                top_picks.append(n)
        return top_picks
    except: return []

def generate_gemini_article(api_key, title, content_text, format_type):
    try:
        client = genai.Client(api_key=api_key)
        rule_map = {"리포트 작성": st.session_state.rules["report"], "단신 작성": st.session_state.rules["briefing"], "포털 기사 작성": st.session_state.rules["portal"]}
        msg = f"[작업명: {format_type}]\n아래 규칙에 맞춰 재작성하세요.\n\n{rule_map.get(format_type, '')}\n\n[원본 제목]: {title}\n[원본 기사]: {content_text}"
        res = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=msg,
            config=types.GenerateContentConfig(system_instruction="당신은 보도국 베테랑 데스크입니다.", temperature=0.2)
        )
        return res.text
    except Exception as e: return f"오류 발생: {e}"

def render_news_list(news_list, tab_key):
    if not news_list: return st.warning("기사가 없습니다.")
    for idx, news in enumerate(news_list):
        item_key = f"{tab_key}_{idx}"
        if item_key not in st.session_state.news_states: st.session_state.news_states[item_key] = {"generated_text": ""}
        if "ai_score" in news:
            st.markdown(f"### 🏆 Top {idx+1}. [{news['title']}]({news['link']})")
            st.info(f"**💡 AI 평점: {news['ai_score']}점** | {news['ai_reason']}")
        else: st.markdown(f"#### [{news['title']}]({news['link']})")
        st.write(f"요약: {news['description']}")
        
        with st.expander("✨ 이 기사를 커스텀 양식으로 자동 변환하기"):
            c1, c2, c3 = st.columns(3)
            def process(f_type):
                with st.spinner('작업 중입니다...'):
                    text = get_article_full_text(news['link'])
                    content = news['description'] if "ERROR" in text else text
                    st.session_state.news_states[item_key]["generated_text"] = generate_gemini_article(st.session_state.api_keys['gemini'], news['title'], content, f_type)
            if c1.button("🎤 리포트", key=f"r_{item_key}"): process("리포트 작성")
            if c2.button("📃 단신", key=f"b_{item_key}"): process("단신 작성")
            if c3.button("💻 포털", key=f"p_{item_key}"): process("포털 기사 작성")
            
            if st.session_state.news_states[item_key]["generated_text"]:
                st.markdown("---")
                st.write(st.session_state.news_states[item_key]["generated_text"])
                create_copy_button(st.session_state.news_states[item_key]["generated_text"])
        st.markdown("---")

# ==========================================
# --- 웹페이지 화면 구성 ---
# ==========================================
st.sidebar.title("📺 AI 뉴스룸")

api_ready = all([st.session_state.api_keys['naver_id'], st.session_state.api_keys['naver_secret'], st.session_state.api_keys['gemini']])
menu_options = ("⚙️ 환경 설정 (로그인 및 규칙)", "📝 통합 AI 데스크", "✍️ 직접 입력 변환 데스크") if api_ready else ("⚙️ 환경 설정 (로그인 및 규칙)",)
page = st.sidebar.radio("메뉴를 선택하세요:", menu_options)
st.sidebar.markdown("---")

if page == "⚙️ 환경 설정 (로그인 및 규칙)":
    st.markdown("### ⚙️ 개인 환경 설정")
    st.write("입력하신 모든 정보는 외부 서버가 아닌 **사용 중인 브라우저에만 암호화되어 안전하게 저장**됩니다.")
    st.markdown("---")

    st.subheader("🔑 1. API 키 설정")
    st.info("💡 아래 링크에서 무료로 API 키를 발급받으실 수 있습니다.\n* [🔗 네이버 검색 API 발급](https://developers.naver.com/apps/#/register)\n* [🔗 구글 Gemini API 발급](https://aistudio.google.com/app/apikey)")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state.api_keys['naver_id'] = st.text_input("Naver Client ID", value=st.session_state.api_keys['naver_id'], type="password")
        st.session_state.api_keys['naver_secret'] = st.text_input("Naver Client Secret", value=st.session_state.api_keys['naver_secret'], type="password")
    with c2:
        st.session_state.api_keys['gemini'] = st.text_input("Gemini API Key", value=st.session_state.api_keys['gemini'], type="password")
    
    st.markdown("---")
    st.subheader("📝 2. 커스텀 프롬프트 (작성 규칙 설정)")
    st.write("기본 설정된 규칙을 본인의 입맛에 맞게 수정해 보세요.")
    with st.expander("🎤 리포트 작성 규칙", expanded=False):
        st.session_state.rules['report'] = st.text_area("리포트 가이드라인", value=st.session_state.rules['report'], height=150)
    with st.expander("📃 단신 작성 규칙", expanded=False):
        st.session_state.rules['briefing'] = st.text_area("단신 가이드라인", value=st.session_state.rules['briefing'], height=150)
    with st.expander("💻 포털 기사 작성 규칙", expanded=False):
        st.session_state.rules['portal'] = st.text_area("포털 가이드라인", value=st.session_state.rules['portal'], height=150)

    st.markdown("---")
    st.subheader("🔍 3. 커스텀 기사 수집 키워드")
    st.write("본인의 출입처나 관심사에 맞게 수집 키워드를 자유롭게 변경하세요. (여러 개일 경우 쉼표로 구분)")
    kw_col1, kw_col2 = st.columns(2)
    with kw_col1:
        st.session_state.keywords['local'] = st.text_input("📍 첫 번째 탭 (예: 광주, 전남)", value=st.session_state.keywords['local'])
    with kw_col2:
        st.session_state.keywords['national'] = st.text_input("🚨 두 번째 탭 (예: 정치, 사고, 속보)", value=st.session_state.keywords['national'])
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💾 모든 설정을 내 PC(브라우저)에 안전하게 저장하기", use_container_width=True):
        if all([st.session_state.api_keys['naver_id'], st.session_state.api_keys['naver_secret'], st.session_state.api_keys['gemini']]):
            # 브라우저 쿠키에 모든 설정 내용 업데이트
            cookies["naver_id"] = st.session_state.api_keys['naver_id']
            cookies["naver_secret"] = st.session_state.api_keys['naver_secret']
            cookies["gemini"] = st.session_state.api_keys['gemini']
            cookies["rule_report"] = st.session_state.rules['report']
            cookies["rule_briefing"] = st.session_state.rules['briefing']
            cookies["rule_portal"] = st.session_state.rules['portal']
            cookies["kw_local"] = st.session_state.keywords['local']
            cookies["kw_national"] = st.session_state.keywords['national']
            cookies.save()
            st.success("✅ 저장이 완료되었습니다! 브라우저를 껐다 켜도 현재 세팅이 그대로 유지됩니다.")
            st.rerun()
        else: 
            st.error("⚠️ 세 가지 API 키를 모두 입력해야 시스템을 사용할 수 있습니다.")

elif page == "📝 통합 AI 데스크":
    col_t, col_b = st.columns([8, 2])
    with col_t: st.markdown("### 📝 통합 AI 데스크")
    
    @st.cache_data(ttl=600)
    def load_all_news(n_id, n_sec, local_kws, national_kws):
        local_list = [k.strip() for k in local_kws.split(",") if k.strip()]
        national_list = [k.strip() for k in national_kws.split(",") if k.strip()]
        
        loc_news = []
        for kw in local_list:
            loc_news.extend(fetch_news(kw, n_id, n_sec))
            
        nat_news = []
        for kw in national_list:
            nat_news.extend(fetch_news(kw, n_id, n_sec))
            
        loc_news = list({n['link']: n for n in loc_news}.values())
        loc_news.sort(key=lambda x: x['time'], reverse=True)
        
        nat_news = list({n['link']: n for n in nat_news}.values())
        nat_news.sort(key=lambda x: x['time'], reverse=True)
        
        return loc_news, nat_news

    with col_b:
        if st.button("🔄 최신 기사 새로고침"):
            load_all_news.clear()
            st.rerun()

    with st.spinner("최신 기사 수집 중..."):
        loc, nat = load_all_news(
            st.session_state.api_keys['naver_id'], 
            st.session_state.api_keys['naver_secret'],
            st.session_state.keywords['local'],
            st.session_state.keywords['national']
        )

    if 'top_picks' not in st.session_state: st.session_state.top_picks = []
    if st.button("🔍 AI 데스크 픽 분석하기 (로딩 약 5~10초)"):
        with st.spinner("뉴스 밸류 측정 중..."): st.session_state.top_picks = evaluate_top_news(st.session_state.api_keys['gemini'], loc[:20] + nat[:20])

    if st.session_state.top_picks: render_news_list(st.session_state.top_picks, "top")
    st.markdown("---")
    
    tab_name_1 = "📍 " + st.session_state.keywords['local'][:15] + ("..." if len(st.session_state.keywords['local']) > 15 else "")
    tab_name_2 = "🚨 " + st.session_state.keywords['national'][:15] + ("..." if len(st.session_state.keywords['national']) > 15 else "")
    
    t1, t2 = st.tabs([tab_name_1, tab_name_2])
    with t1: render_news_list(loc, "loc")
    with t2: render_news_list(nat, "nat")

elif page == "✍️ 직접 입력 변환 데스크":
    st.markdown("### ✍️ 직접 입력 변환 데스크")
    m_title = st.text_input("📌 기사 제목")
    m_content = st.text_area("📝 기사 본문 입력", height=200)
    c1, c2, c3 = st.columns(3)
    def p_manual(f_type):
        if not m_content.strip(): return st.error("내용을 입력하세요.")
        with st.spinner('작성 중...'):
            res = generate_gemini_article(st.session_state.api_keys['gemini'], m_title or "직접 입력", m_content, f_type)
            st.session_state.manual_generated_text = res
            st.write(res)
    if c1.button("🎤 리포트"): p_manual("리포트 작성")
    if c2.button("📃 단신"): p_manual("단신 작성")
    if c3.button("💻 포털"): p_manual("포털 기사 작성")
    if 'manual_generated_text' in st.session_state: create_copy_button(st.session_state.manual_generated_text)
