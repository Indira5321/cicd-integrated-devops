$ErrorActionPreference = "Stop"
$baseUrl = if ($env:RELAY_OPS_URL) { $env:RELAY_OPS_URL.TrimEnd("/") } else { "http://localhost:8080" }
$credential = Get-Credential -Message "Sign in to the Relay Ops demo"
$webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession

$loginPage = Invoke-WebRequest -Uri "$baseUrl/login" -WebSession $webSession -UseBasicParsing
$loginTokenMatch = [regex]::Match($loginPage.Content, 'name="csrf_token" value="([^"]+)"')
if (-not $loginTokenMatch.Success) {
    throw "Could not find the login CSRF token. Check that the app is running at $baseUrl."
}

$loginBody = @{
    username   = $credential.UserName
    password   = $credential.GetNetworkCredential().Password
    csrf_token = $loginTokenMatch.Groups[1].Value
}
Invoke-WebRequest -Uri "$baseUrl/login" -Method Post -Body $loginBody -WebSession $webSession -UseBasicParsing | Out-Null

$dashboard = Invoke-WebRequest -Uri $baseUrl -WebSession $webSession -UseBasicParsing
$dashboardTokenMatch = [regex]::Match($dashboard.Content, '<meta name="csrf-token" content="([^"]+)"')
if (-not $dashboardTokenMatch.Success) {
    throw "Sign-in did not reach the dashboard. Check the username and password."
}
$headers = @{ "X-CSRF-Token" = $dashboardTokenMatch.Groups[1].Value }

Write-Host "Health check:"
Invoke-RestMethod -Uri "$baseUrl/api/health" | Format-List

Write-Host "Creating an example task:"
$task = Invoke-RestMethod -Uri "$baseUrl/api/tasks" -Method Post -WebSession $webSession -Headers $headers -ContentType "application/json" -Body (@{ title = "Review the deployment pipeline" } | ConvertTo-Json)
$task | Format-List

Write-Host "Task list:"
Invoke-RestMethod -Uri "$baseUrl/api/tasks" -WebSession $webSession | Format-Table id, title, completed, created_at

Write-Host "Marking task complete:"
Invoke-RestMethod -Uri "$baseUrl/api/tasks/$($task.id)" -Method Patch -WebSession $webSession -Headers $headers -ContentType "application/json" -Body (@{ completed = $true } | ConvertTo-Json) | Format-List

Write-Host "Overview:"
Invoke-RestMethod -Uri "$baseUrl/api/overview" -WebSession $webSession | Format-List

Write-Host "Deleting example task:"
Invoke-RestMethod -Uri "$baseUrl/api/tasks/$($task.id)" -Method Delete -WebSession $webSession -Headers $headers | Format-List

Write-Host "Done. Open $baseUrl and http://localhost:3000 to explore the dashboard and Grafana."
