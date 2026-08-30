// 폼 전역 상태 관리
let currentStep = 1;
let selectedOriginDistrict = "분당구";
let selectedDestination = "추천";
let selectedCuisine = "한식";
let selectedInterests = ["자연/둘레길"];
let companionCount = 2;

// [STEP 1] 성남시 출발 구 선택
function selectOriginDistrict(district, btnElement) {
    selectedOriginDistrict = district;
    document.querySelectorAll("#step1 .option-btn").forEach(btn => btn.classList.remove("active"));
    if (btnElement) btnElement.classList.add("active");
    
    // 2단계의 추천 서브 텍스트 실시간 반영
    const recSubText = document.getElementById("recommendSubText");
    if (recSubText) {
        recSubText.innerText = `${selectedOriginDistrict} 출발 어르신 선호도 1위 명소로 추천`;
    }
    console.log("선택된 출발 구:", selectedOriginDistrict);
}

// 단계 이동 제어
function showStep(step) {
    document.querySelectorAll(".step-section").forEach(sec => sec.classList.remove("active"));
    const targetSection = document.getElementById(`step${step}`);
    if (targetSection) {
        targetSection.classList.add("active");
    }

    const heroBanner = document.getElementById("heroBanner");
    const mainHeader = document.getElementById("mainHeader");
    const progressContainer = document.getElementById("progressContainer");

    // 1단계(첫 화면)에서는 히어로 일러스트 배너 노출, 2단계 이후부터는 콤팩트 모드
    if (step === 1) {
        if (heroBanner) heroBanner.style.display = "flex";
        if (mainHeader) mainHeader.classList.remove("header-step-mode");
    } else {
        if (heroBanner) heroBanner.style.display = "none";
        if (mainHeader) mainHeader.classList.add("header-step-mode");
    }

    if (progressContainer) {
        progressContainer.style.display = (step === "Loading") ? "none" : "block";
    }

    // 진행 상황 바 업데이트 (총 4단계)
    if (typeof step === "number" && step >= 1 && step <= 4) {
        currentStep = step;
        const progressPercent = Math.round((step / 4) * 100);
        const bar = document.getElementById("progressBar");
        const txt = document.getElementById("progressText");
        if (bar) bar.style.width = `${progressPercent}%`;
        if (txt) txt.innerText = `${step}단계 / 4단계`;
    }
    
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function nextStep(step) {
    if (currentStep === 2 && step === 3) {
        const customInput = document.getElementById("customDest");
        const customVal = customInput ? customInput.value.trim() : "";
        const targetDest = customVal || selectedDestination;

        const isRecommend = !targetDest || ["추천", "알아서 추천", "", "자동추천", "알아서"].includes(targetDest);
        selectedDestination = isRecommend ? "추천" : targetDest;
    }
    showStep(step);
}

function prevStep(step) {
    showStep(step);
}

// [STEP 2] 목적지 선택
function selectDestination(dest, btnElement) {
    const customInput = document.getElementById("customDest");
    const val = customInput ? customInput.value.trim() : "";
    if (val) {
        selectedDestination = val;
    } else {
        selectedDestination = "추천";
    }
    document.querySelectorAll("#step2 .option-btn").forEach(btn => btn.classList.remove("active"));
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

// [STEP 3] 음식 종류(한식/양식/일식/중식) 선택
function selectCuisine(cuisine, btnElement) {
    selectedCuisine = cuisine;
    document.querySelectorAll("#step3 .option-btn").forEach(btn => btn.classList.remove("active"));
    btnElement.classList.add("active");
    console.log("선택된 음식 종류:", selectedCuisine);
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
    console.log("선택된 관심사:", selectedInterests);
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
        originDistrict: selectedOriginDistrict,
        destination: finalDest,
        cuisineType: selectedCuisine,
        lunchBudgetPerPerson: 35000,
        interests: selectedInterests.length > 0 ? selectedInterests : ["자연/둘레길"],
        companionCount: 2
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
            showStep(4);
            document.getElementById("progressContainer").style.display = "block";
        }
    } catch (err) {
        alert("서버 연결에 실패했습니다. 다시 시도해 주세요.");
        showStep(4);
        document.getElementById("progressContainer").style.display = "block";
    }
}

// --- PWA 홈 화면 추가 (스마트폰 앱 설치 유도) ---
let deferredPrompt = null;
const pwaBanner = document.getElementById("pwaInstallBanner");
const btnPwaInstall = document.getElementById("btnPwaInstall");

window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (pwaBanner) {
        pwaBanner.style.display = "block";
    }
});

if (btnPwaInstall) {
    btnPwaInstall.addEventListener("click", async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            console.log("[PWA] Install prompt outcome:", outcome);
            deferredPrompt = null;
            if (pwaBanner) {
                pwaBanner.style.display = "none";
            }
        } else {
            alert("📱 스마트폰 브라우저 메뉴(또는 하단 공유 버튼)에서\n'홈 화면에 추가'를 누르시면 진짜 앱으로 설치됩니다!");
        }
    });
}

window.addEventListener("appinstalled", () => {
    console.log("[PWA] App successfully installed");
    if (pwaBanner) {
        pwaBanner.style.display = "none";
    }
});
