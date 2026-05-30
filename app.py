import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import email.utils
import streamlit as st
import streamlit.components.v1 as components 
from streamlit_cookies_manager import EncryptedCookieManager # [핵심] 쿠키 암호화 저장 라이브러리

# 구글 최신 AI 라이브러리 도입
from google import genai
from google.genai import types

# ==========================================
# --- 웹페이지 UI 기본 설정 ---
# ==========================================
st.set_page_config(page_title="통합 AI 데스크", page_icon="📝", layout="wide")

# ==========================================
# --- 쿠키 매니저 (자동 로그인 보관용) ---
# ==========================================
# 서버(깃허브)에 파일을 남기지 않고, 접속한 기자의 브라우저에 키를 암호화하여 저장합니다.
cookies = EncryptedCookieManager(
    prefix="kbcdesk", 
    password="kbc_newsroom_master_password_2026" # 암호화/복호화에 쓰이는 마스터키
)
if not cookies.ready():
    # 브라우저에서 쿠키를 읽어올 때까지 0.1초 대기합니다.
    st.stop()

# ==========================================
# --- 세션 상태(Session State) 초기화 ---
# ==========================================
if "api_keys" not in st.session_state:
    st.session_state.api_keys = {
        "naver_id": cookies.get("naver_id", ""),
        "naver_secret": cookies.get("naver_secret", ""),
        "gemini": cookies.get("gemini", "")
    }

if "rules" not in st.session_state:
    st.session_state.rules = {
        "report": """🚨 [필수 준수 규칙]\n발제하는 아이템에 맞춰서 방송용 리포트 기사를 작성합니다. 감정적인 요소를 최대한 절제하고 객관적인 문장을 사용합니다. 방송 기사는 구어체, 존댓말을 기반으로 작성합니다. KBC 광주방송이나 SBS 8시 뉴스에 송출되는 기사들의 양식을 따릅니다. 일반적으로 앵커멘트 2문장과 기사 본문 7~8문장, 인터뷰나 싱크 2개로 작성됩니다. 기사 전체 길이는 2분 안팎에 머물러야 합니다. 주로 기사 초반부에 현장의 문제점이나 사례 등을 보여주고 이후 해당 사안에 대한 분석을 담는 포맷을 선호합니다. 기사에 들어가는 정보는 직접 취재를 해서 제공되기도 하지만 인터넷에 기 보도된 다른 언론사의 기사들을 참고해도 좋습니다.""",
        "briefing": """🚨 [필수 준수 규칙]\n각종 보도자료나 통신매체에 있는 기사를 방송용 단신 기사로 바꾸는 작업을 수행합니다. 제공된 자료를 살펴보고 핵심적인 내용을 3줄로 뽑아서 작성합니다. 첫번째 문장은 리드문장으로 중요한 정보를 간략하게 작성합니다. 두번째 문장은 본문으로, 리드문장에 들어간 정보를 제공한 기관명을 시작으로 육하원칙에 맞게 세부적인 내용을 작성합니다. 세번째 문장은 부가 문장으로 리드와 본문에 담지 못한 추가적인 내용을 담습니다. KBC8뉴스에 나온 단신 기사의 포맷을 참고하면 좋습니다. 14글자 안팎의 방송용 자막, 제목도 함께 제안합니다.""",
        "portal": """🚨 [필수 준수 규칙]\n제공되는 기사를 방송용 포털기사로 다시 작성합니다. 기사의 방식은 전형적인 역피라미드 형태입니다. 첫 리드 문장에 기사 전체의 핵심 내용을 간략하게 담습니다. 방송기사와 같이 구어체로 존댓말을 사용합니다. 기존의 KBC 인터넷용 기사를 참고해서 규칙을 적용하면 좋습니다. 날짜는 오늘, 내일 대신 명시된 날짜를 사용합니다. 날짜는 현재 시점의 경우 일자만 적고 연도와 월은 생략합니다. 다가올 미래 시제일 경우 '오는 00일'로 표기합니다. 매 문장마다 문단을 바꿉니다. 시간을 표시할때 정확하지 않은 경우 뒤에 '쯤'을 붙입니다. 월, 일, 오전, 오후 뒤에는 붙이지 않습니다. 나이는 '마흔아홉살'이 아닌 '49살' 처럼 숫자로 작성합니다. 문장 어미에 '데요'를 쓰지 않습니다. 문장 첫 단어로 '이는'을 쓰지 않습니다. 기존 기사보다 최대한 깔끔하게 표현을 바꿉니다. 감정적인 표현은 최대한 배제합니다. 기사 내 언급된 인물이 직접 한 말은 큰따옴표로 처리합니다. 관련된 기사를 검색해서 추가적인 정보도 추가합니다. 검색해서 정보를 추가한 부분은 볼드체로 표기합니다. 검색했던 근거도 링크로 함께 보여줍니다. 사람들이 많이 클릭하게 할만한 기사의 제목도 2~3개씩 함께 제안합니다."""
    }

if "news_states" not in st.session_state:
    st.session_state.news_states = {}

# --- 원클릭 복사 버튼 생성기 ---
def create_copy_button(text_to_copy):
    js_safe_text = json.dumps(text_to_copy).replace("<", "\\u003c")
    html_code = f"""
    <button id="copy-btn" style="width: 100%; background-color: #4CAF50; color: white; padding: 12px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: bold;" 
    onclick='copyToClipboard()'>
    📋 텍스트 복사하기
    </button>
    <script>
    function copyToClipboard() {{
        const text = {js_safe_text};
        navigator.clipboard.writeText(text).then(function() {{
            alert("텍스트가 복사되었습니다!");
        }}).catch(function(err) {{
            alert("복사에 실패했습니다.");
        }});
    }}
    </script>
    """
    components.html(html_code, height=70)

# --- 1. 기사 본문 스크래핑 함수 ---
def get_article_full_text(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            article_body = soup.find('div', id='dic_area') or soup.find('div', id='newsct_article')
            if article_body: return article_body.get_text(separator=' ', strip=True)
            else: return "ERROR_NOT_NAVER"
        else: return "ERROR_CONNECTION"
    except Exception as e: return f"ERROR: {e}"

# --- 2. 뉴스 수집 공통 함수 ---
def fetch_news(keyword, client_id, client_secret, hours=3):
    enc_text = urllib.parse.quote(keyword)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=100&sort=sim"
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            news_data = response.json()
            filtered_news = []
            now = datetime.now(timezone(timedelta(hours=9)))
            time_limit = now - timedelta(hours=hours)
            for item in news_data.get("items", []):
                pub_date = email.utils.parsedate_to_datetime(item["pubDate"])
                if pub_date >= time_limit and "naver.com" in item["link"]:
                    filtered_news.append({
                        "title": item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"'),
                        "description": item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"'),
                        "time": pub_date.strftime("%Y-%m-%d %H:%M"),
                        "link": item["link"]
                    })
            return filtered_news
        return []
    except Exception: return []

# --- 3. Gemini 뉴스 밸류 측정 함수 (신버전 규격 적용) ---
def evaluate_top_news(api_key, news_list):
    if not news_list:
        return []
        
    try:
        client = genai.Client(api_key=api_key)
        
        target_news = news_list[:30]
        news_text_for_prompt = ""
        for idx, news in enumerate(target_news):
            news_text_for_prompt += f"[{idx}] 제목: {news['title']} | 요약: {news['description']}\n"

        prompt = f"""
        당신은 KBC 보도국의 날카로운 편집 데스크입니다. 아래 제공된 기사들의 '뉴스 가치(News Value)'를 총점 100점 만점으로 평가하여 가장 점수가 높은 5개의 기사를 선정하세요.
        
        🚨 [데스크 평가 패러다임]
        1. 지역 밀착성 및 파급력 (50점 만점): 광주·전남 지역민의 실생활과 경제에 직접적인 영향을 미치는 이슈인가?
        2. 전국적 대중성 및 화제성 (50점 만점): 대한민국 전체 국민이 폭발적인 흥미를 갖고 클릭할 만한 기사인가?
        
        반드시 아래 JSON 배열 형식으로만 답변하고, 점수가 높은 순서대로 5개만 담아주세요.
        [
          {{"index": 0, "score": 95, "reason": "전국적인 공분을 산 대형 사건으로 폭발적인 조회수 예상"}},
          {{"index": 5, "score": 88, "reason": "광주·전남 지역 현안이면서 전국적 관심도 집중됨"}}
        ]
        
        [오늘의 기사 목록]
        {news_text_for_prompt}
        """

        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        scored_data = json.loads(response.text)
        
        top_picks = []
        for item in scored_data:
            idx = item.get("index")
            if 0 <= idx < len(target_news):
                selected_news = target_news[idx].copy()
                selected_news["ai_score"] = item.get("score", 0)
                selected_news["ai_reason"] = item.get("reason", "")
                top_picks.append(selected_news)
                
        return top_picks
    except Exception as e:
        print(f"밸류 측정 에러: {e}")
        return []

# --- 4. Gemini 기사 작성 함수 ---
def generate_gemini_article(api_key, title, content_text, format_type):
    try:
        client = genai.Client(api_key=api_key)
        system_msg = "당신은 보도국의 베테랑 데스크입니다. 감정을 배제하고 객관적이고 정확한 방송 뉴스를 제작합니다."
        
        rule_map = {
            "리포트 작성": st.session_state.rules["report"],
            "단신 작성": st.session_state.rules["briefing"],
            "포털 기사 작성": st.session_state.rules["portal"]
        }
        
        user_msg = f"[작업명: {format_type}]\n제공된 원본 기사를 바탕으로 아래 🚨필수 준수 규칙🚨에 맞춰 재작성하세요.\n\n{rule_map.get(format_type, '')}\n\n[원본 제목]: {title}\n[원본 기사]: {content_text}"
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=user_msg,
            config=types.GenerateContentConfig(system_instruction=system_msg, temperature=0.2)
        )
        return response.text
    except Exception as e: return f"오류 발생: {e}"

# --- 화면 렌더링 도우미 함수 ---
def render_news_list(news_list, tab_key):
    if not news_list:
        st.warning("기사가 없습니다.")
        return
    for idx, news in enumerate(news_list):
        item_key = f"{tab_key}_{idx}"
        if item_key not in st.session_state.news_states:
            st.session_state.news_states[item_key] = {"generated_text": ""}
        if "ai_score" in news:
            st.markdown(f"### 🏆 Top {idx+1}. [{news['title']}]({news['link']})")
            st.info(f"**💡 AI 데스크 평점: {news['ai_score']}점** | {news['ai_reason']}")
        else: st.markdown(f"#### [{news['title']}]({news['link']})")
        
        st.caption(f"🕒 보도시간: {news['time']}")
        st.write(f"요약: {news['description']}")
        
        with st.expander("✨ 이 기사를 커스텀 양식으로 자동 변환하기"):
            col1, col2, col3 = st.columns(3)
            def process_article(format_type):
                with st.spinner('원본 기사 본문을 스크랩 중입니다...'):
                    full_text = get_article_full_text(news['link'])
                    content_to_use = news['description'] if "ERROR" in full_text else full_text
                with st.spinner(f'제미나이가 [{format_type}] 작업 중입니다...'):
                    result = generate_gemini_article(st.session_state.api_keys['gemini'], news['title'], content_to_use, format_type)
                    st.session_state.news_states[item_key]["generated_text"] = result
            
            if col1.button("🎤 리포트", key=f"rep_{item_key}"): process_article("리포트 작성")
            if col2.button("📃 단신", key=f"brf_{item_key}"): process_article("단신 작성")
            if col3.button("💻 포털", key=f"por_{item_key}"): process_article("포털 기사 작성")
            
            if st.session_state.news_states[item_key]["generated_text"]:
                st.markdown("---")
                st.write(st.session_state.news_states[item_key]["generated_text"])
                create_copy_button(st.session_state.news_states[item_key]["generated_text"])
        st.markdown("---")

# ==========================================
# --- 웹페이지 화면 구성 (스트림릿 메인) ---
# ==========================================
st.sidebar.title("📺 AI 뉴스룸")

api_ready = all([st.session_state.api_keys['naver_id'], st.session_state.api_keys['naver_secret'], st.session_state.api_keys['gemini']])

if api_ready:
    menu_options = ("⚙️ 환경 설정 (로그인 및 규칙)", "📝 통합 AI 데스크", "✍️ 직접 입력 변환 데스크")
else:
    menu_options = ("⚙️ 환경 설정 (로그인 및 규칙)",)

page = st.sidebar.radio("메뉴를 선택하세요:", menu_options)
st.sidebar.markdown("---")

if page == "⚙️ 환경 설정 (로그인 및 규칙)":
    st.markdown("### ⚙️ 환경 설정 및 로그인")
    st.write("개인 API 키를 입력하고 본인만의 작성 규칙을 세팅하세요. 입력한 정보는 브라우저를 닫기 전까지 안전하게 유지됩니다.")
    
    st.subheader("🔑 1. API 키 로그인")
    st.info("💡 처음 오셨나요? 아래 링크에서 무료로 API 키를 발급받으실 수 있습니다.\n* [🔗 네이버 검색 API 발급받기](https://developers.naver.com/apps/#/register)\n* [🔗 구글 Gemini API 발급받기](https://aistudio.google.com/app/apikey)")
    
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.api_keys['naver_id'] = st.text_input("Naver Client ID", value=st.session_state.api_keys['naver_id'], type="password")
        st.session_state.api_keys['naver_secret'] = st.text_input("Naver Client Secret", value=st.session_state.api_keys['naver_secret'], type="password")
    with col2:
        st.session_state.api_keys['gemini'] = st.text_input("Gemini API Key", value=st.session_state.api_keys['gemini'], type="password")
    
    st.markdown("<br>", unsafe_allow_html=True)
    # [수정] 파일 저장 대신 쿠키 저장 방식 안내로 문구 변경
    save_login_checked = st.checkbox("💾 로그인 정보 계속 유지하기 (내 웹 브라우저 쿠키에 암호화하여 안전하게 보관)", value=True)
    
    st.markdown("---")
    
    st.subheader("📝 2. 커스텀 프롬프트 (작성 규칙 설정)")
    st.write("기본 설정된 규칙을 본인의 입맛에 맞게 수정해 보세요. (규칙은 브라우저 탭을 닫기 전까지 유지됩니다)")
    with st.expander("🎤 리포트 작성 규칙", expanded=False):
        st.session_state.rules['report'] = st.text_area("리포트 가이드라인", value=st.session_state.rules['report'], height=200)
    with st.expander("📃 단신 작성 규칙", expanded=False):
        st.session_state.rules['briefing'] = st.text_area("단신 가이드라인", value=st.session_state.rules['briefing'], height=200)
    with st.expander("💻 포털 기사 작성 규칙", expanded=False):
        st.session_state.rules['portal'] = st.text_area("포털 가이드라인", value=st.session_state.rules['portal'], height=200)
    
    if st.button("저장 및 시스템 시작하기", use_container_width=True):
        if save_login_checked:
            # 브라우저 쿠키에 안전하게 암호화하여 저장
            cookies["naver_id"] = st.session_state.api_keys['naver_id']
            cookies["naver_secret"] = st.session_state.api_keys['naver_secret']
            cookies["gemini"] = st.session_state.api_keys['gemini']
            cookies.save()
        else:
            # 체크 해제 시 쿠키 비우기
            cookies["naver_id"] = ""
            cookies["naver_secret"] = ""
            cookies["gemini"] = ""
            cookies.save()

        if all([st.session_state.api_keys['naver_id'], st.session_state.api_keys['naver_secret'], st.session_state.api_keys['gemini']]): 
            st.success("✅ 로그인이 완료되었습니다! 왼쪽 메뉴에서 데스크 업무를 시작하세요.")
            st.rerun() 
        else: 
            st.error("⚠️ 세 가지 API 키를 모두 입력해야 시스템을 사용할 수 있습니다.")

elif not api_ready:
    st.warning("🚨 [⚙️ 환경 설정] 메뉴로 이동하여 본인의 API 키를 먼저 입력해 주세요.")

elif page == "📝 통합 AI 데스크":
    col_title, col_btn = st.columns([8, 2])
    with col_title:
        st.markdown("### 📝 통합 AI 데스크")
    
    @st.cache_data(ttl=600)
    def load_all_news(n_id, n_sec):
        gj, jn, pol = fetch_news("광주", n_id, n_sec), fetch_news("전남", n_id, n_sec), fetch_news("정치", n_id, n_sec)
        acc, acc2, red = fetch_news("사고", n_id, n_sec), fetch_news("사건", n_id, n_sec), fetch_news("속보", n_id, n_sec)
        local = gj + jn
        national = list({n['link']: n for n in (pol + acc + acc2 + red)}.values())
        national.sort(key=lambda x: x['time'], reverse=True)
        return local, national

    with col_btn:
        if st.button("🔄 최신 기사 새로고침", use_container_width=True):
            load_all_news.clear()
            st.rerun()
    st.markdown("---")

    with st.spinner("최신 기사를 수집하고 있습니다..."):
        local_news, national_news = load_all_news(st.session_state.api_keys['naver_id'], st.session_state.api_keys['naver_secret'])

    st.markdown("#### 🏆 추천 TOP 5")
    
    if 'top_picks' not in st.session_state: st.session_state.top_picks = []
    if st.button("🔍 AI 데스크 픽 분석하기 (로딩 약 5~10초)"):
        with st.spinner("수집된 기사들의 뉴스 밸류를 측정하고 있습니다..."):
            combined_pool = local_news[:20] + national_news[:20]
            st.session_state.top_picks = evaluate_top_news(st.session_state.api_keys['gemini'], combined_pool)

    if st.session_state.top_picks:
        with st.container(): render_news_list(st.session_state.top_picks, "top5")
    else: st.info("상단의 '분석하기' 버튼을 눌러주세요.")
    st.markdown("---")

    tab1, tab2 = st.tabs(["📍 지역 뉴스", "🚨 주요 정치/사건 뉴스"])
    with tab1: render_news_list(local_news, "local")
    with tab2: render_news_list(national_news, "national")

elif page == "✍️ 직접 입력 변환 데스크":
    st.markdown("### ✍️ 직접 입력 변환 데스크")
    st.write("타사 기사나 보도자료를 붙여넣어 즉시 양식으로 변환할 수 있습니다.")
    st.markdown("---")

    manual_title = st.text_input("📌 기사 제목 (선택)", placeholder="기사 제목을 입력하세요")
    manual_content = st.text_area("📝 기사 본문 입력", height=300, placeholder="변환할 텍스트를 붙여넣으세요.")
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    def process_manual_article(format_type):
        if not manual_content.strip(): return st.error("⚠️ 먼저 변환할 텍스트를 입력해 주세요.")
        with st.spinner(f'제미나이가 [{format_type}] 포맷으로 작성 중입니다...'):
            title = manual_title if manual_title.strip() else "직접 입력한 기사"
            result = generate_gemini_article(st.session_state.api_keys['gemini'], title, manual_content, format_type)
            st.session_state.manual_generated_text = result
            st.write(result)

    if col1.button("🎤 리포트로 변환", use_container_width=True): process_manual_article("리포트 작성")
    if col2.button("📃 단신으로 변환", use_container_width=True): process_manual_article("단신 작성")
    if col3.button("💻 포털 기사로 변환", use_container_width=True): process_manual_article("포털 기사 작성")

    if 'manual_generated_text' in st.session_state and st.session_state.manual_generated_text:
        st.markdown("---")
        create_copy_button(st.session_state.manual_generated_text)
