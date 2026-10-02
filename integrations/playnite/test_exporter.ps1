param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference = 'Stop'
$null = [IO.Directory]::CreateDirectory($Directory)
$modulePath = Join-Path $Directory 'LeisureLog.psm1'
$target = Join-Path $Directory 'games.json'
$text = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'LeisureLog.psm1'))
[IO.File]::WriteAllText($modulePath, $text, (New-Object Text.UTF8Encoding($true)))
@{export_path=$target} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Directory 'settings.json') -Encoding UTF8
$dialogs = New-Object PSObject
$dialogs | Add-Member ScriptMethod ShowMessage { param($text,$title) }
$dialogs | Add-Member ScriptMethod ShowErrorMessage { param($text,$title) throw $text }
$game = [pscustomobject]@{
    Id=[guid]::NewGuid(); Name='原神'; IsInstalled=$true; InstallDirectory='D:\Game'
    GenreIds=@([guid]::Empty); TagIds=@()
    GameActions=@([pscustomobject]@{IsPlayAction=$true; Type='File'; Path='{InstallDir}\YuanShen.exe'})
}
$api = [pscustomobject]@{
    Database=[pscustomobject]@{Games=@($game); Genres=@{([guid]::Empty)=[pscustomobject]@{Name='RPG'}}; Tags=@{}}
    Dialogs=$dialogs
}
$api | Add-Member ScriptMethod ExpandGameVariables { param($game,$path) $path.Replace('{InstallDir}', $game.InstallDirectory) }
$module = Import-Module -Name $modulePath -PassThru -Force
foreach ($helper in @('Write-LeisureLogCatalog','Update-LeisureLogCatalog')) {
    if (-not $module.ExportedFunctions.ContainsKey($helper)) { throw "SDK runspace helper missing: $helper" }
}
& $module { param($api) $script:PlayniteApi=$api } $api
Export-LeisureLogCatalog
$result = Get-Content -LiteralPath $target -Raw -Encoding UTF8 | ConvertFrom-Json
if ($result.games.Count -ne 1 -or $result.games[0].name -ne '原神' -or
    $result.games[0].executables[0] -ne 'D:\Game\YuanShen.exe' -or
    $result.games[0].tags[0] -ne 'RPG') { throw 'Export content mismatch' }
$api.Database.Games=@()
Export-LeisureLogCatalog
$result = Get-Content -LiteralPath $target -Raw -Encoding UTF8 | ConvertFrom-Json
if ($result.games.Count -ne 0) { throw 'Empty catalog mismatch' }
if (Test-Path -LiteralPath ($target+'.partial')) { throw 'Incomplete output left behind' }
Write-Output 'SDK mock export, Unicode, paths, tags, empty array and atomic replacement passed.'
