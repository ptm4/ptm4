#Build
$AzCopy = "C:\Users\nnumbat\OneDrive - Supplemental Health Care\Tools\azcopy\azcopy.exe"
$Local  = "C:\Users\nnumbat\OneDrive - Supplemental Health Care\Tools"
$SAS    = "sp=racwdl&st=2025-12-08T18:37:59Z&se=2025-12-11T02:52:59Z&sv=2024-11-04&sr=c&sig=YG06nnNOW0y8yHTrLjEiwABcQAQQOwBGhNvM64Tt6FM%3D"
$Blob   = "https://gawstorage.blob.core.windows.net/testblob?$SAS"

& $AzCopy cp $Local $Blob --recursive --overwrite=ifSourceNewer

