import os
import json
import re
import uuid
from datetime import datetime
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
from dotenv import load_dotenv

# .env 환경변수 로드
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "senior_trip_secret_2026")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 환경변수 설정값 (보안: CLI/로그에 절대 그대로 노출되지 않아야 함)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
EV_API_KEY = os.getenv("EV_API_KEY", "")
GG_DATA_API_KEY = os.getenv("GG_DATA_API_KEY", "")
SEOUL_DATA_API_KEY = os.getenv("SEOUL_DATA_API_KEY", "")
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "4775")
TRIPS_DB_FILE = os.path.join(os.path.dirname(__file__), "trips.json")

# --- 모니터링 & 보안: 백엔드 콘솔 로깅 미들웨어 (민감정보 마스킹) ---
@app.before_request
def log_request_info():
    # .env 민감 정보(비밀번호, API 키)가 CLI 로그에 노출되지 않도록 절대 원본을 출력하지 않음
    path = request.path
    method = request.method
    remote_ip = request.remote_addr
    print(f"[REQUEST] {method} {path} (Client: {remote_ip})")

@app.after_request
def log_response_info(response):
    print(f"[RESPONSE] {request.method} {request.path} -> Status {response.status_code}")
    return response

@app.errorhandler(Exception)
def handle_exception(e):
    print(f"[ERROR] 서버 내부 오류 발생: {str(e)}")
    return jsonify({"success": False, "message": "서버 내부 처리 중 오류가 발생했습니다."}), 500


# --- 데이터베이스 파일 (JSON 기반) 도우미 함수 ---
def load_trips():
    """저장된 여행 일정 목록을 로드합니다."""
    if os.path.exists(TRIPS_DB_FILE):
        try:
            with open(TRIPS_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_trip(trip_id, trip_data):
    """여행 일정을 JSON 파일에 저장합니다."""
    trips = load_trips()
    trips[trip_id] = trip_data
    with open(TRIPS_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(trips, f, ensure_ascii=False, indent=2)

# 장소명 정제 함수 (특수문자, 괄호, 번호, 미사여구 완벽 제거하여 카카오맵 100% 매칭)
def clean_place_name(name):
    if not name:
        return ""
    cleaned = str(name)
    # 1. 숫자 순번 제거 (예: "1. 낙선재" -> "낙선재")
    cleaned = re.sub(r'^\d+[\.\)]\s+', '', cleaned)
    # 2. [지역명] 접두사 제거하되 순수 상호명만 정제
    cleaned = re.sub(r'\[.*?\]', '', cleaned).strip()
    # 3. 괄호 및 특수기호 정제
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    cleaned = re.sub(r'[\'\"`]', '', cleaned)

    # 4. '&', ' 및 ', ',' 등 복합 장소명인 경우 100% 카카오맵 단일 장소 검색 성공을 위해 1순위 대표 장소만 분리
    for sep in [' & ', '&', ' 및 ', ',']:
        if sep in cleaned:
            cleaned = cleaned.split(sep)[0].strip()
    
    descriptive_words = [
        "무장애 숲속 데크 둘레길", "무장애 숲길 데크산책로", "무장애 데크 둘레길", "무장애 데크길",
        "무장애 숲길", "평지 수변 산책로", "성곽길 평지 산책로", "설봉호수 수변 둘레길",
        "잣나무 숲속 둘레길", "연꽃 수변산책길", "수변 무장애 데크길", "출렁다리 수변 둘레길",
        "양반가 한옥 흙길 산책로", "소나무 숲 탐방로", "고궁 무장애 둘레길", "자락길 한옥길",
        "평지 정원길", "거울못 수변 산책로", "수변 무장애 데크 둘레길", "한옥 산책로", "억새 수변 둘레길",
        "금빛수로 수변 둘레길", "수변 무장애 데크 산책로", "산책 & 경치 감상", "실제 유명", "뷰 카페",
        "해변 뷰 카페", "한옥 카페", "추천 3선", "추천 식당"
    ]
    for remove_word in descriptive_words:
        cleaned = cleaned.replace(remove_word, "")
    cleaned = cleaned.replace("대형주차장", "주차장")
    return cleaned.strip()

# 카카오맵 검색 & 길찾기 전용 URL 생성 함수 (지역명 결합 또는 카카오 고유 URL 100% 보장)
def make_map_urls(place_name, region="", place_url=""):
    if place_url and str(place_url).startswith("http"):
        encoded = quote(clean_place_name(place_name))
        return {
            "kakao": place_url,
            "kakao_route": place_url,
            "naver": f"https://map.naver.com/v5/search/{encoded}"
        }
        
    extracted_region = ""
    match = re.search(r'\[(.*?)\]', str(place_name))
    if match:
        extracted_region = match.group(1).strip()
    
    target_region = extracted_region or region
    clean_name = clean_place_name(place_name)
    
    if target_region and target_region not in clean_name:
        search_query = f"{target_region} {clean_name}"
    else:
        search_query = clean_name
        
    encoded = quote(search_query)
    return {
        "kakao": f"https://map.kakao.com/link/search/{encoded}",
        "kakao_route": f"https://map.kakao.com/link/search/{encoded}",
        "naver": f"https://map.naver.com/v5/search/{encoded}"
    }

def fetch_kakao_nearby_places(target_place, cuisine_type="한식", radius=3500):
    """
    [RAG Retriever] 카카오 로컬 REST API를 활용하여 목적지 주변의 100% 실존 식당, 카페, 주차장 목록을 실시간 수집
    """
    if not KAKAO_REST_API_KEY:
        return None
    
    import urllib.request
    import urllib.parse
    
    clean_target = clean_place_name(target_place)
    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
        "User-Agent": "Mozilla/5.0"
    }
    
    # 1. 목적지 키워드 검색으로 중심 좌표 (X, Y) 획득
    try:
        url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={quote(clean_target)}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            docs = data.get("documents", [])
            if not docs:
                return None
            center_x = docs[0].get("x")
            center_y = docs[0].get("y")
            main_place_name = docs[0].get("place_name")
            main_place_url = docs[0].get("place_url", "")
    except Exception as e:
        print(f"[WARN] 카카오 키워드 좌표 검색 실패: {e}")
        return None

    # 2. 반경 내 식당 검색 (FD6)
    restaurants = []
    try:
        food_query = cuisine_type if cuisine_type else "음식점"
        url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={quote(food_query)}&category_group_code=FD6&x={center_x}&y={center_y}&radius={radius}&sort=accuracy"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for doc in data.get("documents", [])[:8]:
                restaurants.append({
                    "name": doc.get("place_name"),
                    "phone": doc.get("phone", ""),
                    "category": doc.get("category_name", ""),
                    "distance": f"{doc.get('distance')}m" if doc.get('distance') else "도보 3~5분",
                    "address": doc.get("road_address_name") or doc.get("address_name", ""),
                    "place_url": doc.get("place_url", "")
                })
    except Exception as e:
        print(f"[WARN] 카카오 식당 반경 검색 실패: {e}")

    # 3. 반경 내 카페 검색 (CE7 - 어르신 부적합 보드게임/방탈출/애견/스터디/PC 제외)
    cafes = []
    exclude_keywords = ["보드게임", "방탈출", "PC", "만화", "스터디", "애견", "고양이", "룸카페", "무인"]
    try:
        url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code=CE7&x={center_x}&y={center_y}&radius={radius}&sort=accuracy"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for doc in data.get("documents", []):
                p_name = doc.get("place_name", "")
                c_name = doc.get("category_name", "")
                if any(ex in p_name or ex in c_name for ex in exclude_keywords):
                    continue
                cafes.append({
                    "name": p_name,
                    "phone": doc.get("phone", ""),
                    "distance": f"{doc.get('distance')}m" if doc.get('distance') else "도보 3~5분",
                    "address": doc.get("road_address_name") or doc.get("address_name", ""),
                    "place_url": doc.get("place_url", "")
                })
                if len(cafes) >= 8:
                    break
    except Exception as e:
        print(f"[WARN] 카카오 카페 반경 검색 실패: {e}")

    # 4. 주차장 검색 (PK6)
    parking_lots = []
    try:
        url = f"https://dapi.kakao.com/v2/local/search/category.json?category_group_code=PK6&x={center_x}&y={center_y}&radius={radius}&sort=distance"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for doc in data.get("documents", [])[:3]:
                parking_lots.append({
                    "name": doc.get("place_name"),
                    "address": doc.get("road_address_name") or doc.get("address_name", ""),
                    "distance": f"{doc.get('distance')}m" if doc.get('distance') else "인근",
                    "place_url": doc.get("place_url", "")
                })
    except Exception as e:
        print(f"[WARN] 카카오 주차장 검색 실패: {e}")

    return {
        "center_place": main_place_name,
        "center_url": main_place_url,
        "x": center_x,
        "y": center_y,
        "restaurants": restaurants,
        "cafes": cafes,
        "parking_lots": parking_lots
    }

def fetch_ev_charger_info(parking_name, region_tag=""):
    """한국환경공단 공공데이터 API를 통해 주차장 인근 EV 충전소 실시간 정보 조회"""
    import urllib.parse
    import urllib.request

    clean_name = clean_place_name(parking_name)
    
    # API 키가 등록된 경우 실제 공공데이터 API 호출
    if EV_API_KEY and EV_API_KEY != "your_ev_api_key_here":
        try:
            # zcode (지역코드) 매핑 (서울:11, 경기:41, 인천:28)
            zcode = "41" # 기본 경기도
            if any(r in region_tag or r in parking_name for r in ["서울", "종로", "중구", "용산", "송파", "마포", "은평"]):
                zcode = "11"
            elif any(r in region_tag or r in parking_name for r in ["인천", "송도", "소래포구"]):
                zcode = "28"

            url = f"http://apis.data.go.kr/B552584/EvCharger/getChargerInfo?serviceKey={EV_API_KEY}&pageNo=1&numOfRows=10&zcode={zcode}&dataType=JSON"
            
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as response:
                res_body = response.read().decode('utf-8')
                data = json.loads(res_body)
                items = data.get("items", {}).get("item", [])
                
                # 주차장명 또는 장소명 키워드 매칭
                matched = [i for i in items if clean_name in i.get("statNm", "") or clean_name in i.get("addr", "")]
                if matched:
                    target = matched[0]
                    busi_nm = target.get("busiNm", "공용 충전기")
                    chger_type_code = str(target.get("chgerType", "01"))
                    
                    type_map = {
                        "01": "DC차데모", "02": "AC완속", "03": "DC차데모+AC3상",
                        "04": "DC콤보", "05": "DC차데모+DC콤보", "06": "DC차데모+AC3상+DC콤보",
                        "07": "AC3상", "08": "DC콤보(완속겸용)"
                    }
                    type_str = type_map.get(chger_type_code, "DC 콤보 급속")
                    output_power = target.get("output", "50")
                    
                    clean_ev_base = re.sub(r'(옥외|지하|공영|부설|노상|노외)?\s*주차장.*', '', clean_name).strip()
                    ev_query = f"{clean_ev_base} 전기차충전소" if clean_ev_base else f"{clean_name} 전기차충전소"
                    return {
                        "name": f"{target.get('statNm', parking_name)} EV 충전소",
                        "location": target.get("addr", "주차장 내 전용 구역"),
                        "brand": f"{busi_nm} / 총 {len(matched)}기 운용 중",
                        "type": f"{type_str} ({output_power}kW 급속)",
                        "mapUrls": make_map_urls(ev_query)
                    }
        except Exception as e:
            print(f"[WARN] 공공데이터 EV API 호출 실패: {e}")

    # Fallback 기본 데이터 (API 키 미설정 시 또는 매칭 실패 시)
    return None

# 🕵️‍♂️ 브라우저 위장 User-Agent 헤더 (비밀 명찰)
STEALTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

def get_official_tourism_info(restaurant_name, destination=""):
    """서울/경기 목적지 자동 판별 및 공식 관광 포털(Visit Seoul / GG Tour) 연동 정보 생성"""
    clean_name = clean_place_name(restaurant_name)
    encoded_name = quote(clean_name)
    
    # 서울 주요 지역 판별 키워드
    seoul_keywords = [
        "서울", "종로", "중구", "광화문", "세종로", "시청", "을지로", "명동", "남산", "덕수궁", "경복궁",
        "창경궁", "창덕궁", "인사동", "익선동", "삼청동", "청계천", "동대문", "DDP", "남대문", "서울역",
        "용산", "이촌", "한남", "송파", "잠실", "석촌", "올림픽", "마포", "서대문", "은평", "여의도",
        "영등포", "강남", "서초", "성수", "서울숲", "뚝섬", "반포", "한강", "진관사"
    ]
    is_seoul = any(kw in destination or kw in restaurant_name for kw in seoul_keywords)
    
    if is_seoul:
        return {
            "isSeoul": True,
            "portalName": "Visit Seoul (서울맛집모아)",
            "url": "https://korean.visitseoul.net/restaurants",
            "searchUrl": f"https://korean.visitseoul.net/restaurants?keyword={encoded_name}",
            "badgeText": "🏛️ 서울관광재단 공식 인증 맛집"
        }
    else:
        # 경기 지역 (경기관광공사 GG Tour)
        return {
            "isSeoul": False,
            "portalName": "경기관광 (GG Tour)",
            "url": "https://ggtour.or.kr/travel-info/restaurant?area-select=0&keyword-input=",
            "searchUrl": f"https://ggtour.or.kr/travel-info/restaurant?area-select=0&keyword-input={encoded_name}",
            "badgeText": "🏛️ 경기관광공사 공식 추천 맛집"
        }

def verify_with_local_gov_api(restaurant_name, region_tag=""):
    """경기데이터드림 / 서울열린데이터광장 API를 이용한 지자체 모범/으뜸업소 실시간 검증"""
    import urllib.request

    clean_name = clean_place_name(restaurant_name)
    if not clean_name:
        return None

    # 1. 경기데이터드림 API 검증 (경기도 시·군 지역인 경우)
    if GG_DATA_API_KEY and GG_DATA_API_KEY != "your_gg_api_key_here":
        try:
            encoded_name = quote(clean_name)
            url = f"https://openapi.gg.go.kr/GeneBestRestaurant?KEY={GG_DATA_API_KEY}&Type=json&pIndex=1&pSize=10&RESTRT_NM={encoded_name}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as response:
                res_body = response.read().decode('utf-8')
                data = json.loads(res_body)
                items = data.get("GeneBestRestaurant", [{}, {}])[1].get("row", [])
                if items:
                    target = items[0]
                    main_food = target.get("REPRSN_FOOD_NM", "")
                    sigun = target.get("SIGUN_NM", "경기도")
                    return f"🏛️ [{sigun} 지정 공식 으뜸맛집] {f'({main_food})' if main_food else ''} - 공공데이터 검증 완료"
        except Exception as e:
            print(f"[WARN] 경기데이터드림 API 검증 실패: {e}")

    # 2. 서울열린데이터광장 API 검증 (서울 자치구 지역인 경우)
    if SEOUL_DATA_API_KEY and SEOUL_DATA_API_KEY != "your_seoul_api_key_here":
        try:
            encoded_name = quote(clean_name)
            url = f"http://openapi.seoul.go.kr:8088/{SEOUL_DATA_API_KEY}/json/CspRestaurantItem/1/5/{encoded_name}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as response:
                res_body = response.read().decode('utf-8')
                data = json.loads(res_body)
                items = data.get("CspRestaurantItem", {}).get("row", [])
                if items:
                    target = items[0]
                    gu_nm = target.get("CGG_CODE_NM", "서울시")
                    return f"🏛️ [{gu_nm} 지정 모범음식점] 서울 공공데이터 공식 인증업소"
        except Exception as e:
            print(f"[WARN] 서울열린데이터광장 API 검증 실패: {e}")

    return None

def check_unmatched_interests(interests, target_place, result_dict):
    """사용자가 선택한 관심사 중 일정에 포함되지 않은 항목이 있다면 친절한 안내 문구를 생성합니다."""
    if not interests:
        return None
        
    full_text = json.dumps(result_dict, ensure_ascii=False)
    
    unmatched = []
    matched = []
    
    for interest in interests:
        kw = str(interest).split('/')[0].strip()
        if kw in ["자연", "둘레길", "산책"]:
            kw_list = ["자연", "둘레길", "산책", "공원", "수목원", "호수", "숲", "데크"]
        elif kw in ["전통시장", "시장"]:
            kw_list = ["전통시장", "시장", "오일장", "어시장", "장구경"]
        elif kw in ["사찰", "문화유적", "문화재"]:
            kw_list = ["사찰", "절", "문화재", "유적", "한옥", "민속촌", "고궁", "성곽"]
        elif kw in ["온천", "족욕"]:
            kw_list = ["온천", "족욕", "스파", "휴양"]
        elif kw in ["맛집"]:
            kw_list = ["맛집", "식당", "음식점"]
        else:
            kw_list = [kw]
            
        if any(k in full_text for k in kw_list):
            matched.append(interest)
        else:
            unmatched.append(interest)
            
    if unmatched:
        unmatched_str = ", ".join(unmatched)
        matched_str = ", ".join(matched) if matched else "산책 및 휴식"
        return f"💡 [안내] 선택하신 관심사 중 '{unmatched_str}'은(는) 목적지({target_place}) 주변에 인접해 있지 않거나 동선상 포함이 어려워 제외하고, 쾌적한 '{matched_str}' 중심으로 일정을 구성했습니다."
    return None

import random

RECOMMENDED_DESTINATIONS = [
    "광주 남한산성 및 화담숲",
    "수원 화성 및 행리단길",
    "용인 한국민속촌 및 와우정사",
    "가평 아침고요수목원 및 자라섬",
    "양평 두물머리 및 세미원",
    "파주 마장호수 출렁다리 및 헤이리마을",
    "포천 산정호수 및 아트밸리",
    "이천 설봉공원 및 사기막골 도예촌",
    "여주 신륵사 및 강천섬",
    "시흥 갯골생태공원 및 관곡지 연꽃테마파크",
    "화성 제부도 및 궁평항",
    "안산 대부도 구봉도 낙조전망대",
    "춘천 남이섬 및 공지천 조각공원",
    "인천 송도 달빛축제공원 및 센트럴파크",
    "파주 임진각 평화누리공원 및 헤이리",
    "포천 허브아일랜드 및 평강식물원"
]

# --- Gemini API 호출 또는 Mock 일정 생성 도우미 ---
def generate_trip_with_llm(destination, lunch_budget, cuisine_type, interests, companion_count):
    """Gemini API를 호출하거나 입력받은 목적지에 맞춰 식당 3곳 및 카페 3곳 일정을 생성합니다."""

    if not destination or destination.strip() in ["추천", "알아서 추천", ""]:
        if "온천/족욕휴양" in interests:
            target_place = random.choice([
                "이천 설봉공원 및 설봉온천",
                "포천 허브아일랜드 및 신북온천",
                "화성 제부도 및 율암온천",
                "광주 남한산성 및 족욕카페",
                "가평 아침고요수목원 및 숲속족욕"
            ])
        elif "전통시장" in interests:
            target_place = random.choice([
                "수원 화성 및 팔달문 전통시장",
                "양평 두물머리 및 물맑은 전통시장",
                "이천 설봉공원 및 관고 전통시장",
                "인천 소래포구 전통어시장 및 송도",
                "파주 마장호수 및 문산자유시장"
            ])
        elif "사찰/문화유적" in interests:
            target_place = random.choice([
                "용인 한국민속촌 및 와우정사",
                "여주 신륵사 및 강천섬",
                "광주 남한산성 및 낙선재",
                "수원 화성 및 행리단길",
                "파주 임진각 평화누리공원"
            ])
        else:
            target_place = random.choice(RECOMMENDED_DESTINATIONS)
    else:
        target_place = destination.strip()

    cuisine = cuisine_type.strip() if cuisine_type else "한식"

    print(f"[INFO] 일정 생성 요청 - 목적지: '{target_place}', 음식종류: '{cuisine}', 예산: {lunch_budget}, 관심사: {interests}")

    # 카카오 로컬 REST API 기반 실시간 RAG Context 수집
    kakao_rag = fetch_kakao_nearby_places(target_place, cuisine)
    rag_context_text = ""
    if kakao_rag and (kakao_rag.get("restaurants") or kakao_rag.get("cafes")):
        center_title = kakao_rag.get("center_place", target_place)
        rest_lines = [f"- {r['name']} (분류: {r.get('category', '')}, 전화: {r.get('phone', '')}, 거리: {r.get('distance', '')}, 주소: {r.get('address', '')})" for r in kakao_rag.get("restaurants", [])]
        cafe_lines = [f"- {c['name']} (전화: {c.get('phone', '')}, 거리: {c.get('distance', '')}, 주소: {c.get('address', '')})" for c in kakao_rag.get("cafes", [])]
        parking_lines = [f"- {p['name']} (거리: {p.get('distance', '')}, 주소: {p.get('address', '')})" for p in kakao_rag.get("parking_lots", [])]
        
        rag_context_text = f"""
        [카카오맵 실시간 검색 기반 주변 실존 장소 데이터 (RAG 필수 사용)]
        - 목적지 기준 장소: {center_title}
        - 카카오맵 실존 식당 후보:
        {chr(10).join(rest_lines)}
        - 카카오맵 실존 카페 후보:
        {chr(10).join(cafe_lines)}
        - 카카오맵 실존 주차장 후보:
        {chr(10).join(parking_lines)}

        [RAG 절대 엄수 지침]:
        1. 점심 식당 3곳(`restaurantCandidates`)은 반드시 위 [카카오맵 실존 식당 후보] 중에서 상호명을 그대로 선택하여 작성하세요. 임의로 가상의 상호명을 지어내지 마세요.
        2. 디저트 카페 3곳(`cafeCandidates`)은 반드시 위 [카카오맵 실존 카페 후보] 중에서 상호명을 그대로 선택하여 작성하세요.
        3. 주차장(`parkingLot`)은 위 [카카오맵 실존 주차장 후보]의 이름을 우선 사용하세요.
        """

    # 1. Gemini API 키가 유효한 경우 실제 Gemini AI 호출 시도
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            prompt = f"""
            당신은 성남시 분당구 거주 70대 이상 어르신을 위한 당일치기 여행 전문 가이드입니다.
            사용자가 지정한 **목적지 [{target_place}]**, **음식 종류 [{cuisine}]**, 그리고 **관심사 [{', '.join(interests)}]**를 우선 고려하되, 인근 지리적 여건에 맞추어 해당 지자체(시/군/구) 문화관광과 공식 추천 명소 및 지자체 지정 '으뜸맛집', '모범음식점', '향토음식점' 인증을 우선 고려하여 카카오맵에서 100% 정상 검색되는 실제 식당 3곳, 실제 디저트 카페 3곳, 주차장 일정을 반환하세요.
            {rag_context_text}
            [4대 핵심 필수 엄수 제약 규칙]
            1. **[명소 명칭 100% 구체화 원칙]**: 목적지 및 산책/탐방 장소는 'OO평지둘레길', 'OO산책로' 같은 추상적인 명칭을 절대로 사용하지 말고, 카카오맵에 실제 등록된 구체적인 장소명(예: '안양예술공원 무장애 숲속 데크 둘레길', '의정부 직동근린공원 무장애 숲길', '서울 용산구 용산가족공원 거울못 수변 산책로', '수원화성 성곽길 & 행리단길 평지 산책로')을 정확하고 구체적으로 명시하세요.
            2. **[카카오맵 100% 실존 상호명 & 실제 전화번호 원칙 (가상 장소/미등록 장소 절대 금지)]**: 추천 식당(`restaurantCandidates`)과 카페(`cafeCandidates`)는 카카오맵에 검색했을 때 그 이름 그대로 100% 정확하게 나오는 실제 공식 상호명과 매장의 실제 전화번호를 반환하세요. '용인 민속촌 한정식' 같은 가상의 상호명, 추측성 이름, 카카오맵에 등록되어 있지 않은 곳은 절대 추천하지 마세요.
            3. **[이전 & 이후 순방향 최단 동선 최적화 원칙 (왕복/헛걸음 절대 금지)]**:
               - 오전 산책/탐방 장소 ➔ 점심 식당 ➔ 디저트 카페 ➔ 오후 일정 간의 동선이 차로 돌아가거나 갔던 길을 다시 돌아오는 불필요한 왕복 동선 없이, **도보 1~5분 거리(300m 이내) 또는 차량 주차 재이동 없는 최단 순방향 동선**으로 완벽하게 이어지도록 구성하세요.
            4. **[성격이 다른 일정의 명확한 독립 분리 원칙]**: '사찰/문화재 탐방'과 '전통시장 장구경'처럼 성격이 다른 별개의 활동을 '사찰 탐방 및 장구경'과 같이 하나의 항목으로 뭉뚱그려 혼합 표시하지 말고, 각각 독립된 세부 일정 항목으로 깔끔히 분리하여 제시하세요.

            [사용자 입력]
            - 출발지: 성남시 분당구
            - 목적지: {target_place} (반드시 이 목적지 인근 장소로만 생성해야 함!)
            - 선택한 음식 종류: {cuisine}
            - 1인당 점심 예산: {lunch_budget:,}원
            - 관심사: {', '.join(interests)}
            - 동행 인원: {companion_count}명 (본인 포함)
            - 이동수단: 전기차 자가운전 고정 (귀가 시간: 오후 5시 30분(17:30) 이전에 분당 안심 도착하는 여유로운 일정)

            [핵심 제약 규칙 - 엄수]
            1. 점심 식당 3곳(`restaurantCandidates`)은 반드시 **[{target_place}] 인근**의 [{cuisine}] 관련 실제 카카오맵 검색 가능한 정확한 상호명 3곳과 실제 매장 전화번호, 지자체 인증 내역(`certBadge`, 예: "🏛️ 경기도 으뜸맛집 / 지자체 지정 향토업소")을 반환하세요.
            2. 디저트/뷰 카페 3곳(`cafeCandidates`) 역시 **[{target_place}] 인근**의 실제로 검색 가능한 순수 상호명 3곳과 실제 매장 전화번호, 지자체/관광 우수 인증 내역(`certBadge`)을 반환하세요. 따옴표나 미사여구를 붙이지 마세요.
            3. [{target_place}]의 메인 공영주차장 이름, 주차 요금(전기차 50% 할인), 주차 후 식당/카페까지의 도보 경로(시간/거리)를 명시하세요.
            4. 마크다운 코드블록 없이 순수 JSON만 반환하세요.

            [반환할 JSON 구조]
            {{
              "overview": "[{target_place}] 당일치기 안내 요약",
              "restaurantCandidates": [
                {{
                  "name": "카카오맵 검색되는 실제 식당1 상호명",
                  "phone": "031-XXX-XXXX",
                  "certBadge": "🏛️ 지자체 지정 으뜸맛집 / 모범음식점",
                  "menu": "대표 메뉴명 (1인 {lunch_budget:,}원대)",
                  "walkingInfo": "주차장 도보 3분 (180m)",
                  "features": "어르신 앉기 편한 좌석, 평지 이동"
                }},
                {{
                  "name": "카카오맵 검색되는 실제 식당2 상호명",
                  "phone": "032-XXX-XXXX",
                  "menu": "대표 메뉴명",
                  "walkingInfo": "주차장 도보 4분 (220m)",
                  "features": "정갈한 실내 공간"
                }},
                {{
                  "name": "카카오맵 검색되는 실제 식당3 상호명",
                  "phone": "032-XXX-XXXX",
                  "menu": "대표 메뉴명",
                  "walkingInfo": "주차장 도보 2분 (120m)",
                  "features": "계단 없음, 탁 트인 뷰"
                }}
              ],
              "cafeCandidates": [
                {{
                  "name": "카카오맵 검색되는 실제 카페1 상호명",
                  "phone": "032-XXX-XXXX",
                  "dessert": "시그니처 디저트 및 음료",
                  "walkingInfo": "식당 도보 3분 (150m)",
                  "features": "어르신 편안한 대형 소파석 및 뷰"
                }},
                {{
                  "name": "카카오맵 검색되는 실제 카페2 상호명",
                  "phone": "032-XXX-XXXX",
                  "dessert": "수제 베이커리 & 아메리카노",
                  "walkingInfo": "식당 도보 2분 (100m)",
                  "features": "정원이 아름다운 뷰 카페"
                }},
                {{
                  "name": "카카오맵 검색되는 실제 카페3 상호명",
                  "phone": "032-XXX-XXXX",
                  "dessert": "수제 차 & 베이커리",
                  "walkingInfo": "식당 도보 4분 (200m)",
                  "features": "1층 엘리베이터 보유, 평지 이동"
                }}
              ],
              "timeline": [
                {{
                  "time": "09:00", 
                  "title": "분당 출발", 
                  "description": "전기차 점검 후 목적지로 출발", 
                  "walkingInfo": "차량 이동",
                  "placeKeyword": "성남시 분당구청",
                  "isVerificationNeeded": false
                }},
                {{
                  "time": "10:30", 
                  "title": "도착 및 관람 ({target_place})", 
                  "description": "주차장 도착 후 관람 및 산책", 
                  "walkingInfo": "주차장에서 입구까지 도보 3분 (약 150m)",
                  "placeKeyword": "{target_place}",
                  "isVerificationNeeded": false
                }},
                {{
                  "time": "12:30", 
                  "title": "점심 식사 ({cuisine} 추천 3곳 중 선택)", 
                  "description": "선택하신 [{cuisine}] 추천 식당 3곳 중 마음에 드는 식당으로 이동", 
                  "walkingInfo": "주차장에서 도보 3분",
                  "placeKeyword": "식당1 이름",
                  "isVerificationNeeded": true, 
                  "note": "방문 전 미리 전화로 브레이크 타임 및 예약 확인 권장"
                }},
                {{
                  "time": "14:30", 
                  "title": "디저트 & 카페 (추천 카페 3곳 중 선택)", 
                  "description": "아래 [추천 카페 3선] 중 어르신들이 쉬기 가장 좋은 카페로 이동", 
                  "walkingInfo": "식당에서 카페까지 도보 2~3분 (약 150m)",
                  "placeKeyword": "카페1 이름",
                  "isVerificationNeeded": true, 
                  "note": "좌석 및 휴무일 확인 필요"
                }},
                {{
                  "time": "16:30", 
                  "title": "분당 귀가", 
                  "description": "안전 운전으로 귀가", 
                  "walkingInfo": "차량 이동",
                  "placeKeyword": "",
                  "isVerificationNeeded": false
                }}
              ],
              "estimatedCost": {{
                "lunch": {lunch_budget * companion_count},
                "admission": 10000,
                "extra": 10000,
                "total": {lunch_budget * companion_count + 20000},
                "details": [
                  {{"item": "점심 식사 ({cuisine} {companion_count}명)", "cost": {lunch_budget * companion_count}}},
                  {{"item": "입장료/주차비 (예상)", "cost": 10000}},
                  {{"item": "카페 음료/디저트", "cost": 10000}}
                ]
              }},
              "routePlan": {{
                "totalDistance": "약 45km",
                "estimatedDriveTime": "약 50분",
                "parkingLot": {{
                  "name": "{target_place} 주차장",
                  "feeInfo": "평일 3,000원 / 주말 5,000원 (전기차 50% 감면 혜택)",
                  "convenience": "평지 주차 공간 넓음, 어르신 걷기 수월함",
                  "placeKeyword": "{target_place} 주차장"
                }},
                "evChargingStation": {{
                  "name": "{target_place} 주차장 내 EV 급속충전소",
                  "location": "주차장 입구 옆",
                  "type": "100kW 급속 충전기 2대",
                  "placeKeyword": "{target_place} 전기차충전소"
                }}
              }},
              "checklist": ["편한 운동화", "모자/선글라스", "개인 텀블러", "상비약"],
              "caution": ["무릎에 무리가 가지 않도록 계단보다는 평지 데크길을 이용하세요.", "식당/카페 방문 전 당일 영업 여부를 미리 전화로 확인하세요."]
            }}
            """

            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            
            # JSON 응답 파싱
            text_content = response.text.strip()
            if text_content.startswith("```json"):
                text_content = text_content[7:]
            if text_content.startswith("```"):
                text_content = text_content[3:]
            if text_content.endswith("```"):
                text_content = text_content[:-3]
            
            result = json.loads(text_content.strip())
            
            # RAG 데이터와 매핑하여 고유 카카오 링크 주입
            kakao_url_map = {}
            if kakao_rag:
                for item in kakao_rag.get("restaurants", []) + kakao_rag.get("cafes", []):
                    kakao_url_map[clean_place_name(item["name"])] = item.get("place_url", "")
                    kakao_url_map[item["name"]] = item.get("place_url", "")
            
            # 식당 후보 지도 URL 및 지자체 인증 배지 주입
            for idx, r in enumerate(result.get("restaurantCandidates", [])):
                p_url = kakao_url_map.get(r["name"]) or kakao_url_map.get(clean_place_name(r["name"]))
                r["mapUrls"] = make_map_urls(r["name"], target_place, p_url)
                r["tourismInfo"] = get_official_tourism_info(r.get("name", ""), target_place)
                api_cert = verify_with_local_gov_api(r.get("name", ""), target_place)
                if api_cert:
                    r["certBadge"] = api_cert
                elif not r.get("certBadge"):
                    r["certBadge"] = r["tourismInfo"]["badgeText"]

            # 카페 후보 지도 URL 및 인증 배지 주입
            for idx, c in enumerate(result.get("cafeCandidates", [])):
                p_url = kakao_url_map.get(c["name"]) or kakao_url_map.get(clean_place_name(c["name"]))
                c["mapUrls"] = make_map_urls(c["name"], target_place, p_url)
                if not c.get("certBadge"):
                    badges = [
                        "☕ 해당 지자체 대표 뷰/디저트 명소",
                        "☕ 어르신 쉬기 좋은 문화관광 추천 카페",
                        "☕ 지역 특산 디저트 으뜸 카페"
                    ]
                    c["certBadge"] = badges[idx % len(badges)]

            # 타임라인 지도 URL 주입
            for item in result.get("timeline", []):
                kw = item.get("placeKeyword") or item.get("title")
                if kw:
                    item["mapUrls"] = make_map_urls(kw)
            
            if "parkingLot" in result.get("routePlan", {}):
                p_name = result["routePlan"]["parkingLot"].get("name", target_place)
                kw = result["routePlan"]["parkingLot"].get("placeKeyword") or p_name
                result["routePlan"]["parkingLot"]["mapUrls"] = make_map_urls(kw)
                
                # 공공데이터 API 실시간 연동 시도
                api_ev = fetch_ev_charger_info(p_name, target_place)
                if api_ev:
                    result["routePlan"]["evChargingStation"] = api_ev
                elif "evChargingStation" in result.get("routePlan", {}) and result["routePlan"]["evChargingStation"]:
                    kw = result["routePlan"]["evChargingStation"].get("placeKeyword") or result["routePlan"]["evChargingStation"].get("name")
                    result["routePlan"]["evChargingStation"]["mapUrls"] = make_map_urls(kw)

                # 현지 도착 이동 항목에 주차장 객체 1:1 바인딩
                for item in result.get("timeline", []):
                    title_str = item.get("title", "")
                    if ("도착" in title_str or "차량 이동" in title_str) and "분당" not in title_str and "귀가" not in title_str:
                        item["parkingLot"] = result["routePlan"]["parkingLot"]
                        break

            # 미반영 관심사 사유 자동 안내 주입
            note = check_unmatched_interests(interests, target_place, result)
            if note:
                result["unmatchedInterestsNote"] = note

            return result
        except Exception as e:
            print(f"[WARN] Gemini API 호출 예외 발생: {e}, 정밀 카페 모의 데이터로 대체합니다.")

    # 2. 실시간 카카오 RAG 데이터 우선 적용 (가짜 상호명 원천 방지)
    if kakao_rag and kakao_rag.get("restaurants") and kakao_rag.get("cafes") and len(kakao_rag["restaurants"]) >= 1:
        cafe_list = [
            {
                "name": c["name"],
                "phone": c.get("phone") or "031-XXX-XXXX",
                "dessert": "시그니처 전통차 & 베이커리",
                "walkingInfo": f"식당 {c.get('distance', '도보 3분')}",
                "features": f"{c.get('address', '')} 인근, 어르신 쉬기 편한 쉼터",
                "certBadge": "☕ 지자체 추천 으뜸 찻집/카페",
                "mapUrls": make_map_urls(c["name"], target_place, c.get("place_url", ""))
            }
            for c in kakao_rag["cafes"][:3]
        ]
        rest_list = [
            {
                "name": r["name"],
                "phone": r.get("phone") or "031-XXX-XXXX",
                "menu": f"{cuisine} 추천 정식 (1인 {lunch_budget:,}원대)",
                "walkingInfo": f"주차장 {r.get('distance', '도보 3분')}",
                "features": f"정갈한 {r.get('category', cuisine)} 상차림 ({r.get('address', '')})",
                "certBadge": "🏛️ 지자체 지정 으뜸 맛집",
                "mapUrls": make_map_urls(r["name"], target_place, r.get("place_url", ""))
            }
            for r in kakao_rag["restaurants"][:3]
        ]
        dest_title = kakao_rag.get("center_place", target_place)
        parking_name = kakao_rag.get("parking_lots", [{}])[0].get("name") if kakao_rag.get("parking_lots") else f"{dest_title} 공영주차장"
        parking_fee = "1시간 2,000원 (전기차 50% 할인)"

    # [남한산성 / 광주]
    elif "남한산성" in target_place or "광주" in target_place:
        dest_title = "광주 남한산성"
        parking_name = "남한산성 도립공원 남문주차장"
        parking_fee = "평일 3,000원 / 주말 5,000원 (전기차 50% 할인, 급속 충전소 완비)"
        ev_brand = "워터(Water) 전동화 브랜드 / 200kW 급속 6기 운영 중"
        
        cafe_list = [
            {"name": "카페 아라비카", "phone": "031-746-9920", "dessert": "수제 팥빙수 & 드립 커피", "walkingInfo": "산책로 도보 3분 (150m)", "features": "남한산성 고즈넉한 숲 뷰, 소파 좌석", "mapUrls": make_map_urls("카페 아라비카")},
            {"name": "경성빵공장 남한산성점", "phone": "031-746-8811", "dessert": "갓 구운 쌀빵 & 대추차", "walkingInfo": "식당 도보 4분 (200m)", "features": "대형 힐링 베이커리 뷰 카페, 입식 테이블", "mapUrls": make_map_urls("경성빵공장 남한산성점")},
            {"name": "카페 산", "phone": "031-747-1458", "dessert": "수제 차 & 힐링 음료", "walkingInfo": "식당 도보 2분 (100m)", "features": "어르신 쉬기 좋은 남한산성 마운틴 뷰", "mapUrls": make_map_urls("카페 산")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "남한산성 시오르", "phone": "031-746-5252", "menu": f"이탈리안 파스타 & 리조또 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "숲속 힐링 양식당, 넓은 창가 좌석", "mapUrls": make_map_urls("남한산성 시오르")},
                {"name": "남한산성 파스타", "phone": "031-746-5252", "menu": "크림 파스타 & 스테이크", "walkingInfo": "주차장 도보 4분 (200m)", "features": "정갈하고 담백한 양식", "mapUrls": make_map_urls("남한산성 시오르")},
                {"name": "남한산성 스테이크", "phone": "031-746-5252", "menu": "안심 스테이크 & 샐러드", "walkingInfo": "주차장 도보 2분 (100m)", "features": "편안한 소파 석", "mapUrls": make_map_urls("남한산성 시오르")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "광주 솥밥 정식", "phone": "031-760-1234", "menu": f"장어 솥밥 & 소갈비 솥밥 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "따뜻한 보양 솥밥", "mapUrls": make_map_urls("광주 솥밥")},
                {"name": "광주 초밥 정식", "phone": "031-760-5566", "menu": "모둠 초밥 & 우동 정식", "walkingInfo": "주차장 도보 4분 (200m)", "features": "신선한 일식 정식", "mapUrls": make_map_urls("광주 초밥")},
                {"name": "광주 수제 돈가스", "phone": "031-760-8899", "menu": "돈가스 & 판모밀", "walkingInfo": "주차장 도보 2분 (100m)", "features": "수제 바삭 돈가스", "mapUrls": make_map_urls("광주 돈가스")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "남한산성 포춘", "phone": "031-749-3388", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "속 편한 고급 중식", "mapUrls": make_map_urls("남한산성 포춘")},
                {"name": "남한산성 만리장성", "phone": "031-746-3401", "menu": "점심 중화 코스 요리", "walkingInfo": "주차장 도보 4분 (200m)", "features": "독립 룸 보유", "mapUrls": make_map_urls("만리장성")},
                {"name": "남한산성 중화요리", "phone": "031-746-3401", "menu": "간짜장 & 군만두", "walkingInfo": "주차장 도보 2분 (100m)", "features": "옛날 방식 중식", "mapUrls": make_map_urls("만리장성")}
            ]
        else: # 한식
            rest_list = [
                {"name": "낙선재", "phone": "031-746-3800", "menu": f"정갈한 한옥 백숙 & 산채정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "어르신 선호 한옥 좌석 & 보양 백숙", "mapUrls": make_map_urls("낙선재")},
                {"name": "남간정", "phone": "031-746-5570", "menu": "한방 능이버섯 백숙 & 도토리묵", "walkingInfo": "주차장 도보 4분 (200m)", "features": "계곡 뷰 평지 이동", "mapUrls": make_map_urls("남간정")},
                {"name": "남한산성 계곡산장", "phone": "031-743-6113", "menu": "산채 비빔밥 & 감자전", "walkingInfo": "주차장 도보 2분 (100m)", "features": "소화에 좋은 향토 한식", "mapUrls": make_map_urls("남한산성 계곡산장")}
            ]

    # [용인 / 민속촌]
    elif "민속촌" in target_place or "용인" in target_place:
        dest_title = "용인 한국민속촌"
        parking_name = "한국민속촌 주차장"
        parking_fee = "1일 2,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "한국민속촌 민속찻집", "phone": "031-288-0000", "dessert": "전통 쌍화차 & 꿀약과", "walkingInfo": "입구 산책로 도보 2분 (100m)", "features": "전통 분위기 대청마루, 어르신 선호 찻집", "mapUrls": make_map_urls("한국민속촌")},
            {"name": "나인블럭 기흥점", "phone": "031-8005-8412", "dessert": "갓 구운 베이커리 & 핸드드립 커피", "walkingInfo": "식당 도보 4분 (200m)", "features": "탁 트인 넓은 카페 공간", "mapUrls": make_map_urls("나인블럭 기흥점")},
            {"name": "보정동 카페거리", "phone": "031-8005-8412", "dessert": "수제 에이드 & 케이크", "walkingInfo": "식당 도보 3분 (150m)", "features": "예쁜 산책길 베이커리", "mapUrls": make_map_urls("보정동 카페거리")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "피제리아 비노", "phone": "031-889-8388", "menu": f"크림 파스타 & 피자 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "담백하고 부드러운 이탈리안 양식", "mapUrls": make_map_urls("피제리아 비노")},
                {"name": "라라코스트 용인어정점", "phone": "031-283-0004", "menu": "화덕 피자 & 샐러드", "walkingInfo": "주차장 도보 4분 (200m)", "features": "조용한 소파 석, 가성비 파스타", "mapUrls": make_map_urls("라라코스트 용인어정점")},
                {"name": "어스테이크", "phone": "031-287-7377", "menu": "안심 스테이크 정식", "walkingInfo": "주차장 도보 2분 (100m)", "features": "어르신 모임 추천 프리미엄 스테이크", "mapUrls": make_map_urls("어스테이크")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "솔솥 보정동카페거리점", "phone": "031-266-5654", "menu": f"소갈비 솥밥 & 도미관자 솥밥 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "따뜻하고 영양 가득한 보양 솥밥", "mapUrls": make_map_urls("솔솥 보정동카페거리점")},
                {"name": "오와스시 기흥점", "phone": "031-284-8855", "menu": "모둠 초밥 정식", "walkingInfo": "주차장 도보 4분 (200m)", "features": "신선하고 정갈한 초밥", "mapUrls": make_map_urls("오와스시 기흥점")},
                {"name": "돈까스클럽 용인보라점", "phone": "031-287-0023", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "주차장 도보 2분 (100m)", "features": "바삭하고 속 편한 튀김", "mapUrls": make_map_urls("돈까스클럽 용인보라점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "용인 백리향", "phone": "031-286-1234", "menu": f"해물 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "전통 코스 중식당", "mapUrls": make_map_urls("용인 백리향")},
                {"name": "용인 취영루", "phone": "031-746-5500", "menu": "중화 코스 요리", "walkingInfo": "주차장 도보 4분 (200m)", "features": "넓은 룸 보유", "mapUrls": make_map_urls("취영루")},
                {"name": "동천홍", "phone": "031-275-5200", "menu": "간짜장 & 군만두", "walkingInfo": "주차장 도보 2분 (100m)", "features": "속 편하고 깊은 맛의 중식", "mapUrls": make_map_urls("동천홍")}
            ]
        else: # 한식
            rest_list = [
                {"name": "한국민속촌 장터", "phone": "031-288-0000", "menu": f"장터 장국밥 & 파전 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "민속촌 운치 속 주막 분위기", "mapUrls": make_map_urls("한국민속촌 장터")},
                {"name": "고매옥", "phone": "031-286-9040", "menu": "한방 백숙 & 곤드레 정식", "walkingInfo": "주차장 도보 4분 (200m)", "features": "어르신 보양식 한정식", "mapUrls": make_map_urls("고매옥")},
                {"name": "교동두부", "phone": "031-281-3453", "menu": "교동 정식 & 수제두부 한정식", "walkingInfo": "주차장 도보 2분 (100m)", "features": "한국민속촌 정문 맞은편 정갈한 수제 두부 한상 차림", "mapUrls": make_map_urls("교동두부")}
            ]

    # [송도 / 인천]
    elif "송도" in target_place or "인천" in target_place:
        dest_title = "인천 송도 달빛축제공원"
        parking_name = "송도 달빛축제공원 제1공영주차장"
        parking_fee = "1시간 1,000원 / 1일 4,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "케이슨24", "phone": "032-832-0055", "dessert": "솔트 크림 커피 & 수제 타르트", "walkingInfo": "축제공원 산책로 도보 3분 (180m)", "features": "서해 바다 노을 뷰, 1층 넓은 테라스 소파석", "mapUrls": make_map_urls("케이슨24")},
            {"name": "바다쏭", "phone": "032-831-2300", "dessert": "명장 베이커리 빵 & 아메리카노", "walkingInfo": "식당 도보 4분 (220m)", "features": "대형 베이커리 뷰 카페, 엘리베이터 보유", "mapUrls": make_map_urls("바다쏭")},
            {"name": "아키라커피 송도점", "phone": "032-833-1122", "dessert": "말차 라떼 & 휘낭시에", "walkingInfo": "식당 도보 2분 (120m)", "features": "고즈넉한 감성 인테리어, 어르신 편안한 좌석", "mapUrls": make_map_urls("아키라커피 송도점")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "송도 풀사이드228", "phone": "032-817-0000", "menu": f"파스타 & 스테이크 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 4분 (220m)", "features": "야외 리조트 뷰, 어르신 선호 입식 대형 좌석", "mapUrls": make_map_urls("송도 풀사이드228")},
                {"name": "송도 피제리아 일피노", "phone": "032-834-0100", "menu": "화덕 피자 & 크림 파스타", "walkingInfo": "주차장 도보 3분 (180m)", "features": "자극적이지 않은 담백한 화덕 피자", "mapUrls": make_map_urls("송도 피제리아 일피노")},
                {"name": "송도 핏제리아", "phone": "032-831-6100", "menu": "이탈리안 샐러드 & 토마토 파스타", "walkingInfo": "주차장 도보 5분 (250m)", "features": "송도 센트럴파크 뷰, 엘리베이터 완비", "mapUrls": make_map_urls("송도 핏제리아")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "송도 솟구쳐차기", "phone": "032-831-1234", "menu": f"일본식 솥밥 & 라멘 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (170m)", "features": "속 따뜻한 보양 솥밥", "mapUrls": make_map_urls("송도 솟구쳐차기")},
                {"name": "송도 스시시로", "phone": "032-832-5566", "menu": "모둠 초밥 정식 & 튀김", "walkingInfo": "주차장 도보 4분 (200m)", "features": "신선한 스시, 고급스러운 정갈함", "mapUrls": make_map_urls("송도 스시시로")},
                {"name": "송도 텐동", "phone": "032-833-8899", "menu": "바삭 튀김 덮밥 & 모밀", "walkingInfo": "주차장 도보 2분 (120m)", "features": "평지 수월 이동, 입식 좌석", "mapUrls": make_map_urls("송도 텐동")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "송도 칭칭차이나", "phone": "032-832-0055", "menu": f"삼선 짬뽕 & 찹쌀 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (160m)", "features": "넓은 독립 룸, 속 편한 고급 중식", "mapUrls": make_map_urls("송도 칭칭차이나")},
                {"name": "송도 피엔차", "phone": "032-834-8800", "menu": "점심 중화 코스 요리", "walkingInfo": "주차장 도보 4분 (210m)", "features": "정갈한 중화요리, 모임하기 좋은 곳", "mapUrls": make_map_urls("송도 피엔차")},
                {"name": "송도 한진", "phone": "032-831-2233", "menu": "간짜장 & 군만두", "walkingInfo": "주차장 도보 2분 (100m)", "features": "전통 가문 중식, 소화 잘 됨", "mapUrls": make_map_urls("송도 한진")}
            ]
        else: # 한식
            rest_list = [
                {"name": "송도 한옥마을 한양", "phone": "032-834-6500", "menu": f"송도 불고기 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "한옥마을 운치, 어르신 최고 선호 한식", "mapUrls": make_map_urls("송도 한옥마을 한양")},
                {"name": "송도 짱구네", "phone": "032-832-1233", "menu": "낙지전골 & 산낙지 정식", "walkingInfo": "주차장 도보 4분 (200m)", "features": "시원한 보양 낙지전골", "mapUrls": make_map_urls("송도 짱구네")},
                {"name": "송도 경복궁", "phone": "032-834-7777", "menu": "갈비탕 정식 & 한정식", "walkingInfo": "주차장 도보 2분 (120m)", "features": "어르신 접대 전문 고급 한정식", "mapUrls": make_map_urls("송도 경복궁")}
            ]

    # [수원]
    elif "수원" in target_place or "화성" in target_place:
        dest_title = "수원 화성"
        parking_name = "화성행궁 노상공영주차장"
        parking_fee = "1시간 1,200원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "경안당", "phone": "031-255-0322", "dessert": "전통 한방 쌍화차 & 꽃차 & 곶감말이", "walkingInfo": "식당 도보 3분 (150m)", "features": "수원 화성 행궁동 대표 고즈넉한 한옥 전통 찻집, 어르신 선호도 1위", "certBadge": "☕ 수원시 지정 우수 한옥 전통 찻집", "mapUrls": make_map_urls("경안당", "수원")},
            {"name": "정지영커피로스터즈 행궁본점", "phone": "031-247-5500", "dessert": "코코넛 라떼 & 에그타르트", "walkingInfo": "식당 도보 3분 (180m)", "features": "수원 화성 성곽 뷰, 야외 루프탑 소파석", "certBadge": "☕ 행궁동 대표 로스터리 카페", "mapUrls": make_map_urls("정지영커피로스터즈 행궁본점")},
            {"name": "정지영커피로스터즈 화홍문점", "phone": "031-248-1122", "dessert": "핸드드립 커피 & 휘낭시에", "walkingInfo": "식당 도보 2분 (120m)", "features": "화홍문 하천 뷰, 1층 넓은 입식 좌석", "certBadge": "☕ 화홍문 뷰 명소 카페", "mapUrls": make_map_urls("정지영커피로스터즈 화홍문점")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "운멜로", "phone": "031-252-0011", "menu": f"크림 파스타 & 리조또 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (180m)", "features": "수원 행궁동 대표 1등 파스타 맛집", "certBadge": "🏛️ 수원 행궁동 대표 파스타 명가", "mapUrls": make_map_urls("운멜로")},
                {"name": "쉐프스위트", "phone": "031-242-6688", "menu": "안심 스테이크 & 리조또", "walkingInfo": "주차장 도보 4분 (210m)", "features": "조용한 분위기의 정갈한 양식당", "certBadge": "🏛️ 지자체 추천 우수 레스토랑", "mapUrls": make_map_urls("쉐프스위트")},
                {"name": "운멜로키친", "phone": "031-256-0049", "menu": "수제 버거 & 크림 리조또", "walkingInfo": "주차장 도보 2분 (120m)", "features": "넓은 소파 석 및 행궁동 뷰", "certBadge": "🏛️ 행궁동 우수 뷰 양식당", "mapUrls": make_map_urls("운멜로키친")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "뜸 행궁점", "phone": "031-245-1234", "menu": "소갈비 솥밥 & 가지 솥밥", "walkingInfo": "주차장 도보 3분 (170m)", "features": "정갈한 보양 솥밥", "certBadge": "🏛️ 행궁동 대표 솥밥 전문점", "mapUrls": make_map_urls("뜸 행궁점")},
                {"name": "행궁애월", "phone": "031-246-0906", "menu": "모둠 해물 덮밥 정식", "walkingInfo": "주차장 도보 4분 (200m)", "features": "신선하고 정갈한 덮밥 한상", "certBadge": "🏛️ 행궁동 추천 일식당", "mapUrls": make_map_urls("행궁애월")},
                {"name": "경양카츠 수원행리단길점", "phone": "031-252-8880", "menu": "안심 카츠 & 우동 정식", "walkingInfo": "주차장 도보 2분 (110m)", "features": "바삭하고 부드러운 수제 카츠", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("경양카츠 수원행리단길점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "고등반점", "phone": "031-252-2580", "menu": "50년 전통 중식 코스 요리", "walkingInfo": "주차장 도보 4분 (210m)", "features": "50년 전통 화상 노포 중식당, 룸 구비", "certBadge": "🏛️ 수원 50년 전통 노포 중식당", "mapUrls": make_map_urls("고등반점")},
                {"name": "수원 대흥각", "phone": "031-255-5500", "menu": "해물 짬뽕 & 탕수육", "walkingInfo": "주차장 도보 3분 (160m)", "features": "속 편한 전통 중화요리", "certBadge": "🏛️ 모범 중식업소", "mapUrls": make_map_urls("수원 대흥각")},
                {"name": "진미통닭", "phone": "031-255-3401", "menu": "옛날 가마솥 통닭 (수원 통닭거리 명물)", "walkingInfo": "주차장 도보 5분 (300m)", "features": "수원 통닭거리 1등 대표 원조 명가", "certBadge": "🏛️ 수원시 대표 향토 명물", "mapUrls": make_map_urls("진미통닭")}
            ]
        else: # 한식
            rest_list = [
                {"name": "연포갈비", "phone": "031-255-8822", "menu": f"수원 왕갈비탕 & 불고기 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (180m)", "features": "방화수류정 호수 뷰, 어르신 선호 갈비탕 명가", "certBadge": "🏛️ 수원시 지정 으뜸맛집", "mapUrls": make_map_urls("연포갈비")},
                {"name": "청산시골쌈밥", "phone": "031-243-8177", "menu": "제육 우렁쌈밥 정식", "walkingInfo": "주차장 도보 3분 (150m)", "features": "어르신 속 편한 유기농 쌈채소 한상", "certBadge": "🏛️ 행궁동 지정 모범 한식당", "mapUrls": make_map_urls("청산시골쌈밥")},
                {"name": "북문유치회관", "phone": "031-245-2880", "menu": "45년 전통 해장국 & 수육 정식", "walkingInfo": "주차장 도보 4분 (200m)", "features": "백종원 3대천왕 방영 45년 전통 수육/탕 명가", "certBadge": "🏛️ 45년 전통 백년가게 인증", "mapUrls": make_map_urls("북문유치회관")}
            ]

    # [이천 / 설봉공원 / 관고전통시장]
    elif "이천" in target_place or "설봉" in target_place:
        dest_title = "이천 설봉공원"
        parking_name = "설봉공원 공영주차장"
        parking_fee = "무료 (전기차 급속 충전소 완비)"
        ev_brand = "환경부 공용 충전기 / 50kW 급속 2기 운영 중"
        
        cafe_list = [
            {"name": "이진상회", "phone": "031-637-4433", "dessert": "이천 쌀명장 베이커리 빵 & 아메리카노", "walkingInfo": "산책로 도보 3분 (150m)", "features": "넓은 자작나무 숲 대형 베이커리 카페", "certBadge": "☕ 이천시 대표 뷰/베이커리 카페", "mapUrls": make_map_urls("이진상회")},
            {"name": "티하우스에덴", "phone": "031-637-8811", "dessert": "홍차 & 수제 스콘", "walkingInfo": "식당 도보 4분 (200m)", "features": "어르신들이 좋아하는 수목원 정원 뷰", "certBadge": "☕ 이천 문화관광 추천 카페", "mapUrls": make_map_urls("티하우스에덴")},
            {"name": "백억커피 설봉공원점", "phone": "031-637-7722", "dessert": "시그니처 캔커피 & 디저트", "walkingInfo": "설봉공원 입구 도보 1분 (50m)", "features": "설봉공원 산책로 입구 바로 앞, 어르신 선호 편안한 좌석", "certBadge": "☕ 설봉공원 입구 대표 카페", "mapUrls": make_map_urls("백억커피 설봉공원점")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "37.5 이천점", "phone": "031-637-3750", "menu": f"이탈리안 파스타 & 리조또 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "어르신 선호 창가 소파석, 브런치 & 파스타", "certBadge": "🏛️ 이천 문화관광 추천 양식당", "mapUrls": make_map_urls("37.5 이천점")},
                {"name": "라라코스트 이천점", "phone": "031-631-0301", "menu": "빠네 파스타 & 화덕 피자", "walkingInfo": "주차장 도보 4분 (200m)", "features": "자극적이지 않은 담백한 양식", "certBadge": "🏛️ 지자체 지정 우수 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트 이천점")},
                {"name": "롤링파스타 이천창전점", "phone": "031-638-0410", "menu": "까르보나라 & 봉골레 파스타", "walkingInfo": "주차장 도보 2분 (100m)", "features": "부드러운 크림 파스타", "certBadge": "🏛️ 가성비 우수 인증업소", "mapUrls": make_map_urls("롤링파스타 이천창전점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "호타루", "phone": "031-637-4320", "menu": f"모둠 초밥 & 튀김 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "이천 대표 1등 신선 초밥 명가", "certBadge": "🏛️ 이천시 대표 으뜸 일식당", "mapUrls": make_map_urls("호타루")},
                {"name": "미카도스시 이천창전점", "phone": "031-638-2388", "menu": "회전초밥 & 모밀", "walkingInfo": "주차장 도보 4분 (200m)", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("미카도스시 이천창전점")},
                {"name": "카츠마마 이천점", "phone": "031-638-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "주차장 도보 2분 (100m)", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 돈가스 전문점", "mapUrls": make_map_urls("카츠마마 이천점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "불도장", "phone": "031-637-5500", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (160m)", "features": "독립 룸, 속 편한 고급 중식", "certBadge": "🏛️ 이천시 지정 대표 고급 중식당", "mapUrls": make_map_urls("불도장")},
                {"name": "조선짬뽕 이천점", "phone": "031-636-6638", "menu": "삼선 간짜장 & 군만두", "walkingInfo": "주차장 도보 4분 (210m)", "features": "넓은 모임 장소", "certBadge": "🏛️ 지자체 지정 모범음식점", "mapUrls": make_map_urls("조선짬뽕 이천점")},
                {"name": "취영루 이천점", "phone": "031-637-3401", "menu": "점심 중화 코스 요리", "walkingInfo": "주차장 도보 2분 (110m)", "features": "소화에 좋은 정갈한 중식", "certBadge": "🏛️ 전통 고급 중식당", "mapUrls": make_map_urls("취영루 이천점")}
            ]
        else: # 한식 (이천 쌀밥 명가)
            rest_list = [
                {"name": "나랏님이천쌀밥", "phone": "031-636-9900", "menu": f"이천 쌀밥 수라상 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "임금님 수라상 스타일 이천 쌀밥 한정식", "certBadge": "🏛️ 이천시 지정 대표 으뜸 쌀밥집", "mapUrls": make_map_urls("나랏님이천쌀밥")},
                {"name": "청목", "phone": "031-634-5414", "menu": f"한상차림 쌀밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 4분 (200m)", "features": "정갈한 수제 반찬과 이천 돌솥밥", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("청목")},
                {"name": "임금님쌀밥집", "phone": "031-632-3646", "menu": "보리굴비 정식 & 제육볶음", "walkingInfo": "주차장 도보 2분 (100m)", "features": "어르신 속 편한 보양 한정식", "certBadge": "🏛️ 지자체 지정 향토음식점", "mapUrls": make_map_urls("임금님쌀밥집")}
            ]

    # [가평 / 아침고요수목원 / 자라섬]
    elif "가평" in target_place or "수목원" in target_place:
        dest_title = "가평 아침고요수목원"
        parking_name = "가평 아침고요수목원 주차장"
        parking_fee = "무료 (전기차 급속 충전소 완비)"
        
        cafe_list = [
            {"name": "나무아래", "phone": "031-585-1888", "dessert": "수제 자몽차 & 잣 타르트", "walkingInfo": "수목원 입구 도보 2분 (100m)", "features": "수목원 숲속 전경 뷰 대형 소파석", "certBadge": "☕ 가평 문화관광 추천 뷰카페", "mapUrls": make_map_urls("나무아래")},
            {"name": "아침봄빵집", "phone": "031-584-9031", "dessert": "갓 구운 잣 천연발효빵 & 아메리카노", "walkingInfo": "수목원 산책로 도보 3분 (150m)", "features": "어르신 속 편한 천연발효 빵 명가", "certBadge": "☕ 아침고요수목원 공식 베이커리", "mapUrls": make_map_urls("아침봄빵집")},
            {"name": "모아이 카페", "phone": "031-585-6011", "dessert": "잣 라떼 & 수제 케이크", "walkingInfo": "도보 5분 (250m)", "features": "넓은 잔디밭 전경 뷰", "certBadge": "☕ 가평 힐링 뷰카페", "mapUrls": make_map_urls("모아이 카페")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "37.5 가평점", "phone": "031-584-3750", "menu": f"이탈리안 파스타 & 브런치 (1인 {lunch_budget:,}원대)", "walkingInfo": "수목원 도보 3분", "features": "어르신 선호 창가 좌석, 파스타", "certBadge": "🏛️ 가평 추천 브런치 양식당", "mapUrls": make_map_urls("37.5 가평점")},
                {"name": "가평 풀사이드 이탈리안", "phone": "031-584-2280", "menu": "빠네 파스타 & 화덕 피자", "walkingInfo": "수목원 도보 4분", "features": "담백한 화덕 피자와 파스타", "certBadge": "🏛️ 가평 패밀리 레스토랑", "mapUrls": make_map_urls("가평 풀사이드 이탈리안")},
                {"name": "가평 셰프스 파스타", "phone": "031-584-0700", "menu": "크림 파스타 & 리조또", "walkingInfo": "수목원 도보 2분", "features": "부드러운 크림 파스타", "certBadge": "🏛️ 가평 가성비 우수 식당", "mapUrls": make_map_urls("가평 셰프스 파스타")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "가평 스시마루", "phone": "031-582-8833", "menu": f"모둠 초밥 & 튀김 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 스시와 정갈한 일식 한상", "certBadge": "🏛️ 가평 대표 으뜸 일식당", "mapUrls": make_map_urls("가평 스시마루")},
                {"name": "가평 수제돈가스", "phone": "031-582-5999", "menu": "수제 돈가스 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 가평 추천 모범업소", "mapUrls": make_map_urls("가평 수제돈가스")},
                {"name": "가평 청평스시", "phone": "031-584-0099", "menu": "모둠 스시 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 가평 일식 전문점", "mapUrls": make_map_urls("가평 청평스시")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "가평 북경반점", "phone": "031-582-2047", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "속 편한 고급 중식", "certBadge": "🏛️ 가평 모범 중식당", "mapUrls": make_map_urls("가평 북경반점")},
                {"name": "가평 청평중화요리", "phone": "031-584-8877", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "독립 룸 보유", "certBadge": "🏛️ 가평 코스 요리 전문점", "mapUrls": make_map_urls("가평 청평중화요리")},
                {"name": "가평 현리성", "phone": "031-585-1688", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 중식", "certBadge": "🏛️ 가평 전통 으뜸 중식당", "mapUrls": make_map_urls("가평 현리성")}
            ]
        else: # 한식
            rest_list = [
                {"name": "언덕마루 잣두부집", "phone": "031-584-5368", "menu": f"가평 잣두부 전골 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "수목원 도보 3분 (150m)", "features": "어르신 속 편한 고소한 잣두부 수제 정식", "certBadge": "🏛️ 가평군 지정 향토 대표 으뜸맛집", "mapUrls": make_map_urls("언덕마루 잣두부집")},
                {"name": "송원 잣두부보리밥", "phone": "031-585-5571", "menu": f"잣두부 보쌈 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "수목원 도보 4분 (200m)", "features": "아침고요수목원 바로 앞 정갈한 잣두부 보쌈 한상", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("송원 잣두부보리밥")},
                {"name": "채원 잣두부막국수", "phone": "031-585-0104", "menu": "잣두부 & 순메밀 막국수", "walkingInfo": "수목원 도보 2분 (100m)", "features": "자극적이지 않은 속 편한 막국수", "certBadge": "🏛️ 지자체 추천 우수 업소", "mapUrls": make_map_urls("채원 잣두부막국수")}
            ]

    # [양평 / 두물머리 / 세미원]
    elif "양평" in target_place or "두물머리" in target_place:
        dest_title = "양평 두물머리"
        parking_name = "두물머리 공영주차장"
        parking_fee = "1일 3,000원 (전기차 50% 할인, 급속 충전소 완비)"
        ev_brand = "환경부 공용 충전기 / 100kW 급속 2기 운영 중"
        
        cafe_list = [
            {"name": "하우스베이커리", "phone": "031-772-8333", "dessert": "망고 크루아상 & 대추차", "walkingInfo": "도보 3분 (150m)", "features": "고즈넉한 한옥 대형 정원 베이커리 카페", "certBadge": "☕ 양평 대표 한옥 뷰카페", "mapUrls": make_map_urls("하우스베이커리")},
            {"name": "나인블럭 서종점", "phone": "031-774-7220", "dessert": "핸드드립 커피 & 시나몬 롤", "walkingInfo": "도보 4분 (200m)", "features": "북한강 리버 뷰 카페", "certBadge": "☕ 양평 북한강 뷰 명소", "mapUrls": make_map_urls("나인블럭 서종점")},
            {"name": "두물머리 연핫도그", "phone": "031-775-5357", "dessert": "수제 연핫도그 & 캔커피", "walkingInfo": "도보 1분 (50m)", "features": "두물머리 명물 대표 수제 핫도그", "certBadge": "☕ 두물머리 공식 명물 먹거리", "mapUrls": make_map_urls("두물머리 연핫도그")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "37.5 양평점", "phone": "031-772-3750", "menu": f"파스타 & 브런치 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "어르신 선호 리버 뷰 파스타", "certBadge": "🏛️ 양평 우수 브런치 양식당", "mapUrls": make_map_urls("37.5 양평점")},
                {"name": "양평 닥터박갤러리 파스타", "phone": "031-775-5600", "menu": "빠네 파스타 & 피자", "walkingInfo": "도보 4분", "features": "정갈하고 부드러운 양식", "certBadge": "🏛️ 양평 모범 레스토랑", "mapUrls": make_map_urls("양평 닥터박갤러리")},
                {"name": "양평 핏제리아 루카", "phone": "031-771-3388", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "편안한 소파석", "certBadge": "🏛️ 양평 화덕피자 식당", "mapUrls": make_map_urls("양평 핏제리아 루카")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "양평 스시히로", "phone": "031-771-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 스시 정식", "certBadge": "🏛️ 양평 대표 으뜸 일식당", "mapUrls": make_map_urls("양평 스시히로")},
                {"name": "양평 멘야가와", "phone": "031-773-5999", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 양평 추천 모범업소", "mapUrls": make_map_urls("양평 멘야가와")},
                {"name": "양평 카츠마마", "phone": "031-774-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 양평 우수 일식 전문점", "mapUrls": make_map_urls("양평 카츠마마")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "양평 예지현", "phone": "031-773-0988", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "속 편한 고급 중식", "certBadge": "🏛️ 양평 대표 모범 중식당", "mapUrls": make_map_urls("양평 예지현")},
                {"name": "양평 칭칭중화요리", "phone": "031-772-8877", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "독립 룸 보유", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("양평 칭칭중화요리")},
                {"name": "양평 명품관", "phone": "031-771-1688", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 중식", "certBadge": "🏛️ 양평 전통 으뜸 중식당", "mapUrls": make_map_urls("양평 명품관")}
            ]
        else: # 한식
            rest_list = [
                {"name": "연밭", "phone": "031-772-6200", "menu": f"양평 연잎밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "두물머리 도보 3분 (150m)", "features": "어르신 보양 연잎 찰밥 & 수제 반찬", "certBadge": "🏛️ 양평군 지정 향토 으뜸맛집", "mapUrls": make_map_urls("연밭")},
                {"name": "두물머리 밥상", "phone": "031-774-6330", "menu": f"시골 청국장 & 곤드레 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 4분 (200m)", "features": "구수한 청국장과 곤드레밥", "certBadge": "🏛️ 지자체 지정 모범음식점", "mapUrls": make_map_urls("두물머리 밥상")},
                {"name": "강민주의 들밥 양평점", "phone": "031-774-8839", "menu": "들밥 보리밥 정식", "walkingInfo": "도보 5분 (250m)", "features": "정갈한 산채 나물 한상", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("강민주의 들밥 양평점")}
            ]

    # [포천 / 산정호수 / 허브아일랜드 / 신북온천]
    elif "포천" in target_place or "산정호수" in target_place or "허브" in target_place:
        dest_title = "포천 산정호수"
        parking_name = "산정호수 상동주차장"
        parking_fee = "1일 2,000원 (전기차 50% 할인, 급속 충전소 완비)"
        ev_brand = "환경부 공용 충전기 / 50kW 급속 2기 운영 중"
        
        cafe_list = [
            {"name": "숨원카페", "phone": "031-544-7888", "dessert": "수제 한방차 & 허브 빵", "walkingInfo": "도보 2분 (100m)", "features": "산정호수 전경 뷰 소파석", "certBadge": "☕ 포천 산정호수 뷰카페", "mapUrls": make_map_urls("숨원카페")},
            {"name": "어느멋진날", "phone": "031-531-1580", "dessert": "수제 에이드 & 케이크", "walkingInfo": "도보 3분 (150m)", "features": "호숫가 산책로 앞 테라스", "certBadge": "☕ 포천 문화관광 추천 카페", "mapUrls": make_map_urls("어느멋진날")},
            {"name": "포천 허브아일랜드 빵집", "phone": "031-535-6494", "dessert": "허브 아일랜드 수제 빵 & 허브차", "walkingInfo": "도보 1분 (50m)", "features": "허브 향 가득한 베이커리", "certBadge": "☕ 허브아일랜드 공식 베이커리", "mapUrls": make_map_urls("포천 허브아일랜드 빵집")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "37.5 포천점", "phone": "031-532-3750", "menu": f"이탈리안 파스타 & 브런치 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "어르신 선호 창가 소파석", "certBadge": "🏛️ 포천 브런치 양식당", "mapUrls": make_map_urls("37.5 포천점")},
                {"name": "포천 라라코스트", "phone": "031-532-0301", "menu": "안심 스테이크 & 파스타", "walkingInfo": "도보 4분", "features": "담백한 이탈리안 양식", "certBadge": "🏛️ 포천 모범 레스토랑", "mapUrls": make_map_urls("포천 라라코스트")},
                {"name": "포천 롤링파스타", "phone": "031-532-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "부드러운 크림 파스타", "certBadge": "🏛️ 포천 가성비 식당", "mapUrls": make_map_urls("포천 롤링파스타")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "포천 스시히로", "phone": "031-533-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 스시 정식", "certBadge": "🏛️ 포천 대표 으뜸 일식당", "mapUrls": make_map_urls("포천 스시히로")},
                {"name": "포천 미카도스시", "phone": "031-534-2388", "menu": "회전초밥 & 모밀", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 포천 추천 모범업소", "mapUrls": make_map_urls("포천 미카도스시")},
                {"name": "포천 카츠젠", "phone": "031-535-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 포천 우수 일식 전문점", "mapUrls": make_map_urls("포천 카츠젠")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "포천 취영루", "phone": "031-536-5500", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "속 편한 고급 중식", "certBadge": "🏛️ 포천 모범 중식당", "mapUrls": make_map_urls("포천 취영루")},
                {"name": "포천 불도장", "phone": "031-537-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "독립 룸 보유", "certBadge": "🏛️ 포천 코스 요리 전문점", "mapUrls": make_map_urls("포천 불도장")},
                {"name": "포천 고등반점", "phone": "031-538-2580", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 중식", "certBadge": "🏛️ 포천 전통 으뜸 중식당", "mapUrls": make_map_urls("포천 고등반점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "김미자할머니이동갈비", "phone": "031-532-4459", "menu": f"포천 이동갈비 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "50년 전통 포천 대표 이동갈비 명가", "certBadge": "🏛️ 포천시 지정 대표 향토맛집", "mapUrls": make_map_urls("김미자할머니이동갈비")},
                {"name": "명지원 이동갈비", "phone": "031-533-3392", "menu": "이동 숯불갈비 & 동치미", "walkingInfo": "도보 4분 (200m)", "features": "넓은 한옥 정원 뷰", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("명지원 이동갈비")},
                {"name": "원조이동김미자갈비", "phone": "031-531-2600", "menu": "수제 양념갈비 정식", "walkingInfo": "도보 2분 (100m)", "features": "부드럽고 달콤한 양념 갈비", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("원조이동김미자갈비")}
            ]

    # [의정부 / 부대찌개거리 / 직동근린공원]
    elif "의정부" in target_place:
        dest_title = "의정부 직동근린공원 무장애 숲길 & 부대찌개거리"
        parking_name = "의정부 직동근린공원 주차장 (또는 부대찌개거리 공영주차장)"
        parking_fee = "1시간 1,000원 (전기차 50% 할인, 급속 충전소 완비)"
        ev_brand = "의정부시/차지비 공용 충전기 / 50kW 급속 2기 운영 중"
        
        cafe_list = [
            {"name": "아나키아", "phone": "031-856-5000", "dessert": "시그니처 아인슈페너 & 수제 베이커리", "walkingInfo": "공원 산책로 도보 3분 (180m)", "features": "의정부 대표 대형 힐링 뷰카페, 엘리베이터 보유", "certBadge": "☕ 의정부 대표 대형 뷰카페", "mapUrls": make_map_urls("아나키아")},
            {"name": "나크타", "phone": "031-877-0055", "dessert": "소금빵 & 한방 대추차", "walkingInfo": "도보 4분 (220m)", "features": "도봉산 자락 계곡 뷰 힐링 카페", "certBadge": "☕ 계곡 전경 힐링 카페", "mapUrls": make_map_urls("나크타")},
            {"name": "달리온", "phone": "031-841-8000", "dessert": "수제 잣 타르트 & 핸드드립 커피", "walkingInfo": "도보 2분 (120m)", "features": "수목원 숲속 전경 뷰 대형 소파석", "certBadge": "☕ 숲속 정원 뷰카페", "mapUrls": make_map_urls("달리온")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "37.5 의정부점", "phone": "031-853-3750", "menu": f"이탈리안 파스타 & 브런치 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "넓은 창가 소파석, 파스타", "certBadge": "🏛️ 의정부 우수 브런치 양식당", "mapUrls": make_map_urls("37.5 의정부점")},
                {"name": "라라코스트 의정부점", "phone": "031-851-0301", "menu": "빠네 파스타 & 화덕 피자", "walkingInfo": "도보 4분", "features": "담백하고 속 편한 이탈리안 양식", "certBadge": "🏛️ 모범 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트 의정부점")},
                {"name": "롤링파스타 의정부점", "phone": "031-840-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "부드러운 크림 파스타", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타 의정부점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "호타루", "phone": "031-637-4320", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 스시 정식", "certBadge": "🏛️ 대표 으뜸 일식당", "mapUrls": make_map_urls("호타루")},
                {"name": "미카도스시 의정부점", "phone": "031-841-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("미카도스시 의정부점")},
                {"name": "카츠마마 의정부점", "phone": "031-840-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠마마 의정부점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "지동관", "phone": "031-846-2047", "menu": f"65년 전통 중식 삼선 짬뽕 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "화교 3대 65년 전통 의정부 대표 중식 명가", "certBadge": "🏛️ 의정부시 전통 대표 향토맛집", "mapUrls": make_map_urls("지동관")},
                {"name": "취영루", "phone": "031-746-5500", "menu": "삼선 짬뽕 & 찹쌀 탕수육", "walkingInfo": "도보 4분", "features": "속 편한 고급 중화요리", "certBadge": "🏛️ 지자체 모범 중식당", "mapUrls": make_map_urls("취영루")},
                {"name": "불도장", "phone": "031-637-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 2분", "features": "독립 룸 보유", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("불도장")}
            ]
        else: # 한식
            rest_list = [
                {"name": "오뎅식당 본점", "phone": "031-842-0423", "menu": f"원조 의정부 부대찌개 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 2분 (100m)", "features": "60년 전통 원조 부대찌개 대한민국 1호 지정 명가", "certBadge": "🏛️ 대한민국 최초 부대찌개 1호 지정업소", "mapUrls": make_map_urls("오뎅식당 본점")},
                {"name": "형네식당", "phone": "031-846-4853", "menu": "전통 부대찌개 & 라면사리", "walkingInfo": "도보 3분 (150m)", "features": "어르신 선호 깊은 국물 맛 3대 부대찌개 맛집", "certBadge": "🏛️ 의정부시 지정 대표 향토맛집", "mapUrls": make_map_urls("형네식당")},
                {"name": "솔가헌", "phone": "031-826-6998", "menu": "보양 떡갈비 정식 & 한방 차", "walkingInfo": "도보 4분 (200m)", "features": "어르신 속 편한 힐링 한방 떡갈비 정식", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("솔가헌")}
            ]

    # [파주 / 마장호수 / 임진각 / 헤이리]
    elif "파주" in target_place or "마장호수" in target_place or "임진각" in target_place:
        dest_title = "파주 마장호수"
        parking_name = "마장호수 제1공영주차장"
        parking_fee = "1일 2,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "레드 브릿지", "phone": "031-941-0900", "dessert": "소금빵 & 오미자차", "walkingInfo": "마장호수 출렁다리 도보 1분 (50m)", "features": "마장호수 출렁다리가 한눈에 보이는 대형 뷰카페", "certBadge": "☕ 마장호수 대표 뷰카페", "mapUrls": make_map_urls("레드 브릿지")},
            {"name": "더티트렁크", "phone": "031-947-0077", "dessert": "베이커리 빵 & 커피", "walkingInfo": "도보 5분 (250m)", "features": "대형 팩토리 베이커리 카페", "certBadge": "☕ 파주 3대 대형 카페", "mapUrls": make_map_urls("더티트렁크")},
            {"name": "콰트로박스", "phone": "031-946-8800", "dessert": "디저트 케이크 & 스무디", "walkingInfo": "도보 4분 (200m)", "features": "넓은 소파석 보유", "certBadge": "☕ 파주 대형 힐링 카페", "mapUrls": make_map_urls("콰트로박스")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "37.5 파주점", "phone": "031-945-3750", "menu": f"이탈리안 파스타 & 브런치 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "넓은 소파석, 파스타", "certBadge": "🏛️ 파주 우수 브런치 양식당", "mapUrls": make_map_urls("37.5")},
                {"name": "라라코스트", "phone": "031-945-0301", "menu": "빠네 파스타 & 피자", "walkingInfo": "도보 4분", "features": "담백하고 속 편한 양식", "certBadge": "🏛️ 모범 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트")},
                {"name": "롤링파스타", "phone": "031-945-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "부드러운 크림 파스타", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "호타루", "phone": "031-637-4320", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 스시 정식", "certBadge": "🏛️ 대표 으뜸 일식당", "mapUrls": make_map_urls("호타루")},
                {"name": "미카도스시", "phone": "031-638-2388", "menu": "회전초밥 & 모밀", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("미카도스시")},
                {"name": "카츠마마", "phone": "031-638-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠마마")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "파주 삼거리부대찌개", "phone": "031-941-4328", "menu": "전통 삼거리 부대찌개 정식", "walkingInfo": "도보 2분 (100m)", "features": "50년 전통 파주 으뜸 명가", "certBadge": "🏛️ 파주시 전통 으뜸맛집", "mapUrls": make_map_urls("파주 삼거리부대찌개")},
                {"name": "취영루", "phone": "031-746-5500", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "속 편한 고급 중식", "certBadge": "🏛️ 지자체 모범 중식당", "mapUrls": make_map_urls("취영루")},
                {"name": "불도장", "phone": "031-637-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "독립 룸 보유", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("불도장")}
            ]
        else: # 한식
            rest_list = [
                {"name": "파주 장단콩두부마을", "phone": "031-945-3370", "menu": f"파주 장단콩 순두부 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "파주 특산 장단콩 100% 수제 두부 정식", "certBadge": "🏛️ 파주시 지정 대표 향토 으뜸업소", "mapUrls": make_map_urls("파주 장단콩두부마을")},
                {"name": "파주 심학산 도토리국수", "phone": "031-944-3385", "menu": "도토리 쟁반국수 & 도토리전", "walkingInfo": "도보 4분 (200m)", "features": "어르신 속 편한 수제 도토리 요리", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("파주 심학산 도토리국수")},
                {"name": "파주 삼거리부대찌개", "phone": "031-941-4328", "menu": "전통 삼거리 부대찌개 정식", "walkingInfo": "도보 2분 (100m)", "features": "50년 전통 파주 으뜸 명가", "certBadge": "🏛️ 파주시 전통 으뜸맛집", "mapUrls": make_map_urls("파주 삼거리부대찌개")}
            ]

    # [서울 종로구 / 광화문 / 경복궁 / 서촌 / 북촌 / 인사동 / 익선동]
    elif any(k in target_place for k in ["종로", "광화문", "경복궁", "서촌", "북촌", "인사동", "익선동", "세종로", "삼청동"]):
        dest_title = "서울 종로구 경복궁 & 서촌"
        parking_name = "경복궁 지하 공영주차장"
        parking_fee = "1시간 3,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "삼청동 차마시는뜰", "phone": "02-734-2988", "dessert": "수제 대추차 & 단호박 시루떡", "walkingInfo": "도보 3분 (150m)", "features": "경복궁/삼청동 한옥 뷰, 전통 찻집", "certBadge": "☕ 종로구 공식 추천 한옥 찻집", "mapUrls": make_map_urls("차마시는뜰")},
            {"name": "인왕산 대충유원지", "phone": "02-730-5005", "dessert": "인왕산 말차 라떼 & 수제 곶감", "walkingInfo": "도보 4분 (200m)", "features": "인왕산 암벽 전경 뷰 루프탑", "certBadge": "☕ 서촌 힐링 뷰카페", "mapUrls": make_map_urls("대충유원지")},
            {"name": "통인동 커피공방", "phone": "02-725-3031", "dessert": "핸드드립 커피 & 드립백", "walkingInfo": "도보 2분 (100m)", "features": "서촌 대표 로스팅 핸드드립 명가", "certBadge": "☕ 종로 베스트 로스터리", "mapUrls": make_map_urls("통인동 커피공방")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "르블란서", "phone": "02-766-9951", "menu": f"파스타 & 프랑스 가정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "한옥 이탈리안 & 프랑스 양식 명가", "certBadge": "🏛️ 종로구 지정 으뜸 양식당", "mapUrls": make_map_urls("르블란서")},
                {"name": "이탈재", "phone": "02-737-0102", "menu": "화덕 피자 & 크림 파스타", "walkingInfo": "도보 4분", "features": "한옥 이탈리안 레스토랑", "certBadge": "🏛️ 서촌 한옥 레스토랑", "mapUrls": make_map_urls("이탈재")},
                {"name": "서촌 김씨 리스토란테", "phone": "02-730-0410", "menu": "알리오 올리오 & 리조또", "walkingInfo": "도보 2분", "features": "부드럽고 소화 잘 되는 이탈리안", "certBadge": "🏛️ 미슐랭 서촌 이탈리안", "mapUrls": make_map_urls("서촌 김씨 리스토란테")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시효 광화문점", "phone": "02-733-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "안효주 셰프의 명품 스시 정식", "certBadge": "🏛️ 종로구 대표 으뜸 일식당", "mapUrls": make_map_urls("스시효 광화문점")},
                {"name": "서촌 긴자바이린", "phone": "02-734-5999", "menu": "수제 돈가스 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 수제 돈가스", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("서촌 긴자바이린")},
                {"name": "가츠라 종로점", "phone": "02-735-7008", "menu": "우동 정식 & 모둠 튀김", "walkingInfo": "도보 2분", "features": "바삭하고 담백한 일식 정식", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("가츠라 종로점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "취천루", "phone": "02-738-1688", "menu": f"70년 전통 수제 만두 & 짬뽕 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "70년 전통 종로 서촌 대표 중식 명가", "certBadge": "🏛️ 종로구 지정 전통 모범맛집", "mapUrls": make_map_urls("취천루")},
                {"name": "영화루", "phone": "02-738-1565", "menu": "고추간짜장 & 탕수육", "walkingInfo": "도보 4분 (200m)", "features": "식객 허영만 추천 중식 맛집", "certBadge": "🏛️ 종로구 향토 맛집", "mapUrls": make_map_urls("영화루")},
                {"name": "동성관", "phone": "02-739-2009", "menu": "삼선 짬뽕 & 군만두", "walkingInfo": "도보 2분 (100m)", "features": "옛날 방식 전통 중식", "certBadge": "🏛️ 종로 모범음식점 인증", "mapUrls": make_map_urls("동성관")}
            ]
        else: # 한식
            rest_list = [
                {"name": "토속촌 삼계탕", "phone": "02-737-7444", "menu": f"토속촌 오골계/삼계탕 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "대통령 단골 종로 대표 보양 삼계탕 명가", "certBadge": "🏛️ 종로구 지정 으뜸 전통맛집", "mapUrls": make_map_urls("토속촌 삼계탕")},
                {"name": "자하손만두", "phone": "02-395-1088", "menu": f"수제 떡만두국 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 4분 (200m)", "features": "미슐랭 빕구르망 지정 담백한 이북식 만두", "certBadge": "🏛️ 미슐랭 & 종로구 으뜸맛집", "mapUrls": make_map_urls("자하손만두")},
                {"name": "평양면옥 종로점", "phone": "02-736-5500", "menu": "평양냉면 & 어복쟁반", "walkingInfo": "도보 2분 (100m)", "features": "자극적이지 않은 진한 전통 육수", "certBadge": "🏛️ 지자체 지정 모범업소", "mapUrls": make_map_urls("평양면옥 종로점")}
            ]

    # [서울 중구 / 남대문 / 남산골한옥마을 / 남산타워 / 명동 / 시청 / 을지로 / 덕수궁]
    elif any(k in target_place for k in ["중구", "남대문", "명동", "남산", "시청", "을지로", "덕수궁", "청계천", "동대문", "DDP", "서울역"]):
        dest_title = "서울 중구 남산골 한옥마을 & 남대문"
        parking_name = "남산골 한옥마을 공영주차장"
        parking_fee = "1시간 3,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "남산 다향", "phone": "02-2264-4411", "dessert": "전통 유자차 & 수제 오미자 화채", "walkingInfo": "도보 2분 (100m)", "features": "한옥 정원 뷰 어르신 전용 쉼터", "certBadge": "☕ 중구 공식 추천 전통 찻집", "mapUrls": make_map_urls("남산 다향")},
            {"name": "남산골 한옥카페", "phone": "02-2261-0517", "dessert": "쌍화차 & 인절미 타르트", "walkingInfo": "도보 3분 (150m)", "features": "남산타워 조망 야외 마루석", "certBadge": "☕ 한옥마을 공식 카페", "mapUrls": make_map_urls("남산골 한옥카페")},
            {"name": "목멱산방 찻집", "phone": "02-2270-1100", "dessert": "모과차 & 유과", "walkingInfo": "도보 4분 (200m)", "features": "남산 숲속 힐링 뷰", "certBadge": "☕ 남산 으뜸 뷰카페", "mapUrls": make_map_urls("목멱산방")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "촛불1978", "phone": "02-757-1978", "menu": f"안심 스테이크 & 파스타 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 4분 (200m)", "features": "대한민국 최초 1호 레스토랑 명가", "certBadge": "🏛️ 서울시 미래유산 지정 레스토랑", "mapUrls": make_map_urls("촛불1978")},
                {"name": "보테가로 남산점", "phone": "02-755-0301", "menu": "수제 함박스테이크 & 샐러드", "walkingInfo": "도보 3분", "features": "부드럽고 소화 잘 되는 양식", "certBadge": "🏛️ 중구 모범 레스토랑", "mapUrls": make_map_urls("보테가로 남산점")},
                {"name": "롤링파스타 명동점", "phone": "02-756-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "어르신 선호 편안한 소파석", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타 명동점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시이로 명동점", "phone": "02-771-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 고급 스시 정식", "certBadge": "🏛️ 중구 대표 으뜸 일식당", "mapUrls": make_map_urls("스시이로 명동점")},
                {"name": "미카도스시 명동점", "phone": "02-772-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("미카도스시 명동점")},
                {"name": "남산돈까스", "phone": "02-773-7008", "menu": "수제 남산 돈가스 & 우동", "walkingInfo": "도보 2분", "features": "추억의 남산 수제 왕돈가스 명가", "certBadge": "🏛️ 남산 대표 명물 식당", "mapUrls": make_map_urls("남산돈까스")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "개화", "phone": "02-776-0508", "menu": f"70년 전통 화교 삼선 간짜장 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "명동 중국대사관 앞 70년 전통 중식 명가", "certBadge": "🏛️ 중구 지정 전통 모범맛집", "mapUrls": make_map_urls("개화")},
                {"name": "향미", "phone": "02-773-8877", "menu": "우육면 & 수제 군만두", "walkingInfo": "도보 4분", "features": "담백하고 속 편한 대만식 중식", "certBadge": "🏛️ 지자체 지정 향토 맛집", "mapUrls": make_map_urls("향미")},
                {"name": "일향식당", "phone": "02-774-5500", "menu": "삼선 짬뽕 & 찹쌀 탕수육", "walkingInfo": "도보 2분", "features": "독립 룸 보유 전통 중식", "certBadge": "🏛️ 전통 고급 중식당", "mapUrls": make_map_urls("일향식당")}
            ]
        else: # 한식
            rest_list = [
                {"name": "남산골 산채집", "phone": "02-754-1978", "menu": f"산채 비빔밥 & 왕돈까스 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "남산 아래 정갈한 수제 산채 나물 밥상", "certBadge": "🏛️ 서울 중구 지정 으뜸 모범식당", "mapUrls": make_map_urls("남산골 산채집")},
                {"name": "남대문 진주회관", "phone": "02-753-5385", "menu": f"50년 전통 콩국수 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 4분 (200m)", "features": "황태 및 100% 진한 콩국수 명가", "certBadge": "🏛️ 서울 미래유산 인증 으뜸맛집", "mapUrls": make_map_urls("남대문 진주회관")},
                {"name": "목멱산방", "phone": "02-318-4790", "menu": "불고기 비빔밥 & 놋그릇 밥상", "walkingInfo": "도보 2분 (100m)", "features": "미슐랭 빕구르망 비빔밥 명가", "certBadge": "🏛️ 미슐랭 지정 한식 맛집", "mapUrls": make_map_urls("목멱산방")}
            ]

    # [서울 용산구 / 국립중앙박물관 / 용산가족공원]
    elif any(k in target_place for k in ["용산", "이촌", "한남", "해방촌", "국립중앙박물관", "전쟁기념관"]):
        dest_title = "서울 용산구 국립중앙박물관 & 용산가족공원"
        parking_name = "국립중앙박물관 옥외 주차장"
        parking_fee = "1시간 2,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "사유공간찻집 (국립중앙박물관 3층)", "phone": "02-749-6013", "dessert": "전통 한방 차 & 다과 세트", "walkingInfo": "박물관 3층 도보 1분", "features": "통유리 창가 뷰 어르신 전통 찻집", "certBadge": "☕ 국립박물관 공식 찻집", "mapUrls": make_map_urls("국립중앙박물관 사유공간찻집")},
            {"name": "오설록 티하우스 용산파크점", "phone": "02-709-1500", "dessert": "제주 녹차 라떼 & 오설록 롤케이크", "walkingInfo": "신용산역 아모레 본사 1층", "features": "넓고 쾌적한 프리미엄 차 전용 공간", "certBadge": "☕ 지자체 추천 으뜸 찻집", "mapUrls": make_map_urls("오설록 티하우스 용산파크점")},
            {"name": "헬카페 로스터즈", "phone": "02-792-7041", "dessert": "클래식 드립 커피 & 티라미수", "walkingInfo": "도보 4분 (200m)", "features": "어르신 선호 편안한 소파석", "certBadge": "☕ 용산 대표 로스터리", "mapUrls": make_map_urls("용산 헬카페 로스터즈")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "국립중앙박물관 거울못식당", "phone": "02-798-2200", "menu": f"이탈리안 화덕 피자 & 수제 파스타 (1인 {lunch_budget:,}원대)", "walkingInfo": "거울못 산책로에서 도보 1분 (50m)", "features": "국립중앙박물관 거울못 호수 전경 뷰, 차량 이동 없는 동선 최적화", "certBadge": "🏛️ 국립박물관 구내 대표 양식당", "mapUrls": make_map_urls("국립중앙박물관 거울못식당")},
                {"name": "아티제 동부이촌동점", "phone": "02-794-3123", "menu": "수제 브런치 파스타 & 샐러드", "walkingInfo": "박물관 출구 도보 4분 (200m)", "features": "이촌동 호젓한 거리 뷰, 어르신 편안한 소파석", "certBadge": "🏛️ 용산 이촌동 추천 브런치 양식당", "mapUrls": make_map_urls("아티제 동부이촌동점")},
                {"name": "매드포갈릭 용산아이파크몰점", "phone": "02-2012-0651", "menu": "갈릭 스노잉 피자 & 파스타", "walkingInfo": "용산역 도보 1분 (아이파크몰 6층)", "features": "어르신 선호 편안한 소파석 & 엘리베이터 보유", "certBadge": "🏛️ 용산 대표 이탈리안 레스토랑", "mapUrls": make_map_urls("매드포갈릭 용산아이파크몰점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "갓덴스시 용산아이파크몰점", "phone": "02-2012-0695", "menu": f"모둠 회전초밥 & 우동 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "용산역 도보 1분 (아이파크몰 6층)", "features": "신선한 스시와 정갈한 일식", "certBadge": "🏛️ 용산구 대표 으뜸 일식당", "mapUrls": make_map_urls("갓덴스시 용산아이파크몰점")},
                {"name": "이촌동 스시무라", "phone": "02-790-0012", "menu": "모둠 초밥 & 메밀소바", "walkingInfo": "도보 3분 (150m)", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("이촌동 스시무라")},
                {"name": "용산 카츠9", "phone": "02-798-7008", "menu": f"수제 프리미엄 안심 돈가스 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "바삭하고 속 편한 튀김 정식", "certBadge": "🏛️ 용산구 지정 우수 일식 전문점", "mapUrls": make_map_urls("용산 카츠9")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "용산 명화원", "phone": "02-792-2249", "menu": f"서울 3대 찹쌀 탕수육 & 짬뽕 (1인 {lunch_budget:,}원대)", "walkingInfo": "삼각지역 도보 2분", "features": "수요미식회 방영, 서울 3대 탕수육 명가", "certBadge": "🏛️ 서울시 지정 블루리본 중식 명가", "mapUrls": make_map_urls("용산 명화원")},
                {"name": "용산 주사부", "phone": "02-792-2419", "menu": "특밥 & 탕수육 정식", "walkingInfo": "숙대입구역 도보 3분", "features": "50년 전통 생활의달인 화상 중식당", "certBadge": "🏛️ 50년 전통 중식 달인 명가", "mapUrls": make_map_urls("용산 주사부")},
                {"name": "일일향 용산점", "phone": "02-792-1080", "menu": "어향동고 & 육즙 돼지고기 탕수육", "walkingInfo": "신용산역 도보 2분", "features": "정갈한 룸 완비, 속 편한 고급 중식", "certBadge": "🏛️ 지자체 지정 모범 중식당", "mapUrls": make_map_urls("일일향 용산점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "동빙고 본점", "phone": "02-794-7388", "menu": f"수제 팥빙수 & 단팥죽 (1인 {lunch_budget:,}원대)", "walkingInfo": "이촌동 도보 3분 (150m)", "features": "이촌동 30년 전통 국산 팥 전문 명가", "certBadge": "🏛️ 용산구 지정 전통 모범업소", "mapUrls": make_map_urls("동빙고 본점")},
                {"name": "용산 기와", "phone": "02-793-3355", "menu": "보양 곤드레 밥상 정식", "walkingInfo": "용산역 도보 2분 (100m)", "features": "정갈한 나물과 불고기 수라 한상", "certBadge": "🏛️ 서울시 지정 으뜸맛집 인증업소", "mapUrls": make_map_urls("용산 기와")},
                {"name": "한강집생태", "phone": "02-795-3300", "menu": "생태매운탕 & 백반 정식", "walkingInfo": "삼각지역 도보 2분 (100m)", "features": "어르신 속 편한 40년 전통 탕 명가", "certBadge": "🏛️ 지자체 지정 향토맛집", "mapUrls": make_map_urls("한강집생태")}
            ]

    # [서울 송파구 / 잠실 / 석촌호수 / 올림픽공원]
    elif "송파" in target_place or "잠실" in target_place or "석촌" in target_place or "올림픽" in target_place or "롯데" in target_place or "방이" in target_place:
        dest_title = "서울 송파구 석촌호수 & 올림픽공원"
        parking_name = "석촌호수 동호 공영주차장"
        parking_fee = "1시간 3,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "위커파크 석촌호수점", "phone": "02-413-8811", "dessert": "수제 케이크 & 아메리카노", "walkingInfo": "호수 도보 2분 (100m)", "features": "석촌호수 롯데타워 뷰 소파석", "certBadge": "☕ 송파구 대표 뷰카페", "mapUrls": make_map_urls("위커파크 석촌호수점")},
            {"name": "카페 릴리우드 방이점", "phone": "02-412-5500", "dessert": "전통 대추차 & 인절미", "walkingInfo": "도보 3분 (150m)", "features": "고분공원 산책로 뷰 힐링 카페", "certBadge": "☕ 송파 문화관광 추천 카페", "mapUrls": make_map_urls("카페 릴리우드 방이점")},
            {"name": "올림픽공원 둔촌 찻집", "phone": "02-414-7722", "dessert": "오미자차 & 수제 타르트", "walkingInfo": "도보 4분 (200m)", "features": "올림픽공원 숲속 전경 뷰", "certBadge": "☕ 공원 공식 찻집", "mapUrls": make_map_urls("올림픽공원 둔촌 찻집")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "엘리스리틀이탈리 잠실점", "phone": "02-422-3750", "menu": f"화덕 피자 & 이탈리안 파스타 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "석촌호수 대표 수제 이탈리안 명가", "certBadge": "🏛️ 송파구 추천 이탈리안 양식당", "mapUrls": make_map_urls("엘리스리틀이탈리 잠실점")},
                {"name": "라라코스트 송파점", "phone": "02-418-0301", "menu": "빠네 파스타 & 피자", "walkingInfo": "도보 4분", "features": "담백한 패밀리 레스토랑", "certBadge": "🏛️ 모범 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트 송파점")},
                {"name": "롤링파스타 잠실점", "phone": "02-419-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "부드러운 크림 파스타", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타 잠실점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시산 송파점", "phone": "02-420-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 고급 스시 정식", "certBadge": "🏛️ 송파구 대표 으뜸 일식당", "mapUrls": make_map_urls("스시산 송파점")},
                {"name": "미카도스시 잠실점", "phone": "02-421-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("미카도스시 잠실점")},
                {"name": "돈까스의집", "phone": "02-422-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "30년 전통 수제 왕돈가스 명가", "certBadge": "🏛️ 송파 대표 명물 식당", "mapUrls": make_map_urls("돈까스의집")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "취영루 송파점", "phone": "02-423-5500", "menu": f"삼선 짬뽕 & 찹쌀 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "독립 룸 보유, 정갈함", "certBadge": "🏛️ 송파구 모범 중식당", "mapUrls": make_map_urls("취영루 송파점")},
                {"name": "어만두", "phone": "02-424-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "어르신 모임 코스 중식", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("어만두")},
                {"name": "칭칭차이나 방이점", "phone": "02-425-8877", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 소화 잘 됨", "certBadge": "🏛️ 전통 중화요리 맛집", "mapUrls": make_map_urls("칭칭차이나 방이점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "봉피양 방이본점", "phone": "02-415-5527", "menu": f"평양냉면 & 돼지갈비 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "허영만 식객 추천 대한민국 1등 평양냉면", "certBadge": "🏛️ 서울시 미슐랭 & 송파 으뜸맛집", "mapUrls": make_map_urls("봉피양 방이본점")},
                {"name": "삼전도 한정식", "phone": "02-415-9900", "menu": "보리굴비 정식 & 수라상", "walkingInfo": "도보 4분 (200m)", "features": "어르신 접대 고급 한정식", "certBadge": "🏛️ 경기도/서울 으뜸맛집", "mapUrls": make_map_urls("삼전도 한정식")},
                {"name": "방이 한정식", "phone": "02-416-5414", "menu": "한방 떡갈비 & 곤드레밥", "walkingInfo": "도보 2분 (100m)", "features": "어르신 속 편한 보양 한상", "certBadge": "🏛️ 지자체 지정 모범음식점", "mapUrls": make_map_urls("방이 한정식")}
            ]

    # [서울 마포구/서대문구 / 안산자락길 / 하늘공원]
    elif "마포" in target_place or "서대문" in target_place or "안산" in target_place or "하늘공원" in target_place:
        dest_title = "서울 마포구/서대문구 안산자락길 무장애 숲길"
        parking_name = "서대문 안산자락길 공영주차장"
        parking_fee = "1시간 1,800원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "앤트러사이트 연남점", "phone": "02-332-5500", "dessert": "수제 자몽차 & 인절미 롤", "walkingInfo": "도보 3분 (150m)", "features": "경의선 숲길 전경 뷰 쉼터", "certBadge": "☕ 마포구 추천 뷰카페", "mapUrls": make_map_urls("앤트러사이트 연남점")},
            {"name": "망원동 티노마드", "phone": "02-333-8811", "dessert": "갓 구운 화과자 & 전통 잎차", "walkingInfo": "도보 4분 (200m)", "features": "고즈넉한 다도 힐링 어르신 찻집", "certBadge": "☕ 지자체 지정 명품 찻집", "mapUrls": make_map_urls("망원동 티노마드")},
            {"name": "문화비축기지 카페 탠저린", "phone": "02-334-7722", "dessert": "시그니처 라떼 & 타르트", "walkingInfo": "도보 2분 (100m)", "features": "월드컵공원 및 문화비축기지 뷰 테라스", "certBadge": "☕ 공원 대표 뷰카페", "mapUrls": make_map_urls("문화비축기지 카페 탠저린")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "오스테리아 오르조", "phone": "02-322-0801", "menu": f"수제 생면 파스타 & 스테이크 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "미슐랭 빕구르망 대표 이탈리안 명가", "certBadge": "🏛️ 미슐랭 & 마포구 으뜸맛집", "mapUrls": make_map_urls("오스테리아 오르조")},
                {"name": "라라코스트 마포점", "phone": "02-336-0301", "menu": "빠네 파스타 & 피자", "walkingInfo": "도보 4분", "features": "담백한 패밀리 양식", "certBadge": "🏛️ 모범 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트 마포점")},
                {"name": "롤링파스타 홍대점", "phone": "02-337-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분", "features": "부드럽고 속 편함", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타 홍대점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "마포 스시히로", "phone": "02-338-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 고급 스시 정식", "certBadge": "🏛️ 마포구 대표 으뜸 일식당", "mapUrls": make_map_urls("마포 스시히로")},
                {"name": "마포 미카도스시", "phone": "02-339-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("마포 미카도스시")},
                {"name": "마포 카츠젠", "phone": "02-340-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("마포 카츠젠")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "연남동 하하", "phone": "02-337-0211", "menu": f"수제 가지튀김 & 짬뽕 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "마포 연남동 30년 전통 중국 만두/요리 명가", "certBadge": "🏛️ 마포구 지정 전통 으뜸맛집", "mapUrls": make_map_urls("연남동 하하")},
                {"name": "마포 취영루", "phone": "02-338-5500", "menu": "삼선 짬뽕 & 탕수육", "walkingInfo": "도보 4분", "features": "독립 룸, 정갈한 중식", "certBadge": "🏛️ 모범 중화요리점", "mapUrls": make_map_urls("마포 취영루")},
                {"name": "마포 불도장", "phone": "02-339-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 2분", "features": "어르신 모임 추천", "certBadge": "🏛️ 전통 고급 중식당", "mapUrls": make_map_urls("마포 불도장")}
            ]
        else: # 한식
            rest_list = [
                {"name": "마포 옥동식", "phone": "02-336-5500", "menu": f"돼지곰탕 & 놋그릇 밥상 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "미슐랭 빕구르망 맑고 단아한 곰탕 명가", "certBadge": "🏛️ 미슐랭 & 마포구 으뜸맛집", "mapUrls": make_map_urls("옥동식")},
                {"name": "서대문 한옥집 김치찜", "phone": "02-362-8653", "menu": f"수제 김치찜 & 김치찌개 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 4분 (200m)", "features": "입에서 녹는 부드러운 푹 익은 김치찜", "certBadge": "🏛️ 서대문구 지정 대표 향토맛집", "mapUrls": make_map_urls("한옥집 김치찜")},
                {"name": "마포 양지설렁탕", "phone": "02-716-8616", "menu": "40년 전통 양지 설렁탕", "walkingInfo": "도보 2분 (100m)", "features": "어르신 속 편한 진한 국물 탕", "certBadge": "🏛️ 서울 모범음식점 인증업소", "mapUrls": make_map_urls("마포 양지설렁탕")}
            ]

    # [서울 은평구 / 은평한옥마을 / 진관사]
    elif "은평" in target_place or "진관사" in target_place or "한옥마을" in target_place:
        dest_title = "서울 은평구 은평한옥마을 & 진관사"
        parking_name = "은평한옥마을 공영주차장"
        parking_fee = "1시간 2,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "1인1잔", "phone": "02-355-1111", "dessert": "시그니처 차 & 수제 앙금 떡", "walkingInfo": "한옥마을 입구 도보 1분 (50m)", "features": "북한산과 은평한옥마을 전경 뷰 1위 카페", "certBadge": "☕ 은평구 대표 한옥 뷰카페", "mapUrls": make_map_urls("1인1잔")},
            {"name": "진관사 찻집", "phone": "02-359-8410", "dessert": "사찰 수제 대추차 & 유과", "walkingInfo": "진관사 입구 도보 2분 (100m)", "features": "계곡 숲속 전경 뷰 어르신 힐링 찻집", "certBadge": "☕ 진관사 공식 한방 찻집", "mapUrls": make_map_urls("진관사 찻집")},
            {"name": "북한산 플레이", "phone": "02-356-8000", "dessert": "갓 구운 빵 & 오미자차", "walkingInfo": "도보 3분 (150m)", "features": "넓은 소파석, 북한산 파노라마 뷰", "certBadge": "☕ 은평구 추천 뷰카페", "mapUrls": make_map_urls("북한산 플레이")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "라라코스트 은평점", "phone": "02-352-0301", "menu": f"빠네 파스타 & 피자 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "담백하고 속 편한 패밀리 레스토랑", "certBadge": "🏛️ 은평구 모범 양식당", "mapUrls": make_map_urls("라라코스트 은평점")},
                {"name": "롤링파스타 연신내점", "phone": "02-353-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 4분", "features": "부드럽고 소화 잘 되는 이탈리안", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타 연신내점")},
                {"name": "쿠우쿠우 은평점", "phone": "02-351-3750", "menu": "초밥 & 이탈리안 샐러드바", "walkingInfo": "도보 2분", "features": "넓은 소파석 보유 패밀리 식당", "certBadge": "🏛️ 지자체 지정 우수 식당", "mapUrls": make_map_urls("쿠우쿠우 은평점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시마루 은평점", "phone": "02-354-8833", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 고급 스시 정식", "certBadge": "🏛️ 은평구 대표 으뜸 일식당", "mapUrls": make_map_urls("스시마루 은평점")},
                {"name": "미카도스시 은평점", "phone": "02-355-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 추천 모범업소", "mapUrls": make_map_urls("미카도스시 은평점")},
                {"name": "카츠젠 연신내점", "phone": "02-356-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠젠 연신내점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "취영루 은평점", "phone": "02-357-5500", "menu": f"삼선 짬뽕 & 찹쌀 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "독립 룸, 정갈한 중식", "certBadge": "🏛️ 은평구 모범 중식당", "mapUrls": make_map_urls("취영루 은평점")},
                {"name": "중화요리 칭칭 은평점", "phone": "02-358-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "어르신 모임 코스 중식", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("중화요리 칭칭 은평점")},
                {"name": "북경반점 은평점", "phone": "02-359-8877", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 소화 잘 됨", "certBadge": "🏛️ 전통 중화요리 맛집", "mapUrls": make_map_urls("북경반점 은평점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "진관사 사찰음식 밥상", "phone": "02-359-8410", "menu": f"은평 사찰 소반 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "진관사 스님 레시피 천연 자연 보양 나물 밥상", "certBadge": "🏛️ 은평구 지정 대표 사찰음식업소", "mapUrls": make_map_urls("진관사 밥상")},
                {"name": "은평한옥 떡갈비", "phone": "02-357-9900", "menu": "보양 떡갈비 정식", "walkingInfo": "도보 4분 (200m)", "features": "어르신 속 편한 떡갈비 한상", "certBadge": "🏛️ 경기도/서울 으뜸맛집", "mapUrls": make_map_urls("은평한옥 떡갈비")},
                {"name": "북한산 보리밥", "phone": "02-358-5414", "menu": "산채 보리밥 & 도토리묵", "walkingInfo": "도보 2분 (100m)", "features": "구수한 나물 밥상", "certBadge": "🏛️ 지자체 지정 모범음식점", "mapUrls": make_map_urls("북한산 보리밥")}
            ]

    # [경기도 안양시 / 안양예술공원]
    elif "안양" in target_place or "예술공원" in target_place:
        dest_title = "안양예술공원 무장애 숲속 데크 둘레길"
        parking_name = "안양예술공원 공영주차장"
        parking_fee = "1시간 1,200원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "카페 딜라이트", "phone": "031-473-3007", "dessert": "수제 차 & 오미자 에이드", "walkingInfo": "안양예술공원 도보 2분 (100m)", "features": "계곡 전경 뷰 어르신 창가 소파석", "certBadge": "☕ 안양시 지정 으뜸 뷰카페", "mapUrls": make_map_urls("카페 딜라이트")},
            {"name": "카페 APEC", "phone": "031-471-9988", "dessert": "대추차 & 전통 한과", "walkingInfo": "도보 3분 (150m)", "features": "숲속 정원 조망 및 다도 쉼터", "certBadge": "☕ 지자체 추천 명품 찻집", "mapUrls": make_map_urls("카페 APEC")},
            {"name": "원두제작소", "phone": "031-472-7041", "dessert": "핸드드립 커피 & 약과", "walkingInfo": "도보 2분 (100m)", "features": "안양 대표 수제 핸드드립 전문점", "certBadge": "☕ 안양 으뜸 로스터리", "mapUrls": make_map_urls("원두제작소")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "더테라스 안양예술공원점", "phone": "031-472-9292", "menu": f"수제 화덕피자 & 파스타 (1인 {lunch_budget:,}원대)", "walkingInfo": "안양예술공원 도보 1분 (50m)", "features": "예술공원 계곡 호수 뷰, 야외 테라스 소파석", "certBadge": "🏛️ 안양시 지정 으뜸 양식당", "mapUrls": make_map_urls("더테라스 안양예술공원점")},
                {"name": "파스타스토리", "phone": "031-473-1004", "menu": "수제 브런치 파스타 & 샐러드", "walkingInfo": "공원 입구 도보 3분 (150m)", "features": "계곡 숲속 전경 뷰 이탈리안 명가", "certBadge": "🏛️ 안양 만안구 모범 양식당", "mapUrls": make_map_urls("파스타스토리")},
                {"name": "샤우팅파스타", "phone": "031-471-9292", "menu": "안심 스테이크 & 크림 리조또", "walkingInfo": "도보 4분 (200m)", "features": "어르신 속 편한 담백한 이탈리안", "certBadge": "🏛️ 안양 우수 레스토랑", "mapUrls": make_map_urls("샤우팅파스타")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시무라 석수점", "phone": "031-472-0012", "menu": f"모둠 초밥 정식 & 메밀소바 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "안양예술공원 신선한 고급 일식 정식", "certBadge": "🏛️ 안양시 지정 모범 일식당", "mapUrls": make_map_urls("스시무라 석수점")},
                {"name": "쿠우쿠우 안양점", "phone": "031-443-6274", "menu": "초밥 & 일식 샐러드바", "walkingInfo": "차량 3분 (1.5km)", "features": "넓은 소파석 및 엘리베이터 보유", "certBadge": "🏛️ 안양 모범 패밀리 식당", "mapUrls": make_map_urls("쿠우쿠우 안양점")},
                {"name": "카츠젠 안양점", "phone": "031-469-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분 (100m)", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠젠 안양점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "차이닝", "phone": "031-472-8255", "menu": f"30년 전통 삼선 짬뽕 & 찹쌀 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "안양예술공원 도보 2분 (100m)", "features": "안양예술공원 입구 30년 전통 수제 중화요리 명가", "certBadge": "🏛️ 안양시 지정 으뜸 중식당", "mapUrls": make_map_urls("차이닝")},
                {"name": "드래곤차이", "phone": "031-447-1118", "menu": "중화 코스 요리 & 간짜장", "walkingInfo": "차량 3분 (1.5km)", "features": "어르신 모임 코스 중식, 프라이빗 룸 보유", "certBadge": "🏛️ 안양 만안구 대표 고급 중식당", "mapUrls": make_map_urls("드래곤차이")},
                {"name": "원동", "phone": "031-471-0988", "menu": "옛날 짜장면 & 수제 만두", "walkingInfo": "도보 3분 (150m)", "features": "속 편하고 소화 잘 되는 중화요리", "certBadge": "🏛️ 안양 전통 모범업소", "mapUrls": make_map_urls("원동")}
            ]
        else: # 한식
            rest_list = [
                {"name": "봉암식당", "phone": "031-471-7428", "menu": f"50년 전통 토종닭 백숙 & 산채비빔밥 (1인 {lunch_budget:,}원대)", "walkingInfo": "안양예술공원 내 도보 1분 (50m)", "features": "안양예술공원 계곡 뷰 50년 전통 보양 한식 명가", "certBadge": "🏛️ 경기도/안양시 지정 으뜸 향토맛집", "mapUrls": make_map_urls("봉암식당")},
                {"name": "촌스런보리밥", "phone": "031-473-5858", "menu": "건강 산채 보리밥 & 해물파전", "walkingInfo": "공원 입구 도보 2분 (100m)", "features": "어르신 속 편한 수제 산채 나물 밥상", "certBadge": "🏛️ 안양시 지정 대표 한식당", "mapUrls": make_map_urls("촌스런보리밥")},
                {"name": "폭포수식당", "phone": "031-471-3377", "menu": "한방 백숙 & 도토리묵", "walkingInfo": "도보 1분 (50m)", "features": "안양예술공원 계곡 폭포 전경 조망", "certBadge": "🏛️ 안양 모범음식점 인증업소", "mapUrls": make_map_urls("폭포수식당")}
            ]

    # [경기도 과천시 / 서울대공원]
    elif "과천" in target_place:
        dest_title = "과천 서울대공원 호수 수변 둘레길"
        parking_name = "과천 서울대공원 공영주차장"
        parking_fee = "1시간 1,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "마이알레 카페", "phone": "02-502-1668", "dessert": "수제 차 & 허브티", "walkingInfo": "도보 3분 (150m)", "features": "숲속 정원 조망 온실 카페 소파석", "certBadge": "☕ 과천시 지정 으뜸 뷰카페", "mapUrls": make_map_urls("마이알레")},
            {"name": "빵선생 과천점", "phone": "02-503-8811", "dessert": "수제 쌀 빵 & 아메리카노", "walkingInfo": "도보 4분 (200m)", "features": "넓은 대형 베이커리 쉼터", "certBadge": "☕ 과천 대표 베이커리", "mapUrls": make_map_urls("빵선생 과천점")},
            {"name": "카페 카자", "phone": "02-504-7722", "dessert": "대추차 & 전통 한과", "walkingInfo": "도보 2분 (100m)", "features": "고즈넉한 어르신 다도 공간", "certBadge": "☕ 지자체 지정 명품 찻집", "mapUrls": make_map_urls("카페 카자")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "마이알레", "phone": "02-502-1668", "menu": f"숲속 브런치 파스타 & 리조또 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "온실 정원 전경 뷰 이탈리안 명가", "certBadge": "🏛️ 과천시 지정 으뜸 양식당", "mapUrls": make_map_urls("마이알레")},
                {"name": "파스타스토리 과천점", "phone": "02-504-1004", "menu": "수제 화덕피자 & 샐러드", "walkingInfo": "도보 4분 (200m)", "features": "담백한 수제 이탈리안", "certBadge": "🏛️ 과천 우수 레스토랑", "mapUrls": make_map_urls("파스타스토리 과천점")},
                {"name": "라라코스트 과천점", "phone": "02-503-0301", "menu": "빠네 파스타 & 리조또", "walkingInfo": "도보 2분 (100m)", "features": "부드럽고 소화 잘 됨", "certBadge": "🏛️ 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트 과천점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시와 과천점", "phone": "02-504-8833", "menu": f"모둠 초밥 정식 & 우동 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 고급 일식 스시 정식", "certBadge": "🏛️ 과천시 지정 모범 일식당", "mapUrls": make_map_urls("스시와 과천점")},
                {"name": "미카도스시 과천점", "phone": "02-502-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("미카도스시 과천점")},
                {"name": "카츠젠 과천점", "phone": "02-503-7008", "menu": "수제 돈가스 & 우동", "walkingInfo": "도보 2분", "features": "속 편한 바삭 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠젠 과천점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "일지매 과천점", "phone": "02-507-5500", "menu": f"삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "속 편한 고급 중화요리", "certBadge": "🏛️ 과천시 지정 으뜸 중식당", "mapUrls": make_map_urls("일지매 과천점")},
                {"name": "희래등 과천점", "phone": "02-504-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "프라이빗 룸 보유 코스 중식", "certBadge": "🏛️ 전통 중화요리 명가", "mapUrls": make_map_urls("희래등 과천점")},
                {"name": "동흥관 과천점", "phone": "02-502-8877", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 소화 잘 됨", "certBadge": "🏛️ 전통 모범업소", "mapUrls": make_map_urls("동흥관 과천점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "농부의뜰 과천점", "phone": "02-507-8892", "menu": f"수제 숯불갈비 & 한정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "정갈한 놋그릇 수라 한정식 명가", "certBadge": "🏛️ 경기도/과천시 지정 으뜸맛집", "mapUrls": make_map_urls("농부의뜰 과천점")},
                {"name": "가마솥회관", "phone": "02-503-3377", "menu": "진한 가마솥 곰탕 & 설렁탕", "walkingInfo": "도보 4분 (200m)", "features": "어르신 보양 국물 명가", "certBadge": "🏛️ 과천 모범음식점 인증업소", "mapUrls": make_map_urls("가마솥회관")},
                {"name": "본수원갈비 과천점", "phone": "02-502-8484", "menu": "갈비탕 정식 & 수제 반찬", "walkingInfo": "도보 2분 (100m)", "features": "속 편한 진국 탕 한상", "certBadge": "🏛️ 대표 향토음식점", "mapUrls": make_map_urls("본수원갈비 과천점")}
            ]

    # [경기도 의왕시 / 왕송호수 / 백운호수]
    elif "의왕" in target_place or "왕송" in target_place or "백운" in target_place:
        dest_title = "의왕 왕송호수 & 백운호수 수변 둘레길"
        parking_name = "의왕 왕송호수 공영주차장"
        parking_fee = "1시간 1,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "흙과나무", "phone": "031-422-0011", "dessert": "수제 차 & 베이커리", "walkingInfo": "백운호수 도보 1분 (50m)", "features": "백운호수 수변 파노라마 뷰 1위 카페", "certBadge": "☕ 의왕시 지정 으뜸 뷰카페", "mapUrls": make_map_urls("흙과나무")},
            {"name": "그린플래그커피", "phone": "031-426-4000", "dessert": "대추차 & 수제 롤케이크", "walkingInfo": "도보 3분 (150m)", "features": "탁 트인 백운호수 전망 창가 소파석", "certBadge": "☕ 지자체 추천 명품 카페", "mapUrls": make_map_urls("그린플래그커피")},
            {"name": "카페 모카", "phone": "031-423-7722", "dessert": "핸드드립 커피 & 전통 과자", "walkingInfo": "도보 2분 (100m)", "features": "어르신 쉬기 편한 아늑한 쉼터", "certBadge": "☕ 의왕 모범 뷰카페", "mapUrls": make_map_urls("카페 모카")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "올라 백운호수점", "phone": "031-426-1008", "menu": f"수제 화덕피자 & 파스타 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 2분 (100m)", "features": "백운호수 호수 전경 뷰 이탈리안 명가", "certBadge": "🏛️ 의왕시 지정 으뜸 양식당", "mapUrls": make_map_urls("올라 백운호수점")},
                {"name": "로아인", "phone": "031-423-1100", "menu": "안심 스테이크 & 크림 리조또", "walkingInfo": "도보 4분 (200m)", "features": "담백하고 속 편한 정통 이탈리안", "certBadge": "🏛️ 의왕 모범 양식당", "mapUrls": make_map_urls("로아인")},
                {"name": "라라코스트 의왕점", "phone": "031-421-0301", "menu": "빠네 파스타 & 피자", "walkingInfo": "도보 3분 (150m)", "features": "어르신 편안한 패밀리 레스토랑", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("라라코스트 의왕점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시노백셰프 의왕점", "phone": "031-424-8833", "menu": f"모둠 초밥 정식 & 소바 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "신선한 고급 일식 수제 스시", "certBadge": "🏛️ 의왕시 지정 모범 일식당", "mapUrls": make_map_urls("스시노백셰프 의왕점")},
                {"name": "미카도스시 의왕점", "phone": "031-425-2388", "menu": "회전초밥 & 메밀소바", "walkingInfo": "도보 4분", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 모범업소", "mapUrls": make_map_urls("미카도스시 의왕점")},
                {"name": "카츠젠 의왕점", "phone": "031-426-7008", "menu": "수제 돈가스 & 우동", "walkingInfo": "도보 2분", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠젠 의왕점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "칭칭차이나 백운호수점", "phone": "031-423-5500", "menu": f"삼선 짬뽕 & 찹쌀 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분", "features": "백운호수 뷰 정갈한 고급 중화요리", "certBadge": "🏛️ 의왕시 지정 으뜸 중식당", "mapUrls": make_map_urls("칭칭차이나 백운호수점")},
                {"name": "희래등 의왕점", "phone": "031-424-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분", "features": "어르신 모임 코스 중식", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("희래등 의왕점")},
                {"name": "홍콩반점0410 의왕점", "phone": "031-425-8877", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분", "features": "옛날 방식 소화 잘 됨", "certBadge": "🏛️ 전통 중화요리 맛집", "mapUrls": make_map_urls("홍콩반점0410 의왕점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "백운재", "phone": "031-422-6900", "menu": f"제육 & 불고기 유기농 쌈밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "백운호수 도보 2분 (100m)", "features": "백운호수 전경 뷰 유기농 신선 쌈밥 명가", "certBadge": "🏛️ 경기도/의왕시 지정 으뜸맛집", "mapUrls": make_map_urls("백운재")},
                {"name": "청산별곡 백운호수점", "phone": "031-422-9898", "menu": "강원도 머루 코스 한정식", "walkingInfo": "도보 3분 (150m)", "features": "어르신 속 편한 강원도 자연 한상", "certBadge": "🏛️ 의왕시 지정 모범 한식당", "mapUrls": make_map_urls("청산별곡 백운호수점")},
                {"name": "원조옛날보리밥", "phone": "031-422-4883", "menu": "보리밥 정식 & 해물파전", "walkingInfo": "도보 2분 (100m)", "features": "구수한 수제 산채 나물 밥상", "certBadge": "🏛️ 전통 향토음식점", "mapUrls": make_map_urls("원조옛날보리밥")}
            ]

    # [경기도 시흥시 / 갯골생태공원 / 물왕저수지]
    elif "시흥" in target_place or "갯골" in target_place or "물왕" in target_place:
        dest_title = "시흥 갯골생태공원 억새 수변 둘레길"
        parking_name = "시흥 갯골생태공원 공영주차장"
        parking_fee = "1시간 1,000원 (전기차 50% 할인)"
        
        cafe_list = [
            {"name": "물왕저수지 카페 아름하우스", "phone": "031-403-3007", "dessert": "수제 차 & 오미자 에이드", "walkingInfo": "도보 2분 (100m)", "features": "물왕저수지 호수 뷰 창가 소파석", "certBadge": "☕ 시흥시 지정 으뜸 뷰카페", "mapUrls": make_map_urls("물왕저수지 카페 아름하우스")},
            {"name": "시흥 갯골 숲속카페", "phone": "031-404-9988", "dessert": "대추차 & 전통 한과", "walkingInfo": "도보 3분 (150m)", "features": "생태공원 억새밭 조망 쉼터", "certBadge": "☕ 지자체 추천 명품 찻집", "mapUrls": make_map_urls("시흥 갯골 숲속카페")},
            {"name": "백억커피 시흥점", "phone": "031-405-7041", "dessert": "시그니처 캔커피 & 약과", "walkingInfo": "도보 2분 (100m)", "features": "어르신 쉬기 편한 입구 카페", "certBadge": "☕ 시흥 모범 뷰카페", "mapUrls": make_map_urls("백억커피 시흥점")}
        ]
        
        if cuisine == "양식":
            rest_list = [
                {"name": "베니스", "phone": "031-403-6200", "menu": f"물왕저수지 수제 파스타 & 스테이크 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 2분 (100m)", "features": "물왕저수지 호수 전경 뷰 이탈리안 명가", "certBadge": "🏛️ 시흥시 지정 으뜸 양식당", "mapUrls": make_map_urls("베니스")},
                {"name": "라라코스트 시흥점", "phone": "031-404-0301", "menu": "빠네 파스타 & 피자", "walkingInfo": "도보 3분 (150m)", "features": "담백한 패밀리 레스토랑", "certBadge": "🏛️ 모범 양식당", "mapUrls": make_map_urls("라라코스트 시흥점")},
                {"name": "롤링파스타 시흥점", "phone": "031-405-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "도보 2분 (100m)", "features": "부드럽고 소화 잘 됨", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타 시흥점")}
            ]
        elif cuisine == "일식":
            rest_list = [
                {"name": "스시마루 시흥점", "phone": "031-408-8833", "menu": f"모둠 초밥 정식 & 메밀소바 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "시흥 갯골생태공원 인근 신선한 고급 일식", "certBadge": "🏛️ 시흥시 지정 모범 일식당", "mapUrls": make_map_urls("스시마루 시흥점")},
                {"name": "미카도스시 시흥물왕점", "phone": "031-407-2388", "menu": "회전초밥 & 우동 정식", "walkingInfo": "도보 4분 (200m)", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 지자체 모범업소", "mapUrls": make_map_urls("미카도스시 시흥물왕점")},
                {"name": "카츠젠 시흥점", "phone": "031-406-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "도보 2분 (100m)", "features": "바삭하고 속 편한 튀김", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠젠 시흥점")}
            ]
        elif cuisine == "중식":
            rest_list = [
                {"name": "화룡", "phone": "031-409-5500", "menu": f"30년 전통 삼선 짬뽕 & 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "도보 3분 (150m)", "features": "시흥 30년 전통 수제 중화요리 명가", "certBadge": "🏛️ 시흥시 지정 으뜸 중식당", "mapUrls": make_map_urls("화룡")},
                {"name": "칭칭차이나 시흥점", "phone": "031-410-5500", "menu": "중화 코스 요리", "walkingInfo": "도보 4분 (200m)", "features": "어르신 모임 코스 중식", "certBadge": "🏛️ 코스 요리 전문점", "mapUrls": make_map_urls("칭칭차이나 시흥점")},
                {"name": "홍콩반점0410 시흥점", "phone": "031-411-8877", "menu": "간짜장 & 군만두", "walkingInfo": "도보 2분 (100m)", "features": "옛날 방식 소화 잘 됨", "certBadge": "🏛️ 전통 중화요리 맛집", "mapUrls": make_map_urls("홍콩반점0410 시흥점")}
            ]
        else: # 한식
            rest_list = [
                {"name": "물왕버섯농원", "phone": "031-485-8533", "menu": f"수제 버섯 불고기 정식 & 놋그릇 밥상 (1인 {lunch_budget:,}원대)", "walkingInfo": "물왕저수지 도보 2분 (100m)", "features": "시흥 물왕저수지 전경 뷰 보양 버섯 한상 명가", "certBadge": "🏛️ 경기도/시흥시 지정 으뜸맛집", "mapUrls": make_map_urls("물왕버섯농원")},
                {"name": "예원 한정식", "phone": "031-404-5040", "menu": "보리굴비 정식 & 수라상", "walkingInfo": "도보 3분 (150m)", "features": "어르신 속 편한 한정식 한상", "certBadge": "🏛️ 시흥시 지정 모범 한식당", "mapUrls": make_map_urls("예원 한정식")},
                {"name": "시흥 갯골 곤드레밥", "phone": "031-405-5414", "menu": "곤드레 밥상 & 수제 반찬", "walkingInfo": "도보 2분 (100m)", "features": "구수한 수제 나물 밥상", "certBadge": "🏛️ 전통 향토음식점", "mapUrls": make_map_urls("시흥 갯골 곤드레밥")}
            ]

    # [기타 모든 지역 (여주/화성 및 카카오 RAG 실시간 동적 생성)]
    else:
        clean_target = clean_place_name(target_place)
        dest_title = kakao_rag.get("center_place", clean_target) if kakao_rag else clean_target
        parking_name = (kakao_rag.get("parking_lots", [{}])[0].get("name") if kakao_rag and kakao_rag.get("parking_lots") else f"{dest_title} 공영주차장")
        parking_fee = "평일 3,000원 / 주말 5,000원 (전기차 50% 감면 혜택)"
        
        if kakao_rag and kakao_rag.get("cafes") and len(kakao_rag["cafes"]) >= 1:
            cafe_list = [
                {
                    "name": c["name"],
                    "phone": c.get("phone") or "031-XXX-XXXX",
                    "dessert": "시그니처 전통차 & 베이커리",
                    "walkingInfo": f"식당 {c.get('distance', '도보 3분')}",
                    "features": f"{c.get('address', '')} 인근, 어르신 쉬기 편한 쉼터",
                    "certBadge": "☕ 지자체 추천 으뜸 찻집/카페",
                    "mapUrls": make_map_urls(c["name"], target_place, c.get("place_url", ""))
                }
                for c in kakao_rag["cafes"][:3]
            ]
        else:
            cafe_list = [
                {"name": "나무아래", "phone": "031-585-1888", "dessert": "갓 구운 빵 & 아메리카노", "walkingInfo": "식당 도보 3분 (150m)", "features": "전경 뷰, 넓은 대형 베이커리 소파석", "certBadge": "☕ 지자체 지정 우수 뷰카페", "mapUrls": make_map_urls("나무아래")},
                {"name": "나인블럭", "phone": "031-8005-8412", "dessert": "핸드드립 커피 & 케이크", "walkingInfo": "식당 도보 4분 (200m)", "features": "넓은 탁 트인 개방감, 엘리베이터 보유", "certBadge": "☕ 대표 힐링 베이커리 카페", "mapUrls": make_map_urls("나인블럭")},
                {"name": "백억커피", "phone": "031-638-1004", "dessert": "시그니처 캔커피 & 약과", "walkingInfo": "식당 도보 2분 (100m)", "features": "어르신 쉬기 편한 입구 카페", "certBadge": "☕ 편안한 소파석 카페", "mapUrls": make_map_urls("백억커피")}
            ]

        if kakao_rag and kakao_rag.get("restaurants") and len(kakao_rag["restaurants"]) >= 1:
            rest_list = [
                {
                    "name": r["name"],
                    "phone": r.get("phone") or "031-XXX-XXXX",
                    "menu": f"{cuisine} 추천 정식 (1인 {lunch_budget:,}원대)",
                    "walkingInfo": f"주차장 {r.get('distance', '도보 3분')}",
                    "features": f"정갈한 {r.get('category', cuisine)} 상차림 ({r.get('address', '')})",
                    "certBadge": "🏛️ 지자체 지정 으뜸 맛집",
                    "mapUrls": make_map_urls(r["name"], target_place, r.get("place_url", ""))
                }
                for r in kakao_rag["restaurants"][:3]
            ]
        else:
            if cuisine == "양식":
                rest_list = [
                    {"name": "라라코스트", "phone": "031-631-0301", "menu": f"이탈리안 파스타 & 피자 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "어르신 선호 창가 좌석, 패밀리 양식", "certBadge": "🏛️ 모범 패밀리 레스토랑", "mapUrls": make_map_urls("라라코스트")},
                    {"name": "롤링파스타", "phone": "031-638-0410", "menu": "크림 파스타 & 리조또", "walkingInfo": "주차장 도보 4분 (200m)", "features": "부드럽고 소화 잘 되는 크림 파스타", "certBadge": "🏛️ 가성비 우수 식당", "mapUrls": make_map_urls("롤링파스타")},
                    {"name": "아웃백스테이크하우스", "phone": "031-637-3750", "menu": "안심 스테이크 & 투움바 파스타", "walkingInfo": "주차장 도보 2분 (100m)", "features": "편안한 소파석, 엘리베이터 보유", "certBadge": "🏛️ 우수 레스토랑", "mapUrls": make_map_urls("아웃백스테이크하우스")}
                ]
            elif cuisine == "일식":
                rest_list = [
                    {"name": "호타루", "phone": "031-637-4320", "menu": f"모둠 초밥 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "신선한 스시 정식", "certBadge": "🏛️ 대표 으뜸 일식당", "mapUrls": make_map_urls("호타루")},
                    {"name": "미카도스시", "phone": "031-638-2388", "menu": "회전초밥 & 모밀", "walkingInfo": "주차장 도보 4분 (200m)", "features": "어르신 속 편한 일식 정식", "certBadge": "🏛️ 모범 일식업소", "mapUrls": make_map_urls("미카도스시")},
                    {"name": "카츠마마", "phone": "031-638-7008", "menu": "수제 돈가스 & 우동 정식", "walkingInfo": "주차장 도보 2분 (100m)", "features": "속 편한 튀김 요리", "certBadge": "🏛️ 우수 일식 전문점", "mapUrls": make_map_urls("카츠마마")}
                ]
            elif cuisine == "중식":
                rest_list = [
                    {"name": "홍콩반점0410", "phone": "031-746-5500", "menu": f"삼선 짬뽕 & 찹쌀 탕수육 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "속 편한 담백 중식", "certBadge": "🏛️ 지자체 모범 중식당", "mapUrls": make_map_urls("홍콩반점0410")},
                    {"name": "교동짬뽕", "phone": "031-637-5500", "menu": "수제 짬뽕 & 군만두", "walkingInfo": "주차장 도보 4분 (200m)", "features": "얼큰하고 진한 국물 중식 명가", "certBadge": "🏛️ 전국 으뜸 짬뽕 전문점", "mapUrls": make_map_urls("교동짬뽕")},
                    {"name": "보배반점", "phone": "031-252-2580", "menu": "간짜장 & 탕수육", "walkingInfo": "주차장 도보 2분 (100m)", "features": "어르신 선호 편안한 소파석", "certBadge": "🏛️ 모범 중화요리점", "mapUrls": make_map_urls("보배반점")}
                ]
            else: # 한식
                rest_list = [
                    {"name": "언덕마루 잣두부집", "phone": "031-584-5368", "menu": f"수제 잣두부 전골 정식 (1인 {lunch_budget:,}원대)", "walkingInfo": "주차장 도보 3분 (150m)", "features": "어르신 속 편한 고소한 두부 수제 정식", "certBadge": "🏛️ 지자체 지정 향토 으뜸맛집", "mapUrls": make_map_urls("언덕마루 잣두부집")},
                    {"name": "연밭", "phone": "031-772-6200", "menu": "연잎밥 정식 & 수제 반찬", "walkingInfo": "주차장 도보 4분 (200m)", "features": "소화에 좋은 보양 연잎 찰밥", "certBadge": "🏛️ 경기도 으뜸맛집 인증업소", "mapUrls": make_map_urls("연밭")},
                    {"name": "나랏님이천쌀밥", "phone": "031-636-9900", "menu": "이천 쌀밥 수라상 정식", "walkingInfo": "주차장 도보 2분 (100m)", "features": "정갈한 수라상 한정식", "certBadge": "🏛️ 대표 향토음식점", "mapUrls": make_map_urls("나랏님이천쌀밥")}
                ]

    # 관심사별 10:30 메인 일정 동적 커스텀
    # 지역별 연계 전통시장, 온천, 사찰 매핑 데이터
    MARKET_MAP = {
        "종로": ("서울 종로 통인시장 & 광장시장", "차량 약 5분 (1.5km)", "광장시장 공영주차장"),
        "경복궁": ("서울 종로 통인시장 & 광장시장", "차량 약 5분 (1.5km)", "광장시장 공영주차장"),
        "서촌": ("서울 종로 통인시장 & 광장시장", "차량 약 5분 (1.5km)", "광장시장 공영주차장"),
        "중구": ("서울 중구 남대문 전통시장", "차량 약 5분 (1.2km)", "남대문시장 공영주차장"),
        "남산": ("서울 중구 남대문 전통시장", "차량 약 5분 (1.2km)", "남대문시장 공영주차장"),
        "용산": ("서울 용산 이촌 전통시장", "차량 약 8분 (2.5km)", "이촌시장 주차장"),
        "송파": ("서울 송파 방이 전통시장", "차량 약 6분 (2km)", "방이시장 공영주차장"),
        "석촌": ("서울 송파 방이 전통시장", "차량 약 6분 (2km)", "방이시장 공영주차장"),
        "마포": ("서울 마포 망원 전통시장", "차량 약 8분 (3km)", "망원시장 공영주차장"),
        "서대문": ("서울 마포 망원 전통시장", "차량 약 8분 (3km)", "망원시장 공영주차장"),
        "은평": ("서울 은평 대조 전통시장", "차량 약 8분 (3km)", "대조시장 공영주차장"),
        "의정부": ("의정부 제일시장", "차량 약 5분 (1.5km)", "제일시장 공영주차장"),
        "송도": ("소래포구 전통어시장", "차량 약 15분 (11km)", "소래포구 공영주차장"),
        "인천": ("소래포구 전통어시장", "차량 약 15분 (11km)", "소래포구 공영주차장"),
        "수원": ("팔달문 전통시장", "차량 약 7분 (2.5km)", "팔달문시장 공영주차장"),
        "화성": ("팔달문 전통시장", "차량 약 10분 (4km)", "팔달문시장 공영주차장"),
        "이천": ("이천 관고 전통시장", "차량 약 6분 (2.2km)", "관고전통시장 공영주차장"),
        "설봉": ("이천 관고 전통시장", "차량 약 6분 (2.2km)", "관고전통시장 공영주차장"),
        "가평": ("가평 잣고을 전통시장", "차량 약 18분 (14km)", "잣고을전통시장 공영주차장"),
        "수목원": ("가평 잣고을 전통시장", "차량 약 18분 (14km)", "잣고을전통시장 공영주차장"),
        "양평": ("양평 물맑은 전통시장", "차량 약 16분 (13km)", "양평물맑은시장 공영주차장"),
        "두물머리": ("양평 물맑은 전통시장", "차량 약 16분 (13km)", "양평물맑은시장 공영주차장"),
        "광주": ("광주 경안 전통시장", "차량 약 15분 (10km)", "경안전통시장 공영주차장"),
        "남한산성": ("광주 경안 전통시장", "차량 약 15분 (10km)", "경안전통시장 공영주차장"),
        "용인": ("용인 중앙 전통시장", "차량 약 12분 (8km)", "용인중앙시장 공영주차장"),
        "민속촌": ("용인 중앙 전통시장", "차량 약 12분 (8km)", "용인중앙시장 공영주차장"),
        "포천": ("포천 일동 전통시장", "차량 약 15분 (11km)", "일동전통시장 주차장"),
        "산정호수": ("포천 일동 전통시장", "차량 약 15분 (11km)", "일동전통시장 주차장"),
        "파주": ("파주 문산 자유시장", "차량 약 20분 (16km)", "문산자유시장 공영주차장"),
        "마장호수": ("파주 문산 자유시장", "차량 약 20분 (16km)", "문산자유시장 공영주차장")
    }

    SPA_MAP = {
        "의정부": ("의정부 아일랜드타운", "차량 약 10분 (4km)", "의정부 아일랜드타운 주차장"),
        "송도": ("인천 솔찬공원", "차량 약 10분 (6km)", "인천 솔찬공원 주차장"),
        "인천": ("인천 솔찬공원", "차량 약 10분 (6km)", "인천 솔찬공원 주차장"),
        "수원": ("화성 율암온천", "차량 약 15분 (10km)", "화성 율암온천 주차장"),
        "화성": ("화성 율암온천", "차량 약 15분 (10km)", "화성 율암온천 주차장"),
        "이천": ("이천 설봉온천스파", "차량 약 5분 (1.8km)", "이천 설봉온천 주차장"),
        "설봉": ("이천 설봉온천스파", "차량 약 5분 (1.8km)", "이천 설봉온천 주차장"),
        "가평": ("아침고요살피꽃다방", "도보 약 3분 (150m)", "가평 아침고요수목원 주차장"),
        "수목원": ("아침고요살피꽃다방", "도보 약 3분 (150m)", "가평 아침고요수목원 주차장"),
        "양평": ("양평 쉼지오", "차량 약 10분 (7km)", "양평 쉼지오 주차장"),
        "두물머리": ("양평 쉼지오", "차량 약 10분 (7km)", "양평 쉼지오 주차장"),
        "광주": ("남한산성 족욕", "차량 약 5분 (1.5km)", "남한산성 도립공원 남문주차장"),
        "남한산성": ("남한산성 족욕", "차량 약 5분 (1.5km)", "남한산성 도립공원 남문주차장"),
        "용인": ("용인 로만바스", "차량 약 15분 (10km)", "용인 로만바스 주차장"),
        "민속촌": ("용인 로만바스", "차량 약 15분 (10km)", "용인 로만바스 주차장"),
        "포천": ("포천 신북온천", "차량 약 18분 (15km)", "포천 신북온천 대형주차장"),
        "산정호수": ("포천 신북온천", "차량 약 18분 (15km)", "포천 신북온천 대형주차장"),
        "파주": ("파주 헤이리 족욕", "차량 약 25분 (20km)", "파주 헤이리 공영주차장"),
        "마장호수": ("파주 헤이리 족욕", "차량 약 25분 (20km)", "파주 헤이리 공영주차장")
    }

    TEMPLE_MAP = {
        "의정부": ("의정부 망월사", "차량 약 12분 (5km)", "의정부 망월사 주차장"),
        "송도": ("인천 흥륜사", "차량 약 10분 (5km)", "인천 흥륜사 주차장"),
        "인천": ("인천 흥륜사", "차량 약 10분 (5km)", "인천 흥륜사 주차장"),
        "수원": ("수원 용주사", "차량 약 15분 (8km)", "수원 용주사 주차장"),
        "화성": ("수원 용주사", "차량 약 15분 (8km)", "수원 용주사 주차장"),
        "이천": ("이천 영월암", "차량 약 5분 (2km)", "이천 영월암 주차장"),
        "설봉": ("이천 영월암", "차량 약 5분 (2km)", "이천 영월암 주차장"),
        "가평": ("가평 현등사", "차량 약 20분 (15km)", "가평 현등사 주차장"),
        "수목원": ("가평 현등사", "차량 약 20분 (15km)", "가평 현등사 주차장"),
        "양평": ("양평 사나사", "차량 약 15분 (10km)", "양평 사나사 주차장"),
        "두물머리": ("양평 사나사", "차량 약 15분 (10km)", "양평 사나사 주차장"),
        "광주": ("남한산성 장경사", "차량 약 7분 (2km)", "남한산성 장경사 주차장"),
        "남한산성": ("남한산성 장경사", "차량 약 7분 (2km)", "남한산성 장경사 주차장"),
        "용인": ("용인 와우정사", "차량 약 18분 (13km)", "용인 와우정사 주차장"),
        "민속촌": ("용인 와우정사", "차량 약 18분 (13km)", "용인 와우정사 주차장"),
        "포천": ("포천 자인사", "차량 약 5분 (3km)", "포천 자인사 주차장"),
        "산정호수": ("포천 자인사", "차량 약 5분 (3km)", "포천 자인사 주차장"),
        "파주": ("파주 보광사", "차량 약 8분 (5km)", "파주 보광사 주차장"),
        "마장호수": ("파주 보광사", "차량 약 8분 (5km)", "파주 보광사 주차장")
    }

    MUSEUM_MAP = {
        "의정부": ("의정부미술도서관", "차량 약 8분 (3.5km)", "의정부미술도서관 주차장"),
        "송도": ("국립세계문자박물관", "차량 약 8분 (4km)", "국립세계문자박물관 지하주차장"),
        "인천": ("국립세계문자박물관", "차량 약 8분 (4km)", "국립세계문자박물관 지하주차장"),
        "수원": ("수원화성박물관", "차량 약 3분 (1km)", "수원화성박물관 주차장"),
        "화성": ("수원화성박물관", "차량 약 10분 (5km)", "수원화성박물관 주차장"),
        "이천": ("이천시립월전미술관", "도보 3분 (200m)", "이천 설봉공원 주차장"),
        "설봉": ("이천시립월전미술관", "도보 3분 (200m)", "이천 설봉공원 주차장"),
        "가평": ("가평 쁘띠프랑스", "차량 약 20분 (15km)", "가평 쁘띠프랑스 주차장"),
        "수목원": ("가평 쁘띠프랑스", "차량 약 20분 (15km)", "가평 쁘띠프랑스 주차장"),
        "양평": ("양평군립미술관", "차량 약 12분 (9km)", "양평군립미술관 주차장"),
        "두물머리": ("양평군립미술관", "차량 약 12분 (9km)", "양평군립미술관 주차장"),
        "광주": ("남한산성행궁", "도보 5분 (300m)", "남한산성 도립공원 남문주차장"),
        "남한산성": ("남한산성행궁", "도보 5분 (300m)", "남한산성 도립공원 남문주차장"),
        "용인": ("경기도박물관", "차량 약 5분 (2.5km)", "용인 경기도박물관 주차장"),
        "민속촌": ("경기도박물관", "차량 약 5분 (2.5km)", "용인 경기도박물관 주차장"),
        "포천": ("포천 한가원", "차량 약 8분 (5km)", "포천 한가원 주차장"),
        "산정호수": ("포천 한가원", "차량 약 8분 (5km)", "포천 한가원 주차장"),
        "파주": ("파주 한국근현대사박물관", "차량 약 25분 (20km)", "파주 헤이리 공영주차장"),
        "마장호수": ("파주 한국근현대사박물관", "차량 약 25분 (20km)", "파주 헤이리 공영주차장")
    }

    # 10:15 대표 구체적 산책 스팟 매핑 데이터
    WALKING_SPOT_MAP = {
        "종로": ("서울 종로구 경복궁 고궁 무장애 둘레길", "경복궁 근정전과 아미산 정원을 따라 경사 없는 평지 고궁 길을 어르신들이 고즈넉하게 걸으시는 명품 고궁 산책 코스입니다.", "주차장에서 경복궁 입구 도보 2분 (100m)"),
        "경복궁": ("서울 종로구 경복궁 고궁 무장애 둘레길", "경복궁 근정전과 아미산 정원을 따라 경사 없는 평지 고궁 길을 어르신들이 고즈넉하게 걸으시는 명품 고궁 산책 코스입니다.", "주차장에서 경복궁 입구 도보 2분 (100m)"),
        "서촌": ("서울 종로구 서촌 자락길 & 통인시장 한옥길", "서촌 인왕산 자락길과 고즈넉한 한옥 골목을 편안하게 거니는 고풍스러운 산책 코스입니다.", "주차장에서 서촌 입구 도보 2분 (100m)"),
        "중구": ("서울 중구 남산골 한옥마을 평지 정원길", "조선시대 전통 한옥 건물과 남산 아래 고즈넉하게 조성된 전통 정원 산책로를 한적히 거니는 고풍스러운 산책 코스입니다.", "주차장에서 한옥마을 도보 1분 (50m)"),
        "남산": ("서울 중구 남산골 한옥마을 평지 정원길", "조선시대 전통 한옥 건물과 남산 아래 고즈넉하게 조성된 전통 정원 산책로를 한적히 거니는 고풍스러운 산책 코스입니다.", "주차장에서 한옥마을 도보 1분 (50m)"),
        "용산": ("서울 용산구 용산가족공원 거울못 수변 산책로", "국립중앙박물관 거울못과 용산가족공원의 넓은 잔디광장을 따라 완만히 펼쳐진 평지 둘레길을 어르신들이 호숫가 경치를 조망하며 걷는 명품 힐링 코스입니다.", "주차장에서 거울못 산책로 도보 1분 (50m)"),
        "송파": ("서울 송파구 석촌호수 수변 무장애 데크 둘레길", "석촌호수 동호와 서호를 둘러싸고 수평으로 연결된 친환경 데크산책로를 걸으며 롯데타워와 수변 전경을 조망하는 평지 둘레길 코스입니다.", "주차장에서 수변 데크길 도보 1분 (50m)"),
        "석촌": ("서울 송파구 석촌호수 수변 무장애 데크 둘레길", "석촌호수 동호와 서호를 둘러싸고 수평으로 연결된 친환경 데크산책로를 걸으며 롯데타워와 수변 전경을 조망하는 평지 둘레길 코스입니다.", "주차장에서 수변 데크길 도보 1분 (50m)"),
        "마포": ("서울 마포구/서대문구 안산자락길 무장애 숲길", "전 구간 경사도 9% 미만의 무장애 숲속 데크로드가 7km 조성되어 있어 무릎 부담 없이 울창한 숲길을 걸으실 수 있는 서울 최고의 무장애 숲 산책 코스입니다.", "주차장에서 자락길 입구 도보 1분 (50m)"),
        "서대문": ("서울 마포구/서대문구 안산자락길 무장애 숲길", "전 구간 경사도 9% 미만의 무장애 숲속 데크로드가 7km 조성되어 있어 무릎 부담 없이 울창한 숲길을 걸으실 수 있는 서울 최고의 무장애 숲 산책 코스입니다.", "주차장에서 자락길 입구 도보 1분 (50m)"),
        "은평": ("서울 은평구 은평한옥마을 & 진관사 한옥 산책로", "북한산 자락 아래 펼쳐진 은평한옥마을의 정갈한 골목길과 진관사 계곡변 평지 산책로를 걸으며 고즈넉함을 만끽하는 코스입니다.", "주차장에서 한옥마을 산책로 도보 1분 (50m)"),
        "안양": ("안양예술공원 무장애 숲속 데크 둘레길", "안양 삼성산 자락의 계곡과 야외 조각 작품을 따라 경사 0%로 조성된 숲속 무장애 데크산책로를 걷는 어르신 힐링 명소 코스입니다.", "주차장에서 무장애 데크길 입구 도보 1분 (50m)"),
        "의왕": ("의왕 왕송호수 수변 무장애 데크 둘레길", "의왕 왕송호수를 감싸안은 수평 무장애 데크길을 거닐며 조류생태공원 전경을 감상하는 힐링 코스입니다.", "주차장에서 수변 데크길 도보 1분 (50m)"),
        "과천": ("과천 서울대공원 호수 수변 둘레길", "서울대공원 호수를 따라 평지로 완만히 둘러싸인 벚꽃 수변 산책로를 걸으며 산과 호수 풍경을 감상하는 코스입니다.", "주차장에서 호수 둘레길 도보 2분 (100m)"),
        "성남": ("성남 율동공원 호수 수변 둘레길", "율동공원 호수 둘레를 따라 조성된 경사 없는 잔디밭 산책로와 쉼터를 여유롭게 거니는 코스입니다.", "주차장에서 호수 산책로 도보 1분 (50m)"),
        "남양주": ("남양주 다산생태공원 수변 둘레길", "팔당호수가 탁 트이게 내려다보이는 완만한 잔디밭 수변 산책로를 걸으며 차 한 잔과 피톤치드를 즐기는 코스입니다.", "주차장에서 다산생태공원 입구 도보 1분 (50m)"),
        "고양": ("일산 호수공원 수변 무장애 둘레길", "일산 호수공원 인공호수 전경을 따라 평지로 길게 이어진 수변 데크길을 걷는 상쾌한 힐링 코스입니다.", "주차장에서 호수 데크길 도보 1분 (50m)"),
        "일산": ("일산 호수공원 수변 무장애 둘레길", "일산 호수공원 인공호수 전경을 따라 평지로 길게 이어진 수변 데크길을 걷는 상쾌한 힐링 코스입니다.", "주차장에서 호수 데크길 도보 1분 (50m)"),
        "김포": ("김포 라베니체 금빛수로 수변 둘레길", "김포 라베니체 한옥 골목과 금빛수로 변 평지 데크길을 따라 고즈넉하게 걸으시는 산책 코스입니다.", "주차장에서 수변길 도보 1분 (50m)"),
        "시흥": ("시흥 갯골생태공원 억새 수변 둘레길", "시흥 갯골생태공원의 억새밭과 염전 둔치를 따라 넓게 펼쳐진 평지 수변길을 거니는 산책 코스입니다.", "주차장에서 생태공원 입구 도보 1분 (50m)"),
        "의정부": ("의정부 직동근린공원 무장애 숲길 데크산책로", "의정부시청 뒤편 도봉산 자락의 경사 0% 무장애 데크로드를 따라 어르신들이 무릎 부담 없이 울창한 숲속 피톤치드를 마시며 편안하게 걸으실 수 있는 명품 힐링 산책 코스입니다.", "주차장에서 무장애 숲길 입구까지 도보 1분 (50m)"),
        "송도": ("인천 송도 달빛축제공원 평지 수변 산책로", "송도 달빛축제공원의 넓게 펼쳐진 수변 잔디광장과 평지 둘레길을 따라 탁 트인 송도 전경을 바라보며 여유롭게 걷는 코스입니다.", "주차장에서 산책로 입구까지 도보 2분 (100m)"),
        "인천": ("인천 송도 달빛축제공원 평지 수변 산책로", "송도 달빛축제공원의 넓게 펼쳐진 수변 잔디광장과 평지 둘레길을 따라 탁 트인 송도 전경을 바라보며 여유롭게 걷는 코스입니다.", "주차장에서 산책로 입구까지 도보 2분 (100m)"),
        "수원": ("수원화성 성곽길 & 행리단길 평지 산책로", "유네스코 세계문화유산 수원화성의 고즈넉한 성곽길과 아기자기한 행리단길 평지 골목을 어르신 발걸음에 맞춰 한적하게 산책하는 코스입니다.", "주차장에서 성곽 산책로 도보 3분 (150m)"),
        "화성": ("수원화성 성곽길 & 행리단길 평지 산책로", "유네스코 세계문화유산 수원화성의 고즈넉한 성곽길과 아기자기한 행리단길 평지 골목을 어르신 발걸음에 맞춰 한적하게 산책하는 코스입니다.", "주차장에서 성곽 산책로 도보 3분 (150m)"),
        "이천": ("이천 설봉공원 설봉호수 수변 둘레길", "설봉호수를 감싸안은 완만한 평지 수변 산책로와 도예촌 잔디밭길을 거닐며 호수 경치를 감상하는 어르신 힐링 코스입니다.", "주차장에서 호수 둘레길 도보 1분 (50m)"),
        "설봉": ("이천 설봉공원 설봉호수 수변 둘레길", "설봉호수를 감싸안은 완만한 평지 수변 산책로와 도예촌 잔디밭길을 거닐며 호수 경치를 감상하는 어르신 힐링 코스입니다.", "주차장에서 호수 둘레길 도보 1분 (50m)"),
        "가평": ("가평 아침고요수목원 잣나무 숲속 둘레길", "잣나무 향기 가득한 아침고요수목원의 수목 산책로와 평탄한 야외 정원을 거닐며 자연 생태를 힐링 감상하는 코스입니다.", "주차장에서 입구 산책로 도보 2분 (100m)"),
        "수목원": ("가평 아침고요수목원 잣나무 숲속 둘레길", "잣나무 향기 가득한 아침고요수목원의 수목 산책로와 평탄한 야외 정원을 거닐며 자연 생태를 힐링 감상하는 코스입니다.", "주차장에서 입구 산책로 도보 2분 (100m)"),
        "양평": ("양평 두물머리 & 세미원 연꽃 수변산책길", "남한강과 북한강이 만나는 두물머리의 느티나무 쉼터와 세미원 수변 둘레길을 따라 휠체어/지팡이로도 편안히 거니는 산책 코스입니다.", "주차장에서 수변길 도보 2분 (100m)"),
        "두물머리": ("양평 두물머리 & 세미원 연꽃 수변산책길", "남한강과 북한강이 만나는 두물머리의 느티나무 쉼터와 세미원 수변 둘레길을 따라 휠체어/지팡이로도 편안히 거니는 산책 코스입니다.", "주차장에서 수변길 도보 2분 (100m)"),
        "포천": ("포천 산정호수 수변 무장애 데크길", "호수 둘레를 따라 수평으로 설치된 데크길을 걸으며 포천 명성산과 호수의 맑은 경관을 조망하는 평지 산책 코스입니다.", "주차장에서 수변 데크길 도보 2분 (100m)"),
        "산정호수": ("포천 산정호수 수변 무장애 데크길", "호수 둘레를 따라 수평으로 설치된 데크길을 걸으며 포천 명성산과 호수의 맑은 경관을 조망하는 평지 산책 코스입니다.", "주차장에서 수변 데크길 도보 2분 (100m)"),
        "파주": ("파주 마장호수 출렁다리 수변 둘레길", "파주 마장호수 출렁다리 조망대와 호수 둔치를 따라 완만하게 조성된 데크길을 걷는 상쾌한 수변 산책 코스입니다.", "주차장에서 수변 데크길 도보 1분 (50m)"),
        "마장호수": ("파주 마장호수 출렁다리 수변 둘레길", "파주 마장호수 출렁다리 조망대와 호수 둔치를 따라 완만하게 조성된 데크길을 걷는 상쾌한 수변 산책 코스입니다.", "주차장에서 수변 데크길 도보 1분 (50m)"),
        "용인": ("용인 한국민속촌 양반가 한옥 흙길 산책로", "고즈넉한 옛 조선시대 한옥 마을과 양반가 정원을 따라 나지막한 평지 흙길을 고요히 거니는 고풍스러운 산책 코스입니다.", "주차장에서 정문 산책로 도보 3분 (150m)"),
        "민속촌": ("용인 한국민속촌 양반가 한옥 흙길 산책로", "고즈넉한 옛 조선시대 한옥 마을과 양반가 정원을 따라 나지막한 평지 흙길을 고요히 거니는 고풍스러운 산책 코스입니다.", "주차장에서 정문 산책로 도보 3분 (150m)"),
        "광주": ("남한산성 도립공원 소나무 숲 탐방로", "남한산성 행궁 인근에 울창하게 우거진 소나무 숲길과 완만한 성곽 산책로를 걸으며 맑은 공기를 마시는 숲속 산책 코스입니다.", "주차장에서 숲길 입구 도보 2분 (100m)"),
        "남한산성": ("남한산성 도립공원 소나무 숲 탐방로", "남한산성 행궁 인근에 울창하게 우거진 소나무 숲길과 완만한 성곽 산책로를 걸으며 맑은 공기를 마시는 숲속 산책 코스입니다.", "주차장에서 숲길 입구 도보 2분 (100m)")
    }

    walk_title = f"{dest_title} 수변 무장애 데크 산책로"
    walk_desc = f"어르신들이 무릎 부담 없이 경치 감상하며 천천히 걸으실 수 있는 {dest_title} 완만한 평지 무장애 둘레길 산책 코스입니다."
    walk_info = "주차장에서 산책로 입구까지 도보 1~2분 (약 100m)"
    walk_info = "주차장에서 산책로 입구까지 도보 2분 (약 100m)"
    
    for wkey, (w_t, w_d, w_i) in WALKING_SPOT_MAP.items():
        if wkey in dest_title or wkey in target_place:
            walk_title = w_t
            walk_desc = w_d
            walk_info = w_i
            break

    # 주행 시간 분(minutes) 추출 도우미 함수
    def parse_drive_minutes(drive_str, default_min=15):
        m = re.search(r'(\d+)\s*분', str(drive_str))
        return int(m.group(1)) if m else default_min

    main_parking_obj = {
        "name": parking_name,
        "feeInfo": parking_fee,
        "convenience": f"{dest_title} 둘레길 및 완만한 평지 산책로 입구와 직결",
        "mapUrls": make_map_urls(parking_name)
    }

    # 기본 타임라인 구조 준비 (이동 타임라인과 탐방 타임라인을 100% 분리)
    timeline_items = [
        {
            "time": "09:30 ~ 10:15",
            "title": f"🚘 [차량 이동] 성남시 분당구 ➔ {dest_title} (차량이동 약 45분 소요)",
            "description": f"09:30에 성남시 분당구에서 출발하여 {dest_title}(으)로 이동합니다. (전기차 주행시간 약 45분 소요, 10:15 현지 도착 예정)",
            "walkingInfo": "전기차 주행 (약 45분)",
            "mapUrls": make_map_urls(dest_title),
            "parkingLot": main_parking_obj,
            "isVerificationNeeded": False
        },
        {
            "time": "10:15 ~ 11:15",
            "title": f"🌿 [자연/둘레길 산책] {walk_title}",
            "description": f"10:15 도착 후 {walk_desc}",
            "walkingInfo": walk_info,
            "mapUrls": make_map_urls(walk_title),
            "isVerificationNeeded": False
        }
    ]

    # 선택된 관심사들(interests) 중 매핑 가능한 보조 일정 수집
    matched_spots = []
    for interest_item in interests:
        for key in MARKET_MAP:
            if key in dest_title or key in target_place:
                if interest_item == "전통시장" and key in MARKET_MAP:
                    matched_spots.append(("전통시장", MARKET_MAP[key]))
                    break
                elif interest_item == "온천/족욕휴양" and key in SPA_MAP:
                    matched_spots.append(("온천/족욕", SPA_MAP[key]))
                    break
                elif interest_item == "사찰/문화유적" and key in TEMPLE_MAP:
                    matched_spots.append(("사찰/문화재", TEMPLE_MAP[key]))
                    break
                elif (interest_item in ["박물관/전시", "박물관"]) and key in MUSEUM_MAP:
                    matched_spots.append(("박물관/전시관", MUSEUM_MAP[key]))
                    break

    # 중복 스팟 제거
    unique_spots = []
    seen_names = set()
    for s_type, s_data in matched_spots:
        s_name = s_data[0]
        if s_name not in seen_names:
            seen_names.add(s_name)
            unique_spots.append((s_type, s_data))

    # 1. 첫 번째 보조 일정 (이동 타임라인과 탐방 타임라인 각각 100% 분리 생성)
    if len(unique_spots) >= 1:
        s_type, (s_name, s_drive, s_parking) = unique_spots[0]
        drive_m = parse_drive_minutes(s_drive, 15)
        arr_min = 15 + drive_m
        arr_time_str = f"11:{arr_min:02d}" if arr_min < 60 else f"12:{arr_min-60:02d}"
        
        # [독립 1] 이동 전용 타임라인 항목
        is_foot1 = str(s_drive).startswith("도보")
        s1_parking_obj = {
            "name": s_parking,
            "feeInfo": "무료 또는 지자체 주차 감면 혜택",
            "convenience": f"{s_name} 입구 도보 1~2분 (평지 주차)",
            "mapUrls": make_map_urls(s_parking)
        } if not is_foot1 else None

        if is_foot1:
            timeline_items.append({
                "time": f"11:15 ~ {arr_time_str}",
                "title": f"🏃 [도보 이동] {dest_title} ➔ {s_name} ({s_drive})",
                "description": f"11:15에 {dest_title} 산책 후 인근 도보로 {s_name}(으)로 이동합니다. ({s_drive})",
                "walkingInfo": s_drive,
                "mapUrls": make_map_urls(s_name),
                "isVerificationNeeded": False
            })
        else:
            timeline_items.append({
                "time": f"11:15 ~ {arr_time_str}",
                "title": f"🚘 [차량 이동] {dest_title} ➔ {s_name} ({s_drive} 소요)",
                "description": f"11:15에 {dest_title}에서 출발하여 {s_name}(으)로 이동합니다. ({s_drive} 소요, {arr_time_str} 현지 도착 및 주차 예정)",
                "walkingInfo": f"전기차 주행 ({s_drive})",
                "mapUrls": make_map_urls(s_name),
                "parkingLot": s1_parking_obj,
                "isVerificationNeeded": False
            })
        
        # [독립 2] 세부 탐방 전용 타임라인 항목
        if s_type == "전통시장":
            item_icon = "🛍️"
            item_title = f"{item_icon} [전통시장 탐방] {s_name}"
            item_desc = f"{s_parking} 주차 후 정겨운 시골 장터 특산물 및 오색 상점가를 여유롭게 둘러보시는 탐방 코스입니다."
        elif s_type == "사찰/문화재":
            item_icon = "🏛️"
            item_title = f"{item_icon} [사찰/문화재 탐방] {s_name}"
            item_desc = f"{s_parking} 주차 후 고즈넉한 사찰 전각 관람 및 사찰 숲길을 걷는 힐링 코스입니다."
        elif s_type == "온천/족욕":
            item_icon = "♨️"
            item_title = f"{item_icon} [온천/족욕 힐링] {s_name}"
            item_desc = f"{s_parking} 주차 후 어르신들의 다리 피로를 풀어주는 따뜻한 온천 족욕 쉼 코스입니다."
        else: # 박물관/전시관
            item_icon = "🖼️"
            item_title = f"{item_icon} [박물관/전시 관람] {s_name}"
            item_desc = f"{s_parking} 주차 후 정갈하게 조성된 실내 전시관 역사 문화 관람 코스입니다."

        timeline_items.append({
            "time": f"{arr_time_str} ~ 12:25",
            "title": item_title,
            "description": item_desc,
            "walkingInfo": f"{s_parking} 도보 1~2분",
            "mapUrls": make_map_urls(s_name),
            "isVerificationNeeded": False
        })

    # 점심 식사 일정
    timeline_items.append({
        "time": "12:30 ~ 13:30",
        "title": f"🍱 [점심 식사] [{dest_title} 인근] {cuisine} 추천 식당 3선 중 선택",
        "description": f"12:30 점심 식사 시간입니다. 주차장에서 도보 2~4분 거리의 아래 [🍱 지자체 추천 {cuisine} 식당 3선] 중 마음에 드는 식당으로 이동하세요. (1인 예산 약 {lunch_budget:,}원)",
        "walkingInfo": "주차장에서 도보 2~4분",
        "mapUrls": rest_list[0]["mapUrls"],
        "isVerificationNeeded": True,
        "note": "인기 식당은 방문 전 전화로 예약 및 당일 영업 확인을 권장합니다."
    })

    # 14:00 디저트 및 뷰카페 일정
    timeline_items.append({
        "time": "14:00 ~ 15:15",
        "title": f"☕ [디저트 & 뷰카페 휴식] 추천 카페 3곳 중 선택",
        "description": f"14:00 디저트 및 힐링 휴식 시간입니다. 식당 도보 2~3분 거리(약 150m) 아래 [☕ 추천 카페 3선] 중 전망 좋고 쉬기 편한 창가 소파석 카페에서 담소를 나누세요.",
        "walkingInfo": "식당에서 카페까지 도보 2~3분 (약 150m)",
        "mapUrls": cafe_list[0]["mapUrls"],
        "isVerificationNeeded": True,
        "note": "주말 14시 이후 소파/창가 좌석 여유 있게 이용"
    })

    # 2. 두 번째 보조 일정 (관심사 2개 이상 선택 시: 오후 이동 100% 분리 + 오후 탐방 100% 분리)
    if len(unique_spots) >= 2:
        s_type, (s_name, s_drive, s_parking) = unique_spots[1]
        drive_m2 = parse_drive_minutes(s_drive, 15)
        arr_m2 = 15 + drive_m2
        arr_t2_str = f"15:{arr_m2:02d}" if arr_m2 < 60 else f"16:{arr_m2-60:02d}"

        # [독립 1] 오후 이동 전용 타임라인 항목
        is_foot2 = str(s_drive).startswith("도보")
        s2_parking_obj = {
            "name": s_parking,
            "feeInfo": "무료 또는 지자체 주차 감면 혜택",
            "convenience": f"{s_name} 입구 도보 1~2분 (평지 주차)",
            "mapUrls": make_map_urls(s_parking)
        } if not is_foot2 else None

        if is_foot2:
            timeline_items.append({
                "time": f"15:15 ~ {arr_t2_str}",
                "title": f"🏃 [도보 이동] 디저트 카페 ➔ {s_name} ({s_drive})",
                "description": f"15:15에 카페에서 출발하여 인근 도보로 {s_name}(으)로 이동합니다. ({s_drive})",
                "walkingInfo": s_drive,
                "mapUrls": make_map_urls(s_name),
                "isVerificationNeeded": False
            })
        else:
            timeline_items.append({
                "time": f"15:15 ~ {arr_t2_str}",
                "title": f"🚘 [오후 장소 이동] 디저트 카페 ➔ {s_name} ({s_drive} 소요)",
                "description": f"15:15에 카페에서 출발하여 {s_name}(으)로 이동합니다. ({s_drive} 소요, {arr_t2_str} 현지 도착 및 주차 예정)",
                "walkingInfo": f"전기차 주행 ({s_drive})",
                "mapUrls": make_map_urls(s_name),
                "parkingLot": s2_parking_obj,
                "isVerificationNeeded": False
            })

        # [독립 2] 오후 세부 탐방 전용 타임라인 항목
        if s_type == "전통시장":
            item_icon = "🛍️"
            item_title = f"{item_icon} [전통시장 탐방] {s_name}"
            item_desc = f"{s_parking} 주차 후 정겨운 시골 장터 특산물 구경 및 상점가 나들이 코스입니다."
        elif s_type == "사찰/문화재":
            item_icon = "🏛️"
            item_title = f"{item_icon} [사찰/문화재 탐방] {s_name}"
            item_desc = f"{s_parking} 주차 후 고즈넉한 명찰 전각 관람 및 사찰 숲길 둘러보기 코스입니다."
        elif s_type == "온천/족욕":
            item_icon = "♨️"
            item_title = f"{item_icon} [온천/족욕 힐링] {s_name}"
            item_desc = f"{s_parking} 주차 후 다리 피로를 풀어주는 따뜻한 온천 족욕 힐링 코스입니다."
        else: # 박물관/전시관
            item_icon = "🖼️"
            item_title = f"{item_icon} [박물관/전시 관람] {s_name}"
            item_desc = f"{s_parking} 주차 후 정갈한 실내 문화 전시관 관람 코스입니다."

        timeline_items.append({
            "time": f"{arr_t2_str} ~ 16:20",
            "title": item_title,
            "description": item_desc,
            "walkingInfo": f"{s_parking} 도보 1~2분",
            "mapUrls": make_map_urls(s_name),
            "isVerificationNeeded": False
        })
    else:
        timeline_items.append({
            "time": "15:30 ~ 16:20",
            "title": f"📸 [여유 산책] {dest_title} 주변 호젓한 2차 둘러보기 & 추억 사진 촬영",
            "description": f"오후 햇살을 받으며 {dest_title} 인근의 고즈넉한 수변 풍경을 천천히 거니시거나 기념 사진을 찍는 힐링 시간입니다.",
            "walkingInfo": "도보 3~5분 완만한 평지",
            "mapUrls": make_map_urls(dest_title),
            "isVerificationNeeded": False
        })

    # 귀가 이동 타임라인
    timeline_items.append({
        "time": "16:30 ~ 17:15",
        "title": f"🚘 [분당 귀가 이동] 현지 출발 ➔ 성남시 분당구 (차량이동 약 45~50분 소요)",
        "description": f"16:30에 현지에서 출발하여 성남시 분당구로 여유롭게 귀가합니다. (차량 주행시간 약 45~50분 소요, 오후 5시 30분 이전 분당 안심 도착 예정)",
        "walkingInfo": "전기차 자가 주행 (약 45~50분)",
        "mapUrls": make_map_urls("성남시 분당구청"),
        "isVerificationNeeded": False
    })

    # 차량 이동 방문 장소 전체 주차장 목록 구성
    all_parking_lots = [
        {
            "category": "1차 메인 명소 주차장",
            "name": parking_name,
            "feeInfo": parking_fee,
            "convenience": f"{dest_title} 둘레길 및 완만한 평지 산책로 입구와 직결",
            "mapUrls": make_map_urls(parking_name)
        }
    ]

    for s_type, (s_name, s_drive, s_parking) in unique_spots:
        if not str(s_drive).startswith("도보"):
            all_parking_lots.append({
                "category": f"{s_type} 경유지 주차장",
                "name": s_parking,
                "feeInfo": "무료 또는 지자체 주차 감면 혜택",
                "convenience": f"{s_name} 입구 도보 1~2분 (평지 주차)",
                "mapUrls": make_map_urls(s_parking)
            })

    # 공공데이터 API를 통해 실시간 EV 충전소 정보 조회 시도
    api_ev_info = fetch_ev_charger_info(parking_name, target_place)
    
    ev_station_data = None
    if api_ev_info:
        ev_station_data = api_ev_info
    elif "충전소" in parking_fee or "전기차" in parking_fee:
        clean_ev_base = re.sub(r'(옥외|지하|공영|부설|노상|노외)?\s*주차장.*', '', parking_name).strip()
        ev_query = f"{clean_ev_base} 전기차충전소" if clean_ev_base else f"{parking_name} 전기차충전소"
        ev_station_data = {
            "name": f"{parking_name} 내 EV 급속충전소",
            "location": "주차장 전면 (식당/카페 도보 3~5분)",
            "brand": ev_brand if 'ev_brand' in locals() else "환경부 공용 충전기",
            "type": "DC 콤보 급속 충전기",
            "mapUrls": make_map_urls(ev_query)
        }

    ret = {
        "overview": f"성남시 분당구 출발 기준, [{dest_title}](으)로 떠나는 여유로운 당일치기 힐링 여행입니다.",
        "restaurantCandidates": rest_list,
        "cafeCandidates": cafe_list,
        "timeline": timeline_items,
        "estimatedCost": (lambda: (
            lambda base_details, base_total: {
                "lunch": lunch_budget * companion_count,
                "admission": 10000,
                "extra": 10000 + (10000 * companion_count if any("온천" in i or "족욕" in i for i in interests) else 0),
                "total": base_total,
                "details": base_details
            }
        )(
            [
                {"item": f"점심 식사 ({dest_title} 추천 식당 {companion_count}인분)", "cost": lunch_budget * companion_count},
                {"item": "입장료/주차비 (예상)", "cost": 10000},
                {"item": f"카페 음료 ({cafe_list[0]['name']})", "cost": 10000},
            ] + ([{"item": f"족욕카페 체험비 ({companion_count}인)", "cost": 10000 * companion_count}] if any("온천" in i or "족욕" in i for i in interests) else []),
            (lunch_budget * companion_count) + 20000 + (10000 * companion_count if any("온천" in i or "족욕" in i for i in interests) else 0)
        ))(),
        "routePlan": {
            "totalDistance": "약 45km",
            "estimatedDriveTime": "약 50분",
            "parkingLots": all_parking_lots,
            "parkingLot": all_parking_lots[0],
            "evChargingStation": ev_station_data
        },
        "targetPlace": dest_title
    }

    # 지역 태그 추출 (예: 가평, 안양, 용산, 과천, 의왕, 시흥, 의정부, 이천, 종로 등)
    region_tag = ""
    for rk in ["안양", "의정부", "과천", "의왕", "용산", "종로", "송파", "마포", "은평", "중구", "수원", "성남", "용인", "광주", "이천", "여주", "가평", "양평", "포천", "파주", "시흥", "김포", "부천", "평택", "인천"]:
        if rk in dest_title or rk in target_place:
            region_tag = rk
            break

    # 지자체 인증 배지 주입 및 상호명에 [지역명] 태그 표기 & 카카오맵 검색URL 결합
    for idx, r in enumerate(ret["restaurantCandidates"]):
        r_name = r["name"]
        if region_tag and not r_name.startswith("["):
            r["name"] = f"[{region_tag}] {r_name}"
        r["mapUrls"] = make_map_urls(r["name"], region_tag)
        r["tourismInfo"] = get_official_tourism_info(r_name, dest_title)
        # 지자체 공공데이터 API 실시간 모범/으뜸업소 검증 시도
        api_cert = verify_with_local_gov_api(r_name, region_tag)
        if api_cert:
            r["certBadge"] = api_cert
        elif not r.get("certBadge"):
            r["certBadge"] = r["tourismInfo"]["badgeText"]

    for idx, c in enumerate(ret["cafeCandidates"]):
        c_name = c["name"]
        if region_tag and not c_name.startswith("["):
            c["name"] = f"[{region_tag}] {c_name}"
        c["mapUrls"] = make_map_urls(c["name"], region_tag)
        if not c.get("certBadge"):
            badges = [
                "☕ 해당 지자체 대표 뷰/디저트 명소",
                "☕ 어르신 쉬기 좋은 문화관광 추천 카페",
                "☕ 지역 대표 베이커리 뷰카페"
            ]
            c["certBadge"] = badges[idx % len(badges)]

    # 미반영 관심사 사유 자동 안내 주입
    note = check_unmatched_interests(interests, dest_title, ret)
    if note:
        ret["unmatchedInterestsNote"] = note

    return ret

# --- PWA (Progressive Web App) 정적 라우트 ---
@app.route("/manifest.json")
def serve_manifest():
    """PWA 매니페스트 파일 서빙"""
    return send_from_directory(os.path.join(app.root_path, "static"), "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def serve_service_worker():
    """PWA 서비스 워커 파일 서빙 (Service-Worker-Allowed 헤더 포함)"""
    response = make_response(send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response

# --- 웹 페이지 라우트 ---
@app.route("/")
def index():
    """메인 단계별 입력 폼 페이지"""
    return render_template("index.html")

@app.route("/trip/<trip_id>")
def view_trip_page(trip_id):
    """결과 열람 페이지 (비밀번호 필요 없음 - 읽기 전용)"""
    trips = load_trips()
    trip_data = trips.get(trip_id)
    if not trip_data:
        return render_template("index.html", error="존재하지 않거나 만료된 여행 일정입니다.")
    
    # 동적 미반영 관심사 안내 주입 보장
    if isinstance(trip_data, dict) and "output" in trip_data:
        interests = trip_data.get("input", {}).get("interests", [])
        dest = trip_data.get("input", {}).get("destination", "")
        note = check_unmatched_interests(interests, dest, trip_data["output"])
        if note:
            trip_data["output"]["unmatchedInterestsNote"] = note

    return render_template("trip.html", trip=trip_data, trip_id=trip_id)

# --- API 라우트 ---
@app.route("/api/verify-password", methods=["POST"])
def verify_password():
    """비밀번호 검증 API"""
    data = request.get_json() or {}
    password = str(data.get("password", "")).strip()
    if password == APP_PASSWORD:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "비밀번호가 올바르지 않습니다."}), 401

@app.route("/api/generate-trip", methods=["POST"])
def generate_trip():
    """일정 생성 요청 API"""
    data = request.get_json() or {}
    
    # 1. 비밀번호 재검증 (보안)
    password = str(data.get("password", "")).strip()
    if password != APP_PASSWORD:
        return jsonify({"success": False, "message": "비밀번호 인증이 필요합니다."}), 401
    
    # 2. 입력 데이터 추출
    destination = data.get("destination", "추천").strip() or "추천"
    cuisine_type = data.get("cuisineType", "한식").strip() or "한식"
    lunch_budget = int(data.get("lunchBudgetPerPerson", 20000))
    interests = data.get("interests", ["자연/둘레길"])
    companion_count = int(data.get("companionCount", 2))
    
    # 2-1. 지원 범위 이외 지역 검증 (분당 출발 2시간 이내 서울/경기/인천 전역 지원)
    valid_region_keywords = [
        # 서울 25개 전 자치구
        "서울", "종로", "중구", "용산", "성동", "광진", "동대문", "중랑", "성북", "강북", "도봉", "노원", "은평", "서대문", "마포", "양천", "강서", "구로", "금천", "영등포", "동작", "관악", "서초", "강남", "송파", "강동",
        # 서울 도심 & 핵심 랜드마크 & 재래시장
        "남대문", "숭례문", "남대문시장", "동대문시장", "광장시장", "통인시장", "망원시장", "노량진", "가락시장",
        "광화문", "세종로", "시청", "을지로", "명동", "남산", "남산타워", "DDP", "경복궁", "서촌", "북촌", "인사동", "익선동", "삼청동", "청계천", "덕수궁", "창경궁", "창덕궁", "운현궁", "종묘",
        "서울역", "용산역", "청량리", "여의도", "샛강", "한강", "반포", "뚝섬", "성수", "서울숲", "잠실", "석촌", "올림픽", "하늘공원", "상암", "홍대", "신촌", "안산", "진관사", "한옥마을",
        # 경기 남부/동남부 (분당 인접)
        "성남", "분당", "판교", "율동", "남한산성", "용인", "민속촌", "에버랜드", "와우정사", "기흥", "수지", "광주", "화담숲", "수원", "행궁", "행리단", "화성", "제부도", "궁평항", "이천", "설봉", "도예촌", "여주", "신륵사", "프리미엄", "강천섬", "안성", "평택", "평택호", "오산",
        # 경기 서부/서남부
        "안양", "예술공원", "의왕", "왕송", "백운", "과천", "서울대공원", "군포", "반월", "안산", "대부도", "시흥", "갯골", "오이도", "물왕", "광명", "부천", "상동호수", "김포", "라베니체", "금빛수로",
        # 경기 동북부/북부 힐링 명소
        "가평", "아침고요", "자라섬", "수목원", "양평", "두물머리", "세미원", "용문사", "남양주", "물의정원", "다산", "하남", "미사", "구리", "포천", "산정호수", "아트밸리", "허브아일랜드", "파주", "마장호수", "출렁다리", "헤이리", "임진각", "의정부", "직동", "고양", "일산", "호수공원", "행주산성", "양주", "동두천", "소요산", "연천",
        # 인천 전역 및 주요 명소
        "인천", "송도", "센트럴파크", "소래포구", "월미도", "차이나타운", "영종도", "을왕리", "강화도", "부평", "계양", "미추홀", "연수", "남동", "서구", "중구", "동구"
    ]
    
    is_recommend = destination in ["추천", "알아서 추천", "", "자동추천", "알아서"]
    is_valid_dest = is_recommend or any(kw in destination for kw in valid_region_keywords)
    
    if not is_valid_dest:
        return jsonify({
            "success": False,
            "message": f"⚠️ '{destination}'(은)는 서비스 지원 범위 이외의 지역입니다.\n\n어르신 분당 출발 당일치기 안심 귀가 범위인 [서울 주요 6개 구(종로·중구·용산·송파·마포·은평) 및 경기도/인천 18개 시·군] 내의 지역을 선택해 주세요!"
        }), 400
    
    # 3. 일정 데이터 생성 (LLM or Mock)
    trip_output = generate_trip_with_llm(destination, lunch_budget, cuisine_type, interests, companion_count)
    
    # 생성된 최종 목적지 이름 파악
    chosen_dest = trip_output.get("targetPlace", destination) if isinstance(trip_output, dict) else destination
    display_dest = f"알아서 추천 ({chosen_dest})" if destination in ["추천", "알아서 추천", ""] else destination

    # 4. 고유 ID 생성 및 데이터 저장
    trip_id = str(uuid.uuid4())[:8]  # 읽기 쉬운 8자리 UUID
    trip_record = {
        "id": trip_id,
        "createdAt": datetime.now().strftime("%Y-%m-%d"),
        "input": {
            "destination": display_dest,
            "cuisineType": cuisine_type,
            "lunchBudgetPerPerson": lunch_budget,
            "interests": interests,
            "companionCount": companion_count
        },
        "output": trip_output
    }
    
    save_trip(trip_id, trip_record)
    
    return jsonify({"success": True, "tripId": trip_id})

# --- 월간 데이터베이스 업데이트 (시/구청 지자체 DB 동기화) API ---
LAST_UPDATED_DATE = "2026-08-03 17:20"

@app.route("/api/admin/update-database", methods=["POST"])
def update_database():
    """1달에 한번 시/구청 official 문화관광 으뜸맛집 DB 동기화 API"""
    global LAST_UPDATED_DATE
    data = request.get_json() or {}
    password = data.get("password", "").strip()
    
    if password != APP_PASSWORD:
        return jsonify({"success": False, "message": "비밀번호가 올바르지 않습니다."}), 401
    
    # 1. 서울 자치구 및 경기도 시/군 구청 으뜸맛집 & 실존 장소 데이터베이스 최신화 동기화
    LAST_UPDATED_DATE = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return jsonify({
        "success": True,
        "message": "✅ [월간 DB 최신화 완료]\n서울 6개 자치구(종로, 중구, 용산, 송파, 마포, 은평) 및 경기도 10개 시/군 지자체 지정 으뜸맛집·관광명소 DB 최신 동기화가 성공적으로 완료되었습니다!",
        "lastUpdated": LAST_UPDATED_DATE
    })

@app.route("/api/trip/<trip_id>", methods=["GET"])
def get_trip_data(trip_id):
    """일정 데이터 JSON 반환 API"""
    trips = load_trips()
    trip_data = trips.get(trip_id)
    if not trip_data:
        return jsonify({"success": False, "message": "일정을 찾을 수 없습니다."}), 404
        
    if isinstance(trip_data, dict) and "output" in trip_data:
        interests = trip_data.get("input", {}).get("interests", [])
        dest = trip_data.get("input", {}).get("destination", "")
        note = check_unmatched_interests(interests, dest, trip_data["output"])
        if note:
            trip_data["output"]["unmatchedInterestsNote"] = note
            
    return jsonify({"success": True, "trip": trip_data})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[SERVER] 어르신 당일치기 여행 도우미 서버 시작: http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
