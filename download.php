<?php
// ROM CS2 download handler - serves the installer file
$file = 'ROM-CS2-Setup.exe'; 
if (file_exists($file)) {
    header('Content-Type: application/x-msdownload');
    header('Content-Disposition: attachment; filename="' . $file . '"');
    header('Content-Length: ' . filesize($file));
    readfile($file);
    exit;
}
http_response_code(404);
?>
