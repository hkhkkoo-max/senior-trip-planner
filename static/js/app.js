// 폼 전역 상태 관리
let currentStep = 0;
let userPassword = "";
let selectedDestination = "추천";
let selectedCuisine = "한식";
let selectedLunchBudget = 10000;
let selectedInterests = [];
let companionCount = 2;

// [STEP 0] 비밀번호 확인
async function checkPassword() {
    const passwordInput = document.getElementById("inputPassword").value.trim();
    const errorDiv = document.getElementById("passwordError");
    errorDiv.innerText = "";

    if (!passwordInput) {
        errorDiv.innerText = "비밀번호를 입력해 주세요.";
        return;
    }

    try {
        const response = await fetch("/api/verify-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: passwordInput })
        });

        let data;
        try {
            data = await response.json();
        } catch (e) {
            errorDiv.innerText = "서버 응답 형식 오류가 발생했습니다. (Flask 서버 로그 확인 필요)";
            return;
        }

        if (response.ok && data.success) {
            userPassword = passwordInput;
            document.getElementById("progressContainer").style.display = "block";
            nextStep(1);
        } else {
            errorDiv.innerText = data.message || "비밀번호가 올바르지 않습니다.";
        }
    } catch (err) {
        errorDiv.innerText = "서버 통신 중 오류가 발생했습니다. (Flask 서버가 실행 중인지 확인해 주세요)";
    }
}

// URL 전용 자동 비밀번호 인증 처리 (?pass=4775 또는 ?key=4775 접속 시 자동 통과)
window.addEventListener("DOMContentLoaded", () => {
    const urlParams = new URLSearchParams(window.location.search);
    const passParam = urlParams.get("pass") || urlParams.get("key");
    if (passParam) {
        const passInput = document.getElementById("inputPassword");
        if (passInput) {
            passInput.value = passParam;
            checkPassword();
        }
    }
});

// 단계 이동 제어
function showStep(step) {
    document.querySelectorAll(".step-section").forEach(sec => sec.classList.remove("active"));
    const targetSection = document.getElementById(`step${step}`);
    if (targetSection) {
        targetSection.classList.add("active");
    }

    // 진행 상황 바 업데이트 (총 5단계)
    if (step >= 1 && step <= 5) {
        currentStep = step;
        const progressPercent = (step / 5) * 100;
        document.getElementById("progressBar").style.width = `${progressPercent}%`;
        document.getElementById("progressText").innerText = `${step}단계 / 5단계`;
    }
}

const VALID_REGION_KEYWORDS = [
    // 서울 25개 전 자치구
    "서울", "종로", "중구", "용산", "성동", "광진", "동대문", "중랑", "성북", "강북", "도봉", "노원", "은평", "서대문", "마포", "양천", "강서", "구로", "금천", "영등포", "동작", "관악", "서초", "강남", "송파", "강동",
    // 서울 도심 & 핵심 랜드마크 & 재래시장
    "남대문", "숭례문", "남대문시장", "동대문시장", "광장시장", "통인시장", "망원시장", "노량진", "가락시장",
    "광화문", "세종로", "시청", "을지로", "명동", "남산", "남산타워", "DDP", "경복궁", "서촌", "북촌", "인사동", "익선동", "삼청동", "청계천", "덕수궁", "창경궁", "창덕궁", "운현궁", "종묘",
    "서울역", "용산역", "청량리", "여의도", "샛강", "한강", "반포", "뚝섬", "성수", "서울숲", "잠실", "석촌", "올림픽", "하늘공원", "상암", "홍대", "신촌", "안산", "진관사", "한옥마을",
    // 경기 남부/동남부 (분당 인접)
    "성남", "분당", "판교", "율동", "남한산성", "용인", "민속촌", "에버랜드", "와우정사", "기흥", "수지", "광주", "화담숲", "수원", "행궁", "행리단", "화성", "제부도", "궁평항", "이천", "설봉", "도예촌", "여주", "신륵사", "프리미엄", "강천섬", "안성", "평택", "평택호", "오산",
    // 경기 서부/서남부
    "안양", "예술공원", "의왕", "왕송", "백운", "과천", "서울대공원", "군포", "반월", "안산", "대부도", "시흥", "갯골", "오이도", "물왕", "광명", "부천", "상동호수", "김포", "라베니체", "금빛수로",
    // 경기 동북부/북부 힐링 명소
    "가평", "아침고요", "자라섬", "수목원", "양평", "두물머리", "세미원", "용문사", "남양주", "물의정원", "다산", "하남", "미사", "구리", "포천", "산정호수", "아트밸리", "허브아일랜드", "파주", "마장호수", "출렁다리", "헤이리", "임진각", "의정부", "직동", "고양", "일산", "호수공원", "행주산성", "양주", "동두천", "소요산", "연천",
    // 인천 전역 및 주요 명소
    "인천", "송도", "센트럴파크", "소래포구", "월미도", "차이나타운", "영종도", "을왕리", "강화도", "부평", "계양", "미추홀", "연수", "남동", "서구", "중구", "동구"
];

function nextStep(step) {
    if (currentStep === 1 && step === 2) {
        const customInput = document.getElementById("customDest");
        const customVal = customInput ? customInput.value.trim() : "";
        const targetDest = customVal || selectedDestination;

        const isRecommend = !targetDest || ["추천", "알아서 추천", "", "자동추천", "알아서"].includes(targetDest);
        const isValid = isRecommend || VALID_REGION_KEYWORDS.some(kw => targetDest.includes(kw));

        if (!isValid) {
            alert(`⚠️ '${targetDest}'(은)는 서비스 지원 범위 이외의 지역입니다.\n\n어르신 분당 출발 당일치기 안심 귀가 범위인 [서울 주요 6개 구(종로·중구·용산·송파·마포·은평) 및 경기도/인천 18개 시·군] 내의 지역을 선택해 주세요!`);
            if (customInput) {
                customInput.focus();
            }
            return;
        }
        selectedDestination = isRecommend ? "추천" : targetDest;
    }
    showStep(step);
}

function prevStep(step) {
    showStep(step);
}

// [STEP 1] 목적지 선택
function selectDestination(dest, btnElement) {
    const customInput = document.getElementById("customDest");
    const val = customInput ? customInput.value.trim() : "";
    if (val) {
        selectedDestination = val;
    } else {
        selectedDestination = "추천";
    }
    document.querySelectorAll("#step1 .option-btn").forEach(btn => btn.classList.remove("active"));
    if (btnElement) btnElement.classList.add("active");
    console.log("선택된 목적지:", selectedDestination);
}

function onCustomDestInput(inputElement) {
    const val = inputElement.value.trim();
    if (val) {
        selectedDestination = val;
    } else {
        selectedDestination = "추천";
    }
    console.log("입력된 목적지:", selectedDestination);
}

// [STEP 2] 음식 종류(한식/양식/일식/중식) 선택
function selectCuisine(cuisine, btnElement) {
    selectedCuisine = cuisine;
    document.querySelectorAll("#step2 .option-btn").forEach(btn => btn.classList.remove("active"));
    btnElement.classList.add("active");
    console.log("선택된 음식 종류:", selectedCuisine);
}

// [STEP 3] 점심 예산 선택
function selectBudget(budget, btnElement) {
    selectedLunchBudget = budget;
    document.querySelectorAll("#step3 .option-btn").forEach(btn => btn.classList.remove("active"));
    btnElement.classList.add("active");
}

// [STEP 4] 관심사 토글
function toggleInterest(checkboxElement) {
    const value = checkboxElement.value;
    const cardLabel = checkboxElement.closest(".check-card");

    if (checkboxElement.checked) {
        cardLabel.classList.add("checked");
        if (!selectedInterests.includes(value)) {
            selectedInterests.push(value);
        }
    } else {
        cardLabel.classList.remove("checked");
        selectedInterests = selectedInterests.filter(item => item !== value);
    }
}

// [STEP 5] 동행 인원 조절
function adjustCompanion(delta) {
    companionCount += delta;
    if (companionCount < 1) companionCount = 1;
    if (companionCount > 10) companionCount = 10;
    document.getElementById("companionDisplay").innerText = `${companionCount}명`;
}

// [SUBMIT] 여행 일정 생성 요청
async function submitTripForm() {
    const customInput = document.getElementById("customDest");
    const customVal = customInput ? customInput.value.trim() : "";
    let finalDest = customVal || selectedDestination || "추천";
    if (["추천", "알아서 추천", "", "자동추천", "알아서"].includes(finalDest)) {
        finalDest = "추천";
    }

    showStep("Loading");
    document.getElementById("progressContainer").style.display = "none";

    const payload = {
        password: userPassword,
        destination: finalDest,
        cuisineType: selectedCuisine,
        lunchBudgetPerPerson: selectedLunchBudget,
        interests: selectedInterests.length > 0 ? selectedInterests : ["자연/둘레길"],
        companionCount: companionCount
    };

    console.log("서버 전송 Payload:", payload);

    try {
        const response = await fetch("/api/generate-trip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await response.json();

        if (data.success && data.tripId) {
            // 결과 페이지로 이동
            window.location.href = `/trip/${data.tripId}`;
        } else {
            alert(data.message || "일정 생성 중 오류가 발생했습니다.");
            showStep(5);
            document.getElementById("progressContainer").style.display = "block";
        }
    } catch (err) {
        alert("서버 연결에 실패했습니다. 다시 시도해 주세요.");
        showStep(5);
        document.getElementById("progressContainer").style.display = "block";
    }
}

// [월간 DB 동기화 업데이트]
async function updateMonthlyDatabase() {
    let password = userPassword;
    if (!password) {
        password = prompt("월간 지자체 DB 동기화 업데이트를 진행하시겠습니까?\n접속 비밀번호 4자리를 입력해 주세요:");
    }
    if (!password) return;
    
    try {
        const response = await fetch("/api/admin/update-database", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password: password })
        });
        const data = await response.json();
        if (data.success) {
            alert(data.message);
            const dbEl = document.getElementById("dbLastUpdated");
            if (dbEl && data.lastUpdated) {
                dbEl.textContent = data.lastUpdated;
            }
        } else {
            alert("⚠️ " + (data.message || "업데이트 실패"));
        }
    } catch (e) {
        alert("⚠️ 업데이트 통신 중 오류가 발생했습니다.");
    }
}
