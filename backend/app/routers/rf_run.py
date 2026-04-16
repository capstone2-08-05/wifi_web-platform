import json
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from app.schemas.scene import SceneSchema

router = APIRouter(prefix="/rf", tags=["rf"])

AI_SERVER_URL = "http://localhost:9000/internal/sionna/run"



@router.post("/run")
async def run_rf_simulation(body: SceneSchema):
    async with httpx.AsyncClient() as client:
        all_data = body.model_dump()
        config = all_data.pop('config')
        antenna = all_data.pop('antenna')
        
        payload = {
            "engine": "sionna_rt",
            "run_type": "run",
            "floor_id": None,
            "input": {
                "kind": "sionna_dto",  
                "data": {            
                    "config": config,
                    "antenna": antenna,
                    "scene": all_data 
                }
            }
        }
        
        target_url = "http://localhost:9000/internal/sionna/run"

        try:
            response = await client.post(
                target_url,
                json=payload,
                timeout=120.0
            )
            
            if response.status_code == 422:
                print("❌ AI 서버 검증 실패 상세:", response.json())
                
            return response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI 서버 통신 에러: {str(e)}")