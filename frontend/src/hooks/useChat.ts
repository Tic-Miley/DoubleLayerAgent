import { useState, useRef, useCallback, useEffect } from 'react';
import { Message, ToolCallEvent, ChartData, SourceState, generateId } from '../types/chat';

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const conversationIdRef = useRef<string>(generateId());
  const messagesRef = useRef<Message[]>([]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const sendMessage = useCallback(async (text: string, model?: string, thinkingMode?: string) => {
    if (!text.trim() || isStreaming) return;

    const userMsg: Message = {
      id: generateId(),
      role: 'user',
      content: text,
      toolCalls: [],
      charts: [],
      sources: [],
      timestamp: Date.now(),
      isStreaming: false,
    };

    const assistantMsg: Message = {
      id: generateId(),
      role: 'assistant',
      content: '',
      toolCalls: [],
      charts: [],
      sources: [],
      timestamp: Date.now(),
      isStreaming: true,
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const recentMessages = messagesRef.current.slice(-20);
    const history = recentMessages.map(m => ({ role: m.role, content: m.content }));

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationIdRef.current,
          history,
          model,
          thinking_mode: thinkingMode,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              handleSSEEvent(currentEvent, data, assistantMsg.id);
            } catch {
              // ignore parse errors
            }
            currentEvent = '';
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsg.id
              ? { ...m, isStreaming: false }
              : m
          )
        );
      } else {
        console.error('Chat error:', err);
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsg.id
              ? { ...m, isStreaming: false, content: m.content || '抱歉，请求失败，请稍后重试。' }
              : m
          )
        );
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }

    function handleSSEEvent(event: string, data: Record<string, unknown>, msgId: string) {
      setMessages(prev =>
        prev.map(m => {
          if (m.id !== msgId) return m;

          switch (event) {
            // ── L1 tool_call events ──
            case 'tool_call': {
              const toolCall: ToolCallEvent = {
                toolName: data.tool_name as string,
                status: data.status as ToolCallEvent['status'],
                message: data.message as string | undefined,
                arguments: data.arguments as Record<string, unknown> | undefined,
                resultPreview: data.result_preview as string | undefined,
                error: data.error as string | undefined,
              };
              const existingIdx = m.toolCalls.findIndex(
                tc => tc.toolName === toolCall.toolName && tc.status === 'running'
              );
              const newToolCalls = [...m.toolCalls];
              if (existingIdx >= 0 && toolCall.status !== 'running') {
                newToolCalls[existingIdx] = { ...newToolCalls[existingIdx], ...toolCall };
              } else if (existingIdx < 0) {
                newToolCalls.push(toolCall);
              }
              const sorted = [...newToolCalls].sort((a, b) => {
                if (a.status === 'running' && b.status !== 'running') return 1;
                if (a.status !== 'running' && b.status === 'running') return -1;
                return 0;
              });
              return { ...m, toolCalls: sorted };
            }

            // ── L1 text events ──
            case 'text': {
              const token = data.token as string;
              return { ...m, content: m.content + token };
            }

            // ── L1 chart events ──
            case 'chart': {
              const chart: ChartData = {
                chartId: data.chart_id as string,
                chartType: data.chart_type as ChartData['chartType'],
                option: data.option as Record<string, unknown>,
              };
              return { ...m, charts: [...m.charts, chart] };
            }

            // ── source_start: create or update SourceState to running ──
            case 'source_start': {
              const sourceId = data.source_id as string;
              const sourceName = data.source_name as string;
              const existing = m.sources.find(s => s.sourceId === sourceId);
              const newSources = existing
                ? m.sources.map(s =>
                    s.sourceId === sourceId
                      ? { ...s, status: 'running' as const, error: undefined }
                      : s
                  )
                : [
                    ...m.sources,
                    {
                      sourceId,
                      sourceName,
                      status: 'running' as const,
                      toolCalls: [],
                      charts: [],
                    },
                  ];
              return { ...m, sources: newSources };
            }

            // ── source_tool_call: append L2 tool state ──
            case 'source_tool_call': {
              const sid = data.source_id as string;
              const l2Tool: ToolCallEvent = {
                toolName: data.tool_name as string,
                status: data.status as ToolCallEvent['status'],
                arguments: data.arguments as Record<string, unknown> | undefined,
                resultPreview: data.result_preview as string | undefined,
                error: data.error as string | undefined,
              };
              return {
                ...m,
                sources: m.sources.map(s =>
                  s.sourceId === sid
                    ? { ...s, toolCalls: [...s.toolCalls, l2Tool] }
                    : s
                ),
              };
            }

            // ── source_chart: append L2 chart ──
            case 'source_chart': {
              const cid = data.source_id as string;
              const l2Chart: ChartData = {
                chartId: data.chart_id as string,
                chartType: data.chart_type as ChartData['chartType'],
                option: data.option as Record<string, unknown>,
              };
              return {
                ...m,
                sources: m.sources.map(s =>
                  s.sourceId === cid
                    ? { ...s, charts: [...s.charts, l2Chart] }
                    : s
                ),
              };
            }

            // ── source_done: mark source as done ──
            case 'source_done': {
              const did = data.source_id as string;
              return {
                ...m,
                sources: m.sources.map(s =>
                  s.sourceId === did
                    ? {
                        ...s,
                        status: 'done' as const,
                        summary: (data.summary as string) || s.summary,
                      }
                    : s
                ),
              };
            }

            // ── source_error: mark source as error ──
            case 'source_error': {
              const eid = data.source_id as string;
              const errMsg = (data.error as string) || '未知错误';
              return {
                ...m,
                sources: m.sources.map(s =>
                  s.sourceId === eid
                    ? { ...s, status: 'error' as const, error: errMsg }
                    : s
                ),
              };
            }

            // ── done: streaming complete ──
            case 'done':
              return { ...m, isStreaming: false };

            // ── error: L1 error ──
            case 'error':
              return {
                ...m,
                isStreaming: false,
                content: m.content || (data.message as string) || '发生错误',
              };

            default:
              // Unknown event types: warn and ignore
              console.warn('useChat: unknown SSE event type:', event);
              return m;
          }
        })
      );
    }
  }, [isStreaming]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, isStreaming, sendMessage, stopStreaming };
}
