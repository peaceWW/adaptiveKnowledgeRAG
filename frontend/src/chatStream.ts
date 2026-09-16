import { useSession } from './stores/session';
export async function streamChat(payload: object, signal: AbortSignal, receive: (event: string, data: any) => void) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-User': useSession().username },
    body: JSON.stringify(payload), signal,
  });
  if (!response.ok) throw new Error(`请求失败（${response.status}），请检查登录状态或稍后重试。`);
  if (!response.body) throw new Error('浏览器不支持流式读取');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', completed = false;
  function dispatch(frame: string) {
    let event = 'message'; const lines: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
    }
    if (!lines.length) return;
    const data = JSON.parse(lines.join('\n'));
    if (event === 'error') throw new Error(data.message || '回答生成失败');
    receive(event, data);
    if (event === 'done') completed = true;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
    if (!completed) throw new Error('连接中断，回答尚未完成，请重新发送。');
  } finally { await reader.cancel(); reader.releaseLock(); }
}
