import { Message } from '../types/chat';
import { UserMessage } from './UserMessage';
import { AssistantMessage } from './AssistantMessage';
import { EmptyState } from './EmptyState';

interface MessageListProps {
  messages: Message[];
  onCopy: (text: string) => void;
}

export function MessageList({ messages, onCopy }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="max-w-[54rem] mx-auto py-4">
      {messages.map(msg =>
        msg.role === 'user' ? (
          <UserMessage key={msg.id} message={msg} />
        ) : (
          <AssistantMessage key={msg.id} message={msg} onCopy={onCopy} />
        )
      )}
    </div>
  );
}
