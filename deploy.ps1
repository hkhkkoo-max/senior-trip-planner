# ==============================================================================
# Senior Trip Planner - Secure Direct Deploy Script (deploy.ps1)
# ==============================================================================

param(
    [string]$ServerIP = ""
)

# 1. 서버 IP 확인
if ([string]::IsNullOrWhiteSpace($ServerIP)) {
    $ServerIP = Read-Host "서버 IP 주소를 입력해 주세요 (예: 123.456.78.90)"
}

if ([string]::IsNullOrWhiteSpace($ServerIP)) {
    Write-Host "[취소] 서버 IP가 입력되지 않아 종료합니다." -ForegroundColor Red
    exit
}

$ServerUser = "ubuntu"
$RemotePath = "/home/ubuntu/senior-trip-planner"
$Dest = "${ServerUser}@${ServerIP}:${RemotePath}/"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " [1/2] 수정된 파일 전송 중 (app.py, templates, static)..." -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

# 2. SCP 파일 전송
scp app.py "${Dest}"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] app.py 전송 실패" -ForegroundColor Red
    exit
}

scp -r templates "${Dest}"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] templates 폴더 전송 실패" -ForegroundColor Red
    exit
}

scp -r static "${Dest}"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] static 폴더 전송 실패" -ForegroundColor Red
    exit
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " [2/2] 서버 서비스(senior-trip) 재시작 중..." -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

# 3. SSH 서버 재시작 명령 실행
ssh "${ServerUser}@${ServerIP}" "sudo systemctl restart senior-trip; sudo systemctl is-active senior-trip"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host " [완료] 배포가 성공적으로 완료되었습니다!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
