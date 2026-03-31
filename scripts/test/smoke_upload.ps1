param(
  [Parameter(Mandatory = $true)]
  [string]$FilePath
)

Write-Host "Upload smoke test start"

if (-Not (Test-Path $FilePath)) {
  throw "File not found: $FilePath"
}

$form = @{
  file = Get-Item $FilePath
}

$result = Invoke-RestMethod -Uri "http://127.0.0.1:8000/upload/floorplan" -Method Post -Form $form
Write-Host "Upload result =>" ($result | ConvertTo-Json -Compress)

if ($result.status -ne "ok") {
  throw "upload failed"
}

Write-Host "Upload smoke test done"
