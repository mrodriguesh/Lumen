# Gera launcher\lumen.ico (desenho próprio: quadrado arredondado com gradiente e uma “lente” clara).
Add-Type -AssemblyName System.Drawing
$sizes = 16, 24, 32, 48, 64, 128, 256
$pngs = foreach ($s in $sizes) {
    $bmp = New-Object Drawing.Bitmap $s, $s
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'; $g.PixelOffsetMode = 'HighQuality'
    $m = $s * 0.04; $w = $s - 2 * $m; $r = $w * 0.45   # cantos bem arredondados
    $path = New-Object Drawing.Drawing2D.GraphicsPath
    $path.AddArc($m, $m, $r, $r, 180, 90); $path.AddArc($m + $w - $r, $m, $r, $r, 270, 90)
    $path.AddArc($m + $w - $r, $m + $w - $r, $r, $r, 0, 90); $path.AddArc($m, $m + $w - $r, $r, $r, 90, 90)
    $path.CloseFigure()
    $grad = New-Object Drawing.Drawing2D.LinearGradientBrush ([Drawing.PointF]::new(0, 0)), ([Drawing.PointF]::new($s, $s)),
        ([Drawing.Color]::FromArgb(255, 94, 92, 230)), ([Drawing.Color]::FromArgb(255, 10, 132, 255))
    $g.FillPath($grad, $path)
    # brilho suave no topo
    $hl = New-Object Drawing.Drawing2D.LinearGradientBrush ([Drawing.PointF]::new(0, 0)), ([Drawing.PointF]::new(0, $s * 0.6)),
        ([Drawing.Color]::FromArgb(70, 255, 255, 255)), ([Drawing.Color]::FromArgb(0, 255, 255, 255))
    $g.SetClip([Drawing.RectangleF]::new(0, 0, $s, $s * 0.6)); $g.FillPath($hl, $path); $g.ResetClip()
    # lente: anel branco + núcleo âmbar
    $c = $s / 2; $ro = $s * 0.27; $pen = New-Object Drawing.Pen ([Drawing.Color]::White), ([Math]::Max(1.2, $s * 0.075))
    $g.DrawEllipse($pen, $c - $ro, $c - $ro, 2 * $ro, 2 * $ro)
    $ri = $s * 0.12
    $g.FillEllipse((New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(255, 255, 214, 10))), $c - $ri, $c - $ri, 2 * $ri, 2 * $ri)
    $ms = New-Object IO.MemoryStream; $bmp.Save($ms, [Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
    , $ms.ToArray()
}
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
