param([string]$Dir, [string]$Out)
Add-Type -AssemblyName System.Drawing
$sizes = @(16, 20, 24, 32, 48)
$z = 6; $gap = 12
$w = 0; foreach ($s in $sizes) { $w += $s * $z + $gap }
foreach ($bg in @(@('dark', 40, 44, 52), @('light', 243, 243, 243))) {
  $strip = New-Object System.Drawing.Bitmap([int]$w, [int](48 * $z))
  $g = [System.Drawing.Graphics]::FromImage($strip)
  $g.Clear([System.Drawing.Color]::FromArgb(255, $bg[1], $bg[2], $bg[3]))
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
  $x = 0
  foreach ($s in $sizes) {
    $img = [System.Drawing.Image]::FromFile((Join-Path $Dir "icon-$s.png"))
    $g.DrawImage($img, $x, 0, $s * $z, $s * $z)
    $img.Dispose()
    $x += $s * $z + $gap
  }
  $g.Dispose()
  $strip.Save("$Out-$($bg[0]).png")
  $strip.Dispose()
  Write-Output "wrote $Out-$($bg[0]).png"
}
