import requests
import uuid 
from typing import Dict, Any
from app.schemas.ai_output import MlOutputDTO
from app.core.settings import ai_service_url

class AIApiClient:
    def __init__(self):

        self.base_url = "http://localhost:9000"

    def fetch_ai_inference(self, image_bytes: bytes, filename: str) -> Dict[str, Any]:
        file_id = str(uuid.uuid4())
        files = {"file": (filename, image_bytes)}
        data = {"file_id": file_id}
        
        unet_url = "http://127.0.0.1:9000/inference/unet"
        unet_res = requests.post(unet_url, files=files, data=data)
        unet_res.raise_for_status()
        
      
        yolo_url = "http://localhost:9000/inference/yolo"
        
        print(f"DEBUG: YOLO 재시도 주소 -> {yolo_url}")
        
        yolo_res = requests.post(yolo_url, files=files, data=data, allow_redirects=False)
        
        yolo_res.raise_for_status()
        
        return {
            "unet": unet_res.json(),
            "yolo": yolo_res.json()
        }

ai_client = AIApiClient()