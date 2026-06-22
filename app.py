import json
import urllib.parse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import email.utils
import time
import os
import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components 

from github import Github, Auth

OPENROUTER_MODEL = "openai/gpt-oss-120b:free"  # GPT OSS 120B 무료 버전 (OpenRouter)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def call_openrouter(api_key, system_prompt, user_prompt, temperature=0.2, response_json=False):
    """OpenRouter API 공통 호출 함수"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://kbc-ai-newsroom.streamlit.app",
        "X-Title": "KBC AI Newsroom"
    }
    body = {
        "model": OPENROUTER_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }
    if response_json:
        body["response_format"] = {"type": "json_object"}
    
    resp = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

st.set_page_config(page_title="통합 AI 데스크", page_icon="📝", layout="wide")

# ==========================================
# --- 깃허브 동기화 및 DB/API 비밀키 설정 ---
# ==========================================
EXCEL_FILE = "users.xlsx"
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
REPO_NAME = st.secrets["REPO_NAME"]

# [추가됨] 시스템 공통으로 사용할 네이버 API 키
NAVER_ID = st.secrets["NAVER_ID"]
NAVER_SECRET = st.secrets["NAVER_SECRET"]

# [규칙 원본 100% 보존]
DEFAULT_RULES = {
    "report": "🚨 [필수 준수 규칙]\n발제하는 아이템에 맞춰서 방송용 리포트 기사를 작성합니다. 감정적인 요소를 최대한 절제하고 객관적인 문장을 사용합니다. 방송 기사는 구어체, 존댓말을 기반으로 작성합니다. KBC 광주방송이나 SBS 8시 뉴스에 송출되는 기사들의 양식을 따릅니다. 일반적으로 앵커멘트 2문장과 기사 본문 7~8문장, 인터뷰나 싱크 2개로 작성됩니다. 기사 전체 길이는 2분 안팎에 머물러야 합니다. 주로 기사 초반부에 현장의 문제점이나 사례 등을 보여주고 이후 해당 사안에 대한 분석을 담는 포맷을 선호합니다. 기사에 들어가는 정보는 직접 취재를 해서 제공되기도 하지만 인터넷에 기 보도된 다른 언론사의 기사들을 참고해도 좋습니다.",
    "briefing": "🚨 [필수 준수 규칙]\n각종 보도자료나 통신매체에 있는 기사를 방송용 단신 기사로 바꾸는 작업을 수행합니다. 제공된 자료를 살펴보고 핵심적인 내용을 3줄로 뽑아서 작성합니다. 첫번째 문장은 리드문장으로 중요한 정보를 간략하게 작성합니다. 두번째 문장은 본문으로, 리드문장에 들어간 정보를 제공한 기관명을 시작으로 육하원칙에 맞게 세부적인 내용을 작성합니다. 세번째 문장은 부가 문장으로 리드와 본문에 담지 못한 추가적인 내용을 담습니다. KBC8뉴스에 나온 단신 기사의 포맷을 참고하면 좋습니다. 14글자 안팎의 방송용 자막, 제목도 함께 제안합니다.",
    "portal": "🚨 [필수 준수 규칙]\n제공되는 기사를 방송용 포털기사로 다시 작성합니다. 기사의 방식은 전형적인 역피라미드 형태입니다. 첫 리드 문장에 기사 전체의 핵심 내용을 간략하게 담습니다. 방송기사와 같이 구어체로 존댓말을 사용합니다. 기존의 KBC 인터넷용 기사를 참고해서 규칙을 적용하면 좋습니다. 날짜는 오늘, 내일 대신 명시된 날짜를 사용합니다. 날짜는 현재 시점의 경우 일자만 적고 연도와 월은 생략합니다. 다가올 미래 시제일 경우 '오는 00일'로 표기합니다. 매 문장마다 문단을 바꿉니다. 시간을 표시할때 정확하지 않은 경우 뒤에 '쯤'을 붙입니다. 월, 일, 오전, 오후 뒤에는 붙이지 않습니다. 나이는 '마흔아홉살'이 아닌 '49살' 처럼 숫자로 작성합니다. 문장 어미에 '데요'를 쓰지 않습니다. 문장 첫 단어로 '이는'을 쓰지 않습니다. 기존 기사보다 최대한 깔끔하게 표현을 바꿉니다. 감정적인 표현은 최대한 배제합니다. 기사 내 언급된 인물이 직접 한 말은 큰따옴표로 처리합니다. 관련된 기사를 검색해서 추가적인 정보도 추가합니다. 검색해서 정보를 추가한 부분은 볼드체로 표기합니다. 검색했던 근거도 링크로 함께 보여줍니다. 사람들이 많이 클릭하게 할만한 기사의 제목도 2~3개씩 함께 제안합니다."
}

def sync_to_github(commit_message):
    try:
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        repo = g.get_repo(REPO_NAME)
        with open(EXCEL_FILE, "rb") as f:
            content = f.read()
        try:
            file = repo.get_contents(EXCEL_FILE)
            repo.update_file(EXCEL_FILE, commit_message, content, file.sha)
        except:
            repo.create_file(EXCEL_FILE, commit_message, content)
    except Exception as e:
        print(f"GitHub 동기화 에러: {e}")
        st.toast(f"⚠️ 깃허브 동기화 실패 (설정을 확인하세요): {e}")

@st.cache_resource
def pull_from_github():
    try:
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        repo = g.get_repo(REPO_NAME)
        file_content = repo.get_contents(EXCEL_FILE)
        with open(EXCEL_FILE, "wb") as f:
            f.write(base64.b64decode(file_content.content))
    except:
        pass

pull_from_github()

def init_db():
    if not os.path.exists(EXCEL_FILE):
        df = pd.DataFrame(columns=[
            "user_id", "password", "naver_id", "naver_secret", "openrouter_key",
            "rule_report", "rule_briefing", "rule_portal",
            "kw_local", "kw_national"
        ])
        df.to_excel(EXCEL_FILE, index=False)
        sync_to_github("초기 DB 파일 생성")

def register_user(u_id, pw, n_id, n_sec, g_key):
    df = pd.read_excel(EXCEL_FILE)
    if u_id in df['user_id'].astype(str).values:
        return False
    
    new_row = {
        "user_id": str(u_id), "password": str(pw), 
        "naver_id": str(n_id), "naver_secret": str(n_sec), "openrouter_key": str(g_key),
        "rule_report": DEFAULT_RULES['report'],
        "rule_briefing": DEFAULT_RULES['briefing'],
        "rule_portal": DEFAULT_RULES['portal'],
        "kw_local": "광주, 전남",
        "kw_national": "정치, 사고, 사건, 속보"
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_excel(EXCEL_FILE, index=False)
    sync_to_github(f"신규 유저 등록: {u_id}")
    return True

def login_user(u_id, pw):
    df = pd.read_excel(EXCEL_FILE)
    user_row = df[(df['user_id'].astype(str) == str(u_id)) & (df['password'].astype(str) == str(pw))]
    if not user_row.empty:
        return user_row.iloc[0].to_dict()
    return None

def update_user_settings(u_id, r_report, r_briefing, r_portal, k_local, k_national):
    df = pd.read_excel(EXCEL_FILE)
    idx = df.index[df['user_id'].astype(str) == str(u_id)].tolist()
    if idx:
        row_idx = idx[0]
        df.at[row_idx, 'rule_report'] = r_report
        df.at[row_idx, 'rule_briefing'] = r_briefing
        df.at[row_idx, 'rule_portal'] = r_portal
        df.at[row_idx, 'kw_local'] = k_local
        df.at[row_idx, 'kw_national'] = k_national
        df.to_excel(EXCEL_FILE, index=False)
        sync_to_github(f"유저 설정 업데이트: {u_id}")
        return True
    return False

init_db()

# ==========================================
# --- 세션 상태 초기화 및 접근 통제 ---
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_info = None

if "news_states" not in st.session_state:
    st.session_state.news_states = {}

if not st.session_state.logged_in:
    st.sidebar.title("📺 AI 뉴스룸")
    st.sidebar.error("🔒 로그인이 필요합니다.")
    
    st.title("🔒 KBC AI 뉴스룸 로그인")
    st.write("서비스를 이용하려면 로그인을 하거나 회원가입을 진행해 주세요.")
    st.markdown("---")
    
    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])
    
    with tab_login:
        st.subheader("기존 계정 로그인")
        with st.form("login_form"):
            login_id = st.text_input("아이디", key="login_id")
            login_pw = st.text_input("비밀번호", type="password", key="login_pw")
            submitted = st.form_submit_button("로그인", use_container_width=True)
        if submitted:
            user_data = login_user(login_id, login_pw)
            if user_data:
                st.session_state.logged_in = True
                st.session_state.user_info = user_data
                st.success("✅ 로그인 성공! 통합 데스크로 이동합니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.error("🚨 로그인 실패: 아이디 또는 비밀번호가 일치하지 않습니다.")
                
    with tab_signup:
        st.subheader("새 계정 회원가입")
        st.write("회원가입 정보는 서버 내 엑셀 파일에 안전하게 저장됩니다.")
        reg_id = st.text_input("새 아이디")
        reg_pw = st.text_input("새 비밀번호", type="password")
        
        # OpenRouter API 발급 링크
        st.info("💡 동료 기자의 원활한 이용을 위해 아래 링크에서 무료로 OpenRouter API 키를 발급받으시면 됩니다.\n* [🔗 OpenRouter API 키 발급](https://openrouter.ai/keys)")
        
        reg_openrouter = st.text_input("OpenRouter API Key", type="password")
        
        if st.button("회원가입 및 저장", use_container_width=True):
            if not all([reg_id, reg_pw, reg_openrouter]):
                st.error("⚠️ 모든 빈칸을 빠짐없이 입력해 주세요.")
            else:
                with st.spinner("엑셀 DB 생성 및 클라우드 동기화 중..."):
                    success = register_user(reg_id, reg_pw, "공통사용", "공통사용", reg_openrouter)
                if success:
                    st.success("🎉 회원가입이 완료되었습니다! 엑셀 파일에 저장되었습니다. 이제 왼쪽 탭에서 로그인해 주세요.")
                else:
                    st.error("🚨 이미 존재하는 아이디입니다. 다른 아이디를 사용해 주세요.")
                    
    st.stop()


# ==========================================
# --- 원클릭 복사 버튼 및 공통 함수 모음 ---
# ==========================================
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

def evaluate_top_news_by_category(api_key, news_list, category_label, eval_criteria):
    if not news_list: return []
    try:
        target = news_list[:20]
        prompt_list = "\n".join([f"[{i}] 제목: {n['title']} | 요약: {n['description']}" for i, n in enumerate(target)])
        
        system_prompt = "당신은 날카로운 편집 데스크입니다. 반드시 JSON 형식으로만 응답하세요."
        user_prompt = f"""아래 제공된 기사들의 '뉴스 가치(News Value)'를 총점 100점 만점으로 평가하여 가장 점수가 높은 5개의 기사를 선정하세요.

🚨 [평가 기준 - {category_label}]
{eval_criteria}

반드시 아래 JSON 형식으로만 답변하고, 점수가 높은 순서대로 5개만 담아주세요.
{{"picks": [{{"index": 0, "score": 95, "reason": "폭발적인 조회수 예상"}}, {{"index": 3, "score": 88, "reason": "핵심 현안으로 주목도 높음"}}]}}

[오늘의 기사 목록]
{prompt_list}"""
        
        raw_text = call_openrouter(api_key, system_prompt, user_prompt, temperature=0.2, response_json=True)
        
        raw_text = raw_text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        
        parsed = json.loads(raw_text.strip())
        # "picks" 키가 있으면 꺼내고, 없으면 리스트 자체로 처리
        scored_data = parsed.get("picks", parsed) if isinstance(parsed, dict) else parsed
        
        top_picks = []
        for item in scored_data:
            idx = item.get("index")
            if idx is not None and 0 <= idx < len(target):
                n = target[idx].copy()
                n.update({"ai_score": item.get("score", 0), "ai_reason": item.get("reason", "")})
                top_picks.append(n)
        return top_picks
    except Exception as e:
        st.error(f"픽 분석 중 오류가 발생했습니다: {e}")
        return []

def generate_article(api_key, title, content_text, format_type):
    try:
        rule_map = {
            "리포트 작성": st.session_state.user_info["rule_report"], 
            "단신 작성": st.session_state.user_info["rule_briefing"], 
            "포털 기사 작성": st.session_state.user_info["rule_portal"]
        }
        system_prompt = "당신은 보도국 베테랑 데스크입니다."
        user_prompt = f"[작업명: {format_type}]\n아래 규칙에 맞춰 재작성하세요.\n\n{rule_map.get(format_type, '')}\n\n[원본 제목]: {title}\n[원본 기사]: {content_text}"
        return call_openrouter(api_key, system_prompt, user_prompt, temperature=0.2)
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
                    st.session_state.news_states[item_key]["generated_text"] = generate_article(
                        st.session_state.user_info['openrouter_key'], news['title'], content, f_type
                    )
            if c1.button("🎤 리포트", key=f"r_{item_key}"): process("리포트 작성")
            if c2.button("📃 단신", key=f"b_{item_key}"): process("단신 작성")
            if c3.button("💻 포털", key=f"p_{item_key}"): process("포털 기사 작성")
            
            if st.session_state.news_states[item_key]["generated_text"]:
                st.markdown("---")
                st.write(st.session_state.news_states[item_key]["generated_text"])
                create_copy_button(st.session_state.news_states[item_key]["generated_text"])
        st.markdown("---")

# ==========================================
# --- 메인 화면 (로그인 통과 시 노출) ---
# ==========================================
st.sidebar.title(f"📺 AI 뉴스룸 ({st.session_state.user_info['user_id']}님)")
menu_options = ["📝 통합 AI 데스크", "✍️ 직접 입력 변환 데스크", "⚙️ 환경설정"]
page = st.sidebar.radio("메뉴를 선택하세요:", menu_options)

st.sidebar.markdown("---")
if st.sidebar.button("로그아웃", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.user_info = None
    st.rerun()

if page == "📝 통합 AI 데스크":
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
        if st.button("🔄 최신 기사 새로고침", use_container_width=True):
            load_all_news.clear()
            st.rerun()

    with st.spinner("사용자 키워드로 최신 기사를 수집하고 있습니다..."):
        # [수정됨] 개인별 네이버 키 대신, 시스템 공통 네이버 API 키를 사용하여 기사를 수집합니다.
        loc, nat = load_all_news(
            NAVER_ID, 
            NAVER_SECRET,
            st.session_state.user_info['kw_local'],
            st.session_state.user_info['kw_national']
        )

    if 'top_picks_local' not in st.session_state: st.session_state.top_picks_local = []
    if 'top_picks_national' not in st.session_state: st.session_state.top_picks_national = []
    
    if st.button("🔍 AI 데스크 픽 분석하기 (로딩 약 10~20초)"):
        with st.spinner("광주·전남 뉴스 밸류 측정 중..."):
            st.session_state.top_picks_local = evaluate_top_news_by_category(
                st.session_state.user_info['openrouter_key'], loc[:20],
                "광주·전남 지역 기사",
                "지역 밀착성 및 파급력: 광주·전남 지역민의 실생활과 경제에 직접적인 영향을 미치는 이슈인가? 지역 현안으로서의 독보성과 중요도를 최우선으로 평가하세요."
            )
        with st.spinner("전국 뉴스 밸류 측정 중..."):
            st.session_state.top_picks_national = evaluate_top_news_by_category(
                st.session_state.user_info['openrouter_key'], nat[:20],
                "전국 이슈 기사",
                "전국적 대중성 및 화제성: 전국적으로 폭발적인 흥미를 갖고 클릭할 만한 기사인가? 사회적 파장과 독자 관심도를 최우선으로 평가하세요."
            )

    if st.session_state.top_picks_local or st.session_state.top_picks_national:
        pick_tab1, pick_tab2 = st.tabs(["📍 광주·전남 TOP 5", "🚨 전국 이슈 TOP 5"])
        with pick_tab1:
            if st.session_state.top_picks_local:
                render_news_list(st.session_state.top_picks_local, "top_local")
            else:
                st.info("광주·전남 기사 픽 결과가 없습니다.")
        with pick_tab2:
            if st.session_state.top_picks_national:
                render_news_list(st.session_state.top_picks_national, "top_national")
            else:
                st.info("전국 이슈 기사 픽 결과가 없습니다.")
        
    st.markdown("---")
    
    kw_l = st.session_state.user_info['kw_local']
    kw_n = st.session_state.user_info['kw_national']
    tab_name_1 = "📍 " + kw_l[:15] + ("..." if len(kw_l) > 15 else "")
    tab_name_2 = "🚨 " + kw_n[:15] + ("..." if len(kw_n) > 15 else "")
    
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
            res = generate_article(st.session_state.user_info['openrouter_key'], m_title or "직접 입력", m_content, f_type)
            st.session_state.manual_generated_text = res
            st.write(res)
    if c1.button("🎤 리포트"): p_manual("리포트 작성")
    if c2.button("📃 단신"): p_manual("단신 작성")
    if c3.button("💻 포털"): p_manual("포털 기사 작성")
    if 'manual_generated_text' in st.session_state: create_copy_button(st.session_state.manual_generated_text)

elif page == "⚙️ 환경설정":
    st.markdown("### ⚙️ 사용자 환경설정 (기사 규칙 및 키워드)")
    st.write(f"현재 로그인된 계정: **{st.session_state.user_info['user_id']}**")
    st.write("여기에서 수정된 규칙과 키워드는 서버의 엑셀 파일에 저장되어 언제든 반영됩니다.")
    st.markdown("---")
    
    st.subheader("📝 커스텀 기사 작성 규칙")
    new_report = st.text_area("🎤 리포트 가이드라인", value=st.session_state.user_info['rule_report'], height=150)
    new_briefing = st.text_area("📃 단신 가이드라인", value=st.session_state.user_info['rule_briefing'], height=150)
    new_portal = st.text_area("💻 포털 가이드라인", value=st.session_state.user_info['rule_portal'], height=150)
    
    st.markdown("---")
    st.subheader("🔍 커스텀 기사 수집 키워드 (쉼표로 구분)")
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        new_local = st.text_input("📍 첫 번째 탭 키워드 (예: 광주, 전남)", value=st.session_state.user_info['kw_local'])
    with col_k2:
        new_national = st.text_input("🚨 두 번째 탭 키워드 (예: 정치, 사고, 속보)", value=st.session_state.user_info['kw_national'])
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("💾 변경된 설정 엑셀에 저장하기", use_container_width=True):
        u_id = st.session_state.user_info['user_id']
        with st.spinner("클라우드 엑셀 DB에 저장 중..."):
            success = update_user_settings(u_id, new_report, new_briefing, new_portal, new_local, new_national)
        
        if success:
            st.session_state.user_info['rule_report'] = new_report
            st.session_state.user_info['rule_briefing'] = new_briefing
            st.session_state.user_info['rule_portal'] = new_portal
            st.session_state.user_info['kw_local'] = new_local
            st.session_state.user_info['kw_national'] = new_national
            
            st.toast("✅ 설정이 깃허브 DB에 안전하게 동기화되었습니다!", icon="💾")
            st.success("✅ 저장이 완료되었습니다!")
            time.sleep(1)
            st.rerun()
        else:
            st.error("🚨 엑셀 저장 중 오류가 발생했습니다.")
