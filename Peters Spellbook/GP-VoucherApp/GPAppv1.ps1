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

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Voucher Query'
$form.Size = New-Object System.Drawing.Size(600,500)
$form.StartPosition = 'CenterScreen'

$form.Icon = New-Object System.Drawing.Icon(".\gpapp.ico")

# Single voucher label
$labelVoucher = New-Object System.Windows.Forms.Label
$labelVoucher.Text = 'Enter Voucher:'
$labelVoucher.AutoSize = $true
$labelVoucher.Location = New-Object System.Drawing.Point(10,20)
$form.Controls.Add($labelVoucher)

# Single voucher textbox
$textBoxVoucher = New-Object System.Windows.Forms.TextBox
$textBoxVoucher.Location = New-Object System.Drawing.Point(150,18)
$textBoxVoucher.Size = New-Object System.Drawing.Size(250,25)
$form.Controls.Add($textBoxVoucher)

# "Add Voucher" button
$buttonAdd = New-Object System.Windows.Forms.Button
$buttonAdd.Text = 'Add'
$buttonAdd.Location = New-Object System.Drawing.Point(420,18)
$buttonAdd.Size = New-Object System.Drawing.Size(80,25)
$form.Controls.Add($buttonAdd)

# Voucher listbox (read-only)
$listBoxVouchers = New-Object System.Windows.Forms.ListBox
$listBoxVouchers.Location = New-Object System.Drawing.Point(150,50)
$listBoxVouchers.Size = New-Object System.Drawing.Size(250,80)
$form.Controls.Add($listBoxVouchers)

# "Remove Voucher" button
$buttonRemove = New-Object System.Windows.Forms.Button
$buttonRemove.Text = 'Remove'
$buttonRemove.Location = New-Object System.Drawing.Point(420,50)
$buttonRemove.Size = New-Object System.Drawing.Size(80,25)
$form.Controls.Add($buttonRemove)

# Username label
$labelUser = New-Object System.Windows.Forms.Label
$labelUser.Text = 'SQL Username:'
$labelUser.AutoSize = $true
$labelUser.Location = New-Object System.Drawing.Point(10,150)
$form.Controls.Add($labelUser)

# Username textbox
$textBoxUser = New-Object System.Windows.Forms.TextBox
$textBoxUser.Location = New-Object System.Drawing.Point(150,148)
$textBoxUser.Size = New-Object System.Drawing.Size(250,25)
$form.Controls.Add($textBoxUser)

# Password label
$labelPass = New-Object System.Windows.Forms.Label
$labelPass.Text = 'SQL Password:'
$labelPass.AutoSize = $true
$labelPass.Location = New-Object System.Drawing.Point(10,190)
$form.Controls.Add($labelPass)

# Password textbox (masked)
$textBoxPass = New-Object System.Windows.Forms.TextBox
$textBoxPass.Location = New-Object System.Drawing.Point(150,188)
$textBoxPass.Size = New-Object System.Drawing.Size(250,25)
$textBoxPass.UseSystemPasswordChar = $true
$form.Controls.Add($textBoxPass)

# Checkbox for integrated security
$checkIntegrated = New-Object System.Windows.Forms.CheckBox
$checkIntegrated.Text = 'Use Windows Authentication'
$checkIntegrated.AutoSize = $true
$checkIntegrated.Location = New-Object System.Drawing.Point(150,220)
$form.Controls.Add($checkIntegrated)

# Toggle username/password enabled state
$checkIntegrated.Add_CheckedChanged({
    if ($checkIntegrated.Checked) {
        $textBoxUser.Enabled = $false
        $textBoxPass.Enabled = $false
    } else {
        $textBoxUser.Enabled = $true
        $textBoxPass.Enabled = $true
    }
})

# "Add Voucher" button click
$buttonAdd.Add_Click({
    $voucher = $textBoxVoucher.Text.Trim()
    if ($voucher -ne "") {
        $listBoxVouchers.Items.Add($voucher)
        Write-Log "Voucher [$voucher] added to list."
        $textBoxVoucher.Clear()
    }
})

# "Remove Voucher" button click
$buttonRemove.Add_Click({
    $selected = $listBoxVouchers.SelectedItem
    if ($selected) {
        $listBoxVouchers.Items.Remove($selected)
        Write-Log "Voucher [$selected] removed from list."
    }
})

# Run button
$buttonRun = New-Object System.Windows.Forms.Button
$buttonRun.Text = 'Run Query'
$buttonRun.Location = New-Object System.Drawing.Point(420,90)
$buttonRun.Size = New-Object System.Drawing.Size(120,40)
$form.Controls.Add($buttonRun)

# Log window (multiline textbox)
$logTextBox = New-Object System.Windows.Forms.TextBox
$logTextBox.Multiline = $true
$logTextBox.ScrollBars = 'Vertical'
$logTextBox.ReadOnly = $true
$logTextBox.Location = New-Object System.Drawing.Point(10,280)
$logTextBox.Size = New-Object System.Drawing.Size(560,180)
$form.Controls.Add($logTextBox)

# Run query for vouchers in list
$buttonRun.Add_Click({
    if ($listBoxVouchers.Items.Count -eq 0) {
        Write-Log "No vouchers in list. Nothing to process."
        return
    }

    $voucherNumbers = $listBoxVouchers.Items
    $user = $textBoxUser.Text
    $pass = $textBoxPass.Text
    $server = "SQL-TARDIS-03-BRIDGE"
    $database = "SHCTest"

    if ($checkIntegrated.Checked) {
        $connectionString = "Data Source=$server;Initial Catalog=$database;Integrated Security=True;Trusted_Connection=yes"
        Write-Log "Starting update for $($voucherNumbers.Count) vouchers using Windows Authentication."
    } else {
        $connectionString = "Data Source=$server;Initial Catalog=$database;User ID=$user;Password=$pass;Trusted_Connection=yes"
        Write-Log "Starting update for $($voucherNumbers.Count) vouchers using SQL Auth (User=$user)."
    }

    try {
        $connection = New-Object System.Data.SqlClient.SqlConnection($connectionString)
        $connection.Open()
        Write-Log "SQL connection opened successfully."

        foreach ($voucherNumber in $voucherNumbers) {
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
    # Allow the form to close without prompting
    $e.Cancel = $false
})


# Show form (non-modal)
$form.Topmost = $true
$form.Show()
[System.Windows.Forms.Application]::Run($form)