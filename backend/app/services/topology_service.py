from typing import List, Tuple
from shapely.geometry import Polygon, Point
from app.schemas.floorplan import Room, Topology

class TopologyService:
    def analyze(self, rooms: List[Room], detections: List[any]) -> Topology:
        adjacencies = []
        connectivity = []
        
        room_polys = [(r.id, Polygon(r.points)) for r in rooms]

        for i in range(len(room_polys)):
            for j in range(i + 1, len(room_polys)):
                id_i, poly_i = room_polys[i]
                id_j, poly_j = room_polys[j]
                
                if poly_i.touches(poly_j):
                    adjacencies.append([id_i, id_j])

        doors = [d for d in detections if d.class_name == "door"]
        for door in doors:
            bx1, by1, bx2, by2 = door.bbox_xyxy
            door_center = Point((bx1 + bx2) / 2, (by1 + by2) / 2)
            
            connected_rooms = []
            for r_id, r_poly in room_polys:
                if r_poly.buffer(0.2).intersects(door_center):
                    connected_rooms.append(r_id)
            
            if len(connected_rooms) >= 2:
                connectivity.append(connected_rooms[:2])

        return Topology(adjacencies=adjacencies, connectivity=connectivity)