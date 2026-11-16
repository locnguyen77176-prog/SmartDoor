# FaceCheck — Hệ thống kiểm soát ra vào bằng khuôn mặt và vân tay

FaceCheck là hệ thống kiểm soát cửa chạy cục bộ trên máy tính Windows, kết hợp:

- nhận diện khuôn mặt bằng camera ESP32-S3 OV3660 hoặc webcam;
- xác thực vân tay bằng cảm biến AS608;
- điều khiển khóa điện qua ESP32-S3;
- giao diện quản trị và màn hình kiosk;
- thông báo Telegram;
- giao tiếp an toàn giữa server và bộ điều khiển cửa qua MQTT/TLS.

Máy tính là **server xử lý AI và quản lý dữ liệu**. ESP32-S3 cửa là **thiết bị điều khiển phần cứng**, vẫn cho phép vân tay và nút nhấn hoạt động khi server hoặc mạng bị mất.

README này mô tả **trạng thái mã nguồn hiện tại**, không mô tả các chức năng mới chỉ nằm trong kế hoạch. Đặc biệt, phiên bản hiện tại không có lệnh `FINGERPRINT_SYNC` và không đọc toàn bộ danh sách slot từ AS608 lên server.

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
- Đồng bộ tên từ bảng `fingerprints` trong `data/facecheck.db` vào NVS mỗi khi MQTT kết nối lại.

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
| Bảng `fingerprints` trong `data/facecheck.db` | ID vân tay, mã nhân viên, họ tên, chức vụ, phòng ban | Registry quản lý trên server |
| NVS của ESP32-S3 cửa | Ánh xạ `ID vân tay → họ tên` | Hiển thị tên Telegram khi server tắt |

AS608 **không lưu họ tên**. Nó chỉ biết mẫu vân tay thuộc ID nào.

Ánh xạ tên trong NVS được cập nhật trong các trường hợp:

- đăng ký vân tay thành công: ESP32 lưu tên đi kèm lệnh đăng ký;
- cập nhật thông tin người dùng: server gửi `FINGERPRINT_SET_NAME`;
- xóa vân tay thành công: ESP32 xóa khóa tên tương ứng khỏi NVS;
- server và ESP32 kết nối lại MQTT: server gửi lại tên của toàn bộ registry hiện có.

Nếu server tắt sau khi đã đồng bộ, ESP32 vẫn thông báo được tên. Nếu NVS bị xóa hoặc ESP32 vừa thay mới, cần bật server và kết nối MQTT ít nhất một lần để đồng bộ lại.

Firmware dùng hai namespace NVS riêng:

- `fp_names`: ánh xạ khóa `id_<ID>` sang họ tên vân tay;
- `door_users`: danh sách Chat ID Telegram đã được admin ủy quyền.

Registry trên server và mẫu trong AS608 là hai nguồn dữ liệu độc lập. Xóa hồ sơ khuôn mặt không tự xóa mẫu AS608; ngược lại, mẫu được thêm trực tiếp ngoài luồng quản trị có thể chưa có tên trên server/NVS. Phiên bản hiện tại chưa có chức năng inventory để tự động phát hiện toàn bộ sai lệch này.

## 4. Thành phần phần mềm

| Tệp/thư mục | Trách nhiệm chính |
|---|---|
| `facecheck.py` | Launcher, chọn nguồn camera, nạp `.env`, chống chạy trùng |
| `desktop_launcher.py` | Launcher Desktop không hiện CMD, có màn hình chờ và log lỗi |
| `web_admin.py` | Khởi động Uvicorn, giao diện trình duyệt/PyWebView và kênh TFT |
| `web_runtime.py` | State dùng chung, CRUD nhân viên, đăng ký, lịch sử và điều phối worker |
| `database.py` | Lớp truy cập SQLite, schema và ánh xạ dữ liệu runtime |
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
| `tools/migrate_to_sqlite.py` | Sao lưu, nhập và kiểm tra dữ liệu JSON/Pickle cũ vào SQLite |
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

### Hai chế độ firmware camera

Hai firmware camera dùng cùng pinout OV3660 của bo đang lắp: XCLK GPIO15, SIOD GPIO4, SIOC GPIO5, D2..D9 lần lượt ở GPIO11, 9, 8, 10, 12, 18, 17, 16, VSYNC GPIO6, HREF GPIO7 và PCLK GPIO13.

| Firmware | Đường truyền | Ảnh/cấu hình hiện tại | Cách server nhận |
|---|---|---|---|
| `esp32_s3_ov3660` | Wi-Fi 2,4 GHz | HVGA 480×320, JPEG quality 20, 1 frame buffer, mục tiêu 5 FPS | HTTP `/capture`, `/health`; MJPEG cổng 81 `/stream` |
| `esp32_s3_ov3660_usb` | USB-OTG CDC | VGA 640×480, JPEG quality 10, 1 frame buffer, mục tiêu 8 FPS | `tools/usb_camera_bridge.py` tạo stream cục bộ cổng 8766 |

Camera chỉ thu và truyền JPEG; YOLO, MediaPipe và ArcFace đều chạy trên máy tính. Khi đã chọn camera Wi-Fi, backend không âm thầm chuyển sang webcam nếu ESP32 mất kết nối mà phải báo camera ngoại tuyến.

### Màn hình ESP32-035 TFT tùy chọn

TFT không chạy AI. Nó kết nối Wi-Fi đến kênh chỉ đọc cổng 8767, gửi `X-FaceCheck-Token`, lấy JPEG mới nhất cùng trạng thái trong HTTP header và hiển thị tối đa 5 FPS. Firmware hỗ trợ hai profile `esp32-035-st7796` và `esp32-035-ili9488`; xem [README của màn hình](firmware/esp32_035_display/README.md) để chọn đúng controller và pinout.

### Bộ điều khiển cửa `Smart_Door`

Firmware được tách thành các driver:

- `Fingerprint_Driver`: giao tiếp AS608 và quản lý mẫu vân tay;
- `Lock_Driver`: điều khiển relay và trạng thái khóa;
- `Display_Driver`: hiển thị OLED;
- `MQTT_Driver`: lệnh mở cửa, quản lý vân tay, ACK và event;
- `Telegram_Driver`: bot, thông báo và tên vân tay trong NVS;
- `Smart_Door.ino`: tạo queue, event group và các FreeRTOS task.

MQTT callback không mở relay trực tiếp. Lệnh phải được kiểm tra thời hạn và đưa vào queue; chỉ task điều khiển khóa được phép tác động relay.

### Sơ đồ chân bộ điều khiển cửa

| Chức năng | GPIO/giao tiếp | Mức tác động hoặc cấu hình |
|---|---:|---|
| Relay khóa | GPIO4 | Active LOW |
| Buzzer | GPIO5 | Active HIGH |
| LED xanh | GPIO6 | Active HIGH |
| LED đỏ | GPIO7 | Active HIGH |
| OLED SDA | GPIO8 | I²C, địa chỉ `0x3C` |
| OLED SCL | GPIO9 | I²C, địa chỉ `0x3C` |
| Nút mở cửa bên trong | GPIO15 | Active LOW, `INPUT_PULLUP` |
| AS608 RX của ESP32 | GPIO18 | Nối TX của AS608 |
| AS608 TX của ESP32 | GPIO17 | Nối RX của AS608 |
| AS608 UART | UART2 | 57.600 baud, 8N1 |

Relay, buzzer và khóa không được cấp tải trực tiếp từ GPIO. Phải dùng tầng công suất, diode bảo vệ và nguồn phù hợp với phần cứng thực tế; tất cả module phải dùng chung tham chiếu GND khi thiết kế yêu cầu.

### Sáu FreeRTOS task của firmware cửa

Khi `ENABLE_LEGACY_TELEGRAM=1` như cấu hình hiện tại, ứng dụng tạo sáu task sau. Đây là task của ứng dụng, chưa tính task hệ thống do Arduino/ESP-IDF tạo.

| Task | Core | Priority | Stack | Trách nhiệm |
|---|---:|---:|---:|---|
| `Task_LockControl` | 1 | 4 | 2.048 byte | Nhận sự kiện, điều khiển relay, buzzer và ACK chu kỳ mở |
| `Task_Fingerprint` | 1 | 3 | 4.096 byte | Quét, đăng ký, xóa và phục hồi kết nối AS608 |
| `Task_Button` | 1 | 3 | 2.048 byte | Chống dội và xử lý nút mở cửa bên trong |
| `Task_Display` | 1 | 2 | 4.096 byte | Nhận message và cập nhật OLED |
| `Task_MQTT` | 0 | 1 | 8.192 byte | Wi-Fi, NTP, MQTT/TLS, heartbeat, ACK và event |
| `Task_Telegram` | 0 | 1 | 12.288 byte | Poll bot, phân quyền và gửi thông báo Telegram |

Các primitive chính:

- `lockEventGroup`: bốn bit mở cửa từ vân tay, nút nhấn, Telegram và server;
- `displayQueue`: 5 phần tử;
- `serverUnlockQueue`: 4 phần tử;
- `fingerprintCommandQueue`: 2 phần tử;
- MQTT ACK queue: 12 phần tử;
- MQTT event queue: 16 phần tử;
- Telegram notification queue: 10 phần tử.

ACK và event được xếp hàng để chỉ `Task_MQTT` truy cập `PubSubClient`. Event queue chỉ nằm trong RAM: có thể gửi bù sau khi MQTT nối lại nếu ESP32 vẫn còn nguồn, nhưng sẽ mất khi reset, mất điện hoặc queue đầy.

### Hợp đồng MQTT/TLS

Các topic được tạo theo `DEVICE_ID` (mặc định `door-01`):

| Topic | Chiều | Retain | Nội dung |
|---|---|---:|---|
| `smartdoor/v1/<device_id>/command` | Server → ESP32 | Không | Lệnh điều khiển |
| `smartdoor/v1/<device_id>/ack` | ESP32 → server | Không | `received`, `started`, `finished`, `failed` |
| `smartdoor/v1/<device_id>/event` | ESP32 → server | Không | Sự kiện phần cứng tối giản |
| `smartdoor/v1/<device_id>/status` | ESP32 → server | Có | `online`/`offline`, firmware, uptime, RSSI |

Lệnh đang được firmware hỗ trợ:

| Lệnh | Tác dụng | Trạng thái kết thúc chính |
|---|---|---|
| `PING` | Kiểm tra đường truyền, không kích relay | `received` |
| `OPEN` | Mở khóa theo `duration_ms` | `started` → `finished` hoặc `failed` |
| `FACE_AUTH_RESULT` | Đưa kết quả khuôn mặt vào queue Telegram | `received` hoặc `failed` |
| `FINGERPRINT_ENROLL` | Thu hai lần, kiểm tra trùng và lưu mẫu | `started` → `finished`/`failed` |
| `FINGERPRINT_DELETE` | Xóa mẫu theo ID | `started` → `finished`/`failed` |
| `FINGERPRINT_SET_NAME` | Ghi ID → tên vào NVS | `finished` hoặc `failed` |

Quy tắc an toàn chính:

- MQTT dùng TLS cổng 8883 và xác thực CA `ISRG Root X1`;
- lệnh mang `device_id`, `command_id` và thời hạn; `command_id` dài tối đa 48 ký tự an toàn;
- các lệnh có thao tác (`OPEN`, kết quả khuôn mặt và quản lý vân tay) phải còn hạn và không quá 15 giây trong tương lai; `PING` chỉ kiểm tra đường truyền nên không yêu cầu TTL;
- `OPEN` chỉ chấp nhận `duration_ms` từ 500 đến 10.000 ms;
- server phát `OPEN` với TTL 10 giây, QoS 1, `retain=false`;
- firmware nhớ 8 `command_id` gần nhất trong RAM để từ chối lệnh trùng;
- callback MQTT chỉ kiểm tra và xếp hàng, không trực tiếp mở relay.

AS608 được phần mềm quản lý trong dải ID `1..127`. Cảm biến kiểm tra ngón tay trùng trước khi tạo mẫu mới. Hiện ACK lỗi `fingerprint_already_registered` **chưa chứa ID cũ**; ID trùng chỉ được firmware biết và in/hiển thị cục bộ. Không được coi registry server là inventory đầy đủ của AS608.

### Telegram Bot

Các lệnh hiện còn hỗ trợ:

- `/start`: hiển thị phần trợ giúp, tương đương `/help`;
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
- relay, tầng công suất và khóa điện;
- OLED, buzzer, LED xanh/đỏ và nút nhấn mở cửa;
- nguồn 12 V cho khóa và nguồn hạ áp phù hợp cho các module;
- ESP32-035 TFT nếu dùng màn hình kiosk ngoài.

## 7. Cài đặt server

Nếu cài trên máy Windows khác và cần giữ nguyên model, hồ sơ, vân tay và cấu hình, xem [Hướng dẫn chạy trên máy khác](HUONG_DAN_CHAY.md).

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
models/blaze_face_short_range.tflite
```

Hai model trên bị `.gitignore` bỏ qua nên không tự xuất hiện sau `git clone`. DeepFace/ArcFace cũng có thể cần tải trọng số vào cache người dùng ở lần chạy đầu. Khi cài máy mới, xem [Hướng dẫn chạy trên máy khác](HUONG_DAN_CHAY.md) và chuẩn bị model trước khi chạy offline.

## 8. Cấu hình `.env`

Tạo file `.env` tại thư mục gốc. Ví dụ tối thiểu:

```dotenv
# Camera
FACECHECK_CAMERA_HOST=facecheck-cam.local
FACECHECK_CAMERA_PROFILE=embedded_ov3660
FACECHECK_CAMERA_FLIP=0

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

`FACECHECK_CAMERA_FLIP` mặc định là `0` với camera nhúng và `1` với webcam. Chỉ đổi giá trị khi camera thực tế bị lật ngang. Nếu không khai báo đủ `MQTT_HOST`, `MQTT_USERNAME` và `MQTT_PASSWORD`, dịch vụ cửa trên server tự tắt theo hướng fail-closed và không gửi lệnh mở cửa.

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

Icon Desktop là cấu hình riêng của từng máy và không đi theo Git. Trên máy mới, tạo shortcut có:

```text
Target:   <thu-muc-du-an>\venv\Scripts\pythonw.exe <thu-muc-du-an>\desktop_launcher.py
Start in: <thu-muc-du-an>
```

Đặt dấu ngoặc kép quanh từng đường dẫn nếu có khoảng trắng. `desktop_launcher.py` chạy `facecheck.py wifi`, không hiện CMD, chờ tối đa 120 giây và mở Admin UI bằng trình duyệt. Muốn dùng webcam hoặc USB-OTG, chạy lệnh PowerShell tương ứng thay vì icon mặc định.

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
| `POST` | `/api/enrollment/cancel-scan` | Hủy riêng lượt quét đang chạy |
| `POST` | `/api/enrollment/activity` | Gia hạn phiên thao tác đăng ký |
| `POST` | `/api/enrollment/finish` | Kết thúc phiên đăng ký |
| `GET` | `/api/employees` | Danh sách nhân viên |
| `GET` | `/api/employees/{id}/image` | Ảnh đại diện nhân viên |
| `PUT` | `/api/employees/{id}` | Cập nhật nhân viên |
| `POST` | `/api/employees/{id}/toggle` | Bật/tắt tham gia nhận diện khuôn mặt |
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
| `data/facecheck.db` | SQLite: nhân viên, embedding ArcFace, registry vân tay, lịch sử xác thực, sự kiện cửa và trạng thái thiết bị |
| `data/faces/` | Ảnh đại diện khuôn mặt |
| `data/facecheck_desktop.log` | Log khởi động từ icon Desktop |
| `models/model.pt` | Model YOLO phát hiện khuôn mặt |
| `models/blaze_face_short_range.tflite` | Model MediaPipe Tasks phục vụ landmark/chất lượng |

Server hiện đọc và ghi dữ liệu nghiệp vụ trực tiếp vào SQLite. Các tệp cũ `embeddings.pkl`, `attendance_history.json`, `fingerprints.json` và `door_events.json` chỉ được giữ lại làm nguồn khôi phục sau lần chuyển đổi; runtime không còn dùng chúng. Các tệp pickle trong `data/benchmark_faces/` vẫn là cache benchmark ngoại tuyến, không phải dữ liệu vận hành.

Ảnh khuôn mặt, embedding và mẫu vân tay là dữ liệu sinh trắc học nhạy cảm. Cần giới hạn quyền truy cập và sao lưu an toàn.

Khi chuyển sang máy khác, nên sao lưu ít nhất:

```text
data/facecheck.db
data/faces/
models/
.env
```

Hãy tắt server trước khi sao chép `facecheck.db`, hoặc dùng cơ chế backup trực tuyến của SQLite. Database bật WAL, khóa ngoại và `busy_timeout`; các cập nhật thay thế nhiều bảng được thực hiện trong transaction. Ảnh khuôn mặt vẫn nằm trong `data/faces/`, vì vậy phải sao lưu thư mục này cùng database.

Nếu đang nâng cấp từ bản dùng JSON/Pickle, chạy một lần:

```powershell
.\venv\Scripts\python.exe tools\migrate_to_sqlite.py
```

Công cụ tạo bản sao lưu có dấu thời gian trong `data/backups/`, hợp nhất dữ liệu cũ với database hiện có, chống nhập trùng khi chạy lại và kiểm tra chính xác các vector embedding sau khi chuyển.

## 13. Nạp firmware

Các cổng COM dưới đây là cấu hình hiện tại trong `platformio.ini`; hãy kiểm tra Device Manager nếu Windows cấp cổng khác.

Chuẩn bị cấu hình riêng trước khi build:

| Firmware | Cấu hình cần tạo |
|---|---|
| Camera Wi-Fi | Sao chép `firmware/esp32_s3_ov3660/secrets.example.h` thành `secrets.h` cùng thư mục |
| Camera USB-OTG | Không cần Wi-Fi hoặc `secrets.h` |
| Bộ điều khiển cửa | Sao chép `firmware/Smart_Door/secrets.example.h` thành `secrets.h` cùng thư mục |
| TFT | Tạo thư mục `include`, rồi sao chép `secrets.example.h` thành `firmware/esp32_035_display/include/secrets.h` |

Không commit bất kỳ `secrets.h` nào.

Lệnh chuẩn bị TFT trên PowerShell:

```powershell
New-Item -ItemType Directory -Force firmware\esp32_035_display\include
Copy-Item firmware\esp32_035_display\secrets.example.h firmware\esp32_035_display\include\secrets.h
```

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
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32_035_display -e esp32-035-st7796 -t upload
```

Nếu bo dùng ILI9488 và bản ST7796 chỉ hiện trắng/đen/nhiễu:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d firmware\esp32_035_display -e esp32-035-ili9488 -t upload
```

Với firmware USB-OTG, COM12 là cổng bootloader/upload trong cấu hình hiện tại; cổng CDC truyền frame khi chạy có thể là COM khác (máy hiện tại dùng COM13). Không dùng cổng CDC runtime để nạp firmware.

Nếu ESP32-S3 không vào chế độ nạp: giữ `BOOT`, nhấn rồi thả `RESET`, thả `BOOT`, sau đó chạy lại lệnh.

Mỗi thư mục firmware có README riêng về cách build, nạp, kết nối và cấu hình tương ứng.

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

Giá trị quyết định chính của phiên bản hiện tại:

| Tham số | Giá trị |
|---|---:|
| `ARCFACE_THRESHOLD` | 0,460 |
| `ARCFACE_TOP2_MARGIN` | 0,120 |
| Số frame gộp query | 2 |
| Nhánh confidence cao | khoảng cách ≤ 0,400, 2 xác nhận |
| Nhánh strict | 3 xác nhận, tối đa 8 lần thử trong 3 giây |
| Khuôn mặt ổn định trước nhận diện | 0,7 giây |
| Số mẫu đăng ký tối đa/tối thiểu | 5/3 |
| Cooldown lịch sử cùng nhân viên | 60 giây |
| Cooldown lệnh cửa từ khuôn mặt | 8 giây mặc định |
| Thời gian không còn mặt để tái kích | 1,5 giây mặc định |

Khoảng cách cosine 0,460 không phải xác suất đúng 46%. Các giá trị phải được hiệu chuẩn lại nếu đổi camera, độ phân giải, ánh sáng hoặc tập người dùng.

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

README không cố định một con số test “luôn đạt”, vì số ca thay đổi cùng mã nguồn. Chỉ công bố kết quả sau khi chạy lệnh trên đúng commit và lưu lại đầu ra; test phần mềm không thay thế thử nghiệm AS608, relay, nguồn, MQTT broker thật và người dùng thật.

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
- Tắt server rồi sao lưu `data/faces/` cùng `data/facecheck.db`.
- Đồng bộ giờ Windows và NTP trên ESP32 để thời gian thông báo chính xác.
- Xóa hồ sơ sinh trắc học từ giao diện là thao tác không thể hoàn tác nếu không có backup.

## 19. Giới hạn hiện tại

- Không có `FINGERPRINT_SYNC` hoặc API đọc toàn bộ inventory slot của AS608.
- ACK `fingerprint_already_registered` chưa trả `duplicate_fingerprint_id` cho server.
- Registry server, NVS và AS608 có thể lệch nếu thao tác ngoài luồng quản trị hoặc mất kết nối giữa chừng.
- Event offline của ESP32 chỉ được đệm bằng RAM 16 phần tử, không bền qua mất điện/reset.
- Mở cửa bằng khuôn mặt phụ thuộc camera, server, MQTT broker và ESP32 cửa; vân tay và nút bên trong mới là hai luồng cục bộ.
- Chưa có cảm biến vị trí cửa; ACK `finished` chỉ xác nhận hết chu kỳ điều khiển relay, không chứng minh cánh cửa đã đóng.
- Chưa có lớp chống giả mạo/liveness hoàn chỉnh; YOLO, kiểm tra chất lượng và nhiều frame không thay thế liveness chuyên dụng.
- Admin UI/API chưa có đăng nhập; vì vậy backend quản trị chỉ bind `127.0.0.1`. Không mở cổng 8765 ra LAN/Internet nếu chưa bổ sung xác thực và phân quyền.
- Telegram cần Internet, token bot hợp lệ và `ENABLE_LEGACY_TELEGRAM=1`; lỗi Telegram không được coi là bằng chứng khóa không hoạt động.
- TFT là module tùy chọn và chỉ nhận ảnh/trạng thái đọc qua cổng 8767 có token; nó không tự nhận diện khuôn mặt.
- Dự án hiện tối ưu cho một cửa (`door-01`), chưa phải hệ thống quản lý nhiều cửa hoàn chỉnh.

## 20. Bắt đầu nhanh

```powershell
cd D:\HK7\DACN\DA
.\venv\Scripts\python.exe facecheck.py wifi
```

Hoặc nhấp đúp icon **FaceCheck Server** trên Desktop.

Sau khi server sẵn sàng, mở:

```text
http://127.0.0.1:8765/?view=admin#dashboard
```
