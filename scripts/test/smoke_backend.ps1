Write-Host "Backend smoke test start"

$health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get
$db = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/db" -Method Get

Write-Host "/health =>" ($health | ConvertTo-Json -Compress)
Write-Host "/health/db =>" ($db | ConvertTo-Json -Compress)

if ($health.status -ne "ok") {
  throw "health check failed"
}

Write-Host "Backend smoke test done"
