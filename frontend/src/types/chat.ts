export interface ChatState {
  messages: Message[];
  isStreaming: boolean;
  error: string | null;
  conversationId: string | null;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls: ToolCallEvent[];
  charts: ChartData[];
  sources: SourceState[];
  timestamp: number;
  isStreaming: boolean;
}

export interface ToolCallEvent {
  toolName: string;
  status: 'running' | 'done' | 'error';
  arguments?: Record<string, unknown>;
  message?: string;
  resultPreview?: string;
  error?: string;
}

export interface ChartData {
  chartId: string;
  chartType: 'pie' | 'line' | 'bar';
  option: Record<string, unknown>;
}

export interface SourceState {
  sourceId: string;
  sourceName: string;
  status: 'pending' | 'running' | 'done' | 'error';
  toolCalls: ToolCallEvent[];
  charts: ChartData[];
  summary?: string;
  error?: string;
}

export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}
