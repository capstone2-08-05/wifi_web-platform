import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, Map, Radio, Settings, Sparkles, Wifi } from 'lucide-react';
import { ProfileMenu } from '@/features/header/ProfileMenu';
import { useAuthStore } from '@/stores/auth-store';

/* ------------------------------------------------------------------ */
/* 스크롤 진입 애니메이션 훅                                            */
/* ------------------------------------------------------------------ */
function useInView(options?: IntersectionObserverInit) {
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setInView(true);
        obs.disconnect();
      }
    }, { threshold: 0.1, rootMargin: '0px 0px -60px 0px', ...options });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return { ref, inView };
}

const SPRING = 'cubic-bezier(0.16, 1, 0.3, 1)';

function fadeUp(inView: boolean, delay = 0, dist = 44) {
  return inView
    ? {
        opacity: 1,
        transform: 'translateY(0)',
        transition: `opacity 0.9s ${delay}ms ${SPRING}, transform 0.9s ${delay}ms ${SPRING}`,
      }
    : { opacity: 0, transform: `translateY(${dist}px)` };
}

/* ------------------------------------------------------------------ */
/* 데이터                                                               */
/* ------------------------------------------------------------------ */
const NAV_ITEMS = [
  { step: '01', label: '공간 편집', active: false },
  { step: '02', label: '시뮬레이션', active: true },
  { step: '03', label: '실측/진단', active: false },
  { step: '04', label: '공유기 배치 추천', active: false },
];

const STEPS = [
  {
    num: '01',
    emoji: '🗺️',
    icon: Map,
    title: '공간 편집',
    desc: '매장 도면을 업로드하고 벽, 가구, 장애물을 설정합니다. 공간 구조를 정확히 반영할수록 시뮬레이션 결과가 정밀해집니다.',
  },
  {
    num: '02',
    emoji: '📡',
    icon: Radio,
    title: '시뮬레이션',
    desc: '도면 위에 공유기를 자유롭게 배치하고 예상 Wi-Fi 신호 범위를 열지도로 확인합니다. 위치를 바꿔가며 최적 배치를 찾아보세요.',
  },
  {
    num: '03',
    emoji: '📱',
    icon: Activity,
    title: '실측/진단',
    desc: '모바일 앱으로 매장을 걸어다니며 실제 Wi-Fi 신호를 측정하고, 시뮬레이션 모델을 현실에 맞게 보정합니다. 예측 정확도가 크게 올라가요.',
  },
  {
    num: '04',
    emoji: '✨',
    icon: Sparkles,
    title: '공유기 배치 추천',
    desc: '실측 데이터를 분석해 신호가 약한 구역을 찾고, 개선 효과가 가장 큰 공유기 설치 위치를 추천합니다.',
  },
];

/* ------------------------------------------------------------------ */
/* 텍스트 순환 컴포넌트                                                  */
/* ------------------------------------------------------------------ */
const CYCLE_ITEMS = [
  '도면 위에 공유기를 배치하고 신호 범위를 예측하세요',
  '모바일로 실측해 사각지대를 바로 확인하세요',
  'AI가 분석한 최적 공유기 위치를 추천받으세요',
  '실측 데이터로 시뮬레이션 정확도를 높이세요',
];

function TextCycler() {
  const [index, setIndex] = useState(0);
  const [animating, setAnimating] = useState(false);

  useEffect(() => {
    const id = setInterval(() => {
      setAnimating(true);
      setTimeout(() => {
        setIndex((i) => (i + 1) % CYCLE_ITEMS.length);
        setAnimating(false);
      }, 400);
    }, 2800);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="relative mt-6 h-14 overflow-hidden">
      <p
        className="absolute inset-0 flex items-center text-lg font-medium text-blue-600"
        style={{
          opacity: animating ? 0 : 1,
          transform: animating ? 'translateY(-20px)' : 'translateY(0)',
          transition: `opacity 0.4s ${SPRING}, transform 0.4s ${SPRING}`,
        }}
      >
        {CYCLE_ITEMS[index]}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 메인 컴포넌트                                                         */
/* ------------------------------------------------------------------ */
export default function LandingPage() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated());

  return (
    <div className="min-h-screen overflow-x-hidden bg-white text-slate-950">
      {/* 유리 닦기 오버레이 */}
      <div
        className="pointer-events-none fixed inset-0 z-100 bg-white/70 backdrop-blur-sm"
        style={{ animation: 'lp-glass-wipe 1s 0.1s cubic-bezier(0.76, 0, 0.24, 1) both' }}
      />

      {/* 헤더 */}
      <header
        className="fixed inset-x-0 top-0 z-50 border-b border-slate-100/80 bg-white/80 backdrop-blur-md"
        style={{ animation: `lp-fade-down 0.7s ${SPRING} both` }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-xl text-white"
              style={{ background: 'linear-gradient(135deg, #0A74FF, #37B6FF)' }}
            >
              <Wifi className="h-4 w-4" />
            </div>
            <span className="font-semibold tracking-tight">Wi-Fi Space</span>
          </div>
          <nav className="flex items-center gap-6 text-sm">
            {isAuthed ? (
              <ProfileMenu />
            ) : (
              <>
                <Link to="/auth/login" className="text-slate-500 transition hover:text-slate-900">
                  로그인
                </Link>
                <Link to="/auth/signup" className="text-slate-500 transition hover:text-slate-900">
                  회원가입
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      {/* ── 히어로 ─────────────────────────────────────── */}
      <section className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-16 px-6 pb-48 pt-40 md:grid-cols-2 md:pt-48">

        {/* 왼쪽: 카피 */}
        <div style={{ animation: `lp-fade-up 1s 0.2s ${SPRING} both` }}>
          <div
            className="mb-6 inline-flex items-center rounded-full border border-sky-100 px-4 py-1.5 text-sm text-sky-400"
            style={{
              backgroundImage: 'linear-gradient(110deg, #f0f9ff 40%, #e0f2fe 50%, #f0f9ff 60%)',
              backgroundSize: '200% auto',
              animation: 'lp-shimmer 2.5s linear infinite',
            }}
          >
            Wi-Fi 신호 범위 최적화 플랫폼
          </div>
          <h1 className="text-4xl font-bold leading-[1.2] tracking-tight sm:text-5xl">
            우리 매장 Wi-Fi<br />상태를 확인하고<br />
            <span className="text-blue-600">최적의 공유기 위치</span>를<br />
            추천해드려요
          </h1>
          <p className="mt-6 max-w-md text-base leading-7 text-slate-500">
            도면 위에 공유기를 배치하면 예상 신호 범위를 바로 확인할 수 있어요.
            실제 측정 데이터와 비교해 가장 안정적인 배치를 완성하세요.
          </p>
          <TextCycler />
          <div className="mt-10">
            <Link
              to={isAuthed ? '/dashboard' : '/auth/signup'}
              className="inline-block rounded-2xl bg-blue-600 px-8 py-4 text-base font-semibold text-white shadow-xl shadow-blue-600/20 transition hover:bg-blue-700 hover:shadow-blue-600/30 active:scale-[0.98]"
            >
              {isAuthed ? '대시보드 바로가기' : '분석 시작하기'}
            </Link>
          </div>
        </div>

        {/* 오른쪽: 앱 미리보기 */}
        <div
          className="relative"
          style={{ animation: `lp-slide-up 1.1s 0.35s ${SPRING} both` }}
        >
          {/* 배경 글로우 */}
          <div className="absolute -inset-8 rounded-4xl bg-blue-100/70 blur-3xl" />

          {/* 앱 창 */}
          <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl shadow-slate-200/80" style={{ animation: 'lp-float 5s ease-in-out infinite' }}>
            {/* 앱 상단 바 */}
            <div className="flex items-center justify-between border-b bg-slate-50 px-5 py-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-5 w-5 items-center justify-center rounded-lg text-white" style={{ background: 'linear-gradient(135deg, #0A74FF, #37B6FF)' }}>
                    <Wifi className="h-3 w-3" />
                  </div>
                <span className="text-xs font-semibold text-slate-700">Wi-Fi Space</span>
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                <span className="rounded-full border bg-white px-2.5 py-0.5 text-slate-500">1F · 카페 매장</span>
                <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 font-semibold text-emerald-600">분석 완료</span>
              </div>
            </div>

            <div className="flex h-80">
              {/* 미니 사이드바 */}
              <nav className="flex w-32 flex-col gap-0.5 border-r bg-slate-50/60 p-2.5">
                {NAV_ITEMS.map((item) => (
                  <div
                    key={item.label}
                    className={`flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[9px] font-medium transition ${
                      item.active ? 'bg-blue-100 text-blue-700' : 'text-slate-400'
                    }`}
                  >
                    <span className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full text-[7px] font-bold ${
                      item.active ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-500'
                    }`}>
                      {item.step}
                    </span>
                    {item.label}
                  </div>
                ))}
                <div className="mt-auto flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[9px] text-slate-300">
                  <Settings className="h-3 w-3" />
                  설정
                </div>
              </nav>

              {/* 메인 화면 */}
              <div className="flex flex-1 flex-col gap-2.5 p-3">
                {/* 도면 + 히트맵 */}
                <div className="relative flex-1 overflow-hidden rounded-2xl bg-slate-100">
                  <div className="absolute left-8 top-5 h-24 w-28 rounded-2xl bg-blue-400/45 blur-xl" />
                  <div className="absolute right-8 top-8 h-22 w-22 rounded-full bg-emerald-400/45 blur-xl" />
                  <div className="absolute bottom-8 left-1/2 h-18 w-22 -translate-x-1/2 rounded-full bg-orange-400/35 blur-lg" />
                  <div className="absolute inset-4 grid grid-cols-3 grid-rows-2 gap-1.5">
                    {Array.from({ length: 6 }).map((_, i) => (
                      <div key={i} className="rounded-xl border border-white/70 bg-white/35" />
                    ))}
                  </div>
                  <div className="absolute left-12 top-9 rounded-full bg-blue-600 px-2 py-0.5 text-[9px] font-bold text-white shadow-md">공유기1</div>
                  <div className="absolute right-12 top-6 rounded-full bg-blue-600 px-2 py-0.5 text-[9px] font-bold text-white shadow-md">공유기2</div>
                  <div className="absolute bottom-2.5 left-2.5 right-2.5 rounded-xl bg-white/90 px-3 py-2 backdrop-blur-sm">
                    <div className="flex items-center justify-between text-[9px]">
                      <span className="text-slate-500">신호 범위</span>
                      <span className="font-bold text-blue-600">78%</span>
                    </div>
                    <div className="mt-1 h-1 rounded-full bg-slate-200">
                      <div className="h-1 w-[78%] rounded-full bg-linear-to-r from-blue-500 to-emerald-400" />
                    </div>
                  </div>
                </div>

                {/* 지표 */}
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: '공유기 수', value: '2개' },
                    { label: '평균 RSSI', value: '-58 dBm' },
                    { label: '주파수', value: '5 GHz' },
                  ].map((m) => (
                    <div key={m.label} className="rounded-xl bg-slate-50 p-2.5 text-center">
                      <div className="text-[8px] text-slate-400">{m.label}</div>
                      <div className="mt-0.5 text-[11px] font-bold text-slate-800">{m.value}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 사용 흐름 ────────────────────────────────────── */}
      <StepsSection />

      {/* ── 하단 CTA ─────────────────────────────────────── */}
      <CtaSection />

      <footer className="border-t border-slate-800 bg-slate-900 px-6 py-8 text-center text-sm text-slate-500">
        Wi-Fi Space · 실내 Wi-Fi 신호 범위 최적화
      </footer>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 사용 흐름 섹션                                                        */
/* ------------------------------------------------------------------ */
function StepCard({ s, delay }: { s: typeof STEPS[number]; delay: number }) {
  const { ref, inView } = useInView();
  return (
    <div ref={ref} style={fadeUp(inView, delay)}>
      <div className="relative h-full rounded-3xl border border-slate-200 bg-white px-9 py-10 shadow-sm transition duration-300 hover:-translate-y-1 hover:ring-2 hover:ring-blue-200 hover:shadow-xl hover:shadow-blue-100/80">
        <div className="mb-10 flex items-start justify-between">
          <div className="relative z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white text-sm font-bold text-blue-600 shadow-sm ring-1 ring-slate-200">
            {s.num}
          </div>
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50 text-3xl">
            {s.emoji}
          </div>
        </div>
        <h3 className="text-xl font-extrabold tracking-tight text-slate-950">{s.title}</h3>
        <p className="mt-4 text-sm leading-7 text-slate-500">{s.desc}</p>
      </div>
    </div>
  );
}

function StepsSection() {
  const { ref, inView } = useInView();
  return (
    <section className="bg-slate-50 px-6 py-48">
      <div className="mx-auto max-w-6xl">
        <div ref={ref} style={fadeUp(inView, 0, 36)} className="mb-16 text-center">
          <h2 className="text-4xl font-bold tracking-tight">이렇게 사용해요</h2>
          <p className="mt-4 text-lg text-slate-500">
            도면 업로드부터 실제 신호 보정까지 한 흐름으로 관리하세요.
          </p>
        </div>
        <div className="relative">
          <div className="pointer-events-none absolute inset-x-0 top-10.5 hidden h-px bg-slate-200 lg:block" />
          <div className="grid gap-5 sm:grid-cols-2 md:grid-cols-4">
            {STEPS.map((s, i) => (
              <StepCard key={s.num} s={s} delay={i * 80} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* 하단 CTA 섹션                                                         */
/* ------------------------------------------------------------------ */
function CtaSection() {
  const { ref, inView } = useInView();
  const isAuthed = useAuthStore((s) => s.isAuthenticated());
  return (
    <section className="relative overflow-hidden bg-slate-900 px-6 pb-30 pt-40">
      {/* 배경 글로우 */}
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-150 w-150 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-700/20 blur-[120px]" />
      <div className="pointer-events-none absolute -left-32 bottom-0 h-80 w-80 rounded-full bg-blue-500/10 blur-3xl" />
      <div className="pointer-events-none absolute -right-32 top-0 h-80 w-80 rounded-full bg-indigo-500/10 blur-3xl" />

      {/* 신호 파동 링 */}
      {[0, 0.8, 1.6].map((delay) => (
        <div
          key={delay}
          className="pointer-events-none absolute left-1/2 top-1/2 h-96 w-96 rounded-full border border-blue-500/20"
          style={{ animation: `lp-ping 3.6s ${delay}s ease-out infinite` }}
        />
      ))}

      {/* 배경 점 패턴 */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage: 'radial-gradient(circle, #94a3b8 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      <div ref={ref} className="relative mx-auto w-full max-w-3xl text-center">
        <p
          style={fadeUp(inView, 0, 36)}
          className="mb-15 text-sm font-semibold uppercase tracking-[0.2em] text-blue-400"
        >
          Wi-Fi Space
        </p>
        <h2
          style={fadeUp(inView, 100, 52)}
          className="text-5xl font-bold leading-tight tracking-tight text-white sm:text-6xl"
        >
          매장 Wi-Fi, 한번<br />직접 분석해보세요
        </h2>
        <p
          style={fadeUp(inView, 220, 40)}
          className="mx-auto mt-10 max-w-md text-lg leading-8 text-slate-400"
        >
          시뮬레이션부터 실측 보정까지,<br />공유기 최적 위치 후보를 바로 확인해보세요.
        </p>
        <div style={fadeUp(inView, 360, 32)} className="mt-20">
          <Link
            to={isAuthed ? '/dashboard' : '/auth/signup'}
            className="inline-block rounded-2xl bg-blue-600 px-15 py-4 text-base font-semibold text-white transition hover:bg-blue-500 active:scale-[0.98]"
            style={{ animation: 'lp-btn-pulse 2.5s ease-in-out infinite' }}
          >
            {isAuthed ? '대시보드 바로가기' : '분석 시작하기'}
          </Link>
        </div>
      </div>
    </section>
  );
}
