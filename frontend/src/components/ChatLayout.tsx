import { useEffect, useRef } from 'react';
import { useChat } from '../hooks/useChat';
import { Header } from './Header';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { QuickQuestions } from './QuickQuestions';

export function ChatLayout() {
  const { messages, isStreaming, sendMessage, stopStreaming } = useChat();

  const scrollRef = useRef<HTMLDivElement>(null);
  const userWantsAutoScrollRef = useRef(true);
  const isAutoScrollingRef = useRef(false);

  // Wheel event: detect user scrolling up
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      if (e.deltaY < -3) {
        userWantsAutoScrollRef.current = false;
        if (isAutoScrollingRef.current) {
          container.scrollTo({ top: container.scrollTop, behavior: 'auto' });
          isAutoScrollingRef.current = false;
        }
      }
    };

    container.addEventListener('wheel', handleWheel, { passive: true });
    return () => container.removeEventListener('wheel', handleWheel);
  }, []);

  // Scroll event: detect when user reaches bottom
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const isAtBottom = scrollTop + clientHeight >= scrollHeight - 10;

      if (isAutoScrollingRef.current) {
        if (isAtBottom) {
          isAutoScrollingRef.current = false;
        }
        return;
      }

      if (isAtBottom) {
        userWantsAutoScrollRef.current = true;
      }
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    if (userWantsAutoScrollRef.current && messages.length > 0) {
      isAutoScrollingRef.current = true;
      const container = scrollRef.current;
      if (container) {
        container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
      }

      const fallbackTimer = setTimeout(() => {
        isAutoScrollingRef.current = false;
      }, 600);

      return () => clearTimeout(fallbackTimer);
    }
  }, [messages]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
  };

  return (
    <div ref={scrollRef} className="flex flex-col h-screen overflow-y-auto bg-[var(--color-bg)]">
      <Header />
      <div className="flex-1 flex flex-col">
        <div className="flex-1">
          <MessageList messages={messages} onCopy={handleCopy} />
        </div>
        {messages.length === 0 && (
          <QuickQuestions onSelect={sendMessage} disabled={isStreaming} />
        )}
      </div>
      <ChatInput
        onSend={sendMessage}
        onStop={stopStreaming}
        isStreaming={isStreaming}
      />
    </div>
  );
}
