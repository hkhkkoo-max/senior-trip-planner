# 🚗 어르신 맞춤 당일치기 여행 도우미 (Senior Trip Planner)

성남시 분당구에 거주하시는 **70대 이상 어르신**들이 간단한 입력만으로 분당 출발 2시간 이내 지역의 **당일치기 여행 일정**을 자동으로 추천받는 시니어 특화 웹 서비스입니다.

---

## 📌 주요 핵심 기능 (Key Features)

1. **시니어 맞춤 접근성 UI/UX**
   - 18px+ 대형 폰트 (`Pretendard` 웹폰트) 및 눈이 편안한 명암비
   - 1화면 1질문 단계별 마법사 입력 폼 (이전/다음 손쉬운 이동)
   - 56px 이상 대형 손가락 터치 버튼 및 어르신 친화적 디자인

2. **비밀번호 보안 게이트**
   - 일정 생성에는 공용 비밀번호 게이트(`APP_PASSWORD`) 적용으로 API 남용 방지
   - 생성된 여행 결과 페이지(`/trip/{id}`)는 비밀번호 없이 가족/지인과 자유롭게 카카오톡/문자 공유 가능

3. **당일치기 & 전기차(EV) 자가운전 특화**
   - 오전 9:30 출발 ~ 17:30 분당 안심 귀가 시간표 고정 (오후 5:30 전 분당 도착)
   - 이동 경로 상 전기차 급속 충전소 및 공영주차장 요금 (전기차 50% 감면 혜택) 명시
   - **방문 장소별 전체 주차장 목록(메인 명소 주차장 + 경유지 주차장) 카카오맵 연동 제공**

4. **1:1 독립 타임라인 & 다중 관심사 지원**
   - `🚗 [장소 이동]` 카드와 `🛍️ [전통시장 탐방]` 카드가 100% 독립 분리되어 출발/도착 시각 및 차량 주행시간(분) 명시
   - 관심사를 2개 이상 선택 시 **오전 11:15(1차)와 오후 15:30(2차) 슬롯으로 자동 분배**

5. **카카오맵 (Kakao Map) 100% 정밀 검색 연동 & PDF/인쇄 최적화**
   - 상호명에 `[지역명]` 태그를 자동 부여하고, 오검색 방지 알고리즘(`clean_place_name`)으로 100% Kakao Map 등록 매장 연결
   - **`생성일: YYYY-MM-DD`** 날짜 정제 표기
   - A4 인쇄 / PDF 저장 시 식당 및 카페의 **전화번호(`📞 031-XXX-XXXX`)가 100% 선명하게 포함되어 출력**

---

## 🛠️ 기술 스택 (Tech Stack)

| 구분 | 사용 기술 |
|---|---|
| **Backend** | Python 3.10+, Flask, `google-genai` (Google Gemini AI), `python-dotenv` |
| **Frontend** | HTML5, CSS3 (Vanilla & Pretendard Font), JavaScript (ES6+ Fetch) |
| **Database** | Lightweight JSON File DB (`trips.json`) |
| **Map Linking** | Kakao Map Search & Route Deep Linking |
| **Server WSGI** | Gunicorn (클라우드 배포용) |

---

## 📁 프로젝트 폴더 구조 (Directory Structure)

```text
senior-trip-planner/
├── app.py              # Flask 백엔드 서버 & 비즈니스 로직
├── requirements.txt    # 파이썬 의존성 패키지 목록 (Flask, google-genai 등)
├── .env                # API Key 및 공용 비밀번호 (보안 파일)
├── .gitignore          # Git 업로드 제외 대상 파일
├── README.md           # 프로젝트 종합 안내 문서
├── templates/
54: │   ├── index.html      # 메인 마법사 입력 폼 템플릿
55: │   └── trip.html       # 일정 결과 및 카카오톡/PDF 공유 템플릿
static/
├── css/
│   └── style.css   # 시니어 접근성 디자인 및 프린트 CSS
└── js/
    └── app.js      # 프론트엔드 비동기 통신 및 폼 검증
```

---

## 🏁 로컬 실행하기 (Local Getting Started)

### 1. 가상환경 활성화
```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
```

### 2. 패키지 설치
```powershell
pip install -r requirements.txt
```

### 3. 환경변수 (`.env`) 설정
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
APP_PASSWORD=4775
FLASK_SECRET_KEY=senior_trip_secret_2026
```

### 4. 웹 서버 실행
```powershell
python app.py
```
👉 접속 주소: **`http://127.0.0.1:5000`**

---

## 🚀 지인 배포 및 공유 방법 (Deployment Guide)

### 방법 A. ngrok 이용하기 (1분 초간단 임시 공유)
내 PC에서 서버를 띄워놓고 지인에게 주소만 빠르게 보내서 보여주고 싶을 때 사용합니다.

1. [ngrok.com](https://ngrok.com)에서 무료 회원가입 후 설치
2. 터미널에서 다음 명령 실행:
   ```bash
   ngrok http 5000
   ```
3. 생성된 `https://xxxx.ngrok-free.app` 주소를 지인에게 전달하면 스마트폰으로 바로 접속 가능합니다.

---

### 방법 B. Render.com 이용하기 (24시간 상시 무료 호스팅 - 추천! 🌟)
내 PC를 꺼두어도 지인들이 언제든지 24시간 스마트폰으로 접속할 수 있습니다.

1. **GitHub에 코드 업로드**:
   본 프로젝트 코드를 GitHub 레포지토리에 올립니다 (`.env` 파일 제외).
2. **Render.com 접속**:
   [render.com](https://render.com) 가입 후 **[New] ➔ [Web Service]** 클릭
3. **설정값 입력**:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app.py:app`
4. **Environment Variables 설정**:
   - `GEMINI_API_KEY`: 발급받은 Gemini API 키
   - `APP_PASSWORD`: `4775`
5. **[Create Web Service]** 클릭 ➔ 몇 분 후 `https://senior-trip-planner.onrender.com` 과 같은 전용 주소가 완성됩니다!
