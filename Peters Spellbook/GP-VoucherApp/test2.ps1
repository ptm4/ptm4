# Load Windows Forms assemblies
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Set up log file (same folder as script/exe)
$scriptPath = [System.IO.Path]::GetDirectoryName([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
$logFile = Join-Path $scriptPath "GPscript_Audit.log"

function Write-Log {
    param([string]$Message)

    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $entry = "$timestamp [$env:USERNAME] $Message"

    # Write to file
    Add-Content -Path $logFile -Value $entry

    # Write to live log window
    $logTextBox.AppendText("$entry`r`n")
    $logTextBox.SelectionStart = $logTextBox.Text.Length
    $logTextBox.ScrollToCaret()
}

# Main form
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Voucher Query'
$form.Size = New-Object System.Drawing.Size(600,500)
$form.StartPosition = 'CenterScreen'

$form.Icon = New-Object System.Drawing.Icon(".\gpapp.ico")

# Voucher label
$labelVoucher = New-Object System.Windows.Forms.Label
$labelVoucher.Text = 'Paste vouchers:'
$labelVoucher.AutoSize = $true
$labelVoucher.Location = New-Object System.Drawing.Point(10,20)
$form.Controls.Add($labelVoucher)

# Multiline textbox for vouchers
$voucherTextBox = New-Object System.Windows.Forms.TextBox
$voucherTextBox.Multiline = $true
$voucherTextBox.ScrollBars = 'Vertical'
$voucherTextBox.Location = New-Object System.Drawing.Point(150,18)
$voucherTextBox.Size = New-Object System.Drawing.Size(250,120)
$form.Controls.Add($voucherTextBox)

# Username label
$labelUser = New-Object System.Windows.Forms.Label
$labelUser.Text = 'SQL Username:'
$labelUser.AutoSize = $true
$labelUser.Location = New-Object System.Drawing.Point(10,160)
$form.Controls.Add($labelUser)

# Username textbox (pre-filled with Windows user)
$textBoxUser = New-Object System.Windows.Forms.TextBox
$textBoxUser.Location = New-Object System.Drawing.Point(150,158)
$textBoxUser.Size = New-Object System.Drawing.Size(250,25)
$textBoxUser.Text = ""  # Prefill current Windows user
$form.Controls.Add($textBoxUser)

# Password label
$labelPass = New-Object System.Windows.Forms.Label
$labelPass.Text = 'SQL Password:'
$labelPass.AutoSize = $true
$labelPass.Location = New-Object System.Drawing.Point(10,200)
$form.Controls.Add($labelPass)

# Password textbox (masked, default *****)
$textBoxPass = New-Object System.Windows.Forms.TextBox
$textBoxPass.Location = New-Object System.Drawing.Point(150,198)
$textBoxPass.Size = New-Object System.Drawing.Size(250,25)
$textBoxPass.UseSystemPasswordChar = $true
$textBoxPass.Text = ""   # Show stars by default
$form.Controls.Add($textBoxPass)

# Checkbox for integrated security
$checkIntegrated = New-Object System.Windows.Forms.CheckBox
$checkIntegrated.Text = 'Use Windows Authentication'
$checkIntegrated.AutoSize = $true
$checkIntegrated.Location = New-Object System.Drawing.Point(150,230)
#$checkIntegrated.Checked = $true  # Default to Windows Auth
$form.Controls.Add($checkIntegrated)

# Toggle username/password enabled state
$checkIntegrated.Add_CheckedChanged({
    if ($checkIntegrated.Checked) {
        # Disable but keep placeholders visible
        $textBoxUser.Enabled = $false
        $textBoxPass.Enabled = $false
        if (-not $textBoxUser.Text) { $textBoxUser.Text = "jlb\$env:USERNAME" }
        if (-not $textBoxPass.Text) { $textBoxPass.Text = "************" }
    } else {
        $textBoxUser.Enabled = $true
        $textBoxPass.Enabled = $true
        if ($textBoxPass.Text) { $textBoxPass.Clear() }
        if ($textBoxUser.Text) { $textBoxUser.Clear() }
    }
})

# Run button
$buttonRun = New-Object System.Windows.Forms.Button
$buttonRun.Text = 'Run Query'
$buttonRun.Location = New-Object System.Drawing.Point(420,50)
$buttonRun.Size = New-Object System.Drawing.Size(120,40)
$form.Controls.Add($buttonRun)

# Make Enter key trigger the Run button
$form.AcceptButton = $buttonRun

# Exit button (not visible, just for Escape key binding)
$buttonExit = New-Object System.Windows.Forms.Button
$buttonExit.Size = New-Object System.Drawing.Size(0,0)   # hidden
$buttonExit.Location = New-Object System.Drawing.Point(-100,-100) # off-screen
$buttonExit.TabStop = $false
$buttonExit.Add_Click({
    $form.Close()
})
$form.Controls.Add($buttonExit)

# Map Escape key to exit
$form.CancelButton = $buttonExit

# Log window (multiline textbox)
$logTextBox = New-Object System.Windows.Forms.TextBox
$logTextBox.Multiline = $true
$logTextBox.ScrollBars = 'Vertical'
$logTextBox.ReadOnly = $true
$logTextBox.Location = New-Object System.Drawing.Point(10,280)
$logTextBox.Size = New-Object System.Drawing.Size(560,180)
$form.Controls.Add($logTextBox)

# Run query for vouchers in textbox
$buttonRun.Add_Click({
    $vouchers = $voucherTextBox.Lines | Where-Object { $_.Trim() -ne "" }
    if ($vouchers.Count -eq 0) {
        Write-Log "No vouchers entered. Nothing to process."
        return
    }

    $user = $textBoxUser.Text
    $pass = if ($textBoxPass.Text -eq "*****") { "" } else { $textBoxPass.Text }
    $server = "SQL-TARDIS-03-BRIDGE"
    $database = "SHCTest"

    if ($checkIntegrated.Checked) {
        $connectionString = "Data Source=$server;Initial Catalog=$database;Integrated Security=True;Trusted_Connection=yes"
        Write-Log "Starting update for $($vouchers.Count) vouchers using Windows Authentication (User=$env:USERNAME)."
    } else {
        $connectionString = "Data Source=$server;Initial Catalog=$database;User ID=$user;Password=$pass;Trusted_Connection=yes"
        Write-Log "Starting update for $($vouchers.Count) vouchers using SQL Auth (User=$user)."
    }

    try {
        $connection = New-Object System.Data.SqlClient.SqlConnection($connectionString)
        $connection.Open()
        Write-Log "SQL connection opened successfully."

        foreach ($voucherNumber in $vouchers) {
            $voucherNumber = $voucherNumber.Trim()
            if (-not $voucherNumber) { continue }

            try {
                $query = "UPDATE PM20000 SET HOLD = 0 WHERE VCHRNMBR = @voucherNumber"
                $command = $connection.CreateCommand()
                $command.CommandText = $query
                $command.Parameters.Add("@voucherNumber",[System.Data.SqlDbType]::VarChar,20).Value = $voucherNumber

                $rowsAffected = $command.ExecuteNonQuery()
                Write-Log "Voucher [$voucherNumber]: Rows affected = $rowsAffected."
            } catch {
                Write-Log "ERROR updating voucher [$voucherNumber]: $($_.Exception.Message)"
            }
        }

        $connection.Close()
        Write-Log "SQL connection closed."
        Write-Log "Processing complete."
    }
    catch {
        Write-Log "ERROR: $($_.Exception.Message)"
    }
})

# Prevent any extra cancel/close messages
$form.Add_FormClosing({
    param($sender, $e)
    $e.Cancel = $false
})

# Show form (non-modal)
$form.Topmost = $true
$form.Show()
[System.Windows.Forms.Application]::Run($form)
