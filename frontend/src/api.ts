import axios from "axios";
import { message } from "ant-design-vue";
import { useSession } from "./stores/session";

export const api = axios.create({ baseURL: "/api" });
let lastErrorAt = 0;
api.interceptors.response.use(response => response, error => {
  if (axios.isCancel(error)) return Promise.reject(error);
  if (Date.now() - lastErrorAt > 3000) {
    const detail = error.response?.data?.detail;
    message.error(typeof detail === 'string' ? detail : '请求失败，请检查服务连接后重试');
    lastErrorAt = Date.now();
  }
  return Promise.reject(error);
});

api.interceptors.request.use((config) => {
  const session = useSession();
  config.headers["X-User"] = session.username;
  return config;
});
