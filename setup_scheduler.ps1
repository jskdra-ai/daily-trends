# Windows 작업 스케줄러 등록 스크립트
# 매일 오전 7시에 daily_trends.py 자동 실행

$taskName = "DailyTrendsUpdate"
$pythonPath = (Get-Command python).Source
$scriptPath = "C:\Users\skybi\daily-trends\daily_trends.py"
$workingDir = "C:\Users\skybi\daily-trends"

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument $scriptPath `
    -WorkingDirectory $workingDir

$trigger = New-ScheduledTaskTrigger -Daily -At "07:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "매일 오전 7시 세계 트렌드 Top10 자동 수집 및 웹페이지 생성" `
    -Force

Write-Host "작업 스케줄러 등록 완료: 매일 오전 7시 자동 실행됩니다." -ForegroundColor Green
