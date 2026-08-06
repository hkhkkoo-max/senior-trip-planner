# 🚗 어르신 맞춤 당일치기 여행 도우미 (Senior Trip Planner)

성남시 분당구에 거주하시는 **70대 이상 어르신**들이 간단한 폼 입력만으로 분당 출발 2시간 이내 지역의 **당일치기 여행 일정**을 자동으로 추천받는 시니어 특화 웹 서비스입니다.

---

## 📌 주요 핵심 기능 (Key Features)

1. **시니어 맞춤 접근성 UI/UX**
   - **18px+ 대형 폰트** (`Pretendard` 웹폰트) 및 눈이 편안한 고대비 배색
   - **1화면 1질문 단계별 마법사 입력 폼** (이전/다음 손쉬운 이동)
   - **56px 이상 대형 손가락 터치 버튼** 및 어르신 친화적 가독성 설계

2. **비밀번호 보안 게이트**
   - 일정 생성 시 공용 비밀번호 게이트(`APP_PASSWORD`)를 적용하여 API 남용 방지
   - 생성된 여행 결과 페이지(`/trip/{id}`)는 비밀번호 없이 가족/지인과 카카오톡/문자 등으로 자유롭게 공유 가능

3. **당일치기 & 전기차(EV) 자가운전 특화**
   - **오전 9:30 출발 ~ 17:30 분당 안심 귀가** 시간표 고정 (오후 5:30 전 분당 도착)
   - 이동 경로 상 **전기차 급속 충전소** 정보 조회 및 공영주차장 요금(전기차 50% 감면) 표시
   - **방문 장소별 주차장 목록 및 카카오맵 길찾기 1:1 연동**

4. **독립 타임라인 & 다중 관심사 지원**
   - `🚗 [장소 이동]` 카드와 `🛍️ [전통시장 탐방]` 카드가 독립 분리되어 출발/도착 시각 및 주행시간(분) 명시
   - 관심사를 2개 이상 선택 시 **오전 11:15(1차)와 오후 15:30(2차) 슬롯으로 자동 분배**

5. **카카오맵 (Kakao Map) 100% 정밀 POI 검색 연동 & PDF/인쇄 최적화**
   - 장소명 오검색 방지 정제 로직 (`clean_place_name`)으로 수식어/특수문자 제거 후 100% Kakao Map 등록 매장 및 주차장 연결
   - A4 인쇄 / PDF 저장 시 식당 및 카페의 **전화번호(`📞 031-XXX-XXXX`) 및 주차 정보가 100% 선명하게 포함**

---

## 🛠️ 기술 스택 (Tech Stack)

| 구분 | 사용 기술 |
|---|---|
| **Backend** | Python 3.10+, Flask, `google-genai` (Google Gemini AI), `python-dotenv` |
| **Frontend** | HTML5, CSS3 (Vanilla & Pretendard Font), JavaScript (ES6+ Fetch) |
| **Database** | Lightweight JSON File DB (`trips.json`) |
| **Map & EV API** | Kakao Map Search & Route Deep Linking, 서울시/공공데이터 EV 충전소 정보 |
| **Server WSGI** | Gunicorn (클라우드 배포용) |

---

## 📁 프로젝트 폴더 구조 (Directory Structure)

```text
senior-trip-planner/
├── app.py                  # Flask 백엔드 서버, Gemini AI 연동 & 데이터 정제 로직
├── check_parking.py        # 주차장 및 충전소 데이터 검증 도구
├── requirements.txt        # 파이썬 의존성 패키지 목록 (Flask, google-genai, gunicorn 등)
├── PROJECT_SPEC.md         # 프로젝트 상세 스펙 문서
├── README.md               # 프로젝트 종합 안내 문서
├── trips.json              # 생성된 여행 일정 데이터베이스 (JSON 파일)
├── templates/
│   ├── index.html          # 시니어 마법사 입력 폼 템플릿
│   └── trip.html           # 일정 결과 및 카카오톡/PDF 공유 템플릿
static/
├── css/
│   └── style.css       # 시니어 접근성 UI 및 인쇄 전용 CSS
└── js/
    └── app.js          # 비동기 통신, 마법사 폼 컨트롤러 & 데이터 검증
```

---

## 🏁 로컬 실행 가이드 (Quick Start)

### 1. 가상환경 활성화 (Windows PowerShell)
```powershell
.\venv\Scripts\Activate.ps1
```

### 2. 의존성 패키지 설치
```powershell
pip install -r requirements.txt
```

### 3. 환경변수 (`.env`) 설정
프로젝트 루트 경로에 `.env` 파일을 생성하고 아래 내용을 입력합니다.
```env
GEMINI_API_KEY=<YOUR_GEMINI_API_KEY>
APP_PASSWORD=<YOUR_APP_PASSWORD>
FLASK_SECRET_KEY=<YOUR_FLASK_SECRET_KEY>
```

### 4. 웹 서버 실행
```powershell
python app.py
```
👉 로컬 접속 주소: **`http://127.0.0.1:5000`**

---

## 🚀 배포 및 공유 방법 (Deployment & Sharing)

### 방법 1: ngrok (1분 임시 외부 공유)
내 PC에서 서버를 실행 중일 때 스마트폰이나 지인에게 임시 링크로 공유하는 방법입니다.

1. [ngrok.com](https://ngrok.com) 회원가입 및 설치
2. 터미널에서 다음 명령어 실행:
   ```bash
   ngrok http 5000
   ```
3. 생성된 `https://xxxx.ngrok-free.app` 주소를 전달하여 접속

---

### 방법 2: Render.com (24시간 상시 무료 호스팅 추천 🌟)
PC를 꺼두어도 365일 언제든지 접속할 수 있는 서비스입니다.

1. **GitHub에 코드 푸시** (`.env` 및 `venv` 제외)
2. **[Render.com](https://render.com) 접속** ➔ **[New] ➔ [Web Service]** 클릭
3. **주요 설정 값**:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app.py:app`
4. **Environment Variables 설정**:
   - `GEMINI_API_KEY`: Google Gemini API 키
   - `APP_PASSWORD`: 사용자가 지정할 비밀번호 (예: 원하는 숫자/문자)
   - `FLASK_SECRET_KEY`: 임의의 비밀키 문자열
5. **[Create Web Service]** 실행 완료 후 제공되는 전용 URL로 접속
