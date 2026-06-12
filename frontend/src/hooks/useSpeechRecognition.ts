import { useState, useRef, useCallback, useEffect } from 'react';

// 最小化类型声明
declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognition;
    webkitSpeechRecognition: new () => SpeechRecognition;
  }
}

interface SpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: {
      isFinal: boolean;
      [index: number]: { transcript: string; confidence: number };
    };
  };
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
}

interface UseSpeechRecognitionOptions {
  onFinalResult: (text: string) => void;
  lang?: string;
}

interface UseSpeechRecognitionReturn {
  isSupported: boolean;
  isListening: boolean;
  interimText: string;
  error: string | null;
  startListening: () => void;
  stopListening: () => void;
  clearError: () => void;
}

export function useSpeechRecognition({
  onFinalResult,
  lang = 'zh-CN',
}: UseSpeechRecognitionOptions): UseSpeechRecognitionReturn {
  const [isListening, setIsListening] = useState(false);
  const [interimText, setInterimText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const finalTranscriptRef = useRef('');
  const errorFlagRef = useRef(false);
  const onFinalResultRef = useRef(onFinalResult);
  onFinalResultRef.current = onFinalResult;

  // 检测支持性
  const isSupported =
    typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

  // 惰性创建 recognition 实例并绑定事件
  const ensureRecognition = useCallback((): SpeechRecognition | null => {
    if (recognitionRef.current) return recognitionRef.current;
    if (!isSupported) return null;

    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new Ctor();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = lang;

    rec.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalTranscriptRef.current += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }
      setInterimText(interim);
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'aborted') return;
      errorFlagRef.current = true;
      const messages: Record<string, string> = {
        'not-allowed': '麦克风权限未授权，请在浏览器设置中允许访问麦克风',
        'no-speech': '未检测到语音，请再试一次',
        'audio-capture': '无法访问麦克风设备',
        'network': '语音识别网络连接失败',
      };
      setError(messages[event.error] || `语音识别错误: ${event.error}`);
    };

    rec.onend = () => {
      const finalText = finalTranscriptRef.current.trim();
      if (finalText) {
        onFinalResultRef.current(finalText);
      } else if (!errorFlagRef.current) {
        setError('未检测到语音，请再试一次');
      }
      // 重置
      finalTranscriptRef.current = '';
      errorFlagRef.current = false;
      setIsListening(false);
      setInterimText('');
    };

    recognitionRef.current = rec;
    return rec;
  }, [isSupported, lang]);

  const startListening = useCallback(() => {
    const rec = ensureRecognition();
    if (!rec) {
      setError('您的浏览器不支持语音识别，请使用 Chrome 或 Edge');
      return;
    }

    setError(null);
    finalTranscriptRef.current = '';
    errorFlagRef.current = false;
    setInterimText('');

    try {
      rec.start();
      setIsListening(true);
    } catch {
      // 如果实例正在运行，先停后启
      try { rec.stop(); } catch { /* ignore */ }
      setTimeout(() => {
        try {
          rec.start();
          setIsListening(true);
          setError(null);
        } catch {
          setError('启动语音识别失败，请刷新页面后重试');
        }
      }, 100);
    }
  }, [ensureRecognition]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const clearError = useCallback(() => setError(null), []);

  // 卸载时释放资源
  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
    };
  }, []);

  return {
    isSupported,
    isListening,
    interimText,
    error,
    startListening,
    stopListening,
    clearError,
  };
}
