Write-Host "Running Alembic migrations..."
alembic upgrade head
Write-Host "Migration complete."
