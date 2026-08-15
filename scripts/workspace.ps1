param(
    [ValidateSet("check", "up", "verify", "test", "scan", "down")]
    [string]$Action = "verify"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendTests = (Resolve-Path (Join-Path $WorkspaceRoot "backend/tests")).Path

function Assert-NativeSuccess {
    param([string]$Operation)

    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

function Invoke-WorkspaceCheck {
    docker compose config --quiet
    Assert-NativeSuccess "Docker Compose validation"

    docker buildx build --check --progress=plain "$WorkspaceRoot/backend"
    Assert-NativeSuccess "Backend Dockerfile check"

    docker buildx build --check --progress=plain "$WorkspaceRoot/frontend"
    Assert-NativeSuccess "Frontend Dockerfile check"
}

function Test-WorkspaceHealth {
    $ExpectedServices = @("backend", "frontend", "minio", "redis", "worker")
    $RunningServices = @(docker compose ps --services --status running)
    Assert-NativeSuccess "Docker Compose status check"

    $MissingServices = @($ExpectedServices | Where-Object { $_ -notin $RunningServices })
    if ($MissingServices.Count -gt 0) {
        throw "Workspace services are not running: $($MissingServices -join ', ')."
    }

    $BackendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 10
    if ($BackendHealth.status -ne "ok") {
        throw "Backend health endpoint did not report ok."
    }

    $FrontendResponse = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -TimeoutSec 10
    if ($FrontendResponse.StatusCode -ne 200) {
        throw "Frontend returned HTTP $($FrontendResponse.StatusCode)."
    }

    $MinioResponse = Invoke-WebRequest -Uri "http://127.0.0.1:9001" -TimeoutSec 10
    if ($MinioResponse.StatusCode -ne 200) {
        throw "MinIO console returned HTTP $($MinioResponse.StatusCode)."
    }

    Write-Output "Workspace is healthy: frontend, backend, worker, Redis, and MinIO are ready."
}

Push-Location $WorkspaceRoot
try {
    switch ($Action) {
        "check" {
            Invoke-WorkspaceCheck
        }
        "up" {
            Invoke-WorkspaceCheck
            docker compose up --detach --build
            Assert-NativeSuccess "Docker Compose startup"
            Test-WorkspaceHealth
        }
        "verify" {
            Test-WorkspaceHealth
        }
        "test" {
            docker compose build backend frontend
            Assert-NativeSuccess "Application image build"
            docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=256m --mount "type=bind,src=$BackendTests,dst=/app/tests,readonly" videolens-backend python -m unittest discover -s tests
            Assert-NativeSuccess "Backend container test suite"
        }
        "scan" {
            docker scout cves videolens-backend --only-severity critical,high --only-fixed
            Assert-NativeSuccess "Backend image scan"
            docker scout cves videolens-frontend --only-severity critical,high --only-fixed
            Assert-NativeSuccess "Frontend image scan"
        }
        "down" {
            docker compose down
            Assert-NativeSuccess "Docker Compose shutdown"
        }
    }
}
finally {
    Pop-Location
}
