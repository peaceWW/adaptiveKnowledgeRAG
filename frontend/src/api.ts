import axios from "axios";
import { useSession } from "./stores/session";

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const session = useSession();
  config.headers["X-User"] = session.username;
  return config;
});
