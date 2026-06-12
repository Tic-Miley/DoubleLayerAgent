import { Message } from '../types/chat';

interface UserMessageProps {
  message: Message;
}

export function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="flex justify-end px-4 sm:px-6 mb-4 animate-slide-up">
      <div className="max-w-[80%] sm:max-w-[70%]">
        <div className="bg-warm-yellow/15 border border-warm-yellow/20 rounded-2xl px-4 py-3">
          <p className="text-sm text-[var(--color-text-primary)] whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    </div>
  );
}
