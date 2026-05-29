$ErrorActionPreference = "Stop"

$ComposeFile = Join-Path $PSScriptRoot "docker-compose.yml"
$EnvFile = Join-Path $PSScriptRoot ".env"
$ProjectName = "trendradar"
$BuildContext = Split-Path $PSScriptRoot -Parent
$Dockerfile = Join-Path $PSScriptRoot "Dockerfile"
$ImageName = "trendradar-local:latest"
$FallbackPodmanDir = Join-Path $env:LOCALAPPDATA "Programs\\Podman"
$FallbackPythonScripts = Join-Path $env:LOCALAPPDATA "Programs\\Python\\Python311\\Scripts"

foreach ($dir in @($FallbackPodmanDir, $FallbackPythonScripts)) {
    if ((Test-Path $dir) -and (-not (($env:PATH -split ';') -contains $dir))) {
        $env:PATH = "$dir;$env:PATH"
    }
}

function Invoke-PodmanCompose {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    podman compose -p $ProjectName --env-file $EnvFile -f $ComposeFile @Args
}

function Build-TrendRadarImage {
    podman build -f $Dockerfile -t $ImageName $BuildContext
}

function Show-Help {
@"
TrendRadar Podman helper

Usage:
  .\podman.ps1 up
  .\podman.ps1 down
  .\podman.ps1 logs
  .\podman.ps1 status
  .\podman.ps1 exec 'python manage.py status'
  .\podman.ps1 mcp-up

Commands:
  up       Start trendradar
  down     Stop all services
  logs     Tail trendradar logs
  status   Show running containers
  exec     Run a command inside trendradar
  mcp-up   Start trendradar-mcp only
"@
}

if (-not (Get-Command podman -ErrorAction SilentlyContinue)) {
    Write-Error "podman command is not available. Please confirm Podman is installed and on PATH, then reopen PowerShell."
}

$Action = if ($args.Count -gt 0) { $args[0] } else { "help" }

switch ($Action) {
    "up" {
        Build-TrendRadarImage
        Invoke-PodmanCompose up -d trendradar
    }
    "down" {
        Invoke-PodmanCompose down
    }
    "logs" {
        podman logs -f trendradar
    }
    "status" {
        podman ps --filter "name=trendradar"
    }
    "exec" {
        if ($args.Count -lt 2) {
            Write-Error "Provide a container command, for example: .\\podman.ps1 exec 'python manage.py status'"
        }
        $InnerCommand = ($args[1..($args.Count - 1)] -join " ")
        podman exec -it trendradar sh -lc $InnerCommand
    }
    "mcp-up" {
        Invoke-PodmanCompose up -d trendradar-mcp
    }
    default {
        Show-Help
    }
}
