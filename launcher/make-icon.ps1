# Gera os icones do Windows a partir da mesma imagem usada na interface.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$source = [Drawing.Image]::FromFile((Join-Path $PSScriptRoot '..\lumen\web\lumen.png'))
$sizes = 16, 24, 32, 48, 64, 128, 256
try {
    $pngs = foreach ($s in $sizes) {
        $bmp = New-Object Drawing.Bitmap $s, $s
        $g = [Drawing.Graphics]::FromImage($bmp)
        $ms = New-Object IO.MemoryStream
        try {
            $g.Clear([Drawing.Color]::Transparent)
            $g.CompositingQuality = 'HighQuality'
            $g.InterpolationMode = 'HighQualityBicubic'
            $g.PixelOffsetMode = 'HighQuality'
            $g.DrawImage($source, [Drawing.Rectangle]::new(0, 0, $s, $s))
            $bmp.Save($ms, [Drawing.Imaging.ImageFormat]::Png)
            , $ms.ToArray()
        } finally { $ms.Dispose(); $g.Dispose(); $bmp.Dispose() }
    }
} finally { $source.Dispose() }
# Contêiner ICO com entradas PNG (aceito desde o Windows Vista)
$out = New-Object IO.MemoryStream; $bw = New-Object IO.BinaryWriter $out
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $b = if ($s -ge 256) { 0 } else { $s }
    $bw.Write([byte]$b); $bw.Write([byte]$b); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32); $bw.Write([uint32]$pngs[$i].Length); $bw.Write([uint32]$offset)
    $offset += $pngs[$i].Length
}
foreach ($p in $pngs) { $bw.Write($p) }
[IO.File]::WriteAllBytes((Join-Path $PSScriptRoot 'lumen.ico'), $out.ToArray())
[IO.File]::WriteAllBytes((Join-Path $PSScriptRoot 'lumen-256.png'), $pngs[-1])
[IO.File]::WriteAllBytes((Join-Path $PSScriptRoot '..\lumen\web\favicon.ico'), $out.ToArray())
$bw.Dispose(); $out.Dispose()
