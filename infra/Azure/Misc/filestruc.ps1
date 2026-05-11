$source = "\\10.20.3.155\ImpExp"
$dest   = "E:\ImpExp"

Get-ChildItem $source -Directory -Recurse | ForEach-Object {
    $relativePath = $_.FullName.Substring($source.Length)
    $targetPath = Join-Path $dest $relativePath
    New-Item -ItemType Directory -Path $targetPath -Force 
}
