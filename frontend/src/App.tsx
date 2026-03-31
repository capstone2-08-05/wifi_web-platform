import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import axios from 'axios'
import { useMemo, useState } from 'react'
import './App.css'

type Wall = {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  thickness: number
  height: number
}

type SceneJson = {
  walls: Wall[]
}

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

function WallMesh({ wall }: { wall: Wall }) {
  const length = Math.hypot(wall.x2 - wall.x1, wall.y2 - wall.y1)
  const angle = Math.atan2(wall.y2 - wall.y1, wall.x2 - wall.x1)
  const centerX = (wall.x1 + wall.x2) / 2
  const centerZ = (wall.y1 + wall.y2) / 2

  return (
    <mesh position={[centerX, wall.height / 2, centerZ]} rotation={[0, -angle, 0]}>
      <boxGeometry args={[length, wall.height, wall.thickness]} />
      <meshStandardMaterial color="#86a8ff" />
    </mesh>
  )
}

function App() {
  const [scene, setScene] = useState<SceneJson | null>(null)
  const [selected, setSelected] = useState<File | null>(null)
  const [message, setMessage] = useState<string>('대기 중')

  const wallCount = useMemo(() => scene?.walls.length ?? 0, [scene])

  const loadSample = async () => {
    const res = await fetch('/examples/simple_room.json')
    const json = (await res.json()) as SceneJson
    setScene(json)
    setMessage('샘플 scene 로드 완료')
  }

  const uploadFloorplan = async () => {
    if (!selected) {
      setMessage('먼저 파일을 선택해 주세요.')
      return
    }

    const form = new FormData()
    form.append('file', selected)

    try {
      const res = await axios.post(`${BACKEND_URL}/upload/floorplan`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setMessage(`업로드 성공: ${res.data.fileId}`)
    } catch (err) {
      setMessage(`업로드 실패: ${String(err)}`)
    }
  }

  return (
    <div className="app">
      <aside className="panel">
        <h1>Floorplan Lab</h1>
        <p>사진/도면 업로드 + 3D 렌더 + 실험 API 체크</p>

        <button onClick={loadSample}>샘플 JSON 로드</button>

        <input
          type="file"
          accept=".png,.jpg,.jpeg,.pdf"
          onChange={(e) => setSelected(e.target.files?.[0] ?? null)}
        />
        <button onClick={uploadFloorplan}>도면 업로드</button>

        <div className="status">
          <div>벽 개수: {wallCount}</div>
          <div>{message}</div>
        </div>
      </aside>

      <main className="viewer">
        <Canvas camera={{ position: [6, 5, 6], fov: 50 }}>
          <color attach="background" args={['#11131a']} />
          <ambientLight intensity={0.7} />
          <directionalLight position={[5, 8, 6]} intensity={0.8} />
          <gridHelper args={[20, 20, '#333', '#333']} />
          <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
            <planeGeometry args={[20, 20]} />
            <meshStandardMaterial color="#1b1f2b" />
          </mesh>
          {scene?.walls.map((wall) => (
            <WallMesh key={wall.id} wall={wall} />
          ))}
          <OrbitControls makeDefault />
        </Canvas>
      </main>
    </div>
  )
}

export default App
