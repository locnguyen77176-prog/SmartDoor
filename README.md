# FaceCheck — Hệ thống kiểm soát ra vào bằng khuôn mặt và vân tay

FaceCheck là hệ thống kiểm soát cửa chạy cục bộ trên máy tính Windows, kết hợp:

- nhận diện khuôn mặt bằng camera ESP32-S3 OV3660 hoặc webcam;
- xác thực vân tay bằng cảm biến AS608;
- điều khiển khóa điện qua ESP32-S3;
- giao diện quản trị và màn hình kiosk;
- thông báo Telegram;
- giao tiếp an toàn giữa server và bộ điều khiển cửa qua MQTT/TLS.

Máy tính là **server xử lý AI và quản lý dữ liệu**. ESP32-S3 cửa là **thiết bị điều khiển phần cứng**, vẫn cho phép vân tay và nút nhấn hoạt động khi server hoặc mạng bị mất.

## 1. Hệ thống làm được gì?

### Nhận diện khuôn mặt

- Nhận hình ảnh từ webcam, camera ESP32-S3 qua Wi-Fi hoặc USB-OTG.
- Phát hiện khuôn mặt bằng YOLOv8-Face.
- Kiểm tra vị trí, kích thước, góc đầu, độ sáng và chất lượng khuôn mặt.
- Sinh embedding ArcFace và so khớp với hồ sơ đã đăng ký.
- Tổng hợp kết quả từ nhiều frame để giảm nhận nhầm do ảnh mờ hoặc nhiễu JPEG.
- Ghi lịch sử thành công, thất bại, người lạ và trường hợp chưa chắc chắn.
- Khi nhận diện đúng, gửi lệnh mở cửa ngắn hạn đến ESP32-S3 qua MQTT/TLS.
- Gửi kết quả nhận diện đúng/sai lên Telegram; kết quả đúng có kèm họ tên.

### Vân tay

- Đăng ký và xóa mẫu vân tay AS608 từ giao diện quản trị.
- Mở cửa trực tiếp tại ESP32-S3, không phụ thuộc server khi xác thực vân tay.
- Gửi sự kiện vân tay thành công/thất bại về server để ghi lịch sử chung.
- Hiển thị tên người dùng trong thông báo Telegram nếu ID đã được đồng bộ vào NVS.
- Đồng bộ tên từ `data/fingerprints.json` vào NVS mỗi khi MQTT kết nối lại.

### Quản trị

- Dashboard trạng thái camera, AI, cửa và MQTT.
- Đăng ký, chỉnh sửa, bật/tắt hoặc xóa hồ sơ nhân viên.
- Quản lý nhân viên chỉ có khuôn mặt, chỉ có vân tay hoặc có cả hai.
- Xem, lọc và phân trang lịch sử xác thực.
- Xem camera trực tiếp và kiểm thử nhận diện bằng ảnh tĩnh.
- Cung cấp màn hình kiosk 480×320 cho ESP32-035 TFT.

## 2. Kiến trúc tổng thể

```text
                         ┌───────────────────────────────┐
 Camera ESP32 / Webcam ─▶│ FaceCheck Server trên laptop │
                         │ YOLO + MediaPipe + ArcFace    │
                         │ Hồ sơ + lịch sử + Web API     │
                         └──────────┬───────────┬────────┘
                                    │           │
                         HTTP/WS    │           │ MQTT/TLS
                                    ▼           ▼
                         Admin UI / Kiosk   MQTT Broker
                                    │           │
                                    ▼           ▼
                            ESP32-035 TFT   ESP32-S3 cửa
                                            ├─ AS608
                                            ├─ OLED
                                            ├─ Relay khóa
                                            ├─ Nút mở cửa
                                            └─ Telegram Bot
```

Luồng khuôn mặt và luồng vân tay độc lập ở phần xác thực, nhưng cùng cập nhật trạng thái và lịch sử trên server.

### Luồng mở cửa bằng khuôn mặt

1. Camera gửi frame về server.
2. Server phát hiện và kiểm tra chất lượng khuôn mặt.
3. ArcFace so khớp với hồ sơ nhân viên.
4. Nếu đạt chính sách xác nhận nhiều frame, server ghi lịch sử thành công.
5. Server gửi lệnh `OPEN` có `command_id`, thời gian hết hạn và thời lượng mở.
6. ESP32 xác thực lệnh, đưa yêu cầu vào FreeRTOS queue rồi mới điều khiển relay.
7. ESP32 trả ACK `started`, `finished` hoặc `failed`.
8. Server áp dụng cooldown và yêu cầu khuôn mặt rời camera trước lượt tiếp theo.

### Luồng mở cửa bằng vân tay

1. AS608 trả về ID của mẫu vân tay khớp.
2. ESP32 mở relay trực tiếp, kể cả khi server đang tắt.
3. ESP32 đọc tên tương ứng từ NVS để tạo thông báo Telegram.
4. Nếu MQTT đang hoạt động, ESP32 gửi sự kiện về server để ghi vào lịch sử chung.

## 3. Dữ liệu vân tay được lưu ở đâu?

| Thành phần | Dữ liệu lưu | Vai trò |
|---|---|---|
| AS608 | Mẫu sinh trắc học và ID khe `1..127` | So khớp vân tay |
| `data/fingerprints.json` | ID vân tay, mã nhân viên, họ tên, chức vụ, phòng ban | Registry quản lý trên server |
| NVS của ESP32-S3 cửa | Ánh xạ `ID vân tay → họ tên` | Hiển thị tên Telegram khi server tắt |

AS608 **không lưu họ tên**. Nó chỉ biết mẫu vân tay thuộc ID nào.

Tên được đồng bộ vào NVS trong các trường hợp:

- đăng ký vân tay thành công;
- cập nhật thông tin người dùng trên server;
- xóa vân tay thành công;
- server và ESP32 kết nối lại MQTT — server gửi lại toàn bộ tên hiện có.

Nếu server tắt sau khi đã đồng bộ, ESP32 vẫn thông báo được tên. Nếu NVS bị xóa hoặc ESP32 vừa thay mới, cần bật server và kết nối MQTT ít nhất một lần để đồng bộ lại.

## 4. Thành phần phần mềm

| Tệp/thư mục | Trách nhiệm chính |
|---|---|
| `facecheck.py` | Launcher, chọn nguồn camera, nạp `.env`, chống chạy trùng |
| `desktop_launcher.py` | Launcher Desktop không hiện CMD, có màn hình chờ và log lỗi |
| `web_admin.py` | Khởi động Uvicorn, giao diện trình duyệt/PyWebView và kênh TFT |
| `web_runtime.py` | State dùng chung, CRUD nhân viên, đăng ký, lịch sử và điều phối worker |
| `web_backend/app.py` | REST API, WebSocket và MJPEG stream |
| `door_service.py` | MQTT/TLS, ACK, cooldown, sự kiện cửa và quản lý vân tay |
| `ai_engine.py` | Detect, landmark, alignment, embedding và cosine distance |
| `camera_capture.py` | Đọc webcam/MJPEG theo chiến lược latest-frame |
| `ekyc_renderer.py` | Vẽ khung hướng dẫn và HUD đăng ký khuôn mặt |
| `mixins/attendance.py` | Pipeline nhận diện và chính sách quyết định |
| `mixins/enrollment.py` | Tạo và lưu hồ sơ khuôn mặt |
| `mixins/camera.py` | Kiểm tra camera và chất lượng đăng ký |
| `mixins/core.py` | Tải model, cache embedding, warm-up và lưu lịch sử |
| `web_ui/` | HTML, CSS và JavaScript của Admin UI/Kiosk |
| `firmware/` | Firmware camera, cửa và màn hình TFT |
| `tools/` | Công cụ MQTT, serial, benchmark và calibration |
| `tests/` | Kiểm thử unit và integration |

Camera và model chỉ được khởi tạo một lần trong vòng đời backend. Chuyển trang trên giao diện không tải lại model hoặc mở lại camera.

## 5. Cấu trúc firmware

```text
firmware/
├── esp32_s3_ov3660/       Camera OV3660 truyền MJPEG qua Wi-Fi
├── esp32_s3_ov3660_usb/   Camera OV3660 truyền JPEG qua USB-OTG
├── Smart_Door/            AS608, OLED, relay, MQTT và Telegram
└── esp32_035_display/      Màn hình kiosk TFT 3.5 inch
```

### Bộ điều khiển cửa `Smart_Door`

Firmware được tách thành các driver:

- `Fingerprint_Driver`: giao tiếp AS608 và quản lý mẫu vân tay;
- `Lock_Driver`: điều khiển relay và trạng thái khóa;
- `Display_Driver`: hiển thị OLED;
- `MQTT_Driver`: lệnh mở cửa, quản lý vân tay, ACK và event;
- `Telegram_Driver`: bot, thông báo và tên vân tay trong NVS;
- `Smart_Door.ino`: tạo queue, event group và các FreeRTOS task.

MQTT callback không mở relay trực tiếp. Lệnh phải được kiểm tra thời hạn và đưa vào queue; chỉ task điều khiển khóa được phép tác động relay.

### Telegram Bot

Các lệnh hiện còn hỗ trợ:

- `/open`: mở khóa từ xa;
- `/adduser <Chat_ID>`: admin ủy quyền người dùng;
- `/removeuser <Chat_ID>`: admin hủy ủy quyền;
- `/listuser`: admin xem danh sách người dùng;
- `/help`: xem trợ giúp.

Các lệnh quản lý mẫu vân tay trên Telegram đã được loại bỏ. Việc đăng ký, cập nhật và xóa vân tay được thực hiện từ giao diện quản trị.

Thông báo Telegram gồm:

- nhận diện khuôn mặt thành công/thất bại;
- mở cửa bằng vân tay, có tên nếu NVS đã đồng bộ;
- vân tay lạ bị từ chối;
- mở cửa từ nút nhấn bên trong.

## 6. Yêu cầu

### Phần mềm

- Windows 10 hoặc Windows 11;
- Python 3.11;
- Git;
- VS Code + PlatformIO nếu cần build/nạp firmware;
- Microsoft Edge WebView2 hoặc trình duyệt mặc định hiện đại.

### Phần cứng

- laptop hoặc PC chạy server;
- ESP32-S3 WROOM CAM + OV3660 hoặc webcam;
- ESP32-S3 N16R8 điều khiển cửa;
- cảm biến vân tay AS608;
- relay và khóa điện;
- OLED, nút nhấn mở cửa;
- ESP32-035 TFT nếu dùng màn hình kiosk ngoài.

## 7. Cài đặt server

Nếu cài trên máy Windows khác và cần giữ nguyên model, hồ sơ, vân tay và cấu hình, xem [Hướng dẫn chạy trên máy khác](HUONG_DAN_CHAY_TREN_MAY_KHAC.md).

Mở PowerShell tại thư mục dự án:

```powershell
cd D:\HK7\DACN\DA
```

Tạo và kích hoạt môi trường Python nếu chưa có:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Model YOLO phải tồn tại tại:

```text
models/model.pt
```

## 8. Cấu hình `.env`

Tạo file `.env` tại thư mục gốc. Ví dụ tối thiểu:

```dotenv
# Camera
FACECHECK_CAMERA_HOST=facecheck-cam.local
FACECHECK_CAMERA_PROFILE=embedded_ov3660
FACECHECK_CAMERA_FLIP=1

# MQTT/TLS của bộ điều khiển cửa
MQTT_HOST=your-broker-host
MQTT_PORT=8883
MQTT_USERNAME=your-username
MQTT_PASSWORD=your-password
MQTT_DOOR_DEVICE_ID=door-01

# Chính sách mở cửa
FACECHECK_DOOR_ENABLED=1
FACECHECK_DOOR_OPEN_DURATION_MS=3000
FACECHECK_DOOR_COOLDOWN_SECONDS=8
FACECHECK_DOOR_FACE_EXIT_SECONDS=1.5
FACECHECK_DOOR_ACK_TIMEOUT_SECONDS=12

# TFT, chỉ cần nếu sử dụng màn hình ngoài
FACECHECK_DISPLAY_HOST=192.168.1.10
FACECHECK_DISPLAY_TOKEN=replace-with-a-long-random-token
```

Không commit `.env`, `secrets.h`, token Telegram hoặc thông tin MQTT lên Git.

## 9. Khởi động hệ thống

### Cách nhanh nhất: icon Desktop

Nhấp đúp **FaceCheck Server** trên Desktop.

Launcher sẽ:

1. hiển thị cửa sổ trạng thái khởi động;
2. tìm ESP32-S3 CAM trong mạng;
3. tải AI và mở backend;
4. mở giao diện quản trị trong trình duyệt;
5. chạy nền mà không hiện CMD.

Nếu server đã chạy, nhấp icon lần nữa sẽ mở lại giao diện quản trị.

Log của launcher Desktop:

```text
data/facecheck_desktop.log
```

### Chạy bằng PowerShell

Camera ESP32-S3 qua Wi-Fi:

```powershell
.\venv\Scripts\python.exe facecheck.py wifi
```

Chỉ định IP camera:

```powershell
.\venv\Scripts\python.exe facecheck.py wifi --camera-host 192.168.1.105
```

Webcam máy tính:

```powershell
.\venv\Scripts\python.exe facecheck.py webcam --camera-index 0
```

Camera ESP32-S3 qua USB-OTG:

```powershell
.\venv\Scripts\python.exe facecheck.py usb
```

Mô phỏng đồng thời màn hình kiosk và Admin UI:

```powershell
.\venv\Scripts\python.exe facecheck.py wifi --simulate-display
```

Chỉ chạy một phiên FaceCheck tại một thời điểm. Muốn đổi nguồn camera, hãy dừng phiên đang chạy trước.

## 10. Địa chỉ và cổng mạng

| Địa chỉ | Chức năng |
|---|---|
| `127.0.0.1:8765` | Admin UI, Kiosk UI, REST API, WebSocket, camera stream |
| `127.0.0.1:8766` | Camera bridge khi dùng USB-OTG |
| `0.0.0.0:8767` | Kênh ảnh/trạng thái chỉ đọc dành cho TFT |
| `<camera-ip>:80` | `/health` và `/capture` của camera Wi-Fi |
| `<camera-ip>:81` | MJPEG stream của camera Wi-Fi |

Giao diện quản trị:

```text
http://127.0.0.1:8765/?view=admin#dashboard
```

## 11. API chính

| Phương thức | Endpoint | Chức năng |
|---|---|---|
| `GET` | `/api/health` | Kiểm tra backend |
| `GET` | `/api/state` | Snapshot trạng thái hệ thống |
| `WS` | `/ws/state` | Cập nhật trạng thái thời gian thực |
| `GET` | `/api/camera/stream` | MJPEG cho giao diện |
| `POST` | `/api/mode` | Chuyển chế độ runtime |
| `POST` | `/api/recognition/retry` | Mở lượt nhận diện mới |
| `POST` | `/api/recognition/test-image` | Kiểm thử một ảnh tĩnh |
| `POST` | `/api/enrollment/start` | Bắt đầu quét đăng ký |
| `POST` | `/api/enrollment/save` | Lưu hồ sơ đã quét |
| `POST` | `/api/enrollment/reset` | Hủy dữ liệu quét hiện tại |
| `GET` | `/api/employees` | Danh sách nhân viên |
| `PUT` | `/api/employees/{id}` | Cập nhật nhân viên |
| `DELETE` | `/api/employees/{id}` | Xóa nhân viên |
| `GET` | `/api/attendance` | Lịch sử xác thực |
| `GET` | `/api/dashboard` | Số liệu dashboard |
| `GET` | `/api/door/events` | Sự kiện gần nhất của cửa |
| `GET` | `/api/admin/fingerprints` | Danh sách registry vân tay |
| `POST` | `/api/admin/fingerprints/enroll` | Đăng ký vân tay |
| `PUT` | `/api/admin/fingerprints/{id}` | Cập nhật danh tính vân tay |
| `DELETE` | `/api/admin/fingerprints/{id}` | Xóa vân tay |

Kênh TFT tại cổng `8767` chỉ cung cấp `GET /health` và `GET /frame.jpg`, yêu cầu header `X-FaceCheck-Token`.

## 12. Dữ liệu lưu trữ

| Đường dẫn | Nội dung |
|---|---|
| `data/embeddings.pkl` | Hồ sơ nhân viên và embedding ArcFace |
| `data/faces/` | Ảnh đại diện khuôn mặt |
| `data/attendance_history.json` | Lịch sử xác thực gần nhất |
| `data/fingerprints.json` | Registry ID vân tay và danh tính |
| `data/door_events.json` | Sự kiện gần nhất từ ESP32-S3 cửa |
| `data/facecheck_desktop.log` | Log khởi động từ icon Desktop |
| `models/model.pt` | Model YOLO phát hiện khuôn mặt |

Ảnh khuôn mặt, embedding và mẫu vân tay là dữ liệu sinh trắc học nhạy cảm. Cần giới hạn quyền truy cập và sao lưu an toàn.

Khi chuyển sang máy khác, nên sao lưu ít nhất:

```text
data/embeddings.pkl
data/faces/
data/attendance_history.json
data/fingerprints.json
models/
.env
```

## 13. Nạp firmware

Các cổng COM dưới đây là cấu hình hiện tại trong `platformio.ini`; hãy kiểm tra Device Manager nếu Windows cấp cổng khác.

### Camera ESP32-S3 OV3660 qua Wi-Fi — COM11

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32_s3_ov3660 -t upload
```

### Camera ESP32-S3 OV3660 qua USB-OTG — COM12

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32_s3_ov3660_usb -t upload
```

### Bộ điều khiển cửa ESP32-S3 N16R8 — COM6

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\Smart_Door -t upload
```

### Màn hình ESP32-035 — COM15

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32_035_display -t upload
```

Nếu ESP32-S3 không vào chế độ nạp: giữ `BOOT`, nhấn rồi thả `RESET`, thả `BOOT`, sau đó chạy lại lệnh.

Mỗi thư mục firmware có README riêng về chân kết nối và cấu hình `secrets.h`.

## 14. Chính sách nhận diện

Các ngưỡng chính nằm trong `config.py`:

- `ARCFACE_THRESHOLD`: ngưỡng cosine distance của ứng viên tốt nhất;
- `ARCFACE_TOP2_MARGIN`: khoảng cách tối thiểu giữa Top 1 và Top 2;
- `ARCFACE_HIGH_CONFIDENCE_*`: nhánh xác nhận nhanh nhưng vẫn yêu cầu nhiều frame;
- `ARCFACE_STRICT_*`: số lần xác nhận và cửa sổ thời gian strict;
- `KIOSK_MIN_FACE_*`: kích thước và confidence tối thiểu;
- `KIOSK_*_ANGLE/RATIO`: giới hạn tư thế khuôn mặt;
- `ENROLLMENT_*`: số mẫu và chất lượng khi đăng ký;
- `KIOSK_ATTENDANCE_COOLDOWN_SECONDS`: chống ghi trùng.

Không nên giảm threshold theo cảm tính. Hãy hiệu chuẩn trên ảnh đúng camera và đúng môi trường triển khai bằng các công cụ trong `tools/`.

## 15. Kiểm thử

Chạy toàn bộ test mà không tải AI hoặc mở camera thật:

```powershell
$env:FACECHECK_WEB_SKIP_AI="1"
.\venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:FACECHECK_WEB_SKIP_AI -ErrorAction SilentlyContinue
```

Build firmware cửa mà chưa nạp:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\Smart_Door
```

## 16. Công cụ hỗ trợ

- `tools/read_serial.py`: đọc log serial;
- `tools/usb_camera_bridge.py`: chuyển JPEG serial thành MJPEG cục bộ;
- `tools/mqtt_door_monitor.py`: theo dõi trạng thái và sự kiện MQTT;
- `tools/mqtt_door_ping.py`: kiểm tra MQTT mà không mở relay;
- `tools/mqtt_door_open.py`: gửi lệnh mở cửa thủ công có xác nhận;
- `tools/benchmark_wifi_camera.py`: đo FPS camera Wi-Fi;
- `tools/calibrate_recognition.py`: hiệu chuẩn ngưỡng nhận diện;
- `tools/calibrate_esp_camera_recognition.py`: hiệu chuẩn bằng ảnh camera ESP32.

Xem tham số trước khi sử dụng:

```powershell
.\venv\Scripts\python.exe tools\benchmark_wifi_camera.py --help
.\venv\Scripts\python.exe tools\calibrate_recognition.py --help
```

## 17. Xử lý sự cố

### Nhấp icon nhưng chưa thấy giao diện

- Lần đầu tải AI có thể mất vài chục giây.
- Kiểm tra cửa sổ trạng thái của launcher.
- Kiểm tra `data/facecheck_desktop.log`.
- Mở thử `http://127.0.0.1:8765/api/health`.
- Nếu server đã chạy, nhấp icon lần nữa để mở lại trang quản trị.

### Không tìm thấy camera Wi-Fi

- Đảm bảo laptop và ESP32 cùng mạng 2.4 GHz.
- Mở `http://<camera-ip>/health`.
- Kiểm tra IP trên Serial Monitor 115200 baud.
- Chạy với `--camera-host <ip>` nếu mDNS không ổn định.
- Kiểm tra router có bật client isolation hay không.

### Camera USB không hoạt động

- Không nhầm cổng upload với cổng CDC runtime.
- Kiểm tra Device Manager.
- Đảm bảo không có Serial Monitor khác đang giữ cổng.
- Mở `http://127.0.0.1:8766/health` để kiểm tra bridge.

### Cổng 8765 hoặc 8767 bị chiếm

```powershell
Get-NetTCPConnection -LocalPort 8765,8767 -ErrorAction SilentlyContinue
```

Đóng phiên FaceCheck cũ trước khi chạy lại. Không khởi chạy nhiều `web_admin.py` trực tiếp.

### Telegram không hiện tên vân tay

- Kiểm tra ID đã có họ tên trong giao diện quản trị.
- Bật server và chờ MQTT kết nối để đồng bộ registry vào NVS.
- Kiểm tra log ESP32 có dòng đồng bộ `FINGERPRINT_SET_NAME`.
- Nếu NVS vừa bị xóa, server phải kết nối lại ít nhất một lần.

### Nhận diện sai hoặc từ chối nhiều

- Đặt mặt đủ gần, nhìn thẳng và chiếu sáng đều.
- Đăng ký bằng đúng camera sẽ dùng thực tế.
- Tránh ảnh mờ, cháy sáng hoặc che vùng miệng.
- Chạy calibration trước khi thay đổi threshold.

## 18. Bảo mật và vận hành

- Admin backend chỉ bind `127.0.0.1`; không mở ra LAN nếu chưa bổ sung xác thực.
- Kênh TFT bind LAN nhưng chỉ đọc và bắt buộc token.
- MQTT sử dụng TLS và lệnh mở cửa có ID, TTL, ACK và giới hạn thời lượng.
- Không commit `.env`, `secrets.h`, ảnh mặt, embedding, lịch sử hoặc token bot.
- Dùng token dài, ngẫu nhiên và khác nhau cho Telegram, MQTT và TFT.
- Sao lưu `data/faces/` cùng `data/embeddings.pkl`.
- Đồng bộ giờ Windows và NTP trên ESP32 để thời gian thông báo chính xác.
- Xóa hồ sơ sinh trắc học từ giao diện là thao tác không thể hoàn tác nếu không có backup.

## 19. Bắt đầu nhanh

```powershell
cd D:\HK7\DACN\DA
.\venv\Scripts\python.exe facecheck.py wifi
```

Hoặc nhấp đúp icon **FaceCheck Server** trên Desktop.

Sau khi server sẵn sàng, mở:

```text
http://127.0.0.1:8765/?view=admin#dashboard
```
