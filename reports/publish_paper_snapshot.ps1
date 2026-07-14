$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Git = "C:\Users\16052\AppData\Local\GitHubDesktop\app-3.6.2\resources\app\git\cmd\git.exe"
$Snapshot = "docs/paper-trading/data/snapshot.json"
$Worktree = [IO.Path]::GetFullPath((Join-Path $Root ".paper-pages-publish"))

if (-not (Test-Path -LiteralPath $Git)) { throw "GitHub Desktop Git not found: $Git" }
if (-not $Worktree.StartsWith($Root + [IO.Path]::DirectorySeparatorChar)) { throw "Unsafe worktree path: $Worktree" }
if (Test-Path -LiteralPath $Worktree) { throw "Publish worktree already exists: $Worktree" }

Push-Location $Root
try {
    & $Git add -- $Snapshot
    & $Git diff --cached --quiet -- $Snapshot
    if ($LASTEXITCODE -ne 0) {
        & $Git commit -m "Update paper trading after-close snapshot" -- $Snapshot
    }
    & $Git push origin master
    & $Git fetch origin main
    & $Git worktree add --detach $Worktree origin/main
    try {
        & $Git -C $Worktree checkout master -- $Snapshot
        & $Git -C $Worktree add -- $Snapshot
        & $Git -C $Worktree diff --cached --quiet -- $Snapshot
        if ($LASTEXITCODE -ne 0) {
            & $Git -C $Worktree commit -m "Publish paper trading after-close snapshot" -- $Snapshot
        }
        & $Git -C $Worktree push origin HEAD:main
    }
    finally {
        & $Git worktree remove $Worktree --force
        & $Git worktree prune
    }
}
finally {
    Pop-Location
}
