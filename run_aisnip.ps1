Set-Location -LiteralPath $PSScriptRoot
Start-Process -FilePath "pythonw" -ArgumentList "aisnip.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
