# Uses the official SDK in Playnite's PowerShell 5.1 runtime. No HTTP or database writes.
function Write-LeisureLogCatalog {
    $ErrorActionPreference = 'Stop'
    $config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'settings.json') -Raw | ConvertFrom-Json
    $target = [IO.Path]::GetFullPath($config.export_path)
    $games = @(
        foreach ($game in $PlayniteApi.Database.Games) {
            $paths = @(
                foreach ($action in $game.GameActions) {
                    if ($action.IsPlayAction -and $action.Type.ToString() -eq 'File' -and $action.Path) {
                        $PlayniteApi.ExpandGameVariables($game, $action.Path)
                    }
                }
            )
            $tags = @(
                foreach ($id in $game.GenreIds) {
                    $genre = $PlayniteApi.Database.Genres[$id]
                    if ($genre) { $genre.Name }
                }
                foreach ($id in $game.TagIds) {
                    $tag = $PlayniteApi.Database.Tags[$id]
                    if ($tag) { $tag.Name }
                }
            )
            [ordered]@{
                id = $game.Id.ToString()
                name = $game.Name
                installed = [bool]$game.IsInstalled
                directory = [string]$game.InstallDirectory
                tags = $tags
                executables = $paths
            }
        }
    )
    $payload = [ordered]@{
        schema_version = 1
        exported_at = [DateTime]::UtcNow.ToString('o')
        games = $games
    } | ConvertTo-Json -Depth 8
    $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    $temporary = $target + '.partial'
    [IO.File]::WriteAllText($temporary, $payload, (New-Object Text.UTF8Encoding($false)))
    # Publish atomically; LeisureLog can only observe the complete previous or next export.
    if ([IO.File]::Exists($target)) { [IO.File]::Replace($temporary, $target, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $target) }
}

function Export-LeisureLogCatalog {
    param($scriptMainMenuItemActionArgs)
    try {
        Write-LeisureLogCatalog
        $PlayniteApi.Dialogs.ShowMessage('游戏资料已保存到本地，LeisureLog 将在下一轮同步时读取。', 'LeisureLog')
    }
    catch { $PlayniteApi.Dialogs.ShowErrorMessage($_.Exception.Message, 'LeisureLog') }
}

function Update-LeisureLogCatalog {
    try { Write-LeisureLogCatalog }
    catch { Write-Warning ('LeisureLog export failed: ' + $_.Exception.Message) }
}

function OnApplicationStarted { param($eventArgs) Update-LeisureLogCatalog }
function OnLibraryUpdated { param($eventArgs) Update-LeisureLogCatalog }
function OnApplicationStopped { param($eventArgs) Update-LeisureLogCatalog }

function GetMainMenuItems {
    param($getMainMenuItemsArgs)
    $item = New-Object Playnite.SDK.Plugins.ScriptMainMenuItem
    $item.Description = '同步游戏资料到 LeisureLog'
    $item.FunctionName = 'Export-LeisureLogCatalog'
    $item.MenuSection = '@LeisureLog'
    return $item
}

# Playnite invokes exported script blocks in its SDK runspace. Helpers must also
# be exported so event and menu handlers can resolve them in that runspace.
Export-ModuleMember -Function Write-LeisureLogCatalog, Update-LeisureLogCatalog, GetMainMenuItems, Export-LeisureLogCatalog, OnApplicationStarted, OnLibraryUpdated, OnApplicationStopped
