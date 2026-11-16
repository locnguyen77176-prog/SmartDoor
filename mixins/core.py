"""Load AI models, embeddings, and attendance history for the web runtime."""

import threading
import re
from pathlib import Path
import numpy as np

from config import DATA_FACES_DIR, DEEPFACE_MODEL_NAME
from ai_engine import check_gpu_quick, load_face_model, load_mediapipe_detector


class CoreMixin:
    """Manage AI resources and persistent data."""

    def _reload_embeddings_cache(self):
        """
        Nạp dữ liệu vector embeddings vào RAM để truy vấn siêu tốc.
        Tự động đối chiếu và dọn dẹp các vector mồ côi (nhân viên đã bị xóa ảnh khỏi database).
        """
        try:
            data = self._read_profiles()
            if data:
                # Quét các ID nhân viên còn ảnh hợp lệ trong DATA_FACES_DIR
                faces_dir = Path(DATA_FACES_DIR)
                active_ids = set()
                if faces_dir.exists():
                    for img_f in faces_dir.glob("*.jpg"):
                        stem = img_f.stem
                        e_id = stem.split("@")[0] if "@" in stem else stem.split("_")[0]
                        active_ids.add(e_id.strip().lower())
                        
                cleaned_data = {}
                need_resave = False
                for emp_id, emp_val in data.items():
                    if str(emp_id).strip().lower() in active_ids:
                        profile = dict(emp_val)
                        role = str(profile.get("role") or "Nhân viên").strip()
                        department = profile.get("department") or profile.get("dept")

                        # Chuẩn hóa hồ sơ cũ từng lưu "Chức vụ - Phòng ban"
                        # trong cùng một trường role.
                        if not department:
                            legacy_parts = re.split(r"\s*[-–]\s*", role, maxsplit=1)
                            if len(legacy_parts) == 2:
                                role, department = legacy_parts[0], legacy_parts[1]
                            else:
                                department = "Phòng IT"
                            need_resave = True

                        if profile.get("role") != role:
                            profile["role"] = role
                            need_resave = True
                        if profile.get("department") != department:
                            profile["department"] = department
                            need_resave = True
                        if "dept" in profile:
                            profile.pop("dept", None)
                            need_resave = True

                        # Hồ sơ benchmark chỉ phục vụ kiểm thử, không được tham gia
                        # điểm danh thật nếu chưa được người quản trị chủ động bật.
                        if profile.get("source") == "LFW benchmark":
                            if profile.get("recognition_enabled", True):
                                profile["recognition_enabled"] = False
                                need_resave = True
                        elif "recognition_enabled" not in profile:
                            profile["recognition_enabled"] = (
                                profile.get("source") != "LFW benchmark"
                            )
                            need_resave = True

                        cleaned_data[emp_id] = profile
                    else:
                        print(f"[AI CACHE] Tự động loại bỏ vector mồ côi của nhân viên đã xóa: {emp_id} ({emp_val.get('name')})")
                        need_resave = True
                        
                if need_resave:
                    self._write_profiles(cleaned_data)
                    print(f"[AI CACHE] Đã đồng bộ lại SQLite (còn {len(cleaned_data)} nhân viên hoạt động).")
                    
                self.embeddings_cache = cleaned_data
            else:
                self.embeddings_cache = {}
        except Exception as e:
            print(f"[AI] Lỗi nạp embeddings cache: {e}")
            self.embeddings_cache = {}

    def _load_attendance_history(self):
        """Nạp toàn bộ lịch sử xác thực từ SQLite."""
        try:
            history = self.database.load_authentication_logs()
            sanitizer = getattr(self, "_json_safe", None)
            self.attendance_history = (
                sanitizer(history) if callable(sanitizer) else history
            )
            if self.attendance_history != history:
                self._save_attendance_history()
                print("[HISTORY] Da lam sach NaN/Infinity trong SQLite.")
        except Exception as exc:
            print(f"[HISTORY] Lỗi đọc SQLite: {exc}")
            self.attendance_history = []

    def _save_attendance_history(self):
        """Lưu lịch sử xác thực bền vững vào SQLite."""
        try:
            self.database.replace_authentication_logs(self.attendance_history)
        except Exception as exc:
            print(f"[HISTORY] Lỗi lưu SQLite: {exc}")

    def _warmup_deepface_async(self):
        """Khởi động sẵn ArcFace & YOLOv8 ngầm để tab Kiosk không bị đơ giật khi nhận diện lần đầu."""
        try:
            # 1. Warm-up YOLOv8 Face trên GPU CUDA
            if hasattr(self, 'face_model') and self.face_model is not None:
                dummy_yolo = np.zeros((480, 640, 3), dtype=np.uint8)
                self.face_model(dummy_yolo, verbose=False)
                
            # 2. Warm-up DeepFace ArcFace
            print("[AI] Đang warm-up DeepFace ArcFace trong nền...")
            from deepface import DeepFace
            dummy_img = np.zeros((112, 112, 3), dtype=np.uint8)
            DeepFace.represent(
                img_path=dummy_img,
                model_name=DEEPFACE_MODEL_NAME,
                detector_backend="skip",
                enforce_detection=False
            )
            print("[AI] DeepFace ArcFace đã sẵn sàng (Warm-up thành công).")
        except Exception as e:
            print(f"[AI] Warm-up ArcFace note: {e}")

    def _load_ai_models(self):
        """Load tất cả AI models qua ai_engine module."""
        print("[AI] Đang load AI models...")
        self.device = check_gpu_quick()
        self.face_model, self.device = load_face_model(self.device)
        self.face_detector = load_mediapipe_detector()
        
        # Nạp cache embeddings vào RAM
        self._reload_embeddings_cache()
        
        # Khởi động sẵn DeepFace ArcFace trong nền
        threading.Thread(target=self._warmup_deepface_async, daemon=True).start()
        print("[AI] Load models hoàn tất.")
