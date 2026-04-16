import requests
import uuid 
from typing import Dict, Any
from app.schemas.ai_response import MlOutputDTO

class AIApiClient:
    def __init__(self):
        self.base_url = "http://localhost:9000"

    def fetch_ai_inference(self, image_bytes: bytes, filename: str) -> Dict[str, Any]:
      
        file_id = str(uuid.uuid4())
        
        files = {"file": (filename, image_bytes)}
        data = {"file_id": file_id}
        
        try:
            unet_url = f"{self.base_url}/inference/unet"
            unet_res = requests.post(unet_url, files=files, data=data, timeout=300.0)
            unet_res.raise_for_status()
            
            yolo_url = f"{self.base_url}/inference/yolo"
            
           
            yolo_res = requests.post(yolo_url, files=files, data=data, timeout=300.0)
            yolo_res.raise_for_status()
            
            return {
                "unet": unet_res.json(),
                "yolo": yolo_res.json()
            }

        except requests.exceptions.RequestException as e:
            print(f"❌ AI 서버 통신 오류 상세: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"상태 코드: {e.response.status_code}")
                print(f"응답 내용: {e.response.text}")
            raise

ai_client = AIApiClient()