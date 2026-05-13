import { QueryProvider } from '@/providers/QueryProvider';
import { AppRouter } from '@/routes/AppRouter';
import { Toaster } from '@/components/Toaster';

export default function App() {
  return (
    <QueryProvider>
      <AppRouter />
      <Toaster />
    </QueryProvider>
  );
}
