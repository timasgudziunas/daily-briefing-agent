#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers "AM Briefing" (7:45 AM) and "PM Debrief" (5:00 PM) in Windows
    Task Scheduler to run Mon-Fri with wake-to-run enabled.

.DESCRIPTION
    Trigger times are set in the local machine clock. This script assumes your PC
    timezone is America/New_York (Eastern). If it's not, adjust the -At values
    below to the equivalent local time - the Python code uses America/New_York
    internally and will handle the rest correctly.

    The Python trading-day gate (calendar.py) handles NYSE holidays - Task
    Scheduler provides the Mon-Fri cadence, Python exits early on holidays.

    Run once from an elevated PowerShell prompt (right-click, "Run as
    administrator"). Safe to re-run; tasks are overwritten with -Force.

.NOTES
    For wake-to-run to work, "Allow wake timers" must be enabled in your active
    power plan. See the instructions printed after this script completes.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error (
        "Python virtualenv not found at '$Python'.`n" +
        "Set it up first:`n" +
        "  python -m venv .venv`n" +
        "  .venv\Scripts\pip install -r requirements.txt"
    )
    exit 1
}

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# Interactive: runs in the user's active session (including when screen is locked).
# Highest: needed so the task survives UAC and wake-to-run requests are honoured.
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Highest

# StartWhenAvailable: if the machine was off at the scheduled time and turns on
# within a reasonable window, the task still fires (useful for brief shutdowns).
# MultipleInstances IgnoreNew: a second trigger while one is still running is dropped.
$Settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

function Register-BriefingTask {
    param(
        [string]$Name,
        [string]$Script,
        [string]$At
    )
    $Action = New-ScheduledTaskAction `
        -Execute $Python `
        -Argument $Script `
        -WorkingDirectory $ProjectDir
    $Trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At $At
    Register-ScheduledTask `
        -TaskName $Name `
        -TaskPath "\DailyBriefing\" `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "daily-briefing-agent - $Name. Trading-day gate is inside the Python script." `
        -Force | Out-Null
    Write-Host "  registered  $Name  at $At  Mon-Fri"
}

Write-Host ""
Write-Host "Registering tasks as: $CurrentUser"
Write-Host "Project:              $ProjectDir"
Write-Host "Python:               $Python"
Write-Host ""

Register-BriefingTask -Name "AM Briefing" -Script "am_briefing.py" -At "07:45"
Register-BriefingTask -Name "PM Debrief"  -Script "pm_debrief.py"  -At "17:00"

Write-Host ""
Write-Host "Done. To verify:"
Write-Host "  Get-ScheduledTask -TaskPath '\DailyBriefing\'"
Write-Host ""
Write-Host "To trigger a manual test run (sends the real email):"
Write-Host "  Start-ScheduledTask -TaskName 'AM Briefing' -TaskPath '\DailyBriefing\'"
Write-Host "  Start-ScheduledTask -TaskName 'PM Debrief'  -TaskPath '\DailyBriefing\'"
Write-Host ""
Write-Host "Run logs are written to: $ProjectDir\data\logs\am.log / pm.log"
Write-Host ""
Write-Host "--- ACTION REQUIRED: enable wake timers ---"
Write-Host "For the machine to wake from sleep at the scheduled time:"
Write-Host "  Control Panel > Power Options > Change plan settings"
Write-Host "  > Change advanced power settings > Sleep > Allow wake timers > Enable"
Write-Host ""
Write-Host "If Control Panel isn't available, run in an elevated PowerShell:"
Write-Host "  powercfg /change standby-timeout-ac 0   # optional: don't sleep on AC"
Write-Host "  # or check current plan's wake timer setting:"
Write-Host "  powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE"
