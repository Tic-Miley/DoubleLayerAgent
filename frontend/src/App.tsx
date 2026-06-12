import { ThemeProvider } from './hooks/useTheme';
import { ChatLayout } from './components/ChatLayout';

export default function App() {
  return (
    <ThemeProvider>
      <ChatLayout />
    </ThemeProvider>
  );
}
