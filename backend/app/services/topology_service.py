import logging
from typing import List, Any
from shapely.geometry import Polygon, Point
# 변경된 경로: floorplan -> scene
from app.schemas.scene import Room, Topology

logger = logging.getLogger(__name__)

class TopologyService:
    def analyze(self, rooms: List[Room], detections: List[Any]) -> Topology:
        """
        방들 사이의 인접성(Adjacency)과 
        문을 통한 연결성(Connectivity)을 분석합니다.
        """
        adjacencies = []
        connectivity = []
        
        # 1. 방들을 Shapely 다각형으로 변환
        room_polys = [(r.id, Polygon(r.points)) for r in rooms]

        # 2. 인접성 분석 (벽이 맞닿아 있는지 확인)
        for i in range(len(room_polys)):
            for j in range(i + 1, len(room_polys)):
                id_i, poly_i = room_polys[i]
                id_j, poly_j = room_polys[j]
                
                # 두 다각형이 맞닿아 있다면 인접한 것으로 간주
                if poly_i.touches(poly_j) or poly_i.intersects(poly_j):
                    adjacencies.append([id_i, id_j])

        # 3. 연결성 분석 (문을 통해 이동 가능한지 확인)
        # DetectionDTO 구조에 맞춰 'door' 클래스만 필터링
        doors = [d for d in detections if getattr(d, 'class_name', getattr(d, 'class', None)) == "door"]
        
        for door in doors:
            bx1, by1, bx2, by2 = door.bbox_xyxy
            door_center = Point((bx1 + bx2) / 2, (by1 + by2) / 2)
            
            connected_rooms = []
            for r_id, r_poly in room_polys:
                # 문 중심점이 방 다각형 근처(약 20px 오차)에 있는지 확인
                if r_poly.buffer(20.0).intersects(door_center):
                    connected_rooms.append(r_id)
            
            # 두 개 이상의 방에 걸쳐 있는 문이라면 연결된 것으로 간주
            if len(connected_rooms) >= 2:
                # 중복 제거 후 상위 2개 방만 연결
                unique_rooms = list(set(connected_rooms))
                if len(unique_rooms) >= 2:
                    connectivity.append(unique_rooms[:2])

        logger.info(f"토폴로지 분석 완료: 인접 {len(adjacencies)}건, 연결 {len(connectivity)}건")
        return Topology(adjacencies=adjacencies, connectivity=connectivity)