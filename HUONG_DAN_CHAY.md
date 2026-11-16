# Hướng dẫn cài đặt và chạy FaceCheck trên máy Windows khác

Tài liệu này mô tả đầy đủ cách chuyển hệ thống FaceCheck từ máy hiện tại sang một máy Windows khác mà vẫn giữ được:

- hồ sơ và ảnh khuôn mặt;
- thông tin quản lý vân tay;
- lịch sử xác thực;
- model AI;
- cấu hình camera, MQTT, cửa và TFT;
- khả năng khởi động bằng icon Desktop không hiện CMD.

> Chỉ `git clone` hoặc `git pull` là chưa đủ. GitHub không chứa model, dữ liệu sinh trắc học, `.env`, mật khẩu, token hoặc môi trường Python của máy hiện tại.

## 1. Những gì GitHub có và không có

### Được lấy về từ GitHub

- source code Python;
- giao diện Web UI;
- test;
- firmware ESP32;
- file cấu hình PlatformIO;
- các file `secrets.example.h` mẫu;
- tài liệu Markdown đã được commit và push.

### Không được lấy về từ GitHub

Các đường dẫn sau bị `.gitignore` loại trừ:

```text
.env
venv/
models/
data/
firmware/**/secrets.h
```

Icon `.lnk` trên Desktop cũng nằm ngoài repository nên phải tạo lại trên máy mới.

## 2. Điều kiện để hai máy chạy gần giống nhau

Máy mới cần đáp ứng đồng thời:

1. dùng cùng phiên bản source code;
2. dùng Python 3.11;
3. cài cùng phiên bản thư viện Python;
4. có cùng model AI;
5. có bản sao dữ liệu khuôn mặt và registry vân tay;
6. có `.env` đúng;
7. truy cập được camera và MQTT broker;
8. được Windows Firewall cho phép các cổng cần thiết;
9. dùng đúng địa chỉ IP và cổng COM của máy mới.

Không nên sao chép nguyên thư mục `venv` giữa hai máy. Hãy tạo lại môi trường Python trên máy mới.

## 3. Chuẩn bị bản sao lưu trên máy cũ

Ví dụ dưới đây giả sử:

- dự án hiện tại ở `D:\HK7\DACN\DA`;
- USB hoặc ổ sao lưu là `E:\FaceCheck-Backup`.

Thay đổi hai đường dẫn cho phù hợp với máy của bạn.

Mở PowerShell:

```powershell
$projectRoot = "D:\HK7\DACN\DA"
$backupRoot = "E:\FaceCheck-Backup"

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
New-Item -ItemType Directory -Force -Path "$backupRoot\models" | Out-Null
New-Item -ItemType Directory -Force -Path "$backupRoot\data" | Out-Null
New-Item -ItemType Directory -Force -Path "$backupRoot\firmware\Smart_Door" | Out-Null
New-Item -ItemType Directory -Force -Path "$backupRoot\firmware\esp32_s3_ov3660" | Out-Null
New-Item -ItemType Directory -Force -Path "$backupRoot\firmware\esp32_035_display\include" | Out-Null
```

### 3.1 Sao lưu cấu hình server

```powershell
Copy-Item -LiteralPath "$projectRoot\.env" -Destination "$backupRoot\.env"
```

### 3.2 Sao lưu model AI

```powershell
Copy-Item -Path "$projectRoot\models\*" -Destination "$backupRoot\models" -Recurse -Force
```

Tối thiểu phải có:

```text
models/model.pt
models/blaze_face_short_range.tflite
```

### 3.3 Sao lưu dữ liệu hệ thống

Thoát hẳn FaceCheck trên máy cũ trước khi sao chép để database SQLite ở trạng thái nhất quán.

```powershell
Copy-Item -Path "$projectRoot\data\*" -Destination "$backupRoot\data" -Recurse -Force
```

Các dữ liệu quan trọng nhất:

```text
data/facecheck.db
data/faces/
```

Ý nghĩa:

| Đường dẫn | Nội dung |
|---|---|
| `facecheck.db` | SQLite chứa hồ sơ, vector ArcFace, registry vân tay, lịch sử xác thực và sự kiện cửa |
| `faces/` | Ảnh đại diện khuôn mặt |

Các tệp JSON/Pickle cũ có thể có trong thư mục sao lưu, nhưng server phiên bản hiện tại không dùng chúng làm nguồn dữ liệu vận hành.

### 3.4 Sao lưu secrets firmware

Chỉ thực hiện với file đang tồn tại:

```powershell
if (Test-Path "$projectRoot\firmware\Smart_Door\secrets.h") {
    Copy-Item "$projectRoot\firmware\Smart_Door\secrets.h" `
        "$backupRoot\firmware\Smart_Door\secrets.h"
}

if (Test-Path "$projectRoot\firmware\esp32_s3_ov3660\secrets.h") {
    Copy-Item "$projectRoot\firmware\esp32_s3_ov3660\secrets.h" `
        "$backupRoot\firmware\esp32_s3_ov3660\secrets.h"
}

if (Test-Path "$projectRoot\firmware\esp32_035_display\include\secrets.h") {
    Copy-Item "$projectRoot\firmware\esp32_035_display\include\secrets.h" `
        "$backupRoot\firmware\esp32_035_display\include\secrets.h"
}
```

Nếu chỉ chuyển server và tiếp tục dùng các ESP32 đã nạp firmware thì không bắt buộc sao chép `secrets.h`. Tuy nhiên vẫn nên lưu để có thể build lại firmware sau này.

### 3.5 Khóa phiên bản thư viện Python

`requirements.txt` sử dụng điều kiện `>=`, vì vậy cài ở thời điểm khác có thể nhận phiên bản thư viện mới hơn. Hãy tạo bản khóa từ máy đang chạy ổn định:

```powershell
& "$projectRoot\venv\Scripts\python.exe" -m pip freeze `
    | Set-Content -LiteralPath "$backupRoot\requirements-lock.txt" -Encoding UTF8
```

### 3.6 Kiểm tra bản sao lưu

```powershell
Get-ChildItem -LiteralPath $backupRoot -Recurse | Select-Object FullName, Length
```

Không đưa thư mục sao lưu này lên repository công khai vì nó có mật khẩu, token và dữ liệu sinh trắc học.

## 4. Đảm bảo source mới nhất đã lên GitHub

Trên máy cũ:

```powershell
cd D:\HK7\DACN\DA
git status
```

Nếu README hoặc source vẫn đang ở trạng thái modified/untracked, cần commit và push:

```powershell
git add README.md HUONG_DAN_CHAY.md
git commit -m "Cap nhat tai lieu cai dat va chuyen may"
git push origin main
```

Không dùng `git add -A` nếu chưa kiểm tra kỹ toàn bộ thay đổi. Không ép thêm `.env`, `data/`, `models/` hoặc `secrets.h` vào Git.

## 5. Chuẩn bị máy Windows mới

Cài đặt:

- Git for Windows;
- Python 3.11 64-bit;
- Microsoft Edge WebView2 Runtime hoặc trình duyệt hiện đại;
- VS Code và PlatformIO nếu cần build firmware;
- driver USB-UART/USB-Serial phù hợp với ESP32.

Kiểm tra:

```powershell
git --version
py -0p
py -3.11 --version
```

Kết quả Python cần là `3.11.x`.

## 6. Clone source từ GitHub

Ví dụ cài dự án vào `D:\FaceCheck`:

```powershell
cd D:\
git clone https://github.com/locnguyen77176-prog/SmartDoor.git FaceCheck
cd D:\FaceCheck
git status
```

Nếu máy mới đã có repository:

```powershell
cd D:\FaceCheck
git switch main
git pull origin main
```

Không pull khi đang có thay đổi chưa commit mà chưa kiểm tra, vì có thể tạo xung đột.

## 7. Khôi phục dữ liệu riêng tư

Ví dụ ổ sao lưu vẫn là `E:\FaceCheck-Backup`:

```powershell
$newRoot = "D:\FaceCheck"
$backupRoot = "E:\FaceCheck-Backup"
```

### 7.1 Khôi phục `.env`, model và dữ liệu

```powershell
Copy-Item -LiteralPath "$backupRoot\.env" -Destination "$newRoot\.env"
New-Item -ItemType Directory -Force -Path "$newRoot\models" | Out-Null
New-Item -ItemType Directory -Force -Path "$newRoot\data" | Out-Null
Copy-Item -Path "$backupRoot\models\*" -Destination "$newRoot\models" -Recurse -Force
Copy-Item -Path "$backupRoot\data\*" -Destination "$newRoot\data" -Recurse -Force
```

### 7.2 Khôi phục secrets firmware

```powershell
if (Test-Path "$backupRoot\firmware\Smart_Door\secrets.h") {
    Copy-Item "$backupRoot\firmware\Smart_Door\secrets.h" `
        "$newRoot\firmware\Smart_Door\secrets.h"
}

if (Test-Path "$backupRoot\firmware\esp32_s3_ov3660\secrets.h") {
    Copy-Item "$backupRoot\firmware\esp32_s3_ov3660\secrets.h" `
        "$newRoot\firmware\esp32_s3_ov3660\secrets.h"
}

if (Test-Path "$backupRoot\firmware\esp32_035_display\include\secrets.h") {
    New-Item -ItemType Directory -Force `
        -Path "$newRoot\firmware\esp32_035_display\include" | Out-Null
    Copy-Item "$backupRoot\firmware\esp32_035_display\include\secrets.h" `
        "$newRoot\firmware\esp32_035_display\include\secrets.h"
}
```

## 8. Tạo môi trường Python trên máy mới

```powershell
cd D:\FaceCheck
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

Nếu PowerShell chặn Activate.ps1, chỉ mở quyền trong phiên hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

### Cài đúng phiên bản của máy cũ

Ưu tiên file lock trong bản sao lưu:

```powershell
pip install -r E:\FaceCheck-Backup\requirements-lock.txt
```

Nếu không có file lock:

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Kiểm tra các import quan trọng:

```powershell
.\venv\Scripts\python.exe -c "import cv2, numpy, starlette, uvicorn, paho.mqtt.client; print('Python dependencies: OK')"
```

## 9. Kiểm tra và chỉnh `.env`

Không cần thay đổi `.env` nếu:

- camera và laptop vẫn ở cùng mô hình mạng;
- MQTT broker vẫn giữ nguyên;
- `MQTT_DOOR_DEVICE_ID` vẫn là thiết bị cũ;
- không dùng IP cố định của máy cũ cho TFT.

Cần kiểm tra các biến:

```dotenv
FACECHECK_CAMERA_HOST=facecheck-cam.local
FACECHECK_CAMERA_PROFILE=embedded_ov3660
FACECHECK_CAMERA_FLIP=1

MQTT_HOST=your-broker-host
MQTT_PORT=8883
MQTT_USERNAME=your-username
MQTT_PASSWORD=your-password
MQTT_DOOR_DEVICE_ID=door-01

FACECHECK_DOOR_ENABLED=1
FACECHECK_DOOR_OPEN_DURATION_MS=3000
FACECHECK_DOOR_COOLDOWN_SECONDS=8
FACECHECK_DOOR_FACE_EXIT_SECONDS=1.5
FACECHECK_DOOR_ACK_TIMEOUT_SECONDS=12
```

Nếu dùng TFT, cập nhật IPv4 của laptop mới:

```powershell
Get-NetIPAddress -AddressFamily IPv4 `
    | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } `
    | Select-Object InterfaceAlias, IPAddress
```

Sau đó đặt:

```dotenv
FACECHECK_DISPLAY_HOST=<IP-laptop-moi>
FACECHECK_DISPLAY_TOKEN=<token-giong-firmware-TFT>
```

Nếu IP laptop thay đổi, firmware TFT cũng phải trỏ đến IP mới hoặc router phải cấp DHCP reservation cố định.

## 10. Kiểm tra model và dữ liệu trước khi chạy

```powershell
$requiredPaths = @(
    "D:\FaceCheck\models\model.pt",
    "D:\FaceCheck\models\blaze_face_short_range.tflite",
    "D:\FaceCheck\data\facecheck.db",
    "D:\FaceCheck\data\faces",
    "D:\FaceCheck\.env"
)

$requiredPaths | ForEach-Object {
    [PSCustomObject]@{ Path = $_; Exists = Test-Path -LiteralPath $_ }
} | Format-Table -AutoSize
```

Tất cả mục quan trọng phải có `Exists = True`.

## 11. Kiểm tra kết nối camera

### Camera ESP32-S3 qua Wi-Fi

Tìm IP camera từ Serial Monitor hoặc router, sau đó mở:

```text
http://<camera-ip>/health
http://<camera-ip>/capture
http://<camera-ip>:81/stream
```

Nếu mDNS hoạt động:

```powershell
Invoke-RestMethod http://facecheck-cam.local/health
```

Nếu mDNS không hoạt động, chạy server với IP cụ thể:

```powershell
.\venv\Scripts\python.exe facecheck.py wifi --camera-host 192.168.1.105
```

### Webcam

```powershell
.\venv\Scripts\python.exe facecheck.py webcam --camera-index 0
```

Nếu không thấy hình, thử index `1` hoặc `2`.

## 12. Chạy lần đầu bằng PowerShell

Lần đầu nên chạy bằng PowerShell để nhìn thấy toàn bộ log:

```powershell
cd D:\FaceCheck
.\venv\Scripts\python.exe facecheck.py wifi
```

Chờ các dấu hiệu:

```text
[WIFI-CAMERA] Đã kết nối ...
[AI] Load models hoàn tất.
[CAMERA] first frame
[DOOR] Đã kết nối ...
[AI] DeepFace ArcFace đã sẵn sàng ...
```

Kiểm tra backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

Mở giao diện:

```text
http://127.0.0.1:8765/?view=admin#dashboard
```

Nếu lần chạy PowerShell thành công, đóng server rồi mới tạo và thử icon Desktop.

## 13. Tạo icon FaceCheck Server trên Desktop

`desktop_launcher.py` sẽ:

- không hiển thị CMD;
- hiện cửa sổ tiến trình khởi động;
- ghi log vào `data/facecheck_desktop.log`;
- tự mở trang quản trị;
- nếu server đang chạy thì mở lại giao diện ngay.

Tạo shortcut bằng PowerShell:

```powershell
$newRoot = "D:\FaceCheck"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "FaceCheck Server.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$newRoot\venv\Scripts\pythonw.exe"
$shortcut.Arguments = "`"$newRoot\desktop_launcher.py`""
$shortcut.WorkingDirectory = $newRoot
$shortcut.IconLocation = "$newRoot\venv\Scripts\python.exe,0"
$shortcut.Description = "Mo FaceCheck Server"
$shortcut.WindowStyle = 7
$shortcut.Save()

Get-Item -LiteralPath $shortcutPath
```

Nhấp đúp **FaceCheck Server** để kiểm tra.

## 14. Windows Firewall

Admin UI chỉ dùng `127.0.0.1:8765`, thông thường không cần mở firewall.

Nếu dùng TFT trong LAN, mở PowerShell bằng quyền Administrator và cho phép TCP `8767` trên mạng Private:

```powershell
New-NetFirewallRule `
    -DisplayName "FaceCheck TFT 8767" `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8767 `
    -Profile Private
```

Không mở cổng `8765` ra Internet.

## 15. Có cần nạp lại ESP32 không?

### Không cần nạp lại nếu

- vẫn dùng các board ESP32 cũ;
- Wi-Fi, MQTT broker và token không đổi;
- camera vẫn kết nối được mạng;
- TFT vẫn trỏ đúng IP laptop.

Mẫu vân tay nằm trong AS608 và ánh xạ tên offline nằm trong NVS của ESP32-S3 cửa, nên chuyển laptop không xóa các dữ liệu này.

### Cần nạp lại nếu

- đổi tên/mật khẩu Wi-Fi;
- đổi MQTT broker hoặc chứng chỉ;
- thay Telegram Bot Token;
- thay IP server mà TFT dùng;
- thay board ESP32 mới;
- NVS hoặc flash của ESP32 đã bị xóa.

## 16. Lệnh build và nạp firmware

Cổng COM có thể khác máy cũ. Kiểm tra Device Manager rồi sửa `upload_port` và `monitor_port` trong `platformio.ini` nếu cần.

Camera Wi-Fi:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" `
    run -d firmware\esp32_s3_ov3660 -t upload
```

Camera USB-OTG:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" `
    run -d firmware\esp32_s3_ov3660_usb -t upload
```

Bộ điều khiển cửa:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" `
    run -d firmware\Smart_Door -t upload
```

Màn hình TFT:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" `
    run -d firmware\esp32_035_display -t upload
```

## 17. Đồng bộ tên vân tay trên máy mới

Sau khi khôi phục `data/facecheck.db`:

1. bật ESP32-S3 cửa;
2. bật server trên máy mới;
3. chờ cả hai kết nối cùng MQTT broker;
4. server tự gửi lại toàn bộ ánh xạ `ID → họ tên` vào NVS ESP32;
5. kiểm tra log server có thông báo đồng bộ tên vân tay;
6. thử quét một vân tay đã đăng ký và kiểm tra Telegram.

Nếu không khôi phục bảng `fingerprints` trong database, AS608 vẫn nhận được mẫu cũ nhưng server không biết tên tương ứng. Không nên đăng ký đè lên ID cũ trước khi kiểm tra registry.

## 18. Chạy kiểm thử trên máy mới

Đóng server trước khi chạy test:

```powershell
cd D:\FaceCheck
$env:FACECHECK_WEB_SKIP_AI = "1"
.\venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:FACECHECK_WEB_SKIP_AI -ErrorAction SilentlyContinue
```

Build thử firmware cửa mà không nạp:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" `
    run -d firmware\Smart_Door
```

## 19. Checklist nghiệm thu

### Server và AI

- [ ] `/api/health` trả `ok: true`.
- [ ] Camera có frame mới liên tục.
- [ ] YOLO và MediaPipe tải thành công.
- [ ] ArcFace warm-up thành công.
- [ ] Danh sách nhân viên và ảnh hiển thị đầy đủ.
- [ ] Lịch sử cũ được khôi phục.

### Cửa và MQTT

- [ ] Server báo MQTT đã kết nối.
- [ ] ESP32-S3 cửa xuất hiện trạng thái online.
- [ ] Nhận diện khuôn mặt đúng mở cửa đúng một lần.
- [ ] Người lạ không mở cửa.
- [ ] ACK `started/finished` được nhận.
- [ ] Không có thông báo Telegram bị lặp.

### Vân tay

- [ ] Registry vân tay hiển thị đúng tên.
- [ ] Log cho thấy tên đã đồng bộ vào NVS.
- [ ] Vân tay đúng mở cửa khi server đang chạy.
- [ ] Vân tay đúng vẫn mở cửa khi server tắt.
- [ ] Telegram vẫn hiển thị tên khi server tắt.
- [ ] Vân tay lạ bị từ chối và có cảnh báo.

### TFT và Desktop

- [ ] TFT tải được `/frame.jpg` qua cổng `8767`.
- [ ] Token TFT khớp với `.env`.
- [ ] Icon Desktop mở server mà không hiện CMD.
- [ ] `data/facecheck_desktop.log` không có lỗi khởi động.

## 20. Lỗi thường gặp

### `ModuleNotFoundError`

Đang dùng sai Python hoặc chưa cài dependency:

```powershell
Get-Command python
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Không tìm thấy `models/model.pt`

Thư mục `models/` không có trên GitHub. Khôi phục từ bản sao lưu.

### Giao diện có nhân viên nhưng không nhận diện được

Kiểm tra đồng thời `data/facecheck.db` và `data/faces/`. Hai phần phải được sao lưu cùng nhau.

### Camera Wi-Fi không tìm thấy

- kiểm tra cùng mạng 2.4 GHz;
- kiểm tra `/health` bằng IP;
- chạy với `--camera-host <ip>`;
- kiểm tra client isolation trên router.

### MQTT không kết nối

- kiểm tra `MQTT_HOST`, port, username và password;
- kiểm tra ngày giờ Windows;
- kiểm tra Internet và TLS;
- đảm bảo server và ESP32 dùng cùng `MQTT_DOOR_DEVICE_ID`.

### Icon Desktop không hiện gì

- kiểm tra `data/facecheck_desktop.log`;
- chạy `facecheck.py wifi` bằng PowerShell để thấy lỗi;
- kiểm tra shortcut có trỏ đúng thư mục máy mới;
- kiểm tra `venv\Scripts\pythonw.exe` tồn tại.

### TFT báo `Forbidden`

`FACECHECK_DISPLAY_TOKEN` trong `.env` phải giống hệt token trong firmware TFT.

## 21. Bảo mật dữ liệu chuyển máy

- Không gửi `.env`, `secrets.h` hoặc dữ liệu khuôn mặt qua kênh công khai.
- Nên mã hóa ổ USB hoặc file backup.
- Không commit `data/`, `models/`, `.env`, `secrets.h` dù Git cho phép ép thêm.
- Sau khi chuyển xong, xóa bản sao tạm không còn cần thiết.
- Nếu token từng bị công khai, thay MQTT password, Telegram Bot Token và token TFT.
- Giới hạn quyền truy cập thư mục `data/` vì có dữ liệu sinh trắc học.

## 22. Quy trình rút gọn

```text
Máy cũ
  ├─ Commit + push source
  ├─ Sao lưu .env
  ├─ Sao lưu models/
  ├─ Sao lưu data/
  ├─ Sao lưu secrets.h
  └─ Tạo requirements-lock.txt

Máy mới
  ├─ Cài Git + Python 3.11
  ├─ Clone repository
  ├─ Khôi phục file riêng tư
  ├─ Tạo venv và cài dependency
  ├─ Chạy lần đầu bằng PowerShell
  ├─ Kiểm tra camera + AI + MQTT
  ├─ Tạo icon Desktop
  └─ Chạy checklist nghiệm thu
```

Hoàn thành toàn bộ checklist trên thì máy mới có thể vận hành tương đương máy hiện tại, ngoại trừ khác biệt phần cứng, driver, địa chỉ IP và cổng COM.
