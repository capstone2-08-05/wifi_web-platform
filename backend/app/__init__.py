import shutil
import os
from pathlib import Path

UPLOAD_DIR = Path("/Users/heiseung/wifi_web-platform/backend/data/uploads")

def initialize_uploads():
    if UPLOAD_DIR.exists():
        for file in os.scandir(UPLOAD_DIR):
            try:
                if file.is_file() or file.is_symlink():
                    os.unlink(file.path)
                elif file.is_dir():
                    shutil.rmtree(file.path)
            except Exception as e:
                print(f"파일 삭제 실패: {file.path} ({e})")
        print(f"✨ {UPLOAD_DIR} 폴더가 깨끗하게 비워졌습니다!")
    else:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

initialize_uploads()