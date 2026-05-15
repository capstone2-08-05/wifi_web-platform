import { useState } from 'react';
import { Camera, MapPin, Smartphone } from 'lucide-react';
import { MobileConnectModal } from '@/features/mobile/MobileConnectModal';

const FLOW_STEPS = [
  '권한 동의 (시작하기 전)',
  'QR 스캔을 통한 손쉬운 연결',
  '직관적인 모드 선택',
  'AR 기반 가구 스캔 UI',
  '간단한 원클릭 와이파이 실측 수집',
];

export default function MobileAppPage() {
  const [connectOpen, setConnectOpen] = useState(false);
  return (
    <div className="h-full overflow-auto bg-muted/20 p-10">
      <div className="mx-auto flex max-w-6xl items-start justify-center gap-12">
        <PhoneMockup />
        <InfoCard onConnectClick={() => setConnectOpen(true)} />
      </div>
      <MobileConnectModal open={connectOpen} onClose={() => setConnectOpen(false)} />
    </div>
  );
}

function PhoneMockup() {
  return (
    <div className="relative w-[320px] shrink-0 rounded-[44px] border-[6px] border-foreground bg-background shadow-2xl">
      {/* 노치 */}
      <div className="absolute left-1/2 top-2 z-10 h-5 w-28 -translate-x-1/2 rounded-full bg-foreground" />

      <div className="overflow-hidden rounded-[36px]">
        {/* 상태바 */}
        <div className="flex items-center justify-between px-6 pt-3 pb-1 text-[11px] font-semibold">
          <span>12:30</span>
          <StatusIcons />
        </div>

        {/* 본문 */}
        <div className="flex h-[610px] flex-col px-6 pb-6 pt-8">
          <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
            <Smartphone className="h-6 w-6 text-primary" strokeWidth={1.8} />
          </div>

          <h2 className="text-[22px] font-bold leading-snug">
            시작하기 전에
            <br />
            권한이 필요해요
          </h2>

          <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
            현장에서 원활하게 데이터를 수집하고 대시보드와 연결하기 위해 아래
            권한을 허용해 주세요.
          </p>

          <ul className="mt-7 space-y-5">
            <PermissionRow
              icon={<Camera className="h-4 w-4" strokeWidth={1.8} />}
              title="카메라"
              description="웹 대시보드의 QR 코드를 스캔하고, 공간의 가구를 자동으로 인식합니다."
            />
            <PermissionRow
              icon={<MapPin className="h-4 w-4" strokeWidth={1.8} />}
              title="위치 및 주변 기기"
              description="실제 걸어다니며 와이파이 신호 강도와 품질을 정확하게 측정합니다."
            />
          </ul>

          <div className="flex-1" />

          <button
            type="button"
            className="w-full rounded-xl bg-primary py-3.5 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
          >
            동의하고 시작하기
          </button>

          {/* iOS 하단 핸들 */}
          <div className="mx-auto mt-3 h-1 w-28 rounded-full bg-foreground/80" />
        </div>
      </div>
    </div>
  );
}

function PermissionRow({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <li className="flex items-start gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        {icon}
      </div>
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-[13px] font-semibold">{title}</p>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
    </li>
  );
}

function InfoCard({ onConnectClick }: { onConnectClick: () => void }) {
  return (
    <div className="flex w-[360px] shrink-0 flex-col gap-3">
      <section className="rounded-2xl border bg-background p-6 shadow-sm">
        <header className="flex items-center gap-2">
          <Smartphone className="h-5 w-5 text-foreground" strokeWidth={1.8} />
          <h3 className="text-base font-bold">모바일 앱 프로토타입</h3>
        </header>

        <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
          비전문가인 소상공인이 현장에서 간편하게 와이파이 품질을 측정하고
          가구를 스캔할 수 있도록 돕는 Android 컴패니언 앱 디자인입니다.
        </p>

        <h4 className="mt-6 text-sm font-semibold">주요 화면 플로우</h4>
        <ul className="mt-3 space-y-2 text-[13px] text-foreground/80">
          {FLOW_STEPS.map((step) => (
            <li key={step} className="flex items-start gap-2">
              <span className="mt-1.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-foreground/60" />
              <span>{step}</span>
            </li>
          ))}
        </ul>
      </section>

      <button
        type="button"
        onClick={onConnectClick}
        className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
      >
        <Smartphone className="h-4 w-4" />
        모바일 앱 연결
      </button>
    </div>
  );
}

function StatusIcons() {
  return (
    <div className="flex items-center gap-1">
      <svg width="14" height="10" viewBox="0 0 14 10" fill="currentColor">
        <path d="M7 0a7 7 0 0 1 5 2.1l-1 1A5.6 5.6 0 0 0 7 1.4 5.6 5.6 0 0 0 3 3.1l-1-1A7 7 0 0 1 7 0Zm0 2.8a4.2 4.2 0 0 1 3 1.3l-1 1A2.8 2.8 0 0 0 7 4.2 2.8 2.8 0 0 0 5 5.1l-1-1A4.2 4.2 0 0 1 7 2.8Zm0 2.8a1.4 1.4 0 0 1 1 .4L7 7l-1-1a1.4 1.4 0 0 1 1-.4Z" />
      </svg>
      <svg width="14" height="10" viewBox="0 0 18 12" fill="currentColor">
        <rect x="0" y="6" width="3" height="6" rx="1" />
        <rect x="5" y="3" width="3" height="9" rx="1" />
        <rect x="10" y="0" width="3" height="12" rx="1" />
        <rect x="15" y="6" width="3" height="6" rx="1" opacity="0.4" />
      </svg>
      <svg width="22" height="11" viewBox="0 0 24 12" fill="none">
        <rect x="0.5" y="0.5" width="20" height="11" rx="3" stroke="currentColor" />
        <rect x="2" y="2" width="17" height="8" rx="1.5" fill="currentColor" />
        <rect x="21" y="3.5" width="1.5" height="5" rx="0.75" fill="currentColor" />
      </svg>
    </div>
  );
}
