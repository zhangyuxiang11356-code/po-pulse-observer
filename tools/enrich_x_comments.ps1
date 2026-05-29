param(
  [string]$CommentMaxItems = "all",
  [int]$CommentsPerItem = 3,
  [string]$TargetDate = "",
  [switch]$SkipTemplateCheck
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
$xScript = Join-Path $PSScriptRoot "x_host_bridge.py"
$templateCheckScript = Join-Path $PSScriptRoot "check_html_template.py"
$xCachePath = Join-Path $root "output\social\x_items.json"

function Invoke-External {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList = @(),
    [string]$StepName
  )

  $output = & $FilePath @ArgumentList 2>&1
  $exitCode = $LASTEXITCODE
  foreach ($line in @($output)) {
    Write-Output ([string]$line)
  }
  if ($exitCode -ne 0) {
    throw "$StepName failed with exit code: $exitCode"
  }
}

function Get-XCommentSummary {
  if (!(Test-Path $xCachePath)) {
    throw "X cache is missing: $xCachePath"
  }

  $payload = Get-Content $xCachePath -Raw -Encoding utf8 | ConvertFrom-Json
  $items = @($payload.items)
  $cardsWithComments = @(
    $items | Where-Object {
      $_.platform -eq "x" -and $_.representative_comments -and @($_.representative_comments).Count -gt 0
    }
  )
  $commentCount = 0
  foreach ($item in $cardsWithComments) {
    $commentCount += @($item.representative_comments).Count
  }

  [pscustomobject]@{
    total_x_items = @($items | Where-Object { $_.platform -eq "x" }).Count
    x_cards_with_comments = $cardsWithComments.Count
    representative_comments = $commentCount
    cache_path = $xCachePath
  }
}

if ($CommentMaxItems -notin @("all", "全部", "*")) {
  try {
    if ([int]$CommentMaxItems -lt 0) {
      throw "CommentMaxItems must be >= 0"
    }
  }
  catch {
    throw "CommentMaxItems must be an integer >= 0 or 'all'"
  }
}
if ($CommentsPerItem -lt 1) {
  throw "CommentsPerItem must be >= 1"
}
if (!(Test-Path $xScript)) {
  throw "X bridge script is missing: $xScript"
}

Push-Location $root
try {
  Write-Output "X comment enrichment"
  Write-Output "CommentMaxItems: $CommentMaxItems"
  Write-Output "CommentsPerItem: $CommentsPerItem"
  if ($TargetDate.Trim()) {
    Write-Output "TargetDate: $($TargetDate.Trim())"
  }

  if ($CommentMaxItems -ne "0") {
    Write-Output "Step 1/3: Enrich X cache with representative comments"
    $commentArgs = @(
      $xScript,
      "comments",
      "--comment-max-items", [string]$CommentMaxItems,
      "--comments-per-item", [string]$CommentsPerItem
    )
    if ($TargetDate.Trim()) {
      $commentArgs += @("--target-date", $TargetDate.Trim())
    }
    Invoke-External -FilePath $python -ArgumentList $commentArgs -StepName "X representative comment enrichment"
  }
  else {
    Write-Output "Step 1/3: Skipped enrichment because CommentMaxItems is 0"
  }

  Write-Output "Step 2/3: Count X cards with comments"
  $summary = Get-XCommentSummary
  $summary | ConvertTo-Json -Compress

  if ($SkipTemplateCheck) {
    Write-Output "Step 3/3: Skipped template check"
  }
  else {
    if (!(Test-Path $templateCheckScript)) {
      throw "Template check script is missing: $templateCheckScript"
    }
    Write-Output "Step 3/3: Run HTML template check"
    Invoke-External -FilePath $python -ArgumentList @($templateCheckScript) -StepName "HTML template check"
  }

  Write-Output "Done: X representative comments are ready for HTML rendering"
}
finally {
  Pop-Location
}
