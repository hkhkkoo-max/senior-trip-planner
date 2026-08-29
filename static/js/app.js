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

    const heroBanner = document.getElementById("heroBanner");
    const mainHeader = document.getElementById("mainHeader");
    const progressContainer = document.getElementById("progressContainer");

    if (step === 0) {
        if (heroBanner) heroBanner.style.display = "flex";
        if (mainHeader) mainHeader.classList.remove("header-step-mode");
        if (progressContainer) progressContainer.style.display = "none";
    } else {
        if (heroBanner) heroBanner.style.display = "none";
        if (mainHeader) mainHeader.classList.add("header-step-mode");
        if (progressContainer) progressContainer.style.display = "block";
    }

    // 진행 상황 바 업데이트 (총 5단계)
    if (step >= 1 && step <= 5) {
        currentStep = step;
        const progressPercent = (step / 5) * 100;
        document.getElementById("progressBar").style.width = `${progressPercent}%`;
        document.getElementById("progressText").innerText = `${step}단계 / 5단계`;
    }
}

function nextStep(step) {
    if (currentStep === 1 && step === 2) {
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
            // iOS Safari 또는 기타 브라우저 안내
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
