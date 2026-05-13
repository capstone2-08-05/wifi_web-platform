// GeoJSON 파싱 + 도형 평행이동 헬퍼.
// 좌표 단위: 미터 (백엔드 PostGIS 저장 기준).

export type Coord = [number, number];

export type GeoJsonGeometry =
  | { type: 'LineString'; coordinates: Coord[] }
  | { type: 'Polygon'; coordinates: Coord[][] }
  | { type: 'Point'; coordinates: Coord };

export function parseGeometry(
  geom: Record<string, unknown> | null | undefined,
): GeoJsonGeometry | null {
  if (!geom || typeof geom !== 'object') return null;
  const type = (geom as { type?: unknown }).type;
  const coordinates = (geom as { coordinates?: unknown }).coordinates;
  if (typeof type !== 'string' || !coordinates) return null;

  if (type === 'LineString' && Array.isArray(coordinates)) {
    const coords = (coordinates as unknown[]).filter(isCoord);
    if (coords.length < 2) return null;
    return { type: 'LineString', coordinates: coords };
  }
  if (type === 'Polygon' && Array.isArray(coordinates)) {
    const rings = (coordinates as unknown[])
      .map((ring) => (Array.isArray(ring) ? ring.filter(isCoord) : []))
      .filter((r) => r.length >= 3);
    if (rings.length === 0) return null;
    return { type: 'Polygon', coordinates: rings };
  }
  if (
    type === 'Point' &&
    Array.isArray(coordinates) &&
    coordinates.length >= 2 &&
    typeof coordinates[0] === 'number' &&
    typeof coordinates[1] === 'number'
  ) {
    return { type: 'Point', coordinates: [coordinates[0], coordinates[1]] };
  }
  return null;
}

function isCoord(p: unknown): p is Coord {
  return (
    Array.isArray(p) &&
    p.length >= 2 &&
    typeof p[0] === 'number' &&
    typeof p[1] === 'number'
  );
}

/** 도형을 (dx, dy) 만큼 평행이동. 동일 type 의 새 GeoJSON 반환. */
export function translateGeometry(
  g: GeoJsonGeometry,
  dx: number,
  dy: number,
): GeoJsonGeometry {
  if (g.type === 'LineString') {
    return {
      type: 'LineString',
      coordinates: g.coordinates.map(([x, y]) => [x + dx, y + dy] as Coord),
    };
  }
  if (g.type === 'Polygon') {
    return {
      type: 'Polygon',
      coordinates: g.coordinates.map((ring) =>
        ring.map(([x, y]) => [x + dx, y + dy] as Coord),
      ),
    };
  }
  return {
    type: 'Point',
    coordinates: [g.coordinates[0] + dx, g.coordinates[1] + dy],
  };
}

/** LineString 의 index 번째 꼭짓점을 (dx, dy) 만큼 이동. */
export function moveLineStringVertex(
  coords: Coord[],
  index: number,
  dx: number,
  dy: number,
): Coord[] {
  return coords.map((c, i) =>
    i === index ? ([c[0] + dx, c[1] + dy] as Coord) : c,
  );
}

/** Polygon 첫 ring 의 index 번째 꼭짓점을 (dx, dy) 만큼 이동. ring 닫힘 유지. */
export function movePolygonVertex(
  rings: Coord[][],
  index: number,
  dx: number,
  dy: number,
): Coord[][] {
  if (rings.length === 0) return rings;
  const ring = rings[0];
  const isClosed =
    ring.length > 0 &&
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1];
  const updated = ring.map((c, i) =>
    i === index ? ([c[0] + dx, c[1] + dy] as Coord) : c,
  );
  // 닫힌 ring 의 첫 꼭짓점을 옮긴 경우 마지막 꼭짓점도 같이 이동시켜 닫힘 유지
  if (isClosed && index === 0) {
    updated[updated.length - 1] = updated[0];
  }
  return [updated, ...rings.slice(1)];
}

/** 도형 회전 중심점. LineString=중점, Polygon=꼭짓점 평균, Point=자기 자신. */
export function geometryCenter(g: GeoJsonGeometry): Coord {
  if (g.type === 'Point') return [g.coordinates[0], g.coordinates[1]];
  if (g.type === 'LineString') {
    const a = g.coordinates[0];
    const b = g.coordinates[g.coordinates.length - 1];
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  }
  const ring = g.coordinates[0] ?? [];
  if (ring.length === 0) return [0, 0];
  const isClosed =
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1];
  const pts = isClosed ? ring.slice(0, -1) : ring;
  const n = pts.length || 1;
  const sx = pts.reduce((s, p) => s + p[0], 0);
  const sy = pts.reduce((s, p) => s + p[1], 0);
  return [sx / n, sy / n];
}

/** (cx, cy) 주위로 90° 시계방향 회전: (x, y) → (cx + (y - cy), cy - (x - cx)). */
export function rotateGeometry90Cw(
  g: GeoJsonGeometry,
  center?: Coord,
): GeoJsonGeometry {
  const [cx, cy] = center ?? geometryCenter(g);
  const rot = ([x, y]: Coord): Coord => [cx + (y - cy), cy - (x - cx)];
  if (g.type === 'LineString') {
    return { type: 'LineString', coordinates: g.coordinates.map(rot) };
  }
  if (g.type === 'Polygon') {
    return {
      type: 'Polygon',
      coordinates: g.coordinates.map((ring) => ring.map(rot)),
    };
  }
  // Point 는 자기 중심 회전 = 변화 없음
  return g;
}
